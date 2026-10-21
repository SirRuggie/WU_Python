"""Independent adversarial bulk-action tests; database and sends are isolated."""
import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from cwl_web import manage_return_bulk as api
from cwl_web.manage_content import fingerprint
from utils import return_bulk


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, *args): return self
    def limit(self, size): self.rows = self.rows[:size]; return self
    async def to_list(self, length=None): return copy.deepcopy(self.rows[:length])
    def __aiter__(self):
        async def iterate():
            for row in self.rows: yield copy.deepcopy(row)
        return iterate()


class Collection:
    def __init__(self): self.rows = {}
    def matches(self, row, query): return all(row.get(k) == v for k,v in query.items())
    async def insert_one(self, row):
        if row['_id'] in self.rows: raise DuplicateKeyError('duplicate')
        self.rows[row['_id']] = copy.deepcopy(row)
    async def find_one(self, query):
        return next((copy.deepcopy(row) for row in self.rows.values() if self.matches(row,query)),None)
    def find(self, query): return Cursor([row for row in self.rows.values() if self.matches(row,query)])
    async def update_one(self, query, change):
        for row in self.rows.values():
            if self.matches(row,query): row.update(copy.deepcopy(change['$set'])); break
    async def update_many(self, query, change):
        for row in self.rows.values():
            if self.matches(row,query): row.update(copy.deepcopy(change['$set']))


def setup_api(monkeypatch):
    db = SimpleNamespace(bot_config=Collection())
    @asynccontextmanager
    async def mongo(request): yield db
    monkeypatch.setattr(api.shared,'mongo',mongo)
    monkeypatch.setattr(api.shared,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(api,'ready',AsyncMock())
    return db


def request(body, **match):
    return SimpleNamespace(json=AsyncMock(return_value=body),match_info=match,path='/status')


def test_queue_replay_preserves_every_terminal_receipt():
    async def scenario():
        db = SimpleNamespace(bot_config=Collection())
        args = dict(user_id='123',guild_id=1,request_id='id',operation='send',items=[dict(tag='#P0',section='MAIN',revision='r',name='A'),dict(tag='#P2',section='FWA',revision='r2',name='B')])
        key = await return_bulk.queue(db,**args)
        db.bot_config.rows[key+':0'].update(status='done',message='Sent')
        db.bot_config.rows[key+':1'].update(status='uncertain',message='Check Discord')
        assert await return_bulk.queue(db,**args) == key
        assert db.bot_config.rows[key+':0']['status'] == 'done'
        assert db.bot_config.rows[key+':1']['status'] == 'uncertain'
        assert len(db.bot_config.rows) == 3
        altered = copy.deepcopy(args); altered['items'][0]['tag']='#P8'
        with pytest.raises(ValueError): await return_bulk.queue(db,**altered)
    asyncio.run(scenario())


def test_batch_receipt_is_bound_to_requesting_user(monkeypatch):
    async def scenario():
        db=setup_api(monkeypatch)
        db.bot_config.rows['private']={'_id':'private','kind':return_bulk.BATCH_KIND,'user_id':'999'}
        with pytest.raises(web.HTTPNotFound): await api.status(request({},batch_id='private'))
    asyncio.run(scenario())


@pytest.mark.parametrize('values', [
    {'clans':['FWA:#P0','FWA:#P0']}, {'clans':['FWA:#P0'],'destination':123},
    {'clans':['FWA:#P0']*51}, {'clans':[{'tag':'#P0'}]}, {'clans':[]},
])
def test_invalid_bulk_selection_never_queues(monkeypatch,values):
    async def scenario():
        setup_api(monkeypatch)
        queued=AsyncMock();monkeypatch.setattr(return_bulk,'queue',queued)
        with pytest.raises(web.HTTPBadRequest): await api.run(request({'request_id':'5529ece3-9d38-4c0f-9c80-92b5c1e63456','values':values},operation='send'))
        queued.assert_not_awaited()
    asyncio.run(scenario())


def test_retry_contains_only_confirmed_failures(monkeypatch):
    async def scenario():
        db=setup_api(monkeypatch)
        current={'_id':'saved'}
        parent={'_id':'batch','kind':return_bulk.BATCH_KIND,'user_id':'123','operation':'send','minutes':60,'items':[1,2,3]}
        db.bot_config.rows['batch']=parent
        for i,status in enumerate(('done','failed','uncertain')):
            db.bot_config.rows[str(i)]=dict(_id=str(i),parent_id='batch',status=status,clan_name='A',values={'clan_tag':f'#P{i}','section':'FWA','destination':123},revision=fingerprint(current))
        rows=await return_bulk.children(db,parent)
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value=current))
        monkeypatch.setattr(api.destinations,'destination',AsyncMock(return_value=123))
        queued=AsyncMock(return_value='retry');monkeypatch.setattr(return_bulk,'queue',queued)
        await api.retry(request({'request_id':'5529ece3-9d38-4c0f-9c80-92b5c1e63456','revision':fingerprint(rows)},batch_id='batch'))
        assert [item['tag'] for item in queued.call_args.kwargs['items']] == ['#P1']
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation',['changed_list','changed_channel','pending'])
def test_retry_rejects_changed_or_unfinished_review(monkeypatch,mutation):
    async def scenario():
        db=setup_api(monkeypatch)
        parent={'_id':'batch','kind':return_bulk.BATCH_KIND,'user_id':'123','operation':'send','minutes':60,'items':[1]}
        db.bot_config.rows['batch']=parent
        current={'_id':'saved'}
        db.bot_config.rows['child']=dict(_id='child',parent_id='batch',status='pending' if mutation=='pending' else 'failed',clan_name='A',values={'clan_tag':'#P0','section':'FWA','destination':123},revision=fingerprint(current))
        rows=await return_bulk.children(db,parent)
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value={'_id':'new'} if mutation=='changed_list' else current))
        monkeypatch.setattr(api.destinations,'destination',AsyncMock(return_value=456 if mutation=='changed_channel' else 123))
        queued=AsyncMock();monkeypatch.setattr(return_bulk,'queue',queued)
        with pytest.raises(web.HTTPConflict): await api.retry(request({'request_id':'5529ece3-9d38-4c0f-9c80-92b5c1e63456','revision':fingerprint(rows)},batch_id='batch'))
        queued.assert_not_awaited()
    asyncio.run(scenario())


