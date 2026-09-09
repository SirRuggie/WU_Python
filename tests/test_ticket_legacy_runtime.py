import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import hikari
import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from extensions.commands import ticket_runtime
from extensions.commands import tickets_legacy
from extensions.commands.tickets_legacy import (
    handlers,
    manage as legacy_manage,
    perms,
    resolve as legacy_resolve,
    setup as legacy_setup,
    store,
)
from extensions.components import registered_functions
from extensions.events.channel import ticket_channel_monitor


LEGACY_ACTIONS = {
    "create_ticket",
    "deny_fwa_default",
    "deny_main_default",
    "deny_custom",
    "process_custom_denial",
    "ticket_override",
    "ticket_dashboard_action",
}


class _CreationCollection:
    def __init__(self, document):
        self.document = deepcopy(document)
        self.update_calls = []

    async def find_one(self, query):
        if self.document and query.get("_id") == self.document.get("_id"):
            return deepcopy(self.document)
        return None

    async def find_one_and_update(self, query, update, **_kwargs):
        self.update_calls.append((deepcopy(query), deepcopy(update)))
        if self.document is None:
            return None
        for key, expected in query.items():
            if self.document.get(key) != expected:
                return None
        self.document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        for key, amount in update.get("$inc", {}).items():
            self.document[key] = int(self.document.get(key, 0)) + int(amount)
        return deepcopy(self.document)


_MISSING = object()


def _matches(document, query):
    for key, expected in query.items():
        if key == "$and":
            if not all(_matches(document, choice) for choice in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches(document, choice) for choice in expected):
                return False
            continue
        actual = document
        for part in key.split("."):
            if not isinstance(actual, dict) or part not in actual:
                actual = _MISSING
                break
            actual = actual[part]
        if isinstance(expected, dict):
            if "$exists" in expected:
                if (actual is not _MISSING) is not bool(expected["$exists"]):
                    return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$lte" in expected and (
                actual is _MISSING or actual > expected["$lte"]
            ):
                return False
            if "$gt" in expected and (
                actual is _MISSING or actual <= expected["$gt"]
            ):
                return False
            continue
        if actual is _MISSING or actual != expected:
            return False
    return True


class _FenceCollection:
    def __init__(self, document=None):
        self.document = deepcopy(document)
        self.find_updates = []
        self.deletes = []
        self.updates = []
        self.update_many_calls = []
        self.indexes = []

    async def find_one(self, query):
        if self.document is not None and _matches(self.document, query):
            return deepcopy(self.document)
        return None

    def find(self, query):
        rows = []
        if self.document is not None and _matches(self.document, query):
            rows.append(deepcopy(self.document))
        return _ListCursor(rows)

    @staticmethod
    def _apply(document, update):
        document.update(update.get("$setOnInsert", {}))
        document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            document.pop(key, None)
        for key, amount in update.get("$inc", {}).items():
            document[key] = int(document.get(key, 0)) + int(amount)

    async def find_one_and_update(self, query, update, *, upsert=False, **_kwargs):
        self.find_updates.append((deepcopy(query), deepcopy(update)))
        if self.document is not None and _matches(self.document, query):
            self._apply(self.document, update)
            return deepcopy(self.document)
        if upsert and self.document is None:
            self.document = {"_id": query["_id"]}
            self._apply(self.document, update)
            return deepcopy(self.document)
        return None

    async def update_one(self, query, update):
        self.updates.append((deepcopy(query), deepcopy(update)))
        matched = bool(self.document is not None and _matches(self.document, query))
        if matched:
            self._apply(self.document, update)
        return SimpleNamespace(matched_count=int(matched), modified_count=int(matched))

    async def delete_one(self, query):
        self.deletes.append(deepcopy(query))
        matched = bool(self.document is not None and _matches(self.document, query))
        if matched:
            self.document = None
        return SimpleNamespace(deleted_count=int(matched))

    async def update_many(self, query, update):
        self.update_many_calls.append((deepcopy(query), deepcopy(update)))
        matched = bool(self.document is not None and _matches(self.document, query))
        if matched:
            self._apply(self.document, update)
        return SimpleNamespace(matched_count=int(matched), modified_count=int(matched))

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))
        return kwargs.get("name")


