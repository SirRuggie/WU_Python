"""Exercise real asyncio deadlines at accelerated fixture time; no network or DB."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from utils import manage_web_worker as worker
from utils.member_profile_runs import ProfileRuns


class AcceleratedLoop(asyncio.SelectorEventLoop):
    """Preserve timer semantics while mapping 125 fixture seconds to 1.25s."""

    speed = 100

    def __init__(self):
        super().__init__()
        original = self._selector
        speed = self.speed

        class Selector:
            def select(self, timeout=None):
                return original.select(
                    None if timeout is None else timeout / speed
                )

            def __getattr__(self, name):
                return getattr(original, name)

        self._selector = Selector()

    def time(self):
        return super().time() * self.speed


@pytest.mark.parametrize(
    ("section", "action", "expected"),
    [
        ("member_profiles", "save", "done"),
        ("fwa_points", "enable", "uncertain"),
    ],
)
def test_profile_work_can_outlast_120_seconds_but_other_sections_cannot(
    monkeypatch, section, action, expected
):
    async def exercise():
        row = dict(
            _id="local-budget-fixture",
            kind="manage_web_request",
            status="pending",
            section=section,
            action=action,
            values={},
            user_id="123456789012345678",
            guild_id=worker.GUILD_ID,
            created_at=time.time(),
        )
        collection = SimpleNamespace(
            find_one_and_update=AsyncMock(side_effect=[row, None]),
            update_many=AsyncMock(),
            update_one=AsyncMock(),
        )
        completed = []

        async def dispatch(*args):
            await asyncio.sleep(125)
            completed.append(True)
            return {"message": "Local fixture completed"}

        monkeypatch.setattr(worker, "context", AsyncMock())
        monkeypatch.setattr(worker, "dispatch", dispatch)
        monkeypatch.setattr(ProfileRuns, "advance", AsyncMock())
        started = asyncio.get_running_loop().time()
        await worker._process_requests(
            None, SimpleNamespace(bot_config=collection)
        )
        elapsed = asyncio.get_running_loop().time() - started
        update = collection.update_one.await_args.args[1]["$set"]
        assert update["status"] == expected
        assert bool(completed) == (expected == "done")
        if expected == "done":
            assert elapsed >= 125
        else:
            assert elapsed >= 120

    def loop_factory():
        loop = AcceleratedLoop()
        asyncio.set_event_loop(loop)
        return loop

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(exercise())
