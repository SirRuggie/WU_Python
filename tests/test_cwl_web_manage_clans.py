import asyncio,copy
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import manage_clans as api

class Rows:
    def __init__(self,row):self.row=row;self.changes=[]
    async def find_one(self,q):return copy.deepcopy(self.row)
    async def update_one(self,q,change,**kwargs):
        self.changes.append((q,change))
        if self.row is None:return NS(matched_count=0)
        if any((k in self.row if v=={'$exists':False} else self.row.get(k)!=v) for k,v in q.items()):return NS(matched_count=0)
        self.row.update(change['$set']);return NS(matched_count=1)
    async def delete_one(self,q):self.row=None;return NS(deleted_count=1)

@pytest.fixture
def setup(monkeypatch):
    rows=Rows({'_id':'clan1','tag':'#P0LYQ','name':'Warriors','type':'FWA','emoji':'','role_id':123456789012345678})
    history=NS(find_one=AsyncMock(return_value=None),insert_one=AsyncMock(),update_one=AsyncMock(return_value=NS(matched_count=1)))
    db=NS(clans=rows,bot_config=NS(database=NS(get_collection=lambda *a,**kw:history)))
    @asynccontextmanager
    async def mongo(request):yield db
    monkeypatch.setattr(api,'mongo',mongo);monkeypatch.setattr(api,'require_manage',AsyncMock(return_value={'user_id':'owner','roles':[]}))
    req=NS(match_info={'tag':'#P0LYQ'},json=AsyncMock(return_value={'revision':api.revision(rows.row),'values':{'type':'Tactical'}}))
    return req,rows,history

def test_dashboard_update_shared_record_preserves_other_fields(setup):
    req,rows,history=setup
    asyncio.run(api.save(req))
    assert rows.row['type']=='Tactical' and rows.row['role_id']==123456789012345678
    assert history.insert_one.await_count==1
    assert api.public(rows.row)['type']=='Tactical'

def test_native_edit_rejects_stale_web_save(setup):
    req,rows,history=setup;rows.row['type']='CWL'
    with pytest.raises(web.HTTPConflict):asyncio.run(api.save(req))
    assert rows.row['type']=='CWL' and not rows.changes

def test_unknown_fields_rejected(setup):
    req,rows,_=setup;req.json.return_value['values']={'_id':'other'}
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.save(req))
    assert not rows.changes

def test_remove_requires_tag_and_retains_snapshot(setup):
    req,rows,history=setup
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.remove(req))
    req.json.return_value['confirm_tag']='#P0LYQ'
    asyncio.run(api.remove(req))
    assert rows.row is None
    assert history.insert_one.await_args.args[0]['clan']['tag']=='#P0LYQ'

def test_foreign_channel_rejected(setup,monkeypatch):
    req,rows,_=setup;req.json.return_value['values']={'chat_channel_id':'123456789012345679'}
    monkeypatch.setattr(api,'discord',AsyncMock(return_value={'guild_id':'other','type':0}))
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.save(req))
    assert not rows.changes

def test_denied_before_database(setup,monkeypatch):
    req,rows,_=setup;monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.save(req))
    req.json.assert_not_awaited()

def test_choices_preserve_role_metadata_and_server_order(setup, monkeypatch):
    import json
    req, _, _ = setup
    monkeypatch.setattr(api, 'require_manage', AsyncMock(return_value={'roles': [
        {'id': '1', 'name': 'Low', 'position': 1, 'color': 0},
        {'id': '2', 'name': 'Bot role', 'position': 4, 'managed': True},
        {'id': '3', 'name': 'Captain', 'position': 3, 'color': 123},
    ]}))
    monkeypatch.setattr(api, 'discord', AsyncMock(side_effect=[[], {'threads': []}]))
    roles = json.loads(asyncio.run(api.choices(req)).text)['roles']
    assert [role['id'] for role in roles] == ['2', '3', '1']
    assert roles[0]['managed'] is True
    assert roles[1]['color'] == 123

def test_selected_leader_keeps_name_and_avatar_outside_search(setup, monkeypatch):
    import json
    from cwl_web import manage_roles
    req, _, _ = setup
    req.query = {'q': 'other', 'selected': '123456789012345678'}
    monkeypatch.setattr(manage_roles, 'searchable_members', AsyncMock(return_value=[
        {'user': {'id': '123456789012345678', 'username': 'captain', 'avatar': 'abcd'}, 'nick': 'Captain'},
    ]))
    members = json.loads(asyncio.run(api.members(req)).text)['members']
    assert members == [{'id': '123456789012345678', 'name': 'Captain', 'avatar_url': 'https://cdn.discordapp.com/avatars/123456789012345678/abcd.png?size=64'}]

def test_success_records_only_confirmed_changed_fields(setup):
    req, rows, history = setup
    asyncio.run(api.save(req))
    assert history.update_one.await_args.args[1]['$set'] == {
        'changes': [{'field': 'type', 'before': 'FWA', 'after': 'Tactical'}],
        'confirmed': True,
    }

def test_losing_cas_does_not_claim_history_change(setup):
    req, rows, history = setup
    rows.update_one = AsyncMock(return_value=NS(matched_count=0))
    with pytest.raises(web.HTTPConflict):
        asyncio.run(api.save(req))
    history.update_one.assert_not_awaited()

