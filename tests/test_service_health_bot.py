"""Bot proof must come from real existing work, not the reporting timer."""

import asyncio
from types import SimpleNamespace as S
from unittest.mock import patch

import pytest

from extensions.tasks import service_health as health, cwl_reminder as bridge
from utils import manage_web_worker as worker
from utils.manage_poll_cache import state_for


class Sender:
    def __init__(self):
        self.calls = []
        self.closed = False

    def submit(self, healthy):
        self.calls.append(healthy)
        return True

    async def close(self):
        self.closed = True


def make(clock, mongo):
    sender = Sender()
    shard = S(is_alive=True, is_connected=True)
    bot = S(is_alive=True, shards={0: shard})
    scheduler = S(state=health.STATE_RUNNING)
    monitor = health.BotHealth(
        bot, mongo, scheduler, sender=sender, clock=lambda: clock[0]
    )
    return monitor, sender, shard, scheduler


def test_connected_gateway_and_existing_recent_work_ping_without_new_reads():
    async def run():
        clock, mongo = [100.0], object()
        monitor, sender, _, _ = make(clock, mongo)
        monitor.job_ran()
        state_for(mongo).heartbeat_at = 90
        assert monitor.check() and sender.calls == [True]
        await monitor.close()
        assert sender.closed and not monitor.check()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    [
        "gateway",
        "empty_shards",
        "process",
        "scheduler",
        "old_job",
        "old_heartbeat",
        "future_job",
    ],
)
def test_dead_or_stale_proof_stops_pings_even_if_reporting_timer_runs(failure):
    async def run():
        clock, mongo = [200.0], object()
        monitor, sender, shard, scheduler = make(clock, mongo)
        monitor.job_ran()
        state_for(mongo).heartbeat_at = 200
        if failure == "gateway":
            shard.is_connected = False
        elif failure == "empty_shards":
            monitor.bot.shards = {}
        elif failure == "process":
            monitor.bot.is_alive = False
        elif failure == "scheduler":
            scheduler.state = 0
        elif failure == "old_job":
            monitor.last_job = 100
        elif failure == "old_heartbeat":
            state_for(mongo).heartbeat_at = 100
        else:
            monitor.last_job = 201
        for _ in range(2):
            assert not monitor.check()
        assert sender.calls == []

    asyncio.run(run())


def test_unchanged_finite_gateway_latency_is_not_used_as_recent_ack_proof():
    async def run():
        clock, mongo = [200.0], object()
        monitor, sender, shard, _ = make(clock, mongo)
        shard.heartbeat_latency = 0.01  # Historical number alone proves nothing.
        monitor.last_job = 0
        state_for(mongo).heartbeat_at = 200
        assert not monitor.check() and sender.calls == []

    asyncio.run(run())


@pytest.mark.parametrize("duration", [70, 150, 200])
def test_actual_management_tick_and_independent_heartbeat_cover_normal_job(
    monkeypatch, duration
):
    async def run():
        clock, writes = [0.0], []

        async def write(*a, **kw):
            writes.append(clock[0])

        mongo = S(bot_config=S(update_one=write))
        monitor, sender, _, _ = make(clock, mongo)
        pending = asyncio.create_task(asyncio.Event().wait())
        monkeypatch.setattr(bridge, "bot_instance", monitor.bot)
        monkeypatch.setattr(bridge, "mongo_client", mongo)
        monkeypatch.setattr(bridge, "_management_stopping", False)
        monkeypatch.setattr(bridge, "_management_driver", pending)
        monkeypatch.setattr(bridge, "_external_health", monitor)
        monkeypatch.setattr(
            worker, "time", S(monotonic=lambda: clock[0], time=lambda: 1000 + clock[0])
        )
        ticks = 0

        async def sleep(seconds):
            nonlocal ticks
            assert seconds == 10
            ticks += 1
            clock[0] += 10
            await bridge._poll_web_management_fast()
            if ticks == duration // 10:
                assert monitor.check()  # Job can still be waiting on Discord.
                raise asyncio.CancelledError()
            await asyncio.sleep(0)

        monkeypatch.setattr(worker, "asyncio", S(sleep=sleep))
        try:
            with pytest.raises(asyncio.CancelledError):
                await worker.maintain_worker_heartbeat(mongo)
            assert clock[0] == duration and sender.calls == [True]
            assert max(b - a for a, b in zip(writes, writes[1:])) == 30
            # A reporter/heartbeat still running cannot renew scheduler proof.
            clock[0] = 300
            state_for(mongo).heartbeat_at = 300
            assert not monitor.check() and sender.calls == [True]
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(run())


def test_unset_url_starts_no_bot_worker(monkeypatch):
    monkeypatch.delenv(health.ENV_NAME, raising=False)
    assert health.start(None, None, None) is None


def test_real_bot_start_stop_owns_one_monitor(monkeypatch):
    from extensions.tasks import service_health

    async def run():
        sender = Sender()
        sender.enabled = True
        monkeypatch.setenv(health.ENV_NAME, "fixture")
        monkeypatch.setattr(service_health, "ExternalHeartbeat", lambda *a: sender)
        monkeypatch.setattr(bridge, "_external_health", None)
        monkeypatch.setattr(bridge, "_management_stopping", False)
        monkeypatch.setattr(bridge, "bot_instance", None)
        monkeypatch.setattr(bridge, "mongo_client", None)
        monkeypatch.setattr(
            bridge,
            "startup_reconciler",
            S(start=lambda: None, stop=lambda: asyncio.sleep(0)),
        )
        monkeypatch.setattr(bridge, "scheduler", S(state=1, running=False))
        monkeypatch.setattr(bridge, "_management_driver", None)
        monkeypatch.setattr(bridge, "_roster_driver", None)
        event = S(app=S(is_alive=True, shards={0: S(is_alive=True, is_connected=True)}))
        await bridge.on_bot_started(event, object())
        first = bridge._external_health
        await bridge.on_bot_started(event, object())
        assert bridge._external_health is first
        await bridge.on_bot_stopping(None)
        assert (
            sender.closed and bridge._external_health is None and first.task.cancelled()
        )

    asyncio.run(run())
