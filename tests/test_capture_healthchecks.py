"""Capture progress/outage policy uses existing observations, never probes."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace as S
from unittest.mock import patch
import unittest

from aiohttp import web
import pytest

from cwl_web import participation_sync as sync
from cwl_web.healthchecks import CapturePass, record_capture
import test_participation_waiting as waiting


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"clans": [], "groups": set(), "wars": set(), "waiting": set()}, True),
        ({"clans": [1], "groups": {1}, "wars": set(), "waiting": set()}, True),
        ({"clans": [1], "groups": set(), "wars": {1}, "waiting": set()}, True),
        ({"clans": [1], "groups": set(), "wars": set(), "waiting": {1}}, True),
        ({"clans": [1], "groups": set(), "wars": set(), "waiting": set()}, False),
    ],
)
def test_capture_progress_rule_and_manual_force_exclusion(values, expected):
    observed = []
    record_capture(observed.append, force=False, **values)
    assert observed == [expected]
    record_capture(observed.append, force=True, **values)
    assert observed == [expected]


class Store:
    def __init__(self, ids):
        self.ids = ids
        self.reads = 0

    @contextmanager
    def tx(self):
        def execute(query):
            assert "participation_sync_settings" in query
            self.reads += 1
            return S(fetchall=lambda: [{"season_id": value} for value in self.ids])

        yield S(execute=execute)


@pytest.mark.parametrize(
    "scenarios,expected",
    [
        ([], True),
        (["success"], True),
        (["failed"], False),
        (["failed", "success"], True),
        (["success", "crash"], False),
        (["changed"], True),
        (["invalid"], False),
    ],
)
def test_ordinary_worker_reports_one_pass_without_new_reads_or_calls(
    scenarios, expected
):
    async def run():
        calls, steps = [], 0
        store = Store(range(len(scenarios)))

        async def sleep(seconds):
            nonlocal steps
            assert seconds == sync.INTERVAL_SECONDS
            steps += 1
            if steps == 2:
                raise asyncio.CancelledError()

        async def capture(app, season, *, observe):
            kind = scenarios[season]
            if kind == "crash":
                raise RuntimeError("PRIVATE_URL")
            if kind == "changed":
                raise web.HTTPConflict()
            if kind == "invalid":
                raise web.HTTPBadRequest()
            observe(kind == "success")

        app = {"store": store, "capture_external_heartbeat": S(submit=calls.append)}
        with patch.object(
            sync, "asyncio", S(sleep=sleep, CancelledError=asyncio.CancelledError)
        ), patch.object(sync, "sync_season", capture):
            with pytest.raises(asyncio.CancelledError):
                await sync._worker(app)
        assert calls == [expected] and store.reads == 1

    asyncio.run(run())


def test_unset_capture_adds_no_reads_or_forced_calls():
    async def run():
        store, calls, steps = Store([1]), [], 0

        async def sleep(seconds):
            nonlocal steps
            steps += 1
            if steps == 2:
                raise asyncio.CancelledError()

        async def capture(app, season):
            calls.append(season)

        with patch.object(
            sync, "asyncio", S(sleep=sleep, CancelledError=asyncio.CancelledError)
        ), patch.object(sync, "sync_season", capture):
            with pytest.raises(asyncio.CancelledError):
                await sync._worker({"store": store})
        assert calls == [1] and store.reads == 1

    asyncio.run(run())


def test_database_worker_crash_fails_once_then_propagates():
    async def run():
        calls = []

        @contextmanager
        def broken():
            raise RuntimeError("fixture storage failure")
            yield

        async def sleep(seconds):
            pass

        with patch.object(
            sync, "asyncio", S(sleep=sleep, CancelledError=asyncio.CancelledError)
        ):
            with pytest.raises(RuntimeError, match="fixture storage"):
                await sync._worker(
                    {
                        "store": S(tx=broken),
                        "capture_external_heartbeat": S(submit=calls.append),
                    }
                )
        assert calls == [False]

    asyncio.run(run())


class CaptureEntryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = waiting.WaitingTests.asyncSetUp
    asyncTearDown = waiting.WaitingTests.asyncTearDown
    auth = waiting.WaitingTests.auth
    call = waiting.WaitingTests.call
    revision = waiting.WaitingTests.revision
    signup = waiting.WaitingTests.signup
    setup_published = waiting.WaitingTests.setup_published
    set_group = waiting.WaitingTests.set_group
    set_war = waiting.WaitingTests.set_war
    account = waiting.WaitingTests.account
    prepare = waiting.WaitingTests.prepare
    base = waiting.WaitingTests.base

    async def enabled(self):
        await self.prepare()
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE participation_sync_settings SET enabled=1 WHERE season_id=?",
                (self.sid,),
            )

    async def capture(self, observed, *, force=False):
        with patch.object(sync, "datetime", waiting.November):
            return await sync.sync_season(
                self.app, self.sid, force=force, observe=observed.append
            )

    async def test_real_capture_progress_then_all_fail_is_not_hidden_by_cache(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], state="WAR", season="2026-11")
        self.set_war("#Y2Y", state="WAR")
        observed = []
        first = await self.capture(observed)
        assert set(first) == {"sync", "updated_accounts"} and observed == [True]
        self.league.fail_groups.add("#C2Y")
        self.league.fail_wars.add("#Y2Y")
        second = await self.capture(observed)
        assert second["sync"]["status"] == "stale" and observed == [True, False]

    async def test_stale_with_fresh_war_is_progress_not_total_failure(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], state="WAR", season="2026-11")
        self.set_war("#Y2Y", state="WAR")
        observed = []
        await self.capture(observed)
        self.league.fail_groups.add("#C2Y")
        result = await self.capture(observed)
        assert result["sync"]["status"] == "stale" and observed == [True, True]

    async def test_real_wait_is_success_and_manual_force_never_records(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], season="2026-10")
        observed = []
        result = await self.capture(observed)
        assert result["sync"]["status"] == "waiting" and observed == [True]
        await self.capture(observed, force=True)
        assert observed == [True]

    async def test_observer_exception_cannot_change_capture_result(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], state="WAR", season="2026-11")
        self.set_war("#Y2Y", state="WAR")

        def broken(value):
            raise RuntimeError("PRIVATE_HEALTHCHECK_URL")

        with patch.object(sync, "datetime", waiting.November):
            result = await sync.sync_season(self.app, self.sid, observe=broken)
        assert result["updated_accounts"] > 0

    async def captured_finished_month(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], state="ENDED", season="2026-11")
        self.set_war("#Y2Y", state="ENDED")
        observed = []
        await self.capture(observed)
        assert observed == [True]
        self.league.war_calls.clear()
        return observed

    async def test_finished_month_not_in_war_on_november_twenty_fifth_is_success(self):
        observed = await self.captured_finished_month()
        self.set_group([], state="NOT_IN_WAR", season="2026-11")

        class LateNovember(waiting.November):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 25, 12, tzinfo=waiting.timezone.utc)

        with patch.object(sync, "datetime", LateNovember):
            result = await sync.sync_season(self.app, self.sid, observe=observed.append)
        assert result["sync"]["status"] == "stale"
        assert observed == [True, True] and self.league.war_calls == []

    async def test_finished_month_later_group_on_december_third_is_success(self):
        observed = await self.captured_finished_month()
        self.set_group([["#J2Y"]], state="PREPARATION", season="2026-12")

        class December(waiting.November):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 12, 3, 12, tzinfo=waiting.timezone.utc)

        with patch.object(sync, "datetime", December):
            result = await sync.sync_season(self.app, self.sid, observe=observed.append)
        assert result["sync"]["status"] == "season_mismatch"
        assert observed == [True, True] and self.league.war_calls == []

    async def test_valid_old_group_and_no_group_with_no_work_are_finished(self):
        observed = await self.captured_finished_month()
        self.set_group([["#Y2Y"]], season="2026-08")
        await self.capture(observed)
        from cwl_web.providers import ProviderUnavailable

        async def no_group(tag):
            error = ProviderUnavailable("No group")
            error.status_code = 404
            raise error

        self.providers.league_group = no_group
        await self.capture(observed)
        assert observed == [True, True, True] and self.league.war_calls == []

    async def test_valid_no_group_does_not_hide_pending_failed_war(self):
        await self.enabled()
        self.set_group([["#Y2Y"]], state="WAR", season="2026-11")
        self.set_war("#Y2Y", state="WAR")
        observed = []
        await self.capture(observed)
        self.set_group([], state="NOT_IN_WAR", season="2026-11")
        self.league.fail_wars.add("#Y2Y")
        await self.capture(observed)
        assert observed == [True, False]
