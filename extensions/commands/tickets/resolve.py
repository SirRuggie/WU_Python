"""Resolving a ticket: the side effects, and the override path when you lose the race.

Two rules govern everything here.

1. SIDE EFFECTS RUN ONLY ON A WON TRANSITION. Before this module existed, the
   deny handlers posted the applicant-facing denial BEFORE writing the status, so
   two recruiters denying the same ticket in the same second sent the applicant
   two denial messages and both writes landed. The message now happens after
   Mongo has arbitrated, and only for the winner.

2. LOSING IS NOT A DEAD END. A mistaken deny, an appeal, or a leader overruling
   are all normal in recruiting, and none of them should require hand-editing
   Mongo. A recruiter who loses the race is offered an override; the audit array
   records that it overturned a prior resolution, and who did it.

The side effects live in one place so that the first attempt and the override
run identical code rather than two drifting copies.
"""

import hikari
import lightbulb
import coc
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Mapping
from utils.component_state import delete_state, get_state, insert_state

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.commands import ticket_runtime
from extensions.commands.tickets import (
    account_sync,
    flag_store,
    loader,
    perms,
    schema,
    store,
)
from extensions.components import register_action
from utils.constants import GREEN_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

DENIED_THUMB = "assets/tickets/static/Denied.png"
# No dedicated "approved"/"accepted" image exists yet in
# assets/tickets/static/ (only Denied.png does) -- the club logo stands in
# for it until one is added.
APPROVAL_THUMB = "assets/branding/logo/WU_Logo.png"
_log = logging.getLogger(__name__)

RESOLUTION_EFFECT_LEASE = timedelta(minutes=10)
RESOLUTION_EFFECT_RETRY_MESSAGE = (
    "The decision is recorded and will not be lost. Remaining Discord and console "
    "updates are retrying automatically. Ask an admin to inspect only if this persists."
)
OVERRIDE_EFFECT_PENDING_MESSAGE = (
    "The earlier decision is still finishing its applicant and console updates. "
    "Nothing was changed. Try this override again in a moment."
)
FWA_IDENTITY_REVIEW_MESSAGE = (
    "New linked account(s) were found. Review the refreshed Chocolate links in "
    "the staff thread, then click Approve again."
)
FWA_IDENTITY_REFRESH_PENDING_MESSAGE = (
    "The staff account and Chocolate checklist is still refreshing. Review it "
    "when the update appears, then click Approve again."
)

KIND_APPROVE = "approve"
KIND_DENY_FWA = "deny_fwa"
KIND_DENY_MAIN = "deny_main"
KIND_DENY_CUSTOM = "deny_custom"

# Kept verbatim from the original handlers - this is copy the applicant reads.
_DENIAL_BODY = {
    KIND_DENY_FWA: (
        "I am sorry but unfortunately, you do not meet the criteria for Warriors United. "
        "Here's a resource link to other FWA Clans that may have a spot for you.\n\n"
        "https://band.us/@reqfwa\n\n"
        "Good luck!"
    ),
    KIND_DENY_MAIN: (
        "I am sorry but unfortunately, you do not meet the criteria for Warriors United. "
        "Here's a resource link to other Clans that may have a spot for you.\n\n"
        "https://discord.com/invite/clashofclans\n\n"
        "Good luck!"
    ),
}

DENIAL_TYPE = {
    KIND_DENY_FWA: "fwa_default",
    KIND_DENY_MAIN: "main_default",
    KIND_DENY_CUSTOM: "custom",
}


def ts(value, style: str = "R") -> str:
    """<t:unix:R> - ages itself, and renders in the reader's own timezone."""
    try:
        return f"<t:{int(value.timestamp())}:{style}>"
    except (AttributeError, TypeError, ValueError):
        return "earlier"


# --- side effects ------------------------------------------------------------


def _thread_identity(ticket: dict) -> tuple[int, int]:
    if ticket.get("venue") != "thread":
        raise RuntimeError("ticket resolution effects require a thread ticket")
    channel_id = int((ticket.get("location") or {}).get("id") or 0)
    user_id = int(ticket.get("user_id") or 0)
    if not channel_id or not user_id:
        raise RuntimeError("ticket is missing its thread or applicant identity")
    return channel_id, user_id

# Fixed card text used to identify a decision notification structurally,
# instead of a hidden marker line. Kept independent of the applicant mention
# and (for denial) the reason, both of which vary per ticket.
APPROVAL_CARD_TITLE = "You have been accepted to Warriors United."
# The approval card's copy changed from a plain-text message to a matching
# Components V2 card. A card posted before that change still carries this
# older sentence -- kept so it is still recognised structurally.
_LEGACY_APPROVAL_CARD_TITLE = "Congratulations on being accepted to Warriors United!"
DENIAL_CARD_TITLE = (
    "we regret to inform you that currently your application has been denied."
)


async def apply_denial(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        kind: str,
        ticket: dict,
        reason: str | None = None,
        marker: str | None = None,
):
    """Message the applicant in the candidate thread. WON transitions only.

    Returns the created message -- callers checkpoint its id for durable,
    marker-free recovery.
    """
    channel_id, user_id = _thread_identity(ticket)
    body = reason if kind == KIND_DENY_CUSTOM else _DENIAL_BODY[kind]
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{user_id}>, we regret to inform you that currently your "
                            f"application has been denied.\n\n"
                            f"## **Reason:**\n{body}"
                        ))
                    ],
                    accessory=Thumbnail(media=DENIED_THUMB),
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]
    return await bot.rest.create_message(
        channel=channel_id,
        components=components,
        mentions_everyone=False,
        user_mentions=[int(user_id)],
        role_mentions=False,
    )


