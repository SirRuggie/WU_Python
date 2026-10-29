"""Background timing keeps slow Mongo off member requests."""
import asyncio
import time
import sqlite3
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

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
    yield SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value={"campaign": {}})))


class MemberTimingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await foundation.WebFoundationTests.asyncSetUp(self)
        clock = patch.object(timing, 'datetime', wraps=datetime)
        fake = clock.start()
        fake.now.return_value = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.addCleanup(clock.stop)
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call
    season = foundation.WebFoundationTests.season

    async def setup_bound(self):
        task = self.app['member_timing_state']['task']
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
            task = self.app['member_timing_state']['task']
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
            if cycle == '2026-09':
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

    async def test_sqlite_failure_logs_once_then_next_pass_populates_and_closes_cleanly(self):
        sid = await self.setup_bound()
        real_bindings = timing.eligible_bindings
        calls = 0

        def bindings(app):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError('database is locked')
            return real_bindings(app)

        value = {'campaign': {'signup_deadline': {'at': '2026-10-30T21:00:00Z'}}}
        with patch.object(timing, 'eligible_bindings', side_effect=bindings), patch.object(timing, 'REFRESH_SECONDS', .001), patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', return_value=value), patch.object(timing.LOG, 'exception') as log:
            lifecycle = timing.lifecycle(self.app)
            await anext(lifecycle)
            try:
                async with asyncio.timeout(.5):
                    while sid not in self.app['member_timing_cache']:
                        await asyncio.sleep(.001)
                self.assertGreaterEqual(calls, 2)
                self.assertEqual(log.call_count, 1)
            finally:
                await lifecycle.aclose()

    async def test_worker_guards_unexpected_refresh_failure_and_shutdown(self):
        await self.setup_bound()
        recovered = asyncio.Event()
        calls = 0

        async def pass_once(app):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError('disk I/O error')
            recovered.set()

        with patch.object(timing, 'refresh', side_effect=pass_once), patch.object(timing, 'REFRESH_SECONDS', .001), patch.object(timing.LOG, 'exception') as log:
            lifecycle = timing.lifecycle(self.app)
            await anext(lifecycle)
            try:
                await asyncio.wait_for(recovered.wait(), .5)
                self.assertEqual(log.call_count, 1)
            finally:
                await lifecycle.aclose()

    async def test_three_slow_seasons_each_get_their_own_budget(self):
        await self.setup_bound()

        async def slow(*args):
            await asyncio.sleep(.03)
            return {'campaign': {'signup_deadline': None}}

        with patch.object(timing, 'eligible_bindings', return_value={1: '2026-10', 2: '2026-11', 3: '2026-10'}), patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', side_effect=slow), patch.object(timing, 'SEASON_TIMEOUT_SECONDS', .05), patch.object(timing, 'PASS_TIMEOUT_SECONDS', .2):
            await timing.refresh(self.app)
        self.assertEqual(set(self.app['member_timing_cache']), {1, 2, 3})

    async def test_season_timeout_does_not_starve_next_season(self):
        await self.setup_bound()

        async def load(mongo, guild, cycle):
            if cycle == '2026-09':
                await asyncio.Event().wait()
            return {'campaign': {'signup_deadline': None}}

        with patch.object(timing, 'eligible_bindings', return_value={1: '2026-10', 2: '2026-11'}), patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', side_effect=load), patch.object(timing, 'SEASON_TIMEOUT_SECONDS', .01), patch.object(timing, 'PASS_TIMEOUT_SECONDS', .3):
            await asyncio.wait_for(timing.refresh(self.app), .2)
        self.assertEqual(set(self.app['member_timing_cache']), {2})

    async def test_whole_pass_timeout_bounds_context_entry_and_retains_cache(self):
        sid = await self.setup_bound()
        original = (time.monotonic(), '2026-10', timing.utc_timing('2026-10-30T21:00:00Z'))
        self.app['member_timing_cache'][sid] = original

        @asynccontextmanager
        async def blocked(request):
            await asyncio.Event().wait()
            yield SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value={"campaign": {}})))

        with patch.object(timing, '_mongo', blocked), patch.object(timing, 'PASS_TIMEOUT_SECONDS', .01), patch.object(timing.LOG, 'exception') as log:
            await asyncio.wait_for(timing.refresh(self.app), .2)
            self.assertEqual(log.call_count, 1)
        self.assertEqual(self.app['member_timing_cache'][sid], original)

    async def test_eligibility_excludes_old_and_far_future_except_member_season(self):
        sid = await self.setup_bound()
        with self.app['store'].tx() as db:
            for ident, cycle in [(90, '2026-09'), (91, '2026-11'), (92, '2027-01')]:
                db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES(?,?,'archived',0)", (ident, cycle))
                db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES(?,?)', (ident, cycle))
            db.execute('UPDATE member_season SET season_id=90 WHERE id=1')
        self.assertEqual(timing.eligible_bindings(self.app), {sid: '2026-10', 90: '2026-09', 91: '2026-11'})


    async def test_bound_cwl_month_uses_previous_campaign_and_january_rolls_year(self):
        sid = await self.setup_bound()
        campaign = {'timezone': 'America/New_York', 'signup_deadline': {'month_end_offset_days': 2, 'hour': 17}}
        for bound, earlier, expected in [('2026-11', '2026-10', '2026-10-29T21:00:00+00:00'),
                                         ('2027-01', '2026-12', '2026-12-29T22:00:00+00:00')]:
            with patch.object(timing, 'eligible_bindings', return_value={sid: bound}), patch.object(timing, '_mongo', fake_mongo), patch.object(timing, 'load_campaign', return_value={'campaign': campaign}) as load:
                await timing.refresh(self.app)
                load.assert_awaited_once()
                self.assertEqual(load.call_args.args[2], earlier)
                self.assertEqual((await self.read(sid))['signup_deadline'], expected)

    async def test_missing_previous_campaign_clears_deadline_without_synthesized_defaults(self):
        sid = await self.setup_bound()
        @asynccontextmanager
        async def missing(request):
            yield SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=None)))
        with patch.object(timing, '_mongo', missing), patch.object(timing, 'load_campaign') as load:
            await timing.refresh(self.app)
            self.assertEqual(await self.read(sid), timing.utc_timing(None))
            load.assert_not_called()
