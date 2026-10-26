"""Real isolated loopback HTTP tests: no production service or signup writes."""
import asyncio
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from utils.cwl_member_client import MemberClientError, bridge_config, request


class MemberClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.mode = 'ok'
        async def endpoint(req):
            self.calls.append((await req.json(), req.headers.get('X-CWL-Discord-Secret')))
            if self.mode == 'redirect':
                raise web.HTTPTemporaryRedirect('/api/cwl/discord/member')
            if self.mode == 'broken':
                return web.Response(text='broken', status=502)
            if self.mode == 'conflict':
                return web.json_response({'error': 'Signups changed. Review again.'}, status=409)
            if self.mode == 'stream':
                response = web.StreamResponse(headers={'Content-Type': 'application/json'})
                await response.prepare(req)
                await response.write(b'{\"ok\":')
                await asyncio.sleep(.01)
                await response.write(b'true}')
                await response.write_eof()
                return response
            if self.mode == 'slow':
                await asyncio.sleep(.2)
            return web.json_response({'ok': True})
        app = web.Application()
        app.router.add_post('/api/cwl/discord/member', endpoint)
        self.server = TestServer(app)
        await self.server.start_server()
        self.env = patch.dict('os.environ', {
            'CWL_DISCORD_BRIDGE_URL': str(self.server.make_url('')).rstrip('/'),
            'CWL_DISCORD_BRIDGE_SECRET': 'test-secret-' * 4,
        })
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.server.close()

    async def test_identity_header_and_single_request(self):
        self.assertEqual(await request('view', user_id=123, guild_id=456), {'ok': True})
        self.assertEqual(self.calls, [({'action': 'view', 'user_id': '123', 'guild_id': '456'}, 'test-secret-' * 4)])

    async def test_no_redirect_retry_or_ambiguous_save_retry(self):
        for mode in ('redirect', 'broken'):
            self.mode = mode
            self.calls.clear()
            with self.assertRaises(MemberClientError) as failure:
                await request('submit', user_id=123, guild_id=456)
            self.assertTrue(failure.exception.uncertain)
            self.assertEqual(len(self.calls), 1)

    async def test_known_conflict_is_safe_and_read_failure_not_write_uncertainty(self):
        self.mode = 'conflict'
        with self.assertRaises(MemberClientError) as failure:
            await request('withdraw', user_id=123, guild_id=456)
        self.assertFalse(failure.exception.uncertain)
        self.assertIn('Review again', str(failure.exception))
        self.mode = 'broken'
        with self.assertRaises(MemberClientError) as failure:
            await request('view', user_id=123, guild_id=456)
        self.assertFalse(failure.exception.uncertain)

    async def test_streamed_json_response_is_read_completely(self):
        self.mode = 'stream'
        self.assertEqual(await request('submit', user_id=123, guild_id=456), {'ok': True})
        self.assertEqual(len(self.calls), 1)

    async def test_cancellation_propagates_without_retry(self):
        self.mode = 'slow'
        task = asyncio.create_task(request('submit', user_id=123, guild_id=456))
        while not self.calls:
            await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.calls), 1)

    def test_nonloopback_credentials_and_weak_secret_fail_before_io(self):
        for url in ('https://example.com', 'http://localhost:8767', 'http://127.0.0.1@evil.com',
                    'http://127.0.0.1/path', 'http://127.0.0.1?x=1', 'http://127.0.0.1:bad'):
            with patch.dict('os.environ', {'CWL_DISCORD_BRIDGE_URL': url}):
                with self.assertRaises(MemberClientError):
                    bridge_config()
        with patch.dict('os.environ', {'CWL_DISCORD_BRIDGE_SECRET': 'short'}):
            with self.assertRaises(MemberClientError):
                bridge_config()
