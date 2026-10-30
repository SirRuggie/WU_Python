"""Saved war browsing and strikes-first history filters."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import patch

from cwl_web import strikes
from utils.strike_store import StrikeService
from utils.strike_wars import normalize, fetch_history_report


NOW = datetime.now(timezone.utc)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_):
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def __aiter__(self):
        for row in self.rows:
            yield row

    async def to_list(self, length=None):
        return self.rows


class Records:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def _match(self, row, query):
        if row['guild_id'] != query['guild_id']:
            return False
        if 'war_key' in query and row.get('war_key') != query['war_key']:
            return False
        kind = query.get('kind')
        if isinstance(kind, str) and row['kind'] != kind:
            return False
        if isinstance(kind, dict) and row['kind'] == kind.get('$ne'):
            return False
        return True

    def find(self, query):
        self.queries.append(query)
        return Cursor([row for row in self.rows if self._match(row, query)])

    async def count_documents(self, query):
        self.queries.append(query)
        return sum(self._match(row, query) for row in self.rows)


def test_default_history_shows_strikes_only_and_exact_war_never_leaks():
    rows = [
        {'_id': 'a', 'guild_id': 1, 'war_key': 'war-one-1', 'kind': 'strike',
         'occurred_at': NOW, 'expires_at': NOW + timedelta(days=90)},
        {'_id': 'b', 'guild_id': 1, 'war_key': 'war-one-1', 'kind': 'missed',
         'occurred_at': NOW, 'expires_at': NOW + timedelta(days=90)},
        {'_id': 'c', 'guild_id': 1, 'war_key': 'war-two-2', 'kind': 'strike',
         'occurred_at': NOW, 'expires_at': NOW + timedelta(days=90)},
    ]
    records = Records(rows)
    ledger = StrikeService(SimpleNamespace(strike_records=records))

    async def run():
        default = await ledger.history(1)
        chosen = await ledger.history(1, war_key='war-one-1', status='all')
        return default, chosen

    default, chosen = asyncio.run(run())
    assert [row['_id'] for row in default['items']] == ['a', 'c']
    assert default['total'] == 2
    assert [row['_id'] for row in chosen['items']] == ['a', 'b']
    assert chosen['total'] == 2
    assert records.queries[0]['kind'] == 'strike'
    assert records.queries[-1]['war_key'] == 'war-one-1'


def test_war_summary_pipeline_keeps_old_one_missed_rows():
    class Aggregate:
        def __init__(self):
            self.pipeline = None

        async def aggregate(self, pipeline):
            self.pipeline = pipeline
            return Cursor([])

    records = Aggregate()
    ledger = StrikeService(SimpleNamespace(strike_records=records))
    asyncio.run(ledger.war_list(1))
    match = records.pipeline[0]['$match']
    assert match['kind']['$in'] == ['strike', 'missed', 'exempt', 'cwl']
    assert 'occurred_at' not in match  # prior imports remain discoverable
    assert records.pipeline[1] == {'$sort': {'occurred_at': -1, '_id': 1}}


def test_saved_war_keeps_clan_and_opponent_names():
    end = NOW - timedelta(hours=1)
    raw = {'state': 'warEnded', 'teamSize': 1, 'attacksPerMember': 2,
           'endTime': end.strftime('%Y%m%dT%H%M%S.000Z'),
           'startTime': (end - timedelta(days=1)).strftime('%Y%m%dT%H%M%S.000Z'),
           'preparationStartTime': (end - timedelta(days=1, hours=23)).strftime('%Y%m%dT%H%M%S.000Z'),
           'clan': {'tag': '#2UVGQU9', 'name': 'Family',
                    'members': [{'tag': '#PC9YGL0JL'}]},
           'opponent': {'tag': '#8GG8', 'name': 'Dragons',
                        'members': [{'tag': '#8GG82'}]}}
    row = normalize(raw, '#2UVGQU9')
    assert row['clan_name'] == 'Family'
    assert row['opponent_name'] == 'Dragons'


def test_missing_type_import_uses_prep_timing_and_counts_skipped_friendlies():
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    fmt = lambda value: value.strftime('%Y%m%dT%H%M%S.000Z')
    start = end - timedelta(days=1)
    def raw(prep_hours):
        return {'state': 'warEnded', 'teamSize': 1, 'attacksPerMember': 2,
                'endTime': fmt(end), 'startTime': fmt(start),
                'preparationStartTime': fmt(start - timedelta(hours=prep_hours)),
                'clan': {'tag': '#2UVGQU9', 'members': [{'tag': '#PC9YGL0JL'}]},
                'opponent': {'tag': '#8GG8', 'members': [{'tag': '#8GG82'}]}}
    assert normalize(raw(23), '#2UVGQU9')['type'] == 'regular'
    for hours in (24, 6):
        try:
            normalize(raw(hours), '#2UVGQU9')
        except ValueError as error:
            assert 'preparation timing' in str(error)
        else:
            raise AssertionError(f'{hours} h preparation must not import')

    class Response:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def json(self):
            return [raw(23), raw(24), raw(6)]
    class Session:
        def get(self, *_args, **_kwargs):
            return Response()
    report = asyncio.run(fetch_history_report('#2UVGQU9', session=Session()))
    assert report['source_count'] == 3
    assert len(report['wars']) == 1
    assert len(report['skipped']) == 2


def test_war_search_resolves_old_opponent_name_before_filtering():
    end = NOW - timedelta(days=3)
    rows = [{'war_key': '#2UVGQU9:#8GG8:2026-10-17T00:00:00+00:00',
             'clan_tag': '#2UVGQU9', 'clan_name': None,
             'opponent_tag': '#8GG8', 'opponent_name': None,
             'war_end': end, 'missed_accounts': 2, 'strikes': 1, 'one_missed': 1}]

    class Ledger:
        async def war_page(self, guild_id, **kwargs):
            assert kwargs['query'] == 'Dragons'
            found = [row.copy() for row in rows]
            await kwargs['enrich_names'](found)
            found = [row for row in found if kwargs['query'] in row['opponent_name']]
            return {'items': found, 'total': len(found)}

    class Provider:
        async def clan(self, value):
            assert value == '#8GG8'
            return {'name': 'Dragons'}

    @asynccontextmanager
    async def mongo(_):
        yield SimpleNamespace(strike_war_snapshots=Records([]))

    async def permit(*_, **__):
        pass

    async def service(*_):
        return Ledger()

    async def clans(_):
        return [{'tag': '#2UVGQU9', 'name': 'Family'}]

    async def run():
        strikes._OPPONENT_NAME_CACHE.clear()
        app = {'providers': Provider()}
        request = SimpleNamespace(method='GET', app=app, query={'query': 'Dragons'})
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', mongo), \
             patch.object(strikes, 'service', service), \
             patch.object(strikes, 'clan_rows', clans):
            return await strikes.wars(request)

    result = json.loads(asyncio.run(run()).text)
    assert len(result['wars']) == 1
    assert result['wars'][0]['opponent_name'] == 'Dragons'
    assert result['wars'][0]['clan_name'] == 'Family'
