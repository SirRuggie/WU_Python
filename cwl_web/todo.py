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


async def _task_accounts(client, tags, sem):
    """Keep completed player reads when one account stalls; never use stale identity."""
    tasks = [asyncio.create_task(todo_data.fetch_accounts(client, [tag], sem=sem, lookup_timeout=3)) for tag in tags]
    try:
        done, _ = await asyncio.wait(tasks, timeout=min(VIEW_TIMEOUT, 8))
        accounts, errors = [], []
        for tag, task in zip(tags, tasks):
            if task not in done:
                errors.append(f'{tag}: lookup timed out')
                continue
            try:
                found, failed = task.result()
                accounts.extend(found)
                errors.extend(failed)
            except Exception:
                errors.append(f'{tag}: lookup unavailable')
        return accounts, errors
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _live_snapshot(app, tags, publish=None):
    client = await get_clash_client(app)

    sem = todo_data.new_semaphore()
    accounts_result, history_result = await asyncio.gather(
        _task_accounts(client, tags, sem),
        _history(app, tags),
    )
    accounts, errors = accounts_result
    candidates, history_note = history_result
    account_note = f"{len(errors)} linked account(s) could not be checked" if errors else ""
    if tags and not accounts:
        raise ProviderUnavailable(account_note or "Linked accounts could not be checked")

    from .todo_games import build_games_view
    result = {key: dict(_unavailable('Checking this activity…'), loading=True)
              for key in ('war', 'cwl', 'raid', 'private', 'games')}
    def snapshot():
        return {"checked_at": _now(), "accounts": [_account(account) for account in accounts],
                "views": dict(result)}
    def notify():
        if publish:
            publish(snapshot())
    notify()

    async def load(key, builder, **kwargs):
        with todo_data.bounded_clan_reads(8):
            # Four activity builders get two slots each. Slow war reads must
            # not occupy every slot and prevent raids/CWL from even starting.
            view = await _section(builder, client, accounts, sem=todo_data.new_semaphore(2), **kwargs)
        extra = account_note
        if key in ('war', 'cwl', 'private') and history_note:
            extra = '; '.join(filter(None, (extra, history_note)))
        result[key] = _view(view, extra) if view else _unavailable(f'{key.title()} status could not be checked')
        notify()
        if key == 'war' and view:
            outcomes, fwa_note = await _fwa_outcomes(app, view.rows)
            enriched = dict(result[key], rows=[dict(row, fwa_outcome=outcome)
                for row, outcome in zip(result[key]['rows'], outcomes)])
            if fwa_note:
                enriched['notes'] = [*enriched['notes'], fwa_note]
            result[key] = enriched
            notify()

    async def games():
        view = await _section(build_games_view, accounts)
        result['games'] = view if view is not None else _unavailable('Current Clan Games progress is unavailable')
        if account_note:
            result['games'] = dict(result['games'],
                incomplete='; '.join(filter(None, (result['games'].get('incomplete'), account_note))),
                note='; '.join(filter(None, (result['games'].get('note'), account_note))))
        notify()

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(load('war', todo_data.build_war_view, candidates=candidates))
        tasks.create_task(load('cwl', todo_data.build_cwl_view, candidates=candidates))
        tasks.create_task(load('raid', todo_data.build_raid_view))
        tasks.create_task(load('private', todo_data.build_blocked_view, candidates=candidates))
        tasks.create_task(games())
    return snapshot()


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


async def _snapshot(app, user_id, progress=None):
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
            result = _fixture(app, tags) if app["dev_fixture"] and hasattr(app["providers"], "players") else await _live_snapshot(app, tags, publish=(lambda value: progress.update(snapshot=value)) if progress is not None else None)
            if len(links) > 100:
                for view in result["views"].values():
                    view["ok"] = False
                    view["incomplete"] = "More than 100 linked accounts; some were not checked"
        cache = app["todo_cache"]
        ttl = 15 if any(not view["ok"] or view.get("incomplete") for view in result["views"].values()) else CACHE_SECONDS
        cache[user_id] = (time.monotonic() + ttl, result)
        _prune(cache)
        return result
    except Exception:
        if progress is not None:
            progress.update(error='Tasks could not be updated. Please try again.', expires=time.monotonic() + 5)
        raise
    finally:
        if progress is not None:
            progress['updating'] = False
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
        return web.json_response({'snapshot': cached[1], 'updating': False} if request.query.get('background') == '1' else cached[1],
            headers={'Cache-Control': 'no-store'})
    background = request.query.get('background') == '1'
    states = app.setdefault('todo_progress', {})
    for uid, state in list(states.items()):
        if uid not in app['todo_inflight'] and state.get('expires', 0) <= time.monotonic():
            states.pop(uid, None)
    task = app['todo_inflight'].get(user_id)
    state = states.get(user_id)
    if task is None and not (background and state and state.get('error')):
        if len(app['todo_inflight']) >= 100:
            raise web.HTTPServiceUnavailable(text='Tasks are busy. Please try again shortly.')
        state = {'snapshot': None, 'updating': True}
        states[user_id] = state
        task = asyncio.create_task(_snapshot(app, user_id, state))
        task.add_done_callback(_observe)
        app['todo_inflight'][user_id] = task
    if background:
        return web.json_response({'snapshot': state.get('snapshot'),
            'updating': state.get('updating', False), 'error': state.get('error')},
            headers={'Cache-Control': 'no-store'})
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
    app.get("todo_progress", {}).clear()


def routes():
    return [web.get(API, todo)]
