"""Capture the latest usable FWA war lineup independently of editor visits."""
import asyncio
from contextlib import suppress
import logging


async def capture_lineups(app):
    directory = await app['providers'].family_clans()
    for clan in directory['clans']:
        if clan.get('type') != 'FWA':
            continue
        try:
            lineup = await app['providers'].weight_war_lineup(clan['tag'])
            app['clan_weight_trial'].remember_lineup(clan['tag'], lineup)
        except Exception:
            # An inaccessible/partial war never clears the last valid lineup.
            logging.getLogger(__name__).debug('War lineup capture unavailable for %s', clan['tag'])


async def lineup_lifecycle(app):
    async def worker():
        while True:
            try:
                await capture_lineups(app)
            except Exception:
                logging.getLogger(__name__).warning('Clan weight lineup capture unavailable; saved lineups retained')
            await asyncio.sleep(600)

    task = None
    if not app.get('dev_fixture') and getattr(app['providers'], 'coc_token', None):
        task = asyncio.create_task(worker())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
