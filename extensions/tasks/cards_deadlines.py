"""Enforce the trade deadlines that nothing else can.

Every rule here is a stored timestamp being compared to now, never a timer
held in memory. That is deliberate: a restart resumes exactly where it left
off, and a bot that was down for two days processes everything overdue on its
first pass rather than losing it.

Eight jobs, in the order a trade meets them:

1. A proposal nobody answers within 12 hours closes itself, and the holder's
   consecutive ignored-request count goes up. Its standing post on the trade
   board collapses to the closed form; nobody is DMed about it.
2. Two ignored in a row asks the holder whether they are still trading.
3. No answer to that within 24 hours hides their cards. Silence is a no.
4. A confirmed side still owed its incoming credit is settled silently:
   the one-time migration for trades that were mid-flight when per-side
   settlement shipped, and the standing safety net for any future
   half-settled side. Runs every pass; fenced and idempotent.
5. Once one player confirms they sent their card, the other has 7 days
   before their whole side is settled for them: their card is deducted if a
   spare remains, their incoming card is credited, their locks are released.
6. A swap NEITHER player ever confirms is closed after 7 days, because nothing
   else would ever release those two cards.
7. An open request (want-ad) nobody claims within 48 hours expires. Its post
   collapses to the closed form; no DM, no ping, no new message.
8. A claim that crashed mid-flight - stuck in "claiming" past its two-minute
   claim window - is returned to the board, fenced so a fresh claim survives.

Standing-post edits across one pass are capped by SWEEP_CHANNEL_EDIT_BUDGET.
A state transition is never deferred for a cosmetic edit: an over-budget doc
still changes state and carries a channel_edit_pending marker that the next
pass drains first, under the same cap.
"""

import asyncio
from datetime import datetime, timezone

import hikari
import lightbulb

from extensions.commands import cards as cards_command
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# Deadlines are hours and days apart, so a minute of granularity is plenty and
# a slow pass never overlaps the next one.
SWEEP_INTERVAL_SECONDS = 5 * 60
# A bot that was down for a week could have thousands due at once; a bounded
# batch keeps one pass short and the rest are picked up next time.
BATCH = 200
# The most standing-post edits one pass may make. A backlog of hundreds of
# expiries must not turn into hundreds of REST edits in one burst - the state
# transitions all land immediately, and over-budget posts are corrected on
# following passes via the channel_edit_pending marker.
SWEEP_CHANNEL_EDIT_BUDGET = 25

sweep_task = None
bot_instance = None
mongo_client = None

# Shared with the owner preview command, so the wording it sends is the
# wording members receive - never a second copy that can drift.
#
# PROPOSAL_EXPIRED_* is no longer sent by anything: proposal expiry now
# routes through the delivery policy ("expired" = silent standing-post edit,
# no DM). The constants stay because tests pin the 12-hour wording against
# SWAP_ACCEPT_FOR; delete them together with that pin if the retired DM is
# ever fully excised.
PROPOSAL_EXPIRED_TITLE = "Card proposal expired"
PROPOSAL_EXPIRED_DETAIL = (
    "Nobody answered within 12 hours, so it closed. Nothing changed."
)
AUTO_DEDUCT_TITLE = "Your card was deducted automatically"
AUTO_DEDUCT_DETAIL_MOVED = (
    "The other player confirmed over 7 days ago. You did not answer.\n"
    "One copy of your card was removed. The card you agreed to receive "
    "was added.\n"
    "If this is wrong: set your real counts in **Update collection**."
)
AUTO_DEDUCT_DETAIL_NO_SPARE = (
    "The other player confirmed over 7 days ago.\n"
    "Your collection showed no spare, so your card was not removed. The "
    "card you agreed to receive was added.\n"
    "If this is wrong: set your real counts in **Update collection**."
)
# RETIRED from live sends: under per-side settlement the waiting player's
# incoming card is credited by their OWN confirmation, so the silent side
# running out of spares no longer changes anything for them and there is
# nothing to break the news about. The constants stay only because the owner
# preview command still imports them; delete them together.
SWAP_CLOSED_OWED_TITLE = "Card swap closed"
SWAP_CLOSED_OWED_DETAIL = (
    "The other player never confirmed.\n"
    "Their collection had no spare left, so the card was not added.\n"
    "If you did receive it in game: set your count in "
    "**Update collection**."
)


