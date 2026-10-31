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
        self.failure = None
        self.permission = AsyncMock(return_value=True)

        async def image(job, item):
            self.sent.append(item['tag'])
            if self.failure and item['tag'] == '#BBB':
                raise self.failure
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
        self.failure = SequenceRejected('Forbidden')
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])
        restarted = SequenceWorker(self.images, self.transport, self.permission)
        self.failure = None
        self.assertEqual((await restarted.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.sent, ['#AAA', '#BBB'])

    async def test_unknown_accepted_message_is_not_duplicated_after_restart(self):
        self.confirm()
        self.failure = TimeoutError('Accepted, response lost')
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'uncertain')
        self.failure = None
        restarted = SequenceWorker(self.images, self.transport, self.permission)
        self.assertEqual((await restarted.advance('a' * 24))['status'], 'stopped')
        self.assertEqual(self.images.receipt('2' * 24)['status'], 'uncertain')
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
        self.failure = SequenceRateLimit(2.5)
        async def waited(seconds):
            self.assertEqual(seconds, 2.5)
            self.assertEqual(self.images.receipt('2' * 24)['retry_after'], 2.5)
            self.assertEqual(self.sent, ['#AAA', '#BBB'])
            self.failure = None
        with patch('utils.cwl_roster_sequence.asyncio.sleep', side_effect=waited) as sleep:
            result = await self.worker.advance('a' * 24)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(sleep.await_count, 1)
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])

    async def test_explicit_resume_skips_confirmed_and_retries_only_known_failure(self):
        self.confirm()
        self.failure = SequenceRejected('Forbidden')
        await self.worker.advance('a' * 24)
        self.failure = None
        self.assertEqual((await self.worker.advance('a' * 24, resume=True))['status'], 'complete')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])

    async def test_explicit_resume_still_requires_check_first_for_unknown_message(self):
        self.confirm()
        self.failure = TimeoutError()
        await self.worker.advance('a' * 24)
        self.failure = None
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
        self.failure = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.worker.advance('a' * 24)
        self.assertEqual(self.images.receipt('2' * 24)['status'], 'uncertain')
        self.failure = None
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

    async def test_durable_resume_intent_survives_worker_restart(self):
        self.confirm()
        self.failure = SequenceRejected('Forbidden')
        await self.worker.advance('a' * 24)
        self.images.request_sequence_resume('a' * 24, self.args['actor'])
        self.failure = None
        restarted = SequenceWorker(self.images, self.transport, self.permission)
        self.assertEqual((await restarted.advance('a' * 24))['status'], 'complete')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])
        self.assertEqual(self.images.sequence('a' * 24)['resume_requested'], 0)

    async def test_new_publication_does_not_replace_frozen_inflight_sequence(self):
        self.confirm()
        with self.store.tx() as db:
            db.execute("INSERT INTO roster_publications(season_id,version,revision,published_by,"
                       "published_at,joining_instructions,assigned_count,unassigned_count,clans_json) "
                       "VALUES(1,2,2,'staff','2026-10-30T01:00:00Z','',0,0,'[]')")
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'complete')
        self.assertEqual(self.images.receipt('1' * 24)['target_version'], 1)

    async def test_explicit_duplicate_confirmation_recovers_only_uncertain_clan(self):
        import json
        self.confirm()
        self.failure = TimeoutError('Response lost')
        await self.worker.advance('a' * 24)
        self.images.recover_sequence_message('a' * 24, '2' * 24, 'f' * 24, self.args['actor'])
        frozen = json.loads(self.images.sequence('a' * 24)['plan_json'])['clans'][1]
        self.assertEqual(frozen['frozen'], self.items[1]['frozen'])
        self.assertEqual(self.images.receipt('2' * 24)['status'], 'uncertain')
        self.failure = None
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'complete')
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#BBB', '#CCC', '#DDD', 'closing'])
        self.assertEqual(self.images.receipt('f' * 24)['status'], 'posted')

    async def test_closing_recovery_retains_old_receipt_and_rejects_late_completion(self):
        self.confirm()
        original = self.transport.closing
        self.transport.closing = AsyncMock(side_effect=TimeoutError())
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'uncertain')
        self.images.recover_sequence_message('a' * 24, 'e' * 24, 'f' * 24, self.args['actor'])
        self.transport.closing = original
        self.assertEqual((await self.worker.advance('a' * 24))['status'], 'complete')
        active = self.images.closing_receipt('a' * 24)
        old = self.images.finish_sequence_closing('a' * 24, expected_request_id='e' * 24,
                                                 status='posted', message='999999999999999999')
        self.assertEqual(old['status'], 'uncertain')
        self.assertEqual(self.images.closing_receipt('a' * 24), active)
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#CCC', '#DDD', 'closing'])

    async def test_deleted_closing_reposts_only_closing_and_keeps_old_receipt(self):
        import json
        self.confirm()
        await self.worker.advance('a' * 24)
        old = self.images.closing_receipt('a' * 24)
        self.images.repost_deleted_closing('a' * 24, old['message_id'], 'new-staff')
        async def replacement(job, item):
            self.sent.append('replacement closing')
            self.assertEqual(item['payload'], json.loads(old['payload_json']))
            return '123456789012345698'
        self.transport.closing = replacement
        await self.worker.advance('a' * 24)
        self.assertEqual(self.sent, ['#AAA', '#BBB', '#CCC', '#DDD', 'closing', 'replacement closing'])
        self.assertEqual(self.images.closing_receipt('a' * 24)['message_id'], '123456789012345698')
        self.assertEqual(self.images.closing_receipt('a' * 24)['error'], 'Reposted (old message was deleted)')
        archive = self.store.one('SELECT receipt_json FROM roster_image_sequence_closing_history')
        self.assertEqual(json.loads(archive['receipt_json'])['message_id'], old['message_id'])
        self.assertEqual(json.loads(archive['receipt_json'])['status'], 'deleted_confirmed')
        await self.worker.advance('a' * 24)
        self.assertEqual(len(self.sent), 6)
