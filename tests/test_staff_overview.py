import asyncio,json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import staff_overview as api
from cwl_web.store import Store

@pytest.fixture
def setup(monkeypatch):
    actor={'user_id':'123','role_ids':set(),'permissions':0}
    monkeypatch.setattr(api,'identity',AsyncMock(return_value=actor))
    monkeypatch.setattr(api,'allowed',AsyncMock(return_value=False))
    class Cursor:
        def sort(self,*a):return self
        def limit(self,*a):return self
        async def to_list(self,**kw):return []
    config=NS(count_documents=AsyncMock(return_value=0),find=lambda *a:Cursor())
    db=NS(bot_config=config,tickets=NS(count_documents=AsyncMock(return_value=3)),ticket_setup=NS(find_one=AsyncMock(return_value={'channel_id':12345})))
    @asynccontextmanager
    async def mongo(_):yield db
    monkeypatch.setattr(api,'mongo',mongo)
    return NS(app={}),db,actor

def test_no_grants_denied_before_ticket_or_action_reads(setup):
    req,db,_=setup
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.overview(req))
    db.bot_config.count_documents.assert_not_awaited();db.tickets.count_documents.assert_not_awaited()

def test_clan_only_summary_excludes_ticket_data_and_filters_action_history(setup,monkeypatch):
    req,db,_=setup
    monkeypatch.setattr(api,'allowed',AsyncMock(side_effect=lambda actor,section,db:section=='clans'))
    response=asyncio.run(api.overview(req));data=json.loads(response.body)
    assert data['areas']==['clan-management'] and data['tickets'] is None and data['seasons']==[]
    query=db.bot_config.count_documents.await_args.args[0]
    assert query['user_id']=='123' and query['guild_id']==api.GUILD_ID and query['section']['$in']==['clans']
    assert response.headers['Cache-Control']=='no-store'

def test_ticket_settings_grant_does_not_bypass_discord_recruiter(setup,monkeypatch):
    from extensions.commands.tickets import perms
    req,db,_=setup
    monkeypatch.setattr(api,'allowed',AsyncMock(side_effect=lambda actor,section,db:section=='ticket_settings'))
    monkeypatch.setattr(perms,'is_recruiter',AsyncMock(return_value=False))
    data=json.loads(asyncio.run(api.overview(req)).body)
    assert data['tickets'] is None and data['warnings']
    db.tickets.count_documents.assert_not_awaited()

def test_recruiter_ticket_count_uses_live_runtime_and_guild(setup,monkeypatch):
    from extensions.commands.tickets import perms
    req,db,_=setup
    monkeypatch.setattr(api,'allowed',AsyncMock(side_effect=lambda actor,section,db:section=='ticket_settings'))
    monkeypatch.setattr(perms,'is_recruiter',AsyncMock(return_value=True))
    data=json.loads(asyncio.run(api.overview(req)).body)
    assert data['tickets']['open']==3
    query=db.tickets.count_documents.await_args.args[0]
    assert query['status']=='open' and query['guild_id']==api.GUILD_ID and query['runtime']

def test_roster_counts_include_missing_entries_and_exclude_archived(tmp_path):
    store=Store(str(tmp_path/'test.sqlite'))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label,status) VALUES(1,'Active','draft'),(2,'Old','archived')")
        for sid,tag in [(1,'#AAA'),(1,'#BBB'),(2,'#CCC')]:
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(?,?,'1','main',0,'Example',16)",(sid,tag))
        db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES(1,'#AAA','#HOST')")
    assert api.cwl_summary(store)==[{'id':1,'label':'Active','signed_up':2,'unplaced':1}]
