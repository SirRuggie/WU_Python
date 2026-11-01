"""Staff-only, explicit reads of extra members in Lazy hosting clans."""

import asyncio
from aiohttp import web
from utils.declaration_extras import extras_for
from .clan_weights import observations


def snapshot(request, source):
    from .app import (
        _sid,
        _season,
        _latest_publication,
        _rule_rows,
        _roster_rows,
        _revision,
    )

    sid = _sid(request)
    with request.app["store"].tx() as db:
        _season(db, sid)
        if source == "published":
            publication = _latest_publication(db, sid)
            if not publication:
                raise web.HTTPConflict(text="No published roster is available")
            accounts = [
                dict(row)
                for row in db.execute(
                    "SELECT tag,assigned_clan_tag,assigned_clan_name FROM publication_accounts WHERE publication_id=?",
                    (publication["id"],),
                )
            ]
            clans = _rule_rows(db, sid)
            basis = publication["version"]
        else:
            accounts = _roster_rows(db, sid)
            clans = _rule_rows(db, sid)
            basis = _revision(db, sid)
    return accounts, clans, basis


async def check(request):
    from .app import _require

    _require(request, "editor")
    source = request.query.get("source", "published")
    if source not in ("published", "draft"):
        raise web.HTTPBadRequest(text="Choose the shown roster source")
    accounts, clans, basis = snapshot(request, source)
    current_accounts, _, current_revision = snapshot(request, "draft")
    expected = request.query.get("basis")
    if expected is not None and expected != str(basis):
        raise web.HTTPConflict(text="Roster changed. Refresh before checking members.")
    assigned = {row.get("assigned_clan_tag") for row in accounts}
    lazy = [
        clan
        for clan in clans
        if clan.get("pool") == "lazy"
        and (clan.get("capacity") is not None or clan["tag"] in assigned)
    ]
    if len(lazy) > 100:
        raise web.HTTPServiceUnavailable(
            text="Too many hosting clans to check together"
        )
    names = {clan["tag"]: clan["name"] for clan in clans}
    cache = observations(request.app)
    force = request.query.get("refresh") == "1"
    gate = asyncio.Semaphore(2)
    deadline = asyncio.get_running_loop().time() + 30

    async def one(clan, index):
        # One page-load/manual request only; no timers, scheduling or polling.
        timed_out = False
        try:
            async with asyncio.timeout_at(deadline):
                await asyncio.sleep(index * 0.15)
                async with gate:
                    saved = await cache.refresh_roster(clan["tag"], force=force)
        except TimeoutError:
            saved = cache.roster(clan["tag"])
            timed_out = True
        current = saved["status"] == "current" and not timed_out
        try:
            extras = (
                extras_for(
                    clan["tag"],
                    saved["value"]["members"],
                    accounts,
                    names,
                    current_accounts=current_accounts,
                )
                if current
                else None
            )
        except (KeyError, TypeError, ValueError):
            current = False
            extras = None
        return {
            "tag": clan["tag"],
            "name": clan["name"],
            "status": "current" if current else "unavailable",
            "capacity": clan.get("capacity"),
            "checked_at": saved.get("checked_at"),
            "count": len(extras) if extras is not None else None,
            "extras": extras,
        }

    rows = await asyncio.gather(*(one(clan, index) for index, clan in enumerate(lazy)))
    if (
        snapshot(request, source)[2] != basis
        or snapshot(request, "draft")[2] != current_revision
    ):
        raise web.HTTPConflict(
            text="Roster changed while members were checked. Refresh again."
        )
    return web.json_response({"source": source, "basis": basis, "clans": rows})


def routes():
    return [web.get("/api/cwl/seasons/{season_id}/declaration-extras", check)]
