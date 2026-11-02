"""HTTP boundaries reject unauthorized or malformed role actions before work."""

import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import member_role_runs as routes

USER = "123456789012345678"
ROLE = "345678901234567890"


def test_every_role_run_route_denies_viewer_before_body_or_provider(monkeypatch):
    async def run():
        gate = AsyncMock(side_effect=web.HTTPForbidden())
        monkeypatch.setattr(routes, "require_manage", gate)
        directory = AsyncMock()
        monkeypatch.setattr(routes, "directory", directory)
        request = S(json=AsyncMock(), match_info={})
        for handler in (
            routes.preview,
            routes.confirm,
            routes.runs,
            routes.status,
            routes.stop,
        ):
            with pytest.raises(web.HTTPForbidden):
                await handler(request)
        request.json.assert_not_awaited()
        directory.assert_not_awaited()
        assert all(call.args[1] == "roles" for call in gate.await_args_list)
        assert gate.await_args_list[-1].kwargs.get("write") is True

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"member_ids": []},
        {"member_ids": [USER, USER]},
        {"member_ids": ["bad"]},
        {"role_id": "bad"},
        {"operation": "send"},
        {"unknown": True},
    ],
)
def test_malformed_preview_is_not_a_durable_action(change):
    body = dict(member_ids=[USER], role_id=ROLE, operation="add")
    body.update(change)
    with pytest.raises(ValueError):
        routes.body_selection(body)


def test_selection_count_is_exact_and_ids_are_not_silently_dropped():
    assert routes.body_selection(
        dict(member_ids=[USER], role_id=ROLE, operation="remove")
    ) == ([USER], ROLE, "remove")


def test_confirmation_without_explicit_protected_field_is_not_queued(monkeypatch):
    async def run():
        monkeypatch.setattr(
            routes, "require_manage", AsyncMock(return_value={"user_id": USER})
        )
        request = S(json=AsyncMock(return_value={"token": "x", "selected": [USER]}))
        with pytest.raises(web.HTTPBadRequest):
            await routes.confirm(request)

    asyncio.run(run())


def test_undo_guard_is_bounded_to_one_person_and_valid_roles():
    good = dict(
        member_ids=[USER], role_id=ROLE, operation="remove", guard_role_ids=[ROLE]
    )
    assert routes.body_selection(good) == ([USER], ROLE, "remove")
    for guard in ([ROLE, ROLE], ["bad"], {}, [ROLE] * 251):
        with pytest.raises(ValueError):
            routes.body_selection(dict(good, guard_role_ids=guard))
    with pytest.raises(ValueError):
        routes.body_selection(dict(good, member_ids=[USER, "234567890123456789"]))


def test_members_login_redirect_keeps_valid_person_and_canonicalizes_old_page():
    from types import SimpleNamespace
    from cwl_web.app import login_destination, saved_login_destination

    person = "111111111111111111"
    expected = "/server/members?account=" + person
    for view in ("members-settings", "member-timezones"):
        for key in ("account", "member"):
            assert login_destination({"view": view, key: person}) == expected
            assert (
                login_destination({"view": view, key: "https://evil.invalid"})
                == "/server/members"
            )
    for path in ("/server/members", "/server/member-timezones"):
        assert (
            saved_login_destination(
                SimpleNamespace(cookies={"wu_login_page": path + "?member=" + person})
            )
            == expected
        )
    assert (
        saved_login_destination(
            SimpleNamespace(cookies={"wu_login_page": "//evil.invalid/server/members"})
        )
        == ""
    )


