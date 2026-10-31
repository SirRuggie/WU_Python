from test_cwl_web_manage_bridge import ManageBridgeTests
from cwl_web.server_management import GUILD_ID


class AnnouncementTestChannelTests(ManageBridgeTests):
    async def test_shared_channel_permission_revision_and_destination(self):
        path = '/manage/announcement-test-channel'
        channel = '123456789012345678'
        calls = []
        destination = {'id': channel, 'guild_id': str(GUILD_ID), 'type': 0, 'name': 'bot-testing'}
        async def fake(method, url, **kwargs):
            calls.append((method, url))
            return dict(destination)
        self.app['server_management_discord'] = fake
        self.assertEqual((await self.call('GET', path, self.member)).status, 403)
        initial = await self.call('GET', path, self.owner)
        self.assertEqual(await initial.json(), {'channel_id': '', 'channel_name': '', 'revision': 0})
        body = {'channel_id': channel, 'expected_revision': 0}
        self.assertEqual((await self.call('PUT', path, self.member, json=body)).status, 403)
        self.assertEqual(calls, [])
        saved = await self.call('PUT', path, self.owner, json=body)
        self.assertEqual(saved.status, 200, await saved.text())
        self.assertEqual((await saved.json())['revision'], 1)
        self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 409)
        body['expected_revision'] = 1
        for overrides in ({'guild_id': 'other'}, {'type': 2}, {'id': '999999999999999999'}):
            original = dict(destination)
            destination.update(overrides)
            self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 400)
            destination.clear(); destination.update(original)
        self.assertEqual((await (await self.call('GET', path, self.owner)).json())['revision'], 1)
        self.assertTrue(all(method == 'GET' for method, _ in calls))

    async def test_malformed_channel_and_revision_are_rejected_before_lookup(self):
        path = '/manage/announcement-test-channel'
        async def forbidden(*args, **kwargs):
            raise AssertionError('No upstream request for malformed input')
        self.app['server_management_discord'] = forbidden
        for body in ({'channel_id': 'x', 'expected_revision': 0},
                     {'channel_id': '123456789012345678', 'expected_revision': True},
                     {'channel_id': '123456789012345678', 'expected_revision': -1},
                     {'channel_id': '123456789012345678', 'expected_revision': 0, 'extra': 1}):
            self.assertEqual((await self.call('PUT', path, self.owner, json=body)).status, 400)
