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
    account_sync,
    close,
    console,
    flag_store,
    migrate,
    perms,
    resolve,
    schema,
    store,
)
from extensions.commands.accounts import (
    AccountEntry,
    AccountsData,
    STATUS_LOADED,
)
from utils.todo_data import Account


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
        ticket_automation_state=Collection(),
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


def _linked_account(tag: str, *, name: str | None = None) -> AccountEntry:
    normalized = schema.player_tag(tag)
    assert normalized is not None
    return AccountEntry(
        normalized,
        STATUS_LOADED,
        Account(
            tag=normalized,
            name=name or f"Player {normalized[-3:]}",
            clan_tag=None,
            clan_name=None,
            town_hall=17,
        ),
    )


@pytest.mark.parametrize("count", [1, 15, 37])
def test_linked_account_sync_persists_complete_snapshot_and_identity_audit(
    monkeypatch,
    count,
):
    ticket = _ticket()
    mongo = _mongo(ticket)
    entries = tuple(
        _linked_account(f"#A{index:07d}", name=f"Account {index}")
        for index in range(count)
    )

    async def load(_client, discord_id, *, force):
        assert discord_id == ticket["user_id"]
        assert force is True
        return AccountsData(entries=entries)

    monkeypatch.setattr(account_sync, "load_accounts", load)
    result = asyncio.run(account_sync.sync_ticket_accounts(
        mongo,
        object(),
        ticket["_id"],
        source=account_sync.SOURCE_OPEN,
        now=NOW,
    ))

    assert result.snapshot.state == account_sync.STATE_READY
    assert len(result.snapshot.current_accounts) == count
    assert len(result.snapshot.current_tags) == count
    assert len(result.added_tags) == count
    durable = mongo.tickets.documents[ticket["_id"]]
    assert len(durable["linked_account_identities"]) == count
    assert durable["account_identity_audit"][-1]["source"] == "ticket_open"
    assert durable["player_tags"][0] == "#ABC123"


def test_linked_account_resync_adds_only_new_and_never_silently_forgets(
    monkeypatch,
):
    ticket = _ticket()
    mongo = _mongo(ticket)
    responses = [
        AccountsData(entries=tuple(_linked_account(f"#B{index:07d}") for index in range(15))),
        AccountsData(entries=tuple(_linked_account(f"#B{index:07d}") for index in range(16))),
        AccountsData(entries=tuple(_linked_account(f"#B{index:07d}") for index in range(1, 16))),
    ]

    async def load(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(account_sync, "load_accounts", load)
    first = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW
    ))
    second = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_RECRUITER_REFRESH, now=NOW
    ))
    third = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_FINAL_DENY, now=NOW
    ))

    assert len(first.added_tags) == 15
    assert second.added_tags == ("#B0000015",)
    assert third.added_tags == ()
    assert third.no_longer_linked_tags == ("#B0000000",)
    durable = mongo.tickets.documents[ticket["_id"]]
    assert len(durable["linked_account_identities"]) == 16
    assert len({item["tag"] for item in durable["linked_account_identities"]}) == 16
    assert "#B0000000" in durable["player_tags"]
    assert "#B0000000" not in third.snapshot.current_tags


def test_linked_account_sync_retries_cas_without_duplicate_identity(monkeypatch):
    ticket = _ticket()
    mongo = _mongo(ticket)
    original = store.compare_and_swap_linked_accounts
    attempts = 0

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#CAS123"),))

    async def lose_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            current = await store.find_one(
                mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
            )
            return store.Transition(store.LOST, current)
        return await original(*args, **kwargs)

    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(store, "compare_and_swap_linked_accounts", lose_once)
    result = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW
    ))

    assert result.snapshot.current_tags == ("#CAS123",)
    assert attempts == 2
    identities = mongo.tickets.documents[ticket["_id"]]["linked_account_identities"]
    assert [item["tag"] for item in identities] == ["#CAS123"]


