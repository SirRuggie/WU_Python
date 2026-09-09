import asyncio
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest
from bson import BSON
from pymongo.errors import (
    DuplicateKeyError,
    ExecutionTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from extensions import components as dispatcher
from extensions.commands import ticket_runtime
from extensions.commands.tickets import (
    account_sync,
    close,
    console,
    flag_store,
    manage,
    migrate,
    perms,
    resolve,
    schema,
    store,
    thread_service,
)
from extensions.commands.accounts import (
    AccountEntry,
    AccountsData,
    STATUS_LOADED,
)
from utils.todo_data import Account


NOW = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
MISSING_VALUE = object()


def _clear_index_failure_caches():
    store._indexes_failed = False
    store._index_retry_at = 0.0
    store._last_index_error = None
    thread_service._creation_index_ready = False
    thread_service._creation_index_failed = False
    thread_service._creation_index_retry_at = 0.0
    thread_service._creation_index_last_error = None


@pytest.fixture(autouse=True)
def _reset_index_failure_cache():
    """Each test builds its own fake `mongo`; a cached index failure from one
    test must not leak into the next test's unrelated `ensure_indexes` call.
    """
    _clear_index_failure_caches()
    yield
    _clear_index_failure_caches()


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
        elif operator == "$lte":
            if not any(value is not None and value <= operand for value in values):
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
        if key == "$and":
            if not all(_matches(document, clause) for clause in expected):
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
        # Mongo sorts a missing/null field before every real value in
        # ascending order (and after, in descending). A bare `_get(..., "")`
        # default would crash comparing a str stand-in against a real
        # datetime the moment one row has the field and another does not, so
        # rank presence first and only compare real values within a rank.
        for path, direction in reversed(spec):
            def key(item, path=path):
                value = _get(item, path, MISSING_VALUE)
                return (0, None) if value is MISSING_VALUE else (1, value)

            self.documents.sort(key=key, reverse=direction < 0)
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

    async def count_documents(self, query, *_args, **_kwargs):
        return sum(1 for document in self.documents.values() if _matches(document, query))

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

    async def aggregate(self, pipeline):
        """Minimal `$match`/`$group` support -- the only two stages
        `store.console_counts` and `flag_store.count_active` actually use."""
        rows = list(self.documents.values())
        for stage in pipeline:
            if "$match" in stage:
                rows = [row for row in rows if _matches(row, stage["$match"])]
            elif "$group" in stage:
                id_spec = (stage["$group"] or {}).get("_id")
                grouped: dict = {}
                order: list = []
                for row in rows:
                    if isinstance(id_spec, dict):
                        id_value = {
                            name: _get(row, str(ref).lstrip("$"), None)
                            for name, ref in id_spec.items()
                        }
                        key = tuple(sorted(id_value.items()))
                    else:
                        id_value = _get(row, str(id_spec).lstrip("$"), None)
                        key = id_value
                    if key not in grouped:
                        grouped[key] = {"_id": id_value, "count": 0}
                        order.append(key)
                    grouped[key]["count"] += 1
                rows = [grouped[key] for key in order]
            else:
                raise AssertionError(f"unsupported aggregate stage: {stage}")
        return Cursor(rows)


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
    ticket = schema.new_ticket_document(
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
    ticket["runtime"] = ticket_runtime.THREAD_RUNTIME
    return ticket


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


def test_find_one_normalizes_stale_schema_version_and_shape():
    ticket = _ticket()
    ticket["schema_version"] = 1
    ticket["player_tags"] = ["abc123"]
    ticket.pop("player_tag", None)
    mongo = _mongo(ticket)

    found = asyncio.run(store.find_one(mongo, {"_id": "ticket_101"}))

    assert found["schema_version"] == schema.SCHEMA_VERSION
    assert found["player_tags"] == ["#ABC123"]
    assert found["player_tag"] == "#ABC123"
    assert found["audit"][-1]["event"] == "schema_backfilled"


def test_find_normalizes_every_document():
    first = _ticket(public=101, staff=102, number=1)
    second = _ticket(public=201, staff=202, number=2)
    first["schema_version"] = 1
    second["schema_version"] = 2
    mongo = _mongo(first, second)

    found = asyncio.run(store.find(mongo, {"status": "open"}))

    assert len(found) == 2
    assert all(doc["schema_version"] == schema.SCHEMA_VERSION for doc in found)


def test_list_open_search_and_history_for_normalize_documents():
    ticket = _ticket()
    ticket["schema_version"] = 1
    mongo = _mongo(ticket)

    opened = asyncio.run(store.list_open(mongo))
    searched = asyncio.run(store.search(mongo, "Applicant"))
    history = asyncio.run(store.history_for(mongo, user_id=ticket["user_id"]))

    assert opened[0]["schema_version"] == schema.SCHEMA_VERSION
    assert searched[0]["schema_version"] == schema.SCHEMA_VERSION
    assert history[0]["schema_version"] == schema.SCHEMA_VERSION


def test_search_count_ignores_searchs_own_result_limit():
    """`search` caps its result page at 10; `search_count` must report the
    true total so the console can say "newest 10 of 27" instead of hiding
    how many results are not shown."""
    tickets = [_ticket(public=100 + index, staff=200 + index, number=index) for index in range(1, 13)]
    mongo = _mongo(*tickets)

    results = asyncio.run(store.search(mongo, "Applicant"))
    total = asyncio.run(store.search_count(mongo, "Applicant"))

    assert len(results) == 10
    assert total == 12


def test_list_open_orders_oldest_first_the_longest_waiting_at_top():
    """The console hub picker only shows the first `limit` results, so the
    longest-waiting applicants must be the ones that stay visible when more
    tickets are open than fit -- not the ones who just opened one."""
    older = _ticket(public=101, staff=102, number=1)
    older["created_at"] = NOW - timedelta(hours=2)
    newer = _ticket(public=201, staff=202, number=2)
    newer["created_at"] = NOW - timedelta(minutes=5)
    mongo = _mongo(newer, older)

    opened = asyncio.run(store.list_open(mongo))

    assert [doc["_id"] for doc in opened] == [older["_id"], newer["_id"]]


def test_username_search_uses_only_the_indexed_normalized_field():
    # A case-insensitive $regex on raw `username` cannot use
    # thread_v2_username_created (no collation); the search filter must stay
    # on the pre-normalized, indexed `username_search` field only.
    assert store._search_identity("Applicant") == {"username_search": "applicant"}
    assert store._search_identity("  John   Doe ") == {
        "username_search": "john doe"
    }


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


def test_slower_older_lookup_cannot_overwrite_a_faster_newer_one(monkeypatch):
    """A sync whose API lookup started before another sync's, but finishes
    persisting after it, must not revert current_tags/last_success_at to its
    own stale result."""
    ticket = _ticket()
    mongo = _mongo(ticket)
    older_lookup_started_at = NOW - timedelta(minutes=5)
    newer_lookup_started_at = NOW
    responses = {
        older_lookup_started_at: AccountsData(entries=(_linked_account("#OLDSTALE"),)),
        newer_lookup_started_at: AccountsData(entries=(_linked_account("#FRESH000"),)),
    }

    async def load(*_args, **_kwargs):
        return responses[load.next_at]

    # The newer lookup's API call finishes and persists first.
    load.next_at = newer_lookup_started_at
    monkeypatch.setattr(account_sync, "load_accounts", load)
    newer = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"],
        source=account_sync.SOURCE_OPEN, now=newer_lookup_started_at,
    ))
    assert newer.snapshot.current_tags == ("#FRESH000",)

    # The older lookup, which actually started earlier, only persists now.
    load.next_at = older_lookup_started_at
    older = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"],
        source=account_sync.SOURCE_OPEN, now=older_lookup_started_at,
    ))

    assert older.snapshot.current_tags == ("#FRESH000",)
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["linked_accounts"]["current_tags"] == ["#FRESH000"]
    assert durable["linked_accounts"]["last_success_at"] == newer_lookup_started_at


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

    # The follow-up branch is gated by the same 10-minute cooldown as the
    # lookup branch, and the sync above just stamped last_attempt_at -- move
    # past the cooldown so the recovery sweep below picks it up.
    monkeypatch.setattr(
        account_sync, "utcnow",
        lambda: datetime.now(timezone.utc) + timedelta(minutes=11),
    )
    recovered = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object()
    ))
    assert recovered == {"processed": 1, "completed": 1, "failed": 0}
    assert loads == 1
    assert expansions == 2
    assert mongo.tickets.documents[ticket["_id"]]["linked_accounts"][
        "flag_refresh_required"
    ] is False