class _EditBudget:
    """The per-pass cap on standing-post edits, shared by every job.

    One instance travels through a whole sweep pass, so the cap bounds the
    pass, not each job. A compare-and-swap state change is never deferred
    for a cosmetic edit: when the cap is spent the doc still transitions and
    is marked channel_edit_pending, which `_drain_pending_channel_edits`
    clears on a following pass under the same cap.
    """

    def __init__(self, limit: int) -> None:
        self.remaining = int(limit)

    def take(self) -> bool:
        """Reserve one edit; False once the pass has spent its cap."""
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


async def _mark_channel_edit_pending(mongo, doc_id) -> None:
    """Defer a standing-post edit to the next pass's drain job."""
    try:
        await mongo.card_trades.update_one(
            {"_id": doc_id},
            {"$set": {"channel_edit_pending": True}},
        )
    except Exception as exc:
        print(f"[Cards Deadlines] edit deferral failed doc={doc_id}: "
              f"{type(exc).__name__}: {exc}")


async def _expire_unanswered_proposals(mongo, bot, *, now, edit_budget) -> int:
    """Job 1 and 2: close ignored proposals, then ask if they are still here."""
    try:
        due = await mongo.card_trades.find({
            "kind": "trade",
            "status": "pending",
            "accept_deadline_at": {"$lte": now},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] proposal query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    closed = 0
    for trade in due:
        result = await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "pending"},
            {
                "$set": {
                    "status": "expired",
                    "expired_at": now,
                    "updated_at": now,
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        if not getattr(result, "modified_count", 0):
            continue          # somebody answered between the read and the write
        closed += 1
        await cards_command._release_proposal_slots(mongo, trade)

        # Nothing was ever reserved by a pending proposal, so there is no
        # inventory to put back - only the count of requests this holder has
        # let run out, which is what the check-in keys on.
        holder_tag = cards_command._normalize_tag(trade.get("holder_tag"))
        ignored = 0
        try:
            document = await mongo.card_inventories.find_one_and_update(
                {"_id": holder_tag},
                {"$inc": {"ignored_requests": 1}},
                return_document=True,
            )
            ignored = int((document or {}).get("ignored_requests") or 0)
        except Exception:
            pass

        # The "expired" policy row: the standing post silently collapses to
        # its closed form and NOBODY is DMed - before this, the post kept
        # looking open forever while both players got a DM about a proposal
        # neither had touched in 12 hours. The check-in below is the one
        # deliberate exception and keeps its DM.
        expired_trade = dict(trade)
        expired_trade.update(
            status="expired", expired_at=now, updated_at=now
        )
        if trade.get("channel_message_id") and not edit_budget.take():
            # Over budget: the state change above already landed; only the
            # cosmetic edit waits for the next pass's drain.
            await _mark_channel_edit_pending(mongo, trade["_id"])
        else:
            await cards_command._deliver(
                bot, mongo, expired_trade, event="expired"
            )

        if ignored >= cards_command.IGNORED_BEFORE_CHECKIN:
            await _send_checkin(mongo, bot, trade, holder_tag, now=now)
    return closed


async def _send_checkin(mongo, bot, trade, holder_tag, *, now) -> None:
    """Ask once, and only once, whether they are still trading."""
    try:
        inventory = await mongo.card_inventories.find_one({"_id": holder_tag})
    except Exception:
        return
    if not inventory or inventory.get("trading_paused"):
        return
    if inventory.get("checkin_sent_at"):
        return            # already asked; the 24-hour clock is already running
    discord_id = trade.get("holder_discord_id")
    if not discord_id:
        return
    sent = await cards_command._send_trade_dm(
        bot,
        int(discord_id),
        cards_command._checkin_dm(holder_tag, inventory.get("player_name")),
        trade_id=str(trade["_id"]),
    )
    # Stamped even when the DM fails, or a member with closed DMs would be
    # asked again after every single expiry and never reach a decision.
    await mongo.card_inventories.update_one(
        {"_id": holder_tag},
        {"$set": {"checkin_sent_at": now, "checkin_delivered": bool(sent)}},
    )


async def _pause_silent_members(mongo, bot, *, now) -> int:
    """Job 3: no answer to the check-in within 24 hours means no."""
    cutoff = now - cards_command.CHECKIN_ANSWER_FOR
    try:
        due = await mongo.card_inventories.find({
            "checkin_sent_at": {"$lte": cutoff},
            "trading_paused": {"$ne": True},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] check-in query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    paused = 0
    for inventory in due:
        result = await mongo.card_inventories.update_one(
            {"_id": inventory["_id"], "trading_paused": {"$ne": True}},
            {"$set": {
                "trading_paused": True,
                "trading_paused_at": now,
                "trading_paused_reason": "no answer to check-in",
                "checkin_sent_at": None,
                "updated_at": now,
            }},
        )
        if getattr(result, "modified_count", 0):
            paused += 1
    return paused


async def _recover_interrupted_completions(mongo, bot, *, now) -> int:
    """Move expired write-ahead claims into the existing review cleanup."""
    try:
        due = await mongo.card_trades.find({
            "kind": "trade",
            "status": "completing",
            "expires_at": {"$lte": now},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] completion recovery query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    recovered = 0
    for trade in due:
        try:
            updated = await cards_command._expire_trade_if_needed(
                mongo, trade, bot=bot
            )
            if updated.get("status") == "needs_review":
                recovered += 1
        except Exception as exc:
            print(f"[Cards Deadlines] completion recovery failed trade="
                  f"{trade.get('_id')}: {type(exc).__name__}: {exc}")
    return recovered


async def _settle_confirmed_sides(mongo, bot, *, now) -> int:
    """Job 4: a confirmed side still owed its incoming credit is settled.

    Old-style confirmations (from before per-side settlement) left the
    confirmer's incoming card reserved on their own inventory until the
    partner answered - the exact "in a trade · 0 for a week" report this
    change exists for. The partner's tap no longer touches the confirmer, so
    this pass delivers the stuck credit instead: for every live trade with a
    confirmed role whose inventory still carries this trade's marker on
    their incoming card, credit below OWNED (fenced on the marker + owner)
    and drop both of that side's markers. Idempotent - a second pass matches
    nothing - and doubling as the standing safety net for any future
    half-settled side, which self-heals within one sweep interval.

    Silent by policy: zero DMs, zero posts. The member's own tap already
    told them everything, and the credit is the bot catching up with it.
    """
    del bot
    try:
        due = await mongo.card_trades.find({
            "kind": "trade",
            "status": {"$in": list(cards_command.SWAP_LIVE_STATUSES)},
            "$or": [
                {"requester_confirmed_at": {"$exists": True}},
                {"holder_confirmed_at": {"$exists": True}},
            ],
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] confirmed-side query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    settled = 0
    for trade in due:
        for role in ("requester", "holder"):
            if not trade.get(f"{role}_confirmed_at"):
                continue
            try:
                if await cards_command._settle_stuck_confirmed_side(
                    mongo, trade, role=role, now=now
                ):
                    settled += 1
            except Exception as exc:
                print(f"[Cards Deadlines] confirmed-side settle failed "
                      f"trade={trade.get('_id')} role={role}: "
                      f"{type(exc).__name__}: {exc}")
    return settled


async def _finish_one_sided_swaps(mongo, bot, *, now) -> int:
    """Job 5: one player confirmed, the other never did.

    The silent side's whole account is settled FOR them: their sent card is
    deducted only if a spare still exists, their incoming card is credited
    if still below OWNED, and their locks are released either way. The trade
    then completes exactly like a tapped confirmation would.
    """
    cutoff = now - cards_command.SWAP_CONFIRM_FOR
    try:
        due = await mongo.card_trades.find({
            "kind": "trade",
            "status": {"$in": list(cards_command.SWAP_LIVE_STATUSES)},
            "confirm_deadline_at": {"$lte": now},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] confirm query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    settled = 0
    for trade in due:
        try:
            for role in ("requester", "holder"):
                if trade.get(f"{role}_confirmed_at"):
                    continue
                outcome, _remaining, updated = (
                    await cards_command._run_swap_leg_confirmation(
                        mongo,
                        trade,
                        role=role,
                        now=now,
                        # The deadline path deliberately closes a silent side
                        # even when its reserved spare is no longer present.
                        record_no_spare=True,
                    )
                )
                if outcome == "changed":
                    continue
                moved = outcome == "moved"
                # The trade closes either way; this records whether the leg
                # really moved, so a completed trade with an unmoved leg can
                # be told apart from a clean one later.
                await mongo.card_trades.update_one(
                    {"_id": trade["_id"]},
                    {"$set": {
                        f"{role}_auto_settled": (
                            "deducted" if moved else "no_spare"
                        ),
                    }},
                )
                settled += 1
                discord_id = trade.get(f"{role}_discord_id")
                if discord_id:
                    await cards_command._notify_trade_status(
                        bot, updated, recipient_id=int(discord_id),
                        title=AUTO_DEDUCT_TITLE,
                        detail=(
                            AUTO_DEDUCT_DETAIL_MOVED
                            if moved
                            else AUTO_DEDUCT_DETAIL_NO_SPARE
                        ),
                        # Gold when a copy was actually removed: the reader
                        # may want to correct it. Otherwise a quiet close.
                        accent=(
                            cards_command.GOLD_ACCENT if moved else None
                        ),
                    )
                # The old "owed player" DM is gone: under per-side
                # settlement the waiting player's incoming card was credited
                # by their OWN confirmation, so the silent side having no
                # spare changes nothing for them.
        except Exception as exc:
            print(f"[Cards Deadlines] confirm settle failed trade="
                  f"{trade.get('_id')}: {type(exc).__name__}: {exc}")
    return settled


async def _close_abandoned_swaps(mongo, bot, *, now) -> int:
    """Job 6: neither player ever confirmed, so nothing else can free these."""
    try:
        due = await mongo.card_trades.find({
            "kind": "trade",
            "status": {"$in": list(cards_command.SWAP_LIVE_STATUSES)},
            "backstop_at": {"$lte": now},
            "requester_confirmed_at": {"$exists": False},
            "holder_confirmed_at": {"$exists": False},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] backstop query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    closed = 0
    for trade in due:
        result = await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": {"$in": list(cards_command.SWAP_LIVE_STATUSES)},
            },
            {
                "$set": {
                    "status": "expired",
                    "expired_at": now,
                    "updated_at": now,
                    **cards_command._cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        if not getattr(result, "modified_count", 0):
            continue
        closed += 1
        await cards_command._release_proposal_slots(mongo, trade)
        await cards_command._finish_trade_cleanup(
            mongo, trade, owner=cards_command._reservation_owner(trade)
        )
        for role in ("requester", "holder"):
            discord_id = trade.get(f"{role}_discord_id")
            if discord_id:
                await cards_command._notify_trade_status(
                    bot, trade, recipient_id=int(discord_id),
                    title="Card swap closed",
                    detail=(
                        "Neither of you confirmed within 7 days, so it was "
                        "closed.\nBoth cards are free again. Nothing was "
                        "changed."
                    ),
                )
    return closed


async def _expire_open_requests(mongo, bot, *, now, edit_budget) -> int:
    """Job 7: a want-ad nobody claimed within 48 hours closes itself.

    NO DM, NO ping, NO new post - a want-ad expiring after 48 quiet hours is
    the definition of nobody-needs-to-know. The public post silently
    collapses to its compact closed form, exactly as cards_req_close flips
    it, minus the task wrapper: sweepers await.
    """
    try:
        due = await mongo.card_trades.find({
            "kind": "open_request",
            "status": "open",
            "expires_at": {"$lte": now},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] open request query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    expired = 0
    for request in due:
        result = await mongo.card_trades.update_one(
            {"_id": request["_id"], "kind": "open_request", "status": "open"},
            {
                "$set": {
                    "status": "expired",
                    "expired_at": now,
                    "updated_at": now,
                },
                # Terminal transitions free the one-request-per-card key.
                "$unset": {"open_request_key": ""},
            },
        )
        if not getattr(result, "modified_count", 0):
            continue      # claimed or closed between the read and the write
        expired += 1
        if not request.get("channel_message_id"):
            continue      # never reached the board; nothing to edit
        if not edit_budget.take():
            await _mark_channel_edit_pending(mongo, request["_id"])
            continue
        # The request is not trade-shaped, so the kind-aware trade edit
        # cannot render it; flip the post directly to its terminal form.
        await cards_command._channel_edit(
            bot,
            channel_id=(
                request.get("channel_id")
                or cards_command._configured_cards_channel_id()
            ),
            message_id=request.get("channel_message_id"),
            components=cards_command._open_request_post(
                dict(request, status="expired")
            ),
            key=request.get("_id"),
        )
    return expired


async def _recover_stalled_claims(mongo, bot, *, now) -> int:
    """Job 8: return a claim that crashed mid-flight to the board.

    `_perform_open_request_claim` writes claim_until at the claiming CAS for
    exactly this recovery: a crash between "claiming" and either "claimed"
    or its rollback would otherwise park the want-ad forever. The CAS here
    is fenced on BOTH status:"claiming" and the expired claim_until, so a
    fresh claim written between the read and this write - carrying a future
    claim_until - survives untouched. The public post never changed during
    claiming, so there is nothing to edit.
    """
    try:
        due = await mongo.card_trades.find({
            "kind": "open_request",
            "status": "claiming",
            "claim_until": {"$lte": now},
        }).to_list(length=BATCH)
    except Exception as exc:
        print(f"[Cards Deadlines] stalled claim query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    recovered = 0
    for request in due:
        result = await mongo.card_trades.update_one(
            {
                "_id": request["_id"],
                "kind": "open_request",
                "status": "claiming",
                "claim_until": {"$lte": now},
            },
            {
                "$set": {"status": "open", "updated_at": now},
                "$unset": {
                    "claim_token": "",
                    "claim_until": "",
                    "claimed_by_discord_id": "",
                    "claimed_by_tag": "",
                    "claimed_at": "",
                },
            },
        )
        if getattr(result, "modified_count", 0):
            recovered += 1
    return recovered


async def _drain_pending_channel_edits(mongo, bot, *, edit_budget) -> int:
    """Flush standing-post edits an over-budget earlier pass deferred.

    Runs FIRST in the pass, so last pass's leftovers get the budget before
    this pass spends it - otherwise a sustained backlog could starve them
    forever. The marker comes off whether or not the edit lands:
    `_channel_edit` already fails soft, a deleted message must not be
    retried every pass for eternity, and any later status change re-renders
    the post anyway.
    """
    if edit_budget.remaining <= 0:
        return 0
    try:
        due = await mongo.card_trades.find({
            "channel_edit_pending": True,
        }).to_list(length=min(BATCH, edit_budget.remaining))
    except Exception as exc:
        print(f"[Cards Deadlines] pending edit query failed: "
              f"{type(exc).__name__}: {exc}")
        return 0

    drained = 0
    for doc in due:
        if not edit_budget.take():
            break
        result = await mongo.card_trades.update_one(
            {"_id": doc["_id"], "channel_edit_pending": True},
            {"$unset": {"channel_edit_pending": ""}},
        )
        if not getattr(result, "modified_count", 0):
            continue      # another pass drained it first
        drained += 1
        if str(doc.get("kind") or "") == "open_request":
            # Not trade-shaped; render its own standing post directly.
            await cards_command._channel_edit(
                bot,
                channel_id=(
                    doc.get("channel_id")
                    or cards_command._configured_cards_channel_id()
                ),
                message_id=doc.get("channel_message_id"),
                components=cards_command._open_request_post(doc),
                key=doc.get("_id"),
            )
        else:
            # Kind-aware: trade V2, legacy content, or gem ask.
            await cards_command._update_trade_channel(bot, doc)
    return drained


async def sweep_once() -> None:
    if not bot_instance or not mongo_client:
        return
    now = datetime.now(timezone.utc)
    edit_budget = _EditBudget(SWEEP_CHANNEL_EDIT_BUDGET)
    drained = await _drain_pending_channel_edits(
        mongo_client, bot_instance, edit_budget=edit_budget
    )
    expired = await _expire_unanswered_proposals(
        mongo_client, bot_instance, now=now, edit_budget=edit_budget
    )
    paused = await _pause_silent_members(mongo_client, bot_instance, now=now)
    recovered = await _recover_interrupted_completions(
        mongo_client, bot_instance, now=now
    )
    sides_settled = await _settle_confirmed_sides(
        mongo_client, bot_instance, now=now
    )
    settled = await _finish_one_sided_swaps(mongo_client, bot_instance, now=now)
    closed = await _close_abandoned_swaps(mongo_client, bot_instance, now=now)
    requests_expired = await _expire_open_requests(
        mongo_client, bot_instance, now=now, edit_budget=edit_budget
    )
    reclaimed = await _recover_stalled_claims(
        mongo_client, bot_instance, now=now
    )
    if (expired or paused or recovered or sides_settled or settled or closed
            or requests_expired or reclaimed or drained):
        print(f"[Cards Deadlines] expired={expired} paused={paused} "
              f"review_recovered={recovered} sides_settled={sides_settled} "
              f"auto_confirmed={settled} "
              f"abandoned={closed} requests_expired={requests_expired} "
              f"claims_reclaimed={reclaimed} edits_drained={drained}")


async def sweep_loop() -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[Cards Deadlines] sweep error: {type(exc).__name__}: {exc}")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global bot_instance, mongo_client, sweep_task

    bot_instance = bot
    mongo_client = mongo
    if sweep_task and not sweep_task.done():
        print("[Cards Deadlines] sweep already running; start skipped")
        return
    sweep_task = asyncio.create_task(sweep_loop(), name="cards-deadlines")
    print(f"[Cards Deadlines] sweeping every {SWEEP_INTERVAL_SECONDS // 60}m")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global sweep_task

    if sweep_task and not sweep_task.done():
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        print("[Cards Deadlines] sweep stopped")
