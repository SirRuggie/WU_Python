"""Cancellation boundaries use real SQLite service methods and fake transports."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import test_cwl_roster_sequence_store as sequence_fixture
import test_cwl_roster_full_test_store as test_fixture
import test_cwl_roster_sequence_worker as main_fixture
import test_cwl_roster_image_posts as http_fixture
from utils.cwl_roster_image_store import RosterImageStore
from utils.cwl_roster_sequence import SequenceWorker, cancel_image_claim
from utils.cwl_roster_test_sequence import TestSequenceWorker as Worker


class Gate:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        assert self.release.wait(3), 'fixture gate was not released'

    async def started(self):
        assert await asyncio.to_thread(self.entered.wait, 2), 'fixture gate did not start'


class TestStepCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = sequence_fixture.SequenceStoreTests.setUp
    prepare = test_fixture.FullTestStoreTests.prepare

    async def asyncTearDown(self):
        self.store.durability = None
        await self.store.close_writer()

    def worker(self, send=None):
        send = send or AsyncMock(return_value='987654321098765432')
        self.transport = NS(test_announcement=send, image=send, closing=send)
        return Worker(self.images, self.transport, AsyncMock(return_value=True))

    async def cancelled(self, task, reason='original'):
        with self.assertRaises(asyncio.CancelledError) as caught:
            await task
        self.assertEqual(caught.exception.args, (reason,))
        self.assertTrue(task.cancelled())

    async def test_queued_claim_cancellation_writes_nothing(self):
        self.prepare()
        gate = Gate()
        blocker = asyncio.create_task(self.store.run_writer(gate.wait))
        await gate.started()
        queued = asyncio.Event()
        original = self.store.run_writer
        async def observe(operation):
            if operation.__name__ == 'claim_step':
                queued.set()
            return await original(operation)
        with patch.object(self.store, 'run_writer', observe):
            worker = self.worker()
            task = asyncio.create_task(worker.advance('f' * 24))
            try:
                await asyncio.wait_for(queued.wait(), 2)
                task.cancel('original')
                await self.cancelled(task)
                self.assertEqual(self.store.rows('SELECT * FROM roster_image_test_receipts'), [])
                self.assertEqual(self.images.test_sequence('f' * 24)['status'], 'ready')
                self.transport.test_announcement.assert_not_awaited()
            finally:
                gate.release.set()
                await blocker

    async def test_started_claim_commit_is_closed_without_losing_identity(self):
        self.prepare()
        gate = Gate()
        original = self.images.claim_test_step
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            gate.wait()  # Entire service transaction already committed.
            return result
        with patch.object(self.images, 'claim_test_step', claim):
            task = asyncio.create_task(self.worker().advance('f' * 24))
            await gate.started()
            task.cancel('original')
            await asyncio.sleep(.01)
            task.cancel('later')
            self.assertFalse(task.done())
            gate.release.set()
            await self.cancelled(task)
        row = self.images.test_sequence('f' * 24)
        self.assertEqual((row['status'], row['next_step']), ('uncertain', 0))
        self.assertEqual(self.store.one('SELECT status FROM roster_image_test_receipts')['status'], 'uncertain')
        self.transport.test_announcement.assert_not_awaited()

    async def test_cancel_during_posted_commit_never_finishes_uncertain_or_advances_twice(self):
        self.prepare()
        gate = Gate()
        attempts = []
        original = self.images.finish_test_step
        def finish(*args, **kwargs):
            attempts.append(kwargs['status'])
            result = original(*args, **kwargs)
            if kwargs['status'] == 'posted':
                gate.wait()
            return result
        with patch.object(self.images, 'finish_test_step', finish):
            task = asyncio.create_task(self.worker().advance('f' * 24))
            await gate.started()
            task.cancel('original')
            await asyncio.sleep(.01)
            task.cancel('later')
            gate.release.set()
            await self.cancelled(task)
        self.assertEqual(attempts, ['posted'])
        row = self.images.test_sequence('f' * 24)
        self.assertEqual((row['status'], row['next_step']), ('ready', 1))
        self.assertEqual(self.store.one('SELECT status,message_id FROM roster_image_test_receipts'),
                         {'status': 'posted', 'message_id': '987654321098765432'})
        self.transport.test_announcement.assert_awaited_once()

    async def test_queued_posted_finish_records_known_message_before_cancel_propagates(self):
        self.prepare()
        gate = Gate()
        queued = asyncio.Event()
        blocker = None
        original = self.store.run_writer
        async def observe(operation):
            if 'finish_test_step' in operation.__code__.co_names:
                queued.set()
            return await original(operation)
        async def send(job, item):
            nonlocal blocker
            blocker = asyncio.create_task(original(gate.wait))
            await gate.started()
            return '987654321098765432'
        with patch.object(self.store, 'run_writer', observe):
            task = asyncio.create_task(self.worker(AsyncMock(side_effect=send)).advance('f' * 24))
            try:
                await asyncio.wait_for(queued.wait(), 2)
                task.cancel('original')
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                gate.release.set()
                await self.cancelled(task)
            finally:
                gate.release.set()
                if blocker:
                    await blocker
        row = self.images.test_sequence('f' * 24)
        self.assertEqual((row['status'], row['next_step']), ('ready', 1))
        self.assertEqual(self.store.one('SELECT status FROM roster_image_test_receipts')['status'], 'posted')
        self.transport.test_announcement.assert_awaited_once()

    async def test_cancellation_in_transport_remains_uncertain_and_never_replays(self):
        self.prepare()
        send = AsyncMock(side_effect=asyncio.CancelledError('accepted'))
        worker = self.worker(send)
        task = asyncio.create_task(worker.advance('f' * 24))
        await self.cancelled(task, 'accepted')
        self.assertEqual(self.images.test_sequence('f' * 24)['status'], 'uncertain')
        await worker.advance('f' * 24)
        send.assert_awaited_once()

    async def test_cancelled_posted_publish_failure_rolls_back_poison_and_keeps_cancel(self):
        from utils.cwl_dashboard_state import MongoDashboardState
        from test_cwl_dashboard_state import Collection
        self.prepare()
        collection = Collection()
        owner = MongoDashboardState(collection)
        owner.seed(Path(self.store.path))
        owner.acquire()
        gate = Gate()
        original = owner.publish
        def publish(db):
            row = db.execute('SELECT status FROM roster_image_test_receipts').fetchone()
            if row and row[0] == 'posted':
                gate.wait()
                collection.fail = 'before'
            return original(db)
        self.store.durability = owner
        with patch.object(owner, 'publish', publish):
            task = asyncio.create_task(self.worker().advance('f' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            await self.cancelled(task)
        self.assertTrue(owner.poisoned)
        self.store.durability = None
        self.assertEqual(self.store.one('SELECT status FROM roster_image_test_receipts')['status'], 'sending')
        self.assertEqual(self.images.test_sequence('f' * 24)['next_step'], 0)
        self.transport.test_announcement.assert_awaited_once()


class MainSequenceCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = main_fixture.SequenceWorkerTests.setUp
    confirm = main_fixture.SequenceWorkerTests.confirm

    async def asyncTearDown(self):
        await self.store.close_writer()

    async def test_claim_commit_cancellation_preserves_owned_receipt_without_post(self):
        self.confirm()
        gate = Gate()
        original = self.images.claim
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            gate.wait()
            return result
        with patch.object(self.images, 'claim', claim):
            task = asyncio.create_task(self.worker.advance('a' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            with self.assertRaises(asyncio.CancelledError) as caught:
                await task
        self.assertEqual(caught.exception.args, ('original',))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.images.receipt('1' * 24)['status'], 'uncertain')
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'stopped')

    async def test_main_posted_commit_is_kept_and_no_next_image_is_sent(self):
        self.confirm()
        gate = Gate()
        original = self.images.finish
        attempts = []
        def finish(receipt, status, *args, **kwargs):
            attempts.append(status)
            result = original(receipt, status, *args, **kwargs)
            if status == 'posted':
                gate.wait()
            return result
        with patch.object(self.images, 'finish', finish):
            task = asyncio.create_task(self.worker.advance('a' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.sent, ['#AAA'])
        self.assertEqual(attempts, ['posted'])
        self.assertEqual(self.images.receipt('1' * 24)['status'], 'posted')


class ImageHTTPCancellation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = http_fixture.ImagePostTests.asyncSetUp
    asyncTearDown = http_fixture.ImagePostTests.asyncTearDown
    auth = http_fixture.ImagePostTests.auth
    call = http_fixture.ImagePostTests.call
    signup = http_fixture.ImagePostTests.signup
    revision = http_fixture.ImagePostTests.revision
    host = http_fixture.ImagePostTests.host
    publish = http_fixture.ImagePostTests.publish
    setup_post = http_fixture.ImagePostTests.setup_post
    republish = http_fixture.ImagePostTests.republish
    send = http_fixture.ImagePostTests.send

    @contextmanager
    def observe_handler(self):
        from cwl_web import roster_image_posts as feature
        original = feature.store
        self.handler = None
        def storage(request):
            self.handler = asyncio.current_task()
            return original(request)
        with patch.object(feature, 'store', storage), patch.object(feature, 'discord', self.fake):
            yield

    async def disconnect(self, request):
        from aiohttp import ServerDisconnectedError
        with self.assertRaises(ServerDisconnectedError):
            await request
        self.assertTrue(self.handler.cancelled())

    async def test_posted_finish_commit_is_not_downgraded_on_handler_cancel(self):
        await self.setup_post()
        gate = Gate()
        attempts = []
        original = RosterImageStore.finish
        def finish(storage, receipt, status, *args, **kwargs):
            attempts.append(status)
            result = original(storage, receipt, status, *args, **kwargs)
            if status == 'posted':
                gate.wait()
            return result
        with self.observe_handler(), patch.object(RosterImageStore, 'finish', finish):
            request = asyncio.create_task(self.send())
            await gate.started()
            self.handler.cancel('original')
            gate.release.set()
            await self.disconnect(request)
        self.assertEqual(attempts, ['posted'])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.app['store'].one('SELECT status,message_id FROM roster_image_posts'),
                         {'status': 'posted', 'message_id': '987654321098765432'})

    async def test_replacement_commit_cancel_closes_new_identity_and_never_reposts(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.assertEqual((await self.send()).status, 200)
        await self.republish()
        self.mode = '404'
        gate = Gate()
        original = RosterImageStore.repost_deleted
        replacements = []
        def replace(storage, receipt):
            result = original(storage, receipt)
            replacements.append(result['request_id'])
            gate.wait()
            return result
        with self.observe_handler(), patch.object(RosterImageStore, 'repost_deleted', replace):
            request = asyncio.create_task(self.send('/update'))
            await gate.started()
            self.handler.cancel('original')
            gate.release.set()
            await self.disconnect(request)
        rows = {r['request_id']: r for r in self.app['store'].rows('SELECT * FROM roster_image_requests')}
        self.assertEqual(rows['a' * 24]['status'], 'posted')
        self.assertEqual(rows['b' * 24]['status'], 'deleted_confirmed')
        self.assertEqual(rows['b' * 24]['replacement_request_id'], replacements[0])
        self.assertEqual(rows[replacements[0]]['status'], 'uncertain')
        self.assertEqual(self.app['store'].one('SELECT request_id,status FROM roster_image_posts'),
                         {'request_id': replacements[0], 'status': 'uncertain'})
        self.assertEqual([s[0] for s in self.sent], ['POST', 'PATCH'])
        with self.observe_handler():
            replay = await self.send('/update')
            self.assertEqual(replay.status, 503)
        self.assertEqual([s[0] for s in self.sent], ['POST', 'PATCH'])

    async def test_unacquired_foreign_claim_cancel_does_not_finish_foreign_receipt(self):
        await self.setup_post()
        gate = Gate()
        original = RosterImageStore.claim
        def claim(storage, *args, **kwargs):
            foreign = list(args)
            foreign[9] = '123456789012345670'
            original(storage, *foreign, **kwargs)
            result = original(storage, *args, **kwargs)
            self.assertFalse(result[1])
            gate.wait()
            return result
        with self.observe_handler(), patch.object(RosterImageStore, 'claim', claim):
            request = asyncio.create_task(self.send())
            await gate.started()
            self.handler.cancel('original')
            gate.release.set()
            await self.disconnect(request)
        self.assertEqual(self.sent, [])
        row = self.app['store'].one('SELECT actor_id,status FROM roster_image_requests')
        self.assertEqual(row, {'actor_id': '123456789012345670', 'status': 'sending'})


class ClosingCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = sequence_fixture.SequenceStoreTests.setUp

    async def asyncSetUp(self):
        from utils.cwl_roster_messages import closing_message
        self.args['plan'] = {'clans': [], 'closing': {
            'request_id': 'e' * 24, 'payload': closing_message()}}
        self.images.prepare_sequence(**self.args)
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        self.transport = NS(image=AsyncMock(), closing=AsyncMock(return_value='987654321098765432'))
        self.worker = SequenceWorker(self.images, self.transport, AsyncMock(return_value=True))

    async def asyncTearDown(self):
        await self.store.close_writer()

    async def test_closing_claim_commit_cancel_marks_only_owned_closing_uncertain(self):
        gate = Gate()
        original = self.images.claim_sequence_closing
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            gate.wait()
            return result
        with patch.object(self.images, 'claim_sequence_closing', claim):
            task = asyncio.create_task(self.worker.advance('a' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            with self.assertRaises(asyncio.CancelledError) as caught:
                await task
        self.assertEqual(caught.exception.args, ('original',))
        self.assertEqual(self.images.closing_receipt('a' * 24)['status'], 'uncertain')
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'stopped')
        self.transport.closing.assert_not_awaited()

    async def test_closing_posted_commit_cancel_keeps_complete_and_never_replays(self):
        gate = Gate()
        original = self.images.finish_sequence_closing
        attempts = []
        def finish(*args, **kwargs):
            attempts.append(kwargs['status'])
            result = original(*args, **kwargs)
            if kwargs['status'] == 'posted':
                gate.wait()
            return result
        with patch.object(self.images, 'finish_sequence_closing', finish):
            task = asyncio.create_task(self.worker.advance('a' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(attempts, ['posted'])
        self.assertEqual(self.images.closing_receipt('a' * 24)['status'], 'posted')
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'complete')
        await self.worker.advance('a' * 24)
        self.transport.closing.assert_awaited_once()


# Extra HTTP variants reuse only the fixture helpers, not the baseline test cases.
class AdditionalImageHTTPCancellation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ImageHTTPCancellation.asyncSetUp
    asyncTearDown = ImageHTTPCancellation.asyncTearDown
    auth, call = ImageHTTPCancellation.auth, ImageHTTPCancellation.call
    signup, revision = ImageHTTPCancellation.signup, ImageHTTPCancellation.revision
    host, publish = ImageHTTPCancellation.host, ImageHTTPCancellation.publish
    setup_post, republish = ImageHTTPCancellation.setup_post, ImageHTTPCancellation.republish
    send = ImageHTTPCancellation.send
    observe_handler, disconnect = ImageHTTPCancellation.observe_handler, ImageHTTPCancellation.disconnect

    async def test_queued_claim_cancel_has_no_receipt_or_transport(self):
        await self.setup_post()
        gate = Gate()
        store = self.app['store']
        original = store.run_writer
        blocker = asyncio.create_task(original(gate.wait))
        await gate.started()
        queued = asyncio.Event()
        async def observe(operation):
            if operation.__name__ == 'claim_image':
                queued.set()
            return await original(operation)
        with self.observe_handler(), patch.object(store, 'run_writer', observe):
            request = asyncio.create_task(self.send())
            try:
                await asyncio.wait_for(queued.wait(), 2)
                self.handler.cancel('original')
                await self.disconnect(request)
                self.assertEqual(store.rows('SELECT * FROM roster_image_requests'), [])
                self.assertEqual(self.sent, [])
            finally:
                gate.release.set()
                await blocker

    async def test_started_owned_claim_cancel_is_uncertain_without_transport(self):
        await self.setup_post()
        gate = Gate()
        original = RosterImageStore.claim
        def claim(storage, *args, **kwargs):
            result = original(storage, *args, **kwargs)
            gate.wait()
            return result
        with self.observe_handler(), patch.object(RosterImageStore, 'claim', claim):
            request = asyncio.create_task(self.send())
            await gate.started()
            self.handler.cancel('original')
            gate.release.set()
            await self.disconnect(request)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.app['store'].one('SELECT status FROM roster_image_requests')['status'], 'uncertain')
        with self.observe_handler():
            self.assertEqual((await self.send()).status, 503)
        self.assertEqual(self.sent, [])

    async def test_queued_known_posted_finish_survives_handler_cancellation(self):
        await self.setup_post()
        gate = Gate()
        store = self.app['store']
        original = store.run_writer
        queued = asyncio.Event()
        blocker = None
        async def observe(operation):
            if 'finish' in operation.__code__.co_names:
                queued.set()
            return await original(operation)
        original_fake = self.fake
        async def fake(request, method, path, **kwargs):
            nonlocal blocker
            result = await original_fake(request, method, path, **kwargs)
            if method == 'POST':
                blocker = asyncio.create_task(original(gate.wait))
                await gate.started()
            return result
        self.fake = fake
        with self.observe_handler(), patch.object(store, 'run_writer', observe):
            request = asyncio.create_task(self.send())
            try:
                await asyncio.wait_for(queued.wait(), 2)
                self.handler.cancel('original')
                await asyncio.sleep(.01)
                self.assertFalse(request.done())
                gate.release.set()
                await self.disconnect(request)
            finally:
                gate.release.set()
                if blocker:
                    await blocker
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(store.one('SELECT status,message_id FROM roster_image_posts'),
                         {'status': 'posted', 'message_id': '987654321098765432'})

    async def test_guarded_cleanup_cannot_downgrade_posted_or_foreign_receipt(self):
        await self.setup_post()
        with self.observe_handler():
            self.assertEqual((await self.send()).status, 200)
        images = RosterImageStore(self.app['store'])
        receipt = images.receipt('a' * 24)
        before = self.app['store'].rows('SELECT * FROM roster_image_requests')
        await cancel_image_claim(images, receipt)
        await cancel_image_claim(images, {**receipt, 'actor_id': 'foreign'})
        self.assertEqual(self.app['store'].rows('SELECT * FROM roster_image_requests'), before)
        self.assertEqual(self.app['store'].one('SELECT status FROM roster_image_posts')['status'], 'posted')

    async def test_queued_replacement_creates_no_new_receipt_and_cleans_only_prior_owned_claim(self):
        await self.setup_post()
        with patch('cwl_web.roster_image_posts.discord', self.fake):
            self.assertEqual((await self.send()).status, 200)
        await self.republish()
        gate = Gate()
        store = self.app['store']
        original = store.run_writer
        queued = asyncio.Event()
        blocker = None
        async def observe(operation):
            if operation.__name__ == 'replace_deleted':
                queued.set()
            return await original(operation)
        original_fake = self.fake
        async def fake(request, method, path, **kwargs):
            nonlocal blocker
            if method == 'PATCH':
                from cwl_web.server_management import DiscordItemNotFound
                self.sent.append((method, path, kwargs))
                blocker = asyncio.create_task(original(gate.wait))
                await gate.started()
                raise DiscordItemNotFound(10008)
            return await original_fake(request, method, path, **kwargs)
        self.fake = fake
        with self.observe_handler(), patch.object(store, 'run_writer', observe):
            request = asyncio.create_task(self.send('/update'))
            try:
                await asyncio.wait_for(queued.wait(), 2)
                self.handler.cancel('original')
                await asyncio.sleep(.01)
                gate.release.set()
                await self.disconnect(request)
            finally:
                gate.release.set()
                if blocker:
                    await blocker
        rows = self.app['store'].rows('SELECT request_id,status,replacement_request_id FROM roster_image_requests ORDER BY request_id')
        self.assertEqual(rows, [
            {'request_id': 'a' * 24, 'status': 'posted', 'replacement_request_id': None},
            {'request_id': 'b' * 24, 'status': 'uncertain', 'replacement_request_id': None},
        ])
        self.assertEqual([s[0] for s in self.sent], ['POST', 'PATCH'])


class AdditionalTestStepCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = TestStepCancellation.setUp
    prepare = TestStepCancellation.prepare
    worker = TestStepCancellation.worker
    cancelled = TestStepCancellation.cancelled
    asyncTearDown = TestStepCancellation.asyncTearDown

    async def test_cancelled_failed_claim_publish_rolls_back_without_cleanup_or_send(self):
        from utils.cwl_dashboard_state import MongoDashboardState
        from test_cwl_dashboard_state import Collection
        self.prepare()
        collection = Collection()
        owner = MongoDashboardState(collection)
        owner.seed(Path(self.store.path))
        owner.acquire()
        gate = Gate()
        original = owner.publish
        def publish(db):
            gate.wait()
            collection.fail = 'before'
            return original(db)
        self.store.durability = owner
        with patch.object(owner, 'publish', publish):
            task = asyncio.create_task(self.worker().advance('f' * 24))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            await self.cancelled(task)
        self.assertTrue(owner.poisoned)
        self.store.durability = None
        self.assertEqual(self.store.rows('SELECT * FROM roster_image_test_receipts'), [])
        self.assertEqual(self.images.test_sequence('f' * 24)['status'], 'ready')
        self.transport.test_announcement.assert_not_awaited()

    async def test_failed_uncertain_cleanup_keeps_original_transport_cancellation(self):
        from utils.cwl_dashboard_state import MongoDashboardState
        from test_cwl_dashboard_state import Collection
        self.prepare()
        collection = Collection()
        owner = MongoDashboardState(collection)
        owner.seed(Path(self.store.path))
        owner.acquire()
        self.store.durability = owner
        async def accepted(job, item):
            collection.fail = 'before'
            raise asyncio.CancelledError('accepted')
        task = asyncio.create_task(self.worker(AsyncMock(side_effect=accepted)).advance('f' * 24))
        await self.cancelled(task, 'accepted')
        self.assertTrue(owner.poisoned)
        self.store.durability = None
        self.assertEqual(self.images.test_sequence('f' * 24)['status'], 'sending')
        self.assertEqual(self.store.one('SELECT status FROM roster_image_test_receipts')['status'], 'sending')
        self.transport.test_announcement.assert_awaited_once()


class RetrySequenceCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = MainSequenceCancellation.setUp
    confirm = MainSequenceCancellation.confirm
    asyncTearDown = MainSequenceCancellation.asyncTearDown

    async def test_retry_claim_commit_cancel_keeps_original_nonce_without_transport(self):
        self.confirm()
        item = self.items[0]
        receipt, acquired = self.images.claim(1, 'lazy', item['tag'], 1, item['request_id'],
            'post', self.args['channel'], None, item['frozen'], self.args['actor'], sequence_id='a' * 24)
        self.assertTrue(acquired)
        self.images.finish(receipt, 'failed', error='Rate limit', retry_after=0, sequence_id='a' * 24)
        gate = Gate()
        original = self.images.retry_sequence_image
        def retry(*args, **kwargs):
            result = original(*args, **kwargs)
            gate.wait()
            return result
        with patch.object(self.images, 'retry_sequence_image', retry):
            task = asyncio.create_task(self.worker.advance('a' * 24, resume=True))
            await gate.started()
            task.cancel('original')
            gate.release.set()
            with self.assertRaises(asyncio.CancelledError) as caught:
                await task
        self.assertEqual(caught.exception.args, ('original',))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.images.receipt(item['request_id'])['status'], 'uncertain')
        self.assertEqual(len(self.store.rows('SELECT * FROM roster_image_requests')), 1)


class QueuedClosingCancellation(unittest.IsolatedAsyncioTestCase):
    setUp = ClosingCancellation.setUp
    asyncSetUp = ClosingCancellation.asyncSetUp
    asyncTearDown = ClosingCancellation.asyncTearDown

    async def test_queued_known_closing_finish_persists_complete_before_cancel(self):
        gate = Gate()
        queued = asyncio.Event()
        blocker = None
        original = self.store.run_writer
        async def observe(operation):
            if 'finish_sequence_closing' in operation.__code__.co_names:
                queued.set()
            return await original(operation)
        async def send(job, item):
            nonlocal blocker
            blocker = asyncio.create_task(original(gate.wait))
            await gate.started()
            return '987654321098765432'
        self.transport.closing = AsyncMock(side_effect=send)
        with patch.object(self.store, 'run_writer', observe):
            task = asyncio.create_task(self.worker.advance('a' * 24))
            try:
                await asyncio.wait_for(queued.wait(), 2)
                task.cancel('original')
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                gate.release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                gate.release.set()
                if blocker:
                    await blocker
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'complete')
        self.assertEqual(self.images.closing_receipt('a' * 24)['status'], 'posted')
        self.transport.closing.assert_awaited_once()
