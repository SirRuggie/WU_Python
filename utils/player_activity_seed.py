"""Bounded one-time seed from ClashKing's observed attack history."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp

from utils.strike_store import tag, stamp

log = logging.getLogger(__name__)
SEED_VERSION = 1


class SeedHTTPError(RuntimeError):
    pass


async def fetch_battle_last_seen(http, player_tag, *, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)
    url = 'https://api.clashk.ing/v2/player/' + quote(tag(player_tag), safe='') + '/battlelog/history'
    async with http.get(url, params={'time[after]': cutoff.isoformat()}, allow_redirects=False) as response:
        if response.status != 200:
            raise SeedHTTPError('Battle history unavailable')
        payload = await response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        raise ValueError('Malformed battle history')
    values = []
    for row in payload['items']:
        value = row['battleTime']
        if isinstance(value, str) and len(value) == 20 and value[8] == 'T':
            seen = datetime.strptime(value, '%Y%m%dT%H%M%S.000Z').replace(tzinfo=timezone.utc)
        else:
            seen = stamp(value)
        if cutoff <= seen <= now:
            values.append(seen)
    return max(values) if values else None


async def seed_players(store, fetch_last_online, *, force=False, sleep=asyncio.sleep, timeout=120):
    counts = {key: 0 for key in ('seeded', 'official_or_existing', 'unavailable', 'failed',
                                 'non_200', 'timeout', 'already_attempted', 'pending')}
    semaphore = asyncio.Semaphore(5)
    rows = await store.all_players()

    async def one(row):
        if row.get('last_seen_at'):
            counts['official_or_existing'] += 1
            return
        if row.get('seed_job_version') == SEED_VERSION and not force:
            counts['already_attempted'] += 1
            return
        status = 'failed'
        try:
            async with semaphore:
                await sleep(1)
                seen = await fetch_last_online(row['_id'])
            if seen is None:
                status = 'unavailable'
            elif await store.seed(row['_id'], seen):
                status = 'seeded'
            else:
                status = 'official_or_existing'
        except asyncio.CancelledError:
            raise
        except SeedHTTPError:
            status = 'non_200'
        except (TimeoutError, asyncio.TimeoutError):
            status = 'timeout'
        except Exception:
            pass  # No upstream error bodies or credential-bearing URLs in logs.
        counts[status] += 1
        await store.mark_seed_attempt(row['_id'], status, SEED_VERSION)

    tasks = [asyncio.create_task(one(row)) for row in rows]
    if tasks:
        try:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        counts['timeout'] += len(pending)
        counts['pending'] = len(pending)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            if not task.cancelled() and task.exception():
                raise RuntimeError('Seed state could not be saved') from None
    log.info('Player activity one-time seed: %s', counts)
    return counts


async def seed_from_clashking(store):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
        return await seed_players(store, lambda player: fetch_battle_last_seen(http, player))
