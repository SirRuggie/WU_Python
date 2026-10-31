"""HTTP facade regressions for the shared native Manage campaign."""
import copy
import os
import unittest
from unittest.mock import patch

import test_cwl_web_roster as roster_fixtures
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign, cwl_web_bridge
from cwl_web.manage_bridge import GUILD_ID


class FakeDiscord:
    async def list_roles(self):
        return [{'id':'1080521665584308286','name':'Fixture CWL'}]

    async def get_channel(self, cid):
        return {'id': cid, 'name': 'fixture', 'type': 0}


class ManageBridgeTests(unittest.IsolatedAsyncioTestCase):
    auth = roster_fixtures.RosterTests.auth
    call = roster_fixtures.RosterTests.call
    revision = roster_fixtures.RosterTests.revision
    signup = roster_fixtures.RosterTests.signup
    asyncTearDown = roster_fixtures.RosterTests.asyncTearDown

    async def asyncSetUp(self):
        await roster_fixtures.RosterTests.asyncSetUp(self)
        self.mongo = MemoryMongo()
        self.app['manage_bridge_mongo'] = self.mongo
        self.app['announcement_transport'] = FakeDiscord()
        self.base = f'/seasons/{self.sid}/manage-bridge'

    async def bind(self):
        response = await self.call('POST', self.base + '/bind', self.owner, json={'cycle':'2026-10'})
        self.assertEqual(response.status, 200)

    async def state(self):
        response = await self.call('GET', self.base, self.owner)
        self.assertEqual(response.status, 200)
        return await response.json()

    async def publish(self):
        await self.signup('main', '#P2Y')
        response = await self.call('POST', f'/seasons/{self.sid}/publication', self.owner,
            json={'revision': await self.revision(), 'acknowledge_unassigned':True,'joining_instructions':''})
        self.assertEqual(response.status, 201)

    async def test_binding_explicit_and_staff_only(self):
        self.assertIsNone((await self.state())['cycle'])
        self.assertEqual((await self.call('GET', self.base, self.member)).status, 403)
        self.assertEqual((await self.call('POST',self.base+'/bind', self.owner,json={'cycle':'November'})).status,400)
        no_csrf={k:v for k,v in self.owner.items() if k!='X-CSRF-Token'}
        self.assertEqual((await self.call('POST',self.base+'/bind',no_csrf,json={'cycle':'2026-10'})).status,403)
        await self.bind()
        data=await self.state()
        native=await cwl_campaign.load_campaign(self.mongo,GUILD_ID,'2026-10')
        self.assertEqual(data['pools']['lazy']['body'],native['campaign']['messages']['roster']['variants']['lazy']['body'])
        self.assertFalse(data['worker_ready'])

    async def test_shared_edit_preserves_other_native_settings_and_rejects_stale(self):
        await self.bind()
        before=await cwl_campaign.load_campaign(self.mongo,GUILD_ID,'2026-10')
        data=await self.state()
        body={'generation':data['generation'],'channel_id':'111111111111111111','body':'Join after finishing attacks.','roster_url':'https://cwl.ruggie.zone/?view=assignments'}
        response=await self.call('PATCH',self.base+'/lazy',self.owner,json=body)
        self.assertEqual(response.status,200,await response.text())
        after=await cwl_campaign.load_campaign(self.mongo,GUILD_ID,'2026-10')
        expected=copy.deepcopy(before['campaign'])
        variant=expected['messages']['roster']['variants']['lazy']
        variant.update(destination_channel_id=111111111111111111,body=body['body'])
        variant['buttons'][0]['url']=body['roster_url'].replace('https://cwl.ruggie.zone', 'https://dash.warriorsunited.cc')
        self.assertEqual(after['campaign'],expected)
        self.assertEqual((await self.state())['pools']['lazy']['body'],body['body'])
        self.assertEqual((await self.call('PATCH',self.base+'/lazy',self.owner,json=body)).status,409)

    async def test_web_send_queues_native_and_manage_receipt_blocks_second_send(self):
        await self.bind()
        await self.publish()
        data=await self.state()
        body={'generation':data['generation'],'channel_id':data['pools']['main']['channel_id'],'version':1}
        self.assertEqual((await self.call('POST',self.base+'/main/send',self.owner,json=body)).status,503)
        await cwl_web_bridge.mark_worker_alive(self.mongo,GUILD_ID)
        response=await self.call('POST',self.base+'/main/send',self.owner,json=body)
        self.assertEqual(response.status,202,await response.text())
        pending=(await response.json())['delivery']
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(pending['publication_version'], 1)
        self.assertTrue(pending['requested_at'])
        self.assertTrue(pending['updated_at'])
        self.assertIsNone(pending['started_at'])
        self.assertIsNone(pending['sent_at'])
        oid=cwl_campaign.occurrence_id('2026-10','roster','main')
        await cwl_campaign.record_delivery(self.mongo,GUILD_ID,'2026-10',{'occurrence_id':oid,'status':'sent','message_url':'https://discord.com/channels/1/2/3','at':'2026-10-22T15:30:00+00:00'})
        shared=(await self.state())['pools']['main']['delivery']
        self.assertEqual(shared['status'],'sent')
        self.assertEqual(shared['publication_version'], 1)
        self.assertEqual(shared['message_url'],'https://discord.com/channels/1/2/3')
        self.assertEqual(shared['sent_at'],'2026-10-22T15:30:00+00:00')
        self.assertTrue(shared['requested_at'])
        self.assertTrue(shared['updated_at'])
        self.assertEqual((await self.call('POST',self.base+'/main/send',self.owner,json=body)).status,409)
        edit={'generation':data['generation'],'channel_id':body['channel_id'],'body':'changed','roster_url':'https://example.com/'}
        self.assertEqual((await self.call('PATCH',self.base+'/main',self.owner,json=edit)).status,409)

    async def test_retired_direct_sender_blocked_in_shared_mode(self):
        with patch.dict(os.environ,{'CWL_WEB_MANAGE_BRIDGE':'1'}):
            response=await self.call('POST',f'/seasons/{self.sid}/announcements/main/send',self.owner,json={})
            self.assertEqual(response.status,409)

    async def test_discord_preview_is_silent_and_does_not_consume_real_delivery(self):
        await self.bind()
        state = await self.state()
        posts=[]
        async def discord(method,path,**kwargs):
            if method=='GET':return {'guild_id':str(GUILD_ID),'type':0}
            posts.append(kwargs['json'])
            return {'id':'123456789012345678'}
        self.app['server_management_discord']=discord
        body={'channel_id':'111111111111111111','request_id':'a'*24,'generation':state['generation'],'body':'Test draft <@&123456789012345678>','roster_url':'https://example.com/roster'}
        self.assertEqual((await self.call('POST',self.base+'/main/test',self.member,json=body)).status,403)
        response=await self.call('POST',self.base+'/main/test',self.owner,json=body)
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual(posts[0]['allowed_mentions'],{'parse':[]})
        self.assertEqual(posts[0]['flags'],32768)
        self.assertIn('Test draft',str(posts[0]['components']))
        self.assertEqual((await self.state())['pools'],state['pools'])
        self.assertEqual((await self.call('POST',self.base+'/main/test',self.owner,json=body)).status,200)
        self.assertEqual(len(posts),1)

    async def test_discord_preview_rejects_foreign_channel(self):
        await self.bind()
        async def discord(method,path,**kwargs):return {'guild_id':'other','type':0}
        self.app['server_management_discord']=discord
        body={'channel_id':'111111111111111111','request_id':'b'*24,'generation':(await self.state())['generation'],'body':'Test','roster_url':'https://example.com/'}
        self.assertEqual((await self.call('POST',self.base+'/main/test',self.owner,json=body)).status,400)


