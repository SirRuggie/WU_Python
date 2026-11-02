"""Real SDK 130-second 429 on loopback; owned Mongo, no Discord calls."""

import asyncio, os, time
from types import SimpleNamespace as S
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from pymongo import AsyncMongoClient
from local_mongo_fixture import fixture_uri
from utils.member_profile_runs import ProfileRuns
from utils.member_profiles import MemberProfiles

URI = fixture_uri(os.environ.get("WU_ACTIVITY_TEST_MONGO_URI"))
pytestmark = pytest.mark.skipif(not URI, reason="owned local Mongo required")


@pytest.mark.parametrize(
    "first_kind,next_kind",
    [
        ("roles", "roles"),
        ("profiles", "profiles"),
        ("roles", "profiles"),
        ("profiles", "roles"),
    ],
)
def test_known_backoff_carries_across_new_runs_and_stop(
    monkeypatch, first_kind, next_kind
):
    import hikari
    from aiohttp import web
    from tests.fixtures.nickname_speed import Rest, Mongo, ACTOR, BOT
    from utils import manage_web_worker as worker, dashboard_access

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_lane_backoff_" + uuid4().hex]
        mongo = Mongo(db)
        calls = []

        async def limited(request):
            calls.append((request.method, time.time()))
            return web.json_response(
                {"message": "fixture backoff", "retry_after": 130, "global": False},
                status=429,
                headers={
                    "X-RateLimit-Bucket": "fixture-shared-lane",
                    "X-RateLimit-Limit": "1",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset-After": "130",
                },
            )

        app = web.Application()
        app.router.add_put("/guilds/{guild}/members/{uid}/roles/{role}", limited)
        app.router.add_patch("/guilds/{guild}/members/{uid}", limited)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sdk = hikari.impl.RESTApp(
            url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}",
            max_rate_limit=120,
        )
        await sdk.start()
        fake = Rest(1)
        role_id = 456789012345678901
        ids = {
            101: 567890123456789012,
            102: 678901234567890123,
            103: 789012345678901234,
        }
        for role in fake.roles:
            old = role.id
            role.id = ids.get(old, old)
            role.name = "Fixture"
            role.is_managed = False
            if old == 101:
                role.permissions |= hikari.Permissions.MANAGE_ROLES
        for person in fake.members.values():
            person.role_ids = [ids.get(r, r) for r in person.role_ids]
        fake.roles.append(
            S(
                id=role_id,
                name="Reviewed role",
                position=5,
                permissions=hikari.Permissions.NONE,
                is_managed=False,
            )
        )
        uid = "123456789012340000"
        profiles = MemberProfiles(mongo)
        await profiles.write(
            uid,
            {"zone_id": "gmt-5", "country": "US", "name_source_tag": None},
            expected_revision=0,
            updated_by=str(ACTOR),
            source="staff",
        )
        manifests = {
            "roles": dict(
                discord_id=uid,
                role_id=str(role_id),
                operation="add",
                expected_role_ids=[str(ids[103])],
                bot=False,
                protected=False,
                revision=0,
            ),
            "profiles": dict(
                discord_id=uid,
                old_nickname="Member 0 | EST 🇺🇸",
                new_nickname="Member 0 | GMT-5 🇺🇸",
                revision=1,
            ),
        }
        monkeypatch.setattr(
            dashboard_access, "dashboard_allowed", AsyncMock(return_value=True)
        )
        # The role transport imports its authorization function by name. Patch
        # that binding too, irrespective of which transport another test imported.
        from extensions import member_role_dashboard

        monkeypatch.setattr(
            member_role_dashboard, "dashboard_allowed", AsyncMock(return_value=True)
        )
        owner = ProfileRuns(mongo)

        async def create(kind):
            return await owner.create(
                actor_id=str(ACTOR),
                guild_id=worker.GUILD_ID,
                request_id=str(uuid4()),
                preview=[manifests[kind]],
                selected=[uid],
                run_type=kind,
            )

        try:
            async with sdk.acquire("fixture.fake.token", hikari.TokenType.BOT) as real:
                fake.add_role_to_member = real.add_role_to_member
                fake.edit_member = real.edit_member
                bot = S(rest=fake, get_me=lambda: S(id=BOT))
                first = await create(first_kind)
                await worker.fast_poll(bot, mongo)
                child = await db.bot_config.find_one({"parent_id": first["_id"]})
                assert (
                    child["status"] == "uncertain"
                    and child["retry_not_before"] > time.time() + 125
                ), child.get("message")
                assert len(calls) == 1
                for _ in range(2):
                    parent = await create(next_kind)
                    assert parent["next_at"] >= child["retry_not_before"]
                    waiting_task = asyncio.create_task(worker.fast_poll(bot, mongo))
                    await asyncio.sleep(0.15)
                    assert len(calls) == 1
                    assert (
                        await db.bot_config.count_documents(
                            {"parent_id": parent["_id"]}
                        )
                        == 0
                    )
                    stopped = await owner.stop(
                        parent["_id"],
                        actor_id=str(ACTOR),
                        guild_id=worker.GUILD_ID,
                        run_type=next_kind,
                    )
                    assert stopped["state"] == "stopped"
                    await asyncio.wait_for(waiting_task, 3)
                parent = await create(next_kind)
                await owner.advance(now=child["retry_not_before"] + 1)
                ready = await db.bot_config.find_one({"parent_id": parent["_id"]})
                assert (
                    ready["status"] == "pending"
                    and ready["created_at"] >= child["retry_not_before"]
                )
                await owner.stop(
                    parent["_id"],
                    actor_id=str(ACTOR),
                    guild_id=worker.GUILD_ID,
                    run_type=next_kind,
                )
                assert len(calls) == 1
                print(
                    f"BACKOFF_REAL_SDK {first_kind}->{next_kind}: one PUT/PATCH, later runs queued/Stop safe"
                )
        finally:
            await sdk.close()
            await runner.cleanup()
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_lane_backoff_ignores_expired_and_other_guild_receipts():
    from tests.fixtures.nickname_speed import Mongo
    from utils.member_profile_runs import KIND

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_lane_scope_" + uuid4().hex]
        mongo = Mongo(db)
        owner = ProfileRuns(mongo)
        now = time.time()
        uid = "123456789012345678"
        actor = "234567890123456789"
        item = dict(discord_id=uid, old_nickname="Old", new_nickname="New", revision=1)
        try:
            await db.bot_config.insert_many(
                [
                    dict(
                        _id="expired",
                        kind="manage_web_request",
                        guild_id=1,
                        section="roles",
                        status="uncertain",
                        retry_not_before=now - 1,
                        finished_at=now,
                    ),
                    dict(
                        _id="elsewhere",
                        kind="manage_web_request",
                        guild_id=2,
                        section="roles",
                        status="uncertain",
                        retry_not_before=now + 300,
                        finished_at=now,
                    ),
                    dict(
                        _id="unrelated",
                        kind="manage_web_request",
                        guild_id=1,
                        section="applications",
                        status="uncertain",
                        retry_not_before=now + 300,
                        finished_at=now,
                    ),
                ]
            )
            parent = await owner.create(
                actor_id=actor,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[item],
                selected=[uid],
            )
            assert parent["next_at"] == 0
            await owner.stop(parent["_id"], actor_id=actor, guild_id=1)
            # A fresh owner after restart must use the greatest matching receipt.
            await db.bot_config.insert_many(
                [
                    dict(
                        _id=str(i),
                        kind="manage_web_request",
                        guild_id=1,
                        section=section,
                        status="uncertain",
                        retry_not_before=now + delay,
                        finished_at=now,
                    )
                    for i, section, delay in [
                        (1, "roles", 80),
                        (2, "member_profiles", 150),
                    ]
                ]
            )
            parent = await ProfileRuns(mongo).create(
                actor_id=actor,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[item],
                selected=[uid],
            )
            assert parent["next_at"] == now + 150
            await owner.stop(parent["_id"], actor_id=actor, guild_id=1)
            old = now - 40 * 86400
            await db.bot_config.insert_many(
                [
                    dict(
                        _id="old-parent",
                        kind=KIND,
                        guild_id=1,
                        run_type="profiles",
                        state="done",
                        finished_at=old,
                        next_at=now + 450,
                    ),
                    dict(
                        _id="old-parent:0",
                        parent_id="old-parent",
                        kind="manage_web_request",
                        guild_id=1,
                        section="member_profiles",
                        status="uncertain",
                        finished_at=old,
                        retry_not_before=now + 450,
                    ),
                ]
            )
            parent = await ProfileRuns(mongo).create(
                actor_id=actor,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[item],
                selected=[uid],
            )
            assert parent["next_at"] == now + 450
            assert await db.bot_config.count_documents({"_id": "old-parent:0"}) == 1
            info = await db.bot_config.index_information()
            assert info["member_change_lane_backoff"]["partialFilterExpression"] == {
                "kind": "manage_web_request",
                "retry_not_before": {"$exists": True},
            }
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["roles", "profiles"])
def test_backoff_arriving_after_parent_creation_blocks_child(kind):
    from tests.fixtures.nickname_speed import Mongo

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_late_backoff_" + uuid4().hex]
        owner = ProfileRuns(Mongo(db))
        uid = "123456789012345678"
        actor = "234567890123456789"
        item = dict(discord_id=uid, old_nickname="Old", new_nickname="New", revision=1)
        if kind == "roles":
            item = dict(
                discord_id=uid,
                role_id="345678901234567890",
                operation="add",
                expected_role_ids=[],
                bot=False,
                protected=False,
                revision=0,
            )
        try:
            parent = await owner.create(
                actor_id=actor,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[item],
                selected=[uid],
                run_type=kind,
            )
            assert parent["next_at"] == 0
            deadline = time.time() + 130
            await db.bot_config.insert_one(
                dict(
                    _id="later429",
                    kind="manage_web_request",
                    guild_id=1,
                    section="member_profiles",
                    status="uncertain",
                    retry_not_before=deadline,
                    finished_at=time.time(),
                )
            )
            await owner.advance()
            assert (
                await db.bot_config.count_documents({"parent_id": parent["_id"]}) == 0
            )
            assert (await db.bot_config.find_one({"_id": parent["_id"]}))[
                "next_at"
            ] == deadline
            await owner.advance(now=deadline + 1)
            assert (
                await db.bot_config.count_documents({"parent_id": parent["_id"]}) == 1
            )
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_standalone_backoff_keeps_pending_other_sections_flow(monkeypatch):
    from tests.fixtures.nickname_speed import Mongo
    from utils import manage_web_worker as worker

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_standalone_backoff_" + uuid4().hex]
        mongo = Mongo(db)
        calls = []

        async def dispatch(bot, mongo, row, ctx):
            calls.append(row["_id"])
            return {"message": "fixture confirmed"}

        monkeypatch.setattr(worker, "context", AsyncMock(return_value=S()))
        monkeypatch.setattr(worker, "dispatch", dispatch)
        try:
            await ProfileRuns(mongo).ensure_work_index()
            now = time.time()
            await db.bot_config.insert_many(
                [
                    dict(
                        _id="429",
                        kind="manage_web_request",
                        guild_id=worker.GUILD_ID,
                        section="roles",
                        status="uncertain",
                        retry_not_before=now + 130,
                        finished_at=now,
                    ),
                    dict(
                        _id="save",
                        kind="manage_web_request",
                        guild_id=worker.GUILD_ID,
                        section="member_profiles",
                        action="save",
                        values={"rename": True},
                        status="pending",
                        created_at=now,
                        expires_at=now + 900,
                    ),
                    dict(
                        _id="other",
                        kind="manage_web_request",
                        guild_id=worker.GUILD_ID,
                        section="applications",
                        action="save",
                        status="pending",
                        created_at=now,
                        expires_at=now + 900,
                    ),
                ]
            )
            # This regression exercises claiming, not unrelated operation validation.
            monkeypatch.setattr(
                worker, "ACTIONS", set(worker.ACTIONS) | {("applications", "save")}
            )
            await worker._process_requests(S(), mongo)
            assert calls == ["other"]
            assert (await db.bot_config.find_one({"_id": "save"}))[
                "status"
            ] == "pending"
            await worker._process_requests(S(), mongo)
            assert calls == ["other"]  # repeated polls never claim/requeue/spin it
            await db.bot_config.update_one(
                {"_id": "429"}, {"$set": {"retry_not_before": time.time() - 1}}
            )
            await worker._process_requests(S(), mongo)
            assert calls == ["other", "save"]
            assert (await db.bot_config.find_one({"_id": "save"}))["status"] == "done"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
