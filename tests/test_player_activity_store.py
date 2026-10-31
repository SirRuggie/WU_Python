import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

from tests.test_player_activity import NOW
from tests.test_strike_streaks import Collection, matches
from utils.player_activity_store import PlayerActivityStore

PLAYER = '#PC9YGL0JL'
CLAN = '#2UVGQU9'


class ActivityCollection(Collection):
    async def replace_one(self, query, document):
        row = next((row for row in self.rows.values() if matches(row, query)), None)
        if row is None:
            return SimpleNamespace(matched_count=0)
        self.rows[row['_id']] = deepcopy(document)
        return SimpleNamespace(matched_count=1)

    async def update_one(self, query, update, upsert=False):
        before = deepcopy(self.rows)
        result = await super().update_one(query, update, upsert)
        result.modified_count = int(before != self.rows)
        return result


def test_one_document_per_player_after_400_days_and_late_read_ignored():
    async def run():
        collection = ActivityCollection()
        store = PlayerActivityStore(SimpleNamespace(player_activity=collection))
        for day in range(400):
            for player in (PLAYER, '#8GG8'):
                await store.record({'tag': player, 'attackWins': day}, CLAN,
                                   now=NOW + timedelta(days=day))
        assert len(collection.rows) == 2
        saved = await store.get(PLAYER)
        assert len(saved['active_days']) == 30
        assert not await store.record({'tag': PLAYER, 'attackWins': 999}, CLAN, now=NOW)
        assert await store.get(PLAYER) == saved
    asyncio.run(run())


def test_seed_membership_and_raid_backfill_safety():
    async def run():
        collection = ActivityCollection()
        store = PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=NOW)
        assert await store.seed(PLAYER, NOW - timedelta(days=2), now=NOW)
        assert not await store.seed(PLAYER, NOW - timedelta(days=1), now=NOW)
        await store.record({'tag': PLAYER, 'attackWins': 2}, CLAN, now=NOW + timedelta(hours=1))
        assert not await store.seed(PLAYER, NOW, now=NOW + timedelta(hours=2))
        assert (await store.get(PLAYER))['last_seen_source'] == 'clash_api'
        await store.reconcile_membership({}, now=NOW + timedelta(hours=2))
        assert (await store.get(PLAYER))['left_at'] is not None
        await store.reconcile_membership({PLAYER: CLAN}, now=NOW + timedelta(hours=3))
        assert (await store.get(PLAYER))['left_at'] is None
        assert not await store.record_weekend(PLAYER, '2026-10-01', 0, observed_member=False)
        for weekend in range(10):
            await store.record_weekend(PLAYER, f'2026-{weekend:02d}', 1, observed_member=False)
        await store.record_weekend(PLAYER, '2026-09', 0, observed_member=True)
        raids = (await store.get(PLAYER))['raid_weekends']
        assert len(raids) == 8
        assert raids[-1]['attacked']
    asyncio.run(run())


def test_seed_cannot_override_an_official_first_seen():
    async def run():
        store = PlayerActivityStore(SimpleNamespace(player_activity=ActivityCollection()))
        await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=NOW)
        await store.record({'tag': PLAYER, 'attackWins': 2}, CLAN, now=NOW+timedelta(hours=1))
        before = await store.get(PLAYER)
        assert not await store.seed(PLAYER, NOW-timedelta(days=2), now=NOW+timedelta(hours=2))
        assert await store.get(PLAYER) == before
    asyncio.run(run())


def test_membership_cas_loss_is_logged_without_claiming_success(caplog):
    async def run():
        collection=ActivityCollection()
        store=PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        async def conflict(*args,**kwargs): return SimpleNamespace(matched_count=0)
        collection.update_one=conflict
        await store.reconcile_membership({},now=NOW+timedelta(hours=1))
        assert not (await store.get(PLAYER)).get('left_at')
        assert 'membership CAS conflict' in caplog.text
    asyncio.run(run())


