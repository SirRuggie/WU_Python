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
from utils.clan_activity import war_detail, war_identity


def war(clan='#P2Y', opponent='#Q2Y'):
    one = NS(tag='#P8Y', name='One', map_position=1, town_hall=16,
             attacks=[NS(defender_tag='#Q8Y', stars=2, destruction=79.3, order=2, duration=123)])
    two = NS(tag='#Q8Y', name='Two', map_position=1, town_hall=16,
             attacks=[NS(defender_tag='#P8Y', stars=3, destruction=100, order=1, duration=111)])
    return NS(state=NS(value='inWar'), clan=NS(tag=clan, name='Us', members=[one], stars=2,
              destruction=79.3, attacks_used=1), opponent=NS(tag=opponent, name='Them',
              members=[two], stars=3, destruction=100, attacks_used=1),
              team_size=1, attacks_per_member=2,
              start_time=NS(time=datetime(2026, 10, 26, tzinfo=timezone.utc)),
              end_time=NS(time=datetime(2026, 10, 27, tzinfo=timezone.utc)))


class Projection(unittest.TestCase):
    def test_reverse_side_linked_scope_and_order(self):
        obj = war()
        result = war_detail('war', obj, '#Q2Y', linked_tags=['#Q8Y', '#P8Y'])
        self.assertEqual(result['lineup']['clan'][0]['tag'], '#Q8Y')
        self.assertTrue(result['lineup']['clan'][0]['linked'])
        self.assertEqual([a['order'] for a in result['attacks']], [1, 2])
        self.assertEqual([a['linked'] for a in result['attacks']], [True, False])
        self.assertFalse(result['lineup']['opponent'][0]['linked'])
        self.assertEqual(result['war_id'], war_identity(obj, '#Q2Y'))
        self.assertNotEqual(result['war_id'], war_identity(war(opponent='#R2Y'), '#P2Y'))
        obj.start_time = None
        obj.end_time = None
        self.assertIsNone(war_identity(obj, '#P2Y'))

    def test_cwl_limit_and_partial_attacks(self):
        obj = war()
        obj.attacks_per_member = None
        obj.clan.members[0].attacks[0].defender_tag = None
        result = war_detail('war', obj, '#P2Y', league=True)
        self.assertEqual(result['attacks_per_member'], 1)
        self.assertFalse(result['attacks_complete'])
        self.assertIsNone(result['attacks'][1]['defender_tag'])

    def test_invalid_attack_stats_are_unknown_and_partial(self):
        obj = war()
        obj.clan.members[0].attacks[0].stars = 99
        obj.clan.members[0].attacks[0].destruction = 700
        obj.clan.members[0].attacks[0].order = 1.5
        result = war_detail('war', obj, '#P2Y')
        self.assertFalse(result['attacks_complete'])
        self.assertIsNone(result['attacks'][-1]['stars'])
        self.assertIsNone(result['attacks'][-1]['destruction'])
        self.assertIsNone(result['attacks'][-1]['order'])

    def test_unreasonable_arrays_are_capped_and_partial(self):
        obj = war()
        extra = obj.clan.members[0].attacks[0]
        obj.clan.members[0].attacks = [extra] * 1000
        obj.clan.members = obj.clan.members * 1000
        result = war_detail('war', obj, '#P2Y')
        self.assertEqual(len(result['lineup']['clan']), 100)
        self.assertEqual(len(result['attacks']), 401)
        self.assertFalse(result['lineup_complete'])
        self.assertFalse(result['attacks_complete'])

    def test_mismatched_attacker_never_claims_ownership(self):
        obj = war()
        obj.opponent.members[0].attacks[0].order = 2
        obj.clan.members[0].attacks[0].attacker_tag = '#P8Y'
        obj.clan.members[0].tag = '#U8Y'
        result = war_detail('war', obj, '#P2Y', linked_tags=['#P8Y'])
        self.assertFalse(result['attacks_complete'])
        self.assertFalse(result['attacks'][0]['linked'])

    def test_unknown_attacks_stays_unknown(self):
        obj = war()
        obj.clan.members[0].attacks = None
        result = war_detail('war', obj, '#P2Y', linked_tags=None)
        self.assertIsNone(result['lineup']['clan'][0]['attacks_used'])
        self.assertIsNone(result['lineup']['clan'][0]['linked'])
        self.assertEqual(len(result['attacks']), 1)


class Endpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.obj = war()
        self.providers = NS(linked_tags=AsyncMock(return_value={'#P8Y': True}),
                            family_clans=AsyncMock(return_value={'clans': [{'tag': '#P2Y', 'name': 'Us'}]}))
        self.app = create_app(db_path=str(Path(self.tmp.name) / 'web.sqlite'),
                              providers=self.providers, secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.app['todo_client'] = NS(close=AsyncMock())
        self.accounts = patch('utils.todo_data.fetch_accounts', new=AsyncMock(return_value=([
            NS(tag='#P8Y', name='One', clan_tag='#P2Y', clan_name='Us')], [])))
        self.accounts_mock = self.accounts.start()
        self.fetch = patch('utils.todo_data.fetch_current_war',
                           new=AsyncMock(return_value=('war', self.obj)))
        self.fetch_mock = self.fetch.start()

    async def asyncTearDown(self):
        await self.client.close()
        self.fetch.stop()
        self.accounts.stop()
        self.tmp.cleanup()

    def auth(self, user='100'):
        token = secrets.token_urlsafe(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user, user, 0, 'csrf', int(time.time()) + 900))
        return {'Cookie': 'cwl_session=' + token}

    def url(self, **changes):
        values = {'scope': 'mine', 'kind': 'regular', 'clan_tag': '#P2Y',
                  'war_id': war_identity(self.obj, '#P2Y')}
        values.update(changes)
        from urllib.parse import urlencode
        return '/api/cwl/war-detail?' + urlencode(values)

    async def test_auth_and_no_arbitrary_clan(self):
        self.assertEqual((await self.client.get(self.url())).status, 401)
        headers = self.auth()
        self.assertEqual((await self.client.get(self.url(scope='family'), headers=headers)).status, 403)
        self.assertEqual((await self.client.get(self.url(clan_tag='#Q2Y'), headers=headers)).status, 403)
        self.assertEqual((await self.client.get(self.url(war_id='bad'), headers=headers)).status, 400)
        self.assertEqual(self.fetch_mock.await_count, 0)

    async def test_detail_and_stale_war(self):
        headers = self.auth()
        response = await self.client.get(self.url(), headers=headers)
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload['attacks'][1]['attacker_tag'], '#P8Y')
        self.assertTrue(payload['attacks'][1]['linked'])
        self.fetch_mock.return_value = ('war', war(opponent='#R2Y'))
        self.assertEqual((await self.client.get(self.url(), headers=headers)).status, 409)

    async def test_recent_clan_cannot_open_regular(self):
        self.accounts_mock.return_value = ([NS(tag='#P8Y', name='One',
                                               clan_tag='#R2Y', clan_name='Elsewhere')], [])
        self.assertEqual((await self.client.get(self.url(), headers=self.auth())).status, 403)

    async def test_recent_cwl_requires_candidate_and_actual_member(self):
        from utils.clan_history import ClanCandidate
        self.accounts_mock.return_value = ([NS(tag='#P8Y', name='One',
                                               clan_tag='#R2Y', clan_name='Elsewhere')], [])
        self.fetch_mock.return_value = ('war', self.obj)
        with patch('cwl_web.war_detail.load_recent_clans',
                   new=AsyncMock(return_value=({'#P8Y': [ClanCandidate('#P2Y')]}, ''))):
            response = await self.client.get(self.url(kind='cwl'), headers=self.auth())
            self.assertEqual(response.status, 200)
            self.obj.clan.members[0].tag = '#U8Y'
            response = await self.client.get(self.url(kind='cwl'), headers=self.auth())
            self.assertEqual(response.status, 403)

    async def test_family_directory_and_unknown_link_highlights(self):
        headers = self.auth('505227988229554179')
        self.providers.linked_tags.side_effect = RuntimeError('offline')
        response = await self.client.get(self.url(scope='family'), headers=headers)
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertIsNone(payload['lineup']['clan'][0]['linked'])
        self.assertTrue(payload['warnings'])
        self.providers.family_clans.return_value = {'clans': []}
        response = await self.client.get(self.url(scope='family'), headers=headers)
        self.assertEqual(response.status, 403)

    async def test_unavailable_data_is_never_an_empty_log(self):
        headers = self.auth()
        self.fetch_mock.return_value = ('private', None)
        response = await self.client.get(self.url(), headers=headers)
        self.assertEqual(response.status, 409)
        self.fetch_mock.return_value = ('error', None)
        response = await self.client.get(self.url(), headers=headers)
        self.assertEqual(response.status, 503)
        self.accounts_mock.return_value = ([], ['offline'])
        response = await self.client.get(self.url(), headers=headers)
        self.assertEqual(response.status, 503)
