"""Idempotent one-time seed coordinator; upstream transport is injected."""
import asyncio
import logging

log = logging.getLogger(__name__)
SEED_VERSION = 1


async def seed_players(store, fetch_last_online, *, force=False, sleep=asyncio.sleep):
    counts = {'seeded': 0, 'official_or_existing': 0, 'unavailable': 0, 'failed': 0, 'already_attempted': 0}
    rows = await store.all_players()
    for row in rows:
        if row.get('last_seen_at'):
            counts['official_or_existing'] += 1
            continue
        if row.get('seed_job_version') == SEED_VERSION and not force:
            counts['already_attempted'] += 1
            continue
        status = 'failed'
        try:
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
        except Exception:
            # Counts, not exception bodies: never expose DeveloperToken URLs.
            status = 'failed'
        counts[status] += 1
        await store.mark_seed_attempt(row['_id'], status, SEED_VERSION)
    log.info('Player activity one-time seed: %s', counts)
    return counts