class _RowsCollection:
    def __init__(self, documents):
        self.documents = deepcopy(documents)
        self.update_many_calls = []

    def find(self, query, *_args):
        return _ListCursor([
            document for document in self.documents if _matches(document, query)
        ])

    async def update_many(self, query, update):
        self.update_many_calls.append((deepcopy(query), deepcopy(update)))
        matched = 0
        for document in self.documents:
            if _matches(document, query):
                matched += 1
                _FenceCollection._apply(document, update)
        return SimpleNamespace(matched_count=matched, modified_count=matched)


class _ListCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.bound = None

    def sort(self, spec):
        for field, direction in reversed(spec):
            self.rows.sort(
                key=lambda row: row.get(field), reverse=direction < 0,
            )
        return self

    def limit(self, value):
        self.bound = int(value)
        return self

    async def to_list(self, *, length=None):
        bound = self.bound if self.bound is not None else length
        return deepcopy(self.rows[:bound] if bound is not None else self.rows)


def _completed_legacy_creation(status="approved"):
    state = {
        "_id": "111:7:main",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "state": "complete",
        "ticket_id": "ticket_444",
        "ticket_number": 10,
        "channel_id": 444,
        "thread_id": 445,
        "channel_name": "🆕main-10-candidate",
        "route": ticket_runtime.ROUTE_LEGACY,
        "runtime": store.LEGACY_RUNTIME,
    }
    ticket = {
        "_id": "ticket_444",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "channel_id": 444,
        "status": status,
    }
    return state, ticket


@pytest.mark.parametrize("attempt_state", ["complete", "creating"])
def test_open_or_incomplete_legacy_attempt_still_blocks(monkeypatch, attempt_state):
    state, ticket = _completed_legacy_creation(status="open")
    state["state"] = attempt_state
    collection = _CreationCollection(state)

    async def no_index(_mongo):
        return None

    async def no_terminal(_mongo, _query):
        return None

    monkeypatch.setattr(handlers, "ensure_creation_index", no_index)
    monkeypatch.setattr(handlers.store, "find_one", no_terminal)
    won, blocked = asyncio.run(handlers.claim_ticket_creation(
        SimpleNamespace(ticket_creation_state=collection), 111, 7, "main",
    ))

    assert not won
    assert blocked["channel_id"] == 444
    assert collection.update_calls == []


def test_legacy_commands_and_persistent_actions_are_preserved():
    assert tickets_legacy.ticket.name == "ticket"
    assert {
        "setup", "config", "approve", "deny", "list", "dashboard",
        "migrate-store", "reset-counter",
    } <= set(tickets_legacy.ticket.subcommands)
    assert LEGACY_ACTIONS <= set(registered_functions)
    for action_name in LEGACY_ACTIONS:
        assert "tickets_legacy" in registered_functions[action_name].declared_at


def test_legacy_filter_accepts_only_explicit_channel_shapes():
    assert "$ne" not in repr(store.LEGACY_FILTER)
    assert store.is_legacy_ticket_document({"type": "ticket"})
    assert store.is_legacy_ticket_document({
        "type": "ticket", "venue": "channel", "runtime": "legacy_channel",
    })
    assert not store.is_legacy_ticket_document({
        "type": "ticket", "venue": "thread", "runtime": "thread_v2",
    })
    assert not store.is_legacy_ticket_document({
        "type": "ticket", "runtime": "thread_v2",
    })


class _AuthorityCollection:
    def __init__(self, existing=None):
        self.existing = deepcopy(existing)
        self.insertions = []
        self.replacement = None
        self.replace_filter = None

    async def find_one(self, query):
        if self.existing is not None and _matches(self.existing, query):
            return deepcopy(self.existing)
        return None

    async def insert_one(self, document):
        self.insertions.append(deepcopy(document))
        if self.existing is not None:
            raise DuplicateKeyError("duplicate authority id")
        self.existing = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def replace_one(self, query, document, **kwargs):
        self.replace_filter = query
        self.replacement = document
        self.replace_kwargs = kwargs


class _ForbiddenCollection:
    def __getattr__(self, name):
        raise AssertionError(f"thread authority accessed through {name}")


