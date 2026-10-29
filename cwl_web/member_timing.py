"""Read-only, five-minute campaign timing projection for member season data."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from utils.cwl_campaign import load_campaign, signup_deadline
from .manage_bridge import GUILD_ID, _mongo


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
    """One bounded Mongo context per batch; an outage is cached across seasons."""
    empty = {'signup_deadline': None, 'placements_by': None}
    state = request.app['member_timing_state']
    cache = request.app['member_timing_cache']
    async with state['lock']:
        now = time.monotonic()
        pending = {}
        with request.app['store'].tx() as db:
            for sid in season_ids:
                eligible = db.execute('SELECT signup_open OR NOT EXISTS(SELECT 1 FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL) FROM seasons WHERE id=?', (sid, sid)).fetchone()
                if not eligible or not eligible[0]:
                    cache[sid] = (now, empty.copy())
                    continue
                cached = cache.get(sid)
                if cached and now - cached[0] < 300:
                    continue
                row = db.execute('SELECT cycle FROM manage_campaign_bindings WHERE season_id=?', (sid,)).fetchone()
                cache[sid] = (now, empty.copy())
                if row:
                    pending[sid] = row['cycle']
        if pending and now >= state['retry_at']:
            try:
                async with asyncio.timeout(1.5):
                    async with _mongo(request) as mongo:
                        for sid, cycle in pending.items():
                            loaded = await load_campaign(mongo, GUILD_ID, cycle)
                            result = empty.copy()
                            if loaded['campaign'].get('signup_deadline') is not None:
                                result = utc_timing(signup_deadline(loaded['campaign'], cycle))
                            cache[sid] = (time.monotonic(), result)
            except asyncio.CancelledError:
                for sid in pending:
                    cache.pop(sid, None)
                raise
            except Exception:
                # Cache failures too; do not create one slow attempt per season.
                state['retry_at'] = time.monotonic() + 300
                for sid in pending:
                    cache[sid] = (time.monotonic(), empty.copy())
        return [dict(cache[sid][1]) for sid in season_ids]
