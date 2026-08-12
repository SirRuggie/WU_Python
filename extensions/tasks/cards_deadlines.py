"""Enforce the trade deadlines that nothing else can.

Every rule here is a stored timestamp being compared to now, never a timer
held in memory. That is deliberate: a restart resumes exactly where it left
off, and a bot that was down for two days processes everything overdue on its
first pass rather than losing it.

Five jobs, in the order a trade meets them:

1. A proposal nobody answers within 12 hours closes itself, and the holder's
   consecutive ignored-request count goes up.
2. Two ignored in a row asks the holder whether they are still trading.
3. No answer to that within 24 hours hides their cards. Silence is a no.
4. Once one player confirms they sent their card, the other has 7 days before
   theirs is deducted for them.
5. A swap NEITHER player ever confirms is closed after 7 days, because nothing
   else would ever release those two cards.
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

sweep_task = None
bot_instance = None
mongo_client = None


async def _expire_unanswered_proposals(mongo, bot, *, now) -> int:
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

        for recipient in ("requester", "holder"):
            discord_id = trade.get(f"{recipient}_discord_id")
            if discord_id:
                await cards_command._notify_trade_status(
                    bot, trade, recipient_id=int(discord_id),
                    title="Card proposal expired",
                    detail=(
                        "Nobody answered within 12 hours, so it closed. "
                        "Nothing changed in either collection."
                    ),
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


async def _finish_one_sided_swaps(mongo, bot, *, now) -> int:
    """Job 4: one player confirmed, the other never did."""
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
        for role in ("requester", "holder"):
            if trade.get(f"{role}_confirmed_at"):
                continue
            moved, _remaining = await cards_command._confirm_swap_leg(
                mongo, trade, role=role, now=now
            )
            updated = await cards_command._record_swap_confirmation(
                mongo, trade, role=role, now=now
            )
            settled += 1
            discord_id = trade.get(f"{role}_discord_id")
            if discord_id:
                await cards_command._notify_trade_status(
                    bot, updated, recipient_id=int(discord_id),
                    title="Your card was deducted automatically",
                    detail=(
                        "The other player confirmed they sent theirs over "
                        "7 days ago and we did not hear back from you. "
                        "If this is wrong, open /cards, tap the card and set "
                        "your real count."
                        if moved
                        else "The other player confirmed theirs over 7 days "
                        "ago. Your collection no longer showed a spare, so "
                        "nothing was changed."
                    ),
                )
    return settled


async def _close_abandoned_swaps(mongo, bot, *, now) -> int:
    """Job 5: neither player ever confirmed, so nothing else can free these."""
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
                        "closed and both cards are free again. Nothing was "
                        "changed in either collection."
                    ),
                )
    return closed


async def sweep_once() -> None:
    if not bot_instance or not mongo_client:
        return
    now = datetime.now(timezone.utc)
    expired = await _expire_unanswered_proposals(mongo_client, bot_instance, now=now)
    paused = await _pause_silent_members(mongo_client, bot_instance, now=now)
    settled = await _finish_one_sided_swaps(mongo_client, bot_instance, now=now)
    closed = await _close_abandoned_swaps(mongo_client, bot_instance, now=now)
    if expired or paused or settled or closed:
        print(f"[Cards Deadlines] expired={expired} paused={paused} "
              f"auto_confirmed={settled} abandoned={closed}")


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
