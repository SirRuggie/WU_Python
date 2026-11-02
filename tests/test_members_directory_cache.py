"""Raw directory caching cannot cache permissions or resurrect old writes."""

import asyncio
from types import SimpleNamespace as S
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import member_timezones as routes, manage_roles, member_role_runs
from cwl_web.member_directory_cache import DirectoryCache, KEY, observe_job, observe_run


def test_hit_expiry_force_and_mutation_isolation():
    async def run():
        now = [0]
        cache = DirectoryCache(clock=lambda: now[0])
        calls = []

        async def fetch():
            calls.append(True)
            return {"rows": [{"value": len(calls)}]}

        first = await cache.read(fetch)
        assert not first.cached
        first.value["rows"][0]["value"] = 99
        second = await cache.read(fetch)
        assert second.cached and second.value["rows"][0]["value"] == 1
        forced = await cache.read(fetch, force=True)
        assert not forced.cached and len(calls) == 2
        now[0] = 60
        expired = await cache.read(fetch)
        assert not expired.cached and len(calls) == 3

    asyncio.run(run())


def test_force_concurrent_readers_share_only_fresh_work():
    async def run():
        cache = DirectoryCache()
        release = asyncio.Event()
        entered = asyncio.Event()
        calls = []

        async def fetch():
            calls.append(True)
            entered.set()
            await release.wait()
            return {"value": "fresh"}

        one = asyncio.create_task(cache.read(fetch, force=True))
        await entered.wait()
        two = asyncio.create_task(cache.read(fetch, force=True))
        await asyncio.sleep(0)
        one.cancel()
        await asyncio.gather(one, return_exceptions=True)
        assert not cache.pending.task.cancelled()
        release.set()
        assert (await two).value == {"value": "fresh"} and len(calls) == 1

    asyncio.run(run())


def test_invalidated_inflight_result_never_repopulates_new_cache():
    async def run():
        cache = DirectoryCache()
        release = asyncio.Event()
        entered = asyncio.Event()

        async def old():
            entered.set()
            await release.wait()
            return {"value": "old"}

        async def new():
            return {"value": "new"}

        first = asyncio.create_task(cache.read(old))
        await entered.wait()
        cache.invalidate()
        assert (await cache.read(new)).value == {"value": "new"}
        release.set()
        await first
        assert (await cache.read(new)).value == {"value": "new"}

    asyncio.run(run())


def test_last_cancelled_reader_cancels_owned_fetch():
    async def run():
        cache = DirectoryCache()
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def fetch():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(cache.read(fetch))
        await entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(cancelled.wait(), 1)

    asyncio.run(run())


def test_receipt_invalidation_is_bounded_and_ignores_other_sections():
    cache = DirectoryCache()
    app = {KEY: cache}
    observe_job(app, dict(_id="other", section="tickets", status="done"))
    assert cache.generation == 0
    job = dict(_id="job", section="roles", status="done")
    observe_job(app, job)
    observe_job(app, job)
    assert cache.generation == 1
    observe_run(app, {"_id": "run"}, [{"status": "done"}])
    observe_run(app, {"_id": "run"}, [{"status": "done"}])
    assert cache.generation == 2
    observe_run(app, {"_id": "run"}, [{"status": "done"}, {"status": "done"}])
    assert cache.generation == 3
    for n in range(200):
        observe_job(app, dict(job, _id=str(n)))
    assert len(cache.receipts) == 128


