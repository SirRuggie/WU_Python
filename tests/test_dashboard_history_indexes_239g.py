"""Fixture index/bootstrap contracts; no live server or TTL scheduling proof."""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from pymongo.errors import OperationFailure

from cwl_web import change_history
from extensions.tasks import gauntlet_help as task


EXPECTED = [
    call([('kind', 1), ('guild_id', 1), ('status', 1), ('due_at', 1)],
         name='gauntlet_help_due_v1'),
    call([('kind', 1), ('guild_id', 1), ('delete_at', 1)],
         name='gauntlet_help_delete_v1'),
    call([('kind', 1), ('target', 1), ('at', -1)],
         name='dashboard_history_target_time_partial_v1',
         partialFilterExpression={'kind': 'dashboard_history'}),
    call([('at', 1)], name='dashboard_history_at_365d_v1',
         expireAfterSeconds=31536000,
         partialFilterExpression={'kind': 'dashboard_history'}),
]


def bootstrap(monkeypatch, create_index):
    """Run the actual started listener; its periodic body is a no-op fixture."""
    async def run():
        monkeypatch.setattr(task, '_task', None)
        monkeypatch.setattr(task, '_bot', None)
        monkeypatch.setattr(task, '_mongo', None)
        monkeypatch.setattr(task, '_loop', AsyncMock())
        mongo = SimpleNamespace(bot_config=SimpleNamespace(create_index=create_index))
        await task.on_started._func(None, bot=object(), mongo=mongo)
        await task._task
    asyncio.run(run())


def test_startup_preserves_existing_indexes_and_adds_exact_history_specs(monkeypatch):
    creator = AsyncMock()
    bootstrap(monkeypatch, creator)
    assert creator.await_args_list == EXPECTED
    assert all('drop' not in str(c) for c in creator.await_args_list)


@pytest.mark.parametrize('failed_at', [0, 1, 2, 3])
def test_index_failure_is_logged_without_repair_or_losing_periodic_start(monkeypatch, caplog, failed_at):
    attempts = []
    async def create(*args, **kwargs):
        attempts.append(call(*args, **kwargs))
        if len(attempts) - 1 == failed_at:
            raise OperationFailure('fixture incompatible index', code=85)
    bootstrap(monkeypatch, AsyncMock(side_effect=create))
    if failed_at < 2:
        assert attempts == EXPECTED[:failed_at + 1] + EXPECTED[2:]
        assert 'Gauntlet help indexes unavailable' in caplog.text
    else:
        assert attempts == EXPECTED[:failed_at + 1]
        assert 'Dashboard history indexes unavailable' in caplog.text
    task._loop.assert_awaited_once()
    assert 'fixture incompatible index' in caplog.text


@pytest.mark.parametrize('cancel_at', [0, 1, 2, 3])
def test_bootstrap_cancellation_propagates_without_starting_periodic_job(monkeypatch, cancel_at):
    async def run():
        calls = []
        async def create(*args, **kwargs):
            calls.append(call(*args, **kwargs))
            if len(calls) - 1 == cancel_at:
                raise asyncio.CancelledError
        monkeypatch.setattr(task, '_task', None)
        monkeypatch.setattr(task, '_bot', None)
        monkeypatch.setattr(task, '_mongo', None)
        loop = AsyncMock()
        monkeypatch.setattr(task, '_loop', loop)
        mongo = SimpleNamespace(bot_config=SimpleNamespace(create_index=AsyncMock(side_effect=create)))
        with pytest.raises(asyncio.CancelledError):
            await task.on_started._func(None, bot=object(), mongo=mongo)
        assert calls == EXPECTED[:cancel_at + 1]
        assert task._task is None
        loop.assert_not_awaited()
    asyncio.run(run())


def test_already_running_startup_does_not_recreate_indexes(monkeypatch):
    async def run():
        running = SimpleNamespace(done=lambda: False)
        monkeypatch.setattr(task, '_task', running)
        monkeypatch.setattr(task, '_bot', None)
        monkeypatch.setattr(task, '_mongo', None)
        creator = AsyncMock()
        await task.on_started._func(None, bot=object(), mongo=SimpleNamespace(bot_config=SimpleNamespace(create_index=creator)))
        creator.assert_not_awaited()
        assert task._task is running
    asyncio.run(run())


