"""HTTP adapters for World clocks (Bot → World clocks on the dashboard).

Authorization: the `world_clocks` section, which maps to the existing
`server_tools` permission (decision D1). Every write checks the clock's
version, so two staff members never overwrite each other. "Create channel"
keeps a receipt per press, so a double tap or retry never makes 2 channels.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import partial
from uuid import UUID

from aiohttp import web

from utils import world_clocks as rules
from utils.world_clock_store import ChannelInUse, Conflict, WorldClockStore
from .server_management import API, GUILD_ID, DiscordDeliveryUncertain, discord, mongo, require_manage

BASE = API + "/world-clocks"
SECTION = "world_clocks"
VOICE, CATEGORY = 2, 4
CLOCK_CHANGED = "This clock changed. The page shows the new version. Check it and try again."
SETTINGS_CHANGED = "Settings changed. The page shows the new version. Check it and try again."
IN_USE = "This channel already has a clock. Select another channel."
UNCERTAIN = ("Discord did not confirm the new channel. Check the category in Discord "
             "before you try again. If the channel is there, add it with Use an existing voice channel.")
OPEN_TRY = ("An earlier try in this category is not confirmed yet. Check the category in Discord. "
            "If the new channel is there, add it with Use an existing voice channel. "
            "Otherwise try again in 15 minutes.")
OPEN_TRY_MINUTES = 15


def _json(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def respond(payload, status=200):
    return web.json_response(payload, status=status, dumps=partial(json.dumps, default=_json))


async def body_of(request) -> dict:
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Check the clock settings.") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Check the clock settings.")
    return body


def version_of(body) -> int:
    value = body.get("revision")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}", value):
        raise web.HTTPBadRequest(text="Reload the page and try again.")
    return int(value)


def snowflake(value, text) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{17,20}", value):
        raise web.HTTPBadRequest(text=text)
    return value


def clock_id(request) -> str:
    value = request.match_info.get("clock_id", "")
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise web.HTTPNotFound(text="This clock was removed. Reload the page.")
    return value


def validated(body, now):
    try:
        return rules.validate_clock(body, now)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None


async def guild_channels(request):
    """All guild channels, or None when Discord is unavailable (partial data)."""
    try:
        rows = await discord(request, "GET", f"/guilds/{GUILD_ID}/channels")
    except web.HTTPException:
        return None
    return [row for row in rows or [] if isinstance(row, dict)]


async def voice_channel(request, channel_id) -> dict:
    channel_id = snowflake(channel_id, "Select a voice channel.")
    found = await discord(request, "GET", f"/channels/{channel_id}")
    if str(found.get("guild_id")) != str(GUILD_ID) or found.get("type") != VOICE:
        raise web.HTTPBadRequest(text="Select a voice channel in this server.")
    return found


def public_clock(row, channels, now, settings):
    at = rules.mark(now, settings["interval_minutes"])
    channel = channels.get(str(row.get("channel_id") or "")) if channels is not None else None
    try:
        names = rules.preview(row, at, settings["time_format"])
    except ValueError:
        names = {"code_auto": None, "flag_auto": "", "needs_code": True, "name_now": None,
                 "name_other": None, "offset_minutes": 0}
    return {
        "id": row["_id"],
        "zone": row.get("zone"),
        "flag": row.get("flag") or "",
        "code": row.get("code"),
        "channel_id": row.get("channel_id"),
        "channel_name": channel.get("name") if channel else None,
        "channel_missing": channels is not None and channel is None,
        "enabled": bool(row.get("enabled")),
        "revision": str(row.get("version", 0)),
        "last_name": row.get("last_name"),
        "last_renamed_at": row.get("last_renamed_at"),
        "status": row.get("status") or "waiting",
        "status_detail": row.get("status_detail") or "",
        **names,
    }


def public_settings(settings):
    return {"category_id": settings["category_id"], "time_format": settings["time_format"],
            "interval_minutes": settings["interval_minutes"], "revision": str(settings["version"])}


async def read(request):
    await require_manage(request, SECTION)
    channels = await guild_channels(request)
    by_id = {str(row["id"]): row for row in channels} if channels is not None else None
    now = datetime.now(timezone.utc)
    async with mongo(request) as db:
        store = WorldClockStore(db)
        settings = await store.get_settings()
        clocks = await store.list_clocks()
        runs = await store.recent_runs()
    try:
        clocks = rules.sort_clocks(clocks, now)
    except ValueError:
        pass
    used = {str(row.get("channel_id")) for row in clocks if row.get("channel_id")}
    categories = {str(row["id"]): row.get("name", "") for row in channels or [] if row.get("type") == CATEGORY}
    return respond({
        "settings": public_settings(settings),
        "clocks": [public_clock(row, by_id, now, settings) for row in clocks],
        "channels_available": channels is not None,
        "categories": [{"id": key, "name": name} for key, name in categories.items()],
        "voice_channels": [
            {"id": str(row["id"]), "name": row.get("name", ""),
             "category": categories.get(str(row.get("parent_id") or ""), ""),
             "used": str(row["id"]) in used}
            for row in channels or [] if row.get("type") == VOICE
        ],
        "chips": [{"label": label, "zone": zone, "flag": rules.flag_for(zone)} for label, zone in rules.CHIPS],
        "now": now,
        "next_update": rules.next_mark(now, settings["interval_minutes"]),
        "runs": runs,
        "max_clocks": rules.MAX_CLOCKS,
    })


async def zones(request):
    await require_manage(request, SECTION)
    now = datetime.now(timezone.utc)
    rows = []
    for zone in sorted(rules.zones()):
        region, _, city = zone.partition("/")
        rows.append({"zone": zone, "city": city.replace("_", " ").replace("/", " · "), "region": region,
                     "flag": rules.flag_for(zone),
                     "offset": rules.offset_label(now.astimezone(rules.zone_info(zone)).utcoffset()),
                     "codes": rules.zone_codes(zone, now)})
    return respond({"zones": rows, "now": now})


async def preview(request):
    await require_manage(request, SECTION)
    body = await body_of(request)
    now = datetime.now(timezone.utc)
    async with mongo(request) as db:
        settings = await WorldClockStore(db).get_settings()
    try:
        rules.zone_info(body.get("zone"))
        code = body.get("code")
        code = None if code in (None, "") else str(code).strip().upper()
        if code is not None and not rules.CODE.fullmatch(code):
            raise ValueError("Use 2 to 6 letters for the code.")
        clock = {"zone": body["zone"], "flag": str(body.get("flag") or "")[:16], "code": code}
        result = rules.preview(clock, rules.mark(now, settings["interval_minutes"]), settings["time_format"])
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    return respond(result)


async def add(request):
    actor = await require_manage(request, SECTION, write=True)
    body = await body_of(request)
    try:
        request_id = str(UUID(str(body.get("request_id", ""))))
    except ValueError:
        raise web.HTTPBadRequest(text="Reload the page and try again.") from None
    now = datetime.now(timezone.utc)
    values = validated(body, now)
    mode = body.get("mode")
    if mode not in ("create", "existing"):
        raise web.HTTPBadRequest(text="Select where the clock goes.")
    async with mongo(request) as db:
        store = WorldClockStore(db)
        if mode == "create":
            # A repeated press is answered from its receipt before any limit check,
            # so a press that already worked never turns into an error.
            earlier = await store.get_request(request_id)
            if earlier is not None and earlier.get("status") != "failed":
                return await replay(request, store, earlier, actor)
        settings = await store.get_settings()
        if await store.count() >= rules.MAX_CLOCKS:
            raise web.HTTPBadRequest(text=f"You can have up to {rules.MAX_CLOCKS} clocks.")
    if mode == "existing":
        channel = await voice_channel(request, body.get("channel_id"))
        async with mongo(request) as db:
            try:
                row = await WorldClockStore(db).add_clock({**values, "channel_id": str(channel["id"])}, actor["user_id"])
            except ChannelInUse:
                raise web.HTTPConflict(text=IN_USE) from None
        return respond({"id": row["_id"]}, status=201)
    return await create_channel(request, actor, body, values, settings, request_id, now)


async def create_channel(request, actor, body, values, settings, request_id, now):
    category_id = snowflake(body.get("category_id") or settings["category_id"],
                            "Select a category for new channels in Settings.")
    channels = await guild_channels(request)
    if channels is None:
        raise web.HTTPServiceUnavailable(text="Discord is unavailable. No channel was created. Try again later.")
    category = next((row for row in channels if str(row["id"]) == category_id and row.get("type") == CATEGORY), None)
    if category is None:
        raise web.HTTPBadRequest(text="The category is gone. Select another category in Settings.")
    if sum(1 for row in channels if str(row.get("parent_id") or "") == category_id) >= 50:
        raise web.HTTPBadRequest(text="This category is full (50 channels). Select another category in Settings.")
    name = rules.clock_name(values, rules.mark(now, settings["interval_minutes"]), settings["time_format"])
    payload = {**values, "category_id": category_id}
    async with mongo(request) as db:
        store = WorldClockStore(db)
        # An unconfirmed create may have made a channel. Block new tries in that
        # category for a while, whatever request id the page sends.
        if await store.open_request(category_id, now - timedelta(minutes=OPEN_TRY_MINUTES), request_id):
            raise web.HTTPConflict(text=OPEN_TRY)
        earlier = await store.claim_request(request_id, actor["user_id"], payload)
        if earlier is not None and not (
                earlier.get("status") == "failed" and await store.retry_failed(request_id, actor["user_id"], payload)):
            return await replay(request, store, earlier, actor)
    try:
        created = await discord(request, "POST", f"/guilds/{GUILD_ID}/channels", roster_delivery=True, json={
            "name": name, "type": VOICE, "parent_id": category_id,
            "permission_overwrites": category.get("permission_overwrites") or [],
        })
    except DiscordDeliveryUncertain:
        async with mongo(request) as db:
            await WorldClockStore(db).finish_request(request_id, status="uncertain")
        raise web.HTTPServiceUnavailable(text=UNCERTAIN) from None
    except web.HTTPException as exc:
        async with mongo(request) as db:
            await WorldClockStore(db).finish_request(request_id, status="failed", detail=exc.text)
        if exc.status == 429:
            raise web.HTTPServiceUnavailable(text="Discord is busy. No channel was created. Try again in a minute.") from None
        if exc.status == 404:
            raise web.HTTPBadRequest(text="The category is gone. Select another category in Settings.") from None
        if exc.status in (401, 403):
            # Not a dashboard permission problem, so never pass a 403 through to the page.
            raise web.HTTPBadRequest(
                text="WU Wizard cannot create channels in this category. Check its permissions.") from None
        raise
    channel_id = str(created["id"])
    async with mongo(request) as db:
        store = WorldClockStore(db)
        await store.finish_request(request_id, status="channel_created", channel_id=channel_id)
        row = await store.add_clock({**values, "channel_id": channel_id}, actor["user_id"])
        await store.record_result(row["_id"], row["version"], status="ok", status_detail="",
                                  last_name=name, last_renamed_at=now, checked_at=now)
        await store.finish_request(request_id, status="created", clock_id=row["_id"])
    return respond({"id": row["_id"], "channel_id": channel_id}, status=201)


def _older_than(value, minutes: int) -> bool:
    if not isinstance(value, datetime):
        return False
    if value.tzinfo is None:  # Mongo returns naive UTC unless the client is tz-aware.
        value = value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - value > timedelta(minutes=minutes)


async def replay(request, store, earlier, actor):
    status = earlier.get("status")
    if earlier.get("actor") not in (None, actor["user_id"]):
        raise web.HTTPConflict(text="Reload the page and try again.")
    if status == "created":
        return respond({"id": earlier.get("clock_id"), "channel_id": earlier.get("channel_id")}, status=200)
    if status == "channel_created" and earlier.get("channel_id"):
        # The channel exists but the clock was not saved; finish the same press.
        values = {key: earlier["payload"][key] for key in ("zone", "flag", "code")}
        try:
            row = await store.add_clock({**values, "channel_id": earlier["channel_id"]}, actor["user_id"])
        except ChannelInUse:
            raise web.HTTPConflict(text=IN_USE) from None
        await store.finish_request(earlier["_id"], status="created", clock_id=row["_id"])
        return respond({"id": row["_id"], "channel_id": earlier["channel_id"]}, status=201)
    if status == "uncertain" or (status == "creating" and _older_than(earlier.get("created_at"), OPEN_TRY_MINUTES)):
        # A press that never finished (for example a restart mid-create) may have made a channel.
        raise web.HTTPConflict(text=UNCERTAIN)
    if status == "failed":
        raise web.HTTPConflict(text="That try failed. Close the sheet and try again.")
    raise web.HTTPConflict(text="Still creating the channel. Reload the page in a moment.")


async def toggle(request):
    actor = await require_manage(request, SECTION, write=True)
    target = clock_id(request)
    body = await body_of(request)
    if not isinstance(body.get("enabled"), bool):
        raise web.HTTPBadRequest(text="Check the clock settings.")
    version = version_of(body)
    now = datetime.now(timezone.utc)
    async with mongo(request) as db:
        store = WorldClockStore(db)
        try:
            row = await store.update_clock(target, version, {"enabled": body["enabled"]}, actor["user_id"])
        except Conflict:
            raise web.HTTPConflict(text=CLOCK_CHANGED) from None
        settings = await store.get_settings()
    return respond({"clock": public_clock(row, None, now, settings), "next_update": rules.next_mark(now, settings["interval_minutes"])})


async def edit(request):
    actor = await require_manage(request, SECTION, write=True)
    target = clock_id(request)
    body = await body_of(request)
    version = version_of(body)
    now = datetime.now(timezone.utc)
    values = validated(body, now)
    async with mongo(request) as db:
        current = await WorldClockStore(db).get_clock(target)
    if current is None:
        raise web.HTTPNotFound(text="This clock was removed. Reload the page.")
    channel_id = body.get("channel_id")
    if channel_id != current.get("channel_id"):
        values["channel_id"] = str((await voice_channel(request, channel_id))["id"])
    async with mongo(request) as db:
        store = WorldClockStore(db)
        try:
            row = await store.update_clock(target, version, values, actor["user_id"])
        except Conflict:
            raise web.HTTPConflict(text=CLOCK_CHANGED) from None
        except ChannelInUse:
            raise web.HTTPConflict(text=IN_USE) from None
        settings = await store.get_settings()
    return respond({"clock": public_clock(row, None, now, settings), "next_update": rules.next_mark(now, settings["interval_minutes"])})


async def remove(request):
    await require_manage(request, SECTION, write=True)
    target = clock_id(request)
    version = version_of(await body_of(request))
    async with mongo(request) as db:
        try:
            await WorldClockStore(db).remove_clock(target, version)
        except Conflict:
            raise web.HTTPConflict(text=CLOCK_CHANGED) from None
    return respond({"removed": target})


async def save_settings(request):
    actor = await require_manage(request, SECTION, write=True)
    body = await body_of(request)
    version = version_of(body)
    time_format = body.get("time_format")
    interval = body.get("interval_minutes")
    category_id = body.get("category_id")
    # type() check: JSON 6.0 equals 6 but would break the schedule (datetime.replace needs an int).
    if time_format not in rules.TIME_FORMATS or type(interval) is not int or interval not in rules.INTERVALS:
        raise web.HTTPBadRequest(text="Check the settings.")
    async with mongo(request) as db:
        current = await WorldClockStore(db).get_settings()
    if category_id is not None and category_id != current["category_id"]:
        category_id = snowflake(category_id, "Select a category.")
        found = await discord(request, "GET", f"/channels/{category_id}")
        if str(found.get("guild_id")) != str(GUILD_ID) or found.get("type") != CATEGORY:
            raise web.HTTPBadRequest(text="Select a category in this server.")
    async with mongo(request) as db:
        try:
            settings = await WorldClockStore(db).save_settings(
                version, {"category_id": category_id, "time_format": time_format, "interval_minutes": interval},
                actor["user_id"])
        except Conflict:
            raise web.HTTPConflict(text=SETTINGS_CHANGED) from None
    return respond({"settings": public_settings(settings)})


routes = [
    web.get(BASE, read),
    web.get(BASE + "/zones", zones),
    web.post(BASE + "/preview", preview),
    web.put(BASE + "/settings", save_settings),
    web.post(BASE, add),
    web.patch(BASE + "/{clock_id}", toggle),
    web.put(BASE + "/{clock_id}", edit),
    web.delete(BASE + "/{clock_id}", remove),
]