def test_extend_matching_flags_raises_a_structured_conflict_on_duplicate_key(
    monkeypatch,
):
    """Commit 3: a DuplicateKeyError from the unique flag indexes becomes an
    operator-actionable conflict instead of an uncaught driver exception."""
    flag_a = {
        "_id": "flag_a", "kind": flag_store.FLAG_BLACKLISTED, "active": True,
        "discord_ids": [30], "player_tags": [], "rev": 0, "audit": [],
    }
    flag_b = {
        "_id": "flag_b", "kind": flag_store.FLAG_BLACKLISTED, "active": True,
        "discord_ids": [], "player_tags": ["#NEW123"], "rev": 0, "audit": [],
    }
    mongo = _mongo()
    mongo.ticket_flags = Collection([flag_a, flag_b])
    original_update = mongo.ticket_flags.find_one_and_update

    async def raise_duplicate(query, *args, **kwargs):
        # Only the flag-extension write should race; the identity lock this
        # function also takes out (same collection) must behave normally.
        if str(query.get("_id") or "") in {"flag_a", "flag_b"}:
            raise DuplicateKeyError("duplicate key")
        return await original_update(query, *args, **kwargs)

    monkeypatch.setattr(mongo.ticket_flags, "find_one_and_update", raise_duplicate)

    with pytest.raises(flag_store.FlagIdentityConflict) as excinfo:
        asyncio.run(flag_store.extend_matching_flags(
            mongo, discord_ids=30, player_tags=("#NEW123",), source="test",
        ))
    assert set(excinfo.value.flag_ids) == {"flag_a", "flag_b"}


def test_reconcile_flag_identities_records_overlap_and_clears_refresh_flag(
    monkeypatch,
):
    """Commit 3: the conflict is recorded and the refresh flag is cleared, so
    approval is never blocked by the overlap itself (only the blacklist gate
    can still block it)."""
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    async def conflict(*_args, **_kwargs):
        raise flag_store.FlagIdentityConflict(["flag_a", "flag_b"])

    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(flag_store, "extend_matching_flags", conflict)

    result = asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW,
    ))

    assert result.snapshot.current_tags == ("#NEW123",)
    linked = mongo.tickets.documents[ticket["_id"]]["linked_accounts"]
    assert linked["flag_refresh_required"] is False
    assert linked["flag_conflict"]["flag_ids"] == ["flag_a", "flag_b"]


def test_reconcile_flag_identities_clears_a_stale_conflict_on_next_success(
    monkeypatch,
):
    """A recorded conflict must not survive a later reconcile that succeeds,
    or the console's "Two flags overlap" notice (build_ticket_detail reads
    linked_accounts.flag_conflict) would stick forever after a recruiter
    fixes the overlap."""
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    async def conflict(*_args, **_kwargs):
        raise flag_store.FlagIdentityConflict(["flag_a", "flag_b"])

    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(flag_store, "extend_matching_flags", conflict)

    asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW,
    ))
    durable = mongo.tickets.documents[ticket["_id"]]
    assert durable["linked_accounts"]["flag_conflict"]["flag_ids"] == ["flag_a", "flag_b"]

    # A later observed-identity change asks for another reconcile - e.g. the
    # recruiter merged or removed one of the overlapping flags.
    linked = durable["linked_accounts"]
    linked["flag_refresh_required"] = True
    linked["flag_refresh_revision"] = linked["revision"]

    async def resolved(*_args, **_kwargs):
        return []

    monkeypatch.setattr(flag_store, "extend_matching_flags", resolved)

    result = asyncio.run(account_sync.reconcile_flag_identities(
        mongo, durable, source=account_sync.SOURCE_OPEN,
    ))

    assert "flag_conflict" not in result["linked_accounts"]
    assert "flag_conflict" not in mongo.tickets.documents[ticket["_id"]]["linked_accounts"]


def _flag_refresh_ticket():
    ticket = _ticket()
    ticket["linked_accounts"] = {
        "version": 1,
        "state": account_sync.STATE_READY,
        "current": [],
        "current_tags": ["#ABC123"],
        "retry_required": False,
        "revision": 1,
        "flag_refresh_required": True,
        "flag_refresh_revision": 1,
    }
    return ticket


def test_reconcile_flag_identities_skips_audit_when_a_flag_already_covers_identity():
    """Bug: extend_matching_flags appended a flag it left untouched (already
    covering the whole observed identity) to its returned list, so reconcile
    pushed a "linked_accounts_flags_refreshed" audit entry recording a
    change that never happened. Fix: the no-op branch is never appended."""
    ticket = _flag_refresh_ticket()
    flag = {
        "_id": "flag_a",
        "kind": flag_store.FLAG_BLACKLISTED,
        "active": True,
        "discord_ids": [ticket["user_id"]],
        "player_tags": ["#ABC123"],
        "rev": 0,
        "audit": [],
    }
    mongo = _mongo(ticket)
    mongo.ticket_flags = Collection([flag])

    result = asyncio.run(account_sync.reconcile_flag_identities(
        mongo, ticket, source=account_sync.SOURCE_OPEN,
    ))

    assert result["linked_accounts"]["flag_refresh_required"] is False
    assert not result.get("account_identity_audit")
    assert mongo.ticket_flags.documents["flag_a"]["rev"] == 0


def test_reconcile_flag_identities_audits_when_a_flag_is_actually_extended():
    ticket = _flag_refresh_ticket()
    flag = {
        "_id": "flag_a",
        "kind": flag_store.FLAG_BLACKLISTED,
        "active": True,
        "discord_ids": [],
        "player_tags": ["#ABC123"],
        "rev": 0,
        "audit": [],
    }
    mongo = _mongo(ticket)
    mongo.ticket_flags = Collection([flag])

    result = asyncio.run(account_sync.reconcile_flag_identities(
        mongo, ticket, source=account_sync.SOURCE_OPEN,
    ))

    assert result["linked_accounts"]["flag_refresh_required"] is False
    audit = result.get("account_identity_audit") or []
    assert audit and audit[-1]["event"] == "linked_accounts_flags_refreshed"
    assert mongo.ticket_flags.documents["flag_a"]["discord_ids"] == [ticket["user_id"]]
    assert mongo.ticket_flags.documents["flag_a"]["rev"] == 1


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

    # The follow-up branch is gated by the same 10-minute cooldown as the
    # lookup branch, and the resync above just stamped last_attempt_at --
    # move past the cooldown so the sweep below picks it up.
    monkeypatch.setattr(
        account_sync, "utcnow",
        lambda: datetime.now(timezone.utc) + timedelta(minutes=11),
    )
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

    # The failure just landed, so it is still within the retry cooldown --
    # a sweep running right now must leave it alone.
    immediate = asyncio.run(account_sync.recover_pending_account_syncs(
        mongo, object(), after_sync=queue
    ))
    assert immediate == {"processed": 0, "completed": 0, "failed": 0}
    still_failed = mongo.tickets.documents[ticket["_id"]]["linked_accounts"]
    assert still_failed["retry_required"] is True

    # Once the cooldown has elapsed, the same sweep retries it.
    monkeypatch.setattr(
        account_sync, "utcnow",
        lambda: datetime.now(timezone.utc) + timedelta(minutes=11),
    )
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
    assert asyncio.run(store.active_store(mongo)) == store.STORE_TICKETS


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
def test_v2_store_authority_is_fixed_even_with_obsolete_activation_config(config):
    documents = [] if config is None else [config]
    mongo = SimpleNamespace(ticket_setup=Collection(documents))
    assert asyncio.run(store.active_store(mongo)) == store.STORE_TICKETS


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


def test_index_preflight_ignores_stale_channel_rows_in_thread_collection():
    live = _ticket()
    stale = {
        **deepcopy(live),
        "_id": "stale-channel-copy",
        "venue": "channel",
        "runtime": "legacy_channel",
    }
    assert store.index_conflicts_for_documents([live, stale]) == {}


def test_index_preflight_ignores_thread_rows_owned_by_another_runtime():
    live = _ticket()
    stale = {
        **deepcopy(live),
        "_id": "stale-thread-copy",
        "runtime": "obsolete_thread_runtime",
    }
    assert store.index_conflicts_for_documents([live, stale]) == {}


def test_open_thread_insert_requires_shared_slot_binding():
    mongo = _mongo()
    with pytest.raises(schema.TicketSchemaError, match="open-slot binding"):
        asyncio.run(store.insert_one(mongo, _ticket()))
    assert mongo.tickets.documents == {}


def test_index_installation_uses_preflighted_partial_unique_contracts():
    mongo = _mongo(_ticket())
    names = asyncio.run(store.ensure_indexes(mongo))
    assert "thread_v2_one_open_ticket_per_applicant_type" in names
    open_index = next(
        options for _spec, options in mongo.tickets.indexes
        if options.get("name") == "thread_v2_one_open_ticket_per_applicant_type"
    )
    assert open_index["unique"] is True
    assert open_index["partialFilterExpression"] == {
        **store.RUNTIME_FILTER,
        "status": "open",
        "user_id": {"$exists": True}, "ticket_type": {"$exists": True},
    }


