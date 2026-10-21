"""Member season is explicit, server enforced, and stable across new drafts."""
import unittest
import test_cwl_web_foundation as foundation
from cwl_web.store import Store


class MemberSeasonTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.WebFoundationTests.asyncSetUp
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call
    season = foundation.WebFoundationTests.season
    async def test_visibility_stale_links_and_writes(self):
        first = await self.season()
        created = await self.call('POST', '/seasons', self.owner, json={'label':'November 2026','signup_open':True})
        second = (await created.json())['id']
        initial = await (await self.call('GET','/seasons',self.member)).json()
        self.assertEqual([x['id'] for x in initial['seasons']], [first])
        self.assertEqual(initial['member_season']['season_id'], first)
        change = {'season_id':second,'revision':initial['member_season']['revision']}
        self.assertEqual((await self.call('PUT','/member-season',self.member,json=change)).status,403)
        self.assertEqual((await self.call('PUT','/member-season',{'Cookie':self.owner['Cookie']},json=change)).status,403)
        self.assertEqual((await self.call('PUT','/member-season',self.owner,json=change)).status,200)
        self.assertEqual((await self.call('PUT','/member-season',self.owner,json=change)).status,409)
        for suffix in ('signups','my-assignments'):
            self.assertEqual((await self.call('GET',f'/seasons/{first}/{suffix}',self.member)).status,403)
            self.assertEqual((await self.call('GET',f'/seasons/{second}/{suffix}',self.member)).status,200)
        body={'pool':'main','accounts':[{'tag':'#P2Y','prefer_crystal_1_or_lower':False}]}
        self.assertEqual((await self.call('POST',f'/seasons/{first}/signups',self.member,json=body)).status,403)
        self.assertEqual((await self.call('DELETE',f'/seasons/{first}/signups/%23P2Y',self.member)).status,403)
        self.assertEqual((await self.call('GET',f'/seasons/{first}/signups',self.owner)).status,200)
        visible=await (await self.call('GET','/seasons',self.member)).json()
        self.assertEqual([x['id'] for x in visible['seasons']],[second])
        # Restart never changes an explicit selection.
        self.assertEqual(Store(self.app['store'].path).member_season()['season_id'],second)
        self.assertEqual((await self.call('PATCH',f'/seasons/{second}',self.owner,json={'status':'archived'})).status,200)
        archived=await (await self.call('GET','/seasons',self.member)).json()
        self.assertEqual(archived['member_season']['season_id'],second)
        self.assertEqual((await self.call('POST',f'/seasons/{second}/signups',self.member,json=body)).status,423)
        self.assertEqual(Store(self.app['store'].path).member_season()['season_id'],second)

    async def test_hide_and_malformed_choices(self):
        sid=await self.season()
        current=await (await self.call('GET','/seasons',self.owner)).json()
        revision=current['member_season']['revision']
        for value in (True,'1',-1,9999,2**64):
            self.assertEqual((await self.call('PUT','/member-season',self.owner,json={'season_id':value,'revision':revision})).status,400)
        self.assertEqual((await self.call('PUT','/member-season',self.owner,json={'season_id':None,'revision':revision})).status,200)
        self.assertEqual((await self.call('GET',f'/seasons/{sid}/signups',self.member)).status,403)
        result=await (await self.call('POST','/seasons',self.owner,json={'label':'Future draft','signup_open':False})).json()
        self.assertTrue(result['id'])
        self.assertIsNone(self.app['store'].member_season()['season_id'])


    async def test_legacy_migration_pins_once_and_keeps_hidden_choice(self):
        first=await self.season()
        second=(await (await self.call('POST','/seasons',self.owner,json={'label':'Next season','signup_open':False})).json())['id']
        with self.app['store'].tx() as db:
            db.execute('DROP TABLE member_season')
        migrated=Store(self.app['store'].path)
        self.assertEqual(migrated.member_season()['season_id'],second)
        migrated.set_member_season(first,0,'owner')
        self.assertEqual(Store(migrated.path).member_season()['season_id'],first)
        migrated.set_member_season(None,1,'owner')
        self.assertIsNone(Store(migrated.path).member_season()['season_id'])