def test_flag_identity_propagation_survives_post_snapshot_failure(monkeypatch):
    ticket = _ticket()
    mongo = _mongo(ticket)
    loads = 0
    expansions = 0

    async def load(*_args, **_kwargs):
        nonlocal loads
        loads += 1
        return AccountsData(entries=(_linked_account("#NEW123"),))

    async def expand(*_args, **_kwargs):
        nonlocal expansions
        expansions += 1
        if expansions == 1:
            raise TimeoutError("flag store unavailable after ticket CAS")
        return []

    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(flag_store, "extend_matching_flags", expand)

    result = asyncio.run(account_sync.sync_ticket_accounts(
        mongo,
        object(),
        ticket["_id"],
        source=account_sync.SOURCE_OPEN,
    ))

    assert result.snapshot.current_tags == ("#NEW123",)
    linked = mongo.tickets.documents[ticket["_id"]]["linked_accounts"]
    assert linked["current_tags"] == ["#NEW123"]
    assert linked["flag_refresh_required"] is True

    recovered = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object()
    ))
    assert recovered == {"processed": 1, "completed": 1, "failed": 0}
    assert loads == 1
    assert expansions == 2
    assert mongo.tickets.documents[ticket["_id"]]["linked_accounts"][
        "flag_refresh_required"
    ] is False


def test_linked_account_discovery_expands_matching_flag_identities(monkeypatch):
    ticket = _ticket()
    flag = {
        "_id": "flag_blacklist",
        "kind": flag_store.FLAG_BLACKLISTED,
        "active": True,
        "discord_ids": [ticket["user_id"]],
        "player_tags": ["#ABC123"],
        "rev": 0,
        "audit": [],
    }
    mongo = _mongo(ticket)
    mongo.ticket_flags = Collection([flag])

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    monkeypatch.setattr(account_sync, "load_accounts", load)
    asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW
    ))

    durable = mongo.ticket_flags.documents[flag["_id"]]
    assert durable["discord_ids"] == [ticket["user_id"]]
    assert set(durable["player_tags"]) == {"#ABC123", "#NEW123"}
    assert durable["audit"][-1]["event"] == "flag_identity_expanded"


@pytest.mark.parametrize(
    ("data", "state", "retry"),
    [
        (AccountsData(), account_sync.STATE_EMPTY, False),
        (AccountsData(problem="link_service"), account_sync.STATE_FAILED, True),
    ],
)
def test_linked_account_sync_distinguishes_empty_from_failure(
    monkeypatch,
    data,
    state,
    retry,
):
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def load(*_args, **_kwargs):
        return data

    monkeypatch.setattr(account_sync, "load_accounts", load)
    result = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW
    ))

    assert result.snapshot.state == state
    assert result.snapshot.retry_required is retry
    assert mongo.tickets.documents[ticket["_id"]]["player_tags"] == ["#ABC123"]


@pytest.mark.parametrize("failure", ["client_unavailable", "cas_error"])
def test_denial_proceeds_with_atomic_account_sync_retry(monkeypatch, failure):
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def effects(_bot, _mongo, resolved):
        return store.Transition(store.WON, resolved)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    if failure == "client_unavailable":
        monkeypatch.setattr(account_sync, "configured_coc_client", lambda: None)
        client = None
    else:
        async def broken(*_args, **_kwargs):
            raise account_sync.AccountSyncError("CAS exhausted")

        monkeypatch.setattr(account_sync, "sync_ticket_accounts", broken)
        client = object()

    result = asyncio.run(resolve.deny_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        kind=resolve.KIND_DENY_CUSTOM,
        reason="Clear denial reason",
        coc_client=client,
    ))

    assert result.outcome == store.WON
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["status"] == "denied"
    assert durable["linked_accounts"]["state"] == account_sync.STATE_FAILED
    assert durable["linked_accounts"]["retry_required"] is True
    assert durable["account_identity_audit"][-1]["retry_queued_with_decision"] is True
    assert durable["audit"][-1]["linked_accounts"]["state"] == account_sync.STATE_FAILED


def test_automatic_retry_recovers_terminal_denial_account_snapshot(monkeypatch):
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_FAILED,
        "current": [],
        "current_tags": [],
        "retry_required": True,
        "last_attempt_at": NOW,
        "revision": 1,
    }
    mongo = _mongo(ticket)

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#LATE123"),))

    async def queue(_ticket):
        return f"ticket_staff_context:{_ticket['_id']}"

    monkeypatch.setattr(account_sync, "load_accounts", load)
    result = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object(), limit=25, after_sync=queue
    ))

    assert result == {"processed": 1, "completed": 1, "failed": 0}
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["status"] == "denied"
    assert durable["linked_accounts"]["current_tags"] == ["#LATE123"]
    assert durable["linked_accounts"]["retry_required"] is False
    assert durable["linked_accounts"]["context_refresh_required"] is False


