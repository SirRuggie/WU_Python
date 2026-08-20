"""Thread-only recruitment ticket extension entry point."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import hikari
import lightbulb

from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler


loader = lightbulb.Loader()
ticket = lightbulb.Group("ticket", "Warriors United thread ticket commands")

ticket_config: dict | None = None
startup_index_errors: dict[str, str] = {}
_startup_complete = False
_workflow_recovery: StartupReconciler | None = None
_staff_context_sweep_after: str | None = None
_staff_context_sweep_complete = False
CREATION_RECOVERY_LIMIT = 50
MIGRATION_RECOVERY_LIMIT = 5
STAFF_CONTEXT_RECOVERY_LIMIT = 25


async def prepare_ticket_runtime(mongo: MongoClient) -> dict[str, str]:
    """Install every durable index independently and report fail-closed errors."""
    operations: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        ("tickets", lambda: store.ensure_indexes(mongo)),
        ("flags", lambda: flag_store.ensure_indexes(mongo)),
        ("creation", lambda: thread_service.ensure_creation_indexes(mongo)),
        ("migration", lambda: legacy_migration.ensure_migration_indexes(mongo)),
        ("staff_context", lambda: console.ensure_staff_context_indexes(mongo)),
    )
    errors: dict[str, str] = {}
    for name, operation in operations:
        try:
            await operation()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {str(exc)[:240]}"
            print(
                f"[Tickets] startup_index_failed subsystem={name} "
                f"error={type(exc).__name__}"
            )
    return errors


async def recover_ticket_workflows(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> None:
    """Resume only durable, previously authorized ticket work."""
    global _staff_context_sweep_after, _staff_context_sweep_complete

    await store.ensure_indexes(mongo)
    creation = await thread_service.recover_pending_thread_ticket_creations(
        bot=bot, mongo=mongo, limit=CREATION_RECOVERY_LIMIT
    )
    migration = await legacy_migration.recover_pending_legacy_migrations(
        bot=bot, mongo=mongo, limit=MIGRATION_RECOVERY_LIMIT
    )
    staff_context = await console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo, limit=STAFF_CONTEXT_RECOVERY_LIMIT
    )
    open_context: dict[str, int | str | bool | None] = {
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "after_ticket_id": _staff_context_sweep_after,
        "exhausted": True,
    }
    if not _staff_context_sweep_complete:
        open_context = await console.recover_open_staff_identity_contexts(
            bot=bot,
            mongo=mongo,
            after_ticket_id=_staff_context_sweep_after,
            limit=STAFF_CONTEXT_RECOVERY_LIMIT,
        )
        advanced = open_context.get("after_ticket_id")
        if advanced:
            _staff_context_sweep_after = str(advanced)
        _staff_context_sweep_complete = bool(open_context.get("exhausted"))
    failed = sum(
        int(result.get("failed", 0))
        for result in (creation, migration, staff_context, open_context)
    )
    print(
        "[Tickets] startup_workflow_recovery "
        f"creation={creation.get('completed', 0)}/{creation.get('processed', 0)} "
        f"migration={migration.get('completed', 0)}/{migration.get('processed', 0)} "
        f"staff_context={staff_context.get('completed', 0)}/"
        f"{staff_context.get('processed', 0)} "
        f"open_context={open_context.get('completed', 0)}/"
        f"{open_context.get('processed', 0)} "
        f"failed={failed}"
    )
    if failed:
        raise RuntimeError(f"{failed} ticket workflow recovery item(s) remain pending")
    if (
        int(creation.get("processed", 0)) >= CREATION_RECOVERY_LIMIT
        or int(migration.get("processed", 0)) >= MIGRATION_RECOVERY_LIMIT
        or int(staff_context.get("processed", 0)) >= STAFF_CONTEXT_RECOVERY_LIMIT
        or not _staff_context_sweep_complete
    ):
        # A full bounded batch cannot prove that no later eligible rows remain.
        # Let StartupReconciler schedule another background pass; the final
        # exact-size batch conservatively causes one harmless empty pass.
        raise RuntimeError("ticket workflow recovery has another bounded batch pending")


async def _recover_ticket_runtime(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> None:
    """Prepare the thread runtime, then resume its durable workflows."""
    global ticket_config, startup_index_errors, _startup_complete

    if not _startup_complete:
        loaded_config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        index_errors = await prepare_ticket_runtime(mongo)
        ticket_config = loaded_config
        startup_index_errors = index_errors
        if index_errors:
            failed = ", ".join(sorted(index_errors))
            raise RuntimeError(f"ticket startup indexes unavailable: {failed}")

        _startup_complete = True
        configured = sum(
            bool(ticket_config.get(f"{kind}_{field}"))
            for kind in ("main", "fwa")
            for field in ("candidate_parent", "staff_parent", "recruiter_role")
        )
        print(
            f"[Tickets] thread_runtime_ready configured_fields={configured}/6 "
            "index_errors=0"
        )

    await recover_ticket_workflows(bot, mongo)


def start_ticket_workflow_recovery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> StartupReconciler:
    """Start one self-healing background recovery task."""
    global _workflow_recovery
    if _workflow_recovery is None:
        _workflow_recovery = StartupReconciler(
            "ticket-workflows",
            lambda: _recover_ticket_runtime(bot, mongo),
        )
    _workflow_recovery.start()
    return _workflow_recovery


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Start retrying runtime preparation and workflow recovery."""
    start_ticket_workflow_recovery(bot, mongo)


@loader.listener(hikari.StoppingEvent)
async def on_stopping(_: hikari.StoppingEvent) -> None:
    """Await every ticket-owned worker before shared REST/Mongo shutdown."""
    global _startup_complete, _staff_context_sweep_after, _staff_context_sweep_complete
    try:
        if _workflow_recovery is not None:
            await _workflow_recovery.stop()
    finally:
        _startup_complete = False
        _staff_context_sweep_after = None
        _staff_context_sweep_complete = False
        try:
            await resolve.stop_resolution_reconciler()
        finally:
            await console.stop_hub_refresh_workers()


# Durable domain modules first; registration modules may safely import them.
from . import schema
from . import store
from . import flag_store
from . import thread_service

# User and interaction surfaces.
from . import setup
from . import config
from . import handlers
from . import resolve
from . import close
from . import migrate
from . import console
from . import flags
from . import legacy_migration


loader.command(ticket)

__all__ = [
    "loader",
    "ticket",
    "ticket_config",
    "startup_index_errors",
    "prepare_ticket_runtime",
    "recover_ticket_workflows",
    "start_ticket_workflow_recovery",
]
