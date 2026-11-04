"""HTTP app ownership for raw activity snapshots, after live authorization."""

from aiohttp import web
from contextlib import asynccontextmanager

from utils.player_activity_cache import ActivitySnapshots

KEY = web.AppKey('strike_raw_activity_snapshots', ActivitySnapshots)


def snapshots(app):
    # Lazy construction also supports disconnected HTTP fixtures. No read or
    # refresh starts here; only an authorized handler supplies a raw-data loader.
    if KEY not in app:
        app[KEY] = ActivitySnapshots()
    return app[KEY]


@asynccontextmanager
async def changing_observations(app, guild_id):
    """Fence in-flight reads before and after a dashboard ledger write.

    The second invalidation also covers partial failures and a refresh started
    by another request while the write was pending. No durable write is added.
    """
    cache = app.get(KEY)
    if cache is not None:
        cache.invalidate_observations(guild_id)
    try:
        yield
    finally:
        cache = app.get(KEY)
        if cache is not None:
            cache.invalidate_observations(guild_id)


async def lifecycle(app):
    snapshots(app)
    try:
        yield
    finally:
        cache = app.get(KEY)
        if cache is not None:
            await cache.close()