@pytest.fixture
def wire(monkeypatch):
    gid = routes.GUILD_ID
    actor_id = str(gid + 9000)
    bot_id = str(gid + 9001)
    target_id = str(gid + 9002)
    everyone = dict(id=str(gid), name="Everyone", position=0, permissions="0")
    low = dict(id=str(gid + 1), name="Low", position=1, permissions="0")
    actor_role = dict(
        id=str(gid + 2),
        name="Actor",
        position=10,
        permissions=str((1 << 27) | (1 << 28)),
    )
    high = dict(id=str(gid + 3), name="Higher", position=20, permissions="0")
    bot_role = dict(
        id=str(gid + 4), name="Bot", position=30, permissions=str((1 << 27) | (1 << 28))
    )
    members = [
        dict(
            user=dict(id=actor_id, username="actor"),
            roles=[actor_role["id"]],
            nick=None,
        ),
        dict(
            user=dict(id=bot_id, username="bot", bot=True),
            roles=[bot_role["id"]],
            nick=None,
        ),
        dict(
            user=dict(id=target_id, username="target"), roles=[low["id"]], nick="Before"
        ),
    ]
    actor = dict(
        user_id=actor_id,
        member=members[0],
        roles=[everyone, low, actor_role, high, bot_role],
        guild={"owner_id": str(gid + 9999)},
    )
    shared = dict(
        actor=actor,
        members=members,
        calls=[],
        auth=[],
        allowed=True,
        profiles={},
        profile_reads=[],
    )

    async def require(request, section, *, write=False):
        shared["auth"].append((request.method, section, write))
        if not shared["allowed"]:
            raise web.HTTPForbidden(text="Access revoked")
        return actor

    async def discord(request, method, path, params=None):
        shared["calls"].append(path)
        if path.endswith("/members"):
            return shared["members"]
        if path == "/users/@me":
            return members[1]["user"]
        if path.endswith("/members/" + bot_id):
            return members[1]
        raise AssertionError(path)

    @asynccontextmanager
    async def mongo(request):
        yield S(member_profiles=None, bot_config=None)

    async def profiles(store, ids, **kwargs):
        shared["profile_reads"].append(tuple(ids))
        return {key: value for key, value in shared["profiles"].items() if key in ids}

    for module in (routes, member_role_runs):
        monkeypatch.setattr(module, "require_manage", require)
        monkeypatch.setattr(module, "mongo", mongo)
    monkeypatch.setattr(routes, "discord", discord)
    monkeypatch.setattr(manage_roles, "discord", discord)
    monkeypatch.setattr(routes.MemberProfiles, "for_members", profiles)
    monkeypatch.setattr(
        manage_roles, "dashboard_grant_roles", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        member_role_runs, "dashboard_grant_roles", AsyncMock(return_value=set())
    )
    from utils.dashboard_access import AccessRepository

    monkeypatch.setattr(
        AccessRepository, "read", AsyncMock(return_value={"grants": []})
    )
    shared.update(
        target_id=target_id, actor_role=actor_role, high=high, low=low, bot_id=bot_id
    )
    return shared


async def client():
    app = web.Application()
    app[KEY] = DirectoryCache()
    from cwl_web.member_row_work import install

    install(app)
    app.router.add_get("/api/cwl/manage/members/overview", routes.members_overview)
    app.router.add_post(
        "/api/cwl/manage/members/role-preview", member_role_runs.preview
    )
    value = TestClient(TestServer(app))
    await value.start_server()
    return value


def test_real_http_hit_force_and_auth_remains_live(wire):
    async def run():
        c = await client()
        try:
            first = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert first["directory_cache"]["cached"] is False
            assert (
                len(wire["calls"]) == 2
            )  # One bounded page +bot identity, no duplicate hierarchy calls.
            second = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert (
                second["directory_cache"]["cached"] is True and len(wire["calls"]) == 2
            )
            assert second["members"] == first["members"] and len(wire["auth"]) == 2
            forced = await (
                await c.get("/api/cwl/manage/members/overview?refresh=1")
            ).json()
            assert (
                forced["directory_cache"]["cached"] is False and len(wire["calls"]) == 4
            )
            wire["allowed"] = False
            assert (await c.get("/api/cwl/manage/members/overview")).status == 403
            assert len(wire["auth"]) == 4
        finally:
            await c.close()

    asyncio.run(run())


