"""Behavioral checks for cached progress and saved-player correction."""
import asyncio
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_clan_weight_trial as trial
from cwl_web.providers import ProviderUnavailable
from utils.clan_weight_observations import WeightObservations


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = trial.WeightTrialTests.asyncSetUp
    asyncTearDown = trial.WeightTrialTests.asyncTearDown
    auth = trial.WeightTrialTests.auth
    call = trial.WeightTrialTests.call
    roster = trial.WeightTrialTests.roster
    save = trial.WeightTrialTests.save

    async def test_directory_unknown_saved_null_and_failed_snapshot(self):
        self.roster()
        route = '/weight-trial/clans'
        cold = await (await self.call('GET', route, self.owner)).json()
        self.assertIsNone(cold['clans'][0]['missing_count'])
        self.assertEqual(cold['clans'][0]['status'], 'loading')
        self.providers.clan_roster.assert_not_awaited()
        await self.save([{'tag': '#P2Y', 'weight': None, 'revision': 0}])
        fresh = await (await self.call('GET', route, self.owner)).json()
        row = fresh['clans'][0]
        self.assertEqual((row['members_count'], row['weighed_count'], row['missing_count']), (2, 1, 1))
        self.providers.clan_roster = AsyncMock(side_effect=ProviderUnavailable('offline'))
        await self.call('GET', route + '/%23R2Y', self.owner)
        stale = (await (await self.call('GET', route, self.owner)).json())['clans'][0]
        self.assertEqual(stale['status'], 'stale')
        self.assertEqual(stale['membership_checked_at'], row['membership_checked_at'])
        self.assertEqual(stale['missing_count'], 1)
        self.assertEqual(self.providers.clan_roster.await_count, 1)

    async def test_departed_save_existence_permissions_cas_and_provenance(self):
        self.roster()
        route = '/weight-trial/saved-players/%23P2Y'
        body = {'weight': 150000, 'revision': 0}
        self.assertEqual((await self.call('PUT', route, self.owner, json=body)).status, 409)
        self.assertEqual(self.app['clan_weight_trial'].all(), [])
        await self.save([{'tag': '#P2Y', 'weight': 149000, 'revision': 0}])
        self.roster(members=[])
        self.assertEqual((await self.call('PUT', route, self.member, json=body)).status, 403)
        self.assertEqual((await self.call('PUT', route, {'Cookie': self.owner['Cookie']}, json=body)).status, 403)
        self.assertEqual((await self.call('PUT', route, self.owner, json=body)).status, 409)
        body['revision'] = 1
        result = await self.call('PUT', route, self.owner, json=body)
        self.assertEqual(result.status, 200)
        row = (await result.json())['player']
        self.assertEqual((row['last_saved_clan_tag'], row['revision']), ('#R2Y', 2))
        self.assertEqual((await self.call('PUT', route, self.owner, json=body)).status, 200)
        self.assertEqual(len(self.app['store'].rows('SELECT * FROM clan_player_weight_history')), 2)
        self.providers.clan_roster.assert_not_awaited()

    async def test_literal_search_and_unknown_location(self):
        self.roster(members=[{'tag': '#P2Y', 'name': '100%_Hero', 'town_hall': 16}])
        await self.save([{'tag': '#P2Y', 'weight': 149000, 'revision': 0}])
        self.providers.player = AsyncMock(side_effect=ProviderUnavailable('offline'))
        result = await (await self.call('GET', '/weight-trial/saved-players?q=%25_', self.owner)).json()
        self.assertEqual(result['total'], 1)
        self.assertIsNone(result['players'][0]['current_is_family'])
        self.assertEqual(result['players'][0]['current_status'], 'unavailable')
        self.assertEqual(self.app['clan_weight_trial'].search('absent%')['total'], 0)
        self.assertEqual((await self.call('GET', '/weight-trial/saved-players?limit=26', self.owner)).status, 400)
        self.providers.family_clans.side_effect = ProviderUnavailable('directory offline')
        self.assertEqual((await self.call('GET', '/weight-trial/saved-players', self.owner)).status, 200)

    async def test_known_nonfamily_and_outside_count_waits_for_membership(self):
        import test_cwl_web_foundation as foundation
        self.roster()
        await self.save([{'tag': '#P2Y', 'weight': 149000, 'revision': 0}])
        self.providers.player = AsyncMock(return_value={
            'tag': '#P2Y', 'current_clan_tag': '#J2Y', 'current_clan_name': 'Elsewhere'})
        result = await (await self.call('GET', '/weight-trial/saved-players', self.owner)).json()
        self.assertFalse(result['players'][0]['current_is_family'])
        self.assertEqual(result['players'][0]['current_status'], 'current')
        sid = await foundation.WebFoundationTests.season(self)
        route = f'/weight-trial/clans?season_id={sid}'
        current = await (await self.call('GET', route, self.owner)).json()
        self.assertEqual(current['outside_fwa_missing_count'], 0)
        self.providers.clan_roster.side_effect = ProviderUnavailable('offline')
        await self.call('GET', '/weight-trial/clans/%23R2Y', self.owner)
        stale = await (await self.call('GET', route, self.owner)).json()
        self.assertIsNone(stale['outside_fwa_missing_count'])
        self.assertEqual(stale['outside_fwa_status'], 'stale')

    async def test_history_failure_rolls_back_saved_player_and_legacy_unchanged(self):
        self.roster()
        await self.save([{'tag': '#P2Y', 'weight': 149000, 'revision': 0}])
        store = self.app['clan_weight_trial']
        with self.app['store'].tx() as db:
            db.execute("CREATE TRIGGER fail_weight_history BEFORE INSERT ON clan_player_weight_history BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.save_existing('#P2Y', {'weight': 150000, 'revision': 1}, 'owner')
        self.assertEqual(store.all()[0]['weight'], 149000)
        with self.app['store'].tx() as db:
            db.execute('UPDATE clan_player_weights SET weight=149001')
        self.assertEqual(store.save_existing('#P2Y', {'weight': 149001, 'revision': 1}, 'owner')['weight'], 149001)
        with self.assertRaises(ValueError):
            store.save_existing('#P2Y', {'weight': 149002, 'revision': 1}, 'owner')
        self.assertEqual(store.all()[0]['weight'], 149001)


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_coalescing_bounds_failure_and_copy_isolation(self):
        active = maximum = 0
        async def roster(tag):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            await asyncio.sleep(.01)
            active -= 1
            return {'tag': tag, 'members': []}
        provider = SimpleNamespace(clan_roster=AsyncMock(side_effect=roster))
        cache = WeightObservations(provider, limit=3)
        await asyncio.gather(*(cache.refresh_roster('#P2Y', force=True) for _ in range(8)))
        self.assertEqual(provider.clan_roster.await_count, 1)
        await asyncio.gather(*(cache.refresh_roster(str(i)) for i in range(8)))
        self.assertLessEqual(maximum, 3)
        self.assertLessEqual(len(cache._rows), 3)
        snapshot = cache.roster('7')
        snapshot['value']['members'].append({'tag': 'fake'})
        self.assertEqual(cache.roster('7')['value']['members'], [])
