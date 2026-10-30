import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from cwl_web import member_events, server_management
from cwl_web.manage_identity_cache import KEY, invalidate, read

UID = '123456789012345678'


class IdentityReads(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.fail = False
        self.granted = True
        self.app = web.Application()
        async def config(query):
            if query['_id'] == 'dashboard-access:' + UID:
                return {'permissions': ['member_roles']} if self.granted else None
            return None
        self.app['server_management_mongo'] = SimpleNamespace(bot_config=SimpleNamespace(find_one=config), member_events=object())
        self.app['server_management_discord'] = self.discord
        self.patches = [patch('cwl_web.app._require', return_value={'user_id':UID}),
                        patch('cwl_web.access_control.request_scopes', return_value={'member_roles'})]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    async def discord(self, method, path, **kwargs):
        self.calls.append(path)
        await asyncio.sleep(.005)
        if self.fail:
            raise web.HTTPServiceUnavailable(text='Discord is busy')
        if path.endswith('/roles'): return []
        if '/members/' in path: return {'roles':[]}
        return {'owner_id':'999'}

    def request(self, method='GET', path='/api/cwl/manage/member-events/example/avatar'):
        req = make_mocked_request(method, path, app=self.app)
        req._match_info['event_id'] = '1792972800000:' + 'a'*32
        return req

    async def avatars(self):
        async def limited(*args, **kwargs):
            if len(self.calls) >= 3:
                raise web.HTTPServiceUnavailable(text='Discord 429 fixture')
            return await self.discord(*args, **kwargs)
        self.app['server_management_discord'] = limited
        store = SimpleNamespace(avatar=AsyncMock(return_value={'avatar':b'fake-png','avatar_type':'image/png'}))
        with patch.object(member_events, 'MemberEventStore', return_value=store):
            results = await asyncio.gather(*(member_events.avatar(self.request()) for _ in range(12)))
        self.assertEqual([r.status for r in results], [200]*12)
        self.assertEqual(len(self.calls), 3)

    async def test_twelve_avatar_requests_through_real_authorization_share_three_calls_under_rate_limit(self):
        await self.avatars()
        self.granted = False
        with self.assertRaises(web.HTTPForbidden):
            await server_management.require_manage(self.request(), 'roles')
        self.assertEqual(len(self.calls), 3)

    async def test_listing_reuses_identity_but_settings_reads_and_writes_stay_fresh(self):
        await server_management.require_manage(self.request(), 'roles')
        await server_management.require_manage(self.request(path='/api/cwl/manage/member-events'), 'roles')
        self.assertEqual(len(self.calls), 3)
        for _ in range(2):
            req = self.request('PUT', '/api/cwl/manage/member-events/settings')
            req.json = AsyncMock(return_value={})
            with self.assertRaises(web.HTTPBadRequest):
                await member_events.save_settings(req)
        self.assertEqual(len(self.calls), 9)
        for _ in range(2):
            await server_management.require_manage(self.request(path='/api/cwl/manage/member-events/settings'), 'roles')
        self.assertEqual(len(self.calls), 15)

    async def test_error_not_cached_and_logout_invalidation_and_expiry_refetch(self):
        self.fail = True
        with self.assertRaises(web.HTTPServiceUnavailable):
            await server_management.require_manage(self.request(), 'roles')
        self.fail = False
        await server_management.require_manage(self.request(), 'roles')
        self.assertEqual(len(self.calls), 6)
        invalidate(self.app, UID)
        await server_management.require_manage(self.request(), 'roles')
        self.assertEqual(len(self.calls), 9)
        self.app[KEY][UID]['until'] = 0
        await server_management.require_manage(self.request(), 'roles')
        self.assertEqual(len(self.calls), 12)

    async def test_cache_is_lru_bounded_and_logout_during_fetch_does_not_reinsert(self):
        app = {}
        fetch = AsyncMock(return_value={})
        for i in range(128): await read(app, str(i), fetch)
        await read(app, '0', fetch)
        await read(app, '128', fetch)
        self.assertEqual(len(app[KEY]), 128)
        self.assertIn('0', app[KEY]); self.assertNotIn('1', app[KEY])
        gate = asyncio.Event()
        async def pending(): await gate.wait(); return {}
        job = asyncio.create_task(read(app, 'pending', pending))
        await asyncio.sleep(0)
        invalidate(app, 'pending'); gate.set(); await job
        self.assertNotIn('pending', app[KEY])
