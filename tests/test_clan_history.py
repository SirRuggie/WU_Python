import asyncio, copy, json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from cwl_web import clan_history as api
from utils.clan_history import native_snapshot

@pytest.fixture
def setup(monkeypatch):
    clan={'_id':'original','tag':'#P0LYQ','name':'Example','type':'FWA','role_id':123,'custom_field':{'kept':True}}
    event={'_id':'event1','guild_id':api.GUILD_ID,'clan':clan,'action':'before_remove','actor':'123','at':datetime.now(timezone.utc)}
    history=NS(find_one=AsyncMock(return_value=event),insert_one=AsyncMock())
    clans=NS(find_one=AsyncMock(return_value=None),insert_one=AsyncMock())
    db=NS(clans=clans,bot_config=NS(database=NS(get_collection=lambda *a,**k:history)))
    @asynccontextmanager
    async def mongo(_):yield db
    monkeypatch.setattr(api,'mongo',mongo)
    monkeypatch.setattr(api,'require_manage',AsyncMock(return_value={'user_id':'staff'}))
    monkeypatch.setattr(api,'ensure_clan_tag_index',AsyncMock(return_value=True))
    request=NS(match_info={'event_id':'event1'},json=AsyncMock(return_value={'confirm_tag':'#P0LYQ'}))
    return request,db,history,event

def test_restore_keeps_all_settings_and_records_actor(setup):
    req,db,h,event=setup
    response=asyncio.run(api.restore(req))
    assert response.status==200
    assert db.clans.insert_one.await_args.args[0]==event['clan']
    assert [c.args[0]['action'] for c in h.insert_one.await_args_list]==['before_restore','restore']
    assert h.insert_one.await_args.args[0]['actor']=='staff'

def test_restore_does_not_overwrite_existing(setup):
    req,db,h,event=setup;db.clans.find_one.return_value={'name':'New settings'}
    with pytest.raises(web.HTTPConflict):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()

def test_restore_race_preserves_existing(setup):
    req,db,h,event=setup;db.clans.insert_one.side_effect=DuplicateKeyError('race')
    with pytest.raises(web.HTTPConflict):asyncio.run(api.restore(req))
    assert h.insert_one.await_count==1 # no false restored event

def test_restore_rejects_old_snapshot(setup):
    req,db,h,event=setup;h.find_one.side_effect=[event,{**event,'_id':'newer'}]
    with pytest.raises(web.HTTPConflict):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()

def test_restore_requires_confirmation_and_permission(setup,monkeypatch):
    req,db,h,event=setup;req.json.return_value={}
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.restore(req))
    monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()

def test_snapshot_failure_prevents_restore(setup):
    req,db,h,event=setup;h.insert_one.side_effect=RuntimeError('backup unavailable')
    with pytest.raises(RuntimeError):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()

def test_native_snapshot_records_discord_source_and_name(setup):
    req,db,h,event=setup;db.clans.find_one.return_value=event['clan']
    asyncio.run(native_snapshot(db,NS(user=NS(id=456,display_name='Leader')),'before_remove','#P0LYQ'))
    snapshot=h.insert_one.await_args.args[0]
    assert snapshot['source']=='Discord' and snapshot['actor_name']=='Leader'
    assert snapshot['clan']==event['clan']

def test_history_restricts_guild_and_never_restores_active_clan(setup):
    req,db,h,event=setup
    class Cursor:
        def sort(self,*a):return self
        def skip(self,*a):return self
        def limit(self,*a):return self
        async def to_list(self,**kw):return [event]
    h.find=lambda query: Cursor()
    class Live:
        async def to_list(self,**kw):return [{'tag':'#P0LYQ'}]
    db.clans.find=lambda *a:Live()
    req.query={}
    response=asyncio.run(api.history(req));item=json.loads(response.body)['events'][0]
    assert item['can_restore'] is False and item['present'] is True
    assert item['at'].endswith('+00:00')
    assert h.find_one.await_args.args[0]['guild_id']==api.GUILD_ID

def test_native_remove_preserves_emoji_and_snapshot(setup):
    from extensions.commands.clan.dashboard import update_clan_info as native
    req,db,h,event=setup
    db.clans.find_one.return_value={**event['clan'],'emoji':'<:clan:123456789012345678>'}
    db.clans.delete_one=AsyncMock(return_value=NS(deleted_count=1))
    rest=NS(delete_application_emoji=AsyncMock())
    ctx=NS(user=NS(id=456,display_name='Leader'))
    result=asyncio.run(native.on_remove_clan_field.__wrapped__._func(ctx=ctx,action_id='confirm_#P0LYQ',mongo=db,bot=NS(rest=rest)))
    assert result
    rest.delete_application_emoji.assert_not_awaited()
    assert h.insert_one.await_args.args[0]['action']=='before_remove'
    assert h.insert_one.await_args.args[0]['clan']['emoji']=='<:clan:123456789012345678>'

def test_restore_unknown_snapshot_and_failed_index_do_not_write(setup,monkeypatch):
    req,db,h,event=setup;h.find_one.return_value=None
    with pytest.raises(web.HTTPNotFound):asyncio.run(api.restore(req))
    h.find_one.return_value=event
    monkeypatch.setattr(api,'ensure_clan_tag_index',AsyncMock(return_value=False))
    with pytest.raises(web.HTTPServiceUnavailable):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()
