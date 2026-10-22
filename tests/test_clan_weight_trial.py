import unittest
from io import BytesIO
from openpyxl import load_workbook
from unittest.mock import AsyncMock
import test_cwl_web_foundation as foundation
from utils.clan_weight_store import ClanWeightStore
from cwl_web.providers import ProviderUnavailable


class WeightTrialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await foundation.WebFoundationTests.asyncSetUp(self)
        self.providers.family_clans=AsyncMock(return_value={'clans':[{'tag':'#R2Y','name':'Family','type':'FWA'}]})
    asyncTearDown=foundation.WebFoundationTests.asyncTearDown
    auth=foundation.WebFoundationTests.auth
    call=foundation.WebFoundationTests.call

    def roster(self, clan='#R2Y', members=None):
        self.providers.weight_war_lineup=AsyncMock(side_effect=ProviderUnavailable('No war'))
        rows=members if members is not None else [{'tag':'#P2Y','name':'=malicious()','town_hall':16},{'tag':'#Q2Y','name':'Second','town_hall':15}]
        self.providers.clan_roster=AsyncMock(return_value={'tag':clan,'name':'Family','members':rows})

    async def save(self,changes,actor=None,clan='%23R2Y'):
        return await self.call('PUT','/weight-trial/clans/'+clan,actor or self.owner,json={'changes':changes})

    async def test_roster_override_cannot_replace_official_clan_weight(self):
        self.roster()
        sid = await foundation.WebFoundationTests.season(self)
        await self.call('POST',f'/seasons/{sid}/signups',self.member,json={
            'pool':'lazy','accounts':[{'tag':'#P2Y','prefer_crystal_1_or_lower':False}]})
        await self.save([{'tag':'#P2Y','weight':149000,'revision':0}])
        roster = await (await self.call('GET',f'/seasons/{sid}/roster',self.owner)).json()
        response = await self.call('PATCH',f'/seasons/{sid}/roster/%23P2Y',self.owner,
            json={'revision':roster['revision'],'manual_weight':175000})
        self.assertEqual(response.status,409)
        self.assertEqual(roster['accounts'][0]['effective_weight'],149000)
        self.assertTrue(roster['accounts'][0]['clan_weight_managed'])
        self.assertEqual((await self.call('PATCH',f'/seasons/{sid}/roster/%23P2Y',self.owner,
            json={'revision':roster['revision'],'kept':True})).status,200)

    async def test_access_validation_atomicity_and_replay(self):
        self.roster()
        for route in ('/weight-trial/clans','/weight-trial/clans/%23R2Y','/weight-trial/export.xlsx'):
            self.assertEqual((await self.call('GET',route,self.member)).status,403)
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO grants(user_id,granted_by,permissions) VALUES ('100','owner','[\"clans\"]')")
        self.assertEqual((await self.call('GET','/weight-trial/clans',self.member)).status,200)
        with self.app['store'].tx() as db:
            db.execute("UPDATE grants SET permissions='[\"cwl\"]' WHERE user_id='100'")
        self.assertEqual((await self.call('GET','/weight-trial/clans',self.member)).status,403)
        item={'tag':'#P2Y','weight':149000,'revision':0}
        self.assertEqual((await self.save([item],self.member)).status,403)
        self.assertEqual((await self.save([item],{'Cookie':self.owner['Cookie']})).status,403)
        for value in [True,149,149001,0,-1000,1000000,'149000']:
            self.assertEqual((await self.save([{**item,'weight':value}])).status,400)
        self.assertEqual((await self.save([item,item])).status,400)
        self.assertEqual((await self.save([item],clan='%23J2Y')).status,404)
        self.assertEqual((await self.save([item,{'tag':'#G2Y','weight':100000,'revision':0}])).status,409)
        self.assertEqual(self.app['clan_weight_trial'].all(),[])
        self.assertEqual((await self.save([item])).status,200)
        self.assertEqual((await self.save([item])).status,200)
        self.assertEqual(len(self.app['store'].rows('SELECT * FROM clan_player_weight_history')),1)
        self.assertEqual((await self.save([{'tag':'#Q2Y','weight':130000,'revision':0},{**item,'weight':150000}])).status,409)
        self.assertEqual(len(self.app['clan_weight_trial'].all()),1)
        self.assertEqual(self.app['store'].rows('SELECT * FROM player_weights'),[])
        self.assertEqual(self.app['store'].rows('SELECT * FROM roster_entries'),[])

    async def test_current_members_movement_restart_export_and_clear(self):
        self.roster()
        await self.save([{'tag':'#P2Y','weight':149000,'revision':0}])
        self.roster(members=[])
        current=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertEqual(current['members'],[])
        self.assertEqual(ClanWeightStore(self.app['store'].path).all()[0]['weight'],149000)
        exported=await self.call('GET','/weight-trial/export.xlsx',self.owner)
        sheet=load_workbook(BytesIO(await exported.read())).active
        self.assertEqual(sheet['B2'].value,'=malicious()')
        self.assertEqual(sheet['B2'].data_type,'s')
        self.assertEqual(sheet['D2'].value,149)
        self.assertEqual(sheet['E2'].value,149000)
        self.providers.family_clans=AsyncMock(return_value={'clans':[{'tag':'#J2Y','name':'Other','type':'FWA'}]})
        self.roster('#J2Y')
        current=await (await self.call('GET','/weight-trial/clans/%23J2Y',self.owner)).json()
        self.assertEqual(current['members'][0]['weight'],149000)
        self.assertEqual((await self.save([{'tag':'#P2Y','weight':None,'revision':1}],clan='%23J2Y')).status,200)
        self.assertIsNone(self.app['clan_weight_trial'].all()[0]['weight'])
        self.providers.clan_roster=AsyncMock(side_effect=ProviderUnavailable('Unavailable'))
        self.assertEqual((await self.call('GET','/weight-trial/clans/%23J2Y',self.owner)).status,503)
        self.assertEqual((await self.save([{'tag':'#P2Y','weight':150000,'revision':2}],clan='%23J2Y')).status,503)
        self.assertIsNone(self.app['clan_weight_trial'].all()[0]['weight'])

    async def test_storage_calculation_persistence_and_conflict(self):
        self.roster()
        item={'tag':'#P2Y','weight':149000,'storages':5,'revision':0}
        self.assertEqual((await self.save([item])).status,200)
        self.assertEqual(ClanWeightStore(self.app['store'].path).all()[0]['storages'],5)
        for changes in ({'storages':True},{'storages':0},{'storages':6},{'weight':149001}):
            self.assertEqual((await self.save([{**item,**changes}])).status,400)
        self.assertEqual((await self.save([{**item,'storages':4}])).status,409)
        self.assertEqual((await self.save([{**item,'storages':4,'revision':1}])).status,200)
        self.assertEqual((await self.save([{**item,'storages':4,'revision':1}])).status,200)
        row=ClanWeightStore(self.app['store'].path).all()[0]
        self.assertEqual(row['storages'],4)
        self.assertEqual(row['revision'],2)

    async def test_war_order_is_optional_and_validated(self):
        from cwl_web.providers import LiveProviders
        provider=LiveProviders()
        provider._league_get=AsyncMock(return_value={'state':'inWar','clan':{'tag':'#R2Y','members':[{'tag':'#P2Y','mapPosition':1}]}})
        self.assertEqual(await provider.weight_war_order('#R2Y'),{'#P2Y':1})
        provider._league_get.return_value['teamSize'] = 2
        with self.assertRaises(ProviderUnavailable): await provider.weight_war_order('#R2Y')
        provider._league_get.return_value.pop('teamSize')
        provider._league_get.return_value['clan']['members'].append({'tag':'#Q2Y','mapPosition':1})
        with self.assertRaises(ProviderUnavailable): await provider.weight_war_order('#R2Y')
        self.roster()
        self.providers.weight_war_lineup=AsyncMock(side_effect=ProviderUnavailable('Private war'))
        result=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertIsNone(result['war_order'])
        self.assertEqual(len(result['members']),2)

    async def test_preparation_active_and_completed_lineup_sources(self):
        from cwl_web.providers import LiveProviders
        provider=LiveProviders()
        for state in ('preparation','inWar','warEnded'):
            provider._league_get=AsyncMock(return_value={'state':state,'clan':{'tag':'#R2Y','members':[{'tag':'#P2Y','mapPosition':1}]},'opponent':{'name':'Opponent'}})
            lineup=await provider.weight_war_lineup('#R2Y')
            self.assertEqual(lineup['state'],state)
            self.roster()
            self.providers.weight_war_lineup=AsyncMock(return_value=lineup)
            result=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
            self.assertEqual(result['war_source']['state'],state)
            self.assertEqual(result['war_order'],{'#P2Y':1})
        provider._league_get=AsyncMock(return_value={'state':'notInWar'})
        with self.assertRaises(ProviderUnavailable): await provider.weight_war_lineup('#R2Y')

    async def test_only_fwa_clans_listed_and_editable(self):
        self.roster()
        self.providers.family_clans=AsyncMock(return_value={'clans':[
            {'tag':'#R2Y','name':'FWA clan','type':'FWA'},
            {'tag':'#J2Y','name':'Tactical clan','type':'Tactical'},
            {'tag':'#C2Y','name':'Unknown category'},
        ]})
        result=await (await self.call('GET','/weight-trial/clans',self.owner)).json()
        self.assertEqual([clan['tag'] for clan in result['clans']],['#R2Y'])
        for clan in ('%23J2Y','%23C2Y'):
            self.assertEqual((await self.call('GET','/weight-trial/clans/'+clan,self.owner)).status,404)
            self.assertEqual((await self.save([{'tag':'#P2Y','weight':149000,'revision':0}],clan=clan)).status,404)
        self.providers.clan_roster.assert_not_awaited()
        await self.save([{'tag':'#P2Y','weight':149000,'revision':0}])
        self.providers.family_clans.return_value={'clans':[{'tag':'#R2Y','name':'Reclassified','type':'Tactical'}]}
        self.assertEqual((await self.save([{'tag':'#P2Y','weight':150000,'revision':1}])).status,404)
        self.assertEqual(self.app['clan_weight_trial'].all()[0]['weight'],149000)

    async def test_last_save_metadata_is_durable_and_not_changed_by_reads_or_replay(self):
        self.roster()
        initial=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertIsNone(initial['last_saved'])
        item={'tag':'#P2Y','weight':149000,'revision':0}
        saved=await (await self.save([item])).json()
        stamp=saved['last_saved']
        self.assertTrue(stamp['at'])
        self.assertTrue(stamp['name'])
        self.assertFalse(stamp['imported'])
        replay=await (await self.save([item])).json()
        self.assertEqual(replay['last_saved'],stamp)
        self.assertEqual((await self.save([{**item,'weight':150000}])).status,409)
        read=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertEqual(read['last_saved'],stamp)
        persisted=ClanWeightStore(self.app['store'].path)
        self.assertEqual(persisted.last_saved('#R2Y')['updated_at'],stamp['at'])
        self.assertIsNone(persisted.last_saved('#J2Y'))
        # A departed player must not remove the clan's historical save receipt.
        self.roster(members=[])
        read=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertEqual(read['last_saved'],stamp)

    async def test_old_import_receipt_resolves_session_name_without_changing_weights(self):
        self.roster()
        store=self.app['clan_weight_trial']
        roster=await self.providers.clan_roster('#R2Y')
        store.save(roster,[{'tag':'#P2Y','weight':149000,'revision':0}], '100:sheet-test-import')
        result=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertEqual(result['last_saved']['discord_id'],'100')
        self.assertTrue(result['last_saved']['imported'])
        self.assertNotIn('sheet-test-import',result['last_saved']['name'])
        self.assertEqual(result['members'][0]['weight'],149000)
        store.save(roster,[{'tag':'#P2Y','weight':150000,'revision':1}], '100', 'Saved Discord name')
        with self.app['store'].tx() as db:
            db.execute("DELETE FROM sessions WHERE user_id='100'")
        self.assertEqual(store.last_saved('#R2Y')['actor_name'],'Saved Discord name')

    async def test_cached_war_order_keeps_current_members_and_reports_capture_time(self):
        self.roster()
        self.providers.weight_war_lineup = AsyncMock(return_value={
            'order': {'#P2Y': 2, '#Q2Y': 1}, 'state': 'warEnded',
            'end_time': '20261021T070000.000Z', 'opponent': 'Opponent'})
        first = await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertEqual(first['war_order'], {'#P2Y': 2, '#Q2Y': 1})
        self.providers.weight_war_lineup.side_effect = ProviderUnavailable('No current war')
        self.providers.clan_roster.return_value['members'] = [{'tag': '#P2Y', 'name': 'Still here', 'town_hall': 17}]
        cached = await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertTrue(cached['war_source']['cached'])
        self.assertTrue(cached['war_source']['captured_at'])
        self.assertEqual([row['tag'] for row in cached['members']], ['#P2Y'])
        self.assertEqual(cached['war_order'], first['war_order'])