def test_legacy_insert_writes_button_store_only_and_stamps_authority():
    button_store = _AuthorityCollection()
    mongo = SimpleNamespace(
        button_store=button_store,
        tickets=_ForbiddenCollection(),
    )

    asyncio.run(store.insert_one(mongo, {
        "_id": "ticket_42",
        "type": "ticket",
        "status": "open",
    }))

    assert button_store.insertions[0]["venue"] == "channel"
    assert button_store.insertions[0]["runtime"] == store.LEGACY_RUNTIME
    assert button_store.replacement is None


def _uncertain_commit_documents(*, status="open"):
    created_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    ticket = {
        "_id": "ticket_444",
        "type": "ticket",
        "ticket_type": "main",
        "ticket_number": 10,
        "guild_id": 111,
        "channel_id": 444,
        "thread_id": 445,
        "category_id": 222,
        "user_id": 7,
        "username": "candidate",
        "created_at": created_at,
        "status": status,
        "venue": "channel",
        "runtime": store.LEGACY_RUNTIME,
        "open_slot_id": "ticket-open:7:main",
        "creation_workflow_id": "legacy:111:7:main",
        "rollout_revision": 8,
        "creation_generation": 1,
    }
    state = {
        "_id": "111:7:main",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "ticket_number": 10,
        "channel_id": 444,
        "thread_id": 445,
        "category_id": 222,
        "route": ticket_runtime.ROUTE_LEGACY,
        "runtime": store.LEGACY_RUNTIME,
        "rollout_revision": 8,
        "open_slot_id": "ticket-open:7:main",
        "creation_workflow_id": "legacy:111:7:main",
        "attempt_generation": 1,
        "ticket_id": "ticket_444",
        "ticket_payload": {**ticket, "status": "open"},
        "commit_started_at": created_at,
        "state": "cleanup_required",
    }
    slot = {
        "_id": "ticket-open:7:main",
        "schema_version": 1,
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "route": ticket_runtime.ROUTE_LEGACY,
        "workflow_id": "legacy:111:7:main",
        "rollout_revision": 8,
        "state": ticket_runtime.SLOT_RESERVED,
        "owner_token": "slot-owner",
        "lease_until": created_at - timedelta(seconds=1),
    }
    return state, ticket, slot


def test_late_commit_duplicate_accepts_exact_and_rejects_changed_identity():
    _state, ticket, _slot = _uncertain_commit_documents()

    class _LateCommitAuthority(_AuthorityCollection):
        async def insert_one(self, document):
            self.insertions.append(deepcopy(document))
            self.existing = deepcopy(document)
            raise DuplicateKeyError("original commit completed late")

    authority = _LateCommitAuthority()
    mongo = SimpleNamespace(button_store=authority)
    recovered = asyncio.run(store.ensure_exact_ticket(mongo, ticket))

    assert recovered == ticket
    assert len(authority.insertions) == 1
    changed = {**ticket, "user_id": 8}
    with pytest.raises(ValueError, match="user_id"):
        asyncio.run(store.ensure_exact_ticket(mongo, changed))
    changed = {
        **ticket,
        "created_at": ticket["created_at"] + timedelta(seconds=1),
    }
    with pytest.raises(ValueError, match="created_at"):
        asyncio.run(store.ensure_exact_ticket(mongo, changed))


