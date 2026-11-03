"""Pure row work cannot block the HTTP loop, leak concurrency or poison recovery."""

import asyncio
import threading
import pytest
from cwl_web.member_row_work import RowWork


def test_rows_run_off_loop_and_recover_after_error():
    async def run():
        worker = RowWork()
        assert await worker.run(threading.get_ident) != threading.get_ident()

        def broken():
            raise ValueError("Fixture row error")

        with pytest.raises(ValueError, match="Fixture row error"):
            await worker.run(broken)
        assert await worker.run(lambda: {"value": "recovered"}) == {
            "value": "recovered"
        }
        await worker.close()
        assert not worker.active
        with pytest.raises(RuntimeError, match="shutting down"):
            await worker.run(lambda: None)

    asyncio.run(run())


def test_cancelled_reader_does_not_release_active_thread_or_execute_cancelled_queue():
    async def run():
        worker = RowWork()
        entered, release = threading.Event(), threading.Event()
        queued_started = threading.Event()

        def slow():
            entered.set()
            assert release.wait(3), "Owned fixture release was not signalled"
            return "finished"

        first = asyncio.create_task(worker.run(slow))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            assert worker.gate.locked() and len(worker.active) == 1
            queued = asyncio.create_task(worker.run(queued_started.set))
            await asyncio.sleep(0)
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert not queued_started.is_set()
            closing = asyncio.create_task(worker.close())
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await asyncio.wait_for(closing, 2)
            assert not worker.active and not queued_started.is_set()
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await worker.close()

    asyncio.run(run())


def test_shutdown_refuses_work_already_waiting_behind_active_snapshot():
    async def run():
        worker = RowWork()
        entered, release = threading.Event(), threading.Event()
        queued_started = threading.Event()

        def slow():
            entered.set()
            assert release.wait(3)

        first = asyncio.create_task(worker.run(slow))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            queued = asyncio.create_task(worker.run(queued_started.set))
            await asyncio.sleep(0)
            closing = asyncio.create_task(worker.close())
            await asyncio.sleep(0)
            release.set()
            await first
            await closing
            with pytest.raises(RuntimeError, match="shutting down"):
                await queued
            assert not queued_started.is_set()
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await worker.close()

    asyncio.run(run())
