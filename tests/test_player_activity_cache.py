"""Optional snapshots never turn missing activity into fresh or healthy data."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from utils.player_activity_cache import ActivitySnapshots


def test_cold_concurrent_warm_stale_and_expired_snapshots():
    async def run():
        now = [1000.0]
        cache = ActivitySnapshots(clock=lambda: now[0])
        release = asyncio.Event()
        async def load():
            await release.wait()
            return [{'tag': 'fixture', 'recent_wars': []}]
        loader = AsyncMock(side_effect=load)
        cold = await asyncio.gather(*(cache.get(123, loader) for _ in range(20)))
        assert all(row.rows is None and row.refreshing for row in cold)
        await asyncio.sleep(0)
        assert loader.await_count == 1
        release.set()
        await cache.entries[123].task
        warm = await cache.get(123, loader)
        assert warm.rows == [{'tag': 'fixture', 'recent_wars': []}]
        assert not warm.stale and not warm.refreshing
        warm.rows[0]['tag'] = 'caller mutation'
        assert (await cache.get(123, loader)).rows[0]['tag'] == 'fixture'
        now[0] += 30
        assert not (await cache.get(123, loader)).stale
        release.clear()
        now[0] += .01
        stale = await cache.get(123, loader)
        assert stale.rows and stale.stale and stale.checked_at and stale.refreshing
        now[0] += 570
        expired = await cache.get(123, loader)
        assert expired.rows is None and expired.checked_at is None
        await cache.close()
        assert not cache.entries
    asyncio.run(run())


def test_failure_retains_good_snapshot_and_logs_once_until_recovery():
    async def run():
        now = [1000.0]
        logger = Mock()
        cache = ActivitySnapshots(clock=lambda: now[0], logger=logger)
        good = AsyncMock(return_value=[{'tag': 'fixture'}])
        await cache.get(123, good, wait=.1)
        bad = AsyncMock(side_effect=TimeoutError('fixture'))
        now[0] += 31
        await cache.get(123, bad)
        await cache.entries[123].task
        for _ in range(5):
            assert (await cache.get(123, bad)).rows == [{'tag': 'fixture'}]
        assert bad.await_count == 1 and logger.warning.call_count == 1
        now[0] += 31
        await cache.get(123, bad)
        await cache.entries[123].task
        assert bad.await_count == 2 and logger.warning.call_count == 1
        now[0] += 540
        assert (await cache.get(123, bad)).rows is None
        await cache.close()
    asyncio.run(run())


def test_refresh_timeout_and_cleanup_drain_children_without_request_ownership():
    async def run():
        cancelled = asyncio.Event()
        started = asyncio.Event()
        async def load():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        cache = ActivitySnapshots(timeout=.01, logger=Mock())
        await cache.get(123, load)
        await cache.entries[123].task
        assert cancelled.is_set() and cache.entries[123].rows is None
        cancelled.clear()
        started.clear()
        cache = ActivitySnapshots(timeout=10)
        request = asyncio.create_task(cache.get(123, load, wait=10))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        await cache.close()
        assert cancelled.is_set()
        with pytest.raises(RuntimeError):
            await cache.get(123, load)
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    asyncio.run(run())
