import asyncio
from pathlib import Path

import pytest

from extensions import components
from extensions.commands import help_catalog
from extensions.commands import tickets as ticket_extension
from extensions.commands.tickets import config, console, resolve


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_COMMANDS = {
    "approve",
    "approve-migration-pilot",
    "config",
    "configure-threads",
    "console",
    "deny",
    "find",
    "flag-add",
    "flag-remove",
    "flags",
    "history",
    "migrate-legacy",
    "migrate-store",
    "setup",
    "thread-config",
}

OBSOLETE_COMMANDS = {
    "claim",
    "release",
    "close",
    "dashboard",
    "list",
    "change-category",
    "reset-counter",
    "diagnostics",
    "cleanup-ghosts",
    "fix-mismatched",
}


def test_ticket_package_registers_only_thread_runtime_commands():
    registered = set(ticket_extension.ticket._commands)

    assert registered == EXPECTED_COMMANDS
    assert not registered & OBSOLETE_COMMANDS


def test_ticket_package_registers_console_and_creation_actions():
    required = {
        "create_ticket",
        "ticket_console_pick",
        "ticket_console_find",
        "ticket_console_view",
        "ticket_console_approve",
        "ticket_console_deny",
        "ticket_console_deny_submit",
        "ticket_override",
    }

    assert required <= set(components.registered_functions)
    assert "ticket_dashboard_action" not in components.registered_functions


def test_main_does_not_load_the_legacy_ticket_channel_monitor():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert '"extensions.commands.tickets"' in source
    assert '"extensions.events.channel.ticket_channel_monitor"' not in source


def test_ticket_stopping_cancels_awaits_and_resets_all_owned_workers(monkeypatch):
    finalized = []

    async def worker(name):
        try:
            await asyncio.Event().wait()
        finally:
            finalized.append(name)

    class Workflow:
        def __init__(self):
            self.stops = 0

        async def stop(self):
            self.stops += 1

    async def run():
        resolution_task = asyncio.create_task(worker("resolution"))
        console_one = asyncio.create_task(worker("console-one"))
        console_two = asyncio.create_task(worker("console-two"))
        await asyncio.sleep(0)
        workflow = Workflow()
        console_startup = Workflow()
        monkeypatch.setattr(ticket_extension, "_workflow_recovery", workflow)
        monkeypatch.setattr(resolve, "_resolution_reconciler_task", resolution_task)
        monkeypatch.setattr(console, "_refresh_tasks", {
            1: console_one,
            2: console_two,
        })
        monkeypatch.setattr(console, "_startup_recovery", console_startup)
        monkeypatch.setattr(ticket_extension, "_staff_context_sweep_after", "ticket_9")
        monkeypatch.setattr(ticket_extension, "_staff_context_sweep_complete", True)

        await ticket_extension.on_stopping(None)
        assert workflow.stops == 1
        assert console_startup.stops == 1
        assert resolve._resolution_reconciler_task is None
        assert console._refresh_tasks == {}
        assert ticket_extension._staff_context_sweep_after is None
        assert ticket_extension._staff_context_sweep_complete is False
        assert all(task.done() for task in (resolution_task, console_one, console_two))
        assert sorted(finalized) == ["console-one", "console-two", "resolution"]

        await ticket_extension.on_stopping(None)
        assert workflow.stops == 2
        assert console_startup.stops == 2
        assert resolve._resolution_reconciler_task is None
        assert console._refresh_tasks == {}

    asyncio.run(run())


def test_ticket_help_matches_the_registered_thread_commands():
    paths = help_catalog.command_paths()
    documented = {
        path.removeprefix("/ticket ")
        for path in paths
        if path.startswith("/ticket ")
    }

    assert documented == EXPECTED_COMMANDS
    assert not documented & OBSOLETE_COMMANDS


