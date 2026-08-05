import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions import components
from utils import component_state


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and "$ne" in expected:
            if actual == expected["$ne"]:
                return False
        elif actual != expected:
            return False
    return True


class _Result:
    def __init__(self, *, matched=0, deleted=0, upserted_id=None):
        self.matched_count = matched
        self.deleted_count = deleted
        self.upserted_id = upserted_id


class _Cursor:
    def __init__(self, documents):
        self.documents = documents

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return deepcopy(next(self._iterator))
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, documents=(), *, index_error=None):
        self.documents = {doc["_id"]: deepcopy(doc) for doc in documents}
        self.index_calls = []
        self.index_error = index_error

    async def insert_one(self, document):
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query, projection=None):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return _Cursor([doc for doc in self.documents.values() if _matches(doc, query)])

    async def update_one(self, query, update, upsert=False):
        for document in self.documents.values():
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                return _Result(matched=1)
        if not upsert:
            return _Result()
        document = {"_id": query["_id"]}
        document.update(deepcopy(update.get("$setOnInsert", {})))
        document.update(deepcopy(update.get("$set", {})))
        self.documents[document["_id"]] = document
        return _Result(upserted_id=document["_id"])

    async def delete_one(self, query):
        for document_id, document in list(self.documents.items()):
            if _matches(document, query):
                del self.documents[document_id]
                return _Result(deleted=1)
        return _Result()

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((keys, deepcopy(kwargs)))
        if self.index_error:
            raise self.index_error
        return kwargs.get("name")


class _Mongo:
    def __init__(self, *, component=(), legacy=(), index_error=None):
        self.component_state = _Collection(component, index_error=index_error)
        self.button_store = _Collection(legacy)
        self.bot_config = _Collection()
        self.tickets = _Collection()


def test_insert_state_adds_fixed_aware_expiry_without_mutating_input(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()
    document = {"_id": "state", "user_id": 1}
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    asyncio.run(component_state.insert_state(mongo, document))

    stored = mongo.component_state.documents["state"]
    assert document == {"_id": "state", "user_id": 1}
    assert stored["created_at"] == now
    assert stored["expires_at"] == now + component_state.STATE_TTL
    assert stored["expires_at"].tzinfo is timezone.utc


def test_get_state_rejects_expired_row_without_waiting_for_ttl_monitor(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo(component=[{
        "_id": "expired",
        "expires_at": now - timedelta(seconds=1),
    }])
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    assert asyncio.run(component_state.get_state(mongo, "expired")) is None
    assert "expired" not in mongo.component_state.documents


def test_ticket_legacy_row_is_never_returned_or_migrated():
    ticket = {"_id": "ticket_42", "type": "ticket", "status": "open"}
    mongo = _Mongo(legacy=[ticket])

    assert asyncio.run(component_state.get_state(mongo, "ticket_42")) is None
    assert mongo.button_store.documents["ticket_42"] == ticket
    assert mongo.component_state.documents == {}


def test_prepare_migrates_only_audited_state_and_preserves_protected_unknowns(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    legacy = [
        {"_id": "ticket_1", "type": "ticket", "status": "open"},
        {"_id": "challenge", "challenge_type": "goblin_ping"},
        {"_id": "unknown", "mystery": True},
        {"_id": "lazy", "command": "snapshot", "user_id": 1},
        {"_id": "old-panel", "type": "fwa_links"},
        {"_id": "war_message_9", "copy_text": "unused"},
    ]
    mongo = _Mongo(legacy=legacy)
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    counts = asyncio.run(component_state.prepare_storage(mongo))

    assert counts == {
        "migrated": 1,
        "removed": 2,
        "protected_or_unknown": 3,
        "failed": 0,
    }
    assert set(mongo.button_store.documents) == {"ticket_1", "challenge", "unknown"}
    assert mongo.component_state.documents["lazy"]["expires_at"] == now + component_state.LEGACY_GRACE
    assert mongo.component_state.index_calls == [(
        "expires_at",
        {"expireAfterSeconds": 0, "name": component_state.TTL_INDEX_NAME},
    )]
    assert mongo.tickets.index_calls == []


def test_index_failure_preserves_every_legacy_row():
    legacy = [{"_id": "lazy", "command": "snapshot", "user_id": 1}]
    mongo = _Mongo(legacy=legacy, index_error=RuntimeError("no index permission"))

    assert asyncio.run(component_state.prepare_storage(mongo)) is None
    assert mongo.button_store.documents == {"lazy": legacy[0]}
    assert mongo.component_state.documents == {}


class _Ctx:
    def __init__(self, custom_id):
        self.interaction = SimpleNamespace(custom_id=custom_id)
        self.user = SimpleNamespace(id=1)
        self.responses = []
        self.deferred = False

    async def defer(self, **kwargs):
        self.deferred = True

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_dispatcher_refuses_missing_required_state_but_runs_stateless_action():
    called = []

    @components.register_action("test_required_state", no_return=True, requires_state=True)
    async def required(**kwargs):
        called.append("required")

    @components.register_action("test_stateless", no_return=True)
    async def stateless(**kwargs):
        called.append("stateless")

    mongo = _Mongo()
    required_ctx = _Ctx("test_required_state:missing")
    stateless_ctx = _Ctx("test_stateless:anything")
    try:
        asyncio.run(components._dispatch(required_ctx, mongo))
        asyncio.run(components._dispatch(stateless_ctx, mongo))
    finally:
        components.registered_functions.pop("test_required_state", None)
        components.registered_functions.pop("test_stateless", None)

    assert called == ["stateless"]
    assert required_ctx.responses[0][0] == (components.MSG_STALE_PANEL,)
