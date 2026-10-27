"""Staff-only HTTP access to durable member join/leave snapshots."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiohttp import web

from utils.member_events import GUILD_ID, ID_PATTERN, MemberEventStore, public_event
from .server_management import API, mongo, require_manage

PREFIX = API + "/member-events"


def date_bound(raw: str, *, end: bool):
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise web.HTTPBadRequest(text="Choose a valid date in YYYY-MM-DD format.") from None
    try:
        return day + timedelta(days=1) if end else day
    except OverflowError:
        raise web.HTTPBadRequest(text="Date is outside the supported range.") from None


async def listing(request):
    await require_manage(request, "roles")
    q = request.query.get("q", "").strip()
    kind = request.query.get("type", "")
    before = request.query.get("before", "")
    raw_limit = request.query.get("limit", "50")
    if len(q) > 80 or any(ord(c) < 32 for c in q):
        raise web.HTTPBadRequest(text="Keep searches to 80 printable characters.")
    if kind not in ("", "join", "leave", "kick", "ban"):
        raise web.HTTPBadRequest(text="Choose join, leave, kick or ban.")
    if before and not ID_PATTERN.fullmatch(before):
        raise web.HTTPBadRequest(text="Invalid page cursor.")
    try:
        limit = int(raw_limit)
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid page size.") from None
    if not 1 <= limit <= 100:
        raise web.HTTPBadRequest(text="Choose 1 to 100 events per page.")
    start = date_bound(request.query["from"], end=False) if "from" in request.query else None
    end = date_bound(request.query["to"], end=True) if "to" in request.query else None
    if start and end and start >= end:
        raise web.HTTPBadRequest(text="Start date must be on or before end date.")
    async with mongo(request) as db:
        rows, cursor = await MemberEventStore(db.member_events).search(
            guild_id=GUILD_ID, query=q, kind=kind, start=start, end=end,
            before=before or None, limit=limit,
        )
    response = web.json_response({"events": [public_event(row, api_prefix=PREFIX) for row in rows],
                                  "next_cursor": cursor})
    response.headers["Cache-Control"] = "no-store"
    return response


async def avatar(request):
    await require_manage(request, "roles")
    row_id = request.match_info["event_id"]
    if not ID_PATTERN.fullmatch(row_id):
        raise web.HTTPNotFound()
    async with mongo(request) as db:
        row = await MemberEventStore(db.member_events).avatar(row_id, GUILD_ID)
    if not row or not row.get("avatar") or row.get("avatar_type") not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        raise web.HTTPNotFound()
    response = web.Response(body=bytes(row["avatar"]), content_type=row["avatar_type"])
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


routes = [web.get(PREFIX, listing), web.get(PREFIX + "/{event_id}/avatar", avatar)]


async def _bot_permissions(request):
    """Fetch the bot's current guild roles for destination permission checks."""
    from .server_management import discord
    from utils.member_events import effective_permissions
    me = await discord(request, "GET", "/users/@me")
    member = await discord(request, "GET", f"/guilds/{GUILD_ID}/members/{me['id']}")
    roles = await discord(request, "GET", f"/guilds/{GUILD_ID}/roles")
    role_ids = {str(value) for value in member.get("roles", [])}
    base = 0
    for role in roles:
        if str(role.get("id")) in role_ids | {str(GUILD_ID)}:
            base |= int(role.get("permissions", 0))
    actor = {"permissions": base, "role_ids": role_ids, "user_id": str(me["id"])}
    return actor, effective_permissions


def _channel_type(channel):
    if channel.get("type") in (0, 5):
        return "text"
    if channel.get("type") == 15:
        return "forum"
    return None


def _channel_option(channel, actor, effective, staff=None):
    from hikari import Permissions
    kind = _channel_type(channel)
    if str(channel.get("guild_id")) != str(GUILD_ID) or not kind:
        return None
    overwrites = channel.get("permission_overwrites", [])
    rights = effective(actor["permissions"], actor["role_ids"], actor["user_id"], overwrites, GUILD_ID)
    if staff is not None:
        staff_rights = effective(staff["permissions"], staff["role_ids"], staff["user_id"], overwrites, GUILD_ID)
        if not (staff_rights & (Permissions.ADMINISTRATOR | Permissions.VIEW_CHANNEL)):
            return None
    needed = Permissions.VIEW_CHANNEL | Permissions.SEND_MESSAGES | Permissions.ATTACH_FILES
    if kind == "forum":
        needed |= Permissions.EMBED_LINKS
    tags = [{"id": str(tag["id"]), "name": str(tag.get("name") or tag["id"]),
             "moderated": bool(tag.get("moderated"))}
            for tag in channel.get("available_tags", [])] if kind == "forum" else []
    return {"id": str(channel["id"]), "name": str(channel.get("name") or channel["id"]),
            "type": kind, "available_tags": tags,
            "can_post": bool(rights & Permissions.ADMINISTRATOR) or rights & needed == needed,
            "requires_tag": bool(int(channel.get("flags") or 0) & 16),
            "can_manage_threads": bool(rights & (Permissions.ADMINISTRATOR | Permissions.MANAGE_THREADS))}


