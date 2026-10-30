"""Paged replacement reads over isolated stored profiles, never live API data."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cwl_web import strikes as api
from cwl_web.store import Store
from test_strike_ux_backend import setup, record


def test_default_page_is_bounded_and_uses_provider_weights_without_profile_weight(tmp_path):
    async def scenario():
        db, ledger = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y', 'name': 'Family', 'type': 'FWA'})
        now = datetime.now(timezone.utc)
        for i in range(273):
            tag = f'#P{i}'
            await db.strike_profiles.insert_one({'_id': f'{api.GUILD_ID}:{tag}',
                'guild_id': api.GUILD_ID, 'player_tag': tag, 'player_name': f'Player {i:03}',
                'current_clan_tag': '#Q2Y', 'roster_seen_at': now,
                'town_hall': 16, 'revision': 2})
            for j in range(i % 5):
                await db.strike_records.insert_one(record(f'{i}-{j}', tag, guild_id=api.GUILD_ID,
                    expires_at=now + timedelta(days=30)))
        store = Store(str(tmp_path / 'fixture.sqlite'))
        provider = SimpleNamespace(weights=AsyncMock(return_value={f'#P{i}': {'weight': 100000+i} for i in range(273)}))
        request = SimpleNamespace(method='GET', query={}, app={'store': store, 'providers': provider,
                                                               'strike_service': ledger})
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo):
            first = json.loads((await api.replacements(request)).text)
            assert first['total'] == 108
            assert len(first['candidates']) == 25 and len(first['top']) == 10
            assert all(row['active_strikes'] >= 3 for row in first['candidates'])
            assert all(row['revision'] == 2 for row in first['candidates'])
            request.query = {'offset': '25'}
            second = json.loads((await api.replacements(request)).text)
            assert not {r['player_tag'] for r in first['candidates']} & {r['player_tag'] for r in second['candidates']}
            request.query = {'include_low': 'true'}
            low = json.loads((await api.replacements(request)).text)
            assert low['total'] == 218
            provider.weights.assert_awaited()
            assert first['candidates'][0]['weight'] is not None
            assert first['town_halls'] == [16]
            for player in ['#P2Y', '#P2YY']:
                await db.strike_profiles.insert_one({'_id':f'{api.GUILD_ID}:{player}', 'guild_id':api.GUILD_ID, 'player_tag':player, 'current_clan_tag':'#Q2Y', 'roster_seen_at':now})
                for j in range(3):
                    await db.strike_records.insert_one(record(f'{player}-{j}', player, guild_id=api.GUILD_ID, expires_at=now+timedelta(days=30)))
            request.query = {'exact_tag':'#P2Y','limit':'1'}
            exact = json.loads((await api.replacements(request)).text)
            assert [row['player_tag'] for row in exact['candidates']] == ['#P2Y']
    asyncio.run(scenario())


def test_route_passes_revision_to_add_update_and_clear():
    async def scenario():
        ledger = SimpleNamespace(
            set_replacement_preference=AsyncMock(return_value={'player_tag':'#P2Y', 'replacement_priority':'high', 'replacement_clan_tag':'#Q2Y', 'revision':9}),
            clear_replacement_preference=AsyncMock(return_value={'revision':9}))
        @asynccontextmanager
        async def mongo(_):
            yield object()
        from cwl_web import app
        for handler, method in [(api.add_replacement_list,'POST'), (api.update_replacement_list,'PUT'), (api.delete_replacement_list,'DELETE')]:
            request = SimpleNamespace(method=method, match_info={'player_tag':'#P2Y'})
            with patch.object(api.shared,'require_manage',AsyncMock()), patch.object(api.shared,'mongo',mongo), patch.object(api,'service',AsyncMock(return_value=ledger)), patch.object(api,'body',AsyncMock(return_value={'player_tag':'#P2Y','priority':'high','note':'keep','revision':8})), patch.object(api,'_verified_replacement_player',AsyncMock(return_value={'tag':'#P2Y','current_clan_tag':'#Q2Y'})), patch.object(app,'_session',return_value={'user_id':'123'}):
                response = await handler(request)
                assert response.status == 200
                call = ledger.clear_replacement_preference if method == 'DELETE' else ledger.set_replacement_preference
                assert call.await_args.kwargs['expected_revision'] == 8
    asyncio.run(scenario())