def test_terminal_retry_context_obligation_survives_callback_failure_and_resync(
    monkeypatch,
):
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_FAILED,
        "current": [],
        "current_tags": [],
        "retry_required": True,
        "last_attempt_at": NOW,
        "revision": 1,
    }
    mongo = _mongo(ticket)
    loads = 0
    queues = 0

    async def load(*_args, **_kwargs):
        nonlocal loads
        loads += 1
        return AccountsData(entries=(_linked_account("#LATE123"),))

    async def crash_after_snapshot(_ticket):
        nonlocal queues
        queues += 1
        raise TimeoutError("outbox unavailable")

    monkeypatch.setattr(account_sync, "load_accounts", load)
    first = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object(), after_sync=crash_after_snapshot
    ))
    assert first == {"processed": 1, "completed": 0, "failed": 1}
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["linked_accounts"]["retry_required"] is False
    assert durable["linked_accounts"]["context_refresh_required"] is True
    first_revision = durable["linked_accounts"]["revision"]

    # A same-content sync must carry the outstanding obligation to its newer
    # account revision instead of making queue confirmation impossible.
    asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_RECOVERY
    ))
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["linked_accounts"]["revision"] == first_revision + 1
    assert durable["linked_accounts"]["context_refresh_revision"] == first_revision + 1

    async def queue(_ticket):
        nonlocal queues
        queues += 1
        return f"ticket_staff_context:{_ticket['_id']}"

    second = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object(), after_sync=queue
    ))
    assert second == {"processed": 1, "completed": 1, "failed": 0}
    assert loads == 2  # recovery does not repeat the lookup after it succeeded
    assert queues == 2
    assert mongo.tickets.documents[ticket["_id"]]["linked_accounts"][
        "context_refresh_required"
    ] is False


def test_record_account_failure_wraps_store_errors(monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("mongo unavailable")

    monkeypatch.setattr(account_sync, "_persist_sync_result", broken)
    with pytest.raises(account_sync.AccountSyncError, match="could not be persisted"):
        asyncio.run(account_sync.record_ticket_account_failure(
            object(),
            "ticket_101",
            source=account_sync.SOURCE_FINAL_APPROVE,
            error="ClashClientUnavailable",
        ))


def test_approval_without_client_persists_retry_and_automatic_recovery(monkeypatch):
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def deliver(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "configured_coc_client", lambda: None)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    blocked = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
    ))

    assert blocked.outcome == store.BLOCKED
    failed = mongo.tickets.documents[ticket["_id"]]["linked_accounts"]
    assert failed["state"] == account_sync.STATE_FAILED
    assert failed["retry_required"] is True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#RECOVER"),))

    async def queue(_ticket):
        return f"ticket_staff_context:{_ticket['_id']}"

    monkeypatch.setattr(account_sync, "load_accounts", load)
    recovered = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object(), after_sync=queue
    ))
    assert recovered == {"processed": 1, "completed": 1, "failed": 0}
    linked = mongo.tickets.documents[ticket["_id"]]["linked_accounts"]
    assert linked["current_tags"] == ["#RECOVER"]
    assert linked["retry_required"] is False


@pytest.mark.parametrize(
    "data",
    [AccountsData(), AccountsData(problem="link_service")],
)
def test_approval_blocks_when_final_account_sync_is_empty_or_failed(
    monkeypatch,
    data,
):
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return data

    refreshed = []

    async def deliver(_bot, _mongo, updated, **_kwargs):
        snapshot = account_sync.snapshot_from_ticket(updated)
        refreshed.append((snapshot.state, snapshot.current_tags))
        return None

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    result = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.BLOCKED
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "open"
    expected_state = (
        account_sync.STATE_FAILED if data.problem else account_sync.STATE_EMPTY
    )
    assert refreshed == [(expected_state, ())]


