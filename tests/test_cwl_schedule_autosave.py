"""Runtime-backed checks for timing forms that activate CWL immediately.

These cover the dashboard boundary only: MemoryMongo and the in-memory
scheduler stand in for persistence and scheduling, and no Discord post is sent.
"""

import asyncio

import pendulum

from extensions.commands import cwl_dashboard as dashboard
from extensions.tasks import cwl_reminder
from tests.test_cwl_dashboard_integration import MemoryMongo, install_runtime, modal_context
from utils import cwl_campaign, cwl_sequence


def _run(coroutine):
    return asyncio.run(coroutine)


def _planned(schedule):
    """One planned time per message, shared by Main and Lazy audiences."""
    result = {}
    for item in schedule:
        if item.get("run_at"):
            result.setdefault(item["message_id"], item["run_at"])
    return result


def _rendered_notice(context):
    components = context.interaction.edit_initial_response.await_args.kwargs["components"]
    return str(components[0].build()[0])


async def _sequence_draft(mongo, *, cycle, opening, closing):
    draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle=cycle)
    campaign = cwl_sequence.configure(
        draft["campaign"], "evenly", count=2, final_hours=3, min_gap_hours=3,
    )
    campaign["signup_deadline"] = {"at": closing.format("YYYY-MM-DD[T]HH:mm:ss")}
    return await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})


