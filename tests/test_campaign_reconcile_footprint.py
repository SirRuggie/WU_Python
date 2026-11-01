"""Native campaign change detection is identical without unrelated BSON payloads."""

import asyncio
from copy import deepcopy
import hashlib
import json
from unittest.mock import AsyncMock

from bson import BSON
import pytest
from tests.test_cwl_dashboard_integration import MemoryMongo, MemoryCollection
from utils import cwl_campaign, cwl_web_bridge as bridge

GUILD = 644963518025826315
KINDS = ("cwl_campaign_defaults", "cwl_campaign_cycle")


class MeasuredCollection(MemoryCollection):
    def __init__(self, documents):
        super().__init__(documents)
        self.reads = []

    def find(self, query=None, projection=None):
        cursor = super().find(query, projection)
        original = cursor.to_list

        async def read(*args, **kwargs):
            rows = await original(*args, **kwargs)
            self.reads.append(
                {
                    "query": deepcopy(query),
                    "projection": deepcopy(projection),
                    "rows": len(rows),
                    "bson_bytes": sum(len(BSON.encode(row)) for row in rows),
                }
            )
            return rows

        cursor.to_list = read
        return cursor


def seed():
    rows = {}
    for key, kind, cycle in [
        ("defaults", "cwl_campaign_defaults", None),
        ("november", "cwl_campaign_cycle", "2026-11"),
        ("december", "cwl_campaign_cycle", "2026-12"),
    ]:
        row = dict(
            _id=(
                cwl_campaign.defaults_id(GUILD)
                if cycle is None
                else cwl_campaign.cycle_id(GUILD, cycle)
            ),
            kind=kind,
            guild_id=GUILD,
            activated=True,
            revision=3,
            updated_at="2026-10-31T12:00:00+00:00",
            recurring_updated_at="2026-11-01T12:00:00+00:00",
            campaign=cwl_campaign.default_campaign(),
            irrelevant_large_blob="x" * 32768,
        )
        if cycle:
            row["cycle"] = cycle
        rows[row["_id"]] = row
    rows["inactive"] = dict(
        _id="inactive",
        kind=KINDS[1],
        guild_id=GUILD,
        activated=False,
        revision=5,
        cycle="2026-10",
        irrelevant_large_blob="x" * 32768,
    )
    rows["other-guild"] = dict(
        _id="other-guild",
        kind=KINDS[1],
        guild_id=1,
        activated=True,
        revision=5,
        cycle="2026-10",
    )
    for i in range(350):
        key = "profile-" + str(i)
        rows[key] = dict(
            _id=key,
            kind="member_profile_standardize" if i % 2 else "manage_web_request",
            guild_id=GUILD,
            activated=True,
            revision=i,
            items=["x" * 8192],
        )
    mongo = MemoryMongo()
    mongo.bot_config = MeasuredCollection(rows)
    return mongo


def original_signature(mongo):
    rows = [
        row
        for row in mongo.bot_config.documents.values()
        if row.get("guild_id") == GUILD
        and row.get("kind") in KINDS
        and row.get("activated") is True
    ]
    return hashlib.sha256(
        json.dumps(
            sorted(
                (
                    str(row["_id"]),
                    int(row.get("revision", 0)),
                    str(row.get("updated_at", "")),
                    str(row.get("recurring_updated_at", "")),
                )
                for row in rows
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_signature_generations_and_response_budget_match_original_semantics():
    async def scenario():
        mongo = seed()
        sync = AsyncMock()
        expected = original_signature(mongo)
        generations = {
            cycle: bridge.campaign_generation(
                await cwl_campaign.load_campaign(mongo, GUILD, cycle)
            )
            for cycle in ("2026-11", "2026-12")
        }
        start = len(mongo.bot_config.reads)
        assert await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        worker = await mongo.bot_config.find_one({"_id": bridge.worker_id(GUILD)})
        assert worker["schedule_fingerprint"] == expected
        assert worker["schedule_generations"] == generations
        read = mongo.bot_config.reads[start]
        old_bytes = sum(
            len(BSON.encode(row))
            for row in mongo.bot_config.documents.values()
            if row.get("guild_id") == GUILD
        )
        assert read["rows"] == 3 and read["bson_bytes"] < 2000
        assert read["bson_bytes"] < old_bytes / 1000
        assert not await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        assert sync.await_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", 4),
        ("updated_at", "2026-11-02T12:00:00+00:00"),
        ("recurring_updated_at", "2026-11-02T13:00:00+00:00"),
        ("cycle", "2027-01"),
    ],
)
def test_every_change_detection_field_still_invalidates_the_fingerprint(field, value):
    async def scenario():
        mongo = seed()
        sync = AsyncMock()
        await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        mongo.bot_config.documents[cwl_campaign.cycle_id(GUILD, "2026-11")][
            field
        ] = value
        expected = original_signature(mongo)
        # cycle itself is not a fingerprint field; changing it must still be
        # observed when its owning revision changes in the same real edit.
        if field == "cycle":
            mongo.bot_config.documents[cwl_campaign.cycle_id(GUILD, "2026-11")][
                "revision"
            ] += 1
            expected = original_signature(mongo)
        assert await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        worker = await mongo.bot_config.find_one({"_id": bridge.worker_id(GUILD)})
        assert worker["schedule_fingerprint"] == expected
        cycles = {
            row["cycle"]
            for row in mongo.bot_config.documents.values()
            if row.get("guild_id") == GUILD
            and row.get("kind") in KINDS
            and row.get("activated") is True
            and row.get("cycle")
        }
        assert set(worker["schedule_generations"]) == cycles
        assert sync.await_count == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("activate", [False, True])
def test_activation_and_deactivation_both_reconcile(activate):
    async def scenario():
        mongo = seed()
        sync = AsyncMock()
        await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        if activate:
            mongo.bot_config.documents["inactive"]["activated"] = True
        else:
            for row in mongo.bot_config.documents.values():
                if row.get("kind") in KINDS:
                    row["activated"] = False
        assert await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        assert mongo.bot_config.documents[bridge.worker_id(GUILD)][
            "schedule_fingerprint"
        ] == original_signature(mongo)
        assert not await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)

    asyncio.run(scenario())


def test_unrelated_parent_receipt_and_large_body_changes_do_not_reschedule():
    async def scenario():
        mongo = seed()
        sync = AsyncMock()
        await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        mongo.bot_config.documents["profile-0"]["revision"] += 1
        mongo.bot_config.documents["profile-1"]["items"] = ["new body"]
        assert not await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        assert sync.await_count == 1

    asyncio.run(scenario())


def test_failed_sync_does_not_acknowledge_and_concurrent_edit_is_seen_next_tick():
    async def scenario():
        mongo = seed()
        sync = AsyncMock(side_effect=RuntimeError("fixture sync failed"))
        with pytest.raises(RuntimeError):
            await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
        assert bridge.worker_id(GUILD) not in mongo.bot_config.documents
        before = original_signature(mongo)

        async def edit():
            mongo.bot_config.documents[cwl_campaign.cycle_id(GUILD, "2026-11")][
                "revision"
            ] += 1

        assert await bridge.reconcile_campaign_changes(mongo, edit, guild_id=GUILD)
        assert (
            mongo.bot_config.documents[bridge.worker_id(GUILD)]["schedule_fingerprint"]
            == before
        )
        assert original_signature(mongo) != before
        assert await bridge.reconcile_campaign_changes(
            mongo, AsyncMock(), guild_id=GUILD
        )

    asyncio.run(scenario())
