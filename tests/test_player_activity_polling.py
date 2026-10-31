import asyncio
from types import SimpleNamespace
from utils.player_activity_polling import poll_hour


def test_poll_spreads_hour_and_failure_does_not_write():
    async def run():
        writes = []
        delays = []
        tick = [0.0]
        async def sleep(delay):
            delays.append(delay)
            tick[0] += delay
        async def fetch(tag):
            if tag == '#B':
                raise TimeoutError()
            return {'tag': tag, 'attackWins': 1}
        async def record(player, clan):
            writes.append((player, clan))
        result = await poll_hour(SimpleNamespace(record=record),
                                 {'#A': '#CLAN', '#B': '#CLAN'}, fetch,
                                 sleep=sleep, clock=lambda: tick[0])
        assert delays == [0, 1800]
        assert result == {'success': 1, 'failure': 1}
        assert len(writes) == 1
    asyncio.run(run())
