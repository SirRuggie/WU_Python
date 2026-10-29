"""Opt-in transport behavior must not alter other dashboard callers."""
import json
import unittest
from unittest.mock import patch
from aiohttp import web
from cwl_web.server_management import discord, DiscordDeliveryUncertain


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value

    async def __aexit__(self, *args):
        return False


class Response:
    status = 429

    async def json(self):
        return {'retry_after': 1.25}


class Client:
    def request(self, *args, **kwargs):
        return Context(Response())


class Request:
    app = {}


class ImageTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_opt_in_preserves_default(self):
        with patch.dict('os.environ', {'DISCORD_TOKEN': 'fake'}), patch('cwl_web.server_management.aiohttp.ClientSession', return_value=Context(Client())):
            with self.assertRaises(web.HTTPServiceUnavailable):
                await discord(Request(), 'POST', '/fake')
            with self.assertRaises(web.HTTPTooManyRequests) as result:
                await discord(Request(), 'POST', '/fake', roster_delivery=True)
            self.assertEqual(json.loads(result.exception.text)['retry_after'], 1.25)

    async def test_timeout_opt_in_preserves_default(self):
        with patch.dict('os.environ', {'DISCORD_TOKEN': 'fake'}), patch('cwl_web.server_management.aiohttp.ClientSession', return_value=Context(TimeoutError())):
            with self.assertRaises(web.HTTPServiceUnavailable):
                await discord(Request(), 'POST', '/fake')
            with self.assertRaises(DiscordDeliveryUncertain):
                await discord(Request(), 'POST', '/fake', roster_delivery=True)

    async def test_server_error_opt_in_preserves_default(self):
        with patch.object(Response, 'status', 502), patch.dict('os.environ', {'DISCORD_TOKEN': 'fake'}), patch('cwl_web.server_management.aiohttp.ClientSession', return_value=Context(Client())):
            with self.assertRaises(web.HTTPServiceUnavailable):
                await discord(Request(), 'POST', '/fake')
            with self.assertRaises(DiscordDeliveryUncertain):
                await discord(Request(), 'POST', '/fake', roster_delivery=True)

    async def test_injected_transport_receives_opt_in_only(self):
        from unittest.mock import AsyncMock
        fake = AsyncMock(return_value={'id': 'fake'})
        request = Request()
        request.app = {'server_management_discord': fake}
        await discord(request, 'POST', '/fake')
        self.assertNotIn('roster_delivery', fake.call_args.kwargs)
        await discord(request, 'POST', '/fake', roster_delivery=True)
        self.assertTrue(fake.call_args.kwargs['roster_delivery'])
