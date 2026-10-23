"""Shared per-clan league lookups; slow clans never lock unrelated cache reads."""
import asyncio
import logging
import time

from .providers import ProviderUnavailable


def _prepare(request, clans):
    app = request.app
    cache = app.setdefault('clan_league_cache', {})
    jobs = app.setdefault('clan_league_jobs', {})
    gate = app.setdefault('clan_league_gate', asyncio.Semaphore(5))

    async def fetch(tag):
        saved = cache.get(tag)
        try:
            async with gate:
                result = await asyncio.wait_for(app['providers'].clan(tag), 35)
            data = {'cwl_league': result.get('cwl_league'), 'cwl_league_stale': False}
            ttl = 300
        except Exception as error:
            if not isinstance(error, (ProviderUnavailable, TimeoutError)):
                logging.getLogger(__name__).exception('Clan league lookup failed')
            data = {'cwl_league': saved['data']['cwl_league'] if saved else None,
                    'cwl_league_stale': True}
            ttl = 30
        finally:
            jobs.pop(tag, None)
        cache[tag] = {'data': data, 'expires': time.monotonic() + ttl}
        for key in list(cache)[:max(0, len(cache) - 5000)]:
            cache.pop(key, None)

    for clan in clans:
        tag = clan['tag']
        saved = cache.get(tag)
        fresh = saved and saved['expires'] > time.monotonic()
        if not fresh and tag not in jobs:
            jobs[tag] = asyncio.create_task(fetch(tag))
        clan.update(saved['data'] if fresh else {
            'cwl_league': saved['data']['cwl_league'] if saved else None,
            'cwl_league_stale': True})
    return [jobs[clan['tag']] for clan in clans if clan['tag'] in jobs]


async def background_enrich(request, clans):
    """Copy cached metadata immediately and coalesce refreshes across callers."""
    return bool(_prepare(request, clans))


async def enrich(request, clans):
    tasks = _prepare(request, clans)
    if tasks:
        # Legacy callers get a bounded wait; jobs continue for the next read.
        # asyncio.wait does not cancel shared tasks on timeout/disconnection.
        await asyncio.wait(tasks, timeout=3)
        cache = request.app['clan_league_cache']
        for clan in clans:
            if clan['tag'] in cache:
                clan.update(cache[clan['tag']]['data'])
                if clan['tag'] in request.app['clan_league_jobs']:
                    clan['cwl_league_stale'] = True
    return clans


async def lifecycle(app):
    app['clan_league_jobs'] = {}
    yield
    tasks = list(app['clan_league_jobs'].values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
