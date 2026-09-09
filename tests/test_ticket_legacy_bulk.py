import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands.tickets import legacy_bulk, legacy_migration


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(legacy_bulk, "utcnow", lambda: NOW)


def _channel(channel_id, name, *, parent_id=0, ctype=hikari.ChannelType.GUILD_TEXT):
    return SimpleNamespace(id=channel_id, name=name, parent_id=parent_id, type=ctype)


class FakeSetup:
    def __init__(self, documents):
        self.documents = {doc["_id"]: dict(doc) for doc in documents}

    async def find_one(self, query):
        doc = self.documents.get(query.get("_id"))
        return dict(doc) if doc else None


class FakeMigrations:
    """mongo.ticket_migrations fake: legacy_bulk only ever calls find_one."""

    def __init__(self, documents=None):
        self.documents = {key: dict(value) for key, value in (documents or {}).items()}
        self.find_one_calls: list[str] = []

    async def find_one(self, query):
        self.find_one_calls.append(query.get("_id"))
        doc = self.documents.get(query.get("_id"))
        return dict(doc) if doc else None


def _clause_matches(document: dict, clause: dict) -> bool:
    for key, condition in clause.items():
        value = document.get(key)
        if isinstance(condition, dict):
            if "$exists" in condition and (key in document) != condition["$exists"]:
                return False
            if "$lte" in condition and (value is None or value > condition["$lte"]):
                return False
        elif value != condition:
            return False
    return True


class FakeBatches:
    """mongo.ticket_migration_batches fake with the CAS semantics legacy_bulk relies on."""

    def __init__(self, document=None):
        self.document = dict(document) if document else None

    async def find_one(self, query):
        if self.document and self.document.get("_id") == query.get("_id"):
            return deepcopy(self.document)
        return None

    async def find_one_and_update(self, query, update, *, upsert=False, return_document=None):
        if self.document is None:
            if not upsert:
                return None
            self.document = {"_id": query["_id"], "revision": 0}
        plain = {key: value for key, value in query.items() if key != "$or"}
        if not _clause_matches(self.document, plain):
            return None
        if "$or" in query and not any(
            _clause_matches(self.document, clause) for clause in query["$or"]
        ):
            return None
        for key, value in update.get("$set", {}).items():
            self.document[key] = deepcopy(value)
        for key, amount in update.get("$inc", {}).items():
            self.document[key] = int(self.document.get(key, 0)) + int(amount)
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        return deepcopy(self.document)


def _ready(channel_id, ticket_type="main", status="pending"):
    return {
        "channel_id": channel_id,
        "channel_name": f"ticket-{channel_id}",
        "classification": legacy_bulk.CLASS_READY,
        "detail": "",
        "ticket_type": ticket_type,
        "status": status,
    }


def _skip(channel_id, classification):
    return {
        "channel_id": channel_id,
        "channel_name": f"ticket-{channel_id}",
        "classification": classification,
        "detail": "skip",
        "ticket_type": None,
        "status": "skipped",
    }


def _batch_document(guild_id, entries, **overrides):
    document = {
        "_id": legacy_bulk._batch_id(guild_id),
        "kind": "legacy_migration_batch",
        "schema_version": 1,
        "source_guild_id": guild_id,
        "category_id": None,
        "attachments": "skip",
        "requested_limit": None,
        "state": "planned",
        "entries": entries,
        "counts": legacy_bulk._tally(entries),
        "consecutive_failures": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "planned_at": NOW,
        "revision": 0,
    }
    document.update(overrides)
    return document


CONFIG = {
    "_id": "config",
    "ticket_target_guild_id": 999,
    "main_candidate_parent": 20,
    "main_staff_parent": 21,
    "fwa_candidate_parent": 22,
    "fwa_staff_parent": 23,
}


def _mongo(*, migrations=None, batch=None, setup_docs=(CONFIG,)):
    return SimpleNamespace(
        ticket_setup=FakeSetup(list(setup_docs)),
        ticket_migrations=FakeMigrations(migrations),
        ticket_migration_batches=FakeBatches(batch),
    )


# ---------------------------------------------------------------------------
# build_plan: classification of a mixed channel list
# ---------------------------------------------------------------------------