def test_blocked_approval_refreshes_shrunken_snapshot_before_blacklist_result(
    monkeypatch,
):
    ticket = _ticket()
    current = [
        {
            "tag": tag,
            "name": tag,
            "town_hall": 17,
            "profile_status": "loaded",
        }
        for tag in ("#KEEP123", "#GONE123")
    ]
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_READY,
        "current": current,
        "current_tags": ["#KEEP123", "#GONE123"],
        "retry_required": False,
        "revision": 1,
    }
    ticket["player_tags"].extend(("#KEEP123", "#GONE123"))
    mongo = _mongo(ticket)
    refreshed = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#KEEP123"),))

    async def deliver(_bot, _mongo, updated, **_kwargs):
        refreshed.append(account_sync.snapshot_from_ticket(updated).current_tags)
        return None

    async def blacklist(*_args, **_kwargs):
        return {"_id": "blocked"}

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    result = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.BLOCKED
    assert result.blocker == {"_id": "blocked"}
    assert refreshed == [("#KEEP123",)]


@pytest.mark.parametrize("opening_failed", [True, False])
def test_fwa_approval_requires_review_after_final_sync_discovers_accounts(
    monkeypatch,
    opening_failed,
):
    ticket = _ticket()
    ticket["ticket_type"] = "fwa"
    old = {
        "tag": "#OLD123",
        "name": "Old Account",
        "town_hall": 17,
        "profile_status": "loaded",
    }
    ticket["linked_accounts"] = {
        "version": 1,
        "state": (
            account_sync.STATE_FAILED if opening_failed else account_sync.STATE_READY
        ),
        "current": [] if opening_failed else [old],
        "current_tags": [] if opening_failed else ["#OLD123"],
        "retry_required": opening_failed,
        "revision": 1,
    }
    if not opening_failed:
        ticket["linked_account_identities"] = [{"tag": "#OLD123"}]
        ticket["player_tags"].append("#OLD123")
    mongo = _mongo(ticket)
    delivered = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        entries = [_linked_account("#NEW123")]
        if not opening_failed:
            entries.insert(0, _linked_account("#OLD123"))
        return AccountsData(entries=tuple(entries))

    async def deliver(_bot, _mongo, updated, **kwargs):
        assert kwargs == {
            "reopen_terminal_thread": False,
            "open_only_refresh": True,
        }
        delivered.append(tuple(updated["linked_accounts"]["current_tags"]))
        state_id = f"ticket_staff_context:{updated['_id']}"
        state = await mongo.ticket_automation_state.find_one({"_id": state_id})
        requested = state["refresh_requested_at"]
        await mongo.ticket_automation_state.update_one(
            {"_id": state_id},
            {"$set": {
                "delivery_state": "delivered",
                "delivered_at": requested,
            }, "$unset": {"lease_owner": "", "lease_until": ""}},
        )
        return 900

    async def effects(_bot, _mongo, resolved):
        return store.Transition(store.WON, resolved)

    async def chocolate_current(*_args, **_kwargs):
        return bool(delivered)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    monkeypatch.setattr(
        console, "staff_chocolate_context_is_current", chocolate_current
    )
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)

    first = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        coc_client=object(),
    ))
    assert first.outcome == store.BLOCKED
    assert first.reason == resolve.FWA_IDENTITY_REVIEW_MESSAGE
    expected = ("#NEW123",) if opening_failed else ("#OLD123", "#NEW123")
    assert delivered == [expected]
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "open"

    second = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        coc_client=object(),
    ))
    assert second.outcome == store.WON
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["status"] == "approved"
    assert durable["linked_accounts"]["approval_review"]["state"] == "acknowledged"
    assert delivered == [expected]


def test_terminal_fwa_override_refreshes_new_tags_before_review_block(monkeypatch):
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket["ticket_type"] = "fwa"
    ticket["rev"] = 1
    marker = f"ticket-resolution:{ticket['_id']}:1:denied"
    ticket["resolution_effects"] = {"marker": marker, "complete": True}
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_FAILED,
        "current": [],
        "current_tags": [],
        "retry_required": True,
        "revision": 1,
    }
    mongo = _mongo(ticket)
    deliveries = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#OVR123"),))

    async def deliver(_bot, _mongo, updated, **kwargs):
        assert kwargs == {
            "reopen_terminal_thread": True,
            "open_only_refresh": False,
        }
        deliveries.append(tuple(updated["linked_accounts"]["current_tags"]))
        state_id = f"ticket_staff_context:{updated['_id']}"
        state = await mongo.ticket_automation_state.find_one({"_id": state_id})
        requested = state["refresh_requested_at"]
        await mongo.ticket_automation_state.update_one(
            {"_id": state_id},
            {"$set": {
                "delivery_state": "delivered",
                "delivered_at": requested,
            }},
        )
        return 900

    async def effects(_bot, _mongo, resolved):
        return store.Transition(store.WON, resolved)

    async def chocolate_current(*_args, **_kwargs):
        return bool(deliveries)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    monkeypatch.setattr(
        console, "staff_chocolate_context_is_current", chocolate_current
    )
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    override = {"status": "denied", "rev": 1, "by": 9, "at": NOW}

    first = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        expected_status="denied", expected_rev=1, override=override,
        prior_effect_marker=marker, coc_client=object(),
    ))
    assert first.outcome == store.BLOCKED
    assert first.reason == resolve.FWA_IDENTITY_REVIEW_MESSAGE
    assert deliveries == [("#OVR123",)]

    second = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        expected_status="denied", expected_rev=1, override=override,
        prior_effect_marker=marker, coc_client=object(),
    ))
    assert second.outcome == store.WON
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "approved"
    assert deliveries == [("#OVR123",)]


