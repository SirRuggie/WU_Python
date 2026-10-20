"""Strike grants are separate for reading, adding, and removing."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import hikari
import pytest
from aiohttp import web

from cwl_web.access_control import dashboard_allowed, scopes
from cwl_web import strikes as api
from extensions.commands import strikes as discord


class Config:
    def __init__(self, permissions):
        self.permissions = permissions

    async def find_one(self, query):
        assert query == {'_id': 'dashboard-access:123'}
        return {'permissions': list(self.permissions)}


class Mongo:
    def __init__(self, permissions):
        self.bot_config = Config(permissions)


def context(*, admin=False, guild=None):
    guild = guild if guild is not None else discord.WARRIORS_UNITED_GUILD_ID
    member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR if admin else hikari.Permissions.NONE)
    return SimpleNamespace(interaction=SimpleNamespace(guild_id=guild, member=member,
                                                      values=['#PC9YGL0JL']),
                           user=SimpleNamespace(id=123))


def test_add_only_grant_can_read_and_add_but_cannot_remove():
    async def run():
        ctx, db = context(), Mongo(['strikes_add'])
        assert await discord.authorized(ctx, db) is True
        assert await discord.authorized(ctx, db, 'strikes_add') is True
        assert await discord.authorized(ctx, db, 'strikes_remove') is False
        actor = {'user_id': '123', 'dashboard_scopes': ['strikes_add']}
        assert await dashboard_allowed(actor, 'strikes_read', db) is True
        assert await dashboard_allowed(actor, 'strikes_add', db) is True
        assert await dashboard_allowed(actor, 'strikes_remove', db) is False
        assert await dashboard_allowed(actor, 'strikes', db) is False
    asyncio.run(run())


def test_remove_only_grant_can_read_and_remove_but_cannot_add():
    async def run():
        ctx, db = context(), Mongo(['strikes_remove'])
        assert await discord.authorized(ctx, db) is True
        assert await discord.authorized(ctx, db, 'strikes_remove') is True
        assert await discord.authorized(ctx, db, 'strikes_add') is False
    asyncio.run(run())


def test_shared_grant_revocation_takes_effect_on_next_check():
    async def run():
        db = Mongo(['strikes_add'])
        ctx = context()
        assert await discord.authorized(ctx, db, 'strikes_add') is True
        db.bot_config.permissions.clear()
        assert await discord.authorized(ctx, db, 'strikes_add') is False
        assert await discord.authorized(ctx, db) is False
    asyncio.run(run())


def test_web_requires_both_local_and_shared_grants():
    async def run():
        db = Mongo(['strikes_add'])
        actor = {'user_id': '123', 'dashboard_scopes': []}
        assert await dashboard_allowed(actor, 'strikes_read', db) is False
        assert await dashboard_allowed(actor, 'strikes_add', db) is False
        actor['dashboard_scopes'] = ['strikes_add']
        assert await dashboard_allowed(actor, 'strikes_add', db) is True
        db.bot_config.permissions.clear()
        assert await dashboard_allowed(actor, 'strikes_add', db) is False
    asyncio.run(run())


def test_admin_bypass_stays_in_configured_guild():
    async def run():
        db = Mongo([])
        assert await discord.authorized(context(admin=True), db, 'strikes_remove') is True
        assert await discord.authorized(context(admin=True, guild=999), db, 'strikes_remove') is False
    asyncio.run(run())


def test_pick_rechecks_add_grant_before_account_resolution():
    async def run():
        ctx, db = context(), Mongo([])
        state = {'guild_id': discord.WARRIORS_UNITED_GUILD_ID,
                 'user_id': 123, 'member_id': 456,
                 'tags': ['#PC9YGL0JL'], 'reason': 'test', 'request_id': 'request1234567890'}
        async def selected(*args):
            return state
        async def should_not_lookup(*args):
            raise AssertionError('Account lookup must not run after grant revocation')
        with patch.object(discord, '_state', selected), \
             patch.object(discord.recruit_links, 'resolve', should_not_lookup):
            result = await discord.pick(ctx, 'token', mongo=db, coc_client=object())
        assert isinstance(result, list)
    asyncio.run(run())


def test_route_scope_checks_precede_mutating_handler():
    called = []

    @api.endpoint(scope='strikes_remove')
    async def remove_handler(request):
        called.append(True)
        return web.json_response({'ok': True})

    async def deny(request, section, *, write=False):
        assert section == 'strikes_remove' and write is True
        raise web.HTTPForbidden(text='No remove grant')

    async def run():
        with patch.object(api.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await remove_handler(SimpleNamespace(method='POST'))
    asyncio.run(run())
    assert called == []


def test_local_scopes_include_split_grants():
    class Store:
        def one(self, query, args):
            return {'permissions': '["strikes_add", "strikes_remove", "bogus"]'}
    assert scopes(Store(), '123') == ['strikes_add', 'strikes_remove']


@pytest.mark.parametrize('handler,expected', [
    (api.manual, 'strikes_add'),
    (api.import_preview, 'strikes_add'),
    (api.import_apply, 'strikes_add'),
    (api.remove, 'strikes_remove'),
])
def test_real_mutation_routes_check_their_grant_before_body(handler, expected):
    async def deny(request, section, *, write=False):
        assert section == expected and write is True
        raise web.HTTPForbidden(text='Grant required')

    async def fail_body(request, allowed):
        raise AssertionError('Body must not be parsed before authorization')

    async def run():
        with patch.object(api.shared, 'require_manage', deny), \
             patch.object(api, 'body', fail_body):
            with pytest.raises(web.HTTPForbidden):
                await handler(SimpleNamespace(method='POST'))
    asyncio.run(run())