async def apply_approval(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        ticket: dict,
        marker: str | None = None,
):
    """Congratulate the applicant. Thread tickets are never renamed.

    Matches ``apply_denial``'s card layout (a green accent instead of red,
    and the club logo standing in for the missing dedicated approval image
    -- see ``APPROVAL_THUMB``), in plain English for non-native speakers.

    Returns the created message -- callers checkpoint its id for durable,
    marker-free recovery.
    """
    channel_id, user_id = _thread_identity(ticket)
    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{user_id}> **Congratulations!** You have been "
                            f"accepted to Warriors United. A recruiter will "
                            f"contact you with your clan invite. This ticket "
                            f"stays open if you have questions. You can "
                            f"always find it again with the **My ticket** "
                            f"button on the panel."
                        ))
                    ],
                    accessory=Thumbnail(media=APPROVAL_THUMB),
                ),
                Media(items=[MediaItem(media="assets/Green_Footer.png")]),
            ],
        )
    ]
    return await bot.rest.create_message(
        channel=channel_id,
        components=components,
        mentions_everyone=False,
        user_mentions=[int(user_id)],
        role_mentions=False,
    )


async def run_side_effects(
        bot, mongo, *, kind: str, ticket: dict,
        reason=None, marker: str | None = None,
):
    """Send the applicant's decision card. Returns the created message.

    ``marker`` is no longer rendered into the card -- it stays only as the
    resolution-effects idempotency key threaded through Mongo checkpoints.
    """
    if kind == KIND_APPROVE:
        return await apply_approval(
            bot, mongo, ticket=ticket, marker=marker,
        )
    return await apply_denial(
        bot, mongo, kind=kind, ticket=ticket, reason=reason, marker=marker,
    )


def _component_contains_marker(component, marker: str) -> bool:
    content = str(getattr(component, "content", "") or "")
    if any(
        line.strip() in {marker, f"-# {marker}"}
        for line in content.splitlines()
    ):
        return True
    return any(
        _component_contains_marker(child, marker)
        for child in (getattr(component, "components", ()) or ())
    )


def _component_contains_text(component, text: str) -> bool:
    content = str(getattr(component, "content", "") or "")
    if text in content:
        return True
    return any(
        _component_contains_text(child, text)
        for child in (getattr(component, "components", ()) or ())
    )


def _is_notification_card(message, kind: str) -> bool:
    """True if this message is the applicant's own decision card.

    Identified by its fixed card text -- no bookkeeping text is posted to
    Discord for it -- rather than a hidden marker line. An approval checks
    both the current and legacy title so a card from before the card's
    copy changed is still recognised.
    """

    titles = (
        (APPROVAL_CARD_TITLE, _LEGACY_APPROVAL_CARD_TITLE)
        if kind == KIND_APPROVE
        else (DENIAL_CARD_TITLE,)
    )
    content = str(getattr(message, "content", "") or "")
    if any(title in content for title in titles):
        return True
    return any(
        _component_contains_text(component, title)
        for component in (getattr(message, "components", ()) or ())
        for title in titles
    )


async def _all_messages(rest, channel_id: int) -> list:
    iterator = rest.fetch_messages(channel_id)
    collect = getattr(iterator, "collect", None)
    if callable(collect):
        return list(await collect(list))
    to_list = getattr(iterator, "to_list", None)
    if callable(to_list):
        return list(await to_list())
    return list(await iterator)


async def _notification_exists(
    rest,
    channel_id: int,
    marker: str,
    *,
    bot_user_id: int,
    kind: str = "",
    message_id: int = 0,
) -> bool:
    """True if the applicant's decision notification was already delivered.

    Checked first by the message id recorded in the resolution-effects
    checkpoint, when there is one. Otherwise this walks the full candidate
    thread -- so a crash followed by heavy activity cannot push the
    notification beyond a fixed recent-message window and cause a duplicate
    -- matching it structurally by ``kind``'s fixed card text (see
    `_is_notification_card`). A message from before this change that still
    carries the old ``-# {marker}`` line is still recognised.
    """

    if message_id:
        try:
            message = await rest.fetch_message(channel_id, message_id)
        except hikari.NotFoundError:
            message = None
        if message is not None and int(
            getattr(getattr(message, "author", None), "id", 0)
        ) == int(bot_user_id):
            return True
    messages = await _all_messages(rest, channel_id)
    for message in messages:
        if int(getattr(getattr(message, "author", None), "id", 0)) != int(bot_user_id):
            continue
        content = str(getattr(message, "content", "") or "")
        if any(
            line.strip() in {marker, f"-# {marker}"}
            for line in content.splitlines()
        ):
            return True
        if any(
            _component_contains_marker(component, marker)
            for component in (getattr(message, "components", ()) or ())
        ):
            return True
        if kind and _is_notification_card(message, kind):
            return True
    return False


async def _checkpoint_effect(
        mongo: MongoClient,
        ticket_id,
        marker: str,
        *,
        step: str,
        state: str,
        error: Exception | None = None,
        message_id: int | None = None,
) -> bool:
    """Best-effort durable checkpoint; physical effects remain authoritative.

    ``message_id``, when given, is the Discord message this step delivered --
    recorded so a later retry can confirm delivery by id first, instead of
    scanning the thread (see `_notification_exists`).
    """
    now = store.utcnow()
    step_doc = {
        "state": state,
        "at": now,
        "error_type": type(error).__name__ if error else None,
    }
    if message_id:
        step_doc["message_id"] = int(message_id)
    try:
        result = await store.update_one(
            mongo,
            {
                "_id": ticket_id,
                **store.RUNTIME_FILTER,
                "resolution_effects.marker": marker,
            },
            {
                "$set": {
                    f"resolution_effects.{step}": step_doc,
                    "resolution_effects.updated_at": now,
                    "updated_at": now,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": {
                    "$each": [{
                        "event": f"resolution_{step}_{state}",
                        "at": now,
                        "effect_marker": marker,
                        "error_type": type(error).__name__ if error else None,
                    }],
                    "$slice": -store.MAX_AUDIT_ENTRIES,
                }},
            },
        )
        return bool(getattr(result, "matched_count", 0))
    except Exception:
        _log.exception("resolution checkpoint failed ticket=%s step=%s", ticket_id, step)
        return False


