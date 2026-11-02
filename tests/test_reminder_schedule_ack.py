"""Actual native scheduler-load acknowledgement, without Discord or network."""

import asyncio
from unittest.mock import AsyncMock

import pendulum
import pytest
from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge
from test_cwl_dashboard_integration import MemoryMongo, MemoryScheduler

GUILD = campaign.LEGACY_WU_GUILD_ID
CYCLE = "2026-11"
EPOCH = "fixture-process-a"


@pytest.fixture
def runtime(monkeypatch):
    clock = pendulum.datetime(2026, 11, 2, 12, tz="America/New_York")
    monkeypatch.setattr(pendulum, "now", lambda tz=None: clock.in_timezone(tz or "UTC"))
    monkeypatch.setattr(bridge, "_schedule_repair_attempts", {})
    mongo = MemoryMongo()
    mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
        "_id": campaign.defaults_id(GUILD),
        "kind": "cwl_campaign_defaults",
        "guild_id": GUILD,
        "activated": True,
        "revision": 1,
        "campaign": campaign.default_campaign(),
        "updated_at": "fixture-v1",
    }
    scheduler = MemoryScheduler()
    monkeypatch.setattr(native, "mongo_client", mongo)
    monkeypatch.setattr(native, "scheduler", scheduler)
    monkeypatch.setattr(native, "_campaign_runtime_id", EPOCH)
    monkeypatch.setattr(native, "_campaign_loaded_generations", {})
    monkeypatch.setattr(native, "_campaign_load_targets", {})
    monkeypatch.setattr(native, "_campaign_sync_locks", {})
    monkeypatch.setattr(native, "_campaign_load_scan_complete", False)
    sender = AsyncMock(side_effect=AssertionError("Ack must never send"))
    monkeypatch.setattr(native, "send_campaign_message", sender)
    return mongo, scheduler, sender


async def reconcile(sync=None, epoch=EPOCH):
    return await bridge.reconcile_campaign_changes(
        native.mongo_client,
        sync or native._sync_all_campaigns,
        guild_id=GUILD,
        loaded_generations=lambda: native._loaded_campaign_generations(GUILD),
        runtime_id=epoch,
    )


def test_defaults_only_real_load_acknowledges_and_idle_poll_does_not_reload_or_write(
    runtime,
):
    mongo, scheduler, sender = runtime

    async def run():
        assert await reconcile()
        row = await mongo.bot_config.find_one({"_id": bridge.worker_id(GUILD)})
        assert row["schedule_generations"][CYCLE] == "1:0"
        assert row["schedule_generations"]["2026-12"] == "1:0"
        assert row["schedule_epoch"] == EPOCH
        jobs = dict(scheduler.jobs)
        update = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = update
        reload = AsyncMock(side_effect=AssertionError("Unchanged poll must not reload"))
        assert not await reconcile(reload)
        update.assert_not_awaited()
        assert scheduler.jobs == jobs
        sender.assert_not_awaited()

    asyncio.run(run())


def test_unchanged_fingerprint_repairs_old_empty_ack_from_completed_load_without_reload(
    runtime,
):
    mongo, scheduler, sender = runtime

    async def run():
        await reconcile()
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        row["schedule_generations"] = {}
        row.pop("schedule_epoch", None)
        reload = AsyncMock(
            side_effect=AssertionError("Already-loaded jobs need only ack repair")
        )
        assert await reconcile(reload)
        assert row["schedule_generations"][CYCLE] == "1:0"
        assert not await reconcile(reload)
        reload.assert_not_awaited()
        sender.assert_not_awaited()

    asyncio.run(run())


def test_callback_without_completed_native_load_cannot_ack(runtime):
    mongo, _, _ = runtime

    async def run():
        with pytest.raises(ValueError, match="No schedule load completed"):
            await reconcile(AsyncMock())
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents

    asyncio.run(run())


