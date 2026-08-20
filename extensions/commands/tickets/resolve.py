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
import asyncio
import logging
import uuid
from datetime import timedelta
from utils.component_state import delete_state, get_state, insert_state

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.commands.tickets import flag_store, loader, perms, store, thread_service
from extensions.components import register_action
from utils.constants import RED_ACCENT
from utils.mongo import MongoClient

DENIED_THUMB = "https://res.cloudinary.com/dxmtzuomk/image/upload/v1753271403/misc_images/Denied.png"
_log = logging.getLogger(__name__)

RESOLUTION_EFFECT_LEASE = timedelta(minutes=10)
RESOLUTION_EFFECT_RETRY_MESSAGE = (
    "The decision is recorded and will not be lost. Remaining Discord and console "
    "updates are retrying automatically. Ask an admin to inspect only if this persists."
)
OVERRIDE_EFFECT_PENDING_MESSAGE = (
    "The earlier decision is still finishing its applicant and archive updates. "
    "Nothing was changed. Try this override again in a moment."
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

_LABEL = {
    KIND_APPROVE: "Overturn and approve",
    KIND_DENY_FWA: "Overturn and deny",
    KIND_DENY_MAIN: "Overturn and deny",
    KIND_DENY_CUSTOM: "Overturn and deny",
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

async def apply_denial(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        kind: str,
        ticket: dict,
        reason: str | None = None,
        marker: str | None = None,
) -> None:
    """Message the applicant in the candidate thread. WON transitions only."""
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
                *([Text(content=f"-# {marker}")] if marker else []),
            ],
        )
    ]
    await bot.rest.create_message(
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
) -> None:
    """Congratulate the applicant. Thread tickets are never renamed."""
    channel_id, user_id = _thread_identity(ticket)
    await bot.rest.create_message(
        channel=channel_id,
        content=(
            f"<@{user_id}> Congratulations on being accepted to Warriors United! "
            f"Stand by for further instructions."
            + (f"\n-# {marker}" if marker else "")
        ),
        mentions_everyone=False,
        user_mentions=[int(user_id)],
        role_mentions=False,
    )


async def run_side_effects(
        bot, mongo, *, kind: str, ticket: dict,
        reason=None, marker: str | None = None,
):
    if kind == KIND_APPROVE:
        await apply_approval(
            bot, mongo, ticket=ticket, marker=marker,
        )
    else:
        await apply_denial(
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
) -> bool:
    # This path runs only when the durable delivered checkpoint is absent. Walk
    # the full thread so a crash followed by heavy activity cannot push the
    # marker beyond a fixed recent-message window and cause a duplicate notice.
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
    return False


async def _checkpoint_effect(
        mongo: MongoClient,
        ticket_id,
        marker: str,
        *,
        step: str,
        state: str,
        error: Exception | None = None,
) -> bool:
    """Best-effort durable checkpoint; physical effects remain authoritative."""
    now = store.utcnow()
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
                    f"resolution_effects.{step}": {
                        "state": state,
                        "at": now,
                        "error_type": type(error).__name__ if error else None,
                    },
                    "resolution_effects.updated_at": now,
                    "updated_at": now,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": {
                    "event": f"resolution_{step}_{state}",
                    "at": now,
                    "effect_marker": marker,
                    "error_type": type(error).__name__ if error else None,
                }},
            },
        )
        return bool(getattr(result, "matched_count", 0))
    except Exception:
        _log.exception("resolution checkpoint failed ticket=%s step=%s", ticket_id, step)
        return False


