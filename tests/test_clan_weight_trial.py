import unittest
from io import BytesIO
from openpyxl import load_workbook
from unittest.mock import AsyncMock
import test_cwl_web_foundation as foundation
from utils.clan_weight_trial_store import ClanWeightTrialStore
from cwl_web.providers import ProviderUnavailable


class WeightTrialTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=foundation.WebFoundationTests.asyncSetUp
    asyncTearDown=foundation.WebFoundationTests.asyncTearDown
    auth=foundation.WebFoundationTests.auth
    call=foundation.WebFoundationTests.call

    def roster(self, clan='#R2Y', members=None):
        self.providers.weight_war_order=AsyncMock(side_effect=ProviderUnavailable('No war'))
        rows=members if members is not None else [{'tag':'#P2Y','name':'=malicious()','town_hall':16},{'tag':'#Q2Y','name':'Second','town_hall':15}]
        self.providers.clan_roster=AsyncMock(return_value={'tag':clan,'name':'Family','members':rows})

    async def save(self,changes,actor=None,clan='%23R2Y'):
        return await self.call('PUT','/weight-trial/clans/'+clan,actor or self.owner,json={'changes':changes})

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
        self.assertEqual(len(self.app['store'].rows('SELECT * FROM clan_weight_trial_history')),1)
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
        self.assertEqual(ClanWeightTrialStore(self.app['store'].path).all()[0]['weight'],149000)
        exported=await self.call('GET','/weight-trial/export.xlsx',self.owner)
        sheet=load_workbook(BytesIO(await exported.read())).active
        self.assertEqual(sheet['B2'].value,'=malicious()')
        self.assertEqual(sheet['B2'].data_type,'s')
        self.assertEqual(sheet['D2'].value,149)
        self.assertEqual(sheet['E2'].value,149000)
        self.providers.family_clans=AsyncMock(return_value={'clans':[{'tag':'#J2Y','name':'Other'}]})
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
        self.assertEqual(ClanWeightTrialStore(self.app['store'].path).all()[0]['storages'],5)
        for changes in ({'storages':True},{'storages':0},{'storages':6},{'weight':149001}):
            self.assertEqual((await self.save([{**item,**changes}])).status,400)
        self.assertEqual((await self.save([{**item,'storages':4}])).status,409)
        self.assertEqual((await self.save([{**item,'storages':4,'revision':1}])).status,200)
        self.assertEqual((await self.save([{**item,'storages':4,'revision':1}])).status,200)
        row=ClanWeightTrialStore(self.app['store'].path).all()[0]
        self.assertEqual(row['storages'],4)
        self.assertEqual(row['revision'],2)

    async def test_war_order_is_optional_and_validated(self):
        from cwl_web.providers import LiveProviders
        provider=LiveProviders()
        provider._league_get=AsyncMock(return_value={'state':'inWar','clan':{'tag':'#R2Y','members':[{'tag':'#P2Y','mapPosition':1}]}})
        self.assertEqual(await provider.weight_war_order('#R2Y'),{'#P2Y':1})
        provider._league_get.return_value['clan']['members'].append({'tag':'#Q2Y','mapPosition':1})
        with self.assertRaises(ProviderUnavailable): await provider.weight_war_order('#R2Y')
        self.roster()
        self.providers.weight_war_order=AsyncMock(side_effect=ProviderUnavailable('Private war'))
        result=await (await self.call('GET','/weight-trial/clans/%23R2Y',self.owner)).json()
        self.assertIsNone(result['war_order'])
        self.assertEqual(len(result['members']),2)
