import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari
import pytest
from bson import BSON
from pymongo.errors import DuplicateKeyError

from extensions import components as dispatcher
from extensions.commands.tickets import (
    close,
    console,
    flag_store,
    migrate,
    perms,
    resolve,
    schema,
    store,
)


NOW = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
MISSING_VALUE = object()


def _values(value, parts):
    if not parts:
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _values(child, parts)]
    if not isinstance(value, dict) or parts[0] not in value:
        return []
    return _values(value[parts[0]], parts[1:])


def _equal(value, expected):
    if isinstance(value, list):
        return expected == value or expected in value
    return value == expected


def _condition(values, expected):
    if not isinstance(expected, dict) or not any(str(key).startswith("$") for key in expected):
        return any(_equal(value, expected) for value in values)
    for operator, operand in expected.items():
        if operator == "$exists":
            if bool(values) != bool(operand):
                return False
        elif operator == "$ne":
            if any(_equal(value, operand) for value in values):
                return False
        elif operator == "$in":
            if not any(any(_equal(value, choice) for choice in operand) for value in values):
                return False
        else:
            raise AssertionError(f"unsupported query operator {operator}")
    return True


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        if not _condition(_values(document, key.split(".")), expected):
            return False
    return True


def _get(document, path, default=MISSING_VALUE):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _set(document, path, value):
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _unset(document, path):
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target.get(part, {})
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def _apply(document, update, *, inserting=False):
    if inserting:
        for path, value in update.get("$setOnInsert", {}).items():
            _set(document, path, value)
    for path, value in update.get("$set", {}).items():
        _set(document, path, value)
    for path in update.get("$unset", {}):
        _unset(document, path)
    for path, amount in update.get("$inc", {}).items():
        current = _get(document, path, 0)
        _set(document, path, current + amount)
    for path, value in update.get("$max", {}).items():
        current = _get(document, path, MISSING_VALUE)
        if current is MISSING_VALUE or value > current:
            _set(document, path, value)
    for path, value in update.get("$push", {}).items():
        current = list(_get(document, path, []))
        if isinstance(value, dict) and "$each" in value:
            current.extend(deepcopy(value["$each"]))
            if "$slice" in value:
                current = current[value["$slice"]:]
        else:
            current.append(deepcopy(value))
        _set(document, path, current)
    for path, value in update.get("$addToSet", {}).items():
        current = list(_get(document, path, []))
        additions = value.get("$each", []) if isinstance(value, dict) else [value]
        for item in additions:
            if item not in current:
                current.append(deepcopy(item))
        _set(document, path, current)


class Result:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, spec):
        for path, direction in reversed(spec):
            self.documents.sort(
                key=lambda item: _get(item, path, ""), reverse=direction < 0
            )
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    async def to_list(self, length=None):
        return deepcopy(self.documents if length is None else self.documents[:length])


class Collection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}
        self.indexes = []

    async def find_one(self, query, *_args, **_kwargs):
        return next(
            (deepcopy(document) for document in self.documents.values() if _matches(document, query)),
            None,
        )

    def find(self, query, *_args, **_kwargs):
        return Cursor(document for document in self.documents.values() if _matches(document, query))

    async def update_one(self, query, update, *, upsert=False, **_kwargs):
        for key, document in self.documents.items():
            if _matches(document, query):
                _apply(document, update)
                self.documents[key] = document
                return Result(1)
        if upsert:
            document = {}
            for path, value in query.items():
                if not path.startswith("$") and not isinstance(value, dict):
                    _set(document, path, value)
            _apply(document, update, inserting=True)
            self.documents[document["_id"]] = document
        return Result(0)

    async def find_one_and_update(self, query, update, **_kwargs):
        for key, document in self.documents.items():
            if _matches(document, query):
                _apply(document, update)
                self.documents[key] = document
                return deepcopy(document)
        return None

    async def replace_one(self, query, document, *, upsert=False, **_kwargs):
        existing = await self.find_one(query)
        if existing is not None or upsert:
            self.documents[document["_id"]] = deepcopy(document)
            return Result(1 if existing is not None else 0)
        return Result(0)

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def create_index(self, spec, **kwargs):
        self.indexes.append((spec, kwargs))
        return kwargs.get("name")


class SetupCollection(Collection):
    def __init__(self):
        super().__init__([{
            "_id": "config",
            "ticket_store": "tickets",
            "ticket_store_activation_version": store.CANONICAL_ACTIVATION_VERSION,
        }])


def _mongo(*documents):
    return SimpleNamespace(
        tickets=Collection(documents),
        button_store=Collection(),
        ticket_setup=SetupCollection(),
        ticket_flags=Collection(),
    )


def _ticket(*, public=101, staff=102, number=1, status="open", source=None, user=30):
    return schema.new_ticket_document(
        ticket_type="main",
        ticket_number=number,
        guild_id=10,
        public_thread_id=public,
        public_parent_id=20,
        staff_thread_id=staff,
        staff_parent_id=21,
        user_id=user,
        username="Applicant",
        player_tags=("abc123",),
        created_at=NOW,
        status=status,
        source=source,
    )


def test_canonical_constructor_normalizes_ids_search_and_creation_audit():
    ticket = schema.new_ticket_document(
        ticket_type="MAIN", ticket_number="7", guild_id="10",
        public_thread_id="101", public_parent_id="20", staff_thread_id="102",
        staff_parent_id="21", user_id="30", username=" Applicant ",
        player_tags=("abc123", "#ABC123"), created_at=NOW,
    )
    assert ticket["_id"] == "ticket_101"
    assert ticket["venue"] == "thread"
    assert ticket["location"] == {
        "guild_id": 10, "id": 101, "public_parent_id": 20,
        "staff_space_id": 102, "staff_parent_id": 21,
    }
    assert ticket["player_tags"] == ["#ABC123"]
    assert ticket["audit"] == [{
        "event": "ticket_created", "at": NOW, "actor": 30,
        "actor_name": "Applicant", "status": "open", "rev": 0,
    }]
    assert not schema.CLAIM_FIELDS.intersection(ticket)


def test_migrated_terminal_ticket_has_source_creation_audit_and_closed_is_blocked():
    source = {"guild_id": "1", "channel_id": "2"}
    ticket = _ticket(status="denied", source=source)
    assert ticket["audit"][0]["event"] == "legacy_ticket_imported"
    assert ticket["audit"][0]["source"]["channel_id"] == 2
    with pytest.raises(schema.TicketSchemaError, match="explicit approved/denied"):
        schema.normalize_ticket_document({"_id": "legacy", "status": "closed"})


