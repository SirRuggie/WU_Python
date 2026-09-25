"""Retry isolated Discord test tickets and their scheduled cleanup."""

from __future__ import annotations

import asyncio
import logging

import hikari
import lightbulb

from extensions.commands.tickets import console, resolve, testing_service, thread_service
from utils.mongo import MongoClient

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
_worker: asyncio.Task | None = None


async def _run(bot: hikari.GatewayBot, mongo: MongoClient) -> None:
    scoped = testing_service.test_mongo(mongo)
    guarded = testing_service.test_bot(bot, scoped)
    indexes_ready = False
    while True:
        try:
            if not indexes_ready:
                await testing_service.ensure_test_indexes(scoped)
                indexes_ready = True
            await testing_service.cleanup_due(guarded, scoped)
            window = await scoped.ticket_automation_state.find_one({
                "_id": testing_service.WINDOW_ID, "mode": testing_service.MODE,
            }) or {}
            if window and not await testing_service.active_window(scoped):
                if window.get("parents_access_closed_at") != window.get("opened_at"):
                    from utils.ticket_testing_control import WINDOW_LOCK, sync_parent_access
                    async with WINDOW_LOCK:
                        fresh = await scoped.ticket_automation_state.find_one({
                            "_id": testing_service.WINDOW_ID, "mode": testing_service.MODE,
                        }) or {}
                        if (fresh.get("opened_at") == window.get("opened_at")
                            and fresh.get("parents_access_closed_at") != fresh.get("opened_at")
                            and not await testing_service.active_window(scoped)):
                            await sync_parent_access(bot, scoped, None)
                            await scoped.ticket_automation_state.update_one(
                                {"_id": testing_service.WINDOW_ID, "mode": testing_service.MODE,
                                 "opened_at": window.get("opened_at")},
                                {"$set": {"parents_access_closed_at": window.get("opened_at")}},
                            )
            if await testing_service.active_window(scoped):
                await thread_service.recover_pending_thread_ticket_creations(
                    bot=guarded, mongo=scoped, limit=25,
                )
            await console.recover_pending_staff_identity_contexts(
                bot=guarded, mongo=scoped, limit=25,
            )
            await resolve.reconcile_pending_resolution_effects(
                guarded, scoped, limit=25,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("isolated ticket test recovery failed; retrying")
        await asyncio.sleep(60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start_ticket_testing(
    _: hikari.StartedEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_run(bot, mongo), name="ticket-test-recovery")


@loader.listener(hikari.StoppingEvent)
async def stop_ticket_testing(_: hikari.StoppingEvent) -> None:
    global _worker
    if _worker is not None and not _worker.done():
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
    _worker = None