async def _finalize_effects(
    mongo: MongoClient,
    ticket_id,
    marker: str,
) -> bool:
    """Mark resolution effects complete once every step is already done.

    Only reached from `_process_resolution_effects_owned` when its `pending`
    list is empty, i.e. the notification, staff_context and hub steps each
    already checkpointed their own `state`/`at` (via `_checkpoint_effect`,
    this pass or an earlier one). Re-stamping those three sub-documents here
    used to overwrite honest per-step delivery times with the completion
    time -- so a notification delivered promptly on an earlier pass looked,
    in Mongo, exactly like it was delivered together with a staff_context
    step that only cleared on a later retry. This only ever touches the
    completion fields; the per-step docs are left as their own checkpoints
    recorded them.
    """
    now = store.utcnow()
    try:
        result = await store.update_one(
            mongo,
            {"_id": ticket_id, **store.RUNTIME_FILTER, "resolution_effects.marker": marker},
            {
                "$set": {
                    "resolution_effects.complete": True,
                    "resolution_effects.completed_at": now,
                    "resolution_effects.updated_at": now,
                    "updated_at": now,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": {
                    "$each": [{
                        "event": "resolution_effects_complete",
                        "at": now,
                        "effect_marker": marker,
                    }],
                    "$slice": -store.MAX_AUDIT_ENTRIES,
                }},
            },
        )
        return bool(getattr(result, "matched_count", 0))
    except Exception:
        _log.exception("resolution final checkpoint failed ticket=%s", ticket_id)
        return False


def _resolution_kind(ticket: dict) -> str:
    effects = ticket.get("resolution_effects") or {}
    kind = effects.get("kind")
    if kind in {KIND_APPROVE, *DENIAL_TYPE}:
        return kind
    if ticket.get("status") == "approved":
        return KIND_APPROVE
    return {
        "fwa_default": KIND_DENY_FWA,
        "main_default": KIND_DENY_MAIN,
        "custom": KIND_DENY_CUSTOM,
    }.get(ticket.get("denial_type"), KIND_DENY_CUSTOM)


async def _ensure_notification_thread_writable(rest, ticket: dict) -> None:
    """Temporarily reopen the candidate thread for a missing decision notice."""
    channel_id, _user_id = _thread_identity(ticket)
    channel = await rest.fetch_channel(channel_id)
    if bool(getattr(channel, "is_archived", False)):
        channel = await rest.edit_channel(
            channel_id,
            archived=False,
            reason="Delivering an updated ticket decision",
        )
    if bool(getattr(channel, "is_locked", False)):
        await rest.edit_channel(
            channel_id,
            locked=False,
            reason="Delivering an updated ticket decision",
        )


async def _delete_previous_decision_card(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket: dict,
        effects: Mapping,
) -> None:
    """Remove the decision card an overturn is about to replace.

    Preferred by the message id checkpointed in the resolution being
    overturned (``resolution_effects.previous_notification_message_id``,
    carried over by ``store.transition``). A ticket resolved before that
    checkpoint existed has no id to go on; the fallback then scans the
    candidate thread for the newest bot-authored message that structurally
    matches either card kind (``_is_notification_card``) and deletes that.
    A 404 (already gone) is swallowed. Any other error is re-raised so the
    caller checkpoints the notification step ``failed`` instead of posting a
    new card over an old one that may still be sitting there -- the retry
    (via ``reconcile_pending_resolution_effects``) is idempotent: the
    checkpointed message id will 404 by then (already deleted) or the
    structural scan will find nothing, and ``_notification_exists`` still
    guards against the new card being posted twice.
    """
    channel_id, _user_id = _thread_identity(ticket)
    message_id = store.as_int(effects.get("previous_notification_message_id"))
    if not message_id:
        me = bot.get_me()
        if me is None:
            return
        try:
            messages = await _all_messages(bot.rest, channel_id)
        except Exception:
            _log.exception(
                "previous decision card scan failed ticket=%s", ticket.get("_id"),
            )
            raise
        candidates = [
            message for message in messages
            if int(getattr(getattr(message, "author", None), "id", 0)) == int(me.id)
            and (
                _is_notification_card(message, KIND_APPROVE)
                or _is_notification_card(message, KIND_DENY_CUSTOM)
            )
        ]
        if not candidates:
            return
        message_id = int(max(candidates, key=lambda message: int(message.id)).id)
    try:
        await bot.rest.delete_message(channel_id, message_id)
    except hikari.NotFoundError:
        pass
    except Exception:
        _log.exception(
            "previous decision card deletion failed ticket=%s message=%s",
            ticket.get("_id"), message_id,
        )
        raise
    try:
        await store.update_one(
            mongo,
            {"_id": ticket["_id"], **store.RUNTIME_FILTER},
            {"$push": {"audit": {
                "$each": [{
                    "event": "previous_decision_card_removed",
                    "at": store.utcnow(),
                    "message_id": message_id,
                }],
                "$slice": -store.MAX_AUDIT_ENTRIES,
            }}},
        )
    except Exception:
        _log.exception(
            "previous decision card audit write failed ticket=%s", ticket.get("_id"),
        )


async def _acquire_resolution_effect_lease(
        mongo: MongoClient,
        ticket_id,
        marker: str,
    owner: str,
) -> dict | None:
    now = store.utcnow()
    return await mongo.tickets.find_one_and_update(
        {
            "_id": ticket_id,
            **store.RUNTIME_FILTER,
            "resolution_effects.marker": marker,
            "resolution_effects.complete": {"$ne": True},
            "$or": [
                {"resolution_effects.lease_until": {"$exists": False}},
                {"resolution_effects.lease_until": {"$lte": now}},
                {"resolution_effects.lease_owner": owner},
            ],
        },
        {"$set": {
            "resolution_effects.lease_owner": owner,
            "resolution_effects.lease_until": now + RESOLUTION_EFFECT_LEASE,
            "resolution_effects.updated_at": now,
        }},
        return_document=store.ReturnDocument.AFTER,
    )


async def _release_resolution_effect_lease(
        mongo: MongoClient,
        ticket_id,
        marker: str,
        owner: str,
) -> None:
    try:
        await store.update_one(
            mongo,
            {
                "_id": ticket_id,
                **store.RUNTIME_FILTER,
                "resolution_effects.marker": marker,
                "resolution_effects.lease_owner": owner,
            },
            {"$unset": {
                "resolution_effects.lease_owner": "",
                "resolution_effects.lease_until": "",
            }},
        )
    except Exception:
        _log.exception("resolution effect lease release failed ticket=%s", ticket_id)


