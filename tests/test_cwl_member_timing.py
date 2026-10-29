"""Background timing keeps slow Mongo off member requests."""
import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import test_cwl_web_foundation as foundation
from cwl_web import member_timing as timing


def test_utc_math_and_null_never_produce_naive_dates():
    assert timing.utc_timing(None) == {'signup_deadline': None, 'placements_by': None}
    assert timing.utc_timing('2026-10-30T17:00:00') == timing.utc_timing(None)
    for at, expected in [('2026-10-30T17:00:00-04:00', '2026-10-31T21:00:00+00:00'),
                         ('2026-10-31T17:00:00-04:00', '2026-11-01T21:00:00+00:00'),
                         ('2026-03-07T17:00:00-05:00', '2026-03-08T22:00:00+00:00')]:
        result = timing.utc_timing(at)
        assert result['placements_by'] == expected
        start, end = (datetime.fromisoformat(result[k]) for k in ('signup_deadline', 'placements_by'))
        assert start.utcoffset() == end.utcoffset() == timedelta(0)
        assert end - start == timedelta(hours=24)


@asynccontextmanager
async def fake_mongo(request):
    yield object()


class MemberTimingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.WebFoundationTests.asyncSetUp
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call
    season = foundation.WebFoundationTests.season

    async def setup_bound(self):
        task = self.app['member_timing_task']
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        sid = await self.season()
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES(?,?)', (sid, '2026-10'))
        return sid

    async def read(self, sid):
        return await timing.season_timing(SimpleNamespace(app=self.app), sid)

    async def test_slow_20_second_mongo_never_blocks_seasons_or_calls_per_request(self):
        sid = await self.setup_bound()
        entered = asyncio.Event()

        async def slow(*args):
            entered.set()
            await asyncio.sleep(20)

        with patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', side_effect=slow) as load:
            worker = asyncio.create_task(timing.refresh(self.app))
            await entered.wait()
            try:
                for _ in range(3):
                    start = time.monotonic()
                    response = await self.call('GET', '/seasons', self.owner)
                    self.assertEqual(response.status, 200)
                    self.assertLess(time.monotonic() - start, .2)
                    self.assertIsNone((await self.read(sid))['signup_deadline'])
                self.assertEqual(load.call_count, 1)
            finally:
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker

    async def test_first_lifecycle_refresh_populates_without_blocking_startup_and_shutdown_cancels(self):
        sid = await self.setup_bound()
        entered, release = asyncio.Event(), asyncio.Event()

        async def load(*args):
            entered.set()
            await release.wait()
            return {'campaign': {'signup_deadline': {'at': '2026-10-30T17:00:00-04:00'}}}

        with patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', side_effect=load):
            lifecycle = timing.lifecycle(self.app)
            await asyncio.wait_for(anext(lifecycle), .2)
            await entered.wait()
            self.assertIsNone((await self.read(sid))['signup_deadline'])
            release.set()
            for _ in range(20):
                if self.app['member_timing_cache']:
                    break
                await asyncio.sleep(0)
            self.assertEqual((await self.read(sid))['signup_deadline'], '2026-10-30T21:00:00+00:00')
            task = self.app['member_timing_task']
            await lifecycle.aclose()
            self.assertTrue(task.cancelled())

    async def test_failures_keep_good_until_six_hours_and_isolate_seasons(self):
        sid = await self.setup_bound()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES(99,'Other','draft',1)")
            db.execute("INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES(99,'2026-11')")
            before = list(db.iterdump())
        value = timing.utc_timing('2026-10-30T21:00:00Z')
        self.app['member_timing_cache'][sid] = (1000, '2026-10', value)

        async def load(mongo, guild, cycle):
            if cycle == '2026-10':
                raise ValueError('bad fake campaign')
            return {'campaign': {'signup_deadline': {'at': '2026-11-30T21:00:00Z'}}}

        with patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', side_effect=load), patch.object(timing.time, 'monotonic', return_value=1001) as clock:
            await timing.refresh(self.app)
            self.assertEqual(await self.read(sid), value)
            self.assertEqual((await self.read(99))['signup_deadline'], '2026-11-30T21:00:00+00:00')
            clock.return_value = 1000 + 6 * 3600 - 1
            self.assertEqual(await self.read(sid), value)
            clock.return_value += 1
            self.assertEqual(await self.read(sid), timing.utc_timing(None))
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()), before)

    async def test_closed_published_and_changed_binding_never_leak_cached_dates(self):
        sid = await self.setup_bound()
        self.app['member_timing_cache'][sid] = (time.monotonic(), 'wrong-cycle', timing.utc_timing('2026-10-30T21:00:00Z'))
        self.assertEqual(await self.read(sid), timing.utc_timing(None))
        with self.app['store'].tx() as db:
            db.execute('UPDATE seasons SET signup_open=0 WHERE id=?', (sid,))
            db.execute("INSERT INTO roster_publications(season_id,version,revision,published_by,published_at,joining_instructions,assigned_count,unassigned_count,clans_json) VALUES(?,1,0,'test','2026-01-01','',0,0,'[]')", (sid,))
        with patch.object(timing, '_mongo') as mongo:
            await timing.refresh(self.app)
            self.assertEqual(await self.read(sid), timing.utc_timing(None))
            mongo.assert_not_called()