def test_incompatible_existing_index_definition_fails_without_replacement():
    class IncompatibleIndexCollection(Collection):
        async def create_index(self, spec, **kwargs):
            if kwargs.get("name") == "thread_v2_ticket_location_unique":
                raise OperationFailure(
                    "Index already exists with a different definition", code=85
                )
            return await super().create_index(spec, **kwargs)

    mongo = _mongo()
    mongo.tickets = IncompatibleIndexCollection([_ticket()])
    with pytest.raises(OperationFailure) as raised:
        asyncio.run(store.ensure_indexes(mongo))
    assert raised.value.code == 85
    assert mongo.tickets.indexes == []


def test_existing_broad_status_index_coexists_with_v2_partial_index():
    class ExistingBroadIndexCollection(Collection):
        def __init__(self, documents):
            super().__init__(documents)
            self.indexes.append((
                [("status", 1), ("created_at", -1)],
                {"name": "status_created"},
            ))

        async def create_index(self, spec, **kwargs):
            if kwargs.get("name") == "status_created":
                raise OperationFailure("legacy index name collision", code=85)
            return await super().create_index(spec, **kwargs)

    mongo = _mongo()
    mongo.tickets = ExistingBroadIndexCollection([_ticket()])
    names = asyncio.run(store.ensure_indexes(mongo))
    assert "thread_v2_status_created" in names
    installed = {options.get("name") for _spec, options in mongo.tickets.indexes}
    assert {"status_created", "thread_v2_status_created"} <= installed


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
        assert options["name"] == (
            "thread_v2_account_recovery_" + field.rsplit(".", 1)[-1]
        )
        assert options["partialFilterExpression"] == {
            **store.RUNTIME_FILTER,
            field: True,
        }
        assert options["name"] in names


def test_find_by_location_runs_two_single_field_lookups_no_or(monkeypatch):
    """`find_by_location` resolves which ticket a channel/thread belongs to
    on every guild message. A single `$or` across `location.id`/
    `location.staff_space_id` cannot use either field's unique partial index
    (each index's `partialFilterExpression` requires only that one field to
    exist, which the `$or`'s other branch does not imply), so it used to
    fall back to a collection scan. Two sequential single-field `find_one`
    calls each stay on their own unique partial index instead."""
    ticket = _ticket(public=101, staff=102)
    mongo = _mongo(ticket)

    by_public = asyncio.run(store.find_by_location(mongo, 101))
    assert by_public is not None
    assert by_public["_id"] == ticket["_id"]

    by_staff = asyncio.run(store.find_by_location(mongo, 102))
    assert by_staff is not None
    assert by_staff["_id"] == ticket["_id"]

    captured = []

    async def fake_find_one(_mongo, filt):
        captured.append(filt)
        return None

    monkeypatch.setattr(store, "find_one", fake_find_one)
    asyncio.run(store.find_by_location(mongo, 101))
    assert captured == [
        {"location.id": {"$in": [101, "101"]}},
        {"location.staff_space_id": {"$in": [101, "101"]}},
    ]
    for filt in captured:
        assert "$or" not in filt


def test_thread_v2_location_lookup_indexes_are_not_installed():
    """The unique partial indexes on `location.id`/`location.staff_space_id`
    already serve `find_by_location`'s two single-field lookups (a non-null
    `$in` entails existence, which is exactly what those indexes' partial
    filter requires) -- a separate non-unique index on the same keys is
    redundant and must not be installed."""
    mongo = _mongo(_ticket())
    names = asyncio.run(store.ensure_indexes(mongo))
    assert "thread_v2_location_lookup" not in names
    assert "thread_v2_staff_location_lookup" not in names
    installed = {options.get("name") for _spec, options in mongo.tickets.indexes}
    assert "thread_v2_location_lookup" not in installed
    assert "thread_v2_staff_location_lookup" not in installed

    # Idempotent: a second install must not error and must produce the same
    # set of names.
    again = asyncio.run(store.ensure_indexes(mongo))
    assert again == names


def test_account_recovery_executes_the_frozen_indexed_predicate(monkeypatch):
    observed = []

    async def find(_mongo, query, *, sort=None, limit=None):
        observed.append((query, sort, limit))
        return []

    monkeypatch.setattr(account_sync.store, "find", find)
    counts = asyncio.run(account_sync.recover_pending_account_syncs(
        SimpleNamespace(), object()
    ))
    assert counts == {"processed": 0, "completed": 0, "failed": 0}
    assert len(observed) == 1
    query, sort, limit = observed[0]

    base_index = account_sync.account_recovery_filter()
    assert query["type"] == base_index["type"]
    assert query["venue"] == base_index["venue"]
    # Both branches -- the lookup-due retry/never-synced case and the
    # flag/context follow-up case -- are gated by the same cooldown, so a
    # permanently-stuck follow-up cannot sort first every sweep and starve
    # the lookups sharing the same bounded batch.
    assert query["$or"][0]["$and"][0] == {"$or": [
        {"linked_accounts.retry_required": True},
        {"status": "open", "linked_accounts.version": {"$exists": False}},
    ]}
    assert query["$or"][1]["$and"][0] == {"$or": [
        {"linked_accounts.context_refresh_required": True},
        {"linked_accounts.flag_refresh_required": True},
    ]}
    for clause in query["$or"]:
        cutoff = clause["$and"][1]["$or"][1]["linked_accounts.last_attempt_at"]["$lte"]
        assert abs((datetime.now(timezone.utc) - timedelta(minutes=10) - cutoff).total_seconds()) < 5
    assert sort == [("linked_accounts.last_attempt_at", 1), ("_id", 1)]
    assert limit == 25


def test_follow_up_due_is_gated_by_the_same_cooldown_as_lookup_due(monkeypatch):
    """A ticket that only needs the flag/context follow-up (it already has
    a `linked_accounts.version`, so the lookup branch is skipped) must be
    gated by the same 10-minute cooldown as a lookup-due ticket -- otherwise
    a permanently-failing follow-up sorts first (oldest/missing
    `last_attempt_at`) every sweep and starves the lookups sharing the same
    bounded batch."""
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(account_sync, "utcnow", lambda: now)

    def _follow_up_ticket(number, *, minutes_ago):
        ticket = _ticket(
            public=200 + number, staff=300 + number,
            number=number, user=100 + number,
        )
        ticket["linked_accounts"] = {
            "version": 1,
            "state": account_sync.STATE_READY,
            "current": [],
            "current_tags": [],
            "retry_required": False,
            "flag_refresh_required": True,
            "last_attempt_at": now - timedelta(minutes=minutes_ago),
            "revision": 1,
        }
        return ticket

    recent = _follow_up_ticket(1, minutes_ago=5)
    stale = _follow_up_ticket(2, minutes_ago=15)
    mongo = _mongo(recent, stale)

    reconciled_ids = []

    async def reconcile(_mongo, ticket, *, source):
        reconciled_ids.append(ticket["_id"])
        durable = deepcopy(ticket)
        durable["linked_accounts"]["flag_refresh_required"] = False
        return durable

    monkeypatch.setattr(account_sync, "reconcile_flag_identities", reconcile)

    counts = asyncio.run(account_sync.recover_pending_account_syncs(mongo, object()))

    # Only the ticket whose follow-up attempt is outside the cooldown
    # (15 minutes ago) is selected; the one attempted 5 minutes ago is
    # skipped.
    assert reconciled_ids == [stale["_id"]]
    assert counts == {"processed": 1, "completed": 1, "failed": 0}


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


def test_ensure_indexes_caches_failure_within_a_retry_window(monkeypatch):
    duplicate = _mongo(
        _ticket(),
        _ticket(public=201, staff=202, number=2, user=30),
    )
    original_index_conflicts = store.index_conflicts
    calls = []

    async def counting_index_conflicts(collection):
        calls.append(1)
        return await original_index_conflicts(collection)

    monkeypatch.setattr(store, "index_conflicts", counting_index_conflicts)

    with pytest.raises(store.IndexConflictError) as first_raise:
        asyncio.run(store.ensure_indexes(duplicate))
    assert len(calls) == 1

    # Still inside the retry window: the cached failure is re-raised without
    # repeating the full-collection preflight scan.
    with pytest.raises(store.IndexConflictError) as second_raise:
        asyncio.run(store.ensure_indexes(duplicate))
    assert len(calls) == 1
    assert second_raise.value is first_raise.value

    # Once the window passes, ensure_indexes tries the preflight again.
    monkeypatch.setattr(store, "_index_retry_at", time.monotonic() - 1)
    with pytest.raises(store.IndexConflictError):
        asyncio.run(store.ensure_indexes(duplicate))
    assert len(calls) == 2