class DeliveryVersionTests(unittest.TestCase):
    def test_announced_version_is_read_only_metadata(self):
        from cwl_web.manage_bridge import _delivery
        for state in ('pending', 'sent'):
            with self.subTest(state=state):
                record = {'status': state, 'publication_version': 3}
                before = copy.deepcopy(record)
                self.assertEqual(_delivery(record)['publication_version'], 3)
                self.assertEqual(record, before)
        for value in ({'status': 'sent'}, {'status': 'pending', 'publication_version': None}):
            self.assertIsNone(_delivery(value)['publication_version'])


class SequenceSendTests(ManageBridgeTests):
    async def test_native_send_persists_frozen_sequence_before_queueing(self):
        from utils.cwl_roster_image_store import RosterImageStore
        await self.bind()
        await self.publish()
        data = await self.state()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        body = {'generation': data['generation'], 'channel_id': data['pools']['main']['channel_id'], 'version': 1}
        original = cwl_web_bridge.queue_roster_send
        async def inspect(mongo, **kwargs):
            job = RosterImageStore(self.app['store']).sequence(kwargs['sequence_id'])
            self.assertEqual(job['status'], 'awaiting_announcement')
            self.assertEqual(job['channel_id'], body['channel_id'])
            self.assertEqual(job['target_version'], 1)
            return await original(mongo, **kwargs)
        with patch('utils.cwl_web_bridge.queue_roster_send', inspect):
            response = await self.call('POST', self.base + '/main/send', self.owner, json=body)
        self.assertEqual(response.status, 202, await response.text())
        state = await self.state()
        self.assertEqual(state['pools']['main']['sequence']['status'], 'awaiting_announcement')
        self.assertTrue(state['pools']['main']['sequence']['sequence_id'])

    async def test_preexisting_sent_announcement_never_acquires_image_sequence(self):
        from utils.cwl_roster_image_store import RosterImageStore
        await self.bind()
        await self.publish()
        data = await self.state()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        await cwl_campaign.record_delivery(self.mongo, GUILD_ID, '2026-10', {
            'occurrence_id': cwl_campaign.occurrence_id('2026-10', 'roster', 'main'),
            'status': 'sent', 'channel_id': data['pools']['main']['channel_id'], 'message_id': 123})
        body = {'generation': data['generation'], 'channel_id': data['pools']['main']['channel_id'], 'version': 1}
        response = await self.call('POST', self.base + '/main/send', self.owner, json=body)
        self.assertEqual(response.status, 409)
        self.assertIsNone(RosterImageStore(self.app['store']).pool_sequence(self.sid, 'main'))

    async def stopped_sequence(self):
        from utils.cwl_roster_image_store import RosterImageStore
        await self.bind()
        await self.publish()
        data = await self.state()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        body = {'generation': data['generation'], 'channel_id': data['pools']['main']['channel_id'], 'version': 1}
        response = await self.call('POST', self.base + '/main/send', self.owner, json=body)
        self.assertEqual(response.status, 202)
        storage = RosterImageStore(self.app['store'])
        job = storage.pool_sequence(self.sid, 'main')
        native = await self.mongo.bot_config.find_one({'_id': cwl_web_bridge.request_id(GUILD_ID, '2026-10', 'main')})
        native.update(status='sent', receipt={'status': 'sent', 'occurrence_id': '2026-10|roster|main',
                                              'channel_id': body['channel_id'], 'message_id': 123456789012345678})
        storage.confirm_sequence_announcement(job['sequence_id'], native)
        storage.stop_sequence(job['sequence_id'], 'Fixture rejected')
        return storage, job

    async def test_resume_is_durable_and_requires_current_sequence(self):
        storage, job = await self.stopped_sequence()
        path = self.base + '/main/sequence/resume'
        wrong = await self.call('POST', path, self.owner, json={'sequence_id': 'wrong'})
        self.assertEqual(wrong.status, 409)
        self.assertEqual(storage.sequence(job['sequence_id'])['status'], 'stopped')
        response = await self.call('POST', path, self.owner, json={'sequence_id': job['sequence_id']})
        self.assertEqual(response.status, 202, await response.text())
        self.assertEqual(storage.sequence(job['sequence_id'])['resume_requested'], 1)
        self.assertEqual((await self.call('POST', path, self.owner, json={'sequence_id': job['sequence_id']})).status, 409)

    async def test_unknown_closing_message_requires_check_first_not_resume(self):
        storage, job = await self.stopped_sequence()
        storage.resume_sequence(job['sequence_id'])
        storage.claim_sequence_closing(job['sequence_id'])
        storage.finish_sequence_closing(job['sequence_id'], status='uncertain', error='Response lost')
        response = await self.call('POST', self.base + '/main/sequence/resume', self.owner,
                                   json={'sequence_id': job['sequence_id']})
        self.assertEqual(response.status, 409)
        self.assertEqual(storage.sequence(job['sequence_id'])['resume_requested'], 0)

    async def test_duplicate_recovery_requires_explicit_confirmation_and_send_permission(self):
        import json
        storage, job = await self.stopped_sequence()
        storage.resume_sequence(job['sequence_id'])
        receipt, _ = storage.claim_sequence_closing(job['sequence_id'])
        storage.finish_sequence_closing(job['sequence_id'], status='uncertain', error='Unknown')
        path = self.base + '/main/sequence/recover'
        body = {'sequence_id': job['sequence_id'], 'request_id': receipt['request_id'], 'confirm_duplicate': True}
        denied = await self.call('POST', path, self.member, json=body)
        self.assertEqual(denied.status, 403)
        missing = await self.call('POST', path, self.owner, json=body | {'confirm_duplicate': False})
        self.assertEqual(missing.status, 400)
        self.assertEqual(storage.closing_receipt(job['sequence_id'])['status'], 'uncertain')
        recovered = await self.call('POST', path, self.owner, json=body)
        self.assertEqual(recovered.status, 202, await recovered.text())
        new = storage.sequence(job['sequence_id'])
        self.assertNotEqual(json.loads(new['plan_json'])['closing']['request_id'], receipt['request_id'])
        self.assertEqual(new['resume_requested'], 1)
        self.assertIsNone(storage.closing_receipt(job['sequence_id']))
        self.assertEqual((await self.call('POST', path, self.owner, json=body)).status, 409)
