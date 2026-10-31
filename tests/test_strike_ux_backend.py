"""Bounded, offline strikes UX contracts and adversarial concurrency checks."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError

from cwl_web import strikes as api
from utils.strike_store import StrikeConflict, StrikeService, status_of

NOW = datetime.now(timezone.utc)


def matches(row, query):
    for key, wanted in query.items():
        if key in ('$or', '$and'):
            values = [matches(row, item) for item in wanted]
            if not (any(values) if key == '$or' else all(values)):
                return False
            continue
        actual = row.get(key)
        if isinstance(wanted, dict):
            for op, value in wanted.items():
                if op == '$exists' and (key in row) != value:
                    return False
                if op == '$in' and actual not in value:
                    return False
                if op == '$nin' and actual in value:
                    return False
                if op == '$ne' and actual == value:
                    return False
                if op == '$regex' and not re.search(value, str(actual or ''), re.I if wanted.get('$options') == 'i' else 0):
                    return False
                if op in ('$gt', '$gte', '$lt', '$lte'):
                    if actual is None:
                        return False
                    if not {'$gt': actual > value, '$gte': actual >= value,
                            '$lt': actual < value, '$lte': actual <= value}[op]:
                        return False
        elif isinstance(actual, list):
            if wanted not in actual:
                return False
        elif actual != wanted:
            return False
    return True


def expression(row, value):
    if isinstance(value, str) and value.startswith('$'):
        return row.get(value[1:])
    if isinstance(value, list):
        return [expression(row, item) for item in value]
    if not isinstance(value, dict):
        return value
    op, args = next(iter(value.items()))
    args = expression(row, args)
    if op == '$cond':
        return args[1] if args[0] else args[2]
    if op == '$and':
        return all(args)
    if op == '$ifNull':
        return args[1] if args[0] is None else args[0]
    if op == '$eq':
        return args[0] == args[1]
    if op == '$ne':
        return args[0] != args[1]
    if args[0] is None:
        return False
    return {'$gt': lambda: args[0] > args[1], '$gte': lambda: args[0] >= args[1],
            '$lte': lambda: args[0] <= args[1]}[op]()


class Cursor:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    async def __aiter__(self):
        for row in self.rows:
            yield row

    async def to_list(self, length=None):
        return self.rows[:length]

    def sort(self, keys, direction=None):
        for key, order in reversed(keys if isinstance(keys, list) else [(keys, direction)]):
            self.rows.sort(key=lambda row: (row.get(key) is not None, row.get(key)), reverse=order < 0)
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self


class Collection:
    def __init__(self, rows=()):
        self.rows = {row['_id']: deepcopy(row) for row in rows}
        self.before_write = None
        self.find_sizes = []

    async def find_one(self, query, projection=None):
        return next((deepcopy(row) for row in self.rows.values() if matches(row, query)), None)

    def find(self, query, projection=None):
        if isinstance(query.get('player_tag'), dict):
            self.find_sizes.append(len(query['player_tag'].get('$in', [])))
        return Cursor([row for row in self.rows.values() if matches(row, query)])

    async def count_documents(self, query):
        return sum(matches(row, query) for row in self.rows.values())

    async def insert_one(self, row):
        if self.before_write:
            callback, self.before_write = self.before_write, None
            await callback()
        if row['_id'] in self.rows:
            raise DuplicateKeyError('race')
        self.rows[row['_id']] = deepcopy(row)

    async def update_one(self, query, update, upsert=False):
        if self.before_write:
            callback, self.before_write = self.before_write, None
            await callback()
        row = next((row for row in self.rows.values() if matches(row, query)), None)
        if row is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            if query['_id'] in self.rows:
                raise DuplicateKeyError('race')
            row = {'_id': query['_id'], **deepcopy(update.get('$setOnInsert', {}))}
            self.rows[row['_id']] = row
        row.update(deepcopy(update.get('$set', {})))
        for key in update.get('$unset', {}):
            row.pop(key, None)
        return SimpleNamespace(matched_count=1)

    async def find_one_and_update(self, query, update, return_document=False):
        before = await self.find_one(query)
        if before is None:
            return None
        await self.update_one(query, update)
        return await self.find_one({'_id': before['_id']}) if return_document else before

    async def aggregate(self, pipeline):
        rows = list(self.rows.values())
        for stage in pipeline:
            op, value = next(iter(stage.items()))
            if op == '$match':
                rows = [row for row in rows if matches(row, value)]
            elif op == '$sort':
                rows = Cursor(rows).sort(list(value.items())).rows
            elif op == '$limit':
                rows = rows[:value]
            elif op == '$group':
                groups = {}
                for row in rows:
                    groups.setdefault(expression(row, value['_id']), []).append(row)
                output = []
                for identity, members in groups.items():
                    result = {'_id': identity}
                    for key, spec in value.items():
                        if key == '_id':
                            continue
                        accumulator, expr = next(iter(spec.items()))
                        vals = [expression(row, expr) for row in members]
                        result[key] = (vals[0] if accumulator == '$first' else sum(vals)
                                       if accumulator == '$sum' else max((v for v in vals if v is not None), default=None))
                    output.append(result)
                rows = output
            else:
                raise AssertionError(f'Unimplemented aggregate stage: {op}')
        return Cursor(rows)


def setup():
    db = SimpleNamespace(**{name: Collection() for name in (
        'strike_settings', 'strike_leaves', 'strike_leave_history', 'strike_records',
        'strike_profiles', 'strike_war_snapshots', 'strike_imports', 'clans')})
    return db, StrikeService(db)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('existing', [False, True])
def test_settings_first_revision_race_preserves_monitoring(existing):
    async def scenario():
        db, store = setup()
        if existing:
            db.strike_settings.rows['1'] = {'_id': '1', 'monitoring_started_at': NOW}
        async def competing_write():
            await store.set_exempt_roles(1, [3], 9, expected_revision=0, strike_limit=7)
        db.strike_settings.before_write = competing_write
        with pytest.raises(StrikeConflict):
            await store.set_exempt_roles(1, [2], 8, expected_revision=0, strike_limit=2)
        saved = await store.settings(1)
        assert (saved['exempt_role_ids'], saved['strike_limit'], saved['revision']) == ([3], 7, 1)
        if existing:
            assert saved['monitoring_started_at'] == NOW
        assert db.strike_records.rows == {}
    run(scenario())


@pytest.mark.parametrize('bad', [0, 21, True, '4', 1.5])
def test_settings_limit_rejects_invalid_values(bad):
    async def scenario():
        db, store = setup()
        with pytest.raises(ValueError):
            await store.set_exempt_roles(1, [], 2, expected_revision=0, strike_limit=bad)
        assert not db.strike_settings.rows
    run(scenario())


def test_leave_losing_cas_never_archives_and_tombstone_prevents_aba():
    async def scenario():
        db, store = setup()
        await store.set_leave(1, 2, (NOW + timedelta(days=3)).date(), 9, expected_revision=0)
        async def competing_write():
            await store.set_leave(1, 2, (NOW + timedelta(days=5)).date(), 9, expected_revision=1)
        db.strike_leaves.before_write = competing_write
        with pytest.raises(StrikeConflict):
            await store.clear_leave(1, 2, expected_revision=1)
        assert len(db.strike_leave_history.rows) == 1
        assert db.strike_leaves.rows['1:2']['revision'] == 2
        await store.clear_leave(1, 2, expected_revision=2)
        assert db.strike_leaves.rows['1:2']['revision'] == 3
        assert db.strike_leaves.rows['1:2']['cleared']
        with pytest.raises(StrikeConflict):
            await store.set_leave(1, 2, (NOW + timedelta(days=6)).date(), 9, expected_revision=0)
        assert len(db.strike_leave_history.rows) == 2
    run(scenario())


def test_leave_archive_crash_recovers_on_exemption_read_without_new_write():
    async def scenario():
        db, store = setup()
        db.strike_leaves.rows['1:2'] = {
            '_id': '1:2', 'guild_id': 1, 'member_id': 2, 'starts_at': NOW - timedelta(days=2),
            'updated_at': NOW - timedelta(days=2), 'until': NOW + timedelta(days=2),
            'account_tags': ['#P2Y']}
        async def unavailable():
            raise RuntimeError('archive unavailable')
        db.strike_leave_history.before_write = unavailable
        with pytest.raises(RuntimeError):
            await store.clear_leave(1, 2, expected_revision=0)
        assert db.strike_leaves.rows['1:2']['pending_history']
        assert not db.strike_leave_history.rows
        assert await store._exemption(1, '#P2Y', 2, NOW - timedelta(days=1), set()) == 'leave'
        assert await store._exemption(1, '#Q2Y', 2, NOW - timedelta(days=1), set()) is None
        assert await store._exemption(1, '#P2Y', 2, NOW + timedelta(days=1), set()) is None
        assert 'pending_history' not in db.strike_leaves.rows['1:2']
        assert len(db.strike_leave_history.rows) == 1
    run(scenario())


def record(identity, player='#P2Y', **kwargs):
    return {'_id': identity, 'guild_id': 1, 'player_tag': player, 'player_name': player,
            'kind': 'strike', 'occurred_at': NOW - timedelta(days=1),
            'expires_at': NOW + timedelta(days=59), **kwargs}


def test_accounts_search_summary_and_action_apply_to_all_300_accounts():
    async def scenario():
        db, store = setup()
        await store.set_exempt_roles(1, [], 2, strike_limit=2, expected_revision=0)
        for i in range(300):
            player = '#P' + f'{i:03}'.translate(str.maketrans('123456789', 'PYLQGRJCU'))
            await db.strike_records.insert_one(record(f'{i}-a', player))
            await db.strike_records.insert_one(record(f'{i}-b', player, occurred_at=NOW - timedelta(days=9)))
            await db.strike_profiles.insert_one({'_id': player, 'guild_id': 1, 'player_tag': player,
                'player_name': 'Last searchable' if i == 299 else f'Player {i}', 'current_clan_tag': '#Q2Y'})
        result = await store.account_list(1, limit=25, skip=275, action='over_limit')
        assert result['total'] == 300 and len(result['items']) == 25
        assert result['summary'] == {'over_limit': 300, 'new_this_week': 300}
        found = await store.account_list(1, query='last searchable', clan_tag='#Q2Y', action='new_this_week')
        assert found['total'] == 1 and found['summary'] == {'over_limit': 1, 'new_this_week': 1}
        assert found['items'][0]['player_name'] == 'Last searchable'
        assert max(db.strike_profiles.find_sizes) <= 200
        # Threshold changes labels only; no strike writes or revocations.
        before = deepcopy(db.strike_records.rows)
        await store.set_exempt_roles(1, [], 2, strike_limit=3, expected_revision=1)
        changed = await store.account_list(1, action='over_limit')
        assert changed['total'] == 0 and changed['summary']['new_this_week'] == 300
        assert db.strike_records.rows == before
    run(scenario())


def test_new_week_ignores_removed_expired_old_and_future_rows():
    async def scenario():
        db, store = setup()
        rows = [record('old', occurred_at=NOW - timedelta(days=9)),
                record('removed', revoked_at=NOW), record('expired', expires_at=NOW - timedelta(seconds=1)),
                record('future', occurred_at=NOW + timedelta(days=1)),
                record('missed', kind='missed')]
        db.strike_records = Collection(rows)
        result = await store.account_list(1, status='all', action='new_this_week')
        assert result['total'] == 0
        assert result['summary']['new_this_week'] == 0
    run(scenario())


@pytest.mark.parametrize('wanted', ['active', 'expired', 'removed', 'missed', 'exempt', 'completed', 'cwl'])
def test_history_status_precedence_and_stable_paging(wanted):
    async def scenario():
        db, store = setup()
        for kind in ('strike', 'cwl', 'missed', 'exempt', 'completed'):
            for revoked in (False, True):
                for expired in (False, True):
                    identity = f'{kind}-{revoked}-{expired}'
                    row = record(identity, kind=kind, expires_at=NOW + timedelta(days=-1 if expired else 1))
                    if revoked:
                        row['revoked_at'] = NOW
                    await db.strike_records.insert_one(row)
        expected = sorted(row['_id'] for row in db.strike_records.rows.values()
                          if status_of(row, NOW) == ('recorded' if wanted == 'cwl' else wanted))
        actual = await store.history(1, status=wanted, skip=1, limit=2, now=NOW)
        assert actual['total'] == len(expected)
        assert [row['_id'] for row in actual['items']] == expected[1:3]
    run(scenario())


def test_war_search_beyond_2000_and_incomplete_dedup_stable_page():
    async def scenario():
        db, store = setup()
        for i in range(2100):
            await db.strike_records.insert_one(record(str(i), source='war', war_key=f'war-{i:04}',
                clan_tag='#Q2Y', opponent_tag='#G2Y', opponent_name='Needle' if i >= 2098 else 'Other'))
        db.strike_war_snapshots.rows = {
            'duplicate': {'_id': 'duplicate', 'guild_id': 1, 'status': 'incomplete', 'war_key': 'war-2099',
                          'clan_tag': '#Q2Y', 'end_time': NOW, 'war': {'opponent_name': 'Needle'}},
            'unique': {'_id': 'unique', 'guild_id': 1, 'status': 'incomplete', 'war_key': 'war-2100',
                       'clan_tag': '#Q2Y', 'end_time': NOW, 'war': {'opponent_name': 'Needle'}}}
        result = await store.war_page(1, query='needle', skip=1, limit=1)
        assert result['total'] == 3
        assert result['items'][0]['war_key'] == 'war-2098'
        first = await store.war_page(1, query='needle', limit=1)
        assert first['items'][0]['incomplete'] is True
    run(scenario())


def test_http_settings_conflict_and_managed_role_retention():
    async def scenario():
        db, store = setup()
        guild = api.GUILD_ID
        actor = {'user_id': '123456789012345678', 'roles': [
            {'id': '222222222222222222', 'name': 'Bot', 'managed': True},
            {'id': '333333333333333333', 'name': 'Normal', 'managed': False}]}
        await store.set_exempt_roles(guild, [222222222222222222, 444444444444444444], 1, expected_revision=0)
        @asynccontextmanager
        async def mongo(_):
            yield db
        request = SimpleNamespace(method='PUT', app={'strike_service': store})
        payload = {'role_ids': ['222222222222222222', '444444444444444444'], 'revision': 1, 'strike_limit': 8}
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'identity', AsyncMock(return_value=actor)), \
             patch.object(api.shared, 'mongo', mongo), patch.object(api, 'body', AsyncMock(side_effect=lambda *_: payload)):
            response = await api.save_roles(request)
            assert json.loads(response.text)['revision'] == 2
            with pytest.raises(web.HTTPConflict):
                await api.save_roles(request)
            payload = {'role_ids': ['555555555555555555'], 'revision': 1}
            with pytest.raises(web.HTTPConflict):
                await api.save_roles(request)
            payload = {'role_ids': ['222222222222222222'], 'revision': 2}
            response = await api.save_roles(request)
            assert json.loads(response.text)['strike_limit'] == 8
            payload = {'role_ids': [], 'revision': 3}
            await api.save_roles(request)
            payload = {'role_ids': ['222222222222222222'], 'revision': 4}
            with pytest.raises(web.HTTPBadRequest):
                await api.save_roles(request)
    run(scenario())


@pytest.mark.parametrize('race', ['none', 'duplicate', 'exempt', 'excluded'])
def test_import_summary_matches_apply_and_reports_actual_race_outcome(race):
    from utils.recruit_links import PlayerOwners
    async def scenario():
        db, store = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y'})
        store.link_resolver = AsyncMock(return_value=PlayerOwners(owners={'#P2Y': '2', '#G2Y': '2'}))
        current_roles = []
        async def roles(*_):
            return current_roles
        store.role_resolver = roles
        war = {'clan_tag': '#Q2Y', 'opponent_tag': '#J2Y', 'end_time': NOW - timedelta(days=1),
               'type': 'regular', 'state': 'warEnded', 'complete': True, 'attacks_per_member': 2,
               'members': [{'tag': '#P2Y', 'name': 'Strike', 'attacks': 0},
                           {'tag': '#G2Y', 'name': 'History', 'attacks': 1}]}
        preview = await store.preview_import(1, [war, war], actor_id=9)
        assert preview['summary'] == {'strikes': 1, 'accounts': 1, 'history_only': 1}
        strike = next(row for row in preview['items'] if row['kind'] == 'strike')
        if race == 'duplicate':
            await db.strike_records.insert_one(strike)
        elif race == 'exempt':
            current_roles.append(769130325460254740)
        exclusions = [strike['_id']] if race == 'excluded' else []
        result = await store.apply_import(1, preview['preview_id'], 9, excluded_keys=exclusions)
        assert result['added_strikes'] == (1 if race == 'none' else 0)
        assert result['history_only'] == (2 if race == 'exempt' else 1)
        assert result['duplicates'] == (1 if race == 'duplicate' else 0)
        assert result['excluded'] == (1 if race == 'excluded' else 0)
        assert result['applied'] == result['added_strikes'] + result['history_only']
        assert all(row.get('capture_source') == 'clashking_import' for row in db.strike_records.rows.values())
    run(scenario())


def test_known_target_search_includes_manual_ledger_accounts_and_is_bounded():
    async def scenario():
        db, store = setup()
        for i in range(50):
            await db.strike_records.insert_one(record(f'{i}', f'#P{i}', player_name=f'Known {i:02}'))
        await db.strike_profiles.insert_one({'_id': 'profile', 'guild_id': 1,
            'player_tag': '#Q2Y', 'player_name': 'Known 00 Profile'})
        result = await store.known_targets(1, 'Known')
        assert len(result) == 25 and any(row['player_tag'] == '#Q2Y' for row in result)
        assert await store.known_targets(1, 'Known [') == []
        assert await store.known_targets(2, 'Known') == []
    run(scenario())


def test_http_target_empty_direct_member_name_unavailable_and_scope():
    async def scenario():
        db, store = setup()
        provider = SimpleNamespace(player=AsyncMock(return_value={'tag': '#P2Y', 'name': 'Known',
            'town_hall': 16, 'current_clan_tag': '#Q2Y', 'current_clan_name': 'Family'}))
        permit = AsyncMock()
        @asynccontextmanager
        async def mongo(_):
            yield db
        request = SimpleNamespace(method='GET', app={'strike_service': store, 'providers': provider}, query={})
        with patch.object(api.shared, 'require_manage', permit), patch.object(api.shared, 'mongo', mongo):
            response = await api.targets(request)
            assert json.loads(response.text) == {'accounts': [], 'members': []}
            provider.player.assert_not_awaited()
            request.query = {'query': '#P2Y'}
            response = await api.targets(request)
            assert json.loads(response.text)['accounts'][0]['town_hall'] == 16
            assert permit.call_args.args[1] == 'strikes_add'
            request.query = {'query': '#INVALID'}
            with pytest.raises(web.HTTPBadRequest):
                await api.targets(request)
            request.query = {'query': '#P2Y'}
            provider.player.side_effect = api.ProviderUnavailable('offline')
            with pytest.raises(web.HTTPServiceUnavailable):
                await api.targets(request)
    run(scenario())


def test_remote_war_name_search_across_all_pages_and_bounded_batches():
    async def scenario():
        db, store = setup()
        for i in range(301):
            await db.strike_records.insert_one(record(str(i), source='war', war_key=f'war-{i:04}',
                clan_tag='#Q2Y', opponent_tag='#G2Y', opponent_name=None))
        batches = []
        async def enrich(rows):
            batches.append(len(rows))
            for row in rows:
                row['opponent_name'] = 'Dragons'
        result = await store.war_page(1, query='dragons', skip=300, limit=1, enrich_names=enrich)
        assert result['total'] == 301 and result['items'][0]['war_key'] == 'war-0300'
        assert max(batches) <= 100 and sum(batches) == 301
    run(scenario())


@pytest.mark.parametrize('handler,method,payload,match_info', [
    (api.save_roles, 'PUT', {'role_ids': []}, {}),
    (api.save_leave, 'POST', {'discord_id': '123456789012345678'}, {}),
    (api.remove_leave, 'DELETE', {}, {'member_id': '123456789012345678'}),
])
def test_dashboard_requires_explicit_revision(handler, method, payload, match_info):
    async def scenario():
        request = SimpleNamespace(method=method, app={}, match_info=match_info)
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
             patch.object(api, 'body', AsyncMock(return_value=payload)):
            with pytest.raises(web.HTTPBadRequest):
                await handler(request)
    run(scenario())


def test_http_leave_save_and_clear_conflict_keep_winner_and_history():
    async def scenario():
        from cwl_web import app
        db, store = setup()
        member_id = '123456789012345678'
        @asynccontextmanager
        async def mongo(_):
            yield db
        request = SimpleNamespace(method='POST', app={'strike_service': store}, match_info={'member_id': member_id})
        payload = {'discord_id': member_id, 'player_tags': ['#P2Y'],
                   'resume_date': (NOW + timedelta(days=3)).date().isoformat(), 'revision': 0}
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api, 'body', AsyncMock(side_effect=lambda *_: payload)), \
             patch.object(api, 'account_rows', AsyncMock(return_value=[{'tag': '#P2Y'}])), \
             patch.object(app, '_session', return_value={'user_id': '9'}):
            response = await api.save_leave(request)
            assert json.loads(response.text)['revision'] == 1
            with pytest.raises(web.HTTPConflict):
                await api.save_leave(request)
            assert not db.strike_leave_history.rows
            request.method = 'DELETE'
            payload = {'revision': 0}
            with pytest.raises(web.HTTPConflict):
                await api.remove_leave(request)
            payload = {'revision': 1}
            response = await api.remove_leave(request)
            assert json.loads(response.text)['revision'] == 2
            assert len(db.strike_leave_history.rows) == 1
            request.method = 'GET'
            response = await api.leave_state(request)
            assert json.loads(response.text)['revision'] == 2
    run(scenario())


def test_role_metadata_in_server_order_and_existing_unavailable_exemption_visible():
    async def scenario():
        db, store = setup()
        actor = {'roles': [
            {'id': '123456789012345678', 'name': 'Normal', 'position': 2, 'color': 123, 'managed': False},
            {'id': '223456789012345678', 'name': 'Bot', 'position': 5, 'color': 456, 'managed': True},
            {'id': str(api.GUILD_ID), 'name': '@everyone', 'position': 0}]}
        @asynccontextmanager
        async def mongo(_):
            yield db
        request = SimpleNamespace(method='GET', app={'strike_service': store})
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.shared, 'identity', AsyncMock(return_value=actor)):
            result = json.loads((await api.settings(request)).text)
        assert [row['position'] for row in result['roles']] == [5, 2]
        assert result['roles'][0]['managed'] is True and result['roles'][1]['color'] == 123
        assert result['excluded_roles'][0]['id'] == '769130325460254740'
        assert result['strike_limit'] == 4 and result['revision'] == 0
    run(scenario())


@pytest.mark.parametrize('length,allowed', [(500, True), (501, False)])
def test_manual_reason_500_preserves_request_id_idempotency(length, allowed):
    async def scenario():
        db, store = setup()
        if not allowed:
            with pytest.raises(ValueError):
                await store.add_manual(1, '#P2Y', 'a' * length, 9, request_id='request-id-123456')
            assert not db.strike_records.rows
        else:
            first = await store.add_manual(1, '#P2Y', 'a' * length, 9, request_id='request-id-123456')
            second = await store.add_manual(1, '#P2Y', 'a' * length, 9, request_id='request-id-123456')
            assert first['_id'] == second['_id'] and len(db.strike_records.rows) == 1
            assert first['expires_at'] - first['occurred_at'] == timedelta(days=60)
    run(scenario())


def test_legacy_leave_without_start_time_and_pending_unset_crash():
    async def scenario():
        db, store = setup()
        db.strike_leaves.rows['1:2'] = {'_id': '1:2', 'guild_id': 1, 'member_id': 2,
            'updated_at': NOW - timedelta(days=2), 'until': NOW + timedelta(days=2), 'account_tags': None}
        original_update = db.strike_leaves.update_one
        async def fail_cleanup(query, update, **kwargs):
            if '$unset' in update:
                raise RuntimeError('cleanup interrupted')
            return await original_update(query, update, **kwargs)
        db.strike_leaves.update_one = fail_cleanup
        with pytest.raises(RuntimeError):
            await store.clear_leave(1, 2, expected_revision=0)
        assert len(db.strike_leave_history.rows) == 1
        db.strike_leaves.update_one = original_update
        assert await store._exemption(1, '#P2Y', 2, NOW - timedelta(days=1), set(), leave_cache={}) == 'leave'
        assert len(db.strike_leave_history.rows) == 1
        assert 'pending_history' not in db.strike_leaves.rows['1:2']
    run(scenario())


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('limit', [None, 2])
def test_settings_returns_own_successful_receipt_before_concurrent_successor(existing, limit):
    """A successor must not lend its revision to the preceding editor's draft."""
    async def scenario():
        db, store = setup()
        if existing:
            db.strike_settings.rows['1'] = {'_id': '1', 'revision': 0,
                'exempt_role_ids': [], 'strike_limit': 6, 'monitoring_started_at': NOW}
        original_insert = db.strike_settings.insert_one
        original_update = db.strike_settings.update_one
        async def successor():
            await store.set_exempt_roles(1, [3], 9, expected_revision=1, strike_limit=7)
        async def insert_then_successor(row):
            result = await original_insert(row)
            if row.get('updated_by') == 8:
                await successor()
            return result
        async def update_then_successor(query, update, **kwargs):
            result = await original_update(query, update, **kwargs)
            if update.get('$set', {}).get('updated_by') == 8:
                await successor()
            return result
        db.strike_settings.insert_one = insert_then_successor
        db.strike_settings.update_one = update_then_successor
        first = await store.set_exempt_roles(1, [2], 8, expected_revision=0, strike_limit=limit)
        assert first['revision'] == 1
        assert first['exempt_role_ids'] == [2]
        assert first['strike_limit'] == (limit if limit is not None else 6 if existing else 4)
        assert first['updated_by'] == 8
        if existing:
            assert first['monitoring_started_at'] == NOW
        successor_row = deepcopy(db.strike_settings.rows['1'])
        assert (successor_row['revision'], successor_row['exempt_role_ids'],
                successor_row['strike_limit']) == (2, [3], 7)
        # Continuing the first editor's unchanged draft must conflict, not undo B.
        with pytest.raises(StrikeConflict):
            await store.set_exempt_roles(1, first['exempt_role_ids'], 8,
                                         expected_revision=first['revision'],
                                         strike_limit=first['strike_limit'])
        assert db.strike_settings.rows['1'] == successor_row
    run(scenario())


