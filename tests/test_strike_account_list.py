"""Account-first strike browsing keeps each linked account separate."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cwl_web import strikes
from utils.strike_store import StrikeService

NOW = datetime.now(timezone.utc)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def __aiter__(self):
        for row in self.rows:
            yield row

    async def to_list(self, length=None):
        return self.rows


class Records:
    def __init__(self, rows):
        self.rows = rows
        self.pipeline = None

    async def aggregate(self, pipeline):
        self.pipeline = pipeline
        return Cursor(self.rows)

    async def distinct(self, field, query):
        assert field == 'player_tag'
        return ['#PLQ8']


class Profiles:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return Cursor([row for row in self.rows if row['player_tag'] in query['player_tag']['$in']])


def fixtures():
    rows = [
        {'_id': '#PC9YGL0JL', 'player_name': 'First', 'member_id': None,
         'active_strikes': 2, 'total_strikes': 3, 'last_strike_at': NOW, 'last_record_at': NOW},
        {'_id': '#8GG82', 'player_name': 'Second', 'member_id': None,
         'active_strikes': 0, 'total_strikes': 2,
         'last_strike_at': NOW - timedelta(days=100), 'last_record_at': NOW - timedelta(days=100)},
        {'_id': '#PLQ8', 'player_name': 'Missed Only', 'member_id': 123456789012345678,
         'active_strikes': 0, 'total_strikes': 0, 'last_strike_at': None,
         'last_record_at': NOW - timedelta(days=2)},
    ]
    profiles = [
        {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9',
         'roster_seen_at': NOW, 'player_name': 'First Now'},
        {'player_tag': '#8GG82', 'current_clan_tag': '#2UVGQU9',
         'roster_seen_at': NOW - timedelta(days=1)},
    ]
    records = Records(rows)
    return StrikeService(SimpleNamespace(strike_records=records,
                                         strike_settings=SimpleNamespace(find_one=AsyncMock(return_value=None)),
                                         strike_profiles=Profiles(profiles))), records


def test_account_list_default_active_and_all_historical():
    ledger, records = fixtures()

    async def run():
        active = await ledger.account_list(1)
        all_rows = await ledger.account_list(1, status='all')
        return active, all_rows

    active, all_rows = asyncio.run(run())
    assert active['total'] == 1
    assert active['items'][0]['player_tag'] == '#PC9YGL0JL'
    assert all_rows['total'] == 3
    assert all_rows['items'][1]['active_strikes'] == 0
    assert all_rows['items'][1]['current_clan_tag'] == '#2UVGQU9'
    assert all_rows['items'][1]['clan_is_current'] is False
    match = records.pipeline[0]['$match']
    assert match == {'guild_id': 1, 'kind': {'$in': ['strike', 'missed', 'exempt', 'cwl', 'no_attack', 'mismatch']}}
    assert all_rows['items'][2]['total_strikes'] == 0
    assert all_rows['items'][2]['last_strike_at'] is None
    assert records.pipeline[2]['$group']['_id'] == '$player_tag'


def test_member_search_preserves_separate_linked_accounts():
    ledger, records = fixtures()
    links = SimpleNamespace(unavailable=(), conflicts=(),
                            sources={'#PC9YGL0JL': ('ClashKing',), '#8GG82': ('ClashKing',)})

    async def run():
        with patch('utils.strike_store.recruit_links.resolve', return_value=links):
            return await ledger.account_list(1, query='123456789012345678', status='all')

    result = asyncio.run(run())
    assert result['total'] == 3
    assert {row['player_tag'] for row in result['items']} == {'#PC9YGL0JL', '#8GG82', '#PLQ8'}
    assert all(row['member_id'] == 123456789012345678 for row in result['items'])
    assert records.pipeline[0]['$match']['player_tag']['$in'] == [
        '#8GG82', '#PC9YGL0JL', '#PLQ8']


def test_account_endpoint_contract_is_one_row_per_player():
    ledger, _ = fixtures()

    @asynccontextmanager
    async def mongo(_):
        yield object()

    async def permit(*_, **__):
        return None

    async def service(*_):
        return ledger

    async def clans(_):
        return [{'tag': '#2UVGQU9', 'name': 'Family', 'is_fwa': True}]

    async def run():
        request = SimpleNamespace(method='GET', query={}, app={})
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', mongo), \
             patch.object(strikes, 'service', service), \
             patch.object(strikes, 'clan_rows', clans):
            return await strikes.accounts(request)

    result = json.loads(asyncio.run(run()).text)
    assert result['total'] == 1
    assert len(result['accounts']) == 1
    assert result['accounts'][0]['active_strikes'] == 2
    assert result['accounts'][0]['current_clan_name'] == 'Family'