def test_store_migration_requires_explicit_closed_classification():
    source = [{"_id": "legacy_closed", "type": "ticket", "status": "closed"}]
    with pytest.raises(migrate.ClosedClassificationError, match="closed-ticket-id"):
        migrate.prepare_source_documents(
            source,
            closed_ticket_id=None,
            closed_status=None,
            actor_id=99,
            actor_name="Operator",
            now=NOW,
        )
    assert source[0]["status"] == "closed"


def test_store_activation_blocks_open_legacy_channels_but_allows_terminal_history():
    open_legacy = migrate._transform({
        "_id": "legacy_open",
        "type": "ticket",
        "status": "open",
        "channel_id": 101,
    })
    terminal_legacy = migrate._transform({
        "_id": "legacy_denied",
        "type": "ticket",
        "status": "denied",
        "channel_id": 102,
    })
    live_thread = _ticket(public=201, staff=202, number=2)

    with pytest.raises(migrate.OpenLegacyTicketsError, match="Resolve each source ticket"):
        migrate.ensure_no_open_legacy_tickets([open_legacy, terminal_legacy, live_thread])
    migrate.ensure_no_open_legacy_tickets([terminal_legacy, live_thread])


def test_store_migration_classifies_closed_once_with_audit_and_revision():
    source = [{
        "_id": "legacy_closed",
        "type": "ticket",
        "status": "closed",
        "rev": 4,
        "audit": [],
    }]
    prepared, classification = migrate.prepare_source_documents(
        source,
        closed_ticket_id="legacy_closed",
        closed_status="denied",
        actor_id=99,
        actor_name="Operator",
        now=NOW,
    )
    assert source[0]["status"] == "closed"
    assert prepared[0]["status"] == "denied"
    assert prepared[0]["rev"] == 5
    assert prepared[0]["audit"][-1] == {
        "event": "legacy_closed_classified",
        "at": NOW.replace(tzinfo=None),
        "actor": 99,
        "actor_name": "Operator",
        "from": "closed",
        "to": "denied",
        "rev_before": 4,
        "rev_after": 5,
    }
    assert classification["needs_source_write"] is True
    assert migrate._status_counts(prepared) == {"denied": 1}

    retry, retry_classification = migrate.prepare_source_documents(
        prepared,
        closed_ticket_id="legacy_closed",
        closed_status="denied",
        actor_id=99,
        actor_name="Operator",
        now=NOW,
    )
    assert retry == prepared
    assert retry_classification["needs_source_write"] is False


def test_store_migration_normalizes_generated_datetimes_to_bson_precision(monkeypatch):
    sub_millisecond = NOW.replace(microsecond=123456)
    source = [{"_id": "legacy_closed", "type": "ticket", "status": "closed"}]
    prepared, _ = migrate.prepare_source_documents(
        source,
        closed_ticket_id="legacy_closed",
        closed_status="approved",
        actor_id=99,
        actor_name="Operator",
        now=sub_millisecond,
    )
    assert prepared[0]["updated_at"].microsecond == 123000
    assert prepared[0]["updated_at"].tzinfo is None
    assert prepared[0]["audit"][-1]["at"].microsecond == 123000
    assert BSON.encode(prepared[0]).decode() == prepared[0]

    monkeypatch.setattr(schema, "utcnow", lambda: sub_millisecond)
    normalized = migrate._transform({
        "_id": "legacy_terminal",
        "type": "ticket",
        "status": "denied",
    })
    backfill = next(
        item for item in normalized["audit"] if item["event"] == "schema_backfilled"
    )
    assert backfill["at"].microsecond == 123000
    assert backfill["at"].tzinfo is None
    assert BSON.encode(normalized).decode() == normalized


def test_store_migration_rejects_wrong_or_silently_terminal_classification():
    closed = [{"_id": "legacy_closed", "type": "ticket", "status": "closed"}]
    with pytest.raises(migrate.ClosedClassificationError, match="does not identify"):
        migrate.prepare_source_documents(
            closed,
            closed_ticket_id="other",
            closed_status="approved",
            actor_id=99,
            actor_name="Operator",
            now=NOW,
        )
    terminal = [{"_id": "legacy_closed", "type": "ticket", "status": "approved"}]
    with pytest.raises(migrate.ClosedClassificationError, match="not an unclassified"):
        migrate.prepare_source_documents(
            terminal,
            closed_ticket_id="legacy_closed",
            closed_status="approved",
            actor_id=99,
            actor_name="Operator",
            now=NOW,
        )


def test_store_migration_activation_is_atomic_and_verified():
    expected = _ticket()
    mongo = _mongo(expected)
    mongo.ticket_setup.documents["config"]["ticket_store"] = "button_store"
    mongo.ticket_setup.documents["config"].pop("ticket_store_activation_version")
    asyncio.run(migrate.activate_canonical_store(
        mongo,
        expected_documents=[expected],
        actor_id=99,
        actor_name="Operator",
        now=NOW,
    ))
    config = mongo.ticket_setup.documents["config"]
    assert config["ticket_store"] == "tickets"
    assert (
        config["ticket_store_activation_version"]
        == store.CANONICAL_ACTIVATION_VERSION
    )
    assert config["ticket_store_activated_by"] == 99
    assert config["ticket_store_activated_at"] == NOW.replace(tzinfo=None)
    assert asyncio.run(store.active_store(mongo)) == "tickets"

    # A clean rerun verifies the same exact dataset and remains safely active.
    asyncio.run(migrate.activate_canonical_store(
        mongo,
        expected_documents=[expected],
        actor_id=99,
        actor_name="Operator",
        now=NOW,
    ))
    assert mongo.tickets.documents == {expected["_id"]: expected}


@pytest.mark.parametrize("mismatch", ["unexpected", "missing", "divergent"])
def test_store_activation_rejects_nonexact_destination_without_mutation(mismatch):
    expected = _ticket()
    observed = [deepcopy(expected)]
    if mismatch == "unexpected":
        observed.append(_ticket(public=201, staff=202, number=2, user=31))
    elif mismatch == "missing":
        observed.clear()
    else:
        observed[0]["username"] = "Changed elsewhere"

    mongo = _mongo(*observed)
    config = mongo.ticket_setup.documents["config"]
    config["ticket_store"] = "button_store"
    config.pop("ticket_store_activation_version")
    before_tickets = deepcopy(mongo.tickets.documents)
    before_config = deepcopy(config)

    with pytest.raises(migrate.CanonicalDatasetMismatchError, match=mismatch):
        asyncio.run(migrate.activate_canonical_store(
            mongo,
            expected_documents=[expected],
            actor_id=99,
            actor_name="Operator",
            now=NOW,
        ))

    assert mongo.ticket_setup.documents["config"] == before_config
    assert mongo.tickets.documents == before_tickets
    assert asyncio.run(store.active_store(mongo)) == store.STORE_BUTTON


