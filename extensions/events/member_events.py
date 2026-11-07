"""Discord gateway transport for durable member and moderation history."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import aiohttp
import hikari
import lightbulb
from utils.member_events import (
    DEFAULT_CHANNEL_ID, GUILD_ID, HISTORY_TYPES, MAX_AVATAR_BYTES, MemberEventStore,
    avatar_source, effective_permissions, event_key, safe_text,
)
from utils.member_event_cards import avatar_filename, build_card, build_forum_message
from utils.member_event_settings import effective_event
from utils.member_invites import MemberInviteStore, attribute_join, snapshot_row
from utils.mongo import MongoClient

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
CHANNEL_ID = DEFAULT_CHANNEL_ID  # Kept for existing imports and deployment checks.
_start_task = None
_indexes_ready = False
_index_lock = asyncio.Lock()
_invite_lock = asyncio.Lock()  # One join diff at a time; create/delete share it.
URL_PATTERN = re.compile(r"https?://\S+")
FORUM_LABELS = {"join": "Joined", "leave": "Left", "kick": "Kicked", "ban": "Banned",
                "timeout_add": "Timed out", "timeout_remove": "Timeout removed",
                "member_update": "Profile changed", "link": "Link",
                "invite_create": "Invite created", "invite_delete": "Invite deleted",
                "invite_use": "Invite used"}


async def ensure_indexes(store):
    global _indexes_ready
    async with _index_lock:
        if not _indexes_ready:
            await store.ensure_indexes()
            _indexes_ready = True


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
    if filename:
        message["attachments"] = [{"id": 0, "filename": filename}]
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        form.add_field("files[0]", row["avatar"], filename=filename,
                       content_type=row["avatar_type"])
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
    row = await store.capture(
        guild_id=GUILD_ID, user_id=uid, kind=kind,
        display_name=display_name, username=username, avatar=None, avatar_type=None,
        at=now, joined_at=joined_at, channel_id=channel_id,
        forum_tag_id=forum_tag_id, reason=reason, moderator_id=moderator_id,
        audit_entry_id=audit_entry_id, episode=episode,
        account_created_at=account_created_at, member_count=member_count,
        roles=roles,
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
    ready_row = await store.ready(row["_id"], enabled=enabled)
    if ready_row and kind == "leave":
        await store.enrich_recent_kick(GUILD_ID, uid, now, ready_row["display_name"],
                                       ready_row["username"], ready_row.get("joined_at"),
                                       ready_row.get("avatar"), ready_row.get("avatar_type"),
                                       roles=ready_row.get("roles"))
    if ready_row and enabled:
        await deliver(store, bot, ready_row)


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
    if _start_task:
        _start_task.cancel()
        try:
            await _start_task
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
    entry = event.entry
    if int(entry.guild_id) != GUILD_ID or not entry.target_id:
        return
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
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to archive or enrich a moderation audit entry")


@loader.listener(hikari.BanDeleteEvent)
@lightbulb.di.with_di
async def unbanned(event: hikari.BanDeleteEvent, mongo: MongoClient = lightbulb.di.INJECTED):
    if int(event.guild_id) != GUILD_ID:
        return
    try:
        store = MemberEventStore(mongo.member_events)
        await ensure_indexes(store)
        await store.ban_episode(GUILD_ID, int(event.user.id), banned=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Could not advance a member ban episode")


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
                       reason=None, joined_at=None):
    """Capture and deliver one of the newer logs. No avatar bytes are stored.

    History kinds keep a row even when delivery is off; link and invite rows are
    only delivery receipts, so they are not written unless delivery is on.
    """
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    config = effective_event(settings or await store.settings(), kind)
    enabled = config["enabled"] and bool(config["channel_id"])
    if not enabled and kind not in HISTORY_TYPES:
        return None
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
    ready_row = await store.ready(row["_id"], enabled=enabled)
    if ready_row and enabled:
        await deliver(store, bot, ready_row)
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
    ignored_channels = set(settings["ignores"]["channel_ids"])
    channel_id = int(message.channel_id)
    if str(channel_id) in ignored_channels:
        return
    if ignored_channels:
        parent = await thread_parent_id(bot, channel_id)
        if parent is not None and str(parent) in ignored_channels:
            return
    member = message.member
    if {str(role) for role in getattr(member, "role_ids", ())} & set(settings["ignores"]["role_ids"]):
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


async def record_invite_use(event, mongo, bot):
    member = event.member
    if int(member.guild_id) != GUILD_ID:
        return
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
