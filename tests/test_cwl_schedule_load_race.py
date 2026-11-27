"""Full-load races and pending poll health, using only native fixture state."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from extensions.tasks import cwl_reminder as native
from utils import cwl_web_bridge as bridge
from test_reminder_schedule_ack import GUILD, EPOCH, reconcile, runtime


def test_poll_leads_startup_trails_and_ack_waits_for_complete_second_load(runtime, monkeypatch):
    mongo, _, sender = runtime
    install = native.sync_campaign_schedule

    async def run():
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()
        release_second = asyncio.Event()
        active = 0
        maximum = 0

        async def gated(guild_id, cycle):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                if asyncio.current_task().get_name() == "poll-load":
                    first_entered.set()
                    await release_first.wait()
                elif asyncio.current_task().get_name() == "startup-load":
                    second_entered.set()
                    await release_second.wait()
                await asyncio.sleep(0)
                return await install(guild_id, cycle)
            finally:
                active -= 1

        monkeypatch.setattr(native, "sync_campaign_schedule", gated)
        first = asyncio.create_task(native._sync_all_campaigns(), name="poll-load")
        await first_entered.wait()
        second = asyncio.create_task(native._sync_all_campaigns(), name="startup-load")
        await asyncio.sleep(0)
        assert not second_entered.is_set()
        release_first.set()
        await first
        await second_entered.wait()
        repair = AsyncMock(side_effect=AssertionError("Pending load must not start a repair"))
        assert await reconcile(repair) is False
        repair.assert_not_awaited()
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents
        assert GUILD not in bridge._schedule_repair_attempts
        release_second.set()
        await second
        assert maximum == 1
        assert not native._campaign_load_in_progress()
        assert await reconcile() is True
        assert mongo.bot_config.documents[bridge.worker_id(GUILD)]["schedule_generations"]
        sender.assert_not_awaited()

    asyncio.run(asyncio.wait_for(run(), timeout=5))


def test_pending_entry_does_not_attempt_repair_or_ack(runtime):
    mongo, _, _ = runtime

    async def run():
        sync = AsyncMock()
        async with native._campaign_sync_all_lock:
            assert await reconcile(sync) is False
        sync.assert_not_awaited()
        assert GUILD not in bridge._schedule_repair_attempts
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents

    asyncio.run(run())


def test_pending_after_sync_removes_attempt_without_ack(runtime):
    mongo, _, _ = runtime

    async def run():
        pending = False

        async def sync():
            nonlocal pending
            pending = True

        assert await bridge.reconcile_campaign_changes(
            mongo, sync, guild_id=GUILD, runtime_id=EPOCH,
            loaded_generations=lambda: None, load_in_progress=lambda: pending,
        ) is False
        assert GUILD not in bridge._schedule_repair_attempts
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents

    asyncio.run(run())


@pytest.mark.parametrize("cancel_holder", [False, True])
def test_cancelled_full_load_or_waiter_releases_its_lane(runtime, monkeypatch, cancel_holder):
    install = native.sync_campaign_schedule

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def gated(guild_id, cycle):
            entered.set()
            await release.wait()
            return await install(guild_id, cycle)

        monkeypatch.setattr(native, "sync_campaign_schedule", gated)
        first = asyncio.create_task(native._sync_all_campaigns())
        await entered.wait()
        if cancel_holder:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert native._loaded_campaign_generations(GUILD) is None
        else:
            waiter = asyncio.create_task(native._sync_all_campaigns())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert native._campaign_load_in_progress()
        release.set()
        if not cancel_holder:
            await first
        assert not native._campaign_load_in_progress()
        assert await native._sync_all_campaigns()
        assert native._loaded_campaign_generations(GUILD)
        assert not native._campaign_load_in_progress()

    asyncio.run(asyncio.wait_for(run(), timeout=5))


def _poll_dependencies(monkeypatch):
    monkeypatch.setattr(native, "bot_instance", object())
    monkeypatch.setattr(native, "_resume_held_signups", AsyncMock())
    worker = SimpleNamespace(ensure_ready=AsyncMock(return_value=True), poll=AsyncMock())
    monkeypatch.setattr(native, "_post_update_worker_for_runtime", lambda: worker)
    queue = AsyncMock(return_value=0)
    monkeypatch.setattr(bridge, "process_pending_roster_requests", queue)
    failures = Mock()
    monkeypatch.setattr(native, "log_failure", failures)
    return queue, failures


def test_pending_poll_is_healthy_logs_once_and_continues_independent_queue(runtime, monkeypatch, caplog):
    queue, failures = _poll_dependencies(monkeypatch)

    async def run():
        async with native._campaign_sync_all_lock:
            assert await native._poll_web_roster_bridge() is True

    with caplog.at_level(logging.INFO, logger=native.__name__):
        asyncio.run(run())
    pending = [row for row in caplog.records if row.message == "cwl-web-roster-bridge: schedule load in progress; acknowledgement deferred"]
    assert len(pending) == 1 and pending[0].exc_info is None
    queue.assert_awaited_once()
    failures.assert_not_called()


def test_pending_poll_does_not_hide_an_independent_queue_failure(runtime, monkeypatch, caplog):
    queue, failures = _poll_dependencies(monkeypatch)
    queue.side_effect = RuntimeError("fixture queue unavailable")

    async def run():
        async with native._campaign_sync_all_lock:
            assert await native._poll_web_roster_bridge() is False

    with caplog.at_level(logging.INFO, logger=native.__name__):
        asyncio.run(run())
    assert failures.call_count == 1
    assert failures.call_args.args[1] == "cwl-web-roster-bridge.poll"


def test_healthy_unchanged_poll_does_not_log_a_pending_load(runtime, monkeypatch, caplog):
    queue, failures = _poll_dependencies(monkeypatch)

    async def run():
        await reconcile()
        assert await native._poll_web_roster_bridge() is True

    with caplog.at_level(logging.INFO, logger=native.__name__):
        asyncio.run(run())
    assert not [row for row in caplog.records if "schedule load in progress" in row.message]
    failures.assert_not_called()
    queue.assert_awaited_once()
