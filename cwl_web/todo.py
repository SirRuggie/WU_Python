"""Authenticated personal Todo feed for the CWL website."""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from aiohttp import web

from utils import clan_history, todo_data
from utils.mongo import MongoClient
from utils.startup import create_authenticated_clash_client
from .providers import ProviderUnavailable

API = "/api/cwl/todo"
CACHE_SECONDS = 60
CACHE_MAX = 1024
VIEW_TIMEOUT = 35
logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _unavailable(note):
    return {"ok": False, "note": note, "notes": [note], "unavailable": note,
            "incomplete": note, "rows": []}


def _row(row):
    total = row.limit if row.limit > 0 else None
    return {"tag": row.tag, "name": row.account, "town_hall": row.town_hall,
            "clan_tag": row.clan_tag, "clan_name": row.clan_name,
            "badge_url": row.clan_badge, "used": row.used if total else None,
            "total": total, "remaining": max(0, total - row.used) if total else None,
            "starts_at": row.starts_at, "ends_at": row.ends_at,
            "state": row.state, "detail": row.reason or None}


def _view(view, extra=""):
    notes = list(view.notes)
    if view.incomplete:
        notes.append(view.incomplete)
    if extra:
        notes.append(extra)
    return {"ok": bool(view.ok),
            "note": "; ".join(dict.fromkeys(notes)) or view.unavailable,
            "notes": list(dict.fromkeys(notes)), "unavailable": view.unavailable,
            "incomplete": "; ".join(part for part in (view.incomplete, extra) if part),
            "rows": [_row(row) for row in view.rows]}


def _account(account):
    return {"tag": account.tag, "name": account.name, "town_hall": account.town_hall,
            "current_clan_tag": account.clan_tag, "current_clan_name": account.clan_name,
            "current_clan_badge_url": account.clan_badge}


async def get_clash_client(app):
    """Return the shared, lifecycle-managed game API client for dashboard reads."""
    client = app["todo_client"]
    if client is not None:
        return client
    token = os.getenv("COC_API_TOKEN", "").strip()
    if not token:
        raise ProviderUnavailable("Clash API is not configured")
    async with app["todo_client_lock"]:
        client = app["todo_client"]
        if client is None:
            try:
                client = await asyncio.wait_for(create_authenticated_clash_client(token), 10)
            except Exception as exc:
                logger.warning("Todo Clash client initialization failed: %s", type(exc).__name__)
                raise ProviderUnavailable("Clash API is unavailable") from exc
            app["todo_client"] = client
    return client


async def _history(app, tags):
    uri = getattr(app["providers"], "mongo_uri", "")
    if not uri:
        return {}, "Recent clan history is unavailable"
    mongo = MongoClient(uri, serverSelectionTimeoutMS=3000, timeoutMS=5000)
    try:
        candidates = await asyncio.wait_for(
            clan_history.load_candidates(mongo, tags, create_indexes=False, raise_errors=True), 7)
        return candidates, ""
    except Exception as exc:
        logger.warning("Todo clan history unavailable: %s", type(exc).__name__)
        return {}, "Recent clan history is unavailable"
    finally:
        await mongo.close()


async def _fwa_outcomes(app, rows):
    from utils.todo_fwa import load_fwa_records, matching_outcome
    if not rows:
        return [], ''
    uri = getattr(app['providers'], 'mongo_uri', '')
    if not uri:
        return [None for _ in rows], 'FWA war outcomes could not be checked'
    mongo = MongoClient(uri, serverSelectionTimeoutMS=3000, timeoutMS=5000)
    try:
        records = await asyncio.wait_for(load_fwa_records(mongo, rows, strict=True), 7)
        return [matching_outcome(row, records) for row in rows], ''
    except Exception as exc:
        logger.warning('Todo FWA outcomes unavailable: %s', type(exc).__name__)
        return [None for _ in rows], 'FWA war outcomes could not be checked'
    finally:
        await mongo.close()


async def _section(fn, *args, **kwargs):
    try:
        return await asyncio.wait_for(fn(*args, **kwargs), VIEW_TIMEOUT)
    except Exception as exc:
        logger.warning("Todo section failed: %s", type(exc).__name__)
        return None


