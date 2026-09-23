"""Restart-recovery coverage for the LazyCWL reminder scheduler.

The old snapshot/auto-ping scheduler was retired. These tests retain the
important operational guarantees on the saved-list reminder service: a failed
restore must retry, and a retry must not duplicate jobs restored before it.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from extensions.commands.fwa import lazy_cwl_service as service
from tests.test_lazy_cwl_service import FakeScheduler, _fake_mongo, _list_doc


def _enabled_doc(list_id: str, clan_tag: str) -> dict:
    document = _list_doc(list_id, clan_tag=clan_tag)
    # The shared fixture's historical NOW is intentionally stable; scheduler
    # recovery must instead see a list that has not expired in real time.
    document["expires_at"] = datetime.now(timezone.utc) + timedelta(days=3)
    document["reminders"].update({
        "enabled": True,
        "every_minutes": 30,
        "started_at": datetime.now(timezone.utc) - timedelta(hours=1),
    })
    return document


def test_restore_registration_failure_is_visible_to_startup_reconciler(monkeypatch):
    """Do not mark startup healthy while an enabled reminder has no job."""
    mongo = _fake_mongo([_enabled_doc("list-1", "ABC")])
    scheduler = FakeScheduler(fail_add=True)
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "scheduler", scheduler)

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        asyncio.run(service.restore_reminder_jobs())


def test_startup_retry_restores_all_enabled_jobs_without_duplicates(monkeypatch):
    """A transient registration failure retries and retains earlier jobs."""
    mongo = _fake_mongo([
        _enabled_doc("list-1", "ABC"),
        _enabled_doc("list-2", "DEF"),
    ])

    class FlakyScheduler(FakeScheduler):
        def __init__(self):
            super().__init__()
            self.failures_remaining = 1

        def add_job(self, function, **kwargs):
            if kwargs["id"] == "lazycwl_reminder_list-2" and self.failures_remaining:
                self.failures_remaining -= 1
                raise RuntimeError("scheduler still starting")
            super().add_job(function, **kwargs)

    scheduler = FlakyScheduler()
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "scheduler", scheduler)

    async def no_wait(_delay):
        return None

    reconciler = service.StartupReconciler(
        "lazycwl-scheduler-test", service.reconcile, retry_delays=(0,), sleep=no_wait,
    )

    async def run():
        reconciler.start()
        await reconciler.task

    asyncio.run(run())

    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 2
    assert scheduler.running is True
    assert set(scheduler.jobs) == {
        "lazycwl_reminder_list-1",
        "lazycwl_reminder_list-2",
        service.EXPIRY_JOB_ID,
    }
    successful_reminder_ids = [
        kwargs["id"] for _function, kwargs in scheduler.add_job_calls
        if kwargs["id"].startswith("lazycwl_reminder_")
    ]
    assert successful_reminder_ids == [
        "lazycwl_reminder_list-1", "lazycwl_reminder_list-2",
    ]
