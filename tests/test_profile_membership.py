import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from extensions.warrior import profile_membership as service


def test_complete_snapshot_repairs_offline_departure_without_sliding_ttl(monkeypatch):
    async def run():
        left = datetime.now(timezone.utc) - timedelta(days=2)
        store = S(
            membership_rows=AsyncMock(
                return_value=[
                    {"_id": "1", "left_at": None},
                    {"_id": "2", "left_at": left},
                ]
            ),
            membership=AsyncMock(),
        )
        monkeypatch.setattr(service, "MemberProfiles", lambda mongo: store)

        async def members(guild):
            yield S(id=1)

        result = await service.reconcile(
            S(rest=S(fetch_members=members), get_me=lambda: S(id=1)), object()
        )
        assert result == {"profiles": 2, "present": 1, "absent": 1}
        assert store.membership.await_args_list[0].kwargs["left_at"] is None
        assert store.membership.await_args_list[1].kwargs["left_at"] == left
        assert all(
            "observed_at" in call.kwargs for call in store.membership.await_args_list
        )

    asyncio.run(run())


def test_partial_directory_failure_never_marks_anyone_departed(monkeypatch):
    async def run():
        store = S(
            membership_rows=AsyncMock(return_value=[{"_id": "1"}]),
            membership=AsyncMock(),
        )
        monkeypatch.setattr(service, "MemberProfiles", lambda mongo: store)

        async def broken(guild):
            yield S(id=1)
            raise RuntimeError("paged directory unavailable")

        with pytest.raises(RuntimeError):
            await service.reconcile(S(rest=S(fetch_members=broken)), object())
        store.membership.assert_not_awaited()

    asyncio.run(run())


def test_empty_profiles_skip_directory_and_owned_task_stops(monkeypatch):
    async def run():
        store = S(membership_rows=AsyncMock(return_value=[]))
        monkeypatch.setattr(service, "MemberProfiles", lambda mongo: store)
        fetch = AsyncMock()
        assert (await service.reconcile(S(rest=S(fetch_members=fetch)), object()))[
            "profiles"
        ] == 0
        fetch.assert_not_called()
        gate = asyncio.Event()

        # A running owned coroutine is cancelled during shutdown, not duplicated.
        async def blocked(*args):
            await gate.wait()
            return {"profiles": 0, "present": 0, "absent": 0}

        monkeypatch.setattr(service, "reconcile", blocked)
        service.start(object(), object())
        task = service._task
        await asyncio.sleep(0)
        service.start(object(), object())
        assert service._task is task
        await service.stop()
        assert task.cancelled() and service._task is None

    asyncio.run(run())


def test_empty_directory_for_existing_profiles_is_not_trusted(monkeypatch):
    async def run():
        store = S(
            membership_rows=AsyncMock(return_value=[{"_id": "1"}]),
            membership=AsyncMock(),
        )
        monkeypatch.setattr(service, "MemberProfiles", lambda mongo: store)

        async def empty(guild):
            for member in ():
                yield member

        with pytest.raises(ValueError, match="did not include the bot"):
            await service.reconcile(
                S(rest=S(fetch_members=empty), get_me=lambda: S(id=9)), object()
            )
        store.membership.assert_not_awaited()

    asyncio.run(run())