@pytest.mark.parametrize("config", [
    None,
    {"_id": "config"},
    {"_id": "config", "ticket_store": "unexpected"},
    {"_id": "config", "ticket_store": "tickets"},
    {
        "_id": "config",
        "ticket_store": "tickets",
        "ticket_store_activation_version": 2,
    },
])
def test_missing_or_invalid_store_activation_fails_closed_to_legacy(config):
    documents = [] if config is None else [config]
    mongo = SimpleNamespace(ticket_setup=Collection(documents))
    assert asyncio.run(store.active_store(mongo)) == store.STORE_BUTTON


def test_backfill_normalizes_mixed_ids_adds_audit_and_removes_claim_fields():
    normalized = schema.normalize_ticket_document({
        "_id": "legacy", "status": "approved", "ticket_type": "MAIN",
        "guild_id": "10", "channel_id": "101", "thread_id": "102",
        "user_id": "30", "username": " Applicant ", "player_tag": "abc123",
        "claimed_by": 99, "claimed_at": NOW, "created_at": NOW,
    })
    assert normalized["venue"] == "channel"
    assert normalized["location"]["id"] == 101
    assert normalized["user_id"] == 30
    assert normalized["player_tags"] == ["#ABC123"]
    assert normalized["audit"][-1]["event"] == "schema_backfilled"
    assert not schema.CLAIM_FIELDS.intersection(normalized)


def test_index_preflight_allows_repeat_terminal_tickets_but_blocks_two_open():
    terminal = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    later = _ticket(public=201, staff=202, number=2, user=30)
    assert "open_applicant" not in store.index_conflicts_for_documents([terminal, later])
    first_open = _ticket()
    conflicts = store.index_conflicts_for_documents([first_open, later])
    assert conflicts["open_applicant"][0]["key"] == (30, "main")


def test_index_installation_uses_preflighted_partial_unique_contracts():
    mongo = _mongo(_ticket())
    names = asyncio.run(store.ensure_indexes(mongo))
    assert "one_open_ticket_per_applicant_type" in names
    open_index = next(
        options for _spec, options in mongo.tickets.indexes
        if options.get("name") == "one_open_ticket_per_applicant_type"
    )
    assert open_index["unique"] is True
    assert open_index["partialFilterExpression"] == {
        "type": "ticket", "venue": "thread", "status": "open",
        "user_id": {"$exists": True}, "ticket_type": {"$exists": True},
    }


def test_runtime_lookup_fails_closed_for_legacy_channel_rows():
    legacy = schema.normalize_ticket_document({
        "_id": "legacy", "status": "open", "ticket_type": "main",
        "channel_id": 101, "user_id": 30,
    })
    mongo = _mongo(legacy)
    assert asyncio.run(store.find_by_location(mongo, 101)) is None


def test_ticket_authorization_is_bound_to_the_configured_target_guild():
    mongo = SimpleNamespace(ticket_setup=Collection([{
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": "101",
        "fwa_recruiter_role": 102,
    }]))
    target_recruiter = SimpleNamespace(
        guild_id=10,
        role_ids=(101,),
        permissions=hikari.Permissions.NONE,
    )
    target_admin = SimpleNamespace(
        guild_id=10,
        role_ids=(),
        permissions=hikari.Permissions.ADMINISTRATOR,
    )
    foreign_admin = SimpleNamespace(
        guild_id=99,
        role_ids=(101,),
        permissions=hikari.Permissions.ADMINISTRATOR,
    )
    assert asyncio.run(perms.is_recruiter(target_recruiter, mongo)) is True
    assert asyncio.run(perms.is_recruiter(target_admin, mongo)) is True
    assert asyncio.run(perms.is_recruiter(foreign_admin, mongo)) is False
    assert asyncio.run(perms.is_target_admin(target_recruiter, mongo)) is False
    assert asyncio.run(perms.is_target_admin(target_admin, mongo)) is True
    assert asyncio.run(perms.is_target_admin(foreign_admin, mongo)) is False


def test_foreign_guild_admin_cannot_read_or_mutate_private_ticket_data(monkeypatch):
    mongo = SimpleNamespace(ticket_setup=Collection([{
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": 101,
    }]))
    foreign_admin = SimpleNamespace(
        id=99,
        guild_id=99,
        role_ids=(101,),
        permissions=hikari.Permissions.ADMINISTRATOR,
    )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("private ticket data was accessed after guild mismatch")

    monkeypatch.setattr(resolve.store, "find_one", forbidden)
    resolution = asyncio.run(resolve.approve_ticket(
        SimpleNamespace(),
        mongo,
        ticket_id="ticket_101",
        member=foreign_admin,
        actor_name="Foreign admin",
    ))
    assert resolution.outcome == store.UNAUTHORIZED

    monkeypatch.setattr(flag_store, "set_flag", forbidden)
    flag = asyncio.run(flag_store.set_flag_authorized(
        mongo,
        member=foreign_admin,
        actor_name="Foreign admin",
        kind=flag_store.FLAG_BLACKLISTED,
        discord_ids=(123456789012345678,),
        source="test",
    ))
    assert flag.outcome == store.UNAUTHORIZED

    responses = []

    async def respond(content, **kwargs):
        responses.append((content, kwargs))

    ctx = SimpleNamespace(member=foreign_admin, respond=respond)
    assert asyncio.run(console._require_recruiter(ctx, mongo)) is False
    assert responses[0][0] == "Only recruiters can use the ticket console."


def test_insert_is_idempotent_and_mirror_failure_does_not_undo_primary():
    class FailingMirror(Collection):
        async def replace_one(self, *_args, **_kwargs):
            raise TimeoutError("mirror unavailable")

    mongo = _mongo()
    mongo.button_store = FailingMirror()
    ticket = _ticket()
    first = asyncio.run(store.insert_one(mongo, ticket))
    second = asyncio.run(store.insert_one(mongo, ticket))
    assert first == second == ticket
    assert mongo.tickets.documents[ticket["_id"]] == ticket


