import asyncio
from copy import deepcopy

from extensions.commands import cwl_dashboard as ui
from extensions.tasks import cwl_reminder
from tests.test_cwl_dashboard_integration import MemoryMongo, install_runtime, modal_context
from tests.test_cwl_navigation import nodes
from utils import cwl_campaign


async def save_button(draft, mongo):
    return next(node for node in nodes(await ui.panel(draft, mongo=mongo)) if node.get("label") == "Save posts")


def test_direct_save_and_undo_track_actual_changes_and_repeat_after_reload(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        install_runtime(monkeypatch, mongo)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        original = deepcopy(draft["campaign"])
        assert (await save_button(draft, mongo))["disabled"]
        edited = deepcopy(original)
        edited["messages"]["signup"]["variants"]["main"]["body"] = "CWL signups are open!"
        draft = await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": edited})
        assert not (await save_button(draft, mongo))["disabled"]
        draft = await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": original})
        assert (await save_button(draft, mongo))["disabled"]
        draft = await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": edited})
        rendered = await ui.save_options(modal_context(), draft["token"] + "|overview", mongo=mongo)
        assert "Use these settings for" not in str(rendered)
        assert "Repeats monthly until changed" in str(rendered[0].build()[0])
        saved = await cwl_campaign.load_draft(mongo, draft["token"])
        assert (await save_button(saved, mongo))["disabled"]
        for cycle in ("2030-10", "2030-11", "2031-02", "2032-01"):
            loaded = await cwl_campaign.load_campaign(mongo, 22, cycle)
            assert loaded["campaign"]["messages"]["signup"]["variants"]["main"]["body"] == "CWL signups are open!"
            assert next(item["run_at"] for item in loaded["schedule"] if item["message_id"] == "signup").startswith(cycle)
        await ui.save_options(modal_context(), draft["token"] + "|overview", mongo=mongo)
        assert (await cwl_campaign.load_campaign(mongo, 22, "2030-10"))["revision"] == 1
    asyncio.run(scenario())


def test_recurring_change_replaces_old_future_snapshot_and_invalidates_old_jobs(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        install_runtime(monkeypatch, mongo)
        future = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-11")
        await cwl_campaign.apply_draft(mongo, future["token"], 11)
        before = await cwl_campaign.load_campaign(mongo, 22, "2030-11")
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        campaign = draft["campaign"]
        campaign["messages"]["signup"]["schedule"] = {"mode":"monthly", "day":24, "hour":19, "minute":0}
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign":campaign})
        await ui.save_options(modal_context(), draft["token"] + "|overview", mongo=mongo)
        after = await cwl_campaign.load_campaign(mongo, 22, "2030-11")
        assert after["campaign"]["messages"]["signup"]["schedule"]["day"] == 24
        assert cwl_reminder._campaign_generation(before) != cwl_reminder._campaign_generation(after)
        assert await cwl_reminder.send_campaign_message(22, "2030-11", "signup", ["main"], cwl_reminder._campaign_generation(before)) is False
        job = await mongo.cwl_pending_reminders.find_one({"_id":cwl_reminder._campaign_job_id(22,"2030-11","signup","main")})
        assert job["run_time"].startswith("2030-11-24T19:00")
    asyncio.run(scenario())


def test_saved_copy_repeats_without_replaying_a_sent_signup(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        _, rest = install_runtime(monkeypatch, mongo)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        await cwl_campaign.apply_draft(mongo, draft["token"], 11, keep_draft=True, repeat_monthly=True)
        assert await cwl_reminder.send_campaign_message(22, "2030-10", "signup", ["main"])
        draft = await cwl_campaign.load_draft(mongo, draft["token"])
        campaign = deepcopy(draft["campaign"])
        campaign["messages"]["signup"]["variants"]["main"]["body"] = "Updated CWL copy"
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        await ui.save_options(modal_context(), draft["token"] + "|overview", mongo=mongo)
        following = await cwl_campaign.load_campaign(mongo, 22, "2030-11")
        assert following["campaign"]["messages"]["signup"]["variants"]["main"]["body"] == "Updated CWL copy"
        assert await cwl_reminder.send_campaign_message(22, "2030-10", "signup", ["main"]) is False
        assert len(rest.sent) == 1
        await ui.pause(modal_context(), draft["token"], mongo=mongo)
        following = await cwl_campaign.load_campaign(mongo, 22, "2030-11")
        assert following["campaign"]["paused"]
        assert following["campaign"]["messages"]["signup"]["variants"]["main"]["body"] == "Updated CWL copy"
        await ui.pause(modal_context(), draft["token"], mongo=mongo)
        assert not (await cwl_campaign.load_campaign(mongo, 22, "2030-11"))["campaign"]["paused"]
    asyncio.run(scenario())


def test_dated_rules_repeat_in_correct_month_including_cross_month_close():
    campaign = cwl_campaign.default_campaign()
    campaign["messages"]["signup"]["schedule"] = {"mode":"specific", "at":"2030-10-25T17:00:00"}
    campaign["signup_deadline"] = {"at":"2030-11-03T17:00:00"}
    recurring = cwl_campaign.monthly_campaign(campaign, "2030-10")
    rows = cwl_campaign.resolve_schedule(recurring, "2030-12")
    assert next(row["run_at"] for row in rows if row["message_id"] == "signup").startswith("2030-12-25")
    assert cwl_campaign.signup_deadline(recurring,"2030-12").format("YYYY-MM-DD") == "2031-01-03"
