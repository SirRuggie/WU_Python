"""Durable refresh countdowns and send-before-delete recovery for private panels."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.recruit import questions
from utils import recruit_panel_refresh as refresh
from tests.test_recruit_goblin_challenges import Collection

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def database():
    jobs = Collection()
    database = NS(
        get_collection=lambda name: jobs if name == "recruit_panel_refreshes" else None
    )
    return NS(component_state=NS(database=database)), jobs


def ctx(message_id=10, created=NOW):
    return NS(
        guild_id=1,
        channel_id=2,
        user=NS(id=3),
        interaction=NS(
            message=NS(id=message_id),
            created_at=created,
            application_id=4,
            token="test-secret",
            custom_id="primary_questions:session",
        ),
    )


def rest(source_id=10):
    return NS(
        fetch_interaction_response=AsyncMock(return_value=NS(id=source_id)),
        execute_webhook=AsyncMock(return_value=NS(id=100)),
        fetch_webhook_message=AsyncMock(return_value=NS(id=100)),
        delete_interaction_response=AsyncMock(),
    )


def missing():
    return hikari.NotFoundError(
        url="https://discord.com", headers={}, raw_body=b"", message="gone", code=10008
    )


def test_delay_stays_ten_minutes():
    assert questions.PANEL_REFRESH_DELAY_SECONDS == refresh.DELAY_SECONDS == 600


def test_first_pick_is_durable_and_later_picks_do_not_slide_countdown(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        first = ctx()
        await questions.refresh_questions_panel(first, 22, mongo)
        await questions.refresh_questions_panel(
            ctx(created=NOW + timedelta(minutes=3)), 22, mongo
        )
        assert len(jobs.documents) == 1
        assert jobs.documents["10"]["due_at"] == NOW + timedelta(minutes=10)
        api = rest()
        render = AsyncMock(return_value=[])
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=9))
        await refresh.run_due(mongo, api, render)
        api.execute_webhook.assert_not_awaited()
        # A fresh worker uses only persisted Mongo state, no old ctx or task.
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=10))
        order = []

        async def send(*args, **kwargs):
            order.append("send")
            return NS(id=100)

        async def delete(*args, **kwargs):
            order.append("delete")

        api.execute_webhook.side_effect = send
        api.delete_interaction_response.side_effect = delete
        await refresh.run_due(mongo, api, render)
        assert order == ["send", "delete"]
        job = jobs.documents["10"]
        assert job["status"] == "done" and "interaction_token" not in job
        flags = api.execute_webhook.call_args.kwargs["flags"]
        assert (
            flags & hikari.MessageFlag.EPHEMERAL
            and flags & hikari.MessageFlag.IS_COMPONENTS_V2
        )
        await refresh.run_due(mongo, api, render)
        assert api.execute_webhook.await_count == 1

    asyncio.run(run())


def test_send_failure_keeps_original_and_next_selection_can_retry(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=10))
        api = rest()
        api.execute_webhook.side_effect = RuntimeError("do not log test-secret")
        await refresh.run_due(mongo, api, AsyncMock(return_value=[]))
        api.delete_interaction_response.assert_not_awaited()
        assert jobs.documents["10"]["status"] == "failed"
        assert "interaction_token" not in jobs.documents["10"]
        await refresh.schedule(mongo, ctx(created=NOW + timedelta(minutes=11)), 22)
        assert jobs.documents["10"]["status"] == "pending"
        assert jobs.documents["10"]["due_at"] == NOW + timedelta(minutes=21)

    asyncio.run(run())


def test_cleanup_retries_without_resending_and_survives_restart(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=10))
        api = rest()
        api.delete_interaction_response.side_effect = RuntimeError("temporary")
        render = AsyncMock(return_value=[])
        await refresh.run_due(mongo, api, render)
        assert jobs.documents["10"]["status"] == "cleanup"
        assert jobs.documents["10"]["replacement_id"] == 100
        api.delete_interaction_response.side_effect = None
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=11))
        await refresh.run_due(mongo, api, render)
        assert (
            api.execute_webhook.await_count == 1
            and jobs.documents["10"]["status"] == "done"
        )

    asyncio.run(run())


@pytest.mark.parametrize("target", ["source", "replacement"])
def test_missing_panel_is_handled_without_deleting_a_usable_source(monkeypatch, target):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=10))
        api = rest()
        getattr(
            api,
            (
                "fetch_interaction_response"
                if target == "source"
                else "fetch_webhook_message"
            ),
        ).side_effect = missing()
        await refresh.run_due(mongo, api, AsyncMock(return_value=[]))
        api.delete_interaction_response.assert_not_awaited()
        assert jobs.documents["10"]["status"] == "failed"
        if target == "source":
            api.execute_webhook.assert_not_awaited()

    asyncio.run(run())


def test_long_outage_expires_token_and_next_pick_rearms(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=16))
        api = rest()
        await refresh.run_due(mongo, api, AsyncMock(return_value=[]))
        api.execute_webhook.assert_not_awaited()
        api.delete_interaction_response.assert_not_awaited()
        assert (
            jobs.documents["10"]["status"] == "expired"
            and "interaction_token" not in jobs.documents["10"]
        )
        await refresh.schedule(mongo, ctx(created=NOW + timedelta(minutes=16)), 22)
        assert jobs.documents["10"]["due_at"] == NOW + timedelta(minutes=26)

    asyncio.run(run())


def test_unknown_delivery_after_crash_does_not_blindly_send_again(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        jobs.documents["10"].update(
            status="sending", lease_until=NOW + timedelta(minutes=11)
        )
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=12))
        api = rest()
        await refresh.run_due(mongo, api, AsyncMock(return_value=[]))
        api.execute_webhook.assert_not_awaited()
        api.delete_interaction_response.assert_not_awaited()
        assert jobs.documents["10"]["failure"] == "delivery_unknown_after_restart"

    asyncio.run(run())


def test_two_workers_cannot_send_same_refresh(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW + timedelta(minutes=10))
        api = rest()
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def send(*a, **kw):
            entered.set()
            await finish.wait()
            return NS(id=100)

        api.execute_webhook.side_effect = send
        render = AsyncMock(return_value=[])
        first = asyncio.create_task(refresh.run_due(mongo, api, render))
        await entered.wait()
        await refresh.run_due(mongo, api, render)
        finish.set()
        await first
        assert api.execute_webhook.await_count == 1

    asyncio.run(run())


def test_worker_shutdown_leaves_pending_job_intact(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        refresh.start(mongo, rest(), AsyncMock(return_value=[]))
        await refresh.stop()
        assert jobs.documents["10"]["status"] == "pending"
        assert refresh._worker is None

    asyncio.run(run())


def test_separate_panel_has_its_own_countdown(monkeypatch):
    async def run():
        mongo, jobs = database()
        monkeypatch.setattr(refresh, "utcnow", lambda: NOW)
        await refresh.schedule(mongo, ctx(), 22)
        await refresh.schedule(mongo, ctx(11, created=NOW + timedelta(minutes=3)), 23)
        assert jobs.documents["10"]["due_at"] != jobs.documents["11"]["due_at"]
        assert len(jobs.documents) == 2

    asyncio.run(run())
