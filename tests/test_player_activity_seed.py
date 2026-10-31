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
        assert first['seeded']==1 and first['timeout']==1 and first['unavailable']==1
        again = await seed_players(store, fetch, sleep=no_sleep)
        assert again['already_attempted']==1 and again['official_or_existing']==1 and again['timeout']==1
        await seed_players(store, fetch, sleep=no_sleep)
        capped = await seed_players(store, fetch, sleep=no_sleep)
        assert capped['already_attempted']==2
        await store.record({'tag': PLAYER, 'attackWins': 2}, CLAN, now=NOW+timedelta(hours=1))
        await seed_players(store, fetch, sleep=no_sleep)
        assert (await store.get(PLAYER))['last_seen_source']=='clash_api'
    asyncio.run(run())


def test_seed_http_contract_newest_attack_and_non_200():
    from datetime import datetime, timezone
    import pytest
    from utils.player_activity_seed import fetch_battle_last_seen, SeedHTTPError
    class Response:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def json(self):
            return {'items': [{'battleTime': '20261030T120000.000Z'},
                              {'battleTime': '2026-10-29T12:00:00Z'}]}
    class HTTP:
        def get(self, url, **kwargs):
            assert '%23PC9YGL0JL' in url and url.endswith('/battlelog/history')
            assert set(kwargs['params'])=={'time[after]'}
            assert kwargs['allow_redirects'] is False
            return response
    async def run():
        assert await fetch_battle_last_seen(HTTP(), PLAYER, now=NOW)==datetime(2026,10,30,12,tzinfo=timezone.utc)
        response.status = 503
        with pytest.raises(SeedHTTPError):
            await fetch_battle_last_seen(HTTP(), PLAYER, now=NOW)
    response = Response()
    asyncio.run(run())


def test_seed_concurrency_and_run_deadline_are_bounded():
    async def run():
        store = PlayerActivityStore(SimpleNamespace(player_activity=ActivityCollection()))
        alphabet = '0289PYLQGRJCUV'
        for value in alphabet:
            await store.record({'tag': '#PP'+value, 'attackWins': 1}, CLAN, now=NOW)
        active = maximum = 0
        async def fetch(player):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.Future()
            finally:
                active -= 1
        async def no_sleep(delay):
            pass
        counts = await seed_players(store, fetch, sleep=no_sleep, timeout=0.01)
        assert maximum==5 and active==0
        assert counts['timeout']==len(alphabet)
    asyncio.run(run())
