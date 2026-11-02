"""Only the reviewed roster pool changes; other future-cycle messages survive."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from extensions.tasks import cwl_reminder as native
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge

GUILD = 22
CURRENT = "2026-11"
CANDIDATE = {
    "title": "Updated roster",
    "body": "Updated body",
    "buttons": [{"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}],
}


def fixture(monkeypatch):
    monkeypatch.setattr(campaign, "_utcnow", lambda: "2026-11-02T19:00:00+00:00")
    mongo = MemoryMongo()
    current = campaign.default_campaign()
    current["messages"]["signup"]["variants"]["main"]["body"] = "Current custom signup"
    future = campaign.default_campaign()
    future["messages"]["signup"]["variants"]["main"]["body"] = "Future custom signup"
    future["messages"]["reminder:3"]["enabled"] = False
    for cycle, value, active in [(CURRENT, current, True), ("2026-12", future, False)]:
        mongo.bot_config.documents[campaign.cycle_id(GUILD, cycle)] = {
            "_id": campaign.cycle_id(GUILD, cycle),
            "kind": "cwl_campaign_cycle",
            "guild_id": GUILD,
            "cycle": cycle,
            "campaign": value,
            "revision": 4,
            "activated": active,
            "updated_at": "2026-11-01T00:00:00+00:00",
            "deliveries": [
                {
                    "status": "sent",
                    "occurrence_id": cycle + "|roster|main",
                    "channel_id": 300,
                    "message_id": 400,
                }
            ],
            "sent_occurrences": [cycle + "|roster|main"],
        }
    return mongo


@pytest.mark.parametrize("future_months", [False, True])
def test_confirmed_copy_save_changes_only_current_pool_and_optional_future_pool(
    monkeypatch, future_months
):
    mongo = fixture(monkeypatch)

    async def run():
        before = {
            cycle: await campaign.load_campaign(mongo, GUILD, cycle)
            for cycle in (CURRENT, "2026-12", "2027-01")
        }
        raw = deepcopy(mongo.bot_config.documents)
        generation = bridge.campaign_generation(before[CURRENT])
        result = await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=generation,
            future_months=future_months,
        )
        assert result == {"campaign_saved": True, "recurring_saved": future_months}
        for cycle, old in before.items():
            new = await campaign.load_campaign(mongo, GUILD, cycle)
            expected = deepcopy(old["campaign"])
            if cycle == CURRENT or future_months:
                expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
            assert new["campaign"] == expected
            assert new["activated"] == old["activated"]
            assert (
                new["deliveries"] == old["deliveries"]
                and new["sent_occurrences"] == old["sent_occurrences"]
            )
            assert native._campaign_generation(new) == bridge.campaign_generation(new)
        current = mongo.bot_config.documents[campaign.cycle_id(GUILD, CURRENT)]
        assert (
            current["campaign"]["messages"]["signup"]
            == raw[campaign.cycle_id(GUILD, CURRENT)]["campaign"]["messages"]["signup"]
        )
        assert (
            mongo.bot_config.documents[campaign.cycle_id(GUILD, "2026-12")]
            == raw[campaign.cycle_id(GUILD, "2026-12")]
        )
        assert ("recurring_roster_copy" in current) is future_months

    asyncio.run(run())


def test_newer_explicit_future_edit_wins_without_changing_other_messages(monkeypatch):
    mongo = fixture(monkeypatch)

    async def run():
        loaded = await campaign.load_campaign(mongo, GUILD, CURRENT)
        old_future = await campaign.load_campaign(mongo, GUILD, "2026-12")
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(loaded),
            future_months=True,
        )
        row = mongo.bot_config.documents[campaign.cycle_id(GUILD, "2026-12")]
        row["updated_at"] = "2026-11-03T00:00:00+00:00"
        row["campaign"]["messages"]["roster"]["variants"]["main"][
            "body"
        ] = "Later explicit roster"
        result = await campaign.load_campaign(mongo, GUILD, "2026-12")
        assert (
            result["campaign"]["messages"]["roster"]["variants"]["main"]["body"]
            == "Later explicit roster"
        )
        assert (
            result["campaign"]["messages"]["signup"]
            == old_future["campaign"]["messages"]["signup"]
        )

    asyncio.run(run())


def test_existing_general_recurring_copy_and_other_pool_are_not_rewritten(monkeypatch):
    mongo = fixture(monkeypatch)
    recurring = campaign.default_campaign()
    recurring["messages"]["signup"]["variants"]["lazy"][
        "body"
    ] = "Existing recurring custom signup"
    source = {
        "_id": campaign.cycle_id(GUILD, "2026-10"),
        "kind": "cwl_campaign_cycle",
        "guild_id": GUILD,
        "cycle": "2026-10",
        "activated": True,
        "recurring_campaign": recurring,
        "recurring_updated_at": "2026-10-20T00:00:00+00:00",
    }
    mongo.bot_config.documents[source["_id"]] = deepcopy(source)

    async def run():
        loaded = await campaign.load_campaign(mongo, GUILD, CURRENT)
        future = await campaign.load_campaign(mongo, GUILD, "2027-01")
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(loaded),
            future_months=True,
        )
        after = await campaign.load_campaign(mongo, GUILD, "2027-01")
        expected = deepcopy(future["campaign"])
        expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
        assert after["campaign"] == expected
        assert mongo.bot_config.documents[source["_id"]] == source
        assert after["recurring_version"] == future["recurring_version"]
        assert bridge.campaign_generation(after) != bridge.campaign_generation(future)

    asyncio.run(run())


def test_stale_generation_never_saves_or_changes_delivery_ledger(monkeypatch):
    mongo = fixture(monkeypatch)
    before = deepcopy(mongo.bot_config.documents)
    writes = AsyncMock(wraps=mongo.bot_config.update_one)
    mongo.bot_config.update_one = writes

    async def run():
        with pytest.raises(RuntimeError, match="Campaign changed"):
            await campaign.save_updated_roster_variant(
                mongo,
                guild_id=GUILD,
                cycle=CURRENT,
                pool="main",
                user_id=200,
                candidate=CANDIDATE,
                expected_generation="stale",
                future_months=True,
            )
        writes.assert_not_awaited()
        assert mongo.bot_config.documents == before

    asyncio.run(run())


@pytest.mark.parametrize("inheritance", ["other_pool", "whole_recurring"])
@pytest.mark.parametrize("future_months", [False, True])
def test_field_save_preserves_inherited_unrelated_pool_and_whole_template(
    monkeypatch, inheritance, future_months
):
    mongo = fixture(monkeypatch)
    source = {
        "_id": campaign.cycle_id(GUILD, "2026-10"),
        "kind": "cwl_campaign_cycle",
        "guild_id": GUILD,
        "cycle": "2026-10",
        "activated": True,
    }
    if inheritance == "other_pool":
        source.update(
            recurring_roster_copy={
                "lazy": {**deepcopy(CANDIDATE), "body": "Inherited Lazy roster"}
            },
            recurring_roster_copy_updated_at={"lazy": "2026-11-02T18:00:00+00:00"},
        )
    else:
        template = campaign.default_campaign()
        template["messages"]["signup"]["variants"]["main"][
            "body"
        ] = "Recent recurring signup must stay"
        template["messages"]["roster"]["variants"]["lazy"][
            "body"
        ] = "Recurring Lazy must stay"
        template["messages"]["roster"]["variants"]["main"][
            "destination_channel_id"
        ] = 555
        template["messages"]["roster"]["variants"]["main"]["role_ids"] = [777]
        source.update(
            recurring_campaign=template,
            recurring_updated_at="2026-11-02T18:00:00+00:00",
        )
    mongo.bot_config.documents[source["_id"]] = deepcopy(source)
    raw_before = deepcopy(mongo.bot_config.documents[campaign.cycle_id(GUILD, CURRENT)])

    async def run():
        before = await campaign.load_campaign(mongo, GUILD, CURRENT)
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(before),
            future_months=future_months,
        )
        after = await campaign.load_campaign(mongo, GUILD, CURRENT)
        expected = deepcopy(before["campaign"])
        expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
        assert after["campaign"] == expected
        assert mongo.bot_config.documents[source["_id"]] == source
        raw_after = mongo.bot_config.documents[campaign.cycle_id(GUILD, CURRENT)]
        assert (
            raw_after["campaign"]["messages"]["signup"]
            == raw_before["campaign"]["messages"]["signup"]
        )
        assert (
            raw_after["campaign"]["messages"]["roster"]["variants"]["lazy"]
            == raw_before["campaign"]["messages"]["roster"]["variants"]["lazy"]
        )
        assert after["deliveries"] == before["deliveries"]

    asyncio.run(run())


def test_ordinary_full_save_at_same_timestamp_invalidates_old_field_markers(
    monkeypatch,
):
    mongo = fixture(monkeypatch)

    async def run():
        before = await campaign.load_campaign(mongo, GUILD, CURRENT)
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(before),
            future_months=True,
        )
        # A real ordinary editor save shares the frozen wall-clock timestamp.
        # Its higher revision, not timestamp inequality, invalidates field state.
        draft = await campaign.new_draft(mongo, GUILD, 200, CURRENT)
        value = deepcopy(draft["campaign"])
        value["messages"]["roster"]["variants"]["lazy"][
            "body"
        ] = "Explicit ordinary Lazy edit"
        value["messages"]["signup"]["variants"]["lazy"][
            "title"
        ] = "Explicit signup edit"
        await campaign.patch_draft(mongo, draft["_id"], {"campaign": value})
        await campaign.apply_draft(mongo, draft["_id"], 200)
        after = await campaign.load_campaign(mongo, GUILD, CURRENT)
        assert (
            after["campaign"]["messages"]["roster"]["variants"]["lazy"]["body"]
            == "Explicit ordinary Lazy edit"
        )
        assert (
            after["campaign"]["messages"]["signup"]["variants"]["lazy"]["title"]
            == "Explicit signup edit"
        )
        assert (
            after["campaign"]["messages"]["roster"]["variants"]["main"]["body"]
            == CANDIDATE["body"]
        )
        row = mongo.bot_config.documents[campaign.cycle_id(GUILD, CURRENT)]
        assert row["updated_at"] == "2026-11-02T19:00:00+00:00"
        assert row["revision"] > row["roster_copy_edit_revision"]
        assert campaign._roster_copy_edit_stamps(row) == {}

    asyncio.run(run())


def test_receipt_only_cycle_field_save_keeps_default_sequence_and_other_settings(
    monkeypatch,
):
    mongo = fixture(monkeypatch)
    row = mongo.bot_config.documents[campaign.cycle_id(GUILD, CURRENT)]
    row.pop("campaign")
    from utils import cwl_sequence

    defaults = cwl_sequence.configure(campaign.default_campaign(), "evenly", count=4)
    mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
        "_id": campaign.defaults_id(GUILD),
        "kind": "cwl_campaign_defaults",
        "guild_id": GUILD,
        "activated": True,
        "revision": 1,
        "campaign": defaults,
    }

    async def run():
        before = await campaign.load_campaign(mongo, GUILD, CURRENT)
        assert before["campaign"]["reminder_sequence"]["enabled"]
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(before),
            future_months=False,
        )
        after = await campaign.load_campaign(mongo, GUILD, CURRENT)
        expected = deepcopy(before["campaign"])
        expected["messages"]["roster"]["variants"]["main"].update(CANDIDATE)
        assert after["campaign"] == expected

    asyncio.run(run())


def test_ordinary_draft_cannot_overwrite_a_new_cross_cycle_recurring_pool_copy(
    monkeypatch,
):
    mongo = fixture(monkeypatch)

    async def run():
        old = await campaign.new_draft(mongo, GUILD, 200, "2026-12")
        updated = deepcopy(old["campaign"])
        updated["messages"]["signup"]["variants"]["lazy"][
            "title"
        ] = "Unrelated old-editor change"
        await campaign.patch_draft(mongo, old["_id"], {"campaign": updated})
        current = await campaign.load_campaign(mongo, GUILD, CURRENT)
        await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=201,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(current),
            future_months=True,
        )
        before = deepcopy(mongo.bot_config.documents)
        with pytest.raises(RuntimeError, match="settings changed"):
            await campaign.apply_draft(mongo, old["_id"], 200)
        assert mongo.bot_config.documents == before

    asyncio.run(run())


def test_cross_cycle_field_after_whole_clock_tie_inherits_until_later_whole_save(
    monkeypatch,
):
    mongo = fixture(monkeypatch)
    source = {
        "_id": "source",
        "kind": "cwl_campaign_cycle",
        "guild_id": GUILD,
        "cycle": "2026-10",
        "revision": 3,
        "recurring_campaign": campaign.default_campaign(),
        "recurring_updated_at": "2026-11-02T19:00:00+00:00",
    }
    mongo.bot_config.documents["source"] = source

    async def run():
        before = await campaign.load_campaign(mongo, GUILD, CURRENT)
        result = await campaign.save_updated_roster_variant(
            mongo,
            guild_id=GUILD,
            cycle=CURRENT,
            pool="main",
            user_id=200,
            candidate=CANDIDATE,
            expected_generation=bridge.campaign_generation(before),
            future_months=True,
        )
        assert result["recurring_saved"] is True
        future = await campaign.load_campaign(mongo, GUILD, "2027-01")
        assert (
            future["campaign"]["messages"]["roster"]["variants"]["main"]["body"]
            == CANDIDATE["body"]
        )
        # A later ordinary whole-template save at the same timestamp wins,
        # even if its body is identical; its durable revision proves ordering.
        source["revision"] += 1
        future = await campaign.load_campaign(mongo, GUILD, "2027-01")
        assert (
            future["campaign"]["messages"]["roster"]["variants"]["main"]["body"]
            != CANDIDATE["body"]
        )

    asyncio.run(run())
