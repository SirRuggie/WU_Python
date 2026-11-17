"""Intentional unresolved reservation policy survives cancellation unchanged."""
import asyncio
from contextlib import contextmanager
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

from test_delivery_writer_cancellation import Gate
import test_cwl_web_announcements as announcement_fixture
import test_cwl_bonus_raffle as raffle_fixture
import test_cwl_lazy_infractions as infractions_fixture
import test_cwl_lazy_bonus_announcement as lazy_fixture
import test_cwl_web_push as push_fixture


def fixture_methods(fixture):
    def decorate(target):
        for name, value in vars(fixture).items():
            if not name.startswith('__') and not name.startswith('test_') and name not in vars(target):
                setattr(target, name, value)
        return target
    return decorate


class ReservationHTTP:
    async def cancel_at_publish(self, request, predicate, capture_callback):
        from aiohttp import ServerDisconnectedError
        gate = Gate()
        store = self.app['store']
        handler = None
        used = False
        original = store.run_tx
        async def observed(operation):
            nonlocal handler
            if operation.__name__ == capture_callback:
                handler = asyncio.current_task()
            return await original(operation)
        class Owner:
            def check(self):
                pass
            def publish(self, db):
                nonlocal used
                if not used and predicate(db):
                    used = True
                    gate.wait()
        store.durability = Owner()
        with patch.object(store, 'run_tx', observed):
            task = asyncio.create_task(request)
            try:
                await gate.started()
                self.assertIsNotNone(handler)
                handler.cancel('original')
                gate.release.set()
                with self.assertRaises(ServerDisconnectedError):
                    await task
                self.assertTrue(handler.cancelled())
            finally:
                gate.release.set()
                store.durability = None


@fixture_methods(announcement_fixture.AnnouncementTests)
class AnnouncementReservationCancellation(ReservationHTTP, unittest.IsolatedAsyncioTestCase):
    async def test_claim_await_cancel_leaves_existing_unresolved_intent_and_no_post(self):
        version = await self.publish()
        await self.set_channel('main', announcement_fixture.MAIN_CHANNEL)
        await self.cancel_at_publish(
            self.send('main', version, announcement_fixture.MAIN_CHANNEL),
            lambda db: db.execute("SELECT 1 FROM announcement_deliveries WHERE status='sending'").fetchone(),
            '_send_announcement_transaction_2')
        self.assertEqual(self.app['store'].one('SELECT status FROM announcement_deliveries')['status'], 'sending')
        self.assertEqual(self.transport.calls, [])
        self.assertEqual((await self.send('main', version, announcement_fixture.MAIN_CHANNEL)).status, 409)
        self.assertEqual(self.transport.calls, [])

    async def test_known_sent_result_is_retained_when_final_write_is_cancelled(self):
        version = await self.publish()
        await self.set_channel('main', announcement_fixture.MAIN_CHANNEL)
        await self.cancel_at_publish(
            self.send('main', version, announcement_fixture.MAIN_CHANNEL),
            lambda db: db.execute("SELECT 1 FROM announcement_deliveries WHERE status='sent'").fetchone(),
            '_send_announcement_transaction_2')
        self.assertEqual(self.app['store'].one('SELECT status FROM announcement_deliveries')['status'], 'sent')
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual((await self.send('main', version, announcement_fixture.MAIN_CHANNEL)).status, 200)
        self.assertEqual(len(self.transport.calls), 1)


@fixture_methods(raffle_fixture.RaffleTests)
class RaffleReservationCancellation(ReservationHTTP, unittest.IsolatedAsyncioTestCase):
    async def test_reservation_cancel_never_sends_or_replays(self):
        await self.ready()
        draw = await self.approve(await self.draw())
        await self.cancel_at_publish(self.send(draw),
            lambda db: db.execute("SELECT 1 FROM bonus_raffle_deliveries WHERE status='sending'").fetchone(),
            '_send_transaction_3')
        self.assertEqual(self.app['store'].one('SELECT status FROM bonus_raffle_deliveries')['status'], 'sending')
        self.assertEqual(self.transport.calls, [])
        await self.send(draw)
        self.assertEqual(self.transport.calls, [])

    async def test_page_sent_commit_cancel_retains_confirmed_page_without_conflicting_cleanup(self):
        await self.ready()
        draw = await self.approve(await self.draw())
        await self.cancel_at_publish(self.send(draw),
            lambda db: db.execute("SELECT 1 FROM bonus_raffle_pages WHERE status='sent'").fetchone(),
            '_send_transaction_3')
        self.assertEqual(self.app['store'].one('SELECT status FROM bonus_raffle_deliveries')['status'], 'sending')
        page = self.app['store'].one('SELECT status,message_id FROM bonus_raffle_pages WHERE page=0')
        self.assertEqual(page, {'status': 'sent', 'message_id': '900000000000000001'})
        self.assertEqual(len(self.transport.calls), 1)
        await self.send(draw)
        self.assertEqual(len(self.transport.calls), 1)