def test_config_summary_has_thread_parents_roles_and_console_only():
    summary = config.configuration_summary({
        "main_candidate_parent": 101,
        "main_staff_parent": 102,
        "main_recruiter_role": 103,
        "fwa_candidate_parent": 201,
        "fwa_staff_parent": 202,
        "fwa_recruiter_role": 203,
        "ticket_console_channel_id": 301,
        "main_category": 999,
    })

    assert "Thread-only" in summary
    assert "<#101>" in summary
    assert "<@&203>" in summary
    assert "<#301>" in summary
    assert "category" not in summary.casefold()
    assert "claim" not in summary.casefold()


def test_startup_prepares_all_durable_ticket_indexes(monkeypatch):
    calls = []

    async def record(name):
        calls.append(name)

    monkeypatch.setattr(ticket_extension.store, "ensure_indexes", lambda _mongo: record("tickets"))
    monkeypatch.setattr(ticket_extension.flag_store, "ensure_indexes", lambda _mongo: record("flags"))
    monkeypatch.setattr(
        ticket_extension.thread_service,
        "ensure_creation_indexes",
        lambda _mongo: record("creation"),
    )
    monkeypatch.setattr(
        ticket_extension.legacy_migration,
        "ensure_migration_indexes",
        lambda _mongo: record("migration"),
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "ensure_staff_context_indexes",
        lambda _mongo: record("staff_context"),
    )

    errors = asyncio.run(ticket_extension.prepare_ticket_runtime(object()))

    assert errors == {}
    assert calls == ["tickets", "flags", "creation", "migration", "staff_context"]


def test_effect_and_hub_startup_recovery_are_loaded():
    assert callable(resolve.recover_resolution_effects)
    assert callable(console.recover_ticket_console)
    assert callable(console.queue_staff_identity_context)
    assert callable(console.recover_pending_staff_identity_contexts)
    assert callable(console.recover_open_staff_identity_contexts)


def test_startup_resumes_confirmed_creation_and_migration_after_indexes(monkeypatch):
    calls = []

    async def indexes(_mongo):
        calls.append("indexes")

    async def creations(*, bot, mongo, limit):
        calls.append(("creation", bot, mongo, limit))
        return {"processed": 1, "completed": 1, "failed": 0}

    async def migrations(*, bot, mongo, limit):
        calls.append(("migration", bot, mongo, limit))
        return {"processed": 1, "completed": 1, "failed": 0}

    async def staff_contexts(*, bot, mongo, limit):
        calls.append(("staff_context", bot, mongo, limit))
        return {"processed": 1, "completed": 1, "failed": 0}

    async def open_contexts(*, bot, mongo, after_ticket_id, limit):
        calls.append(("open_context", bot, mongo, after_ticket_id, limit))
        return {
            "processed": 1,
            "completed": 1,
            "failed": 0,
            "after_ticket_id": "ticket_1",
            "exhausted": True,
        }

    monkeypatch.setattr(ticket_extension.store, "ensure_indexes", indexes)
    monkeypatch.setattr(
        ticket_extension.thread_service,
        "recover_pending_thread_ticket_creations",
        creations,
    )
    monkeypatch.setattr(
        ticket_extension.legacy_migration,
        "recover_pending_legacy_migrations",
        migrations,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_pending_staff_identity_contexts",
        staff_contexts,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_open_staff_identity_contexts",
        open_contexts,
    )
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_after", None)
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_complete", False)
    bot = object()
    mongo = object()

    asyncio.run(ticket_extension.recover_ticket_workflows(bot, mongo))

    assert calls == [
        "indexes",
        ("creation", bot, mongo, 50),
        ("migration", bot, mongo, 5),
        ("staff_context", bot, mongo, 25),
        ("open_context", bot, mongo, None, 25),
    ]


