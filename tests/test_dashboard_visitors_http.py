from test_cwl_web_foundation import WebFoundationTests
from unittest.mock import patch


class VisitorsHTTPTests(WebFoundationTests):
    async def test_only_authenticated_session_calls_count_and_owner_gets_aggregates(self):
        response = await self.client.get('/api/cwl/auth/me')
        self.assertEqual(response.status, 401)
        self.assertEqual(self.app['store'].rows('SELECT * FROM visit_days'), [])
        for _ in range(2):
            response = await self.call('GET', '/auth/me', self.member)
            self.assertEqual(response.status, 200)
        rows = self.app['store'].rows('SELECT * FROM visit_days')
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

    async def test_oauth_bot_is_rejected_without_visit_or_session(self):
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
        self.assertEqual(response.status, 403)
        self.assertNotIn("cwl_session", response.cookies)
        self.assertEqual(self.app["store"].rows("SELECT * FROM visit_days"), [])
        self.assertEqual(self.app["store"].rows("SELECT * FROM sessions WHERE user_id='300'"), [])
