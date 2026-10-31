import asyncio
import unittest
from unittest.mock import AsyncMock

from utils.cwl_roster_messages import clan_image_message, closing_message
from utils.cwl_roster_sequence import SequenceWorker, SequenceRejected, SequenceRateLimit


class SequenceWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from test_cwl_roster_sequence_store import SequenceStoreTests
        SequenceStoreTests.setUp(self)
        self.items = []
        for index, tag in enumerate(('#AAA', '#BBB', '#CCC', '#DDD')):
            self.items.append({'tag': tag, 'request_id': str(index + 1) * 24,
                               'frozen': {'name': tag, 'league': 'Gold', 'season_label': 'November',
                                          'payload': clan_image_message(tag, tag)}})
        self.args['plan'] = {'clans': self.items, 'closing': {
            'request_id': 'e' * 24, 'payload': closing_message()}}
        self.images.prepare_sequence(**self.args)
        self.sent = []
        self.fail = None
        self.permission = AsyncMock(return_value=True)

        async def image(job, item):
            self.sent.append(item['tag'])
            if self.fail and item['tag'] == '#BBB':
                raise self.fail
            return str(123456789012345680 + len(self.sent))

        async def closing(job, item):
            self.sent.append('closing')
            return '123456789012345699'

        class Transport:
            pass
        self.transport = Transport()
        self.transport.image = image
        self.transport.closing = closing
        self.worker = SequenceWorker(self.images, self.transport, self.permission)

    def confirm(self):
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)

    async def test_waits_for_announcement_then_serial_images_and_closing_once(self):
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'awaiting_announcement')
        self.assertEqual(self.sent, [])
        self.confirm()
        results = await asyncio.gather(self.worker.advance('a' * 24), self.worker.advance('a' * 24))
        self.assertEqual([r['status'] for r in results], ['complete', 'complete'])
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#CCC', '#DDD', 'closing'])
        self.assertEqual(self.permission.await_count, 5)

    async def test_first_rejection_stops_and_restart_does_not_retry_failed_message(self):
        self.confirm()
        self.fail = SequenceRejected('Forbidden')
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])
        restarted = SequenceWorker(self.images, self.transport, self.permission)
        self.fail = None
        self.assertEqual((await restarted.advance('a' * 24))['clan_tag'], '#BBB')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])

    async def test_unknown_accepted_message_is_not_duplicated_after_restart(self):
        self.confirm()
        self.fail = TimeoutError('Accepted, response lost')
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'uncertain')
        self.fail = None
        restarted = SequenceWorker(self.images, self.transport, self.permission)
        self.assertEqual((await restarted.advance('a' * 24))['status'], 'uncertain')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])

    async def test_permission_denied_before_any_send(self):
        self.confirm()
        self.permission.return_value = False
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.images.receipt('1' * 24))

    async def test_known_rate_limit_waits_then_retries_same_clan_before_advancing(self):
        from unittest.mock import patch
        self.confirm()
        self.fail = SequenceRateLimit(2.5)
        async def waited(seconds):
            self.assertEqual(seconds, 2.5)
            self.assertEqual(self.images.receipt('2' * 24)['retry_after'], 2.5)
            self.assertEqual(self.sent, ['#AAA', '#BBB'])
            self.fail = None
        with patch('utils.cwl_roster_sequence.asyncio.sleep', side_effect=waited) as sleep:
            result = await self.worker.advance('a' * 24)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(sleep.await_count, 1)
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])

    async def test_explicit_resume_skips_confirmed_and_retries_only_known_failure(self):
        self.confirm()
        self.fail = SequenceRejected('Forbidden')
        await self.worker.advance('a' * 24)
        self.fail = None
        self.assertEqual((await self.worker.advance('a' * 24, resume=True))['status'], 'complete')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])

    async def test_explicit_resume_still_requires_check_first_for_unknown_message(self):
        self.confirm()
        self.fail = TimeoutError()
        await self.worker.advance('a' * 24)
        self.fail = None
        self.assertEqual((await self.worker.advance('a' * 24, resume=True))['status'], 'uncertain')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])

    async def test_permission_revocation_between_clans_stops_before_second_claim(self):
        self.confirm()
        self.permission.side_effect = [True, False]
        self.assertEqual((await self.worker.advance('a' * 24))['clan_tag'], '#BBB')
        self.assertEqual(self.sent, ['#AAA'])
        self.assertIsNone(self.images.receipt('2' * 24))

    async def test_cancelled_send_is_unknown_and_never_retried_by_resume(self):
        self.confirm()
        self.fail = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.worker.advance('a' * 24)
        self.assertEqual(self.images.receipt('2' * 24)['status'], 'uncertain')
        self.fail = None
        self.assertEqual((await self.worker.advance('a' * 24, resume=True))['status'], 'uncertain')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])

    async def test_closing_retry_keeps_all_confirmed_images(self):
        self.confirm()
        original = self.transport.closing
        self.transport.closing = AsyncMock(side_effect=SequenceRejected('Forbidden'))
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#CCC', '#DDD'])
        self.transport.closing = original
        self.assertEqual((await self.worker.advance('a' * 24, resume=True))['status'], 'complete')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#CCC', '#DDD', 'closing'])
