import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from utils import poll_store


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if not isinstance(expected, dict):
            if actual != expected:
                return False
            continue
        if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
            return False
        if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
            return False
    return True


def _set_path(document, path, value):
    current = document
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = deepcopy(value)


class _Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]
        self.requested_length = None

    def sort(self, field, direction):
        self.documents.sort(
            key=lambda document: document.get(field), reverse=direction < 0
        )
        return self

    def limit(self, length):
        self.documents = self.documents[:length]
        return self

    async def to_list(self, *, length):
        self.requested_length = length
        if length is None:
            return deepcopy(self.documents)
        return deepcopy(self.documents[:length])


class _Collection:
    def __init__(self, documents=()):
        self.documents = {
            document["_id"]: deepcopy(document) for document in documents
        }
        self.index_calls = []
        self.atomic_calls = []

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((deepcopy(keys), deepcopy(kwargs)))
        return kwargs.get("name")

    async def insert_one(self, document):
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return _Cursor(
            document
            for document in self.documents.values()
            if _matches(document, query)
        )

    async def find_one_and_update(self, query, update, **kwargs):
        self.atomic_calls.append((
            deepcopy(query), deepcopy(update), deepcopy(kwargs)
        ))
        for document in self.documents.values():
            if not _matches(document, query):
                continue
            for path, value in update.get("$set", {}).items():
                _set_path(document, path, value)
            return deepcopy(document)
        return None


class _Mongo:
    def __init__(self, documents=()):
        self.discord_polls = _Collection(documents)


def _poll(
    poll_id,
    *,
    guild_id=1,
    active=True,
    ends_at=NOW + timedelta(hours=1),
    created_at=NOW,
):
    return {
        "_id": poll_id,
        "guild_id": guild_id,
        "active": active,
        "ends_at": ends_at,
        "created_at": created_at,
        "votes": {},
    }


def test_ensure_indexes_covers_guild_views_due_work_and_ended_retention():
    mongo = _Mongo()

    asyncio.run(poll_store.ensure_indexes(mongo))

    assert mongo.discord_polls.index_calls == [
        (
            [("guild_id", 1), ("active", 1), ("ends_at", 1)],
            {"name": poll_store.GUILD_ACTIVE_END_INDEX},
        ),
        (
            [("active", 1), ("ends_at", 1)],
            {"name": poll_store.DUE_END_INDEX},
        ),
        (
            "purge_at",
            {"expireAfterSeconds": 0, "name": poll_store.PURGE_INDEX},
        ),
        (
            [("message_sync_pending", 1), ("updated_at", 1)],
            {"name": poll_store.SYNC_PENDING_INDEX},
        ),
    ]


def test_create_poll_keeps_active_rows_durable_and_does_not_mutate_input():
    mongo = _Mongo()
    source = {
        "_id": "poll-1",
        "guild_id": "7",
        "ends_at": NOW + timedelta(hours=2),
        "title": "Choose a card",
        "active": False,
        "ended_at": NOW,
        "ended_reason": "stale",
        "purge_at": NOW + timedelta(days=1),
    }
    original = deepcopy(source)

    created = asyncio.run(
        poll_store.create_poll(mongo, source, observed_at=NOW)
    )

    assert source == original
    assert created["guild_id"] == 7
    assert created["active"] is True
    assert created["created_at"] == NOW
    assert created["updated_at"] == NOW
    assert created["votes"] == {}
    assert created["message_sync_pending"] is False
    assert "ended_at" not in created
    assert "ended_reason" not in created
    assert "purge_at" not in created
    assert mongo.discord_polls.documents["poll-1"] == created


def test_get_and_recent_list_never_cross_guilds():
    mongo = _Mongo([
        _poll("g1-old", guild_id=1, created_at=NOW - timedelta(hours=2)),
        _poll("g1-new", guild_id=1, created_at=NOW - timedelta(hours=1)),
        _poll("g2", guild_id=2, created_at=NOW),
    ])

    wrong_guild = asyncio.run(
        poll_store.get_poll(mongo, guild_id=1, poll_id="g2")
    )
    recent = asyncio.run(
        poll_store.list_recent_polls(mongo, guild_id=1, limit=1)
    )

    assert wrong_guild is None
    assert [poll["_id"] for poll in recent] == ["g1-new"]


def test_active_list_is_guild_scoped_unexpired_sorted_and_limited():
    mongo = _Mongo([
        _poll("later", guild_id=1, ends_at=NOW + timedelta(hours=2)),
        _poll("soon", guild_id=1, ends_at=NOW + timedelta(minutes=5)),
        _poll("expired", guild_id=1, ends_at=NOW),
        _poll("ended", guild_id=1, active=False),
        _poll("other-guild", guild_id=2, ends_at=NOW + timedelta(minutes=1)),
    ])

    active = asyncio.run(
        poll_store.list_active_polls(
            mongo, guild_id=1, observed_at=NOW, limit=2
        )
    )

    assert [poll["_id"] for poll in active] == ["soon", "later"]


def test_open_list_returns_unexpired_active_polls_across_guilds_for_restart():
    mongo = _Mongo([
        _poll("guild-2-first", guild_id=2, ends_at=NOW + timedelta(minutes=5)),
        _poll("guild-1-second", guild_id=1, ends_at=NOW + timedelta(hours=1)),
        _poll("expired", guild_id=1, ends_at=NOW),
        _poll("ended", guild_id=2, active=False),
    ])

    open_polls = asyncio.run(
        poll_store.list_open_polls(mongo, observed_at=NOW, limit=10)
    )

    assert [poll["_id"] for poll in open_polls] == [
        "guild-2-first", "guild-1-second",
    ]


