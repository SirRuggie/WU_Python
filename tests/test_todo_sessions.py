"""Regression tests for bounded /todo session bookkeeping."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from utils import todo_sessions


class _Collection:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0
        self.updates = []
        self.delete_one_queries = []
        self.find_query = None
        self.find_one_query = None
        self.documents = []

    async def create_index(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary Mongo outage")
        return "ttl_expires_at"

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        return SimpleNamespace()

    async def delete_one(self, query):
        self.delete_one_queries.append(query)
        return SimpleNamespace()

    def find(self, query):
        self.find_query = query
        return self

    def sort(self, *args):
        return self

    def limit(self, *args):
        return self

    async def to_list(self, length=None):
        return list(self.documents)

    async def find_one(self, query):
        self.find_one_query = query
        return self.documents[0] if self.documents else None


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


def test_dm_record_schedules_panel_and_uses_event_deadline(monkeypatch):
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    requested = now + timedelta(hours=48)
    monkeypatch.setattr(todo_sessions, "_index_ready", True)
    monkeypatch.setattr(
        todo_sessions, "time",
        SimpleNamespace(time=lambda: now.timestamp(), monotonic=lambda: 0.0),
    )

    written = asyncio.run(todo_sessions.record(
        mongo,
        user_id=1,
        channel_id=2,
        message_id=3,
        view="war",
        refresh_until=requested,
    ))

    assert written is True
    query, update, upsert = mongo.todo_sessions.updates[0]
    assert query == {"_id": 3}
    assert upsert is True
    fields = update["$set"]
    assert fields["active"] is True
    assert fields["next_refresh_at"] == now + timedelta(minutes=10)
    assert fields["refresh_until"] == requested
    assert fields["expires_at"] == requested


def test_due_query_only_selects_active_unexpired_dm_panels():
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    mongo.todo_sessions.documents = [{"_id": 3}]

    result = asyncio.run(todo_sessions.due(mongo, observed_at=now))

    assert result == [{"_id": 3}]
    assert mongo.todo_sessions.find_query == {
        "is_dm": True,
        "active": True,
        "next_refresh_at": {"$lte": now},
        "refresh_until": {"$gt": now},
    }


def test_background_refresh_does_not_extend_retention():
    mongo = _Mongo()
    checked = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    asyncio.run(todo_sessions.mark_refreshed(mongo, 3, checked_at=checked))

    fields = mongo.todo_sessions.updates[0][1]["$set"]
    assert fields["last_checked_at"] == checked
    assert fields["next_refresh_at"] == checked + timedelta(minutes=10)
    assert "refresh_until" not in fields
    assert "expires_at" not in fields


def test_refresh_window_is_bounded_between_24_and_72_hours():
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    default = todo_sessions.bounded_refresh_until(None, observed_at=now)
    too_long = todo_sessions.bounded_refresh_until(
        now + timedelta(days=10), observed_at=now
    )
    too_short = todo_sessions.bounded_refresh_until(
        now + timedelta(hours=1), observed_at=now
    )
    already_past = todo_sessions.bounded_refresh_until(
        now - timedelta(hours=1), observed_at=now
    )

    assert default == now + timedelta(hours=24)
    assert too_long == now + timedelta(hours=72)
    assert too_short == now + timedelta(hours=24)
    assert already_past == now + timedelta(hours=24)