def test_unchanged_hourly_poll_and_membership_only_write_daily_or_at_boundary():
    async def run():
        class CountCollection(ActivityCollection):
            writes=0
            async def update_one(self,*args,**kwargs):
                self.writes+=1;return await super().update_one(*args,**kwargs)
            async def replace_one(self,*args,**kwargs):
                self.writes+=1;return await super().replace_one(*args,**kwargs)
        collection=CountCollection();store=PlayerActivityStore(SimpleNamespace(player_activity=collection))
        payload={'tag':PLAYER,'attackWins':1}
        await store.record(payload,CLAN,now=NOW)
        await store.reconcile_membership({PLAYER:CLAN},now=NOW)
        writes=collection.writes
        for hour in range(1,5):
            await store.reconcile_membership({PLAYER:CLAN},now=NOW+timedelta(hours=hour))
            assert not await store.record(payload,CLAN,now=NOW+timedelta(hours=hour))
        assert collection.writes==writes
        assert await store.record(payload,CLAN,now=NOW+timedelta(days=1))
        assert await store.record({**payload,'attackWins':2},CLAN,now=NOW+timedelta(days=1,hours=1))
    asyncio.run(run())


def test_raid_membership_bracket_requires_recent_observation_and_pre_end_join():
    from datetime import datetime, timezone
    end = datetime(2026, 10, 26, 7, tzinfo=timezone.utc)
    async def run():
        for age, joined_after, expected in ((90, False, True), (91, False, False), (60, True, False)):
            collection = ActivityCollection()
            store = PlayerActivityStore(SimpleNamespace(player_activity=collection))
            await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=end-timedelta(minutes=90))
            row = collection.rows[PLAYER]
            row.update(family_since=end+timedelta(seconds=1) if joined_after else end-timedelta(days=7),
                       last_roster_at=end-timedelta(minutes=age-15))
            await store.reconcile_membership({PLAYER: CLAN}, now=end+timedelta(minutes=15))
            assert (end.isoformat() in (await store.get(PLAYER)).get('raid_membership_ends', [])) is expected
    asyncio.run(run())


def test_membership_retries_one_seed_revision_race_and_preserves_boundary():
    from datetime import datetime, timezone
    async def run():
        class Race(ActivityCollection):
            raced=False
            async def update_one(self,q,u,upsert=False):
                if not self.raced and 'raid_membership_ends' in u.get('$set',{}):
                    self.raced=True
                    self.rows[PLAYER]['revision']+=1
                    self.rows[PLAYER]['seed_status']='seeded'
                    return SimpleNamespace(matched_count=0)
                return await super().update_one(q,u,upsert)
        end=datetime(2026,10,26,7,tzinfo=timezone.utc)
        c=Race();store=PlayerActivityStore(SimpleNamespace(player_activity=c))
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=end-timedelta(minutes=10))
        c.rows[PLAYER].update(family_since=end-timedelta(days=7),last_roster_at=end-timedelta(minutes=10))
        await store.reconcile_membership({PLAYER:CLAN},now=end+timedelta(minutes=15))
        row=await store.get(PLAYER)
        assert c.raced and row['seed_status']=='seeded'
        assert end.isoformat() in row['raid_membership_ends']
    asyncio.run(run())


def test_clan_cache_is_not_a_player_and_retirement_preserves_cache():
    async def run():
        c = ActivityCollection()
        store = PlayerActivityStore(SimpleNamespace(player_activity=c))
        await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=NOW)
        await store.save_history_clan(CLAN, {'status': 'complete', 'version': 1,
                                            'wars': []}, now=NOW)
        assert [row['_id'] for row in await store.all_players()] == [PLAYER]
        assert [row['tag'] for row in await store.overview()] == [PLAYER]
        assert await store.history_report() == []
        await store.reconcile_membership({PLAYER: CLAN}, now=NOW)
        assert not (await store.history_clans())[0].get('left_at')
        await store.retire_history_clans(set(), now=NOW)
        assert (await store.history_clans())[0]['left_at'] == NOW
        assert len(await store.all_players()) == 1
    asyncio.run(run())


def test_naive_bson_war_timestamps_do_not_rewrite_unchanged_rows():
    async def run():
        collection=ActivityCollection();store=PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        observation={'war_key':'known','occurred_at':NOW,'attacks_used':0,'attacks_available':2}
        await store.save_recent_wars(PLAYER,[observation],version=3,now=NOW)
        revision=(await store.get(PLAYER))['revision']
        collection.rows[PLAYER]['recent_wars'][0]['occurred_at']=NOW.replace(tzinfo=None)
        for hour in (1,2,3):
            assert not await store.save_recent_wars(PLAYER,[observation],version=3,
                                                   now=NOW+timedelta(hours=hour))
            assert (await store.get(PLAYER))['revision']==revision
    asyncio.run(run())
