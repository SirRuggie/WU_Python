"""No Discord sends: exercise the management worker's claim and failure boundary."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from utils import manage_web_worker as worker

class EmptyCursor:
    def sort(self, *args): return self
    def limit(self, *args): return self
    def __aiter__(self):
        async def iterate():
            for row in (): yield row
        return iterate()


class ManageWorkerTests(unittest.IsolatedAsyncioTestCase):
    def db(self,row):
        config=SimpleNamespace(find=lambda query: EmptyCursor(),update_one=AsyncMock(),update_many=AsyncMock(),find_one_and_update=AsyncMock(side_effect=[row,None]))
        return SimpleNamespace(bot_config=config,fwa_data=SimpleNamespace(find_one=AsyncMock(return_value={})))

    def row(self,**kw):
        return dict(_id='operation1',guild_id=worker.GUILD_ID,section='fwa_points',action='enable',user_id='123',created_at=time.time(),values={},revision='snapshot',**kw)

    async def test_expired_request_never_reaches_dispatch(self):
        row=self.row();row['created_at']=time.time()-121;db=self.db(row)
        with patch.object(worker,'context',AsyncMock()) as context,patch.object(worker,'dispatch',AsyncMock()) as dispatch:
            await worker.poll(None,db)
            context.assert_not_awaited();dispatch.assert_not_awaited()
        self.assertEqual(db.bot_config.update_one.call_args.args[1]['$set']['status'],'failed')

    async def test_revoked_access_never_dispatches(self):
        db=self.db(self.row())
        with patch.object(worker,'context',AsyncMock(side_effect=ValueError('Access revoked'))),patch.object(worker,'dispatch',AsyncMock()) as dispatch:
            await worker.poll(None,db);dispatch.assert_not_awaited()
        self.assertEqual(db.bot_config.update_one.call_args.args[1]['$set']['status'],'failed')

    async def test_unknown_actions_never_dispatch(self):
        row=self.row();row['action']='delete_everything';db=self.db(row)
        with patch.object(worker,'context',AsyncMock()) as context,patch.object(worker,'dispatch',AsyncMock()) as dispatch:
            await worker.poll(None,db);context.assert_not_awaited();dispatch.assert_not_awaited()

    async def test_uncertain_effect_is_not_requeued(self):
        db=self.db(self.row())
        with patch.object(worker,'context',AsyncMock()),patch.object(worker,'dispatch',AsyncMock(side_effect=TimeoutError)):
            await worker.poll(None,db)
        update=db.bot_config.update_one.call_args.args[1]['$set']
        self.assertEqual(update['status'],'uncertain')
        self.assertNotEqual(update['status'],'pending')
        claim=db.bot_config.find_one_and_update.call_args_list[0]
        self.assertEqual(claim.args[1]['$set']['status'],'running')

    async def test_dispatch_points_checks_native_revision_before_toggle(self):
        db=SimpleNamespace()
        from extensions.tasks import fwa_points_monitor
        with patch('cwl_web.manage_operations.load_document',AsyncMock(return_value={'revision':'new'})),patch.object(fwa_points_monitor,'set_monitor_enabled',AsyncMock()) as toggle:
            with self.assertRaises(ValueError):await worker.dispatch(None,db,self.row(),None)
            toggle.assert_not_awaited()

    def test_runtime_snapshot_does_not_expose_band_key(self):
        from cwl_web.manage_operations import runtime_snapshot
        monitor=SimpleNamespace(poll_health=SimpleNamespace(state='healthy',last_success_at=None,last_error=None),band_check_task=None,startup_reconciler=None,BAND_KEY='secret-value',DEBUG_MODE=False)
        result=runtime_snapshot(monitor)
        self.assertTrue(result['key_ready']);self.assertNotIn('secret-value',str(result))

    async def test_duplicate_queue_does_not_replace_completed_receipt(self):
        from contextlib import asynccontextmanager
        from pymongo.errors import DuplicateKeyError
        from cwl_web import server_management as shared
        rows={worker.WORKER_ID:{'checked_at':time.time()}}
        async def find(query):return rows.get(query['_id'])
        async def insert(row):
            if row['_id'] in rows:raise DuplicateKeyError('already queued')
            rows[row['_id']]=dict(row,status='done',message='Already completed')
        db=SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(side_effect=find),insert_one=AsyncMock(side_effect=insert)))
        @asynccontextmanager
        async def mongo(_):yield db
        with patch.object(shared,'mongo',mongo),patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})):
            request=SimpleNamespace(json=AsyncMock(return_value={'request_id':'8ba89d9c-15bf-4a22-a573-222c25c58538'}))
            one=await shared.queue_action(request,'fwa_points','enable',{},'same')
            two=await shared.queue_action(request,'fwa_points','enable',{},'same')
        self.assertEqual(one.text,two.text)
        self.assertEqual(len(rows),2)
        self.assertEqual(next(v for k,v in rows.items() if k!=worker.WORKER_ID)['status'],'done')

    async def test_queue_rejects_unknown_action_and_non_object_values(self):
        from cwl_web import server_management as shared
        from aiohttp import web
        with patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'123'})):
            with self.assertRaises(web.HTTPBadRequest):await shared.queue_action({},'fwa_points','drop_database',{},'r')
            with self.assertRaises(web.HTTPBadRequest):await shared.queue_action({},'fwa_points','enable',['bad'],'r')

    async def test_malformed_tester_access_rejected_before_native_control(self):
        row=self.row();row.update(section='ticket_testing',action='access',values={'allow_admins':'false'})
        with self.assertRaises(ValueError):await worker.dispatch(None,None,row,None)
        row['values']={'allowed_user_ids':['123']*26}
        with self.assertRaises(ValueError):await worker.dispatch(None,None,row,None)

    async def test_return_interval_cannot_bypass_native_picker(self):
        row=self.row();row.update(section='cwl_rosters',action='start',values={'every_minutes':1})
        with self.assertRaises(ValueError):await worker.dispatch(None,None,row,None)
