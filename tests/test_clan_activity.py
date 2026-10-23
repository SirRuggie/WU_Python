import asyncio
import hashlib
import secrets
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from utils.clan_activity import war_summary, raid_summary
from utils import todo_data


class Projections(unittest.TestCase):
    def war(self):
        side = lambda tag: NS(tag=tag,name=tag,stars=100,destruction=80.5,attacks_used=45)
        return NS(state=NS(value='inWar'),clan=side('#ONE'),opponent=side('#TWO'),team_size=50,
                  attacks_per_member=2,start_time=NS(time=datetime(2026,10,21)),end_time=NS(time=datetime(2026,10,22)))

    def test_full_clan_counts_and_reverse_cwl_side(self):
        war=self.war()
        war.opponent.stars=120
        result=war_summary('war',war,'#TWO',now=0)
        self.assertEqual(result['clan']['stars'],120)
        self.assertEqual(result['opponent']['tag'],'#ONE')
        self.assertEqual(result['attacks_total'],100)
        self.assertEqual(result['starts_at'],int(datetime(2026,10,21,tzinfo=timezone.utc).timestamp()))

    def test_unknown_and_private_are_not_zero_scores(self):
        self.assertEqual(war_summary('private',None,'#ONE'),{'state':'private'})
        self.assertEqual(war_summary('error',None,'#ONE'),{'state':'error'})
        self.assertEqual(war_summary('war',self.war(),'#OTHER'),{'state':'error'})
        war=self.war();war.clan.stars=None
        self.assertIsNone(war_summary('war',war,'#ONE',now=0)['clan']['stars'])

    def test_expired_live_war_waits_for_result(self):
        self.assertEqual(war_summary('war',self.war(),'#ONE',now=9999999999)['state'],'awaitingResult')
        self.assertEqual(raid_summary('not_started',None),{'state':'not_started'})


class ActivityEndpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.providers=NS(linked_tags=AsyncMock(side_effect=lambda user:{'#PLAYER'+user:True}),
                          family_clans=AsyncMock(return_value={'clans':[{'tag':'#FAMILY','name':'Family'}]}))
        self.app=create_app(db_path=str(Path(self.tmp.name)/'web.sqlite'),providers=self.providers,secure_cookies=False)
        self.client=TestClient(TestServer(self.app));await self.client.start_server()
        self.app['todo_client']=NS(close=AsyncMock())
        async def accounts(client,tags):
            return [NS(clan_tag=tags[0],clan_name='Personal clan')],[]
        self.accounts=patch('utils.todo_data.fetch_accounts',new=AsyncMock(side_effect=accounts));self.accounts.start()
        self.fetch=patch('utils.todo_data.fetch_clan_overview',new=AsyncMock(return_value={'regular':{'state':'none'},'cwl':{'state':'private'}}));self.overview=self.fetch.start()

    async def asyncTearDown(self):
        await self.client.close();self.accounts.stop();self.fetch.stop();self.tmp.cleanup()

    def auth(self,user,owner=False):
        token=secrets.token_urlsafe(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),user,user,int(owner),'csrf',int(time.time())+900))
        return {'Cookie':'cwl_session='+token}

    async def test_auth_scope_and_no_arbitrary_clan_access(self):
        response=await self.client.get('/api/cwl/clan-activity');self.assertEqual(response.status,401)
        headers=self.auth('100')
        response=await self.client.get('/api/cwl/clan-activity?scope=family',headers=headers);self.assertEqual(response.status,403)
        response=await self.client.get('/api/cwl/clan-activity?scope=invalid',headers=headers);self.assertEqual(response.status,400)
        response=await self.client.get('/api/cwl/clan-activity?tag=%23OTHER',headers=headers)
        self.assertEqual((await response.json())['clans'][0]['tag'],'#PLAYER100')
        self.providers.family_clans.assert_not_awaited()

    async def test_users_have_separate_cached_snapshots(self):
        for user in ('100','200'):
            response=await self.client.get('/api/cwl/clan-activity',headers=self.auth(user))
            self.assertEqual((await response.json())['clans'][0]['tag'],'#PLAYER'+user)

    async def test_parallel_reads_coalesce_and_recheck_permission(self):
        headers=self.auth('100')
        results=await asyncio.gather(*(self.client.get('/api/cwl/clan-activity',headers=headers) for _ in range(3)))
        self.assertTrue(all(result.status==200 for result in results));self.assertEqual(self.overview.await_count,1)
        response=await self.client.get('/api/cwl/clan-activity?scope=family',headers=headers)
        self.assertEqual(response.status,403)

    async def test_discord_guild_owner_does_not_grant_dashboard_access(self):
        response = await self.client.get(
            '/api/cwl/clan-activity?scope=family', headers=self.auth('100', True))
        self.assertEqual(response.status, 403)
        self.providers.family_clans.assert_not_awaited()

    async def test_directory_failure_is_not_an_empty_family(self):
        self.providers.family_clans.side_effect=__import__('cwl_web.providers',fromlist=['ProviderUnavailable']).ProviderUnavailable('offline')
        response=await self.client.get('/api/cwl/clan-activity?scope=family',headers=self.auth('505227988229554179'))
        self.assertEqual(response.status,503)
        self.assertFalse(self.app['clan_activity_cache'])

class SharedReads(unittest.IsolatedAsyncioTestCase):
    async def test_one_failed_read_keeps_other_war_status(self):
        with patch('utils.todo_data._get_war',new=AsyncMock(side_effect=TimeoutError())), patch('utils.todo_data._get_cwl_round',new=AsyncMock(return_value=('none',None))):
            result=await todo_data.fetch_clan_overview(object(),'#ONE','war')
        self.assertEqual(result,{'regular':{'state':'error'},'cwl':{'state':'none'}})
