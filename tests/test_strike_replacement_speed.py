"""Replacement views must never wait for external weight feeds."""
import asyncio

from extensions.commands import strikes


def test_cached_weights_returns_immediately_and_singleflights(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_feed(tags):
        calls.append(tags)
        started.set()
        await release.wait()
        return {'#P2Y': 149000}

    monkeypatch.setattr(strikes, '_provider_weights', slow_feed)
    monkeypatch.setattr(strikes, '_manual_weights', lambda: {})
    monkeypatch.setattr(strikes, '_weight_cache', {})
    monkeypatch.setattr(strikes, '_weight_cache_at', 0.0)
    monkeypatch.setattr(strikes, '_weight_retry_at', 0.0)
    monkeypatch.setattr(strikes, '_weight_refresh_task', None)

    async def run():
        first = strikes.cached_weights(['#P2Y'])
        task = strikes._weight_refresh_task
        second = strikes.cached_weights(['#P2Y'])
        assert first == second == {}
        assert strikes._weight_refresh_task is task
        await asyncio.wait_for(started.wait(), 0.5)
        assert len(calls) == 1
        release.set()
        await task
        assert strikes.cached_weights(['#P2Y']) == {'#P2Y': 149000}

    asyncio.run(run())


def test_failed_refresh_keeps_old_weights_and_cools_down(monkeypatch):
    calls = []

    async def broken_feed(tags):
        calls.append(tags)
        raise RuntimeError('feed down')

    monkeypatch.setattr(strikes, '_provider_weights', broken_feed)
    monkeypatch.setattr(strikes, '_manual_weights', lambda: {'#P2Y': 150000})
    monkeypatch.setattr(strikes, '_weight_cache', {'#P2Y': 149000})
    monkeypatch.setattr(strikes, '_weight_cache_at', 0.0)
    monkeypatch.setattr(strikes, '_weight_retry_at', 0.0)
    monkeypatch.setattr(strikes, '_weight_refresh_task', None)

    async def run():
        assert strikes.cached_weights(['#P2Y']) == {'#P2Y': 150000}
        await strikes._weight_refresh_task
        assert strikes.cached_weights(['#P2Y']) == {'#P2Y': 150000}
        assert len(calls) == 1

    asyncio.run(run())


def test_shutdown_cancels_all_background_strike_tasks(monkeypatch):
    async def forever():
        await asyncio.Event().wait()

    async def run():
        tasks = [asyncio.create_task(forever()) for _ in range(3)]
        monkeypatch.setattr(strikes, '_task', tasks[0])
        monkeypatch.setattr(strikes, '_weight_warm_task', tasks[1])
        monkeypatch.setattr(strikes, '_weight_refresh_task', tasks[2])
        await strikes.stopped(None)
        assert all(task.cancelled() for task in tasks)
        assert strikes._task is None
        assert strikes._weight_warm_task is None
        assert strikes._weight_refresh_task is None

    asyncio.run(run())
