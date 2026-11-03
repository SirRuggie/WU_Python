"""Schema-versioned legacy fallback is independent of newer marked defaults."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign


@pytest.mark.parametrize("partial_title", [False, True])
def test_sparse_unmarked_snapshot_uses_saved_copy_baseline_not_new_defaults(partial_title):
    async def run():
        guild, cycle = 22, "2026-11"
        mongo = MemoryMongo()
        mongo.bot_config.documents[campaign.defaults_id(guild)] = {
            "_id": campaign.defaults_id(guild), "kind": "cwl_campaign_defaults",
            "guild_id": guild, "campaign": campaign.default_campaign(),
        }
        snapshot = {"schema_version": campaign.SCHEMA_VERSION}
        if partial_title:
            snapshot["messages"] = {"signup": {"variants": {"main": {"title": "Saved custom title"}}}}
        mongo.bot_config.documents[campaign.cycle_id(guild, cycle)] = {
            "_id": campaign.cycle_id(guild, cycle), "kind": "cwl_campaign_cycle",
            "guild_id": guild, "cycle": cycle, "revision": 1, "campaign": snapshot,
        }
        raw = deepcopy(mongo.bot_config.documents)
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        loaded = await campaign.load_campaign(mongo, guild, cycle)
        expected = campaign.normalize_signup_entry(campaign.default_campaign(new_copy=False))
        if partial_title:
            expected["messages"]["signup"]["variants"]["main"]["title"] = "Saved custom title"
        assert loaded["campaign"] == expected
        assert campaign.DEFAULT_COPY_FIELD not in loaded["campaign"]
        assert mongo.bot_config.documents == raw
        writes.assert_not_awaited()
    asyncio.run(run())
