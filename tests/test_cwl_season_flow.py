"""Season carry-forward and signup concurrency contracts, isolated SQLite only."""
import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from cwl_web import create_app
from tests.test_cwl_web_roster import Providers


class SeasonFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(db_path=str(Path(self.tmp.name) / 'fixture.sqlite'), providers=Providers(), secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        raw, csrf = secrets.token_hex(24), secrets.token_hex(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)',
                       (hashlib.sha256(raw.encode()).hexdigest(), '505227988229554179', 'owner', 0, csrf, int(time.time()) + 900))
        self.headers = {'Cookie': 'cwl_session=' + raw, 'X-CSRF-Token': csrf}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def call(self, method, path, body):
        return await self.client.request(method, '/api/cwl' + path, headers=self.headers, json=body)

    async def create(self, label='First season'):
        return await self.call('POST', '/seasons', {'label': label, 'signup_open': False})

    async def seed(self):
        sid = (await (await self.create()).json())['id']
        with self.app['store'].tx() as db:
            for value, archived in [('#P2Y', 0), ('#Q2Y', 1)]:
                db.execute('INSERT INTO clans(tag,name,archived) VALUES (?,?,?)', (value, value, archived))
                db.execute('INSERT INTO lineup(season_id,tag) VALUES (?,?)', (sid, value))
                db.execute('INSERT INTO lineup_rules(season_id,tag,pool,capacity,min_weight,max_weight,lower_league) VALUES (?,?,?,15,150000,180000,1)', (sid, value, 'main'))
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,'#P2Y','100','main',0,'Player',18)", (sid,))
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) VALUES (?,'#P2Y','#P2Y',1,170000)", (sid,))
        return sid

    async def test_first_season_has_no_copied_clans(self):
        response = await self.create()
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())['copied_clan_count'], 0)

    async def test_rules_copied_archived_skipped_and_roster_empty(self):
        sid = await self.seed()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO seasons(label) VALUES ('Newer empty season')")
        response = await self.create('Next season')
        self.assertEqual(response.status, 201)
        data = await response.json()
        self.assertEqual(data['copied_clan_count'], 1)
        store = self.app['store']
        rules = store.rows('SELECT * FROM lineup_rules WHERE season_id=?', (data['id'],))
        self.assertEqual(len(rules), 1)
        self.assertEqual([rules[0][k] for k in ['tag', 'pool', 'capacity', 'min_weight', 'max_weight', 'lower_league']], ['#P2Y', 'main', 15, 150000, 180000, None])
        self.assertEqual(store.rows('SELECT lower_league FROM lineup_rules WHERE season_id=? AND tag=?', (sid, '#P2Y'))[0]['lower_league'], 1)
        for table in ['signups', 'roster_entries', 'roster_publications', 'roster_meta']:
            self.assertEqual(store.rows(f'SELECT * FROM {table} WHERE season_id=?', (data['id'],)), [])

    async def test_copy_failure_rolls_back_season_and_lineup(self):
        await self.seed()
        store = self.app['store']
        before = {table: store.rows(f'SELECT * FROM {table}') for table in ['seasons', 'lineup', 'lineup_rules']}
        with store.tx() as db:
            db.execute("CREATE TRIGGER fail_copy BEFORE INSERT ON lineup_rules WHEN NEW.season_id > 1 BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        response = await self.create('Must roll back')
        self.assertEqual(response.status, 500)
        self.assertIn("Couldn't copy hosting clans; nothing was created.", await response.text())
        self.assertEqual(before, {table: store.rows(f'SELECT * FROM {table}') for table in before})

    async def test_signup_guard_mismatch_is_409_without_any_write(self):
        sid = (await (await self.create()).json())['id']
        store = self.app['store']
        before = {table: store.rows(f'SELECT * FROM {table}') for table in ['seasons', 'roster_meta', 'roster_audit']}
        response = await self.call('PATCH', f'/seasons/{sid}', {'signup_open': True, 'expected_signup_open': True, 'label': 'Must not change'})
        self.assertEqual(response.status, 409)
        self.assertIn('Signups were changed by someone else. Refresh and try again.', await response.text())
        self.assertEqual(before, {table: store.rows(f'SELECT * FROM {table}') for table in before})

    async def test_signup_guard_matches_and_legacy_calls_still_work(self):
        sid = (await (await self.create()).json())['id']
        for body in [{'signup_open': True, 'expected_signup_open': False}, {'signup_open': False, 'expected_signup_open': True}, {'signup_open': True}]:
            response = await self.call('PATCH', f'/seasons/{sid}', body)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['signup_open'], body['signup_open'])

    async def test_signup_guard_rejects_non_bool(self):
        sid = (await (await self.create()).json())['id']
        for value in [0, 1, None, 'false', [], {}]:
            response = await self.call('PATCH', f'/seasons/{sid}', {'signup_open': True, 'expected_signup_open': value})
            self.assertEqual(response.status, 400)

    async def test_label_status_only_unchanged(self):
        sid = (await (await self.create()).json())['id']
        response = await self.call('PATCH', f'/seasons/{sid}', {'label': 'Renamed season', 'status': 'archived'})
        self.assertEqual(response.status, 200)
        row = await response.json()
        self.assertEqual((row['label'], row['status'], row['signup_open']), ('Renamed season', 'archived', False))

    async def test_clan_lookup_has_no_database_writes(self):
        from unittest.mock import AsyncMock
        provider = self.app['providers']
        provider.clan = AsyncMock(return_value={'tag': '#P2Y', 'name': 'Preview clan', 'extra': 'not returned'})
        with self.app['store'].tx() as db:
            before = list(db.iterdump())
        response = await self.call('GET', '/clans/lookup?tag=%23P2Y', None)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'tag': '#P2Y', 'name': 'Preview clan'})
        provider.clan.assert_awaited_once_with('#P2Y')
        with self.app['store'].tx() as db:
            self.assertEqual(before, list(db.iterdump()))

    async def test_clan_lookup_invalid_not_found_unavailable_and_unauthorized(self):
        from unittest.mock import AsyncMock
        from cwl_web.providers import ProviderUnavailable
        response = await self.call('GET', '/clans/lookup?tag=invalid', None)
        self.assertEqual(response.status, 400)
        error = ProviderUnavailable('Missing')
        error.status_code = 404
        self.app['providers'].clan = AsyncMock(side_effect=error)
        response = await self.call('GET', '/clans/lookup?tag=%23P2Y', None)
        self.assertEqual(response.status, 404)
        self.app['providers'].clan = AsyncMock(side_effect=ProviderUnavailable('Outage'))
        response = await self.call('GET', '/clans/lookup?tag=%23P2Y', None)
        self.assertEqual(response.status, 503)
        self.client.session.cookie_jar.clear()
        response = await self.client.get('/api/cwl/clans/lookup?tag=%23P2Y')
        self.assertEqual(response.status, 401)

    async def test_duplicate_season_remains_409(self):
        await self.create()
        response = await self.create()
        self.assertEqual(response.status, 409)
        self.assertIn('Season already exists', await response.text())

    async def test_lookup_requires_settings_permission_like_add(self):
        from unittest.mock import AsyncMock
        provider = self.app['providers']
        provider.clan = AsyncMock(return_value={'tag': '#P2Y', 'name': 'Preview'})
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)',
                       ('200', '505227988229554179', '["cwl_roster"]'))
            db.execute("UPDATE sessions SET user_id='200'")
        response = await self.call('GET', '/clans/lookup?tag=%23P2Y', None)
        self.assertEqual(response.status, 403)
        provider.clan.assert_not_awaited()
