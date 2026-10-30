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

def test_native_remove_is_read_only(setup):
    from extensions.commands.clan.dashboard import update_clan_info as native
    req,db,h,event=setup
    db.clans.find_one.return_value=event['clan']
    db.clans.delete_one=AsyncMock()
    ctx=NS(member=NS(get_roles=lambda: [NS(id=993015846442127420)]), respond=AsyncMock())
    asyncio.run(native.on_remove_clan_field.__wrapped__._func(ctx=ctx,action_id='confirm_#P0LYQ',mongo=db))
    db.clans.delete_one.assert_not_awaited()
    h.insert_one.assert_not_awaited()
    assert 'Dashboard → Family clans → History' in ctx.respond.await_args.args[0]

def test_restore_unknown_snapshot_and_failed_index_do_not_write(setup,monkeypatch):
    req,db,h,event=setup;h.find_one.return_value=None
    with pytest.raises(web.HTTPNotFound):asyncio.run(api.restore(req))
    h.find_one.return_value=event
    monkeypatch.setattr(api,'ensure_clan_tag_index',AsyncMock(return_value=False))
    with pytest.raises(web.HTTPServiceUnavailable):asyncio.run(api.restore(req))
    db.clans.insert_one.assert_not_awaited()

def test_public_changes_only_confirmed_and_no_raw_ids():
    row = {'changes': [{'field': 'type', 'before': 'FWA', 'after': 'CWL'}]}
    assert api.public_changes(row) == []
    row['confirmed'] = True
    assert api.public_changes(row) == [{'field': 'Clan type', 'before': 'FWA', 'after': 'CWL'}]
    row['changes'] = [{'field': 'leader_id', 'before': 123456789012345678, 'after': 987654321098765432}]
    assert api.public_changes(row)[0]['before'] == 'Name not recorded'

def test_history_unknown_actor_and_non_utc_time_are_honest(setup):
    from datetime import timedelta
    req, db, h, event = setup
    event['at'] = datetime(2026, 10, 30, 12, tzinfo=timezone(timedelta(hours=2)))
    class Cursor:
        def sort(self, *a): return self
        def skip(self, *a): return self
        def limit(self, *a): return self
        async def to_list(self, **kw): return [event]
    h.find = lambda query: Cursor()
    class Live:
        async def to_list(self, **kw): return []
    db.clans.find = lambda *a: Live()
    req.query = {'kind': 'reminders'}
    item = json.loads(asyncio.run(api.history(req)).body)['events'][0]
    assert item['actor'] == 'Staff member (name unavailable)'
    assert item['at'] == '2026-10-30T10:00:00+00:00'


def test_reminder_snapshot_preserves_off_and_empty_values_without_live_inference():
    clan = {'reminder_settings': {
        'enabled': False, 'channel_id': 123456789012345678,
        'minutes': [], 'audience': 'zero', 'war_started': False,
        'version': 12, 'unrelated': 'private',
    }}
    assert api.reminder_snapshot(clan) == [
        {'field': 'Reminders', 'value': 'Off'},
        {'field': 'Reminder channel', 'value': 'Name not recorded'},
        {'field': 'Reminder times', 'value': 'None'},
        {'field': 'Remind who', 'value': 'Players with no attacks used'},
        {'field': 'War-start message', 'value': 'Off'},
    ]
    assert api.reminder_snapshot({}) == []
    assert api.reminder_snapshot({'reminder_settings': None}) == []


def test_confirmed_change_uses_frozen_names():
    row = {'confirmed': True, 'changes': [{
        'field': 'leader_role_id', 'before': 123, 'after': 456,
        'display': {'before': 'Old leaders', 'after': 'New leaders'},
    }]}
    assert api.public_changes(row) == [
        {'field': 'Leader role', 'before': 'Old leaders', 'after': 'New leaders'}
    ]


def test_change_names_uses_server_roles_and_honest_unavailable_fallback(monkeypatch):
    from cwl_web import manage_clans
    lookup = AsyncMock(side_effect=[
        {'user': {'username': 'Old member'}, 'nick': 'Old leader'},
        {'user': {'global_name': 'New leader'}},
        {'name': 'Foreign channel', 'guild_id': 'other'},
        RuntimeError('Discord unavailable'),
    ])
    monkeypatch.setattr(manage_clans, 'discord', lookup)
    result = asyncio.run(manage_clans.change_names(None,
        {'roles': [{'id': '11', 'name': 'Leaders'}]},
        {'leader_role_id': 11, 'leader_id': 12, 'chat_channel_id': 14},
        {'leader_role_id': 0, 'leader_id': 13, 'chat_channel_id': 15}))
    assert result == {
        'leader_role_id': {'before': 'Leaders', 'after': 'Not set'},
        'leader_id': {'before': 'Old leader', 'after': 'New leader'},
        'chat_channel_id': {'before': 'Name not recorded', 'after': 'Name not recorded'},
    }
