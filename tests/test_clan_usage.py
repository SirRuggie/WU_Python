import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from cwl_web import clan_usage as api
from cwl_web.store import Store


def test_usage_uses_active_season_membership_and_rule_pool(tmp_path, monkeypatch):
    store = Store(str(tmp_path / 'usage.sqlite'))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label,status) VALUES(1,'November','draft'),(2,'October','archived'),(3,'December','draft')")
        db.execute("INSERT INTO clans(tag,name,pool) VALUES('#P0LYQ','Example','main')")
        db.execute("INSERT INTO lineup(season_id,tag) VALUES(1,'#P0LYQ'),(2,'#P0LYQ')")
        db.execute("INSERT INTO lineup_rules(season_id,tag,pool) VALUES(1,'#P0LYQ','lazy')")
    row = {'tag': '#P0LYQ', 'type': 'FWA'}
    @asynccontextmanager
    async def mongo(_):
        yield NS(clans=NS(find_one=AsyncMock(return_value=row)))
    monkeypatch.setattr(api, 'mongo', mongo)
    monkeypatch.setattr(api, 'require_manage', AsyncMock())
    req = NS(match_info={'tag': '#P0LYQ'}, app={'store': store})
    links = json.loads(asyncio.run(api.usage(req)).text)['links']
    assert links == [
        {'label': 'Strikes tracking', 'href': '/clans/strikes'},
        {'label': 'Clan weights (FWA)', 'href': '/clan-weights?clan=%23P0LYQ'},
        {'label': 'CWL hosting (Lazy · November)', 'href': '/cwl/roster?season=1'},
    ]
    row['type'] = 'CWL'
    links = json.loads(asyncio.run(api.usage(req)).text)['links']
    assert all('weights' not in link['label'] for link in links)
    assert len(links) == 2
    with store.tx() as db:
        db.execute("UPDATE clans SET archived=1")
    assert len(json.loads(asyncio.run(api.usage(req)).text)['links']) == 1


def test_usage_requires_family_permission_before_storage(monkeypatch):
    monkeypatch.setattr(api, 'require_manage', AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(api.usage(NS()))