def test_opening_post_intent_fences_terminal_and_clear_is_exact():
    authority = _FenceCollection({
        "_id": "ticket_42",
        "type": "ticket",
        "venue": "channel",
        "runtime": store.LEGACY_RUNTIME,
        "status": "open",
        "guild_id": 111,
        "channel_id": 444,
        "thread_id": 445,
        "user_id": 7,
        "ticket_type": "main",
    })
    mongo = SimpleNamespace(button_store=authority)

    acquired = asyncio.run(store.acquire_opening_post_intent(
        mongo,
        "ticket_42",
        guild_id=111,
        channel_id=444,
        thread_id=445,
        user_id=7,
        ticket_type="main",
        token="post-owner",
        step="welcome_sent",
        target_id=444,
    ))
    assert acquired["opening_post_intent"]["token"] == "post-owner"

    blocked = asyncio.run(store.transition(
        mongo,
        "ticket_42",
        to_status="denied",
        actor_id=8,
        actor_name="Recruiter",
    ))
    assert blocked.busy
    assert authority.document["status"] == "open"

    assert not asyncio.run(store.clear_opening_post_intent(
        mongo,
        "ticket_42",
        token="stale-owner",
        step="welcome_sent",
    ))
    assert authority.document["opening_post_intent"]["token"] == "post-owner"

    assert asyncio.run(store.clear_opening_post_intent(
        mongo,
        "ticket_42",
        token="post-owner",
        step="welcome_sent",
    ))
    resolved = asyncio.run(store.transition(
        mongo,
        "ticket_42",
        to_status="denied",
        actor_id=8,
        actor_name="Recruiter",
    ))
    assert resolved.won
    assert authority.document["status"] == "denied"

    # Resolution won first, so no later opening POST can acquire authority.
    assert asyncio.run(store.acquire_opening_post_intent(
        mongo,
        "ticket_42",
        guild_id=111,
        channel_id=444,
        thread_id=445,
        user_id=7,
        ticket_type="main",
        token="late-owner",
        step="questionnaire_sent",
        target_id=444,
    )) is None


def test_opening_post_intent_requires_exact_ticket_identity():
    authority = _FenceCollection({
        "_id": "ticket_42",
        "type": "ticket",
        "venue": "channel",
        "runtime": store.LEGACY_RUNTIME,
        "status": "open",
        "guild_id": "111",
        "channel_id": "444",
        "thread_id": "445",
        "user_id": "7",
        "ticket_type": "main",
    })
    mongo = SimpleNamespace(button_store=authority)

    acquired = asyncio.run(store.acquire_opening_post_intent(
        mongo,
        "ticket_42",
        guild_id=111,
        channel_id=444,
        thread_id=999,
        user_id=7,
        ticket_type="main",
        token="post-owner",
        step="welcome_sent",
        target_id=444,
    ))
    assert acquired is None
    assert "opening_post_intent" not in authority.document


def _janitorial_ticket(ticket_id, channel_id, *, busy=False):
    document = {
        "_id": ticket_id,
        "type": "ticket",
        "venue": "channel",
        "runtime": store.LEGACY_RUNTIME,
        "status": "open",
        "guild_id": 111,
        "channel_id": channel_id,
        "ticket_type": "main",
        "ticket_number": channel_id,
        "username": f"candidate-{channel_id}",
    }
    if busy:
        document["opening_post_intent"] = {
            "token": "post-owner",
            "step": "welcome_sent",
            "target_id": channel_id,
        }
    return document


class _JanitorialContext:
    guild_id = 111
    user = SimpleNamespace(id=8, username="Admin")
    member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)

    def __init__(self):
        self.responses = []

    async def defer(self, **_kwargs):
        return None

    async def respond(self, content=None, **kwargs):
        self.responses.append((content, kwargs))


def test_cleanup_ghosts_atomically_closes_busy_row_and_clears_intent(monkeypatch):
    rows = _RowsCollection([
        _janitorial_ticket("free", 444),
        _janitorial_ticket("busy", 555, busy=True),
    ])

    async def no_threads(*_args):
        return set()

    class _Rest:
        async def fetch_guild_channels(self, _guild_id):
            return []

    monkeypatch.setattr(legacy_manage, "_active_thread_ids", no_threads)
    command = legacy_manage.CleanupGhosts()
    command.confirm = True
    ctx = _JanitorialContext()
    asyncio.run(command.invoke(
        ctx,
        mongo=SimpleNamespace(button_store=rows),
        bot=SimpleNamespace(rest=_Rest()),
    ))

    by_id = {document["_id"]: document for document in rows.documents}
    assert by_id["free"]["status"] == "denied"
    assert by_id["busy"]["status"] == "denied"
    assert "opening_post_intent" not in by_id["busy"]
    query, update = rows.update_many_calls[0]
    assert "opening_post_intent" not in query["$and"][0]
    assert update["$unset"] == {"opening_post_intent": ""}


