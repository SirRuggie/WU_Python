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

    def find(self, _query):
        return _Cursor(list(self.documents))

    async def find_one_and_update(self, query, update, **_kwargs):
        document = next((item for item in self.documents if item["_id"] == query["_id"]), None)
        if document:
            document.update(update.get("$set", {}))
        return document

    async def update_one(self, query, update):
        self.updates.append((query, update))


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
