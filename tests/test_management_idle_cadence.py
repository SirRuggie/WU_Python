"""Cadence never stands in for authorization or a durable request claim."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest

from utils import manage_operations_runtime as runtime, manage_web_worker as worker
from utils.manage_poll_cache import state_for


def test_heartbeat_repeats_with_margin_and_failures_do_not_suppress_retry():
    async def run():
        clock = [0.0]
        writes = []

        async def write(query, update, **kwargs):
            writes.append(update["$set"]["checked_at"])
            if len(writes) == 2:
                raise RuntimeError("fixture outage")

        mongo = NS(bot_config=NS(update_one=write))
        with patch.object(
            worker, "time", NS(monotonic=lambda: clock[0], time=lambda: 1000 + clock[0])
        ):
            assert await worker._write_heartbeat(mongo)
            clock[0] = 29
            assert not await worker._write_heartbeat(mongo)
            clock[0] = 30
            with pytest.raises(RuntimeError):
                await worker._write_heartbeat(mongo)
            assert await worker._write_heartbeat(mongo)
            clock[0] = 60
            assert await worker._write_heartbeat(mongo)
        assert writes == [1000, 1030, 1030, 1060]
        assert max(b - a for a, b in zip(writes, writes[1:])) < 60

    asyncio.run(run())


def test_base_images_are_projected_cached_and_can_be_forced_after_change():
    async def run():
        now = [0.0]
        read = AsyncMock(return_value={})
        mongo = NS(fwa_data=NS(find_one=read))
        with patch.object(runtime, "time", NS(monotonic=lambda: now[0])):
            await runtime.refresh_base_image_cache(mongo)
            now[0] = 59
            await runtime.refresh_base_image_cache(mongo)
            read.assert_awaited_once_with(
                {"_id": "fwa_config"},
                {"_id": 0, "war_base_images": 1, "active_base_images": 1},
            )
            now[0] = 60
            await runtime.refresh_base_image_cache(mongo)
            await runtime.refresh_base_image_cache(mongo, force=True)
            assert read.await_count == 3

    asyncio.run(run())


def test_idle_observation_skips_only_recent_confirmed_empty_work_and_band_updates_on_change():
    async def run():
        import time

        clock = [100.0]
        mongo = NS(bot_config=NS(update_one=AsyncMock(), update_many=AsyncMock()))
        process = AsyncMock(return_value=7)
        prune = AsyncMock()
        values = {"checked_at": 1, "health": "healthy"}
        state = state_for(mongo)
        state.ready_at = clock[0]
        state.ready = None
        profile = NS(prune_throttled=prune)
        with patch.object(
            worker,
            "time",
            NS(
                monotonic=lambda: clock[0],
                time=lambda: clock[0],
                perf_counter=time.perf_counter,
            ),
        ), patch.object(runtime, "refresh_base_image_cache", AsyncMock()), patch.object(
            runtime, "runtime_snapshot", lambda _: dict(values)
        ), patch(
            "utils.return_bulk.activate", AsyncMock()
        ) as activate, patch.object(
            worker, "_process_requests", process
        ), patch(
            "utils.member_profile_runs.ProfileRuns", return_value=profile
        ):
            assert await worker._poll(None, mongo) == 0
            assert await worker._poll(None, mongo) == 0
            process.assert_not_awaited()
            band_writes = lambda: [
                c
                for c in mongo.bot_config.update_one.await_args_list
                if c.args[0]["_id"] == "manage-web-band-status"
            ]
            assert len(band_writes()) == 1
            values["checked_at"] = 2
            await worker._poll(None, mongo)
            assert len(band_writes()) == 1
            values["health"] = "unhealthy"
            await worker._poll(None, mongo)
            assert len(band_writes()) == 2
            assert [
                call.args[1]["$set"].get("checked_at") for call in band_writes()
            ] == [1, 2]
            state.ready = {"_id": "new request"}
            assert await worker._poll(None, mongo) == 7
            state.ready = None
            clock[0] += 3
            assert await worker._poll(None, mongo) == 7
            clock[0] += 60
            state.ready_at = clock[0]
            assert await worker._poll(None, mongo) == 0
            assert activate.await_count == 2
            assert mongo.bot_config.update_many.await_count == 2

    asyncio.run(run())


def test_idle_detection_is_bounded_at_two_seconds_and_active_work_never_throttles():
    async def run():
        clock = [0.0]
        mongo = object()
        with patch.object(worker, "time", NS(monotonic=lambda: clock[0])):
            assert worker.idle_poll_due(mongo)
            state = state_for(mongo)
            state.ready_at = 0
            state.ready = None
            clock[0] = 1.99
            assert not worker.idle_poll_due(mongo)
            clock[0] = 2
            assert worker.idle_poll_due(mongo)
            state.ready_at = 2
            state.ready = {"_id": "pending"}
            assert worker.idle_poll_due(mongo)

    asyncio.run(run())


def test_ten_second_admission_never_waits_for_delivery_or_starts_a_duplicate(
    monkeypatch,
):
    from extensions.tasks import cwl_reminder as bridge

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        heartbeat_stopped = asyncio.Event()
        calls = []

        async def slow():
            calls.append("delivery")
            entered.set()
            await release.wait()

        async def heartbeat(mongo):
            try:
                await asyncio.Event().wait()
            finally:
                heartbeat_stopped.set()

        monkeypatch.setattr(bridge, "_roster_driver", None)
        monkeypatch.setattr(bridge, "_management_stopping", False)
        monkeypatch.setattr(bridge, "_poll_web_roster_bridge", slow)
        monkeypatch.setattr(worker, "maintain_worker_heartbeat", heartbeat)
        monkeypatch.setattr(worker, "poll", AsyncMock(return_value=0))
        await asyncio.wait_for(bridge._poll_web_roster_requests(), 0.1)
        await entered.wait()
        owned = bridge._roster_driver
        await asyncio.wait_for(bridge._poll_web_roster_requests(), 0.1)
        assert bridge._roster_driver is owned and calls == ["delivery"]
        release.set()
        await owned
        assert heartbeat_stopped.is_set()

    asyncio.run(run())


def test_canceled_bridge_keeps_lane_releasable_and_shutdown_blocks_new_admission(
    monkeypatch,
):
    from extensions.tasks import cwl_reminder as bridge

    async def run():
        entered = asyncio.Event()

        async def slow():
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(bridge, "_roster_driver", None)
        monkeypatch.setattr(bridge, "_management_stopping", False)
        monkeypatch.setattr(bridge, "_poll_web_roster_bridge", slow)
        monkeypatch.setattr(worker, "maintain_worker_heartbeat", AsyncMock())
        await bridge._poll_web_roster_requests()
        await entered.wait()
        owned = bridge._roster_driver
        owned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owned
        assert not worker.queue_lock().locked()
        monkeypatch.setattr(bridge, "_management_stopping", True)
        await bridge._poll_web_roster_requests()
        assert bridge._roster_driver is owned

    asyncio.run(run())


def test_unusable_base_image_result_never_caches_failure_or_partially_changes_images():
    async def run():
        from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE

        original_war, original_active = dict(FWA_WAR_BASE), dict(FWA_ACTIVE_WAR_BASE)
        read = AsyncMock(
            side_effect=[
                {"war_base_images": {"fixture": None}, "active_base_images": None},
                {},
            ]
        )
        mongo = NS(fwa_data=NS(find_one=read))
        try:
            with pytest.raises(ValueError):
                await runtime.refresh_base_image_cache(mongo)
            assert dict(FWA_WAR_BASE) == original_war
            assert dict(FWA_ACTIVE_WAR_BASE) == original_active
            assert await runtime.refresh_base_image_cache(mongo)
            assert read.await_count == 2
        finally:
            FWA_WAR_BASE.clear()
            FWA_WAR_BASE.update(original_war)
            FWA_ACTIVE_WAR_BASE.clear()
            FWA_ACTIVE_WAR_BASE.update(original_active)

    asyncio.run(run())


def test_independent_heartbeat_survives_a_temporary_mongo_failure(caplog):
    async def run():
        write = AsyncMock(side_effect=[RuntimeError("owned outage"), True])
        ticks = 0

        async def sleep(seconds):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                raise asyncio.CancelledError()

        with patch.object(worker, "_write_heartbeat", write), patch.object(
            worker, "asyncio", NS(sleep=sleep)
        ):
            with pytest.raises(asyncio.CancelledError):
                await worker.maintain_worker_heartbeat(object())
        assert write.await_count == 2

    asyncio.run(run())
    assert (
        sum(
            "Management heartbeat unavailable" in record.message
            for record in caplog.records
        )
        == 1
    )
