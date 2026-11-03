"""Cross-feature175 heartbeat,177 copy and183 editor safety.

Only MemoryMongo, synthetic identities and mocked Discord transport; no real I/O.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from extensions.tasks import cwl_reminder as native
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge

GUILD = 22
CYCLE = "2026-11"
CANDIDATE = {
    "title": "Reviewed synthetic roster",
    "body": "One reviewed pool only",
    "buttons": [{"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}],
}


@pytest.mark.parametrize("post_ready", [False, True])
def test_one_heartbeat_preserves_ack_identity_and_post_update_protocol(monkeypatch, post_ready):
    async def run():
        mongo = MemoryMongo()
        now = "2026-11-03T17:00:00+00:00"
        monkeypatch.setattr(bridge, "_now", lambda: now)
        sender = AsyncMock()
        heartbeat_writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = heartbeat_writes
        assert await bridge.process_pending_roster_requests(
            mongo, sender, guild_id=GUILD, worker_epoch="synthetic-runtime",
            schedule_ready=True, post_update_ready=post_ready,
        ) == 0
        heartbeat_writes.assert_awaited_once()
        assert heartbeat_writes.await_args.args[0] == {"_id": bridge.worker_id(GUILD)}
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        assert row["worker_epoch"] == "synthetic-runtime"
        assert row["schedule_ready"] is True
        assert row["post_update_protocol"] == 1
        assert row["post_update_ready"] is post_ready
        assert row["post_update_ready_at"] == row["updated_at"] == now
        sender.assert_not_awaited()
    asyncio.run(run())


def test_omitted_optional_heartbeat_fields_do_not_erase_other_protocol():
    async def run():
        mongo = MemoryMongo()
        await bridge.mark_worker_alive(mongo, GUILD, worker_epoch="epoch", schedule_ready=True, post_update_ready=True)
        await bridge.mark_worker_alive(mongo, GUILD, worker_epoch="epoch2", schedule_ready=False)
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        assert row["post_update_ready"] is True
        assert row["worker_epoch"] == "epoch2" and row["schedule_ready"] is False
        await bridge.mark_worker_alive(mongo, GUILD, post_update_ready=False)
        row = mongo.bot_config.documents[bridge.worker_id(GUILD)]
        assert row["post_update_ready"] is False
        assert row["worker_epoch"] == "epoch2" and row["schedule_ready"] is False
    asyncio.run(run())


@pytest.mark.parametrize("bad", [0, 1, "ready"])
def test_invalid_post_readiness_does_not_write_or_damage_ack_fields(bad):
    async def run():
        mongo = MemoryMongo()
        await bridge.mark_worker_alive(mongo, GUILD, worker_epoch="epoch", schedule_ready=True)
        before = deepcopy(mongo.bot_config.documents)
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        with pytest.raises(ValueError, match="Post-update readiness must be explicit"):
            await bridge.mark_worker_alive(mongo, GUILD, worker_epoch="replacement", post_update_ready=bad)
        assert mongo.bot_config.documents == before
        writes.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("ready", [False, True])
def test_actual_native_poll_advertises_both_protocols_without_sending(monkeypatch, ready):
    async def run():
        mongo = MemoryMongo()
        worker = SimpleNamespace(ensure_ready=AsyncMock(return_value=ready), poll=AsyncMock())
        monkeypatch.setattr(native, "mongo_client", mongo)
        monkeypatch.setattr(native, "bot_instance", SimpleNamespace())
        monkeypatch.setattr(native, "_campaign_runtime_id", "native-epoch")
        monkeypatch.setattr(native, "_loaded_campaign_generations", lambda guild: {})
        monkeypatch.setattr(native, "_post_update_worker_for_runtime", lambda: worker)
        monkeypatch.setattr(bridge, "reconcile_campaign_changes", AsyncMock())
        sender = AsyncMock()
        monkeypatch.setattr(native, "send_campaign_message", sender)
        await native._poll_web_roster_bridge()
        row = mongo.bot_config.documents[bridge.worker_id(campaign.LEGACY_WU_GUILD_ID)]
        assert row["worker_epoch"] == "native-epoch"
        assert row["schedule_ready"] is True
        assert row["post_update_ready"] is ready
        assert row["post_update_protocol"] == 1
        assert worker.poll.await_count == int(ready)
        sender.assert_not_awaited()
    asyncio.run(run())


def test_native_stop_clears_both_load_scan_and_post_editor_lifecycle(monkeypatch):
    async def run():
        for name in ["_campaign_load_targets", "_campaign_loaded_generations", "_campaign_sync_locks"]:
            monkeypatch.setattr(native, name, {"synthetic": True})
        for name in ["startup_reconciler", "_management_driver", "_roster_driver"]:
            monkeypatch.setattr(native, name, None)
        monkeypatch.setattr(native, "_management_stopping", False)
        monkeypatch.setattr(native, "_campaign_load_scan_complete", True)
        monkeypatch.setattr(native, "_post_update_worker", object())
        monkeypatch.setattr(native, "scheduler", SimpleNamespace(running=False))
        await native.on_bot_stopping(SimpleNamespace())
        assert native._campaign_load_scan_complete is False
        assert native._post_update_worker is None
        assert native._management_stopping is True
        assert not native._campaign_load_targets
        assert not native._campaign_loaded_generations
        assert not native._campaign_sync_locks
    asyncio.run(run())


def seed_campaign(mongo, marked):
    value = campaign.default_campaign(new_copy=marked)
    for pool in campaign.AUDIENCES:
        value["messages"]["signup"]["variants"][pool]["body"] = (
            "Saved synthetic signup. " + campaign.SHORT_SIGNUP_CHECK_LINE
        )
    mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
        "_id": campaign.cycle_id(GUILD, CYCLE), "kind": "cwl_campaign_cycle",
        "guild_id": GUILD, "cycle": CYCLE, "revision": 4,
        "campaign": value, "updated_at": "2026-11-01T00:00:00+00:00",
        "activated": True, "deliveries": [{"status": "sent", "message_id": 400}],
        "sent_occurrences": ["synthetic-existing-occurrence"],
    }
    return value


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("future_months", [False, True])
def test_field_copy_save_preserves177_marker_and_other_message_normalization(monkeypatch, marked, future_months):
    async def run():
        mongo = MemoryMongo()
        monkeypatch.setattr(campaign, "_utcnow", lambda: "2026-11-03T17:00:00+00:00")
        seed_campaign(mongo, marked)
        before = await campaign.load_campaign(mongo, GUILD, CYCLE)
        await campaign.save_updated_roster_variant(
            mongo, guild_id=GUILD, cycle=CYCLE, pool="main", user_id=200,
            candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before),
            future_months=future_months,
        )
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        after = await campaign.load_campaign(mongo, GUILD, CYCLE)
        expected = deepcopy(before["campaign"])
        expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
        assert after["campaign"] == expected
        assert after["campaign"].get(campaign.DEFAULT_COPY_FIELD) == (
            campaign.DEFAULT_COPY_VERSION if marked else None
        )
        for pool in campaign.AUDIENCES:
            body = after["campaign"]["messages"]["signup"]["variants"][pool]["body"]
            assert body == before["campaign"]["messages"]["signup"]["variants"][pool]["body"]
        assert after["deliveries"] == before["deliveries"]
        assert after["sent_occurrences"] == before["sent_occurrences"]
        writes.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("marked", [False, True])
def test_pause_flips_preserve_marker_and_future_field_copy_without_template_reset(monkeypatch, marked):
    async def run():
        mongo = MemoryMongo()
        value = seed_campaign(mongo, marked)
        source = mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
        source.update(recurring_campaign=deepcopy(value), recurring_updated_at="2026-10-20T00:00:00+00:00")
        monkeypatch.setattr(campaign, "_utcnow", lambda: "2026-11-03T17:00:00+00:00")
        before = await campaign.load_campaign(mongo, GUILD, CYCLE)
        await campaign.save_updated_roster_variant(
            mongo, guild_id=GUILD, cycle=CYCLE, pool="main", user_id=200,
            candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before), future_months=True,
        )
        for index, paused in enumerate([True, False, True, False]):
            monkeypatch.setattr(campaign, "_utcnow", lambda: f"2026-11-03T2{index}:00:00+00:00")
            await campaign.set_paused(mongo, GUILD, paused, CYCLE, 200)
            for cycle in [CYCLE, "2026-12", "2027-01"]:
                loaded = await campaign.load_campaign(mongo, GUILD, cycle)
                assert loaded["campaign"]["paused"] is paused
                assert loaded["campaign"]["messages"]["roster"]["variants"]["main"]["body"] == CANDIDATE["body"]
                assert loaded["campaign"].get(campaign.DEFAULT_COPY_FIELD) == (
                    campaign.DEFAULT_COPY_VERSION if marked else None
                )
                assert loaded["campaign"]["messages"]["signup"]["variants"]["lazy"]["body"] == before["campaign"]["messages"]["signup"]["variants"]["lazy"]["body"]
    asyncio.run(run())