def test_stale_directory_cannot_allow_role_preview_write(wire):
    async def run():
        c = await client()
        try:
            await c.get("/api/cwl/manage/members/overview")
            wire["members"][2]["roles"] = [wire["high"]["id"]]
            stale = await (await c.get("/api/cwl/manage/members/overview")).json()
            row = next(
                r for r in stale["members"] if r["discord_id"] == wire["target_id"]
            )
            assert (
                row["role_editable"] is True
            )  # Cached display is not write authority.
            response = await c.post(
                "/api/cwl/manage/members/role-preview",
                json=dict(
                    member_ids=[wire["target_id"]],
                    role_id=wire["low"]["id"],
                    operation="add",
                ),
            )
            assert response.status == 422
            assert wire["auth"][-1] == ("POST", "roles", True)
            assert wire["calls"].count(f"/guilds/{routes.GUILD_ID}/members") == 2
        finally:
            await c.close()

    asyncio.run(run())


def test_fresh_saved_profile_invalidates_cached_nickname_without_extra_normal_query(
    wire,
):
    async def run():
        c = await client()
        try:
            await c.get("/api/cwl/manage/members/overview")
            wire["members"][2]["nick"] = "After"
            wire["profiles"][wire["target_id"]] = dict(
                source="staff",
                updated_at=datetime.now(timezone.utc),
                zone_id="utc",
                gmt_label="GMT",
                revision=1,
            )
            result = await (await c.get("/api/cwl/manage/members/overview")).json()
            row = next(
                r for r in result["members"] if r["discord_id"] == wire["target_id"]
            )
            assert (
                row["nickname"] == "After" and not result["directory_cache"]["cached"]
            )
            assert len(wire["profile_reads"]) == 2
            again = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert (
                again["directory_cache"]["cached"] is True
                and len(wire["profile_reads"]) == 3
            )
        finally:
            await c.close()

    asyncio.run(run())


def test_profile_update_and_membership_race_reads_only_new_ids(wire):
    async def run():
        c = await client()
        try:
            await c.get("/api/cwl/manage/members/overview")
            wire["profiles"][wire["target_id"]] = dict(
                source="staff",
                updated_at=datetime.now(timezone.utc),
                zone_id="utc",
                gmt_label="GMT",
                revision=2,
            )
            new_id = str(routes.GUILD_ID + 9003)
            wire["members"].append(
                dict(user=dict(id=new_id, username="New member"), roles=[], nick=None)
            )
            result = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert len(result["members"]) == 4
            assert wire["profile_reads"][-1] == (new_id,)
            assert (
                len(wire["profile_reads"]) == 3
            )  # first, normal read, one-ID race repair
        finally:
            await c.close()

    asyncio.run(run())


def test_failed_fetch_is_not_cached_or_poisoned():
    async def run():
        cache = DirectoryCache()
        calls = []

        async def fetch():
            calls.append(True)
            if len(calls) == 1:
                raise web.HTTPServiceUnavailable(text="Fixture unavailable")
            return {"value": "recovered"}

        with pytest.raises(web.HTTPServiceUnavailable):
            await cache.read(fetch)
        assert cache.value is None
        assert (await cache.read(fetch)).value == {"value": "recovered"}
        assert (await cache.read(fetch)).cached and len(calls) == 2

    asyncio.run(run())


def test_cached_directory_recalculates_live_actor_hierarchy(wire):
    async def run():
        c = await client()
        try:
            first = await (await c.get("/api/cwl/manage/members/overview")).json()
            prior = next(
                row
                for row in first["members"]
                if row["discord_id"] == wire["target_id"]
            )
            assert prior["role_editable"]
            wire["actor"]["member"]["roles"] = []
            second = await (await c.get("/api/cwl/manage/members/overview")).json()
            changed = next(
                row
                for row in second["members"]
                if row["discord_id"] == wire["target_id"]
            )
            assert second["directory_cache"]["cached"] and not changed["role_editable"]
            assert second["manageable_roles"] == [] and len(wire["calls"]) == 2
        finally:
            await c.close()

    asyncio.run(run())


def test_missing_bot_nickname_permission_still_blocks_nickname_tools(wire):
    async def run():
        c = await client()
        try:
            wire["actor"]["roles"][-1]["permissions"] = "0"
            result = await (await c.get("/api/cwl/manage/members/overview")).json()
            row = next(
                row
                for row in result["members"]
                if row["discord_id"] == wire["target_id"]
            )
            assert row["skip_reason"] == "Bot needs Manage Nicknames"
        finally:
            await c.close()

    asyncio.run(run())


