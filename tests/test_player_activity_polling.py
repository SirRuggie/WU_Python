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


def test_identity_mismatch_and_cancellation_do_not_write():
    async def run():
        writes = []
        async def record(*args):
            writes.append(args)
        async def wrong(tag):
            return {'tag': '#OTHER'}
        async def no_sleep(delay):
            pass
        store = SimpleNamespace(record=record)
        result = await poll_hour(store, {'#A': '#CLAN'}, wrong, sleep=no_sleep)
        assert result['failure'] == 1
        assert writes == []
        async def cancel(tag):
            raise asyncio.CancelledError()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await poll_hour(store, {'#A': '#CLAN'}, cancel, sleep=no_sleep)
        assert writes == []
    asyncio.run(run())


def test_worker_cancels_its_background_seed_on_shutdown(monkeypatch):
    from utils import player_activity_polling as polling
    async def scenario():
        seed_started = asyncio.Event()
        seed_stopped = asyncio.Event()
        class Store:
            def __init__(self, mongo):
                pass
            async def ensure_indexes(self):
                pass
            async def reconcile_membership(self, members):
                pass
        async def family(*args):
            return {'#A': '#CLAN'}
        async def raids(*args):
            return {}
        async def hour(*args):
            return {'success': 1, 'failure': 0}
        async def seed(store):
            seed_started.set()
            try:
                await asyncio.Future()
            finally:
                seed_stopped.set()
        monkeypatch.setattr(polling, 'PlayerActivityStore', Store)
        monkeypatch.setattr(polling, 'family_members', family)
        monkeypatch.setattr(polling, 'capture_raids', raids)
        monkeypatch.setattr(polling, 'poll_hour', hour)
        monkeypatch.setattr(polling, 'seed_from_clashking', seed)
        task = asyncio.create_task(polling.run(None, SimpleNamespace(get_player=None)))
        await seed_started.wait()
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seed_stopped.is_set()
    asyncio.run(scenario())


def test_transient_index_failure_does_not_permanently_kill_worker(monkeypatch):
    import pytest
    from utils import player_activity_polling as polling
    async def scenario():
        attempts = []
        class Store:
            def __init__(self, mongo):
                pass
            async def ensure_indexes(self):
                attempts.append(1)
                if len(attempts)==1:
                    raise TimeoutError()
            async def reconcile_membership(self, members):
                pass
        async def family(*args):
            return {}
        async def raids(*args):
            pass
        async def stop(*args):
            raise asyncio.CancelledError()
        async def no_sleep(delay):
            pass
        monkeypatch.setattr(polling, 'PlayerActivityStore', Store)
        monkeypatch.setattr(polling, 'family_members', family)
        monkeypatch.setattr(polling, 'capture_raids', raids)
        monkeypatch.setattr(polling, 'poll_hour', stop)
        monkeypatch.setattr(polling.asyncio, 'sleep', no_sleep)
        with pytest.raises(asyncio.CancelledError):
            await polling.run(None, SimpleNamespace(get_player=None))
        assert len(attempts)==2
    asyncio.run(scenario())
