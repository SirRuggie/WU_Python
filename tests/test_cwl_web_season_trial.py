"""Isolated whole-season acceptance trial; no live APIs, bot or announcements."""
import csv
import io
import unittest
import test_cwl_web_roster as fixture


class SeasonTrial(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.RosterTests.asyncSetUp
    asyncTearDown = fixture.RosterTests.asyncTearDown
    auth = fixture.RosterTests.auth
    call = fixture.RosterTests.call
    revision = fixture.RosterTests.revision
    signup = fixture.RosterTests.signup
    host = fixture.RosterTests.host

    async def test_complete_season_and_archive(self):
        base = f'/seasons/{self.sid}'
        async def request(method, path, body=None, who=None, status=200):
            response = await self.call(method, base + path, who or self.owner, **({'json': body} if body is not None else {}))
            self.assertEqual(response.status, status, await response.text())
            return await response.json()
        # One member joins both pools with different accounts; moves require consent.
        self.assertEqual((await self.signup('main', '#P2Y')).status, 200)
        self.assertEqual((await self.signup('lazy', '#Q2Y', True)).status, 200)
        await request('POST', '/signups', {'pool': 'main', 'accounts': [{'tag': '#Q2Y', 'prefer_crystal_1_or_lower': False}]}, self.member, 409)
        await request('POST', '/signups', {'pool': 'main', 'accounts': [{'tag': '#Q2Y', 'prefer_crystal_1_or_lower': False, 'move_from_pool': 'lazy'}]}, self.member)
        await request('POST', '/signups', {'pool': 'lazy', 'accounts': [{'tag': '#Q2Y', 'prefer_crystal_1_or_lower': True, 'move_from_pool': 'main'}]}, self.member)
        await self.signup('main', '#G2Y')
        await request('DELETE', '/signups/%23G2Y', who=self.member)
        # Staff prepares actual rules and source weights, then applies the preview.
        await self.host('#C2Y', 'main')
        await self.host('#R2Y', 'lazy', True)
        await request('POST', '/roster/refresh-weights', {'revision': await self.revision()})
        preview = await request('POST', '/roster/auto-preview', {'revision': await self.revision()})
        self.assertEqual(len(preview['placements']), 2)
        await request('POST', '/roster/auto-apply', {'revision': preview['revision'], 'placements': preview['placements']})
        provisional = await request('GET', '/my-assignments', who=self.member)
        self.assertEqual(len(provisional['accounts']), 2)
        self.assertTrue(all(row['assigned_clan_tag'] is None for row in provisional['accounts']))
        self.assertIsNone(provisional['published'])
        outsider = await request('GET', '/my-assignments', who=self.auth('200'))
        self.assertEqual(outsider['accounts'], [])
        await request('POST', '/publication', {'revision': await self.revision(), 'acknowledge_unassigned': False, 'joining_instructions': ''}, status=201)
        self.assertFalse((await request('GET', '/my-assignments', who=self.member))['draft_changed'])
        await request('POST', '/participation/sync-settings', {'cycle': '2026-10', 'enabled': False})
        await request('PATCH', '/participation/%23P2Y', {'revision': 0, 'publication_version': 1, 'attacks': 7, 'stars': 18, 'notes': 'Season trial'})
        await request('PATCH', '/bonuses/settings', {'revision': 0, 'policy': {'min_attacks': 5, 'min_stars': 8, 'cooldown_months': 0}, 'clans': [{'tag': '#C2Y', 'slots': 1}, {'tag': '#R2Y', 'slots': 1}]})
        await request('PATCH', '/bonuses/draft', {'revision': 1, 'selections': [{'tag': '#P2Y', 'reason': 'Trial manual results reviewed'}]})
        preview = await request('GET', '/bonuses/preview')
        await request('POST', '/bonuses/confirm', {'revision': 2, 'fingerprint': preview['fingerprint'], 'acknowledge_warnings': True})
        # Archive must preserve official member visibility and readable exports.
        await request('PATCH', '', {'status': 'archived', 'signup_open': False})
        assignments = await request('GET', '/my-assignments', who=self.member)
        self.assertFalse(assignments['draft_changed'], 'Archiving alone must not turn official placements provisional')
        self.assertEqual(len(assignments['accounts']), 2)
        for kind in ('accounts', 'participation', 'bonus-history'):
            response = await self.call('GET', base + '/export.csv?kind=' + kind, self.owner)
            self.assertEqual(response.status, 200)
            rows = list(csv.DictReader(io.StringIO((await response.read()).decode('utf-8-sig'))))
            self.assertTrue(rows)
            self.assertEqual(rows[0]['season_status'], 'archived')
        await request('PATCH', '/roster/%23P2Y', {'revision': await self.revision(), 'assigned_clan_tag': None}, status=423)
        await request('POST', '/publication', {'revision': await self.revision(), 'acknowledge_unassigned': True, 'joining_instructions': ''}, status=423)
        await request('POST', '/signups', {'pool': 'main', 'accounts': [{'tag': '#G2Y', 'prefer_crystal_1_or_lower': False}]}, self.member, 423)

    async def test_administration_does_not_hide_real_unpublished_edits(self):
        await self.signup('main', '#P2Y')
        base = f'/seasons/{self.sid}'
        response = await self.call('POST', base + '/publication', self.owner,
            json={'revision': await self.revision(), 'acknowledge_unassigned': True, 'joining_instructions': ''})
        self.assertEqual(response.status, 201)
        # Closing signup and renaming do not change roster content.
        response = await self.call('PATCH', base, self.owner, json={'signup_open': False, 'label': 'Closed October trial'})
        self.assertEqual(response.status, 200)
        self.assertFalse((await (await self.call('GET', base + '/publication', self.owner)).json())['draft_changed'])
        # A genuine weight edit still requires republishing, including after archive.
        response = await self.call('PATCH', base + '/roster/%23P2Y', self.owner,
            json={'revision': await self.revision(), 'manual_weight': 174000})
        self.assertEqual(response.status, 200)
        self.assertTrue((await (await self.call('GET', base + '/publication', self.owner)).json())['draft_changed'])
        await self.call('PATCH', base, self.owner, json={'status': 'archived'})
        self.assertFalse((await (await self.call('GET', base + '/my-assignments', self.member)).json())['draft_changed'])
