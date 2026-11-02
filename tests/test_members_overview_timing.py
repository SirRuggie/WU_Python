"""Request timing is private, byte-neutral and never a new request failure."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, patch
import logging
import pytest
from aiohttp import web
import hikari
from cwl_web import member_timezones as routes, manage_roles, server_management
from cwl_web import members_overview_timing as timing

G = routes.GUILD_ID


def fixture(monkeypatch):
    actor_id, bot_id = G + 9001, G + 9002
    roles = {
        G: S(id=G, name="Everyone", position=0, permissions=0, is_managed=False),
        G + 1: S(id=G + 1, name="Low", position=1, permissions=0, is_managed=False),
        G + 2: S(id=G + 2, name="Actor", position=10, permissions=0, is_managed=False),
        G
        + 3: S(
            id=G + 3,
            name="Bot",
            position=20,
            permissions=int(
                hikari.Permissions.MANAGE_NICKNAMES | hikari.Permissions.MANAGE_ROLES
            ),
            is_managed=False,
        ),
    }
    acting = S(id=actor_id, guild_id=G, role_ids=(G + 2,))
    me = S(id=bot_id, guild_id=G, role_ids=(G + 3,))
    guild = S(
        id=G,
        owner_id=G + 20000,
        get_role=roles.get,
        get_member=lambda uid: me if int(uid) == bot_id else None,
    )
    bot = S(get_me=lambda: S(id=bot_id))
    raw = [
        dict(
            user=dict(
                id=str(G + 20000 + i),
                username="PRIVATE_USERNAME",
                global_name="PRIVATE_NAME",
            ),
            roles=[str(G + 1)],
            nick=None,
        )
        for i in range(1450)
    ]
    raw[-1] = dict(
        user=dict(id=str(bot_id), username="PRIVATE_BOT", bot=True),
        roles=[str(G + 3)],
        nick=None,
    )

    async def discord(method, path, params=None):
        if path == "/users/@me":
            return dict(id=str(bot_id))
        assert path.endswith("/members")
        return raw[1000:] if params.get("after") else raw[:1000]

    calls = AsyncMock(side_effect=discord)
    gate = AsyncMock(return_value=dict(user_id=str(actor_id)))
    hierarchy = AsyncMock(return_value=(roles, guild, bot, acting))
    profiles = AsyncMock(return_value={})
    grants = AsyncMock(return_value=set())

    @asynccontextmanager
    async def mongo(*args):
        yield S(member_profiles=None)

    monkeypatch.setattr(routes, "require_manage", gate)

    async def dispatch(request, method, path, **kwargs):
        request.app = {"server_management_discord": calls}
        return await server_management.discord(request, method, path, **kwargs)

    monkeypatch.setattr(routes, "discord", dispatch)
    monkeypatch.setattr(routes, "hierarchy", hierarchy)
    monkeypatch.setattr(routes, "mongo", mongo)
    monkeypatch.setattr(routes.MemberProfiles, "for_members", profiles)
    monkeypatch.setattr(manage_roles, "dashboard_grant_roles", grants)
    return calls, gate, hierarchy, profiles, grants


def test_one_numeric_line_no_identity_and_byte_identical_with_without_timing(
    monkeypatch, caplog
):
    calls = fixture(monkeypatch)
    request = S()

    async def run():
        with patch.object(timing, "OverviewTiming", timing.NoTiming):
            baseline = await routes.members_overview(request)
        before = [mock.await_count for mock in calls]
        response = await routes.members_overview(request)
        after = [mock.await_count for mock in calls]
        assert (
            response.body == baseline.body and response.status == baseline.status == 200
        )
        assert [b - a for a, b in zip(before, after)] == before == [3, 1, 1, 1, 1]
        assert b"PRIVATE_NAME" in response.body
        return response

    with caplog.at_level(logging.INFO, logger="cwl_web.member_timezones"):
        response = asyncio.run(run())
    records = [
        r for r in caplog.records if r.message.startswith("Members overview timing ")
    ]
    assert len(records) == 1
    line = records[0].message
    fields = dict(item.split("=", 1) for item in line.split()[3:])
    assert set(fields) == {
        "directory_ms",
        "hierarchy_ms",
        "profiles_ms",
        "rows_ms",
        "json_ms",
        "total_ms",
        "members",
        "roles",
        "discord_pages",
        "discord_requests",
        "bytes",
    }
    assert all(float(value) >= 0 for value in fields.values())
    assert fields["discord_requests"] == "3"
    assert (
        fields["members"] == "1450"
        and fields["roles"] == "4"
        and fields["discord_pages"] == "2"
        and int(fields["bytes"]) == len(response.body)
    )
    assert "PRIVATE" not in line and str(G) not in line and str(G + 20000) not in line


@pytest.mark.parametrize(
    "failure", ["clock", "clock_after_start", "logger", "constructor"]
)
def test_timing_failure_never_changes_the_successful_response(monkeypatch, failure):
    fixture(monkeypatch)
    request = S()

    async def run():
        with patch.object(timing, "OverviewTiming", timing.NoTiming):
            baseline = await routes.members_overview(request)

        def broken(*a, **kw):
            raise RuntimeError("PRIVATE_FAILURE")

        if failure == "clock":
            monkeypatch.setattr(timing, "perf_counter", broken)
        elif failure == "clock_after_start":
            count = 0

            def fails_after_start():
                nonlocal count
                count += 1
                return 0.0 if count == 1 else broken()

            monkeypatch.setattr(timing, "perf_counter", fails_after_start)
        elif failure == "logger":
            monkeypatch.setattr(timing.LOG, "info", broken)
        else:
            monkeypatch.setattr(timing, "OverviewTiming", broken)
        response = await routes.members_overview(request)
        assert response.status == 200 and response.body == baseline.body

    asyncio.run(run())


def test_denial_remains_denial_and_logs_no_exception_text(monkeypatch, caplog):
    calls = fixture(monkeypatch)
    calls[1].side_effect = web.HTTPForbidden(text="PRIVATE_AUTH_ERROR")

    async def run():
        with pytest.raises(web.HTTPForbidden):
            await routes.members_overview(S())

    with caplog.at_level(logging.INFO, logger="cwl_web.member_timezones"):
        asyncio.run(run())
    calls[0].assert_not_awaited()
    calls[2].assert_not_awaited()
    calls[3].assert_not_awaited()
    records = [
        r for r in caplog.records if r.message.startswith("Members overview timing ")
    ]
    assert (
        len(records) == 1
        and "PRIVATE" not in records[0].message
        and "members=0" in records[0].message
    )


def test_counter_tracks_existing_injected_dispatch_without_extra_calls():
    from cwl_web import server_management

    async def run():
        injected = AsyncMock(return_value={"unchanged": "body"})
        request = S(app={"server_management_discord": injected})
        recorder = timing.OverviewTiming()
        binding = timing.bind(request, recorder)
        try:
            assert await server_management.discord(request, "GET", "/users/@me") == {
                "unchanged": "body"
            }
            injected.assert_awaited_once_with("GET", "/users/@me")
            assert recorder.requests == 1
        finally:
            timing.unbind(request, binding)
        assert not hasattr(request, timing.KEY)

    asyncio.run(run())