@pytest.mark.parametrize('length', [500, 501])
def test_remove_reason_limit_in_http_and_store(length):
    async def scenario():
        db, store = setup()
        await db.strike_records.insert_one(record('remove-me'))
        reason = 'x' * length
        if length == 501:
            with pytest.raises(ValueError):
                await store.revoke(1, 'remove-me', 9, reason)
            assert 'revoked_at' not in db.strike_records.rows['remove-me']
        else:
            removed = await store.revoke(1, 'remove-me', 9, reason)
            assert removed['revoke_reason'] == reason
        ledger = SimpleNamespace(revoke=AsyncMock())
        request = SimpleNamespace(method='POST', app={'strike_service': ledger},
                                  match_info={'strike_id': 'remove-me'},
                                  json=AsyncMock(return_value={'reason': reason}))
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
             patch.object(api.shared, 'mongo', mongo), \
             patch('cwl_web.app._session', return_value={'user_id': '9'}):
            if length == 501:
                with pytest.raises(web.HTTPBadRequest):
                    await api.remove(request)
                ledger.revoke.assert_not_awaited()
            else:
                response = await api.remove(request)
                assert response.status == 200
                ledger.revoke.assert_awaited_once()
    run(scenario())


def test_reimport_counts_candidates_already_present_at_preview_once():
    from utils.recruit_links import PlayerOwners
    async def scenario():
        db, store = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y'})
        store.link_resolver = AsyncMock(return_value=PlayerOwners(owners={'#P2Y': '2', '#G2Y': '2'}))
        store.role_resolver = AsyncMock(return_value=[])
        war = {'clan_tag': '#Q2Y', 'opponent_tag': '#J2Y', 'end_time': NOW - timedelta(days=1),
               'type': 'regular', 'state': 'warEnded', 'complete': True, 'attacks_per_member': 2,
               'members': [{'tag': '#P2Y', 'name': 'Strike', 'attacks': 0},
                           {'tag': '#G2Y', 'name': 'History', 'attacks': 1}]}
        preview = await store.preview_import(1, [war], actor_id=9)
        first = await store.apply_import(1, preview['preview_id'], 9)
        assert first['applied'] == 2
        before = deepcopy(db.strike_records.rows)
        repeat = await store.preview_import(1, [war, war], actor_id=9)
        result = await store.apply_import(1, repeat['preview_id'], 9)
        assert result['duplicates'] == 2
        assert result['applied'] == result['added_strikes'] == 0
        assert db.strike_records.rows == before
    run(scenario())


