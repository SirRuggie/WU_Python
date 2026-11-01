import asyncio
import logging
import time
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from utils import manage_web_worker as worker
from utils.member_profile_runs import ProfileRuns


def test_idle_fast_check_is_one_projected_indexed_query(monkeypatch):
    async def run():
        coll = S(
            find_one=AsyncMock(return_value=None), create_index=AsyncMock()
        )
        mongo = S(bot_config=coll)
        for _ in range(3):
            await worker.fast_poll(None, mongo)
        assert coll.find_one.await_count == 3
        assert coll.create_index.await_count == 1
        call = coll.find_one.await_args
        assert call.kwargs["hint"] == "management_ready_work"
        assert call.args[1] == {"_id": 1, "kind": 1, "next_at": 1}

    asyncio.run(run())


def test_pruning_is_at_most_once_per_minute(monkeypatch):
    async def run():
        store = ProfileRuns(S(bot_config=None))
        monkeypatch.setattr(store, "prune", AsyncMock())
        for at in [100, 101, 120, 159, 160]:
            await store.prune_throttled(at)
        assert store.prune.await_count == 2

    asyncio.run(run())


def test_other_sections_keep_five_per_ten_seconds_and_dispatch_budget(
    monkeypatch,
):
    async def run():
        rows = [
            dict(
                _id=str(i),
                kind="manage_web_request",
                status="pending",
                section="fwa_points",
                action="enable",
                guild_id=worker.GUILD_ID,
                user_id="123",
                values={},
                revision="x",
                created_at=time.time(),
            )
            for i in range(50)
        ]

        async def claim(query, *args, **kwargs):
            for row in rows:
                if row["status"] == "pending" and (
                    "section" not in query
                    or row["section"] == query["section"]
                ):
                    row["status"] = "running"
                    return row

        coll = S(
            find_one_and_update=AsyncMock(side_effect=claim),
            update_many=AsyncMock(),
            update_one=AsyncMock(),
        )
        mongo = S(bot_config=coll)
        monkeypatch.setattr(ProfileRuns, "advance", AsyncMock())
        monkeypatch.setattr(worker, "context", AsyncMock())
        dispatch = AsyncMock(return_value={"message": "ok"})
        monkeypatch.setattr(worker, "dispatch", dispatch)
        original = asyncio.wait_for
        budgets = []

        async def wait(coro, timeout):
            budgets.append(timeout)
            return await original(coro, timeout)

        monkeypatch.setattr(worker.asyncio, "wait_for", wait)
        await worker._process_requests(None, mongo)
        await worker._process_requests(None, mongo)
        assert dispatch.await_count == 5
        assert budgets == [120] * 5
        assert len([r for r in rows if r["status"] == "pending"]) == 45

    asyncio.run(run())


def test_only_fast_job_execution_logs_are_filtered():
    from extensions.tasks import cwl_reminder as bridge

    bridge._silence_fast_job_logs()
    logger = logging.getLogger("apscheduler.executors.default")
    fast = logging.LogRecord(
        logger.name,
        logging.INFO,
        "",
        1,
        'Job "_poll_web_management_fast" executed successfully',
        (),
        None,
    )
    other = logging.LogRecord(
        logger.name,
        logging.INFO,
        "",
        1,
        'Job "_poll_web_roster_requests" executed successfully',
        (),
        None,
    )
    assert not logger.filter(fast)
    assert logger.filter(other)


def test_bridge_and_management_share_the_same_lane(monkeypatch):
    from extensions.tasks import cwl_reminder as bridge

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def cwl():
            entered.set()
            await release.wait()

        monkeypatch.setattr(bridge, "_poll_web_roster_bridge", cwl)
        monkeypatch.setattr(bridge, "bot_instance", None)
        monkeypatch.setattr(bridge, "mongo_client", None)
        process = AsyncMock(return_value=0)
        monkeypatch.setattr(worker, "_process_requests", process)
        monkeypatch.setattr(
            worker, "ready_work", AsyncMock(return_value={"_id": "pending"})
        )
        task = asyncio.create_task(bridge._poll_web_roster_requests())
        await entered.wait()
        assert await worker.poll(None, None, fast=True) == 0
        process.assert_not_awaited()
        release.set()
        await task

    asyncio.run(run())


def test_rate_limit_receipt_defers_next_member(monkeypatch):
    async def run():
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            state="queued",
            cursor=0,
            items=[{}, {}],
            next_at=0,
        )
        child = dict(status="uncertain", finished_at=100, retry_not_before=180)
        coll = S(
            find_one=AsyncMock(side_effect=[parent, child]),
            update_one=AsyncMock(),
        )
        store = ProfileRuns(S(bot_config=coll))
        monkeypatch.setattr(store, "prune_throttled", AsyncMock())
        await store.advance(now=100)
        assert coll.update_one.await_args.args[1]["$set"]["next_at"] == 180

    asyncio.run(run())


def test_long_rate_limit_receipt_retains_delay_and_never_retries(monkeypatch):
    import hikari

    async def run():
        row = dict(
            _id="rate",
            kind="manage_web_request",
            status="pending",
            section="member_profiles",
            action="save",
            guild_id=worker.GUILD_ID,
            user_id="123",
            values={},
            created_at=time.time(),
        )
        coll = S(
            find_one_and_update=AsyncMock(side_effect=[row, None]),
            update_many=AsyncMock(),
            update_one=AsyncMock(),
        )
        monkeypatch.setattr(ProfileRuns, "advance", AsyncMock())
        monkeypatch.setattr(worker, "context", AsyncMock())
        error = hikari.RateLimitTooLongError(
            route=S(),
            is_global=False,
            retry_after=90,
            max_retry_after=20,
            reset_at=0,
            limit=1,
            period=90,
        )
        dispatch = AsyncMock(side_effect=error)
        monkeypatch.setattr(worker, "dispatch", dispatch)
        before = time.time()
        await worker._process_requests(None, S(bot_config=coll))
        update = coll.update_one.await_args.args[1]["$set"]
        assert update["status"] == "uncertain"
        assert update["retry_not_before"] >= before + 90
        dispatch.assert_awaited_once()

    asyncio.run(run())
