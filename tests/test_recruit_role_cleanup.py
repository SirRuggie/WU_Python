import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.tasks import recruit_role_cleanup as cleanup


class _Cursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    async def to_list(self, length=None):
        return list(self.documents[:length] if length is not None else self.documents)


class _Collection:
    def __init__(self, documents):
        self.documents = documents
        self.updates = []
        self.find_queries = []

    def find(self, query):
        self.find_queries.append(query)
        return _Cursor(list(self.documents))

    async def find_one_and_update(self, query, update, **_kwargs):
        document = next((item for item in self.documents if item["_id"] == query["_id"]), None)
        if document:
            document.update(update.get("$set", {}))
        return document

    async def update_one(self, query, update):
        self.updates.append((query, update))
        document = next((item for item in self.documents if item["_id"] == query["_id"]), None)
        if document:
            document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                document.pop(key, None)


class _Rest:
    def __init__(self):
        self.removed = []

    async def fetch_member(self, guild_id, user_id):
        if user_id == 1:
            raise RuntimeError("temporary Discord failure")
        return SimpleNamespace(
            id=user_id,
            role_ids=(cleanup.NEW_RECRUIT_ROLE_ID,),
            display_name=f"member-{user_id}",
        )

    async def remove_role_from_member(self, guild_id, user_id, role_id, **_kwargs):
        self.removed.append((guild_id, user_id, role_id))


class _Cache:
    def get_guild(self, _guild_id):
        return None


def test_cleanup_retry_schedule_is_capped():
    assert [cleanup._retry_delay(attempt) for attempt in range(1, 7)] == [
        timedelta(hours=1),
        timedelta(hours=3),
        timedelta(hours=6),
        timedelta(hours=12),
        timedelta(hours=24),
        timedelta(hours=24),
    ]


def test_failed_row_is_deferred_without_blocking_later_recruit(monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    collection = _Collection([
        {"_id": "first", "user_id": 1, "guild_id": 10,
         "walkthrough_started_at": old, "new_recruit_role_removed": False},
        {"_id": "second", "user_id": 2, "guild_id": 10,
         "walkthrough_started_at": old, "new_recruit_role_removed": False},
    ])
    rest = _Rest()
    monkeypatch.setattr(cleanup, "mongo_client", SimpleNamespace(recruit_onboarding=collection))
    monkeypatch.setattr(cleanup, "bot_instance", SimpleNamespace(cache=_Cache(), rest=rest))

    asyncio.run(cleanup.remove_expired_recruit_roles())

    first_updates = [update for query, update in collection.updates if query["_id"] == "first"]
    second_updates = [update for query, update in collection.updates if query["_id"] == "second"]
    assert any(update.get("$set", {}).get("cleanup_status") == "retry_member_fetch"
               for update in first_updates)
    assert any(update.get("$set", {}).get("new_recruit_role_removed") is True
               for update in second_updates)
    assert rest.removed == [(10, 2, cleanup.NEW_RECRUIT_ROLE_ID)]
    assert collection.find_queries[0]["cleanup_terminal"] == {"$ne": True}


def test_transient_cleanup_failure_uses_persistent_backoff():
    now = datetime.now(timezone.utc)
    document = {"_id": "row", "user_id": 1, "guild_id": 10}
    collection = _Collection([document])

    terminal = asyncio.run(cleanup._record_cleanup_failure(
        collection, document, "member_fetch", RuntimeError("temporary"), now
    ))

    assert terminal is False
    assert document["cleanup_attempts"] == 1
    assert document["cleanup_status"] == "retry_member_fetch"
    assert document["cleanup_next_attempt_at"] == now + cleanup.RETRY_DELAYS[0]
    assert document["cleanup_first_failed_at"] == now
    assert "cleanup_terminal" not in document


def test_cleanup_failure_limit_creates_terminal_state():
    now = datetime.now(timezone.utc)
    document = {
        "_id": "row", "user_id": 1, "guild_id": 10,
        "cleanup_attempts": cleanup.MAX_CLEANUP_FAILURES - 1,
        "cleanup_next_attempt_at": now,
        "cleanup_lease_until": now,
    }
    collection = _Collection([document])

    terminal = asyncio.run(cleanup._record_cleanup_failure(
        collection, document, "role_removal", RuntimeError("still failing"), now
    ))

    assert terminal is True
    assert document["cleanup_attempts"] == cleanup.MAX_CLEANUP_FAILURES
    assert document["cleanup_status"] == "abandoned_role_removal"
    assert document["cleanup_terminal"] is True
    assert document["cleanup_terminal_reason"] == "failure_limit"
    assert "cleanup_next_attempt_at" not in document
    assert "cleanup_lease_until" not in document


def test_permanent_cleanup_failure_is_terminal_immediately():
    now = datetime.now(timezone.utc)
    document = {"_id": "row", "user_id": 1, "guild_id": 10}
    collection = _Collection([document])
    forbidden = cleanup.hikari.ForbiddenError(
        "https://discord.test", {}, {}, "Missing permissions"
    )

    terminal = asyncio.run(cleanup._record_cleanup_failure(
        collection, document, "role_removal", forbidden, now
    ))

    assert terminal is True
    assert document["cleanup_attempts"] == 1
    assert document["cleanup_terminal_reason"] == "permanent_discord_error"