def test_build_plan_classifies_a_mixed_channel_list(monkeypatch):
    channels = [
        _channel(1006, "✅main-6-frank"),
        _channel(1005, "✅main-5-erin"),
        _channel(1004, "✅main-4-dave"),
        _channel(1003, "🆕fwa-3-carol"),
        _channel(1002, "❌fwa-2-bob"),
        _channel(1001, "✅main-1-alice"),
        _channel(1000, "general-chat"),  # ignored: does not match the ticket pattern
    ]

    async def fetch_guild_channels(_guild_id):
        return channels

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    async def fake_preview(*, bot, mongo, request):
        channel_id = request.source_channel_id
        if channel_id in (1001, 1002):
            return SimpleNamespace()
        if channel_id == 1003:
            raise legacy_migration.LegacyTicketStillOpen("still open")
        if channel_id == 1004:
            raise legacy_migration.LegacyMigrationError(
                "the candidate Discord ID could not be detected; enter it in `user-id`"
            )
        if channel_id == 1005:
            raise legacy_migration.LegacyMigrationError(
                "the ticket type could not be detected; choose Main or FWA"
            )
        if channel_id == 1006:
            raise RuntimeError("boom")
        raise AssertionError(f"unexpected preview for {channel_id}")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)

    mongo = _mongo()
    document = asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=1, category_id=None,
        attachments="copy", limit=None,
    ))

    entries = {entry["channel_id"]: entry for entry in document["entries"]}
    assert set(entries) == {1001, 1002, 1003, 1004, 1005, 1006}
    assert entries[1001]["classification"] == legacy_bulk.CLASS_READY
    assert entries[1002]["classification"] == legacy_bulk.CLASS_READY
    assert entries[1003]["classification"] == legacy_bulk.CLASS_OPEN
    assert entries[1004]["classification"] == legacy_bulk.CLASS_NO_APPLICANT
    assert entries[1005]["classification"] == legacy_bulk.CLASS_AMBIGUOUS_TYPE
    assert entries[1006]["classification"] == "error:RuntimeError"

    # channel-id (oldest-first) ordering, regardless of the REST listing order
    assert [entry["channel_id"] for entry in document["entries"]] == [
        1001, 1002, 1003, 1004, 1005, 1006,
    ]


def test_build_plan_document_shape(monkeypatch):
    async def fetch_guild_channels(_guild_id):
        return [_channel(2001, "✅main-1-alice")]

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    async def fake_preview(*, bot, mongo, request):
        return SimpleNamespace()

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)

    mongo = _mongo()
    document = asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=42, category_id=None,
        attachments="copy", limit=5,
    ))

    assert document["_id"] == "batch:42"
    assert document["state"] == "planned"
    assert document["source_guild_id"] == 42
    assert document["attachments"] == "copy"
    assert document["requested_limit"] == 5
    assert document["counts"] == {legacy_bulk.CLASS_READY: 1}
    assert document["revision"] >= 1
    assert len(document["entries"]) == 1
    entry = document["entries"][0]
    assert set(entry) == {
        "channel_id", "channel_name", "classification", "detail", "ticket_type", "status",
    }


def test_build_plan_skips_already_copied_channels_without_previewing(monkeypatch):
    async def fetch_guild_channels(_guild_id):
        return [_channel(3001, "✅main-1-alice")]

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    async def fail_preview(*_args, **_kwargs):
        raise AssertionError("already-copied channels must not be previewed again")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fail_preview)

    migration_id = legacy_migration._migration_id(7, 3001)
    mongo = _mongo(migrations={migration_id: {"_id": migration_id, "state": "complete"}})

    document = asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=7, category_id=None,
        attachments="copy", limit=None,
    ))

    entry = document["entries"][0]
    assert entry["classification"] == legacy_bulk.CLASS_ALREADY_COPIED
    assert mongo.ticket_migrations.find_one_calls == [migration_id]


# ---------------------------------------------------------------------------
# run_batch
# ---------------------------------------------------------------------------

def _patch_migration_cycle(monkeypatch, *, failing_ids=frozenset(), calls=None):
    preview_calls = calls if calls is not None else []

    async def fake_preview(*, bot, mongo, request):
        preview_calls.append(request.source_channel_id)
        return SimpleNamespace(request=request)

    async def fake_migrate(*, bot, mongo, preview):
        channel_id = preview.request.source_channel_id
        if channel_id in failing_ids:
            raise RuntimeError(f"boom-{channel_id}")
        return legacy_migration.LegacyMigrationResult(
            ticket={"_id": f"ticket_{channel_id}", "ticket_number": channel_id},
            migration={},
            resumed=False,
        )

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    monkeypatch.setattr(legacy_migration, "migrate_legacy_ticket", fake_migrate)
    return preview_calls


