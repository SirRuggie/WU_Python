"""Durable, status-bound delivery of legacy ticket resolution effects."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
import uuid

import hikari
from pymongo import ReturnDocument

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.commands.tickets_legacy import store
from utils.mongo import MongoClient


DELIVERY_LEASE = timedelta(minutes=5)
RETRY_BACKOFF = timedelta(seconds=5)
BACKGROUND_RETRY_DELAYS_SECONDS = (5, 15, 30, 60, 300)
RECOVERY_LIMIT = 25
ONLINE_SCAN_INTERVAL_SECONDS = 5
PENDING_STATES = ("pending", "retry", "processing")
_retry_tasks: dict[str, asyncio.Task] = {}
_retry_stopping = False
_online_recovery_task: asyncio.Task | None = None
_online_recovery_stopping = True


class ResolutionLeaseLost(RuntimeError):
    """The worker no longer owns the exact decision effect."""


class ResolutionPostUncertain(RuntimeError):
    """Discord may have accepted a POST whose response was lost."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _effect(ticket: dict) -> dict:
    effect = ticket.get("resolution_delivery")
    if not isinstance(effect, dict) or not effect.get("effect_id"):
        raise RuntimeError("legacy resolution delivery marker is invalid")
    if effect.get("decision_status") not in store.TERMINAL_STATUSES:
        raise RuntimeError("legacy resolution delivery decision is invalid")
    if not isinstance(effect.get("plan"), dict):
        raise RuntimeError("legacy resolution delivery plan is invalid")
    return effect


def _plan(ticket: dict) -> dict:
    effect = _effect(ticket)
    plan = dict(effect["plan"])
    kind = str(plan.get("kind") or "")
    if kind not in {"approve", "deny_fwa", "deny_main", "deny_custom"}:
        raise RuntimeError("legacy resolution delivery kind is invalid")
    user_id = int(plan.get("user_id") or ticket.get("user_id") or 0)
    if user_id <= 0:
        raise RuntimeError("legacy resolution delivery applicant is invalid")
    plan["user_id"] = user_id
    if kind == "approve":
        if not isinstance(plan.get("notice_content"), str):
            plan["notice_content"] = (
                f"<@{user_id}> Congratulations on being accepted to Warriors United! "
                "Stand by for further instructions."
            )
        plan.setdefault("rename_emoji", "✅")
    else:
        if not isinstance(plan.get("notice_text"), str):
            raise RuntimeError("legacy denial delivery text is missing")
        plan.setdefault("rename_emoji", "❌")
    plan.setdefault("actor_name", str(effect.get("actor_name") or "Unknown"))
    return plan


def denial_components(plan: dict) -> list:
    return [Container(
        accent_color=int(plan["accent_color"]),
        components=[
            Section(
                components=[Text(content=plan["notice_text"])],
                accessory=Thumbnail(media=plan["denied_thumb"]),
            ),
            Media(items=[MediaItem(media=plan["footer_media"])]),
        ],
    )]


def _component_signature(components) -> tuple:
    def scalar(value):
        if value is hikari.UNDEFINED:
            return None
        if value is None or isinstance(value, (str, int, bool, float)):
            return value
        url = getattr(value, "url", None)
        return str(url if url is not None else value)

    def media_scalar(value):
        raw = scalar(value)
        if raw is None:
            return None
        text = str(raw)
        parsed = urlparse(text)
        basename = PurePosixPath(unquote(parsed.path or text)).name
        if not parsed.scheme or parsed.hostname in {
            "cdn.discordapp.com",
            "media.discordapp.net",
        }:
            return ("attachment", basename)
        return ("url", parsed._replace(query="", fragment="").geturl())

    def one(component) -> tuple:
        spoiler = getattr(component, "is_spoiler", hikari.UNDEFINED)
        if spoiler is hikari.UNDEFINED:
            spoiler = getattr(component, "spoiler", False)
        if spoiler is hikari.UNDEFINED:
            spoiler = False
        accessory = getattr(component, "accessory", None)
        return (
            scalar(getattr(component, "type", None)),
            str(getattr(component, "content", "") or ""),
            scalar(getattr(component, "accent_color", None)),
            bool(spoiler),
            media_scalar(getattr(component, "media", None)),
            scalar(getattr(component, "description", None)),
            one(accessory) if accessory is not None else None,
            tuple(one(child) for child in (getattr(component, "components", ()) or ())),
            tuple(one(item) for item in (getattr(component, "items", ()) or ())),
        )

    return tuple(one(component) for component in (components or ()))


