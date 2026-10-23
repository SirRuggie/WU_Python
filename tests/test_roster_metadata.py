import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cwl_web.providers import ProviderUnavailable
from cwl_web.roster_metadata import enrich, lifecycle


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_family_refresh_is_unknown_and_has_cooldown(self):
        provider = SimpleNamespace(family_clans=AsyncMock(side_effect=ProviderUnavailable('offline')))
        request = SimpleNamespace(app={'providers': provider,
            'roster_family_snapshot': (0, {'#OLD'})})
        result = {'accounts': [], 'clans': []}
        self.assertIsNone(await enrich(request, result))
        self.assertTrue(result['metadata_updating'])
        await request.app['roster_family_job']
        self.assertIsNone(await enrich(request, result))
        self.assertFalse(result['metadata_updating'])
        provider.family_clans.assert_awaited_once()

    async def test_family_job_is_cancelled_on_shutdown(self):
        release = asyncio.Event()
        async def wait():
            await release.wait()
        request = SimpleNamespace(app={'providers': SimpleNamespace(family_clans=wait)})
        life = lifecycle(request.app)
        await anext(life)
        await enrich(request, {'accounts': [], 'clans': []})
        task = request.app['roster_family_job']
        with self.assertRaises(StopAsyncIteration):
            await anext(life)
        self.assertTrue(task.cancelled())

    async def test_fresh_directory_does_not_refetch(self):
        provider = SimpleNamespace(family_clans=AsyncMock())
        request = SimpleNamespace(app={'providers': provider,
            'roster_family_snapshot': (time.monotonic()+120, {'#FAMILY'})})
        self.assertEqual(await enrich(request, {'accounts': [], 'clans': []}), {'#FAMILY'})
        provider.family_clans.assert_not_awaited()
