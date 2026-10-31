"""Full-resolution multipart adapter checks against isolated fixture publications."""
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image
from aiohttp import web

from cwl_web.roster_sequence_transport import SequenceTransport
from utils.cwl_roster_messages import clan_image_message, closing_message
from utils.cwl_roster_sequence import SequenceRejected, SequenceRateLimit


class SequenceTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_cwl_roster_image_posts import ImagePostTests
        self.fixture = ImagePostTests()
        await self.fixture.asyncSetUp()
        await self.fixture.setup_post()
        self.transport = SequenceTransport(self.fixture.app)
        self.job = {'season_id': self.fixture.sid, 'target_version': 1,
                    'pool': 'main', 'channel_id': '123456789012345678'}
        self.item = {'tag': '#C2Y', 'request_id': 'd' * 24,
                     'frozen': {'name': 'Frozen name', 'league': 'Frozen league',
                                'season_label': 'Frozen November',
                                'payload': clan_image_message('Frozen name', '#C2Y')}}

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def test_full_resolution_files_frozen_metadata_and_closing_same_channel(self):
        with patch('cwl_web.roster_sequence_transport.discord', self.fixture.fake):
            await self.transport.image(self.job, self.item)
            await self.transport.closing(self.job, {'request_id': 'e' * 24, 'payload': closing_message()})
        first, last = self.fixture.sent
        self.assertEqual(first[1], last[1])
        self.assertEqual(first[1], '/channels/123456789012345678/messages')
        form = first[2]['data']
        payload = json.loads(form._fields[0][2])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(payload['nonce'], 'd' * 24)
        self.assertNotIn('embeds', payload)
        png = form._fields[1][2]
        self.assertEqual(Image.open(io.BytesIO(png)).width, 1000)
        self.assertEqual(last[2]['json']['allowed_mentions'], {'parse': []})
        # A restart reads the same immutable publication and frozen text, not live metadata.
        restarted = SequenceTransport(self.fixture.app)
        with patch('cwl_web.roster_sequence_transport.discord', self.fixture.fake):
            await restarted.image(self.job, self.item)
        self.assertEqual(self.fixture.sent[-1][2]['data']._fields[1][2], png)

    async def test_foreign_channel_blocks_post(self):
        async def foreign(request, method, path, **kwargs):
            self.assertEqual(method, 'GET')
            return {'guild_id': 'other', 'type': 0}
        with patch('cwl_web.roster_sequence_transport.discord', foreign), self.assertRaises(SequenceRejected):
            await self.transport.image(self.job, self.item)
        self.assertEqual(self.fixture.sent, [])

    async def test_rate_limit_is_distinct_from_uncertain_outcome(self):
        self.fixture.mode = '429'
        with patch('cwl_web.roster_sequence_transport.discord', self.fixture.fake), self.assertRaises(SequenceRateLimit):
            await self.transport.closing(self.job, {'request_id': 'e' * 24, 'payload': closing_message()})
        self.fixture.mode = 'timeout'
        with patch('cwl_web.roster_sequence_transport.discord', self.fixture.fake), self.assertRaises(TimeoutError):
            await self.transport.closing(self.job, {'request_id': 'e' * 24, 'payload': closing_message()})