def test_startup_recovery_drains_records_beyond_all_batch_limits(monkeypatch):
    remaining = {
        "creation": 101,
        "migration": 11,
        "staff_context": 51,
        "open_context": 51,
    }
    batches = {
        "creation": [],
        "migration": [],
        "staff_context": [],
        "open_context": [],
    }

    async def indexes(_mongo):
        return None

    async def recover(kind, limit):
        processed = min(remaining[kind], limit)
        remaining[kind] -= processed
        batches[kind].append(processed)
        return {"processed": processed, "completed": processed, "failed": 0}

    async def creations(*, bot, mongo, limit):
        return await recover("creation", limit)

    async def migrations(*, bot, mongo, limit):
        return await recover("migration", limit)

    async def staff_contexts(*, bot, mongo, limit):
        return await recover("staff_context", limit)

    async def open_contexts(*, bot, mongo, after_ticket_id, limit):
        processed = min(remaining["open_context"], limit)
        remaining["open_context"] -= processed
        batches["open_context"].append(processed)
        offset = sum(batches["open_context"])
        return {
            "processed": processed,
            "completed": processed,
            "failed": 0,
            "after_ticket_id": f"ticket_{offset}" if processed else after_ticket_id,
            "exhausted": processed < limit,
        }

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(ticket_extension.store, "ensure_indexes", indexes)
    monkeypatch.setattr(
        ticket_extension.thread_service,
        "recover_pending_thread_ticket_creations",
        creations,
    )
    monkeypatch.setattr(
        ticket_extension.legacy_migration,
        "recover_pending_legacy_migrations",
        migrations,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_pending_staff_identity_contexts",
        staff_contexts,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_open_staff_identity_contexts",
        open_contexts,
    )
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_after", None)
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_complete", False)

    async def scenario():
        reconciler = ticket_extension.StartupReconciler(
            "ticket-workflow-batches",
            lambda: ticket_extension.recover_ticket_workflows(object(), object()),
            retry_delays=(0,),
            sleep=no_wait,
        )
        await reconciler.start()
        return reconciler

    reconciler = asyncio.run(scenario())

    assert batches == {
        "creation": [50, 50, 1],
        "migration": [5, 5, 1],
        "staff_context": [25, 25, 1],
        "open_context": [25, 25, 1],
    }
    assert remaining == {
        "creation": 0,
        "migration": 0,
        "staff_context": 0,
        "open_context": 0,
    }
    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 3


def test_startup_recovery_retries_failed_staff_contexts(monkeypatch):
    async def indexes(_mongo):
        return None

    async def complete(**_kwargs):
        return {"processed": 0, "completed": 0, "failed": 0}

    async def context_failed(**_kwargs):
        return {"processed": 1, "completed": 0, "failed": 1}

    monkeypatch.setattr(ticket_extension.store, "ensure_indexes", indexes)
    monkeypatch.setattr(
        ticket_extension.thread_service,
        "recover_pending_thread_ticket_creations",
        complete,
    )
    monkeypatch.setattr(
        ticket_extension.legacy_migration,
        "recover_pending_legacy_migrations",
        complete,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_pending_staff_identity_contexts",
        context_failed,
    )
    monkeypatch.setattr(
        ticket_extension.console,
        "recover_open_staff_identity_contexts",
        lambda **_kwargs: complete(),
    )
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_after", None)
    monkeypatch.setattr(ticket_extension, "_staff_context_sweep_complete", False)

    with pytest.raises(RuntimeError, match="1 ticket workflow recovery"):
        asyncio.run(ticket_extension.recover_ticket_workflows(object(), object()))