def test_status_transition_is_cas_audited_and_missing_has_no_write():
    mongo = _mongo(_ticket())
    won = asyncio.run(store.transition(
        mongo, "ticket_101", to_status="approved", actor_id=99,
        actor_name="Recruiter", expected_rev=0, effect_kind=resolve.KIND_APPROVE,
    ))
    assert won.outcome == store.WON
    assert won.doc["status"] == "approved"
    assert won.doc["rev"] == 1
    assert won.doc["resolution_effects"]["notification"]["state"] == "pending"
    assert won.doc["audit"][-1]["from"] == "open"
    before = deepcopy(mongo.tickets.documents)
    lost = asyncio.run(store.transition(
        mongo, "ticket_101", to_status="denied", actor_id=98,
        actor_name="Late", expect="open", expected_rev=0,
    ))
    assert lost.outcome == store.LOST
    assert mongo.tickets.documents == before
    missing = asyncio.run(store.transition(
        mongo, "ticket_missing", to_status="denied", actor_id=98,
        actor_name="Late",
    ))
    assert missing.outcome == store.MISSING
    assert mongo.tickets.documents == before


def test_override_requires_observed_terminal_revision_and_records_prior_decision():
    prior_marker = "ticket-resolution:ticket_101:4:approved"
    terminal = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    terminal.update({
        "rev": 4,
        "approved_by": 40,
        "approved_at": NOW,
        "resolution_effects": {
            "marker": prior_marker,
            "complete": True,
        },
    })
    mongo = _mongo(terminal)
    result = asyncio.run(store.transition(
        mongo, terminal["_id"], to_status="denied", actor_id=50,
        actor_name="Lead", expect="approved", expected_rev=4,
        overrides={"status": "approved", "rev": 4, "by": 40, "at": NOW},
        extra={"denial_type": "custom", "denial_reason": "Appeal reviewed"},
        effect_kind=resolve.KIND_DENY_CUSTOM,
        prior_effect_marker=prior_marker,
    ))
    assert result.won
    assert result.doc["status"] == "denied"
    assert result.doc["rev"] == 5
    assert "approved_by" not in result.doc
    assert result.doc["audit"][-1]["overrode"]["by"] == 40


def test_override_cas_requires_exact_completed_prior_effect_marker():
    prior_marker = "ticket-resolution:ticket_101:4:approved"
    terminal = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    terminal.update({
        "rev": 4,
        "approved_by": 40,
        "approved_at": NOW,
        "resolution_effects": {
            "marker": prior_marker,
            "complete": False,
        },
    })
    mongo = _mongo(terminal)
    kwargs = {
        "to_status": "denied",
        "actor_id": 50,
        "actor_name": "Lead",
        "expect": "approved",
        "expected_rev": 4,
        "overrides": {"status": "approved", "rev": 4, "by": 40, "at": NOW},
        "extra": {"denial_type": "custom", "denial_reason": "Appeal reviewed"},
        "effect_kind": resolve.KIND_DENY_CUSTOM,
    }

    incomplete = asyncio.run(store.transition(
        mongo,
        terminal["_id"],
        prior_effect_marker=prior_marker,
        **kwargs,
    ))
    assert incomplete.outcome == store.LOST
    assert mongo.tickets.documents[terminal["_id"]]["status"] == "approved"

    mongo.tickets.documents[terminal["_id"]]["resolution_effects"]["complete"] = True
    wrong_marker = asyncio.run(store.transition(
        mongo,
        terminal["_id"],
        prior_effect_marker="ticket-resolution:other",
        **kwargs,
    ))
    assert wrong_marker.outcome == store.LOST
    assert mongo.tickets.documents[terminal["_id"]]["status"] == "approved"


@pytest.mark.parametrize(
    "provenance_event",
    ["legacy_ticket_imported", "legacy_location_replaced"],
)
def test_markerless_imported_terminal_offer_and_override_remain_available(
    monkeypatch,
    provenance_event,
):
    terminal = _ticket(
        status="approved",
        source={"guild_id": 1, "channel_id": 2},
    )
    terminal["audit"] = [{"event": provenance_event, "at": NOW, "rev": 0}]
    mongo = _mongo(terminal)
    state = {}
    deleted = []
    edits = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def insert(_mongo, document):
        state.update(deepcopy(document))

    async def get(_mongo, action_id):
        assert action_id == state["_id"]
        return deepcopy(state)

    async def delete(_mongo, action_id):
        deleted.append(action_id)

    async def effects(_bot, _mongo, ticket):
        return store.Transition(store.WON, ticket)

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    async def respond(*_args, **_kwargs):
        raise AssertionError("the owner-bound override should edit its original response")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "insert_state", insert)
    monkeypatch.setattr(resolve, "get_state", get)
    monkeypatch.setattr(resolve, "delete_state", delete)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    ctx = SimpleNamespace(
        member=SimpleNamespace(id=50),
        user=SimpleNamespace(id=50, username="Lead"),
        respond=respond,
        interaction=SimpleNamespace(
            id=444,
            edit_initial_response=edit_initial_response,
        ),
    )

    async def run():
        _content, rows = await resolve.offer_override(
            ctx,
            mongo,
            kind=resolve.KIND_DENY_CUSTOM,
            current=terminal,
            ticket_id=terminal["_id"],
            channel_id=101,
            user_id=30,
            reason="Appeal reviewed",
        )
        assert rows
        await resolve.ticket_override_handler(
            ctx,
            state["_id"],
            mongo=mongo,
            bot=SimpleNamespace(),
        )

    asyncio.run(run())

    assert state["prior_effect_marker"] == ""
    assert state["prior_effects_legacy_baseline"] is True
    assert mongo.tickets.documents[terminal["_id"]]["status"] == "denied"
    assert mongo.tickets.documents[terminal["_id"]]["rev"] == 1
    assert deleted == ["444"]
    assert edits[-1]["components"] == []


def test_candidate_activity_is_idempotent_and_merges_normalized_tags():
    mongo = _mongo(_ticket())
    first = asyncio.run(store.append_candidate_activity(
        mongo, "ticket_101", message_id=500, author_id=30,
        content="My tag is #def456", player_tags=("def456",), occurred_at=NOW,
    ))
    again = asyncio.run(store.append_candidate_activity(
        mongo, "ticket_101", message_id=500, author_id=30,
        content="My tag is #def456", player_tags=("def456",), occurred_at=NOW,
    ))
    assert first.won and again.won
    assert again.reason == "already recorded"
    assert again.doc["answer_count"] == 1
    assert again.doc["player_tags"] == ["#ABC123", "#DEF456"]


