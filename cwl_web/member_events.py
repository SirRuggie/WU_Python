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
    if kind not in ("", "join", "leave"):
        raise web.HTTPBadRequest(text="Choose join or leave.")
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
