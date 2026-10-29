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
    cache = request.app.setdefault('member_timing_cache', {})
    cached = cache.get(season_id)
    if cached and time.monotonic() - cached[0] < 300:
        return dict(cached[1])
    result = {'signup_deadline': None, 'placements_by': None}
    try:
        with request.app['store'].tx() as db:
            row = db.execute('SELECT cycle FROM manage_campaign_bindings WHERE season_id=?', (season_id,)).fetchone()
        if row:
            async with _mongo(request) as mongo:
                loaded = await load_campaign(mongo, GUILD_ID, row['cycle'])
            if loaded['campaign'].get('signup_deadline') is not None:
                result = utc_timing(signup_deadline(loaded['campaign'], row['cycle']))
    except asyncio.CancelledError:
        raise
    except Exception:
        # Optional member guidance must not prevent reading saved signups.
        pass
    cache[season_id] = (time.monotonic(), result)
    return dict(result)