@pytest.mark.parametrize("mode", ["unauthorized", "missing", "blacklisted", "lost"])
def test_secure_approval_stops_before_side_effects(monkeypatch, mode):
    calls = []
    ticket = _ticket()

    async def recruiter(*_args):
        calls.append("permission")
        return mode != "unauthorized"

    async def find(*_args, **_kwargs):
        calls.append("find")
        return None if mode == "missing" else ticket

    async def blacklist(*_args, **_kwargs):
        calls.append("blacklist")
        return {"_id": "flag"} if mode == "blacklisted" else None

    async def transition(*_args, **_kwargs):
        calls.append("transition")
        return store.Transition(store.LOST, ticket)

    async def effects(*_args, **_kwargs):
        calls.append("effects")
        raise AssertionError("side effects must not run")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", find)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    monkeypatch.setattr(resolve.store, "transition", transition)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    mongo = SimpleNamespace(ticket_flags=Collection())
    result = asyncio.run(resolve.approve_ticket(
        SimpleNamespace(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
    ))
    expected = {
        "unauthorized": store.UNAUTHORIZED,
        "missing": store.MISSING,
        "blacklisted": store.BLOCKED,
        "lost": store.LOST,
    }[mode]
    assert result.outcome == expected
    assert "effects" not in calls
    if mode == "unauthorized":
        assert calls == ["permission"]
    if mode == "missing":
        assert calls == ["permission", "find"]
    if mode == "blacklisted":
        assert "transition" not in calls


def _effect_ticket():
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "handled_by_name": "Recruiter",
        "denial_type": "custom",
        "denial_reason": "Not eligible",
        "resolution_effects": {
            "marker": "ticket-resolution:ticket_101:1:denied",
            "kind": resolve.KIND_DENY_CUSTOM,
            "notification": {"state": "pending"},
            "archive": {"state": "pending"},
            "hub": {"state": "pending"},
            "complete": False,
        },
    })
    return ticket


def test_applicant_resolution_messages_suppress_unrelated_mentions():
    class Rest:
        def __init__(self):
            self.kwargs = None

        async def create_message(self, **kwargs):
            self.kwargs = kwargs

    rest = Rest()
    asyncio.run(resolve.apply_denial(
        SimpleNamespace(rest=rest),
        SimpleNamespace(),
        kind=resolve.KIND_DENY_CUSTOM,
        ticket=_effect_ticket(),
        reason="Do not ping @everyone or <@&123456789012345678>.",
    ))
    assert rest.kwargs["mentions_everyone"] is False
    assert rest.kwargs["role_mentions"] is False
    assert rest.kwargs["user_mentions"] == [30]


class MessageIterator:
    def __init__(self, rest):
        self.rest = rest

    async def to_list(self):
        return list(self.rest.messages)


class EffectRest:
    def __init__(self, *, archived=False, locked=False):
        self.messages = []
        self.channels = {
            thread_id: SimpleNamespace(
                id=thread_id,
                is_archived=archived,
                is_locked=locked,
            )
            for thread_id in (101, 102)
        }
        self.fetch_channel_calls = []
        self.edits = []

    def fetch_messages(self, _channel_id):
        return MessageIterator(self)

    async def fetch_channel(self, channel_id):
        self.fetch_channel_calls.append(channel_id)
        return self.channels[channel_id]

    async def edit_channel(self, channel_id, **kwargs):
        self.edits.append((channel_id, kwargs))
        current = self.channels[channel_id]
        updated = SimpleNamespace(
            id=channel_id,
            is_archived=kwargs.get("archived", current.is_archived),
            is_locked=kwargs.get("locked", current.is_locked),
        )
        self.channels[channel_id] = updated
        return updated


def _effect_bot(rest):
    return SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))


def test_override_waits_for_prior_notice_before_sending_replacement(monkeypatch):
    prior_marker = "ticket-resolution:ticket_101:1:approved"
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 1,
        "approved_by": 9,
        "approved_at": NOW,
        "resolution_effects": {
            "version": 1,
            "marker": prior_marker,
            "kind": resolve.KIND_APPROVE,
            "notification": {"state": "pending"},
            "archive": {"state": "pending"},
            "hub": {"state": "pending"},
            "complete": False,
        },
    })
    mongo = _mongo(ticket)
    rest = EffectRest()
    bot = _effect_bot(rest)
    state = {}
    deleted = []
    edits = []
    notices = []
    notification_started = asyncio.Event()
    release_notification = asyncio.Event()

    async def recruiter(*_args, **_kwargs):
        return True

    async def insert(_mongo, document):
        state.update(deepcopy(document))

    async def get(_mongo, action_id):
        assert action_id == state["_id"]
        return deepcopy(state)

    async def delete(_mongo, action_id):
        deleted.append(action_id)

    async def notification(*_args, marker, **_kwargs):
        if marker == prior_marker:
            notification_started.set()
            await release_notification.wait()
        notices.append(marker)
        rest.messages.append(SimpleNamespace(
            content=f"-# {marker}",
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def refresh(*_args, **_kwargs):
        return True

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    async def respond(*_args, **_kwargs):
        raise AssertionError("the owner-bound override should edit its original response")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "insert_state", insert)
    monkeypatch.setattr(resolve, "get_state", get)
    monkeypatch.setattr(resolve, "delete_state", delete)
    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)
    ctx = SimpleNamespace(
        member=SimpleNamespace(id=50),
        user=SimpleNamespace(id=50, username="Lead"),
        respond=respond,
        interaction=SimpleNamespace(
            id=555,
            edit_initial_response=edit_initial_response,
        ),
    )

    async def run():
        _content, rows = await resolve.offer_override(
            ctx,
            mongo,
            kind=resolve.KIND_DENY_CUSTOM,
            current=ticket,
            ticket_id=ticket["_id"],
            channel_id=101,
            user_id=30,
            reason="Appeal reviewed",
        )
        assert rows

        first_worker = asyncio.create_task(
            resolve.process_resolution_effects(bot, mongo, ticket)
        )
        await notification_started.wait()

        await resolve.ticket_override_handler(
            ctx,
            state["_id"],
            mongo=mongo,
            bot=bot,
        )
        durable = mongo.tickets.documents[ticket["_id"]]
        assert durable["status"] == "approved"
        assert durable["resolution_effects"]["complete"] is False
        assert notices == []
        assert deleted == []
        assert edits[-1]["content"] == resolve.OVERRIDE_EFFECT_PENDING_MESSAGE
        assert edits[-1]["components"]

        release_notification.set()
        first_result = await first_worker
        assert first_result.won
        assert notices == [prior_marker]

        await resolve.ticket_override_handler(
            ctx,
            state["_id"],
            mongo=mongo,
            bot=bot,
        )

    asyncio.run(run())

    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["status"] == "denied"
    assert notices[0] == prior_marker
    assert notices[1] == durable["resolution_effects"]["marker"]
    assert notices[1].endswith(":denied")
    assert notices.count(prior_marker) == 1
    assert deleted == ["555"]
    assert edits[-1]["components"] == []


