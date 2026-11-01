"""Owned Mongo verifies type/filter/projection semantics; no live provider calls."""

import asyncio
import hashlib
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from bson import BSON
import pytest
from pymongo import AsyncMongoClient
from utils import cwl_campaign, cwl_web_bridge as bridge

URI = os.environ.get("WU_CAMPAIGN_READ_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated owned Mongo fixture not provided"
)
GUILD = 644963518025826315


def test_real_mongo_filter_projected_signature_and_native_generation():
    async def scenario():
        assert URI == "mongodb://127.0.0.1:27156"
        client = AsyncMongoClient(URI, serverSelectionTimeoutMS=3000)
        database = client["wu_campaign_read_" + uuid4().hex]
        col = database.config
        try:
            common = dict(
                guild_id=GUILD,
                activated=True,
                revision=3,
                updated_at="before",
                recurring_updated_at="recurring-before",
                campaign=cwl_campaign.default_campaign(),
            )
            rows = [
                dict(
                    common,
                    _id=cwl_campaign.defaults_id(GUILD),
                    kind="cwl_campaign_defaults",
                ),
                dict(
                    common,
                    _id=cwl_campaign.cycle_id(GUILD, "2026-11"),
                    kind="cwl_campaign_cycle",
                    cycle="2026-11",
                ),
            ]
            rows += [
                dict(
                    _id="parent-" + str(i),
                    kind="member_profile_standardize",
                    guild_id=GUILD,
                    items=["x" * 4096],
                )
                for i in range(350)
            ]
            rows += [
                dict(
                    common,
                    _id="numeric-true",
                    kind="cwl_campaign_cycle",
                    cycle="2027-01",
                    activated=1,
                ),
                dict(
                    common,
                    _id="false",
                    kind="cwl_campaign_cycle",
                    cycle="2027-02",
                    activated=False,
                ),
                dict(
                    common,
                    _id="other-guild",
                    kind="cwl_campaign_cycle",
                    cycle="2027-03",
                    guild_id=1,
                ),
            ]
            await col.insert_many(rows)
            mongo = SimpleNamespace(bot_config=col)
            baseline = [row async for row in col.find({"guild_id": GUILD})]
            participating = [
                row
                for row in baseline
                if row.get("kind") in ("cwl_campaign_defaults", "cwl_campaign_cycle")
                and row.get("activated") is True
            ]
            expected = hashlib.sha256(
                json.dumps(
                    sorted(
                        (
                            str(row["_id"]),
                            int(row.get("revision", 0)),
                            str(row.get("updated_at", "")),
                            str(row.get("recurring_updated_at", "")),
                        )
                        for row in participating
                    ),
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            expected_generation = bridge.campaign_generation(
                await cwl_campaign.load_campaign(mongo, GUILD, "2026-11")
            )
            sync = AsyncMock()
            assert await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
            worker = await col.find_one({"_id": bridge.worker_id(GUILD)})
            assert worker["schedule_fingerprint"] == expected
            assert worker["schedule_generations"] == {"2026-11": expected_generation}
            assert not await bridge.reconcile_campaign_changes(
                mongo, sync, guild_id=GUILD
            )
            await col.update_one(
                {"_id": cwl_campaign.cycle_id(GUILD, "2026-11")},
                {
                    "$inc": {"revision": 1},
                    "$set": {"recurring_updated_at": "recurring-after"},
                },
            )
            assert await bridge.reconcile_campaign_changes(mongo, sync, guild_id=GUILD)
            assert sync.await_count == 2
            projected = [
                row
                async for row in col.find(
                    {
                        "guild_id": GUILD,
                        "kind": {
                            "$in": ["cwl_campaign_defaults", "cwl_campaign_cycle"]
                        },
                        "activated": True,
                    },
                    {
                        "_id": 1,
                        "revision": 1,
                        "updated_at": 1,
                        "recurring_updated_at": 1,
                        "cycle": 1,
                    },
                )
            ]
            assert (
                len(projected) == 2
                and sum(len(BSON.encode(row)) for row in projected) < 1000
            )
            assert sum(len(BSON.encode(row)) for row in baseline) > 1_000_000
        finally:
            await client.drop_database(database.name)
            await client.close()

    asyncio.run(scenario())