def test_return_worker_wraps_native_value_error_as_uncertain(monkeypatch):
    async def scenario():
        from utils import manage_web_worker as worker
        from extensions.commands.fwa import lazy_cwl_service as service
        current={'_id':'saved'}
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value=current))
        monkeypatch.setattr(api.destinations,'destination',AsyncMock(return_value=123))
        send=AsyncMock(side_effect=ValueError('after send'))
        monkeypatch.setattr(service,'remind_now',send)
        row=dict(section='cwl_rosters',action='send',values={'clan_tag':'#P0','section':'FWA','destination':123},revision=fingerprint(current),user_id='123')
        with pytest.raises(RuntimeError): await worker.dispatch(None,object(),row,None)
        send.assert_awaited_once()
    asyncio.run(scenario())


def test_return_worker_rechecks_destination_before_send(monkeypatch):
    async def scenario():
        from utils import manage_web_worker as worker
        from extensions.commands.fwa import lazy_cwl_service as service
        current={'_id':'saved'}
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value=current))
        monkeypatch.setattr(api.destinations,'destination',AsyncMock(return_value=456))
        send=AsyncMock();monkeypatch.setattr(service,'remind_now',send)
        row=dict(section='cwl_rosters',action='send',values={'clan_tag':'#P0','section':'FWA','destination':123},revision=fingerprint(current),user_id='123')
        with pytest.raises(ValueError): await worker.dispatch(None,object(),row,None)
        send.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('bulk,age,allowed',[(False,121,False),(True,121,True),(True,899,True),(True,901,False)])