def test_checkpoint_failure_after_notification_does_not_report_false_failure(monkeypatch):
    ticket = _effect_ticket()
    rest = EffectRest()
    sends = []
    archives = []
    checkpoint_failed = False

    async def side_effects(*_args, marker, **_kwargs):
        sends.append(marker)
        rest.messages.append(SimpleNamespace(
            content=marker,
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def update(_mongo, _filter, update):
        nonlocal checkpoint_failed
        fields = update.get("$set", {})
        if "resolution_effects.notification" in fields and not checkpoint_failed:
            checkpoint_failed = True
            raise TimeoutError("acknowledgement lost")
        return Result(1)

    async def archive(*_args):
        archives.append(True)

    async def refresh(*_args, **_kwargs):
        return True

    async def latest(*_args, **_kwargs):
        return ticket

    async def acquire(*_args, **_kwargs):
        return ticket

    async def release(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolve, "run_side_effects", side_effects)
    monkeypatch.setattr(resolve.store, "update_one", update)
    monkeypatch.setattr(resolve.store, "find_one", latest)
    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(resolve.thread_service, "archive_ticket_pair", archive)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)
    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), SimpleNamespace(), ticket
    ))
    assert result.won
    assert sends == [ticket["resolution_effects"]["marker"]]
    assert archives == [True]


def test_notification_failure_still_archives_and_requests_hub(monkeypatch):
    ticket = _effect_ticket()
    mongo = _mongo(ticket)
    rest = EffectRest()
    calls = []

    async def notification(*_args, **_kwargs):
        calls.append("notification")
        raise TimeoutError("notification unavailable")

    async def archive(*_args):
        calls.append("archive")

    async def refresh(*_args, **_kwargs):
        calls.append("hub")
        return True

    async def acquire(received_mongo, *_args, **_kwargs):
        return await store.find_one(
            received_mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
        )

    async def release(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(resolve.thread_service, "archive_ticket_pair", archive)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.outcome == store.EFFECT_FAILED
    assert calls == ["notification", "archive", "hub"]
    assert result.reason == "TimeoutError: applicant notification is pending"
    effects = result.doc["resolution_effects"]
    assert effects["notification"]["state"] == "failed"
    assert effects["archive"]["state"] == "archived"
    assert effects["hub"]["state"] == "requested"
    assert effects["complete"] is False


def test_notification_retry_reopens_only_to_write_and_rearchives(monkeypatch):
    ticket = _effect_ticket()
    ticket["resolution_effects"].update({
        "notification": {"state": "failed"},
        "archive": {"state": "archived"},
        "hub": {"state": "requested"},
    })
    mongo = _mongo(ticket)
    rest = EffectRest(archived=True, locked=True)
    notices = []

    async def notification(*_args, marker, **_kwargs):
        notices.append(marker)
        rest.messages.append(SimpleNamespace(
            content=f"-# {marker}",
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def acquire(received_mongo, *_args, **_kwargs):
        return await store.find_one(
            received_mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
        )

    async def release(*_args, **_kwargs):
        return None

    async def no_hub_retry(*_args, **_kwargs):
        raise AssertionError("an already-requested hub refresh was queued again")

    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", no_hub_retry)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.won
    assert notices == [ticket["resolution_effects"]["marker"]]
    assert rest.edits == [
        (101, {
            "archived": False,
            "reason": "Delivering an updated ticket decision",
        }),
        (101, {
            "locked": False,
            "reason": "Delivering an updated ticket decision",
        }),
        (101, {
            "locked": True,
            "archived": True,
            "reason": "Archiving resolved ticket",
        }),
    ]
    assert all(
        channel.is_archived and channel.is_locked
        for channel in rest.channels.values()
    )
    assert result.doc["resolution_effects"]["complete"] is True

    edits = list(rest.edits)
    again = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, result.doc
    ))
    assert again.won
    assert notices == [ticket["resolution_effects"]["marker"]]
    assert rest.edits == edits


@pytest.mark.parametrize("cancel_stage", ["before", "during", "after"])
def test_resolution_notification_cancellation_archives_releases_and_resumes_once(
    monkeypatch,
    cancel_stage,
):
    ticket = _effect_ticket()
    mongo = _mongo(ticket)
    rest = EffectRest(archived=True, locked=True)
    marker = ticket["resolution_effects"]["marker"]
    cancellation_injected = False
    original_ensure = resolve._ensure_notification_thread_writable
    original_checkpoint = resolve._checkpoint_effect

    async def ensure_writable(rest_client, current_ticket):
        nonlocal cancellation_injected
        await original_ensure(rest_client, current_ticket)
        if cancel_stage == "before" and not cancellation_injected:
            cancellation_injected = True
            raise asyncio.CancelledError

    async def notification(*_args, marker, **_kwargs):
        nonlocal cancellation_injected
        rest.messages.append(SimpleNamespace(
            content=f"-# {marker}",
            components=[],
            author=SimpleNamespace(id=7),
        ))
        if cancel_stage == "during" and not cancellation_injected:
            cancellation_injected = True
            raise asyncio.CancelledError

    async def checkpoint(*args, **kwargs):
        nonlocal cancellation_injected
        if (
            cancel_stage == "after"
            and kwargs.get("step") == "notification"
            and not cancellation_injected
        ):
            cancellation_injected = True
            raise asyncio.CancelledError
        return await original_checkpoint(*args, **kwargs)

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve, "_ensure_notification_thread_writable", ensure_writable)
    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(resolve, "_checkpoint_effect", checkpoint)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(resolve.process_resolution_effects(
            _effect_bot(rest), mongo, ticket
        ))

    assert cancellation_injected is True
    assert all(
        channel.is_archived and channel.is_locked
        for channel in rest.channels.values()
    )
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["resolution_effects"]["complete"] is False
    assert "lease_owner" not in durable["resolution_effects"]
    assert "lease_until" not in durable["resolution_effects"]

    resumed = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))
    assert resumed.won
    assert sum(
        marker in str(getattr(message, "content", ""))
        for message in rest.messages
    ) == 1
    assert all(
        channel.is_archived and channel.is_locked
        for channel in rest.channels.values()
    )