async def _message_history(rest, channel_id: int) -> list:
    iterator = rest.fetch_messages(channel_id)
    collect = getattr(iterator, "collect", None)
    if callable(collect):
        return list(await collect(list))
    to_list = getattr(iterator, "to_list", None)
    if callable(to_list):
        return list(await to_list())
    return list(await iterator)


def _message_id(message) -> int:
    try:
        return int(getattr(message, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def _notice_exists(
    bot,
    ticket: dict,
    plan: dict,
    *,
    after_message_id: int | None = None,
) -> bool:
    me = bot.get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable for resolution inspection")
    if after_message_id is None:
        after_message_id = int(
            _effect(ticket).get("notice_history_after_id") or 0
        )
    expected_components = (
        _component_signature(denial_components(plan))
        if plan["kind"] != "approve"
        else None
    )
    for message in await _message_history(bot.rest, int(ticket["channel_id"])):
        if _message_id(message) <= int(after_message_id):
            continue
        if int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        if plan["kind"] == "approve":
            if str(getattr(message, "content", "") or "") == plan["notice_content"]:
                return True
        elif _component_signature(
            tuple(getattr(message, "components", ()) or ())
        ) == expected_components:
            return True
    return False


async def ensure_notice_history_boundary(
    bot,
    mongo: MongoClient,
    ticket: dict,
    owner: str,
) -> dict:
    """Freeze the channel high-water before this effect can post its notice."""
    effect = _effect(ticket)
    if "notice_history_after_id" in effect:
        return ticket

    ticket = await assert_lease(mongo, ticket, owner)
    messages = await _message_history(bot.rest, int(ticket["channel_id"]))
    boundary = max((_message_id(message) for message in messages), default=0)
    ticket = await assert_lease(mongo, ticket, owner)
    moment = utcnow()
    updated = await mongo.button_store.find_one_and_update(
        store._legacy_filter({
            "_id": ticket["_id"],
            "status": effect["decision_status"],
            "resolution_delivery.effect_id": effect["effect_id"],
            "resolution_delivery.state": "processing",
            "resolution_delivery.lease_owner": str(owner),
            "resolution_delivery.lease_until": {"$gt": moment},
            "resolution_delivery.notice_history_after_id": {"$exists": False},
        }),
        {"$set": {
            "resolution_delivery.notice_history_after_id": boundary,
            "resolution_delivery.updated_at": moment,
            "resolution_delivery.lease_until": moment + DELIVERY_LEASE,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ResolutionLeaseLost(
            "legacy resolution notice boundary lost its lease"
        )
    return updated


def _claimable_clause(now: datetime) -> dict:
    return {
        "$or": [
            {"resolution_delivery.state": "pending"},
            {
                "$and": [
                    {"resolution_delivery.state": "retry"},
                    {"$or": [
                        {"resolution_delivery.retry_after": {"$lte": now}},
                        {"resolution_delivery.retry_after": {"$exists": False}},
                    ]},
                ],
            },
            {
                "resolution_delivery.state": "processing",
                "resolution_delivery.lease_until": {"$lte": now},
            },
        ],
    }


def _recoverable_query(now: datetime) -> dict:
    return store._legacy_filter(_claimable_clause(now))


async def claim_delivery(
    mongo: MongoClient,
    ticket: dict,
    *,
    now: datetime | None = None,
) -> dict | None:
    moment = now or utcnow()
    effect = _effect(ticket)
    owner = uuid.uuid4().hex
    return await mongo.button_store.find_one_and_update(
        store._legacy_filter({"$and": [
            {
                "_id": ticket["_id"],
                "status": effect["decision_status"],
                "resolution_delivery.effect_id": effect["effect_id"],
            },
            _claimable_clause(moment),
        ]}),
        {
            "$set": {
                "resolution_delivery.state": "processing",
                "resolution_delivery.lease_owner": owner,
                "resolution_delivery.lease_until": moment + DELIVERY_LEASE,
                "resolution_delivery.updated_at": moment,
            },
            "$unset": {
                "resolution_delivery.last_error": "",
                "resolution_delivery.retry_after": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )


async def assert_lease(
    mongo: MongoClient,
    ticket: dict,
    owner: str,
    *,
    now: datetime | None = None,
) -> dict:
    moment = now or utcnow()
    effect = _effect(ticket)
    updated = await mongo.button_store.find_one_and_update(
        store._legacy_filter({
            "_id": ticket["_id"],
            "status": effect["decision_status"],
            "resolution_delivery.effect_id": effect["effect_id"],
            "resolution_delivery.state": "processing",
            "resolution_delivery.lease_owner": str(owner),
            "resolution_delivery.lease_until": {"$gt": moment},
        }),
        {"$set": {
            "resolution_delivery.lease_until": moment + DELIVERY_LEASE,
            "resolution_delivery.updated_at": moment,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ResolutionLeaseLost("legacy resolution delivery lease was lost")
    return updated


async def mark_step(
    mongo: MongoClient,
    ticket: dict,
    owner: str,
    step: str,
) -> dict:
    now = utcnow()
    effect = _effect(ticket)
    updated = await mongo.button_store.find_one_and_update(
        store._legacy_filter({
            "_id": ticket["_id"],
            "status": effect["decision_status"],
            "resolution_delivery.effect_id": effect["effect_id"],
            "resolution_delivery.state": "processing",
            "resolution_delivery.lease_owner": str(owner),
            "resolution_delivery.lease_until": {"$gt": now},
        }),
        {"$set": {
            f"resolution_delivery.{step}": True,
            "resolution_delivery.updated_at": now,
            "resolution_delivery.lease_until": now + DELIVERY_LEASE,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ResolutionLeaseLost("legacy resolution checkpoint lost its lease")
    return updated


async def release_delivery(
    mongo: MongoClient,
    ticket: dict,
    owner: str,
    error: Exception,
) -> bool:
    now = utcnow()
    effect = _effect(ticket)
    result = await mongo.button_store.update_one(
        store._legacy_filter({
            "_id": ticket["_id"],
            "resolution_delivery.effect_id": effect["effect_id"],
            "resolution_delivery.state": "processing",
            "resolution_delivery.lease_owner": str(owner),
            "resolution_delivery.lease_until": {"$gt": now},
        }),
        {
            "$set": {
                "resolution_delivery.state": "retry",
                "resolution_delivery.last_error": str(error)[:500],
                "resolution_delivery.retry_after": now + RETRY_BACKOFF,
                "resolution_delivery.updated_at": now,
            },
            "$unset": {
                "resolution_delivery.lease_owner": "",
                "resolution_delivery.lease_until": "",
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def finish_delivery(mongo: MongoClient, ticket: dict, owner: str) -> bool:
    now = utcnow()
    effect = _effect(ticket)
    result = await mongo.button_store.update_one(
        store._legacy_filter({
            "_id": ticket["_id"],
            "status": effect["decision_status"],
            "resolution_delivery.effect_id": effect["effect_id"],
            "resolution_delivery.state": "processing",
            "resolution_delivery.lease_owner": str(owner),
            "resolution_delivery.lease_until": {"$gt": now},
        }),
        {
            "$set": {
                "resolution_delivery.state": "complete",
                "resolution_delivery.completed_at": now,
                "resolution_delivery.updated_at": now,
            },
            "$unset": {
                "resolution_delivery.lease_owner": "",
                "resolution_delivery.lease_until": "",
                "resolution_delivery.last_error": "",
                "resolution_delivery.retry_after": "",
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def _clear_monitor(mongo: MongoClient, channel_id: int) -> None:
    await mongo.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}},
    )


def _renamed(name: str, emoji: str) -> str:
    for current in ("🆕", "❌", "✅"):
        if name.startswith(current):
            return emoji + name[len(current):]
    return emoji + name


async def deliver_claimed(bot, mongo: MongoClient, ticket: dict) -> bool:
    effect = _effect(ticket)
    owner = str(effect.get("lease_owner") or "")
    if not owner:
        raise ResolutionLeaseLost("legacy resolution delivery has no owner")
    plan = _plan(ticket)
    channel_id = int(ticket["channel_id"])

    async def notice() -> None:
        nonlocal ticket
        if _effect(ticket).get("notice_sent"):
            return
        ticket = await ensure_notice_history_boundary(
            bot, mongo, ticket, owner
        )
        boundary = int(_effect(ticket)["notice_history_after_id"])
        ticket = await assert_lease(mongo, ticket, owner)
        if await _notice_exists(
            bot,
            ticket,
            plan,
            after_message_id=boundary,
        ):
            ticket = await mark_step(mongo, ticket, owner, "notice_sent")
            return
        ticket = await assert_lease(mongo, ticket, owner)
        try:
            if plan["kind"] == "approve":
                await bot.rest.create_message(
                    channel=channel_id,
                    content=plan["notice_content"],
                    user_mentions=[plan["user_id"]],
                )
            else:
                await bot.rest.create_message(
                    channel=channel_id,
                    components=denial_components(plan),
                    user_mentions=[plan["user_id"]],
                )
        except Exception as error:
            raise ResolutionPostUncertain(
                "legacy resolution applicant notice outcome is uncertain"
            ) from error
        ticket = await mark_step(mongo, ticket, owner, "notice_sent")

    async def clear_monitor() -> None:
        nonlocal ticket
        if _effect(ticket).get("monitor_cleared"):
            return
        ticket = await assert_lease(mongo, ticket, owner)
        await _clear_monitor(mongo, channel_id)
        ticket = await mark_step(mongo, ticket, owner, "monitor_cleared")

    async def rename() -> None:
        nonlocal ticket
        if _effect(ticket).get("rename_done"):
            return
        ticket = await assert_lease(mongo, ticket, owner)
        channel = await bot.rest.fetch_channel(channel_id)
        if int(getattr(channel, "guild_id", 0)) != int(ticket.get("guild_id") or 0):
            raise RuntimeError("legacy resolution channel guild does not match")
        emoji = str(plan["rename_emoji"])
        if str(getattr(channel, "name", "") or "").startswith(emoji):
            ticket = await mark_step(mongo, ticket, owner, "rename_done")
            return
        ticket = await assert_lease(mongo, ticket, owner)
        await bot.rest.edit_channel(
            channel_id,
            name=_renamed(str(channel.name), emoji),
            reason=f"Ticket resolved by {plan['actor_name']}",
        )
        ticket = await mark_step(mongo, ticket, owner, "rename_done")

    if plan["kind"] == "approve":
        await clear_monitor()
        await rename()
        if not _effect(ticket).get("notice_sent"):
            await asyncio.sleep(1)
        await notice()
    else:
        await notice()
        await clear_monitor()
        await rename()
    if not await finish_delivery(mongo, ticket, owner):
        raise ResolutionLeaseLost("legacy resolution completion lost its lease")
    return True


async def recover_pending_deliveries(
    *,
    bot,
    mongo: MongoClient,
    limit: int = RECOVERY_LIMIT,
    only_ticket_id: str | None = None,
) -> dict[str, int]:
    moment = utcnow()
    query = _recoverable_query(moment)
    if only_ticket_id is not None:
        query = {"$and": [query, {"_id": str(only_ticket_id)}]}
    rows = await mongo.button_store.find(query).sort([
        ("resolution_delivery.updated_at", 1),
        ("_id", 1),
    ]).limit(
        max(1, int(limit))
    ).to_list(length=max(1, int(limit)))
    completed = 0
    failed = 0
    for cursor_ticket in rows:
        claimed = None
        owner = ""
        try:
            effect = _effect(cursor_ticket)
            if cursor_ticket.get("status") != effect["decision_status"]:
                await mongo.button_store.update_one(
                    store._legacy_filter({
                        "_id": cursor_ticket["_id"],
                        "resolution_delivery.effect_id": effect["effect_id"],
                    }),
                    {"$set": {
                        "resolution_delivery.state": "cancelled",
                        "resolution_delivery.cancel_reason": "decision status changed",
                        "resolution_delivery.updated_at": utcnow(),
                    }},
                )
                continue
            claimed = await claim_delivery(mongo, cursor_ticket, now=utcnow())
            if claimed is None:
                continue
            owner = str(_effect(claimed).get("lease_owner") or "")
            await deliver_claimed(bot, mongo, claimed)
            completed += 1
        except Exception as error:
            if claimed is not None and owner:
                await release_delivery(mongo, claimed, owner, error)
            failed += 1
    pending = await mongo.button_store.count_documents(store._legacy_filter({
        "resolution_delivery.state": {"$in": list(PENDING_STATES)},
    }))
    return {
        "processed": len(rows),
        "completed": completed,
        "failed": failed,
        "pending": int(pending),
    }


async def ensure_and_deliver(bot, mongo: MongoClient, ticket: dict) -> bool:
    result = await recover_pending_deliveries(
        bot=bot,
        mongo=mongo,
        limit=1,
        only_ticket_id=str(ticket["_id"]),
    )
    current = await store.find_one(mongo, {"_id": ticket["_id"]})
    state = str(((current or {}).get("resolution_delivery") or {}).get("state") or "")
    return bool(result["completed"] and state == "complete")


async def _retry_worker(*, bot, mongo: MongoClient, ticket_id: str, effect_id: str) -> None:
    attempt = 0
    while True:
        try:
            ticket = await store.find_one(mongo, {"_id": ticket_id})
            if ticket is None:
                return
            effect = ticket.get("resolution_delivery") or {}
            if (
                effect.get("effect_id") != effect_id
                or effect.get("state") in {"complete", "cancelled"}
            ):
                return
            if await ensure_and_deliver(bot, mongo, ticket):
                return
            raise RuntimeError("legacy resolution delivery remains pending")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            attempt += 1
            delay = BACKGROUND_RETRY_DELAYS_SECONDS[
                min(attempt - 1, len(BACKGROUND_RETRY_DELAYS_SECONDS) - 1)
            ]
            if attempt <= len(BACKGROUND_RETRY_DELAYS_SECONDS):
                print(
                    "[Tickets:Legacy] resolution_delivery_retry "
                    f"ticket_id={ticket_id} attempt={attempt} "
                    f"error={type(error).__name__}"
                )
            await asyncio.sleep(delay)


def schedule_retry(*, bot, mongo: MongoClient, ticket: dict) -> asyncio.Task:
    if _retry_stopping:
        raise RuntimeError("legacy resolution retry scheduling is stopping")
    effect = _effect(ticket)
    key = f"{ticket['_id']}:{effect['effect_id']}"
    current = _retry_tasks.get(key)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(
        _retry_worker(
            bot=bot,
            mongo=mongo,
            ticket_id=str(ticket["_id"]),
            effect_id=str(effect["effect_id"]),
        ),
        name=f"legacy-resolution:{key}",
    )
    _retry_tasks[key] = task

    def discard(done: asyncio.Task) -> None:
        if _retry_tasks.get(key) is done:
            _retry_tasks.pop(key, None)
        if not done.cancelled() and done.exception() is not None:
            print(
                "[Tickets:Legacy] resolution_delivery_worker_failed "
                f"ticket_id={ticket['_id']}"
            )

    task.add_done_callback(discard)
    return task


async def drive_or_schedule(*, bot, mongo: MongoClient, ticket: dict) -> bool:
    try:
        if await ensure_and_deliver(bot, mongo, ticket):
            return True
    except Exception:
        pass
    try:
        schedule_retry(bot=bot, mongo=mongo, ticket=ticket)
    except RuntimeError:
        # The durable marker remains discoverable at the next startup while the
        # shutdown gate prevents a new worker from outliving bot dependencies.
        pass
    return False


async def _online_recovery_worker(*, bot, mongo: MongoClient) -> None:
    """Continuously discover markers committed after the startup scan exits."""

    while not _online_recovery_stopping:
        try:
            await recover_pending_deliveries(
                bot=bot,
                mongo=mongo,
                limit=RECOVERY_LIMIT,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(
                "[Tickets:Legacy] resolution_delivery_scan_failed "
                f"error={type(error).__name__}"
            )
        await asyncio.sleep(ONLINE_SCAN_INTERVAL_SECONDS)


def start_online_recovery(*, bot, mongo: MongoClient) -> asyncio.Task:
    """Start the singleton shutdown-fenced online marker discovery loop."""

    global _online_recovery_task, _online_recovery_stopping
    current = _online_recovery_task
    if current is not None and not current.done():
        return current
    _online_recovery_stopping = False
    _online_recovery_task = asyncio.create_task(
        _online_recovery_worker(bot=bot, mongo=mongo),
        name="legacy-resolution-online-recovery",
    )
    return _online_recovery_task


async def stop_online_recovery() -> None:
    """Prevent new scans and await the exact owned online worker."""

    global _online_recovery_task, _online_recovery_stopping
    _online_recovery_stopping = True
    task = _online_recovery_task
    _online_recovery_task = None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def stop_retries() -> None:
    global _retry_stopping
    _retry_stopping = True
    tasks = list(_retry_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _retry_tasks.clear()


async def start_retries() -> None:
    global _retry_stopping
    await stop_retries()
    _retry_stopping = False
