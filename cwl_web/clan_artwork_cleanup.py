"""Own the retry task for confirmed clan artwork replacements."""
import asyncio
from contextlib import suppress
import logging
import os
from types import SimpleNamespace

from utils.clan_dashboard_history import cleanup_artwork
from utils.media_store import MediaStore
from .server_management import mongo


async def lifecycle(app):
    media = app.get('server_management_media') or MediaStore.from_env()
    task = None
    if not app.get('dev_fixture') and getattr(media, 'configured', False) and (app.get('server_management_mongo') or os.getenv('MONGODB_URI')):
        async def worker():
            while True:
                try:
                    async with mongo(SimpleNamespace(app=app)) as db:
                        await cleanup_artwork(db, media)
                except Exception:
                    logging.getLogger(__name__).exception('Clan artwork cleanup unavailable; will retry')
                await asyncio.sleep(300)
        task = asyncio.create_task(worker())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