@pytest.mark.parametrize("role_run", [False, True])
def test_accepted_confirm_invalidates_raw_display_cache(monkeypatch, role_run):
    async def run():
        from utils.member_profile_runs import ProfileRuns
        import time

        module = member_role_runs if role_run else routes
        cache = DirectoryCache()
        request = S(
            app={KEY: cache},
            json=AsyncMock(
                return_value=dict(token="review", selected=[], protected_confirmed=True)
            ),
        )
        monkeypatch.setattr(
            module,
            "require_manage",
            AsyncMock(return_value={"user_id": "800000000000000001"}),
        )

        @asynccontextmanager
        async def db(_):
            yield S(
                bot_config=S(
                    find_one=AsyncMock(return_value={"checked_at": time.time()})
                ),
                component_state=S(),
            )

        monkeypatch.setattr(module, "mongo", db)
        monkeypatch.setattr(
            ProfileRuns,
            "confirm",
            AsyncMock(return_value={"_id": "run", "state": "queued"}),
        )
        await (module.confirm if role_run else module.standardize_confirm)(request)
        assert cache.generation == 1
        monkeypatch.setattr(
            ProfileRuns, "confirm", AsyncMock(side_effect=ValueError("Review expired"))
        )
        with pytest.raises(web.HTTPConflict):
            await (module.confirm if role_run else module.standardize_confirm)(request)
        assert (
            cache.generation == 1
        )  # Refused writes do not pretend to update anything.

    asyncio.run(run())


@pytest.mark.parametrize("role_run", [False, True])
def test_existing_run_receipts_invalidate_on_completion_without_new_poll(
    monkeypatch, role_run
):
    async def run():
        from utils.member_profile_runs import ProfileRuns

        module = member_role_runs if role_run else routes
        cache = DirectoryCache()
        request = S(app={KEY: cache}, match_info={"run_id": "run"})
        monkeypatch.setattr(
            module,
            "require_manage",
            AsyncMock(return_value={"user_id": "800000000000000001"}),
        )

        @asynccontextmanager
        async def db(_):
            yield S(bot_config=S(), component_state=S())

        monkeypatch.setattr(module, "mongo", db)
        row = dict(_id="run", state="done", items=[], user_id="800000000000000001")
        status = AsyncMock(return_value=(row, [dict(_id="run:0", status="done")]))
        monkeypatch.setattr(ProfileRuns, "status", status)
        await (module.status if role_run else module.standardize_status)(request)
        assert cache.generation == 1 and status.await_count == 1
        await (module.status if role_run else module.standardize_status)(request)
        assert cache.generation == 1 and status.await_count == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "section,action", [("roles", "bulk_one"), ("member_profiles", "save")]
)
def test_accepted_single_write_and_existing_receipt_invalidate(
    monkeypatch, section, action
):
    async def run():
        from cwl_web import server_management as shared, app as actual
        from utils.manage_web_worker import WORKER_ID
        import time

        cache = DirectoryCache()
        request = S(
            app={KEY: cache},
            json=AsyncMock(return_value={}),
            match_info={"request_id": "job"},
        )
        saved = {}

        async def find(query):
            if query["_id"] == WORKER_ID:
                return {"checked_at": time.time()}
            return saved

        async def insert(row):
            saved.update(row)

        @asynccontextmanager
        async def db(_):
            yield S(bot_config=S(find_one=find, insert_one=insert))

        monkeypatch.setattr(shared, "mongo", db)
        monkeypatch.setattr(
            shared,
            "require_manage",
            AsyncMock(return_value={"user_id": "800000000000000001"}),
        )
        monkeypatch.setattr(
            actual, "_require", lambda _: {"user_id": "800000000000000001"}
        )
        await shared.queue_action(request, section, action, {}, "fixture")
        assert cache.generation == 1
        saved["status"] = "done"
        await shared.request_status(request)
        assert cache.generation == 2
        await shared.request_status(request)
        assert cache.generation == 2

    asyncio.run(run())


