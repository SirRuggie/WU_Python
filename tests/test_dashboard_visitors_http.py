import test_cwl_web_foundation as foundation
import unittest
from unittest.mock import patch


class VisitorsHTTPTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.WebFoundationTests.asyncSetUp
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call

    async def test_only_authenticated_session_calls_count_and_owner_gets_aggregates(self):
        response = await self.client.get('/api/cwl/auth/me')
        self.assertEqual(response.status, 401)
        self.assertEqual(self.app['visit_store'].rows('SELECT * FROM visit_days'), [])
        for _ in range(2):
            response = await self.call('GET', '/auth/me', self.member)
            self.assertEqual(response.status, 200)
        rows = self.app['visit_store'].rows('SELECT * FROM visit_days')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['is_staff'], 0)
        denied = await self.call('GET', '/manage/visitors', self.member)
        self.assertEqual(denied.status, 403)
        allowed = await self.call('GET', '/manage/visitors', self.owner)
        self.assertEqual(allowed.status, 200)
        body = await allowed.json()
        self.assertEqual(body['windows']['1'], {'total': 1, 'staff': 0, 'members': 1})
        self.assertNotIn('user_id', str(body))
        self.assertEqual(len(body['series']), 30)

    async def test_counter_failure_does_not_break_session(self):
        with patch.object(self.app['visit_store'], 'record_session', side_effect=RuntimeError('fixture')):
            response = await self.call('GET', '/auth/me', self.member)
        self.assertEqual(response.status, 200)

    async def test_oauth_bot_keeps_auth_behavior_but_is_not_counted(self):
        self.app["oauth"] = {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://example.test/callback"}
        response = await self.call("GET", "/auth/discord", allow_redirects=False)
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(response.headers["Location"]).query)["state"][0]
        cookie = response.cookies["cwl_oauth_state"].value

        class FakeResponse:
            status = 200
            def __init__(self, payload):
                self.payload = payload
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def json(self):
                return self.payload

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            def post(self, url, **kwargs):
                return FakeResponse({"access_token": "test-token"})
            def get(self, url, **kwargs):
                if url.endswith("/users/@me"):
                    return FakeResponse({"id": "300", "bot": True, "username": "owner_handle", "global_name": "Current owner", "avatar": "a_0123456789abcdef0123456789abcdef"})
                return FakeResponse([{"id": "644963518025826315", "owner": True}])

        with patch("cwl_web.app.aiohttp.ClientSession", return_value=FakeSession()):
            response = await self.call("GET", f"/auth/callback?state={state}&code=code",
                                       {"Cookie": "cwl_oauth_state=" + cookie + "; wu_login_page=/cwl/publish?season=12&step=announce"}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertIn("cwl_session", response.cookies)
        counted = await self.call('GET', '/auth/me', {"Cookie": "cwl_session=" + response.cookies["cwl_session"].value})
        self.assertEqual(counted.status, 200)
        self.assertEqual(self.app["visit_store"].rows("SELECT * FROM visit_days"), [])
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM sessions WHERE user_id='300'")), 1)

    async def test_repeat_auth_me_does_no_visit_database_work(self):
        first = await self.call('GET', '/auth/me', self.member)
        self.assertEqual(first.status, 200)
        with patch.object(self.app['visit_store'], 'tx', side_effect=AssertionError('repeat DB access')) as tx:
            second = await self.call('GET', '/auth/me', self.member)
        self.assertEqual(second.status, 200)
        tx.assert_not_called()

    async def test_failing_durable_publisher_is_never_used_by_counting(self):
        from test_cwl_dashboard_state import Collection
        from utils.cwl_dashboard_state import MongoDashboardState
        store = self.app['store']
        collection = Collection()
        owner = MongoDashboardState(collection)
        owner.seed(store.path)
        owner.restore(store.path)
        store.durability = owner
        collection.fail = 'before'
        with patch.object(owner, 'publish', wraps=owner.publish) as publish:
            response = await self.call('GET', '/auth/me', self.member)
            self.assertEqual(response.status, 200)
            publish.assert_not_called()
        self.assertFalse(owner.poisoned)
        self.assertEqual(len(self.app['visit_store'].rows('SELECT * FROM visit_days')), 1)
        collection.fail = None
        with store.tx() as db:
            db.execute("INSERT INTO seasons(id,label) VALUES(999,'Unrelated write succeeds')")
        self.assertEqual(store.one('SELECT label FROM seasons WHERE id=999')['label'], 'Unrelated write succeeds')
        self.assertFalse(store.rows("SELECT name FROM sqlite_master WHERE name='visit_days'"))

    async def test_counting_runs_on_worker_and_errors_are_rate_limited(self):
        import threading
        from cwl_web.visitors import LOG
        loop_thread = threading.get_ident()
        threads = []
        def broken(*args, **kwargs):
            threads.append(threading.get_ident())
            raise RuntimeError('non-durable file unavailable')
        with patch.object(self.app['visit_store'], 'record_session', side_effect=broken), patch.object(LOG, 'exception') as log:
            for _ in range(3):
                response = await self.call('GET', '/auth/me', self.member)
                self.assertEqual(response.status, 200)
            self.assertEqual(log.call_count, 1)
        self.assertTrue(threads)
        self.assertNotIn(loop_thread, threads)

    async def test_cache_resets_at_local_day_boundary_and_has_a_bound(self):
        from cwl_web.visitors import VisitCounter
        from datetime import datetime, timezone, timedelta
        from unittest.mock import Mock
        store = Mock()
        counter = VisitCounter(store)
        first = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
        with patch('cwl_web.visitors.MAX_DAILY_CACHE', 2):
            await counter.record('100', first, False)
            await counter.record('100', first + timedelta(hours=1), True)
            self.assertEqual(store.record_session.call_count, 1)
            await counter.record('200', first, False)
            await counter.record('300', first, False)
            self.assertEqual(len(counter.seen), 2)
            self.assertEqual(store.record_session.call_count, 2)
            await counter.record('300', first + timedelta(days=1), False)
            self.assertEqual(store.record_session.call_count, 3)
            self.assertEqual(len(counter.seen), 1)


    async def test_cached_count_skips_staff_scope_lookup(self):
        from types import SimpleNamespace
        from cwl_web.visitors import record
        request = SimpleNamespace(app=self.app)
        session = {'user_id': '987654321', 'is_bot': False}
        with patch('cwl_web.app._owner', return_value=False), patch('cwl_web.access_control.request_scopes', return_value=[]) as scopes:
            await record(request, session)
            await record(request, session)
        scopes.assert_called_once_with(request, session['user_id'])
