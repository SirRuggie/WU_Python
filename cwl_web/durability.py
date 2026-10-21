"""Dashboard lifecycle for the shared Mongo recovery owner."""
import asyncio
import logging
from contextlib import suppress

from utils.cwl_dashboard_state import DashboardDurabilityError


async def lifecycle(app):
    durability = app['store'].durability
    if durability is None:
        yield
        return

    async def renew():
        while True:
            await asyncio.sleep(20)
            try:
                durability.heartbeat()
            except DashboardDurabilityError:
                logging.getLogger(__name__).critical(
                    'Dashboard durable storage unavailable; writes fenced until restart/recovery.')
                return

    worker = asyncio.create_task(renew())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