def test_new_reader_never_inherits_last_reader_cancelled_fetch():
    async def run():
        cache = DirectoryCache()
        entered, cleanup = asyncio.Event(), asyncio.Event()

        async def old():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup.wait()

        task = asyncio.create_task(cache.read(old))
        await entered.wait()
        producer = cache.pending.task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        try:
            assert cache.pending is None

            async def fresh():
                return {"value": "fresh"}

            assert (await asyncio.wait_for(cache.read(fresh), 1)).value == {
                "value": "fresh"
            }
        finally:
            cleanup.set()
            await asyncio.gather(producer, return_exceptions=True)

    asyncio.run(run())


def test_http_row_work_uses_private_worker_and_recovers_after_async_error(
    wire, monkeypatch
):
    async def run():
        import threading

        main = threading.get_ident()
        threads = []
        fail = [True]
        original_inventory, original_roles = routes.inventory_rows, routes.role_rows

        def inventory(*args):
            threads.append(threading.get_ident())
            if fail[0]:
                fail[0] = False
                raise RuntimeError("Fixture row failure")
            return original_inventory(*args)

        def roles(*args):
            threads.append(threading.get_ident())
            return original_roles(*args)

        monkeypatch.setattr(routes, "inventory_rows", inventory)
        monkeypatch.setattr(routes, "role_rows", roles)
        c = await client()
        try:
            assert (await c.get("/api/cwl/manage/members/overview")).status == 500
            response = await c.get("/api/cwl/manage/members/overview")
            assert response.status == 200
            data = await response.json()
            assert len(data["members"]) == 3 and data["directory_cache"]["cached"]
            assert len(threads) == 3 and all(thread != main for thread in threads)
        finally:
            await c.close()

    asyncio.run(run())


def test_cached_bot_membership_cannot_allow_role_preview_after_bot_loses_roles(wire):
    async def run():
        c = await client()
        try:
            first = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert wire["low"]["id"] in {row["id"] for row in first["manageable_roles"]}
            wire["members"][1]["roles"] = []
            stale = await (await c.get("/api/cwl/manage/members/overview")).json()
            assert stale["directory_cache"]["cached"]
            assert wire["low"]["id"] in {row["id"] for row in stale["manageable_roles"]}
            response = await c.post(
                "/api/cwl/manage/members/role-preview",
                json=dict(
                    member_ids=[wire["target_id"]],
                    role_id=wire["low"]["id"],
                    operation="add",
                ),
            )
            assert (
                response.status == 422
                and (await response.json())["code"] == "role_refused"
            )
            assert wire["auth"][-1] == ("POST", "roles", True)
        finally:
            await c.close()

    asyncio.run(run())


def test_force_never_joins_or_publishes_an_older_plain_read():
    async def run():
        cache = DirectoryCache()
        entered, release = asyncio.Event(), asyncio.Event()

        async def old():
            entered.set()
            await release.wait()
            return {"value": "old"}

        async def fresh():
            return {"value": "new"}

        pending = asyncio.create_task(cache.read(old))
        await entered.wait()
        result = await cache.read(fresh, force=True)
        assert result.value == {"value": "new"} and not result.cached
        release.set()
        assert (await pending).value == {"value": "old"}
        hit = await cache.read(old)
        assert hit.cached and hit.value == {"value": "new"}

    asyncio.run(run())


def test_simultaneous_profiles_share_only_inflight_generation_and_mode():
    async def run():
        cache = DirectoryCache()
        release, entered = asyncio.Event(), asyncio.Event()
        calls = []

        async def fetch():
            calls.append(True)
            entered.set()
            await release.wait()
            return {"id": {"revision": len(calls)}}

        tasks = [asyncio.create_task(cache.profiles(["1"], fetch)) for _ in range(8)]
        await entered.wait()
        await asyncio.sleep(0)
        assert len(calls) == 1
        forced = asyncio.create_task(cache.profiles(["1"], fetch, force=True))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(calls) == 2
        release.set()
        values = await asyncio.gather(*tasks, forced)
        values[0]["id"]["revision"] = 999
        assert values[1]["id"]["revision"] != 999
        await asyncio.sleep(0)
        await cache.profiles(["1"], fetch)
        assert len(calls) == 3 and not cache.profile_pending

    asyncio.run(run())


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/cwl/manage/members/overview", True),
        ("POST", "/api/cwl/manage/members/overview", False),
        ("GET", "/api/cwl/manage/members/overview/", False),
        ("GET", "/api/cwl/manage/members", False),
        ("GET", "/api/cwl/manage/member-profiles", False),
    ],
)
def test_eligible_is_only_the_exact_read_only_overview(method, path, expected):
    from cwl_web.member_directory_cache import eligible

    assert eligible(S(method=method, path=path)) is expected


