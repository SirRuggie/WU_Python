import asyncio

import pendulum
import pytest

from extensions.tasks import cwl_reminder
from tests.test_cwl_dashboard_integration import (
    MemoryMongo,
    StrictCampaignRest,
    install_runtime,
)
from utils import cwl_campaign, cwl_sequence


TZ = "America/New_York"
GUILD_ID = 22
USER_ID = 11


def run(coroutine):
    return asyncio.run(coroutine)


async def saved_sequence(
    monkeypatch, *, opening, deadline, count=1,
    mode="evenly", interval_hours=48,
):
    mongo = MemoryMongo()
    cycle = opening.in_timezone(TZ).format("YYYY-MM")
    campaign = cwl_sequence.configure(
        cwl_campaign.default_campaign(),
        mode=mode,
        count=count,
        interval_hours=interval_hours,
        final_hours=1,
        min_gap_hours=1,
    )
    campaign["messages"]["signup"]["schedule"] = {
        "mode": "specific", "at": opening.isoformat(),
    }
    campaign["signup_deadline"] = {"at": deadline.isoformat()}
    cwl_campaign.validate_campaign(campaign)
    mongo.bot_config.documents[cwl_campaign.cycle_id(GUILD_ID, cycle)] = {
        "_id": cwl_campaign.cycle_id(GUILD_ID, cycle),
        "kind": "cwl_campaign_cycle",
        "guild_id": GUILD_ID,
        "cycle": cycle,
        "campaign": campaign,
        "revision": 1,
        "activated": True,
    }
    loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
    scheduler, rest = install_runtime(
        monkeypatch, mongo, rest=StrictCampaignRest(guild_id=GUILD_ID)
    )
    return mongo, scheduler, rest, loaded


def test_cutoff_is_inclusive_and_unused_slots_are_blocked(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        _mongo, _scheduler, _rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.add(days=1), count=1
        )
        deadline = pendulum.parse(loaded["deadline"])

        assert cwl_reminder._sequence_delivery_blocked(
            loaded, "reminder:1", deadline.subtract(microseconds=1)
        ) is False
        assert cwl_reminder._sequence_delivery_blocked(
            loaded, "reminder:1", deadline
        ) is True
        assert cwl_reminder._sequence_delivery_blocked(
            loaded, "reminder:2", now
        ) is True
        assert cwl_reminder._sequence_delivery_blocked(
            loaded, "signup", deadline.add(days=1)
        ) is False
        assert cwl_reminder._sequence_delivery_blocked(
            loaded, "roster", deadline.add(days=1)
        ) is False

    run(scenario())


def test_sender_drops_expired_pending_job_before_claim_or_rest(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        mongo, scheduler, rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.subtract(minutes=1)
        )
        generation = cwl_reminder._campaign_generation(loaded)
        job_id = cwl_reminder._campaign_job_id(
            GUILD_ID, loaded["cycle"], "reminder:1", "main"
        )
        await cwl_reminder._persist_campaign_job(
            job_id, now, GUILD_ID, loaded["cycle"], "reminder:1", ["main"],
            generation, job_kind="retry",
        )
        cwl_reminder._add_campaign_job(
            job_id, now, GUILD_ID, loaded["cycle"], "reminder:1", ["main"],
            generation,
        )

        assert await cwl_reminder.send_campaign_message(
            GUILD_ID, loaded["cycle"], "reminder:1", ["main"], generation
        ) is False
        assert rest.sent == []
        assert job_id not in scheduler.jobs
        assert job_id not in mongo.cwl_pending_reminders.documents
        row = await mongo.bot_config.find_one(
            {"_id": cwl_campaign.cycle_id(GUILD_ID, loaded["cycle"])}
        )
        assert not row.get("delivery_claims")

    run(scenario())


def test_manual_and_admin_retry_reject_expired_or_unused_sequence_slot(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        mongo, scheduler, _rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.subtract(minutes=1)
        )
        with pytest.raises(ValueError, match="no longer scheduled|closed"):
            await cwl_reminder.queue_manual_campaign_occurrence(
                GUILD_ID, loaded["cycle"], "reminder:1", ["main"]
            )
        with pytest.raises(ValueError, match="no longer scheduled|closed"):
            await cwl_reminder.queue_campaign_retry(
                GUILD_ID, loaded["cycle"],
                cwl_campaign.occurrence_id(loaded["cycle"], "reminder:1", "main"),
            )
        assert scheduler.jobs.get(cwl_reminder.CAMPAIGN_ROLLOVER_JOB_ID) is None
        assert mongo.cwl_pending_reminders.documents == {}

        mongo, scheduler, _rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.add(days=1), count=1
        )
        with pytest.raises(ValueError, match="no longer scheduled|closed"):
            await cwl_reminder.queue_manual_campaign_occurrence(
                GUILD_ID, loaded["cycle"], "reminder:2", ["main"]
            )
        with pytest.raises(ValueError, match="no longer scheduled|closed"):
            await cwl_reminder.queue_campaign_retry(
                GUILD_ID, loaded["cycle"],
                cwl_campaign.occurrence_id(loaded["cycle"], "reminder:2", "main"),
            )
        assert mongo.cwl_pending_reminders.documents == {}
        assert not scheduler.jobs

    run(scenario())


