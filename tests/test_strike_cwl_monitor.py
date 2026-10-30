"""The automatic monitor uses official current-war and league-war responses."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from extensions.commands import strikes
from utils import strike_wars


def war(kind, *, state='warEnded'):
    end = datetime.now(timezone.utc) - timedelta(minutes=3)
    member = SimpleNamespace(tag='#PC9YGL0JL', name='Player', town_hall=17,
                             map_position=1, attacks=[])
    side = lambda value: SimpleNamespace(tag=value, name=value, members=[member])
    return SimpleNamespace(state=state, type=kind,
                           clan=side('#P2Y'), opponent=side('#8GG8'),
                           start_time=SimpleNamespace(time=end - timedelta(days=1)),
                           end_time=SimpleNamespace(time=end), team_size=1,
                           attacks_per_member=1 if kind == 'cwl' else 2,
                           war_tag='#2UVGQU9' if kind == 'cwl' else None)


def test_monitor_routes_official_regular_and_cwl_without_clashking(monkeypatch):
    store = SimpleNamespace(ensure_indexes=AsyncMock(), sync_roster=AsyncMock(),
                            process_war=AsyncMock(return_value={'deferred_count': 0}),
                            process_cwl_war=AsyncMock(return_value={'records': 1}))
    tracking = SimpleNamespace(ensure_indexes=AsyncMock(), begin=AsyncMock(return_value='token'),
                               snapshot_key=lambda *_: 'key',
                               snapshot=AsyncMock(return_value={'seen_active': True}),
                               observe=AsyncMock(return_value={'status': 'observing', 'seen_active': True}),
                               finalized=AsyncMock(), abandon_older=AsyncMock(return_value=0),
                               pending_finals=AsyncMock(return_value=[]), finish=AsyncMock(),
                               rows=AsyncMock(return_value=[{'status': 'healthy'}]))
    clan_rows = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: clan_rows))
    client = SimpleNamespace(
        get_clan=AsyncMock(return_value=SimpleNamespace(members=[])),
        get_clan_war=AsyncMock(return_value=war('random')),
        get_league_group=AsyncMock(return_value=SimpleNamespace(rounds=[['#2UVGQU9']])),
        get_league_war=AsyncMock(return_value=war('cwl')),
    )
    legacy = AsyncMock(side_effect=AssertionError('regular scan called ClashKing'))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes, 'StrikeTracking', lambda *_: tracking)
    monkeypatch.setattr(strike_wars, 'fetch_history_report', legacy)
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), client))
    store.process_war.assert_awaited_once()
    store.process_cwl_war.assert_awaited_once()
    assert store.process_war.await_args.args[1]['type'] == 'regular'
    assert store.process_cwl_war.await_args.args[1]['type'] == 'cwl'
    legacy.assert_not_awaited()


@pytest.mark.parametrize('failure', [RuntimeError('links down'), asyncio.CancelledError()])
def test_regular_failure_keeps_cwl_check_and_cancellation_propagates(monkeypatch, failure):
    store = SimpleNamespace(ensure_indexes=AsyncMock(), sync_roster=AsyncMock(),
                            process_war=AsyncMock(side_effect=failure),
                            process_cwl_war=AsyncMock(return_value={'records': 1}))
    tracking = SimpleNamespace(ensure_indexes=AsyncMock(), begin=AsyncMock(return_value='token'),
                               snapshot_key=lambda *_: 'key',
                               snapshot=AsyncMock(return_value={'seen_active': True}),
                               observe=AsyncMock(return_value={'status': 'observing', 'seen_active': True}),
                               finalized=AsyncMock(), abandon_older=AsyncMock(return_value=0),
                               pending_finals=AsyncMock(return_value=[]), finish=AsyncMock(),
                               rows=AsyncMock(return_value=[{'status': 'error'}]))
    clan_rows = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: clan_rows))
    client = SimpleNamespace(
        get_clan=AsyncMock(return_value=SimpleNamespace(members=[])),
        get_clan_war=AsyncMock(return_value=war('random')),
        get_league_group=AsyncMock(return_value=SimpleNamespace(rounds=[['#2UVGQU9']])),
        get_league_war=AsyncMock(return_value=war('cwl')))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes, 'StrikeTracking', lambda *_: tracking)
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    if isinstance(failure, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(strikes.scan_once(mongo, object(), client))
        store.process_cwl_war.assert_not_awaited()
    else:
        asyncio.run(strikes.scan_once(mongo, object(), client))
        store.process_cwl_war.assert_awaited_once()
