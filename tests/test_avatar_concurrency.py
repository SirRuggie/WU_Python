"""Isolated avatar load diagnostics; no live Discord or Mongo access."""
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pymongo.errors import ServerSelectionTimeoutError

from cwl_web.app import errors
from cwl_web import issues


class AvatarDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_mongo_cause_class_reaches_issue_without_secret_exception_text(self):
        request = make_mocked_request('GET', '/api/cwl/manage/member-events/example/avatar')

        async def unavailable(_):
            try:
                raise ServerSelectionTimeoutError('secret provider connection string')
            except ServerSelectionTimeoutError as exc:
                raise web.HTTPServiceUnavailable(text='Temporarily unavailable') from exc

        async def adapted(req):
            return await errors(req, unavailable)

        with patch.object(issues, 'record', new=AsyncMock(return_value='fixture')) as record:
            response = await issues.diagnostics(request, adapted)
        self.assertEqual(response.status, 503)
        self.assertEqual(record.call_args.kwargs['error_type'], 'ServerSelectionTimeoutError')
        self.assertNotIn('secret', str(record.call_args))
        self.assertNotIn('secret', response.text)


class AvatarPool(unittest.IsolatedAsyncioTestCase):
    async def test_twelve_parallel_avatars_share_one_pool_and_auth_every_request(self):
        import asyncio
        from types import SimpleNamespace
        from cwl_web import member_events, server_management, mongo_client
        from unittest.mock import Mock
        app = {}
        lifetime = server_management.mongo_lifecycle(app)
        await anext(lifetime)
        clients = []

        def make_client(*args, **kwargs):
            # A fixture with a one-pool budget reproduces pool proliferation:
            # restoring per-request clients fails the concurrent load below.
            if clients:
                raise ServerSelectionTimeoutError('fixture connection budget exhausted')
            client = SimpleNamespace(member_events=object(), close=AsyncMock())
            clients.append(client)
            return client

        async def auth(request, section):
            async with server_management.mongo(request):
                await asyncio.sleep(0)

        async def avatar(*args):
            await asyncio.sleep(0)
            return {'avatar': b'fixture', 'avatar_type':'image/png'}

        requests = [SimpleNamespace(app=app, match_info={'event_id':'1792972800000:'+f'{i:032x}'}) for i in range(12)]
        with patch.dict('os.environ', {'MONGODB_URI':'mongodb://fixture.invalid'}), patch.object(mongo_client, 'MongoClient', side_effect=make_client), patch.object(member_events, 'require_manage', new=AsyncMock(side_effect=auth)) as authorize, patch.object(member_events, 'MemberEventStore', return_value=SimpleNamespace(avatar=AsyncMock(side_effect=avatar))):
            responses = await asyncio.gather(*(member_events.avatar(request) for request in requests))
            self.assertEqual([r.status for r in responses], [200]*12)
            self.assertEqual(authorize.await_count, 12)
            self.assertEqual(len(clients), 1)
            clients[0].close.assert_not_awaited()
        with self.assertRaises(StopAsyncIteration):
            await anext(lifetime)
        clients[0].close.assert_awaited_once()

    async def test_injected_pool_is_not_owned_or_closed(self):
        from types import SimpleNamespace
        from cwl_web import server_management
        client = SimpleNamespace(close=AsyncMock())
        app = {'server_management_mongo':client}
        lifetime = server_management.mongo_lifecycle(app)
        await anext(lifetime)
        async with server_management.mongo(SimpleNamespace(app=app)) as actual:
            self.assertIs(actual, client)
        with self.assertRaises(StopAsyncIteration):
            await anext(lifetime)
        client.close.assert_not_awaited()
