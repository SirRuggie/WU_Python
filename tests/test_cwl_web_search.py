"""250 read-only search: real isolated HTTP/session/store, fake providers only."""
import asyncio
from copy import deepcopy
import hashlib
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from urllib.parse import parse_qs, urlsplit
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from cwl_web.providers import LiveProviders, ProviderUnavailable
from cwl_web.search import SearchState, RATE_ERROR, search_tag

def not_found():
    error = ProviderUnavailable('synthetic404')
    error.status_code = 404
    return error

class FakeProviders:

    def __init__(self):
        self.links = {'100': ['#P2Y'], '200': ['#Q2Y']}
        self.names = {'#P2Y': 'Fixture A', '#Q2Y': 'Fixture B'}
        self.calls = []
        self.release = None
        self.entered = asyncio.Event()
        self.fail = False

    async def linked_tags(self, user):
        return {key: True for key in self.links.get(str(user), [])}

    async def player(self, value):
        self.calls.append(('player', value))
        if value not in self.names:
            raise not_found()
        return {'tag': value, 'name': self.names[value], 'town_hall': 18, 'current_clan_tag': '#R2Y', 'current_clan_name': 'Fixture family', 'discord_id': 'PRIVATE_ID', 'secret': 'PRIVATE_TOKEN', 'trophies': 3210}

    async def clan(self, value):
        self.calls.append(('clan', value))
        if value == '#P2Y':
            raise not_found()
        return {'tag': value, 'name': 'Public clan', 'level': 20, 'members': 35, 'cwl_league': 'Gold I', 'public_war_log': False, 'badge_url': 'javascript:bad', 'private': 'PRIVATE_TOKEN'}

    async def family_clans(self):
        return {'status': 'ok', 'clans': [{'tag': '#R2Y', 'name': 'Fixture family', 'type': 'Tactical'}]}

    async def search_clans(self, name, limit=10):
        self.calls.append(('search_clans', name, limit))
        self.entered.set()
        if self.release:
            await self.release.wait()
        if self.fail:
            raise ProviderUnavailable('PRIVATE upstream detail')
        return [{'tag': '#C2Y', 'name': 'Fixture public', 'level': 18, 'members': 20, 'war_league': 'Gold I', 'badge_url': None, 'discord_id': 'PRIVATE_ID'}]

class SearchHTTPTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = FakeProviders()
        self.app = create_app(db_path=str(Path(self.tmp.name) / 'fixture.sqlite'), providers=self.providers, secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.a = self.auth('100')
        self.b = self.auth('200')

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def auth(self, user):
        raw = secrets.token_urlsafe(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES(?,?,?,?,?,?)', (hashlib.sha256(raw.encode()).hexdigest(), user, 'Fixture', 0, 'fixture-csrf', int(time.time()) + 3600))
        return {'Cookie': 'cwl_session=' + raw}

    async def get(self, q='fixture', headers=None):
        return await self.client.get('/api/cwl/search', params={'q': q}, headers=headers or self.a)

    def counts(self):
        with self.app['store'].read() as db:
            names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {n: db.execute('SELECT COUNT(*) FROM "' + n + '"').fetchone()[0] for n in names}

    async def test_signed_out_and_member_editor_auth(self):
        self.assertEqual((await self.client.get('/api/cwl/search?q=fixture')).status, 401)
        response = await self.get()
        self.assertEqual(response.status, 200)
        from cwl_web.app import OWNER_IDS
        editor = self.auth(next(iter(OWNER_IDS)))
        response = await self.get(headers=editor)
        self.assertEqual(response.status, 200)

    async def test_public_cache_same_for_two_users_and_no_private_reads(self):
        self.providers.linked_tags = AsyncMock(side_effect=AssertionError('No family lookup in public endpoint'))
        self.providers.family_clans = AsyncMock(side_effect=AssertionError('No directory lookup in public endpoint'))
        a = await (await self.get('fixture')).json()
        b = await (await self.get('  FIXTURE  ', self.b)).json()
        self.assertEqual(a, b)
        self.assertTrue(all((row['source'] == 'clash' for row in a['results'])))
        self.assertNotIn('PRIVATE', str(a))
        self.assertNotIn('#P2Y', [r['tag'] for r in a['results']])
        self.assertEqual(len([c for c in self.providers.calls if c[0] == 'search_clans']), 1)
        self.providers.linked_tags.assert_not_called()
        self.providers.family_clans.assert_not_called()

    async def test_short_name_no_public_search_and_validation(self):
        self.assertEqual((await self.get('')).status, 400)
        self.assertEqual((await self.get('x' * 41)).status, 400)
        await self.get('fi')
        self.assertFalse(any((c[0] == 'search_clans' for c in self.providers.calls)))
        self.assertIsNone(search_tag('#' + 'P' * 13))
        self.assertEqual(search_tag(' poy '), '#P0Y')

    async def test_tag_player_clan_concurrent_and404_skipped(self):
        self.providers.links['100'] = []
        entered = []
        gate = asyncio.Event()

        async def player(value):
            entered.append('player')
            await gate.wait()
            return {'tag': value, 'name': 'Player', 'town_hall': 18}

        async def clan(value):
            entered.append('clan')
            gate.set()
            raise not_found()
        self.providers.player = player
        self.providers.clan = clan
        response = await asyncio.wait_for(self.get('#P2Y'), 1)
        body = await response.json()
        self.assertEqual(set(entered), {'player', 'clan'})
        self.assertEqual([r['kind'] for r in body['results']], ['player'])
        self.assertNotIn('errors', body)

    async def test_upstream_failure_public_errors_and_not_error_cached(self):
        self.providers.fail = True
        body = await (await self.get()).json()
        self.assertEqual(body['results'], [])
        self.assertIn('Clash data is unavailable. Try again.', body['errors'])
        self.providers.fail = False
        body = await (await self.get()).json()
        self.assertNotIn('errors', body)

    async def test_quota_counts_cache_hits_case_spacing_and_details_shared(self):
        for i in range(19):
            self.assertEqual((await self.get(' FIXTURE ' if i % 2 else 'fixture')).status, 200)
        self.assertEqual((await self.client.get('/api/cwl/search/details?kind=player&tag=%23P2Y', headers=self.a)).status, 200)
        response = await self.get('different')
        self.assertEqual(response.status, 429)
        self.assertIn(RATE_ERROR, await response.text())
        self.assertEqual((await self.get(headers=self.b)).status, 200)

    async def test_details_validation_whitelist_not_found(self):
        for path, status in [('/api/cwl/search/details?kind=bad&tag=%23P2Y', 400), ('/api/cwl/search/details?kind=player&tag=bad', 400), ('/api/cwl/search/details?kind=player&tag=%23V2Y', 404), ('/api/cwl/search/details?kind=clan&tag=%23R2Y', 200)]:
            response = await self.client.get(path, headers=self.a)
            self.assertEqual(response.status, status, path)
            if status == 200:
                body = await response.json()
                self.assertIsNone(body['badge_url'])
                self.assertFalse(body['public_war_log'])
                self.assertNotIn('PRIVATE', str(body))

    async def test_concurrent_public_coalescing_same_sanitized_data(self):
        self.providers.release = asyncio.Event()
        a = asyncio.create_task(self.get('fixture'))
        await self.providers.entered.wait()
        b = asyncio.create_task(self.get('fixture', self.b))
        await asyncio.sleep(0)
        self.providers.release.set()
        left, right = await asyncio.gather(a, b)
        self.assertEqual(await left.json(), await right.json())
        self.assertEqual(len([c for c in self.providers.calls if c[0] == 'search_clans']), 1)

    async def test_26_65_125_fixture_counts_and_store_write_denial(self):
        for count in (26, 65, 125):
            with self.subTest(count=count):
                tags = ['#P' + format(i, 'b').replace('1', 'Y').replace('0', '2').rjust(8, '2') for i in range(count)]
                self.providers.links['100'] = tags
                self.providers.names.update({t: 'Fixture ' + str(i) for i, t in enumerate(tags)})
                with self.app['store'].tx() as db:
                    db.execute('INSERT INTO seasons(id,label,status,signup_open) VALUES(?,?,?,1)', (count, str(count) + '-account fixture', 'draft'))
                    db.execute('INSERT OR IGNORE INTO clans(tag,name) VALUES(?,?)', ('#R2Y', 'Synthetic fixture'))
                    for i, value in enumerate(tags):
                        db.execute('INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower) VALUES(?,?,?,?,?,?,0)', (count, value, '100', 'Fixture ' + str(i), 18, 'main' if i % 2 == 0 else 'lazy'))
                        db.execute('INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES(?,?,?,?)', (count, value, '#R2Y' if i % 4 else None, int(i % 4 != 0 and i % 10 == 0)))
                self.providers.calls.clear()
                self.providers.linked_tags = AsyncMock(side_effect=AssertionError('Cold linked accounts must not fan out'))
                self.providers.family_clans = AsyncMock(side_effect=AssertionError('No family directory from public search'))
                before = self.counts()
                with patch.object(self.app['store'], 'tx', side_effect=AssertionError('SEARCH WRITE')), patch.object(self.app['store'], 'run_tx', side_effect=AssertionError('SEARCH WRITE')):
                    response = await self.get()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(all((r['source'] == 'clash' for r in (await response.json())['results'])))
                self.assertEqual(self.counts(), before)
                with self.app['store'].read() as db:
                    rows = [dict(row) for row in db.execute('SELECT s.season_id,s.pool,COUNT(*) signups,SUM(r.assigned_clan_tag IS NOT NULL) assigned,SUM(COALESCE(r.kept,0)) locks FROM signups s LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag WHERE s.season_id=? GROUP BY s.season_id,s.pool ORDER BY s.pool', (count,))]
                self.assertEqual(sum((row['signups'] for row in rows)), count)
                print('SEARCH250_FIXTURE_COUNTS ' + json.dumps({'fixture': count, 'before_after_identical': True, 'sql_tables': len(before), 'pools': rows}))
                self.providers.linked_tags.assert_not_called()
                self.providers.family_clans.assert_not_called()
                self.assertFalse(any((c[0] in ('player', 'clan') for c in self.providers.calls)))

class PureStateTests(unittest.IsolatedAsyncioTestCase):

    async def test_TTL_bounded500_and_hour_quota(self):
        now = [1.0]
        state = SearchState(lambda: now[0])
        calls = []

        async def load():
            calls.append(1)
            return {'results': []}
        await state.public(('q', 'same'), load)
        await state.public(('q', 'same'), load)
        self.assertEqual(len(calls), 1)
        now[0] += 60
        await state.public(('q', 'same'), load)
        self.assertEqual(len(calls), 2)
        for i in range(501):
            await state.public(('q', str(i)), load)
        self.assertEqual(len(state.cache), 500)
        for batch in range(10):
            for _ in range(20):
                state.claim('session')
            now[0] += 61
        from aiohttp import web
        with self.assertRaises(web.HTTPTooManyRequests):
            state.claim('session')

    async def test_coalesced_public_read_survives_one_waiter_cancellation(self):
        state = SearchState()
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def load():
            calls.append(1)
            entered.set()
            await release.wait()
            return {'results': []}
        first = asyncio.create_task(state.public(('q', 'same'), load))
        await entered.wait()
        second = asyncio.create_task(state.public(('q', 'same'), load))
        await asyncio.sleep(0)
        self.assertEqual(len(state.inflight), 1)
        self.assertEqual(len(calls), 1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertEqual(await second, {'results': []})
        self.assertEqual(len(calls), 1)

class ProviderSearchTests(unittest.IsolatedAsyncioTestCase):

    async def test_official_encoded_read_short_limit_and_shape(self):
        provider = LiveProviders(coc_token='fixture', mongo_uri='', routes={})
        provider._clash_json = AsyncMock(return_value={'items': [{'tag': '#C2Y', 'name': 'Fixture & Clan', 'clanLevel': 18, 'members': 20, 'warLeague': {'name': 'Gold'}, 'badgeUrls': {'medium': 'https://api-assets.clashofclans.com/badges/test.png'}}]})
        self.assertEqual(await provider.search_clans('ab'), [])
        provider._clash_json.assert_not_called()
        rows = await provider.search_clans('Fixture & Clan')
        query = parse_qs(urlsplit(provider._clash_json.call_args.args[0]).query)
        self.assertEqual(query, {'name': ['Fixture & Clan'], 'limit': ['10']})
        self.assertEqual(rows[0]['level'], 18)
        provider._clash_json.return_value = {'items': [{'tag': '#C2Y', 'name': 'Bad', 'members': True, 'clanLevel': 18}]}
        with self.assertRaises(ProviderUnavailable):
            await provider.search_clans('fixture')
