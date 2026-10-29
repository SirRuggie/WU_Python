"""Read-only, five-minute campaign timing projection for member season data."""
import asyncio
import time
import logging
from contextlib import suppress
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from utils.cwl_campaign import load_campaign, signup_deadline
from .manage_bridge import GUILD_ID, _mongo

LOG = logging.getLogger(__name__)
REFRESH_SECONDS = 300
MAX_AGE_SECONDS = 6 * 60 * 60
SEASON_TIMEOUT_SECONDS = 30
PASS_TIMEOUT_SECONDS = 120


def eligible_bindings(app):
    now = datetime.now(timezone.utc)
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    cycles = (now.strftime('%Y-%m'), next_month.strftime('%Y-%m'))
    with app['store'].tx() as db:
        return {row['id']: row['cycle'] for row in db.execute(
            'SELECT s.id,b.cycle FROM seasons s JOIN manage_campaign_bindings b '
            'ON b.season_id=s.id WHERE (s.signup_open OR NOT EXISTS '
            '(SELECT 1 FROM roster_publications p WHERE p.season_id=s.id AND p.withdrawn_at IS NULL)) '
            'AND (b.cycle IN (?,?) OR s.id=(SELECT season_id FROM member_season WHERE id=1))', cycles)}


async def refresh(app):
    """One background Mongo context; failed seasons retain their last good result."""
    started = time.monotonic()
    pending = {}
    cache = app['member_timing_cache']
    refreshed = 0
    failed = set()
    completed = set()
    try:
        pending = eligible_bindings(app)
        if pending:
            async with asyncio.timeout(PASS_TIMEOUT_SECONDS):
                async with _mongo(SimpleNamespace(app=app)) as mongo:
                    for sid, cycle in pending.items():
                        try:
                            async with asyncio.timeout(SEASON_TIMEOUT_SECONDS):
                                loaded = await load_campaign(mongo, GUILD_ID, cycle)
                            campaign = loaded['campaign']
                            value = utc_timing(signup_deadline(campaign, cycle)) if campaign.get('signup_deadline') is not None else utc_timing(None)
                            cache[sid] = (time.monotonic(), cycle, value)
                            refreshed += 1
                        except Exception:
                            failed.add(sid)
                        completed.add(sid)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOG.exception('Member timing refresh failed; retaining last-good values')
        failed.update(set(pending) - completed)
    finally:
        LOG.info('Member timing refresh: refreshed=%d failures=%d elapsed=%.3fs',
                 refreshed, len(failed), time.monotonic() - started)


async def lifecycle(app):
    async def worker():
        while True:
            try:
                await refresh(app)
            except Exception:
                LOG.exception('Member timing worker pass failed; retrying next interval')
            await asyncio.sleep(REFRESH_SECONDS)

    task = asyncio.create_task(worker(), name='member-timing-refresh')
    app['member_timing_state']['task'] = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


def utc_timing(value):
    """Use standard aware datetimes so DST and Pendulum arithmetic cannot drop UTC."""
    empty = {'signup_deadline': None, 'placements_by': None}
    if value is None:
        return empty
    raw = value if isinstance(value, str) else value.isoformat()
    deadline = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if deadline.tzinfo is None or deadline.utcoffset() is None:
        return empty
    deadline = deadline.astimezone(timezone.utc)
    return {'signup_deadline': deadline.isoformat(),
            'placements_by': (deadline + timedelta(hours=24)).isoformat()}


async def season_timing(request, season_id):
    return (await seasons_timing(request, [season_id]))[0]


async def seasons_timing(request, season_ids):
    """Cache-only reads: no Mongo, waiting on locks, or refresh on request paths."""
    cache = request.app['member_timing_cache']
    bindings = eligible_bindings(request.app)
    now = time.monotonic()
    return [dict(cache[sid][2]) if sid in cache and bindings.get(sid) == cache[sid][1]
            and now - cache[sid][0] < MAX_AGE_SECONDS else utc_timing(None)
            for sid in season_ids]