def test_archive_retry_finds_marker_and_never_duplicates_notification(monkeypatch):
    ticket = _effect_ticket()
    rest = EffectRest()
    sends = []
    archive_attempts = 0
    hub_attempts = 0

    async def side_effects(*_args, marker, **_kwargs):
        sends.append(marker)
        rest.messages.append(SimpleNamespace(
            content=marker,
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def update(*_args, **_kwargs):
        return Result(1)

    async def archive(*_args):
        nonlocal archive_attempts
        archive_attempts += 1
        if archive_attempts == 1:
            raise TimeoutError("archive response lost")

    async def refresh(*_args, **_kwargs):
        nonlocal hub_attempts
        hub_attempts += 1
        return True

    async def latest(*_args, **_kwargs):
        return ticket

    async def acquire(*_args, **_kwargs):
        return ticket

    async def release(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolve, "run_side_effects", side_effects)
    monkeypatch.setattr(resolve.store, "update_one", update)
    monkeypatch.setattr(resolve.store, "find_one", latest)
    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(resolve.thread_service, "archive_ticket_pair", archive)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)
    first = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), SimpleNamespace(), ticket
    ))
    second = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), SimpleNamespace(), ticket
    ))
    assert first.outcome == store.EFFECT_FAILED
    assert second.won
    assert sends == [ticket["resolution_effects"]["marker"]]
    assert archive_attempts == 2
    assert hub_attempts == 2
    assert rest.fetch_channel_calls == [101]


def test_resolution_effect_lease_blocks_a_second_notification_worker(monkeypatch):
    ticket = _effect_ticket()

    async def busy(*_args, **_kwargs):
        return None

    async def current(*_args, **_kwargs):
        return ticket

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a worker without the durable lease ran side effects")

    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", busy)
    monkeypatch.setattr(resolve.store, "find_one", current)
    monkeypatch.setattr(resolve, "run_side_effects", forbidden)
    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(EffectRest()), SimpleNamespace(), ticket
    ))
    assert result.outcome == store.EFFECT_FAILED
    assert result.reason == "another worker is delivering this decision"


def test_missing_notification_reopens_locked_candidate_thread_in_safe_order():
    class Rest:
        def __init__(self):
            self.edits = []

        async def fetch_channel(self, channel_id):
            return SimpleNamespace(id=channel_id, is_archived=True, is_locked=True)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))
            if kwargs.get("archived") is False:
                return SimpleNamespace(id=channel_id, is_archived=False, is_locked=True)
            return SimpleNamespace(id=channel_id, is_archived=False, is_locked=False)

    rest = Rest()
    asyncio.run(resolve._ensure_notification_thread_writable(rest, _effect_ticket()))
    assert rest.edits == [
        (101, {
            "archived": False,
            "reason": "Delivering an updated ticket decision",
        }),
        (101, {
            "locked": False,
            "reason": "Delivering an updated ticket decision",
        }),
    ]


def test_slash_approval_effect_failure_reports_durable_automatic_retry(monkeypatch):
    ticket = _effect_ticket()
    responses = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def find(*_args, **_kwargs):
        return ticket

    async def effects_pending(*_args, **_kwargs):
        return store.Transition(
            store.EFFECT_FAILED, ticket, "console refresh is pending"
        )

    async def respond(content, **_kwargs):
        responses.append(content)

    async def defer(**_kwargs):
        return None

    monkeypatch.setattr(close.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(close.store, "find_by_location", find)
    monkeypatch.setattr(close.resolve, "approve_ticket", effects_pending)
    ctx = SimpleNamespace(
        channel_id=101,
        member=SimpleNamespace(id=9),
        user=SimpleNamespace(username="Recruiter"),
        defer=defer,
        respond=respond,
    )
    asyncio.run(close.Approve.invoke._func(
        SimpleNamespace(), ctx, mongo=SimpleNamespace(), bot=SimpleNamespace()
    ))

    assert responses == [f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}"]


@pytest.mark.parametrize("handler", [
    close.deny_fwa_default_handler,
    close.deny_main_default_handler,
    close.process_custom_denial_handler,
])
def test_denial_effect_failure_reports_durable_automatic_retry(monkeypatch, handler):
    ticket = _effect_ticket()
    data = {
        "type": "deny_action",
        "denier_id": 10,
        "guild_id": 20,
        "ticket_id": ticket["_id"],
        "channel_id": 101,
        "user_id": 30,
    }
    edits = []
    deleted = []

    async def get(*_args, **_kwargs):
        return data

    async def recruiter(*_args, **_kwargs):
        return True

    async def effects_pending(*_args, **_kwargs):
        return store.Transition(store.EFFECT_FAILED, ticket, "thread archive is pending")

    async def delete(_mongo, action_id):
        deleted.append(action_id)

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    async def defer(**_kwargs):
        return None

    async def respond(*_args, **_kwargs):
        raise AssertionError("the effect-failure path must edit the original response")

    monkeypatch.setattr(close, "get_state", get)
    monkeypatch.setattr(close, "delete_state", delete)
    monkeypatch.setattr(close.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(close.resolve, "deny_ticket", effects_pending)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=10, username="Recruiter"),
        member=SimpleNamespace(id=10),
        guild_id=20,
        defer=defer,
        respond=respond,
        interaction=SimpleNamespace(
            components=[[SimpleNamespace(
                custom_id="denial_reason",
                value="Application requirements were not met.",
            )]],
            edit_initial_response=edit_initial_response,
        ),
    )
    asyncio.run(handler(
        ctx, "state", mongo=SimpleNamespace(), bot=SimpleNamespace()
    ))

    assert edits[-1]["content"] == f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}"
    assert deleted == ["state"]


