"""HTTP contracts with fixture registries and fake Discord only."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import wraps
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from cwl_web import town_halls as api
from cwl_web import change_history, server_management as shared
from test_town_halls import registry


@pytest.fixture(autouse=True)
def admin_permissions(monkeypatch):
    # Existing244 tests exercise the admin contract;245 role combinations have
    # separate permission regressions and do not inherit this fixture.
    monkeypatch.setattr(api.bases, 'permissions', AsyncMock(return_value=(True, False)))
    from cwl_web import server_roles
    monkeypatch.setattr(server_roles, 'role_choices', AsyncMock(return_value=([], {})))
    monkeypatch.setattr(api.registry, 'load_roles', AsyncMock(return_value={'revision':0, 'roles':{}, 'exists':False}))


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def fixture():
    doc = registry(); doc['_id'] = str(shared.GUILD_ID)
    return doc


@asynccontextmanager
async def mongo(_):
    yield object()


def request(item='19', values=None, revision=7):
    return SimpleNamespace(app={}, match_info={'item':item}, json=AsyncMock(return_value={
        'revision':revision, 'values':values if values is not None else {'emoji':'', 'min':181000, 'max':190000}}))


def test_grouped_list_and_level_documents():
    doc = fixture(); before=deepcopy(doc)
    records = api.document(doc)['documents']
    assert [row['id'] for row in records] == ['add','settings','20','19','12','11','1']
    assert records[1]['value'] == 'TH12'
    assert records[2]['meta'] == 'No weight range'
    assert records[2]['list_group'] == 'fwa'
    assert records[-1]['list_group'] == 'other'
    assert all('group' not in row for row in records)
    assert [row['key'] for row in api.document(doc,'19')['fields']] == ['emoji','role','min','max']
    assert all(row['group']=='Town Hall' for row in api.document(doc,'19')['fields'])
    assert len(api.document(doc,'11')['fields'])==2
    assert api.document(doc,'11')['help']=='Weights and bases are for TH12 and up.'
    assert api.document(doc,'add')['create'] is True
    assert api.document(doc,'add')['fields'][0]['value']==21
    assert doc == before


@pytest.mark.parametrize('item', ['0','01','100','-1','19.$','unknown','13'])
def test_unknown_level_never_falls_back(item):
    with pytest.raises(web.HTTPNotFound): api.document(fixture(), item)


@run_async
async def test_emoji_sources_partial_failure_and_no_mongo():
    async def discord(request, method, path):
        if path.endswith('/emojis') and '/guilds/' in path:
            raise TimeoutError()
        if path=='/applications/@me':return {'id':'123456789012345678'}
        return {'items':[{'id':'1571025137896005783','name':'TH_19A','animated':True}, {'id':'bad','name':'bad'}]}
    with patch.object(shared,'require_manage',AsyncMock()) as auth, patch.object(shared,'discord',discord), patch.object(shared,'mongo',side_effect=AssertionError('emoji lookup must not access Mongo')):
        result=json.loads((await api.emojis(object())).text)
    assert auth.call_args.args[1] == 'fwa_weight'
    assert result['errors']=={'server':'Server emojis could not load.'}
    assert len(result['emojis'])==1
    assert result['emojis'][0]['image_url'].endswith('.gif?size=48')


@run_async
async def test_emoji_same_name_both_sources_unavailable_cap_and_sort():
    async def discord(request, method, path):
        values=[{'id':'1571025137896005783','name':'TH_19A','available':False}]*501
        if '/guilds/' in path:return values
        if path=='/applications/@me':return {'id':'123456789012345678'}
        return {'items':[{'id':'1571025137896005784','name':'TH_19A'}]}
    with patch.object(shared,'require_manage',AsyncMock()),patch.object(shared,'discord',discord):
        result=json.loads((await api.emojis(object())).text)
    assert len(result['emojis'])==501
    assert result['emojis'][0]['source']=='server'
    assert result['emojis'][0]['available'] is False
    assert result['emojis'][-1]['source']=='bot'


@run_async
async def test_both_sources_fail_503():
    with patch.object(shared,'require_manage',AsyncMock()),patch.object(shared,'discord',AsyncMock(side_effect=TimeoutError)):
        with pytest.raises(web.HTTPServiceUnavailable) as error:
            await api.emojis(object())
        assert error.value.text == 'Emojis could not load. Try again.'


@run_async
async def test_saved_once_queues_after_cas_and_returns_actual_saved_revision():
    saved=fixture();saved['revision']=8
    order=[]
    async def persist(*args):order.append('save');return saved
    async def queue(*args):order.append('queue');return web.json_response({'status':'pending'})
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock(side_effect=persist)) as save,patch.object(shared,'queue_action',AsyncMock(side_effect=queue)) as queued,patch.object(change_history,'record_committed',AsyncMock()):
        result=json.loads((await api.save(request())).text)
    assert order==['save','queue']
    assert result['saved'] and result['revision']==8
    save.assert_awaited_once()
    assert queued.call_args.args[1:]==('town_halls','refresh',{},8)
    assert (await queued.call_args.args[0].json())==(await api.RefreshRequest(request(),8).json())


@run_async
@pytest.mark.parametrize('fail', ['queue','history'])
async def test_postsave_failures_report_saved_never_retry_registry(fail):
    saved=fixture();saved['revision']=8
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock(return_value=saved)) as save,patch.object(shared,'queue_action',AsyncMock(side_effect=TimeoutError if fail=='queue' else None,return_value=web.json_response({'status':'pending'}))),patch.object(change_history,'record_committed',AsyncMock(side_effect=TimeoutError if fail=='history' else None)):
        result=json.loads((await api.save(request())).text)
    assert result['saved'] and result['revision']==8
    if fail=='history':assert result['history_saved'] is False
    else:assert 'saved' in result['warning']
    save.assert_awaited_once()


@run_async
async def test_stale_revision_has_no_history_save_or_queue():
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock()) as save,patch.object(shared,'queue_action',AsyncMock()) as queue,patch.object(change_history,'record_committed',AsyncMock()) as begin:
        with pytest.raises(web.HTTPConflict) as error:
            await api.save(request(revision=6))
        assert error.value.text == api.registry.CONFLICT_MESSAGE
    save.assert_not_awaited();queue.assert_not_awaited();begin.assert_not_awaited()


@run_async
async def test_missing_registry_readiness_error_no_write():
    with patch.object(api.registry,'load',AsyncMock(return_value=None)):
        with pytest.raises(web.HTTPServiceUnavailable) as error:
            await api.required(object())
        assert error.value.text == api.registry.MISSING_MESSAGE


@run_async
async def test_member_list_signed_in_only_cached_no_markup():
    req=request()
    with patch('cwl_web.app._require',return_value={'user_id':'123'}) as auth,patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())) as load:
        result=json.loads((await api.member_list(req)).text)
        assert json.loads((await api.member_list(req)).text)==result
    assert auth.call_count==2;load.assert_awaited_once()
    assert [row['level'] for row in result]==[20,19,12,11,1]
    assert all(set(row)=={'level','emoji_url'} for row in result)
    assert '<:' not in json.dumps(result)
    with patch('cwl_web.app._require',side_effect=web.HTTPUnauthorized):
        with pytest.raises(web.HTTPUnauthorized):await api.member_list(req)


def test_emoji_route_is_before_generic_and_history_targets():
    assert str(api.routes[0].path).endswith('/emojis')
    assert api.routes[0].handler is api.emojis
    assert change_history.target_info('/manage/town-halls/19')==('town_halls','town_halls',{'item':'19'},'/api/cwl/manage/town-halls/19')


@run_async
@pytest.mark.parametrize('permission,roles,allowed', [(8,set(),True),(0,{993015846442127420},True),(0,set(),False)])
async def test_native_permissions_match_admin_or_base_manager(permission,roles,allowed):
    actor={'permissions':permission,'role_ids':roles}
    assert await shared.allowed(actor,'town_halls',object()) is allowed


@run_async
@pytest.mark.parametrize('value', [9.5, True, 0, 100, '9'])
async def test_lowest_fwa_malformed_input_never_writes(value):
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock()) as save,patch.object(shared,'queue_action',AsyncMock()) as queue,patch.object(change_history,'record_committed',AsyncMock()) as begin:
        with pytest.raises(web.HTTPBadRequest):
            await api.save(request(item='settings',values={'lowest_fwa_town_hall':value}))
    save.assert_not_awaited();queue.assert_not_awaited();begin.assert_not_awaited()


@run_async
async def test_config_readiness_requires_registry_only_outside_disconnected_fixture():
    from cwl_web.app import config
    req=SimpleNamespace(app={'dev_fixture':False})
    with patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(side_effect=web.HTTPServiceUnavailable(text='Town Halls not migrated'))) as ready:
        with pytest.raises(web.HTTPServiceUnavailable) as error:
            await config(req)
        assert error.value.text=='Town Halls not migrated'
        ready.assert_awaited_once()
    req.app['dev_fixture']=True
    with patch.object(api,'required',AsyncMock()) as ready:
        assert json.loads((await config(req)).text)=={'dev_fixture':True}
        ready.assert_not_awaited()


@run_async
async def test_actual_queue_deduplicates_same_saved_revision_without_rewriting_receipt():
    from pymongo.errors import DuplicateKeyError
    from utils.manage_web_worker import WORKER_ID
    rows={WORKER_ID:{'checked_at':time_now()}}
    async def find(query):return rows.get(query['_id'])
    async def insert(row):
        if row['_id'] in rows:raise DuplicateKeyError('duplicate')
        rows[row['_id']]=deepcopy(row)
    db=SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(side_effect=find),insert_one=AsyncMock(side_effect=insert)))
    @asynccontextmanager
    async def connection(_):yield db
    req=api.RefreshRequest(request(),8)
    with patch.object(shared,'mongo',connection),patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})):
        first=json.loads((await shared.queue_action(req,'town_halls','refresh',{},8)).text)
        rows[first['request_id']]['status']='done'
        again=json.loads((await shared.queue_action(req,'town_halls','refresh',{},8)).text)
    assert first['request_id']==again['request_id']
    assert again['status']=='done'
    assert len(rows)==2
    assert rows[first['request_id']]['revision']==8


def time_now():
    import time
    return time.time()


@run_async
async def test_permission_denial_stops_emoji_read_and_save_before_data_access():
    with patch.object(shared,'require_manage',AsyncMock(side_effect=web.HTTPForbidden)),patch.object(shared,'discord',AsyncMock()) as discord,patch.object(shared,'mongo',side_effect=AssertionError('no Mongo after denial')):
        for handler in (api.read,api.save,api.emojis):
            with pytest.raises(web.HTTPForbidden):await handler(request())
    discord.assert_not_awaited()


@run_async
async def test_emoji_endpoint_rejects_malformed_names_and_values_roundtrip_owner():
    async def discord(request,method,path):
        if path=='/applications/@me':return {'id':'123456789012345678'}
        values=[{'id':'1571025137896005783','name':None},{'id':'1571025137896005783','name':19},
                {'id':'1571025137896005783','name':'TH_19A'}, {'id':'bad/path','name':'TH_20'}]
        return values if '/guilds/' in path else {'items':values}
    with patch.object(shared,'require_manage',AsyncMock()),patch.object(shared,'discord',discord):
        result=json.loads((await api.emojis(request())).text)
    assert len(result['emojis'])==2
    for item in result['emojis']:
        doc=fixture();doc['levels']['19']['emoji']=item['value']
        api.registry.validate(doc)


@run_async
async def test_two_admins_read_same_revision_loser_has_no_history_or_queue():
    original=fixture(); stored=deepcopy(original); wrote=[]; history=[]; queued=[]
    both_read=asyncio.Event(); reads=0
    async def read(_):
        nonlocal reads
        value=deepcopy(original)
        reads+=1
        if reads==2:both_read.set()
        await both_read.wait()
        return value
    async def persist(db,guild,doc,user,revision):
        if revision!=stored['revision']:
            raise api.registry.TownHallsConflict(api.registry.CONFLICT_MESSAGE)
        stored.update(deepcopy(doc),revision=revision+1)
        wrote.append(user)
        return deepcopy(stored)
    async def begin(db,target,actor,before,after,**kwargs):
        history.append((actor['user_id'],before,kwargs))
        return 'history'
    async def queue(req,*args):
        queued.append(req.original.actor['user_id'])
        return web.json_response({'status':'pending'})
    one=request();one.actor={'user_id':'123'}
    two=request();two.actor={'user_id':'456'}
    async def auth(req,*args,**kwargs):return req.actor
    with patch.object(shared,'require_manage',auth),patch.object(shared,'mongo',mongo),patch.object(api,'required',read),patch.object(api.registry,'save',persist),patch.object(change_history,'record_committed',begin),patch.object(shared,'queue_action',queue):
        results=await asyncio.gather(api.save(one),api.save(two),return_exceptions=True)
    assert len(wrote)==len(history)==len(queued)==1
    assert history[0][0]==queued[0]==str(wrote[0])
    assert stored['revision']==8
    assert sum(isinstance(result,web.HTTPConflict) for result in results)==1
    assert history[0][2]['raw_before']['revision']==7
    assert history[0][2]['action']=='edit'


@run_async
async def test_actual_history_restore_forwards_restore_action_and_saved_before_image():
    doc=fixture();saved=deepcopy(doc);saved['revision']=8
    saved['levels']['19']['emoji']=''
    req=request();req.query={'target':'/manage/town-halls/19'}
    req.json=AsyncMock(return_value={'revision':7,'side':'before','id':'history-id'})
    old=dict(kind='dashboard_history',target='/api/cwl/manage/town-halls/19',status='saved',
             before={'emoji':'','min':181000,'max':190000},raw_before=doc)
    db=SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=old)))
    @asynccontextmanager
    async def connection(_):yield db
    with patch.object(change_history,'mongo',connection),patch.object(change_history,'require_manage',AsyncMock()),patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',connection),patch.object(api,'required',AsyncMock(return_value=doc)),patch.object(api.registry,'save',AsyncMock(return_value=saved)),patch.object(change_history,'record_committed',AsyncMock()) as begin,patch.object(shared,'queue_action',AsyncMock(return_value=web.json_response({'status':'pending'}))):
        result=json.loads((await change_history.restore(req)).text)
    assert result['saved'] is True
    assert begin.call_args.kwargs['action']=='restore'
    assert begin.call_args.kwargs['raw_before']['revision']==7


@run_async
async def test_history_owner_inserts_one_deterministic_revision_and_accepts_duplicate():
    from pymongo.errors import DuplicateKeyError
    rows={}
    async def insert(row):
        if row['_id'] in rows:raise DuplicateKeyError('already recorded')
        rows[row['_id']]=deepcopy(row)
    db=SimpleNamespace(bot_config=SimpleNamespace(insert_one=AsyncMock(side_effect=insert)))
    event=f'dashboard-history:town-halls:{shared.GUILD_ID}:8'
    for _ in range(2):
        await change_history.record_committed(db,'/api/cwl/manage/town-halls/19',{'user_id':'123'},
             {'emoji':''},{'emoji':'<:TH_19A:1571025137896005783>'},event_id=event)
    assert list(rows)==[event]
    assert rows[event]['status']=='saved'
    assert rows[event]['before']=={'emoji':''}
    assert db.bot_config.insert_one.await_count==2


@run_async
async def test_history_failure_logs_once_with_revision_no_new_warning_ui(caplog):
    saved=fixture();saved['revision']=8
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock(return_value=saved)) as save,patch.object(shared,'queue_action',AsyncMock(return_value=web.json_response({'status':'pending'}))),patch.object(change_history,'record_committed',AsyncMock(side_effect=TimeoutError)):
        result=json.loads((await api.save(request())).text)
    assert result['saved'] and result['history_saved'] is False and result['revision']==8
    assert 'warning' not in result
    assert len(caplog.records)==1 and 'revision 8' in caplog.text
    save.assert_awaited_once()


@run_async
async def test_minimum_save_invalidates_only_after_committed_cas():
    req=request(item='settings',values={'lowest_fwa_town_hall':19})
    req.app['base_bank_cache']='old-visible-levels'
    saved=fixture();saved.update(revision=8,lowest_fwa_town_hall=19)
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())),patch.object(api.registry,'save',AsyncMock(return_value=saved)),patch.object(shared,'queue_action',AsyncMock(return_value=web.json_response({'status':'pending'}))),patch.object(change_history,'record_committed',AsyncMock()):
        assert json.loads((await api.save(req)).text)['saved'] is True
    assert 'base_bank_cache' not in req.app
    req=request(item='settings',values={'lowest_fwa_town_hall':19},revision=6)
    req.app['base_bank_cache']='keep-on-conflict'
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=fixture())):
        with pytest.raises(web.HTTPConflict):await api.save(req)
    assert req.app['base_bank_cache']=='keep-on-conflict'


@run_async
async def test_inflight_old_base_read_cannot_refill_cache_after_minimum_cas():
    from cwl_web import base_bank as bank
    current=fixture();started=asyncio.Event();release=asyncio.Event();reads=[]
    req=request(item='settings',values={'lowest_fwa_town_hall':19})
    bank_request=SimpleNamespace(app=req.app,query={})
    async def load(_):return deepcopy(current)
    async def persist(db,guild,doc,user,revision):
        assert current['revision']==revision
        current.update(deepcopy(doc),revision=revision+1)
        return deepcopy(current)
    async def base_read(_):
        minimum=current['lowest_fwa_town_hall'];reads.append(minimum)
        if len(reads)==1:
            started.set();await release.wait()
        return ([{'key':f'th{minimum}','town_hall':minimum,'variant':'merged'}],{f'th{minimum}':{}})
    with patch('cwl_web.app._require',return_value={'user_id':'123'}),patch('cwl_web.server_membership.server_member_status',AsyncMock(return_value=True)),patch.object(bank,'mongo',mongo),patch.object(bank,'read_base_bank',base_read),patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',load),patch.object(api.registry,'save',AsyncMock(side_effect=persist)) as save,patch.object(shared,'queue_action',AsyncMock(return_value=web.json_response({'status':'pending'}))),patch.object(change_history,'record_committed',AsyncMock()):
        pending=asyncio.create_task(bank.read(bank_request))
        await started.wait()
        assert json.loads((await api.save(req)).text)['saved'] is True
        release.set()
        result=json.loads((await pending).text)
        again=json.loads((await bank.read(bank_request)).text)
    assert reads==[12,19]
    assert result==again=={'bases':[{'key':'th19','town_hall':19,'variant':'merged','variant_label':'Merged'}]}
    assert req.app['base_bank_cache'][1]==result['bases']
    save.assert_awaited_once()


def test_minimum_select_choices_are_strings_but_draft_value_is_integer():
    field=api.document(fixture(),'settings')['fields'][0]
    assert field['value']==12 and type(field['value']) is int
    assert field['required'] is True
    assert all(type(option['value']) is str for option in field['options'])
    assert {option['value'] for option in field['options']}=={'11','12','19'}
    add=api.document(fixture(),'add')
    assert [field['key'] for field in add['fields']]==['level','emoji']
    assert add['fields'][0]['required'] is True


@run_async
async def test_add_records_create_and_before_restore_is_never_deletion():
    doc=fixture();saved=api.registry.add_level(doc,21,'');saved['revision']=8
    with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(shared,'mongo',mongo),patch.object(api,'required',AsyncMock(return_value=doc)),patch.object(api.registry,'save',AsyncMock(return_value=saved)),patch.object(shared,'queue_action',AsyncMock(return_value=web.json_response({'status':'pending'}))),patch.object(change_history,'record_committed',AsyncMock()) as history:
        assert json.loads((await api.save(request(item='add',values={'level':21,'emoji':''}))).text)['saved']
        assert history.call_args.kwargs['action']=='create'
        assert history.call_args.args[3]=={}
        assert history.call_args.args[4]['level']==21
        assert history.call_args.args[4]['emoji']==''
    req=request();req.query={'target':'/manage/town-halls/21'}
    req.json=AsyncMock(return_value={'revision':8,'side':'before','id':'created'})
    row=dict(kind='dashboard_history',target='/api/cwl/manage/town-halls/21',status='saved',action='create',before={},after={'level':21,'emoji':'','min':None,'max':None})
    @asynccontextmanager
    async def connection(_):yield SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=row)))
    with patch.object(change_history,'mongo',connection),patch.object(change_history,'require_manage',AsyncMock()),patch.object(api,'save',AsyncMock()) as write:
        with pytest.raises(web.HTTPConflict) as rejected:await change_history.restore(req)
        assert 'no prior version' in rejected.value.text
        write.assert_not_called()


@run_async
async def test_create_after_restore_keeps_recorded_level_out_of_edit_fields():
    req=request();req.query={'target':'/manage/town-halls/21'}
    req.json=AsyncMock(return_value={'revision':8,'side':'after','id':'created'})
    row=dict(kind='dashboard_history',target='/api/cwl/manage/town-halls/21',status='saved',action='create',before={},after={'level':21,'emoji':'','min':None,'max':None})
    @asynccontextmanager
    async def connection(_):yield SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=row)))
    with patch.object(change_history,'mongo',connection),patch.object(change_history,'require_manage',AsyncMock()),patch.object(api,'save',AsyncMock(return_value=web.json_response({'saved':True}))) as write:
        await change_history.restore(req)
        assert await write.call_args.args[0].json()=={'revision':8,'values':{'emoji':'','min':None,'max':None}}
        assert write.call_args.args[0].history_action=='restore'
