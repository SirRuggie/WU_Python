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
    good=dict(member_ids=[USER],role_id=ROLE,operation='remove',guard_role_ids=[ROLE])
    assert routes.body_selection(good)==([USER],ROLE,'remove')
    for guard in ([ROLE,ROLE],['bad'],{},[ROLE]*251):
        with pytest.raises(ValueError):routes.body_selection(dict(good,guard_role_ids=guard))
    with pytest.raises(ValueError):routes.body_selection(dict(good,member_ids=[USER,'234567890123456789']))


def test_members_login_redirect_keeps_valid_person_and_canonicalizes_old_page():
    from types import SimpleNamespace
    from cwl_web.app import login_destination, saved_login_destination
    person = '111111111111111111'
    expected = '/server/members?account=' + person
    for view in ('members-settings', 'member-timezones'):
        for key in ('account', 'member'):
            assert login_destination({'view': view, key: person}) == expected
            assert login_destination({'view': view, key: 'https://evil.invalid'}) == '/server/members'
    for path in ('/server/members', '/server/member-timezones'):
        assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': path+'?member='+person})) == expected
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': '//evil.invalid/server/members'})) == ''
