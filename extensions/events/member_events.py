"""Discord gateway transport for the permanent staff member event archive."""
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

from utils.member_events import GUILD_ID, MAX_AVATAR_BYTES, MemberEventStore, avatar_source, safe_text
from utils.mongo import MongoClient

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
CHANNEL_ID = 1004519991648997447
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


def components(row):
    kind = row["event_type"]
    heading = "↗ Joined" if kind == "join" else "↘ Left"
    color = 0x2BA66A if kind == "join" else 0xD34A4A
    name = safe_text(row["display_name"]) or "Unknown member"
    username = safe_text(row["username"]) or "unknown"
    uid = int(row["user_id"])
    stamp = int(row["occurred_at"].timestamp())
    body = Text(content=f"**{heading}** · <t:{stamp}:f>\n**{name}** · @{username}\nID: `{uid}` · [Profile](https://discord.com/users/{uid})")
    if row.get("avatar"):
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}[row["avatar_type"]]
        filename = f"member-avatar.{extension}"
        section = Section(components=[body], accessory=Thumbnail(media=f"attachment://{filename}", description="Saved member avatar"))
        return [Container(accent_color=color, components=[section])], [hikari.Bytes(row["avatar"], filename, row["avatar_type"])]
    return [Container(accent_color=color, components=[body])], []


async def post_card(row):
    """One HTTP attempt. Hikari's shared REST client retries ambiguous POSTs."""
    cards, files = components(row)
    payload = {
        "flags": int(hikari.MessageFlag.IS_COMPONENTS_V2),
        "components": [card.build()[0] for card in cards],
        "allowed_mentions": {"parse": []},
    }
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("Discord token is unavailable")
    headers = {"Authorization": "Bot " + token}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if files:
            blob = files[0]
            payload["attachments"] = [{"id": 0, "filename": blob.filename}]
            form = aiohttp.FormData()
            form.add_field("payload_json", json.dumps(payload))
            form.add_field("files[0]", row["avatar"], filename=blob.filename, content_type=row["avatar_type"])
            request_args = {"data": form}
        else:
            request_args = {"json": payload}
        async with session.post(
            f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
            headers=headers, **request_args,
        ) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Discord member event post returned HTTP {response.status}")
            result = await response.json()
            message_id = result.get("id")
            if not isinstance(message_id, str) or not message_id.isdigit():
                raise RuntimeError("Discord member event response had no message ID")
            return message_id


async def channel_ready(bot):
    channel = await bot.rest.fetch_channel(CHANNEL_ID)
    return (int(getattr(channel, "guild_id", 0)) == GUILD_ID and
            getattr(channel, "type", None) in (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS))


async def deliver(store: MemberEventStore, bot, row):
    # Check ownership before claiming: bad configuration remains safely queued.
    if not await channel_ready(bot):
        log.error("Member event destination is outside the configured server or not a text channel")
        return False
    row = await store.claim(row["_id"])
    if not row:
        return False
    try:
        message_id = await post_card(row)
        await store.finish(row["_id"], status="sent", message_id=message_id)
        return True
    except BaseException:
        # The HTTP request may have reached Discord; no automatic resend.
        try:
            await store.finish(row["_id"], status="uncertain")
        except Exception:
            log.exception("Could not persist uncertain member event receipt")
        raise


async def record(event, kind: str, mongo: MongoClient, bot: hikari.GatewayBot):
    if kind == "join":
        member = event.member
        guild_id = int(member.guild_id)
        user = member.user
    else:
        guild_id = int(event.guild_id)
        member = event.old_member
        user = event.user
    if guild_id != GUILD_ID:
        return
    uid = int(user.id)
    now = datetime.now(timezone.utc)
    username = str(getattr(user, "username", None) or uid)
    display_name = str(getattr(member, "display_name", None) or getattr(user, "global_name", None) or username)
    url = avatar_source(guild_id, uid, getattr(user, "avatar_hash", None), getattr(member, "guild_avatar_hash", None))
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    joined_at = getattr(member, "joined_at", None)
    if kind == "leave" and not isinstance(joined_at, datetime):
        # The gateway may omit old_member after an uncached leave. A captured
        # join identifies the episode even across a restart or rapid rejoin.
        joined_at = await store.latest_joined_at(guild_id, uid, now)
    row = await store.capture(
        guild_id=guild_id, user_id=uid, kind=kind,
        display_name=display_name, username=username, avatar=None, avatar_type=None,
        at=now, joined_at=joined_at,
        channel_id=CHANNEL_ID,
    )
    if row:
        avatar, mime = await download_avatar(url)
        if avatar:
            try:
                await store.save_avatar(row["_id"], avatar, mime)
            except Exception:
                log.exception("Could not save member avatar; identity record remains queued")
            else:
                row["avatar"], row["avatar_type"] = avatar, mime
        ready_row = await store.ready(row["_id"])
        if ready_row:
            await deliver(store, bot, ready_row)


async def recover(mongo, bot):
    store = MemberEventStore(mongo.member_events)
    await ensure_indexes(store)
    await store.release_stale_captures(GUILD_ID, CHANNEL_ID)
    if not await channel_ready(bot):
        log.error("Member event destination is outside the configured server or not a text channel")
        return
    while True:
        rows = await store.queued(GUILD_ID, CHANNEL_ID)
        if not rows:
            return
        for row in rows:
            try:
                if not await channel_ready(bot):
                    return
                if not await deliver(store, bot, row):
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Could not deliver queued member event %s", row["_id"])
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
