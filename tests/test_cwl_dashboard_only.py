"""Registration guardrails for the consolidated CWL announcement dashboard."""

import asyncio
from types import SimpleNamespace

from extensions.commands import cwl_announcement
from extensions.commands import cwl_bonus_lottery
from extensions.commands import cwl_dashboard
from extensions.commands import fwa
from extensions.commands import help_catalog
from extensions.commands import lazyprep
from extensions.tasks import cwl_reminder


def _loader_command_names(loader) -> set[str]:
    """Read the commands a Lightbulb loader will actually install."""
    names = set()
    for loadable in loader._loadables:
        command = getattr(loadable, "_command", None)
        command_data = getattr(command, "_command_data", None)
        if command_data is not None:
            names.add(command_data.name)
    return names


def test_only_dashboard_registers_as_a_cwl_announcement_entrypoint():
    assert _loader_command_names(cwl_dashboard.loader) == {"cwl"}
    assert set(cwl_dashboard.cwl.subcommands) == {"dashboard"}

    assert "cwl-announcement" not in _loader_command_names(cwl_announcement.loader)
    assert "lazyprep" not in _loader_command_names(lazyprep.loader)
    assert "cwl-reminder" not in _loader_command_names(cwl_reminder.loader)


def test_help_only_advertises_dashboard_for_cwl_announcements():
    paths = help_catalog.command_paths()
    assert "/cwl dashboard" in paths
    assert "/cwl-announcement" not in paths
    assert "/lazyprep" not in paths
    assert not any(path.startswith("/cwl-reminder ") for path in paths)


def test_unrelated_cwl_operational_tools_remain_registered():
    assert _loader_command_names(cwl_bonus_lottery.loader) == {"lazycwl-bonuses"}
    assert {
        "lazycwl-snapshot",
        "lazycwl-ping",
        "lazycwl-status",
        "lazycwl-roster",
        "lazycwl-reset",
        "lazycwl-autopings-start",
        "lazycwl-autopings-stop",
        "lazycwl-autopings-status",
        "lazycwl-remove-player",
    } <= set(fwa.fwa.subcommands)


def test_legacy_reminder_runtime_is_explicitly_fail_closed():
    assert cwl_reminder.LEGACY_RUNTIME_DISABLED is True


def test_clean_start_still_installs_monthly_campaign_rollover(monkeypatch):
    class EmptyCursor:
        async def to_list(self, *, length):
            return []

    class PendingCollection:
        def find(self):
            return EmptyCursor()

    class RecordingScheduler:
        running = True

        def __init__(self):
            self.jobs = []

        def get_job(self, _job_id):
            return None

        def remove_job(self, _job_id):
            raise AssertionError("A clean scheduler has no legacy jobs to remove")

        def add_job(self, _callback, **kwargs):
            self.jobs.append(kwargs["id"])

    async def no_pending():
        return None

    async def no_active_campaigns():
        return False

    scheduler = RecordingScheduler()
    monkeypatch.setattr(cwl_reminder, "scheduler", scheduler)
    monkeypatch.setattr(
        cwl_reminder,
        "mongo_client",
        SimpleNamespace(cwl_pending_reminders=PendingCollection()),
    )
    monkeypatch.setattr(cwl_reminder, "restore_pending_reminders", no_pending)
    monkeypatch.setattr(cwl_reminder, "_sync_all_campaigns", no_active_campaigns)

    asyncio.run(cwl_reminder._reconcile_cwl_startup())

    assert cwl_reminder.CAMPAIGN_ROLLOVER_JOB_ID in scheduler.jobs
