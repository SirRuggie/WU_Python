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
                    'added_strikes': 1, 'history_only': 1, 'duplicates': 3,
                    'excluded': 1, 'skipped': [{'war': 'one'}, {'war': 'two'}]}

    async def permit(request, section, *, write=False):
        assert section == 'strikes_add'

    async def request_body(request, allowed):
        return {'preview_id': 'preview1234567890', 'excluded_keys': ['row1']}

    async def fake_service(request, db):
        return Ledger()

    @asynccontextmanager
    async def fake_mongo(request):
        yield object()

    async def run():
        app = {}
        request = SimpleNamespace(method='POST', app=app)
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', fake_mongo), \
             patch.object(strikes, 'body', request_body), \
             patch.object(strikes, 'service', fake_service), \
             patch('cwl_web.app._session', return_value={'user_id': '123'}):
            response = await strikes.import_apply(request)
            queued = json.loads(response.text)
            assert response.status == 202
            await asyncio.gather(*strikes._jobs(app)['tasks'])
            poll = SimpleNamespace(method='GET', app=app, match_info={'job_id': queued['job_id']})
            return await strikes.import_job(poll)

    response = asyncio.run(run())
    payload = json.loads(response.text)
    assert payload['result'] == {'applied': 2, 'strikes': 1, 'skipped': 4, 'skipped_wars': 2,
                                 'added_strikes': 1, 'history_only': 1, 'duplicates': 3, 'excluded': 1,
                                 'deferred_accounts': [], 'deferred_count': 0,
                                 'skipped_war_details': [{'war': 'one'}, {'war': 'two'}],
                                 'cwl_wars': 0, 'cwl_records': 0, 'cwl_missed': 0}


def test_confirmed_departed_discord_member_has_no_exempt_roles():
    async def missing(request, method, path):
        raise web.HTTPNotFound()

    async def run():
        request = SimpleNamespace(app={})
        with patch.object(strikes.shared, 'discord', missing):
            ledger = await strikes.service(request, object())
            assert await ledger.role_resolver(strikes.GUILD_ID, 123) == []
    asyncio.run(run())


def test_preview_api_separates_deferred_accounts_from_skipped_wars():
    from datetime import datetime, timezone
    from utils import strike_wars

    end = datetime(2026, 10, 19, tzinfo=timezone.utc)
    deferred = {'row_id': 'war:x', 'player_tag': '#PC9YGL0JL',
                'player_name': 'Player', 'clan_tag': '#2UVGQU9',
                'clan_name': 'Family', 'war_end': end,
                'missed_attacks': 2, 'reason': 'Account owner conflict'}

    class Ledger:
        async def preview_import(self, guild_id, wars, actor_id, *, cwl_wars=()):
            return {'preview_id': 'id123', 'wars': 1, 'items': [],
                    'summary': {'strikes': 0, 'accounts': 0, 'history_only': 0},
                    'existing': 0, 'deferred_accounts': [deferred],
                    'skipped': [{'war': '#2UVGQU9', 'reason': 'Account links unavailable'}]}

    async def fake_service(request, db):
        return Ledger()

    async def fake_clans(db):
        return [{'tag': '#2UVGQU9', 'name': 'Family'}]

    async def fake_history(clan_tag, days=90):
        return {'wars': [{'end_time': end}], 'skipped': [], 'source_count': 1}

    @asynccontextmanager
    async def fake_mongo(request):
        yield object()

    async def run():
        with patch.object(strikes.shared, 'mongo', fake_mongo), \
             patch.object(strikes, 'service', fake_service), \
             patch.object(strikes, 'clan_rows', fake_clans), \
             patch.object(strike_wars, 'fetch_history_report', fake_history):
            return await strikes._preview_work({}, 123, 90)
    result = asyncio.run(run())
    assert result['summary'] == {'strikes': 0, 'accounts': 0, 'history_only': 0}
    assert result['deferred_count'] == 1
    assert result['deferred_accounts'][0]['war_end'] == end.isoformat()
    assert result['incomplete_wars'] == 1
    assert result['coverage'][0]['deferred_accounts'] == 1
    assert result['coverage'][0]['processing_skipped_wars'] == 1
