"""Fixture regressions for local cursor budgets and retention-safe projections."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pymongo
from pymongo import _csot
from pymongo.errors import NetworkTimeout
import pytest

from extensions.commands.tickets import store as tickets
from utils.strike_tracking import StrikeTracking
from utils.strike_retention import snapshot_purge_after
from utils.player_activity_polling import active_clan, CLAN_SCAN_FIELDS


class Cursor:
    def __init__(self, rows, *, error=None, events=None):
        self.rows = rows
        self.error = error
        self.events = events

    async def to_list(self, length=None):
        assert length is None, 'maintenance must not truncate matching rows'
        assert _csot.get_timeout() == 30
        if self.events is not None:
            self.events.append('read')
        if self.error is not None:
            raise self.error
        return deepcopy(self.rows)


def projected(row, fields):
    return {key: deepcopy(value) for key, value in row.items()
            if fields.get(key) or key == '_id' and fields.get('_id', 1)}


class Snapshots:
    def __init__(self, rows, error=None):
        self.rows = {row['_id']: deepcopy(row) for row in rows}
        self.error = error
        self.projection = None
        self.updates = []

    def find(self, query, fields):
        self.projection = fields
        assert query == {'guild_id': 1, 'status': 'observing'}
        return Cursor([projected(r, fields) for r in self.rows.values()
                       if r['guild_id'] == 1 and r['status'] == 'observing'], error=self.error)

    async def update_one(self, query, update):
        assert _csot.get_timeout() is None, 'per-read budget must not cover writes'
        row = self.rows[query['_id']]
        assert query['status'] == row['status']
        self.updates.append((query, update))
        row.update(update['$set'])
        return SimpleNamespace(matched_count=1)


@pytest.mark.parametrize('held', [False, True])
def test_abandon_projection_retains_manual_hold_and_exact_retention(held):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = now - timedelta(days=1)
    rows = [{'_id': str(n), 'guild_id': 1, 'clan_tag': '#P' + str(n),
             'status': 'observing', 'manual_review_required': held,
             'resolved_at': now, 'end_time': end, 'war': {'large': 'x' * 1000}}
            for n in range(1001)]
    rows += [{**rows[0], '_id': 'tracked', 'clan_tag': '#TRACKED'},
             {**rows[0], '_id': 'other-guild', 'guild_id': 2}]
    collection = Snapshots(rows)
    tracking = StrikeTracking(SimpleNamespace(strike_war_snapshots=collection))
    removed = asyncio.run(tracking.abandon_untracked(1, {'#TRACKED'}, now=now))
    assert len(removed) == len(collection.updates) == 1001
    assert collection.projection == {'_id': 1, 'clan_tag': 1, 'manual_review_required': 1,
                                     'status': 1, 'resolved_at': 1, 'end_time': 1}
    expected = snapshot_purge_after({**rows[0], 'status': 'abandoned'})
    assert all(update['$set']['purge_after'] == expected for _, update in collection.updates)
    assert expected is None if held else expected is not None
    assert collection.rows['tracked']['status'] == collection.rows['other-guild']['status'] == 'observing'
    assert all('war' not in update['$set'] for _, update in collection.updates)


@pytest.mark.parametrize('error', [NetworkTimeout('fixture'), asyncio.CancelledError('fixture')])
def test_abandon_read_failure_or_cancellation_does_not_change_snapshots(error):
    collection = Snapshots([], error)
    with pytest.raises(type(error)):
        asyncio.run(StrikeTracking(SimpleNamespace(strike_war_snapshots=collection)).abandon_untracked(1, set()))
    assert collection.updates == []
    assert _csot.get_timeout() is None


class TicketCollection:
    def __init__(self, rows, error=None, events=None):
        self.rows = rows
        self.error = error
        self.events = events
        self.fields = None
        self.indexes = []

    def find(self, query, fields):
        assert query == tickets.RUNTIME_FILTER
        self.fields = fields
        return Cursor([projected(row, fields) for row in self.rows], error=self.error, events=self.events)

    async def create_index(self, keys, **options):
        assert _csot.get_timeout() == 30
        self.indexes.append(options['name'])
        if self.events is not None:
            self.events.append('index')
        return options['name']


def ticket(**updates):
    return {'_id': 'one', 'type': 'ticket', 'runtime': 'thread_v2', 'schema_version': 3,
            'venue': 'thread', 'status': 'open', 'ticket_type': 'main', 'ticket_number': 1,
            'user_id': 123, 'location': {'guild_id': 1, 'id': 2, 'staff_space_id': 3},
            'audit': [], 'answers': [], 'rev': 0, 'unrelated_large_payload': 'x' * 100_000,
            **updates}


@pytest.mark.parametrize('bad', [{}, {'rev': 'bad'}, {'schema_version': 'bad'},
                                {'source': 'bad'}, {'location': {'guild_id': 'bad'}},
                                {'answer_count': 'bad'}, {'schema_version': 2, 'audit': [1]}])
def test_ticket_projection_preserves_unique_and_schema_preflight(bad):
    rows = [ticket(**bad), ticket(_id='two')]
    collection = TicketCollection(rows)
    expected = tickets.index_conflicts_for_documents(rows)
    assert asyncio.run(tickets.index_conflicts(collection)) == expected
    assert 'unrelated_large_payload' not in collection.fields
    assert {'audit', 'answers', 'schema_version', 'rev', 'source'} <= collection.fields.keys()
    assert _csot.get_timeout() is None


def test_ticket_preflight_and_each_index_have_independent_local_budget(monkeypatch):
    from contextlib import contextmanager
    events = []
    original = pymongo.timeout

    @contextmanager
    def budget(seconds):
        assert seconds == 30
        events.append('enter')
        try:
            with original(seconds):
                yield
        finally:
            events.append('exit')

    monkeypatch.setattr(pymongo, 'timeout', budget)
    collection = TicketCollection([], events=events)
    result = asyncio.run(tickets._install_indexes(SimpleNamespace(tickets=collection)))
    assert len(result) == len(collection.indexes) >= 13
    assert events == ['enter', 'read', 'exit'] + ['enter', 'index', 'exit'] * len(result)
    assert _csot.get_timeout() is None


@pytest.mark.parametrize('error', [NetworkTimeout('fixture'), asyncio.CancelledError('fixture')])
def test_ticket_preflight_failure_cancels_bootstrap_before_indexes(error):
    collection = TicketCollection([], error)
    with pytest.raises(type(error)):
        asyncio.run(tickets._install_indexes(SimpleNamespace(tickets=collection)))
    assert collection.indexes == []
    assert _csot.get_timeout() is None


@pytest.mark.parametrize('changes', [{}, {'active': False}, {'removed_at': 'now'},
                                    {'status': 'archived'}, {'deleted': True}])
def test_family_scan_projection_preserves_all_membership_exclusions(changes):
    full = {'tag': '#P2Y', 'unrelated_war_payload': 'x' * 1000, **changes}
    narrow = projected(full, CLAN_SCAN_FIELDS)
    assert active_clan(full) == active_clan(narrow)
    assert 'unrelated_war_payload' not in narrow


def test_legacy_scan_stays_streaming_and_processing_has_no_inherited_deadline(monkeypatch):
    from utils import component_state
    events = []

    class StreamingCursor:
        def __init__(self):
            self.index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            assert _csot.get_timeout() == 30
            if self.index == 1001:
                raise StopAsyncIteration
            self.index += 1
            events.append('read')
            return {'_id': self.index, 'type': 'ticket', 'large': 'x' * 1000}

    class Collection:
        def find(self, query):
            assert query == {}
            return StreamingCursor()

    original = component_state.legacy_state_kind

    def classify(row):
        assert _csot.get_timeout() is None
        events.append('process')
        return original(row)

    monkeypatch.setattr(component_state, 'legacy_state_kind', classify)
    result = asyncio.run(component_state.migrate_legacy_state(SimpleNamespace(button_store=Collection())))
    assert result == {'migrated': 0, 'removed': 0, 'protected_or_unknown': 1001, 'failed': 0}
    assert events == ['read', 'process'] * 1001
    assert _csot.get_timeout() is None


@pytest.mark.parametrize('preloaded', [False, True])
def test_fwa_autocomplete_preserves_role_in_selected_value(monkeypatch, preloaded):
    from extensions import autocomplete

    class Clans:
        async def distinct(self, field):
            return []

        def find(self, query, fields):
            rows = [{'name': 'Warriors', 'tag': '#ABC', 'type': 'FWA',
                     'role_id': 987654321012345678, 'unneeded': 'private'}]
            return Cursor([projected(row, fields) for row in rows])

    class Context:
        focused = SimpleNamespace(value='Warriors')
        responses = []

        async def respond(self, choices):
            self.responses.append(choices)

    monkeypatch.setattr(autocomplete, '_cache', {
        key: {'data': None, 'timestamp': 0} for key in autocomplete._cache
    })
    mongo = SimpleNamespace(clans=Clans())
    ctx = Context()

    async def run():
        if preloaded:
            await autocomplete.preload_autocomplete_cache(mongo)
        await autocomplete.fwa_clans(ctx, mongo)

    asyncio.run(run())
    assert ctx.responses == [[('Warriors', 'Warriors|#ABC|987654321012345678')]]
    assert 'unneeded' not in autocomplete._cache['fwa_clans']['data'][0]