@fixture_methods(infractions_fixture.LazyInfractionsApiTests)
class InfractionsReservationCancellation(ReservationHTTP, unittest.IsolatedAsyncioTestCase):
    async def test_claim_await_cancel_preserves_unresolved_audit_and_blocks_replay(self):
        await self.asyncSetUpLazy()
        await self.flag('#P2Y', ['lingering'])
        preview = await self.preview()
        await self.cancel_at_publish(self.send_now(preview),
            lambda db: db.execute("SELECT 1 FROM bonus_audit WHERE action='lazy_infractions_announcement' AND json_extract(after_json,'$.status')='sending'").fetchone(),
            '_send_transaction_2')
        self.assertEqual([r['status'] for r in self.audit()], ['sending'])
        self.assertEqual(self.transport.calls, [])
        await self.send_now(preview, status=409)
        self.assertEqual(self.transport.calls, [])

    async def test_known_final_audit_cancel_retains_sent_and_prevents_duplicate(self):
        await self.asyncSetUpLazy()
        await self.flag('#P2Y', ['lingering'])
        preview = await self.preview()
        await self.cancel_at_publish(self.send_now(preview),
            lambda db: db.execute("SELECT 1 FROM bonus_audit WHERE action='lazy_infractions_announcement' AND json_extract(after_json,'$.status')='sent'").fetchone(),
            '_send_transaction_2')
        self.assertEqual([r['status'] for r in self.audit()], ['sending', 'sent'])
        count = len(self.transport.calls)
        self.assertGreater(count, 0)
        await self.send_now(preview)
        self.assertEqual(len(self.transport.calls), count)


@fixture_methods(lazy_fixture.LazyAnnouncementTests)
class BonusAnnouncementReservationCancellation(ReservationHTTP, unittest.IsolatedAsyncioTestCase):
    async def test_claim_await_cancel_preserves_unresolved_audit_and_blocks_replay(self):
        await self.approved_lazy()
        preview = await self.preview()
        await self.cancel_at_publish(self.send_now(preview),
            lambda db: db.execute("SELECT 1 FROM bonus_audit WHERE action='lazy_bonus_announcement' AND json_extract(after_json,'$.status')='sending'").fetchone(),
            '_send_transaction_2')
        self.assertEqual([r['status'] for r in self.audit()], ['sending'])
        self.assertEqual(self.transport.calls, [])
        await self.send_now(preview, status=409)
        self.assertEqual(self.transport.calls, [])

    async def test_known_final_audit_cancel_retains_sent_and_prevents_duplicate(self):
        await self.approved_lazy()
        preview = await self.preview()
        await self.cancel_at_publish(self.send_now(preview),
            lambda db: db.execute("SELECT 1 FROM bonus_audit WHERE action='lazy_bonus_announcement' AND json_extract(after_json,'$.status')='sent'").fetchone(),
            '_send_transaction_2')
        self.assertEqual([r['status'] for r in self.audit()], ['sending', 'sent'])
        count = len(self.transport.calls)
        self.assertGreater(count, 0)
        await self.send_now(preview)
        self.assertEqual(len(self.transport.calls), count)


@fixture_methods(push_fixture.PushTests)
class PushReservationCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_claim_await_cancellation_retains_dedup_and_no_notification(self):
        from cwl_web import push
        await self.save()
        now = int(time.time())
        with self.app['store'].tx() as db:
            db.execute('UPDATE push_subscriptions SET updated_at=?', (now-100,))
        snapshot = push_fixture.snapshot(now)
        snapshot['views']['war']['rows'] = snapshot['views']['war']['rows'][:2]
        gate = Gate()
        class Owner:
            def check(self):
                pass
            def publish(self, db):
                if db.execute('SELECT 1 FROM push_deliveries').fetchone():
                    gate.wait()
        self.app['store'].durability = Owner()
        with patch.object(push, 'fresh', AsyncMock(return_value=snapshot)), patch.object(push, 'send', return_value='sent') as send:
            task = asyncio.create_task(push.process_user(self.app, '100'))
            try:
                await gate.started()
                task.cancel('original')
                gate.release.set()
                with self.assertRaises(asyncio.CancelledError) as caught:
                    await task
                self.assertEqual(caught.exception.args, ('original',))
            finally:
                gate.release.set()
                self.app['store'].durability = None
            self.assertEqual(len(self.app['store'].rows('SELECT * FROM push_deliveries')), 1)
            send.assert_not_called()
            await push.process_user(self.app, '100')
            send.assert_not_called()
