import asyncio

from extensions.tasks import cwl_reminder
from tests.test_cwl_dashboard_integration import (
    MemoryMongo,
    MemoryScheduler,
    install_runtime,
)
from utils import cwl_campaign, cwl_sequence


def _run(coro):
    return asyncio.run(coro)


def _times(schedule, *message_ids):
    wanted = set(message_ids)
    return {
        item["message_id"]: item["run_at"]
        for item in schedule
        if item["message_id"] in wanted and item["variant"] == "main"
    }


def test_signup_date_edit_reanchors_sequence_after_signup_post_was_sent(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)

        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        campaign = cwl_sequence.configure(
            draft["campaign"], "evenly", count=3, final_hours=3,
            min_gap_hours=3,
        )
        original_main_title = campaign["messages"]["signup"]["variants"]["main"]["title"]
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        # The post receipt describes what Discord received.  It must protect
        # that audience's content, but its actual send time is not the event
        # start used to calculate later reminders.
        await cwl_campaign.record_delivery(mongo, 22, "2026-10", {
            "occurrence_id": "2026-10|signup|main",
            "status": "sent",
            "at": "2026-10-21T03:05:00+00:00",
        })

        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        campaign = draft["campaign"]
        campaign["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 22, "hour": 17, "minute": 0,
        }
        campaign["messages"]["signup"]["variants"]["main"]["title"] = "Do not replace the delivered post"
        campaign["messages"]["signup"]["variants"]["lazy"]["title"] = "Lazy audience remains editable"
        preview = _times(
            cwl_campaign.resolve_schedule(campaign, "2026-10"),
            "signup", "reminder:1", "reminder:2", "reminder:3",
        )
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        applied = await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        assert applied["campaign"]["messages"]["signup"]["schedule"]["day"] == 22
        assert _times(
            applied["schedule"], "signup", "reminder:1", "reminder:2", "reminder:3",
        ) == preview == {
            "signup": "2026-10-22T17:00:00-04:00",
            "reminder:1": "2026-10-25T00:00:00-04:00",
            "reminder:2": "2026-10-27T07:00:00-04:00",
            "reminder:3": "2026-10-29T14:00:00-04:00",
        }
        signup = applied["campaign"]["messages"]["signup"]["variants"]
        assert signup["main"]["title"] == original_main_title
        assert signup["lazy"]["title"] == "Lazy audience remains editable"
        assert applied["protected_sent"] == ["2026-10|signup|main"]

    _run(scenario())


def test_signup_anchor_precedence_is_cycle_then_defaults_then_legacy():
    async def scenario():
        guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 24, "hour": 7, "minute": 0,
            "followups": [],
        })

        legacy = await cwl_campaign.load_campaign(mongo, guild_id, "2026-09")
        assert _times(legacy["schedule"], "signup")["signup"] == "2026-09-24T07:00:00-04:00"

        defaults = cwl_campaign.default_campaign()
        defaults["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 23, "hour": 8, "minute": 15,
        }
        await mongo.bot_config.update_one(
            {"_id": cwl_campaign.defaults_id(guild_id)},
            {"$set": {"revision": 1, "campaign": defaults}},
            upsert=True,
        )
        inherited = await cwl_campaign.load_campaign(mongo, guild_id, "2026-09")
        assert _times(inherited["schedule"], "signup")["signup"] == "2026-09-23T08:15:00-04:00"

        cycle = cwl_campaign.default_campaign()
        cycle["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 22, "hour": 22, "minute": 10,
        }
        await mongo.bot_config.update_one(
            {"_id": cwl_campaign.cycle_id(guild_id, "2026-09")},
            {"$set": {
                "revision": 1, "guild_id": guild_id, "cycle": "2026-09",
                "campaign": cycle,
            }},
            upsert=True,
        )
        selected = await cwl_campaign.load_campaign(mongo, guild_id, "2026-09")
        assert _times(selected["schedule"], "signup")["signup"] == "2026-09-22T22:10:00-04:00"

    _run(scenario())