def test_fix_mismatched_skips_busy_authority_row(monkeypatch):
    rows = _RowsCollection([
        _janitorial_ticket("free", 444),
        _janitorial_ticket("busy", 555, busy=True),
    ])

    class _Rest:
        async def fetch_guild_channels(self, _guild_id):
            return [
                SimpleNamespace(id=444, name="❌main-1-candidate"),
                SimpleNamespace(id=555, name="❌main-2-candidate"),
            ]

    command = legacy_manage.FixMismatched()
    command.confirm = True
    ctx = _JanitorialContext()
    asyncio.run(command.invoke(
        ctx,
        mongo=SimpleNamespace(button_store=rows),
        bot=SimpleNamespace(rest=_Rest()),
    ))

    by_id = {document["_id"]: document for document in rows.documents}
    assert by_id["free"]["status"] == "denied"
    assert by_id["busy"]["status"] == "open"
    assert rows.update_many_calls[0][0]["$and"][0][
        "opening_post_intent"
    ] == {"$exists": False}


def test_override_busy_reports_no_decision_and_runs_no_side_effect(monkeypatch):
    edits = []

    async def state(_mongo, _action_id):
        return {
            "kind": legacy_resolve.KIND_APPROVE,
            "ticket_id": "ticket_42",
            "channel_id": 444,
            "user_id": 7,
            "prior_status": "denied",
        }

    async def allow(*_args):
        return True

    async def busy(*_args, **_kwargs):
        return store.Transition(store.BUSY, {"status": "open"})

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("busy override ran a side effect")

    class _Interaction:
        async def edit_initial_response(self, **kwargs):
            edits.append(kwargs)

    ctx = SimpleNamespace(
        guild_id=111,
        member=SimpleNamespace(),
        user=SimpleNamespace(id=8, username="Recruiter"),
        interaction=_Interaction(),
    )
    monkeypatch.setattr(legacy_resolve, "get_state", state)
    monkeypatch.setattr(legacy_resolve.perms, "is_recruiter", allow)
    monkeypatch.setattr(legacy_resolve.store, "transition", busy)
    monkeypatch.setattr(legacy_resolve, "run_side_effects", forbidden)
    monkeypatch.setattr(legacy_resolve, "delete_state", forbidden)

    asyncio.run(legacy_resolve.ticket_override_handler(
        ctx,
        "override-action",
        mongo=object(),
        bot=object(),
    ))
    assert edits == [{
        "content": store.OPENING_DELIVERY_BUSY_MESSAGE,
        "components": [],
    }]


def test_monitor_isolated_to_legacy_repository_and_names():
    assert ticket_channel_monitor.store is store
    assert ticket_channel_monitor.LEGACY_CHANNEL_NAME_RE.match(
        "🆕main-123-candidate"
    )
    assert ticket_channel_monitor.LEGACY_CHANNEL_NAME_RE.match(
        "🆕fwa-456-candidate"
    )
    assert not ticket_channel_monitor.LEGACY_CHANNEL_NAME_RE.match(
        "staff-main-123-candidate"
    )


def test_main_explicitly_loads_both_ticket_runtimes_and_monitor():
    source = open("main.py", encoding="utf-8").read()
    assert '"extensions.commands.tickets_legacy"' in source
    assert '"extensions.commands.tickets"' in source
    assert '"extensions.events.channel.ticket_channel_monitor"' in source
    assert '"tickets_legacy"' in source


