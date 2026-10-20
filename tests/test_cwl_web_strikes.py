"""Isolated strike route guards and response-shape regressions."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
import pytest

from cwl_web import strikes


def test_mutation_authorization_runs_before_handler():
    called = []

    async def deny(request, section, *, write=False):
        assert section == 'strikes'
        assert write is True
        raise web.HTTPForbidden(text='No strike access')

    @strikes.endpoint
    async def mutating_handler(request):
        called.append(True)
        return web.json_response({'ok': True})

    async def run():
        with patch.object(strikes.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await mutating_handler(SimpleNamespace(method='POST'))

    asyncio.run(run())
    assert called == []


@pytest.mark.parametrize('value', [True, 1.0, '1.0', '１', '-1', None])
def test_number_rejects_ambiguous_input(value):
    with pytest.raises(ValueError):
        strikes.number(value)


def test_completed_war_is_not_labeled_one_missed():
    row = {'_id': 'done', 'player_tag': '#PC9YGL0JL', 'kind': 'completed',
           'status': 'completed', 'source': 'war', 'occurred_at': '2026-10-19T12:00:00+00:00',
           'missed_attacks': 0}
    visible = strikes.entry(row, {})
    assert visible['status'] != 'recorded'
    assert visible['kind'] != 'miss'


def test_import_apply_returns_numeric_skipped_count():
    class Ledger:
        async def apply_import(self, guild_id, preview_id, actor_id, excluded_keys=()):
            assert guild_id == strikes.GUILD_ID
            assert preview_id == 'preview1234567890'
            assert actor_id == 123
            assert excluded_keys == ['row1']
            return {'applied': 2, 'strikes': 1, 'existing': 3,
                    'excluded': 1, 'skipped': [{'war': 'one'}, {'war': 'two'}]}

    async def permit(request, section, *, write=False):
        assert section == 'strikes_add' and write is True

    async def request_body(request, allowed):
        return {'preview_id': 'preview1234567890', 'excluded_keys': ['row1']}

    async def fake_service(request, db):
        return Ledger()

    @asynccontextmanager
    async def fake_mongo(request):
        yield object()

    async def run():
        request = SimpleNamespace(method='POST')
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', fake_mongo), \
             patch.object(strikes, 'body', request_body), \
             patch.object(strikes, 'service', fake_service), \
             patch('cwl_web.app._session', return_value={'user_id': '123'}):
            return await strikes.import_apply(request)

    response = asyncio.run(run())
    payload = json.loads(response.text)
    assert payload == {'applied': 2, 'strikes': 1, 'skipped': 4, 'skipped_wars': 2}
