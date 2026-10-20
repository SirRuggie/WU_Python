import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from extensions.commands import strikes


def test_monitor_routes_cwl_separately_and_respects_activation(monkeypatch):
    activation = datetime.now(timezone.utc) - timedelta(days=1)
    regular = {'type': 'regular', 'end_time': activation + timedelta(hours=1)}
    cwl = {'type': 'cwl', 'end_time': activation + timedelta(hours=2)}
    old_cwl = {'type': 'cwl', 'end_time': activation - timedelta(hours=1)}
    store = SimpleNamespace(ensure_indexes=AsyncMock(), monitor_activation=AsyncMock(return_value=activation),
                            sync_roster=AsyncMock(), process_war=AsyncMock(), process_cwl_war=AsyncMock())
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': '#P2Y'}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: cursor))
    client = SimpleNamespace(get_clan=AsyncMock(return_value=SimpleNamespace(members=[])))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes.strike_wars, 'fetch_history_report', AsyncMock(return_value={
        'wars': [regular], 'cwl_wars': [old_cwl, cwl]}))
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), client))
    store.process_war.assert_awaited_once_with(strikes.WARRIORS_UNITED_GUILD_ID, regular)
    store.process_cwl_war.assert_awaited_once_with(strikes.WARRIORS_UNITED_GUILD_ID, cwl)
