"""Staff signup editing: atomic batches, ownership, eligibility and privacy."""
import unittest
from unittest.mock import AsyncMock
import test_cwl_web_foundation as fixture


class StaffSignupChangesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WebFoundationTests.asyncSetUp
    asyncTearDown = fixture.WebFoundationTests.asyncTearDown
    auth = fixture.WebFoundationTests.auth
    call = fixture.WebFoundationTests.call
    season = fixture.WebFoundationTests.season

    async def seed(self):
        sid = await self.season()
        await self.call('POST', f'/seasons/{sid}/signups', self.member, json={
            'pool':'lazy','accounts':[{'tag':t,'prefer_crystal_1_or_lower':False} for t in ['#P2Y','#Q2Y']]})
        with self.app['store'].tx() as db:
            db.execute("INSERT OR REPLACE INTO clans(tag,name) VALUES ('#R2Y','Private hosting clan')")
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#P2Y','#R2Y')", (sid,))
        data = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.owner)).json()
        return sid, data['revision']

    async def test_atomic_change_stale_retry_and_member_privacy(self):
        sid, revision = await self.seed()
        member = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.member)).json()
        self.assertNotIn('Private hosting clan', str(member))
        self.assertNotIn('assigned_clan_tag', str(member))
        staff = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.owner)).json()
        self.assertEqual(staff['signups'][0]['assigned_clan_name'], 'Private hosting clan')
        body={'revision':revision,'user_id':'100','tags':['#P2Y','#Q2Y'],'action':'main'}
        path=f'/seasons/{sid}/staff-signup-changes'
        self.assertEqual((await self.call('POST',path,self.member,json=body)).status,403)
        self.assertEqual((await self.call('POST',path,{k:v for k,v in self.owner.items() if k!='X-CSRF-Token'},json=body)).status,403)
        response=await self.call('POST',path,self.owner,json=body)
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((await response.json())['count'],2)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'main'})
        self.assertIsNone(self.app['store'].one('SELECT assigned_clan_tag FROM roster_entries')['assigned_clan_tag'])
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual(len(self.app['store'].rows("SELECT * FROM roster_audit WHERE action='staff_pool_change'")),2)

    async def test_fwa_or_changed_member_rejects_whole_batch(self):
        sid, revision=await self.seed()
        path=f'/seasons/{sid}/staff-signup-changes'
        body={'revision':revision,'user_id':'100','tags':['#Q2Y','#P2Y'],'action':'main'}
        self.providers.family_clans=AsyncMock(return_value={'clans':[{'tag':'#R2Y','type':'FWA'}]})
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'lazy'})
        body.update(action='remove',user_id='200')
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual(len(self.app['store'].rows('SELECT * FROM signups')),2)
        body.update(user_id='100')
        result=await self.call('POST',path,self.owner,json=body)
        self.assertEqual(result.status,200,await result.text())
        self.assertEqual(self.app['store'].rows('SELECT * FROM signups'),[])
        self.assertEqual(self.app['store'].rows('SELECT * FROM roster_entries'),[])
        self.assertEqual(len(self.app['store'].rows("SELECT * FROM roster_audit WHERE action='staff_remove_signup'")),2)

    async def test_malformed_and_archived_batches(self):
        sid,revision=await self.seed()
        path=f'/seasons/{sid}/staff-signup-changes'
        body={'revision':revision,'user_id':'100','tags':['#P2Y'],'action':'remove'}
        for patch in [{'tags':[]},{'tags':['#P2Y','#P2Y']},{'action':'other'},{'user_id':None}]:
            self.assertEqual((await self.call('POST',path,self.owner,json={**body,**patch})).status,400)
        with self.app['store'].tx() as db: db.execute("UPDATE seasons SET status='archived' WHERE id=?",(sid,))
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,423)

    async def test_revision_change_during_upstream_check_does_not_mutate(self):
        sid,revision=await self.seed()
        async def changing_player(value):
            with self.app['store'].tx() as db:
                db.execute('UPDATE roster_meta SET revision=revision+1 WHERE season_id=?',(sid,))
            return self.providers.players[value].copy()
        self.providers.player=changing_player
        result=await self.call('POST',f'/seasons/{sid}/staff-signup-changes',self.owner,json={
            'revision':revision,'user_id':'100','tags':['#P2Y','#Q2Y'],'action':'main'})
        self.assertEqual(result.status,409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'lazy'})
        self.assertEqual(self.app['store'].one('SELECT assigned_clan_tag FROM roster_entries')['assigned_clan_tag'],'#R2Y')
