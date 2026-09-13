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


def _project(document, projection):
    if not projection:
        return deepcopy(document)
    included = {
        field for field, value in projection.items()
        if field != "_id" and bool(value)
    }
    excluded = {
        field for field, value in projection.items()
        if field != "_id" and not bool(value)
    }
    inclusion = bool(included) or (not excluded and bool(projection.get("_id")))
    if inclusion:
        result = {
            field: deepcopy(value)
            for field, value in document.items()
            if field in projection and bool(projection[field])
        }
        if projection.get("_id", 1) and "_id" in document:
            result["_id"] = deepcopy(document["_id"])
        return result
    return {
        field: deepcopy(value)
        for field, value in document.items()
        if bool(projection.get(field, 1))
    }


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
        self.find_one_calls = []
        self.index_error = index_error

    async def insert_one(self, document):
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query, projection=None):
        self.find_one_calls.append((deepcopy(query), deepcopy(projection)))
        for document in self.documents.values():
            if _matches(document, query):
                return _project(document, projection)
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


def test_get_state_inclusion_projection_fetches_and_returns_only_envelope(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo(component=[{
        "_id": "detail",
        "type": "ticket_console_detail",
        "owner_id": 7,
        "guild_id": 8,
        "ticket_id": "ticket_private",
        "denial_reason": "private reason",
        "expires_at": now + timedelta(hours=1),
    }])
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    envelope = asyncio.run(component_state.get_state(mongo, "detail", {
        "type": 1,
        "owner_id": 1,
        "guild_id": 1,
    }))

    assert envelope == {
        "_id": "detail",
        "type": "ticket_console_detail",
        "owner_id": 7,
        "guild_id": 8,
    }
    assert mongo.component_state.find_one_calls == [(
        {"_id": "detail"},
        {"type": 1, "owner_id": 1, "guild_id": 1, "expires_at": 1},
    )]


def test_get_state_inclusion_projection_honors_id_exclusion_without_expiry_leak(
    monkeypatch,
):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo(component=[{
        "_id": "detail",
        "type": "ticket_console_detail",
        "ticket_id": "ticket_private",
        "expires_at": now + timedelta(hours=1),
    }])
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    result = asyncio.run(component_state.get_state(
        mongo, "detail", {"type": 1, "_id": 0}
    ))

    assert result == {"type": "ticket_console_detail"}
    assert mongo.component_state.find_one_calls[0][1] == {
        "type": 1,
        "_id": 0,
        "expires_at": 1,
    }


def test_get_state_inclusion_projection_still_rejects_expired_row(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo(component=[{
        "_id": "expired-private",
        "type": "deny_action",
        "denier_id": 7,
        "ticket_id": "ticket_private",
        "expires_at": now - timedelta(seconds=1),
    }])
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    assert asyncio.run(component_state.get_state(
        mongo,
        "expired-private",
        {"type": 1, "denier_id": 1, "guild_id": 1},
    )) is None
    assert "expired-private" not in mongo.component_state.documents
    assert mongo.component_state.find_one_calls[0][1]["expires_at"] == 1


def test_projected_legacy_envelope_does_not_fetch_private_fields_or_migrate(monkeypatch):
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    legacy = {
        "_id": "deny-state",
        "type": "deny_action",
        "denier_id": 7,
        "guild_id": 8,
        "ticket_id": "ticket_private",
        "denial_reason": "private reason",
    }
    mongo = _Mongo(legacy=[legacy])
    monkeypatch.setattr(component_state, "utcnow", lambda: now)

    envelope = asyncio.run(component_state.get_state(mongo, "deny-state", {
        "type": 1,
        "denier_id": 1,
        "guild_id": 1,
    }))

    assert envelope == {
        "_id": "deny-state",
        "type": "deny_action",
        "denier_id": 7,
        "guild_id": 8,
    }
    legacy_projection = mongo.button_store.find_one_calls[0][1]
    assert legacy_projection["type"] == 1
    assert legacy_projection["challenge_type"] == 1
    assert "ticket_id" not in legacy_projection
    assert "denial_reason" not in legacy_projection
    assert mongo.component_state.documents == {}
    assert mongo.button_store.documents == {"deny-state": legacy}

    full = asyncio.run(component_state.get_state(mongo, "deny-state"))
    assert full["ticket_id"] == "ticket_private"
    assert "deny-state" in mongo.component_state.documents
    assert mongo.button_store.documents == {}


def test_projected_unknown_legacy_row_fails_closed_without_private_fetch():
    legacy = {
        "_id": "unknown-state",
        "user_id": 7,
        "guild_id": 8,
        "private_payload": "must not be fetched",
    }
    mongo = _Mongo(legacy=[legacy])

    assert asyncio.run(component_state.get_state(mongo, "unknown-state", {
        "user_id": 1,
        "guild_id": 1,
    })) is None
    projection = mongo.button_store.find_one_calls[0][1]
    assert "private_payload" not in projection
    assert mongo.component_state.documents == {}
    assert mongo.button_store.documents == {"unknown-state": legacy}


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
        self.defer_kwargs = []

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs.append(kwargs)

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


def test_dispatcher_preserves_exact_stateful_and_stateless_edit_responses():
    called = []

    @components.register_action(
        "test_stateful_edit",
        ephemeral=True,
        requires_state=True,
    )
    async def stateful(**kwargs):
        called.append(("stateful", kwargs["user_id"], kwargs["action_id"]))
        return ["stateful-components"]

    @components.register_action("test_stateless_edit", ephemeral=True)
    async def stateless(**kwargs):
        called.append(("stateless", kwargs["action_id"]))
        return ["stateless-components"]

    mongo = _Mongo(component=[{
        "_id": "saved",
        "user_id": 42,
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }])
    stateful_ctx = _Ctx("test_stateful_edit:saved")
    stateless_ctx = _Ctx("test_stateless_edit:any")
    try:
        asyncio.run(components._dispatch(stateful_ctx, mongo))
        asyncio.run(components._dispatch(stateless_ctx, mongo))
    finally:
        components.registered_functions.pop("test_stateful_edit", None)
        components.registered_functions.pop("test_stateless_edit", None)

    assert called == [
        ("stateful", 42, "saved"),
        ("stateless", "any"),
    ]
    assert stateful_ctx.defer_kwargs == [{"edit": True}]
    assert stateless_ctx.defer_kwargs == [{"edit": True}]
    assert stateful_ctx.responses == [
        ((), {"components": ["stateful-components"], "edit": True})
    ]
    assert stateless_ctx.responses == [
        ((), {"components": ["stateless-components"], "edit": True})
    ]


def test_dispatcher_modal_response_is_not_deferred_or_edited():
    @components.register_action("test_modal_response", is_modal=True)
    async def modal(**kwargs):
        return ["modal-components"]

    mongo = _Mongo()
    ctx = _Ctx("test_modal_response:any")
    try:
        asyncio.run(components._dispatch(ctx, mongo))
    finally:
        components.registered_functions.pop("test_modal_response", None)

    assert not ctx.deferred
    assert ctx.responses == [((), {"components": ["modal-components"]})]


def test_modal_handler_can_acknowledge_before_opted_out_state_load(monkeypatch):
    events = []

    @components.register_action(
        "test_modal_owned_state",
        is_modal=True,
        no_return=True,
        preload_state=False,
    )
    async def modal(ctx, **_kwargs):
        await ctx.defer(ephemeral=True)
        events.append("handler-work")

    async def forbidden_state_load(*_args, **_kwargs):
        raise AssertionError("dispatcher loaded state before the modal acknowledgement")

    monkeypatch.setattr(components, "get_state", forbidden_state_load)
    ctx = _Ctx("test_modal_owned_state:any")
    try:
        asyncio.run(components._dispatch(ctx, _Mongo()))
    finally:
        components.registered_functions.pop("test_modal_owned_state", None)

    assert ctx.defer_kwargs == [{"ephemeral": True}]
    assert events == ["handler-work"]


def test_dispatcher_no_return_handler_remains_the_only_responder():
    @components.register_action("test_self_response", no_return=True)
    async def self_responding(ctx, **kwargs):
        await ctx.respond("handled directly", ephemeral=True)

    mongo = _Mongo()
    ctx = _Ctx("test_self_response:any")
    try:
        asyncio.run(components._dispatch(ctx, mongo))
    finally:
        components.registered_functions.pop("test_self_response", None)

    assert ctx.defer_kwargs == [{"edit": True}]
    assert ctx.responses == [
        (("handled directly",), {"ephemeral": True})
    ]