def test_unapplied_draft_has_its_own_schedule_while_live_stays_legacy():
    async def scenario():
        guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 24, "hour": 7, "minute": 0,
            "followups": [],
        })
        draft = await cwl_campaign.new_draft(mongo, guild_id, 11, cycle="2026-09")
        campaign = cwl_sequence.configure(
            draft["campaign"], "evenly", count=2, final_hours=3,
            min_gap_hours=3,
        )
        campaign["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 22, "hour": 22, "minute": 10,
        }
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})

        saved_draft = await cwl_campaign.load_draft(mongo, draft["token"])
        draft_times = _times(
            cwl_campaign.resolve_schedule(saved_draft["campaign"], saved_draft["cycle"]),
            "signup", "reminder:1", "reminder:2",
        )
        live = await cwl_campaign.load_campaign(mongo, guild_id, "2026-09")

        assert draft_times == {
            "signup": "2026-09-22T22:10:00-04:00",
            "reminder:1": "2026-09-25T18:05:00-04:00",
            "reminder:2": "2026-09-28T14:00:00-04:00",
        }
        assert _times(live["schedule"], "signup")["signup"] == "2026-09-24T07:00:00-04:00"

    _run(scenario())


def test_editing_message_schedule_retires_its_transitional_override(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        campaign = cwl_campaign.default_campaign()
        campaign["schedules"] = {
            "signup": {"mode": "monthly", "day": 24, "hour": 7, "minute": 0},
        }
        await mongo.bot_config.update_one(
            {"_id": cwl_campaign.defaults_id(22)},
            {"$set": {"revision": 1, "campaign": campaign}},
            upsert=True,
        )

        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-09")
        assert _times(
            cwl_campaign.resolve_schedule(draft["campaign"], draft["cycle"]), "signup",
        )["signup"] == "2026-09-24T07:00:00-04:00"

        edited = draft["campaign"]
        edited["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 22, "hour": 22, "minute": 10,
        }
        saved = await cwl_campaign.patch_draft(
            mongo, draft["token"], {"campaign": edited},
        )
        assert "signup" not in saved["campaign"].get("schedules", {})
        assert _times(
            cwl_campaign.resolve_schedule(saved["campaign"], saved["cycle"]), "signup",
        )["signup"] == "2026-09-22T22:10:00-04:00"

        applied = await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        assert _times(applied["schedule"], "signup")["signup"] == "2026-09-22T22:10:00-04:00"

    _run(scenario())


def test_reanchor_sync_and_restart_never_requeue_sent_signup(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        campaign = cwl_sequence.configure(
            draft["campaign"], "evenly", count=3, final_hours=3,
            min_gap_hours=3,
        )
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        for variant in cwl_campaign.AUDIENCES:
            await cwl_campaign.record_delivery(mongo, 22, "2030-10", {
                "occurrence_id": f"2030-10|signup|{variant}",
                "status": "sent",
            })

        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        campaign = draft["campaign"]
        campaign["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 22, "hour": 17, "minute": 0,
        }
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        scheduler, _ = install_runtime(monkeypatch, mongo)
        applied = await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        expected_times = {
            "reminder:1": "2030-10-25T00:00:00-04:00",
            "reminder:2": "2030-10-27T07:00:00-04:00",
            "reminder:3": "2030-10-29T14:00:00-04:00",
        }
        assert _times(
            applied["schedule"], "reminder:1", "reminder:2", "reminder:3",
        ) == expected_times
        pending = await mongo.cwl_pending_reminders.find({
            "kind": "campaign", "guild_id": 22, "cycle": "2030-10",
        }).to_list(length=None)
        assert pending
        assert {row["message_id"] for row in pending} == set(expected_times)
        assert {
            row["message_id"]: row["run_time"] for row in pending
            if row["variants"] == ["main"]
        } == expected_times
        assert not any(":signup:" in job_id for job_id in scheduler.jobs)

        # Startup rebuilds the in-memory scheduler from the same durable rows.
        # The sent-occurrence ledger must continue to suppress both signup
        # audiences while retaining the newly anchored reminder dates.
        restarted = MemoryScheduler()
        monkeypatch.setattr(cwl_reminder, "scheduler", restarted)
        await cwl_reminder.restore_pending_reminders()
        assert not any(":signup:" in job_id for job_id in restarted.jobs)
        restored_campaign_jobs = {
            job_id for job_id in restarted.jobs
            if job_id.startswith(cwl_reminder.CAMPAIGN_JOB_PREFIX)
        }
        assert len(restored_campaign_jobs) == 6
        assert all(any(f":{message_id}:" in job_id for message_id in expected_times)
                   for job_id in restored_campaign_jobs)

    _run(scenario())
