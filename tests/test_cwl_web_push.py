"""Push is explicit, account scoped, deadline bound and durable across restarts."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from cwl_web import push
from cwl_web.store import Store


def subscription(host='fcm.googleapis.com'):
    return {'endpoint': f'https://{host}/send/example', 'keys': {
        'p256dh': base64.urlsafe_b64encode(b'\x04'+b'x'*64).decode().rstrip('='),
        'auth': base64.urlsafe_b64encode(b'x'*16).decode().rstrip('=')}}


def prefs():
    return {'enabled': 1, 'tags': json.dumps(['#P2Y', '#Q2Y', '#R2Y']), 'war': 1, 'cwl': 1, 'offsets': '[360,120,30]', 'updated_at': 100}


def snapshot(now=10000):
    def row(tag, clan, **overrides):
        return {'tag': tag, 'name': tag, 'clan_tag': clan, 'clan_name': clan, 'state': 'inWar', 'remaining': 1, 'ends_at': now+1800, **overrides}
    return {'views': {'war': {'ok': True, 'rows': [row('#P2Y', '#C2Y'), row('#Q2Y', '#C2Y'), row('#R2Y', '#V2Y')]}, 'cwl': {'ok': True, 'rows': []}}}


class PlannerTests(unittest.TestCase):
    def test_one_per_clan_and_no_completed_unselected_accounts(self):
        data = snapshot()
        data['views']['war']['rows'] += [{'tag': '#OTHER', 'clan_tag': '#C2Y', 'state': 'inWar', 'remaining': 2, 'ends_at': 11800}]
        planned = push.plan(data, prefs(), 10000)
        self.assertEqual(len(planned), 2)
        self.assertEqual(set(planned[0]['accounts']), {'#P2Y', '#Q2Y'})
        data['views']['war']['rows'][0]['remaining'] = 0
        self.assertEqual(set(push.plan(data, prefs(), 10000)[0]['accounts']), {'#Q2Y'})

    def test_no_late_bursts_or_future_or_new_optin(self):
        self.assertEqual(push.plan(snapshot(), prefs(), 10121), [])
        self.assertEqual(push.plan(snapshot(), prefs(), 9999), [])
        self.assertEqual(push.plan(snapshot(), prefs() | {'updated_at': 10001}, 10002), [])
        self.assertEqual(push.plan(snapshot(), prefs(), 11801), [])

    def test_unavailable_preparation_and_unknown_not_sent(self):
        data = snapshot()
        data['views']['war']['ok'] = False
        self.assertEqual(push.plan(data, prefs(), 10000), [])
        for field, value in [('state', 'preparation'), ('ends_at', None), ('remaining', None), ('clan_tag', None)]:
            data = snapshot()
            for row in data['views']['war']['rows']:
                row[field] = value
            self.assertEqual(push.plan(data, prefs(), 10000), [])

    def test_notification_summary_and_account_details(self):
        item = push.plan(snapshot(), prefs(), 10000)[0]
        item['accounts']['#P2Y'].update(name='Sir 2 Stoned', remaining=2)
        item['accounts']['#Q2Y'].update(name='₮HɆ ĐɄ₳Ⱡł₮Ɏ', remaining=2)
        payload = push.reminder_payload(item)
        self.assertEqual(payload['body'], '4 attacks remaining across 2 accounts\nSir 2 Stoned: 2 attacks\n₮HɆ ĐɄ₳Ⱡł₮Ɏ: 2 attacks')
        self.assertIn('⚔️ War · 30m remaining', payload['title'])
        self.assertEqual(payload['url'], '/tasks')
        for offset, expected in [(540, '9h'), (95, '1h 35m'), (1, '1m')]:
            self.assertIn(expected + ' remaining', push.reminder_payload(item | {'offset': offset})['title'])
        item['kind'] = 'cwl'
        item['accounts'] = {'#P2Y': {'name': 'Solo', 'remaining': 1}}
        self.assertEqual(push.reminder_payload(item)['body'], '1 attack remaining across 1 account\nSolo: 1 attack')
        self.assertIn('🏆 CWL', push.reminder_payload(item)['title'])
        for number in range(5):
            item['accounts'][str(number)] = {'name': 'Long\n' + 'x' * 80, 'remaining': 2}
        payload = push.reminder_payload(item)
        self.assertTrue(payload['body'].startswith('11 attacks remaining across 6 accounts'))
        self.assertEqual(len(payload['body'].splitlines()), 5)
        self.assertTrue(payload['body'].endswith('+3 more accounts · Open Todo'))
        self.assertIn('…: 2 attacks', payload['body'])

    def test_endpoint_allowlist(self):
        for host in ['127.0.0.1', 'localhost', 'fcm.googleapis.com.evil.test', 'evil.test']:
            with self.assertRaises(Exception):
                push._subscription(subscription(host))
        self.assertEqual(push._subscription(subscription()), subscription())
        for endpoint in ['http://fcm.googleapis.com/send', 'https://user@fcm.googleapis.com/send', 'https://fcm.googleapis.com:8443/send']:
            with self.assertRaises(Exception):
                push._subscription(subscription() | {'endpoint': endpoint})


class Providers:
    async def linked_tags(self, uid):
        return {'#P2Y': True, '#Q2Y': True, '#R2Y': True} if uid == '100' else {'#OTHER': True}


class PushTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(db_path=str(Path(self.tmp.name)/'db'), providers=Providers(), secure_cookies=False, dev_fixture=True)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        private = Path(self.tmp.name)/'key.pem'
        private.write_text('test key')
        self.cfg = patch.dict(os.environ, {'CWL_PUSH_VAPID_PRIVATE_KEY': str(private), 'CWL_PUSH_VAPID_PUBLIC_KEY': 'public', 'CWL_PUSH_VAPID_SUBJECT': 'mailto:test@example.com'})
        self.cfg.start()

    async def asyncTearDown(self):
        self.cfg.stop()
        await self.client.close()
        self.tmp.cleanup()

    def auth(self, uid='100', csrf=True):
        raw = secrets.token_urlsafe(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)', (hashlib.sha256(raw.encode()).hexdigest(), uid, uid, 0, 'csrf', int(time.time())+900))
        return {'Cookie': 'cwl_session='+raw} | ({'X-CSRF-Token': 'csrf'} if csrf else {})

    async def save(self):
        body = {'subscription': subscription(), 'enabled': True, 'tags': ['#P2Y', '#Q2Y', '#R2Y'], 'war': True, 'cwl': True, 'offsets': [30]}
        response = await self.client.put(push.API+'/subscriptions', json=body, headers=self.auth())
        self.assertEqual(response.status, 200, await response.text())
        return await response.json(), body

    async def test_custom_reminder_times_are_validated_and_persisted(self):
        _, body = await self.save()
        for offsets in ([1, 95, 1440], [45]):
            response = await self.client.put(push.API+'/subscriptions', json=body | {'offsets': offsets}, headers=self.auth())
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['offsets'], sorted(offsets, reverse=True))
        for offsets in ([], [0], [1441], [True], [1.5], [30, 30], [1,2,3,4,5,6], [[30]]):
            response = await self.client.put(push.API+'/subscriptions', json=body | {'offsets': offsets}, headers=self.auth())
            self.assertEqual(response.status, 400, str(offsets))

    async def test_auth_csrf_ownership_and_no_secret_response(self):
        self.assertEqual((await self.client.get(push.API)).status, 401)
        saved, body = await self.save()
        self.assertEqual(saved['id'], hashlib.sha256(subscription()['endpoint'].encode()).hexdigest())
        response = await self.client.get(push.API, headers=self.auth())
        text = await response.text()
        self.assertNotIn('endpoint', text)
        self.assertNotIn('p256dh', text)
        self.assertNotIn('key.pem', text)
        self.assertEqual((await self.client.put(push.API+'/subscriptions', json=body, headers=self.auth(csrf=False))).status, 403)
        other = await self.client.get(push.API, headers=self.auth('200'))
        self.assertEqual((await other.json())['subscriptions'], [])
        self.assertEqual((await self.client.put(push.API+'/subscriptions', json=body | {'tags':['#OTHER']}, headers=self.auth('200'))).status, 409)
        self.assertEqual((await self.client.put(push.API+'/subscriptions', json=body | {'tags':['#OTHER']}, headers=self.auth())).status, 403)
        await self.client.delete(push.API+'/subscriptions/'+saved['id'], headers=self.auth('200'))
        self.assertEqual(len((await (await self.client.get(push.API, headers=self.auth())).json())['subscriptions']), 1)

    async def test_durable_clan_dedup_and_expired_subscription_cleanup(self):
        saved, _ = await self.save()
        now = int(time.time())
        with self.app['store'].tx() as db:
            db.execute('UPDATE push_subscriptions SET updated_at=?', (now-100,))
        with patch.object(push, 'fresh', new=AsyncMock(return_value=snapshot(now))), patch.object(push, 'send', return_value='sent') as send:
            await push.process_user(self.app, '100')
            self.assertEqual(send.call_count, 2)
            self.assertEqual(send.call_args_list[0].args[1]['url'], '/tasks')
            self.assertIn('#P2Y', send.call_args_list[0].args[1]['body'])
            self.assertIn('#Q2Y', send.call_args_list[0].args[1]['body'])
            # Reopening the durable store simulates restart; no replay.
            self.app['store'] = Store(str(Path(self.tmp.name)/'db'))
            await push.process_user(self.app, '100')
            self.assertEqual(send.call_count, 2)
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM push_deliveries')
        with patch.object(push, 'fresh', new=AsyncMock(return_value=snapshot(now))), patch.object(push, 'send', return_value='expired') as send:
            await push.process_user(self.app, '100')
            self.assertEqual(send.call_count, 1)
        result = await self.client.get(push.API, headers=self.auth())
        self.assertEqual((await result.json())['subscriptions'], [])

    async def test_test_rate_limit_and_disable(self):
        saved, body = await self.save()
        with patch.object(push, 'send', return_value='sent') as send:
            endpoint = push.API+'/subscriptions/'+saved['id']+'/test'
            self.assertEqual((await self.client.post(endpoint, headers=self.auth())).status, 200)
            self.assertEqual(send.call_args.args[1]['url'], '/tasks')
            self.assertEqual((await self.client.post(endpoint, headers=self.auth())).status, 429)
        await self.client.put(push.API+'/subscriptions', json=body | {'enabled':False}, headers=self.auth())
        with patch.object(push, 'fresh', new=AsyncMock(return_value=snapshot(int(time.time())))), patch.object(push, 'send') as send:
            await push.process_user(self.app, '100')
            send.assert_not_called()

    async def test_unlinked_accounts_not_delivered(self):
        await self.save()
        # Fresh lookup excludes an account after unlinking, regardless of saved preferences.
        with patch('cwl_web.todo.get_clash_client', new=AsyncMock(return_value=object())), patch('cwl_web.todo.load_recent_clans', new=AsyncMock(return_value=({}, ''))), patch('utils.todo_data.fetch_accounts', new=AsyncMock(return_value=([], []))) as fetch, patch('utils.todo_data.build_war_view', new=AsyncMock(return_value=__import__('utils.todo_data', fromlist=['ViewData']).ViewData())), patch('utils.todo_data.build_cwl_view', new=AsyncMock(return_value=__import__('utils.todo_data', fromlist=['ViewData']).ViewData())):
            self.app['providers'].linked_tags = AsyncMock(return_value={'#Q2Y': True})
            await push.fresh(self.app, '100')
            self.assertEqual(fetch.call_args.args[1], ['#Q2Y'])

    async def test_slow_cwl_keeps_fresh_war_and_cancels_unfinished_read(self):
        from utils.todo_data import ViewData, Row
        await self.save()
        now = int(time.time())
        cancelled = asyncio.Event()

        async def slow(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        war = ViewData(rows=[Row('Player', '#P2Y', 'Clan', '#C2Y', 0, 2, now + 1800)])
        with patch('cwl_web.todo.get_clash_client', new=AsyncMock(return_value=object())), \
             patch('cwl_web.todo.load_recent_clans', new=AsyncMock(return_value=({}, ''))), \
             patch('utils.todo_data.fetch_accounts', new=AsyncMock(return_value=([], []))), \
             patch('utils.todo_data.build_war_view', new=AsyncMock(return_value=war)), \
             patch('utils.todo_data.build_cwl_view', new=slow), \
             patch.object(push, 'FRESH_VIEW_TIMEOUT', 0.02):
            result = await push.fresh(self.app, '100')
        self.assertTrue(cancelled.is_set())
        self.assertTrue(result['views']['war']['ok'])
        self.assertFalse(result['views']['cwl']['ok'])
        planned = push.plan(result, prefs(), now)
        self.assertEqual([item['kind'] for item in planned], ['war'])
        self.assertEqual(set(planned[0]['accounts']), {'#P2Y'})

    async def test_disabled_kind_is_not_fetched(self):
        from utils.todo_data import ViewData
        await self.save()
        with self.app['store'].tx() as db:
            db.execute('UPDATE push_subscriptions SET cwl=0')
        with patch('cwl_web.todo.get_clash_client', new=AsyncMock(return_value=object())), \
             patch('cwl_web.todo.load_recent_clans', new=AsyncMock(return_value=({}, ''))), \
             patch('utils.todo_data.fetch_accounts', new=AsyncMock(return_value=([], []))), \
             patch('utils.todo_data.build_war_view', new=AsyncMock(return_value=ViewData())), \
             patch('utils.todo_data.build_cwl_view', new=AsyncMock()) as cwl:
            result = await push.fresh(self.app, '100')
        cwl.assert_not_awaited()
        self.assertEqual(set(result['views']), {'war'})

    async def test_view_failure_and_cancellation_never_become_empty_success(self):
        with self.assertLogs(push.LOG, level='WARNING'):
            result = await push._fresh_view('war', AsyncMock(side_effect=ValueError('bad data'))())
        self.assertFalse(result['ok'])
        self.assertEqual(push.plan({'views': {'war': result}}, prefs(), 10000), [])
        with self.assertRaises(asyncio.CancelledError):
            await push._fresh_view('war', AsyncMock(side_effect=asyncio.CancelledError())())

    async def test_logout_removes_only_this_users_device(self):
        saved, _ = await self.save()
        response = await self.client.post('/api/cwl/auth/logout', json={'push_id': saved['id']}, headers=self.auth('200'))
        self.assertEqual(response.status, 200)
        result = await self.client.get(push.API, headers=self.auth())
        self.assertEqual(len((await result.json())['subscriptions']), 1)
        response = await self.client.post('/api/cwl/auth/logout', json={'push_id': saved['id']}, headers=self.auth())
        self.assertEqual(response.status, 200)
        result = await self.client.get(push.API, headers=self.auth())
        self.assertEqual((await result.json())['subscriptions'], [])

    async def test_unavailable_links_dont_change_settings(self):
        saved, body = await self.save()
        self.app['providers'].linked_tags = AsyncMock(side_effect=TimeoutError())
        response = await self.client.put(push.API+'/subscriptions', json=body, headers=self.auth())
        self.assertEqual(response.status, 503)

    async def test_pywebpush_signs_and_encrypts_without_redirects(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        from requests import Response
        vapid = Vapid()
        vapid.generate_keys()
        vapid.save_key(os.environ['CWL_PUSH_VAPID_PRIVATE_KEY'])
        recipient = ec.generate_private_key(ec.SECP256R1())
        point = recipient.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        sub = subscription()
        sub['keys']['p256dh'] = base64.urlsafe_b64encode(point).decode().rstrip('=')
        response = Response()
        response.status_code = 201
        response._content = b''
        with patch('requests.Session.request', return_value=response) as request:
            self.assertEqual(push.send(sub, {'title':'Test', 'body':'Private content'}), 'sent')
            kwargs = request.call_args.kwargs
            self.assertFalse(kwargs['allow_redirects'])
            self.assertEqual(kwargs['timeout'], 15)
            self.assertNotIn(b'Private content', kwargs['data'])
            self.assertIn('authorization', {key.lower(): value for key,value in kwargs['headers'].items()})

    async def test_fresh_read_context_does_not_disable_dashboard_cache(self):
        from utils import todo_data
        todo_data.cache_put('war:push-test', 'cached', 120)
        self.assertEqual(todo_data.cache_get('war:push-test'), 'cached')
        with todo_data.fresh_reads():
            self.assertIsNone(todo_data.cache_get('war:push-test'))
        self.assertEqual(todo_data.cache_get('war:push-test'), 'cached')
        todo_data.cache_drop_prefix('war:push-test')

    async def test_worker_assets_have_root_scope_and_no_cache(self):
        root = Path(self.tmp.name)/'static'
        root.mkdir()
        (root/'index.html').write_text('index')
        (root/'sw.js').write_text('self.addEventListener("push",()=>{});')
        (root/'manifest.webmanifest').write_text('{}')
        app = create_app(db_path=str(Path(self.tmp.name)/'assets-db'), providers=Providers(), dev_fixture=True, static_dir=str(root))
        async with TestClient(TestServer(app)) as client:
            page = await client.get('/')
            self.assertEqual(page.status, 200)
            self.assertIn('no-store', page.headers['Cache-Control'])
            response = await client.get('/sw.js')
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
            self.assertEqual(response.headers['Cache-Control'], 'no-cache')
            self.assertEqual(response.content_type, 'application/javascript')
            response = await client.get('/manifest.webmanifest')
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, 'application/manifest+json')