def test_failed_job_install_never_creates_process_proof(runtime, monkeypatch):
    mongo, scheduler, _ = runtime
    add = scheduler.add_job

    def failing(function, **kwargs):
        if str(kwargs.get("id", "")).startswith(native.CAMPAIGN_JOB_PREFIX):
            raise RuntimeError("fixture scheduler unavailable")
        return add(function, **kwargs)

    monkeypatch.setattr(scheduler, "add_job", failing)

    async def run():
        with pytest.raises(RuntimeError, match="scheduler unavailable"):
            await reconcile()
        assert native._loaded_campaign_generations(GUILD) is None
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents

    asyncio.run(run())


def test_changed_generation_and_racing_edit_ack_only_what_was_installed(runtime):
    mongo, scheduler, sender = runtime

    async def run():
        await reconcile()
        defaults = mongo.bot_config.documents[campaign.defaults_id(GUILD)]
        defaults.update(revision=2, updated_at="fixture-v2")

        async def racing_load():
            await native._sync_all_campaigns()
            defaults.update(revision=3, updated_at="fixture-v3")

        assert await reconcile(racing_load)
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        assert row["schedule_generations"][CYCLE] == "2:0"
        current = await campaign.load_campaign(mongo, GUILD, CYCLE)
        assert bridge.campaign_generation(current) == "3:0"
        assert row["schedule_generations"][CYCLE] != bridge.campaign_generation(current)
        assert await reconcile()
        assert row["schedule_generations"][CYCLE] == "3:0"
        sender.assert_not_awaited()

    asyncio.run(run())


def test_restart_requires_real_restore_and_keeps_sent_occurrences_unscheduled(
    runtime, monkeypatch
):
    mongo, _, sender = runtime

    async def run():
        await reconcile()
        oid = campaign.occurrence_id(CYCLE, "signup", "main")
        mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
            "_id": campaign.cycle_id(GUILD, CYCLE),
            "kind": "cwl_campaign_cycle",
            "guild_id": GUILD,
            "cycle": CYCLE,
            "activated": True,
            "revision": 0,
            "sent_occurrences": [oid],
        }
        monkeypatch.setattr(native, "scheduler", MemoryScheduler())
        native._campaign_loaded_generations.clear()
        native._campaign_load_targets.clear()
        native._campaign_sync_locks.clear()
        monkeypatch.setattr(native, "_campaign_load_scan_complete", False)
        monkeypatch.setattr(native, "_campaign_runtime_id", "fixture-process-b")
        await bridge.mark_worker_alive(
            mongo, GUILD, worker_epoch="fixture-process-b", schedule_ready=False
        )
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        assert row["worker_epoch"] != row["schedule_epoch"]
        assert await reconcile(epoch="fixture-process-b")
        assert row["schedule_epoch"] == "fixture-process-b"
        assert (
            native._campaign_job_id(GUILD, CYCLE, "signup", "main")
            not in native.scheduler.jobs
        )
        assert row["schedule_generations"][CYCLE] == "1:0"
        sender.assert_not_awaited()

    asyncio.run(run())


