"""Staff-only member timeline and log health for the moderation archive."""
from __future__ import annotations

from datetime import timezone

from aiohttp import web

from utils import member_events as store_module
from utils.member_events import GUILD_ID, ID_PATTERN, MemberEventStore, public_event
from utils.member_event_settings import EVENT_TYPES, effective_event, normalize_settings
from .member_events import PREFIX, _bot_permissions, _resolve_option
from .server_management import mongo, require_manage

# Contract v2 history list. utils.member_events owns it once updated; until then
# fall back to the same tuple so the timeline never lags the contract.
_CONTRACT_HISTORY = ("join", "leave", "kick", "ban", "unban", "timeout_add", "timeout_remove",
                     "member_update", "roles_added", "roles_removed", "invite_use")
HISTORY_TYPES = (store_module.HISTORY_TYPES if "unban" in store_module.HISTORY_TYPES
                 else _CONTRACT_HISTORY)
BACKLOG_LIMIT = 25
VIEW_AUDIT_LOG = 1 << 7
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3
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
    events = [public_event(row, api_prefix=PREFIX) for row in rows[:limit]]
    newest = events[0]
    member = {"user_id": user_id, "display_name": newest["display_name"],
              "username": newest["username"], "avatar_url": newest["avatar_url"]}
    return _json({"member": member, "events": events, "next_before": next_before})


async def _discord_items(request, saved):
    actor, effective = await _bot_permissions(request)
    rights = int(actor["permissions"])
    items = []
    if not rights & ADMINISTRATOR and not rights & VIEW_AUDIT_LOG:
        items.append({"key": "audit_log", "level": "warning", "text": "View Audit Log needed for moderator names"})
    if not rights & ADMINISTRATOR and not rights & MANAGE_GUILD:
        items.append({"key": "manage_server", "level": "warning", "text": "Manage Server needed for invite counts"})
    options = {}
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