def test_name_and_linked_target_search_use_saved_th_and_current_clan_without_live_player_calls():
    from cwl_web import manage_roles
    async def scenario():
        db, store = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y', 'name': 'Family'})
        await db.strike_profiles.insert_one({'_id': 'profile', 'guild_id': api.GUILD_ID,
            'player_tag': '#P2Y', 'player_name': 'Known player', 'town_hall': 16,
            'current_clan_tag': '#Q2Y'})
        provider = SimpleNamespace(player=AsyncMock(side_effect=AssertionError('No live name lookups')))
        request = SimpleNamespace(method='GET', app={'strike_service': store, 'providers': provider}, query={'query': 'Known'})
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
             patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.shared, 'discord', AsyncMock(return_value={})), \
             patch.object(manage_roles, 'searchable_members', AsyncMock(return_value=[])), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=SimpleNamespace(sources={'#P2Y': ['fixture']}, unavailable=False, conflicts={}))):
            for query in ('Known', '123456789012345678'):
                request.query = {'query': query}
                response = await api.targets(request)
                assert json.loads(response.text)['accounts'] == [{'tag': '#P2Y', 'name': 'Known player',
                    'town_hall': 16, 'current_clan_tag': '#Q2Y', 'current_clan_name': 'Family'}]
            provider.player.assert_not_awaited()
    run(scenario())


def test_http_settings_reject_retired_opponent_field_before_storage():
    async def scenario():
        request = SimpleNamespace(method='PUT', app={})
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
             patch('cwl_web.app._json', AsyncMock(return_value={
                 'revision': 0, 'role_ids': [], 'no_attack_opponents': ['#2CYVV92R']})), \
             patch.object(api.shared, 'identity', AsyncMock()) as identity:
            with pytest.raises(web.HTTPBadRequest) as error:
                await api.save_roles(request)
            assert 'Unknown field' in error.value.text
            identity.assert_not_called()
    run(scenario())