async def settings(request):
    staff = await require_manage(request, "roles")
    async with mongo(request) as db:
        saved = await MemberEventStore(db.member_events).settings()
    try:
        from .server_management import discord
        actor, effective = await _bot_permissions(request)
        channels = await discord(request, "GET", f"/guilds/{GUILD_ID}/channels")
        options = [_channel_option(row, actor, effective, staff) for row in channels]
        options = [row for row in options if row]
        channels_available = True
        warning = None if int(actor["permissions"]) & ((1 << 7) | 8) else "The bot lacks View Audit Log; confirmed kick events cannot be recorded."
    except web.HTTPException:
        options = None
        channels_available = False
        warning = "Discord channel inventory is unavailable; saved settings are shown."
    response = web.json_response({**saved, "channels": options,
                                  "channels_available": channels_available, "warning": warning})
    response.headers["Cache-Control"] = "no-store"
    return response


async def save_settings(request):
    staff = await require_manage(request, "roles", write=True)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid settings JSON.") from None
    if not isinstance(body, dict) or set(body) != {"revision", "events"}:
        raise web.HTTPBadRequest(text="Choose all four event settings and a revision.")
    revision, events = body["revision"], body["events"]
    from utils.member_events import EVENT_TYPES, SettingsConflict
    if type(revision) is not int or revision < 0 or not isinstance(events, dict) or set(events) != set(EVENT_TYPES):
        raise web.HTTPBadRequest(text="Invalid member event settings.")
    from .server_management import discord
    actor, effective = await _bot_permissions(request)
    checked = {}
    for kind in EVENT_TYPES:
        config = events[kind]
        if not isinstance(config, dict) or set(config) != {"enabled", "channel_id", "forum_tag_id"}:
            raise web.HTTPBadRequest(text=f"Invalid {kind} destination.")
        enabled, channel_id, tag_id = config["enabled"], config["channel_id"], config["forum_tag_id"]
        if type(enabled) is not bool:
            raise web.HTTPBadRequest(text=f"Invalid {kind} enable setting.")
        if channel_id is not None and (not isinstance(channel_id, str) or not channel_id.isdigit() or not 15 <= len(channel_id) <= 22):
            raise web.HTTPBadRequest(text=f"Invalid {kind} channel.")
        if tag_id is not None and (not isinstance(tag_id, str) or not tag_id.isdigit() or not 15 <= len(tag_id) <= 22):
            raise web.HTTPBadRequest(text=f"Invalid {kind} forum tag.")
        if enabled and not channel_id:
            raise web.HTTPBadRequest(text=f"Choose a {kind} channel before enabling delivery.")
        if tag_id and not channel_id:
            raise web.HTTPBadRequest(text="A forum tag requires a channel.")
        if enabled:
            try:
                channel = await discord(request, "GET", f"/channels/{channel_id}")
            except web.HTTPNotFound:
                raise web.HTTPBadRequest(text=f"The {kind} channel no longer exists.") from None
            option = _channel_option(channel, actor, effective, staff)
            if not option:
                raise web.HTTPBadRequest(text=f"The {kind} channel must be a text or forum channel in this server.")
            if not option["can_post"]:
                raise web.HTTPBadRequest(text=f"The bot needs View Channel, Send Messages, Attach Files and, for forums, Embed Links in the {kind} channel.")
            if option["type"] != "forum" and tag_id:
                raise web.HTTPBadRequest(text="Forum tags can only be used with forum channels.")
            if option["requires_tag"] and not tag_id:
                raise web.HTTPBadRequest(text=f"The {kind} forum requires a tag.")
            if tag_id:
                tag = next((tag for tag in option["available_tags"] if tag["id"] == tag_id), None)
                if not tag:
                    raise web.HTTPBadRequest(text=f"The {kind} forum tag is no longer available.")
                if tag["moderated"] and not option["can_manage_threads"]:
                    raise web.HTTPBadRequest(text=f"The bot cannot apply the moderated {kind} forum tag.")
        checked[kind] = {"enabled": enabled, "channel_id": channel_id, "forum_tag_id": tag_id}
    async with mongo(request) as db:
        try:
            saved = await MemberEventStore(db.member_events).save_settings(revision, checked)
        except SettingsConflict:
            raise web.HTTPConflict(text="Member log settings changed. Reload before saving.") from None
    response = web.json_response(saved)
    response.headers["Cache-Control"] = "no-store"
    return response


routes.extend([web.get(PREFIX + "/settings", settings), web.put(PREFIX + "/settings", save_settings)])
