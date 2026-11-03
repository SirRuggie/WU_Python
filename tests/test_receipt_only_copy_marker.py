"""Receipt-only roster field saves retain only proven inherited copy."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign, cwl_sequence
from utils import cwl_web_bridge as bridge

GUILD = 22
CYCLE = "2026-11"
STAMP = "2026-11-03T17:00:00+00:00"
CANDIDATE = {
    "title": "Reviewed synthetic roster",
    "body": "Only this pool changes",
    "buttons": [{"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}],
}


def seed(marked):
    mongo = MemoryMongo()
    defaults = cwl_sequence.configure(campaign.default_campaign(new_copy=marked), "evenly", count=4)
    mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
        "_id": campaign.defaults_id(GUILD), "kind": "cwl_campaign_defaults",
        "guild_id": GUILD, "activated": True, "revision": 1, "campaign": defaults,
    }
    row = {
        "_id": campaign.cycle_id(GUILD, CYCLE), "kind": "cwl_campaign_cycle",
        "guild_id": GUILD, "cycle": CYCLE, "revision": 4,
        "updated_at": STAMP, "deliveries": [{"status": "sent", "message_id": 400}],
        "sent_occurrences": ["synthetic-existing-occurrence"],
    }
    mongo.bot_config.documents[row["_id"]] = row
    return mongo, row


@pytest.mark.parametrize("marked", [False, True])
def test_receipt_only_field_save_preserves_inherited_copy_and_sequence_without_read_writes(monkeypatch, marked):
    async def run():
        mongo, row = seed(marked)
        monkeypatch.setattr(campaign, "_utcnow", lambda: STAMP)
        before = await campaign.load_campaign(mongo, GUILD, CYCLE)
        assert before["campaign"]["reminder_sequence"]["enabled"]
        await campaign.save_updated_roster_variant(
            mongo, guild_id=GUILD, cycle=CYCLE, pool="main", user_id=200,
            candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before), future_months=False,
        )
        saved = mongo.bot_config.documents[row["_id"]]
        assert saved["roster_copy_base_campaign_missing"] is True
        assert campaign._roster_copy_edit_stamps(saved)
        raw = deepcopy(mongo.bot_config.documents)
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        after = await campaign.load_campaign(mongo, GUILD, CYCLE)
        expected = deepcopy(before["campaign"])
        expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
        assert after["campaign"] == expected
        assert after["campaign"].get(campaign.DEFAULT_COPY_FIELD) == (
            campaign.DEFAULT_COPY_VERSION if marked else None
        )
        assert after["deliveries"] == before["deliveries"]
        assert after["sent_occurrences"] == before["sent_occurrences"]
        assert mongo.bot_config.documents == raw
        writes.assert_not_awaited()
    asyncio.run(run())


def partial_field_row(row):
    row.update(
        campaign={"messages": {"roster": {"variants": {"main": deepcopy(CANDIDATE)}}}},
        roster_copy_edit_revision=4,
        roster_copy_edit_updated_at={"main": STAMP},
        roster_copy_base_campaign_missing=True,
        roster_copy_base_updated_at="2026-10-01T00:00:00+00:00",
    )


@pytest.mark.parametrize("broken", ["absent", "stale-revision", "stale-clock", "empty-stamps", "empty-list", "base-false", "base-string", "whole-recurring"])
def test_unproven_or_superseded_field_metadata_keeps177_legacy_behavior_without_read_writes(broken):
    async def run():
        mongo, row = seed(True)
        partial_field_row(row)
        if broken == "absent":
            for key in list(row):
                if key.startswith("roster_copy_"):
                    row.pop(key)
        elif broken == "stale-revision":
            row["roster_copy_edit_revision"] = 3
        elif broken == "stale-clock":
            row["updated_at"] = "2026-11-03T18:00:00+00:00"
        elif broken == "empty-stamps":
            row["roster_copy_edit_updated_at"] = {}
        elif broken == "empty-list":
            row["roster_copy_edit_updated_at"] = []
        elif broken == "base-false":
            row["roster_copy_base_campaign_missing"] = False
        elif broken == "base-string":
            row["roster_copy_base_campaign_missing"] = "true"
        else:
            key = campaign.cycle_id(GUILD, "2026-10")
            mongo.bot_config.documents[key] = {
                "_id": key, "kind": "cwl_campaign_cycle", "guild_id": GUILD,
                "cycle": "2026-10", "revision": 1,
                "recurring_campaign": campaign.default_campaign(new_copy=False),
                "recurring_updated_at": "2026-11-03T18:00:00+00:00",
            }
        before = deepcopy(mongo.bot_config.documents)
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        loaded = await campaign.load_campaign(mongo, GUILD, CYCLE)
        assert campaign.DEFAULT_COPY_FIELD not in loaded["campaign"]
        assert mongo.bot_config.documents == before
        writes.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("bad_stamps", [[STAMP], {"main": 7}, {"unknown-pool": STAMP}])
def test_malformed_field_metadata_refuses_inheritance_without_read_writes(bad_stamps):
    async def run():
        mongo, row = seed(True)
        partial_field_row(row)
        row["roster_copy_edit_updated_at"] = bad_stamps
        before = deepcopy(mongo.bot_config.documents)
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        with pytest.raises(ValueError, match="metadata is invalid"):
            await campaign.load_campaign(mongo, GUILD, CYCLE)
        assert mongo.bot_config.documents == before
        writes.assert_not_awaited()
    asyncio.run(run())
