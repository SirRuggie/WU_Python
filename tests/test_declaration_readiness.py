from test_cwl_web_roster import RosterTests
from cwl_web.providers import ProviderUnavailable
from unittest.mock import AsyncMock
import unittest

class DeclarationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=RosterTests.asyncSetUp
    asyncTearDown=RosterTests.asyncTearDown
    auth=RosterTests.auth
    call=RosterTests.call
    signup=RosterTests.signup
    revision=RosterTests.revision

    async def test_location_refresh_and_staff_only(self):
        await self.signup('main','#P2Y')
        url=f'/seasons/{self.sid}/arrival-check'
        self.assertEqual((await self.call('GET',url,self.member)).status,403)
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#P2Y','#R2Y')",(self.sid,))
        data=await (await self.call('GET',url,self.owner)).json()
        self.assertEqual(data['source'],'draft')
        self.assertEqual(data['accounts'][0]['arrival_status'],'arrived')
        self.app['providers'].players['#P2Y']['current_clan_tag']='#J2Y'
        data=await (await self.call('GET',url+'?refresh=1',self.owner)).json()
        self.assertEqual(data['accounts'][0]['arrival_status'],'missing')
        self.assertTrue(data['accounts'][0]['outside_family'])
        self.app['providers'].player=AsyncMock(side_effect=ProviderUnavailable('offline'))
        data=await (await self.call('GET',url+'?refresh=1',self.owner)).json()
        self.assertEqual(data['accounts'][0]['arrival_status'],'unknown')
        self.assertEqual(data['accounts'][0]['current_clan_status'],'stale')

    async def publish(self):
        response = await self.call('POST', f'/seasons/{self.sid}/publication', self.owner, json={
            'revision': await self.revision(), 'acknowledge_unassigned': True, 'joining_instructions': 'Test snapshot'})
        self.assertEqual(response.status, 201)

    async def test_current_signups_default_and_outdated_snapshot_counts(self):
        await self.signup('lazy', '#P2Y')
        await self.publish()
        url = f'/seasons/{self.sid}/arrival-check'
        same = await (await self.call('GET', url+'?source=published', self.owner)).json()
        self.assertFalse(same['publication_outdated'])
        self.assertTrue(same['publication_available'])
        await self.call('DELETE', f'/seasons/{self.sid}/signups/%23P2Y', self.member)
        await self.signup('main', '#Q2Y')
        current = await (await self.call('GET', url, self.owner)).json()
        self.assertEqual(current['source'], 'draft')
        self.assertEqual([a['tag'] for a in current['accounts']], ['#Q2Y'])
        snapshot = await (await self.call('GET', url+'?source=published&refresh=1', self.owner)).json()
        self.assertEqual([a['tag'] for a in snapshot['accounts']], ['#P2Y'])
        self.assertTrue(snapshot['publication_outdated'])
        self.assertEqual(snapshot['removed_since_publication'], 1)
        self.assertEqual(snapshot['added_since_publication'], 1)
        self.assertIsNotNone(snapshot['published_at'])

    async def test_pool_change_marks_snapshot_outdated_without_added_or_removed_accounts(self):
        await self.signup('main', '#P2Y')
        await self.publish()
        response = await self.call('POST', f'/seasons/{self.sid}/signups', self.member, json={
            'pool': 'lazy', 'accounts': [{'tag': '#P2Y', 'prefer_crystal_1_or_lower': False, 'move_from_pool': 'main'}]})
        self.assertEqual(response.status, 200)
        data = await (await self.call('GET', f'/seasons/{self.sid}/arrival-check?source=published', self.owner)).json()
        self.assertTrue(data['publication_outdated'])
        self.assertEqual((data['removed_since_publication'], data['added_since_publication']), (0, 0))

    async def test_missing_publication_and_invalid_source(self):
        url = f'/seasons/{self.sid}/arrival-check'
        data = await (await self.call('GET', url+'?source=published', self.owner)).json()
        self.assertEqual(data['source'], 'draft')
        self.assertFalse(data['publication_available'])
        self.assertFalse(data['publication_outdated'])
        self.assertEqual((await self.call('GET', url+'?source=invalid', self.owner)).status, 400)
