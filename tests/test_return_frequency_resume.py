"""Frontend frequency action prerequisite: existing running resume behavior."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from extensions.commands.fwa import lazy_cwl_service as service
from utils import lazy_cwl_store as store
from tests.test_lazy_cwl_service import FakeScheduler, _fake_mongo, _list_doc, _wire


@pytest.mark.parametrize("minutes", [30, 60, 120])
def test_running_resume_changes_cadence_without_send_or_extending_stop(
    monkeypatch, minutes
):
    now = datetime.now(timezone.utc)
    last = now - timedelta(minutes=10)
    stop = now + timedelta(days=2)
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["reminders"] = dict(
        enabled=True,
        every_minutes=60,
        started_at=now - timedelta(days=1),
        last_sent_at=last,
        sent_count=3,
        schedule_start_at=now - timedelta(days=1),
        schedule_end_at=stop,
    )
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})
    send = AsyncMock(side_effect=AssertionError("Changing frequency must not send"))
    monkeypatch.setattr(service, "reminder_job", send)

    result = asyncio.run(
        service.set_reminders(
            "#ABC", True, minutes, expected_list_id="list-1", section="FWA"
        )
    )
    assert result == {"ok": True, "error": None}
    saved = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert saved["reminders"] == {**doc["reminders"], "every_minutes": minutes}
    assert len(scheduler.add_job_calls) == 1
    _, job = scheduler.add_job_calls[0]
    assert job["replace_existing"] is True
    assert job["next_run_time"] == last + timedelta(minutes=minutes)
    assert job["next_run_time"] > now
    assert job["trigger"].interval == timedelta(minutes=minutes)
    assert saved["reminders"]["schedule_end_at"] == stop
    send.assert_not_awaited()
