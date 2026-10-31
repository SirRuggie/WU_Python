import io,json,unittest
from unittest.mock import patch,AsyncMock
from PIL import Image
import test_cwl_web_roster as fixtures
from cwl_web.roster_images import render,GUILD_ID
class RosterImageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.RosterTests.asyncSetUp
    asyncTearDown=fixtures.RosterTests.asyncTearDown
    auth=fixtures.RosterTests.auth
    call=fixtures.RosterTests.call
    signup=fixtures.RosterTests.signup
    revision=fixtures.RosterTests.revision
    host=fixtures.RosterTests.host
    async def publish(self):
        await self.signup('main','#P2Y');await self.host('#C2Y','main')
        response=await self.call('PATCH',f'/seasons/{self.sid}/roster/%23P2Y',self.owner,json={'revision':await self.revision(),'assigned_clan_tag':'#C2Y'})
        self.assertEqual(response.status,200)
        response=await self.call('POST',f'/seasons/{self.sid}/publication',self.owner,json={'revision':await self.revision(),'acknowledge_unassigned':True,'joining_instructions':''})
        self.assertEqual(response.status,201)
    async def test_preview_requires_staff_and_published_snapshot(self):
        path=f'/seasons/{self.sid}/roster-images'
        self.assertEqual((await self.call('GET',path,self.member)).status,403)
        self.assertEqual((await self.call('GET',path,self.owner)).status,409)
        await self.publish()
        with self.app['store'].tx() as db:db.execute("UPDATE roster_entries SET assigned_clan_tag=NULL WHERE season_id=?",(self.sid,))
        data=await (await self.call('GET',path,self.owner)).json()
        self.assertEqual(data['clans'][0]['count'],1)
        image=await self.call('GET',path+'/%23C2Y.png?version=1',self.owner)
        self.assertEqual(image.status,200)
        self.assertEqual(Image.open(io.BytesIO(await image.read())).width,1000)
        self.assertEqual((await self.call('GET',path+'/%23C2Y.png?version=2',self.owner)).status,409)
        self.assertEqual((await self.call('GET',path+'/%23C2Y.png?page=2',self.owner)).status,400)
    async def test_test_send_no_pings_deduplicated_and_channel_guard(self):
        await self.publish();path=f'/seasons/{self.sid}/roster-images/%23C2Y/test'
        before_audit = self.app['store'].one('SELECT COUNT(*) AS n FROM roster_audit')['n']
        body={'channel_id':'123456789012345678','request_id':'a'*24,'version':1}
        mock=AsyncMock(side_effect=[{'guild_id':str(GUILD_ID),'type':0},{'id':'987654321098765432'},{'guild_id':str(GUILD_ID),'type':0}])
        with patch('cwl_web.roster_images.discord',mock):
            first=await self.call('POST',path,self.owner,json=body);self.assertEqual(first.status,200)
            second=await self.call('POST',path,self.owner,json=body);self.assertEqual(second.status,200)
            self.assertEqual(await first.json(),await second.json())
        self.assertEqual(self.app['store'].one('SELECT COUNT(*) AS n FROM roster_audit')['n'], before_audit)
        self.assertEqual(sum(c.args[1]=='POST' for c in mock.call_args_list),1)
        form=mock.call_args_list[1].kwargs['data']
        payload=json.loads(form._fields[0][2]);self.assertEqual(payload['allowed_mentions'],{'parse':[], 'roles':[]})
        self.assertFalse(payload['content'].startswith('TEST')); self.assertTrue(payload['content'].startswith('**'))
        with patch('cwl_web.roster_images.discord',AsyncMock(return_value={'guild_id':'other','type':0})):
            self.assertEqual((await self.call('POST',path,self.owner,json=body|{'request_id':'b'*24})).status,400)
    def test_render_splits_fifteen_per_image(self):
        group={'name':'Clan','tag':'#ABC','pool':'lazy','league':'Unranked','accounts':[{'player_name':'𝕿𝕳𝕰 Player','tag':'#ABC','town_hall':18}]*30}
        first=render({'label':'November'},{'version':1},group,1)
        second=render({'label':'November'},{'version':1},group,2)
        self.assertEqual(Image.open(io.BytesIO(first)).height,1440)
        self.assertNotEqual(first,second)
