"""Discord gateway transport for durable member and moderation history."""
from __future__ import annotations

import asyncio
import collections
import contextvars
import enum
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import hikari
import lightbulb
from utils.member_events import (
    DEFAULT_CHANNEL_ID, GUILD_ID, HISTORY_TYPES, MAX_AVATAR_BYTES, MemberEventStore,
    avatar_source, effective_permissions, event_key, safe_text,
)
from utils.member_event_cards import avatar_filename, build_card, build_forum_message, transcript_file
from utils.member_event_settings import effective_event, resolve_ignored_bots
from utils.member_invites import MemberInviteStore, attribute_join, snapshot_row
from utils.mongo import MongoClient

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
CHANNEL_ID = DEFAULT_CHANNEL_ID  # Kept for existing imports and deployment checks.
_start_task = None
_audit_task = None
_indexes_ready = False
AUDIT_RECOVERY_WINDOW = timedelta(hours=24)
AUDIT_RECOVERY_LIMIT = 500
# While "pending", live audit entries only note the newest id; recovery reads the old cursor first.
_audit_state = {"pending": True, "live_max": 0}
_recovering: contextvars.ContextVar[bool] = contextvars.ContextVar("member_events_recovering", default=False)
_audit_entry: contextvars.ContextVar[int | None] = contextvars.ContextVar("member_events_audit_entry", default=None)
# Rows an audit entry's handler persisted; delivered only after the entry is marked handled.
_deferred: contextvars.ContextVar[list | None] = contextvars.ContextVar("member_events_deferred", default=None)
_index_lock = asyncio.Lock()
_invite_lock = asyncio.Lock()  # One join diff at a time; create/delete share it.
INVITE_WAIT_SECONDS = 3
_invite_waits: dict[int, asyncio.Future] = {}  # Join card waits here for its invite name.
_invite_born: dict[int, float] = {}  # When each waiting future was created (loop time).
INVITE_STALE_SECONDS = 5
_recent_app_adds: list[dict] = []  # Posted "App added" audit entries: time, action type, application id, matched.
APP_ADD_WINDOW_SECONDS = 60
APP_ADD_STORED_WINDOW = timedelta(minutes=10)
URL_PATTERN = re.compile(r"https?://\S+")
FORUM_LABELS = {"join": "Joined", "leave": "Left", "kick": "Kicked", "ban": "Banned",
                "timeout_add": "Timed out", "timeout_remove": "Timeout removed",
                "member_update": "Profile changed", "link": "Link",
                "invite_create": "Invite created", "invite_delete": "Invite deleted",
                "invite_use": "Invite used", "unban": "Unbanned",
                "role_create": "Role created", "role_update": "Role updated",
                "role_delete": "Role deleted", "roles_added": "Roles added",
                "roles_removed": "Roles removed", "message_delete": "Message deleted",
                "message_edit": "Message edited", "message_bulk_delete": "Bulk delete",
                "channel_create": "Channel created", "channel_update": "Channel updated",
                "channel_delete": "Channel deleted", "channel_permissions": "Permissions",
                "thread_delete": "Thread deleted", "thread_lock": "Thread locked",
                "server_update": "Server updated", "emoji": "Emoji", "sticker": "Sticker",
                "app": "App", "webhook": "Webhook", "automod": "AutoMod"}


async def ensure_indexes(store):
    global _indexes_ready
    async with _index_lock:
        if not _indexes_ready:
            await store.ensure_indexes()
            _indexes_ready = True


async def deliver_or_defer(store, bot, row):
    pending = _deferred.get()
    if pending is None:
        await deliver(store, bot, row)
    else:
        pending.append((store, row))


async def download_avatar(url: str | None):
    if not url:
        return None, None
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200 or int(response.headers.get("Content-Length", "0")) > MAX_AVATAR_BYTES:
                    return None, None
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if mime not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
                    return None, None
                chunks = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_AVATAR_BYTES:
                        return None, None
                    chunks.append(chunk)
                return (b"".join(chunks), mime) if total else (None, None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None, None


def identity_metadata(bot, user_id: int, member, saved):
    """Capture best-effort display facts before a member leaves the guild."""
    created_at = datetime.fromtimestamp(
        ((int(user_id) >> 22) + 1420070400000) / 1000, tz=timezone.utc,
    )
    cache = getattr(bot, "cache", None)
    guild = cache.get_guild(GUILD_ID) if cache and hasattr(cache, "get_guild") else None
    count = getattr(guild, "member_count", None)
    member_count = count if isinstance(count, int) and count >= 0 else None
    role_ids = getattr(member, "role_ids", None)
    if role_ids is None:
        roles = (saved or {}).get("roles")
    else:
        roles = []
        for role_id in role_ids:
            if int(role_id) == GUILD_ID:
                continue
            role = cache.get_role(role_id) if cache and hasattr(cache, "get_role") else None
            roles.append(str(getattr(role, "name", None) or f"Role ID {int(role_id)}")[:80])
        roles = roles[:30]
    return created_at, member_count, roles


async def post_card(row, *, forum=False):
    """One HTTP attempt for either message or forum thread creation."""
    channel_id = int(row["channel_id"])
    filename = avatar_filename(row)
    if forum:
        label = FORUM_LABELS[row["event_type"]]
        occurred = row["occurred_at"].replace(tzinfo=row["occurred_at"].tzinfo or timezone.utc)
        date = occurred.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        suffix = f" · {row['user_id']} · {date}" if row["user_id"] != "0" else f" · {date}"
        name_budget = max(1, 100 - len(label) - len(suffix) - 3)
        title = f"{label} · {safe_text(row['display_name'], name_budget)}{suffix}"
        payload = {"name": title[:100], "message": build_forum_message(row)}
        if row.get("forum_tag_id"):
            payload["applied_tags"] = [str(row["forum_tag_id"])]
        endpoint = f"https://discord.com/api/v10/channels/{channel_id}/threads"
        message = payload["message"]
    else:
        payload = build_card(row)
        endpoint = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        message = payload
    files = [(filename, row["avatar"], row["avatar_type"])] if filename else []
    transcript = transcript_file(row)
    if transcript:
        files.append(transcript)
    if files:
        message["attachments"] = [{"id": index, "filename": name} for index, (name, _, _) in enumerate(files)]
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        for index, (name, data, content_type) in enumerate(files):
            form.add_field(f"files[{index}]", data, filename=name, content_type=content_type)
        request_args = {"data": form}
    else:
        request_args = {"json": payload}
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("Discord token is unavailable")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.post(endpoint, headers={"Authorization": "Bot " + token},
                                **request_args) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Discord member event post returned HTTP {response.status}")
            result = await response.json()
            message_id = (result.get("message") or result).get("id")
            if not isinstance(message_id, str) or not message_id.isdigit():
                raise RuntimeError("Discord member event response had no message ID")
            return message_id


async def channel_ready(bot, row):
    """Check current destination ownership, tag and bot rights before claim."""
    if not row.get("channel_id"):
        return None
    channel = await bot.rest.fetch_channel(int(row["channel_id"]))
    if int(getattr(channel, "guild_id", 0)) != GUILD_ID:
        return None
    kind = getattr(channel, "type", None)
    if kind not in (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS,
                    hikari.ChannelType.GUILD_FORUM, hikari.ChannelType.GUILD_PUBLIC_THREAD):
        return None
    permission_channel = channel
    if kind == hikari.ChannelType.GUILD_PUBLIC_THREAD:
        permission_channel = await bot.rest.fetch_channel(int(channel.parent_id))
        if (int(getattr(permission_channel, "guild_id", 0)) != GUILD_ID
                or permission_channel.type != hikari.ChannelType.GUILD_FORUM
                or getattr(channel, "is_locked", False)):
            return None
    tag_id = row.get("forum_tag_id")
    if kind == hikari.ChannelType.GUILD_FORUM:
        tags = {int(tag.id): tag for tag in getattr(channel, "available_tags", ())}
        if int(getattr(channel, "flags", 0)) & 16 and not tag_id:
            return None
        if tag_id and int(tag_id) not in tags:
            return None
    elif tag_id:
        return None
    me = await bot.rest.fetch_my_user()
    member = await bot.rest.fetch_member(GUILD_ID, me.id)
    roles = await bot.rest.fetch_roles(GUILD_ID)
    role_ids = set(member.role_ids)
    base = 0
    for role in roles:
        if int(role.id) in role_ids | {GUILD_ID}:
            base |= int(role.permissions)
    rights = effective_permissions(base, role_ids, int(me.id),
                                   getattr(permission_channel, "permission_overwrites", {}), GUILD_ID)
    needed = (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES |
              hikari.Permissions.ATTACH_FILES)
    if kind == hikari.ChannelType.GUILD_PUBLIC_THREAD:
        needed = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES_IN_THREADS | hikari.Permissions.ATTACH_FILES
    if kind == hikari.ChannelType.GUILD_FORUM:
        needed |= hikari.Permissions.EMBED_LINKS
        if tag_id and tags[int(tag_id)].moderated and not rights & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_THREADS):
            return None
    if not rights & hikari.Permissions.ADMINISTRATOR and rights & needed != needed:
        return None
    return channel