def test_repeated_started_same_bot_keeps_loaded_proof_and_new_bot_clears_it(
    runtime, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    mongo, _, _ = runtime
    app = object()
    reconciler = SimpleNamespace(start=Mock())
    monkeypatch.setattr(native, "bot_instance", app)
    monkeypatch.setattr(native, "startup_reconciler", reconciler)

    async def run():
        await reconcile()
        before = native._loaded_campaign_generations(GUILD)
        await native.on_bot_started(SimpleNamespace(app=app), mongo)
        assert native._campaign_runtime_id == EPOCH
        assert native._loaded_campaign_generations(GUILD) == before
        await native.on_bot_started(SimpleNamespace(app=object()), mongo)
        assert native._campaign_runtime_id != EPOCH
        assert native._loaded_campaign_generations(GUILD) is None

    asyncio.run(run())


def test_same_cycle_concurrent_install_serializes_and_ack_matches_last_completed(
    runtime, monkeypatch
):
    mongo, _, sender = runtime
    original = campaign.load_campaign
    active = 0
    maximum = 0

    async def gated(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0)
            return await original(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(campaign, "load_campaign", gated)

    async def run():
        await asyncio.gather(
            native.sync_campaign_schedule(GUILD, CYCLE),
            native.sync_campaign_schedule(GUILD, CYCLE),
        )
        assert maximum == 1
        assert native._loaded_campaign_generations(GUILD) == {CYCLE: "1:0"}
        sender.assert_not_awaited()

    asyncio.run(run())


def test_failed_load_is_bounded_across_six_unchanged_polls(runtime):
    async def run():
        sync = AsyncMock(side_effect=ValueError("bad cycle"))
        for _ in range(6):
            try:
                await reconcile(sync)
            except ValueError:
                pass
        assert sync.await_count == 1

    asyncio.run(run())


def test_single_cycle_install_failure_never_records_even_partial_proof(
    runtime, monkeypatch
):
    _, scheduler, sender = runtime
    add = scheduler.add_job
    calls = 0

    def fail_second(function, **kwargs):
        nonlocal calls
        if str(kwargs.get("id", "")).startswith(native.CAMPAIGN_JOB_PREFIX):
            calls += 1
            if calls == 2:
                raise RuntimeError("second install failed")
        return add(function, **kwargs)

    monkeypatch.setattr(scheduler, "add_job", fail_second)

    async def run():
        with pytest.raises(RuntimeError, match="second install"):
            await native.sync_campaign_schedule(GUILD, CYCLE)
        assert calls == 2
        assert (GUILD, CYCLE) not in native._campaign_loaded_generations
        sender.assert_not_awaited()

    asyncio.run(run())


def test_cleared_process_proof_unchanged_fingerprint_requires_real_reinstall(runtime):
    async def run():
        await reconcile()
        native._campaign_loaded_generations.clear()
        reload = AsyncMock(wraps=native._sync_all_campaigns)
        assert (
            await reconcile(reload) is False
        )  # existing acknowledgement already exact
        reload.assert_awaited_once()
        assert native._loaded_campaign_generations(GUILD)[CYCLE] == "1:0"

    asyncio.run(run())


@pytest.mark.parametrize("epoch", ["", None, 123])
def test_invalid_runtime_identity_refused_before_loading(runtime, epoch):
    async def run():
        reload = AsyncMock()
        with pytest.raises(ValueError, match="process identity"):
            await reconcile(reload, epoch=epoch)
        reload.assert_not_awaited()

    asyncio.run(run())


def test_failed_load_retries_after_300s_and_config_change_bypasses_backoff(
    runtime, monkeypatch
):
    mongo, _, _ = runtime
    clock = [100.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: clock[0])

    async def run():
        sync = AsyncMock(side_effect=ValueError("bad cycle"))
        with pytest.raises(ValueError):
            await reconcile(sync)
        clock[0] += 299
        assert not await reconcile(sync)
        mongo.bot_config.documents[campaign.defaults_id(GUILD)]["revision"] += 1
        with pytest.raises(ValueError):
            await reconcile(sync)
        clock[0] += 300
        with pytest.raises(ValueError):
            await reconcile(sync)
        assert sync.await_count == 3

    asyncio.run(run())


def test_runtime_change_during_install_never_records_old_process_proof(
    runtime, monkeypatch
):
    original = native._persist_campaign_job

    async def restart_during_install(*args, **kwargs):
        result = await original(*args, **kwargs)
        monkeypatch.setattr(native, "_campaign_runtime_id", "replacement-process")
        return result

    monkeypatch.setattr(native, "_persist_campaign_job", restart_during_install)

    async def run():
        await native.sync_campaign_schedule(GUILD, CYCLE)
        assert (GUILD, CYCLE) not in native._campaign_loaded_generations

    asyncio.run(run())


def test_native_repair_scan_projects_only_active_campaign_ownership(runtime):
    mongo, _, _ = runtime
    find = mongo.bot_config.find
    calls = []

    def observed(query=None, projection=None, *args, **kwargs):
        calls.append((query, projection))
        return find(query, projection, *args, **kwargs)

    mongo.bot_config.find = observed

    async def run():
        await native._sync_all_campaigns()
        assert calls[0] == (
            {
                "kind": {"$in": ["cwl_campaign_defaults", "cwl_campaign_cycle"]},
                "activated": True,
            },
            {"_id": 1, "kind": 1, "activated": 1, "guild_id": 1, "cycle": 1},
        )

    asyncio.run(run())
