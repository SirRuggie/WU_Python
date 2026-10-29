"""Isolated roster image configuration: no Discord network or production data."""
import json
from unittest.mock import AsyncMock, patch
import test_cwl_web_roster as fixtures


class ImageChannelTests(fixtures.RosterTests):
    async def test_global_channel_validates_destination_and_audits(self):
        path = '/roster-image-channels'
        body = {'pool': 'lazy', 'channel_id': '123456789012345678'}
        for destination in ({'guild_id': 'wrong', 'type': 0}, {'guild_id': '644963518025826315', 'type': 15}):
            with patch('cwl_web.roster_image_posts.discord', AsyncMock(return_value=destination)):
                self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 400)
        with patch('cwl_web.roster_image_posts.discord', AsyncMock(return_value={'guild_id': '644963518025826315', 'type': 5, 'name': 'rosters'})) as transport:
            self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 200)
            self.assertEqual(transport.call_args.args[1], 'GET')
        response = await self.call('GET', path, self.owner)
        self.assertEqual((await response.json())['channels'][0]['channel_name'], 'rosters')
        await self.call('POST', '/seasons', self.owner, json={'label': 'Next season', 'signup_open': False})
        self.assertEqual(len((await (await self.call('GET', path, self.owner)).json())['channels']), 1)
        with self.app['store'].tx() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM roster_audit WHERE action='roster_image_channel'").fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM roster_image_posts').fetchone()[0], 0)

    async def test_invalid_channel_pool_permission_and_csrf_never_call_discord(self):
        path = '/roster-image-channels'
        with patch('cwl_web.roster_image_posts.discord', AsyncMock()) as transport:
            for body in ({'pool': 'other', 'channel_id': '123456789012345678'}, {'pool': 'main', 'channel_id': '../messages'}, {'pool': 'main', 'channel_id': 12}):
                self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 400)
            self.assertEqual((await self.call('GET', path, self.member)).status, 403)
            headers = {k: v for k, v in self.owner.items() if k != 'X-CSRF-Token'}
            self.assertEqual((await self.call('PUT', path, headers, json={'pool': 'main', 'channel_id': '123456789012345678'})).status, 403)
            transport.assert_not_called()

    async def test_statuses_readable_without_send_but_channels_protected(self):
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES(?,?,?)', ('200', 'owner', json.dumps(['cwl_roster'])))
        headers = self.auth('200')
        self.assertEqual((await self.call('GET', '/roster-image-channels', headers)).status, 403)
        response = await self.call('GET', f'/seasons/{self.sid}/roster-image-posts', headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'posts': [], 'published': None, 'last_publication': None})

    async def test_receipt_schema_has_frozen_text_and_no_image_blob(self):
        with self.app['store'].tx() as db:
            columns = {r['name']: r['type'] for r in db.execute('PRAGMA table_info(roster_image_requests)')}
            self.assertIn('payload_json', columns)
            self.assertNotIn('BLOB', columns.values())
            self.assertTrue({'operation', 'target_version', 'message_id', 'request_id'}.issubset(columns))
