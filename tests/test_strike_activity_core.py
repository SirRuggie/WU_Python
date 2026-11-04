"""159 core failures must remain errors; optional clan names never hide rows."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pymongo.errors import NetworkTimeout
from utils.strike_store import StrikeService
from utils.player_activity_overview import family_activity_rows, activity_view_context
from datetime import datetime, timezone


def fixture(profile_error=False, count_error=False, clan_error=False, header_error=False, gate=None):
    async def read(label, value, fail):
        if gate:
            await gate(label)
        if fail:
            raise NetworkTimeout('isolated '+label)
        return value
    profiles = [{'player_tag': '#PYY', 'current_clan_tag': '#2UVGQU9', 'player_name': 'Known'}]
    counts = [{'_id': '#PYY', 'active_strikes': 3, 'total_strikes': 5,
               'new_this_week': 1, 'replacement_active': 3, 'invalid': 0}]
    db = SimpleNamespace(
        player_activity=SimpleNamespace(find=Mock(return_value=SimpleNamespace(to_list=lambda **kw: read('headers', [], header_error)))),
        strike_profiles=SimpleNamespace(find=Mock(return_value=SimpleNamespace(to_list=lambda **kw: read('profiles', profiles, profile_error)))),
        strike_records=SimpleNamespace(aggregate=AsyncMock(return_value=SimpleNamespace(to_list=lambda **kw: read('counts', counts, count_error)))),
        clans=SimpleNamespace(find=Mock(return_value=SimpleNamespace(to_list=lambda **kw: read('clans', [{'tag': '#2UVGQU9', 'name': 'Family'}], clan_error)))))
    ledger = StrikeService(db)
    ledger.settings = lambda guild: read('settings', {'strike_limit': 4}, False)
    return ledger


@pytest.mark.parametrize('field', ['profiles', 'counts', 'headers'])
def test_missing_core_read_is_an_error_not_zero_counts(field):
    async def run():
        ledger = fixture(profile_error=field == 'profiles', count_error=field == 'counts', header_error=field == 'headers')
        with pytest.raises(NetworkTimeout):
            await ledger.activity_core(123)
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    asyncio.run(run())


def test_plain_header_timeout_maps_to_the_core_service_unavailable_error():
    async def run():
        from aiohttp import web
        from cwl_web.server_management import mongo
        ledger = fixture()
        ledger.mongo.player_activity.find.return_value.to_list = AsyncMock(side_effect=TimeoutError('fixture'))
        with pytest.raises(NetworkTimeout, match='scope read timed out'):
            await ledger.activity_core(123)
        request = SimpleNamespace(app={'server_management_mongo': ledger.mongo})
        with pytest.raises(web.HTTPServiceUnavailable) as caught:
            async with mongo(request):
                await ledger.activity_core(123)
        assert caught.value.status == 503
        assert isinstance(caught.value.__cause__, NetworkTimeout)
    asyncio.run(run())


def test_clan_failure_keeps_known_counts_and_tag_label_without_hiding_profile():
    async def run():
        core = await fixture(clan_error=True).activity_core(123)
        assert core['clan_warning'] is True
        rows = family_activity_rows([], **activity_view_context(core, None, None))
        assert len(rows) == 1
        assert rows[0]['current_clan_name'] == '#2UVGQU9'
        assert rows[0]['active_strikes'] == 3 and rows[0]['total_strikes'] == 5
        assert rows[0]['new_this_week'] is True and rows[0]['over_limit'] is False
    asyncio.run(run())


def test_independent_core_reads_start_together_and_cancel_without_orphans():
    async def run():
        started = set()
        ready, release = asyncio.Event(), asyncio.Event()
        async def gate(label):
            started.add(label)
            if len(started) == 5:
                ready.set()
            await release.wait()
        task = asyncio.create_task(fixture(gate=gate).activity_core(123))
        await asyncio.wait_for(ready.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert started == {'profiles', 'counts', 'settings', 'clans', 'headers'}
        assert not [item for item in asyncio.all_tasks() if item is not asyncio.current_task() and not item.done()]
    asyncio.run(run())


def test_family_departure_filter_matches_mongo_date_type_comparison():
    async def run():
        core = await fixture().activity_core(123)
        now = datetime.now(timezone.utc)
        base = {'current_clan_tag': None, 'departed_clan_tag': '#2UVGQU9'}
        core['profiles'] = [dict(base, player_tag='#PYY', departed_last_seen_at=now),
                            dict(base, player_tag='#QYY', departed_last_seen_at=now.isoformat())]
        selected = activity_view_context(core, [], [], now=now)
        assert [row['player_tag'] for row in selected['profiles']] == ['#PYY']
    asyncio.run(run())


def test_cold_account_set_only_adds_rows_when_activity_fills_and_counts_stay_equal():
    async def run():
        from datetime import timedelta
        from copy import deepcopy
        core = await fixture().activity_core(123)
        now = datetime.now(timezone.utc)
        family = '#2UVGQU9'
        core['profiles'] += [
            {'player_tag': '#QYY', 'current_clan_tag': '#OUT'},
            {'player_tag': '#RYY', 'departed_clan_tag': family, 'departed_last_seen_at': now-timedelta(days=2)},
            {'player_tag': '#UYY', 'departed_clan_tag': family, 'departed_last_seen_at': now-timedelta(days=100)},
        ]
        for player in ('#QYY', '#RYY', '#UYY', '#VYY'):
            core['record_totals'][player] = {'active_strikes': 2, 'total_strikes': 5, 'new_this_week': False}
        # Fresh headers exclude the contradictory family profile from cold,
        # matching the exact955 filled visibility rather than overriding it.
        activity = [{'tag': '#PYY', 'current_clan_tag': '#OUT'},
                    {'tag': '#QYY', 'current_clan_tag': family},
                    {'tag': '#VYY', 'current_clan_tag': family}]
        core['activity_headers'] = deepcopy(activity)
        before = deepcopy(core)
        cold = {row['player_tag']: row for row in family_activity_rows([], **activity_view_context(core, None, None, now=now), now=now)}
        filled = {row['player_tag']: row for row in family_activity_rows(activity, **activity_view_context(core, activity, [], now=now), now=now)}
        assert set(cold) == {'#RYY'}
        assert '#PYY' not in filled
        assert set(cold) <= set(filled)
        assert {'#QYY', '#VYY'} <= set(filled)
        assert '#UYY' not in cold
        for player in cold:
            assert cold[player]['active_strikes'] == filled[player]['active_strikes']
            assert cold[player]['total_strikes'] == filled[player]['total_strikes']
        assert core == before
    asyncio.run(run())
