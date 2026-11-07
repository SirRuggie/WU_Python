"""Staff-only member timeline and log health for the moderation archive."""
from __future__ import annotations

from datetime import timezone

from aiohttp import web

from utils.member_events import GUILD_ID, HISTORY_TYPES, ID_PATTERN, MemberEventStore, effective_permissions
from utils.member_event_settings import EVENT_TYPES, effective_event, normalize_settings
from .member_events import PREFIX, _bot_permissions, _resolve_option, public_events_named
from .server_management import discord, mongo, require_manage

BACKLOG_LIMIT = 25
VIEW_AUDIT_LOG = 1 << 7
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
UNAVAILABLE = {"key": "health_unavailable", "level": "warning", "text": "Health check unavailable"}


def _json(payload):
    response = web.json_response(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


async def timeline(request):
    await require_manage(request, "roles")
    user_id = request.match_info["user_id"]
    if not user_id.isascii() or not user_id.isdigit() or not 17 <= len(user_id) <= 20:
        raise web.HTTPBadRequest(text="Enter a valid member ID.")
    before = request.query.get("before", "")
    if before and not ID_PATTERN.fullmatch(before):
        raise web.HTTPBadRequest(text="Invalid page cursor.")
    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid page size.") from None
    if not 1 <= limit <= 100:
        raise web.HTTPBadRequest(text="Select 1 to 100 events per page.")
    filters = {"guild_id": GUILD_ID, "user_id": user_id, "event_type": {"$in": list(HISTORY_TYPES)}}
    if before:
        filters["_id"] = {"$lt": before}
    async with mongo(request) as db:
        rows = await db.member_events.find(filters, {"avatar": 0}).sort("_id", -1).limit(limit + 1).to_list(length=limit + 1)
    if not rows:
        raise web.HTTPNotFound(text="No history for this member.")
    next_before = rows[limit - 1]["_id"] if len(rows) > limit else None
    events = await public_events_named(request, rows[:limit])
    newest = events[0]
    member = {"user_id": user_id, "display_name": newest["display_name"],
              "username": newest["username"], "avatar_url": newest["avatar_url"]}
    return _json({"member": member, "events": events, "next_before": next_before})


async def _public_channel(request, channel_id, everyone):
    """Return (log channel id, name) when @everyone can view it, else None."""
    channel = await discord(request, "GET", f"/channels/{channel_id}")
    if channel.get("type") == 11 and channel.get("parent_id"):
        channel = await discord(request, "GET", f"/channels/{channel['parent_id']}")
    rights = effective_permissions(everyone, (), 0, channel.get("permission_overwrites", []), GUILD_ID)
    if rights & (ADMINISTRATOR | VIEW_CHANNEL):
        return str(channel["id"]), str(channel.get("name") or "")
    return None


async def _discord_items(request, saved):
    actor, effective = await _bot_permissions(request)
    rights = int(actor["permissions"])
    items = []
    if not rights & ADMINISTRATOR and not rights & VIEW_AUDIT_LOG:
        items.append({"key": "audit_log", "level": "warning", "text": "View Audit Log needed for moderator names"})
    if not rights & ADMINISTRATOR and not rights & MANAGE_GUILD:
        items.append({"key": "manage_server", "level": "warning", "text": "Manage Server needed for invite counts"})
    options = {}
    everyone = None
    checked = {}
    public = {}
    for kind in EVENT_TYPES:
        resolved = effective_event(saved, kind)
        if not resolved["enabled"]:
            continue
        channel_id = resolved["channel_id"]
        if channel_id and channel_id not in options:
            try:
                options[channel_id] = await _resolve_option(request, channel_id, actor, effective, None)
            except (web.HTTPNotFound, web.HTTPForbidden):
                options[channel_id] = None
        option = options.get(channel_id) if channel_id else None
        if not option or not option["can_post"]:
            items.append({"key": f"destination_{kind}", "level": "error",
                          "text": f"{kind.replace('_', ' ').capitalize()} cannot post to its channel"})
        if option and channel_id not in checked:
            if everyone is None:
                roles = await discord(request, "GET", f"/guilds/{GUILD_ID}/roles")
                everyone = next((int(role.get("permissions", 0)) for role in roles
                                 if str(role.get("id")) == str(GUILD_ID)), 0)
            checked[channel_id] = await _public_channel(request, channel_id, everyone)
            if checked[channel_id]:
                public.setdefault(checked[channel_id][0], checked[channel_id][1])
    for log_id, name in public.items():
        items.append({"key": f"public_{log_id}", "level": "error",
                      "text": f"{name} is visible to everyone" if name else "A log channel is visible to everyone"})
    return items


async def health(request):
    await require_manage(request, "roles")
    async with mongo(request) as db:
        collection = db.member_events
        backlog = await collection.count_documents({"guild_id": GUILD_ID, "delivery_status": "queued"})
        sent = await collection.find_one({"guild_id": GUILD_ID, "delivery_status": "sent"},
                                         {"delivered_at": 1}, sort=[("_id", -1)])
        saved = normalize_settings(await MemberEventStore(collection).settings(),
                                   MemberEventStore.default_settings())
    delivered = sent.get("delivered_at") if sent else None
    last_sent_at = (delivered.replace(tzinfo=delivered.tzinfo or timezone.utc).isoformat()
                    if delivered is not None else None)
    try:
        items = await _discord_items(request, saved)
    except Exception:  # Any Discord lookup failure degrades to one warning, never a 500.
        items = [dict(UNAVAILABLE)]
    if backlog > BACKLOG_LIMIT:
        items.append({"key": "backlog", "level": "warning", "text": f"{backlog} events waiting to send"})
    return _json({"items": items, "backlog": backlog, "last_sent_at": last_sent_at})


routes = [web.get(PREFIX + "/members/{user_id}", timeline), web.get(PREFIX + "/health", health)]
