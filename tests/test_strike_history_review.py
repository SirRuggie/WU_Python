"""History defaults, grouped accounts, and exact-war lookup regressions."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils.strike_store import StrikeService
from cwl_web import strikes as api


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.offset = 0
        self.max_items = None

    def sort(self, *args):
        return self

    def skip(self, value):
        self.offset = value
        return self

    def limit(self, value):
        self.max_items = value
        return self

    async def __aiter__(self):
        for row in self.rows:
            yield row

    async def to_list(self, length=None):
        end = self.max_items if self.max_items is not None else length
        return self.rows[self.offset:self.offset + end if end is not None else None]


class Records:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []
        self.pipeline = None

    def find(self, query):
        self.queries.append(query)
        return Cursor(self.rows)

    async def count_documents(self, query):
        self.queries.append(query)
        return len(self.rows)

    async def aggregate(self, pipeline):
        self.pipeline = pipeline
        return Cursor(self.rows)

    async def distinct(self, key, query):
        assert key == 'player_tag'
        self.queries.append(query)
        return [row['_id'] for row in self.rows if row.get('member_id') == query['member_id']]


class Profiles:
    def __init__(self, rows=None):
        self.rows = rows or []

    def find(self, query):
        return Cursor(self.rows)


class Mongo:
    def __init__(self, rows=None, profiles=None):
        self.strike_records = Records(rows)
        self.strike_profiles = Profiles(profiles)
        self.strike_settings = SimpleNamespace(find_one=AsyncMock(return_value=None))


def test_default_history_filters_strikes_before_count_and_pagination():
    async def run():
        now = datetime.now(timezone.utc)
        rows = [{'_id': str(index), 'kind': 'strike', 'player_tag': '#PC9YGL0JL',
                 'occurred_at': now, 'expires_at': now + timedelta(days=1)} for index in range(4)]
        mongo = Mongo(rows)
        result = await StrikeService(mongo).history(123, limit=2, skip=2)
        assert result['total'] == 4
        assert [row['_id'] for row in result['items']] == ['2', '3']
        assert all(query['kind'] == 'strike' for query in mongo.strike_records.queries)
    asyncio.run(run())


def test_exact_war_all_status_includes_one_missed_without_other_wars():
    async def run():
        now = datetime.now(timezone.utc)
        row = {'_id': 'one', 'kind': 'missed', 'player_tag': '#PC9YGL0JL',
               'occurred_at': now, 'expires_at': now + timedelta(days=1)}
        mongo = Mongo([row])
        selected = '#2UVGQU9:#8GG8:2026-10-20T00:00:00+00:00'
        result = await StrikeService(mongo).history(123, status='all', war_key=selected)
        assert result['total'] == 1
        assert result['items'][0]['status'] == 'missed'
        assert all(query['war_key'] == selected and query['kind'] == {'$ne': 'completed'}
                   for query in mongo.strike_records.queries)
    asyncio.run(run())


def test_grouped_account_active_filter_and_member_snapshot_fallback():
    async def run():
        now = datetime.now(timezone.utc)
        rows = [
            {'_id': '#PC9YGL0JL', 'player_name': 'Account 1', 'member_id': 456,
             'total_strikes': 3, 'active_strikes': 1, 'last_strike_at': now},
            {'_id': '#8GG82', 'player_name': 'Account 2', 'member_id': 456,
             'total_strikes': 2, 'active_strikes': 0, 'last_strike_at': now},
            {'_id': '#YLC820G', 'player_name': 'Account 3', 'member_id': 456,
             'total_strikes': 0, 'active_strikes': 0, 'last_strike_at': None},
        ]
        mongo = Mongo(rows)
        async def no_current_links(member_id):
            return SimpleNamespace(sources={}, unavailable=(), conflicts=())
        with patch('utils.strike_store.recruit_links.resolve', no_current_links):
            active = await StrikeService(mongo).account_list(123, query='456', status='active')
            all_accounts = await StrikeService(mongo).account_list(123, query='456', status='all')
        assert active['total'] == 1
        assert active['items'][0]['player_tag'] == '#PC9YGL0JL'
        assert active['items'][0]['total_strikes'] == 3
        assert all_accounts['total'] == 3
        assert all_accounts['items'][-1]['total_strikes'] == 0
        match = mongo.strike_records.pipeline[0]['$match']
        assert match['player_tag']['$in'] == ['#8GG82', '#PC9YGL0JL', '#YLC820G']
        assert match['kind'] == {'$in': ['strike', 'missed', 'exempt', 'cwl']}
        group = mongo.strike_records.pipeline[2]['$group']
        assert group['_id'] == '$player_tag'
        active_condition = group['active_strikes']['$sum']['$cond'][0]['$and']
        assert any('$gt' in check and check['$gt'][0] == '$expires_at' for check in active_condition)
        assert any('$eq' in check and check['$eq'][0] == {'$ifNull': ['$revoked_at', None]}
                   for check in active_condition)
    asyncio.run(run())


def test_repeated_matchups_keep_distinct_exact_war_keys():
    async def run():
        now = datetime.now(timezone.utc)
        rows = [
            {'_id': '#2UVGQU9:#8GG8:2026-10-20', 'clan_tag': '#2UVGQU9',
             'opponent_tag': '#8GG8', 'war_end': now, 'strikes': 2, 'one_missed': 1},
            {'_id': '#2UVGQU9:#8GG8:2026-10-18', 'clan_tag': '#2UVGQU9',
             'opponent_tag': '#8GG8', 'war_end': now - timedelta(days=2),
             'strikes': 1, 'one_missed': 2},
        ]
        mongo = Mongo(rows)
        wars = await StrikeService(mongo).war_list(123, clan_tag='#2UVGQU9')
        assert len(wars) == 2
        assert wars[0]['war_key'] != wars[1]['war_key']
        assert mongo.strike_records.pipeline[2]['$group']['_id'] == '$war_key'
        assert mongo.strike_records.pipeline[0]['$match']['clan_tag'] == '#2UVGQU9'
    asyncio.run(run())


def test_old_import_opponent_name_falls_back_to_tag_if_lookup_unavailable(monkeypatch):
    monkeypatch.setattr(api, "_OPPONENT_NAME_CACHE", {})
    async def run():
        now = datetime.now(timezone.utc)
        row = {'clan_tag': '#2UVGQU9', 'opponent_tag': '#8GG8',
               'war_end': now, 'opponent_name': None}
        class Providers:
            async def clan(self, tag):
                raise api.ProviderUnavailable('offline')
        request = SimpleNamespace(app={'providers': Providers()})
        enriched = await api._enrich_war_names(request, [row], {'#2UVGQU9': 'Home'})
        assert enriched[0]['clan_name'] == 'Home'
        assert enriched[0]['opponent_name'] == '#8GG8'
    asyncio.run(run())
