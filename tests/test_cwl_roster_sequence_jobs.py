import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cwl_web.roster_sequence_jobs import SequenceJobs
from utils.cwl_roster_messages import clan_image_message, closing_message


class SequenceJobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from test_cwl_roster_sequence_store import SequenceStoreTests
        from tests.test_cwl_dashboard_integration import MemoryMongo
        SequenceStoreTests.setUp(self)
        self.args['plan'] = {'clans': [{'tag': '#AAA', 'request_id': 'b' * 24,
                            'frozen': {'name': 'Clan', 'league': 'Gold', 'season_label': 'November',
                                       'payload': clan_image_message('Clan', '#AAA')}}],
                            'closing': {'request_id': 'c' * 24, 'payload': closing_message()}}
        self.images.prepare_sequence(**self.args)
        self.app = {'store': self.store, 'manage_bridge_mongo': MemoryMongo()}
        self.jobs = SequenceJobs(self.app)
        self.jobs.authorized = AsyncMock(return_value=True)
        self.transport = unittest.mock.Mock()
        self.transport.image = AsyncMock(return_value='123456789012345680')
        self.transport.closing = AsyncMock(return_value='123456789012345681')

    async def test_crash_before_announcement_queue_recovers_only_queue_not_images(self):
        with patch('cwl_web.roster_sequence_jobs.get_roster_send_status', AsyncMock(return_value=None)), \
             patch('cwl_web.roster_sequence_jobs.queue_roster_send', AsyncMock()) as queue, \
             patch('cwl_web.roster_sequence_jobs.SequenceTransport', return_value=self.transport):
            await self.jobs.advance('a' * 24)
        self.assertEqual(queue.await_count, 1)
        self.assertEqual(queue.call_args.kwargs['sequence_id'], 'a' * 24)
        self.transport.image.assert_not_awaited()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'awaiting_announcement')

    async def test_old_native_announcement_cannot_unlock_new_sequence(self):
        with patch('cwl_web.roster_sequence_jobs.get_roster_send_status', AsyncMock(return_value={
            'status': 'sent', 'receipt': self.bridge['receipt']})), \
             patch('cwl_web.roster_sequence_jobs.SequenceTransport', return_value=self.transport):
            await self.jobs.advance('a' * 24)
        self.transport.image.assert_not_awaited()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'stopped')

    async def test_matching_native_receipt_runs_sequence_without_browser(self):
        with patch('cwl_web.roster_sequence_jobs.get_roster_send_status', AsyncMock(return_value=self.bridge)), \
             patch('cwl_web.roster_sequence_jobs.SequenceTransport', return_value=self.transport):
            await self.jobs.advance('a' * 24)
        self.transport.image.assert_awaited_once()
        self.transport.closing.assert_awaited_once()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'complete')

    async def test_poll_never_duplicates_an_inflight_job(self):
        gate = asyncio.Event()
        async def waiting(sequence_id):
            await gate.wait()
        self.jobs.advance = AsyncMock(side_effect=waiting)
        self.jobs.poll()
        self.jobs.poll()
        await asyncio.sleep(0)
        self.assertEqual(self.jobs.advance.await_count, 1)
        self.assertEqual(len(self.jobs.tasks), 1)
        gate.set()
        await asyncio.gather(*self.jobs.tasks.values())
        self.assertEqual(self.jobs.tasks, {})

    async def test_revoked_permission_never_queues_announcement(self):
        self.jobs.authorized.return_value = False
        with patch('cwl_web.roster_sequence_jobs.queue_roster_send', AsyncMock()) as queue:
            await self.jobs.advance('a' * 24)
        queue.assert_not_awaited()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'stopped')

    async def test_republished_after_http_failure_never_queues_old_intent(self):
        with self.store.tx() as db:
            db.execute("UPDATE roster_publications SET version=2 WHERE season_id=1")
        with patch('cwl_web.roster_sequence_jobs.get_roster_send_status', AsyncMock(return_value=None)), \
             patch('cwl_web.roster_sequence_jobs.queue_roster_send', AsyncMock()) as queue:
            await self.jobs.advance('a' * 24)
        queue.assert_not_awaited()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'stopped')

    async def test_missing_message_needs_staff_assumption_then_only_images_and_closing(self):
        bridge = self.bridge | {'receipt': self.bridge['receipt'] | {'message_id': None}}
        with patch('cwl_web.roster_sequence_jobs.get_roster_send_status', AsyncMock(return_value=bridge)), \
             patch('cwl_web.roster_sequence_jobs.queue_roster_send', AsyncMock()) as queue, \
             patch('cwl_web.roster_sequence_jobs.SequenceTransport', return_value=self.transport):
            await self.jobs.advance('a' * 24)
            self.transport.image.assert_not_awaited()
            job = self.images.sequence('a' * 24)
            self.assertEqual(job['status'], 'stopped')
            self.images.assume_announcement(job, bridge, '123456789012345679')
            from utils.cwl_roster_image_store import ImageConflict
            with self.assertRaises(ImageConflict):
                self.images.assume_announcement(job, bridge, 'other')
            await self.jobs.advance('a' * 24)
            queue.assert_not_awaited()
        self.transport.image.assert_awaited_once()
        self.transport.closing.assert_awaited_once()
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'complete')
        assumption = self.images.announcement_assumption('a' * 24)
        self.assertEqual(assumption['actor_id'], '123456789012345679')
        self.assertTrue(assumption['assumed_at'])
        self.assertIsNone(self.images.sequence('a' * 24)['announcement_message_id'])