def test_ensure_creation_indexes_caches_failure_within_a_retry_window(monkeypatch):
    calls = []

    async def failing_canonical_store(_mongo):
        calls.append(1)
        raise store.IndexConflictError({"location": ["ticket_101"]})

    monkeypatch.setattr(
        thread_service, "ensure_canonical_ticket_store", failing_canonical_store
    )
    mongo = SimpleNamespace()

    with pytest.raises(store.IndexConflictError):
        asyncio.run(thread_service.ensure_creation_indexes(mongo))
    assert len(calls) == 1

    with pytest.raises(store.IndexConflictError):
        asyncio.run(thread_service.ensure_creation_indexes(mongo))
    assert len(calls) == 1

    monkeypatch.setattr(
        thread_service, "_creation_index_retry_at", time.monotonic() - 1
    )
    with pytest.raises(store.IndexConflictError):
        asyncio.run(thread_service.ensure_creation_indexes(mongo))
    assert len(calls) == 2


def test_ensure_indexes_does_not_cache_a_transient_connection_error(monkeypatch):
    """A ServerSelectionTimeoutError from the index_conflicts preflight (an
    Atlas outage) must not block ticket intake for the retry window once
    Mongo recovers -- unlike IndexConflictError, it is retried every call.
    ExecutionTimeout subclasses OperationFailure but is transient, as is a
    bare OperationFailure whose .code is an Atlas failover code (91 here).
    """
    transient_errors = [
        ServerSelectionTimeoutError("no primary available"),
        OperationFailure("interrupted due to repl state change", code=91),
        ExecutionTimeout("operation exceeded time limit", code=50),
    ]

    for error in transient_errors:
        mongo = _mongo(_ticket())
        calls = []

        async def flaky_index_conflicts(collection, _error=error):
            calls.append(1)
            raise _error

        monkeypatch.setattr(store, "index_conflicts", flaky_index_conflicts)

        with pytest.raises(type(error)):
            asyncio.run(store.ensure_indexes(mongo))
        assert len(calls) == 1
        assert store._indexes_failed is False
        assert store._last_index_error is None

        with pytest.raises(type(error)):
            asyncio.run(store.ensure_indexes(mongo))
        assert len(calls) == 2


def test_ensure_indexes_caches_a_non_transient_bare_operation_failure(monkeypatch):
    """A bare OperationFailure for an incompatible index definition (85,
    IndexOptionsConflict) needs operator repair and is stable, unlike the
    Atlas-failover codes above -- it must be cached like IndexConflictError.
    """
    mongo = _mongo(_ticket())
    calls = []

    async def failing_index_conflicts(collection):
        calls.append(1)
        raise OperationFailure(
            "Index already exists with a different definition", code=85
        )

    monkeypatch.setattr(store, "index_conflicts", failing_index_conflicts)

    with pytest.raises(OperationFailure):
        asyncio.run(store.ensure_indexes(mongo))
    assert len(calls) == 1

    with pytest.raises(OperationFailure):
        asyncio.run(store.ensure_indexes(mongo))
    assert len(calls) == 1


def test_ensure_creation_indexes_does_not_cache_a_transient_connection_error(monkeypatch):
    calls = []

    async def flaky_canonical_store(_mongo):
        calls.append(1)
        raise ServerSelectionTimeoutError("no primary available")

    monkeypatch.setattr(
        thread_service, "ensure_canonical_ticket_store", flaky_canonical_store
    )
    mongo = SimpleNamespace()

    with pytest.raises(ServerSelectionTimeoutError):
        asyncio.run(thread_service.ensure_creation_indexes(mongo))
    assert len(calls) == 1
    assert thread_service._creation_index_failed is False

    with pytest.raises(ServerSelectionTimeoutError):
        asyncio.run(thread_service.ensure_creation_indexes(mongo))
    assert len(calls) == 2


def test_runtime_lookup_fails_closed_for_legacy_channel_rows():
    legacy = schema.normalize_ticket_document({
        "_id": "legacy", "status": "open", "ticket_type": "main",
        "channel_id": 101, "user_id": 30,
    })
    mongo = _mongo(legacy)
    assert asyncio.run(store.find_by_location(mongo, 101)) is None


def test_store_find_default_hides_channel_era_rows_include_legacy_reveals_them():
    """manage.py's diagnostics view filters for CHANNEL_ERA_ONLY (venue !=
    thread). store.find's default RUNTIME_FILTER merges its own venue/runtime
    keys in last, silently overriding that filter and returning zero rows;
    include_legacy=True is the diagnostics-only opt-out.
    """
    legacy = schema.normalize_ticket_document({
        "_id": "legacy-101", "status": "open", "ticket_type": "main",
        "channel_id": 101, "user_id": 30,
    })
    mongo = _mongo(legacy)
    query = {"type": "ticket", **manage.CHANNEL_ERA_ONLY}

    assert asyncio.run(store.find(mongo, query)) == []

    rows = asyncio.run(store.find(mongo, query, include_legacy=True))
    assert [row["_id"] for row in rows] == ["legacy-101"]


def test_store_find_include_legacy_returns_raw_documents_normalization_would_reject():
    """normalize_ticket_document raises TicketSchemaError on a legacy row with
    status == "closed" (schema.py), and such a row exists in production.
    manage.py's diagnostics reader -- the only include_legacy=True caller --
    wants the raw status, so include_legacy=True must skip normalisation
    entirely instead of crashing the diagnostics command.
    """
    raw_closed = {
        "_id": "legacy-closed-1",
        "type": "ticket",
        "venue": "channel",
        "status": "closed",
        "ticket_type": "main",
        "channel_id": 555,
        "user_id": 40,
    }
    mongo = _mongo(raw_closed)

    assert asyncio.run(store.find(mongo, {"_id": "legacy-closed-1"})) == []

    rows = asyncio.run(
        store.find(mongo, {"_id": "legacy-closed-1"}, include_legacy=True)
    )
    assert rows == [raw_closed]


