"""Dashboard lifecycle for the shared Mongo recovery owner."""

import asyncio
import logging
from contextlib import suppress

from utils.cwl_dashboard_state import DashboardDurabilityError


async def lifecycle(app):
    durability = app["store"].durability
    if durability is None:
        yield
        return

    async def renew():
        degraded = False
        while True:
            await asyncio.sleep(20)
            try:
                if durability.poisoned:
                    await asyncio.to_thread(app["store"].recover_durability)
                else:
                    durability.heartbeat()
                if degraded:
                    logging.getLogger(__name__).info(
                        "Dashboard durable storage recovered; saved receipts reconciled."
                    )
                degraded = False
            except DashboardDurabilityError:
                if not degraded:
                    logging.getLogger(__name__).warning(
                        "Dashboard storage is recovering; saves are temporarily unavailable."
                    )
                degraded = True

    worker = asyncio.create_task(renew())
    try:
        yield
    finally:
        role_backup = app.get("pool_role_backup_task")
        if role_backup is not None:
            with suppress(Exception):
                await role_backup
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