async def _process_resolution_effects_owned(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket: dict,
) -> store.Transition:
    """Run resolution effects while the caller owns the durable effect lease."""
    effects = ticket.get("resolution_effects") or {}
    marker = str(effects.get("marker") or "")
    kind = _resolution_kind(ticket)
    location_id = int((ticket.get("location") or {}).get("id") or 0)
    pending: list[tuple[str, Exception]] = []
    # Set by the GuildThreadDeleteEvent listener in handlers.py. A step that
    # needs the missing half of the pair is marked skipped (with an audit
    # note from _checkpoint_effect) instead of retried every 60s forever.
    candidate_thread_missing = ticket_runtime.thread_missing_has_role(ticket, "candidate")
    staff_thread_missing = ticket_runtime.thread_missing_has_role(ticket, "staff")

    notification = effects.get("notification") or {}
    notification_message_id = store.as_int(notification.get("message_id"))
    try:
        notification_state = notification.get("state")
        if notification_state not in {"delivered", "skipped"}:
            if candidate_thread_missing:
                await _checkpoint_effect(
                    mongo, ticket["_id"], marker, step="notification", state="skipped",
                )
            else:
                me = bot.get_me()
                if me is None:
                    raise RuntimeError("bot identity is unavailable")
                sent_message = None
                if not await _notification_exists(
                    bot.rest,
                    location_id,
                    marker,
                    bot_user_id=int(me.id),
                    kind=kind,
                    message_id=notification_message_id,
                ):
                    await _ensure_notification_thread_writable(bot.rest, ticket)
                    if effects.get("overturn"):
                        await _delete_previous_decision_card(bot, mongo, ticket, effects)
                    sent_message = await run_side_effects(
                        bot,
                        mongo,
                        kind=kind,
                        ticket=ticket,
                        reason=ticket.get("denial_reason"),
                        marker=marker,
                    )
                notification_message_id = (
                    store.as_int(getattr(sent_message, "id", 0))
                    or notification_message_id
                )
                await _checkpoint_effect(
                    mongo, ticket["_id"], marker, step="notification", state="delivered",
                    message_id=notification_message_id or None,
                )
    except Exception as exc:
        await _checkpoint_effect(
            mongo, ticket["_id"], marker, step="notification", state="failed", error=exc
        )
        pending.append(("applicant notification", exc))

    try:
        staff_context_state = (effects.get("staff_context") or {}).get("state")
        if staff_context_state in {"delivered", "skipped"}:
            pass
        elif staff_thread_missing:
            await _checkpoint_effect(
                mongo, ticket["_id"], marker, step="staff_context", state="skipped",
            )
        else:
            # Decisions committed before linked-account snapshots existed have
            # nothing new to render; checkpoint them for upgrade-safe recovery.
            if (ticket.get("linked_accounts") or {}).get("version"):
                from extensions.commands.tickets import console

                await console.deliver_staff_identity_context(
                    bot,
                    mongo,
                    ticket,
                    reopen_terminal_thread=True,
                )
                state_id = f"ticket_staff_context:{ticket['_id']}"
                context_state = await mongo.ticket_automation_state.find_one({
                    "_id": state_id,
                    "kind": "ticket_staff_context",
                }) or {}
                delivered_at = context_state.get("delivered_at")
                requested_at = context_state.get("refresh_requested_at")
                if (
                    context_state.get("delivery_state") != "delivered"
                    or context_state.get("lease_owner")
                    or not isinstance(delivered_at, datetime)
                    or not isinstance(requested_at, datetime)
                    or delivered_at < requested_at
                ):
                    raise RuntimeError("latest staff context refresh remains pending")
            await _checkpoint_effect(
                mongo,
                ticket["_id"],
                marker,
                step="staff_context",
                state="delivered",
            )
    except Exception as exc:
        await _checkpoint_effect(
            mongo,
            ticket["_id"],
            marker,
            step="staff_context",
            state="failed",
            error=exc,
        )
        pending.append(("staff account context", exc))

    try:
        if (effects.get("hub") or {}).get("state") != "requested":
            from extensions.commands.tickets import console

            queued = await console.request_hub_refresh_best_effort(
                bot, mongo, reason=f"ticket {ticket.get('status')}"
            )
            if not queued:
                raise RuntimeError("hub refresh was not queued")
            await _checkpoint_effect(
                mongo, ticket["_id"], marker, step="hub", state="requested"
            )
    except Exception as exc:
        await _checkpoint_effect(
            mongo, ticket["_id"], marker, step="hub", state="failed", error=exc
        )
        pending.append(("console refresh", exc))

    if pending:
        latest = await store.find_one(
            mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
        )
        return store.Transition(
            store.EFFECT_FAILED,
            latest or ticket,
            "; ".join(
                f"{type(error).__name__}: {label} is pending"
                for label, error in pending
            ),
        )

    finalized = await _finalize_effects(mongo, ticket["_id"], marker)
    latest = await store.find_one(
        mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
    )
    if not finalized:
        return store.Transition(
            store.EFFECT_FAILED,
            latest or ticket,
            "resolution completion checkpoint is pending",
        )
    return store.Transition(store.WON, latest or ticket)


async def process_resolution_effects(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket: dict,
) -> store.Transition:
    """Reconcile notify -> staff context -> hub without duplicating notifications."""
    effects = ticket.get("resolution_effects") or {}
    if effects.get("complete"):
        return store.Transition(store.WON, ticket, "effects already complete")
    marker = str(effects.get("marker") or "")
    if not marker:
        return store.Transition(store.EFFECT_FAILED, ticket, "resolution marker is missing")
    kind = _resolution_kind(ticket)
    location_id = int((ticket.get("location") or {}).get("id") or 0)
    if not location_id:
        return store.Transition(store.EFFECT_FAILED, ticket, "ticket thread is missing")
    owner = uuid.uuid4().hex
    try:
        leased = await _acquire_resolution_effect_lease(
            mongo, ticket["_id"], marker, owner
        )
    except Exception as exc:
        _log.exception("resolution effect lease acquisition failed ticket=%s", ticket.get("_id"))
        return store.Transition(
            store.EFFECT_FAILED,
            ticket,
            f"{type(exc).__name__}: resolution delivery is pending",
        )
    if leased is None:
        latest = await store.find_one(
            mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
        )
        if ((latest or {}).get("resolution_effects") or {}).get("complete"):
            return store.Transition(store.WON, latest, "effects already complete")
        return store.Transition(
            store.EFFECT_FAILED,
            latest or ticket,
            "another worker is delivering this decision",
        )
    try:
        return await _process_resolution_effects_owned(bot, mongo, leased)
    finally:
        await _release_resolution_effect_lease(
            mongo, ticket["_id"], marker, owner
        )


