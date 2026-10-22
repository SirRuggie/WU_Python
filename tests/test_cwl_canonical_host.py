"""Domain migration must not forward credentials or create old-origin state."""
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cwl_web.canonical_host import canonical_host


class CanonicalHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = 0
        async def endpoint(request):
            self.calls += 1
            return web.Response(text="handled")
        app = web.Application(middlewares=[canonical_host])
        app.router.add_route("*", "/{path:.*}", endpoint)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_old_links_preserve_destination_without_running_handler(self):
        for path in ("/signup", "/?view=bonuses&season=1", "/api/cwl/auth/discord?view=signup", "/signup?next=https://evil.example/path"):
            response = await self.client.get(path, headers={"Host": "cwl.ruggie.zone"}, allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers['Location'], 'https://dash.warriorsunited.cc' + path)
            self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(self.calls, 0)

    async def test_old_callback_discards_credentials(self):
        response = await self.client.get('/api/cwl/auth/callback?code=secret&state=secret', headers={'Host': 'cwl.ruggie.zone'}, allow_redirects=False)
        self.assertEqual(response.headers['Location'], 'https://dash.warriorsunited.cc/')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')

    async def test_old_writes_are_not_forwarded_or_processed(self):
        response = await self.client.post('/api/cwl/signups', headers={'Host': 'cwl.ruggie.zone'}, json={'account': 'test'}, allow_redirects=False)
        self.assertEqual(response.status, 409)
        self.assertNotIn('Location', response.headers)
        self.assertEqual(self.calls, 0)

    async def test_new_and_local_hosts_remain_unchanged(self):
        for host in ('dash.warriorsunited.cc', '127.0.0.1:8766', 'localhost:8766', 'cwl.ruggie.zone.evil.example'):
            response = await self.client.get('/signup', headers={'Host': host, 'X-Forwarded-Host': 'cwl.ruggie.zone'}, allow_redirects=False)
            self.assertEqual(response.status, 200)
