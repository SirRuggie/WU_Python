"""Moderation follow-up: honest failures, quiet missing avatars and unsent claims."""
import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from cwl_web import member_events as api, moderation_names, server_management
from utils.member_events import GUILD_ID, MemberEventStore, TestRateLimited as RateLimited
from utils.member_event_cards import build_card, build_forum_message, sample_row
from tests import test_member_event_settings as existing


class TestSendPolish(unittest.IsolatedAsyncioTestCase):
    setUp = existing.TestSendApiTests.setUp
    _call = existing.TestSendApiTests._call

    async def test_real_card_and_forum_test_labels_reach_transport(self):
        self.card_module.sample_row = sample_row
        self.card_module.build_card = build_card
        self.card_module.build_forum_message = build_forum_message
        for kind in ('join', 'leave', 'kick', 'ban'):
            self.saved['events'][kind] = dict(self.saved['events']['kick'])
            for destination in ('text', 'forum'):
                self.store.reserve_test.reset_mock()
                self.store.finish_test.reset_mock()
                _, transport = await self._call(kind, option_type=destination)
                payload = transport.await_args.kwargs['json']
                self.assertIn('Test log · sent by <@123456789012345678>', json.dumps(payload, ensure_ascii=False))
                if destination == 'forum':
                    self.assertTrue(payload['name'].startswith('Test ' + kind + ' · '))
                self.assertEqual((payload.get('message') or payload)['allowed_mentions'], {'parse': []})

    async def test_rate_limited_response_is_429_and_no_delivery(self):
        self.store.reserve_test.side_effect = RateLimited('Wait 10 seconds')
        with self.assertRaises(web.HTTPTooManyRequests):
            await self._call()
        self.store.finish_test.assert_not_awaited()

    async def test_revision_recheck_cancels_own_slot_before_any_post(self):
        self.store.settings.side_effect = [self.saved, {**self.saved, 'revision': 4}]
        self.store.cancel_test = AsyncMock()
        self.card_module.build_card = Mock(side_effect=AssertionError('Must cancel before constructing/posting the message'))
        with self.assertRaises(web.HTTPConflict):
            await self._call()
        self.card_module.build_card.assert_not_called()
        self.store.cancel_test.assert_awaited_once_with('test-audit-id', kind='kick', destination='111111111111111111')

    async def test_cancel_releases_only_its_own_rate_claim(self):
        class Audit:
            def __init__(self): self.rows = {}
            async def find_one_and_update(self, query, update, **kw):
                from pymongo.errors import DuplicateKeyError
                old = self.rows.get(query['_id'])
                if old and old['last_at'] > query['last_at']['$lte']: raise DuplicateKeyError('occupied')
                self.rows[query['_id']] = {'_id': query['_id'], **update['$set']}
            async def insert_one(self, row): self.rows[row['_id']] = dict(row)
            async def update_one(self, query, update):
                row = self.rows.get(query['_id'])
                if row and all(row.get(k) == v for k,v in query.items()): row.update(update['$set'])
            async def delete_one(self, query):
                row = self.rows.get(query['_id'])
                if row and all(row.get(k) == v for k,v in query.items()): del self.rows[query['_id']]
        audit = Audit(); store = MemberEventStore(object(), audit)
        now = datetime.now(timezone.utc)
        first = await store.reserve_test('join', 'staff', now)
        await store.cancel_test(first, kind='join', destination='channel')
        second = await store.reserve_test('join', 'staff', now + timedelta(seconds=1))
        await store.cancel_test(first, kind='join', destination='channel')
        with self.assertRaises(RateLimited): await store.reserve_test('join', 'staff', now + timedelta(seconds=2))
        self.assertEqual(audit.rows[first]['status'], 'cancelled')
        self.assertEqual(audit.rows[second]['status'], 'attempting')


