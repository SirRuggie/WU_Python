import asyncio
from copy import deepcopy
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


class _TicketSetup:
    def __init__(self, config=None):
        self.config = config

    async def find_one(self, query):
        assert query == {"_id": "config"}
        return self.config


def test_legacy_control_guild_uses_rollout_then_target_fallback(monkeypatch):
    async def valid_rollout(_mongo):
        return ticket_runtime.RolloutState(
            phase=ticket_runtime.PHASE_PILOT,
            revision=2,
            valid=True,
            legacy_intake=ticket_runtime.IntakeSource(111, 12, 13),
        )

    monkeypatch.setattr(ticket_runtime, "get_rollout", valid_rollout)
    mongo = SimpleNamespace(ticket_setup=_TicketSetup({"ticket_target_guild_id": 222}))
    assert asyncio.run(perms.is_legacy_control_guild(mongo, 111))
    assert not asyncio.run(perms.is_legacy_control_guild(mongo, 222))

    async def invalid_rollout(_mongo):
        return ticket_runtime.RolloutState(
            phase=ticket_runtime.PHASE_LEGACY_ONLY,
            revision=0,
            valid=False,
        )

    monkeypatch.setattr(ticket_runtime, "get_rollout", invalid_rollout)
    assert asyncio.run(perms.is_legacy_control_guild(mongo, 222))
    assert not asyncio.run(perms.is_legacy_control_guild(mongo, 111))

    unbound = SimpleNamespace(ticket_setup=_TicketSetup({}))
    assert asyncio.run(perms.is_legacy_control_guild(unbound, 333))


@pytest.mark.parametrize(
    "phase",
    [ticket_runtime.PHASE_THREAD_DEFAULT, ticket_runtime.PHASE_THREAD_ONLY],
)
def test_legacy_setup_refuses_retired_phases_before_posting(monkeypatch, phase):
    rollout = ticket_runtime.RolloutState(
        phase=phase,
        revision=3,
        valid=True,
        legacy_intake=ticket_runtime.IntakeSource(111, 12, 13),
    )

    async def get_rollout(_mongo):
        return rollout

    class _Context:
        guild_id = 111
        channel_id = 12
        member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
        user = SimpleNamespace(id=7)

        def __init__(self):
            self.responses = []

        async def defer(self, **_kwargs):
            return None

        async def respond(self, content, **_kwargs):
            self.responses.append(content)

    class _Rest:
        async def create_message(self, **_kwargs):
            raise AssertionError("retired legacy setup posted a panel")

    monkeypatch.setattr(ticket_runtime, "get_rollout", get_rollout)
    ctx = _Context()
    asyncio.run(legacy_setup.Setup().invoke(
        ctx,
        bot=SimpleNamespace(rest=_Rest()),
        mongo=SimpleNamespace(ticket_setup=_TicketSetup({})),
    ))

    assert ctx.responses == [
        "❌ Legacy intake is retired in the current rollout phase. Nothing was posted."
    ]


