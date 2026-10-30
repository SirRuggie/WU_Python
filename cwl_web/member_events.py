"""Staff-only HTTP access to durable member join/leave snapshots."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiohttp import web

from utils.member_events import (
    GUILD_ID, ID_PATTERN, MemberEventStore, SettingsConflict,
    TestRateLimited, public_event,
)
from utils.member_event_settings import (
    CATEGORIES, EVENT_TYPES, SCHEMA_VERSION, effective_event, normalize_settings,
)
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
    if channel.get("type") == 11:
        return "forum_post"
    return None


def _channel_option(channel, actor, effective, staff=None, parent=None):
    from hikari import Permissions
    kind = _channel_type(channel)
    if str(channel.get("guild_id")) != str(GUILD_ID) or not kind:
        return None
    if kind == "forum_post":
        if not parent or parent.get("type") != 15 or str(parent.get("guild_id")) != str(GUILD_ID) or str(parent.get("id")) != str(channel.get("parent_id")):
            return None
    overwrites = (parent if kind == "forum_post" else channel).get("permission_overwrites", [])
    rights = effective(actor["permissions"], actor["role_ids"], actor["user_id"], overwrites, GUILD_ID)
    if staff is not None:
        staff_rights = effective(staff["permissions"], staff["role_ids"], staff["user_id"], overwrites, GUILD_ID)
        if not (staff_rights & (Permissions.ADMINISTRATOR | Permissions.VIEW_CHANNEL)):
            return None
    needed = Permissions.VIEW_CHANNEL | Permissions.SEND_MESSAGES | Permissions.ATTACH_FILES
    if kind == "forum_post":
        needed = Permissions.VIEW_CHANNEL | Permissions.SEND_MESSAGES_IN_THREADS | Permissions.ATTACH_FILES
    if kind == "forum":
        needed |= Permissions.EMBED_LINKS
    tags = [{"id": str(tag["id"]), "name": str(tag.get("name") or tag["id"]),
             "moderated": bool(tag.get("moderated"))}
            for tag in channel.get("available_tags", [])] if kind == "forum" else []
    return {"id": str(channel["id"]), "name": str(channel.get("name") or channel["id"]),
            "type": kind, "available_tags": tags,
            "can_post": (bool(rights & Permissions.ADMINISTRATOR) or rights & needed == needed) and not (kind == "forum_post" and channel.get("thread_metadata", {}).get("locked")),
            "requires_tag": kind == "forum" and bool(int(channel.get("flags") or 0) & 16),
            "can_manage_threads": bool(rights & (Permissions.ADMINISTRATOR | Permissions.MANAGE_THREADS))}


async def _resolve_option(request, channel_id, actor, effective, staff):
    from .server_management import discord
    channel = await discord(request, "GET", f"/channels/{channel_id}")
    parent = None
    if channel.get("type") == 11 and str(channel.get("guild_id")) == str(GUILD_ID):
        parent = await discord(request, "GET", f"/channels/{channel['parent_id']}")
    return _channel_option(channel, actor, effective, staff, parent)


async def destination(request):
    staff = await require_manage(request, "roles")
    channel_id = request.match_info["channel_id"]
    if not channel_id.isascii() or not channel_id.isdigit() or not 15 <= len(channel_id) <= 22:
        raise web.HTTPBadRequest(text="Enter a valid channel or forum post ID.")
    actor, effective = await _bot_permissions(request)
    try:
        option = await _resolve_option(request, channel_id, actor, effective, staff)
    except (web.HTTPNotFound, web.HTTPForbidden):
        raise web.HTTPBadRequest(text="That destination is missing or inaccessible to the bot.") from None
    if not option:
        raise web.HTTPBadRequest(text="Choose an accessible text channel, forum, or forum post in this server.")
    if not option["can_post"]:
        raise web.HTTPBadRequest(text="The bot cannot post here. Check its permissions and whether the forum post is locked.")
    response = web.json_response(option)
    response.headers["Cache-Control"] = "no-store"
    return response


async def settings(request):
    staff = await require_manage(request, "roles")
    async with mongo(request) as db:
        saved = normalize_settings(await MemberEventStore(db.member_events).settings(),
                                   MemberEventStore.default_settings())
    try:
        from .server_management import discord
        actor, effective = await _bot_permissions(request)
        channels = await discord(request, "GET", f"/guilds/{GUILD_ID}/channels")
        options = [_channel_option(row, actor, effective, staff) for row in channels]
        options = [row for row in options if row]
        parents = {str(row["id"]): row for row in channels}
        post_warning = None
        try:
            active = await discord(request, "GET", f"/guilds/{GUILD_ID}/threads/active")
            for thread in active.get("threads", []):
                option = _channel_option(thread, actor, effective, staff, parents.get(str(thread.get("parent_id"))))
                if option:
                    options.append(option)
        except web.HTTPException:
            post_warning = "Forum post search is unavailable. You can still look up a post by ID."
        known = {row["id"] for row in options}
        configured = [saved["main"], *saved["categories"].values(), *saved["events"].values()]
        for channel_id in {config.get("channel_id") for config in configured if config.get("channel_id")} - known:
            try:
                option = await _resolve_option(request, channel_id, actor, effective, staff)
                if option:
                    options.append(option)
            except (web.HTTPNotFound, web.HTTPForbidden):
                pass
        channels_available = True
        warning = post_warning if int(actor["permissions"]) & ((1 << 7) | 8) else "The bot lacks View Audit Log; confirmed kick events cannot be recorded."
    except web.HTTPException:
        options = None
        channels_available = False
        warning = "Discord channel inventory is unavailable; saved settings are shown."
    from utils.member_event_cards import build_card, build_forum_message, sample_row
    preview_cards = {kind: build_card(sample_row(kind)) for kind in EVENT_TYPES}
    forum_preview_cards = {kind: build_forum_message(sample_row(kind)) for kind in EVENT_TYPES}
    response = web.json_response({**saved, "preview_cards": preview_cards,
                                  "forum_preview_cards": forum_preview_cards, "channels": options,
                                  "channels_available": channels_available, "warning": warning})
    response.headers["Cache-Control"] = "no-store"
    return response


def _snowflake(value, label):
    if value is not None and (not isinstance(value, str) or not value.isascii()
                              or not value.isdigit() or not 15 <= len(value) <= 22):
        raise web.HTTPBadRequest(text=f"Invalid {label} ID.")
    return value


def _destination(value, label):
    if not isinstance(value, dict) or set(value) != {"channel_id", "forum_tag_id"}:
        raise web.HTTPBadRequest(text=f"Invalid {label} destination.")
    channel_id = _snowflake(value["channel_id"], f"{label} channel")
    tag_id = _snowflake(value["forum_tag_id"], f"{label} forum tag")
    if tag_id and not channel_id:
        raise web.HTTPBadRequest(text="A forum tag requires a channel.")
    return {"channel_id": channel_id, "forum_tag_id": tag_id}


def _checked_settings(body):
    if not isinstance(body, dict) or type(body.get("revision")) is not int or body["revision"] < 0:
        raise web.HTTPBadRequest(text="Choose a valid settings revision.")
    if set(body) == {"revision", "events"}:  # Original API clients.
        body = normalize_settings(body, MemberEventStore.default_settings())
    if set(body) == {"revision", "main", "categories", "events", "ignores"}:
        body = {"schema_version": SCHEMA_VERSION, **body}
    if set(body) != {"schema_version", "revision", "main", "categories", "events", "ignores"}:
        raise web.HTTPBadRequest(text="Choose all member log settings.")
    if body["schema_version"] != SCHEMA_VERSION or body["ignores"] != {}:
        raise web.HTTPBadRequest(text="Unsupported member log settings schema.")
    main = _destination(body["main"], "main")
    categories = body["categories"]
    if not isinstance(categories, dict) or set(categories) != set(CATEGORIES):
        raise web.HTTPBadRequest(text="Choose both member log categories.")
    checked_categories = {}
    for category in CATEGORIES:
        value = categories[category]
        if not isinstance(value, dict) or set(value) != {"mode", "channel_id", "forum_tag_id"}:
            raise web.HTTPBadRequest(text=f"Invalid {category} category.")
        if value["mode"] not in ("main", "own", "off"):
            raise web.HTTPBadRequest(text=f"Invalid {category} routing mode.")
        checked_categories[category] = {"mode": value["mode"], **_destination(
            {"channel_id": value["channel_id"], "forum_tag_id": value["forum_tag_id"]}, category)}
    events = body["events"]
    if not isinstance(events, dict) or set(events) != set(EVENT_TYPES):
        raise web.HTTPBadRequest(text="Choose all four event settings.")
    checked_events = {}
    for kind in EVENT_TYPES:
        value = events[kind]
        if not isinstance(value, dict) or set(value) != {"enabled", "channel_id", "forum_tag_id"}:
            raise web.HTTPBadRequest(text=f"Invalid {kind} settings.")
        if type(value["enabled"]) is not bool:
            raise web.HTTPBadRequest(text=f"Invalid {kind} enable setting.")
        checked_events[kind] = {"enabled": value["enabled"], **_destination(
            {"channel_id": value["channel_id"], "forum_tag_id": value["forum_tag_id"]}, kind)}
    return {"schema_version": SCHEMA_VERSION, "revision": body["revision"],
            "main": main, "categories": checked_categories, "events": checked_events,
            "ignores": {}}


async def _validate_destination(request, kind, resolved, actor, effective, staff):
    channel_id, tag_id = resolved["channel_id"], resolved["forum_tag_id"]
    if not channel_id:
        raise web.HTTPBadRequest(text=f"Choose a {kind} channel before enabling delivery.")
    try:
        option = await _resolve_option(request, channel_id, actor, effective, staff)
    except (web.HTTPNotFound, web.HTTPForbidden):
        raise web.HTTPBadRequest(text=f"The {kind} destination is missing or inaccessible to the bot.") from None
    if not option or not option["can_post"]:
        raise web.HTTPBadRequest(text=f"The bot cannot post in the {kind} destination.")
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
    return option


async def save_settings(request):
    staff = await require_manage(request, "roles", write=True)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid settings JSON.") from None
    checked = _checked_settings(body)
    actor, effective = await _bot_permissions(request)
    for kind in EVENT_TYPES:
        resolved = effective_event(checked, kind)
        if resolved["enabled"]:
            await _validate_destination(request, kind, resolved, actor, effective, staff)
    async with mongo(request) as db:
        try:
            saved = await MemberEventStore(db.member_events).save_settings(checked["revision"], checked)
        except SettingsConflict:
            raise web.HTTPConflict(text="Member log settings changed. Reload before saving.") from None
    response = web.json_response(saved)
    response.headers["Cache-Control"] = "no-store"
    return response


async def send_test(request):
    staff = await require_manage(request, "roles", write=True)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid test JSON.") from None
    if (not isinstance(body, dict) or set(body) != {"event_type", "revision"}
            or body["event_type"] not in EVENT_TYPES
            or type(body["revision"]) is not int or body["revision"] < 0):
        raise web.HTTPBadRequest(text="Choose an event and saved settings revision.")
    kind = body["event_type"]
    async with mongo(request) as db:
        store = MemberEventStore(db.member_events, db.member_event_test_audit)
        saved = await store.settings()
        if body["revision"] != saved["revision"]:
            raise web.HTTPConflict(text="Member log settings changed. Reload before testing.")
        resolved = effective_event(saved, kind)
        if not resolved["enabled"]:
            raise web.HTTPBadRequest(text="Enable this event and save before testing.")
        actor, effective = await _bot_permissions(request)
        option = await _validate_destination(request, kind, resolved, actor, effective, staff)
        from utils.member_event_cards import build_card, build_forum_message, sample_row
        from .server_management import DiscordDeliveryUncertain, discord
        now = datetime.now(timezone.utc)
        try:
            audit_id = await store.reserve_test(kind, str(staff["user_id"]), now)
        except TestRateLimited as exc:
            raise web.HTTPTooManyRequests(text=str(exc)) from None
        # A save may have completed while Discord permissions were checked.
        # Never send a sample for settings already known to be superseded.
        latest = await store.settings()
        if latest["revision"] != saved["revision"]:
            await store.finish_test(audit_id, status="cancelled", destination=resolved["channel_id"])
            raise web.HTTPConflict(text="Member log settings changed. Reload before testing.")
        sample = sample_row(kind)
        sample["occurred_at"] = now
        forum = option["type"] == "forum"
        payload = build_forum_message(sample, test_staff_id=str(staff["user_id"])) if forum else build_card(
            sample, test_staff_id=str(staff["user_id"]))
        if forum:
            title = f"Test {kind} · {now.strftime('%Y-%m-%d %H:%M UTC')}"
            data = {"name": title[:100], "message": payload}
            if resolved["forum_tag_id"]:
                data["applied_tags"] = [resolved["forum_tag_id"]]
            path = f"/channels/{resolved['channel_id']}/threads"
        else:
            data = payload
            path = f"/channels/{resolved['channel_id']}/messages"
        try:
            sent = await discord(request, "POST", path, json=data, roster_delivery=True)
        except asyncio.CancelledError:
            await store.finish_test(audit_id, status="uncertain", destination=resolved["channel_id"])
            raise
        except (DiscordDeliveryUncertain, web.HTTPException):
            await store.finish_test(audit_id, status="uncertain", destination=resolved["channel_id"])
            raise web.HTTPServiceUnavailable(text="Test delivery is unconfirmed. Check Discord before sending again.") from None
        item = sent.get("message") or sent if isinstance(sent, dict) else None
        message_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(message_id, str) or not message_id.isdigit():
            await store.finish_test(audit_id, status="uncertain", destination=resolved["channel_id"])
            raise web.HTTPServiceUnavailable(text="Test delivery is unconfirmed. Check Discord before sending again.")
        try:
            await store.finish_test(audit_id, status="sent", destination=resolved["channel_id"])
        except Exception:
            raise web.HTTPServiceUnavailable(
                text="Test was accepted but its audit could not be recorded. Check Discord before sending again.") from None
    response = web.json_response({"sent": True, "event_type": kind,
                                  "destination": {"id": option["id"], "name": option["name"],
                                                  "type": option["type"]}, "message_id": message_id})
    response.headers["Cache-Control"] = "no-store"
    return response

routes.extend([web.get(PREFIX + "/settings", settings), web.put(PREFIX + "/settings", save_settings),
               web.post(PREFIX + "/test", send_test)])

routes.append(web.get(PREFIX + "/destinations/{channel_id}", destination))