def test_restore_and_sync_drop_expired_jobs_but_recover_confirmed_receipt(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        mongo, scheduler, rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.subtract(minutes=1)
        )
        generation = cwl_reminder._campaign_generation(loaded)
        retry_id = cwl_reminder._campaign_job_id(
            GUILD_ID, loaded["cycle"], "reminder:1", "main"
        )
        await cwl_reminder._persist_campaign_job(
            retry_id, now.subtract(minutes=5), GUILD_ID, loaded["cycle"],
            "reminder:1", ["main"], generation, job_kind="retry",
        )

        receipt_id = cwl_reminder._campaign_job_id(
            GUILD_ID, loaded["cycle"], "reminder:1", "lazy"
        )
        occurrence = cwl_campaign.occurrence_id(
            loaded["cycle"], "reminder:1", "lazy"
        )
        await cwl_reminder._persist_campaign_job(
            receipt_id, now.subtract(minutes=5), GUILD_ID, loaded["cycle"],
            "reminder:1", ["lazy"], generation,
        )
        await mongo.cwl_pending_reminders.update_one(
            {"_id": receipt_id},
            {"$set": {"status": "ledger_pending", "receipt": {
                "occurrence_id": occurrence,
                "message_key": "reminder:1",
                "variant": "lazy",
                "status": "sent",
                "channel_id": 100,
                "message_id": 200,
                "revision": generation,
            }}},
        )

        await cwl_reminder.restore_pending_reminders()
        assert retry_id not in scheduler.jobs
        assert retry_id not in mongo.cwl_pending_reminders.documents
        assert receipt_id not in mongo.cwl_pending_reminders.documents
        assert rest.sent == []
        recovered = await cwl_campaign.load_campaign(
            mongo, GUILD_ID, loaded["cycle"]
        )
        assert occurrence in recovered["sent_occurrences"]

        # Reconciliation must not resurrect a manually queued expired job.
        await cwl_reminder._persist_campaign_job(
            retry_id, now.add(minutes=5), GUILD_ID, loaded["cycle"],
            "reminder:1", ["main"], generation, job_kind="manual",
        )
        cwl_reminder._add_campaign_job(
            retry_id, now.add(minutes=5), GUILD_ID, loaded["cycle"],
            "reminder:1", ["main"], generation,
        )
        await cwl_reminder.sync_campaign_schedule(GUILD_ID, loaded["cycle"])
        assert retry_id not in scheduler.jobs
        assert retry_id not in mongo.cwl_pending_reminders.documents

    run(scenario())


def test_automatic_retry_is_not_queued_past_deadline(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        mongo, scheduler, _rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(days=2), deadline=now.add(minutes=4)
        )
        generation = cwl_reminder._campaign_generation(loaded)
        job_id = cwl_reminder._campaign_job_id(
            GUILD_ID, loaded["cycle"], "reminder:1", "main"
        )
        await cwl_reminder._schedule_campaign_retry(
            GUILD_ID, loaded["cycle"], "reminder:1", ["main"], generation,
            [("main", RuntimeError("temporary"))],
        )

        assert job_id not in scheduler.jobs
        assert job_id not in mongo.cwl_pending_reminders.documents
        result = await cwl_campaign.load_campaign(mongo, GUILD_ID, loaded["cycle"])
        assert any(
            row.get("occurrence_id") == cwl_campaign.occurrence_id(
                loaded["cycle"], "reminder:1", "main"
            )
            and row.get("status") == "skipped"
            for row in result["deliveries"]
        )

    run(scenario())


def test_spacing_tolerance_allows_normal_latency_but_blocks_catchup(monkeypatch):
    async def scenario():
        now = pendulum.now(TZ)
        _mongo, _scheduler, _rest, loaded = await saved_sequence(
            monkeypatch, opening=now.subtract(hours=1),
            deadline=now.add(hours=7), mode="interval", interval_hours=1,
        )
        rows = {
            row["message_id"]: pendulum.parse(row["run_at"])
            for row in loaded["schedule"]
            if row["variant"] == "main" and row["message_id"].startswith("reminder:")
        }
        current = rows["reminder:1"]

        assert cwl_reminder._sequence_spacing_blocked(
            loaded, "reminder:1", "main", current.add(seconds=30)
        ) is False
        # Once enough time has elapsed that the next planned reminder would
        # violate the one-minute-tolerant minimum gap, skip this overdue one.
        assert cwl_reminder._sequence_spacing_blocked(
            loaded, "reminder:1", "main", current.add(seconds=61)
        ) is True

    run(scenario())
