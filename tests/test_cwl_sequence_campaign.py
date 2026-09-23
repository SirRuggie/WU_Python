import asyncio
from copy import deepcopy

import pytest

from extensions.tasks import cwl_reminder
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign, cwl_sequence
from utils.cwl_review import change_summary


def test_sequence_apply_round_trip_and_future_defaults_do_not_change_current_cycle(monkeypatch):
    async def run():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        cycle = cwl_campaign.cycle_key()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle=cycle)
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        before = await cwl_campaign.load_campaign(mongo, 22, cycle)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle=cycle, scope="defaults")
        candidate = cwl_sequence.configure(draft["campaign"], "evenly", count=4)
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": candidate})
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        current = await cwl_campaign.load_campaign(mongo, 22, cycle)
        assert current["campaign"] == before["campaign"]
        month = cwl_campaign._month(cycle, "America/New_York").add(months=1).format("YYYY-MM")
        future = await cwl_campaign.load_campaign(mongo, 22, month)
        assert future["campaign"]["reminder_sequence"]["enabled"]
        reminders = [item for item in future["schedule"] if item["message_id"].startswith("reminder:")]
        assert len(reminders) == 8  # Four reminders, two audiences; unused slots omitted.
        assert "reminder_sequence" not in str(current["schedule"])
    asyncio.run(run())


def test_impossible_future_monthly_window_is_rejected_before_defaults_are_written(monkeypatch):
    async def run():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10", scope="defaults")
        campaign = cwl_sequence.configure(draft["campaign"], "evenly", count=1)
        campaign["messages"]["signup"]["schedule"] = {"mode": "monthly", "day": 27, "hour": 17, "minute": 0}
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        with pytest.raises(ValueError, match="after signups open"):
            await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        assert await mongo.bot_config.find_one({"_id": cwl_campaign.defaults_id(22)}) is None
    asyncio.run(run())


def test_review_describes_sequence_settings_even_when_dates_match():
    before = cwl_sequence.configure(cwl_campaign.default_campaign(), "evenly", count=1)
    after = deepcopy(before)
    after["reminder_sequence"]["mode"] = "interval"
    after["reminder_sequence"]["interval_hours"] = 744
    summary = change_summary(before, after, "2026-09")
    assert "every 744 hours" in summary
    assert "3 hours before closing" in summary
