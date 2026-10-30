"""Offline official-client Tasks contracts; all SDK HTTP methods are fakes."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import coc
import pytest

from cwl_web import todo, todo_games
from cwl_web.providers import ProviderUnavailable
from utils import startup, todo_data

CLAN = '#P2Y'
PLAYER = '#Q2Y'
WAR = '#R2Y'
NOW = datetime.now(timezone.utc)
START = (NOW - timedelta(hours=1)).strftime('%Y%m%dT%H%M%S.000Z')
END = (NOW + timedelta(hours=20)).strftime('%Y%m%dT%H%M%S.000Z')


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('No network is authorized in Tasks contract tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    todo_data._cache.clear()
    yield
    todo_data._cache.clear()


def test_tasks_module_bans_all_clashking_hosts_and_cache_busters():
    source = Path(todo_data.__file__).read_text()
    assert 'clashk.ing' not in source.lower()
    assert '?cb=' not in source


def war_payload(*, cwl=False):
    return {'state': 'inWar', 'teamSize': 1, 'attacksPerMember': 1 if cwl else 2,
            'preparationStartTime': (NOW - timedelta(hours=25)).strftime('%Y%m%dT%H%M%S.000Z'),
            'startTime': START, 'endTime': END,
            'clan': {'tag': CLAN, 'name': 'Fixture clan', 'clanLevel': 10,
                     'members': [{'tag': PLAYER, 'name': 'Fixture player', 'townhallLevel': 16,
                                  'mapPosition': 1, 'attacks': [] if cwl else [{'order': 1,
                                  'attackerTag': PLAYER, 'defenderTag': '#J2Y',
                                  'stars': 3, 'destructionPercentage': 100, 'duration': 120}]}]},
            'opponent': {'tag': '#G2Y', 'name': 'Fixture opponent', 'members': []}}


def fake_sdk():
    """Use the actual shared factory and coc.py parsers, without login/network."""
    client = startup.create_clash_client()
    client.http = SimpleNamespace(
        get_clan_current_war=AsyncMock(return_value=war_payload()),
        get_clan_war_league_group=AsyncMock(return_value={
            'state': 'inWar', 'season': '2026-10', 'clans': [],
            'rounds': [{'warTags': [WAR]}]}),
        get_cwl_wars=AsyncMock(return_value=war_payload(cwl=True)),
        get_clan_raid_log=AsyncMock(return_value={'items': [{
            'state': 'ongoing', 'startTime': START, 'endTime': END,
            'totalAttacks': 2, 'members': [{'tag': PLAYER, 'name': 'Fixture player',
                'attacks': 2, 'attackLimit': 5, 'bonusAttackLimit': 0}],
            'attackLog': [{'defender': {'tag': '#G2Y', 'name': 'Fixture opponent'},
                           'districts': []}], 'defenseLog': []}]}),
    )
    return client


def account():
    return todo_data.Account(PLAYER, 'Fixture player', CLAN, 'Fixture clan', 16)


def test_real_sdk_payloads_keep_tasks_serialized_war_cwl_and_raid_contract():
    async def run():
        client = fake_sdk()
        views = {}
        for name, build in [('war', todo_data.build_war_view), ('cwl', todo_data.build_cwl_view),
                            ('raid', todo_data.build_raid_view)]:
            views[name] = todo._view(await build(client, [account()]))
        for name, total, used in [('war', 2, 1), ('cwl', 1, 0), ('raid', 5, 2)]:
            view = views[name]
            assert view['ok'] and not view['incomplete']
            assert len(view['rows']) == 1
            row = view['rows'][0]
            assert (row['tag'], row['name'], row['clan_tag'], row['town_hall']) == (
                PLAYER, 'Fixture player', CLAN, 16)
            assert (row['used'], row['total'], row['remaining']) == (used, total, total - used)
            assert row['ends_at'] == int(datetime.strptime(END, '%Y%m%dT%H%M%S.000Z').replace(tzinfo=timezone.utc).timestamp())
        for method in ('get_clan_current_war', 'get_clan_war_league_group', 'get_cwl_wars', 'get_clan_raid_log'):
            assert getattr(client.http, method).await_count == 1
        assert client.http.get_cwl_wars.call_args.args == (WAR,)
        assert client.http.get_clan_raid_log.call_args.kwargs['limit'] == 1
        # The retained DTO contract is transport independent: the exact parsed
        # payload gives the same serialized Tasks output from a plain client.
        plain = SimpleNamespace(
            get_clan_war=AsyncMock(return_value=await client.get_clan_war(CLAN)),
            get_league_group=AsyncMock(return_value=await client.get_league_group(CLAN)),
            get_league_war=AsyncMock(return_value=await client.get_league_war(WAR)),
            get_raid_log=AsyncMock(return_value=await client.get_raid_log(CLAN, limit=1)),
        )
        todo_data._cache.clear()
        for name, build in [('war', todo_data.build_war_view), ('cwl', todo_data.build_cwl_view),
                            ('raid', todo_data.build_raid_view)]:
            assert todo._view(await build(plain, [account()])) == views[name]
    asyncio.run(run())


@pytest.mark.parametrize('error,kind,ttl', [
    ('private', 'private', 900), ('not_found', 'none', 900),
    ('rate_limit', 'error', 60), ('timeout', 'error', 60),
])
def test_official_errors_keep_classification_cache_ttl_and_coalesce(error, kind, ttl):
    async def run():
        client = fake_sdk()
        errors = {
            'private': coc.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), {'reason': 'accessDenied'}),
            'not_found': coc.NotFound(SimpleNamespace(status=404, reason='Not Found'), {'reason': 'notFound'}),
            'rate_limit': coc.HTTPException(SimpleNamespace(status=429, reason='Too Many Requests'), {'reason': 'rateLimitExceeded'}),
            'timeout': asyncio.TimeoutError(),
        }
        client.http.get_clan_current_war.side_effect = errors[error]
        with patch.object(todo_data, 'cache_put', wraps=todo_data.cache_put) as cache:
            results = await asyncio.gather(*(todo_data._get_war(client, CLAN) for _ in range(4)))
            assert results == [(kind, None)] * 4
            assert client.http.get_clan_current_war.await_count == 1
            assert cache.call_args.args == (f'war:{CLAN}', (kind, None), ttl)
        view = todo._view(await todo_data.build_war_view(client, [account()]))
        if kind == 'error':
            assert view['incomplete'] and not view['rows']
        if kind == 'private':
            with patch.object(todo_data, '_get_cwl_round', AsyncMock(return_value=('none', None))):
                blocked = todo._view(await todo_data.build_blocked_view(client, [account()]))
            assert blocked['rows'][0]['detail'] == 'private'
    asyncio.run(run())


def test_dashboard_initializes_authenticated_shared_factory_once(monkeypatch):
    async def run():
        monkeypatch.setenv('COC_API_TOKEN', '  fixture-token  ')
        client = object()
        factory = AsyncMock(return_value=client)
        app = {'todo_client': None, 'todo_client_lock': asyncio.Lock()}
        with patch.object(todo, 'create_authenticated_clash_client', factory):
            assert await asyncio.gather(*(todo.get_clash_client(app) for _ in range(6))) == [client] * 6
        factory.assert_awaited_once_with('fixture-token')
    asyncio.run(run())


def test_dashboard_missing_token_does_not_attempt_authentication(monkeypatch):
    async def run():
        monkeypatch.delenv('COC_API_TOKEN', raising=False)
        factory = AsyncMock()
        with patch.object(todo, 'create_authenticated_clash_client', factory):
            with pytest.raises(ProviderUnavailable):
                await todo.get_clash_client({'todo_client': None, 'todo_client_lock': asyncio.Lock()})
        factory.assert_not_called()
    asyncio.run(run())


def test_clan_games_remains_separate_score_provider_with_unknown_not_zero():
    async def run():
        second = todo_data.Account('#J2Y', 'Other', CLAN, 'Fixture clan', 16)
        fetch = AsyncMock(return_value={PLAYER: 2450})
        with patch.object(todo_games, 'fetch_clan_scores', fetch):
            view = await todo_games.build_games_view([account(), second],
                now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
        assert fetch.await_count == 1
        assert fetch.call_args.args[1:3] == (CLAN, '2026-10')
        assert [row['used'] for row in view['rows']] == [2450, None]
        assert all(row['total'] is None for row in view['rows'])
    asyncio.run(run())