def test_ticket_runtime_startup_retries_config_indexes_and_workflow_once(monkeypatch):
    attempts = {"config": 0, "indexes": 0, "workflow": 0}

    class Setup:
        async def find_one(self, query):
            assert query == {"_id": "config"}
            attempts["config"] += 1
            if attempts["config"] == 1:
                raise TimeoutError("temporary config outage")
            return {"main_candidate_parent": 123}

    class Mongo:
        ticket_setup = Setup()

    async def prepare(_mongo):
        attempts["indexes"] += 1
        if attempts["indexes"] == 1:
            return {"migration": "TimeoutError: temporary index outage"}
        return {}

    async def workflows(_bot, _mongo):
        attempts["workflow"] += 1
        if attempts["workflow"] == 1:
            raise TimeoutError("temporary workflow outage")

    async def no_wait(_delay):
        return None

    real_reconciler = ticket_extension.StartupReconciler
    monkeypatch.setattr(
        ticket_extension,
        "StartupReconciler",
        lambda name, operation: real_reconciler(
            name,
            operation,
            retry_delays=(0,),
            sleep=no_wait,
        ),
    )
    monkeypatch.setattr(ticket_extension, "prepare_ticket_runtime", prepare)
    monkeypatch.setattr(ticket_extension, "recover_ticket_workflows", workflows)
    monkeypatch.setattr(ticket_extension, "_workflow_recovery", None)
    monkeypatch.setattr(ticket_extension, "_startup_complete", False)
    monkeypatch.setattr(ticket_extension, "ticket_config", None)
    monkeypatch.setattr(ticket_extension, "startup_index_errors", {})

    async def scenario():
        mongo = Mongo()
        bot = object()
        await ticket_extension.on_started(None, mongo, bot)
        reconciler = ticket_extension._workflow_recovery
        first = reconciler.task
        await ticket_extension.on_started(None, mongo, bot)
        assert reconciler.task is first
        await first
        assert reconciler.health.state == "healthy"
        assert reconciler.health.attempts == 4
        assert ticket_extension.ticket_config == {"main_candidate_parent": 123}
        assert ticket_extension.startup_index_errors == {}
        assert ticket_extension._startup_complete is True
        await reconciler.stop()
        await reconciler.stop()
        assert reconciler.task is None
        assert reconciler.health.state == "stopped"

    asyncio.run(scenario())

    assert attempts == {"config": 3, "indexes": 2, "workflow": 2}


def test_console_startup_retries_hub_state_and_dirty_write_once(monkeypatch):
    attempts = {"state": 0, "dirty": 0, "scheduled": 0}

    async def hub_state(_mongo):
        attempts["state"] += 1
        if attempts["state"] == 1:
            raise TimeoutError("temporary hub read outage")
        return {"channel_id": 123}

    async def mark_dirty(_mongo, *, reason):
        assert reason == "startup recovery"
        attempts["dirty"] += 1
        if attempts["dirty"] == 1:
            raise TimeoutError("temporary hub write outage")
        return 1

    def schedule(bot, mongo):
        assert bot is test_bot
        assert mongo is test_mongo
        attempts["scheduled"] += 1

    async def no_wait(_delay):
        return None

    real_reconciler = console.StartupReconciler
    monkeypatch.setattr(
        console,
        "StartupReconciler",
        lambda name, operation: real_reconciler(
            name,
            operation,
            retry_delays=(0,),
            sleep=no_wait,
        ),
    )
    monkeypatch.setattr(console, "_hub_state", hub_state)
    monkeypatch.setattr(console, "_mark_hub_dirty", mark_dirty)
    monkeypatch.setattr(console, "_schedule_hub_refresh", schedule)
    monkeypatch.setattr(console, "_startup_recovery", None)
    monkeypatch.setattr(console, "_refresh_tasks", {})
    test_bot = object()
    test_mongo = object()

    async def scenario():
        await console.recover_ticket_console(None, test_mongo, test_bot)
        reconciler = console._startup_recovery
        first = reconciler.task
        await console.recover_ticket_console(None, test_mongo, test_bot)
        assert reconciler.task is first
        await first
        assert reconciler.health.state == "healthy"
        assert reconciler.health.attempts == 3
        await console.stop_hub_refresh_workers()
        await console.stop_hub_refresh_workers()
        assert reconciler.task is None
        assert reconciler.health.state == "stopped"

    asyncio.run(scenario())

    assert attempts == {"state": 3, "dirty": 2, "scheduled": 1}
