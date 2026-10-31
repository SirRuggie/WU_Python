import asyncio
import json
from unittest.mock import AsyncMock

from test_cwl_web_manage_bridge import ManageBridgeTests
from cwl_web.roster_sequence_jobs import SequenceJobs
from utils.cwl_roster_image_store import RosterImageStore


class FullTestHTTPTests(ManageBridgeTests):
    from test_cwl_web_roster import RosterTests
    host = RosterTests.host
    async def test_full_test_is_queued_once_then_runs_without_browser_or_production_marks(self):
        await self.bind()
        from test_cwl_roster_images import RosterImageTests
        await RosterImageTests.publish(self)
        before = await self.state()
        sent = []
        async def fake(method, path, **kwargs):
            if method == 'GET':
                return {'guild_id': '644963518025826315', 'type': 0}
            if 'data' in kwargs:
                import io
                from PIL import Image
                form = kwargs['data']
                sent.append(json.loads(form._fields[0][2]))
                self.assertEqual(Image.open(io.BytesIO(form._fields[1][2])).width, 1000)
            else:
                sent.append(kwargs['json'])
            return {'id': str(987654321098765432 + len(sent))}
        self.app['server_management_discord'] = fake
        body = {'channel_id': '123456789012345678', 'request_id': 'e' * 24,
                'generation': before['generation'], 'body': 'Reviewed test',
                'roster_url': 'https://example.test/assignments', 'version': 1}
        path = self.base + '/main/test-full'
        denied = await self.call('POST', path, self.member, json=body)
        self.assertEqual(denied.status, 403)
        response = await self.call('POST', path, self.owner, json=body)
        self.assertEqual(response.status, 202, await response.text())
        self.assertEqual(sent, [])
        replay = await self.call('POST', path, self.owner, json=body)
        self.assertEqual(replay.status, 200)
        jobs = SequenceJobs(self.app)
        jobs.authorized = AsyncMock(return_value=True)
        jobs.poll()
        await asyncio.gather(*list(jobs.tasks.values()))
        self.assertEqual(len(sent), 3)
        from utils import cwl_campaign
        from cwl_web.manage_bridge import GUILD_ID
        import copy
        production = copy.deepcopy(await cwl_campaign.load_campaign(self.mongo, GUILD_ID, '2026-10'))
        variant = production['campaign']['messages']['roster']['variants']['main']
        variant['body'] = body['body']
        variant['buttons'][0]['url'] = body['roster_url']
        components = await cwl_campaign.render_message(production, 'roster', 'main', preview=False)
        self.assertEqual(sent[0]['components'], [component.build()[0] for component in components])
        self.assertEqual(sent[0]['flags'], 32768)
        self.assertNotIn('TEST', json.dumps(sent, ensure_ascii=False))
        self.assertTrue(sent[1]['content'].startswith('**'))
        self.assertTrue(sent[2]['content'].startswith('Can'))
        self.assertTrue(all(payload['allowed_mentions'] == {'parse': [], 'roles': []} for payload in sent))
        status = await self.call('GET', path + '/' + body['request_id'], self.owner)
        self.assertEqual((await status.json())['test']['status'], 'complete')
        self.assertEqual((await self.state())['pools'], before['pools'])
        self.assertIsNone(RosterImageStore(self.app['store']).pool_sequence(self.sid, 'main'))
        self.assertEqual((await self.call('POST', path, self.owner, json=body)).status, 200)
        jobs.poll()
        self.assertEqual(jobs.tasks, {})
        self.assertEqual(len(sent), 3)

    async def test_full_test_rejects_changed_generation_before_job_creation(self):
        await self.bind()
        await self.publish()
        self.app['server_management_discord'] = AsyncMock(return_value={'guild_id': '644963518025826315', 'type': 0})
        response = await self.call('POST', self.base + '/main/test-full', self.owner, json={
            'channel_id': '123456789012345678', 'request_id': 'e' * 24, 'generation': 'stale',
            'body': 'Test', 'roster_url': 'https://example.test/', 'version': 1})
        self.assertEqual(response.status, 409)
        self.assertIsNone(RosterImageStore(self.app['store']).test_sequence('e' * 24))