def test_final_account_sync_exposes_new_identity_to_blacklist_gate(monkeypatch):
    ticket = _ticket()
    mongo = _mongo(ticket)
    seen = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    async def blacklist(_mongo, *, user_id, player_tags):
        seen.extend(player_tags)
        return {"_id": "flag_new"} if "#NEW123" in player_tags else None

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    result = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.BLOCKED
    assert result.blocker == {"_id": "flag_new"}
    assert "#NEW123" in seen
    assert "#NEW123" in mongo.tickets.documents[ticket["_id"]]["player_tags"]


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


def test_account_recovery_or_predicates_each_have_a_selective_index():
    mongo = _mongo(_ticket())
    names = asyncio.run(store.ensure_indexes(mongo))
    indexes = {
        spec[0][0]: options
        for spec, options in mongo.tickets.indexes
        if spec
    }
    query = account_sync.account_recovery_filter()

    assert query["type"] == "ticket"
    assert query["venue"] == "thread"
    assert query["$or"][-1] == {
        "status": "open",
        "linked_accounts.version": {"$exists": False},
    }
    # The missing-version branch is bounded by the existing status index to the
    # live open-ticket set; terminal ticket growth cannot expand that scan.
    assert "status" in indexes
    for field in store.ACCOUNT_RECOVERY_BOOLEAN_FIELDS:
        assert field in indexes
        options = indexes[field]
        assert options["name"] == "account_recovery_" + field.rsplit(".", 1)[-1]
        assert options["partialFilterExpression"] == {
            **store.RUNTIME_FILTER,
            field: True,
        }
        assert options["name"] in names


def test_account_recovery_executes_the_frozen_indexed_predicate(monkeypatch):
    observed = []

    async def find(_mongo, query):
        observed.append(query)
        return []

    monkeypatch.setattr(account_sync.store, "find", find)
    counts = asyncio.run(account_sync.recover_pending_account_syncs(
        SimpleNamespace(), object()
    ))
    assert counts == {"processed": 0, "completed": 0, "failed": 0}
    assert observed == [account_sync.account_recovery_filter()]


def test_recovery_indexes_are_idempotent_and_unique_preflight_still_fails_closed():
    mongo = _mongo(_ticket())
    first = asyncio.run(store.ensure_indexes(mongo))
    second = asyncio.run(store.ensure_indexes(mongo))
    assert first == second

    duplicate = _mongo(
        _ticket(),
        _ticket(public=201, staff=202, number=2, user=30),
    )
    with pytest.raises(store.IndexConflictError):
        asyncio.run(store.ensure_indexes(duplicate))
    assert duplicate.tickets.indexes == []


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


def test_terminal_decision_cas_rejects_a_newer_linked_account_snapshot():
    ticket = _ticket()
    ticket["linked_accounts"] = {"revision": 2}
    mongo = _mongo(ticket)

    result = asyncio.run(store.transition(
        mongo,
        ticket["_id"],
        to_status="approved",
        actor_id=99,
        actor_name="Recruiter",
        expected_rev=0,
        expected_linked_account_revision=1,
    ))

    assert result.outcome == store.LOST
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "open"


