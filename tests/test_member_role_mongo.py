"""Owned loopback Mongo only; durable role-run restart/Stop, no Discord calls."""

import asyncio
import os
import time
from types import SimpleNamespace as S
from uuid import uuid4
import pytest
from pymongo import AsyncMongoClient
from utils.member_profile_runs import ProfileRuns

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="owned local role Mongo fixture required"
)
USER = "123456789012345678"
OTHER = "123456789012345679"
ACTOR = "234567890123456789"
ROLE = "345678901234567890"


def item(uid=USER, protected=False):
    return dict(
        discord_id=uid,
        role_id=ROLE,
        operation="add",
        expected_role_ids=[],
        bot=False,
        protected=protected,
        revision=0,
    )


@pytest.mark.parametrize("child_status", ["done", "uncertain", "running"])
def test_role_restart_never_replays_child_and_stop_blocks_later_people(child_status):
    async def run():
        assert URI == "mongodb://127.0.0.1:27154"
        client = AsyncMongoClient(URI)
        db = client["wu_members_role_restart_" + uuid4().hex]
        mongo = S(bot_config=db.bot_config, component_state=db.component_state)
        try:
            owner = ProfileRuns(mongo)
            parent = await owner.create(
                actor_id=ACTOR,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[item(), item(OTHER)],
                selected=[USER, OTHER],
                run_type="roles",
            )
            now = time.time()
            await owner.advance(now=now)
            key = parent["_id"] + ":0"
            first = await db.bot_config.find_one({"_id": key})
            assert first["section"] == "roles" and first["values"]["discord_id"] == USER
            await db.bot_config.update_one(
                {"_id": key}, {"$set": {"status": child_status, "finished_at": now}}
            )
            restarted = ProfileRuns(mongo)
            await restarted.advance(now=now + 1)
            assert await db.bot_config.count_documents({"_id": key}) == 1
            assert (await db.bot_config.find_one({"_id": key}))[
                "status"
            ] == child_status
            stopped = await restarted.stop(
                parent["_id"], actor_id=ACTOR, guild_id=1, run_type="roles"
            )
            if child_status == "running":
                assert stopped["state"] == "queued" and stopped["stop_requested"]
                await db.bot_config.update_one(
                    {"_id": key}, {"$set": {"status": "uncertain"}}
                )
            await restarted.advance(now=now + 10)
            final = await db.bot_config.find_one({"_id": parent["_id"]})
            assert final["state"] == "stopped"
            assert (
                await db.bot_config.count_documents({"_id": parent["_id"] + ":1"}) == 0
            )
            with pytest.raises(ValueError):
                await restarted.get(parent["_id"], guild_id=1, run_type="profiles")
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_protected_role_confirmation_and_shared_lane_are_durable():
    async def run():
        assert URI == "mongodb://127.0.0.1:27154"
        client = AsyncMongoClient(URI)
        db = client["wu_members_role_confirm_" + uuid4().hex]
        mongo = S(bot_config=db.bot_config, component_state=db.component_state)
        try:
            owner = ProfileRuns(mongo)
            nonce = await owner.preview(
                actor_id=ACTOR,
                guild_id=1,
                rows=[item(protected=True)],
                run_type="roles",
            )
            with pytest.raises(ValueError, match="protected role"):
                await owner.confirm(
                    actor_id=ACTOR,
                    guild_id=1,
                    nonce=nonce,
                    selected=[USER],
                    run_type="roles",
                )
            assert await db.bot_config.count_documents({}) == 0
            parent = await owner.confirm(
                actor_id=ACTOR,
                guild_id=1,
                nonce=nonce,
                selected=[USER],
                run_type="roles",
                protected_confirmed=True,
            )
            retry = await ProfileRuns(mongo).confirm(
                actor_id=ACTOR,
                guild_id=1,
                nonce=nonce,
                selected=[USER],
                run_type="roles",
                protected_confirmed=True,
            )
            assert retry["_id"] == parent["_id"]
            assert (
                await db.bot_config.count_documents(
                    {"kind": "member_profile_standardize"}
                )
                == 1
            )
            with pytest.raises(ValueError, match="still working"):
                await owner.create(
                    actor_id=ACTOR,
                    guild_id=1,
                    request_id=str(uuid4()),
                    preview=[item(OTHER)],
                    selected=[OTHER],
                    run_type="roles",
                )
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
