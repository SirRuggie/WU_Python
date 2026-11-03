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
            await job.function(*job.args)


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
