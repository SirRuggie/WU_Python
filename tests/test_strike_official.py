"""Official current-war snapshots are durable and fail closed without a final."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import coc
from pymongo.errors import DuplicateKeyError

from extensions.commands.strikes import _finish_official_war, _league_observations
from utils.strike_official import normalize
from utils.strike_tracking import StrikeTracking
from utils.recruit_links import PlayerOwners
from utils.strike_store import StrikeService, DEFAULT_EXEMPT_ROLE
from test_strike_review import Mongo

GUILD = 123
CLAN = '#2UVGQU9'
OPPONENT = '#8GG8'
PLAYER = '#PC9YGL0JL'


class Rows:
    def __init__(self):
        self.rows = {}

    @staticmethod
    def matches(row, query):
        for field, expected in query.items():
            value = row.get(field)
            if isinstance(expected, dict):
                if '$lte' in expected and (value is None or value > expected['$lte']):
                    return False
                if '$ne' in expected and value == expected['$ne']:
                    return False
                if '$in' in expected and value not in expected['$in']:
                    return False
            elif value != expected:
                return False
        return True

    async def create_index(self, *args, **kwargs):
        return None

    async def find_one(self, query, projection=None, sort=None):
        found = [row for row in self.rows.values() if self.matches(row, query)]
        if sort:
            found.sort(key=lambda row: row[sort[0][0]], reverse=sort[0][1] < 0)
        return deepcopy(found[0]) if found else None

    async def insert_one(self, row):
        if row['_id'] in self.rows:
            raise DuplicateKeyError('duplicate')
        self.rows[row['_id']] = deepcopy(row)

    async def update_one(self, query, update, upsert=False):
        row = self.rows.get(query['_id'])
        if row is None and upsert:
            row = {'_id': query['_id'], **deepcopy(update.get('$setOnInsert', {}))}
            self.rows[query['_id']] = row
        if row is None or not self.matches(row, query):
            return SimpleNamespace(matched_count=0)
        row.update(deepcopy(update.get('$set', {})))
        return SimpleNamespace(matched_count=1)

    def find(self, query, projection=None):
        found = [deepcopy(row) for row in self.rows.values() if self.matches(row, query)]
        async def listed(length=None):
            return found[:length] if length else found
        return SimpleNamespace(to_list=listed)


def tracking():
    mongo = SimpleNamespace(strike_war_snapshots=Rows(), strike_tracking=Rows(),
                            strike_records=Rows())
    return StrikeTracking(mongo)


def real_war(state, *, end=None, hits=0, kind='random'):
    """Pass actual official response JSON through installed coc.ClanWar."""
    end = end or datetime.now(timezone.utc) - timedelta(minutes=2)
    fmt = lambda value: value.strftime('%Y%m%dT%H%M%S.000Z')
    attacks = [{'attackerTag': PLAYER, 'defenderTag': OPPONENT, 'stars': 2,
                'destructionPercentage': 75, 'order': 1, 'duration': 120}][:hits]
    def side(clan_tag, member_tag, member_attacks):
        return {'tag': clan_tag, 'name': clan_tag, 'clanLevel': 20,
                'attacks': len(member_attacks), 'stars': 0,
                'destructionPercentage': 0,
                'members': [{'tag': member_tag, 'name': 'Player', 'townhallLevel': 17,
                             'mapPosition': 1, 'opponentAttacks': 0,
                             'bestOpponentAttack': {}, 'attacks': member_attacks}]}
    raw = {'state': state, 'teamSize': 1, 'attacksPerMember': 2,
           'preparationStartTime': fmt(end - timedelta(days=1, hours=23)),
           'startTime': fmt(end - timedelta(days=1)), 'endTime': fmt(end),
           'clan': side(CLAN, PLAYER, attacks),
           'opponent': side(OPPONENT, OPPONENT, [])}
    if kind == 'cwl':
        raw['tag'] = '#2UVGQU9'
        raw['attacksPerMember'] = 1
    return coc.ClanWar(data=raw, client=SimpleNamespace(raw_attribute=True), clan_tag=CLAN)


def test_real_coc_model_normalizes_public_attack_details_and_enum():
    war = normalize(real_war('inWar', hits=1), CLAN)
    assert war['state'] == 'inWar' and war['type'] == 'regular'
    assert war['members'][0]['town_hall'] == 17
    assert war['members'][0]['map_position'] == 1
    assert war['members'][0]['attacks'] == 1
    assert war['members'][0]['attack_details'][0]['stars'] == 2
    assert war['complete'] is True


def test_24_hour_friendly_is_observed_without_strikes_and_23_hour_regular_can_strike():
    async def run():
        owner = tracking()
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        for index, (prep_hours, expected) in enumerate(((24, 'friendly'), (23, 'regular'))):
            model = real_war('warEnded', end=datetime.now(timezone.utc) -
                             timedelta(days=index, minutes=2))
            model.preparation_start_time = SimpleNamespace(
                time=model.start_time.time - timedelta(hours=prep_hours))
            final = normalize(model, CLAN)
            assert final['type'] == expected
            active = {**final, 'state': 'inWar'}
            await owner.observe(GUILD, active, now=final['end_time'] - timedelta(hours=2))
            result = await _finish_official_war(owner, store, GUILD, final)
            assert result[0] == (1 if expected == 'regular' else 0)
        assert store.process_war.await_count == 1
    asyncio.run(run())


def test_aggregate_mismatch_or_missing_start_cannot_finalize():
    for kind in ('random', 'cwl'):
        war = real_war('warEnded', hits=0, kind=kind)
        war.clan.attacks_used = 1
        assert normalize(war, CLAN)['complete'] is False
    war = real_war('warEnded')
    war.start_time = None
    try:
        normalize(war, CLAN)
    except ValueError as error:
        assert 'timing' in str(error)
    else:
        raise AssertionError('missing start must fail closed')


def test_cwl_middle_round_is_observed_despite_later_placeholders():
    async def run():
        war = real_war('inWar', kind='cwl')
        client = SimpleNamespace(
            get_league_group=AsyncMock(return_value=SimpleNamespace(
                rounds=[['#WAR1']] + [['#0'] for _ in range(6)])),
            get_league_war=AsyncMock(return_value=war))
        observed = await _league_observations(client, CLAN, {})
        assert len(observed) == 1 and observed[0]['state'] == 'inWar'
        client.get_league_war.assert_awaited_once_with('#WAR1')
    asyncio.run(run())


def test_active_then_final_once_across_restart_and_same_ledger_key():
    async def run():
        owner = tracking()
        active = normalize(real_war('inWar'), CLAN)
        final = normalize(real_war('warEnded', end=active['end_time']), CLAN)
        saved = await owner.observe(GUILD, active, now=active['end_time'] - timedelta(minutes=5))
        assert saved['next_check_at'] == active['end_time'] + timedelta(seconds=60)
        assert await owner.due_clans(GUILD, now=active['end_time']) == set()
        assert await owner.due_clans(GUILD, now=active['end_time'] + timedelta(seconds=61)) == {CLAN}
        restarted = StrikeTracking(owner.mongo)
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        result = await _finish_official_war(restarted, store, GUILD, final)
        assert result == (1, 0, 0, 0)
        assert store.process_war.await_count == 1
        assert await _finish_official_war(restarted, store, GUILD, final) == (0, 0, 0, 0)
        assert store.process_war.await_count == 1
        assert (await restarted.snapshot(GUILD, final))['status'] == 'finalized'
    asyncio.run(run())


def test_no_active_capture_or_missing_final_makes_zero_strikes_and_review_row():
    async def run():
        owner = tracking()
        final = normalize(real_war('warEnded'), CLAN)
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        assert await _finish_official_war(owner, store, GUILD, final) == (0, 0, 0, 0)
        assert await owner.snapshot(GUILD, final) is None
        active = normalize(real_war('inWar', end=final['end_time']), CLAN)
        await owner.observe(GUILD, active)
        next_war = {**active, 'end_time': active['end_time'] + timedelta(days=2)}
        assert await owner.abandon_older(GUILD, CLAN,
                {owner.snapshot_key(GUILD, next_war)}, now=active['end_time'] + timedelta(minutes=1)) == 1
        incomplete = await owner.incomplete_wars(GUILD)
        assert len(incomplete) == 1 and incomplete[0]['strikes'] == 0
        assert 'review in Find war' in incomplete[0]['review_message']
        store.process_war.assert_not_awaited()
    asyncio.run(run())


def test_active_and_incomplete_final_never_post_and_pending_requires_complete_end():
    async def run():
        owner = tracking()
        active = normalize(real_war('inWar'), CLAN)
        await owner.observe(GUILD, active)
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        assert await _finish_official_war(owner, store, GUILD, active) == (0, 0, 0, 0)
        assert await owner.pending_finals(GUILD, CLAN) == []
        final = {**active, 'state': 'warEnded', 'complete': False}
        assert await _finish_official_war(owner, store, GUILD, final) == (0, 0, 0, 1)
        assert await owner.pending_finals(GUILD, CLAN) == []
        store.process_war.assert_not_awaited()
    asyncio.run(run())


def test_removed_clan_snapshot_abandoned_once_and_cannot_reactivate():
    async def run():
        owner = tracking()
        active = normalize(real_war('inWar'), CLAN)
        await owner.observe(GUILD, active, now=active['end_time'] - timedelta(minutes=5))
        assert await owner.abandon_untracked(GUILD, set()) == {CLAN}
        assert await owner.abandon_untracked(GUILD, set()) == set()
        assert await owner.due_clans(GUILD, now=active['end_time'] + timedelta(hours=1)) == set()
        final = {**active, 'state': 'warEnded'}
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        assert await _finish_official_war(owner, store, GUILD, final) == (0, 0, 0, 0)
        assert (await owner.snapshot(GUILD, final))['status'] == 'abandoned'
        store.process_war.assert_not_awaited()
    asyncio.run(run())


def test_tracking_health_uses_latest_war_and_unknown_private_stale_fail_closed():
    async def run():
        owner = tracking()
        clans = [{'tag': CLAN, 'name': 'Clan'}]
        async def finish(state='notInWar', **kwargs):
            token = await owner.begin(GUILD, CLAN)
            await owner.finish(GUILD, CLAN, started_at=token,
                               current_war_state=state, **kwargs)
            return (await owner.rows(GUILD, clans))[0]
        unknown = await finish('unknown')
        assert unknown['status'] == 'behind'
        assert owner.mongo.strike_tracking.rows[owner.key(GUILD, CLAN)]['last_scan_status'] == 'needs_review'
        assert (await finish('private', private=True))['status'] == 'private'
        await owner.begin(GUILD, CLAN)
        assert (await owner.rows(GUILD, clans))[0]['status'] == 'behind'
        assert (await finish('private', private=True,
                             error='War source unavailable'))['status'] == 'error'

        old_end = datetime.now(timezone.utc) - timedelta(days=30)
        old = normalize(real_war('inWar', end=old_end), CLAN)
        await owner.observe(GUILD, old, now=old_end - timedelta(minutes=5))
        await owner.abandon_older(GUILD, CLAN, set(), now=old_end + timedelta(minutes=2))
        assert (await finish())['status'] == 'behind'

        recent_end = datetime.now(timezone.utc) - timedelta(days=1)
        recent = normalize(real_war('inWar', end=recent_end), CLAN)
        await owner.observe(GUILD, recent, now=recent_end - timedelta(minutes=5))
        await owner.finalized(GUILD, {**recent, 'state': 'warEnded'})
        await owner.mongo.strike_records.insert_one({
            '_id': 'recent', 'guild_id': GUILD, 'clan_tag': CLAN,
            'source': 'war', 'occurred_at': recent_end})
        assert (await finish())['status'] == 'healthy'

        stale_end = datetime.now(timezone.utc) - timedelta(days=4)
        owner.mongo.strike_records.rows['recent']['occurred_at'] = stale_end
        owner.mongo.strike_war_snapshots.rows[owner.snapshot_key(GUILD, recent)]['end_time'] = stale_end
        assert (await finish())['status'] == 'behind'
    asyncio.run(run())


def test_recent_incomplete_war_beats_older_recorded_war_for_health():
    async def run():
        owner = tracking()
        now = datetime.now(timezone.utc)
        await owner.mongo.strike_records.insert_one({
            '_id': 'older-record', 'guild_id': GUILD, 'clan_tag': CLAN,
            'source': 'war', 'occurred_at': now - timedelta(days=2)})
        ended = now - timedelta(hours=1)
        active = normalize(real_war('inWar', end=ended), CLAN)
        await owner.observe(GUILD, active, now=ended - timedelta(minutes=5))
        await owner.abandon_older(GUILD, CLAN, set(), now=ended + timedelta(minutes=2))
        token = await owner.begin(GUILD, CLAN)
        await owner.finish(GUILD, CLAN, started_at=token,
                           current_war_state='notInWar')
        # The recorded war is recent, and every other health flag is clear.
        assert (await owner.rows(GUILD, [{'tag': CLAN}]))[0]['status'] == 'behind'
    asyncio.run(run())


def test_unknown_current_state_is_behind_even_with_recent_record():
    async def run():
        owner = tracking()
        await owner.mongo.strike_records.insert_one({
            '_id': 'recent-record', 'guild_id': GUILD, 'clan_tag': CLAN,
            'source': 'war', 'occurred_at': datetime.now(timezone.utc) - timedelta(hours=1)})
        token = await owner.begin(GUILD, CLAN)
        await owner.finish(GUILD, CLAN, started_at=token,
                           current_war_state='unknown')
        assert (await owner.rows(GUILD, [{'tag': CLAN}]))[0]['status'] == 'behind'
    asyncio.run(run())


def test_source_failure_backoff_and_final_payload_survive_new_prep():
    async def run():
        owner = tracking()
        active = normalize(real_war('inWar'), CLAN)
        await owner.observe(GUILD, active, now=active['end_time'] - timedelta(minutes=5))
        due = active['end_time'] + timedelta(seconds=61)
        await owner.defer_due(GUILD, CLAN, now=due)
        row = await owner.snapshot(GUILD, active)
        assert row['next_check_at'] >= due + timedelta(seconds=60)
        final = normalize(real_war('warEnded', end=active['end_time']), CLAN)
        await owner.observe(GUILD, final)
        next_war = {**active, 'end_time': active['end_time'] + timedelta(days=2)}
        await owner.abandon_older(GUILD, CLAN,
                                  {owner.snapshot_key(GUILD, next_war)},
                                  now=active['end_time'] + timedelta(minutes=2))
        assert (await owner.snapshot(GUILD, final))['status'] == 'observing'
        assert len(await owner.pending_finals(GUILD, CLAN)) == 1
    asyncio.run(run())


def test_official_final_honors_one_miss_role_and_leave():
    async def run():
        for case in ('one_miss', 'role', 'leave'):
            from test_strike_streaks import Collection
            mongo = Mongo()
            mongo.strike_profiles = Collection()
            mongo.strike_records = Collection()
            mongo.strike_war_snapshots = Rows()
            owner = StrikeTracking(mongo)
            async def links(tags):
                return PlayerOwners(owners={} if case == 'one_miss' else {PLAYER: '456'})
            async def roles(guild_id, member_id):
                return [DEFAULT_EXEMPT_ROLE] if case == 'role' else []
            final = normalize(real_war('warEnded', hits=1 if case == 'one_miss' else 0), CLAN)
            if case == 'leave':
                ended = final['end_time']
                mongo.strike_leaves.rows['123:456'] = {
                    '_id': '123:456', 'guild_id': GUILD, 'member_id': 456,
                    'starts_at': ended - timedelta(days=1),
                    'updated_at': ended - timedelta(days=1),
                    'until': ended + timedelta(days=1),
                    'account_tags': [PLAYER],
                }
            active = normalize(real_war('inWar', end=final['end_time'],
                                        hits=1 if case == 'one_miss' else 0), CLAN)
            await owner.observe(GUILD, active, now=final['end_time'] - timedelta(hours=2))
            service = StrikeService(mongo, link_resolver=links, role_resolver=roles)
            assert await _finish_official_war(owner, service, GUILD, final) == (1, 0, 0, 0)
            rows = list(mongo.strike_records.rows.values())
            assert len(rows) == 1
            assert rows[0]['kind'] == {'one_miss': 'missed', 'role': 'exempt',
                                      'leave': 'exempt'}[case]
            assert rows[0]['capture_source'] == 'clash_api'
            assert rows[0]['exemption'] == {'one_miss': None, 'role': 'role',
                                            'leave': 'leave'}[case]
            assert (await owner.snapshot(GUILD, final))['status'] == 'finalized'
    asyncio.run(run())


def test_saved_final_replays_after_bson_timezone_loss():
    from bson import BSON

    async def run():
        owner = tracking()
        final = normalize(real_war('warEnded'), CLAN)
        await owner.observe(GUILD, {**final, 'state': 'inWar'},
                            now=final['end_time'] - timedelta(hours=1))
        stored_final = BSON(BSON.encode(final)).decode()
        assert stored_final['end_time'].tzinfo is None
        store = SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count': 0}))
        result = await _finish_official_war(owner, store, GUILD, stored_final)
        assert result == (1, 0, 0, 0)
        assert (await owner.snapshot(GUILD, stored_final))['status'] == 'finalized'
        assert await _finish_official_war(owner, store, GUILD, stored_final) == (0, 0, 0, 0)
        store.process_war.assert_awaited_once()
    asyncio.run(run())