def test_worker_queue_expiry_preserves_single_and_bulk_limits(monkeypatch,bulk,age,allowed):
    async def scenario():
        from utils import manage_web_worker as worker
        now=time.time()
        row=dict(_id='job',kind='manage_web_request',guild_id=worker.GUILD_ID,section='fwa_points',action='enable',user_id='123',values={},revision='r',created_at=now-age)
        if bulk: row.update(parent_id='batch',expires_at=now-age+900)
        config=SimpleNamespace(find=lambda query:Cursor([]),update_one=AsyncMock(),update_many=AsyncMock(),find_one_and_update=AsyncMock(side_effect=[row,None]))
        db=SimpleNamespace(bot_config=config)
        monkeypatch.setattr(worker,'context',AsyncMock())
        dispatch=AsyncMock(return_value={'message':'Done'});monkeypatch.setattr(worker,'dispatch',dispatch)
        await worker.poll(None,db)
        assert dispatch.await_count == int(allowed)
        updates=[call.args[1]['$set'] for call in config.update_one.call_args_list if call.args[0].get('_id')=='job']
        assert updates[-1]['status'] == ('done' if allowed else 'failed')
    asyncio.run(scenario())


def test_interrupted_manifest_recovers_without_extending_review_or_replaying(monkeypatch):
    async def scenario():
        db=SimpleNamespace(bot_config=Collection())
        original_insert=db.bot_config.insert_one
        fail=True
        async def insert(row):
            nonlocal fail
            if row['_id'].endswith(':1') and fail:
                fail=False
                raise ConnectionError('Interrupted manifest')
            await original_insert(row)
        db.bot_config.insert_one=insert
        args=dict(user_id='123',guild_id=1,request_id='rid',operation='send',items=[dict(tag='#P0',section='MAIN',revision='r',name='A'),dict(tag='#P2',section='FWA',revision='r2',name='B')])
        with pytest.raises(ConnectionError): await return_bulk.queue(db,**args)
        parent=next(row for row in db.bot_config.rows.values() if row['kind']==return_bulk.BATCH_KIND)
        assert parent['state']=='building'
        first=db.bot_config.rows[parent['_id']+':0']
        assert first['status']=='held'
        deadline=first['expires_at']
        # Even an already-confirmed child must remain untouched during recovery.
        first['status']='done'
        await return_bulk.activate(db)
        assert parent['state']=='queued'
        assert first['status']=='done'
        second=db.bot_config.rows[parent['_id']+':1']
        assert second['status']=='pending'
        assert second['expires_at']==deadline
        assert second['created_at']==first['created_at']==parent['created_at']
    asyncio.run(scenario())


def test_retry_network_replay_returns_original_receipt_after_live_changes(monkeypatch):
    async def scenario():
        db=setup_api(monkeypatch)
        current={'_id':'saved'}
        parent={'_id':'batch','kind':return_bulk.BATCH_KIND,'user_id':'123','operation':'send','minutes':60,'items':[1]}
        db.bot_config.rows['batch']=parent
        db.bot_config.rows['child']=dict(_id='child',parent_id='batch',status='failed',clan_name='A',values={'clan_tag':'#P0','section':'FWA','destination':123},revision=fingerprint(current))
        rows=await return_bulk.children(db,parent)
        getter=AsyncMock(return_value=current);monkeypatch.setattr(api.store,'get_active',getter)
        monkeypatch.setattr(api.destinations,'destination',AsyncMock(return_value=123))
        req=request({'request_id':'5529ece3-9d38-4c0f-9c80-92b5c1e63456','revision':fingerprint(rows)},batch_id='batch')
        first=await api.retry(req)
        getter.return_value={'_id':'changed-after-success'}
        second=await api.retry(req)
        assert json.loads(first.text)['status_url']==json.loads(second.text)['status_url']
        assert getter.await_count==1
        other_tab=request({'request_id':'171170c3-349b-4b96-a2e4-0cc594819dd3','revision':fingerprint(rows)},batch_id='batch')
        third=await api.retry(other_tab)
        assert json.loads(third.text)['status_url']==json.loads(first.text)['status_url']
        assert getter.await_count==1
        assert len([row for row in db.bot_config.rows.values() if row.get('retry_of')=='batch'])==1
    asyncio.run(scenario())