def test_run_batch_processes_only_ready_entries_in_order_and_respects_limit(monkeypatch):
    _patch_migration_cycle(monkeypatch)
    entries = [_ready(2001), _skip(2002, legacy_bulk.CLASS_OPEN), _ready(2003), _ready(2005)]
    batch = _batch_document(11, entries, state="planned")
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    document = asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=11, guild_name="Legacy One",
        limit=2, actor_id=1, actor_name="Admin",
    ))

    statuses = {entry["channel_id"]: entry["status"] for entry in document["entries"]}
    assert statuses[2001] == "done"
    assert statuses[2003] == "done"
    assert statuses[2005] == "pending"
    assert document["state"] == "running"
    assert "lease_owner" not in document


def test_run_batch_resumes_and_skips_done_entries(monkeypatch):
    calls = _patch_migration_cycle(monkeypatch)
    entries = [_ready(2001), _skip(2002, legacy_bulk.CLASS_OPEN), _ready(2003), _ready(2005)]
    batch = _batch_document(11, entries, state="planned")
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=11, guild_name="Legacy One",
        limit=2, actor_id=1, actor_name="Admin",
    ))
    assert calls == [2001, 2003]

    document = asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=11, guild_name="Legacy One",
        limit=None, actor_id=1, actor_name="Admin",
    ))

    # 2001 and 2003 were not previewed a second time.
    assert calls == [2001, 2003, 2005]
    statuses = {entry["channel_id"]: entry["status"] for entry in document["entries"]}
    assert statuses == {2001: "done", 2002: "skipped", 2003: "done", 2005: "done"}
    assert document["state"] == "complete"


def test_run_batch_marks_failures_and_stops_after_ten_consecutive(monkeypatch):
    failing_ids = frozenset(range(3001, 3013))
    _patch_migration_cycle(monkeypatch, failing_ids=failing_ids)
    entries = [_ready(channel_id) for channel_id in range(3001, 3013)]  # twelve ready entries
    batch = _batch_document(12, entries, state="planned")
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    document = asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=12, guild_name="Legacy Two",
        limit=None, actor_id=1, actor_name="Admin",
    ))

    assert document["state"] == "paused"
    statuses = [entry["status"] for entry in document["entries"]]
    failed = [status for status in statuses if status.startswith("failed:")]
    pending = [status for status in statuses if status == "pending"]
    assert len(failed) == legacy_bulk.CONSECUTIVE_FAILURE_LIMIT
    assert len(pending) == 2


def test_run_batch_refuses_a_second_runner_while_the_lease_is_held(monkeypatch):
    _patch_migration_cycle(monkeypatch)
    entries = [_ready(4001)]
    batch = _batch_document(
        13, entries, state="running",
        lease_owner="someone-else", lease_until=NOW + timedelta(minutes=5),
    )
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    with pytest.raises(legacy_bulk.BulkMigrationError, match="already in progress"):
        asyncio.run(legacy_bulk.run_batch(
            bot=bot, mongo=mongo, source_guild_id=13, guild_name="Legacy Three",
            limit=None, actor_id=1, actor_name="Admin",
        ))


def test_run_batch_requires_a_plan_first():
    mongo = _mongo(batch=None)
    bot = SimpleNamespace(rest=SimpleNamespace())

    with pytest.raises(legacy_bulk.BulkMigrationError, match="dry run"):
        asyncio.run(legacy_bulk.run_batch(
            bot=bot, mongo=mongo, source_guild_id=14, guild_name="Legacy Four",
            limit=None, actor_id=1, actor_name="Admin",
        ))


def test_run_batch_refuses_a_stale_plan():
    entries = [_ready(5001)]
    batch = _batch_document(
        15, entries, state="planned", planned_at=NOW - timedelta(hours=25),
    )
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    with pytest.raises(legacy_bulk.BulkMigrationError, match="24 hours"):
        asyncio.run(legacy_bulk.run_batch(
            bot=bot, mongo=mongo, source_guild_id=15, guild_name="Legacy Five",
            limit=None, actor_id=1, actor_name="Admin",
        ))


# ---------------------------------------------------------------------------
# legacy_migration._identity fallback via the legacy welcome message
# ---------------------------------------------------------------------------

def test_identity_fallback_reads_the_bot_welcome_message_mention():
    class Rest:
        def __init__(self):
            self.fetch_member_calls: list[tuple[int, int]] = []

        async def fetch_member(self, guild_id, user_id):
            self.fetch_member_calls.append((guild_id, user_id))
            return SimpleNamespace(username="ghost", display_name="Ghost")

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    source_channel = SimpleNamespace(name="✅main-9-oldname", permission_overwrites={})
    messages = [
        SimpleNamespace(author=SimpleNamespace(id=999), content="unrelated bot chatter"),
        SimpleNamespace(
            author=SimpleNamespace(id=999),
            content="<@555> Welcome! Thank you for your interest!",
        ),
    ]
    rest = Rest()

    user_id, username, display_name = asyncio.run(legacy_migration._identity(
        rest,
        source_ticket=None,
        source_channel=source_channel,
        request=request,
        bot_user_id=999,
        messages=messages,
    ))

    assert user_id == 555
    assert rest.fetch_member_calls == [(1, 555)]
    assert username == "ghost"
    assert display_name == "Ghost"