def test_eight_stale_readers_share_profile_fetch_and_one_fresh_directory(
    wire, monkeypatch
):
    async def run():
        c = await client()
        try:
            await c.get("/api/cwl/manage/members/overview")
            wire["members"][2]["nick"] = "Saved nickname"
            wire["profiles"][wire["target_id"]] = dict(
                source="staff",
                updated_at=datetime.now(timezone.utc),
                zone_id="utc",
                gmt_label="GMT",
                revision=1,
            )
            original = routes.MemberProfiles.for_members
            entered, release = asyncio.Event(), asyncio.Event()

            async def blocked(store, ids, **kwargs):
                entered.set()
                await release.wait()
                return await original(store, ids, **kwargs)

            monkeypatch.setattr(routes.MemberProfiles, "for_members", blocked)
            pending = [
                asyncio.create_task(c.get("/api/cwl/manage/members/overview"))
                for _ in range(8)
            ]
            await entered.wait()

            async def all_waiting():
                while (
                    sum(
                        entry.readers
                        for entry in c.server.app[KEY].profile_pending.values()
                    )
                    != 8
                ):
                    await asyncio.sleep(0)

            await asyncio.wait_for(all_waiting(), 2)
            release.set()
            responses = await asyncio.gather(*pending)
            results = [await response.json() for response in responses]
            assert len(wire["profile_reads"]) == 2
            assert wire["calls"].count(f"/guilds/{routes.GUILD_ID}/members") == 2
            assert all(
                next(
                    r for r in data["members"] if r["discord_id"] == wire["target_id"]
                )["nickname"]
                == "Saved nickname"
                for data in results
            )
        finally:
            await c.close()

    asyncio.run(run())


@pytest.mark.parametrize("uncertain", [False, True])
def test_direct_role_write_invalidates_before_transport_even_on_uncertainty(
    monkeypatch, uncertain
):
    async def run():
        cache = DirectoryCache()
        await cache.read(AsyncMock(return_value={"old": True}))
        target_id, role_id = "800000000000000001", "800000000000000002"
        role = S(name="Member")
        request = S(
            app={KEY: cache},
            match_info={"action": "add"},
            json=AsyncMock(
                return_value={"values": {"member_id": target_id, "role_ids": [role_id]}}
            ),
        )
        target = S(role_ids=[])

        async def transport(request, method, path):
            if method == "GET":
                return {"unused": True}
            assert cache.value is None
            if uncertain:
                raise web.HTTPServiceUnavailable()

        monkeypatch.setattr(manage_roles, "require_manage", AsyncMock(return_value={}))
        monkeypatch.setattr(
            manage_roles, "dashboard_grant_roles", AsyncMock(return_value=set())
        )
        monkeypatch.setattr(
            manage_roles,
            "hierarchy",
            AsyncMock(return_value=({int(role_id): role}, S(), S(), S())),
        )
        monkeypatch.setattr(manage_roles, "member", lambda value: target)
        monkeypatch.setattr(manage_roles, "role_is_manageable", lambda *args: True)
        monkeypatch.setattr(
            manage_roles.perms, "actor_can_manage_member", lambda *args: True
        )
        monkeypatch.setattr(
            manage_roles.perms, "actor_can_manage_role", lambda *args: True
        )
        monkeypatch.setattr(manage_roles, "discord", transport)
        if uncertain:
            with pytest.raises(web.HTTPServiceUnavailable):
                await manage_roles.change(request)
        else:
            assert (await manage_roles.change(request)).status == 200
        assert cache.value is None

    asyncio.run(run())