def test_future_signup_timing_autosaves_live_campaign_reanchors_reminders_and_jobs(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        scheduler, rest = install_runtime(monkeypatch, mongo)
        now = pendulum.now("America/New_York").replace(second=0, microsecond=0)
        opening = now.add(days=2)
        closing = now.add(days=10)
        cycle = cwl_campaign.cycle_key(timezone_name="America/New_York")
        draft = await _sequence_draft(mongo, cycle=cycle, opening=opening, closing=closing)

        context = modal_context(values={
            "date": opening.format("YYYY-MM-DD"), "time": opening.format("HH:mm"),
        })
        await dashboard.submit_schedule(
            context, f"{draft['token']}|signup|specific", mongo=mongo,
        )

        live_after_open = await cwl_campaign.load_campaign(mongo, 22, cycle)
        # The retained token must also drive the next timing form. Changing the
        # closing rule applies immediately and reanchors automatic reminders.
        revised_closing = closing.add(days=2)
        closing_context = modal_context(values={
            "date": revised_closing.format("YYYY-MM-DD"), "time": revised_closing.format("HH:mm"),
            "timezone": "America/New_York",
        })
        await dashboard.submit_settings(
            closing_context, f"{draft['token']}|specific", mongo=mongo,
        )

        live = await cwl_campaign.load_campaign(mongo, 22, cycle)
        saved = await cwl_campaign.load_draft(mongo, draft["token"])
        expected = _planned(cwl_campaign.resolve_schedule(saved["campaign"], cycle))
        assert live["campaign"]["messages"]["signup"]["schedule"]["at"] == opening.format("YYYY-MM-DD[T]HH:mm:00")
        assert live["campaign"]["signup_deadline"]["at"] == revised_closing.format("YYYY-MM-DD[T]HH:mm:00")
        assert _planned(live["schedule"]) == expected
        assert _planned(live_after_open["schedule"])["reminder:1"] != expected["reminder:1"]
        assert set(expected) >= {"signup", "reminder:1", "reminder:2"}
        assert saved["token"] == draft["token"]
        assert saved["base_revision"] == live["revision"]

        pending = await mongo.cwl_pending_reminders.find({
            "kind": "campaign", "guild_id": 22, "cycle": cycle,
        }).to_list(length=None)
        assert {row["message_id"] for row in pending} == set(expected)
        assert {row["message_id"]: row["run_time"] for row in pending} == expected
        assert len([job_id for job_id in scheduler.jobs if job_id.startswith(f"{cwl_reminder.CAMPAIGN_JOB_PREFIX}22:{cycle}:")]) == len(pending)
        assert {
            (row["message_id"], tuple(row["variants"])) for row in pending
        } == {(message_id, (variant,)) for message_id in expected for variant in cwl_campaign.AUDIENCES}
        assert "Scheduled." in _rendered_notice(context)
        assert "Scheduled." in _rendered_notice(closing_context)

        # Scheduled Main/Lazy jobs use the same fake REST surface as runtime.
        # A second invocation of the retained job cannot create a duplicate.
        for variant in cwl_campaign.AUDIENCES:
            job_id = cwl_reminder._campaign_job_id(22, cycle, "signup", variant)
            job = scheduler.jobs[job_id]
            assert await job.function(*job.args) is True
            assert await job.function(*job.args) is False
        assert len(rest.sent) == len(cwl_campaign.AUDIENCES)
        delivered = await cwl_campaign.load_campaign(mongo, 22, cycle)
        expected_receipts = {
            cwl_campaign.occurrence_id(cycle, "signup", variant)
            for variant in cwl_campaign.AUDIENCES
        }
        assert expected_receipts <= set(delivered["sent_occurrences"])
        assert {
            row["occurrence_id"] for row in delivered["deliveries"] if row.get("status") == "sent"
        } >= expected_receipts

    _run(scenario())


def test_invalid_closing_stays_in_draft_with_not_scheduled_notice_and_live_plan_unchanged(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        install_runtime(monkeypatch, mongo)
        now = pendulum.now("America/New_York").replace(second=0, microsecond=0)
        opening, closing = now.add(days=2), now.add(days=10)
        cycle = cwl_campaign.cycle_key(timezone_name="America/New_York")
        draft = await _sequence_draft(mongo, cycle=cycle, opening=opening, closing=closing)
        await dashboard.submit_schedule(
            modal_context(values={"date": opening.format("YYYY-MM-DD"), "time": opening.format("HH:mm")}),
            f"{draft['token']}|signup|specific", mongo=mongo,
        )
        before = await cwl_campaign.load_campaign(mongo, 22, cycle)

        invalid_close = opening.subtract(hours=1)
        context = modal_context(values={
            "date": invalid_close.format("YYYY-MM-DD"), "time": invalid_close.format("HH:mm"),
            "timezone": "America/New_York",
        })
        await dashboard.submit_settings(context, f"{draft['token']}|specific", mongo=mongo)

        saved = await cwl_campaign.load_draft(mongo, draft["token"])
        after = await cwl_campaign.load_campaign(mongo, 22, cycle)
        assert saved["campaign"]["signup_deadline"]["at"] == invalid_close.format("YYYY-MM-DD[T]HH:mm:00")
        assert after["campaign"] == before["campaign"]
        assert _planned(after["schedule"]) == _planned(before["schedule"])
        assert "NOT SCHEDULED:" in _rendered_notice(context)
        assert "Previous schedule kept" in _rendered_notice(context)

    _run(scenario())


def test_past_unsent_signup_timing_is_kept_as_draft_but_refuses_activation(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        scheduler, _rest = install_runtime(monkeypatch, mongo)
        now = pendulum.now("America/New_York").replace(second=0, microsecond=0)
        opening, closing = now.subtract(days=1), now.add(days=5)
        cycle = cwl_campaign.cycle_key(timezone_name="America/New_York")
        draft = await _sequence_draft(mongo, cycle=cycle, opening=opening, closing=closing)
        context = modal_context(values={
            "date": opening.format("YYYY-MM-DD"), "time": opening.format("HH:mm"),
        })
        await dashboard.submit_schedule(
            context, f"{draft['token']}|signup|specific", mongo=mongo,
        )

        saved = await cwl_campaign.load_draft(mongo, draft["token"])
        live_row = await mongo.bot_config.find_one({"_id": cwl_campaign.cycle_id(22, cycle)})
        pending = await mongo.cwl_pending_reminders.find({"kind": "campaign"}).to_list(length=None)
        assert saved["campaign"]["messages"]["signup"]["schedule"]["at"] == opening.format("YYYY-MM-DD[T]HH:mm:00")
        assert live_row is None
        assert pending == []
        assert scheduler.jobs == {}
        assert "NOT SCHEDULED:" in _rendered_notice(context)
        assert "already passed" in _rendered_notice(context)

    _run(scenario())


def test_activated_unchanged_past_signup_allows_closing_and_reminder_autosaves(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        install_runtime(monkeypatch, mongo)
        now = pendulum.now("America/New_York").replace(second=0, microsecond=0)
        opening, closing = now.subtract(days=2), now.add(days=3)
        cycle = cwl_campaign.cycle_key(timezone_name="America/New_York")
        campaign = cwl_sequence.configure(
            cwl_campaign.default_campaign(), "evenly", count=2, final_hours=3, min_gap_hours=1,
        )
        campaign["messages"]["signup"]["schedule"] = {
            "mode": "specific", "at": opening.format("YYYY-MM-DD[T]HH:mm:ss"),
        }
        campaign["signup_deadline"] = {"at": closing.format("YYYY-MM-DD[T]HH:mm:ss")}
        mongo.bot_config.documents[cwl_campaign.cycle_id(22, cycle)] = {
            "_id": cwl_campaign.cycle_id(22, cycle), "kind": "cwl_campaign_cycle",
            "guild_id": 22, "cycle": cycle, "revision": 1, "activated": True,
            "campaign": campaign,
        }
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle=cycle)

        revised_closing = closing.add(hours=4)
        closing_context = modal_context(values={
            "date": revised_closing.format("YYYY-MM-DD"), "time": revised_closing.format("HH:mm"),
            "timezone": "America/New_York",
        })
        await dashboard.submit_settings(
            closing_context, f"{draft['token']}|specific", mongo=mongo,
        )
        live_after_closing = await cwl_campaign.load_campaign(mongo, 22, cycle)
        assert live_after_closing["campaign"]["signup_deadline"]["at"] == revised_closing.format("YYYY-MM-DD[T]HH:mm:00")
        assert "NOT SCHEDULED:" not in _rendered_notice(closing_context)

        sequence_context = modal_context(values={
            "count": "1", "final_hours": "3", "min_gap_hours": "1",
        })
        await dashboard.submit_sequence(
            sequence_context, f"{draft['token']}|evenly", mongo=mongo,
        )
        live_after_reminder = await cwl_campaign.load_campaign(mongo, 22, cycle)
        retained = await cwl_campaign.load_draft(mongo, draft["token"])
        assert live_after_reminder["campaign"]["reminder_sequence"]["count"] == 1
        assert retained["token"] == draft["token"]
        assert retained["base_revision"] == live_after_reminder["revision"]
        assert "NOT SCHEDULED:" not in _rendered_notice(sequence_context)
        assert any(
            row["message_id"] == "reminder:1"
            for row in await mongo.cwl_pending_reminders.find({"kind": "campaign", "cycle": cycle}).to_list(length=None)
        )

    _run(scenario())