async def deliver(store: MemberEventStore, bot, row):
    # A settings change cancels unsent rows for old destinations. It never
    # touches a send already claimed or an uncertain Discord receipt.
    current = effective_event(await store.settings(), row["event_type"])
    if (not current["enabled"] or str(current["channel_id"]) != str(row.get("channel_id"))
            or str(current.get("forum_tag_id")) != str(row.get("forum_tag_id"))):
        await store.skip_queued(row["_id"])
        return True
    # Bad configuration or changed permissions leave the row safely queued.
    channel = await channel_ready(bot, row)
    if not channel:
        log.warning("Member event destination is unavailable for %s", row["_id"])
        return False
    row = await store.claim(row["_id"])
    if not row:
        return False
    try:
        message_id = await post_card(row, forum=channel.type == hikari.ChannelType.GUILD_FORUM)
        await store.finish(row["_id"], status="sent", message_id=message_id)
        return True
    except BaseException:
        # Discord may already have accepted either POST. Never auto-replay it.
        try:
            await store.finish(row["_id"], status="uncertain")
        except Exception:
            log.exception("Could not persist uncertain member event receipt")
        raise


async def record_identity(kind, guild_id, user_id, mongo, bot, *, user=None, member=None,
                          at=None, moderator_id=None, reason=None, audit_entry_id=None,
                          episode_override=None):
    if int(guild_id) != GUILD_ID:
        return
    now = at or datetime.now(timezone.utc)
    uid = int(user_id)
    if kind == "join":
        discard_stale_invite(uid)
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    saved = await store.latest_identity(GUILD_ID, uid) if kind in ("leave", "kick", "ban") else None
    username = str(getattr(user, "username", None) or (saved or {}).get("username") or uid)
    display_name = str(getattr(member, "display_name", None) or
                       getattr(user, "global_name", None) or (saved or {}).get("display_name") or username)
    joined_at = getattr(member, "joined_at", None)
    if not isinstance(joined_at, datetime):
        joined_at = (saved or {}).get("joined_at")
    if kind == "leave" and not isinstance(joined_at, datetime):
        joined_at = await store.latest_joined_at(GUILD_ID, uid, now)
    account_created_at, member_count, roles = identity_metadata(bot, uid, member, saved)
    episode = (episode_override if episode_override is not None else
               await store.ban_episode(GUILD_ID, uid, banned=True)) if kind == "ban" else None
    pending_audit = (await store.pending_ban_audit(GUILD_ID, uid, now)
                     if kind == "ban" and audit_entry_id is None else None)
    if pending_audit:
        moderator_id = moderator_id or pending_audit.get("moderator_id")
        reason = reason or pending_audit.get("reason")
        audit_entry_id = int(pending_audit["_id"].rsplit(":", 1)[1])
    settings = await store.settings()
    config = effective_event(settings, kind)
    enabled = config["enabled"] and bool(config["channel_id"])
    channel_id = int(config["channel_id"]) if enabled else None
    forum_tag_id = int(config["forum_tag_id"]) if enabled and config.get("forum_tag_id") else None
    join_details = {"join_count": await store.count_joins(GUILD_ID, uid) + 1} if kind == "join" else None
    row = await store.capture(
        guild_id=GUILD_ID, user_id=uid, kind=kind,
        display_name=display_name, username=username, avatar=None, avatar_type=None,
        at=now, joined_at=joined_at, channel_id=channel_id,
        forum_tag_id=forum_tag_id, reason=reason, moderator_id=moderator_id,
        audit_entry_id=audit_entry_id, episode=episode,
        account_created_at=account_created_at, member_count=member_count,
        roles=roles, details=join_details or ({"recovered": True} if _recovering.get() else None),
    )
    if not row:
        return
    if pending_audit:
        await store.consume_ban_audit(pending_audit["_id"])
    elif kind == "ban" and audit_entry_id is not None:
        await store.consume_ban_audit(f"ban-audit:{GUILD_ID}:{audit_entry_id}")
    # Audit kick entries contain a target ID but no User object. Try a public
    # identity lookup only after the durable ID snapshot exists.
    if user is None and saved is None:
        try:
            user = await bot.rest.fetch_user(uid)
        except Exception:
            user = None
        if user:
            username = str(getattr(user, "username", None) or uid)
            display_name = str(getattr(user, "global_name", None) or username)
            await store.save_identity(row["_id"], display_name, username)
    source = avatar_source(GUILD_ID, uid, getattr(user, "avatar_hash", None),
                           getattr(member, "guild_avatar_hash", None))
    avatar, mime = await download_avatar(source)
    if not avatar and saved and saved.get("avatar"):
        avatar, mime = bytes(saved["avatar"]), saved.get("avatar_type")
    if avatar and mime:
        try:
            await store.save_avatar(row["_id"], avatar, mime)
        except Exception:
            log.exception("Could not save member avatar; identity record remains")
    if kind == "kick" and saved is None:
        # Audit entries can precede the member-removal gateway event. Give its
        # durable snapshot a brief chance to arrive before posting the card.
        await asyncio.sleep(2)
        departure = await store.latest_departure_identity(GUILD_ID, uid)
        if departure:
            await store.enrich_recent_kick(
                GUILD_ID, uid, now, departure.get("display_name") or str(uid),
                departure.get("username") or str(uid), departure.get("joined_at"),
                departure.get("avatar"), departure.get("avatar_type"),
                roles=departure.get("roles"),
            )
    if kind == "ban":
        # Give a near-simultaneous audit entry a chance to enrich the queued card.
        await asyncio.sleep(1)
    if kind == "join":
        label = await wait_invite_label(uid, enabled)
        if label:
            await store.save_details(row["_id"], {**join_details, "invite": label})
    ready_row = await store.ready(row["_id"], enabled=enabled)
    if ready_row and kind == "leave":
        await store.enrich_recent_kick(GUILD_ID, uid, now, ready_row["display_name"],
                                       ready_row["username"], ready_row.get("joined_at"),
                                       ready_row.get("avatar"), ready_row.get("avatar_type"),
                                       roles=ready_row.get("roles"))
    if ready_row and enabled:
        await deliver_or_defer(store, bot, ready_row)


async def record(event, kind: str, mongo: MongoClient, bot: hikari.GatewayBot):
    if kind == "join":
        member, user = event.member, event.member.user
        guild_id = member.guild_id
    else:
        member, user = event.old_member, event.user
        guild_id = event.guild_id
    await record_identity(kind, guild_id, user.id, mongo, bot, user=user, member=member)


