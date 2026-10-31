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