def test_ticket_authorization_is_bound_to_the_configured_target_guild():
    mongo = SimpleNamespace(ticket_setup=Collection([{
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_thread_recruiter_role": "101",
        "fwa_thread_recruiter_role": 102,
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

    legacy_only = SimpleNamespace(ticket_setup=Collection([{
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": 101,
        "fwa_recruiter_role": 102,
    }]))
    assert asyncio.run(perms.is_recruiter(target_recruiter, legacy_only)) is False


def test_foreign_guild_admin_cannot_read_or_mutate_private_ticket_data(monkeypatch):
    mongo = SimpleNamespace(ticket_setup=Collection([{
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_thread_recruiter_role": 101,
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


def test_insert_is_idempotent_and_never_writes_legacy_authority():
    class FailingMirror(Collection):
        async def replace_one(self, *_args, **_kwargs):
            raise TimeoutError("mirror unavailable")

    mongo = _mongo()
    mongo.button_store = FailingMirror()
    ticket = _ticket()
    ticket.update({
        "open_slot_id": "ticket-open:30:main",
        "creation_workflow_id": "thread:30:main",
    })
    first = asyncio.run(store.insert_one(mongo, ticket))
    second = asyncio.run(store.insert_one(mongo, ticket))
    assert first == second
    assert first["runtime"] == "thread_v2"
    assert mongo.tickets.documents[ticket["_id"]] == first
    assert mongo.button_store.documents == {}


@pytest.mark.parametrize("field", [
    "location", "location.id", "guild_id", "channel_id", "thread_id",
    "player_tag", "player_tags",
])
def test_update_one_rejects_guarded_identity_field_writes(field):
    mongo = _mongo(_ticket())
    with pytest.raises(store.GuardedFieldWriteError):
        asyncio.run(store.update_one(
            mongo, {"_id": "ticket_101"}, {"$set": {field: "anything"}},
        ))
    assert mongo.tickets.documents["ticket_101"]["channel_id"] == 101


def test_update_many_rejects_guarded_identity_field_writes():
    mongo = _mongo(_ticket())
    with pytest.raises(store.GuardedFieldWriteError):
        asyncio.run(store.update_many(
            mongo, {"status": "open"}, {"$set": {"guild_id": 999}},
        ))


def test_update_one_allows_unrelated_field_writes():
    mongo = _mongo(_ticket())
    result = asyncio.run(store.update_one(
        mongo, {"_id": "ticket_101"}, {"$set": {"handled_by_name": "Recruiter"}},
    ))
    assert result.matched_count == 1
    assert mongo.tickets.documents["ticket_101"]["handled_by_name"] == "Recruiter"


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


def test_status_transition_slices_audit_and_account_identity_audit_at_200():
    ticket = _ticket()
    old_audit = [{"event": f"seed_{index}"} for index in range(250)]
    old_account_audit = [{"event": f"acct_seed_{index}"} for index in range(250)]
    ticket["audit"] = old_audit
    ticket["account_identity_audit"] = old_account_audit
    mongo = _mongo(ticket)

    won = asyncio.run(store.transition(
        mongo, "ticket_101", to_status="denied", actor_id=99,
        actor_name="Recruiter", expected_rev=0,
        linked_account_retry={"source": "final_denial", "error": "AccountSyncError"},
    ))

    assert won.outcome == store.WON
    audit = won.doc["audit"]
    assert len(audit) == store.MAX_AUDIT_ENTRIES
    assert audit[:-1] == old_audit[-(store.MAX_AUDIT_ENTRIES - 1):]
    assert audit[-1]["event"] == "status_transition"

    account_audit = won.doc["account_identity_audit"]
    assert len(account_audit) == store.MAX_AUDIT_ENTRIES
    assert account_audit[:-1] == old_account_audit[-(store.MAX_AUDIT_ENTRIES - 1):]
    assert account_audit[-1]["event"] == "linked_accounts_sync_failed"


def test_account_sync_slices_account_identity_audit_at_200(monkeypatch):
    ticket = _ticket()
    ticket["account_identity_audit"] = [
        {"event": f"acct_seed_{index}"} for index in range(250)
    ]
    mongo = _mongo(ticket)

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#SLICE01"),))

    monkeypatch.setattr(account_sync, "load_accounts", load)
    asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW,
    ))

    durable = mongo.tickets.documents[ticket["_id"]]
    account_audit = durable["account_identity_audit"]
    assert len(account_audit) == store.MAX_AUDIT_ENTRIES
    assert any(entry["event"] == "linked_accounts_synced" for entry in account_audit)


def test_flag_set_slices_audit_at_200():
    existing_flag = {
        "_id": "flag_existing",
        "kind": "blacklisted",
        "discord_ids": [42],
        "player_tags": [],
        "active": True,
        "rev": 0,
        "audit": [{"event": f"seed_{index}"} for index in range(250)],
        "created_at": NOW,
        "updated_at": NOW,
    }
    mongo = SimpleNamespace(ticket_flags=Collection([existing_flag]))

    updated = asyncio.run(flag_store.set_flag(
        mongo,
        kind="blacklisted",
        discord_ids=42,
        source="recruiter_review",
        added_by=99,
        added_by_name="Recruiter",
        reason="repeat abuse",
    ))

    audit = updated["audit"]
    assert len(audit) == store.MAX_AUDIT_ENTRIES
    assert audit[-1]["event"] == "flag_set"


@pytest.mark.parametrize("status", ["approved", "denied"])
def test_terminal_commit_checkpoints_slot_and_release_failure_is_retryable(
    monkeypatch, status
):
    mongo = _mongo(_ticket())
    calls = []

    async def mark(_mongo, *, ticket_id, terminal_status):
        calls.append(("mark", ticket_id, terminal_status))
        return {"state": "release_pending"}

    async def fail_release(_mongo, *, ticket_id):
        calls.append(("release", ticket_id))
        raise TimeoutError("release will reconcile at startup")

    monkeypatch.setattr(ticket_runtime, "mark_slot_release_pending", mark)
    monkeypatch.setattr(ticket_runtime, "release_open_slot", fail_release)
    result = asyncio.run(store.transition(
        mongo,
        "ticket_101",
        to_status=status,
        actor_id=99,
        actor_name="Recruiter",
        expected_rev=0,
    ))

    assert result.won
    assert result.doc["status"] == status
    assert calls == [
        ("mark", "ticket_101", status),
        ("release", "ticket_101"),
    ]
    before = deepcopy(mongo.tickets.documents)
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


def test_override_transition_audits_as_an_overturn_with_reason():
    """Commit 2: an override is logged under its own event, not a plain
    status_transition, with the fields a reader would look for."""
    prior_marker = "ticket-resolution:ticket_101:4:approved"
    terminal = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    terminal.update({
        "rev": 4,
        "approved_by": 40,
        "approved_at": NOW,
        "resolution_effects": {"marker": prior_marker, "complete": True},
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
    entry = result.doc["audit"][-1]
    assert entry["event"] == "overturn"
    assert entry["from"] == "approved"
    assert entry["to"] == "denied"
    assert entry["by"] == 50
    assert entry["reason"] == "Appeal reviewed"


def test_overturn_ticket_requires_recruiter(monkeypatch):
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    mongo = _mongo(ticket)

    async def not_recruiter(*_args, **_kwargs):
        return False

    monkeypatch.setattr(resolve.perms, "is_recruiter", not_recruiter)
    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="denied", reason="Appeal reviewed",
    ))
    assert result.outcome == store.UNAUTHORIZED


def test_overturn_ticket_refuses_an_undecided_ticket(monkeypatch):
    ticket = _ticket(status="open")
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="denied", reason="Appeal reviewed",
    ))
    assert result.outcome == store.LOST
    assert result.reason == resolve.OVERTURN_NOT_DECIDED_MESSAGE


def test_overturn_ticket_refuses_the_same_status(monkeypatch):
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="approved",
    ))
    assert result.outcome == store.LOST
    assert "already approved" in (result.reason or "")


def test_overturn_deny_after_approve_removes_recorded_roles(monkeypatch):
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 4,
        "approved_by": 40,
        "approved_by_name": "Lead",
        "approved_at": NOW,
        "granted_role_ids": [555],
        "resolution_effects": {"marker": "m", "complete": True},
    })
    mongo = _mongo(ticket)
    removed = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def deny(_bot, _mongo, **kwargs):
        assert kwargs["override"]["by"] == 40
        assert kwargs["override"]["status"] == "approved"
        assert "rev" not in kwargs["override"]
        assert "expected_rev" not in kwargs
        assert kwargs["prior_effect_marker"] == "m"
        current = deepcopy(ticket)
        current["status"] = "denied"
        return store.Transition(store.WON, current)

    async def remove_role(guild_id, user_id, role_id, **_kwargs):
        removed.append((guild_id, user_id, role_id))

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "deny_ticket", deny)

    bot = SimpleNamespace(rest=SimpleNamespace(remove_role_from_member=remove_role))
    result = asyncio.run(resolve.overturn_ticket(
        bot, mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="denied", reason="Appeal reviewed",
    ))
    assert result.won
    assert removed == [(ticket["guild_id"], ticket["user_id"], 555)]


def test_overturn_deny_after_approve_is_a_no_op_when_no_roles_were_recorded(
    monkeypatch,
):
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 4,
        "approved_by": 40,
        "resolution_effects": {"marker": "m", "complete": True},
    })
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def deny(_bot, _mongo, **_kwargs):
        current = deepcopy(ticket)
        current["status"] = "denied"
        return store.Transition(store.WON, current)

    async def remove_role(*_args, **_kwargs):
        raise AssertionError("nothing was ever granted; there is nothing to remove")

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "deny_ticket", deny)

    bot = SimpleNamespace(rest=SimpleNamespace(remove_role_from_member=remove_role))
    result = asyncio.run(resolve.overturn_ticket(
        bot, mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="denied", reason="Appeal reviewed",
    ))
    assert result.won


def test_overturn_approve_after_deny_delegates_with_the_prior_decision(monkeypatch):
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 2,
        "denied_by": 41,
        "denied_by_name": "Other Lead",
        "denied_at": NOW,
        "resolution_effects": {"marker": "m2", "complete": True},
    })
    mongo = _mongo(ticket)
    calls = {}

    async def recruiter(*_args, **_kwargs):
        return True

    async def approve(_bot, _mongo, **kwargs):
        calls.update(kwargs)
        current = deepcopy(ticket)
        current["status"] = "approved"
        return store.Transition(store.WON, current)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "approve_ticket", approve)

    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="approved",
    ))
    assert result.won
    assert calls["override"]["by"] == 41
    assert calls["expected_status"] == "denied"
    assert "rev" not in calls["override"]
    assert "expected_rev" not in calls


def test_overturn_ignores_an_unrelated_rev_bump_between_snapshot_and_transition(
    monkeypatch,
):
    """Commit: overturn_ticket no longer freezes an expected_rev snapshot
    before the account-sync round trip. An unrelated rev bump landing between
    that read and the eventual CAS must not produce a false "Already approved
    by" notice - the status filter is the only guard now."""
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 2,
        "approved_by": 40,
        "approved_at": NOW,
        "resolution_effects": {"marker": "m", "complete": True},
    })
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def effects(_bot, _mongo, doc):
        # Effects delivery is exercised elsewhere; this test is only about
        # the CAS the transition itself uses.
        return store.Transition(store.WON, doc)

    real_snapshot_from_ticket = account_sync.snapshot_from_ticket
    bumped = {"done": False}

    def bump_once_then_snapshot(ticket_doc):
        if not bumped["done"]:
            bumped["done"] = True
            # An unrelated write (e.g. candidate activity) lands after
            # overturn_ticket's initial read but before the CAS transition.
            mongo.tickets.documents[ticket["_id"]]["rev"] += 3
        return real_snapshot_from_ticket(ticket_doc)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    monkeypatch.setattr(account_sync, "snapshot_from_ticket", bump_once_then_snapshot)

    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="denied", reason="Appeal reviewed",
    ))

    assert result.won
    assert result.reason is None
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "denied"
    assert mongo.tickets.documents[ticket["_id"]]["rev"] == 6