async def _finalize_effects(mongo: MongoClient, ticket_id, marker: str) -> bool:
    now = store.utcnow()
    try:
        result = await store.update_one(
            mongo,
            {"_id": ticket_id, **store.RUNTIME_FILTER, "resolution_effects.marker": marker},
            {
                "$set": {
                    "resolution_effects.notification": {"state": "delivered", "at": now},
                    "resolution_effects.archive": {"state": "archived", "at": now},
                    "resolution_effects.hub": {"state": "requested", "at": now},
                    "resolution_effects.complete": True,
                    "resolution_effects.completed_at": now,
                    "resolution_effects.updated_at": now,
                    "updated_at": now,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": {
                    "event": "resolution_effects_complete",
                    "at": now,
                    "effect_marker": marker,
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


async def _acquire_resolution_effect_lease(
        mongo: MongoClient,
        ticket_id,
        marker: str,
        owner: str,
) -> dict | None:
    now = store.utcnow()
    primary, _secondary = await store._both(mongo)
    return await primary.find_one_and_update(
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


async def _archive_terminal_pair_after_cancellation(
    rest: hikari.api.RESTClient,
    ticket: dict,
) -> None:
    """Best-effort physical convergence while cancellation is propagating."""
    try:
        await thread_service.archive_ticket_pair(rest, ticket)
    except Exception:
        _log.exception(
            "resolution cancellation archive failed ticket=%s", ticket.get("_id")
        )


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
    notification_write_needed = False

    try:
        delivered = (effects.get("notification") or {}).get("state") == "delivered"
        if not delivered:
            me = bot.get_me()
            if me is None:
                raise RuntimeError("bot identity is unavailable")
            if not await _notification_exists(
                bot.rest,
                location_id,
                marker,
                bot_user_id=int(me.id),
            ):
                notification_write_needed = True
                await _ensure_notification_thread_writable(bot.rest, ticket)
                await run_side_effects(
                    bot,
                    mongo,
                    kind=kind,
                    ticket=ticket,
                    reason=ticket.get("denial_reason"),
                    marker=marker,
                )
            await _checkpoint_effect(
                mongo, ticket["_id"], marker, step="notification", state="delivered"
            )
    except Exception as exc:
        await _checkpoint_effect(
            mongo, ticket["_id"], marker, step="notification", state="failed", error=exc
        )
        pending.append(("applicant notification", exc))

    try:
        # Reconcile physical state on every attempt. A notification retry may
        # have temporarily reopened the candidate after an earlier archive
        # checkpoint, and terminal threads must never be left active.
        await thread_service.archive_ticket_pair(bot.rest, ticket)
        if (
            (effects.get("archive") or {}).get("state") != "archived"
            or notification_write_needed
        ):
            await _checkpoint_effect(
                mongo, ticket["_id"], marker, step="archive", state="archived"
            )
    except Exception as exc:
        await _checkpoint_effect(
            mongo, ticket["_id"], marker, step="archive", state="failed", error=exc
        )
        pending.append(("thread archive", exc))

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
    """Reconcile notify -> archive -> hub without duplicating notifications."""
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
        try:
            return await _process_resolution_effects_owned(bot, mongo, leased)
        except asyncio.CancelledError:
            await _archive_terminal_pair_after_cancellation(bot.rest, leased)
            raise
    finally:
        await _release_resolution_effect_lease(
            mongo, ticket["_id"], marker, owner
        )


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


async def _resolution_reconciler(bot: hikari.GatewayBot, mongo: MongoClient) -> None:
    while True:
        try:
            counts = await reconcile_pending_resolution_effects(bot, mongo)
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
) -> store.Transition:
    """Authorize, enforce flags, CAS status, then run effects exactly once."""
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
    target = "approved" if kind == KIND_APPROVE else "denied"
    extra = {}
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
            if kind == KIND_APPROVE and expected_rev is None
            else expected_rev
        ),
        "extra": extra,
        "overrides": override,
        "effect_kind": kind,
        "prior_effect_marker": prior_effect_marker,
        "prior_effects_legacy_baseline": prior_effects_legacy_baseline,
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
                result = await store.transition(mongo, ticket_id, **transition_kwargs)
        except flag_store.IdentityLockBusy as exc:
            return store.Transition(store.BLOCKED, ticket, str(exc))
    else:
        result = await store.transition(mongo, ticket_id, **transition_kwargs)
    if not result.won:
        return result
    return await process_resolution_effects(bot, mongo, result.doc)


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
) -> store.Transition:
    return await _resolve_ticket(
        bot, mongo, ticket_id=ticket_id, member=member, actor_name=actor_name,
        kind=KIND_APPROVE, expected_status=expected_status,
        expected_rev=expected_rev, override=override,
        prior_effect_marker=prior_effect_marker,
        prior_effects_legacy_baseline=prior_effects_legacy_baseline,
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
) -> store.Transition:
    if kind not in DENIAL_TYPE:
        raise ValueError("kind must be deny_fwa, deny_main, or deny_custom")
    return await _resolve_ticket(
        bot, mongo, ticket_id=ticket_id, member=member, actor_name=actor_name,
        kind=kind, reason=reason, expected_status=expected_status,
        expected_rev=expected_rev, override=override,
        prior_effect_marker=prior_effect_marker,
        prior_effects_legacy_baseline=prior_effects_legacy_baseline,
    )


# --- losing the race ---------------------------------------------------------

def _prior(current: dict) -> dict:
    """Who resolved it first, and when, from whichever pair of fields was written."""
    if current.get("status") == "approved":
        return {"verb": "approved", "by": current.get("approved_by"), "at": current.get("approved_at")}
    return {"verb": "denied", "by": current.get("denied_by"), "at": current.get("denied_at")}


def _override_rows(kind: str, action_id: str) -> list:
    return [ActionRow(components=[Button(
        style=(
            hikari.ButtonStyle.SUCCESS
            if kind == KIND_APPROVE
            else hikari.ButtonStyle.DANGER
        ),
        custom_id=f"ticket_override:{action_id}",
        label=_LABEL[kind],
    )])]


def lost_message(kind: str, current: dict, action_id: str | None) -> tuple[str, list]:
    """(content, components) for the panel a recruiter sees when someone got there first.

    Deliberately NOT a Components V2 container. The ephemeral this replaces is
    plain content plus an ActionRow, and IS_COMPONENTS_V2 is a one-way latch:
    once set on a message, `content` is rejected with a 400 forever after. This
    panel gets edited with text when the override completes, so it must stay
    non-V2. (ActionRow alone does not trip the flag - hikari excludes it.)

    `action_id is None` means the viewer may not override, so no button is shown
    and the copy does not dangle an option they cannot take.
    """
    prior = _prior(current)
    who = f"<@{prior['by']}>" if prior["by"] else "Someone"
    when = ts(prior["at"])
    noun = "approval" if prior["verb"] == "approved" else "denial"

    if action_id is None:
        return (
            f"### {who} already {prior['verb']} this one\n"
            f"That was {when}, so I've left it as it stands. A recruiter can revisit it "
            f"if it needs another look.",
            [],
        )

    if kind == KIND_APPROVE:
        content = (
            f"### {who} {prior['verb']} this one already\n"
            f"That was {when}, so I've not touched anything — the applicant still has the "
            f"{noun}, and the channel still shows it.\n\n"
            f"Approving now overturns that. Normal enough if there's been an appeal or a "
            f"leader's called it differently; it'll go on the record as yours."
        )
    else:
        content = (
            f"### {who} already {prior['verb']} this one\n"
            f"That was {when}. I've left everything as it was — the applicant hasn't been "
            f"messaged again, and the channel still shows their call.\n\n"
            f"If this needs overturning, that's yours to make. Mistaken deny, an appeal, a "
            f"leader stepping in — go ahead and it'll be recorded as your decision."
        )
    return content, _override_rows(kind, action_id)


async def offer_override(
        ctx,
        mongo: MongoClient,
        *,
        kind: str,
        current: dict,
        ticket_id,
        channel_id,
        user_id,
        reason: str | None = None,
) -> tuple[str, list]:
    """Stash what an override would need, and build the panel offering it.

    Returns (content, components); the caller delivers them, because the deny
    handlers respond through edit_initial_response and approve responds directly.
    """
    if not await perms.is_recruiter(ctx.member, mongo):
        return lost_message(kind, current, None)
    target = "approved" if kind == KIND_APPROVE else "denied"
    if current.get("status") == target:
        return lost_message(kind, current, None)

    prior_effect_marker = str(
        ((current.get("resolution_effects") or {}).get("marker") or "")
    )
    prior_effects_legacy_baseline = (
        not prior_effect_marker
        and store.is_markerless_legacy_terminal(current)
    )
    if not prior_effect_marker and not prior_effects_legacy_baseline:
        return OVERRIDE_EFFECT_PENDING_MESSAGE, []

    prior = _prior(current)
    action_id = str(ctx.interaction.id)
    await insert_state(mongo, {
        "_id": action_id,
        "type": "ticket_override",
        "kind": kind,
        "ticket_id": ticket_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "reason": reason,
        "prior_status": current.get("status"),
        "prior_rev": int(current.get("rev") or 0),
        "prior_effect_marker": prior_effect_marker,
        "prior_effects_legacy_baseline": prior_effects_legacy_baseline,
        "prior_by": prior["by"],
        "prior_at": prior["at"],
        "owner_id": int(ctx.user.id),
    })
    return lost_message(kind, current, action_id)


@register_action("ticket_override", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def ticket_override_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
):
    """Overturn a resolution someone else already made.

    Re-checks the recruiter role at click time. The dispatcher enforces nothing -
    `user_only` is stored and never read - so a button cannot inherit trust from
    the interaction that rendered it, even an ephemeral one.
    """
    data = await get_state(mongo, action_id)
    if not data:
        await ctx.interaction.edit_initial_response(
            content="That override has expired. Run the command again.", components=[]
        )
        return

    if int(data.get("owner_id") or 0) != int(ctx.user.id):
        await ctx.respond("This override belongs to another recruiter.", ephemeral=True)
        return

    if not await perms.is_recruiter(ctx.member, mongo):
        await ctx.interaction.edit_initial_response(
            content="Only recruiters can overturn a resolution.", components=[]
        )
        return

    kind = data["kind"]
    prior_status = str(data.get("prior_status") or "")
    prior_effect_marker = str(data.get("prior_effect_marker") or "")
    prior_effects_legacy_baseline = bool(
        data.get("prior_effects_legacy_baseline")
    )
    prior_rev = max(0, int(data.get("prior_rev") or 0))
    current = await store.find_one(
        mongo,
        {"_id": data.get("ticket_id"), **store.RUNTIME_FILTER},
    )
    if current is None:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=f"The ticket record `{data.get('ticket_id')}` has gone. Nothing was changed.",
            components=[],
        )
        return
    effects = current.get("resolution_effects") or {}
    current_rev = max(0, int(current.get("rev") or 0))
    exact_legacy_baseline = bool(
        prior_effects_legacy_baseline
        and store.is_markerless_legacy_terminal(current)
    )
    if (
        current.get("status") != prior_status
        or current_rev < prior_rev
        or (
            not exact_legacy_baseline
            and (
                not prior_effect_marker
                or str(effects.get("marker") or "") != prior_effect_marker
            )
        )
    ):
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content="The ticket changed again before your override landed. Nothing was changed.",
            components=[],
        )
        return
    if not exact_legacy_baseline and effects.get("complete") is not True:
        await ctx.interaction.edit_initial_response(
            content=OVERRIDE_EFFECT_PENDING_MESSAGE,
            components=_override_rows(kind, action_id),
        )
        return

    override = {
        "status": prior_status,
        "rev": current_rev,
        "by": data.get("prior_by"),
        "by_name": None,
        "at": data.get("prior_at"),
    }
    action = approve_ticket if kind == KIND_APPROVE else deny_ticket
    action_kwargs = {
        "ticket_id": data["ticket_id"],
        "member": ctx.member,
        "actor_name": ctx.user.username,
        "expected_status": prior_status,
        "expected_rev": current_rev,
        "override": override,
        "prior_effect_marker": prior_effect_marker,
        "prior_effects_legacy_baseline": exact_legacy_baseline,
    }
    if kind != KIND_APPROVE:
        action_kwargs.update({"kind": kind, "reason": data.get("reason")})
    result = await action(bot, mongo, **action_kwargs)

    if result.outcome == store.MISSING:
        await ctx.interaction.edit_initial_response(
            content=f"The ticket record `{data['ticket_id']}` has gone. Nothing was changed.",
            components=[],
        )
        return
    if result.outcome == store.LOST:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content="The ticket changed again before your override landed. Nothing was changed.",
            components=[],
        )
        return
    if result.outcome in {store.UNAUTHORIZED, store.BLOCKED}:
        await delete_state(mongo, action_id)
        message = (
            "Approval blocked: this applicant is blacklisted."
            if result.blocker else result.reason or "This action is not allowed."
        )
        await ctx.interaction.edit_initial_response(content=message, components=[])
        return
    if result.outcome == store.EFFECT_FAILED:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=RESOLUTION_EFFECT_RETRY_MESSAGE,
            components=[],
        )
        return
    await delete_state(mongo, action_id)

    verb = "Approved" if kind == KIND_APPROVE else "Denied"
    who = f"<@{data['prior_by']}>" if data.get("prior_by") else "the previous decision"
    await ctx.interaction.edit_initial_response(
        content=(
            f"{verb}. That overturns {who}'s call from {ts(data.get('prior_at'))}, "
            f"recorded against your name."
        ),
        components=[],
    )
