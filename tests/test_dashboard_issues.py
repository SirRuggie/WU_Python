import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from cwl_web.providers import FixtureProviders
from utils.dashboard_issues import IssueRepository


class Collection:
    def __init__(self):
        self.items = []
        self.fail = False

    async def update_one(self, query, update, **kwargs):
        if self.fail:
            raise RuntimeError('secret database detail')
        self.items = (self.items + update['$push']['items']['$each'])[-500:]

    async def find_one(self, query):
        if self.fail:
            raise RuntimeError('offline')
        return {'items': self.items}


class IssuesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.collection = Collection()
        self.app = create_app(db_path=str(Path(self.tmp.name)/'test.sqlite'), providers=FixtureProviders('100'), secure_cookies=False)
        self.app['server_management_mongo'] = SimpleNamespace(bot_config=self.collection)
        async def broken(request):
            raise RuntimeError('private token: dont-store-this')
        async def rejected(request):
            raise web.HTTPConflict(text='Please check your selection')
        self.app.router.add_get('/api/cwl/test/{account}', broken)
        self.app.router.add_post('/api/cwl/reject', rejected)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth('505227988229554179')
        self.member = self.auth('100')

    def auth(self, uid):
        token = 'token'+uid
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),uid,uid,0,'csrf',int(time.time())+1000))
        return {'Cookie':'cwl_session='+token,'X-CSRF-Token':'csrf'}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_sanitized_error_and_owner_only_history(self):
        response = await self.client.get('/api/cwl/test/PRIVATE?code=SECRET', headers=self.member)
        self.assertEqual(response.status,500)
        data = await response.json()
        self.assertEqual(data['issue_reference'],self.collection.items[0]['id'])
        self.assertEqual(self.collection.items[0]['action'],'/api/cwl/test/{account}')
        self.assertNotIn('SECRET',str(self.collection.items))
        self.assertNotIn('private token',str(self.collection.items)+str(data))
        self.assertEqual((await self.client.get('/api/cwl/issues', headers=self.member)).status,403)
        response = await self.client.get('/api/cwl/issues',headers=self.owner)
        self.assertEqual(len((await response.json())['items']),1)

    async def test_failed_mutation_preserves_status_and_reason(self):
        response = await self.client.post('/api/cwl/reject',headers=self.member)
        self.assertEqual(response.status,409)
        data = await response.json()
        self.assertEqual(data['error'],'Please check your selection')
        self.assertTrue(data['issue_reference'])

    async def test_browser_auth_csrf_allowlist_and_limit(self):
        url='/api/cwl/issues/browser'
        self.assertEqual((await self.client.post(url,json={'kind':'browser_error'})).status,401)
        self.assertEqual((await self.client.post(url,headers={'Cookie':self.member['Cookie']},json={'kind':'browser_error'})).status,403)
        self.assertEqual((await self.client.post(url,headers=self.member,json={'kind':'private text'})).status,400)
        response=await self.client.post(url,headers=self.member,json={'kind':'browser_error','message':'secret'})
        self.assertEqual(response.status,200)
        self.assertNotIn('secret',str(self.collection.items))
        self.assertEqual((await self.client.post(url,headers=self.member,json={'kind':'browser_error'})).status,429)

    async def test_storage_failure_does_not_mask_original_failure(self):
        self.collection.fail=True
        response=await self.client.get('/api/cwl/test/account',headers=self.member)
        self.assertEqual(response.status,500)
        self.assertTrue((await response.json())['issue_reference'])

    async def test_bounded_history_survives_new_repository(self):
        repo=IssueRepository(self.collection)
        for i in range(510):
            await repo.append({'id':str(i),'at':time.time()})
        items=await IssueRepository(self.collection).recent()
        self.assertEqual(len(items),500)
        self.assertEqual(items[0]['id'],'509')
        self.collection.items[0]['at']=0
        self.assertEqual(len(await repo.recent()),499)
