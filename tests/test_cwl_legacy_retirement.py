import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import cwl_announcement, lazyprep
from extensions.tasks import cwl_reminder
from tests.test_cwl_dashboard_integration import MemoryMongo, MemoryScheduler


def _command_names(loader):
    return {
        getattr(loadable._command, "name", None)
        for loadable in loader._loadables
        if hasattr(loadable, "_command")
    }


def test_legacy_announcement_commands_are_not_registered():
    assert _command_names(cwl_reminder.loader) == set()
    assert _command_names(cwl_announcement.loader) == set()
    assert _command_names(lazyprep.loader) == set()


def test_direct_legacy_delivery_and_scheduling_fail_closed(monkeypatch):
    async def scenario():
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 24, "hour": 7, "minute": 0,
        })
        scheduler = MemoryScheduler()
        rest = SimpleNamespace(create_message=AsyncMock())
        monkeypatch.setattr(cwl_reminder, "mongo_client", mongo)
        monkeypatch.setattr(cwl_reminder, "scheduler", scheduler)
        monkeypatch.setattr(cwl_reminder, "bot_instance", SimpleNamespace(rest=rest))

        before = deepcopy(mongo.cwl_reminder.documents)
        assert await cwl_reminder.send_cwl_reminder(0) is False
        assert await cwl_reminder.send_cwl_reminder(0, test_mode=True) is False
        with pytest.raises(RuntimeError, match="/cwl dashboard"):
            await cwl_reminder.schedule_cwl_reminder(24, 7, 0)

        rest.create_message.assert_not_awaited()
        assert scheduler.jobs == {}
        assert mongo.cwl_reminder.documents == before

    asyncio.run(scenario())


def test_startup_removes_only_legacy_runtime_state_and_keeps_import_source(monkeypatch):
    async def scenario():
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 24, "hour": 7, "minute": 0,
            "followups": [{"number": 1, "delay_minutes": 60}],
        })
        mongo.cwl_pending_reminders.documents.update({
            cwl_reminder.cwl_initial_retry_job_id: {
                "_id": cwl_reminder.cwl_initial_retry_job_id,
                "reminder_number": 0,
                "run_time": "2030-10-24T07:00:00-04:00",
            },
            "cwl_followup_1": {
                "_id": "cwl_followup_1", "reminder_number": 1,
                "run_time": "2030-10-24T08:00:00-04:00",
            },
        })
        scheduler = MemoryScheduler()
        scheduler.jobs[cwl_reminder.cwl_base_job_id] = SimpleNamespace()
        scheduler.jobs[cwl_reminder.cwl_initial_retry_job_id] = SimpleNamespace()
        scheduler.jobs["cwl_followup_1"] = SimpleNamespace()
        monkeypatch.setattr(cwl_reminder, "mongo_client", mongo)
        monkeypatch.setattr(cwl_reminder, "scheduler", scheduler)

        source = deepcopy(mongo.cwl_reminder.documents["schedule"])
        await cwl_reminder._reconcile_cwl_startup()

        assert mongo.cwl_pending_reminders.documents == {}
        assert not ({
            cwl_reminder.cwl_base_job_id,
            cwl_reminder.cwl_initial_retry_job_id,
            "cwl_followup_1",
        } & set(scheduler.jobs))
        # Timing remains available for the dashboard's one-time importer.
        assert mongo.cwl_reminder.documents["schedule"] == source

    asyncio.run(scenario())


@pytest.mark.parametrize("command", [cwl_announcement.CWLAnnouncement, lazyprep.LazyPrep])
def test_stale_standalone_command_callback_only_redirects(monkeypatch, command):
    async def scenario():
        rest = SimpleNamespace(create_message=AsyncMock())
        ctx = SimpleNamespace(
            member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),
            interaction=SimpleNamespace(guild_id=22),
            respond=AsyncMock(), defer=AsyncMock(), respond_with_modal=AsyncMock(),
        )
        if command is cwl_announcement.CWLAnnouncement:
            await command.invoke(SimpleNamespace(type="main"), ctx, mongo=MemoryMongo())
        else:
            await command.invoke(SimpleNamespace(type="open"), ctx, bot=SimpleNamespace(rest=rest))

        assert "/cwl dashboard" in ctx.respond.await_args.args[0]
        rest.create_message.assert_not_awaited()
        ctx.defer.assert_not_awaited()
        ctx.respond_with_modal.assert_not_awaited()

    asyncio.run(scenario())