def test_history_completion_outage_keeps_before_image_and_successful_save(setup):
    req, rows, history = setup
    history.update_one.side_effect = RuntimeError('history unavailable')
    result = asyncio.run(api.save(req))
    assert result.status == 200
    assert rows.row['type'] == 'Tactical'
    assert history.insert_one.await_args.args[0]['clan']['type'] == 'FWA'


def test_lookup_existing_clan_does_not_require_upstream(setup):
    import json
    req, rows, _ = setup
    req.app = {'providers': NS(clan_roster=AsyncMock(side_effect=AssertionError('no upstream')))}
    response = json.loads(asyncio.run(api.lookup(req)).text)
    assert response['state'] == 'existing'
    assert response['clan']['tag'] == '#P0LYQ'
    assert not rows.changes


@pytest.mark.parametrize('removed', [False, True])
def test_lookup_reports_removed_choice_and_real_member_count(setup, removed, monkeypatch):
    import json
    req, rows, history = setup
    rows.row = None
    monkeypatch.setattr(api, 'WarReminderStore', lambda db: NS(get_settings=AsyncMock(return_value=None)))
    history.find_one = AsyncMock(return_value={'_id': 'removal'} if removed else None)
    req.app = {'providers': NS(clan_roster=AsyncMock(return_value={'name': 'Found clan', 'members': [{}] * 42}))}
    response = json.loads(asyncio.run(api.lookup(req)).text)
    assert response == {
        'state': 'removed' if removed else 'found', 'tag': '#P0LYQ',
        'name': 'Found clan', 'members': 42, 'removal_id': 'removal' if removed else None,
        'reminder_revision': api.revision(None) if removed else None,
    }
    assert history.find_one.await_args.args[0]['guild_id'] == api.GUILD_ID
    assert not rows.changes


@pytest.mark.parametrize('old_removal', [False, True])
def test_add_existing_tag_is_not_a_silent_success(setup, monkeypatch, old_removal):
    req, rows, history = setup
    history.find_one.return_value = {'_id': 'old'} if old_removal else None
    req.json.return_value = {'tag': '#P0LYQ'}
    req.app = {'providers': NS(clan=AsyncMock(return_value={'name': 'Found clan'}))}
    rows.update_one = AsyncMock(return_value=NS(upserted_id=None))
    monkeypatch.setattr(api, 'ensure_clan_tag_index', AsyncMock(return_value=True))
    with pytest.raises(web.HTTPConflict) as error:
        asyncio.run(api.add(req))
    assert 'Already in the family' in error.value.text
    history.insert_one.assert_not_awaited()

@pytest.mark.parametrize('conflict', [False, True])
def test_start_fresh_clears_reminders_with_cas_and_preserves_concurrent_edits(setup, monkeypatch, conflict):
    import json
    req, rows, history = setup
    rows.row = None
    old = {'version': 8, 'enabled': True, 'channel_id': '123456789012345678', 'minutes': [30]}
    store = NS(get_settings=AsyncMock(return_value=old), save_settings=AsyncMock())
    if conflict:
        store.save_settings.side_effect = api.SettingsConflict()
    monkeypatch.setattr(api, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(api, 'ensure_clan_tag_index', AsyncMock(return_value=True))
    history.find_one.return_value = {'_id': 'removed'}
    async def insert(q, change, **kwargs):
        rows.row = {'tag': '#P0LYQ', **change['$setOnInsert']}
        return NS(upserted_id='new')
    rows.update_one = AsyncMock(side_effect=insert)
    req.app = {'providers': NS(clan=AsyncMock(return_value={'name': 'Found clan'}))}
    req.json.return_value = {'tag': '#P0LYQ', 'mode': 'fresh', 'removal_id': 'removed', 'reminder_revision': api.revision(old)}
    result = json.loads(asyncio.run(api.add(req)).text)
    call = store.save_settings.await_args
    assert call.args[:3] == ('#P0LYQ', old, api.reminder_defaults())
    assert call.args[2]['enabled'] is False and call.args[2]['channel_id'] == ''
    assert call.kwargs['history_context'][0]['tag'] == '#P0LYQ'
    assert bool(result['warning']) is conflict
    if conflict:
        assert 'Those changes were kept' in result['warning']
    # No delivery receipt API is called: the store fake intentionally exposes none.


def test_removed_add_requires_explicit_choice_and_fresh_reminder_revision(setup, monkeypatch):
    req, rows, history = setup
    rows.row = None
    old = {'version': 8}
    store = NS(get_settings=AsyncMock(return_value=old), save_settings=AsyncMock())
    monkeypatch.setattr(api, 'WarReminderStore', lambda db: store)
    history.find_one.return_value = {'_id': 'removed'}
    req.app = {'providers': NS(clan=AsyncMock(return_value={'name': 'Found clan'}))}
    for body in ({'tag': '#P0LYQ'}, {'tag': '#P0LYQ', 'mode': 'fresh', 'removal_id': 'removed', 'reminder_revision': 'stale'}):
        req.json.return_value = body
        with pytest.raises(web.HTTPConflict):
            asyncio.run(api.add(req))
    assert not rows.changes
    store.save_settings.assert_not_awaited()