def test_partial_ttl_fixture_eligibility_and_bson_date_writer(monkeypatch):
    creator = AsyncMock()
    bootstrap(monkeypatch, creator)
    ttl = creator.await_args_list[-1]
    assert ttl.kwargs['partialFilterExpression'] == {'kind': 'dashboard_history'}
    assert ttl.kwargs['expireAfterSeconds'] == 31536000
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    old = now - timedelta(days=366)
    recent = now - timedelta(days=364)
    rows = [
        {'_id': 'old', 'kind': 'dashboard_history', 'at': old},
        {'_id': 'boundary', 'kind': 'dashboard_history', 'at': now - timedelta(days=365)},
        {'_id': 'recent', 'kind': 'dashboard_history', 'at': recent},
        {'_id': 'other-old', 'kind': 'gauntlet_help', 'at': old},
        {'_id': 'other-array', 'kind': 'settings', 'at': [old]},
        {'_id': 'other-kind-array', 'kind': ['settings', 'gauntlet_help'], 'at': old},
        {'_id': 'mixed-kind-array', 'kind': ['settings', 'dashboard_history'], 'at': old},
        {'_id': 'history-kind-array', 'kind': ['dashboard_history'], 'at': old},
        {'_id': 'recent-mixed-kind-array', 'kind': ['settings', 'dashboard_history'], 'at': recent},
        {'_id': 'missing-kind', 'at': old},
        {'_id': 'null-kind', 'kind': None, 'at': old},
        {'_id': 'missing-at', 'kind': 'dashboard_history'},
        {'_id': 'null-at', 'kind': 'dashboard_history', 'at': None},
        {'_id': 'string-at', 'kind': 'dashboard_history', 'at': old.isoformat()},
        {'_id': 'numeric-at', 'kind': 'dashboard_history', 'at': old.timestamp()},
        {'_id': 'history-date-array', 'kind': 'dashboard_history', 'at': [old, recent]},
    ]
    # Fixture model of Mongo scalar equality and TTL: scalar equality also
    # matches an array containing that value; TTL uses the earliest date.
    # This does not run Mongo's query engine/TTL monitor or prove deletion latency.
    def eligible(row):
        def matches(value, expected):
            return value == expected or (isinstance(value, list) and expected in value)
        if any(not matches(row.get(k), v) for k, v in ttl.kwargs['partialFilterExpression'].items()):
            return False
        dates = row.get('at')
        dates = dates if isinstance(dates, list) else [dates]
        dates = [v for v in dates if isinstance(v, datetime)]
        return bool(dates) and min(dates) + timedelta(seconds=ttl.kwargs['expireAfterSeconds']) <= now
    assert [r['_id'] for r in rows if eligible(r)] == [
        'old', 'boundary', 'mixed-kind-array', 'history-kind-array', 'history-date-array',
    ]
    # A release must stop on all array-valued matching kinds, even when the
    # current date is recent: that malformed row could become eligible later.
    ambiguous = [r['_id'] for r in rows
                 if isinstance(r.get('kind'), list) and 'dashboard_history' in r['kind']]
    assert ambiguous == ['mixed-kind-array', 'history-kind-array', 'recent-mixed-kind-array']
    async def run():
        insert = AsyncMock()
        db = SimpleNamespace(bot_config=SimpleNamespace(insert_one=insert))
        await change_history.begin(db, '/api/cwl/manage/content/war--win', {'user_id': '1'}, {})
        row = insert.await_args.args[0]
        assert row['kind'] == 'dashboard_history'
        assert isinstance(row['at'], datetime) and row['at'].utcoffset() == timedelta(0)
    asyncio.run(run())


def test_repeat_bootstrap_keeps_external_full_and_other_indexes(monkeypatch):
    catalog = {
        'dashboard_history_target_time': {'key': [('kind', 1), ('target', 1), ('at', -1)]},
        'unrelated_config_index': {'key': [('other', 1)]},
    }
    original = copy.deepcopy(catalog)
    async def create(keys, **kwargs):
        spec = {'key': keys, **{k: v for k, v in kwargs.items() if k != 'name'}}
        if kwargs['name'] in catalog:
            assert catalog[kwargs['name']] == spec
        catalog[kwargs['name']] = spec
    bootstrap(monkeypatch, AsyncMock(side_effect=create))
    first = copy.deepcopy(catalog)
    bootstrap(monkeypatch, AsyncMock(side_effect=create))
    assert catalog == first
    assert all(catalog[name] == spec for name, spec in original.items())
    assert len(catalog) == 6


def test_listing_query_matches_partial_compound_and_preserves_target_sort_limit(monkeypatch):
    async def run():
        target = '/api/cwl/manage/content/war--win'
        now = datetime.now(timezone.utc)
        rows = [dict(_id=str(i), kind='dashboard_history', target=target,
                     at=now - timedelta(seconds=i), before={'text': 'before'},
                     after={'text': str(i)}, actor_id='1', actor_name='Fixture',
                     status='saved', action='edit') for i in range(32)]
        rows += [dict(rows[0], _id='foreign-target', target='/other'),
                 dict(rows[0], _id='foreign-kind', kind='other')]
        original = copy.deepcopy(rows)
        seen = []
        class Cursor:
            def __init__(self, selected): self.rows = selected
            def sort(self, field, direction):
                seen.append(('sort', field, direction))
                self.rows.sort(key=lambda row: row[field], reverse=direction < 0)
                return self
            def limit(self, count):
                seen.append(('limit', count)); self.rows = self.rows[:count]; return self
            async def to_list(self, length):
                seen.append(('length', length)); return self.rows[:length]
        def find(query):
            seen.append(('find', query))
            return Cursor([row for row in rows if all(row.get(k) == v for k, v in query.items())])
        @asynccontextmanager
        async def database(_):
            yield SimpleNamespace(bot_config=SimpleNamespace(find=find))
        auth = AsyncMock()
        monkeypatch.setattr(change_history, 'mongo', database)
        monkeypatch.setattr(change_history, 'require_manage', auth)
        result = json.loads((await change_history.listing(SimpleNamespace(query={'target': target}))).text)
        assert seen == [('find', {'kind': 'dashboard_history', 'target': target}),
                        ('sort', 'at', -1), ('limit', 30), ('length', 30)]
        assert [row['id'] for row in result['entries']] == [str(i) for i in range(30)]
        auth.assert_awaited_once()
        assert rows == original
    asyncio.run(run())