def test_approval_loses_when_account_snapshot_changes_after_blacklist_check_begins(
    monkeypatch,
):
    ticket = _ticket()
    existing = {
        "tag": "#ABC123",
        "name": "Existing",
        "town_hall": 17,
        "profile_status": "loaded",
    }
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_READY,
        "current": [existing],
        "current_tags": ["#ABC123"],
        "retry_required": False,
        "revision": 1,
    }
    ticket["linked_account_identities"] = [{"tag": "#ABC123"}]
    mongo = _mongo(ticket)
    loads = iter((
        AccountsData(entries=(_linked_account("#ABC123"),)),
        AccountsData(entries=(
            _linked_account("#ABC123"),
            _linked_account("#RACE123"),
        )),
    ))

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return next(loads)

    async def blacklist(*_args, **_kwargs):
        # This refresh lands after the approval's final lookup but before its
        # decision CAS, invalidating the exact identity view that was checked.
        await account_sync.sync_ticket_accounts(
            mongo,
            object(),
            ticket["_id"],
            source=account_sync.SOURCE_RECRUITER_REFRESH,
        )
        return None

    async def effects(*_args, **_kwargs):
        raise AssertionError("a stale approval must not run terminal effects")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    result = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.LOST
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["status"] == "open"
    assert durable["linked_accounts"]["current_tags"] == ["#ABC123", "#RACE123"]


def test_permission_is_rechecked_at_terminal_mutation_boundary(monkeypatch):
    ticket = _ticket()
    ticket["linked_accounts"] = {"revision": 0}
    mongo = _mongo(ticket)
    authorization = iter((True, False))

    async def recruiter(*_args, **_kwargs):
        return next(authorization)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "configured_coc_client", lambda: None)
    result = asyncio.run(resolve.deny_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        kind=resolve.KIND_DENY_CUSTOM,
        reason="Clear denial reason",
    ))

    assert result.outcome == store.UNAUTHORIZED
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "open"


