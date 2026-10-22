"""Current-clan restrictions and durable, staff-only member change reviews."""
import unittest
from unittest.mock import AsyncMock
import test_cwl_web_foundation as fixture


class SignupPolicyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WebFoundationTests.asyncSetUp
    asyncTearDown = fixture.WebFoundationTests.asyncTearDown
    auth = fixture.WebFoundationTests.auth
    call = fixture.WebFoundationTests.call
    season = fixture.WebFoundationTests.season

    async def test_batch_fwa_rejection_atomic_and_staff_cannot_bypass(self):
        sid = await self.season()
        self.providers.family_clans = AsyncMock(return_value={'clans': [{'tag': '#R2Y', 'type': 'FWA'}]})
        choices = [{'tag': tag, 'prefer_crystal_1_or_lower': False} for tag in ('#Q2Y', '#P2Y')]
        for endpoint, headers, body in [
            ('signups', self.member, {'pool': 'main', 'accounts': choices}),
            ('staff-signups', self.owner, {'pool': 'main', 'accounts': choices, 'user_id': '100'}),
        ]:
            response = await self.call('POST', f'/seasons/{sid}/{endpoint}', headers, json=body)
            self.assertEqual(response.status, 409, await response.text())
            self.assertEqual(self.app['store'].rows('SELECT * FROM signups'), [])

    async def test_assigned_pool_change_clears_placement_alerts_once_and_review_is_scoped(self):
        sid = await self.season()
        account = {'tag': '#P2Y', 'prefer_crystal_1_or_lower': False}
        self.assertEqual((await self.call('POST', f'/seasons/{sid}/signups', self.member,
            json={'pool': 'main', 'accounts': [account]})).status, 200)
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?, '#P2Y', '#R2Y', 1)", (sid,))
        body = {'pool': 'lazy', 'accounts': [{**account, 'move_from_pool': 'main'}]}
        self.assertEqual((await self.call('POST', f'/seasons/{sid}/signups', self.member, json=body)).status, 200)
        self.assertIsNone(self.app['store'].one('SELECT assigned_clan_tag FROM roster_entries')['assigned_clan_tag'])
        self.assertEqual((await self.call('POST', f'/seasons/{sid}/signups', self.member, json=body)).status, 409)
        path = f'/seasons/{sid}/signup-activity'
        self.assertEqual((await self.call('GET', path, self.member)).status, 403)
        items = (await (await self.call('GET', path, self.owner)).json())['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['action'], 'member_pool_change')
        self.assertEqual(items[0]['assigned_clan_tag'], '#R2Y')
        endpoint = path + f"/{items[0]['id']}/review"
        no_csrf = {k: v for k, v in self.owner.items() if k != 'X-CSRF-Token'}
        self.assertEqual((await self.call('POST', endpoint, no_csrf)).status, 403)
        self.assertEqual((await self.call('POST', endpoint, self.member)).status, 403)
        self.assertEqual((await self.call('POST', endpoint.replace(f'/seasons/{sid}', '/seasons/999'), self.owner)).status, 404)
        for _ in range(2):
            self.assertEqual((await self.call('POST', endpoint, self.owner)).status, 200)
        self.assertEqual((await (await self.call('GET', path, self.owner)).json())['items'], [])
        self.assertEqual((await self.call('DELETE', f'/seasons/{sid}/signups/%23P2Y', self.member)).status, 200)
        self.assertEqual((await self.call('DELETE', f'/seasons/{sid}/signups/%23P2Y', self.member)).status, 200)
        items = (await (await self.call('GET', path, self.owner)).json())['items']
        self.assertEqual(items, [])
        self.assertEqual(len(self.app['store'].rows("SELECT * FROM roster_audit WHERE action='member_withdrawal'")), 1)

    async def test_only_placed_changes_are_listed_before_limit_and_name_is_preserved(self):
        import json
        sid = await self.season()
        store = self.app['store']
        with store.tx() as db:
            db.execute("INSERT OR REPLACE INTO clans(tag,name) VALUES ('#R2Y','Former hosting clan')")
        account = {'tag': '#P2Y', 'prefer_crystal_1_or_lower': False}
        await self.call('POST', f'/seasons/{sid}/signups', self.member,
                        json={'pool': 'main', 'accounts': [account]})
        with store.tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?, '#P2Y', '#R2Y', 0)", (sid,))
        self.assertEqual((await self.call('DELETE', f'/seasons/{sid}/signups/%23P2Y', self.member)).status, 200)
        with store.tx() as db:
            db.execute("UPDATE clans SET name='Renamed clan' WHERE tag='#R2Y'")
            for _ in range(105):
                db.execute("INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json) VALUES (?,?,?,?,?)",
                           (sid, '#OTHER', '100', 'member_pool_change', json.dumps({'pool':'main','assigned_clan_tag':None})))
        path = f'/seasons/{sid}/signup-activity'
        items = (await (await self.call('GET', path, self.owner)).json())['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['assigned_clan_name'], 'Former hosting clan')
        self.assertEqual(items[0]['assigned_clan_tag'], '#R2Y')
        self.assertEqual(items[0]['action'], 'member_withdrawal')
        self.assertEqual(len(store.rows("SELECT * FROM roster_audit WHERE action='member_pool_change'")), 105)