def test_identity_fallback_uses_the_channel_name_when_the_applicant_is_gone():
    class Rest:
        async def fetch_member(self, _guild_id, _user_id):
            raise hikari.NotFoundError(url="", headers={}, raw_body=b"", code=10007)

        async def fetch_user(self, _user_id):
            raise hikari.NotFoundError(url="", headers={}, raw_body=b"", code=10013)

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21, user_id_override=555,
    )
    source_channel = SimpleNamespace(name="✅main-9-oldname", permission_overwrites={})

    user_id, username, display_name = asyncio.run(legacy_migration._identity(
        Rest(),
        source_ticket=None,
        source_channel=source_channel,
        request=request,
        bot_user_id=999,
        messages=(),
    ))

    assert user_id == 555
    assert username == "oldname"
    assert display_name == "oldname"


# ---------------------------------------------------------------------------
# pilot cap bypass for confirmed bulk runs
# ---------------------------------------------------------------------------

def test_bulk_batch_id_bypasses_the_pilot_cap_and_logs(monkeypatch, caplog):
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)

    class Migrations:
        def __init__(self):
            self.inserted: dict | None = None

        async def find_one(self, _query):
            return None

        async def count_documents(self, _query):
            raise AssertionError("pilot count_documents should not run for a bulk batch")

        async def insert_one(self, document):
            self.inserted = dict(document)

    class Setup:
        async def find_one(self, query):
            assert query == {"_id": "config"}
            return {
                "_id": "config",
                "ticket_target_guild_id": 10,
                "legacy_migration_pilot_approved": False,
            }

        async def update_one(self, *_args, **_kwargs):
            raise AssertionError("pilot slot reservation should not run for a bulk batch")

        async def find_one_and_update(self, *_args, **_kwargs):
            raise AssertionError("pilot slot reservation should not run for a bulk batch")

    migrations = Migrations()
    mongo = SimpleNamespace(ticket_migrations=migrations, ticket_setup=Setup())

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21, bulk_batch_id="batch:1",
    )
    preview = legacy_migration.LegacyMigrationPreview(
        request=request,
        source_channel=SimpleNamespace(name="✅main-1-test", id=2),
        source_staff_thread=None,
        source_ticket=None,
        ticket_type="main",
        status="approved",
        user_id=7,
        username="tester",
        display_name="Tester",
        player_tags=(),
        created_at=NOW,
        original_ticket_number=1,
        public_message_count=0,
        staff_message_count=0,
        attachment_count=0,
        recruiter_role_id=40,
    )

    caplog.set_level(logging.INFO, logger="extensions.commands.tickets.legacy_migration")
    owner, document, resumed = asyncio.run(legacy_migration._claim_migration(mongo, preview))

    assert resumed is False
    assert owner
    assert migrations.inserted is not None
    assert "migration_pilot_cap_bypassed" in caplog.text
    assert "batch:1" in caplog.text
    assert "channel=2" in caplog.text


def test_single_ticket_request_without_bulk_batch_id_still_enforces_the_pilot_cap(monkeypatch):
    monkeypatch.setattr(legacy_migration, "_migration_index_ready", True)

    class Migrations:
        async def find_one(self, _query):
            return None

        async def count_documents(self, _query):
            return legacy_migration.PILOT_LIMIT

    mongo = SimpleNamespace(
        ticket_migrations=Migrations(),
        ticket_setup=FakeSetup([{
            "_id": "config",
            "ticket_target_guild_id": 10,
            "legacy_migration_pilot_approved": False,
        }]),
    )

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    preview = legacy_migration.LegacyMigrationPreview(
        request=request,
        source_channel=SimpleNamespace(name="✅main-1-test", id=2),
        source_staff_thread=None,
        source_ticket=None,
        ticket_type="main",
        status="approved",
        user_id=7,
        username="tester",
        display_name="Tester",
        player_tags=(),
        created_at=NOW,
        original_ticket_number=1,
        public_message_count=0,
        staff_message_count=0,
        attachment_count=0,
        recruiter_role_id=40,
    )

    with pytest.raises(legacy_migration.PilotLimitReached):
        asyncio.run(legacy_migration._claim_migration(mongo, preview))