@pytest.mark.parametrize(
    "permissions, allowed",
    [
        ([], False),
        (["member_profiles"], False),
        (["member_roles"], True),
        (["member_roles", "member_profiles"], True),
    ],
)
def test_real_dashboard_policy_requires_existing_member_roles_for_confirmation(
    monkeypatch, permissions, allowed
):
    from contextlib import asynccontextmanager
    from cwl_web import server_management

    async def run():
        actor = {
            "user_id": USER,
            "dashboard": True,
            "role_ids": set(),
            "dashboard_scopes": permissions,
        }
        monkeypatch.setattr(
            server_management, "identity", AsyncMock(return_value=actor)
        )

        async def find(query, *args, **kwargs):
            return (
                {"permissions": permissions}
                if query.get("_id") == "dashboard-access:" + USER
                else None
            )

        db = S(bot_config=S(find_one=AsyncMock(side_effect=find)))

        @asynccontextmanager
        async def mongo(request):
            yield db

        monkeypatch.setattr(server_management, "mongo", mongo)
        request = S(
            json=AsyncMock(return_value={"token": "review", "selected": [USER]})
        )
        # Missing protected_confirmed is malformed only after authorization.
        with pytest.raises(web.HTTPBadRequest if allowed else web.HTTPForbidden):
            await routes.confirm(request)
        if allowed:
            request.json.assert_awaited_once()
        else:
            request.json.assert_not_awaited()

    asyncio.run(run())


def test_real_app_route_table_keeps_old_member_picker_and_ticket_fallback(
    tmp_path, monkeypatch
):
    from aiohttp.test_utils import TestClient, TestServer
    from cwl_web.app import create_app
    from cwl_web import manage_roles, member_timezones

    calls = []
    ticket_only = False

    async def gate(request, section, *args, **kwargs):
        calls.append(section)
        if ticket_only and section == "roles":
            raise web.HTTPForbidden()
        return {"user_id": USER, "roles": []}

    monkeypatch.setattr(manage_roles, "require_manage", gate)
    monkeypatch.setattr(
        manage_roles,
        "discord",
        AsyncMock(
            return_value=[
                {
                    "user": {
                        "id": USER,
                        "username": "Fixture picker",
                        "global_name": None,
                        "avatar": None,
                    },
                    "roles": [],
                    "nick": None,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        manage_roles, "dashboard_grant_roles", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        member_timezones,
        "inventory",
        AsyncMock(return_value=([], {}, S(), S(), S(), {"user_id": USER})),
    )

    async def run():
        nonlocal ticket_only
        app = create_app(db_path=str(tmp_path / "routes.sqlite"), dev_fixture=True)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for restricted in (False, True):
                ticket_only = restricted
                response = await client.get("/api/cwl/manage/members")
                assert response.status == 200
                data = await response.json()
                assert (
                    isinstance(data["options"], list)
                    and data["options"][0]["value"] == USER
                )
                assert "members" not in data
            assert "ticket_settings" in calls
            response = await client.get("/api/cwl/manage/members/overview")
            assert response.status == 200
            assert (await response.json())["members"] == []
        finally:
            await client.close()

    asyncio.run(run())


def test_undo_preview_rejects_changed_live_roles_without_creating_review(monkeypatch):
    from contextlib import asynccontextmanager
    import hikari

    async def run():
        monkeypatch.setattr(
            routes, "require_manage", AsyncMock(return_value={"user_id": USER})
        )
        role = S(id=int(ROLE), name="Fixture role", permissions=hikari.Permissions.NONE)
        monkeypatch.setattr(
            routes,
            "hierarchy",
            AsyncMock(return_value=({int(ROLE): role}, S(), S(), S())),
        )
        monkeypatch.setattr(routes, "role_is_manageable", lambda *args: True)
        monkeypatch.setattr(routes.perms, "actor_can_manage_role", lambda *args: True)
        monkeypatch.setattr(
            routes, "dashboard_grant_roles", AsyncMock(return_value=set())
        )
        db = S(bot_config=S(find_one=AsyncMock(return_value=None)))

        @asynccontextmanager
        async def mongo(request):
            yield db

        monkeypatch.setattr(routes, "mongo", mongo)
        monkeypatch.setattr(
            routes,
            "directory",
            AsyncMock(
                return_value=[{"user": {"id": USER, "bot": False}, "roles": [ROLE]}]
            ),
        )
        preview = AsyncMock()
        monkeypatch.setattr(routes.ProfileRuns, "preview", preview)
        request = S(
            json=AsyncMock(
                return_value=dict(
                    member_ids=[USER],
                    role_id=ROLE,
                    operation="remove",
                    guard_role_ids=[],
                )
            )
        )
        with pytest.raises(web.HTTPConflict) as error:
            await routes.preview(request)
        assert "roles changed" in error.value.text
        preview.assert_not_awaited()

    asyncio.run(run())
