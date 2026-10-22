import unittest
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp import web
from cwl_web.access_identities import decorate_access


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_names_preserve_ids_and_permissions_without_mutation(self):
        data = {'revision': 7, 'grants': [
            {'kind':'user','id':'100','label':'100','permissions':['tickets']},
            {'kind':'role','id':'777','label':'Old role','permissions':['cwl_roster']},
        ]}
        async def discord(request, method, path):
            if path.endswith('/roles'):
                return [{'id':'777','name':'Current role'}]
            return {'nick':'Current nickname <test>', 'user':{'username':'unique_user', 'avatar':'avatar_hash'}}
        with patch('cwl_web.server_management.discord', discord):
            result = await decorate_access(SimpleNamespace(), data)
        self.assertEqual(result['grants'][0]['display_name'], 'Current nickname <test>')
        self.assertEqual(result['grants'][0]['username'], 'unique_user')
        self.assertEqual(result['grants'][0]['avatar_url'], 'https://cdn.discordapp.com/avatars/100/avatar_hash.png?size=64')
        self.assertEqual(result['grants'][1]['display_name'], 'Current role')
        self.assertEqual(result['grants'][0]['id'], '100')
        self.assertEqual(result['grants'][0]['permissions'], ['tickets'])
        self.assertEqual(result['revision'], 7)
        self.assertNotIn('display_name',data['grants'][0])

    async def test_partial_failure_preserves_all_access_entries(self):
        data = {'grants':[{'kind':'user','id':str(i),'label':'Saved name','permissions':['tickets']} for i in range(3)]}
        async def discord(request, method, path):
            if path.endswith('/0'): raise web.HTTPNotFound()
            if path.endswith('/1'): raise web.HTTPServiceUnavailable()
            return {'user':{'username':'Found'}}
        with patch('cwl_web.server_management.discord', discord):
            result = await decorate_access(None, data)
        self.assertEqual([g['identity_status'] for g in result['grants']], ['missing','unavailable','current'])
        self.assertEqual(result['grants'][1]['label'],'Saved name')
        self.assertEqual(len(result['grants']),3)
