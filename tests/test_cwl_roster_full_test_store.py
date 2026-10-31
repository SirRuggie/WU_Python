"""Full-post tests have durable order but never consume production claims."""
import unittest

from cwl_web.store import Store
from utils.cwl_roster_image_store import ImageConflict, RosterImageStore
from test_cwl_roster_sequence_store import SequenceStoreTests


class FullTestStoreTests(unittest.TestCase):
    setUp = SequenceStoreTests.setUp

    def prepare(self):
        self.test_args = dict(request_id='f' * 24, sid=1, pool='lazy', version=1,
            channel='123456789012345678', actor='staff', plan=[
                {'kind': kind, 'payload': {'content': kind, 'allowed_mentions': {'parse': [], 'roles': []}}}
                for kind in ('announcement', 'image', 'closing')])
        return self.images.prepare_test_sequence(**self.test_args)

    def test_restart_resumes_only_after_a_confirmed_message_and_keeps_production_empty(self):
        job = self.prepare()
        self.assertEqual(self.images.prepare_test_sequence(**self.test_args), job)
        first = self.images.claim_test_step(job['request_id'])
        self.assertEqual(first['item']['kind'], 'announcement')
        reopened = RosterImageStore(Store(self.path))
        with self.assertRaises(ImageConflict):
            reopened.claim_test_step(job['request_id'])
        reopened.finish_test_step(job['request_id'], 0, status='posted', message_id='987654321098765432')
        for step, kind in [(1, 'image'), (2, 'closing')]:
            item = reopened.claim_test_step(job['request_id'])
            self.assertEqual((item['step'], item['item']['kind']), (step, kind))
            reopened.finish_test_step(job['request_id'], step, status='posted', message_id=str(987654321098765432+step))
        complete = reopened.test_sequence(job['request_id'])
        self.assertEqual(complete['status'], 'complete')
        self.assertEqual(complete['first_message_id'], '987654321098765432')
        from cwl_web.roster_sequence_tests import public_test
        self.assertTrue(public_test(complete)['message_url'].endswith('/123456789012345678/987654321098765432'))
        with self.store.tx() as db:
            for table in ('roster_image_posts', 'roster_image_requests', 'roster_image_sequences', 'roster_audit'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0, table)
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT nonce) FROM roster_image_test_receipts').fetchone()[0], 3)
        with self.assertRaises(ImageConflict):
            reopened.claim_test_step(job['request_id'])

    def test_failed_or_uncertain_test_never_advances_or_reposts_automatically(self):
        for status in ('failed', 'uncertain'):
            with self.subTest(status=status):
                self.prepare()
                key = self.test_args['request_id']
                if status == 'uncertain':
                    self.test_args['request_id'] = 'e' * 24
                    self.images.prepare_test_sequence(**self.test_args)
                    key = self.test_args['request_id']
                self.images.claim_test_step(key)
                self.images.finish_test_step(key, 0, status=status, error='Check Discord')
                with self.assertRaises(ImageConflict):
                    RosterImageStore(Store(self.path)).claim_test_step(key)
                self.assertEqual(self.images.test_sequence(key)['next_step'], 0)

    def test_review_is_immutable_and_mentions_rejected(self):
        self.prepare()
        for field, value in [('channel', '111111111111111111'), ('actor', 'other'), ('version', 2)]:
            with self.subTest(field=field), self.assertRaises(ImageConflict):
                self.images.prepare_test_sequence(**(self.test_args | {field: value}))
        self.test_args['request_id'] = 'e' * 24
        self.test_args['plan'][0]['payload']['allowed_mentions'] = {'parse': ['roles']}
        with self.assertRaises(ImageConflict):
            self.images.prepare_test_sequence(**self.test_args)


class FullTestWorkerTests(unittest.TestCase):
    setUp = SequenceStoreTests.setUp
    prepare = FullTestStoreTests.prepare

    def run_worker(self, transport, authorize=None):
        import asyncio
        from unittest.mock import AsyncMock
        from utils.cwl_roster_test_sequence import TestSequenceWorker
        return asyncio.run(TestSequenceWorker(self.images, transport, authorize or AsyncMock(return_value=True)).advance('f' * 24))

    def test_worker_preserves_order_across_concurrent_passes(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from utils.cwl_roster_test_sequence import TestSequenceWorker
        self.prepare()
        sent = []
        async def send(job, item):
            sent.append(item['kind'])
            await asyncio.sleep(0)
            return '987654321098765432'
        transport = SimpleNamespace(test_announcement=send, image=send, closing=send)
        async def run():
            await asyncio.gather(*[TestSequenceWorker(self.images, transport, AsyncMock(return_value=True)).advance('f' * 24) for _ in range(2)])
        asyncio.run(run())
        self.assertEqual(sent, ['announcement', 'image', 'closing'])
        self.assertEqual(self.images.test_sequence('f' * 24)['status'], 'complete')

    def test_worker_stops_at_unknown_image_and_reopening_cannot_replay(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        self.prepare()
        transport = SimpleNamespace(test_announcement=AsyncMock(return_value='987654321098765432'), image=AsyncMock(side_effect=TimeoutError()), closing=AsyncMock())
        self.assertEqual(self.run_worker(transport)['status'], 'uncertain')
        self.images = RosterImageStore(Store(self.path))
        self.run_worker(transport)
        transport.test_announcement.assert_awaited_once()
        transport.image.assert_awaited_once()
        transport.closing.assert_not_awaited()

    def test_permission_loss_prevents_all_messages(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        self.prepare()
        transport = SimpleNamespace(test_announcement=AsyncMock(), image=AsyncMock(), closing=AsyncMock())
        self.assertEqual(self.run_worker(transport, AsyncMock(return_value=False))['status'], 'failed')
        transport.test_announcement.assert_not_awaited()
        self.assertEqual(self.images.pending_test_sequences(), [])
