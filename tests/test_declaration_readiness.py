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
