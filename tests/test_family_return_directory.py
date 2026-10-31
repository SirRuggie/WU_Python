import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from cwl_web import manage_returns
from extensions.commands import lazycwl_dashboard


class Rows:
    def __init__(self):
        self.query = None
    def find(self, query):
        self.query = query
        return self
    async def to_list(self, **kwargs):
        clans = [dict(tag='#P0LYQ', name='Tactical clan', type='Tactical'),
                 dict(tag='#P0LY2', name='FWA clan', type='FWA'),
                 dict(tag='#P0LY3', name='Removed FWA', type='FWA', removed=True)]
        return [c for c in clans if all(c.get(k) != v['$ne'] if isinstance(v, dict) else c.get(k) == v for k, v in self.query.items())]


def test_returns_index_includes_all_active_types(monkeypatch):
    rows = Rows()
    @asynccontextmanager
    async def mongo(_):
        yield NS(clans=rows)
    monkeypatch.setattr(manage_returns, 'mongo', mongo)
    monkeypatch.setattr(manage_returns, 'require_manage', AsyncMock())
    monkeypatch.setattr(manage_returns.store, 'list_active', AsyncMock(return_value=[]))
    response = asyncio.run(manage_returns.page(NS(match_info={})))
    docs = json.loads(response.text)['documents']
    assert any(d.get('clan_tag') == '#P0LYQ' and d.get('return_section') == 'MAIN' for d in docs)
    assert any(d.get('clan_tag') == '#P0LY2' and d.get('return_section') == 'FWA' for d in docs)
    assert not any(d.get('clan_tag') == '#P0LY3' for d in docs)


def test_discord_fwa_directory_excludes_removed_clans():
    rows = Rows()
    result = asyncio.run(lazycwl_dashboard._fwa_clans(NS(clans=rows)))
    assert [c['tag'] for c in result] == ['#P0LY2']
