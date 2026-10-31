import json
from unittest.mock import patch
from aiohttp import web
from cwl_web.server_management import DiscordItemNotFound
from test_cwl_roster_image_posts import ImagePostTests


class DeletedRepostTests(ImagePostTests):
    async def test_confirmed_deletion_reposts_once_and_next_version_edits_new_id(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
        await self.republish()
        calls = []
        async def transport(request, method, path, **kwargs):
            if method == 'GET':
                return {'guild_id': '644963518025826315', 'type': 0}
            calls.append((method, path, kwargs))
            if method == 'PATCH' and path.endswith('987654321098765432'):
                raise DiscordItemNotFound(10008)
            return {'id': '987654321098765499'}
        with patch('cwl_web.roster_image_posts.discord', transport):
            response = await self.send('/update')
            self.assertEqual(response.status, 200, await response.text())
            post = (await response.json())['post']
            self.assertEqual(post['message_id'], '987654321098765499')
            self.assertEqual(post['error'], 'Reposted (old message was deleted)')
            self.assertEqual([c[0] for c in calls], ['PATCH', 'POST'])
            payload = json.loads(calls[-1][2]['data']._fields[0][2])
            self.assertEqual(payload['allowed_mentions'], {'parse': []})
            self.assertTrue(payload['enforce_nonce'])
            self.assertEqual((await self.send('/update')).status, 200)
            self.assertEqual(len(calls), 2)
            original = self.app['store'].one('SELECT * FROM roster_image_requests WHERE request_id=?', ('b'*24,))
            self.assertEqual(original['message_id'], '987654321098765432')
            self.assertEqual(original['status'], 'deleted_confirmed')
            self.assertTrue(original['replacement_request_id'])
            await self.republish()
            self.body['request_id'] = 'c' * 24
            self.assertEqual((await self.send('/update')).status, 200)
            self.assertEqual(calls[-1][0:2], ('PATCH', '/channels/123456789012345678/messages/987654321098765499'))

    async def check_no_repost(self, failure):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
        await self.republish()
        calls = []
        async def transport(request, method, path, **kwargs):
            if method == 'GET':
                return {'guild_id': '644963518025826315', 'type': 0}
            calls.append(method)
            raise failure
        with patch('cwl_web.roster_image_posts.discord', transport):
            response = await self.send('/update')
        self.assertIn(response.status, (400, 503))
        self.assertEqual(calls, ['PATCH'])
        post = self.app['store'].one('SELECT * FROM roster_image_posts WHERE season_id=?', (self.sid,))
        self.assertEqual(post['message_id'], '987654321098765432')

    async def test_missing_channel_never_reposts(self):
        await self.check_no_repost(DiscordItemNotFound(10003))

    async def test_uncertain_edit_never_reposts(self):
        await self.check_no_repost(TimeoutError())

    async def test_access_denied_never_reposts(self):
        await self.check_no_repost(web.HTTPForbidden())

    async def test_uncertain_replacement_stays_a_new_post_receipt(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            await self.send()
        await self.republish()
        calls = []
        async def transport(request, method, path, **kwargs):
            if method == 'GET':
                return {'guild_id': '644963518025826315', 'type': 0}
            calls.append(method)
            if method == 'PATCH':
                raise DiscordItemNotFound(10008)
            raise TimeoutError()
        with patch('cwl_web.roster_image_posts.discord', transport):
            self.assertEqual((await self.send('/update')).status, 503)
            await self.send('/update')
        self.assertEqual(calls, ['PATCH', 'POST'])
        old = self.app['store'].one('SELECT * FROM roster_image_requests WHERE request_id=?', ('b'*24,))
        replacement = self.app['store'].one('SELECT * FROM roster_image_requests WHERE request_id=?', (old['replacement_request_id'],))
        self.assertEqual(replacement['operation'], 'post')
        self.assertEqual(replacement['status'], 'uncertain')
        self.assertIsNone(replacement['message_id'])
        self.assertEqual(old['message_id'], '987654321098765432')
