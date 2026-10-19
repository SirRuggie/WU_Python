"""Live Discord authorization boundaries for management editors."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from cwl_web import server_management as manage


def test_permission_boundaries_match_native_manage():
    async def scenario():
        db = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={'ticket_target_guild_id': manage.GUILD_ID})))
        ordinary = {'permissions': 0, 'role_ids': set()}
        editor = {'permissions': 32, 'role_ids': set()}
        admin = {'permissions': 8, 'role_ids': set()}
        fwa_rep = {'permissions': 0, 'role_ids': {769130325460254740}}
        for section in ('recruit', 'recruitment_questions', 'recruitment_staff_thread'):
            assert not await manage.allowed(ordinary, section, db, write=True)
            assert await manage.allowed(editor, section, db, write=True)
        # Native FWA messages requires the actual representative role even for admins.
        assert not await manage.allowed(admin, 'fwa_war_messages', db, write=True)
        assert await manage.allowed(fwa_rep, 'fwa_war_messages', db, write=True)
        assert not await manage.allowed(editor, 'ticket_settings', db, write=True)
        assert await manage.allowed(admin, 'ticket_settings', db, write=True)
        assert not await manage.allowed(admin, 'unknown', db, write=True)
    asyncio.run(scenario())


def test_identity_refreshes_roles_on_every_new_request():
    async def scenario():
        from cwl_web import app
        roles = [{'id': str(manage.GUILD_ID), 'permissions': '0'}, {'id': '1', 'permissions': '32'}]
        current_roles = ['1']
        async def discord(request, method, path, **kwargs):
            if path.endswith('/roles'):
                return roles
            if '/members/' in path:
                return {'user': {'id': '123'}, 'roles': current_roles.copy()}
            return {'owner_id': '999'}
        with patch.object(app, '_require', return_value={'user_id': '123'}), patch.object(app, '_store', return_value=SimpleNamespace(one=lambda *args: None)), patch.object(manage, 'discord', discord):
            assert (await manage.identity({}))['permissions'] == 32
            current_roles.clear()
            assert (await manage.identity({}))['permissions'] == 0
    asyncio.run(scenario())


def test_ticket_testers_can_open_but_cannot_change_controls():
    async def scenario():
        from extensions.commands.tickets import testing_service
        db = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={})))
        actor = {'user_id':'123', 'permissions':0, 'role_ids':set()}
        window = {'mode':'test', 'guild_id':manage.GUILD_ID, 'allowed_user_ids':[123]}
        with patch.object(testing_service, 'test_mongo', return_value=object()), patch.object(testing_service, 'active_window', AsyncMock(return_value=window)):
            assert await manage.allowed(actor, 'ticket_testing', db, write=False)
            assert not await manage.allowed(actor, 'ticket_testing', db, write=True)
            actor['user_id'] = '456'
            assert not await manage.allowed(actor, 'ticket_testing', db, write=False)
    asyncio.run(scenario())


def test_roles_invalid_body_rejected_before_discord_change():
    async def scenario():
        from cwl_web import manage_roles
        from aiohttp import web
        actor = {'user_id':'123'}
        request = SimpleNamespace(match_info={'action':'add'}, json=AsyncMock(return_value=[]))
        with patch.object(manage_roles, 'require_manage', AsyncMock(return_value=actor)), patch.object(manage_roles, 'discord', AsyncMock()) as transport:
            with pytest.raises(web.HTTPBadRequest):
                await manage_roles.change(request)
            transport.assert_not_awaited()
    asyncio.run(scenario())