# Tracks in-flight background effect runs so asyncio does not garbage-collect
# a Task that nothing else holds a reference to (a task with no other
# referrers can be swept mid-run, silently dropping the applicant
# notification, staff context delivery, and hub refresh it was doing).
_background_effect_tasks: set[asyncio.Task] = set()


def _on_background_effects_done(task: asyncio.Task) -> None:
    _background_effect_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _log.error(
            "background resolution effects task %s failed", task.get_name(),
            exc_info=exc,
        )
        return
    # `process_resolution_effects` never raises for a step that failed --
    # it reports failure as `Transition(EFFECT_FAILED, ...)` so the reason
    # and partial doc survive -- so a failed applicant notification only
    # shows up here by reading the result, not by catching an exception.
    result = task.result()
    if not result.won:
        _log.error(
            "[Tickets] resolution effects incomplete ticket=%s reason=%s",
            (result.doc or {}).get("_id"), result.reason,
        )


def _schedule_resolution_effects(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket: dict,
) -> asyncio.Task:
    """Run `process_resolution_effects` off the click path.

    The decision itself (`store.transition`) has already committed by the
    time this is called; everything `process_resolution_effects` does from
    here -- the candidate-thread scan, the decision card, staff-context
    delivery, the hub refresh -- is idempotent and reconciled on its own by
    `reconcile_pending_resolution_effects` on startup, so a crash mid-task
    is already handled without the caller waiting on it.
    """
    task = asyncio.create_task(
        process_resolution_effects(bot, mongo, ticket),
        name=f"ticket-resolution-effects:{ticket.get('_id')}",
    )
    _background_effect_tasks.add(task)
    task.add_done_callback(_on_background_effects_done)
    return task


