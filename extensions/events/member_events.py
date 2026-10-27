"""Discord gateway transport for durable member and moderation history."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aiohttp
import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container
from hikari.impl import SectionComponentBuilder as Section
from hikari.impl import TextDisplayComponentBuilder as Text
from hikari.impl import ThumbnailComponentBuilder as Thumbnail

from utils.member_events import (
    DEFAULT_CHANNEL_ID, GUILD_ID, MAX_AVATAR_BYTES, MemberEventStore,
    avatar_source, effective_permissions, safe_text,
)
from utils.mongo import MongoClient

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
CHANNEL_ID = DEFAULT_CHANNEL_ID  # Kept for existing imports and deployment checks.
_start_task = None
_indexes_ready = False
_index_lock = asyncio.Lock()


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


def event_lines(row):
    labels = {"join": "↗ Joined", "leave": "↘ Left", "kick": "⚠ Kicked", "ban": "⛔ Banned"}
    name = safe_text(row.get("display_name")) or "Unknown member"
    username = safe_text(row.get("username")) or "unknown"
    uid = int(row["user_id"])
    occurred = row["occurred_at"]
    stamp = int(occurred.replace(tzinfo=occurred.tzinfo or timezone.utc).timestamp())
    lines = [f"**{labels[row['event_type']]}** · <t:{stamp}:R>", f"**{name}** · @{username}"]
    joined_at = row.get("joined_at")
    if isinstance(joined_at, datetime):
        joined_stamp = int(joined_at.replace(tzinfo=joined_at.tzinfo or timezone.utc).timestamp())
        label = "Last known join" if row["event_type"] in ("kick", "ban") else "Joined server"
        lines.append(f"{label}: <t:{joined_stamp}:D> · <t:{joined_stamp}:R>")
    else:
        lines.append("Joined server: date unavailable")
    if row.get("moderator_id"):
        lines.append(f"Moderator ID: `{int(row['moderator_id'])}`")
    if row.get("reason"):
        lines.append(f"Reason: {safe_text(row['reason'], 500)}")
    lines.append(f"ID: `{uid}` · [Profile](https://discord.com/users/{uid})")
    return lines


def accent(kind):
    return {"join": 0x2BA66A, "leave": 0xD34A4A,
            "kick": 0xE69935, "ban": 0xA8384B}[kind]


def avatar_filename(row):
    if not row.get("avatar"):
        return None
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                 "image/webp": "webp"}[row["avatar_type"]]
    return f"member-avatar.{extension}"


def components(row):
    body = Text(content="\n".join(event_lines(row)))
    filename = avatar_filename(row)
    if filename:
        section = Section(components=[body], accessory=Thumbnail(
            media=f"attachment://{filename}", description="Saved member avatar"))
        return [Container(accent_color=accent(row["event_type"]), components=[section])], [
            hikari.Bytes(row["avatar"], filename, row["avatar_type"])]
    return [Container(accent_color=accent(row["event_type"]), components=[body])], []


def forum_message(row):
    """Forum starters use documented embed fields; V2 flags are unverified there."""
    filename = avatar_filename(row)
    embed = {"description": "\n".join(event_lines(row)),
             "color": accent(row["event_type"])}
    if filename:
        embed["thumbnail"] = {"url": f"attachment://{filename}"}
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


async def post_card(row, *, forum=False):
    """One HTTP attempt for either message or forum thread creation."""
    channel_id = int(row["channel_id"])
    filename = avatar_filename(row)
    if forum:
        label = {"join": "Joined", "leave": "Left", "kick": "Kicked", "ban": "Banned"}[row["event_type"]]
        occurred = row["occurred_at"].replace(tzinfo=row["occurred_at"].tzinfo or timezone.utc)
        date = occurred.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        suffix = f" · {row['user_id']} · {date}"
        name_budget = max(1, 100 - len(label) - len(suffix) - 3)
        title = f"{label} · {safe_text(row['display_name'], name_budget)}{suffix}"
        payload = {"name": title[:100], "message": forum_message(row)}
        if row.get("forum_tag_id"):
            payload["applied_tags"] = [str(row["forum_tag_id"])]
        endpoint = f"https://discord.com/api/v10/channels/{channel_id}/threads"
        message = payload["message"]
    else:
        cards, _ = components(row)
        payload = {"flags": int(hikari.MessageFlag.IS_COMPONENTS_V2),
                   "components": [card.build()[0] for card in cards],
                   "allowed_mentions": {"parse": []}}
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
    current = (await store.settings())["events"][row["event_type"]]
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
    episode = (episode_override if episode_override is not None else
               await store.ban_episode(GUILD_ID, uid, banned=True)) if kind == "ban" else None
    pending_audit = (await store.pending_ban_audit(GUILD_ID, uid, now)
                     if kind == "ban" and audit_entry_id is None else None)
    if pending_audit:
        moderator_id = moderator_id or pending_audit.get("moderator_id")
        reason = reason or pending_audit.get("reason")
        audit_entry_id = int(pending_audit["_id"].rsplit(":", 1)[1])
    settings = await store.settings()
    config = settings["events"][kind]
    enabled = config["enabled"] and bool(config["channel_id"])
    channel_id = int(config["channel_id"]) if enabled else None
    forum_tag_id = int(config["forum_tag_id"]) if enabled and config.get("forum_tag_id") else None
    row = await store.capture(
        guild_id=GUILD_ID, user_id=uid, kind=kind,
        display_name=display_name, username=username, avatar=None, avatar_type=None,
        at=now, joined_at=joined_at, channel_id=channel_id,
        forum_tag_id=forum_tag_id, reason=reason, moderator_id=moderator_id,
        audit_entry_id=audit_entry_id, episode=episode,
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
            )
    if kind == "ban":
        # Give a near-simultaneous audit entry a chance to enrich the queued card.
        await asyncio.sleep(1)
    ready_row = await store.ready(row["_id"], enabled=enabled)
    if ready_row and kind == "leave":
        await store.enrich_recent_kick(GUILD_ID, uid, now, ready_row["display_name"],
                                       ready_row["username"], ready_row.get("joined_at"),
                                       ready_row.get("avatar"), ready_row.get("avatar_type"))
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