async def _live_snapshot(app, tags):
    client = await get_clash_client(app)

    sem = todo_data.new_semaphore()
    accounts_result, history_result = await asyncio.gather(
        _section(todo_data.fetch_accounts, client, tags, sem=sem),
        _history(app, tags),
    )
    if accounts_result is None:
        accounts, errors = [], ["Account lookups timed out"]
    else:
        accounts, errors = accounts_result
    candidates, history_note = history_result
    account_note = f"{len(errors)} linked account(s) could not be checked" if errors else ""
    if tags and not accounts:
        raise ProviderUnavailable(account_note or "Linked accounts could not be checked")

    from .todo_games import build_games_view
    games_task = asyncio.create_task(_section(build_games_view, accounts))
    try:
        war, cwl, raid = await asyncio.gather(
            _section(todo_data.build_war_view, client, accounts, sem=sem, candidates=candidates),
            _section(todo_data.build_cwl_view, client, accounts, sem=sem, candidates=candidates),
            _section(todo_data.build_raid_view, client, accounts, sem=sem),
        )
        private = await _section(todo_data.build_blocked_view, client, accounts, sem=sem, candidates=candidates)
        result = {}
        for key, view in (("war", war), ("cwl", cwl), ("raid", raid), ("private", private)):
            extra = account_note
            if key in ("war", "cwl", "private") and history_note:
                extra = "; ".join(filter(None, (extra, history_note)))
            result[key] = _view(view, extra) if view else _unavailable(f"{key.title()} status could not be checked")

        if war:
            outcomes, fwa_note = await _fwa_outcomes(app, war.rows)
            for row, outcome in zip(result['war']['rows'], outcomes):
                row['fwa_outcome'] = outcome
            if fwa_note:
                result['war']['notes'].append(fwa_note)

        games = await games_task
        result["games"] = games if games is not None else _unavailable("Current Clan Games progress is unavailable")
        if account_note:
            games_view = result["games"]
            games_view["incomplete"] = "; ".join(filter(None, (games_view.get("incomplete"), account_note)))
            games_view["note"] = "; ".join(filter(None, (games_view.get("note"), account_note)))
    finally:
        if not games_task.done():
            games_task.cancel()
            await asyncio.gather(games_task, return_exceptions=True)
    return {"checked_at": _now(), "accounts": [_account(account) for account in accounts],
            "views": result}


def _fixture(app, tags):
    players = app["providers"].players
    accounts = [{**players[tag], "current_clan_badge_url": players[tag].get("current_clan_badge_url")}
                for tag in tags if tag in players]
    def row(account, used, total, detail=None):
        return {"tag": account["tag"], "name": account["name"],
                "town_hall": account["town_hall"], "clan_tag": account["current_clan_tag"],
                "clan_name": account["current_clan_name"], "badge_url": None,
                "used": used, "total": total,
                "remaining": max(0, total-used) if total is not None else None,
                "starts_at": None, "ends_at": None, "state": "inWar", "detail": detail}
    def section(rows):
        return {"ok": True, "note": "Fictional development data", "notes": [],
                "unavailable": "", "incomplete": "", "rows": rows}
    views = {"war": section([row(accounts[0], 1, 2)] if accounts else []),
             "cwl": section([row(accounts[1], 0, 1)] if len(accounts)>1 else []),
             "raid": section([row(accounts[0], 2, 5)] if accounts else []),
             "private": section([row(accounts[-1], None, None, "private")] if accounts else []),
             "games": section([row(accounts[0], 2450, None)] if accounts else [])}
    for key in ("war", "cwl", "raid", "private"):
        for item in views[key]["rows"]:
            if key == "private":
                item["state"] = "private"
    for item in views['war']['rows']:
        item['fwa_outcome'] = {'status': 'win', 'opponent': 'Fixture FWA Opponent'}
    for item in views["games"]["rows"]:
        item["state"] = "reported"
    from .todo_games import event_window
    start, end = event_window(datetime.now(timezone.utc))
    views["games"].update(season=start.strftime("%Y-%m"), source="ClashPerk (sample)", checked_at=_now(),
                          event_start=start.timestamp(), event_end=end.timestamp())
    return {"checked_at": _now(), "accounts": accounts, "views": views}


def _prune(cache):
    now = time.monotonic()
    for key, (expiry, _) in list(cache.items()):
        if expiry <= now:
            cache.pop(key, None)
    while len(cache) > CACHE_MAX:
        cache.pop(next(iter(cache)))


async def _snapshot(app, user_id):
    try:
        try:
            links = await asyncio.wait_for(app["providers"].linked_tags(user_id), 10)
        except Exception as exc:
            logger.warning("Todo linked tags unavailable: %s", type(exc).__name__)
            raise ProviderUnavailable("Linked accounts could not be checked") from exc
        tags = list(links)[:100]
        if not tags:
            empty = _view(todo_data.ViewData())
            result = {"checked_at": _now(), "accounts": [],
                      "views": {key: dict(empty) for key in ("war", "cwl", "raid", "private", "games")}}
        else:
            result = _fixture(app, tags) if app["dev_fixture"] and hasattr(app["providers"], "players") else await _live_snapshot(app, tags)
            if len(links) > 100:
                for view in result["views"].values():
                    view["ok"] = False
                    view["incomplete"] = "More than 100 linked accounts; some were not checked"
        cache = app["todo_cache"]
        cache[user_id] = (time.monotonic() + CACHE_SECONDS, result)
        _prune(cache)
        return result
    finally:
        app["todo_inflight"].pop(user_id, None)


def _observe(task):
    if not task.cancelled():
        task.exception()


async def todo(request):
    # Import here to avoid a route-module cycle while sharing the existing session.
    from .app import _require
    user_id = _require(request)["user_id"]
    app = request.app
    _prune(app["todo_cache"])
    cached = app["todo_cache"].get(user_id)
    if cached:
        return web.json_response(cached[1])
    task = app["todo_inflight"].get(user_id)
    if task is None:
        task = asyncio.create_task(_snapshot(app, user_id))
        task.add_done_callback(_observe)
        app["todo_inflight"][user_id] = task
    return web.json_response(await asyncio.shield(task))


async def lifecycle(app):
    yield
    tasks = list(app["todo_inflight"].values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    client = app["todo_client"]
    if client is not None:
        await client.close()
    app["todo_inflight"].clear()
    app["todo_cache"].clear()


def routes():
    return [web.get(API, todo)]
