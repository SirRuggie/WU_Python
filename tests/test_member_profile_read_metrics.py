"""Public monitoring is numeric, concurrent-task isolated and non-authoritative."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace as S
from pymongo import monitoring
from utils.mongo_read_metrics import NumericReadListener, collect, CURRENT


def test_monitor_collects_only_numeric_totals_and_resets_context():
    listener = NumericReadListener()
    with collect() as value:
        listener.connection_checked_out(
            monitoring.ConnectionCheckedOutEvent(("private", 1), 1, 0.012)
        )
        listener.started(S(command={"private": "never read"}))
        listener.succeeded(
            monitoring.CommandSucceededEvent(
                timedelta(milliseconds=8),
                {"private": "never read"},
                "find",
                7,
                ("private", 1),
                1,
            )
        )
        assert value.checkouts == value.commands == value.responses == 1
        assert value.checkout_ms == 12 and value.command_ms == 8
        assert value.first_response_ms >= 0
        assert all(isinstance(v, (int, float)) for v in vars(value).values())
    assert CURRENT.get() is None


def test_monitor_concurrent_tasks_do_not_share_request_metrics():
    async def run():
        listener = NumericReadListener()

        async def read(count):
            with collect() as value:
                for _ in range(count):
                    listener.started(S())
                    await asyncio.sleep(0)
                return value.commands

        assert await asyncio.gather(read(2), read(7)) == [2, 7]

    asyncio.run(run())