def test_overturn_deny_to_approve_ignores_rev_bump_between_snapshot_and_transition(
    monkeypatch,
):
    """Bug: _resolve_ticket froze expected_rev to the just-read ticket rev
    whenever kind == KIND_APPROVE, even on the override/overturn path. A
    background effect checkpoint bumping rev between that freeze and
    store.transition's CAS then produced a false "prior resolution changed"
    LOST on an approve-side overturn, even though override's own status
    filter is the only guard an overturn is supposed to need. Fix: the
    freeze is skipped whenever override is not None."""
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "rev": 2,
        "denied_by": 41,
        "denied_by_name": "Other Lead",
        "denied_at": NOW,
        "resolution_effects": {"marker": "m2", "complete": True},
        "linked_accounts": {
            "version": 1,
            "state": account_sync.STATE_READY,
            "current": [{
                "tag": "#ABC123",
                "name": "Player 123",
                "town_hall": 17,
                "profile_status": STATUS_LOADED,
            }],
            "current_tags": ["#ABC123"],
            "retry_required": False,
            "revision": 1,
        },
        "linked_account_identities": [{
            "tag": "#ABC123",
            "name": "Player 123",
            "town_hall": 17,
            "profile_status": STATUS_LOADED,
            "first_seen_at": NOW,
            "first_seen_source": "test",
        }],
    })
    mongo = _mongo(ticket)

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#ABC123"),))

    async def effects(_bot, _mongo, doc):
        return store.Transition(store.WON, doc)

    async def blacklist_with_rev_bump(*_args, **_kwargs):
        # A background effect checkpoint (e.g. a concurrent resolution's
        # side-effect write) lands after transition_kwargs is built - the
        # point a buggy freeze would have snapshotted rev at - but before
        # store.transition runs its CAS.
        mongo.tickets.documents[ticket["_id"]]["rev"] += 3
        return None

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist_with_rev_bump)

    result = asyncio.run(resolve.overturn_ticket(
        object(), mongo, ticket_id=ticket["_id"], member=SimpleNamespace(id=1),
        actor_name="Recruiter", to_status="approved", coc_client=object(),
    ))

    assert result.won
    assert result.reason is None
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "approved"
    assert mongo.tickets.documents[ticket["_id"]]["rev"] == 6


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


def test_candidate_activity_is_idempotent_and_merges_normalized_tags():
    mongo = _mongo(_ticket())
    first = asyncio.run(store.append_candidate_activity(
        mongo, "ticket_101", message_id=500, author_id=30,
        content="My tag is #def456", mentioned_tags=("def456",), occurred_at=NOW,
    ))
    again = asyncio.run(store.append_candidate_activity(
        mongo, "ticket_101", message_id=500, author_id=30,
        content="My tag is #def456", mentioned_tags=("def456",), occurred_at=NOW,
    ))
    assert first.won and again.won
    assert again.reason == "already recorded"
    assert again.doc["answer_count"] == 1
    # A tag typed by the applicant is unverified: it merges into mentioned_tags
    # only, and never joins the verified player_tags identity.
    assert again.doc["player_tags"] == ["#ABC123"]
    assert again.doc["mentioned_tags"] == ["#DEF456"]
    # Applicant activity must never bump `rev`: that is the console's
    # resolution CAS counter, and a false "another recruiter changed this"
    # must not be manufactured by the applicant typing another answer.
    assert again.doc.get("rev", 0) == 0
    assert again.doc["activity_revision"] == 1


def test_mark_thread_missing_sets_a_field_not_a_status():
    mongo = _mongo(_ticket())
    result = asyncio.run(store.mark_thread_missing(
        mongo, "ticket_101", thread_role="candidate",
    ))
    assert result.won
    assert result.doc["status"] == "open"
    assert result.doc["thread_missing"]["thread_role"] == "candidate"

    # Idempotent: re-marking an already-flagged ticket is a no-op, not an error.
    again = asyncio.run(store.mark_thread_missing(
        mongo, "ticket_101", thread_role="candidate",
    ))
    assert again.won
    assert again.doc["thread_missing"]["thread_role"] == "candidate"


def test_mark_thread_missing_rejects_an_unknown_role():
    mongo = _mongo(_ticket())
    with pytest.raises(ValueError, match="thread_role"):
        asyncio.run(store.mark_thread_missing(
            mongo, "ticket_101", thread_role="applicant",
        ))


def test_mark_thread_missing_staff_never_overwrites_a_candidate_marker():
    """A staff-thread deletion must not downgrade a ticket that already knows
    its candidate thread is gone: overwriting `thread_missing` back to
    "staff" would bring the ticket back into the open authority set even
    though the slot was already released. The staff call on an
    already-candidate-marked ticket must be a no-op that still reports WON
    with the existing (unchanged) document, while a staff call on a fresh
    ticket with no marker at all must still set one normally."""
    mongo = _mongo(_ticket())
    candidate = asyncio.run(store.mark_thread_missing(
        mongo, "ticket_101", thread_role="candidate",
    ))
    assert candidate.won
    assert candidate.doc["thread_missing"]["thread_role"] == "candidate"

    staff_after_candidate = asyncio.run(store.mark_thread_missing(
        mongo, "ticket_101", thread_role="staff",
    ))
    assert staff_after_candidate.won
    assert staff_after_candidate.doc["thread_missing"]["thread_role"] == "candidate"
    assert mongo.tickets.documents["ticket_101"]["thread_missing"]["thread_role"] == "candidate"

    fresh_mongo = _mongo(_ticket())
    fresh_staff = asyncio.run(store.mark_thread_missing(
        fresh_mongo, "ticket_101", thread_role="staff",
    ))
    assert fresh_staff.won
    assert fresh_staff.doc["thread_missing"]["thread_role"] == "staff"


def test_claim_creation_dm_wins_once_then_a_retry_is_a_no_op():
    """The CAS marker must let exactly one caller send the DM -- a retried
    REST call after a crash between send and record must find the marker
    already set and skip, never sending a second copy."""
    mongo = _mongo(_ticket())
    first = asyncio.run(store.claim_creation_dm(mongo, "ticket_101"))
    assert first is True
    assert mongo.tickets.documents["ticket_101"]["creation_dm_sent_at"] is not None

    second = asyncio.run(store.claim_creation_dm(mongo, "ticket_101"))
    assert second is False


def test_approve_succeeds_after_applicant_activity_between_panel_open_and_click():
    mongo = _mongo(_ticket())
    asyncio.run(store.append_candidate_activity(
        mongo, "ticket_101", message_id=501, author_id=30,
        content="One more answer", occurred_at=NOW,
    ))
    # A recruiter's detail panel was rendered before the applicant's message
    # landed; the console no longer snapshots a client-side expected_rev, so
    # the applicant's activity in between must not defeat the approval.
    won = asyncio.run(store.transition(
        mongo, "ticket_101", to_status="approved", actor_id=99,
        actor_name="Recruiter", expected_rev=None, effect_kind=resolve.KIND_APPROVE,
    ))
    assert won.outcome == store.WON
    assert won.doc["status"] == "approved"


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
def test_final_account_context_must_be_fresh_before_terminal_effects(
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

    async def hub(*_args, **_kwargs):
        return True

    monkeypatch.setattr(console, "deliver_staff_identity_context", context)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", hub)
    result = asyncio.run(resolve._process_resolution_effects_owned(
        _effect_bot(EffectRest()),
        mongo,
        ticket,
    ))

    # No archive step exists any more -- staff context is the only thing
    # this path calls, and its freshness alone decides WON vs EFFECT_FAILED.
    assert order == [("context", ("#NEW123",))]
    if fresh:
        assert result.outcome == store.WON
    else:
        assert result.outcome == store.EFFECT_FAILED


def test_checkpoint_failure_after_notification_does_not_report_false_failure(monkeypatch):
    ticket = _effect_ticket()
    rest = EffectRest()
    sends = []
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
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)
    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), SimpleNamespace(), ticket
    ))
    assert result.won
    assert sends == [ticket["resolution_effects"]["marker"]]


def test_notification_failure_still_requests_hub(monkeypatch):
    ticket = _effect_ticket()
    mongo = _mongo(ticket)
    rest = EffectRest()
    calls = []

    async def notification(*_args, **_kwargs):
        calls.append("notification")
        raise TimeoutError("notification unavailable")

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
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.outcome == store.EFFECT_FAILED
    assert calls == ["notification", "hub"]
    assert result.reason == "TimeoutError: applicant notification is pending"
    effects = result.doc["resolution_effects"]
    assert effects["notification"]["state"] == "failed"
    assert effects["hub"]["state"] == "requested"
    assert effects["complete"] is False