def test_exact_ticket_recovery_race_against_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_legacy_commit_recovery_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(button_store=database.button_store)
        _state, ticket, _slot = _uncertain_commit_documents()
        try:
            await client.admin.command("ping")
            first, second = await asyncio.gather(
                store.ensure_exact_ticket(mongo, ticket),
                store.ensure_exact_ticket(mongo, ticket),
            )
            assert first["_id"] == ticket["_id"]
            assert second["_id"] == ticket["_id"]
            assert await database.button_store.count_documents({
                "_id": ticket["_id"],
            }) == 1

            with pytest.raises(ValueError, match="channel_id"):
                await store.ensure_exact_ticket(
                    mongo,
                    {**ticket, "channel_id": 999},
                )
            persisted = await database.button_store.find_one({
                "_id": ticket["_id"],
            })
            assert persisted["channel_id"] == 444
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_opening_post_intent_terminal_fence_against_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_legacy_opening_intent_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(button_store=database.button_store)
        ticket = {
            "_id": "ticket_42",
            "type": "ticket",
            "venue": "channel",
            "runtime": store.LEGACY_RUNTIME,
            "status": "open",
            "guild_id": 111,
            "channel_id": 444,
            "thread_id": 445,
            "user_id": 7,
            "ticket_type": "main",
        }
        try:
            await client.admin.command("ping")
            await database.button_store.insert_one(ticket)
            acquired = await store.acquire_opening_post_intent(
                mongo,
                ticket["_id"],
                guild_id=111,
                channel_id=444,
                thread_id=445,
                user_id=7,
                ticket_type="main",
                token="post-owner",
                step="welcome_sent",
                target_id=444,
            )
            assert acquired is not None

            blocked = await store.transition(
                mongo,
                ticket["_id"],
                to_status="approved",
                actor_id=8,
                actor_name="Recruiter",
            )
            assert blocked.busy
            assert (await database.button_store.find_one(
                {"_id": ticket["_id"]}
            ))["status"] == "open"

            assert not await store.clear_opening_post_intent(
                mongo,
                ticket["_id"],
                token="stale-owner",
                step="welcome_sent",
            )
            assert await store.clear_opening_post_intent(
                mongo,
                ticket["_id"],
                token="post-owner",
                step="welcome_sent",
            )
            resolved = await store.transition(
                mongo,
                ticket["_id"],
                to_status="approved",
                actor_id=8,
                actor_name="Recruiter",
            )
            assert resolved.won
            assert await store.acquire_opening_post_intent(
                mongo,
                ticket["_id"],
                guild_id=111,
                channel_id=444,
                thread_id=445,
                user_id=7,
                ticket_type="main",
                token="late-owner",
                step="questionnaire_sent",
                target_id=444,
            ) is None
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_legacy_create_with_no_rollout_or_guild_binding_runs_unconditionally():
    """A legacy `create_ticket:main` click must run main's create path
    unconditionally: no rollout document, no `legacy_ticket_guild_id` on the
    ticket_setup config, and nothing to consult in ticket_runtime at all -
    the module isn't even imported any more."""
    assert not hasattr(handlers, "ticket_runtime")

    creation = _FenceCollection()
    authority = _AuthorityCollection()
    edits = []

    class _Setup:
        def __init__(self):
            self.counter = 0

        async def find_one(self, query):
            assert query == {"_id": "config"}
            return None  # No config document at all: no rollout, no guild binding.

        async def find_one_and_update(self, query, update, **_kwargs):
            assert query == {"_id": "config"}
            self.counter += update["$inc"]["main_ticket_counter"]
            return {"_id": "config", "main_ticket_counter": self.counter}

    class _Rest:
        def __init__(self):
            self.created = []

        async def fetch_guild_channels(self, _guild_id):
            return []

        async def fetch_channel(self, _channel_id):
            raise RuntimeError("no category configured")

        async def create_guild_text_channel(self, **_kwargs):
            self.created.append("channel")
            return SimpleNamespace(id=444)

        async def create_thread(self, *_args, **_kwargs):
            self.created.append("thread")
            return SimpleNamespace(id=445)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def create_message(self, *_args, **_kwargs):
            return None

    async def defer(**_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs["content"])

    ctx = SimpleNamespace(
        guild_id=111,
        user=SimpleNamespace(id=7, username="candidate"),
        defer=defer,
        interaction=SimpleNamespace(edit_initial_response=edit_initial_response),
    )
    bot = SimpleNamespace(rest=_Rest(), get_me=lambda: SimpleNamespace(id=900))
    mongo = SimpleNamespace(
        ticket_setup=_Setup(),
        ticket_creation_state=creation,
        button_store=authority,
    )
    handlers.user_cooldowns.clear()

    asyncio.run(handlers.handle_create_ticket(ctx, "main", bot=bot, mongo=mongo))

    assert authority.insertions[0]["channel_id"] == 444
    assert authority.insertions[0]["thread_id"] == 445
    assert creation.document["state"] == "complete"
    assert "has been created!" in edits[-1]
