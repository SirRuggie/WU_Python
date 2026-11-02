"""Owned loopback Mongo only; durable role-run restart/Stop, no Discord calls."""

import asyncio
import os
import time
from types import SimpleNamespace as S
from uuid import uuid4
import pytest
from local_mongo_fixture import fixture_uri
from pymongo import AsyncMongoClient
from utils.member_profile_runs import ProfileRuns

URI = fixture_uri(os.environ.get("WU_ACTIVITY_TEST_MONGO_URI"))
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


def test_real_prune_separates_histories_and_preserves_needed_role_receipts():
    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_role_retention_" + uuid4().hex]
        try:
            now = time.time()
            rows = []
            rows += [
                dict(
                    _id="nickname",
                    kind="member_profile_standardize",
                    guild_id=1,
                    state="done",
                    finished_at=now - 1000,
                ),
                dict(
                    _id="nickname:0",
                    kind="manage_web_request",
                    section="member_profiles",
                    parent_id="nickname",
                    status="done",
                    finished_at=now - 1000,
                ),
            ]
            for index in range(22):
                key = "role-" + str(index)
                rows += [
                    dict(
                        _id=key,
                        kind="member_profile_standardize",
                        guild_id=1,
                        run_type="roles",
                        state="done",
                        finished_at=now - index,
                    ),
                    dict(
                        _id=key + ":0",
                        kind="manage_web_request",
                        section="roles",
                        parent_id=key,
                        status="done",
                        finished_at=now - index,
                        role_audit={"actor_id": ACTOR, "confirmed_at": now - index},
                    ),
                ]
            old = now - 31 * 86400
            rows += [
                dict(
                    _id="uncertain-role",
                    kind="member_profile_standardize",
                    guild_id=1,
                    run_type="roles",
                    state="stopped",
                    finished_at=old,
                ),
                dict(
                    _id="uncertain-role:0",
                    kind="manage_web_request",
                    section="roles",
                    parent_id="uncertain-role",
                    status="uncertain",
                    finished_at=old,
                    role_audit={"actor_id": ACTOR},
                ),
                dict(
                    _id="expired-orphan:0",
                    kind="manage_web_request",
                    section="roles",
                    parent_id="expired-orphan",
                    status="done",
                    finished_at=old,
                    role_audit={"actor_id": ACTOR},
                ),
            ]
            await db.config.insert_many(rows)
            await ProfileRuns(S(bot_config=db.config)).prune()
            assert await db.config.find_one({"_id": "nickname"})
            assert await db.config.find_one({"_id": "nickname:0"})
            assert (
                await db.config.count_documents(
                    {
                        "kind": "member_profile_standardize",
                        "run_type": "roles",
                        "state": "done",
                    }
                )
                == 20
            )
            assert (
                await db.config.count_documents({"role_audit": {"$exists": True}}) == 23
            )
            assert await db.config.find_one(
                {"_id": "role-21:0"}
            )  # Audited child survives parent cap.
            assert await db.config.find_one({"_id": "uncertain-role"})
            assert await db.config.find_one({"_id": "uncertain-role:0"})
            assert not await db.config.find_one({"_id": "expired-orphan:0"})
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("stop", [False, True])
def test_real_hikari_role_429_wait_and_stop_are_not_uncertain(monkeypatch, stop):
    """Owned Mongo and real SDK against loopback HTTP; no Discord request."""
    import hikari
    from aiohttp import web
    from tests.test_member_role_transport import fixture, BOT
    from tests.fixtures.nickname_speed import Mongo
    from utils import manage_web_worker as worker, dashboard_access
    from unittest.mock import AsyncMock

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_role_sdk_" + uuid4().hex]
        bot, _, state, roles, row, _, _ = fixture()
        calls = []
        accepted = []
        until = None
        first = asyncio.Event()

        async def add(request):
            nonlocal until
            now = time.monotonic()
            uid = request.match_info["uid"]
            calls.append(now)
            first.set()
            if until is None:
                until = now + (2 if stop else 70)
            delay = until - now
            if delay > 0:
                return web.json_response(
                    dict(
                        message="Fixture rate limit", retry_after=delay, global_=False
                    ),
                    status=429,
                    headers={
                        "X-RateLimit-Bucket": "fixture-role",
                        "X-RateLimit-Limit": "1",
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset-After": str(delay),
                    },
                )
            accepted.append(uid)
            state[int(uid)].append(int(ROLE))
            return web.Response(
                status=204,
                headers={
                    "X-RateLimit-Bucket": "fixture-role",
                    "X-RateLimit-Limit": "100",
                    "X-RateLimit-Remaining": "99",
                    "X-RateLimit-Reset-After": "1",
                },
            )

        app = web.Application()
        app.router.add_put("/guilds/{guild}/members/{uid}/roles/{role}", add)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sdk = hikari.impl.RESTApp(
            url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}",
            max_rate_limit=120,
        )
        await sdk.start()
        monkeypatch.setattr(
            dashboard_access, "dashboard_allowed", AsyncMock(return_value=True)
        )
        try:
            async with sdk.acquire("fixture.fake.token", hikari.TokenType.BOT) as real:
                bot.rest.add_role_to_member = real.add_role_to_member
                rows = [
                    dict(row["values"], discord_id=str(int(USER) + i)) for i in range(4)
                ]
                for r in rows:
                    state[int(r["discord_id"])] = []
                mongo = Mongo(db)
                owner = ProfileRuns(mongo)
                parent = await owner.create(
                    actor_id=row["user_id"],
                    guild_id=worker.GUILD_ID,
                    request_id=str(uuid4()),
                    preview=rows,
                    selected=[r["discord_id"] for r in rows],
                    run_type="roles",
                )
                start = time.monotonic()
                task = asyncio.create_task(worker.fast_poll(bot, mongo))
                if stop:
                    await asyncio.wait_for(first.wait(), 5)
                    await owner.stop(
                        parent["_id"],
                        actor_id=row["user_id"],
                        guild_id=worker.GUILD_ID,
                        run_type="roles",
                    )
                await asyncio.wait_for(task, 115)
                final = await db.bot_config.find_one({"_id": parent["_id"]})
                children = await db.bot_config.find(
                    {"parent_id": parent["_id"]}
                ).to_list(10)
                expected = 1 if stop else 4
                assert final["state"] == ("stopped" if stop else "done")
                assert [r["status"] for r in children] == ["done"] * expected
                assert len(accepted) == len(set(accepted)) == expected
                assert len(calls) == expected + 1
                assert calls[1] - calls[0] >= (1.9 if stop else 69)
                print(
                    f"ROLE_REAL_SDK_429 elapsed={time.monotonic()-start:.3f}s accepted={expected} uncertain=0"
                )
        finally:
            await sdk.close()
            await runner.cleanup()
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