def test_override_effect_failure_reports_durable_automatic_retry(monkeypatch):
    ticket = _effect_ticket()
    prior_effect_marker = ticket["resolution_effects"]["marker"]
    ticket["rev"] = 3
    ticket["resolution_effects"]["complete"] = True
    data = {
        "owner_id": 10,
        "kind": resolve.KIND_APPROVE,
        "ticket_id": ticket["_id"],
        "prior_status": "denied",
        "prior_rev": 3,
        "prior_effect_marker": prior_effect_marker,
        "prior_by": 9,
        "prior_at": NOW,
    }
    edits = []

    async def get(*_args, **_kwargs):
        return data

    async def recruiter(*_args, **_kwargs):
        return True

    async def find_current(*_args, **_kwargs):
        return ticket

    async def effects_pending(*_args, **_kwargs):
        return store.Transition(
            store.EFFECT_FAILED, ticket, "completion checkpoint is pending"
        )

    async def delete(*_args, **_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    monkeypatch.setattr(resolve, "get_state", get)
    monkeypatch.setattr(resolve, "delete_state", delete)
    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", find_current)
    monkeypatch.setattr(resolve, "approve_ticket", effects_pending)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=10, username="Recruiter"),
        member=SimpleNamespace(id=10),
        respond=None,
        interaction=SimpleNamespace(edit_initial_response=edit_initial_response),
    )
    asyncio.run(resolve.ticket_override_handler(
        ctx, "state", mongo=SimpleNamespace(), bot=SimpleNamespace()
    ))

    assert edits == [{
        "content": resolve.RESOLUTION_EFFECT_RETRY_MESSAGE,
        "components": [],
    }]


@pytest.mark.parametrize(
    "handler",
    [
        close.deny_fwa_default_handler,
        close.deny_main_default_handler,
        close.process_custom_denial_handler,
    ],
)
def test_denial_followups_reject_a_different_recruiter_before_any_action(monkeypatch, handler):
    responses = []

    async def get(*_args):
        return {
            "type": "deny_action",
            "denier_id": 10,
            "guild_id": 20,
            "ticket_id": "ticket_101",
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("authorization or denial action ran after owner mismatch")

    async def respond(content, **kwargs):
        responses.append((content, kwargs))

    async def edit_initial_response(content=None, **kwargs):
        responses.append((content, kwargs))

    async def defer(**_kwargs):
        return None

    monkeypatch.setattr(close, "get_state", get)
    monkeypatch.setattr(close.perms, "is_recruiter", forbidden)
    monkeypatch.setattr(close.resolve, "deny_ticket", forbidden)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="Other"), member=SimpleNamespace(id=11),
        guild_id=20,
        respond=respond, defer=defer,
        interaction=SimpleNamespace(
            components=[], create_modal_response=forbidden,
            edit_initial_response=edit_initial_response,
        ),
    )
    asyncio.run(handler(ctx, "state", mongo=SimpleNamespace(), bot=SimpleNamespace()))
    assert len(responses) == 1
    assert responses[0][0] == "This denial session belongs to another recruiter."


def test_custom_denial_opener_sends_modal_without_state_or_permission_work(monkeypatch):
    modals = []

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("custom denial opener performed prerequisite work")

    async def create_modal_response(**kwargs):
        modals.append(kwargs)

    async def no_defer(**_kwargs):
        raise AssertionError("custom denial opener was deferred")

    monkeypatch.setattr(close, "get_state", forbidden)
    monkeypatch.setattr(close.perms, "is_recruiter", forbidden)
    monkeypatch.setattr(dispatcher, "get_state", forbidden)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=10),
        defer=no_defer,
        interaction=SimpleNamespace(
            custom_id="deny_custom:state",
            create_modal_response=create_modal_response,
        ),
    )

    asyncio.run(dispatcher._dispatch(ctx, SimpleNamespace()))

    assert len(modals) == 1
    assert modals[0]["custom_id"] == "process_custom_denial:state"
    action = dispatcher.registered_functions["deny_custom"]
    assert action.opens_modal is True
    assert action.preload_state is False


def test_custom_denial_modal_defers_before_state_or_permission_work(monkeypatch):
    events = []

    async def defer(**kwargs):
        events.append(("defer", kwargs))

    async def get(*_args):
        assert _args[2] == {
            "type": 1,
            "denier_id": 1,
            "guild_id": 1,
        }
        events.append(("state", {}))
        return {
            "type": "deny_action",
            "denier_id": 10,
            "guild_id": 20,
            "ticket_id": "ticket_101",
        }

    async def denied(*_args):
        events.append(("permission", {}))
        return False

    async def edit_initial_response(content=None, **kwargs):
        events.append(("edit", {"content": content, **kwargs}))

    monkeypatch.setattr(close, "get_state", get)
    monkeypatch.setattr(close.perms, "is_recruiter", denied)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=10, username="Recruiter"),
        member=SimpleNamespace(id=10),
        guild_id=20,
        defer=defer,
        interaction=SimpleNamespace(
            components=[], edit_initial_response=edit_initial_response,
        ),
    )

    asyncio.run(close.process_custom_denial_handler(
        ctx, "state", mongo=SimpleNamespace(), bot=SimpleNamespace(),
    ))

    assert [event[0] for event in events] == [
        "defer", "state", "permission", "edit",
    ]


def test_override_state_is_owner_bound_before_permission_or_transition(monkeypatch):
    responses = []

    async def get(*_args):
        return {"owner_id": 10, "kind": resolve.KIND_APPROVE}

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("permission or transition ran after owner mismatch")

    async def respond(content, **kwargs):
        responses.append((content, kwargs))

    monkeypatch.setattr(resolve, "get_state", get)
    monkeypatch.setattr(resolve.perms, "is_recruiter", forbidden)
    monkeypatch.setattr(resolve, "approve_ticket", forbidden)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11), member=SimpleNamespace(id=11), respond=respond,
        interaction=SimpleNamespace(edit_initial_response=forbidden),
    )
    asyncio.run(resolve.ticket_override_handler(
        ctx, "state", mongo=SimpleNamespace(), bot=SimpleNamespace()
    ))
    assert responses == [("This override belongs to another recruiter.", {"ephemeral": True})]


def test_unauthorized_flag_mutation_has_no_write(monkeypatch):
    async def denied(*_args):
        return False

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("flag write ran")

    monkeypatch.setattr(flag_store.perms, "is_recruiter", denied)
    monkeypatch.setattr(flag_store, "set_flag", forbidden)
    result = asyncio.run(flag_store.set_flag_authorized(
        SimpleNamespace(), member=SimpleNamespace(id=9), actor_name="Nope",
        kind=flag_store.FLAG_BLACKLISTED, discord_ids=(30,), source="test",
    ))
    assert result.outcome == store.UNAUTHORIZED
