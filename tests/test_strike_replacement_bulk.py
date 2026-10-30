"""Bulk replacement selection verifies live clan membership and preserves manual marks."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web

from cwl_web import strikes
from cwl_web.providers import LiveProviders, ProviderUnavailable


CLAN = '#2UVGQU9'
P1 = '#PC9YGL0JL'
P2 = '#8GG82'


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows


class Db:
    def __init__(self, *, registered=True, existing=(), existing_clans=None):
        self.registered = registered
        self.existing = {value: CLAN for value in existing}
        self.existing.update(existing_clans or {})
        self.clans = self
        self.strike_profiles = self

    async def find_one(self, query, projection=None):
        return {'tag': CLAN} if self.registered and query['tag'] == CLAN else None

    def find(self, query, projection=None):
        return Cursor([{'player_tag': value, 'replacement_listed': True,
                        'replacement_clan_tag': clan}
                       for value, clan in self.existing.items()
                       if value in query['player_tag']['$in']])


class Provider:
    def __init__(self, members=(P1, P2)):
        self.members = members
        self.calls = 0

    async def clan_roster(self, clan_tag):
        self.calls += 1
        assert clan_tag == CLAN
        return {'tag': CLAN, 'name': 'Family',
                'members': [{'tag': value, 'name': f'Player {i}'}
                            for i, value in enumerate(self.members)]}


class Ledger:
    def __init__(self):
        self.saved = []

    async def set_replacement_preference(self, guild_id, tag, priority, note, actor,
                                         *, clan_tag, player_name, town_hall=None, only_if_unmarked):
        assert guild_id == strikes.GUILD_ID and actor == 123
        assert clan_tag == CLAN and only_if_unmarked
        self.saved.append(tag)
        return {'player_tag': tag}


async def permit(request, section, *, write=False):
    assert section == ('strikes_read' if request.method == 'GET' else 'strikes')
    assert write is (request.method != 'GET')


@asynccontextmanager
async def mongo_context(request):
    yield request.app['db']


async def service(request, db):
    return request.app['ledger']


async def payload(request, allowed):
    return request.app['payload']


def run_post(data, *, registered=True, members=(P1, P2), existing=(), existing_clans=None):
    async def run():
        db = Db(registered=registered, existing=existing, existing_clans=existing_clans)
        ledger = Ledger()
        provider = Provider(members)
        request = SimpleNamespace(method='POST', app={'db': db, 'ledger': ledger,
                                  'providers': provider, 'payload': data})
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', mongo_context), \
             patch.object(strikes, 'service', service), \
             patch.object(strikes, 'body', payload), \
             patch('cwl_web.app._session', return_value={'user_id': '123'}):
            response = await strikes.bulk_add_replacement_list(request)
        return response, ledger, provider
    return asyncio.run(run())


def test_bulk_add_skips_existing_mark_without_overwriting():
    response, ledger, provider = run_post(
        {'clan_tag': CLAN, 'player_tags': [P1, P2], 'priority': 'high', 'note': 'Rotation'},
        existing=(P1,))
    data = json.loads(response.text)
    assert data['added'] == [P2] and data['skipped'] == [P1]
    assert data['added_count'] == data['skipped_count'] == 1
    assert ledger.saved == [P2] and provider.calls == 1


def test_duplicate_selection_rejected_before_network_or_writes():
    with pytest.raises(web.HTTPBadRequest) as error:
        run_post({'clan_tag': CLAN, 'player_tags': [P1, P1],
                  'priority': 'normal', 'note': ''})
    assert 'each account only once' in error.value.text


def test_unregistered_clan_and_departed_member_rejected_before_writes():
    data = {'clan_tag': CLAN, 'player_tags': [P1], 'priority': 'normal', 'note': ''}
    with pytest.raises(web.HTTPBadRequest) as error:
        run_post(data, registered=False)
    assert 'registered family clan' in error.value.text
    with pytest.raises(web.HTTPConflict) as error:
        run_post(data, members=(P2,))
    assert 'left this clan' in error.value.text


def test_roster_route_requires_view_scope_before_reading_provider():
    async def deny(request, section, *, write=False):
        assert section == 'strikes_read' and not write
        raise web.HTTPForbidden()
    async def run():
        with patch.object(strikes.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await strikes.replacement_roster(SimpleNamespace(method='GET'))
    asyncio.run(run())


def test_bulk_route_requires_manage_scope_before_reading_payload():
    async def deny(request, section, *, write=False):
        assert section == 'strikes' and write
        raise web.HTTPForbidden()
    async def run():
        with patch.object(strikes.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await strikes.bulk_add_replacement_list(SimpleNamespace(method='POST'))
    asyncio.run(run())


def test_bulk_routes_registered_and_roster_provider_rejects_partial_member_list():
    routes = {(route.method, route.path) for route in strikes.routes}
    assert ('GET', strikes.API + '/replacement-roster') in routes
    assert ('POST', strikes.API + '/replacement-list/bulk') in routes

    async def run():
        provider = LiveProviders(coc_token='fixture')
        async def partial(kind, value):
            return {'tag': CLAN, 'name': 'Family', 'members': 2,
                    'memberList': [{'tag': P1, 'name': 'Player'}]}
        provider._coc = partial
        with pytest.raises(ProviderUnavailable, match='Incomplete Clash clan roster'):
            await provider.clan_roster(CLAN)
    asyncio.run(run())


def test_old_clan_mark_does_not_block_new_clan_bulk_add():
    response, ledger, _ = run_post(
        {'clan_tag': CLAN, 'player_tags': [P1], 'priority': 'high', 'note': ''},
        existing_clans={P1: '#8GG82'})
    data = json.loads(response.text)
    assert data['added'] == [P1] and data['skipped'] == []
    assert ledger.saved == [P1]


def test_roster_shows_old_clan_mark_as_unlisted():
    async def run():
        db = Db(existing_clans={P1: '#8GG82'})
        request = SimpleNamespace(method='GET', query={'clan': CLAN},
                                  app={'db': db, 'providers': Provider()})
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', mongo_context):
            return await strikes.replacement_roster(request)
    response = asyncio.run(run())
    assert json.loads(response.text)['accounts'][0]['is_manual'] is False


def test_conditional_bulk_write_scopes_existing_mark_to_current_clan():
    from utils.strike_store import StrikeService

    class Profiles:
        def __init__(self):
            self.query = None
        async def update_one(self, query, changes, upsert=False):
            self.query = query
    class Clans:
        async def find_one(self, query, projection=None):
            return {'tag': CLAN}
    async def run():
        profiles = Profiles()
        db = SimpleNamespace(clans=Clans(), strike_profiles=profiles)
        await StrikeService(db).set_replacement_preference(
            123, P1, 'high', '', 456, clan_tag=CLAN, only_if_unmarked=True)
        assert profiles.query['$nor'] == [
            {'replacement_listed': True, 'replacement_clan_tag': CLAN},
            {'filler': True, 'filler_clan_tag': CLAN}]
    asyncio.run(run())
