"""Delivery tests use local SQLite and fake Discord exclusively."""
import io
import json
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import web
from PIL import Image
from test_cwl_roster_images import RosterImageTests
from cwl_web.store import Store


class ImagePostTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RosterImageTests.asyncSetUp
    asyncTearDown = RosterImageTests.asyncTearDown
    auth = RosterImageTests.auth
    call = RosterImageTests.call
    signup = RosterImageTests.signup
    revision = RosterImageTests.revision
    host = RosterImageTests.host
    publish = RosterImageTests.publish

    async def setup_post(self):
        await self.publish()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO roster_image_channels(pool,channel_id,channel_name,configured_by) VALUES('main','123456789012345678','rosters','owner')")
        self.path = f'/seasons/{self.sid}/roster-image-posts/%23C2Y'
        self.body = {'pool': 'main', 'version': 1, 'request_id': 'a' * 24}
        self.sent = []
        self.mode = None

        async def fake(request, method, path, **kwargs):
            self.assertNotEqual(method, 'DELETE')
            if method == 'GET':
                return {'guild_id': '644963518025826315', 'type': 0}
            self.sent.append((method, path, kwargs))
            if self.mode == 'timeout':
                raise TimeoutError('accepted then timed out')
            if self.mode == '404':
                raise web.HTTPNotFound()
            if self.mode == '429':
                raise web.HTTPTooManyRequests(text=json.dumps({'retry_after': 0.01}), content_type='application/json')
            return {'id': '987654321098765432'}
        self.fake = fake

    async def republish(self, drop=False):
        with self.app['store'].tx() as db:
            if drop:
                db.execute('UPDATE roster_entries SET assigned_clan_tag=NULL WHERE season_id=?', (self.sid,))
            else:
                db.execute("UPDATE signups SET player_name='New name' WHERE season_id=?", (self.sid,))
        response = await self.call('POST', f'/seasons/{self.sid}/publication', self.owner, json={'revision': await self.revision(), 'acknowledge_unassigned': True, 'joining_instructions': ''})
        self.assertEqual(response.status, 201)
        self.body = self.body | {'version': 2, 'request_id': 'b' * 24}

    async def send(self, op=''):
        return await self.call('POST', self.path + op, self.owner, json=self.body)

    async def test_post_replay_conflicts_and_version_guards(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.assertEqual((await self.send()).status, 200)
            self.assertEqual((await self.send()).status, 200)
            self.assertEqual(len(self.sent), 1)
            self.body = self.body | {'version': 2, 'request_id': 'b' * 24}
            self.assertEqual((await self.send()).status, 409)
            with self.app['store'].tx() as db:
                db.execute("UPDATE roster_image_posts SET status='sending'")
            self.body = self.body | {'version': 1}
            self.assertEqual((await self.send()).status, 409)
        payload = json.loads(self.sent[0][2]['data']._fields[0][2])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertTrue(payload['enforce_nonce'])

    async def test_uncertain_new_post_requires_new_request_and_can_post_again(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.mode = 'timeout'
            self.assertEqual((await self.send()).status, 503)
            self.mode = None
            self.assertEqual((await self.send()).status, 503)
            self.assertEqual(len(self.sent), 1)
            self.body['request_id'] = 'c' * 24
            self.assertEqual((await self.send()).status, 200)
            self.assertEqual([s[0] for s in self.sent], ['POST', 'POST'])

    async def test_uncertain_update_restart_renders_identical_pixels_and_patches_same_id(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
            await self.republish()
            self.mode = 'timeout'
            self.assertEqual((await self.send('/update')).status, 503)
            first = self.sent[-1]
            self.app['store'] = Store(self.app['store'].path)
            self.mode = None
            self.body['request_id'] = 'c' * 24
            with patch('cwl_web.roster_images.metadata', AsyncMock(side_effect=AssertionError('must use frozen metadata'))):
                self.assertEqual((await self.send('/update')).status, 200)
            second = self.sent[-1]
            self.assertEqual(first[:2], second[:2])
            self.assertEqual(first[0], 'PATCH')
            self.assertTrue(first[1].endswith('/987654321098765432'))
            fields1, fields2 = first[2]['data']._fields, second[2]['data']._fields
            self.assertEqual(json.loads(fields1[0][2]), json.loads(fields2[0][2]))
            for a, b in zip(fields1[1:], fields2[1:]):
                self.assertEqual(Image.open(io.BytesIO(a[2])).tobytes(), Image.open(io.BytesIO(b[2])).tobytes())
            self.assertEqual(len(fields1), len(fields2))
            with self.app['store'].tx() as db:
                receipt = db.execute("SELECT payload_json FROM roster_image_requests WHERE request_id=?", ('c'*24,)).fetchone()[0]
                self.assertNotIn('base64', receipt)
                self.assertLess(len(receipt), 3000)

    async def test_uncertain_drop_retry_404_marks_dropped_no_repost(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
            await self.republish(drop=True)
            self.mode = 'timeout'
            self.assertEqual((await self.send('/drop')).status, 503)
            first = self.sent[-1]
            self.app['store'] = Store(self.app['store'].path)
            self.body['request_id'] = 'd' * 24
            self.mode = '404'
            response = await self.send('/drop')
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['post']['status'], 'dropped')
            self.assertEqual(first, self.sent[-1])
            payload = self.sent[-1][2]['json']
            self.assertEqual(payload['attachments'], [])
            self.assertEqual(payload['components'], [])
            self.assertIn('no longer hosting', payload['content'])
            self.assertEqual([s[0] for s in self.sent], ['POST', 'PATCH', 'PATCH'])

    async def test_update_retry_404_offers_new_post_and_rate_limit_receipt(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
            await self.republish()
            self.mode = 'timeout'
            await self.send('/update')
            self.body['request_id'] = 'c' * 24
            self.mode = '404'
            response = await self.send('/update')
            self.assertEqual(response.status, 400)
            self.assertEqual((await response.json())['error'], 'Message was deleted in Discord')
            self.body['request_id'] = 'd' * 24
            self.mode = '429'
            response = await self.send()
            self.assertEqual(response.status, 429)
            self.assertEqual((await response.json())['retry_after'], 0.01)
            self.body['request_id'] = 'e' * 24
            self.mode = None
            self.assertEqual((await self.send()).status, 200)
        with self.app['store'].tx() as db:
            actions = [r[0] for r in db.execute("SELECT action FROM roster_audit WHERE action LIKE 'roster_image_%'")]
            self.assertIn('roster_image_update', actions)
            self.assertIn('roster_image_post', actions)

    async def test_hidden_never_and_missing_permission_do_not_send(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.assertEqual((await self.call('POST', self.path, self.member, json=self.body)).status, 403)
            with self.app['store'].tx() as db:
                db.execute("UPDATE roster_publications SET withdrawn_at=CURRENT_TIMESTAMP WHERE season_id=?", (self.sid,))
            self.assertEqual((await self.send()).status, 409)
            self.assertEqual(self.sent, [])

    async def test_concurrent_attempt_has_one_sender(self):
        import asyncio
        await self.setup_post()
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(request, method, path, **kwargs):
            if method != 'GET':
                entered.set()
                await release.wait()
            return await self.fake(request, method, path, **kwargs)
        with patch('cwl_web.roster_image_posts.discord', held):
            first = asyncio.create_task(self.send())
            await entered.wait()
            self.body = self.body | {'request_id': 'c' * 24}
            try:
                second = await self.send()
                self.assertEqual(second.status, 409)
            finally:
                release.set()
            self.assertEqual((await first).status, 200)
            self.assertEqual(len(self.sent), 1)

    async def test_never_published_and_wrong_pool_do_not_send(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.body['pool'] = 'lazy'
            self.assertEqual((await self.send()).status, 400)
            self.body['pool'] = 'main'
            with self.app['store'].tx() as db:
                db.execute('DELETE FROM publication_accounts WHERE publication_id IN (SELECT id FROM roster_publications WHERE season_id=?)', (self.sid,))
                db.execute('DELETE FROM roster_publications WHERE season_id=?', (self.sid,))
            self.assertEqual((await self.send()).status, 409)
            self.assertEqual(self.sent, [])
