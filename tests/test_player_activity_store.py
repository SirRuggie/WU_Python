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
