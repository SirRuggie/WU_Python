"""564: bounded background observations, immediate core and write fencing."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cwl_web.strike_activity_cache import snapshots, changing_observations
from cwl_web.strike_activity_reads import read_activity
from utils.player_activity_cache import ActivityPayload, ActivitySnapshots


def test_observations_expire_from_fetch_start_and_are_not_served_after_a_write():
    async def run():
        clock = [1000.0]
        cache = ActivitySnapshots(clock=lambda: clock[0])
        loader = AsyncMock(return_value=ActivityPayload([{'tag': '#PYY'}], [{'kind': 'exempt'}]))
        cold = await cache.get(123, loader, require_observations=True)
        assert cold.observations is None and cold.refreshing
        await cache.entries[123].task
        clock[0] += 30
        assert (await cache.get(123, loader, require_observations=True)).observations == [{'kind': 'exempt'}]
        clock[0] += .01
        expired = await cache.get(123, loader, require_observations=True)
        assert expired.observations is None and expired.refreshing
        cache.invalidate_observations(123)
        task = cache.entries[123].task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        assert cache.entries[123].observations is None
        await cache.close()
    asyncio.run(run())


def test_write_fences_reads_started_during_partial_or_failed_writes():
    async def run():
        app = {}
        cache = snapshots(app)
        good = AsyncMock(return_value=ActivityPayload([], [{'kind': 'exempt'}]))
        await cache.get(123, good, wait=.1)
        with pytest.raises(RuntimeError):
            async with changing_observations(app, 123):
                assert cache.entries[123].observations is None
                await cache.get(123, good, wait=.1, require_observations=True)
                await cache.entries[123].task
                assert cache.entries[123].observations is not None
                raise RuntimeError('partial fixture write')
        assert cache.entries[123].observations is None
        await cache.close()
    asyncio.run(run())


def test_cold_core_returns_without_waiting_for_observations_then_fills_once():
    async def run():
        request = SimpleNamespace(app={})
        release = asyncio.Event()
        async def observations(guild_id):
            assert guild_id == 123
            await release.wait()
            return []
        core = {'profiles': [{'player_tag': '#PYY', 'current_clan_tag': '#CLAN'}],
            'record_totals': {'#PYY': {'active_strikes': 3, 'total_strikes': 5, 'new_this_week': True}},
            'clans': [{'tag': '#CLAN', 'name': 'Family'}], 'clan_warning': False,
            'replacements': [], 'strike_limit': 4}
        ledger = SimpleNamespace(activity_core=AsyncMock(return_value=core),
                                 activity_observations=AsyncMock(side_effect=observations))
        db = SimpleNamespace(player_activity=object())
        with patch('utils.player_activity_store.PlayerActivityStore.overview', AsyncMock(return_value=[{'tag': '#PYY', 'current_clan_tag': '#CLAN'}])), \
             patch('utils.player_activity_store.PlayerActivityStore.history_report', AsyncMock(return_value=[])):
            cold = await asyncio.wait_for(read_activity(request, db, ledger, 123), timeout=.2)
            assert cold.unavailable and cold.updating
            assert cold.context['record_totals']['#PYY']['active_strikes'] == 3
            release.set()
            await snapshots(request.app).entries[123].task
            filled = await read_activity(request, db, ledger, 123)
            assert not filled.unavailable and not filled.updating
            assert filled.warning.startswith('Activity as of ')
            assert ledger.activity_observations.await_count == 1
            assert ledger.activity_core.await_count == 2
        await snapshots(request.app).close()
    asyncio.run(run())


def test_refresh_timeout_preserves_core_and_stops_updating_until_another_attempt():
    async def run():
        request = SimpleNamespace(app={})
        cache = snapshots(request.app)
        cache.timeout = .01  # Same production bound mechanism, no 12-second test sleep.
        drained = asyncio.Event()
        async def observations(guild_id):
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()
        core = {'profiles': [{'player_tag': '#PYY', 'current_clan_tag': '#CLAN'}],
            'record_totals': {'#PYY': {'active_strikes': 3, 'total_strikes': 5, 'new_this_week': True}},
            'clans': [{'tag': '#CLAN', 'name': 'Family'}], 'clan_warning': False,
            'replacements': [], 'strike_limit': 4}
        ledger = SimpleNamespace(activity_core=AsyncMock(return_value=core),
                                 activity_observations=AsyncMock(side_effect=observations))
        db = SimpleNamespace(player_activity=object())
        with patch('utils.player_activity_store.PlayerActivityStore.overview', AsyncMock(return_value=[])), \
             patch('utils.player_activity_store.PlayerActivityStore.history_report', AsyncMock(return_value=[])):
            cold = await read_activity(request, db, ledger, 123)
            assert cold.updating and cold.unavailable
            await cache.entries[123].task
            failed = await read_activity(request, db, ledger, 123)
            assert failed.unavailable and not failed.updating
            assert failed.warning.startswith('Activity unavailable')
            assert failed.context['record_totals']['#PYY']['active_strikes'] == 3
            assert failed.context['record_totals']['#PYY']['total_strikes'] == 5
            assert ledger.activity_observations.await_count == 1 and drained.is_set()
        await cache.close()
    asyncio.run(run())
