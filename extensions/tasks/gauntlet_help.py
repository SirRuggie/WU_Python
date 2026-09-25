"""Sticky Gauntlet help and one-shot, durable recruit assistance reminders."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.constants import GOLDENROD_ACCENT
from utils.gauntlet_help import get_settings, record_progress, settings_id, utcnow
from utils.mongo import MongoClient

loader = lightbulb.Loader()
log = logging.getLogger(__name__)

GUILD_ID = 644963518025826315
HELP_CHANNEL_ID = 1553128653645160479
RECRUIT_ROLE_ID = 1003797104088592444
STAGE_ROLES = (
    1551011479577165844,
    1553110276251979937,
    1553110508746448956,
    1553110621711634502,
)
CHECK_SECONDS = 60
BATCH_SIZE = 20
DELETE_AFTER = timedelta(minutes=10)
STICKY_AFTER = timedelta(minutes=30)
CLAIM_LEASE = timedelta(minutes=5)

_bot = None
_mongo = None
_task = None


def _aware(value: datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return None


def _sticky_components():
    return [Container(accent_color=GOLDENROD_ACCENT, components=[
        Text(content="**Recruit Gauntlet help**"),
        Text(content=(
            "If you need assistance with any Gauntlet step, ask your question here "
            f"and please ping <@&{RECRUIT_ROLE_ID}>. A recruiter can help you continue."
        )),
    ])]


def _reminder_components(user_id: int, stage: int):
    return [Container(accent_color=GOLDENROD_ACCENT, components=[
        Text(content=f"**Recruit Gauntlet step {stage}**"),
        Text(content=(
            f"<@{user_id}> — do you need assistance with the next step? "
            f"Ask here and please ping <@&{RECRUIT_ROLE_ID}>. A recruiter can help you continue."
        )),
    ])]


def _message_text(message) -> str:
    parts = []
    def walk(component):
        content = getattr(component, "content", None)
        if isinstance(content, str):
            parts.append(content)
        for child in getattr(component, "components", ()) or ():
            walk(child)
    for component in getattr(message, "components", ()) or ():
        walk(component)
    return "\n".join(parts)


async def _recent_bot_messages(bot) -> list:
    messages = []
    get_me = getattr(bot, "get_me", None)
    me = get_me() if callable(get_me) else None
    if me is None:
        me = await bot.rest.fetch_my_user()
    own_id = int(me.id)
    async for message in bot.rest.fetch_messages(HELP_CHANNEL_ID).limit(100):
        author = getattr(message, "author", None)
        if author is not None and int(getattr(author, "id", 0)) == own_id:
            messages.append(message)
    return messages


async def _reconcile_unknown(bot, mongo, now: datetime) -> None:
    """Recover known successful creates after a crash before the Mongo receipt."""
    config = await mongo.bot_config.find_one({"_id": settings_id(GUILD_ID)}) or {}
    cursor = mongo.bot_config.find({"kind": "gauntlet_help_progress", "guild_id": GUILD_ID,
                                    "status": "send_unknown"}).limit(BATCH_SIZE)
    unknown = await cursor.to_list(length=BATCH_SIZE)
    channel = await bot.rest.fetch_channel(HELP_CHANNEL_ID)
    if int(getattr(channel, "id", 0)) != HELP_CHANNEL_ID or int(getattr(channel, "guild_id", 0)) != GUILD_ID:
        return
    messages = await _recent_bot_messages(bot)
    sticky = next((m for m in messages if "**Recruit Gauntlet help**" in _message_text(m)), None)
    if sticky and (not config.get("sticky_message_id") or config.get("sticky_state") in {"posting", "unknown"}):
        old_id = int(config.get("sticky_message_id") or 0)
        await mongo.bot_config.update_one({"_id": settings_id(GUILD_ID)}, {"$set": {
            "sticky_state": "posted", "sticky_message_id": int(sticky.id),
            "sticky_posted_at": _aware(getattr(sticky, "created_at", None)) or now,
            "pending_sticky_delete_id": old_id if old_id != int(sticky.id) else 0,
        }, "$unset": {"sticky_token": ""}})
    # Every recognizable own reminder receives a deletion receipt, even if
    # its progress row advanced before the REST response was persisted.
    for message in messages:
        body = _message_text(message)
        if "**Recruit Gauntlet step " not in body or "do you need assistance" not in body:
            continue
        created = _aware(getattr(message, "created_at", None))
        if created:
            await _queue_delete(mongo, int(message.id), created + DELETE_AFTER)
    for row in unknown:
        marker = f"**Recruit Gauntlet step {int(row['stage'])}**"
        user = f"<@{int(row['user_id'])}>"
        started = _aware(row.get("send_started_at"))
        message = next((m for m in messages if marker in _message_text(m)
                        and user in _message_text(m)
                        and (not started or not _aware(getattr(m, "created_at", None))
                             or _aware(m.created_at) >= started - timedelta(minutes=1))), None)
        if message is None:
            continue
        delete_at = (_aware(getattr(message, "created_at", None)) or now) + DELETE_AFTER
        await _queue_delete(mongo, int(message.id), delete_at)
        await mongo.bot_config.update_one(
            {"_id": row["_id"], "status": "send_unknown", "claim_token": row.get("claim_token")},
            {"$set": {"status": "reminded", "message_id": int(message.id), "delete_at": delete_at},
             "$unset": {"claim_token": ""}},
        )


async def _latest_human_at(bot, channel_id: int) -> datetime | None:
    """Bootstrap quiet time from channel history, never from our own messages."""
    try:
        async for message in bot.rest.fetch_messages(channel_id).limit(100):
            author = getattr(message, "author", None)
            if author is not None and not getattr(author, "is_bot", False):
                return _aware(getattr(message, "created_at", None))
    except Exception:
        log.exception("Gauntlet help history read failed")
    return None


async def note_human_activity(mongo, *, at: datetime | None = None) -> None:
    await mongo.bot_config.update_one(
        {"_id": settings_id(GUILD_ID)},
        {"$max": {"last_human_at": at or utcnow()},
         "$setOnInsert": {"enabled": True, "guild_id": GUILD_ID}},
        upsert=True,
    )


@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def on_help_message(event: hikari.GuildMessageCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED):
    if int(event.guild_id) != GUILD_ID or int(event.channel_id) != HELP_CHANNEL_ID:
        return
    author = getattr(event.message, "author", None)
    if author is None or getattr(author, "is_bot", False):
        return
    await note_human_activity(mongo, at=_aware(getattr(event.message, "created_at", None)))


async def _sticky(bot, mongo, settings: dict, now: datetime) -> None:
    if not settings["enabled"]:
        return
    row = await mongo.bot_config.find_one({"_id": settings_id(GUILD_ID)}) or {}
    # Validate channel before beginning any create/delete sequence.
    channel = await bot.rest.fetch_channel(HELP_CHANNEL_ID)
    if int(getattr(channel, "id", 0)) != HELP_CHANNEL_ID or int(getattr(channel, "guild_id", 0)) != GUILD_ID:
        return
    if "last_human_at" not in row:
        latest = await _latest_human_at(bot, HELP_CHANNEL_ID)
        await note_human_activity(mongo, at=latest or now)
        row["last_human_at"] = latest or now

    previous = row.get("sticky_message_id")
    last_human = _aware(row.get("last_human_at")) or now
    if previous:
        newest = getattr(channel, "last_message_id", None)
        if newest and int(newest) == int(previous):
            return
        missing = False
        try:
            await bot.rest.fetch_message(HELP_CHANNEL_ID, int(previous))
        except hikari.NotFoundError:
            missing = True
        except Exception:
            log.exception("Gauntlet sticky verification failed")
            return
        if not missing:
            if now - last_human < STICKY_AFTER:
                return
            # A bot reminder alone does not justify a repost.
            posted = _aware(row.get("sticky_posted_at"))
            if posted and last_human <= posted:
                return
    latest = await _latest_human_at(bot, HELP_CHANNEL_ID)
    if latest and latest > last_human:
        await note_human_activity(mongo, at=latest)
        if previous and now - latest < STICKY_AFTER:
            return

    # The create intent is durable. If Discord creates the message but the
    # response is lost, an automatic retry would duplicate a sticky.
    token = uuid.uuid4().hex
    claimed = await mongo.bot_config.update_one(
        {"_id": settings_id(GUILD_ID), "sticky_state": {"$nin": ["posting", "unknown"]}},
        {"$set": {"sticky_state": "posting", "sticky_token": token}},
    )
    if not claimed.matched_count:
        return
    try:
        message = await bot.rest.create_message(
            channel=HELP_CHANNEL_ID, components=_sticky_components(),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
    except Exception:
        await mongo.bot_config.update_one(
            {"_id": settings_id(GUILD_ID), "sticky_token": token},
            {"$set": {"sticky_state": "unknown"}},
        )
        log.exception("Gauntlet sticky create outcome unknown; automatic retry suppressed")
        return
    await mongo.bot_config.update_one(
        {"_id": settings_id(GUILD_ID), "sticky_token": token},
        {"$set": {"sticky_state": "posted", "sticky_message_id": int(message.id),
                  "sticky_posted_at": utcnow(),
                  "pending_sticky_delete_id": int(previous) if previous else 0},
         "$unset": {"sticky_token": ""}},
    )
    await _drain_pending_sticky(mongo, now)


async def _drain_pending_sticky(mongo, now: datetime) -> None:
    row = await mongo.bot_config.find_one({"_id": settings_id(GUILD_ID)}) or {}
    previous = int(row.get("pending_sticky_delete_id") or 0)
    if not previous:
        return
    await _queue_delete(mongo, previous, now)
    await mongo.bot_config.update_one(
        {"_id": settings_id(GUILD_ID), "pending_sticky_delete_id": previous},
        {"$unset": {"pending_sticky_delete_id": ""}},
    )


async def _queue_delete(mongo, message_id: int, at: datetime) -> None:
    key = f"gauntlet_help_delete:{GUILD_ID}:{int(message_id)}"
    await mongo.bot_config.update_one(
        {"_id": key},
        {"$setOnInsert": {"kind": "gauntlet_help_delete", "guild_id": GUILD_ID,
                           "message_id": int(message_id), "delete_at": at,
                           "attempts": 0}},
        upsert=True,
    )


async def _drain_deletes(bot, mongo, now: datetime) -> None:
    cursor = mongo.bot_config.find({"kind": "gauntlet_help_delete", "guild_id": GUILD_ID,
                                    "delete_at": {"$lte": now}}).sort("delete_at", 1).limit(BATCH_SIZE)
    for row in await cursor.to_list(length=BATCH_SIZE):
        key = row["_id"]
        try:
            await bot.rest.delete_message(HELP_CHANNEL_ID, row["message_id"])
        except hikari.NotFoundError:
            pass
        except Exception:
            attempts = min(int(row.get("attempts", 0)) + 1, 8)
            await mongo.bot_config.update_one({"_id": key}, {"$set": {
                "attempts": attempts,
                "delete_at": now + timedelta(minutes=min(2 ** attempts, 60)),
            }})
            log.exception("Gauntlet message deletion delayed: %s", key)
            continue
        await mongo.bot_config.delete_one({"_id": key})


async def _ticket_exists(mongo, user_id: int, advanced_at: datetime) -> bool:
    query = {"type": "ticket", "guild_id": GUILD_ID, "user_id": user_id,
             "ticket_type": {"$in": ["main", "fwa"]},
             "$or": [{"status": "open"}, {"created_at": {"$gte": advanced_at}}]}
    for collection_name in ("tickets", "button_store"):
        collection = getattr(mongo, collection_name, None)
        if collection is not None and await collection.find_one(query):
            return True
    return False


async def _sweep_progress(bot, mongo, settings: dict, now: datetime) -> None:
    if not settings["enabled"]:
        return
    query = {"kind": "gauntlet_help_progress", "guild_id": GUILD_ID,
             "due_at": {"$lte": now},
             "$or": [{"status": "waiting"}, {"status": "checking", "lease_until": {"$lte": now}}]}
    cursor = mongo.bot_config.find(query).sort("due_at", 1).limit(BATCH_SIZE)
    for candidate in await cursor.to_list(length=BATCH_SIZE):
        token = uuid.uuid4().hex
        row = await mongo.bot_config.find_one_and_update(
            {"_id": candidate["_id"], "stage": candidate["stage"],
             "due_at": candidate["due_at"], "$or": query["$or"]},
            {"$set": {"status": "checking", "claim_token": token,
                       "lease_until": now + CLAIM_LEASE}},
            return_document=ReturnDocument.AFTER,
        )
        if not row:
            continue
        user_id, stage = int(row["user_id"]), int(row["stage"])
        try:
            member = await bot.rest.fetch_member(GUILD_ID, user_id)
        except hikari.NotFoundError:
            await mongo.bot_config.update_one(
                {"_id": row["_id"], "claim_token": token},
                {"$set": {"status": "left_guild"}, "$unset": {"claim_token": "", "lease_until": ""}},
            )
            continue
        except Exception:
            log.exception("Gauntlet member fetch failed for %s", user_id)
            await mongo.bot_config.update_one(
                {"_id": row["_id"], "claim_token": token},
                {"$set": {"status": "waiting", "due_at": now + timedelta(minutes=5)},
                 "$unset": {"claim_token": "", "lease_until": ""}},
            )
            continue
        if await _ticket_exists(mongo, user_id, _aware(row.get("advanced_at")) or now):
            await mongo.bot_config.update_one(
                {"_id": row["_id"], "claim_token": token},
                {"$set": {"status": "complete", "completed_at": now},
                 "$unset": {"claim_token": "", "lease_until": ""}},
            )
            continue
        held_roles = set(map(int, member.role_ids))
        later_stages = [index + 1 for index, role_id in enumerate(STAGE_ROLES)
                        if index + 1 > stage and role_id in held_roles]
        if later_stages:
            await record_progress(mongo, GUILD_ID, user_id, max(later_stages))
            continue
        if STAGE_ROLES[stage - 1] not in held_roles:
            await mongo.bot_config.update_one(
                {"_id": row["_id"], "claim_token": token},
                {"$set": {"status": "role_revoked", "updated_at": now},
                 "$unset": {"claim_token": "", "lease_until": ""}},
            )
            continue
        # Atomic transition before REST create; unknown outcomes never reping.
        marked = await mongo.bot_config.update_one(
            {"_id": row["_id"], "claim_token": token, "status": "checking"},
            {"$set": {"status": "send_unknown", "send_started_at": utcnow()},
             "$unset": {"lease_until": ""}},
        )
        if not marked.matched_count:
            continue
        try:
            message = await bot.rest.create_message(
                channel=HELP_CHANNEL_ID, components=_reminder_components(user_id, stage),
                flags=hikari.MessageFlag.IS_COMPONENTS_V2,
                user_mentions=[user_id], role_mentions=False, mentions_everyone=False,
            )
        except Exception:
            log.exception("Gauntlet reminder outcome unknown for %s; no automatic reping", user_id)
            continue
        delete_at = utcnow() + DELETE_AFTER
        await _queue_delete(mongo, int(message.id), delete_at)
        await mongo.bot_config.update_one(
            {"_id": row["_id"], "claim_token": token, "status": "send_unknown"},
            {"$set": {"status": "reminded", "message_id": int(message.id), "delete_at": delete_at},
             "$unset": {"claim_token": ""}},
        )


async def sweep_once(bot=None, mongo=None, *, now: datetime | None = None) -> None:
    bot, mongo, now = bot or _bot, mongo or _mongo, now or utcnow()
    if bot is None or mongo is None:
        return
    settings = await get_settings(mongo, GUILD_ID)
    await _drain_pending_sticky(mongo, now)
    await _drain_deletes(bot, mongo, now)
    if settings["enabled"]:
        await _reconcile_unknown(bot, mongo, now)
        await _drain_pending_sticky(mongo, now)
        await _drain_deletes(bot, mongo, now)
    if not settings["enabled"]:
        return
    await _sticky(bot, mongo, settings, now)
    await _drain_deletes(bot, mongo, now)
    await _sweep_progress(bot, mongo, settings, now)


async def _loop():
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Gauntlet help sweep failed")
        await asyncio.sleep(CHECK_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(event: hikari.StartedEvent, bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                     mongo: MongoClient = lightbulb.di.INJECTED):
    global _bot, _mongo, _task
    _bot, _mongo = bot, mongo
    if _task and not _task.done():
        return
    try:
        await mongo.bot_config.create_index(
            [("kind", 1), ("guild_id", 1), ("status", 1), ("due_at", 1)],
            name="gauntlet_help_due_v1",
        )
        await mongo.bot_config.create_index(
            [("kind", 1), ("guild_id", 1), ("delete_at", 1)],
            name="gauntlet_help_delete_v1",
        )
    except Exception:
        log.exception("Gauntlet help indexes unavailable")
    _task = asyncio.create_task(_loop(), name="gauntlet-help")


@loader.listener(hikari.StoppingEvent)
async def on_stopping(event: hikari.StoppingEvent):
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