async def wait_for_background_effects() -> None:
    """Test helper: await every in-flight background effects task, then clear it.

    Production code never calls this -- the whole point of scheduling these
    as background tasks is that nothing on the click path waits for them.
    """
    tasks = list(_background_effect_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _background_effect_tasks.clear()


async def reconcile_pending_resolution_effects(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        limit: int = 100,
) -> dict[str, int]:
    pending = await store.find(mongo, {
        **store.RUNTIME_FILTER,
        "status": {"$in": ["approved", "denied"]},
        "resolution_effects.complete": {"$ne": True},
        "resolution_effects.marker": {"$exists": True},
    })
    counts = {"processed": 0, "completed": 0, "pending": 0}
    for ticket in pending[:max(1, int(limit))]:
        counts["processed"] += 1
        result = await process_resolution_effects(bot, mongo, ticket)
        if result.won:
            counts["completed"] += 1
        else:
            counts["pending"] += 1
    return counts


_resolution_reconciler_task: asyncio.Task | None = None


async def _recover_live_account_syncs(
        mongo: MongoClient,
        *,
        bot: hikari.GatewayBot | None = None,
) -> dict[str, int]:
    """Sweep durable account failures while the process remains online."""

    coc_client = account_sync.configured_coc_client()
    if coc_client is None:
        return {"processed": 0, "completed": 0, "failed": 0}

    async def queue_context(ticket: dict) -> str | None:
        from extensions.commands.tickets import console

        return await console.queue_staff_identity_context(mongo, ticket)

    counts = await account_sync.recover_pending_account_syncs(
        mongo,
        coc_client,
        after_sync=queue_context,
    )
    if bot is not None:
        from extensions.commands.tickets import console

        context = await console.recover_pending_staff_identity_contexts(
            bot=bot,
            mongo=mongo,
        )
        counts["context_processed"] = int(context.get("processed", 0))
        counts["context_failed"] = int(context.get("failed", 0))
    return counts


async def _resolution_reconciler(bot: hikari.GatewayBot, mongo: MongoClient) -> None:
    while True:
        try:
            counts = await reconcile_pending_resolution_effects(bot, mongo)
            account_counts = await _recover_live_account_syncs(mongo, bot=bot)
            if (
                account_counts.get("failed")
                or account_counts.get("context_failed")
                or account_counts.get("processed", 0) >= 25
                or account_counts.get("context_processed", 0) >= 25
            ):
                counts["pending"] = 1
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("ticket resolution reconciliation pass failed")
            counts = {"pending": 1}
        await asyncio.sleep(60 if counts.get("pending") else 300)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def recover_resolution_effects(
        _: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    global _resolution_reconciler_task
    if _resolution_reconciler_task is None or _resolution_reconciler_task.done():
        _resolution_reconciler_task = asyncio.create_task(
            _resolution_reconciler(bot, mongo), name="ticket-resolution-reconciler"
        )


async def stop_resolution_reconciler() -> None:
    """Cancel, await, and release the package-owned resolution worker."""
    global _resolution_reconciler_task
    task = _resolution_reconciler_task
    _resolution_reconciler_task = None
    if task is None:
        return
    if not task.done():
        task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    error = result[0] if result else None
    if isinstance(error, Exception) and not isinstance(error, asyncio.CancelledError):
        _log.error(
            "ticket resolution reconciler stopped after %s", type(error).__name__
        )


def _pending_fwa_identity_review(ticket: Mapping) -> Mapping | None:
    linked = ticket.get("linked_accounts") or {}
    review = linked.get("approval_review") if isinstance(linked, Mapping) else None
    if not isinstance(review, Mapping) or review.get("state") != "pending":
        return None
    return review


async def _staff_context_is_fresh_for_review(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket: Mapping,
    review: Mapping,
) -> bool:
    requested_review_at = review.get("requested_at")
    if not isinstance(requested_review_at, datetime):
        return False
    state = await mongo.ticket_automation_state.find_one({
        "_id": f"ticket_staff_context:{ticket.get('_id')}",
        "kind": "ticket_staff_context",
    }) or {}
    refresh_requested_at = state.get("refresh_requested_at")
    delivered_at = state.get("delivered_at")
    durable_fresh = bool(
        state.get("delivery_state") == "delivered"
        and not state.get("lease_owner")
        and isinstance(refresh_requested_at, datetime)
        and isinstance(delivered_at, datetime)
        and refresh_requested_at >= requested_review_at
        and delivered_at >= refresh_requested_at
    )
    if not durable_fresh:
        return False
    from extensions.commands.tickets import console

    return await console.staff_chocolate_context_is_current(
        bot, mongo, ticket
    )


async def _queue_and_deliver_latest_staff_context(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket: dict,
        snapshot: account_sync.AccountSnapshot,
) -> bool:
    """Transfer an account obligation to the outbox, then attempt it now."""

    from extensions.commands.tickets import console

    try:
        if account_sync.staff_context_refresh_required(ticket):
            state_id = await console.queue_staff_identity_context(mongo, ticket)
            if not state_id:
                return False
            if not await account_sync.confirm_staff_context_queued(
                mongo,
                ticket["_id"],
                account_revision=snapshot.revision,
            ):
                return False
        terminal = str(ticket.get("status") or "") in {"approved", "denied"}
        await console.deliver_staff_identity_context(
            bot,
            mongo,
            ticket,
            reopen_terminal_thread=terminal,
            open_only_refresh=not terminal,
        )
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.exception(
            "ticket staff identity refresh could not be queued ticket=%s",
            ticket.get("_id"),
        )
        return False


async def _resolve_ticket(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        ticket_id,
        member: hikari.Member,
        actor_name: str,
        kind: str,
        reason: str | None = None,
        expected_status: str = "open",
        expected_rev: int | None = None,
        override: dict | None = None,
        prior_effect_marker: str | None = None,
        prior_effects_legacy_baseline: bool = False,
        coc_client: coc.Client | None = None,
) -> store.Transition:
    """Authorize, enforce flags, CAS status, then run effects exactly once."""
    if coc_client is None:
        coc_client = account_sync.configured_coc_client()
    if not await perms.is_recruiter(member, mongo):
        return store.Transition(store.UNAUTHORIZED, None, "recruiter permission required")
    if kind not in {KIND_APPROVE, *DENIAL_TYPE}:
        raise ValueError("unknown ticket resolution kind")
    if kind == KIND_DENY_CUSTOM:
        reason = str(reason or "").strip()
        if not 5 <= len(reason) <= 1000:
            return store.Transition(store.BLOCKED, None, "custom denial reason must be 5-1000 characters")

    ticket = await store.find_one(mongo, {"_id": ticket_id, **store.RUNTIME_FILTER})
    if ticket is None:
        return store.Transition(store.MISSING, None)
    # Only meaningful on an override (overturn): the card this resolution's
    # own effects will delete before posting a replacement. Read here,
    # before store.transition() replaces resolution_effects wholesale.
    previous_notification_message_id = store.as_int(
        ((ticket.get("resolution_effects") or {}).get("notification") or {}).get(
            "message_id"
        )
    ) or None
    if override is not None:
        effects = ticket.get("resolution_effects") or {}
        marker = str(prior_effect_marker or "")
        legacy_baseline = bool(
            prior_effects_legacy_baseline
            and store.is_markerless_legacy_terminal(ticket)
        )
        if not legacy_baseline and (
            not marker or str(effects.get("marker") or "") != marker
        ):
            return store.Transition(store.LOST, ticket, "prior resolution changed")
        if not legacy_baseline and effects.get("complete") is not True:
            return store.Transition(
                store.BLOCKED,
                ticket,
                OVERRIDE_EFFECT_PENDING_MESSAGE,
            )
    sync_retry: dict | None = None
    snapshot = account_sync.snapshot_from_ticket(ticket)
    sync_source = (
        account_sync.SOURCE_FINAL_APPROVE
        if kind == KIND_APPROVE
        else account_sync.SOURCE_FINAL_DENY
    )
    if coc_client is None:
        if kind == KIND_APPROVE:
            try:
                failed = await account_sync.record_ticket_account_failure(
                    mongo,
                    ticket_id,
                    source=sync_source,
                    error="ClashClientUnavailable",
                )
            except account_sync.AccountSyncError:
                failed = None
            if failed is not None and failed.ticket is not None:
                ticket = failed.ticket
                snapshot = failed.snapshot
            else:
                snapshot = account_sync.AccountSnapshot(
                    state=account_sync.STATE_FAILED,
                    current_accounts=snapshot.current_accounts,
                    current_tags=snapshot.current_tags,
                    observed_tags=snapshot.observed_tags,
                    retry_required=True,
                    source=sync_source,
                    last_attempt_at=store.utcnow(),
                    last_success_at=snapshot.last_success_at,
                    error="ClashClientUnavailable",
                    revision=snapshot.revision,
                )
        else:
            sync_retry = {
                "source": sync_source,
                "error": "ClashClientUnavailable",
            }
            snapshot = account_sync.AccountSnapshot(
                state=account_sync.STATE_FAILED,
                current_accounts=snapshot.current_accounts,
                current_tags=snapshot.current_tags,
                observed_tags=snapshot.observed_tags,
                retry_required=True,
                source=sync_source,
                last_attempt_at=store.utcnow(),
                last_success_at=snapshot.last_success_at,
                error=sync_retry["error"],
                revision=snapshot.revision + 1,
            )
    else:
        try:
            synced = await account_sync.sync_ticket_accounts(
                mongo,
                coc_client,
                ticket_id,
                source=sync_source,
            )
        except account_sync.AccountSyncError:
            latest = await store.find_one(
                mongo, {"_id": ticket_id, **store.RUNTIME_FILTER}
            )
            if latest is None:
                return store.Transition(store.MISSING, None)
            ticket = latest
            snapshot = account_sync.snapshot_from_ticket(ticket)
            sync_retry = {
                "source": sync_source,
                "error": "AccountSyncCASFailed",
            }
            snapshot = account_sync.AccountSnapshot(
                state=account_sync.STATE_FAILED,
                current_accounts=snapshot.current_accounts,
                current_tags=snapshot.current_tags,
                observed_tags=snapshot.observed_tags,
                retry_required=True,
                source=sync_source,
                last_attempt_at=store.utcnow(),
                last_success_at=snapshot.last_success_at,
                error=sync_retry["error"],
                revision=snapshot.revision + 1,
            )
        else:
            if synced.ticket is None:
                return store.Transition(store.MISSING, None)
            ticket = synced.ticket
            snapshot = synced.snapshot
    context_refreshed_this_attempt = False
    if kind == KIND_APPROVE and account_sync.staff_context_refresh_required(ticket):
        queued = await _queue_and_deliver_latest_staff_context(
            bot, mongo, ticket, snapshot
        )
        if not queued:
            return store.Transition(
                store.BLOCKED,
                ticket,
                "staff account context could not be queued; approval is blocked",
            )
        context_refreshed_this_attempt = True
    review = (
        _pending_fwa_identity_review(ticket)
        if kind == KIND_APPROVE
        and str(ticket.get("ticket_type") or "").lower() == "fwa"
        else None
    )
    review_acknowledged = False
    if review is not None:
        review_revision = max(0, int(review.get("account_revision") or 0))
        context_fresh = await _staff_context_is_fresh_for_review(
            bot, mongo, ticket, review
        )
        if review_revision == snapshot.revision or context_refreshed_this_attempt:
            return store.Transition(
                store.BLOCKED,
                ticket,
                (
                    FWA_IDENTITY_REVIEW_MESSAGE
                    if context_fresh
                    else FWA_IDENTITY_REFRESH_PENDING_MESSAGE
                ),
            )
        if not context_fresh:
            await _queue_and_deliver_latest_staff_context(
                bot, mongo, ticket, snapshot
            )
            return store.Transition(
                store.BLOCKED,
                ticket,
                FWA_IDENTITY_REFRESH_PENDING_MESSAGE,
            )
        review_acknowledged = True
    if kind == KIND_APPROVE and not snapshot.has_linked_accounts:
        reason = (
            "linked-account lookup failed; approval is blocked until it succeeds"
            if snapshot.state == account_sync.STATE_FAILED
            else "approval requires at least one linked Clash account"
        )
        return store.Transition(store.BLOCKED, ticket, reason)
    if kind == KIND_APPROVE and account_sync.flag_identity_refresh_required(ticket):
        return store.Transition(
            store.BLOCKED,
            ticket,
            "linked-account flag identities are still refreshing; approval is blocked",
        )
    target = "approved" if kind == KIND_APPROVE else "denied"
    extra = {}
    if review_acknowledged:
        extra.update({
            "linked_accounts.approval_review.state": "acknowledged",
            "linked_accounts.approval_review.acknowledged_at": store.utcnow(),
            "linked_accounts.approval_review.acknowledged_by": member.id,
        })
    if kind != KIND_APPROVE:
        extra["denial_type"] = DENIAL_TYPE[kind]
        if reason:
            extra["denial_reason"] = reason
    transition_kwargs = {
        "to_status": target,
        "actor_id": member.id,
        "actor_name": actor_name,
        "expect": expected_status,
        "expected_rev": (
            max(0, int(ticket.get("rev") or 0))
            if kind == KIND_APPROVE and expected_rev is None and override is None
            else expected_rev
        ),
        "extra": extra,
        "overrides": override,
        "effect_kind": kind,
        "prior_effect_marker": prior_effect_marker,
        "prior_effects_legacy_baseline": prior_effects_legacy_baseline,
        "linked_account_snapshot": {
            "state": snapshot.state,
            "revision": snapshot.revision,
            "current_tags": snapshot.current_tags,
            "retry_required": snapshot.retry_required,
        },
        "linked_account_retry": sync_retry,
        "expected_linked_account_revision": account_sync.snapshot_from_ticket(
            ticket
        ).revision,
        "previous_notification_message_id": previous_notification_message_id,
    }
    if kind == KIND_APPROVE:
        try:
            async with flag_store.identity_guard(
                mongo,
                discord_ids=ticket.get("user_id"),
                player_tags=ticket.get("player_tags") or (),
            ):
                blocker = await flag_store.active_blacklist(
                    mongo,
                    user_id=ticket.get("user_id"),
                    player_tags=ticket.get("player_tags") or (),
                )
                if blocker is not None:
                    return store.Transition(
                        store.BLOCKED,
                        ticket,
                        "applicant is blacklisted",
                        blocker=blocker,
                    )
                # The lookup and blacklist check can take long enough for a
                # recruiter role change to arrive.  Authorization is required
                # at the write boundary, not only when the action began.
                if not await perms.is_recruiter(member, mongo):
                    return store.Transition(
                        store.UNAUTHORIZED, None, "recruiter permission required"
                    )
                result = await store.transition(mongo, ticket_id, **transition_kwargs)
        except flag_store.IdentityLockBusy as exc:
            return store.Transition(store.BLOCKED, ticket, str(exc))
    else:
        if not await perms.is_recruiter(member, mongo):
            return store.Transition(
                store.UNAUTHORIZED, None, "recruiter permission required"
            )
        result = await store.transition(mongo, ticket_id, **transition_kwargs)
    if not result.won:
        return result
    # The decision itself is already committed at this point. Everything
    # process_resolution_effects still has to do -- the candidate-thread
    # scan, the decision card, staff-context delivery, the hub refresh --
    # can take seconds to tens of seconds, and none of it needs to finish
    # before the clicker sees a result: it is idempotent and reconciled on
    # its own by reconcile_pending_resolution_effects on startup, so a
    # crash mid-task loses nothing. Only failing to even schedule it should
    # still surface as EFFECT_FAILED.
    try:
        _schedule_resolution_effects(bot, mongo, result.doc)
    except Exception as exc:
        _log.exception(
            "failed to schedule resolution effects ticket=%s", ticket_id,
        )
        return store.Transition(
            store.EFFECT_FAILED,
            result.doc,
            f"{type(exc).__name__}: resolution effects could not be scheduled",
        )
    return result


async def approve_ticket(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        ticket_id,
        member: hikari.Member,
        actor_name: str,
        expected_status: str = "open",
        expected_rev: int | None = None,
        override: dict | None = None,
        prior_effect_marker: str | None = None,
        prior_effects_legacy_baseline: bool = False,
        coc_client: coc.Client | None = None,
) -> store.Transition:
    return await _resolve_ticket(
        bot, mongo, ticket_id=ticket_id, member=member, actor_name=actor_name,
        kind=KIND_APPROVE, expected_status=expected_status,
        expected_rev=expected_rev, override=override,
        prior_effect_marker=prior_effect_marker,
        prior_effects_legacy_baseline=prior_effects_legacy_baseline,
        coc_client=coc_client,
    )


async def deny_ticket(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        ticket_id,
        member: hikari.Member,
        actor_name: str,
        kind: str,
        reason: str | None = None,
        expected_status: str = "open",
        expected_rev: int | None = None,
        override: dict | None = None,
        prior_effect_marker: str | None = None,
        prior_effects_legacy_baseline: bool = False,
        coc_client: coc.Client | None = None,
) -> store.Transition:
    if kind not in DENIAL_TYPE:
        raise ValueError("kind must be deny_fwa, deny_main, or deny_custom")
    return await _resolve_ticket(
        bot, mongo, ticket_id=ticket_id, member=member, actor_name=actor_name,
        kind=kind, reason=reason, expected_status=expected_status,
        expected_rev=expected_rev, override=override,
        prior_effect_marker=prior_effect_marker,
        prior_effects_legacy_baseline=prior_effects_legacy_baseline,
        coc_client=coc_client,
    )


# --- overturning a decided ticket from the console ---------------------------

OVERTURN_NOT_DECIDED_MESSAGE = "This ticket has not been decided yet."


async def _remove_granted_roles(bot: hikari.GatewayBot, ticket: Mapping) -> None:
    """Undo whatever roles the earlier approval granted, if any were recorded.

    Nothing in this pipeline grants roles yet, so `granted_role_ids` is
    normally absent and this is a no-op. It exists so that whenever approval
    does start granting a role, it only has to record the id here to make
    deny-after-approve overturn-safe automatically.
    """
    role_ids = [
        int(value) for value in (ticket.get("granted_role_ids") or ()) if int(value or 0)
    ]
    if not role_ids:
        return
    guild_id = int(ticket.get("guild_id") or 0)
    user_id = int(ticket.get("user_id") or 0)
    if not guild_id or not user_id:
        return
    for role_id in role_ids:
        try:
            await bot.rest.remove_role_from_member(
                guild_id, user_id, role_id,
                reason="Approval overturned to a denial",
            )
        except Exception:
            _log.exception(
                "overturn role removal failed ticket=%s role=%s",
                ticket.get("_id"), role_id,
            )


async def overturn_ticket(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        ticket_id,
        member: hikari.Member,
        actor_name: str,
        to_status: str,
        reason: str | None = None,
        coc_client: coc.Client | None = None,
) -> store.Transition:
    """Flip a decided ticket the other way. Any recruiter may do this.

    Reuses the normal approve/deny path with the same override CAS the
    legacy race-loss flow uses, so the candidate thread gets a fresh decision
    card (unarchived first if Discord had auto-archived it, then posted --
    never re-archived) and approve-after-deny still runs the usual approval
    checks (blacklist, linked accounts). Deny-after-approve additionally
    removes whatever roles the earlier approval granted.
    """
    if to_status not in schema.TERMINAL_STATUSES:
        raise ValueError("to_status must be approved or denied")
    if not await perms.is_recruiter(member, mongo):
        return store.Transition(store.UNAUTHORIZED, None, "recruiter permission required")
    current = await store.find_one(mongo, {"_id": ticket_id, **store.RUNTIME_FILTER})
    if current is None:
        return store.Transition(store.MISSING, None)
    if current.get("status") not in schema.TERMINAL_STATUSES:
        return store.Transition(store.LOST, current, OVERTURN_NOT_DECIDED_MESSAGE)
    if current.get("status") == to_status:
        return store.Transition(store.LOST, current, f"already {to_status}")

    effects = current.get("resolution_effects") or {}
    prior_effect_marker = str(effects.get("marker") or "")
    prior_effects_legacy_baseline = (
        not prior_effect_marker and store.is_markerless_legacy_terminal(current)
    )
    if not prior_effect_marker and not prior_effects_legacy_baseline:
        return store.Transition(store.BLOCKED, current, OVERRIDE_EFFECT_PENDING_MESSAGE)
    if not prior_effects_legacy_baseline and effects.get("complete") is not True:
        return store.Transition(store.BLOCKED, current, OVERRIDE_EFFECT_PENDING_MESSAGE)

    prior = _prior(current)
    # No expected_rev snapshot here: the ticket is re-fetched inside
    # store.transition() right before the CAS, after the account-sync
    # network round-trip, so a snapshot taken now would be stale. The
    # status filter (expected_status/override["status"]) is the only guard;
    # store.transition() reads the current revision itself.
    common = dict(
        ticket_id=ticket_id,
        member=member,
        actor_name=actor_name,
        expected_status=current.get("status"),
        override={
            "status": current.get("status"),
            "by": prior["by"],
            "by_name": None,
            "at": prior["at"],
        },
        prior_effect_marker=prior_effect_marker,
        prior_effects_legacy_baseline=prior_effects_legacy_baseline,
        coc_client=coc_client,
    )
    if to_status == "approved":
        return await approve_ticket(bot, mongo, **common)

    reason = str(reason or "").strip()
    if not 5 <= len(reason) <= 1000:
        return store.Transition(
            store.BLOCKED, current, "custom denial reason must be 5-1000 characters"
        )
    result = await deny_ticket(bot, mongo, kind=KIND_DENY_CUSTOM, reason=reason, **common)
    if result.won:
        await _remove_granted_roles(bot, current)
    return result


# --- losing the race ---------------------------------------------------------

def _prior(current: dict) -> dict:
    """Who resolved it first, and when, from whichever pair of fields was written."""
    if current.get("status") == "approved":
        return {"verb": "approved", "by": current.get("approved_by"), "at": current.get("approved_at")}
    return {"verb": "denied", "by": current.get("denied_by"), "at": current.get("denied_at")}