def test_live_resolution_reconciler_sweeps_durable_account_retries(monkeypatch):
    ticket = _ticket()
    seen = []

    async def recover(_mongo, client, *, after_sync, **_kwargs):
        assert client is not None
        await after_sync(ticket)
        return {"processed": 1, "completed": 1, "failed": 0}

    async def queue(_mongo, ticket_doc):
        seen.append(ticket_doc["_id"])
        return f"ticket_staff_context:{ticket_doc['_id']}"

    async def drain(*, bot, mongo, limit=25):
        assert bot == "gateway"
        assert limit == 25
        seen.append("drained")
        return {"processed": 1, "completed": 1, "failed": 0}

    monkeypatch.setattr(account_sync, "configured_coc_client", lambda: object())
    monkeypatch.setattr(account_sync, "recover_pending_account_syncs", recover)
    monkeypatch.setattr(console, "queue_staff_identity_context", queue)
    monkeypatch.setattr(console, "recover_pending_staff_identity_contexts", drain)

    counts = asyncio.run(resolve._recover_live_account_syncs(
        _mongo(ticket), bot="gateway"
    ))

    assert counts == {
        "processed": 1,
        "completed": 1,
        "failed": 0,
        "context_processed": 1,
        "context_failed": 0,
    }
    assert seen == [ticket["_id"], "drained"]


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

    async def sync(*_args, **_kwargs):
        calls.append("account_sync")
        return account_sync.AccountSyncResult(
            ticket,
            account_sync.AccountSnapshot(
                state=account_sync.STATE_READY,
                current_accounts=(account_sync.LinkedAccount("#ABC123"),),
                current_tags=("#ABC123",),
                observed_tags=("#ABC123",),
                retry_required=False,
                revision=1,
            ),
        )

    async def transition(*_args, **_kwargs):
        calls.append("transition")
        return store.Transition(store.LOST, ticket)

    async def effects(*_args, **_kwargs):
        calls.append("effects")
        raise AssertionError("side effects must not run")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", find)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    monkeypatch.setattr(resolve.account_sync, "sync_ticket_accounts", sync)
    monkeypatch.setattr(resolve.store, "transition", transition)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    mongo = SimpleNamespace(ticket_flags=Collection())
    result = asyncio.run(resolve.approve_ticket(
        SimpleNamespace(), mongo, ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99), actor_name="Recruiter", coc_client=object(),
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


def test_ticket_flag_manager_cas_rejects_stale_reason_then_binds_all_identities(
    monkeypatch,
):
    user_id = 223456789012345678
    original = {
        "_id": "flag_existing",
        "kind": flag_store.FLAG_NOT_LOYAL,
        "discord_ids": [user_id],
        "player_tags": ["#OLD123"],
        "source": "Warriors United recruiter note",
        "reason": "Current reason",
        "active": True,
        "checked_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        "rev": 4,
        "audit": [],
    }
    mongo = SimpleNamespace(ticket_flags=Collection([original]))
    tags = [f"#A{index:07d}" for index in range(37)]

    async def allowed(*_args, **_kwargs):
        return True

    monkeypatch.setattr(flag_store.perms, "is_recruiter", allowed)
    member = SimpleNamespace(id=99)
    stale = asyncio.run(flag_store.set_flag_if_current_authorized(
        mongo,
        member=member,
        actor_name="Recruiter",
        kind=flag_store.FLAG_NOT_LOYAL,
        discord_ids=user_id,
        player_tags=tags,
        source="Warriors United recruiter note",
        reason="Stale overwrite",
        expected_flag_id="flag_existing",
        expected_rev=3,
    ))
    assert stale.outcome == store.LOST
    assert mongo.ticket_flags.documents["flag_existing"]["reason"] == "Current reason"

    saved = asyncio.run(flag_store.set_flag_if_current_authorized(
        mongo,
        member=member,
        actor_name="Recruiter",
        kind=flag_store.FLAG_NOT_LOYAL,
        discord_ids=user_id,
        player_tags=tags,
        source="Warriors United recruiter note",
        reason="Fresh reason",
        expected_flag_id="flag_existing",
        expected_rev=4,
    ))
    assert saved.won
    assert saved.doc["reason"] == "Fresh reason"
    assert set(tags) <= set(saved.doc["player_tags"])
    assert saved.doc["discord_ids"] == [user_id]
    assert saved.doc["rev"] == 5


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
            "staff_context": {"state": "delivered"},
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


@pytest.mark.parametrize("fresh", [True, False])
def test_final_account_context_must_be_fresh_before_terminal_archive(
    monkeypatch,
    fresh,
):
    marker = "ticket-resolution:ticket_101:1:denied"
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 1,
        "linked_accounts": {
            "version": 1,
            "state": account_sync.STATE_READY,
            "current": [{
                "tag": "#NEW123",
                "name": "New Account",
                "town_hall": 17,
                "profile_status": "loaded",
            }],
            "current_tags": ["#NEW123"],
            "retry_required": False,
            "revision": 1,
        },
        "resolution_effects": {
            "version": 1,
            "marker": marker,
            "kind": resolve.KIND_DENY_CUSTOM,
            "notification": {"state": "delivered"},
            "staff_context": {"state": "pending"},
            "archive": {"state": "pending"},
            "hub": {"state": "pending"},
            "complete": False,
        },
    })
    mongo = _mongo(ticket)
    mongo.ticket_automation_state = Collection()
    order = []

    async def context(_bot, _mongo, updated_ticket, **kwargs):
        order.append(("context", tuple(
            (updated_ticket.get("linked_accounts") or {}).get("current_tags") or ()
        )))
        assert kwargs == {"reopen_terminal_thread": True}
        requested = NOW
        delivered = NOW if fresh else NOW.replace(hour=5)
        mongo.ticket_automation_state.documents[
            f"ticket_staff_context:{ticket['_id']}"
        ] = {
            "_id": f"ticket_staff_context:{ticket['_id']}",
            "kind": "ticket_staff_context",
            "delivery_state": "delivered",
            "refresh_requested_at": requested,
            "delivered_at": delivered,
        }
        return 555

    async def archive(*_args, **_kwargs):
        order.append(("archive", ()))

    async def hub(*_args, **_kwargs):
        return True

    monkeypatch.setattr(console, "deliver_staff_identity_context", context)
    monkeypatch.setattr(resolve.thread_service, "archive_ticket_pair", archive)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", hub)
    result = asyncio.run(resolve._process_resolution_effects_owned(
        _effect_bot(EffectRest()),
        mongo,
        ticket,
    ))

    assert order[0] == ("context", ("#NEW123",))
    if fresh:
        assert order[1] == ("archive", ())
        assert result.outcome == store.WON
    else:
        assert all(step != "archive" for step, _details in order)
        assert result.outcome == store.EFFECT_FAILED


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
            "staff_context": {"state": "delivered"},
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
