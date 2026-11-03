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


def test_diagnostic_logging_failure_does_not_change_profile_read(monkeypatch):
    from utils.member_profiles import MemberProfiles
    import logging

    class Cursor:
        def batch_size(self, count):
            return self

        def limit(self, count):
            return self

        async def to_list(self, **kwargs):
            return [{"discord_id": "800000000000000001"}]

    collection = S(find=lambda *args: Cursor())

    def unavailable(*args):
        raise RuntimeError("diagnostic unavailable")

    monkeypatch.setattr(logging.getLogger("utils.member_profiles"), "info", unavailable)

    async def run():
        result = await MemberProfiles(S(member_profiles=collection)).for_members(
            ["800000000000000001"], display_only=True
        )
        assert result == {"800000000000000001": {"discord_id": "800000000000000001"}}
        assert CURRENT.get() is None

    asyncio.run(run())