def test_resolution_effects_skip_a_known_missing_thread_instead_of_retrying(monkeypatch):
    """thread_missing is set by the GuildThreadDeleteEvent listener in
    handlers.py. Effects that need the gone thread must be marked skipped
    (with an audit note) and the whole pipeline must still complete --
    never retried every 60s, per the P1 fix for a deleted candidate thread.
    """
    ticket = _effect_ticket()
    ticket["thread_missing"] = {"thread_role": "candidate"}

    class Rest:
        def __init__(self):
            self.edits = []

        async def fetch_channel(self, channel_id):
            if channel_id == 101:
                raise hikari.NotFoundError(
                    url="", headers={}, raw_body=b"", code=10003
                )
            return SimpleNamespace(id=channel_id, is_archived=False, is_locked=False)

        async def edit_channel(self, channel_id, **kwargs):
            self.edits.append((channel_id, kwargs))

    rest = Rest()
    mongo = _mongo(ticket)

    async def acquire(received_mongo, *_args, **_kwargs):
        return await store.find_one(
            received_mongo, {"_id": ticket["_id"], **store.RUNTIME_FILTER}
        )

    async def release(*_args, **_kwargs):
        return None

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.outcome == store.WON
    assert result.doc["resolution_effects"]["complete"] is True
    # A decision never archives or locks either thread, missing or not.
    assert rest.edits == []
    audit_events = [entry["event"] for entry in result.doc["audit"]]
    assert "resolution_notification_skipped" in audit_events


@pytest.mark.parametrize("order", [("candidate", "staff"), ("staff", "candidate")])
def test_thread_missing_records_both_roles_regardless_of_mark_order(monkeypatch, order):
    """A candidate-thread deletion followed by a staff-thread deletion (or
    the reverse) must record both facts, not lose the first one:
    `thread_missing.roles` accumulates additively. Once "candidate" is
    recorded the ticket must leave the open authority set (it must not keep
    re-claiming/re-backfilling its own slot), and once each role is
    recorded the resolution effect that needs that now-gone thread must be
    skipped rather than retried forever -- regardless of mark order.
    """
    # -- both roles accumulate in thread_missing.roles, in either order --
    open_ticket = _ticket(status="open")
    mongo = _mongo(open_ticket)
    for role in order:
        result = asyncio.run(store.mark_thread_missing(
            mongo, open_ticket["_id"], thread_role=role,
        ))
        assert result.won
    stored = mongo.tickets.documents[open_ticket["_id"]]
    assert set(stored["thread_missing"]["roles"]) == {"candidate", "staff"}
    # thread_role stays the first-recorded role, for compatibility.
    assert stored["thread_missing"]["thread_role"] == order[0]

    # -- out of the open authority set --
    authoritative = asyncio.run(
        ticket_runtime._open_authoritative_tickets(mongo, limit=25)
    )
    assert authoritative == []

    # -- both resolution-effect kinds are skipped, not retried --
    effect_ticket = _effect_ticket()
    effect_ticket["resolution_effects"]["staff_context"] = {"state": "pending"}
    effect_mongo = _mongo(effect_ticket)
    marked = None
    for role in order:
        marked = asyncio.run(store.mark_thread_missing(
            effect_mongo, effect_ticket["_id"], thread_role=role,
        ))
        assert marked.won

    class Rest:
        async def fetch_channel(self, _channel_id):
            raise hikari.NotFoundError(url="", headers={}, raw_body=b"", code=10003)

        async def edit_channel(self, *_args, **_kwargs):
            return None

    rest = Rest()

    async def acquire(received_mongo, *_args, **_kwargs):
        return await store.find_one(
            received_mongo, {"_id": effect_ticket["_id"], **store.RUNTIME_FILTER}
        )

    async def release(*_args, **_kwargs):
        return None

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve, "_acquire_resolution_effect_lease", acquire)
    monkeypatch.setattr(resolve, "_release_resolution_effect_lease", release)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), effect_mongo, marked.doc,
    ))

    assert result.outcome == store.WON
    assert result.doc["resolution_effects"]["complete"] is True
    audit_events = [entry["event"] for entry in result.doc["audit"]]
    assert "resolution_notification_skipped" in audit_events
    assert "resolution_staff_context_skipped" in audit_events


def test_notification_retry_reopens_only_to_write_and_stays_open(monkeypatch):
    ticket = _effect_ticket()
    ticket["resolution_effects"].update({
        "notification": {"state": "failed"},
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
    ]
    # The candidate thread was reopened to deliver the notice and stays
    # open -- nothing re-archives or re-locks it afterward.
    assert not rest.channels[101].is_archived
    assert not rest.channels[101].is_locked
    assert result.doc["resolution_effects"]["complete"] is True

    edits = list(rest.edits)
    again = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, result.doc
    ))
    assert again.won
    assert notices == [ticket["resolution_effects"]["marker"]]
    assert rest.edits == edits


@pytest.mark.parametrize("cancel_stage", ["before", "during", "after"])
def test_resolution_notification_cancellation_releases_and_resumes_once(
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
    # Cancellation must not archive or lock either thread. Only the
    # candidate thread was reopened to deliver the notice, and it stays
    # open; the staff thread is untouched by this path.
    assert not rest.channels[101].is_archived
    assert not rest.channels[101].is_locked
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
    assert not rest.channels[101].is_archived
    assert not rest.channels[101].is_locked


def test_checkpoint_effect_caps_audit_at_max_entries():
    """`audit` is unbounded per-action history on a collection with no TTL
    (store.MAX_AUDIT_ENTRIES); every $push into it must slice to that bound,
    including the resolution-effect checkpoint pushes.
    """
    ticket = _effect_ticket()
    mongo = _mongo(ticket)
    marker = ticket["resolution_effects"]["marker"]

    for i in range(250):
        matched = asyncio.run(resolve._checkpoint_effect(
            mongo, ticket["_id"], marker,
            step="notification", state=f"attempt_{i}",
        ))
        assert matched

    audit = mongo.tickets.documents[ticket["_id"]]["audit"]
    assert len(audit) == store.MAX_AUDIT_ENTRIES
    assert audit[-1]["event"] == "resolution_notification_attempt_249"


def test_hub_retry_finds_marker_and_never_duplicates_notification(monkeypatch):
    ticket = _effect_ticket()
    rest = EffectRest()
    sends = []
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

    async def refresh(*_args, **_kwargs):
        nonlocal hub_attempts
        hub_attempts += 1
        if hub_attempts == 1:
            raise TimeoutError("hub refresh response lost")
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
    assert hub_attempts == 2
    assert rest.fetch_channel_calls == [101]


@pytest.mark.parametrize("status,kind", [
    ("approved", resolve.KIND_APPROVE),
    ("denied", resolve.KIND_DENY_CUSTOM),
])
def test_approve_and_deny_effects_never_lock_or_archive_either_thread(
    monkeypatch, status, kind,
):
    """Owner decision, live smoke test 2026-09-09: approving/denying a
    ticket locked and archived both threads immediately, so nobody could
    see the notice or keep talking. The bot must never archive or lock a
    ticket thread because of a decision -- both threads stay open.
    """
    ticket = _ticket(status=status, source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "handled_by_name": "Recruiter",
        "resolution_effects": {
            "marker": f"ticket-resolution:{ticket['_id']}:1:{status}",
            "kind": kind,
            "notification": {"state": "pending"},
            "staff_context": {"state": "delivered"},
            "hub": {"state": "pending"},
            "complete": False,
        },
    })
    if kind != resolve.KIND_APPROVE:
        ticket["denial_type"] = "custom"
        ticket["denial_reason"] = "Not eligible"
    mongo = _mongo(ticket)
    rest = EffectRest()

    async def notification(*_args, marker, **_kwargs):
        rest.messages.append(SimpleNamespace(
            content=f"-# {marker}",
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.won
    assert not any(
        kwargs.get("archived") is True or kwargs.get("locked") is True
        for _channel_id, kwargs in rest.edits
    )


def test_overturn_unarchives_to_post_and_never_rearchives(monkeypatch):
    """Owner decision, live smoke test 2026-09-09: an overturn must be able
    to deliver its fresh decision card into a candidate thread Discord had
    already auto-archived -- unarchiving it to post, then leaving it open
    rather than re-archiving or re-locking it.
    """
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket.update({
        "handled_by_name": "Recruiter",
        "resolution_effects": {
            "marker": f"ticket-resolution:{ticket['_id']}:2:approved",
            "kind": resolve.KIND_APPROVE,
            "notification": {"state": "pending"},
            "staff_context": {"state": "delivered"},
            "hub": {"state": "pending"},
            "complete": False,
        },
    })
    mongo = _mongo(ticket)
    # Discord's own seven-day inactivity archive never locks a thread.
    rest = EffectRest(archived=True, locked=False)
    notices = []

    async def notification(*_args, marker, **_kwargs):
        notices.append(marker)
        rest.messages.append(SimpleNamespace(
            content=f"-# {marker}",
            components=[],
            author=SimpleNamespace(id=7),
        ))

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(resolve, "run_side_effects", notification)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    result = asyncio.run(resolve.process_resolution_effects(
        _effect_bot(rest), mongo, ticket
    ))

    assert result.won
    assert notices == [ticket["resolution_effects"]["marker"]]
    assert (101, {
        "archived": False,
        "reason": "Delivering an updated ticket decision",
    }) in rest.edits
    assert not any(
        kwargs.get("archived") is True or kwargs.get("locked") is True
        for _channel_id, kwargs in rest.edits
    )
    assert not rest.channels[101].is_archived
    assert not rest.channels[101].is_locked


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
        "type": "ticket_v2_deny_action",
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
            "type": "ticket_v2_deny_action",
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
            custom_id="ticket_v2_deny_custom:state",
            create_modal_response=create_modal_response,
        ),
    )

    asyncio.run(dispatcher._dispatch(ctx, SimpleNamespace()))

    assert len(modals) == 1
    assert modals[0]["custom_id"] == "ticket_v2_process_custom_denial:state"
    action = dispatcher.registered_functions["ticket_v2_deny_custom"]
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
            "type": "ticket_v2_deny_action",
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


