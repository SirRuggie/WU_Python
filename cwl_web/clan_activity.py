"""Authenticated read-only clan activity, separate from personal unfinished tasks."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from aiohttp import web
from utils import todo_data
from .providers import ProviderUnavailable
from .todo import get_clash_client

logger = logging.getLogger(__name__)
MAX_CLANS = 100


async def build_snapshot(app, user_id, scope, kind):
    warnings = []
    if scope == 'family':
        directory = await asyncio.wait_for(app['providers'].family_clans(), 10)
        clans = {clan['tag']: clan['name'] for clan in directory['clans']}
    else:
        links = await asyncio.wait_for(app['providers'].linked_tags(user_id), 10)
        tags = list(links)[:100]
        if len(links) > 100:
            warnings.append('Only the first 100 linked accounts were checked.')
        if not tags:
            return {'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': scope, 'clans': [], 'warnings': warnings}
        client = await get_clash_client(app)
        accounts, errors = await todo_data.fetch_accounts(client, tags)
        if errors:
            warnings.append(f'{len(errors)} linked accounts could not be checked; their clans may be missing.')
        if not accounts:
            raise ProviderUnavailable('Linked accounts could not be checked')
        clans = {account.clan_tag: account.clan_name or account.clan_tag for account in accounts if account.clan_tag}
    if len(clans) > MAX_CLANS:
        warnings.append(f'Only the first {MAX_CLANS} clans were checked.')
    client = await get_clash_client(app) if clans else None
    semaphore = asyncio.Semaphore(8)
    async def one(tag, name):
        async with semaphore:
            try:
                data = await todo_data.fetch_clan_overview(client, tag, kind)
            except Exception as exc:
                logger.warning('Clan activity projection failed: %s', type(exc).__name__)
                data = {key: {'state': 'error'} for key in (('raid',) if kind == 'raid' else ('regular', 'cwl'))}
            return {'tag': tag, 'name': name, **data}
    rows = await asyncio.gather(*(one(tag, name) for tag, name in list(clans.items())[:MAX_CLANS]))
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': scope, 'clans': rows, 'warnings': warnings}


async def _load(app, key):
    try:
        result = await asyncio.wait_for(build_snapshot(app, *key), 60)
        app['clan_activity_cache'][key] = (time.monotonic() + 60, result)
        return result
    except Exception as exc:
        logger.warning('Clan activity snapshot failed: %s', type(exc).__name__)
        raise ProviderUnavailable('Clan activity is unavailable. Please retry.') from exc
    finally:
        app['clan_activity_inflight'].pop(key, None)


def _observe(task):
    if not task.cancelled():
        task.exception()


async def activity(request):
    from .app import _require
    scope = request.query.get('scope', 'mine')
    kind = request.query.get('kind', 'war')
    if scope not in ('mine', 'family') or kind not in ('war', 'raid'):
        raise web.HTTPBadRequest(text='Invalid activity scope or kind')
    session = _require(request, 'editor' if scope == 'family' else 'member')
    key = (session['user_id'], scope, kind)
    app = request.app
    cache = app['clan_activity_cache']
    for cached_key, (expiry, _) in list(cache.items()):
        if expiry <= time.monotonic():
            cache.pop(cached_key, None)
    while len(cache) > 512:
        cache.pop(next(iter(cache)))
    if key in cache:
        return web.json_response(cache[key][1])
    task = app['clan_activity_inflight'].get(key)
    if task is None:
        task = asyncio.create_task(_load(app, key))
        task.add_done_callback(_observe)
        app['clan_activity_inflight'][key] = task
    return web.json_response(await asyncio.shield(task))


async def lifecycle(app):
    yield
    tasks = list(app['clan_activity_inflight'].values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    app['clan_activity_cache'].clear()


def setup(app):
    app['clan_activity_cache'] = {}
    app['clan_activity_inflight'] = {}
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/api/cwl/clan-activity', activity)
