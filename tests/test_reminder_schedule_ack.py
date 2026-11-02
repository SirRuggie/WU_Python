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


def test_repeated_started_same_bot_keeps_loaded_proof_and_new_bot_clears_it(runtime, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    mongo, _, _ = runtime
    app = object()
    reconciler = SimpleNamespace(start=Mock())
    monkeypatch.setattr(native, 'bot_instance', app)
    monkeypatch.setattr(native, 'startup_reconciler', reconciler)
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


def test_same_cycle_concurrent_install_serializes_and_ack_matches_last_completed(runtime, monkeypatch):
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
    monkeypatch.setattr(campaign, 'load_campaign', gated)
    async def run():
        await asyncio.gather(native.sync_campaign_schedule(GUILD, CYCLE), native.sync_campaign_schedule(GUILD, CYCLE))
        assert maximum == 1
        assert native._loaded_campaign_generations(GUILD) == {CYCLE: '1:0'}
        sender.assert_not_awaited()
    asyncio.run(run())
