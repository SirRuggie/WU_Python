"""Behavioral regressions for dashboard grants, concurrency and revocation."""
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from cwl_web.providers import FixtureProviders
from utils.dashboard_access import AccessRepository, AccessConflict, DOCUMENT_ID, OWNER_IDS, effective, dashboard_allowed
from dashboard_access_fakes import AccessCollection


class DashboardAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.collection = AccessCollection()
        self.db = SimpleNamespace(bot_config=self.collection)
        self.member_roles = []
        async def discord(method, path, **kwargs):
            if path.endswith('/roles'):
                return [{'id': '777', 'name': 'CWL staff', 'managed': False}]
            return {'user': {'id': path.rsplit('/', 1)[-1], 'username': 'Staff <test>'}, 'roles': self.member_roles}
        self.app = create_app(db_path=str(Path(self.tmp.name)/'test.sqlite'), providers=FixtureProviders('100'), secure_cookies=False, live_access=True)
        self.app['server_management_mongo'] = self.db
        self.app['server_management_discord'] = discord
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth('505227988229554179')
        self.second = self.auth('644005027052126208')
        self.member = self.auth('100')
        self.fake_owner = self.auth('200', guild_owner=True)

    def auth(self, uid, guild_owner=False):
        token = 'token-'+uid
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),uid,uid,int(guild_owner),'csrf',int(time.time())+1000))
        return {'Cookie':'cwl_session='+token,'X-CSRF-Token':'csrf'}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def call(self, method, path, headers=None, **kwargs):
        return await self.client.request(method,'/api/cwl'+path,headers=headers or self.owner,**kwargs)

    async def save(self, permissions, *, kind='user', subject='100', revision=None, headers=None):
        row = self.collection.documents.get(DOCUMENT_ID, {})
        return await self.call('POST','/access',headers,json={'revision':row.get('revision',0) if revision is None else revision,'kind':kind,'id':subject,'permissions':permissions})

    async def test_only_two_fixed_owners_manage_access(self):
        for actor in (self.member,self.fake_owner):
            self.assertEqual((await self.call('GET','/access',actor)).status,403)
            self.assertEqual((await self.save(['cwl_send'],headers=actor)).status,403)
        self.assertEqual((await self.call('GET','/access',self.second)).status,200)
        for uid in OWNER_IDS:
            self.assertEqual((await self.save(['cwl_send'],subject=uid)).status,400)
        self.assertEqual((await self.save(['owner'])).status,400)
        self.assertEqual((await self.save(['cwl_send'],kind='role',subject='644963518025826315')).status,400)

    async def test_atomic_migration_preserves_unrelated_grants(self):
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)',('300','owner',json.dumps(['cwl','clans'])))
        self.assertEqual((await self.save(['tickets'])).status,200)
        doc=await AccessRepository(self.collection).read()
        old=effective(doc,'300')
        self.assertIn('cwl_publish',old); self.assertIn('clan_weights',old)
        self.assertEqual(effective(doc,'100'),{'tickets'})
        self.assertEqual(len(doc['history']),1)
        # Restarting a repository reads the same authority, not stale local grants.
        self.assertEqual((await AccessRepository(self.collection).read())['revision'],1)

    async def test_role_membership_is_fresh_and_combines_with_direct_grants(self):
        await self.save(['cwl_signups'],kind='role',subject='777')
        await self.save(['clan_weights'])
        data=await (await self.call('GET','/auth/me',self.member)).json()
        self.assertEqual(data['dashboard_permissions'],['clan_weights'])
        self.member_roles=['777']
        data=await (await self.call('GET','/auth/me',self.member)).json()
        self.assertEqual(set(data['dashboard_permissions']),{'clan_weights','cwl_signups'})
        self.member_roles=[]
        data=await (await self.call('GET','/auth/me',self.member)).json()
        self.assertFalse(data['can_edit'])

    async def test_no_clan_to_cwl_or_publish_to_edit_escalation(self):
        await self.save(['clans'])
        self.assertEqual((await self.call('GET','/seasons/1/roster',self.member)).status,403)
        self.assertEqual((await self.call('GET','/weight-trial/clans',self.member)).status,403)
        await self.save(['cwl_publish'])
        for method,path in [('POST','/seasons'),('POST','/seasons/1/staff-signups'),('PATCH','/seasons/1/roster/%23P2Y')]:
            response=await self.call(method,path,self.member,json={})
            self.assertEqual(response.status,403,(path,await response.text()))
        await self.save(['cwl_roster'])
        self.assertEqual((await self.call('POST','/seasons/1/publication',self.member,json={})).status,403)

    async def test_conflicting_saves_and_removal_do_not_overwrite(self):
        self.assertEqual((await self.save(['cwl_roster'],revision=0)).status,200)
        self.assertEqual((await self.save(['cwl_publish'],revision=0)).status,409)
        self.assertEqual(effective(await AccessRepository(self.collection).read(),'100'),{'cwl_roster'})
        self.assertEqual((await self.save(None)).status,200)
        self.assertEqual((await self.call('GET','/seasons/1/roster',self.member)).status,403)
        doc=await AccessRepository(self.collection).read()
        self.assertEqual(len(doc['history']),2)
        self.assertEqual(doc['history'][-1]['before']['permissions'],['cwl_roster'])
        self.assertIsNone(doc['history'][-1]['after'])

    async def test_failed_storage_does_not_split_permissions_and_history(self):
        await self.save(['tickets'])
        before=await AccessRepository(self.collection).read()
        self.collection.fail=True
        with self.assertRaises(RuntimeError):
            await AccessRepository(self.collection).save(before,revision=1,actor_id=next(iter(OWNER_IDS)),kind='user',subject_id='100',permissions=['cwl_send'],label='Test')
        self.assertEqual(await AccessRepository(self.collection).read(),before)

    async def test_worker_rechecks_saved_role_and_user_grants(self):
        await self.save(['tickets'],kind='role',subject='777')
        actor={'user_id':'100','role_ids':['777'],'dashboard':True}
        self.assertTrue(await dashboard_allowed(actor,'ticket_testing',self.db))
        await self.save(None,kind='role',subject='777')
        self.assertFalse(await dashboard_allowed(actor,'ticket_testing',self.db))
        actor['guild_owner']=True
        self.assertFalse(await dashboard_allowed(actor,'ticket_testing',self.db))

    async def test_csrf_and_unknown_permissions_fail(self):
        response=await self.save(['cwl_send'],headers={'Cookie':self.owner['Cookie']})
        self.assertEqual(response.status,403)
        self.assertEqual((await self.save(['cwl_send','not_real'])).status,400)
        self.assertEqual((await self.save(['cwl_send'],kind='role',subject='999')).status,400)

    async def test_role_lookup_outage_denies_role_access_but_keeps_member_pages(self):
        from aiohttp import web
        await self.save(['cwl_roster'],kind='role',subject='777')
        self.app['server_management_discord'] = AsyncMock(side_effect=web.HTTPServiceUnavailable(text='Discord unavailable'))
        response = await self.call('GET','/auth/me',self.member)
        self.assertEqual(response.status,200)
        data = await response.json()
        self.assertFalse(data['can_edit'])
        self.assertIn('could not be checked',data['access_warning'])
        self.assertEqual((await self.call('GET','/seasons/1/roster',self.member)).status,403)

    async def test_expired_session_cannot_block_a_fresh_login(self):
        with self.app['store'].tx() as db:
            db.execute("UPDATE sessions SET expires_at=0 WHERE user_id='100'")
        self.app['oauth'] = {'client_id':'test','client_secret':'test','redirect_uri':'https://example.test/callback'}
        response = await self.call('GET','/auth/discord',self.member,allow_redirects=False)
        self.assertEqual(response.status,302)
        self.assertTrue(response.headers['Location'].startswith('https://discord.com/'))
