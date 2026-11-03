"""Native startup catch-up contract; isolated state and fake Discord only."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pendulum
import pytest

from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign
from test_cwl_dashboard_integration import MemoryMongo, StrictCampaignRest, install_runtime

GUILD = 22
CYCLE = "2026-11"


@pytest.fixture
def runtime(monkeypatch):
    clock = [pendulum.datetime(2026, 11, 20, 12, tz="America/New_York")]
    monkeypatch.setattr(
        pendulum, "now", lambda tz=None: clock[0].in_timezone(tz or "UTC")
    )
    monkeypatch.setattr(campaign, "_utcnow", lambda: clock[0].in_timezone("UTC").isoformat())
    mongo = MemoryMongo()
    template = campaign.default_campaign()
    template["reminder_sequence"] = {"enabled": False}
    for message in template["messages"].values():
        message["enabled"] = False
    signup = template["messages"]["signup"]
    signup["enabled"] = True
    signup["variants"]["lazy"]["enabled"] = False
    signup["variants"]["main"].update(
        destination_channel_id=300,
        role_ids=[700],
        title="Original local signup",
        body="Original local signup text.",
    )
    mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
        "_id": campaign.defaults_id(GUILD),
        "kind": "cwl_campaign_defaults",
        "guild_id": GUILD,
        "activated": True,
        "revision": 1,
        "campaign": template,
    }
    scheduler, rest = install_runtime(
        monkeypatch, mongo, rest=StrictCampaignRest(guild_id=GUILD)
    )
    monkeypatch.setattr(native, "_campaign_runtime_id", "catchup-process-a")
    monkeypatch.setattr(native, "_campaign_loaded_generations", {})
    monkeypatch.setattr(native, "_campaign_load_targets", {})
    monkeypatch.setattr(native, "_campaign_sync_locks", {})
    monkeypatch.setattr(native, "_campaign_load_scan_complete", False)
    monkeypatch.setattr(native, "_campaign_catchup_active", set())
    return SimpleNamespace(clock=clock, mongo=mongo, scheduler=scheduler, rest=rest)


async def persist_due(runtime, *, minutes):
    due = runtime.clock[0].subtract(minutes=minutes)
    template = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]
    template["messages"]["signup"]["schedule"] = {
        "mode": "monthly", "day": due.day, "hour": due.hour, "minute": due.minute
    }
    loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
    assert loaded["activated"] and not loaded["campaign"]["paused"]
    assert pendulum.parse(loaded["deadline"]) > runtime.clock[0]
    job_id = native._campaign_job_id(GUILD, CYCLE, "signup", "main")
    startup = runtime.clock[0]
    runtime.clock[0] = due.subtract(minutes=1)
    try:
        await native._persist_campaign_job(
            job_id, due, GUILD, CYCLE, "signup", ["main"],
            native._campaign_generation(loaded),
        )
    finally:
        runtime.clock[0] = startup
    return job_id, due, loaded


async def run_current_due_jobs(runtime):
    runtime.clock[0] = runtime.clock[0].add(seconds=6)
    for job in list(runtime.scheduler.jobs.values()):
        if not job.id.startswith(f"{native.CAMPAIGN_JOB_PREFIX}{GUILD}:{CYCLE}:"):
            continue
        if pendulum.instance(job.trigger.run_date) <= runtime.clock[0]:
            await job.function(*job.args, **(getattr(job, "kwargs", None) or {}))


@pytest.mark.parametrize("minutes", [1, 359])
def test_native_restart_sends_one_unsent_signup_inside_window(runtime, minutes):
    async def run():
        await persist_due(runtime, minutes=minutes)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        assert runtime.rest.sent[0]["channel"] == 300
        assert runtime.rest.sent[0]["role_mentions"] == [700]
        assert runtime.rest.sent[0]["user_mentions"] is False
        assert runtime.rest.sent[0]["mentions_everyone"] is False
        # The original sent ledger is authoritative after a second restart.
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1

    asyncio.run(run())


def test_native_restart_records_too_late_without_calling_sender(runtime):
    async def run():
        _, due, _ = await persist_due(runtime, minutes=361)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert any(
            entry.get("occurrence_id") == campaign.occurrence_id(CYCLE, "signup", "main")
            and entry.get("status") == "skipped"
            and "too late" in str(entry.get("reason", "")).lower()
            for entry in loaded["deliveries"]
        ), f"No durable too-late decision for original due time {due}"

    asyncio.run(run())


def test_native_restart_never_catches_up_an_existing_sent_receipt(runtime):
    async def run():
        await persist_due(runtime, minutes=1)
        await campaign.record_delivery(runtime.mongo, GUILD, CYCLE, {
            "occurrence_id": campaign.occurrence_id(CYCLE, "signup", "main"),
            "message_key": "signup", "variant": "main", "status": "sent",
            "message_id": 9001,
        })
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []

    asyncio.run(run())


def test_native_restart_recovers_confirmed_pending_ledger_without_sender(runtime):
    async def run():
        job_id, _, _ = await persist_due(runtime, minutes=1)
        receipt = {
            "occurrence_id": campaign.occurrence_id(CYCLE, "signup", "main"),
            "message_key": "signup", "variant": "main", "status": "sent",
            "channel_id": 300, "message_id": 9002,
        }
        runtime.mongo.cwl_pending_reminders.documents[job_id].update(
            status="ledger_pending", receipt=deepcopy(receipt)
        )
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert receipt["occurrence_id"] in loaded["sent_occurrences"]
        assert job_id not in runtime.mongo.cwl_pending_reminders.documents

    asyncio.run(run())


@pytest.mark.parametrize("change, reason", [
    ("paused", "paused"), ("off", "automation is off"),
    ("message_off", "message is off"), ("variant_off", "message is off"),
    ("generation", "settings changed"), ("closed", "signups closed"),
    ("rollover", "another month"),
])
def test_ineligible_restored_jobs_record_why_without_sender(runtime, change, reason):
    async def run():
        await persist_due(runtime, minutes=1)
        defaults = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]
        config = defaults["campaign"]
        if change == "paused":
            config["paused"] = True
        elif change == "off":
            defaults["activated"] = False
        elif change == "message_off":
            config["messages"]["signup"]["enabled"] = False
        elif change == "variant_off":
            config["messages"]["signup"]["variants"]["main"]["enabled"] = False
        elif change == "generation":
            defaults["revision"] += 1
        elif change == "closed":
            config["signup_deadline"] = {"at": runtime.clock[0].subtract(seconds=1).isoformat()}
        else:
            runtime.clock[0] = pendulum.datetime(2026, 12, 1, 0, 1, tz="America/New_York")
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        decisions = [entry for entry in loaded["deliveries"] if entry.get("status") == "skipped"]
        assert len(decisions) == 1 and reason in decisions[0]["reason"].lower()
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        assert len((await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]) == 1

    asyncio.run(run())


@pytest.mark.parametrize("status", ["sent", "failed", "uncertain", "skipped"])
def test_any_existing_delivery_record_excludes_catchup(runtime, status):
    async def run():
        await persist_due(runtime, minutes=1)
        await campaign.record_delivery(runtime.mongo, GUILD, CYCLE, {
            "occurrence_id": campaign.occurrence_id(CYCLE, "signup", "main"),
            "message_key": "signup", "variant": "main", "status": status,
        })
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert len(loaded["deliveries"]) == 1

    asyncio.run(run())


def test_no_occurrence_is_derived_without_a_persisted_job(runtime):
    async def run():
        runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 20, "hour": 11, "minute": 59,
        }
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        assert not (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]

    asyncio.run(run())


def test_post_accepted_then_crash_never_replays_after_claim_expiry(runtime):
    async def run():
        await persist_due(runtime, minutes=1)
        create = runtime.rest.create_message
        async def crash_after_accept(*args, **kwargs):
            await create(*args, **kwargs)
            raise asyncio.CancelledError("Fixture process dies after POST acceptance")
        runtime.rest.create_message = crash_after_accept
        await native._reconcile_cwl_startup()
        with pytest.raises(asyncio.CancelledError):
            await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        oid = campaign.occurrence_id(CYCLE, "signup", "main")
        assert oid in (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["uncertain_occurrences"]
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        deliveries = (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]
        assert len(deliveries) == 1 and deliveries[0]["status"] == "uncertain"

    asyncio.run(run())


def test_new_protocol_pre_post_crash_can_resume_without_guessing_an_old_claim(runtime):
    async def run():
        await persist_due(runtime, minutes=1)
        fetch = runtime.rest.fetch_channel
        async def crash_before_post(_channel):
            raise asyncio.CancelledError("Fixture process dies before POST boundary")
        runtime.rest.fetch_channel = crash_before_post
        await native._reconcile_cwl_startup()
        with pytest.raises(asyncio.CancelledError):
            await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        runtime.rest.fetch_channel = fetch
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1

    asyncio.run(run())


def test_legacy_claim_without_a_receipt_fails_closed_instead_of_guessing(runtime):
    async def run():
        await persist_due(runtime, minutes=1)
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert await native._claim_campaign_occurrence(
            GUILD, CYCLE, campaign.occurrence_id(CYCLE, "signup", "main"),
            native._campaign_generation(loaded),
        )
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        assert (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"][0]["status"] == "uncertain"

    asyncio.run(run())


def test_second_restart_uses_original_due_time_not_the_first_recovery_time(runtime):
    async def run():
        _, original, _ = await persist_due(runtime, minutes=359)
        await native._reconcile_cwl_startup()
        job_id = native._campaign_job_id(GUILD, CYCLE, "signup", "main")
        assert runtime.mongo.cwl_pending_reminders.documents[job_id]["catchup"]["original_due_at"] == original.isoformat()
        runtime.clock[0] = runtime.clock[0].add(minutes=2)
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        assert "too late" in (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"][0]["reason"].lower()

    asyncio.run(run())


@pytest.mark.parametrize("job_kind", ["manual", "retry"])
def test_manual_and_retry_rows_keep_existing_behavior(runtime, job_kind):
    async def run():
        job_id, due, loaded = await persist_due(runtime, minutes=420)
        await native._persist_campaign_job(
            job_id, due, GUILD, CYCLE, "signup", ["main"], native._campaign_generation(loaded),
            job_kind=job_kind, failure_count=1 if job_kind == "retry" else 0,
        )
        await native._reconcile_cwl_startup()
        assert not runtime.mongo.cwl_pending_reminders.documents[job_id].get("catchup")
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        assert not (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"][0].get("late")

    asyncio.run(run())


@pytest.mark.parametrize("pools", [["main"], ["main", "lazy"]])
def test_only_newest_overdue_is_sent_per_pool_and_older_is_recorded(runtime, pools):
    async def run():
        config = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]
        for key, minutes in [("signup", 10), ("reminder:1", 1)]:
            due = runtime.clock[0].subtract(minutes=minutes)
            message = config["messages"][key]
            message["enabled"] = True
            message["schedule"] = {"mode": "monthly", "day": due.day, "hour": due.hour, "minute": due.minute}
            for variant in campaign.AUDIENCES:
                message["variants"][variant]["enabled"] = variant in pools
                message["variants"][variant]["destination_channel_id"] = 300 if variant == "main" else 301
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        for key, minutes in [("signup", 10), ("reminder:1", 1)]:
            for variant in pools:
                await native._persist_campaign_job(
                    native._campaign_job_id(GUILD, CYCLE, key, variant),
                    runtime.clock[0].subtract(minutes=minutes), GUILD, CYCLE, key,
                    [variant], native._campaign_generation(loaded),
                )
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == len(pools)
        entries = (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]
        assert {item["message_key"] for item in entries if item["status"] == "sent"} == {"reminder:1"}
        assert len([item for item in entries if item["status"] == "skipped"]) == len(pools)
        assert all(item.get("late") for item in entries)

    asyncio.run(run())


def test_existing_sequence_spacing_guard_is_not_overridden(runtime):
    from utils import cwl_sequence

    async def run():
        config = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]
        config["messages"]["signup"]["schedule"] = {"mode": "monthly", "day": 19, "hour": 11, "minute": 59}
        config["messages"]["reminder:1"]["enabled"] = True
        config["messages"]["reminder:1"]["variants"]["lazy"]["enabled"] = False
        config["signup_deadline"] = {"day": 21, "hour": 13, "minute": 0}
        configured = cwl_sequence.configure(config, "interval", interval_hours=24, min_gap_hours=3, final_hours=3)
        runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"] = configured
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        due = next(pendulum.parse(row["run_at"]) for row in loaded["schedule"] if row["message_id"] == "reminder:1" and row["variant"] == "main")
        await native._persist_campaign_job(
            native._campaign_job_id(GUILD, CYCLE, "reminder:1", "main"), due,
            GUILD, CYCLE, "reminder:1", ["main"], native._campaign_generation(loaded),
        )
        await campaign.record_delivery(runtime.mongo, GUILD, CYCLE, {
            "occurrence_id": campaign.occurrence_id(CYCLE, "signup", "main"),
            "message_key": "signup", "variant": "main", "status": "sent",
            "at": runtime.clock[0].subtract(minutes=30).isoformat(),
        })
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        entries = (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]
        assert entries[-1]["reason"] == "Skipped: too close to another send"

    asyncio.run(run())


def test_catchup_skip_does_not_disable_a_new_future_ordinary_schedule(runtime):
    async def run():
        await persist_due(runtime, minutes=361)
        await native._reconcile_cwl_startup()
        defaults = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]
        defaults["revision"] += 1
        defaults["campaign"]["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 20, "hour": 12, "minute": 10,
        }
        await native.sync_campaign_schedule(GUILD, CYCLE)
        runtime.clock[0] = runtime.clock[0].add(minutes=10)
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        entries = (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"]
        assert entries[-1]["status"] == "sent" and not entries[-1].get("late")

    asyncio.run(run())


def test_catchup_receipt_write_failure_recovers_late_metadata_without_resend(runtime, monkeypatch):
    async def run():
        await persist_due(runtime, minutes=1)
        original = campaign.record_catchup_delivery
        calls = 0
        async def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Fixture receipt persistence interrupted")
            return await original(*args, **kwargs)
        monkeypatch.setattr(campaign, "record_catchup_delivery", fail_once)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        job_id = native._campaign_job_id(GUILD, CYCLE, "signup", "main")
        assert runtime.mongo.cwl_pending_reminders.documents[job_id]["status"] == "ledger_pending"
        confirmed_at = runtime.mongo.cwl_pending_reminders.documents[job_id]["receipt"]["at"]
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert loaded["deliveries"][0]["status"] == "sent" and loaded["deliveries"][0]["late"]
        assert loaded["deliveries"][0]["at"] == confirmed_at
        assert not loaded["uncertain_occurrences"]

    asyncio.run(run())


def test_window_and_settings_are_revalidated_after_transport_preparation(runtime):
    async def run():
        await persist_due(runtime, minutes=359)
        fetch = runtime.rest.fetch_channel
        async def slow_prepare(channel):
            runtime.clock[0] = runtime.clock[0].add(minutes=2)
            return await fetch(channel)
        runtime.rest.fetch_channel = slow_prepare
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        assert "too late" in (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["deliveries"][0]["reason"].lower()

    asyncio.run(run())


def test_idle_future_ack_does_not_fetch_catchup_state(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from utils import cwl_web_bridge as bridge

    async def run():
        await persist_due(runtime, minutes=1)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        async def reconcile():
            return await bridge.reconcile_campaign_changes(
                runtime.mongo, native._sync_all_campaigns, guild_id=GUILD,
                loaded_generations=lambda: native._loaded_campaign_generations(GUILD),
                runtime_id=native._campaign_runtime_id,
            )
        await reconcile()
        state = AsyncMock(side_effect=AssertionError("Idle reconciliation must not scan catch-up state"))
        monkeypatch.setattr(campaign, "catchup_state", state)
        assert not await reconcile()
        state.assert_not_awaited()

    asyncio.run(run())


def test_bson_snowflake_guild_roundtrip_is_not_rejected_as_invalid(runtime):
    from bson import BSON

    async def run():
        guild_id = 644963518025826319  # Fictional, snowflake-sized local fixture.
        document = runtime.mongo.bot_config.documents.pop(campaign.defaults_id(GUILD))
        document.update(_id=campaign.defaults_id(guild_id), guild_id=guild_id)
        document["campaign"]["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 20, "hour": 11, "minute": 59,
        }
        runtime.mongo.bot_config.documents[document["_id"]] = BSON.encode(document).decode()
        runtime.rest.guild_id = guild_id
        loaded = await campaign.load_campaign(runtime.mongo, guild_id, CYCLE)
        job_id = native._campaign_job_id(guild_id, CYCLE, "signup", "main")
        await native._persist_campaign_job(
            job_id, runtime.clock[0].subtract(minutes=1), guild_id, CYCLE,
            "signup", ["main"], native._campaign_generation(loaded),
        )
        row = runtime.mongo.cwl_pending_reminders.documents[job_id]
        runtime.mongo.cwl_pending_reminders.documents[job_id] = BSON.encode(row).decode()
        assert isinstance(runtime.mongo.cwl_pending_reminders.documents[job_id]["guild_id"], int)
        await native._reconcile_cwl_startup()
        runtime.clock[0] = runtime.clock[0].add(seconds=6)
        job = runtime.scheduler.get_job(job_id)
        if job:
            await job.function(*job.args, **(getattr(job, "kwargs", None) or {}))
        assert len(runtime.rest.sent) == 1

    asyncio.run(run())


@pytest.mark.parametrize("extra_microseconds, expected_sends", [(0, 1), (1, 0)])
def test_six_hour_boundary_is_inclusive_at_dispatch(runtime, extra_microseconds, expected_sends):
    async def run():
        job_id, _, _ = await persist_due(runtime, minutes=360)
        await native._reconcile_cwl_startup()
        job = runtime.scheduler.get_job(job_id)
        assert job is not None
        runtime.clock[0] = runtime.clock[0].add(microseconds=extra_microseconds)
        await job.function(*job.args, **(getattr(job, "kwargs", None) or {}))
        assert len(runtime.rest.sent) == expected_sends
        if not expected_sends:
            loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
            assert any("too late" in item.get("reason", "").lower() for item in loaded["deliveries"])

    asyncio.run(run())


@pytest.mark.parametrize("claim", [{}, None, "malformed"])
def test_existing_malformed_claim_fails_closed(runtime, claim):
    async def run():
        await persist_due(runtime, minutes=1)
        oid = campaign.occurrence_id(CYCLE, "signup", "main")
        runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
            "_id": campaign.cycle_id(GUILD, CYCLE),
            "delivery_claims": {oid: claim},
        }
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert any(item.get("status") == "uncertain" for item in loaded["deliveries"])

    asyncio.run(run())


def test_lost_attempt_ack_never_enters_sender_or_replays(runtime, monkeypatch):
    async def run():
        await persist_due(runtime, minutes=1)
        original = campaign.begin_catchup_attempt
        async def applied_then_lost(*args, **kwargs):
            assert await original(*args, **kwargs)
            raise OSError("Fixture lost database acknowledgement")
        monkeypatch.setattr(campaign, "begin_catchup_attempt", applied_then_lost)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert runtime.rest.sent == []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert len(loaded["deliveries"]) == 1
        assert loaded["deliveries"][0]["status"] == "uncertain"

    asyncio.run(run())


def test_lost_confirmed_receipt_ack_recovers_without_duplicate_history(runtime, monkeypatch):
    async def run():
        await persist_due(runtime, minutes=1)
        original = campaign.record_catchup_delivery
        async def applied_then_lost(*args, **kwargs):
            await original(*args, **kwargs)
            raise OSError("Fixture lost receipt acknowledgement")
        monkeypatch.setattr(campaign, "record_catchup_delivery", applied_then_lost)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        monkeypatch.setattr(campaign, "record_catchup_delivery", original)
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert len(runtime.rest.sent) == 1
        assert len(loaded["deliveries"]) == 1
        assert loaded["deliveries"][0]["status"] == "sent"
        assert not loaded["uncertain_occurrences"]

    asyncio.run(run())


def test_accepted_result_without_message_id_is_uncertain_and_not_replayed(runtime):
    async def run():
        await persist_due(runtime, minutes=1)
        original = runtime.rest.create_message
        async def accepted_without_id(*args, **kwargs):
            await original(*args, **kwargs)
            return SimpleNamespace(id=None)
        runtime.rest.create_message = accepted_without_id
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        runtime.clock[0] = runtime.clock[0].add(minutes=16)
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(runtime.rest.sent) == 1
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert loaded["deliveries"][0]["status"] == "uncertain"

    asyncio.run(run())


@pytest.mark.parametrize("guild_id", [True, "22", 22.0, 0, -1])
def test_storage_scope_rejects_non_native_guild_identifiers(guild_id):
    with pytest.raises(ValueError, match="scope"):
        campaign._catchup_scope(guild_id, CYCLE, campaign.occurrence_id(CYCLE, "signup", "main"))


@pytest.mark.parametrize("changes", [
    {"message_id": "roster"}, {"variants": ["main", "lazy"]},
    {"variants": ["outside"]}, {"kind": "other"}, {"job_kind": "manual"},
    {"status": "ledger_pending"}, {"failure_count": True}, {"failure_count": 1},
    {"_id": "someone-else"},
    {"job_kind": "catchup", "catchup": {"protocol": True, "original_due_at": "2026-11-20T11:00:00-05:00"}},
])
def test_storage_refuses_forged_or_non_scheduled_pending_rows(runtime, changes):
    async def run():
        job_id, _, _ = await persist_due(runtime, minutes=1)
        row = deepcopy(runtime.mongo.cwl_pending_reminders.documents[job_id])
        row.update(changes)
        with pytest.raises(ValueError):
            campaign._catchup_row_scope(row)
        assert runtime.rest.sent == []

    asyncio.run(run())
