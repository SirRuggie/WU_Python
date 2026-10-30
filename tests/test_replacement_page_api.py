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


def test_default_page_is_bounded_and_uses_saved_weights_without_upstream(tmp_path):
    async def scenario():
        db, ledger = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y', 'name': 'Family', 'type': 'FWA'})
        now = datetime.now(timezone.utc)
        for i in range(273):
            tag = f'#P{i}'
            await db.strike_profiles.insert_one({'_id': f'{api.GUILD_ID}:{tag}',
                'guild_id': api.GUILD_ID, 'player_tag': tag, 'player_name': f'Player {i:03}',
                'current_clan_tag': '#Q2Y', 'roster_seen_at': now, 'weight': 100000 + i,
                'town_hall': 16, 'revision': 2})
            for j in range(i % 5):
                await db.strike_records.insert_one(record(f'{i}-{j}', tag, guild_id=api.GUILD_ID,
                    expires_at=now + timedelta(days=30)))
        store = Store(str(tmp_path / 'fixture.sqlite'))
        provider = SimpleNamespace(weights=AsyncMock(side_effect=AssertionError('No network on list load')))
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
            provider.weights.assert_not_awaited()
    asyncio.run(scenario())
