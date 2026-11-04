"""Fresh core is required even when a raw activity snapshot is warm."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pymongo.errors import NetworkTimeout

from cwl_web.strike_activity_reads import read_activity
from cwl_web.strike_activity_cache import snapshots
from utils.player_activity_overview import family_activity_rows
from utils.player_activity_cache import ActivityPayload


def fixture():
    core = {'profiles': [{'player_tag': '#PYY', 'current_clan_tag': '#CLAN'}],
        'clans': [{'tag': '#CLAN', 'name': 'Family'}], 'clan_warning': False,
        'record_totals': {'#PYY': {'active_strikes': 3, 'total_strikes': 5, 'new_this_week': True}},
        'replacements': [], 'strike_limit': 4}
    return SimpleNamespace(activity_core=AsyncMock(return_value=core),
        activity_observations=AsyncMock(return_value=[]))


def test_warm_snapshot_keeps_core_and_manual_dispositions_fresh_and_stale_signals_known():
    async def run():
        now = [1000.0]
        request = SimpleNamespace(app={})
        cache = snapshots(request.app)
        cache.clock = lambda: now[0]
        ledger = fixture()
        stamp = datetime.now(timezone.utc)
        activity = [{'tag': '#PYY', 'current_clan_tag': '#CLAN', 'updated_at': stamp,
                     'recent_wars': [{'war_key': 'war', 'occurred_at': stamp, 'attacks_used': 0, 'attacks_available': 2}]}]
        with patch('utils.player_activity_store.PlayerActivityStore.overview', AsyncMock(return_value=activity)), \
             patch('utils.player_activity_store.PlayerActivityStore.history_report', AsyncMock(return_value=[])):
            async def load():
                return ActivityPayload(activity, await ledger.activity_observations(123))
            await cache.get(123, load, require_observations=True)
            await cache.entries[123].task
            first = await read_activity(request, SimpleNamespace(player_activity=object()), ledger, 123)
            assert family_activity_rows(first.activity, **first.context)[0]['no_attack_wars'] == 1
            ledger.activity_core.return_value['record_totals']['#PYY']['active_strikes'] = 2
            ledger.activity_observations.return_value = [{'player_tag': '#PYY', 'source': 'war', 'kind': 'exempt', 'war_key': 'war'}]
            now[0] += 31
            cache.invalidate_observations(123)  # Dashboard edit invalidates immediately (564).
            await cache.get(123, load, require_observations=True)
            await cache.entries[123].task
            second = await read_activity(request, SimpleNamespace(player_activity=object()), ledger, 123)
            row = family_activity_rows(second.activity, **second.context)[0]
            assert row['active_strikes'] == 2 and row['total_strikes'] == 5
            assert row['no_attack_wars'] == 0
            assert second.warning.startswith('Activity as of ') and not second.unavailable
            assert ledger.activity_core.await_count == ledger.activity_observations.await_count == 2
        await cache.close()
    asyncio.run(run())


def test_core_error_is_never_replaced_by_cached_activity_or_zero_counts():
    async def run():
        request = SimpleNamespace(app={})
        cache = snapshots(request.app)
        await cache.get(123, AsyncMock(return_value=[]), wait=.1)
        ledger = fixture()
        ledger.activity_core.side_effect = NetworkTimeout('fixture core unavailable')
        with patch('utils.player_activity_store.PlayerActivityStore.history_report', AsyncMock(return_value=[])):
            with pytest.raises(NetworkTimeout):
                await read_activity(request, SimpleNamespace(player_activity=object()), ledger, 123)
        await cache.close()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    asyncio.run(run())


def test_missing_observations_cannot_leave_quiet_risk_from_partial_activity():
    async def run():
        from datetime import timedelta
        request = SimpleNamespace(app={})
        ledger = fixture()
        ledger.activity_core.return_value['record_totals']['#PYY']['active_strikes'] = 0
        ledger.activity_observations.side_effect = NetworkTimeout('optional fixture')
        now = datetime.now(timezone.utc)
        activity = [{'tag': '#PYY', 'current_clan_tag': '#CLAN', 'updated_at': now,
                     'last_seen_at': now-timedelta(days=40)}]
        with patch('utils.player_activity_store.PlayerActivityStore.overview', AsyncMock(return_value=activity)), \
             patch('utils.player_activity_store.PlayerActivityStore.history_report', AsyncMock(return_value=[])):
            view = await read_activity(request, SimpleNamespace(player_activity=object()), ledger, 123)
            assert view.unavailable and view.activity == []
            row = family_activity_rows(view.activity, **view.context)[0]
            assert row['active_strikes'] == 0 and row['total_strikes'] == 5
            assert row['quiet_days'] is None and row['status'] == 'active'
        await snapshots(request.app).close()
    asyncio.run(run())
