import asyncio
from datetime import timedelta
from types import SimpleNamespace as NS

from tests.test_player_activity import NOW
from tests.test_player_activity_store import ActivityCollection, PLAYER, CLAN
from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_raids import capture_raids


def test_family_move_attack_and_observed_skip_but_never_historical_skip():
    async def run():
        collection = ActivityCollection()
        store = PlayerActivityStore(NS(player_activity=collection))
        other = '#8GG8'
        for tag in (PLAYER, other):
            await store.record({'tag': tag, 'attackWins': 1}, CLAN, now=NOW-timedelta(hours=2))
        await store.reconcile_membership({PLAYER: CLAN, other: CLAN}, now=NOW-timedelta(minutes=30))
        await store.reconcile_membership({PLAYER: '#8GG8', other: CLAN}, now=NOW+timedelta(minutes=30))
        async def raid(clan, limit):
            return [NS(end_time=NOW, members=[NS(tag=PLAYER, attack_count=3 if clan=='#8GG8' else 2)]),
                    NS(end_time=NOW-timedelta(days=7), members=[])]
        result = await capture_raids(store, NS(get_raid_log=raid), [CLAN, '#8GG8'], now=NOW+timedelta(minutes=30))
        assert result['complete']
        assert (await store.get(PLAYER))['raid_weekends'][-1]['attacked']
        assert (await store.get(PLAYER))['raid_weekends'][-1]['attacks'] == 5
        skipped = (await store.get(other))['raid_weekends']
        assert len(skipped)==1 and not skipped[0]['attacked']
        async def partial(clan, limit):
            if clan==CLAN:
                raise TimeoutError()
            return [NS(end_time=NOW+timedelta(days=7), members=[])]
        await capture_raids(store, NS(get_raid_log=partial), [CLAN, '#8GG8'], now=NOW+timedelta(days=8))
        assert (await store.get(other))['raid_weekends']==skipped
    asyncio.run(run())


def test_entire_family_without_raid_entries_can_have_an_observed_skip():
    from datetime import datetime, timezone
    async def run():
        end = datetime(2026, 11, 2, 7, tzinfo=timezone.utc)
        store = PlayerActivityStore(NS(player_activity=ActivityCollection()))
        await store.record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=end-timedelta(hours=2))
        await store.reconcile_membership({PLAYER: CLAN}, now=end-timedelta(minutes=30))
        await store.reconcile_membership({PLAYER: CLAN}, now=end+timedelta(minutes=30))
        async def empty(*args, **kwargs):
            return []
        await capture_raids(store, NS(get_raid_log=empty), [CLAN], now=end+timedelta(minutes=30))
        rows = (await store.get(PLAYER))['raid_weekends']
        assert rows == [{'weekend_id': end.isoformat(), 'attacked': False, 'attacks': 0}]
    asyncio.run(run())