class AvatarPolish(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = NS(app={}, match_info={'event_id': '1792972800000:'+'a'*32})
        self.store = NS(avatar=AsyncMock(return_value=None))
    @asynccontextmanager
    async def db(self, request): yield NS(member_events=object())

    async def test_missing_is_204_negatively_cached_bounded_and_still_authorized(self):
        with patch.object(api, 'require_manage', new=AsyncMock()) as auth, patch.object(api, 'mongo', self.db), patch.object(api, 'MemberEventStore', return_value=self.store):
            for _ in range(2): self.assertEqual((await api.avatar(self.request)).status, 204)
            self.assertEqual(self.store.avatar.await_count, 1)
            self.assertEqual(auth.await_count, 2)
            auth.side_effect = web.HTTPForbidden()
            with self.assertRaises(web.HTTPForbidden): await api.avatar(self.request)
            auth.side_effect = None
            self.request.app['member_avatar_missing'][(GUILD_ID,self.request.match_info['event_id'])] = 0
            self.assertEqual((await api.avatar(self.request)).status, 204)
            self.assertEqual(self.store.avatar.await_count, 2)
            for n in range(130):
                self.request.match_info['event_id'] = '1792972800000:'+f'{n:032x}'
                await api.avatar(self.request)
            self.assertEqual(len(self.request.app['member_avatar_missing']), 128)
            self.assertTrue(all(key[0] == GUILD_ID for key in self.request.app['member_avatar_missing']))

    async def test_storage_and_auth_outages_remain_503_not_cached_as_missing(self):
        @asynccontextmanager
        async def unavailable(request): raise web.HTTPServiceUnavailable(text='Database unavailable'); yield
        with patch.object(api, 'require_manage', new=AsyncMock()), patch.object(api, 'mongo', unavailable):
            with self.assertRaises(web.HTTPServiceUnavailable): await api.avatar(self.request)
        self.assertFalse(self.request.app.get('member_avatar_missing'))
        with patch.object(api, 'require_manage', new=AsyncMock(side_effect=web.HTTPServiceUnavailable(text='Authorization unavailable'))):
            with self.assertRaises(web.HTTPServiceUnavailable): await api.avatar(self.request)
        self.assertFalse(self.request.app.get('member_avatar_missing'))

    async def test_real_mongo_adapter_preserves_database_failure_as_503(self):
        from pymongo.errors import ServerSelectionTimeoutError
        client = NS(member_events=object(), close=AsyncMock())
        self.store.avatar.side_effect = ServerSelectionTimeoutError('fixture database unavailable')
        with patch.dict('os.environ', {'MONGODB_URI': 'mongodb://fixture.invalid'}), patch('cwl_web.mongo_client.MongoClient', return_value=client), patch.object(api, 'require_manage', new=AsyncMock()), patch.object(api, 'MemberEventStore', return_value=self.store):
            with self.assertRaises(web.HTTPServiceUnavailable) as caught:
                await api.avatar(self.request)
            self.assertIn('Server settings are unavailable', caught.exception.text)
            client.close.assert_not_awaited()
            self.assertFalse(self.request.app.get('member_avatar_missing'))
            with self.assertRaises(web.HTTPServiceUnavailable):
                await api.avatar(self.request)
            self.assertEqual(self.store.avatar.await_count, 2)
            self.assertFalse(self.request.app.get('member_avatar_missing'))

    async def test_saved_image_is_served_and_malformed_id_never_reads_storage(self):
        self.store.avatar.return_value={'avatar':b'fixture','avatar_type':'image/png'}
        with patch.object(api, 'require_manage', new=AsyncMock()), patch.object(api, 'mongo', self.db), patch.object(api, 'MemberEventStore', return_value=self.store):
            response=await api.avatar(self.request)
            self.assertEqual((response.status,response.body,response.content_type),(200,b'fixture','image/png'))
            self.request.match_info['event_id']='../foreign'
            with self.assertRaises(web.HTTPNotFound): await api.avatar(self.request)
            self.store.avatar.assert_awaited_once()


class NamePolish(unittest.IsolatedAsyncioTestCase):
    async def test_listing_returns_resolved_moderator_name(self):
        uid = '987654321098765432'
        row = {**sample_row('kick'), '_id': '1792972800000:' + 'a' * 32,
               'moderator_id': uid, 'delivery_status': 'sent'}
        store = NS(search=AsyncMock(return_value=([row], None)))
        @asynccontextmanager
        async def database(request):
            yield NS(member_events=object())
        request = make_mocked_request('GET', api.PREFIX, app=web.Application())
        with patch.object(api, 'require_manage', new=AsyncMock()) as auth, \
             patch.object(api, 'mongo', database), \
             patch.object(api, 'MemberEventStore', return_value=store), \
             patch.object(moderation_names, 'discord', new=AsyncMock(return_value={
                 'user': {'id': uid, 'username': 'moderator'}, 'nick': 'Morgan <Staff>',
             })) as lookup:
            response = await api.listing(request)
        auth.assert_awaited_once_with(request, 'roles')
        lookup.assert_awaited_once_with(request, 'GET', f'/guilds/{GUILD_ID}/members/{uid}')
        event = json.loads(response.text)['events'][0]
        self.assertEqual(event['moderator_id'], uid)
        self.assertEqual(event['moderator_name'], 'Morgan <Staff>')

    async def test_unique_name_lookup_uses_existing_member_shape_and_cache(self):
        request=NS(app={});uid='123456789012345678'
        with patch.object(moderation_names,'discord',new=AsyncMock(return_value={'user':{'id':uid,'username':'person'},'nick':'<b>Mod & Name</b>'})) as lookup:
            self.assertEqual(await moderation_names.resolve_names(request,[uid,uid,None]),{uid:'<b>Mod & Name</b>'})
            await moderation_names.resolve_names(request,[uid]);lookup.assert_awaited_once()
        with patch.object(moderation_names,'discord',new=AsyncMock(side_effect=web.HTTPNotFound())):
            self.assertEqual(await moderation_names.resolve_names(NS(app={}),[uid]),{uid:None})

    async def test_lookup_concurrency_is_bounded_and_cancelled_with_request(self):
        active=0; peak=0
        async def lookup(*args):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try: await asyncio.sleep(.01);return {'user':{'id':args[2].split('/')[-1],'username':'Staff'}}
            finally:active-=1
        with patch.object(moderation_names,'discord',lookup):
            result=await moderation_names.resolve_names(NS(app={}),[str(123456789012345678+n) for n in range(12)])
        self.assertEqual(len(result),12);self.assertEqual(peak,3);self.assertEqual(active,0)

    async def test_bad_member_payloads_are_unknown_and_negative_cached(self):
        uid = '123456789012345678'
        for response in (None, [], {'user': {'id': 'bad'}}, {'user': {'id': uid}}):
            request = NS(app={})
            with patch.object(moderation_names, 'discord', new=AsyncMock(return_value=response)) as lookup:
                self.assertEqual(await moderation_names.resolve_names(request, [uid]), {uid: None})
                await moderation_names.resolve_names(request, [uid])
                lookup.assert_awaited_once()

    async def test_page_cancellation_cleans_pending_lookups(self):
        entered = asyncio.Event()
        stopped = asyncio.Event()
        async def lookup(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        with patch.object(moderation_names, 'discord', lookup):
            task = asyncio.create_task(moderation_names.resolve_names(NS(app={}), ['123456789012345678']))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(stopped.is_set())
