"""Owned Mongo: actual pool connections and bounded maintenance-shaped calls."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient, MongoClient, UpdateOne

from cwl_web.mongo_client import get_client, lifecycle

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not URI, reason="owned real Mongo fixture not provided")


def test_actual_shared_pool_uses_fewer_connections_for_same_reads():
    assert URI == "mongodb://127.0.0.1:27154"
    observer = MongoClient(
        URI, appName="wu-p97-owned-observer", serverSelectionTimeoutMS=2000
    )
    name = "wu_p97_pool_" + uuid4().hex
    try:
        observer[name].work.insert_one({"_id": "fixture", "payload": "x" * 17135})

        def counters():
            status = observer.admin.command("serverStatus")
            return {
                "connections": status["connections"]["totalCreated"],
                "bytes_in": status["network"]["bytesIn"],
                "bytes_out": status["network"]["bytesOut"],
            }

        async def run():
            before = counters()
            for _ in range(20):
                client = AsyncMongoClient(
                    URI,
                    appName="wu-p97-owned-old-per-call",
                    maxPoolSize=20,
                    timeoutMS=15000,
                    serverSelectionTimeoutMS=2000,
                )
                try:
                    assert (await client[name].work.find_one({"_id": "fixture"}))[
                        "payload"
                    ]
                finally:
                    await client.close()
            middle = counters()
            provider = SimpleNamespace(mongo_uri=URI, routes={})
            app = {"providers": provider}
            context = lifecycle(app)
            await context.__anext__()
            shared = get_client(app)
            try:
                for _ in range(20):
                    assert get_client(app) is shared
                    assert (await shared[name].work.find_one({"_id": "fixture"}))[
                        "payload"
                    ]
            finally:
                await context.aclose()
            after = counters()
            prior = {key: middle[key] - before[key] for key in before}
            current = {key: after[key] - middle[key] for key in before}
            assert current["connections"] <= prior["connections"] / 2
            result = {
                "scope": "Owned local Mongo, identical 20 full-document reads; raw server counters include observer/handshake overhead, no compression. Not production/Atlas quota evidence.",
                "reads_each": 20,
                "old_per_call": prior,
                "shared_startup_owned": current,
            }
            evidence = os.environ.get("P97_EVIDENCE_DIR")
            if evidence:
                (Path(evidence) / "p97-real-pool-counters.json").write_text(
                    json.dumps(result, indent=2)
                )

        asyncio.run(run())
    finally:
        observer.drop_database(name)
        observer.close()


def test_bot_budget_keeps_index_bulk_and_hourly_read_shapes_working():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(
            URI,
            appName="wu-p97-owned-long-shapes",
            maxPoolSize=20,
            timeoutMS=30000,
            serverSelectionTimeoutMS=3000,
        )
        name = "wu_p97_long_" + uuid4().hex
        try:
            collection = client[name].activity
            await collection.create_index([("guild_id", 1), ("tag", 1)], unique=True)
            await collection.insert_many(
                [
                    {"guild_id": 1, "tag": str(i), "payload": "x" * 1024}
                    for i in range(584)
                ]
            )
            result = await collection.bulk_write(
                [
                    UpdateOne({"guild_id": 1, "tag": str(i)}, {"$set": {"seen": True}})
                    for i in range(500)
                ],
                ordered=False,
            )
            assert result.modified_count == 500
            assert len(await collection.find({}).to_list(None)) == 584
            assert client.options.timeout == 30
        finally:
            await client.drop_database(name)
            await client.close()

    asyncio.run(run())


def test_slow_strike_history_fetch_does_not_spend_later_mongo_budget():
    """Actual import-preview adapter, fake 16s provider, real local receipt write."""
    from unittest.mock import AsyncMock, patch
    from cwl_web import strikes
    assert URI == "mongodb://127.0.0.1:27154"
    async def run():
        client = AsyncMongoClient(URI, timeoutMS=15000)
        db = client["wu_p105_import_" + uuid4().hex]
        app = {"server_management_mongo": SimpleNamespace(bot_config=db.bot_config)}
        async def history(*args, **kwargs):
            await asyncio.sleep(16)
            return {"wars": [], "cwl_wars": [], "skipped": [], "source_count": 0}
        async def preview(*args, **kwargs):
            await db.bot_config.insert_one({"_id": "preview-complete"})
            return {"preview_id": "fixture", "summary": {}, "items": [], "wars": 0}
        ledger = SimpleNamespace(preview_import=preview)
        try:
            with patch.object(strikes, "service", AsyncMock(return_value=ledger)), patch.object(
                strikes, "clan_rows", AsyncMock(return_value=[{"tag": "#P2Y", "name": "Fixture"}])
            ), patch("utils.strike_wars.fetch_history_report", history):
                result = await strikes._preview_work(app, 5, 60)
            assert result["preview_id"] == "fixture"
            assert await db.bot_config.find_one({"_id": "preview-complete"})
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())
