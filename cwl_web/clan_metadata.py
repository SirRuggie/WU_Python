"""Bounded, cached live league metadata; API errors never imply Unranked."""
import asyncio
import time
from .providers import ProviderUnavailable


async def enrich(request, clans):
    cache = request.app.setdefault('clan_league_cache', {})
    lock = request.app.setdefault('clan_league_lock', asyncio.Lock())
    async with lock:
        gate = asyncio.Semaphore(5)
        async def one(clan):
            saved = cache.get(clan['tag'])
            if saved and saved['expires'] > time.monotonic():
                clan.update(saved['data'])
                return
            async with gate:
                try:
                    result = await asyncio.wait_for(request.app['providers'].clan(clan['tag']), 8)
                    data = {'cwl_league': result.get('cwl_league'), 'cwl_league_stale': False}
                    ttl = 300
                except (ProviderUnavailable, TimeoutError):
                    data = {'cwl_league': saved['data']['cwl_league'] if saved else None, 'cwl_league_stale': True}
                    ttl = 30
                cache[clan['tag']] = {'data': data, 'expires': time.monotonic() + ttl}
                clan.update(data)
        await asyncio.gather(*(one(clan) for clan in clans))
    return clans
