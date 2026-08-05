"""Regression tests for bounded /todo session bookkeeping."""

import asyncio
from types import SimpleNamespace

from utils import todo_sessions


class _Collection:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    async def create_index(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary Mongo outage")
        return "ttl_expires_at"


class _Mongo:
    def __init__(self, failures=0):
        self.todo_sessions = _Collection(failures)


def test_ttl_index_retries_after_backoff(monkeypatch):
    mongo = _Mongo(failures=1)
    clock = {"now": 100.0}
    monkeypatch.setattr(
        todo_sessions, "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
    )
    monkeypatch.setattr(todo_sessions, "_index_ready", False)
    monkeypatch.setattr(todo_sessions, "_index_failed", False)
    monkeypatch.setattr(todo_sessions, "_index_retry_at", 0.0)

    async def exercise():
        await todo_sessions.ensure_indexes(mongo)
        await todo_sessions.ensure_indexes(mongo)
        clock["now"] = 3701.0
        await todo_sessions.ensure_indexes(mongo)

    asyncio.run(exercise())

    assert mongo.todo_sessions.calls == 2
    assert todo_sessions._index_ready is True
    assert todo_sessions._index_failed is False
