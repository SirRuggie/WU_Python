"""Bounded current-clan lookups; never mistake signup snapshots for live locations."""
import asyncio
import time
import logging
from datetime import datetime, timezone
from .providers import ProviderUnavailable

async def enrich(request, accounts, *, force=False):
    cache = request.app.setdefault('roster_location_cache', {})
    gate = request.app.setdefault('roster_location_gate', asyncio.Semaphore(8))
    async def fetch(account):
        key = account['tag']
        old = cache.get(key)
        if not force and old and time.monotonic() - old[0] < 120:
            account.update(old[1])
            return
        try:
            async with gate:
                player = await request.app['providers'].player(key)
            values = {'current_clan_tag':player.get('current_clan_tag'),
                      'current_clan_name':player.get('current_clan_name'), 'current_clan_status':'current', 'current_clan_checked_at':datetime.now(timezone.utc).isoformat()}
            cache[key] = (time.monotonic(),values)
            account.update(values)
        except (ProviderUnavailable, TimeoutError):
            pass
    for account in accounts:
        old = cache.get(account['tag'])
        account.update({**old[1], 'current_clan_status':'stale'} if old else {'current_clan_tag':None,'current_clan_name':None,'current_clan_status':'unavailable'})
    tasks = [asyncio.create_task(fetch(account)) for account in accounts]
    if tasks:
        _, pending = await asyncio.wait(tasks,timeout=15 if force else 3)
        for task in pending: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
    if len(cache)>5000:
        for key in list(cache)[:len(cache)-5000]:cache.pop(key,None)


async def background_enrich(request, accounts, *, force=False):
    """Return a snapshot immediately; shared per-player jobs finish independently."""
    app = request.app
    cache = app.setdefault('roster_location_cache', {})
    jobs = app.setdefault('roster_location_jobs', {})
    failures = app.setdefault('roster_location_failures', {})
    gate = app.setdefault('roster_location_gate', asyncio.Semaphore(8))

    async def check(key):
        try:
            # The provider owns transport retries; do not multiply them here.
            async with gate:
                player = await asyncio.wait_for(app['providers'].player(key), timeout=35)
            cache[key] = (time.monotonic(), {
                'current_clan_tag': player.get('current_clan_tag'),
                'current_clan_name': player.get('current_clan_name'),
                'current_clan_status': 'current',
                'current_clan_checked_at': datetime.now(timezone.utc).isoformat()})
            failures.pop(key, None)
            for old_key in list(cache)[:max(0, len(cache) - 5000)]:
                cache.pop(old_key, None)
        except (ProviderUnavailable, TimeoutError):
            failures[key] = time.monotonic()
        except Exception:
            failures[key] = time.monotonic()
            logging.getLogger(__name__).exception('Clan location lookup failed')
        finally:
            jobs.pop(key,None)
            for old_key in list(failures)[:max(0, len(failures) - 5000)]:
                failures.pop(old_key, None)

    for account in accounts:
        key = account['tag']
        old = cache.get(key)
        fresh = old is not None and time.monotonic()-old[0] < 120 and key not in failures
        retry_allowed = key not in failures or time.monotonic()-failures[key] >= 30
        if key not in jobs and (force or (not fresh and retry_allowed)):
            jobs[key] = asyncio.create_task(check(key))
        updating = key in jobs
        account.update({**old[1], 'current_clan_status':'current' if fresh and not updating else 'stale'} if old else {
            'current_clan_tag':None,'current_clan_name':None,'current_clan_status':'unavailable'})
        account['location_updating'] = updating
    return any(account['location_updating'] for account in accounts)


async def lifecycle(app):
    app['roster_location_jobs'] = {}
    yield
    tasks = list(app['roster_location_jobs'].values())
    for task in tasks: task.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