async def recover(mongo, bot):
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    await store.release_stale_captures(GUILD_ID)
    after = None
    while True:
        rows = await store.queued(GUILD_ID, after=after)
        if not rows:
            return
        for row in rows:
            after = row["_id"]
            try:
                await deliver(store, bot, row)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Continue this bounded pass so one invalid destination cannot
                # starve events configured for other channels.
                log.exception("Could not deliver queued member event %s", row["_id"])
        if len(rows) < 100:
            return


async def recovery_loop(mongo, bot):
    while True:
        try:
            await recover(mongo, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Member event recovery could not complete")
        await asyncio.sleep(60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def started(event: hikari.StartedEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    global _start_task
    _start_task = asyncio.create_task(recovery_loop(mongo, bot), name="member-events-recover")


@loader.listener(hikari.StoppingEvent)
async def stopping(event: hikari.StoppingEvent):
    for task in (_start_task, _audit_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@loader.listener(hikari.MemberCreateEvent)
@lightbulb.di.with_di
async def joined(event: hikari.MemberCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                 bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    try:
        await record(event, "join", mongo, bot)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive a member join")


@loader.listener(hikari.MemberDeleteEvent)
@lightbulb.di.with_di
async def left(event: hikari.MemberDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED,
               bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    try:
        await record(event, "leave", mongo, bot)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive a member departure")


@loader.listener(hikari.BanCreateEvent)
@lightbulb.di.with_di
async def banned(event: hikari.BanCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                 bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    try:
        await record_identity("ban", event.guild_id, event.user.id, mongo, bot, user=event.user)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive a confirmed ban")


@loader.listener(hikari.AuditLogEntryCreateEvent)
@lightbulb.di.with_di
async def audited(event: hikari.AuditLogEntryCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await handle_audit_entry(event.entry, mongo, bot)


async def handle_audit_entry(entry, mongo, bot, *, recovered=False) -> bool:
    """Route one audit entry, live or recovered. Never raises; True once handled."""
    if int(entry.guild_id) != GUILD_ID or not entry.target_id:
        return False
    if recovered:
        try:
            store = MemberEventStore(mongo.member_events)
            await ensure_indexes(store)
            if (await store.audit_handled(GUILD_ID, entry.id)
                    or await store.audit_row_exists(GUILD_ID, entry.id)):
                await note_audit_cursor(entry, mongo, recovered=True)
                return True  # A replay of an entry already handled must not post or change state.
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Could not check a replayed audit entry")
            return False
    token = _recovering.set(recovered)
    pending: list = []
    deferred = _deferred.set(pending)
    current = _audit_entry.set(int(entry.id))
    try:
        if entry.action_type == hikari.AuditLogEventType.MEMBER_KICK:
            cache = getattr(bot, "cache", None)
            member = cache.get_member(GUILD_ID, int(entry.target_id)) if cache else None
            await record_identity("kick", GUILD_ID, entry.target_id, mongo, bot,
                                  user=getattr(member, "user", None), member=member,
                                  at=entry.created_at, moderator_id=entry.user_id,
                                  reason=entry.reason, audit_entry_id=entry.id)
        elif entry.action_type == hikari.AuditLogEventType.MEMBER_UPDATE:
            await record_timeout(entry, mongo, bot)
        elif entry.action_type == hikari.AuditLogEventType.MEMBER_BAN_ADD:
            store = MemberEventStore(mongo.member_events)
            await ensure_indexes(store)
            uid, audit_id = int(entry.target_id), int(entry.id)
            fact = await store.record_ban_audit(
                GUILD_ID, uid, audit_id, entry.created_at,
                int(entry.user_id) if entry.user_id else None, entry.reason,
            )
            if await store.enrich_ban(GUILD_ID, uid, entry.created_at,
                                      int(entry.user_id) if entry.user_id else None,
                                      entry.reason, audit_id):
                await store.note_ban_audit(GUILD_ID, uid, audit_id)
                await store.consume_ban_audit(fact["_id"])
            elif await store.ban_audit_exists(GUILD_ID, audit_id):
                await store.consume_ban_audit(fact["_id"])
            else:
                # A BanCreate may have deduplicated against an old episode if
                # its intervening BanDelete was missed during downtime. The
                # distinct audit ID is authoritative evidence of a new ban.
                episode = await store.advance_ban_episode_for_audit(GUILD_ID, uid, audit_id)
                await record_identity(
                    "ban", GUILD_ID, uid, mongo, bot, at=entry.created_at,
                    moderator_id=entry.user_id, reason=entry.reason,
                    audit_entry_id=audit_id, episode_override=episode,
                )
        elif entry.action_type == hikari.AuditLogEventType.MEMBER_BAN_REMOVE:
            store = MemberEventStore(mongo.member_events)
            await ensure_indexes(store)
            uid = int(entry.target_id)
            if not await store.audit_handled(GUILD_ID, entry.id):  # A duplicate must not flip ban state.
                await emit_unban(mongo, bot, uid, await store.ban_episode(GUILD_ID, uid, banned=False),
                                 at=entry.created_at, entry=entry)
        elif entry.action_type == hikari.AuditLogEventType.MEMBER_ROLE_UPDATE:
            await record_member_roles(entry, mongo, bot)
        elif entry.action_type in (hikari.AuditLogEventType.MESSAGE_DELETE,
                                   hikari.AuditLogEventType.MESSAGE_BULK_DELETE):
            if not recovered:  # Delete facts only help a live gateway event.
                note_message_audit(entry)
        else:
            await record_audit_kind(entry, mongo, bot)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive or enrich a moderation audit entry")
        return False
    finally:
        _recovering.reset(token)
        _deferred.reset(deferred)
        _audit_entry.reset(current)
    marked = True
    try:  # Once the entry's state and rows are persisted, before any Discord delivery.
        store = MemberEventStore(mongo.member_events)
        await ensure_indexes(store)
        await store.mark_audit_handled(GUILD_ID, entry.id)
    except asyncio.CancelledError:
        raise
    except Exception:
        marked = False
        log.warning("Could not mark an audit entry as handled", exc_info=True)
    delivered = True
    for store, row in pending:  # A failure leaves the row queued for the recovery loop.
        try:
            await deliver(store, bot, row)
        except asyncio.CancelledError:
            raise
        except Exception:
            delivered = False
            log.exception("Failed to deliver a moderation audit log row")
    if marked:  # Persisted effects, not delivery, decide whether the entry is done.
        await note_audit_cursor(entry, mongo, recovered=recovered)
    return marked and delivered


async def note_audit_cursor(entry, mongo, *, recovered):
    entry_id = int(entry.id)
    if not recovered and _audit_state["pending"]:
        _audit_state["live_max"] = max(_audit_state["live_max"], entry_id)
        return
    try:
        store = MemberEventStore(mongo.member_events)
        await ensure_indexes(store)
        await store.advance_audit_cursor(entry_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("Could not save the audit cursor", exc_info=True)


async def recover_audit(mongo, bot):
    """Replay audit entries missed while down: newest 24 h / 500, oldest first.

    No cursor yet (first run) only sets it. A failure logs one warning and leaves
    that gap unrecovered; the live-entry hold is released so the cursor keeps moving.
    """
    try:
        store = MemberEventStore(mongo.member_events)
        await ensure_indexes(store)
        cursor = await store.audit_cursor()
        floor = datetime.now(timezone.utc) - AUDIT_RECOVERY_WINDOW
        missed, done = [], False
        async for page in bot.rest.fetch_audit_log(GUILD_ID):
            for entry in sorted(page.entries.values(), key=lambda item: int(item.id), reverse=True):
                if cursor is None:  # First run: start from now, recover nothing.
                    await store.advance_audit_cursor(entry.id)
                    done = True
                    break
                if (int(entry.id) <= cursor or entry.created_at < floor
                        or len(missed) >= AUDIT_RECOVERY_LIMIT):
                    done = True
                    break
                missed.append(entry)
            if done:
                break
        for entry in reversed(missed):
            await handle_audit_entry(entry, mongo, bot, recovered=True)
        _audit_state["pending"] = False
        if _audit_state["live_max"]:
            await store.advance_audit_cursor(_audit_state["live_max"])
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("Audit recovery unavailable (%s); missed audit entries are not replayed", exc)
        _audit_state["pending"] = False
        if _audit_state["live_max"]:
            try:
                await MemberEventStore(mongo.member_events).advance_audit_cursor(_audit_state["live_max"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Could not save the audit cursor", exc_info=True)


@loader.listener(hikari.BanDeleteEvent)
@lightbulb.di.with_di
async def unbanned(event: hikari.BanDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                   bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    if int(event.guild_id) != GUILD_ID:
        return
    try:
        store = MemberEventStore(mongo.member_events)
        await ensure_indexes(store)
        uid = int(event.user.id)
        episode = await store.ban_episode(GUILD_ID, uid, banned=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Could not advance a member ban episode")
        return
    try:
        await emit_unban(mongo, bot, uid, episode, at=datetime.now(timezone.utc), user=event.user)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive an unban")


def _text(value):
    return value if isinstance(value, str) and value else None


def extract_urls(content) -> list[str]:
    """Distinct http(s) URLs in order, trailing punctuation trimmed, bounded."""
    urls = []
    for match in URL_PATTERN.findall(content or ""):
        url = match.rstrip(")>.,")[:200]
        if len(url) > len("https://") and url not in urls:
            urls.append(url)
    return urls[:10]


def profile_changes(old, new) -> list[dict]:
    """Contract fields only; roles and timeouts are not profile changes."""
    old_user, new_user = old.user, new.user
    pairs = (
        ("nickname", old.nickname, new.nickname),
        ("username", old_user.username, new_user.username),
        ("global_name", getattr(old_user, "global_name", None), getattr(new_user, "global_name", None)),
        ("avatar", old_user.avatar_hash, new_user.avatar_hash),
        ("guild_avatar", getattr(old, "guild_avatar_hash", None), getattr(new, "guild_avatar_hash", None)),
        ("discriminator", getattr(old_user, "discriminator", None), getattr(new_user, "discriminator", None)),
    )
    changes = []
    for field, before, after in pairs:
        before, after = _text(before), _text(after)
        if before == after or (field == "discriminator" and after in (None, "0")):
            continue
        if field in ("avatar", "guild_avatar"):
            before = after = None  # Hashes are not shown; the card says "Changed".
        changes.append({"field": field, "before": before, "after": after})
    return changes


async def member_identity(bot, user_id: int):
    """Cached member first, one REST lookup second; never raises."""
    cache = getattr(bot, "cache", None)
    member = cache.get_member(GUILD_ID, user_id) if cache else None
    if member is None:
        try:
            member = await bot.rest.fetch_member(GUILD_ID, user_id)
        except Exception:
            member = None
    user = getattr(member, "user", None)
    username = _text(getattr(user, "username", None)) or str(user_id)
    return {
        "display_name": _text(getattr(member, "display_name", None))
        or _text(getattr(user, "global_name", None)) or username,
        "username": username,
        "joined_at": getattr(member, "joined_at", None),
        "avatar_url": avatar_source(GUILD_ID, user_id, getattr(user, "avatar_hash", None),
                                    getattr(member, "guild_avatar_hash", None)),
    }


async def record_extra(kind, mongo, bot, *, user_id, display_name, username, at, details,
                       settings=None, dedupe_key=None, audit_entry_id=None, moderator_id=None,
                       reason=None, joined_at=None, hold=False):
    """Capture and deliver one of the newer logs. No avatar bytes are stored.

    History kinds keep a row even when delivery is off; other rows are only
    delivery receipts, so they are not written unless delivery is on. ``hold``
    gives a near-simultaneous audit entry a second to enrich the unsent row.
    """
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    config = effective_event(settings or await store.settings(), kind)
    enabled = config["enabled"] and bool(config["channel_id"])
    if not enabled and kind not in HISTORY_TYPES:
        return None
    if _recovering.get():
        details = {**(details or {}), "recovered": True}
    if audit_entry_id is None:
        audit_entry_id = _audit_entry.get()  # Every row of an audit entry carries its id for the replay guard.
    row = await store.capture(
        guild_id=GUILD_ID, user_id=int(user_id), kind=kind, display_name=display_name,
        username=username, avatar=None, avatar_type=None, at=at, joined_at=joined_at,
        channel_id=int(config["channel_id"]) if enabled else None,
        forum_tag_id=int(config["forum_tag_id"]) if enabled and config.get("forum_tag_id") else None,
        reason=reason, moderator_id=moderator_id, audit_entry_id=audit_entry_id,
        details=details, dedupe_key=dedupe_key,
    )
    if not row:
        return None
    if hold:
        await asyncio.sleep(1)
    ready_row = await store.ready(row["_id"], enabled=enabled)
    if ready_row and enabled:
        await deliver_or_defer(store, bot, ready_row)
    return ready_row


async def record_timeout(entry, mongo, bot):
    change = next((c for c in entry.changes
                   if c.key == hikari.AuditLogChangeKey.COMMUNICATION_DISABLED_UNTIL), None)
    if change is None:
        return
    new, old, created = change.new_value, change.old_value, entry.created_at
    if isinstance(new, datetime) and new > created:
        kind = "timeout_add"
    elif old and not (isinstance(new, datetime) and new > created):
        kind = "timeout_remove"  # Cleared by a moderator; natural expiry has no audit entry.
    else:
        return
    uid = int(entry.target_id)
    who = await member_identity(bot, uid)
    details = {"avatar_url": who["avatar_url"]}
    if kind == "timeout_add":
        details["until"] = new.isoformat()
        details["duration_seconds"] = round((new - created).total_seconds() / 60) * 60
    await record_extra(
        kind, mongo, bot, user_id=uid, display_name=who["display_name"],
        username=who["username"], at=created, details=details,
        audit_entry_id=int(entry.id), moderator_id=entry.user_id, reason=entry.reason,
        joined_at=who["joined_at"],
    )


async def nickname_actor(bot, user_id: int, at: datetime):
    """Moderator or self named by the audit entry for this nickname change."""
    await asyncio.sleep(1)  # The audit entry can trail the member update.
    try:
        async for page in bot.rest.fetch_audit_log(
                GUILD_ID, event_type=hikari.AuditLogEventType.MEMBER_UPDATE):
            for entry in page.entries.values():
                if (entry.target_id and int(entry.target_id) == user_id and entry.user_id
                        and any(c.key == hikari.AuditLogChangeKey.NICK for c in entry.changes)
                        and abs((entry.created_at - at).total_seconds()) <= 15):
                    return str(entry.user_id)
            return None
    except Exception:
        log.info("Nickname audit lookup unavailable", exc_info=True)
    return None


async def record_profile_change(event, mongo, bot):
    if int(event.guild_id) != GUILD_ID or event.old_member is None:
        return
    changes = profile_changes(event.old_member, event.member)
    if not changes:
        return
    member = event.member
    uid, now = int(member.user.id), datetime.now(timezone.utc)
    actor = await nickname_actor(bot, uid, now) if any(c["field"] == "nickname" for c in changes) else None
    digest = hashlib.sha1(json.dumps(changes, sort_keys=True).encode()).hexdigest()[:12]
    await record_extra(
        "member_update", mongo, bot, user_id=uid,
        display_name=_text(member.display_name) or member.user.username,
        username=member.user.username, at=now,
        details={"changes": changes, "actor_id": actor,
                 "avatar_url": avatar_source(GUILD_ID, uid, member.user.avatar_hash,
                                             getattr(member, "guild_avatar_hash", None))},
        dedupe_key=f"{GUILD_ID}:member_update:{uid}:{digest}:{int(now.timestamp()) // 10}",
        joined_at=member.joined_at if isinstance(member.joined_at, datetime) else None,
    )


async def thread_parent_id(bot, channel_id: int):
    """Parent channel of a thread, else None. Plain channels' parent is a category."""
    cache = getattr(bot, "cache", None)
    channel = (cache.get_thread(channel_id) or cache.get_guild_channel(channel_id)) if cache else None
    if channel is None:
        try:
            channel = await bot.rest.fetch_channel(channel_id)
        except Exception:
            return None
    threads = (hikari.ChannelType.GUILD_PUBLIC_THREAD, hikari.ChannelType.GUILD_PRIVATE_THREAD,
               hikari.ChannelType.GUILD_NEWS_THREAD)
    return getattr(channel, "parent_id", None) if getattr(channel, "type", None) in threads else None


async def message_ignored(bot, settings, channel_id: int, role_ids=()) -> bool:
    """Staff ignore lists: a channel (or its thread parent) or an author role."""
    ignored_channels = set(settings["ignores"]["channel_ids"])
    if str(channel_id) in ignored_channels:
        return True
    if ignored_channels:
        parent = await thread_parent_id(bot, channel_id)
        if parent is not None and str(parent) in ignored_channels:
            return True
    return bool({str(role) for role in role_ids or ()} & set(settings["ignores"]["role_ids"]))


async def record_link(event, mongo, bot):
    message = event.message
    if message.guild_id is None or int(message.guild_id) != GUILD_ID:
        return
    author = message.author
    if getattr(author, "is_bot", False) or getattr(message, "webhook_id", None):
        return
    urls = extract_urls(message.content)
    if not urls:
        return
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    config = effective_event(settings, "link")
    if not (config["enabled"] and config["channel_id"]):
        return
    channel_id = int(message.channel_id)
    member = message.member
    if await message_ignored(bot, settings, channel_id, getattr(member, "role_ids", ())):
        return
    uid = int(author.id)
    username = _text(getattr(author, "username", None)) or str(uid)
    await record_extra(
        "link", mongo, bot, settings=settings, user_id=uid,
        display_name=_text(getattr(member, "display_name", None))
        or _text(getattr(author, "global_name", None)) or username,
        username=username, at=message.created_at,
        details={"channel_id": str(channel_id), "message_id": str(message.id),
                 "content": (message.content or "")[:500], "urls": urls,
                 "avatar_url": avatar_source(GUILD_ID, uid, getattr(author, "avatar_hash", None),
                                             getattr(member, "guild_avatar_hash", None))},
        dedupe_key=f"{GUILD_ID}:link:{message.id}",
        joined_at=getattr(member, "joined_at", None),
    )


def invite_row(invite, *, bot=None, vanity=False, now=None):
    inviter = getattr(invite, "inviter", None)
    channel = getattr(invite, "channel", None)
    channel_id = getattr(invite, "channel_id", None) or getattr(channel, "id", None)
    channel_name = getattr(channel, "name", None)
    cache = getattr(bot, "cache", None)
    if not channel_name and channel_id and cache:
        channel_name = getattr(cache.get_guild_channel(int(channel_id)), "name", None)
    return snapshot_row(
        GUILD_ID, invite.code, uses=getattr(invite, "uses", 0),
        max_uses=getattr(invite, "max_uses", None),
        inviter_id=getattr(inviter, "id", None),
        inviter_name=_text(getattr(inviter, "global_name", None)) or _text(getattr(inviter, "username", None)),
        channel_id=channel_id, channel_name=channel_name,
        expires_at=getattr(invite, "expires_at", None), vanity=vanity, now=now,
    )


async def fetch_invite_rows(bot):
    """Current invites and vanity URL as snapshot rows; raises when unreadable."""
    rows = []
    for invite in await bot.rest.fetch_guild_invites(GUILD_ID):
        if not hasattr(invite, "uses"):  # Without Manage Server, Discord omits counts.
            raise PermissionError("Invite use counts need the Manage Server permission")
        rows.append(invite_row(invite, bot=bot))
    try:
        vanity = await bot.rest.fetch_vanity_url(GUILD_ID)
    except (hikari.NotFoundError, hikari.ForbiddenError, hikari.BadRequestError):
        vanity = None
    if vanity is not None and vanity.code:
        rows.append(snapshot_row(GUILD_ID, vanity.code, uses=vanity.uses, max_uses=None, vanity=True))
    return rows


def invite_details(row: dict, names: dict, **extra) -> dict:
    return {
        "code": row["code"], "name": names.get(row["code"]), "vanity": bool(row.get("vanity")),
        "inviter_id": row.get("inviter_id"), "inviter_name": row.get("inviter_name"),
        "channel_id": row.get("channel_id"), "channel_name": row.get("channel_name"),
        "uses": row.get("uses"), "max_uses": row.get("max_uses"),
        "expires_at": row["expires_at"].isoformat() if isinstance(row.get("expires_at"), datetime) else None,
        **extra,
    }


async def refresh_invites(mongo, bot):
    async with _invite_lock:
        store = MemberInviteStore(mongo.member_invites)
        await store.ensure_indexes()
        await store.replace_all(GUILD_ID, await fetch_invite_rows(bot))


async def record_invite_create(event, mongo, bot):
    if int(event.guild_id) != GUILD_ID:
        return
    row = invite_row(event.invite, bot=bot)
    async with _invite_lock:
        await MemberInviteStore(mongo.member_invites).upsert(row)
    settings = await MemberEventStore(mongo.member_events).settings()
    created = getattr(event.invite, "created_at", None) or datetime.now(timezone.utc)
    await record_extra(
        "invite_create", mongo, bot, settings=settings, user_id=int(row["inviter_id"] or 0),
        display_name=row["code"], username=row["inviter_name"] or "", at=created,
        details=invite_details(row, settings["invite_names"]),
        dedupe_key=f"{GUILD_ID}:invite_create:{row['code']}:{int(created.timestamp())}",
    )


async def record_invite_delete(event, mongo, bot):
    if int(event.guild_id) != GUILD_ID:
        return
    store = MemberInviteStore(mongo.member_invites)
    async with _invite_lock:
        saved = await store.get(GUILD_ID, event.code)
        await store.delete(GUILD_ID, event.code)
    row = saved or (invite_row(event.old_invite, bot=bot) if event.old_invite else
                    snapshot_row(GUILD_ID, event.code, uses=0, max_uses=None,
                                 channel_id=event.channel_id))
    settings = await MemberEventStore(mongo.member_events).settings()
    now = datetime.now(timezone.utc)
    await record_extra(
        "invite_delete", mongo, bot, settings=settings, user_id=0,
        display_name=event.code, username="", at=now,
        details=invite_details(row, settings["invite_names"]),
        dedupe_key=f"{GUILD_ID}:invite_delete:{event.code}:{int(now.timestamp()) // 10}",
    )


def _invite_future(uid: int):
    """One future per joining user; whichever of join or invite-use runs first creates it."""
    loop = asyncio.get_running_loop()
    future = _invite_waits.get(uid)
    if future is None:
        future = _invite_waits[uid] = loop.create_future()
        _invite_born[uid] = loop.time()
        loop.call_later(30, lambda: _drop_invite(uid) if _invite_waits.get(uid) is future else None)
    return future


def _drop_invite(uid: int):
    _invite_waits.pop(uid, None)
    _invite_born.pop(uid, None)


def discard_stale_invite(uid: int):
    """A new join must not read the previous join's label; keep a fresh one set for this join."""
    future = _invite_waits.get(uid)
    if future is not None and future.done() and (
            asyncio.get_running_loop().time() - _invite_born.get(uid, 0)) > INVITE_STALE_SECONDS:
        _drop_invite(uid)


def settle_invite_label(uid: int, label: str | None):
    future = _invite_future(uid)
    if not future.done():
        future.set_result(label)


async def wait_invite_label(uid: int, wanted: bool = True) -> str | None:
    """Invite name or code for this join, if attribution finishes within the wait."""
    if not wanted:
        _drop_invite(uid)
        return None
    future = _invite_future(uid)
    try:
        return await asyncio.wait_for(asyncio.shield(future), INVITE_WAIT_SECONDS)
    except TimeoutError:
        return None
    finally:
        if _invite_waits.get(uid) is future:
            _drop_invite(uid)


async def record_invite_use(event, mongo, bot):
    member = event.member
    if int(member.guild_id) != GUILD_ID:
        return
    try:
        await _record_invite_use(event, mongo, bot)
    finally:
        settle_invite_label(int(member.user.id), None)  # No effect once a label was set.


async def _record_invite_use(event, mongo, bot):
    member = event.member
    store = MemberInviteStore(mongo.member_invites)
    before, after, unavailable = {}, {}, False
    async with _invite_lock:
        before = await store.load(GUILD_ID)
        try:
            rows = await fetch_invite_rows(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Invite attribution unavailable (%s); posting Unknown invite", exc)
            unavailable = True
        else:
            after = {row["code"]: row for row in rows}
            await store.replace_all(GUILD_ID, rows)
    code = None if unavailable else attribute_join(before, after)
    settings = await MemberEventStore(mongo.member_events).settings()
    uid, now = int(member.user.id), datetime.now(timezone.utc)
    settle_invite_label(uid, str(settings["invite_names"].get(code) or code)[:40] if code else None)
    if code:
        matched = dict(after.get(code) or before[code])
        if code not in after:  # Spent its last use on this join.
            matched["uses"] = int(matched.get("uses") or 0) + 1
        details = invite_details(matched, settings["invite_names"], unknown=False)
    else:
        details = {"unknown": True}
    details["avatar_url"] = avatar_source(GUILD_ID, uid, getattr(member.user, "avatar_hash", None),
                                          getattr(member, "guild_avatar_hash", None))
    joined_at = member.joined_at if isinstance(member.joined_at, datetime) else None
    await record_extra(
        "invite_use", mongo, bot, settings=settings, user_id=uid,
        display_name=_text(member.display_name) or member.user.username,
        username=member.user.username, at=now, details=details, joined_at=joined_at,
        dedupe_key=event_key(GUILD_ID, uid, "invite_use", now, joined_at),
    )


_bot_users: dict[int, str | None] = {}  # Fetched answers (bot name, None for a human); a failed lookup is not cached.


def _bot_name(user, uid: int) -> str:
    return _text(getattr(user, "global_name", None)) or _text(getattr(user, "username", None)) or str(uid)


async def bot_actor(bot, user_id) -> str | None:
    """Name of the bot account per cache, else one fetch; None for humans and unknowns."""
    if not user_id:
        return None
    uid = int(user_id)
    cache = getattr(bot, "cache", None)
    cached = cache.get_user(uid) if cache and hasattr(cache, "get_user") else None
    if cached is not None:
        return _bot_name(cached, uid) if getattr(cached, "is_bot", False) else None
    if uid not in _bot_users:
        try:
            user = await bot.rest.fetch_user(uid)
            _bot_users[uid] = _bot_name(user, uid) if user.is_bot else None
        except Exception:
            return None
        if len(_bot_users) > 500:
            _bot_users.pop(next(iter(_bot_users)))
    return _bot_users[uid]


async def own_bot_id(bot) -> str | None:
    me = bot.get_me() if hasattr(bot, "get_me") else None
    if me is None:
        try:
            me = await bot.rest.fetch_my_user()
        except Exception:
            return None
    return str(me.id) if getattr(me, "id", None) else None


async def actor_ignored(bot, store, settings, user_id) -> bool:
    """True when the audit actor is a bot staff chose to ignore (default: this bot).

    Every bot seen as an actor is remembered so staff can pick it in the dashboard.
    """
    name = await bot_actor(bot, user_id)
    if name is None:
        return False
    try:
        await store.note_bot_actor(user_id, name)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("Could not remember a bot actor", exc_info=True)
    ignored = settings.get("ignored_bot_ids")
    if not isinstance(ignored, list):
        ignored = resolve_ignored_bots(settings, await own_bot_id(bot))
    return str(user_id) in ignored


def _enabled(settings, kind) -> bool:
    config = effective_event(settings, kind)
    return bool(config["enabled"] and config["channel_id"])


def _brief(value):
    """Short text for an audit value; None for structures shown as 'Changed'."""
    if value is None or isinstance(value, (dict, list, tuple, set, frozenset)) or hasattr(value, "values"):
        return None
    if isinstance(value, enum.Enum):
        return value.name.replace("_", " ").title()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)[:100]


def audit_changes(entry, *, drop=("position",)) -> list[dict]:
    changes = []
    for change in entry.changes:
        field = str(getattr(change.key, "value", change.key)).lower()
        if field in drop:
            continue
        changes.append({"field": field, "before": _brief(change.old_value), "after": _brief(change.new_value)})
    return changes[:8]


def _roles_named(value) -> list[str]:
    items = value.values() if hasattr(value, "values") else (value or ())
    return [str(getattr(item, "name", None) or "Unknown role")[:60] for item in items][:15]


async def user_identity(bot, user_id: int, user=None):
    """Public identity for someone who may not be in the guild (for example, unbanned)."""
    if user is None:
        cache = getattr(bot, "cache", None)
        user = cache.get_user(user_id) if cache and hasattr(cache, "get_user") else None
    if user is None:
        try:
            user = await bot.rest.fetch_user(user_id)
        except Exception:
            user = None
    username = _text(getattr(user, "username", None)) or str(user_id)
    return {"display_name": _text(getattr(user, "global_name", None)) or username, "username": username,
            "avatar_url": avatar_source(GUILD_ID, user_id, getattr(user, "avatar_hash", None))}


# Audit-sourced guild-object logs: action type -> (event kind, action word on the card).
_A = hikari.AuditLogEventType
AUDIT_KINDS = {
    _A.ROLE_CREATE: ("role_create", "created"), _A.ROLE_UPDATE: ("role_update", "updated"),
    _A.ROLE_DELETE: ("role_delete", "deleted"),
    _A.CHANNEL_CREATE: ("channel_create", "created"), _A.CHANNEL_UPDATE: ("channel_update", "updated"),
    _A.CHANNEL_DELETE: ("channel_delete", "deleted"),
    _A.CHANNEL_OVERWRITE_CREATE: ("channel_permissions", "added"),
    _A.CHANNEL_OVERWRITE_UPDATE: ("channel_permissions", "changed"),
    _A.CHANNEL_OVERWRITE_DELETE: ("channel_permissions", "removed"),
    _A.THREAD_DELETE: ("thread_delete", "deleted"), _A.THREAD_UPDATE: ("thread_lock", "locked"),
    _A.GUILD_UPDATE: ("server_update", "updated"),
    _A.EMOJI_CREATE: ("emoji", "added"), _A.EMOJI_UPDATE: ("emoji", "changed"),
    _A.EMOJI_DELETE: ("emoji", "removed"),
    _A.STICKER_CREATE: ("sticker", "added"), _A.STICKER_UPDATE: ("sticker", "changed"),
    _A.STICKER_DELETE: ("sticker", "removed"),
    _A.BOT_ADD: ("app", "added"), _A.INTEGRATION_CREATE: ("app", "added"),
    _A.INTEGRATION_UPDATE: ("app", "changed"), _A.INTEGRATION_DELETE: ("app", "removed"),
    _A.WEBHOOK_CREATE: ("webhook", "added"), _A.WEBHOOK_UPDATE: ("webhook", "changed"),
    _A.WEBHOOK_DELETE: ("webhook", "removed"),
    _A.AUTO_MODERATION_RULE_CREATE: ("automod", "added"), _A.AUTO_MODERATION_RULE_UPDATE: ("automod", "changed"),
    _A.AUTO_MODERATION_RULE_DELETE: ("automod", "removed"),
}
_C = hikari.AuditLogChangeKey


def audit_object_name(entry, bot, kind: str) -> str:
    for change in entry.changes:
        if change.key == _C.NAME:
            value = change.new_value or change.old_value
            if isinstance(value, str) and value:
                return value
    cache = getattr(bot, "cache", None)
    target, found = int(entry.target_id), None
    if cache:
        if kind.startswith("role"):
            found = cache.get_role(target)
        elif kind.startswith(("channel", "thread")):
            found = cache.get_thread(target) or cache.get_guild_channel(target)
        elif kind == "app":
            found = cache.get_user(target)
        elif kind == "server_update":
            found = cache.get_guild(GUILD_ID)
    return str(getattr(found, "name", None) or getattr(found, "username", None) or "")


def _application_id(entry):
    if entry.action_type == _A.BOT_ADD:
        return str(entry.target_id)
    change = next((c for c in entry.changes if c.key == _C.APPLICATION_ID), None)
    value = (change.new_value or change.old_value) if change else None
    return str(value) if value else None


def _app_add_seen(entry) -> bool:
    """True when this entry repeats an app add already posted: BOT_ADD and INTEGRATION_CREATE pair up."""
    now = time.monotonic()
    _recent_app_adds[:] = [a for a in _recent_app_adds if now - a["at"] <= APP_ADD_WINDOW_SECONDS]
    app_id = _application_id(entry)
    others = [a for a in _recent_app_adds if a["type"] != entry.action_type and not a["matched"]]
    same = [a for a in others if a["app_id"] and app_id and a["app_id"] == app_id]
    if not same and (app_id is None or any(a["app_id"] is None for a in others)) and len(others) == 1:
        same = others  # No id on one side: a lone entry of the other type in the window is the same app.
    if same:
        same[0]["matched"] = True
        return True
    _recent_app_adds.append({"at": now, "type": entry.action_type, "app_id": app_id, "matched": False})
    return False


async def record_audit_kind(entry, mongo, bot) -> bool:
    """Roles, channels, threads and server logs from one audit entry. False when not ours."""
    spec = AUDIT_KINDS.get(entry.action_type)
    if spec is None:
        return False
    kind, action = spec
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    if not _enabled(settings, kind):
        return True
    if not (kind == "app" and action == "added") and await actor_ignored(bot, store, settings, entry.user_id):
        return True  # Only ignored bots are skipped; adding an app always posts.
    details = {"action": action, "target_id": str(entry.target_id)}
    if kind == "app" and action == "added":
        details["application_id"] = _application_id(entry)
        if details["application_id"] and await store.app_add_posted(
                GUILD_ID, details["application_id"], entry.created_at, APP_ADD_STORED_WINDOW):
            return True  # The pair was posted before a restart or in another order.
        if _app_add_seen(entry):
            return True  # BOT_ADD and INTEGRATION_CREATE both describe one new app.
    if kind == "thread_lock":
        locked = [c for c in entry.changes if c.key in (_C.LOCKED, _C.ARCHIVED) and c.new_value is True]
        if not locked:
            return True  # Reopened, renamed or auto-archived threads are not lock events.
        details["action"] = "locked" if any(c.key == _C.LOCKED for c in locked) else "archived"
    elif action in ("updated", "changed"):
        changes = audit_changes(entry)
        if kind in ("role_update", "channel_update") and not changes:
            return True  # Position-only moves are noise.
        details["changes"] = changes
    if kind == "channel_permissions":
        options = entry.options
        subject = str(getattr(getattr(options, "type", None), "name", getattr(options, "type", ""))).lower()
        details["subject_type"] = "role" if "role" in subject else "member" if "member" in subject else None
        details["subject_id"] = str(getattr(options, "id", "") or "") or None
        details["subject_name"] = _text(getattr(options, "role_name", None))
    await record_extra(
        kind, mongo, bot, settings=settings, user_id=0, display_name=audit_object_name(entry, bot, kind),
        username="", at=entry.created_at, details=details, audit_entry_id=int(entry.id),
        moderator_id=entry.user_id, reason=entry.reason,
    )
    return True


async def record_member_roles(entry, mongo, bot):
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    if await actor_ignored(bot, store, settings, entry.user_id):
        return
    uid = int(entry.target_id)
    for key, kind in ((_C.ADD_ROLE_TO_MEMBER, "roles_added"), (_C.REMOVE_ROLE_FROM_MEMBER, "roles_removed")):
        change = next((c for c in entry.changes if c.key == key), None)
        names = _roles_named(change.new_value if change else None)
        if not names:
            continue
        who = await member_identity(bot, uid)
        await record_extra(
            kind, mongo, bot, settings=settings, user_id=uid, display_name=who["display_name"],
            username=who["username"], at=entry.created_at,
            details={"roles": names, "avatar_url": who["avatar_url"]},
            dedupe_key=f"{GUILD_ID}:audit:{entry.id}:{kind}", moderator_id=entry.user_id,
            joined_at=who["joined_at"],
        )


_bot_unbans: set = set()  # (user id, ban episode) whose unban audit entry came from an ignored bot.


async def emit_unban(mongo, bot, uid: int, episode: int, *, at, user=None, entry=None):
    """Post an unban once; the gateway event and its audit entry may come in either order.

    A handled-entry marker (not the row) makes a replay or duplicate of that entry skip.
    """
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    if entry is not None and await store.audit_handled(GUILD_ID, entry.id):
        return
    key = f"{GUILD_ID}:unban:{uid}:{episode}"
    settings = await store.settings()
    if entry is not None and await actor_ignored(bot, store, settings, entry.user_id):
        _bot_unbans.add((uid, episode))
        await store.discard_unsent(key)
        return
    if (uid, episode) in _bot_unbans:
        return
    moderator = int(entry.user_id) if entry is not None and entry.user_id else None
    reason = entry.reason if entry is not None else None
    if entry is not None and await store.enrich_unban(key, moderator, reason, int(entry.id)):
        return
    who = await user_identity(bot, uid, user)
    row = await record_extra(
        "unban", mongo, bot, settings=settings, user_id=uid, display_name=who["display_name"],
        username=who["username"], at=at, dedupe_key=key, moderator_id=moderator, reason=reason,
        details={"avatar_url": who["avatar_url"]}, hold=entry is None,
        audit_entry_id=int(entry.id) if entry is not None else None,
    )
    return row


_recent_deletes: collections.deque = collections.deque(maxlen=200)  # Audit MESSAGE_DELETE facts.
_delete_counts: collections.OrderedDict = collections.OrderedDict()  # Audit entry id -> last count seen.
_recent_bulk: collections.deque = collections.deque(maxlen=50)  # Audit MESSAGE_BULK_DELETE facts.


def note_message_audit(entry):
    options = getattr(entry, "options", None)
    channel = getattr(options, "channel_id", None)
    if entry.action_type == hikari.AuditLogEventType.MESSAGE_DELETE:
        try:
            total = max(1, int(getattr(options, "count", None) or 1))
        except (TypeError, ValueError):
            total = 1
        entry_id = int(entry.id)
        uses = max(0, total - _delete_counts.get(entry_id, 0))  # Discord's count is a running total.
        _delete_counts[entry_id] = total
        _delete_counts.move_to_end(entry_id)
        while len(_delete_counts) > 500:
            _delete_counts.popitem(last=False)
        if uses == 0:
            return
        _recent_deletes.append([int(entry.target_id), int(channel or 0), entry.user_id, entry.created_at, uses])
    else:
        _recent_bulk.append([int(entry.target_id), 0, entry.user_id, entry.created_at, 1])


async def audit_moderator(facts, target: int, channel: int = 0):
    """Moderator of a message delete from recent audit facts; None when unsure.

    A fact attributes at most as many deletes as its entry counted, so a later
    self-delete by the same author is never credited to the moderator.
    """
    await asyncio.sleep(1)  # The audit entry can trail the gateway event.
    now = datetime.now(timezone.utc)
    for fact in reversed(facts):
        known_target, known_channel, moderator, created, remaining = fact
        if (remaining > 0 and known_target == target and (not channel or known_channel == channel)
                and abs((now - created.replace(tzinfo=created.tzinfo or timezone.utc)).total_seconds()) <= 10):
            fact[4] = remaining - 1
            return str(moderator) if moderator else None
    return None


def attachment_info(message) -> list[dict]:
    return [{"name": str(getattr(a, "filename", "") or "File")[:80],
             "type": str(getattr(a, "media_type", None) or "unknown")[:40]}
            for a in (getattr(message, "attachments", None) or ())][:10]


def _human_message(message) -> bool:
    return not (getattr(message.author, "is_bot", False) or getattr(message, "webhook_id", None))


async def record_message_delete(event, mongo, bot):
    message = event.old_message
    if message is None or int(event.guild_id) != GUILD_ID or not _human_message(message):
        return  # Uncached messages are never logged.
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    channel_id = int(event.channel_id)
    member = getattr(message, "member", None)
    if not _enabled(settings, "message_delete") or await message_ignored(
            bot, settings, channel_id, getattr(member, "role_ids", ())):
        return
    author = message.author
    uid, username = int(author.id), _text(getattr(author, "username", None)) or str(author.id)
    moderator = await audit_moderator(_recent_deletes, uid, channel_id)
    await record_extra(
        "message_delete", mongo, bot, settings=settings, user_id=uid,
        display_name=_text(getattr(member, "display_name", None)) or _text(getattr(author, "global_name", None)) or username,
        username=username, at=datetime.now(timezone.utc), moderator_id=moderator,
        details={"channel_id": str(channel_id), "message_id": str(message.id),
                 "content": (message.content or "")[:500], "attachments": attachment_info(message),
                 "avatar_url": avatar_source(GUILD_ID, uid, getattr(author, "avatar_hash", None),
                                             getattr(member, "guild_avatar_hash", None))},
        dedupe_key=f"{GUILD_ID}:message_delete:{message.id}",
        joined_at=getattr(member, "joined_at", None),
    )


async def record_message_edit(event, mongo, bot):
    old = event.old_message
    content = event.content
    if old is None or int(event.guild_id) != GUILD_ID or content is hikari.UNDEFINED or not _human_message(old):
        return
    after, before = content or "", old.content or ""
    if after == before:
        return  # Embed unfurls and pin changes arrive as updates too.
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    channel_id = int(event.channel_id)
    member = getattr(old, "member", None) or getattr(event, "member", None)
    if not _enabled(settings, "message_edit") or await message_ignored(
            bot, settings, channel_id, getattr(member, "role_ids", ())):
        return
    author = old.author
    uid, username = int(author.id), _text(getattr(author, "username", None)) or str(author.id)
    digest = hashlib.sha1(after.encode()).hexdigest()[:12]
    await record_extra(
        "message_edit", mongo, bot, settings=settings, user_id=uid,
        display_name=_text(getattr(member, "display_name", None)) or _text(getattr(author, "global_name", None)) or username,
        username=username, at=datetime.now(timezone.utc),
        details={"channel_id": str(channel_id), "message_id": str(old.id), "before": before[:500],
                 "after": after[:500], "attachments": attachment_info(old),
                 "avatar_url": avatar_source(GUILD_ID, uid, getattr(author, "avatar_hash", None),
                                             getattr(member, "guild_avatar_hash", None))},
        dedupe_key=f"{GUILD_ID}:message_edit:{old.id}:{digest}",
        joined_at=getattr(member, "joined_at", None),
    )


TRANSCRIPT_LIMIT = 200 * 1024


def build_transcript(messages) -> str:
    """Cached human messages, oldest first, capped at 200 KB of UTF-8 including the marker."""
    marker = "[transcript truncated]"
    lines, size = [], 0
    for message in sorted(messages, key=lambda m: int(m.id)):
        if not _human_message(message):
            continue
        files = ", ".join(a["name"] for a in attachment_info(message))
        line = (f"[{message.created_at:%Y-%m-%d %H:%M:%S} UTC] {getattr(message.author, 'username', 'unknown')} "
                f"({message.author.id}): {(message.content or '').replace(chr(10), ' / ')}"
                + (f" [files: {files}]" if files else ""))
        size += len(line.encode("utf-8")) + 1
        if size > TRANSCRIPT_LIMIT - len(marker) - 1:
            lines.append(marker)
            break
        lines.append(line)
    return "\n".join(lines)


async def record_bulk_delete(event, mongo, bot):
    if int(event.guild_id) != GUILD_ID:
        return
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    settings = await store.settings()
    channel_id = int(event.channel_id)
    if not _enabled(settings, "message_bulk_delete") or await message_ignored(bot, settings, channel_id):
        return
    moderator = await audit_moderator(_recent_bulk, channel_id)
    details = {"channel_id": str(channel_id), "count": len(event.message_ids)}
    transcript = build_transcript((event.old_messages or {}).values())
    if transcript:
        details["transcript"] = transcript
    cache = getattr(bot, "cache", None)
    channel = cache.get_guild_channel(channel_id) if cache and hasattr(cache, "get_guild_channel") else None
    await record_extra(
        "message_bulk_delete", mongo, bot, settings=settings, user_id=0,
        display_name=_text(getattr(channel, "name", None)) or "Channel", username="",
        at=datetime.now(timezone.utc), details=details, moderator_id=moderator,
        dedupe_key=f"{GUILD_ID}:message_bulk_delete:{channel_id}:{min(int(i) for i in event.message_ids)}:{details['count']}"
        if event.message_ids else None,
    )


def _safely(action, failure):
    """Listener wrapper: a log failure must never reach the gateway dispatcher."""
    async def run(event, mongo, bot):
        try:
            await action(event, mongo, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(failure)
    return run


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def invites_started(event: hikari.StartedEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                          bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    try:
        await refresh_invites(mongo, bot)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("Invite snapshot unavailable (%s); invite uses will read Unknown invite", exc)
    global _audit_task  # After the snapshot; a background task never delays other startup work.
    _audit_task = asyncio.create_task(recover_audit(mongo, bot), name="member-events-audit-recover")


@loader.listener(hikari.MemberUpdateEvent)
@lightbulb.di.with_di
async def profile_changed(event: hikari.MemberUpdateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                          bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_profile_change, "Failed to archive a profile change")(event, mongo, bot)


@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def link_posted(event: hikari.GuildMessageCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                      bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_link, "Failed to log a posted link")(event, mongo, bot)


@loader.listener(hikari.InviteCreateEvent)
@lightbulb.di.with_di
async def invite_created(event: hikari.InviteCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                         bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_invite_create, "Failed to log an invite creation")(event, mongo, bot)


@loader.listener(hikari.InviteDeleteEvent)
@lightbulb.di.with_di
async def invite_deleted(event: hikari.InviteDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                         bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_invite_delete, "Failed to log an invite deletion")(event, mongo, bot)


@loader.listener(hikari.MemberCreateEvent)
@lightbulb.di.with_di
async def invite_used(event: hikari.MemberCreateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                      bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_invite_use, "Failed to log an invite use")(event, mongo, bot)


@loader.listener(hikari.GuildMessageDeleteEvent)
@lightbulb.di.with_di
async def message_deleted(event: hikari.GuildMessageDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                          bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_message_delete, "Failed to log a deleted message")(event, mongo, bot)


@loader.listener(hikari.GuildMessageUpdateEvent)
@lightbulb.di.with_di
async def message_edited(event: hikari.GuildMessageUpdateEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                         bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_message_edit, "Failed to log an edited message")(event, mongo, bot)


@loader.listener(hikari.GuildBulkMessageDeleteEvent)
@lightbulb.di.with_di
async def messages_bulk_deleted(event: hikari.GuildBulkMessageDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                                bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    await _safely(record_bulk_delete, "Failed to log a bulk delete")(event, mongo, bot)
