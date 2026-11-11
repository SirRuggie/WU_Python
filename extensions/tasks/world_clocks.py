"""Bot task that renames World clocks voice channels on each update mark.

Rules (decisions D2, D3, D7 and the auto order, 2026-11-11):
- One run per mark (:00, :06, :12 … for a 6-minute interval). A run renames a
  channel at most once, and only when its name is wrong. Staff edits wait for
  the next mark; nothing else renames a clock channel.
- No fast retry. When Discord asks to wait, the clock waits for its next mark.
- Off clocks are never renamed. Missing channels and permission errors mark
  only that clock; the other clocks keep running.
- Clock channels are sorted by GMT offset, lowest first, using only the
  positions clock channels already hold. Other channels never move.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import hikari
import lightbulb

from utils import world_clocks as rules
from utils.mongo import MongoClient
from utils.world_clock_store import WorldClockStore

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 20
START_DELAY_SECONDS = 2
AUDIT_REASON = "World clocks update"
_task = None

MISSING = "Channel missing. Select another voice channel."
NO_CHANNEL = "No channel. Select a voice channel."
FORBIDDEN = "WU Wizard cannot rename this channel. Check its permissions."
NEEDS_CODE = "Type a code for this time zone."
WAITING = "Discord asked to wait. Next try at the next update."
FAILED = "Discord did not accept the rename. Next try at the next update."


def _channel_map(channels) -> dict[str, dict]:
    return {
        str(channel.id): {
            "name": channel.name,
            "position": channel.position,
            "parent_id": str(channel.parent_id) if channel.parent_id else "",
            "type": channel.type,
        }
        for channel in channels
    }


async def _rename(rest, channel_id: str, name: str):
    await asyncio.wait_for(
        rest.edit_channel(int(channel_id), name=name, reason=AUDIT_REASON),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


async def update_clock(store, rest, clock, channels, at, settings, now):
    """Rename one clock when needed. Returns the result label for the run log."""
    channel_id = str(clock.get("channel_id") or "")
    version = clock.get("version")
    if not channel_id:
        await store.record_result(clock["_id"], version, status="problem", status_detail=NO_CHANNEL, checked_at=now)
        return "problem"
    channel = channels.get(channel_id)
    if channel is None or channel["type"] != hikari.ChannelType.GUILD_VOICE:
        await store.record_result(clock["_id"], version, status="problem", status_detail=MISSING, checked_at=now)
        return "problem"
    try:
        name = rules.clock_name(clock, at, settings["time_format"])
    except ValueError:
        await store.record_result(clock["_id"], version, status="problem", status_detail=NEEDS_CODE, checked_at=now)
        return "problem"
    if channel["name"] == name:
        await store.record_result(clock["_id"], version, status="ok", status_detail="", last_name=name, checked_at=now)
        return "unchanged"
    # A run can take minutes when Discord is slow. Skip a clock that staff
    # turned off, removed or edited since the run read the list.
    fresh = await store.get_clock(clock["_id"])
    if fresh is None or fresh.get("version") != version or not fresh.get("enabled"):
        return "skipped"
    try:
        await _rename(rest, channel_id, name)
    except asyncio.CancelledError:
        raise
    except hikari.NotFoundError:
        detail, label = MISSING, "problem"
    except hikari.ForbiddenError:
        detail, label = FORBIDDEN, "problem"
    except (asyncio.TimeoutError, hikari.RateLimitTooLongError):
        await store.record_result(clock["_id"], version, status="waiting", status_detail=WAITING, checked_at=now)
        return "waited"
    except Exception as exc:  # A Discord or network error must not stop the other clocks.
        _log.warning("World clock rename failed for %s: %s", channel_id, type(exc).__name__)
        detail, label = FAILED, "problem"
    else:
        await store.record_result(clock["_id"], version, status="ok", status_detail="",
                                  last_name=name, last_renamed_at=now, checked_at=now)
        return "renamed"
    await store.record_result(clock["_id"], version, status="problem", status_detail=detail, checked_at=now)
    return label


async def reorder(rest, clocks, channels, at) -> bool:
    changes = rules.positions_for(clocks, channels, at)
    if not changes:
        return False
    async def send():
        repositioner = rest.reposition_channels(rules.GUILD_ID, reason=AUDIT_REASON)
        for channel_id, position in changes.items():
            repositioner.add_reposition_channel(position=position, channel=int(channel_id))
        await repositioner

    try:
        await asyncio.wait_for(send(), timeout=REQUEST_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.warning("World clock reorder failed: %s", type(exc).__name__)
        return False
    return True


async def run_once(store, rest, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    settings = await store.get_settings()
    clocks = await store.list_clocks()
    if not clocks:
        return None
    at = rules.mark(now, settings["interval_minutes"])
    try:
        channels = _channel_map(await asyncio.wait_for(
            rest.fetch_guild_channels(rules.GUILD_ID), timeout=REQUEST_TIMEOUT_SECONDS))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Record the miss so Recent updates shows it.
        _log.warning("World clocks could not read channels: %s", type(exc).__name__)
        entry = {"at": now, "mark": at, "discord_unavailable": True}
        await store.add_run(entry)
        return entry
    counts = {"renamed": 0, "unchanged": 0, "waited": 0, "problem": 0, "skipped": 0}
    for clock in clocks:
        if not clock.get("enabled"):
            continue
        counts[await update_clock(store, rest, clock, channels, at, settings, now)] += 1
    placed = [clock for clock in clocks if str(clock.get("channel_id") or "") in channels]
    try:
        moved = await reorder(rest, placed, channels, at)
    except ValueError:  # A clock with a bad zone; it is already marked as a problem.
        moved = False
    entry = {"at": now, "mark": at, **counts, "moved": moved}
    await store.add_run(entry)
    return entry


async def loop(db, bot):
    store = WorldClockStore(db)
    indexes_ready = False
    while True:
        try:
            if not indexes_ready:
                await store.ensure_indexes()
                indexes_ready = True
            settings = await store.get_settings()
            now = datetime.now(timezone.utc)
            wait = (rules.next_mark(now, settings["interval_minutes"]) - now).total_seconds()
            await asyncio.sleep(max(0.0, wait) + START_DELAY_SECONDS)
            await run_once(store, bot.rest)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("World clocks run failed")
            await asyncio.sleep(60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(loop(mongo, bot), name="world-clocks")


@loader.listener(hikari.StoppingEvent)
async def stop(event: hikari.StoppingEvent):
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
