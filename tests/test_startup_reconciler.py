import asyncio

from utils.startup_reconciler import ERROR_DETAIL_LIMIT, StartupReconciler


def test_reconciler_recovers_with_capped_backoff(capsys):
    attempts = 0
    sleeps = []

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise RuntimeError("Mongo temporarily unavailable")

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def scenario():
        reconciler = StartupReconciler(
            "test-monitor",
            operation,
            retry_delays=(5, 15),
            sleep=fake_sleep,
        )
        task = reconciler.start()
        await task
        return reconciler

    reconciler = asyncio.run(scenario())

    assert attempts == 4
    assert sleeps == [5, 15, 15]
    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 4
    assert reconciler.health.last_error is None
    output = capsys.readouterr().out
    assert "startup_reconcile_retry" in output
    assert "startup_reconcile_recovered" in output


def test_duplicate_start_does_not_duplicate_operation():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    async def scenario():
        reconciler = StartupReconciler("single", operation)
        first = reconciler.start()
        second = reconciler.start()
        assert first is second
        await entered.wait()
        release.set()
        await first
        assert reconciler.start() is first
        return reconciler

    reconciler = asyncio.run(scenario())

    assert calls == 1
    assert reconciler.health.state == "healthy"


def test_stop_cancels_retry_sleep_cleanly():
    sleeping = asyncio.Event()

    async def operation():
        raise RuntimeError("offline")

    async def blocked_sleep(_delay):
        sleeping.set()
        await asyncio.Event().wait()

    async def scenario():
        reconciler = StartupReconciler(
            "cancel",
            operation,
            retry_delays=(5,),
            sleep=blocked_sleep,
        )
        reconciler.start()
        await sleeping.wait()
        await reconciler.stop()
        return reconciler

    reconciler = asyncio.run(scenario())

    assert reconciler.task is None
    assert reconciler.health.state == "stopped"


def test_error_detail_is_single_line_and_bounded(capsys):
    observed = []

    async def operation():
        if not observed:
            observed.append(True)
            raise RuntimeError(
                "mongodb://user:pass@db.example/app?access_token=abc "
                + "x" * 300
                + "\nprivate-tail"
            )

    async def no_wait(_delay):
        return None

    async def scenario():
        reconciler = StartupReconciler(
            "bounded",
            operation,
            retry_delays=(0,),
            sleep=no_wait,
        )
        await reconciler.start()
        return reconciler

    reconciler = asyncio.run(scenario())

    assert reconciler.health.state == "healthy"
    retry_line = next(
        line for line in capsys.readouterr().out.splitlines()
        if "startup_reconcile_retry" in line
    )
    detail = retry_line.split("detail=", 1)[1]
    assert len(detail) <= ERROR_DETAIL_LIMIT
    assert "user:pass" not in detail
    assert "access_token=abc" not in detail
    assert "access_token=***" in detail
    assert "private-tail" not in detail
