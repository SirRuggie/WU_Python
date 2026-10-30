"""Fixture-only streak receipts and departure lifecycle; no Mongo connection."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from utils.recruit_links import PlayerOwners
from utils.strike_store import StrikeService, war_key, DEFAULT_EXEMPT_ROLE

GUILD = 123
PLAYER = '#PC9YGL0JL'
CLAN = '#2UVGQU9'
NOW = datetime.now(timezone.utc)


def value(row, path):
    for key in path.split('.'):
        if not isinstance(row, dict) or key not in row:
            return None
        row = row[key]
    return row


def matches(row, query):
    for key, wanted in query.items():
        if key == '$or':
            if not any(matches(row, part) for part in wanted):
                return False
            continue
        actual = value(row, key)
        if isinstance(wanted, dict):
            for op, target in wanted.items():
                if op == '$exists' and (actual is not None) != target:
                    return False
                if op == '$in' and actual not in target:
                    return False
                if op == '$nin' and actual in target:
                    return False
                if op == '$ne' and actual == target:
                    return False
                if op in ('$gt', '$gte', '$lt', '$lte'):
                    if actual is None:
                        return False
                    if not {'$gt': actual > target, '$gte': actual >= target,
                            '$lt': actual < target, '$lte': actual <= target}[op]:
                        return False
        elif actual != wanted:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    async def __aiter__(self):
        for row in self.rows:
            yield row

    async def to_list(self, length=None):
        return self.rows

    def sort(self, *args):
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self


class Collection:
    def __init__(self):
        self.rows = {}

    def find(self, query, projection=None):
        return Cursor([row for row in self.rows.values() if matches(row, query)])

    async def count_documents(self, query):
        return len([row for row in self.rows.values() if matches(row, query)])

    async def find_one(self, query, projection=None):
        return next((deepcopy(row) for row in self.rows.values() if matches(row, query)), None)

    async def insert_one(self, row):
        if row['_id'] in self.rows:
            raise DuplicateKeyError('duplicate')
        self.rows[row['_id']] = deepcopy(row)

    async def update_one(self, query, update, upsert=False):
        row = next((row for row in self.rows.values() if matches(row, query)), None)
        if row is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            if query['_id'] in self.rows:
                raise DuplicateKeyError('duplicate')
            row = {'_id': query['_id'], **deepcopy(update.get('$setOnInsert', {}))}
            self.rows[row['_id']] = row
        row.update(deepcopy(update.get('$set', {})))
        for key in update.get('$unset', {}):
            row.pop(key, None)
        for key, amount in update.get('$inc', {}).items():
            row[key] = row.get(key, 0) + amount
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, query):
        found = next((key for key, row in self.rows.items() if matches(row, query)), None)
        if found is not None:
            del self.rows[found]

    async def aggregate(self, pipeline):
        counts = {}
        for row in self.rows.values():
            if matches(row, pipeline[0]['$match']):
                counts[row['player_tag']] = counts.get(row['player_tag'], 0) + 1
        return Cursor([{'_id': key, 'count': count} for key, count in counts.items()])


class Mongo:
    def __init__(self):
        for name in ('clans', 'strike_records', 'strike_profiles', 'strike_war_snapshots',
                     'strike_settings', 'strike_leaves', 'strike_leave_history'):
            setattr(self, name, Collection())
        self.clans.rows['clan'] = {'_id': 'clan', 'tag': CLAN, 'type': 'FWA'}


async def links(tags):
    return PlayerOwners(owners={PLAYER: 9}, unavailable=(), conflicts=())


async def roles(*args):
    return []


def setup():
    db = Mongo()
    return db, StrikeService(db, link_resolver=links, role_resolver=roles)


def war(index, attacks=2):
    return {'clan_tag': CLAN, 'opponent_tag': '#8GG8',
            'end_time': NOW - timedelta(days=10) + timedelta(hours=index),
            'type': 'regular', 'state': 'warEnded', 'attacks_per_member': 2,
            'complete': True, 'members': [{'tag': PLAYER, 'attacks': attacks}]}


async def capture(db, store, index, attacks=2, *, apply=True):
    item = war(index, attacks)
    key = war_key(item)
    db.strike_war_snapshots.rows[f'{GUILD}:{key}'] = {
        '_id': f'{GUILD}:{key}', 'guild_id': GUILD, 'status': 'observing',
        'seen_active': True, 'war_key': key, 'end_time': item['end_time'], 'war': item}
    if apply:
        return await store.process_war(GUILD, item, official_capture=True)
    return item


async def strikes(db, count=5):
    for i in range(count):
        await db.strike_records.insert_one({'_id': f's{i}', 'guild_id': GUILD,
            'player_tag': PLAYER, 'kind': 'strike',
            'occurred_at': NOW - timedelta(days=20) + timedelta(hours=i),
            'expires_at': NOW + timedelta(days=30)})


def removed(db):
    return [row for row in db.strike_records.rows.values() if row.get('revoked_at')]


def test_two_four_six_clear_oldest_softly_and_reset_with_system_audit():
    async def run():
        db, store = setup()
        await strikes(db)
        for index in range(1, 7):
            await capture(db, store, index)
            if index in (2, 4):
                assert [row['_id'] for row in removed(db)] == [f's{i}' for i in range(index // 2)]
                assert removed(db)[-1]['revoke_reason'] == 'Cleared by streak (2 wars played)'
        assert len(removed(db)) == 5
        assert all(row['revoked_by'] == 'system' for row in removed(db))
        assert db.strike_records.rows['s4']['revoke_reason'] == 'Reset by streak (6 wars played)'
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        await store.process_war(GUILD, war(6), official_capture=True)
        assert len(removed(db)) == 5 and len(db.strike_records.rows) == 11
    asyncio.run(run())


@pytest.mark.parametrize('attacks', [0, 1])
def test_missed_attacks_break_streak_and_only_zero_adds_strike(attacks):
    async def run():
        db, store = setup()
        await capture(db, store, 1)
        result = await capture(db, store, 2, attacks)
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        assert result['strikes'] == (1 if attacks == 0 else 0)
    asyncio.run(run())


@pytest.mark.parametrize('neutral', ['leave', 'role'])
def test_fully_played_exempt_accounts_pause_streak(neutral):
    async def run():
        db, store = setup()
        await capture(db, store, 1)
        if neutral == 'role':
            async def exempt(*args):
                return [DEFAULT_EXEMPT_ROLE]
            store.role_resolver = exempt
        else:
            db.strike_leaves.rows['123:9'] = {'_id': '123:9', 'updated_at': NOW - timedelta(days=20),
                'starts_at': NOW - timedelta(days=20), 'until': NOW, 'account_tags': [PLAYER]}
        await capture(db, store, 2)
        assert (await store.streak(GUILD, PLAYER))['count'] == 1
        row = next(row for row in db.strike_records.rows.values() if row['war_key'] == war_key(war(2)))
        assert row['kind'] == 'completed' and row['exemption'] == neutral
        assert (await store.history(GUILD, status='all'))['items'] == []
        assert (await store.history(GUILD, status='exempt'))['items'] == []
        assert (await store.account_list(GUILD, status='all'))['items'] == []
        assert await store.war_list(GUILD) == []
    asyncio.run(run())


def test_expired_strikes_are_not_selected_and_duplicate_does_not_clear_new_target():
    async def run():
        db, store = setup()
        await strikes(db, 3)
        db.strike_records.rows['s0']['expires_at'] = NOW - timedelta(seconds=1)
        await capture(db, store, 1)
        await capture(db, store, 2)
        await store.process_war(GUILD, war(2), official_capture=True)
        assert [r['_id'] for r in removed(db)] == ['s1']
    asyncio.run(run())


def test_crash_after_revoke_resumes_frozen_targets_and_concurrent_retry():
    async def run():
        db, store = setup()
        await strikes(db, 3)
        await capture(db, store, 1)
        original = db.strike_records.update_one
        async def crash(query, update, **kwargs):
            result = await original(query, update, **kwargs)
            if 'revoked_at' in update.get('$set', {}):
                raise RuntimeError('crash after revoke')
            return result
        db.strike_records.update_one = crash
        with pytest.raises(RuntimeError):
            await capture(db, store, 2)
        db.strike_records.update_one = original
        restarted = StrikeService(db, link_resolver=links, role_resolver=roles)
        await asyncio.gather(*(restarted.process_war(GUILD, war(2), official_capture=True) for _ in range(4)))
        assert [r['_id'] for r in removed(db)] == ['s0']
        assert (await restarted.streak(GUILD, PLAYER))['count'] == 2
    asyncio.run(run())


def test_older_unresolved_capture_blocks_newer_until_resolved():
    async def run():
        db, store = setup()
        await capture(db, store, 1, apply=False)
        result = await capture(db, store, 2)
        assert result['deferred_count'] == 1
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        await store.process_war(GUILD, war(1), official_capture=True)
        await store.process_war(GUILD, war(2), official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 2
    asyncio.run(run())


def test_untracked_legacy_import_incomplete_cwl_and_non_lineup_never_count():
    async def run():
        db, store = setup()
        await store.process_war(GUILD, war(1))
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        await store.process_war(GUILD, war(2), official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        item = await capture(db, store, 3, apply=False)
        item['complete'] = False
        await store.process_war(GUILD, item, official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
        cwl = {**war(4), 'type': 'cwl', 'attacks_per_member': 1, 'war_tag': '#8GG8',
               'members': [{'tag': PLAYER, 'attacks': 1}]}
        await store.process_cwl_war(GUILD, cwl)
        other = await capture(db, store, 5, apply=False)
        other['members'] = [{'tag': '#YYY', 'attacks': 2}]
        await store.process_war(GUILD, other, official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('hours,expires', [(24, False), (47.99, False), (48.01, True)])
def test_departure_grace_and_rejoin_keeps_only_unexpired_priority(hours, expires):
    async def run():
        db, store = setup()
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}])
        profile = db.strike_profiles.rows[f'{GUILD}:{PLAYER}']
        profile.update({'roster_seen_at': datetime.now(timezone.utc) - timedelta(hours=hours),
                        'replacement_listed': True, 'replacement_clan_tag': CLAN,
                        'replacement_priority': 'high'})
        await store.sync_roster(GUILD, CLAN, [])
        candidates = await store.replacement(GUILD)
        assert bool(candidates) is not expires
        if not expires:
            assert candidates[0]['departed'] and not candidates[0]['clan_is_current']
            assert candidates[0]['last_seen_clan_tag'] == CLAN
        else:
            assert profile['replacement_clear_reason'] == 'Left clan (48h)'
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}])
        assert bool(profile.get('replacement_listed')) is not expires
        assert 'departed_clan_tag' not in profile
    asyncio.run(run())


def test_concurrent_played_events_do_not_duplicate_receipt_effects():
    async def run():
        db, store = setup()
        await strikes(db, 3)
        await capture(db, store, 1)
        item = await capture(db, store, 2, apply=False)
        original = db.strike_profiles.find_one
        async def yielding_read(*args, **kwargs):
            result = await original(*args, **kwargs)
            await asyncio.sleep(0)
            return result
        db.strike_profiles.find_one = yielding_read
        await asyncio.gather(*(store.process_war(GUILD, item, official_capture=True) for _ in range(8)))
        assert len(removed(db)) == 1
        assert (await store.streak(GUILD, PLAYER))['count'] == 2
    asyncio.run(run())


@pytest.mark.parametrize('source', ['clashking_import', 'clash_api'])
def test_preexisting_rows_never_become_new_streak_events(source):
    async def run():
        db, store = setup()
        item = await capture(db, store, 1, apply=False)
        await store.process_war(GUILD, item)
        row = next(iter(db.strike_records.rows.values()))
        row['capture_source'] = source
        await store.process_war(GUILD, item, official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
    asyncio.run(run())


def test_unknown_roles_defer_fully_played_account_and_block_later_war():
    async def run():
        db, store = setup()
        store.role_resolver = None
        result = await capture(db, store, 1)
        assert result['deferred_count'] == 1
        store.role_resolver = roles
        result = await capture(db, store, 2)
        assert result['deferred_count'] == 1
        assert (await store.streak(GUILD, PLAYER))['count'] == 0
    asyncio.run(run())


def test_departure_exact_boundary_and_concurrent_rejoin_are_safe():
    async def run():
        db, store = setup()
        key = f'{GUILD}:{PLAYER}'
        db.strike_profiles.rows[key] = {'_id': key, 'guild_id': GUILD, 'player_tag': PLAYER,
            'departed_clan_tag': CLAN, 'departed_last_seen_at': NOW - timedelta(hours=48),
            'replacement_clan_tag': CLAN, 'replacement_listed': True}
        await store.expire_departed_replacements(GUILD, now=NOW)
        assert db.strike_profiles.rows[key]['replacement_listed']
        original = db.strike_profiles.update_one
        async def rejoin(query, update, **kwargs):
            db.strike_profiles.rows[key]['current_clan_tag'] = CLAN
            return await original(query, update, **kwargs)
        db.strike_profiles.update_one = rejoin
        await store.expire_departed_replacements(GUILD, now=NOW + timedelta(seconds=1))
        assert db.strike_profiles.rows[key]['replacement_listed']
    asyncio.run(run())


def test_stale_roster_response_cannot_remove_a_rejoined_account():
    async def run():
        db, store = setup()
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}], observed_at=NOW)
        await store.sync_roster(GUILD, CLAN, [], observed_at=NOW - timedelta(minutes=1))
        assert db.strike_profiles.rows[f'{GUILD}:{PLAYER}']['current_clan_tag'] == CLAN
    asyncio.run(run())


def test_cwl_between_regular_wars_is_neutral():
    async def run():
        db, store = setup()
        await capture(db, store, 1)
        cwl = {**war(2), 'type': 'cwl', 'attacks_per_member': 1, 'war_tag': '#8GG8',
               'members': [{'tag': PLAYER, 'attacks': 1}]}
        await store.process_cwl_war(GUILD, cwl)
        assert (await store.streak(GUILD, PLAYER))['count'] == 1
        await capture(db, store, 3)
        assert (await store.streak(GUILD, PLAYER))['count'] == 2
    asyncio.run(run())


def test_streak_overview_is_available_without_any_page_history():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import strikes as api

    async def run():
        db, store = setup()
        db.strike_profiles.rows[f'{api.GUILD_ID}:{PLAYER}'] = {
            '_id': f'{api.GUILD_ID}:{PLAYER}', 'streak_count': 3, 'streak_last_war_key': 'last'}
        store.history = AsyncMock(return_value={'items': [], 'total': 100})
        @asynccontextmanager
        async def mongo(request):
            yield db
        request = SimpleNamespace(method='GET', query={'query': PLAYER, 'offset': '100'}, app={})
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
                patch.object(api.shared, 'mongo', mongo), \
                patch.object(api, 'service', AsyncMock(return_value=store)), \
                patch.object(api, 'clan_rows', AsyncMock(return_value=[])):
            payload = json.loads((await api.overview(request)).text)
        assert payload['entries'] == []
        assert payload['streak'] == {'count': 3, 'last_war_key': 'last'}
    asyncio.run(run())


def test_delayed_finalization_clears_oldest_currently_active_manual_strike():
    async def run():
        db, store = setup()
        await store.add_manual(GUILD, PLAYER, 'Manual strike after war ended', 9)
        await capture(db, store, 1)
        await capture(db, store, 2)
        assert len(removed(db)) == 1 and removed(db)[0]['source'] == 'manual'
    asyncio.run(run())


def test_revoke_failure_keeps_previous_streak_until_durable_receipt_completes():
    async def run():
        db, store = setup()
        await strikes(db, 2)
        await capture(db, store, 1)
        original = db.strike_records.update_one
        async def fail_before(query, update, **kwargs):
            if 'revoked_at' in update.get('$set', {}):
                raise RuntimeError('write unavailable')
            return await original(query, update, **kwargs)
        db.strike_records.update_one = fail_before
        with pytest.raises(RuntimeError):
            await capture(db, store, 2)
        assert (await store.streak(GUILD, PLAYER))['count'] == 1
        assert not removed(db)
        assert db.strike_profiles.rows[f'{GUILD}:{PLAYER}']['streak_pending']['strike_ids'] == ['s0']
        db.strike_records.update_one = original
        await store.process_war(GUILD, war(2), official_capture=True)
        assert (await store.streak(GUILD, PLAYER))['count'] == 2
        assert [row['_id'] for row in removed(db)] == ['s0']
    asyncio.run(run())


def test_transfer_does_not_refresh_old_clan_priority_grace():
    async def run():
        db, store = setup()
        key = f'{GUILD}:{PLAYER}'
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}], observed_at=NOW - timedelta(hours=47))
        db.strike_profiles.rows[key].update({'replacement_listed': True,
            'replacement_clan_tag': CLAN, 'replacement_priority': 'high'})
        await store.sync_roster(GUILD, '#8GG8', [{'tag': PLAYER}], observed_at=NOW)
        assert db.strike_profiles.rows[key]['replacement_listed']
        await store.expire_departed_replacements(GUILD, now=NOW + timedelta(hours=2))
        profile = db.strike_profiles.rows[key]
        assert not profile.get('replacement_listed')
        assert profile['current_clan_tag'] == '#8GG8'
        assert profile['replacement_updated_by'] == 'system'
        assert profile['replacement_clear_reason'] == 'Left clan (48h)'
    asyncio.run(run())


@pytest.mark.parametrize('move', [False, True])
def test_departed_mark_visible_under_original_clan_during_grace(move):
    async def run():
        db, store = setup()
        other = '#8GG8'
        db.clans.rows['other'] = {'_id': 'other', 'tag': other, 'type': 'FWA'}
        start = datetime.now(timezone.utc) - timedelta(hours=6)
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}], observed_at=start)
        profile = db.strike_profiles.rows[f'{GUILD}:{PLAYER}']
        profile.update(replacement_listed=True, replacement_clan_tag=CLAN, replacement_priority='high')
        await store.sync_roster(GUILD, other if move else CLAN, [{'tag': PLAYER}] if move else [])
        for options in ({}, {'clan_tag': CLAN}):
            rows = await store.replacement(GUILD, **options)
            assert len(rows) == 1
            assert rows[0]['departed'] and rows[0]['replacement_listed']
            assert rows[0]['last_seen_clan_tag'] == CLAN
            assert rows[0]['current_clan_tag'] == other if move else not rows[0].get('current_clan_tag')
        if move:
            assert await store.replacement(GUILD, clan_tag=other) == []
            # Leaving the destination must not replace X's original grace clock.
            await store.sync_roster(GUILD, other, [])
            assert profile['departed_clan_tag'] == CLAN
            assert profile['departed_last_seen_at'] == start
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}])
        assert profile['replacement_listed'] and 'departed_clan_tag' not in profile
        assert not (await store.replacement(GUILD, clan_tag=CLAN))[0]['departed']
    asyncio.run(run())


def test_direct_family_return_retains_original_mark():
    async def run():
        db, store = setup()
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}])
        profile = db.strike_profiles.rows[f'{GUILD}:{PLAYER}']
        profile.update(replacement_listed=True, replacement_clan_tag=CLAN)
        await store.sync_roster(GUILD, '#8GG8', [{'tag': PLAYER}])
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}])
        assert profile['replacement_listed'] and 'departed_clan_tag' not in profile
    asyncio.run(run())


@pytest.mark.parametrize('attacks', [0, 2])
def test_owner_conflict_defers_only_disputed_account(attacks):
    async def run():
        db, store = setup()
        other = '#YYY'
        async def disputed(tags):
            return PlayerOwners(owners={other: 10}, conflicts=(PLAYER,), unavailable=())
        store.link_resolver = disputed
        item = await capture(db, store, 1, attacks, apply=False)
        item['members'].append({'tag': other, 'attacks': attacks})
        result = await store.process_war(GUILD, item, official_capture=True)
        assert result['deferred_count'] == 1
        assert result['deferred_accounts'][0]['player_tag'] == PLAYER
        assert result['applied'] == 1
        assert result['strikes'] == (1 if attacks == 0 else 0)
        assert {row['player_tag'] for row in db.strike_records.rows.values()} == {other}
        assert (await store.streak(GUILD, other))['count'] == (1 if attacks == 2 else 0)
    asyncio.run(run())


def test_replacement_api_groups_family_move_under_original_clan():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import strikes as api
    from cwl_web import app
    from utils import clan_weights

    async def run():
        db, store = setup()
        store.replacement = AsyncMock(return_value=[{
            'player_tag': PLAYER, 'current_clan_tag': '#8GG8', 'departed': True,
            'last_seen_clan_tag': CLAN, 'last_seen_at': NOW,
            'replacement_priority': 'high', 'active_strikes': 0, 'weight_difference': None, 'is_manual': True}])
        @asynccontextmanager
        async def mongo(request):
            yield db
        request = SimpleNamespace(method='GET', query={}, app={})
        clans = [{'tag': CLAN, 'name': 'Original', 'is_fwa': True},
                 {'tag': '#8GG8', 'name': 'Destination', 'is_fwa': True}]
        with patch.object(api.shared, 'require_manage', AsyncMock()), \
                patch.object(api.shared, 'mongo', mongo), \
                patch.object(api, 'service', AsyncMock(return_value=store)), \
                patch.object(api, 'clan_rows', AsyncMock(return_value=clans)), \
                patch.object(app, '_store', return_value=object()), \
                patch.object(clan_weights, 'overlay_accounts', return_value={'accounts': []}):
            row = json.loads((await api.replacements(request)).text)['candidates'][0]
        assert (row['clan_tag'], row['clan_name']) == (CLAN, 'Original')
        assert (row['current_clan_tag'], row['current_clan_name']) == ('#8GG8', 'Destination')
        assert row['departed']
    asyncio.run(run())


@pytest.mark.parametrize('elapsed,visible', [(timedelta(hours=48), True),
                                            (timedelta(hours=48, microseconds=1), False)])
def test_transferred_mark_read_grace_without_roster_sync(elapsed, visible):
    from unittest.mock import patch
    import utils.strike_store as module

    class ClockMeta(type):
        def __instancecheck__(self, item):
            return isinstance(item, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return NOW + elapsed

    async def run():
        db, store = setup()
        other = '#8GG8'
        db.clans.rows['other'] = {'_id': 'other', 'tag': other, 'type': 'FWA'}
        await store.sync_roster(GUILD, CLAN, [{'tag': PLAYER}], observed_at=NOW)
        profile = db.strike_profiles.rows[f'{GUILD}:{PLAYER}']
        profile.update(replacement_listed=True, replacement_clan_tag=CLAN,
                       replacement_priority='high')
        await store.sync_roster(GUILD, other, [{'tag': PLAYER}], observed_at=NOW + timedelta(hours=1))
        before = deepcopy(profile)
        # No sync or cleanup succeeds after the transfer. API reads stay read-only.
        with patch.object(module, 'datetime', Clock):
            for options, expected in [({}, visible), ({'clan_tag': CLAN}, visible),
                                      ({'clan_tag': other}, False)]:
                Clock.calls = 0
                rows = await store.replacement(GUILD, **options)
                assert bool(rows) == expected
                assert Clock.calls == 1
                if rows:
                    assert rows[0]['departed'] and rows[0]['last_seen_clan_tag'] == CLAN
        assert profile == before
        # Eventual cleanup owns the durable audit, not a read request.
        await store.expire_departed_replacements(GUILD, now=NOW + elapsed)
        assert bool(profile.get('replacement_listed')) == visible
        if not visible:
            assert profile['replacement_clear_reason'] == 'Left clan (48h)'
    asyncio.run(run())
