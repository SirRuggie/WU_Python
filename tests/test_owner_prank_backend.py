"""Owner prank HTTP and storage contract, with fixture identities and fake Discord."""

import asyncio
import hashlib
import os
import re
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web import owner_prank
from cwl_web.store import Store
from utils.owner_prank_store import read


NOTIFY = '111111111111111111'
TARGET = '222222222222222222'
STAFF = '333333333333333333'


class OwnerPrankTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = patch.dict(os.environ, {
            'PRANK_ENABLED': 'true', 'PRANK_NOTIFY_USER_ID': NOTIFY,
            'PRANK_TARGET_USER_ID': TARGET,
        })
        self.owners = patch.object(owner_prank, 'OWNER_IDS', {NOTIFY, TARGET})
        self.config.start()
        self.owners.start()
        self.app = create_app(db_path=str(Path(self.tmp.name) / 'prank.sqlite'), secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.client_closed = False
        self.headers = {uid: self.auth(uid) for uid in (NOTIFY, TARGET, STAFF)}
        self.messages = []
        self.fail_delivery = False

        async def fake_discord(request, method, path, **kwargs):
            if self.fail_delivery:
                raise RuntimeError('fixture Discord outage')
            if path == '/users/@me/channels':
                self.assertEqual(kwargs['json'], {'recipient_id': NOTIFY})
                return {'id': 'fixture-dm'}
            self.assertEqual(path, '/channels/fixture-dm/messages')
            self.messages.append(kwargs['json']['content'])
            return {'id': str(len(self.messages))}

        self.transport = patch.object(owner_prank, 'discord', fake_discord)
        self.transport.start()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO seasons(label) VALUES ('Fixture season')")
            sid = db.execute('SELECT id FROM seasons').fetchone()[0]
            db.execute('UPDATE member_season SET season_id=? WHERE id=1', (sid,))
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,?,?,?,?,?)",
                       (sid, '#P2Y', STAFF, 'main', 0, 'Fixture', 18))
        self.signup_before = self.app['store'].rows('SELECT * FROM signups')
        with self.app['store'].tx() as db:
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER prank_test_block_{operation.lower()} BEFORE {operation} ON signups "
                           "BEGIN SELECT RAISE(ABORT, 'prank cannot mutate signups'); END")

    async def asyncTearDown(self):
        self.transport.stop()
        if not self.client_closed:
            await self.client.close()
        self.owners.stop()
        self.config.stop()
        self.tmp.cleanup()

    def auth(self, uid):
        raw, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)',
                       (hashlib.sha256(raw.encode()).hexdigest(), uid, uid, 0, csrf,
                        int(time.time()) + 900))
        return {'Cookie': 'cwl_session=' + raw, 'X-CSRF-Token': csrf}

    async def call(self, method, path, uid=TARGET, *, body=None, headers=None):
        return await self.client.request(method, '/api/cwl/prank' + path,
                                         headers=headers if headers is not None else self.headers[uid],
                                         json=body)

    async def post(self, event, card, *, run=1, uid=TARGET, branch=None):
        body = {'event': event, 'card': card, 'run': run}
        if branch is not None:
            body['branch'] = branch
        return await self.call('POST', '/event', uid, body=body)

    async def delivery_idle(self):
        while self.app[owner_prank.TASKS_KEY]:
            await asyncio.gather(*tuple(self.app[owner_prank.TASKS_KEY]))

    async def test_guard_config_csrf_assets_and_readonly_count(self):
        state = await self.call('GET', '/state')
        self.assertEqual(state.status, 200)
        data = await state.json()
        self.assertEqual(data['signup_count'], 1)
        self.assertEqual(data['card'], 1)
        self.assertEqual(self.app['store'].rows('SELECT * FROM owner_prank_state'), [])
        for path in ('/state', '/assets/78096.webp', '/assets/ASSETS.md',
                     '/assets/%2e%2e%2fsecret'):
            response = await self.call('GET', path, STAFF)
            self.assertEqual(response.status, 404)
        self.assertEqual((await self.call('GET', '/state', headers={})).status, 404)
        self.assertEqual((await self.call('POST', '/event', body={'event': 'prank_opened', 'card': 1, 'run': 1},
                                          headers={'Cookie': self.headers[TARGET]['Cookie']})).status, 403)
        with patch.dict(os.environ, {'PRANK_ENABLED': 'false'}):
            self.assertEqual((await self.call('GET', '/state')).status, 404)
        with patch.dict(os.environ, {'PRANK_TARGET_USER_ID': NOTIFY}):
            self.assertEqual((await self.call('GET', '/state')).status, 404)
        asset_dir = Path(self.tmp.name) / 'assets'
        asset_dir.mkdir()
        (asset_dir / '78096.webp').write_bytes(b'RIFFfixtureWEBP')
        (asset_dir / '97724.webp').write_bytes(b'RIFFrejectedWEBP')
        (asset_dir / '79701.webp').write_bytes(b'RIFFrejectedWEBP')
        (asset_dir / 'ASSETS.md').write_text('not public')
        with patch.object(owner_prank, 'ASSETS', asset_dir):
            self.assertEqual((await self.call('GET', '/assets/78096.webp')).status, 200)
            self.assertEqual((await self.call('GET', '/assets/ASSETS.md')).status, 404)
            for rejected in ('97724.webp', '79701.webp'):
                self.assertEqual((await self.call('GET', '/assets/' + rejected)).status, 404)
        self.assertEqual(self.signup_before, self.app['store'].rows('SELECT * FROM signups'))

    async def test_full_flow_dedup_replay_and_stale_run(self):
        self.assertEqual((await self.post('prank_opened', 1)).status, 200)
        self.assertEqual((await self.post('prank_bait_no', 1)).status, 200)
        self.assertEqual((await self.post('prank_bait_yes', 1)).status, 400)
        self.assertEqual((await self.post('prank_card_seen', 2)).status, 200)
        self.assertEqual((await self.post('prank_closed_early', 2)).status, 200)
        self.assertEqual((await self.post('prank_closed_early', 2)).status, 200)
        self.assertEqual((await self.call('GET', '/state')).status, 200)
        self.assertEqual(read(self.app['store'], TARGET)['card'], 2)
        for card in range(3, 16):
            self.assertEqual((await self.post('prank_card_seen', card)).status, 200)
            milestone = {3: 'prank_jumpscare_seen', 10: 'prank_rickroll_seen',
                         11: 'prank_encore_1', 12: 'prank_encore_2',
                         13: 'prank_encore_3', 14: 'prank_encore_4',
                         15: 'prank_completed'}.get(card)
            if milestone:
                self.assertEqual((await self.post(milestone, card)).status, 200)
                self.assertEqual((await self.post(milestone, card)).status, 200)
        await self.delivery_idle()
        self.assertEqual(len(self.messages), 10)
        self.assertEqual((await self.post('prank_replay', 15)).status, 400)
        self.assertEqual((await self.call('GET', '/state')).status, 200)
        self.assertEqual(self.signup_before, self.app['store'].rows('SELECT * FROM signups'))

        self.assertEqual((await self.post('prank_opened', 1, uid=NOTIFY)).status, 200)
        self.assertEqual((await self.post('prank_bait_yes', 1, uid=NOTIFY)).status, 200)
        for card in range(2, 16):
            self.assertEqual((await self.post('prank_card_seen', card, uid=NOTIFY)).status, 200)
        self.assertEqual((await self.post('prank_completed', 15, uid=NOTIFY)).status, 200)
        replay = await self.post('prank_replay', 15, uid=NOTIFY)
        self.assertEqual(replay.status, 200)
        self.assertEqual((await replay.json())['run'], 2)
        self.assertEqual((await self.post('prank_opened', 1, uid=NOTIFY)).status, 409)
        self.assertEqual((await self.post('prank_opened', 1, run=2, uid=NOTIFY)).status, 200)
        await self.delivery_idle()
        self.assertEqual(sum(message.startswith('[TEST] 😈') for message in self.messages), 2)

    async def test_claim_survives_delivery_failure_and_concurrent_duplicate(self):
        self.fail_delivery = True
        self.assertEqual((await self.post('prank_opened', 1)).status, 200)
        await self.delivery_idle()
        self.fail_delivery = False
        results = await asyncio.gather(*[self.post('prank_opened', 1) for _ in range(4)])
        self.assertTrue(all(result.status == 200 for result in results))
        self.assertEqual(self.messages, [])
        self.assertEqual(len(read(self.app['store'], TARGET)['notified'].split('prank_opened')) - 1, 1)
        results = await asyncio.gather(*[self.post('prank_bait_yes', 1) for _ in range(8)])
        self.assertTrue(all(result.status == 200 for result in results))
        await self.delivery_idle()
        self.assertEqual(len(self.messages), 1)
        reopened = Store(self.app['store'].path)
        self.assertEqual(read(reopened, TARGET)['branch'], 'yes')
        self.assertEqual((await self.post('prank_bait_yes', 1)).status, 200)
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.signup_before, self.app['store'].rows('SELECT * FROM signups'))

    async def test_malformed_event_shapes_return_400_without_writes(self):
        cases = [
            {'event': [], 'card': 1, 'run': 1},
            {'event': {}, 'card': 1, 'run': 1},
            {'event': None, 'card': 1, 'run': 1},
            {'event': 'prank_bait_yes', 'card': 1, 'run': 1, 'branch': []},
            {'event': 'prank_bait_yes', 'card': 1, 'run': 1, 'branch': {}},
            {'event': 'prank_opened', 'card': [1], 'run': 1},
            {'event': 'prank_opened', 'card': 1, 'run': {}},
        ]
        for body in cases:
            with self.subTest(body=body):
                response = await self.call('POST', '/event', body=body)
                self.assertEqual(response.status, 400)
        self.assertEqual(self.app['store'].rows('SELECT * FROM owner_prank_state'), [])
        self.assertEqual(self.messages, [])

    async def test_hanging_discord_does_not_hold_post_and_shutdown_cancels(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()

        async def hanging_discord(request, method, path, **kwargs):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return {'id': 'fixture-dm'}

        with patch.object(owner_prank, 'discord', hanging_discord):
            response = await asyncio.wait_for(self.post('prank_opened', 1), timeout=0.5)
            self.assertEqual(response.status, 200)
            await asyncio.wait_for(started.wait(), timeout=0.5)
            self.assertEqual(len(self.app[owner_prank.TASKS_KEY]), 1)
            self.assertIn('prank_opened', read(self.app['store'], TARGET)['notified'])
            await asyncio.wait_for(self.client.close(), timeout=0.5)
            self.client_closed = True
            await asyncio.wait_for(cancelled.wait(), timeout=0.5)
        self.assertEqual(self.messages, [])

    async def test_early_close_title_punctuation(self):
        for card, title in ((1, 'Remove all signups'), (2, 'Working'),
                            (3, 'HEY!! WHAT ARE YOU DOING?!'), (11, 'LOL. You Thought'),
                            (14, 'One Last Thing, Chief'), (15, 'Well, Look Who Survived')):
            with self.app['store'].tx() as db:
                db.execute('INSERT INTO owner_prank_state(user_id,card,branch) VALUES (?,?,?) '
                           'ON CONFLICT(user_id) DO UPDATE SET card=excluded.card, '
                           'branch=excluded.branch',
                           (TARGET, card, 'yes' if card >= 2 else None))
            self.assertEqual((await self.post('prank_closed_early', card)).status, 200)
            await self.delivery_idle()
            self.assertIn(f'at card {card}: {title}. He couldn\'t', self.messages[-1])

    def test_python_titles_match_frontend_model(self):
        model = Path(__file__).resolve().parents[1] / 'web/cwl/src/ownerPrank/model.ts'
        titles = re.findall(r'^\s*title:\s*"([^"]+)",', model.read_text(), re.MULTILINE)
        self.assertEqual(len(titles), 16)
        self.assertEqual(titles[2], titles[3])  # Card 3 has Yes and No variants.
        self.assertEqual(tuple(titles[:2] + titles[3:]), owner_prank.TITLES[1:])

    def test_frontend_art_matches_owner_only_allowlist_and_files(self):
        model = Path(__file__).resolve().parents[1] / 'web/cwl/src/ownerPrank/model.ts'
        references = re.findall(r'\bart:\s*asset\("([^"]+)"\)', model.read_text())
        self.assertEqual(len(references), 14)  # Both card 3 branches reference the Wizard.
        used_files = {f'{name}.webp' for name in references}
        shipped_files = {path.name for path in owner_prank.ASSETS.glob('*.webp')}
        self.assertEqual(used_files, owner_prank.ASSET_NAMES)
        self.assertEqual(shipped_files, used_files)
