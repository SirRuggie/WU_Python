import asyncio
from datetime import timedelta
from types import SimpleNamespace

from tests.test_player_activity import NOW
from tests.test_player_activity_store import ActivityCollection, PLAYER, CLAN
from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_seed import seed_players


def test_background_seed_failures_are_counted_and_rerun_is_safe():
    async def run():
        store = PlayerActivityStore(SimpleNamespace(player_activity=ActivityCollection()))
        for player in (PLAYER, '#8GG8', '#PYY'):
            await store.record({'tag': player, 'attackWins': 1}, CLAN, now=NOW)
        async def fetch(player):
            if player == '#8GG8':
                raise TimeoutError('sensitive upstream detail')
            if player == '#PYY':
                return None
            return NOW-timedelta(days=4)
        async def no_sleep(delay):
            pass
        first = await seed_players(store, fetch, sleep=no_sleep)
        assert first['seeded']==1 and first['failed']==1 and first['unavailable']==1
        again = await seed_players(store, fetch, sleep=no_sleep)
        assert again['already_attempted']==2 and again['official_or_existing']==1
        await store.record({'tag': PLAYER, 'attackWins': 2}, CLAN, now=NOW+timedelta(hours=1))
        await seed_players(store, fetch, force=True, sleep=no_sleep)
        assert (await store.get(PLAYER))['last_seen_source']=='clash_api'
    asyncio.run(run())
