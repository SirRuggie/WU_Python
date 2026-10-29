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
