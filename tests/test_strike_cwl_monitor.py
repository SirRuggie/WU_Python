"""The automatic monitor uses official current-war and league-war responses."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import coc

from extensions.commands import strikes
from utils import strike_wars


def war(kind, *, state='warEnded', end=None):
    end = end or datetime.now(timezone.utc) - timedelta(minutes=3)
    member = SimpleNamespace(tag='#PC9YGL0JL', name='Player', town_hall=17,
                             map_position=1, attacks=[])
    side = lambda value: SimpleNamespace(tag=value, name=value, members=[member])
    return SimpleNamespace(state=state, type=kind,
                           clan=side('#P2Y'), opponent=side('#8GG8'),
                           preparation_start_time=SimpleNamespace(
                               time=end - timedelta(days=1, hours=23)),
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
                               abandon_untracked=AsyncMock(return_value=set()),
                               pending_finals=AsyncMock(return_value=[]), defer_due=AsyncMock(),
                               finish=AsyncMock(),
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


@pytest.mark.parametrize('kind,state', [
    ('random', 'preparation'), ('random', 'inWar'),
    ('cwl', 'preparation'), ('cwl', 'inWar'),
])
def test_active_scan_routes_only_to_observation(monkeypatch, kind, state):
    end = datetime.now(timezone.utc) + timedelta(hours=47 if state == 'preparation' else 1)
    active = war(kind, state=state, end=end)
    store = SimpleNamespace(ensure_indexes=AsyncMock(), sync_roster=AsyncMock(),
                            process_war=AsyncMock(), process_cwl_war=AsyncMock())
    tracking = SimpleNamespace(ensure_indexes=AsyncMock(),
                               abandon_untracked=AsyncMock(return_value=set()),
                               begin=AsyncMock(return_value='token'),
                               snapshot_key=lambda *_: 'key', observe=AsyncMock(),
                               pending_finals=AsyncMock(return_value=[]),
                               abandon_older=AsyncMock(return_value=0),
                               finish=AsyncMock(), rows=AsyncMock(return_value=[{'status': 'behind'}]))
    clans = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: clans))
    client = SimpleNamespace(
        get_clan=AsyncMock(return_value=SimpleNamespace(members=[])),
        get_clan_war=AsyncMock(return_value=active if kind == 'random' else
                               war('random', state='notInWar')),
        get_league_group=AsyncMock(return_value=SimpleNamespace(
            rounds=[['#2UVGQU9']] if kind == 'cwl' else [])),
        get_league_war=AsyncMock(return_value=active))
    final = AsyncMock(return_value=(0, 0, 0, 0))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes, 'StrikeTracking', lambda *_: tracking)
    monkeypatch.setattr(strikes, '_finish_official_war', final)
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), client))
    final.assert_not_awaited()
    tracking.observe.assert_awaited_once()
    assert tracking.observe.await_args.args[1]['state'] == state
    store.process_war.assert_not_awaited()
    store.process_cwl_war.assert_not_awaited()


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
                               abandon_untracked=AsyncMock(return_value=set()),
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


def test_empty_current_response_cannot_report_healthy(monkeypatch):
    store = SimpleNamespace(ensure_indexes=AsyncMock(), sync_roster=AsyncMock())
    tracking = SimpleNamespace(ensure_indexes=AsyncMock(), begin=AsyncMock(return_value='token'),
                               pending_finals=AsyncMock(return_value=[]), defer_due=AsyncMock(),
                               abandon_older=AsyncMock(return_value=0),
                               abandon_untracked=AsyncMock(return_value=set()), finish=AsyncMock(),
                               rows=AsyncMock(return_value=[{'status': 'error'}]))
    clan_rows = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: clan_rows))
    client = SimpleNamespace(get_clan=AsyncMock(return_value=SimpleNamespace(members=[])),
                             get_clan_war=AsyncMock(return_value=None),
                             get_league_group=AsyncMock(return_value=SimpleNamespace(rounds=[])))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes, 'StrikeTracking', lambda *_: tracking)
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), client))
    assert tracking.finish.await_args.kwargs['error'] == 'War source unavailable'
    assert tracking.finish.await_args.kwargs['current_war_state'] == 'unknown'


@pytest.mark.parametrize('reason,expected', [
    ('accessDenied', None), ('accessDenied.invalidIp', 'Clash API key/IP rejected'),
])
def test_private_war_log_distinguishes_clan_privacy_from_bad_key(monkeypatch, reason, expected):
    store = SimpleNamespace(ensure_indexes=AsyncMock(), sync_roster=AsyncMock())
    tracking = SimpleNamespace(ensure_indexes=AsyncMock(), begin=AsyncMock(return_value='token'),
                               abandon_untracked=AsyncMock(return_value=set()),
                               pending_finals=AsyncMock(return_value=[]), defer_due=AsyncMock(),
                               finish=AsyncMock(), rows=AsyncMock(return_value=[{'status': 'private'}]))
    clans = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}, {'tag': '#8GG8'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: clans))
    client = SimpleNamespace(
        get_clan=AsyncMock(return_value=SimpleNamespace(members=[])),
        get_clan_war=AsyncMock(side_effect=coc.PrivateWarLog(403, reason)),
        get_league_group=AsyncMock(return_value=SimpleNamespace(rounds=[])))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes, 'StrikeTracking', lambda *_: tracking)
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), client, clan_tags={'#P2Y'}))
    first = tracking.finish.await_args.kwargs
    assert first['error'] == expected
    assert first['private'] is (expected is None)
    tracking.finish.reset_mock()
    asyncio.run(strikes.scan_once(mongo, object(), client))
    assert tracking.finish.await_count == 4
    assert all(call.kwargs['error'] == 'Clash API key/IP rejected'
               for call in tracking.finish.await_args_list[-2:])


def test_ended_cwl_cache_saves_second_pass_calls_and_active_refetches():
    async def run():
        alphabet = '0289PYLQGRJCUV'
        def tag_for(index):
            return f'#P2Y{alphabet[index // len(alphabet)]}{alphabet[index % len(alphabet)]}'
        clans = [tag_for(index) for index in range(25)]
        groups = [[tag_for(25 + group * 28 + offset) for offset in range(28)]
                  for group in range(4)]
        wars = {}
        for group_index, group_tags in enumerate(groups):
            for offset, war_tag in enumerate(group_tags):
                row = war('cwl', state='warEnded')
                row.clan.tag = clans[group_index * 8] if offset == 0 else '#P2YVVV'
                row.opponent.tag = '#P2YUUU'
                wars[war_tag] = row
        async def get_group(clan_tag):
            return SimpleNamespace(rounds=[groups[clans.index(clan_tag) // 8]])
        async def get_war(war_tag):
            return wars[war_tag]
        client = SimpleNamespace(
            get_clan=AsyncMock(), get_clan_war=AsyncMock(),
            get_league_group=AsyncMock(side_effect=get_group),
            get_league_war=AsyncMock(side_effect=get_war))
        ended_cache = {}
        calls_after_pass = []
        for _ in range(2):
            pass_cache = {}
            for clan_tag in clans:
                await client.get_clan(clan_tag)
                await client.get_clan_war(clan_tag)
                await strikes._league_observations(client, clan_tag, pass_cache, ended_cache)
            calls_after_pass.append(sum(method.await_count for method in
                                        (client.get_clan, client.get_clan_war,
                                         client.get_league_group, client.get_league_war)))
        assert client.get_league_war.await_count == 112  # Four groups, 28 tags each.
        assert client.get_clan.await_count == client.get_clan_war.await_count == 50
        assert client.get_league_group.await_count == 50
        assert calls_after_pass == [187, 262]  # Cold 187; warm adds only 75.
        active = war('cwl', state='inWar')
        client.get_league_group = AsyncMock(return_value=SimpleNamespace(rounds=[['#P2YVVV']]))
        client.get_league_war = AsyncMock(return_value=active)
        ended_cache.clear()
        for _ in range(2):
            await strikes._league_observations(client, '#P2Y', {}, ended_cache)
        assert client.get_league_war.await_count == 2  # Active tag refetched on pass two.
    asyncio.run(run())
