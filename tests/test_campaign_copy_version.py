"""Explicit new-default provenance; old/unmarked copy retains exact normalization."""

import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from extensions.commands import cwl_dashboard as dashboard
from extensions.tasks import cwl_reminder as native
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign

GUILD = campaign.LEGACY_WU_GUILD_ID
OLD = json.loads(
    (
        Path(__file__).parent / "fixtures/cwl-campaign-existing-normalized-p127.json"
    ).read_text()
)


def test_old_default_normalization_matches_checked_in_prechange_snapshot():
    old = campaign.default_campaign(new_copy=False)
    assert campaign.DEFAULT_COPY_FIELD not in old
    assert campaign.normalize_signup_entry(old) == OLD


@pytest.mark.parametrize("marker", [None, 0, "127", True, 126, 127.0])
def test_unmarked_or_unknown_version_custom_short_help_has_original_normalization(
    marker,
):
    value = campaign.default_campaign(new_copy=False)
    if marker is not None:
        value[campaign.DEFAULT_COPY_FIELD] = marker
    custom = "Custom saved text. " + campaign.SHORT_SIGNUP_CHECK_LINE
    for mid, message in value["messages"].items():
        if mid != "roster":
            for item in message["variants"].values():
                item["body"] = custom
    before = copy.deepcopy(value)
    normalized = campaign.normalize_signup_entry(value)
    assert value == before
    for mid, message in normalized["messages"].items():
        if mid != "roster":
            for item in message["variants"].values():
                assert item["body"] == custom + "\n\n" + campaign.SIGNUP_CHECK_LINE
    assert normalized.get(campaign.DEFAULT_COPY_FIELD) == marker


@pytest.mark.parametrize(
    "kind", ["missing", "empty", "partial", "cycle", "prior", "future"]
)
def test_unmarked_existing_records_keep_fallback_copy_without_marker_or_writes(kind):
    async def run():
        mongo = MemoryMongo()
        row = {
            "_id": campaign.defaults_id(GUILD),
            "kind": "cwl_campaign_defaults",
            "guild_id": GUILD,
        }
        if kind == "empty":
            row["campaign"] = {}
        if kind == "partial":
            row["campaign"] = {
                "messages": {
                    "signup": {"variants": {"main": {"title": "Custom title"}}}
                }
            }
        if kind in ("cycle", "prior", "future"):
            cycle = {"cycle": "2026-11", "prior": "2026-10", "future": "2026-12"}[kind]
            row = {
                "_id": campaign.cycle_id(GUILD, cycle),
                "kind": "cwl_campaign_cycle",
                "guild_id": GUILD,
                "cycle": cycle,
                "campaign": {},
            }
        mongo.bot_config.documents[row["_id"]] = row
        writes = AsyncMock(wraps=mongo.bot_config.update_one)
        mongo.bot_config.update_one = writes
        result = await campaign.load_campaign(mongo, GUILD, "2026-11")
        expected = copy.deepcopy(OLD)
        if kind == "partial":
            expected["messages"]["signup"]["variants"]["main"]["title"] = "Custom title"
        assert result["campaign"] == expected
        assert campaign.DEFAULT_COPY_FIELD not in result["campaign"]
        baseline = await campaign.load_defaults_campaign(mongo, GUILD)
        assert campaign.DEFAULT_COPY_FIELD not in baseline
        assert (
            baseline["messages"]["roster"]["variants"]["main"]["body"]
            == campaign.default_campaign(new_copy=False)["messages"]["roster"][
                "variants"
            ]["main"]["body"]
        )
        writes.assert_not_awaited()

    asyncio.run(run())


def test_new_defaults_marker_survives_real_draft_save_reload_and_short_help_once(
    monkeypatch,
):
    monkeypatch.setattr(native, "bot_instance", None)
    monkeypatch.setattr(native, "mongo_client", None)

    async def run():
        mongo = MemoryMongo()
        draft = await campaign.new_draft(
            mongo, 22, 11, cycle="2026-11", scope="defaults"
        )
        assert (
            draft["campaign"][campaign.DEFAULT_COPY_FIELD]
            == campaign.DEFAULT_COPY_VERSION
        )
        await campaign.apply_draft(mongo, draft["token"], 11)
        saved = mongo.bot_config.documents[campaign.defaults_id(22)]["campaign"]
        assert saved[campaign.DEFAULT_COPY_FIELD] == campaign.DEFAULT_COPY_VERSION
        loaded = await campaign.load_campaign(mongo, 22, "2026-12")
        baseline = await dashboard._saved_defaults_campaign(mongo, 22)
        assert baseline[campaign.DEFAULT_COPY_FIELD] == campaign.DEFAULT_COPY_VERSION
        for pool in campaign.AUDIENCES:
            for number in range(1, 6):
                body = loaded["campaign"]["messages"][f"reminder:{number}"]["variants"][
                    pool
                ]["body"]
                assert body.count("Check my signups") == 1
                assert campaign.SIGNUP_CHECK_LINE not in body
        campaign.validate_campaign(loaded["campaign"])

    asyncio.run(run())


def test_unmarked_cycle_does_not_inherit_new_default_provenance():
    async def run():
        mongo = MemoryMongo()
        mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
            "_id": campaign.defaults_id(GUILD),
            "kind": "cwl_campaign_defaults",
            "guild_id": GUILD,
            "campaign": campaign.default_campaign(),
        }
        mongo.bot_config.documents[campaign.cycle_id(GUILD, "2026-11")] = {
            "_id": campaign.cycle_id(GUILD, "2026-11"),
            "kind": "cwl_campaign_cycle",
            "guild_id": GUILD,
            "cycle": "2026-11",
            "campaign": {
                "messages": {
                    "signup": {
                        "variants": {
                            "main": {
                                "body": "Custom " + campaign.SHORT_SIGNUP_CHECK_LINE
                            }
                        }
                    }
                }
            },
        }
        result = await campaign.load_campaign(mongo, GUILD, "2026-11")
        assert campaign.DEFAULT_COPY_FIELD not in result["campaign"]
        body = result["campaign"]["messages"]["signup"]["variants"]["main"]["body"]
        assert (
            body
            == "Custom "
            + campaign.SHORT_SIGNUP_CHECK_LINE
            + "\n\n"
            + campaign.SIGNUP_CHECK_LINE
        )

    asyncio.run(run())
