"""Opt-in real Mongo fixture, never the default production endpoint."""

import asyncio
import os
from types import SimpleNamespace as S
from uuid import uuid4
import pytest
from pymongo import AsyncMongoClient
from utils.declaration_ping_store import DeclarationPingStore, PingConflict

URI = os.getenv("WU_DECLARATION_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="isolated declaration Mongo fixture not supplied"
)
GUILD = "644963518025826315"
ACTOR = "123456789012345678"
CHANNEL = "234567890123456789"
GROUPS = [dict(accounts=[{}], unlinked=[])]
PLAN = [dict(payload="fixture")]


def test_real_revision_claim_double_click_cooldown_and_restart():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_declaration_fixture_" + uuid4().hex]
        a = DeclarationPingStore(S(bot_config=db.bot_config), GUILD)
        b = DeclarationPingStore(S(bot_config=db.bot_config), GUILD)
        try:
            assert (await a.read("main"))["revision"] == 0
            await a.configure("main", CHANNEL, "fixture", ACTOR, 0, now=1000)
            with pytest.raises(PingConflict):
                await b.configure("main", CHANNEL, "other", ACTOR, 0, now=1001)
            preview = await a.preview("main", ACTOR, 1, GROUPS, 3, "hash", 1, now=1000)

            async def claim(store):
                return await store.claim(
                    "main", ACTOR, 1, preview["token"], "hash", PLAN, "first", now=1001
                )

            results = await asyncio.gather(claim(a), claim(b))
            assert sum(bool(r[0]) for r in results) == 1
            await a.begin_chunk("main", preview["token"], 0)
            await a.posted("main", preview["token"], 0, "345678901234567890")
            result = await a.finish("main", preview["token"], "done", now=1002)
            assert result["posted"] == [dict(chunk=0, message_id="345678901234567890")]
            assert not (await claim(b))[0]
            other = await a.preview("main", ACTOR, 1, GROUPS, 3, "hash", 1, now=1003)
            with pytest.raises(PingConflict):
                await a.claim(
                    "main",
                    ACTOR,
                    1,
                    other["token"],
                    "hash",
                    PLAN,
                    "first",
                    send_again=True,
                    now=1004,
                )
            later = await a.preview("main", ACTOR, 1, GROUPS, 3, "hash", 1, now=1400)
            with pytest.raises(PingConflict):
                await a.claim(
                    "main", ACTOR, 1, later["token"], "hash", PLAN, "first", now=1401
                )
            assert (
                await a.claim(
                    "main",
                    ACTOR,
                    1,
                    later["token"],
                    "hash",
                    PLAN,
                    "first",
                    send_again=True,
                    now=1401,
                )
            )[0]
            await a.begin_chunk("main", later["token"], 0)
            await b.recover_other_process("main", "second", now=1402)
            recovered = await b.receipt("main", later["token"])
            assert recovered["state"] == "uncertain" and recovered["attempting"] == 0
            assert not (await b.read("main"))["active"]
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_test_mode_consumes_review_without_receipt_or_cooldown():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_declaration_test_fixture_" + uuid4().hex]
        store = DeclarationPingStore(S(bot_config=db.bot_config), GUILD)
        try:
            await store.configure("lazy", CHANNEL, "fixture", ACTOR, 0, now=1000)
            preview = await store.preview(
                "lazy",
                ACTOR,
                1,
                GROUPS,
                3,
                "hash",
                1,
                test_channel={"id": CHANNEL, "name": "test"},
                now=1000,
            )
            with pytest.raises(PingConflict):
                await store.consume_test(
                    "lazy", ACTOR, 1, preview["token"], "stale", now=1001
                )
            await store.consume_test(
                "lazy", ACTOR, 1, preview["token"], "hash", now=1001
            )
            with pytest.raises(PingConflict):
                await store.consume_test(
                    "lazy", ACTOR, 1, preview["token"], "hash", now=1002
                )
            await store.release_test("lazy", preview["token"])
            lane = await store.read("lazy")
            assert (
                lane["history"] == []
                and lane["last_attempt_at"] == 0
                and lane["active"] is None
            )
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
