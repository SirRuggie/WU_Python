"""Regression tests for bounded /todo session bookkeeping."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError

from utils import todo_sessions


class _Collection:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0
        self.indexes = []
        self.updates = []
        self.inserts = []
        self.delete_one_queries = []
        self.delete_many_queries = []
        self.find_query = None
        self.find_one_query = None
        self.documents = []
        self.update_result = None
        self.delete_result = None
        self.find_failure = None
        self.insert_failure = None
        self.sort_args = None
        self.limit_value = None

    async def create_index(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary Mongo outage")
        self.indexes.append((args, kwargs))
        return kwargs.get("name")

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        if self.update_result is not None:
            return self.update_result
        return SimpleNamespace(
            matched_count=0 if upsert else 1,
            upserted_id=query.get("_id") if upsert else None,
        )

    async def insert_one(self, document):
        if self.insert_failure:
            raise self.insert_failure
        self.inserts.append(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def delete_one(self, query):
        self.delete_one_queries.append(query)
        return self.delete_result or SimpleNamespace(deleted_count=1)

    async def delete_many(self, query):
        self.delete_many_queries.append(query)
        return SimpleNamespace(deleted_count=1)

    def find(self, query):
        self.find_query = query
        return self

    def sort(self, *args):
        self.sort_args = args
        return self

    def limit(self, *args):
        self.limit_value = args[0]
        return self

    async def to_list(self, length=None):
        return list(self.documents)

    async def find_one(self, query):
        self.find_one_query = query
        if self.find_failure:
            raise self.find_failure
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

    assert mongo.todo_sessions.calls == 3
    assert todo_sessions._index_ready is True
    assert todo_sessions._index_failed is False
    assert [kwargs["name"] for _args, kwargs in mongo.todo_sessions.indexes] == [
        "ttl_expires_at", "due_active_next_refresh",
    ]


def test_claim_creates_one_owner_with_exact_30_day_deadline(monkeypatch):
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(todo_sessions, "_index_ready", True)
    monkeypatch.setattr(
        todo_sessions, "time",
        SimpleNamespace(time=lambda: now.timestamp(), monotonic=lambda: 0.0),
    )

    claimed = asyncio.run(todo_sessions.claim(
        mongo,
        user_id=1,
        channel_id=2,
        message_id=3,
        view="war",
        expected_owner=None,
    ))

    assert claimed is not None
    generation, until = claimed
    assert until == now + timedelta(days=30)
    assert mongo.todo_sessions.updates == []
    fields = mongo.todo_sessions.inserts[0]
    assert fields["_id"] == "dm:1:2"
    assert fields["message_id"] == 3
    assert fields["generation"] == generation
    assert fields["active"] is True
    assert fields["next_refresh_at"] == now + timedelta(minutes=10)
    assert fields["refresh_until"] == now + timedelta(days=30)
    assert fields["expires_at"] == now + timedelta(days=30)


def test_first_claim_is_insert_only_and_duplicate_key_loses_race(monkeypatch):
    mongo = _Mongo()
    mongo.todo_sessions.insert_failure = DuplicateKeyError("winner inserted")
    monkeypatch.setattr(todo_sessions, "_index_ready", True)

    claimed = asyncio.run(todo_sessions.claim(
        mongo, user_id=1, channel_id=2, message_id=8, view="war",
        expected_owner=None,
    ))

    assert claimed is None
    assert mongo.todo_sessions.updates == []


def test_claim_uses_generation_cas_and_reports_lost_race(monkeypatch):
    mongo = _Mongo()
    mongo.todo_sessions.update_result = SimpleNamespace(
        matched_count=0, upserted_id=None
    )
    monkeypatch.setattr(todo_sessions, "_index_ready", True)
    owner = {"generation": "old", "message_id": 7}

    claimed = asyncio.run(todo_sessions.claim(
        mongo, user_id=1, channel_id=2, message_id=8, view="war",
        expected_owner=owner,
    ))

    assert claimed is None
    query, _update, upsert = mongo.todo_sessions.updates[0]
    assert query == {
        "_id": "dm:1:2", "generation": "old", "message_id": 7,
    }
    assert upsert is False


def test_owner_read_failure_is_distinct_from_no_existing_owner():
    mongo = _Mongo()
    mongo.todo_sessions.find_failure = RuntimeError("Mongo unavailable")

    succeeded, owner = asyncio.run(todo_sessions.read_owner(
        mongo, user_id=1, channel_id=2
    ))

    assert succeeded is False
    assert owner is None
    assert mongo.todo_sessions.find_one_query == {"_id": "dm:1:2"}


def test_due_query_only_selects_active_unexpired_dm_panels():
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    mongo.todo_sessions.documents = [{"_id": "dm:1:2", "message_id": 3}]

    result = asyncio.run(todo_sessions.due(mongo, observed_at=now))

    assert result == [{"_id": "dm:1:2", "message_id": 3}]
    assert mongo.todo_sessions.find_query == {
        "is_dm": True,
        "active": True,
        "next_refresh_at": {"$lte": now},
        "refresh_until": {"$gt": now},
    }
    assert mongo.todo_sessions.sort_args == ("next_refresh_at", 1)
    assert mongo.todo_sessions.limit_value == todo_sessions.REFRESH_BATCH_SIZE


def test_background_refresh_does_not_extend_retention():
    mongo = _Mongo()
    checked = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    result = asyncio.run(todo_sessions.mark_refreshed(
        mongo, "dm:1:2", 3, "gen", checked_at=checked
    ))

    assert result is True
    query = mongo.todo_sessions.updates[0][0]
    assert query == {
        "_id": "dm:1:2", "message_id": 3,
        "generation": "gen", "active": True,
    }
    fields = mongo.todo_sessions.updates[0][1]["$set"]
    assert fields["last_checked_at"] == checked
    assert fields["next_refresh_at"] == checked + timedelta(minutes=10)
    assert "refresh_until" not in fields
    assert "expires_at" not in fields


def test_only_explicit_renewal_creates_an_exact_30_day_window():
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    assert todo_sessions.new_refresh_until(observed_at=now) == (
        now + timedelta(days=30)
    )


def test_navigation_updates_schedule_but_never_retention():
    mongo = _Mongo()
    checked = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    result = asyncio.run(todo_sessions.update_navigation(
        mongo, owner_id="dm:1:2", message_id=3, generation="gen",
        view="cwl", page=2, kind="dashboard", trigger="view:cwl",
        checked_at=checked,
    ))

    assert result is True
    fields = mongo.todo_sessions.updates[0][1]["$set"]
    assert fields["view"] == "cwl"
    assert fields["page"] == 2
    assert fields["next_refresh_at"] == checked + timedelta(minutes=10)
    assert "refresh_until" not in fields
    assert "expires_at" not in fields


def test_stale_generation_cannot_postpone_or_remove_replacement():
    mongo = _Mongo()
    mongo.todo_sessions.update_result = SimpleNamespace(
        matched_count=0, upserted_id=None
    )
    mongo.todo_sessions.delete_result = SimpleNamespace(deleted_count=0)

    postponed = asyncio.run(todo_sessions.postpone(
        mongo, "dm:1:2", 3, "stale"
    ))
    removed = asyncio.run(todo_sessions.remove(
        mongo, "dm:1:2", 3, "stale"
    ))

    assert postponed is False
    assert removed is False
    assert mongo.todo_sessions.delete_one_queries == [{
        "_id": "dm:1:2", "message_id": 3, "generation": "stale",
    }]


def test_legacy_rows_are_identified_and_cleaned_without_current_owner():
    mongo = _Mongo()
    documents = [{"_id": 11}, {"_id": 12}, {"_id": "dm:1:2", "message_id": 13}]

    cleaned = asyncio.run(todo_sessions.remove_legacy_rows(mongo, documents))

    assert cleaned is True
    assert [todo_sessions.panel_message_id(doc) for doc in documents] == [11, 12, 13]
    assert mongo.todo_sessions.delete_many_queries == [{"_id": {"$in": [11, 12]}}]
