"""Optional roster display metadata, independent of saved assignments and access."""
import asyncio
import time
import logging

from .providers import ProviderUnavailable
from .clan_metadata import background_enrich as leagues
from .roster_locations import background_enrich as locations


async def enrich(request, result):
    app = request.app
    now = time.monotonic()
    cached = app.get('roster_family_snapshot')
    if (not cached or cached[0] <= now) and not app.get('roster_family_job'):
        async def fetch():
            try:
                family = await asyncio.wait_for(app['providers'].family_clans(), 15)
                app['roster_family_snapshot'] = (time.monotonic() + 120, {c['tag'] for c in family['clans']})
            except Exception as error:
                if not isinstance(error, (ProviderUnavailable, TimeoutError)):
                    logging.getLogger(__name__).exception('Roster family lookup failed')
                app['roster_family_snapshot'] = (time.monotonic() + 30, None)
            finally:
                app['roster_family_job'] = None
        app['roster_family_job'] = asyncio.create_task(fetch())
    family = cached[1] if cached and cached[0] > now else None
    updating_leagues = await leagues(request, result['clans'])
    updating_locations = await locations(request, result['accounts'])
    result['metadata_updating'] = bool(app.get('roster_family_job') or updating_leagues or updating_locations)
    return family


async def lifecycle(app):
    yield
    job = app.get('roster_family_job')
    if job:
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