def test_slash_approve_on_a_decided_ticket_names_the_decision_maker_no_overturn(
    monkeypatch,
):
    """Commit 2: /tickets never offers an overturn - only the console does."""
    ticket = _ticket(status="approved", source={"guild_id": 1, "channel_id": 2})
    ticket["approved_by_name"] = "Lead Recruiter"
    ticket["approved_at"] = NOW
    responses = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def find_by_location(_mongo, _channel_id):
        return deepcopy(ticket)

    async def approve(*_args, **_kwargs):
        return store.Transition(store.LOST, deepcopy(ticket))

    async def defer(**_kwargs):
        return None

    async def respond(content, **_kwargs):
        responses.append(content)

    monkeypatch.setattr(close.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(close.store, "find_by_location", find_by_location)
    monkeypatch.setattr(close.resolve, "approve_ticket", approve)

    ctx = SimpleNamespace(
        member=SimpleNamespace(id=1), user=SimpleNamespace(id=1, username="Recruiter"),
        channel_id=999, defer=defer, respond=respond,
    )
    asyncio.run(close.Approve.invoke._func(
        SimpleNamespace(), ctx, mongo=object(), bot=object(),
    ))

    assert len(responses) == 1
    assert "Already approved by Lead Recruiter" in responses[0]
    assert "Use the console to overturn" in responses[0]


def test_slash_deny_button_on_a_decided_ticket_names_the_decision_maker_no_overturn(
    monkeypatch,
):
    ticket = _ticket(status="denied", source={"guild_id": 1, "channel_id": 2})
    ticket["denied_by_name"] = "Other Recruiter"
    ticket["denied_at"] = NOW
    edits = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def deny(*_args, **_kwargs):
        return store.Transition(store.LOST, deepcopy(ticket))

    async def get(*_args, **_kwargs):
        return {
            "denier_id": 1,
            "ticket_id": ticket["_id"],
            "channel_id": 101,
            "user_id": 30,
        }

    async def delete(*_args, **_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    monkeypatch.setattr(close.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(close.resolve, "deny_ticket", deny)
    monkeypatch.setattr(close, "get_state", get)
    monkeypatch.setattr(close, "delete_state", delete)

    ctx = SimpleNamespace(
        member=SimpleNamespace(id=1), user=SimpleNamespace(id=1, username="Recruiter"),
        interaction=SimpleNamespace(edit_initial_response=edit_initial_response),
    )
    asyncio.run(close.deny_fwa_default_handler(
        ctx, "action", mongo=object(), bot=object(),
    ))

    assert len(edits) == 1
    assert "Already denied by Other Recruiter" in edits[0]["content"]
    assert edits[0]["components"] == []


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


def test_approval_message_tells_the_applicant_what_happens_next_and_how_to_return():
    """The old copy ("Stand by for further instructions.") was posted into a
    thread that is then locked, leaving the applicant with an instruction to
    wait with no way to act on it. The new copy must say what happens next
    and how to find the ticket again, and must not still say the old line."""
    sent = []

    class Rest:
        async def create_message(self, **kwargs):
            sent.append(kwargs)

    bot = SimpleNamespace(rest=Rest())
    ticket = {
        "venue": "thread",
        "location": {"id": 101},
        "user_id": 30,
    }

    asyncio.run(resolve.apply_approval(bot, SimpleNamespace(), ticket=ticket))

    assert len(sent) == 1
    content = sent[0]["content"]
    assert "A recruiter will contact you with your clan invite" in content
    assert "This ticket is now closed" in content
    assert "My ticket" in content
    assert "Stand by for further instructions" not in content


def test_custom_denial_modal_label_matches_the_console_wording(monkeypatch):
    """The slash-command deny modal and the console's overturn-deny modal
    must show the applicant-facing field the same way: "Reason shown to the
    applicant", not the old "Denial Reason"."""
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
            custom_id="ticket_v2_deny_custom:state",
            create_modal_response=create_modal_response,
        ),
    )

    asyncio.run(dispatcher._dispatch(ctx, SimpleNamespace()))

    assert len(modals) == 1
    field = modals[0]["components"][0].components[0]
    assert field.label == "Reason shown to the applicant"
    assert field.custom_id == "denial_reason"


def test_hub_payload_produces_chart_counts_from_real_documents(monkeypatch):
    """`_hub_payload` wires `store.list_open`, `store.console_counts`, and
    `flag_store.count_active` together against real Mongo-shaped documents
    -- `_hub_payload` itself is never stubbed here. Only the PNG rendering
    step is replaced, since pixel output is not what this test pins."""

    def _doc(number, *, ticket_type, status, source=None):
        document = schema.new_ticket_document(
            ticket_type=ticket_type,
            ticket_number=number,
            guild_id=10,
            public_thread_id=100 + number,
            public_parent_id=20,
            staff_thread_id=200 + number,
            staff_parent_id=21,
            user_id=1000 + number,
            username=f"Applicant {number}",
            created_at=NOW,
            status=status,
            source=source,
        )
        document["runtime"] = ticket_runtime.THREAD_RUNTIME
        return document

    legacy_source = {"guild_id": 10, "channel_id": 999}
    tickets = [
        _doc(1, ticket_type="main", status="open"),
        _doc(2, ticket_type="main", status="open"),
        _doc(3, ticket_type="fwa", status="open"),
        _doc(4, ticket_type="main", status="approved", source=legacy_source),
        _doc(5, ticket_type="fwa", status="denied", source=legacy_source),
    ]
    flags = [
        {"_id": "flag_a", "kind": flag_store.FLAG_BLACKLISTED, "active": True},
        {"_id": "flag_b", "kind": flag_store.FLAG_BLACKLISTED, "active": True},
        {"_id": "flag_c", "kind": flag_store.FLAG_DENIED_BEFORE, "active": True},
        {"_id": "flag_d", "kind": flag_store.FLAG_DENIED_BEFORE, "active": False},
    ]
    mongo = SimpleNamespace(
        tickets=Collection(tickets),
        ticket_flags=Collection(flags),
    )

    captured = []

    async def fake_render(counts):
        captured.append(counts)
        return b"png"

    monkeypatch.setattr(console, "render_overview", fake_render)

    components = asyncio.run(console._hub_payload(mongo))

    assert len(captured) == 1
    overview = captured[0]
    assert overview.statuses == {"open": 3, "approved": 1, "denied": 1}
    assert overview.by_type["main"] == {"open": 2, "approved": 1, "denied": 0}
    assert overview.by_type["fwa"] == {"open": 1, "approved": 0, "denied": 1}
    assert overview.flags == {
        flag_store.FLAG_BLACKLISTED: 2,
        flag_store.FLAG_DENIED_BEFORE: 1,
        flag_store.FLAG_NOT_LOYAL: 0,
    }

    container, _attachments = components[0].build()
    select = container["components"][1]["components"][0]
    assert len(select["options"]) == 3


def test_search_identity_field_names_match_what_schema_writes():
    """`_search_identity`'s query must reference the exact field names
    `schema.py` actually writes onto a ticket document -- a rename on
    either side does not raise, it just silently returns zero rows, so this
    pins both sides against each other."""
    document = schema.new_ticket_document(
        ticket_type="main", ticket_number=1, guild_id=10,
        public_thread_id=101, public_parent_id=20,
        staff_thread_id=102, staff_parent_id=21,
        user_id=30, username="Applicant",
        player_tags=("abc123",), created_at=NOW,
    )
    written_fields = set(document)

    discord_id_query = store._search_identity("223456789012345678")
    assert set(discord_id_query) == {"user_id"}
    assert set(discord_id_query) <= written_fields

    username_query = store._search_identity("Applicant")
    assert set(username_query) == {"username_search"}
    assert set(username_query) <= written_fields

    tag_query = store._search_identity("#ABC123")
    tag_fields = {name for clause in tag_query["$or"] for name in clause}
    assert tag_fields == {"player_tags", "mentioned_tags", "player_tag", "tag"}
    # `tag` alone is a legacy-only fallback kept for rows written before this
    # schema and is not something `new_ticket_document` writes; every other
    # branch here must be a field the current schema actually writes.
    assert (tag_fields - {"tag"}) <= written_fields
