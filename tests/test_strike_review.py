"""Independent regression checks for the strike ledger's risky boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from types import SimpleNamespace
from pymongo.errors import DuplicateKeyError

from utils.recruit_links import PlayerOwners
from utils.strike_store import StrikeService, validate_war


def war(*, attacks=0, complete=True, state='warEnded', war_type='regular', attack_limit=2):
    return {
        'clan_tag': '#2UVGQU9', 'opponent_tag': '#8GG8',
        'end_time': datetime.now(timezone.utc) - timedelta(hours=1),
        'state': state, 'type': war_type, 'attacks_per_member': attack_limit,
        'complete': complete,
        'members': [{'tag': '#PC9YGL0JL', 'name': 'Player', 'attacks': attacks}],
    }


@pytest.mark.parametrize('changes', [
    {'complete': False}, {'state': 'inWar'}, {'type': 'cwl'},
    {'attacks_per_member': 1}, {'members': []},
    {'members': [{'tag': '#PC9YGL0JL', 'attacks': None}]},
])
def test_war_requires_final_complete_two_attack_roster(changes):
    candidate = war()
    candidate.update(changes)
    with pytest.raises(ValueError):
        validate_war(candidate)


class Collection:
    def __init__(self, rows=None):
        self.rows = rows or {}

    async def find_one(self, query, projection=None):
        if '_id' in query:
            return self.rows.get(query['_id'])
        for row in self.rows.values():
            if 'tag' in query and row.get('tag') != query['tag']:
                continue
            if 'guild_id' in query and row.get('guild_id') != query['guild_id']:
                continue
            if 'member_id' in query and row.get('member_id') != query['member_id']:
                continue
            if 'starts_at' in query and not row['starts_at'] <= query['starts_at']['$lte']:
                continue
            if 'until' in query and not row['until'] > query['until']['$gt']:
                continue
            if '$or' in query and not any(
                    row.get('account_tags') is None if option['account_tags'] is None
                    else option['account_tags'] in row.get('account_tags', ())
                    for option in query['$or']):
                continue
            return row
        return None

    def find(self, query, projection=None):
        def matches(row):
            for key, value in query.items():
                if key == '_id' and isinstance(value, dict) and '$in' in value:
                    if row.get('_id') not in value['$in']:
                        return False
                elif row.get(key) != value:
                    return False
            return True
        rows = [row for row in self.rows.values() if matches(row)]
        if projection == {'_id': 1}:
            rows = [{'_id': row['_id']} for row in rows]
        class Cursor:
            async def to_list(self, length=None):
                return rows
        return Cursor()

    async def update_one(self, query, update, upsert=False):
        key = query['_id']
        row = self.rows.setdefault(key, {'_id': key})
        row.update(update.get('$set', {}))
        if '$setOnInsert' in update and len(row) == 1:
            row.update(update['$setOnInsert'])
        for field in update.get('$unset', {}):
            row.pop(field, None)
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, query):
        self.rows.pop(query['_id'], None)

    async def insert_one(self, row):
        if row['_id'] in self.rows:
            raise DuplicateKeyError('duplicate')
        self.rows[row['_id']] = row


class Mongo:
    def __init__(self):
        self.clans = Collection({'clan': {'tag': '#2UVGQU9'}})
        self.strike_settings = Collection()
        self.strike_leaves = Collection()
        self.strike_leave_history = Collection()
        self.strike_records = Collection()


def test_war_retry_is_idempotent_and_records_one_miss_without_strike():
    asyncio.run(_war_retry_is_idempotent_and_records_one_miss_without_strike())


async def _war_retry_is_idempotent_and_records_one_miss_without_strike():
    mongo = Mongo()

    async def links(tags):
        return PlayerOwners(owners={})

    service = StrikeService(mongo, link_resolver=links)
    candidate = war(attacks=1)
    first = await service.process_war(123, candidate)
    second = await service.process_war(123, candidate)
    assert first['applied'] == 1
    assert second['applied'] == 0
    assert second['existing'] == 1
    assert next(iter(mongo.strike_records.rows.values()))['kind'] == 'missed'


def test_duplicate_two_missed_strike_does_not_increase_reported_strikes():
    async def run():
        mongo = Mongo()
        async def links(tags):
            return PlayerOwners(owners={})
        ledger = StrikeService(mongo, link_resolver=links)
        candidate = war(attacks=0)
        first = await ledger.process_war(123, candidate)
        second = await ledger.process_war(123, candidate)
        assert first['strikes'] == 1
        assert second['strikes'] == 0
        assert second['existing'] == 1
        assert len(mongo.strike_records.rows) == 1
    asyncio.run(run())


def test_unknown_member_roles_defer_only_that_account():
    asyncio.run(_unknown_member_roles_defer_only_that_account())


async def _unknown_member_roles_defer_only_that_account():
    mongo = Mongo()

    async def links(tags):
        return PlayerOwners(owners={'#PC9YGL0JL': '1234'})

    candidate = war()
    candidate['members'].append({'tag': '#8GG82', 'name': 'Other', 'attacks': 0})
    service = StrikeService(mongo, link_resolver=links)
    result = await service.process_war(123, candidate)
    assert result['applied'] == 1
    assert result['deferred_count'] == 1
    assert result['deferred_accounts'][0]['player_tag'] == '#PC9YGL0JL'
    assert next(iter(mongo.strike_records.rows.values()))['player_tag'] == '#8GG82'


def test_leave_does_not_reach_back_into_import_history():
    asyncio.run(_leave_does_not_reach_back_into_import_history())


async def _leave_does_not_reach_back_into_import_history():
    mongo = Mongo()
    now = datetime.now(timezone.utc)
    mongo.strike_leaves.rows['123:456'] = {
        'starts_at': now, 'updated_at': now,
        'until': now + timedelta(days=5), 'account_tags': None,
    }
    service = StrikeService(mongo, role_resolver=lambda guild, member: [])
    assert await service._exemption(123, '#PC9YGL0JL', 456,
                                    now - timedelta(days=1), set()) is None
    assert await service._exemption(123, '#PC9YGL0JL', 456,
                                    now + timedelta(days=1), set()) == 'leave'


def test_import_rechecks_role_and_honors_preview_exclusions():
    asyncio.run(_import_rechecks_role_and_honors_preview_exclusions())


async def _import_rechecks_role_and_honors_preview_exclusions():
    mongo = Mongo()
    mongo.strike_imports = Collection()
    current_roles = []

    async def links(tags):
        return PlayerOwners(owners={'#PC9YGL0JL': '456'})

    async def roles(guild_id, member_id):
        return current_roles

    service = StrikeService(mongo, link_resolver=links, role_resolver=roles)
    first = await service.preview_import(123, [war()], actor_id=789)
    assert first['strikes'] == 1
    current_roles.append(769130325460254740)
    applied = await service.apply_import(123, first['preview_id'], 789)
    assert applied['strikes'] == 0
    assert next(iter(mongo.strike_records.rows.values()))['kind'] == 'exempt'

    mongo.strike_records.rows.clear()
    current_roles.clear()
    second = await service.preview_import(123, [war()], actor_id=789)
    excluded = [second['items'][0]['_id']]
    result = await service.apply_import(123, second['preview_id'], 789,
                                        excluded_keys=excluded)
    assert result['applied'] == 0
    assert mongo.strike_records.rows == {}


def test_saved_war_without_type_needs_explicit_two_attack_limit():
    from utils.strike_wars import normalize

    regular = {
        'state': 'warEnded', 'teamSize': 1, 'attacksPerMember': 2,
        'endTime': '20260927T151018.000Z',
        'startTime': '20260926T151018.000Z',
        'preparationStartTime': '20260925T161018.000Z',
        'clan': {'tag': '#2UVGQU9', 'members': [{'tag': '#PC9YGL0JL'}]},
        'opponent': {'tag': '#8GG8', 'members': [{'tag': '#8GG82'}]},
    }
    row = normalize(regular, '#2UVGQU9')
    assert row['members'][0]['attacks'] == 0
    del regular['attacksPerMember']
    with pytest.raises(ValueError):
        normalize(regular, '#2UVGQU9')


def test_ending_leave_preserves_past_exemption_but_stops_future_exemption():
    asyncio.run(_ending_leave_preserves_past_exemption_but_stops_future_exemption())


async def _ending_leave_preserves_past_exemption_but_stops_future_exemption():
    mongo = Mongo()
    service = StrikeService(mongo)
    now = datetime.now(timezone.utc)
    mongo.strike_leaves.rows['123:456'] = {
        '_id': '123:456', 'guild_id': 123, 'member_id': 456,
        'starts_at': now - timedelta(days=2), 'updated_at': now - timedelta(days=2),
        'until': now + timedelta(days=3), 'account_tags': ['#PC9YGL0JL'],
    }
    past = now - timedelta(days=1)
    assert await service._exemption(123, '#PC9YGL0JL', 456, past, set()) == 'leave'
    await service.clear_leave(123, 456)
    assert mongo.strike_leaves.rows['123:456']['cleared'] is True
    assert mongo.strike_leaves.rows['123:456']['revision'] == 1
    assert await service._exemption(123, '#PC9YGL0JL', 456, past, set()) == 'leave'
    assert await service._exemption(123, '#PC9YGL0JL', 456,
                                    now + timedelta(days=1), set()) is None
    assert await service._exemption(123, '#8GG82', 456, past, set()) is None


def test_replacement_uses_effective_weights_after_filler_and_strikes():
    asyncio.run(_replacement_uses_effective_weights_after_filler_and_strikes())


async def _replacement_uses_effective_weights_after_filler_and_strikes():
    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, length=None):
            return self.rows

    class Clans:
        def find(self, query, projection=None):
            assert query == {'type': 'FWA'}
            return Cursor([{'tag': '#2UVGQU9'}])

    class Profiles:
        def find(self, query):
            assert 'roster_seen_at' in query
            now = datetime.now(timezone.utc)
            rows = [
                {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9',
                 'roster_seen_at': now, 'weight': 100000, 'filler': True,
                 'filler_clan_tag': '#2UVGQU9'},
                {'player_tag': '#8GG82', 'current_clan_tag': '#2UVGQU9',
                 'roster_seen_at': now, 'weight': 120000, 'filler': False},
            ]
            return Cursor(rows)

    class Records:
        async def aggregate(self, pipeline):
            assert pipeline[0]['$match']['kind'] == 'strike'
            return Cursor([{'_id': '#8GG82', 'count': 2}])

    mongo = Mongo()
    mongo.clans = Clans()
    mongo.strike_profiles = Profiles()
    mongo.strike_records = Records()
    rows = await StrikeService(mongo).replacement(
        123, 115000, weights={'#PC9YGL0JL': 114000, '#8GG82': 115000})
    assert [row['player_tag'] for row in rows] == ['#PC9YGL0JL', '#8GG82']
    assert [row['weight'] for row in rows] == [114000, 115000]
    assert [row['weight_difference'] for row in rows] == [1000, 0]
    assert [row['active_strikes'] for row in rows] == [0, 2]


def test_import_caches_leave_reads_per_run_but_rechecks_before_apply():
    asyncio.run(_import_caches_leave_reads_per_run_but_rechecks_before_apply())


async def _import_caches_leave_reads_per_run_but_rechecks_before_apply():
    class CurrentLeaves(Collection):
        reads = 0

        async def find_one(self, query, projection=None):
            self.reads += 1
            return await super().find_one(query, projection)

    class PastLeaves(Collection):
        reads = 0

        def find(self, query):
            self.reads += 1
            return super().find(query)

    mongo = Mongo()
    mongo.strike_imports = Collection()
    mongo.strike_leaves = CurrentLeaves()
    mongo.strike_leave_history = PastLeaves()

    async def links(tags):
        return PlayerOwners(owners={'#PC9YGL0JL': '456'})

    async def roles(guild_id, member_id):
        return []

    service = StrikeService(mongo, link_resolver=links, role_resolver=roles)
    first = war()
    second = war()
    second['end_time'] = first['end_time'] - timedelta(hours=1)
    preview = await service.preview_import(123, [first, second], actor_id=789)
    assert preview['strikes'] == 2
    assert mongo.strike_leaves.reads == 1
    assert mongo.strike_leave_history.reads == 1

    now = datetime.now(timezone.utc)
    mongo.strike_leaves.rows['123:456'] = {
        '_id': '123:456', 'guild_id': 123, 'member_id': 456,
        'starts_at': now - timedelta(hours=4), 'updated_at': now - timedelta(hours=4),
        'until': now + timedelta(days=1), 'account_tags': ['#PC9YGL0JL'],
    }
    applied = await service.apply_import(123, preview['preview_id'], 789)
    assert applied['applied'] == 2
    assert applied['strikes'] == 0
    assert mongo.strike_leaves.reads == 2
    assert mongo.strike_leave_history.reads == 2
    assert {row['kind'] for row in mongo.strike_records.rows.values()} == {'exempt'}


def test_confirmed_unlinked_account_gets_its_own_strike():
    async def run():
        mongo = Mongo()
        async def links(tags):
            return PlayerOwners(owners={})
        result = await StrikeService(mongo, link_resolver=links).process_war(123, war())
        assert result['strikes'] == 1 and result['deferred_count'] == 0
        row = next(iter(mongo.strike_records.rows.values()))
        assert row['member_id'] is None and row['link_status'] == 'unlinked'
    asyncio.run(run())


def test_link_provider_outage_still_defers_entire_war_without_guessing_unlinked():
    async def run():
        mongo = Mongo()
        async def links(tags):
            return PlayerOwners(owners={}, unavailable=('ClashKing',))
        with pytest.raises(RuntimeError, match='Account links unavailable'):
            await StrikeService(mongo, link_resolver=links).process_war(123, war())
        assert mongo.strike_records.rows == {}
    asyncio.run(run())


def test_conflict_only_defers_that_missed_account_and_retry_is_idempotent():
    async def run():
        mongo = Mongo()
        disputed = True
        async def links(tags):
            if disputed:
                return PlayerOwners(owners={}, conflicts=('#8GG82',))
            return PlayerOwners(owners={})
        candidate = war()
        candidate['members'].append({'tag': '#8GG82', 'name': 'Other', 'attacks': 0})
        ledger = StrikeService(mongo, link_resolver=links)
        first = await ledger.process_war(123, candidate)
        assert first['strikes'] == 1 and first['deferred_count'] == 1
        assert first['deferred_accounts'][0]['reason'] == 'Account owner conflict'
        assert {row['player_tag'] for row in mongo.strike_records.rows.values()} == {'#PC9YGL0JL'}
        disputed = False
        retry = await ledger.process_war(123, candidate)
        assert retry['applied'] == 1 and retry['existing'] == 1
        assert retry['deferred_count'] == 0
        assert len(mongo.strike_records.rows) == 2
    asyncio.run(run())


def test_apply_never_promotes_account_deferred_in_preview():
    async def run():
        mongo = Mongo()
        mongo.strike_imports = Collection()
        disputed = True
        async def links(tags):
            if disputed:
                return PlayerOwners(owners={}, conflicts=('#8GG82',))
            return PlayerOwners(owners={})
        candidate = war()
        candidate['members'].append({'tag': '#8GG82', 'name': 'Other', 'attacks': 0})
        ledger = StrikeService(mongo, link_resolver=links)
        preview = await ledger.preview_import(123, [candidate], actor_id=789)
        assert [row['player_tag'] for row in preview['items']] == ['#PC9YGL0JL']
        assert preview['items'][0]['link_status'] == 'unlinked'
        assert preview['deferred_count'] == 1
        assert preview['deferred_accounts'][0]['player_tag'] == '#8GG82'
        assert len(mongo.strike_imports.rows[preview['preview_id']]['approved_rows']) == 1
        disputed = False
        applied = await ledger.apply_import(123, preview['preview_id'], 789)
        assert applied['applied'] == 1 and applied['deferred_count'] == 1
        assert 'new preview' in applied['deferred_accounts'][0]['reason']
        assert {row['player_tag'] for row in mongo.strike_records.rows.values()} == {'#PC9YGL0JL'}
        second = await ledger.preview_import(123, [candidate], actor_id=789)
        assert [row['player_tag'] for row in second['items']] == ['#8GG82']
        retry = await ledger.apply_import(123, second['preview_id'], 789)
        assert retry['applied'] == 1
        assert len(mongo.strike_records.rows) == 2
    asyncio.run(run())


def test_role_resolver_error_defers_only_linked_account():
    async def run():
        mongo = Mongo()
        async def links(tags):
            return PlayerOwners(owners={'#PC9YGL0JL': '456'})
        async def roles(guild_id, member_id):
            raise RuntimeError('Discord outage')
        candidate = war()
        candidate['members'].append({'tag': '#8GG82', 'name': 'Other', 'attacks': 0})
        result = await StrikeService(mongo, link_resolver=links,
                                     role_resolver=roles).process_war(123, candidate)
        assert result['applied'] == 1 and result['deferred_count'] == 1
        assert result['deferred_accounts'][0]['reason'] == 'Discord roles unavailable'
        assert next(iter(mongo.strike_records.rows.values()))['link_status'] == 'unlinked'
    asyncio.run(run())