def test_schedule_replay_preserves_dates_and_rejects_changed_dates(monkeypatch):
    from datetime import datetime, timedelta, timezone
    async def scenario():
        db = setup_api(monkeypatch)
        now = datetime.now(timezone.utc)
        current = {'_id': 'saved', 'expires_at': now + timedelta(days=10)}
        items = {'FWA:#P0': dict(section='FWA', tag='#P0', name='Example', revision=fingerprint(current), active=True)}
        monkeypatch.setattr(api, 'available', AsyncMock(return_value=items))
        monkeypatch.setattr(api.destinations, 'load', AsyncMock(return_value={}))
        monkeypatch.setattr(api.store, 'get_active', AsyncMock(return_value=current))
        values = dict(clans=['FWA:#P0'], every_minutes=60, schedule_start=(now+timedelta(days=1)).isoformat(), schedule_end=(now+timedelta(days=3)).isoformat())
        body = dict(request_id='5529ece3-9d38-4c0f-9c80-92b5c1e63456', revision=fingerprint({'items':items,'channels':{}}), values=values)
        first = await api.run(request(body, operation='schedule'))
        monkeypatch.setattr(api, 'available', AsyncMock(side_effect=AssertionError('Replay must use receipt')))
        second = await api.run(request(body, operation='schedule'))
        assert first.text == second.text
        children = [row for row in db.bot_config.rows.values() if row.get('parent_id')]
        assert len(children) == 1
        assert children[0]['values']['schedule_start'] == values['schedule_start']
        assert children[0]['values']['schedule_end'] == values['schedule_end']
        body['values']['schedule_end'] = (now+timedelta(days=4)).isoformat()
        with pytest.raises(web.HTTPConflict): await api.run(request(body, operation='schedule'))
    asyncio.run(scenario())


@pytest.mark.parametrize('pool,invalid', [('MAIN',False), ('FWA',True)])
def test_schedule_invalid_selection_never_queues(monkeypatch, pool, invalid):
    from datetime import datetime, timedelta, timezone
    async def scenario():
        setup_api(monkeypatch)
        now = datetime.now(timezone.utc)
        current = {'_id':'saved','expires_at':now+timedelta(days=2)}
        all_items = {pool+':#P0':dict(section=pool,tag='#P0',name='Example',revision=fingerprint(current),active=True)}
        items = api.eligible(all_items,'schedule')
        monkeypatch.setattr(api,'available',AsyncMock(return_value=all_items))
        monkeypatch.setattr(api.destinations,'load',AsyncMock(return_value={}))
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value=current))
        queued = AsyncMock(); monkeypatch.setattr(return_bulk,'queue',queued)
        body = dict(request_id='5529ece3-9d38-4c0f-9c80-92b5c1e63456',revision=fingerprint({'items':items,'channels':{}}),values=dict(clans=[pool+':#P0'],schedule_start=now.isoformat(),schedule_end=(now+timedelta(days=3)).isoformat()))
        with pytest.raises(web.HTTPBadRequest): await api.run(request(body,operation='schedule'))
        queued.assert_not_awaited()
    asyncio.run(scenario())


def test_start_worker_requests_immediate_start_with_stale_settings_guard(monkeypatch):
    async def scenario():
        from utils import manage_web_worker as worker
        from extensions.commands.fwa import lazy_cwl_service as service
        current = {'_id':'saved','reminders':{'enabled':False}}
        monkeypatch.setattr(api.store,'get_active',AsyncMock(return_value=current))
        start = AsyncMock(return_value={'ok':True})
        monkeypatch.setattr(service,'set_reminders',start)
        row = dict(section='cwl_rosters',action='start',values={'clan_tag':'#P0','section':'FWA','every_minutes':120},revision=fingerprint(current),user_id='123')
        await worker.dispatch(None,object(),row,None)
        assert start.call_args.kwargs['start_now'] is True
        assert start.call_args.kwargs['expected_reminders'] == current['reminders']
        assert start.call_args.args == ('#P0',True,120)
    asyncio.run(scenario())