def test_record_vote_is_one_atomic_active_unexpired_guild_scoped_write():
    mongo = _Mongo([
        _poll("live", guild_id=1),
        _poll("expired", guild_id=1, ends_at=NOW),
        _poll("ended", guild_id=1, active=False),
    ])

    voted = asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=1,
        poll_id="live",
        user_id=42,
        choice=2,
        observed_at=NOW,
    ))
    wrong_guild = asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=2,
        poll_id="live",
        user_id=99,
        choice=1,
        observed_at=NOW,
    ))
    expired = asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=1,
        poll_id="expired",
        user_id=99,
        choice=1,
        observed_at=NOW,
    ))
    ended = asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=1,
        poll_id="ended",
        user_id=99,
        choice=1,
        observed_at=NOW,
    ))

    assert voted["votes"] == {"42": 2}
    assert voted["message_sync_pending"] is True
    assert voted["updated_at"] == NOW
    assert wrong_guild is None
    assert expired is None
    assert ended is None
    assert mongo.discord_polls.documents["live"]["votes"] == {"42": 2}
    first_query, first_update, _ = mongo.discord_polls.atomic_calls[0]
    assert first_query == {
        "_id": "live",
        "guild_id": 1,
        "active": True,
        "ends_at": {"$gt": NOW},
    }
    assert first_update["$set"]["votes.42"] == 2
    assert first_update["$set"]["message_sync_pending"] is True


def test_record_vote_replaces_one_users_choice_without_adding_a_second_ballot():
    mongo = _Mongo([_poll("live", guild_id=1)])

    asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=1,
        poll_id="live",
        user_id=42,
        choice=1,
        observed_at=NOW,
    ))
    changed = asyncio.run(poll_store.record_vote(
        mongo,
        guild_id=1,
        poll_id="live",
        user_id=42,
        choice=3,
        observed_at=NOW + timedelta(seconds=1),
    ))

    assert changed["votes"] == {"42": 3}
    assert mongo.discord_polls.documents["live"]["votes"] == {"42": 3}


def test_end_poll_is_atomic_and_starts_retention_only_once():
    mongo = _Mongo([_poll("poll-1", guild_id=1)])

    ended = asyncio.run(poll_store.end_poll(
        mongo,
        guild_id=1,
        poll_id="poll-1",
        reason="manual",
        observed_at=NOW,
    ))
    second = asyncio.run(poll_store.end_poll(
        mongo,
        guild_id=1,
        poll_id="poll-1",
        reason="expired",
        observed_at=NOW + timedelta(minutes=1),
    ))

    assert ended["active"] is False
    assert ended["ended_at"] == NOW
    assert ended["ended_reason"] == "manual"
    assert ended["purge_at"] == NOW + timedelta(days=30)
    assert ended["message_sync_pending"] is True
    assert ended["message_sync_error"] is None
    assert second is None
    stored = mongo.discord_polls.documents["poll-1"]
    assert stored["ended_reason"] == "manual"
    assert stored["purge_at"] == NOW + timedelta(days=30)


def test_due_list_is_global_active_due_sorted_and_limited():
    mongo = _Mongo([
        _poll("oldest", guild_id=1, ends_at=NOW - timedelta(hours=2)),
        _poll("newer", guild_id=2, ends_at=NOW - timedelta(minutes=1)),
        _poll("boundary", guild_id=3, ends_at=NOW),
        _poll("future", guild_id=1, ends_at=NOW + timedelta(seconds=1)),
        _poll("already-ended", guild_id=1, active=False, ends_at=NOW - timedelta(days=1)),
    ])

    due = asyncio.run(
        poll_store.list_due_polls(mongo, observed_at=NOW, limit=2)
    )

    assert [poll["_id"] for poll in due] == ["oldest", "newer"]


def test_pending_message_sync_is_global_for_recovery_and_state_updates_are_guild_scoped():
    pending = _poll("pending", guild_id=1)
    pending.update({"message_sync_pending": True, "updated_at": NOW})
    other = _poll("other", guild_id=2)
    other.update({
        "message_sync_pending": True,
        "updated_at": NOW + timedelta(seconds=1),
    })
    mongo = _Mongo([pending, other, _poll("clean", guild_id=1)])

    listed = asyncio.run(poll_store.list_pending_message_sync(mongo, limit=10))
    wrong_guild = asyncio.run(poll_store.mark_message_synced(
        mongo, guild_id=2, poll_id="pending", observed_at=NOW,
    ))
    transient = asyncio.run(poll_store.mark_message_sync_pending(
        mongo,
        guild_id=1,
        poll_id="pending",
        error="ServerHTTPError",
        observed_at=NOW + timedelta(seconds=2),
    ))
    synced = asyncio.run(poll_store.mark_message_synced(
        mongo,
        guild_id=1,
        poll_id="pending",
        observed_at=NOW + timedelta(seconds=3),
    ))
    unavailable = asyncio.run(poll_store.mark_message_unavailable(
        mongo,
        guild_id=2,
        poll_id="other",
        error="NotFoundError",
        observed_at=NOW + timedelta(seconds=4),
    ))

    assert [document["_id"] for document in listed] == ["pending", "other"]
    assert wrong_guild is None
    assert transient["message_sync_pending"] is True
    assert transient["message_sync_error"] == "ServerHTTPError"
    assert synced["message_sync_pending"] is False
    assert synced["message_synced_at"] == NOW + timedelta(seconds=3)
    assert unavailable["message_sync_pending"] is False
    assert unavailable["message_sync_terminal"] is True
    assert unavailable["message_sync_error"] == "NotFoundError"