def test_legacy_setup_atomically_rebinds_both_public_sources(monkeypatch):
    rollout = ticket_runtime.RolloutState(
        phase=ticket_runtime.PHASE_PILOT,
        revision=7,
        valid=True,
        legacy_intake=ticket_runtime.IntakeSource(111, 12, 13),
        thread_intake=ticket_runtime.IntakeSource(111, 22, 23),
        pilot_intake=ticket_runtime.IntakeSource(111, 32, 33),
        pilot_user_ids=(7,),
        pilot_ticket_types=("main",),
    )
    configured = []

    async def get_rollout(_mongo):
        return rollout

    async def configure(_mongo, **kwargs):
        configured.append(kwargs)
        return rollout

    class _Context:
        guild_id = 111
        channel_id = 44
        member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
        user = SimpleNamespace(id=7)

        def __init__(self):
            self.responses = []

        async def defer(self, **_kwargs):
            return None

        async def respond(self, content, **_kwargs):
            self.responses.append(content)

    class _Rest:
        async def create_message(self, **kwargs):
            assert kwargs["channel"] == 44
            return SimpleNamespace(id=55)

        async def delete_message(self, *_args, **_kwargs):
            raise AssertionError("an active replacement panel must not be deleted")

    monkeypatch.setattr(ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(ticket_runtime, "configure_rollout", configure)
    ctx = _Context()
    asyncio.run(legacy_setup.Setup().invoke(
        ctx,
        bot=SimpleNamespace(rest=_Rest()),
        mongo=SimpleNamespace(ticket_setup=_TicketSetup({})),
    ))

    public = {"guild_id": 111, "channel_id": 44, "message_id": 55}
    assert configured[0]["legacy_intake"] == public
    assert configured[0]["thread_intake"] == public
    assert configured[0]["pilot"]["intake"] == {
        "guild_id": 111, "channel_id": 32, "message_id": 33,
    }
    assert ctx.responses == ["✅ Ticket system embed has been posted!"]


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


def test_terminal_completed_attempt_resets_for_repeat_ticket(monkeypatch):
    state, ticket = _completed_legacy_creation()
    collection = _CreationCollection(state)

    async def no_index(_mongo):
        return None

    async def exact_ticket(_mongo, query):
        assert query == {
            "_id": "ticket_444",
            "guild_id": 111,
            "user_id": {"$in": [7, "7"]},
            "ticket_type": "main",
            "channel_id": {"$in": [444, "444"]},
            "status": {"$in": ["approved", "denied"]},
        }
        return ticket

    monkeypatch.setattr(handlers, "ensure_creation_index", no_index)
    monkeypatch.setattr(handlers.store, "find_one", exact_ticket)
    won, claimed = asyncio.run(handlers.claim_ticket_creation(
        SimpleNamespace(ticket_creation_state=collection), 111, 7, "main",
    ))

    assert won
    assert claimed["state"] == "creating"
    assert claimed["attempt_generation"] == 1
    assert "channel_id" not in claimed
    assert "thread_id" not in claimed
    assert "ticket_id" not in claimed
    assert state["channel_id"] == 444


def test_terminal_ticket_heals_crash_before_complete_marker(monkeypatch):
    state, ticket = _completed_legacy_creation()
    state.update({
        "state": "creating",
        "lease_owner": "crashed-owner",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    })
    collection = _FenceCollection(state)

    async def no_index(_mongo):
        return None

    async def exact_ticket(_mongo, _query):
        return ticket

    monkeypatch.setattr(handlers, "ensure_creation_index", no_index)
    monkeypatch.setattr(handlers.store, "find_one", exact_ticket)
    won, claimed = asyncio.run(handlers.claim_ticket_creation(
        SimpleNamespace(ticket_creation_state=collection),
        111,
        7,
        "main",
        slot_id="ticket-open:7:main",
        workflow_id="legacy:111:7:main",
    ))

    assert won
    assert claimed["state"] == "creating"
    assert claimed["lease_owner"] != "crashed-owner"
    assert "ticket_id" not in claimed
    assert "channel_id" not in claimed
    assert "expires_at" not in claimed


def test_expired_creation_takeover_fences_stale_worker(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    collection = _FenceCollection({
        "_id": "111:7:main",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "state": "creating",
        "lease_owner": "stale-owner",
        "lease_until": now - timedelta(seconds=1),
        "ticket_number": 10,
    })

    async def no_index(_mongo):
        return None

    monkeypatch.setattr(handlers, "ensure_creation_index", no_index)
    mongo = SimpleNamespace(ticket_creation_state=collection)
    won, claimed = asyncio.run(handlers.claim_ticket_creation(
        mongo,
        111,
        7,
        "main",
        slot_id="ticket-open:7:main",
        workflow_id="legacy:111:7:main",
        now=now,
    ))

    assert won
    assert claimed["lease_owner"] != "stale-owner"
    assert claimed["ticket_number"] == 10
    assert "expires_at" not in claimed
    with pytest.raises(handlers.CreationLeaseLost):
        asyncio.run(handlers.update_creation_state(
            mongo,
            "111:7:main",
            "stale-owner",
            channel_name="must-not-land",
        ))
    assert "channel_name" not in collection.document


def test_stale_rollback_cannot_delete_discord_state_or_shared_slot(monkeypatch):
    collection = _FenceCollection({
        "_id": "111:7:main",
        "state": "creating",
        "lease_owner": "new-owner",
    })

    class _Rest:
        async def delete_channel(self, *_args, **_kwargs):
            raise AssertionError("stale worker reached Discord")

    async def cancel(*_args, **_kwargs):
        raise AssertionError("stale worker cancelled the shared slot")

    monkeypatch.setattr(ticket_runtime, "cancel_open_slot", cancel)
    result = asyncio.run(handlers.rollback_ticket_creation(
        SimpleNamespace(rest=_Rest()),
        SimpleNamespace(ticket_creation_state=collection),
        "111:7:main",
        444,
        RuntimeError("late failure"),
        lease_owner="stale-owner",
        slot_id="ticket-open:7:main",
        slot_owner="stale-slot-owner",
        workflow_id="legacy:111:7:main",
    ))

    assert result is False
    assert collection.document["lease_owner"] == "new-owner"
    assert collection.deletes == []


def test_uncertain_creation_read_never_cancels_shared_slot(monkeypatch):
    class _UnavailableState:
        async def find_one(self, _query):
            raise RuntimeError("Mongo unavailable")

    async def cancel(*_args, **_kwargs):
        raise AssertionError("uncertain evidence check cancelled the slot")

    monkeypatch.setattr(handlers, "cancel_claimed_open_slot", cancel)
    result = asyncio.run(handlers.cancel_slot_if_creation_absent(
        SimpleNamespace(ticket_creation_state=_UnavailableState()),
        ticket_runtime.SlotClaim(True, "owner", {"_id": "ticket-open:7:main"}),
        "111:7:main",
    ))

    assert result is False


def test_ambiguous_cleanup_retains_evidence_and_slot_without_ttl(monkeypatch):
    collection = _FenceCollection({
        "_id": "111:7:main",
        "state": "creating",
        "lease_owner": "owner",
        "channel_id": 444,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    })

    class _Rest:
        async def delete_channel(self, *_args, **_kwargs):
            raise RuntimeError("Discord unavailable")

    async def cancel(*_args, **_kwargs):
        raise AssertionError("ambiguous cleanup cancelled the shared slot")

    monkeypatch.setattr(ticket_runtime, "cancel_open_slot", cancel)
    result = asyncio.run(handlers.rollback_ticket_creation(
        SimpleNamespace(rest=_Rest()),
        SimpleNamespace(ticket_creation_state=collection),
        "111:7:main",
        444,
        RuntimeError("creation failed"),
        lease_owner="owner",
        slot_id="ticket-open:7:main",
        slot_owner="slot-owner",
        workflow_id="legacy:111:7:main",
    ))

    assert result is False
    assert collection.document["state"] == "cleanup_required"
    assert collection.document["channel_id"] == 444
    assert "lease_owner" not in collection.document
    assert "expires_at" not in collection.document
    assert collection.deletes == []


def test_unconfirmed_discord_create_request_is_never_auto_deleted():
    past = datetime.now(timezone.utc) - timedelta(minutes=20)
    collection = _FenceCollection({
        "_id": "111:7:main",
        "state": "creating",
        "lease_owner": "expired-owner",
        "lease_until": past,
        "channel_name": "🆕main-10-candidate",
        "channel_create_state": "requested",
        "guild_id": 111,
        "category_id": 222,
    })

    class _Rest:
        async def fetch_guild_channels(self, _guild_id):
            return []

    result = asyncio.run(handlers.release_missing_channel_blocker(
        SimpleNamespace(rest=_Rest()),
        SimpleNamespace(ticket_creation_state=collection),
        deepcopy(collection.document),
    ))

    assert result is False
    assert collection.document["state"] == "cleanup_required"
    assert collection.document["channel_name"] == "🆕main-10-candidate"
    assert "expires_at" not in collection.document
    assert collection.deletes == []


def test_only_completed_creation_evidence_receives_expiry(monkeypatch):
    collection = _FenceCollection({
        "_id": "111:7:main",
        "state": "creating",
        "lease_owner": "owner",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(handlers, "_creation_index_ready", False)

    asyncio.run(handlers.ensure_creation_index(mongo))
    assert "expires_at" not in collection.document
    assert collection.update_many_calls == [(
        {"state": {"$ne": "complete"}, "expires_at": {"$exists": True}},
        {"$unset": {"expires_at": ""}},
    )]

    asyncio.run(handlers.complete_creation_state(
        mongo,
        "111:7:main",
        "owner",
        444,
        445,
        "ticket_444",
    ))
    assert collection.document["state"] == "complete"
    assert isinstance(collection.document["expires_at"], datetime)
    assert "lease_owner" not in collection.document


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


@pytest.mark.parametrize("sticky", [False, True])
def test_thread_recovery_outage_claims_nothing_and_preserves_sticky_slot(
    monkeypatch, sticky,
):
    edits = []
    existing_slot = ({
        "_id": "ticket-open:7:main",
        "state": ticket_runtime.SLOT_RESERVED,
        "route": ticket_runtime.ROUTE_THREAD,
        "workflow_id": "thread:7:main",
        "owner_token": "prior-owner",
    } if sticky else None)
    original_slot = deepcopy(existing_slot)

    class _Slots:
        def __init__(self, row):
            self.row = row
            self.reads = []

        async def find_one(self, query):
            self.reads.append(query)
            return self.row

    slots = _Slots(existing_slot)

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            (
                ticket_runtime.ROUTE_LEGACY
                if sticky
                else ticket_runtime.ROUTE_THREAD
            ),
            True,
            (
                ticket_runtime.PHASE_ROLLBACK_LEGACY
                if sticky
                else ticket_runtime.PHASE_THREAD_DEFAULT
            ),
            8,
            "sticky_test",
        )

    async def no_open(*_args, **_kwargs):
        return None

    async def forbidden_claim(*_args, **_kwargs):
        raise AssertionError("recovery outage must not claim or resume a slot")

    async def defer(**_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    ctx = SimpleNamespace(
        guild_id=111,
        channel_id=44,
        user=SimpleNamespace(id=7, username="candidate"),
        member=SimpleNamespace(role_ids=(), display_name="Candidate"),
        defer=defer,
        interaction=SimpleNamespace(
            message=SimpleNamespace(id=55),
            edit_initial_response=edit_initial_response,
        ),
    )
    monkeypatch.setattr(ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers, "find_open_ticket", no_open)
    monkeypatch.setattr(handlers, "_thread_intake_is_ready", lambda: False)
    monkeypatch.setattr(handlers, "claim_public_open_slot", forbidden_claim)
    handlers.user_cooldowns.clear()

    asyncio.run(handlers.handle_create_ticket(
        ctx,
        "main",
        bot=SimpleNamespace(),
        mongo=SimpleNamespace(ticket_open_slots=slots),
    ))

    assert handlers.user_cooldowns == {}
    assert existing_slot == original_slot
    assert slots.reads == [{
        "_id": "ticket-open:7:main",
        "state": {"$in": sorted(ticket_runtime.ACTIVE_SLOT_STATES)},
    }]
    assert "still starting" in edits[-1]["content"]
    if sticky:
        assert "prior ticket attempt remains saved" in edits[-1]["content"]
    else:
        assert "Nothing was created" in edits[-1]["content"]


def test_legacy_commands_and_persistent_actions_are_preserved():
    assert tickets_legacy.ticket.name == "ticket"
    assert {"setup", "config", "approve", "deny", "list", "dashboard"} <= set(
        tickets_legacy.ticket.subcommands
    )
    assert "migrate-store" not in tickets_legacy.ticket.subcommands
    assert "reset-counter" not in tickets_legacy.ticket.subcommands
    assert LEGACY_ACTIONS <= set(registered_functions)
    for action_name in LEGACY_ACTIONS:
        assert "tickets_legacy" in registered_functions[action_name].declared_at


def test_diagnostics_count_only_explicit_thread_v2_authority():
    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, *, length):
            assert length is None
            return self.rows

    class Tickets:
        def __init__(self):
            self.query = None

        def find(self, query, projection):
            self.query = query
            assert projection == {"status": 1}
            return Cursor([{"status": "open"}, {"status": "approved"}])

    tickets = Tickets()
    counts = asyncio.run(legacy_manage._thread_runtime_status_counts(
        SimpleNamespace(tickets=tickets), 111
    ))

    assert tickets.query == {
        "type": "ticket",
        "venue": "thread",
        "runtime": ticket_runtime.THREAD_RUNTIME,
        "guild_id": 111,
    }
    assert counts == {"open": 1, "approved": 1}


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


def test_legacy_insert_never_overwrites_a_thread_row():
    button_store = _AuthorityCollection(existing={
        "_id": "ticket_42",
        "type": "ticket",
        "venue": "thread",
        "runtime": "thread_v2",
    })
    mongo = SimpleNamespace(button_store=button_store)

    with pytest.raises(ValueError, match="non-legacy"):
        asyncio.run(store.insert_one(mongo, {
            "_id": "ticket_42", "type": "ticket", "status": "open",
        }))

    assert button_store.insertions == []
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


def test_recovery_mismatched_authority_fails_closed_without_mutation(monkeypatch):
    state, ticket, slot = _uncertain_commit_documents()
    mismatched = {**ticket, "thread_id": 999}
    authority = _AuthorityCollection(existing=mismatched)
    creation = _FenceCollection(state)
    slots = _FenceCollection(slot)
    queued = []

    async def queue(*_args, **_kwargs):
        queued.append(True)
        return True

    monkeypatch.setattr(handlers, "_queue_committed_initial_delivery", queue)
    mongo = SimpleNamespace(
        button_store=authority,
        ticket_creation_state=creation,
        ticket_open_slots=slots,
    )

    with pytest.raises(ValueError, match="thread_id"):
        asyncio.run(handlers.recover_uncertain_legacy_ticket_creation(
            bot=SimpleNamespace(),
            mongo=mongo,
            creation_id=state["_id"],
            expected_ticket_id=ticket["_id"],
            expected_generation=1,
        ))

    assert authority.existing == mismatched
    assert authority.insertions == []
    assert creation.document["state"] == "cleanup_required"
    assert slots.document["state"] == ticket_runtime.SLOT_RESERVED
    assert queued == []


def test_recovery_respects_active_foreign_creation_lease(monkeypatch):
    state, _ticket, slot = _uncertain_commit_documents()
    state.update({
        "state": "creating",
        "lease_owner": "new-owner",
        "lease_until": datetime.now(timezone.utc) + timedelta(minutes=5),
    })
    authority = _AuthorityCollection()
    queued = []

    async def queue(*_args, **_kwargs):
        queued.append(True)
        return True

    monkeypatch.setattr(handlers, "_queue_committed_initial_delivery", queue)
    mongo = SimpleNamespace(
        button_store=authority,
        ticket_creation_state=_FenceCollection(state),
        ticket_open_slots=_FenceCollection(slot),
    )

    with pytest.raises(RuntimeError, match="lease is active"):
        asyncio.run(handlers.recover_uncertain_legacy_ticket_creation(
            bot=SimpleNamespace(),
            mongo=mongo,
            creation_id=state["_id"],
            creation_owner_token="stale-owner",
            expected_ticket_id="ticket_444",
            expected_generation=1,
        ))

    assert authority.insertions == []
    assert mongo.ticket_open_slots.document == slot
    assert queued == []


@pytest.mark.parametrize("slot_already_released", [False, True])
def test_terminal_late_commit_completes_without_reopening_delivery(
    monkeypatch,
    slot_already_released,
):
    state, ticket, slot = _uncertain_commit_documents(status="approved")
    creation = _FenceCollection(state)
    slots = _FenceCollection(None if slot_already_released else slot)

    async def forbidden_queue(*_args, **_kwargs):
        raise AssertionError("terminal recovery queued opening delivery")

    monkeypatch.setattr(
        handlers, "_queue_committed_initial_delivery", forbidden_queue,
    )
    mongo = SimpleNamespace(
        button_store=_AuthorityCollection(existing=ticket),
        ticket_creation_state=creation,
        ticket_open_slots=slots,
    )

    assert asyncio.run(handlers.recover_uncertain_legacy_ticket_creation(
        bot=SimpleNamespace(),
        mongo=mongo,
        creation_id=state["_id"],
        slot_owner_token="slot-owner",
        expected_ticket_id=ticket["_id"],
        expected_generation=1,
    ))

    assert creation.document["state"] == "complete"
    assert isinstance(creation.document["expires_at"], datetime)
    assert slots.document is None


def test_uncertain_commit_discovery_pages_past_a_failed_first_row(monkeypatch):
    rows = [
        {
            "_id": creation_id,
            "state": "cleanup_required",
            "ticket_id": f"ticket_{index}",
            "ticket_payload": {},
            "commit_started_at": datetime.now(timezone.utc),
            "attempt_generation": 1,
        }
        for index, creation_id in enumerate(("a", "b"), start=1)
    ]

    class _RowsCollection:
        def find(self, query):
            return _ListCursor([row for row in rows if _matches(row, query)])

    seen = []
    scheduled = []

    async def recover(**kwargs):
        seen.append(kwargs["creation_id"])
        if kwargs["creation_id"] == "a":
            raise RuntimeError("deterministic first-row failure")
        return True

    def schedule(**kwargs):
        scheduled.append(kwargs["creation_id"])
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(
        handlers, "recover_uncertain_legacy_ticket_creation", recover,
    )
    monkeypatch.setattr(
        handlers, "schedule_uncertain_legacy_ticket_recovery", schedule,
    )
    result = asyncio.run(handlers.recover_pending_uncertain_legacy_creations(
        bot=SimpleNamespace(),
        mongo=SimpleNamespace(ticket_creation_state=_RowsCollection()),
        limit=1,
    ))

    assert result == {"processed": 2, "completed": 1, "failed": 1}
    assert seen == ["a", "b"]
    assert scheduled == ["a"]


def test_uncertain_commit_startup_discovery_retries_transient_scan_failure(
    monkeypatch,
):
    attempts = []

    async def discover(**_kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise TimeoutError("Mongo scan unavailable")
        return {"processed": 1, "completed": 1, "failed": 0}

    monkeypatch.setattr(
        handlers, "recover_pending_uncertain_legacy_creations", discover,
    )

    async def scenario():
        tickets_legacy._uncertain_commit_discovery = None
        reconciler = tickets_legacy.start_uncertain_commit_discovery(
            SimpleNamespace(), SimpleNamespace(),
        )
        reconciler.retry_delays = (0,)
        try:
            await asyncio.wait_for(reconciler.task, timeout=1)
            return reconciler.health.state, reconciler.health.attempts
        finally:
            await reconciler.stop()
            tickets_legacy._uncertain_commit_discovery = None

    health_state, health_attempts = asyncio.run(scenario())
    assert len(attempts) == 2
    assert health_state == "healthy"
    assert health_attempts == 2


def test_uncertain_commit_discovery_repairs_slot_then_rescans(monkeypatch):
    state, ticket, slot = _uncertain_commit_documents()
    slot["lease_until"] = datetime.now(timezone.utc) + timedelta(minutes=10)
    creation = _FenceCollection(state)
    authority = _AuthorityCollection()
    slots = _FenceCollection(slot)
    queued = []
    repairs = []

    async def queue(_bot, _mongo, ticket_data):
        queued.append(deepcopy(ticket_data))
        return True

    def no_worker(**_kwargs):
        return SimpleNamespace(done=lambda: False)

    async def repair(_mongo):
        repairs.append(True)
        slots.document.update({
            "state": ticket_runtime.SLOT_OPEN,
            "ticket_id": ticket["_id"],
            "location_id": ticket["channel_id"],
        })
        slots.document.pop("owner_token", None)
        slots.document.pop("lease_until", None)
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(handlers, "_queue_committed_initial_delivery", queue)
    monkeypatch.setattr(
        handlers, "schedule_uncertain_legacy_ticket_recovery", no_worker,
    )
    monkeypatch.setattr(ticket_runtime, "recover_ticket_runtime", repair)
    mongo = SimpleNamespace(
        ticket_creation_state=creation,
        button_store=authority,
        ticket_open_slots=slots,
    )

    asyncio.run(tickets_legacy.recover_uncertain_commit_discovery(
        SimpleNamespace(), mongo,
    ))

    assert repairs == [True]
    assert authority.existing == ticket
    assert len(authority.insertions) == 1
    assert slots.document["state"] == ticket_runtime.SLOT_OPEN
    assert creation.document["state"] == "complete"
    assert queued == [ticket]


def test_terminal_commit_releases_shared_slot_after_commit(monkeypatch):
    order = []

    class _Collection:
        async def find_one_and_update(self, _query, _update, **_kwargs):
            order.append("terminal_commit")
            return {
                "_id": "ticket_42",
                "type": "ticket",
                "venue": "channel",
                "runtime": "legacy_channel",
                "status": "approved",
            }

    class _Slots:
        async def find_one(self, _query):
            return None

    async def mark(_mongo, **_kwargs):
        order.append("release_pending")
        return {"state": ticket_runtime.SLOT_RELEASE_PENDING}

    async def release(_mongo, **_kwargs):
        order.append("released")
        return True

    monkeypatch.setattr(ticket_runtime, "mark_slot_release_pending", mark)
    monkeypatch.setattr(ticket_runtime, "release_open_slot", release)
    mongo = SimpleNamespace(
        button_store=_Collection(),
        ticket_open_slots=_Slots(),
    )

    result = asyncio.run(store.transition(
        mongo,
        "ticket_42",
        to_status="approved",
        actor_id=7,
        actor_name="Recruiter",
    ))

    assert result.won
    assert order == ["terminal_commit", "release_pending", "released"]


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
    released = []

    async def allow(*_args):
        return True

    async def no_threads(*_args):
        return set()

    async def release(_mongo, ticket_ids):
        released.extend(ticket_ids)

    class _Rest:
        async def fetch_guild_channels(self, _guild_id):
            return []

    monkeypatch.setattr(legacy_manage.perms, "is_legacy_control_guild", allow)
    monkeypatch.setattr(legacy_manage, "_active_thread_ids", no_threads)
    monkeypatch.setattr(legacy_manage, "_release_terminal_slots", release)
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
    assert released == ["free", "busy"]
    query, update = rows.update_many_calls[0]
    assert "opening_post_intent" not in query["$and"][0]
    assert update["$unset"] == {"opening_post_intent": ""}


def test_fix_mismatched_skips_busy_authority_row(monkeypatch):
    rows = _RowsCollection([
        _janitorial_ticket("free", 444),
        _janitorial_ticket("busy", 555, busy=True),
    ])
    released = []

    async def allow(*_args):
        return True

    async def release(_mongo, ticket_ids):
        released.extend(ticket_ids)

    class _Rest:
        async def fetch_guild_channels(self, _guild_id):
            return [
                SimpleNamespace(id=444, name="❌main-1-candidate"),
                SimpleNamespace(id=555, name="❌main-2-candidate"),
            ]

    monkeypatch.setattr(legacy_manage.perms, "is_legacy_control_guild", allow)
    monkeypatch.setattr(legacy_manage, "_release_terminal_slots", release)
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
    assert released == ["free"]
    assert rows.update_many_calls[0][0]["$and"][0][
        "opening_post_intent"
    ] == {"$exists": False}


def test_override_busy_reports_no_decision_and_runs_no_side_effect(monkeypatch):
    edits = []

    async def state(_mongo, _action_id):
        return {
            "kind": legacy_resolve.KIND_APPROVE,
            "ticket_id": "ticket_42",
            "guild_id": 111,
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
    monkeypatch.setattr(legacy_resolve.perms, "is_legacy_control_guild", allow)
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


def test_public_slot_resume_honors_sticky_runtime(monkeypatch):
    existing = {
        "_id": "ticket-open:7:main",
        "route": ticket_runtime.ROUTE_THREAD,
        "workflow_id": "thread:7:main",
        "state": ticket_runtime.SLOT_RESERVED,
        "owner_token": "prior-owner",
    }
    calls = []

    async def claim(_mongo, **kwargs):
        calls.append(("claim", kwargs["route"]))
        return ticket_runtime.SlotClaim(False, None, existing)

    async def resume(_mongo, **kwargs):
        calls.append(("resume", kwargs))
        return ticket_runtime.SlotClaim(True, "new-owner", existing)

    monkeypatch.setattr(ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(ticket_runtime, "resume_open_slot", resume)

    result = asyncio.run(handlers.claim_public_open_slot(
        object(),
        route=ticket_runtime.ROUTE_LEGACY,
        rollout_revision=9,
        guild_id=1,
        user_id=7,
        ticket_type="main",
    ))

    assert result.won
    assert result.slot["route"] == ticket_runtime.ROUTE_THREAD
    assert calls[0] == ("claim", ticket_runtime.ROUTE_LEGACY)
    assert calls[1][1]["workflow_id"] == "thread:7:main"
    assert calls[1][1]["route"] == ticket_runtime.ROUTE_THREAD
    assert calls[1][1].get("owner_token") is None


def test_fresh_click_cannot_take_an_unexpired_slot_owner(monkeypatch):
    existing = {
        "_id": "ticket-open:7:main",
        "route": ticket_runtime.ROUTE_LEGACY,
        "workflow_id": "legacy:1:7:main",
        "state": ticket_runtime.SLOT_RESERVED,
        "owner_token": "active-worker",
    }

    async def claim(_mongo, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, existing)

    async def resume(_mongo, **kwargs):
        assert kwargs.get("owner_token") is None
        return ticket_runtime.SlotClaim(False, None, existing)

    monkeypatch.setattr(ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(ticket_runtime, "resume_open_slot", resume)

    result = asyncio.run(handlers.claim_public_open_slot(
        object(),
        route=ticket_runtime.ROUTE_LEGACY,
        rollout_revision=9,
        guild_id=1,
        user_id=7,
        ticket_type="main",
    ))

    assert not result.won
    assert result.slot["owner_token"] == "active-worker"


def test_thread_delegate_does_not_cancel_after_service_starts(monkeypatch):
    from extensions.commands import tickets as thread_tickets
    from extensions.commands.tickets import thread_service

    class _Setup:
        async def find_one(self, _query):
            return {}

    class _Interaction:
        def __init__(self):
            self.content = None

        async def edit_initial_response(self, *, content):
            self.content = content

    interaction = _Interaction()
    ctx = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(id=7, username="candidate"),
        member=SimpleNamespace(display_name="Candidate"),
        interaction=interaction,
    )
    slot_claim = ticket_runtime.SlotClaim(True, "owner", {
        "_id": "ticket-open:7:main",
        "workflow_id": "thread:7:main",
        "route": ticket_runtime.ROUTE_THREAD,
    })
    cancelled = []

    async def create(**_kwargs):
        raise RuntimeError("failure after Discord work may have started")

    async def cancel(*_args, **_kwargs):
        cancelled.append(True)
        return True

    monkeypatch.setattr(thread_tickets, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(thread_service, "create_live_thread_ticket", create)
    monkeypatch.setattr(handlers, "cancel_claimed_open_slot", cancel)

    asyncio.run(handlers._create_thread_runtime_ticket(
        ctx,
        SimpleNamespace(),
        SimpleNamespace(ticket_setup=_Setup()),
        "main",
        handlers.datetime.now(handlers.timezone.utc),
        slot_claim,
    ))

    assert cancelled == []
    assert "saved" in interaction.content


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


def test_authoritative_commit_queues_delivery_before_slot_bind():
    source = Path(handlers.__file__).read_text(encoding="utf-8")
    committed = source.index("await store.insert_one(mongo, ticket_data)")
    marked = source.index("ticket_persisted = True", committed)
    queued = source.index(
        "await _queue_committed_initial_delivery(bot, mongo, ticket_data)",
        marked,
    )
    bound = source.index("await ticket_runtime.bind_open_slot", queued)

    assert committed < marked < queued < bound


def test_commit_confirmed_after_error_converges_before_success():
    source = Path(handlers.__file__).read_text(encoding="utf-8")
    exception_branch = source.index("if ticket_persisted:", source.index(
        "creation_commit_confirmed_after_error"
    ))
    recovered = source.index(
        "await recover_uncertain_legacy_ticket_creation(",
        exception_branch,
    )
    responded = source.index(
        "await ctx.interaction.edit_initial_response(", recovered,
    )

    assert exception_branch < recovered < responded


@pytest.mark.parametrize("commit_visible", [False, True], ids=["absent", "late"])
def test_commit_response_loss_converges_exact_ticket_and_completes_online(
    monkeypatch,
    commit_visible,
):
    creation = _FenceCollection({
        "_id": "111:7:main",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "state": "creating",
        "attempt_generation": 1,
        "lease_owner": "creation-owner",
        "lease_until": datetime.now(timezone.utc) + timedelta(minutes=10),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    })
    authority = _AuthorityCollection()
    attempted_ticket = []
    queued_delivery = []
    edits = []
    create_calls = []
    slot_claims = []

    class _Setup:
        async def find_one(self, _query):
            return {"main_category": 222}

    class _Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            create_calls.append("channel")
            return SimpleNamespace(id=444)

        async def create_thread(self, *_args, **_kwargs):
            create_calls.append("thread")
            return SimpleNamespace(id=445)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)
            raise AssertionError("uncertain commit deleted its channel")

    class _Interaction:
        message = SimpleNamespace(id=55)

        async def edit_initial_response(self, **kwargs):
            edits.append(kwargs["content"])

    async def defer(**_kwargs):
        return None

    ctx = SimpleNamespace(
        guild_id=111,
        channel_id=44,
        user=SimpleNamespace(id=7, username="candidate"),
        member=SimpleNamespace(role_ids=()),
        interaction=_Interaction(),
        defer=defer,
    )
    rest = _Rest()
    bot = SimpleNamespace(
        rest=rest,
        get_me=lambda: SimpleNamespace(id=900),
    )
    mongo = SimpleNamespace(
        ticket_creation_state=creation,
        ticket_setup=_Setup(),
        button_store=authority,
        ticket_open_slots=_FenceCollection({
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
            "lease_until": datetime.now(timezone.utc) + timedelta(minutes=10),
        }),
    )
    route = ticket_runtime.RouteDecision(
        ticket_runtime.ROUTE_LEGACY,
        True,
        ticket_runtime.PHASE_PILOT,
        8,
        "late_commit_test",
    )
    slot = ticket_runtime.SlotClaim(True, "slot-owner", {
        "_id": "ticket-open:7:main",
        "workflow_id": "legacy:111:7:main",
        "route": ticket_runtime.ROUTE_LEGACY,
        "rollout_revision": 8,
    })

    async def route_intake(*_args, **_kwargs):
        return route

    async def open_ticket(*_args, **_kwargs):
        return None

    async def no_sticky(*_args, **_kwargs):
        return None

    async def claim_slot(*_args, **_kwargs):
        slot_claims.append(True)
        return slot

    async def claim_creation(*_args, **_kwargs):
        return True, deepcopy(creation.document)

    async def category_space(*_args, **_kwargs):
        return 10

    async def reserve_number(*_args, **_kwargs):
        return 10

    async def response_lost_after_write(_mongo, document):
        attempted_ticket.append(deepcopy(document))
        if commit_visible:
            authority.existing = deepcopy(document)
        raise TimeoutError("ticket write response lost")

    async def negative_commit_read(_mongo, _query):
        return deepcopy(authority.existing)

    async def queue_delivery(_bot, _mongo, ticket_data):
        queued_delivery.append(deepcopy(ticket_data))
        return True

    async def forbidden_rollback(*_args, **_kwargs):
        raise AssertionError("uncertain commit entered destructive rollback")

    async def forbidden_cancel(*_args, **_kwargs):
        raise AssertionError("uncertain commit cancelled its shared slot")

    monkeypatch.setattr(ticket_runtime, "route_public_intake", route_intake)
    monkeypatch.setattr(handlers, "find_open_ticket", open_ticket)
    monkeypatch.setattr(handlers, "_existing_public_open_slot", no_sticky)
    monkeypatch.setattr(handlers, "claim_public_open_slot", claim_slot)
    monkeypatch.setattr(handlers, "claim_ticket_creation", claim_creation)
    monkeypatch.setattr(handlers, "check_category_space", category_space)
    monkeypatch.setattr(handlers, "reserve_ticket_number", reserve_number)
    monkeypatch.setattr(handlers.store, "insert_one", response_lost_after_write)
    monkeypatch.setattr(handlers.store, "find_one", negative_commit_read)
    monkeypatch.setattr(
        handlers, "_queue_committed_initial_delivery", queue_delivery,
    )
    monkeypatch.setattr(handlers, "rollback_ticket_creation", forbidden_rollback)
    monkeypatch.setattr(ticket_runtime, "cancel_open_slot", forbidden_cancel)
    handlers.user_cooldowns.clear()

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=mongo,
    ))

    assert attempted_ticket[0]["_id"] == "ticket_444"
    assert create_calls == ["channel", "thread"]
    assert rest.deleted == []
    assert len(slot_claims) == 1
    assert creation.deletes == []
    assert creation.document["state"] == "complete"
    assert creation.document["channel_id"] == 444
    assert creation.document["thread_id"] == 445
    assert creation.document["ticket_id"] == "ticket_444"
    assert isinstance(creation.document["expires_at"], datetime)
    assert authority.existing == attempted_ticket[0]
    assert len(authority.insertions) == int(not commit_visible)
    assert queued_delivery == [attempted_ticket[0]]
    assert mongo.ticket_open_slots.document["state"] == ticket_runtime.SLOT_OPEN
    assert mongo.ticket_open_slots.document["ticket_id"] == "ticket_444"
    assert mongo.ticket_open_slots.document["location_id"] == 444
    assert "created." in edits[-1]

    # A repeated online/startup pass is a no-op: one ticket, one pair, one slot,
    # and one delivery obligation remain authoritative.
    assert asyncio.run(handlers.recover_uncertain_legacy_ticket_creation(
        bot=bot,
        mongo=mongo,
        creation_id="111:7:main",
    ))

    assert create_calls == ["channel", "thread"]
    assert len(slot_claims) == 1
    assert len(authority.insertions) == int(not commit_visible)
    assert len(queued_delivery) == 1


def test_postcommit_queue_failure_already_has_tracked_online_retry(monkeypatch):
    scheduled = []
    ticket_data = {
        "_id": "ticket_81",
        "channel_id": 81,
        "guild_id": 7,
        "user_id": 181,
        "ticket_type": "main",
        "status": "open",
    }

    def schedule(**kwargs):
        scheduled.append(kwargs)
        return SimpleNamespace(done=lambda: False)

    async def unavailable(_mongo, _ticket_data):
        raise TimeoutError("automation insert unavailable")

    monkeypatch.setattr(
        ticket_channel_monitor,
        "schedule_ticket_automation_delivery_retry",
        schedule,
    )
    monkeypatch.setattr(
        ticket_channel_monitor,
        "ensure_ticket_automation_delivery",
        unavailable,
    )
    bot = SimpleNamespace()
    mongo = SimpleNamespace()

    result = asyncio.run(
        handlers._queue_committed_initial_delivery(bot, mongo, ticket_data)
    )

    assert result is False
    assert scheduled == [{
        "bot": bot,
        "mongo": mongo,
        "ticket_data": ticket_data,
    }]


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
