import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands.tickets import legacy_bulk, legacy_migration


@pytest.fixture(autouse=True)
def _no_run_sleep(monkeypatch):
    # The confirmed run pauses one second per ticket in production;
    # tests must not.
    from extensions.commands.tickets import legacy_bulk
    monkeypatch.setattr(legacy_bulk, "RUN_SLEEP_SECONDS", 0)


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
        "channel_id", "channel_name", "classification", "detail", "ticket_type",
        "ticket_status", "status",
    }


def test_build_plan_previews_an_applicant_name_with_log_as_a_substring(monkeypatch):
    async def fetch_guild_channels(_guild_id):
        return [_channel(2002, "fwa-7-catalog")]

    previewed = []

    async def fake_preview(*, bot, mongo, request):
        previewed.append(request.source_channel_id)
        return SimpleNamespace()

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    document = asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=_mongo(), source_guild_id=1, category_id=None,
        attachments="copy", limit=None,
    ))

    assert previewed == [2002]
    assert document["entries"][0]["classification"] == legacy_bulk.CLASS_READY


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


def test_run_batch_retries_a_failed_ready_entry_without_double_counting_progress(monkeypatch):
    attempts: dict[int, int] = {}

    async def preview(*, bot, mongo, request):
        return SimpleNamespace(request=request)

    async def migrate(*, bot, mongo, preview):
        channel_id = preview.request.source_channel_id
        attempts[channel_id] = attempts.get(channel_id, 0) + 1
        if channel_id == 2001 and attempts[channel_id] == 1:
            raise RuntimeError("transient failure")
        return legacy_migration.LegacyMigrationResult(
            ticket={"_id": f"ticket_{channel_id}", "ticket_number": channel_id},
            migration={}, resumed=False,
        )

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", preview)
    monkeypatch.setattr(legacy_migration, "migrate_legacy_ticket", migrate)
    mongo = _mongo(batch=_batch_document(11, [_ready(2001), _ready(2003)]))
    bot = SimpleNamespace(rest=SimpleNamespace())

    first = asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=11, guild_name="Legacy One",
        limit=None, actor_id=1, actor_name="Admin",
    ))
    assert first["state"] == "running"
    assert [entry["status"] for entry in first["entries"]] == [
        "failed:RuntimeError: transient failure", "done",
    ]

    second = asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=11, guild_name="Legacy One",
        limit=None, actor_id=1, actor_name="Admin",
    ))
    assert second["state"] == "complete"
    assert [entry["status"] for entry in second["entries"]] == ["done", "done"]
    assert attempts == {2001: 2, 2003: 1}


def test_run_batch_skips_applicants_deleted_since_the_plan_without_pausing(monkeypatch):
    _patch_migration_cycle(monkeypatch)
    deleted_ids = set(range(3001, 3013))

    async def preview(*, bot, mongo, request):
        if request.source_channel_id in deleted_ids:
            raise legacy_migration.DeletedApplicant("applicant account deleted")
        return SimpleNamespace(request=request)

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", preview)
    entries = [_ready(channel_id) for channel_id in range(3001, 3014)]
    mongo = _mongo(batch=_batch_document(12, entries, state="planned"))
    document = asyncio.run(legacy_bulk.run_batch(
        bot=SimpleNamespace(rest=SimpleNamespace()), mongo=mongo,
        source_guild_id=12, guild_name="Legacy Two",
        limit=None, actor_id=1, actor_name="Admin",
    ))
    assert document["state"] == "complete"
    assert document["counts"][legacy_bulk.CLASS_DELETED_APPLICANT] == 12
    assert all(entry["status"] == "skipped" for entry in document["entries"][:-1])
    assert document["entries"][-1]["status"] == "done"
    assert document["consecutive_failures"] == 0


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
# Progress logging and durable summaries (long dry runs and runs outlive a
# 15-minute interaction token; see docs/ticket-console-operations.md "Bulk
# legacy migration").
# ---------------------------------------------------------------------------

def test_build_plan_prints_progress_lines_every_ten_channels(monkeypatch, capsys):
    channels = [_channel(7000 + i, f"main-{i}-user{i}") for i in range(23)]

    async def fetch_guild_channels(_guild_id):
        return channels

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    async def fake_preview(*, bot, mongo, request):
        return SimpleNamespace()

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    monkeypatch.setattr(legacy_bulk, "PREVIEW_SLEEP_SECONDS", 0)

    mongo = _mongo()
    asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=77, category_id=None,
        attachments="copy", limit=None,
    ))

    out = capsys.readouterr().out
    assert "[Tickets] migrate_all_plan_start guild=77 candidates=23" in out
    assert "[Tickets] migrate_all_plan_progress guild=77 scanned=10/23 ready=10 problems=0" in out
    assert "[Tickets] migrate_all_plan_progress guild=77 scanned=20/23 ready=20 problems=0" in out
    assert "[Tickets] migrate_all_plan_done guild=77 scanned=23 ready=23 problems=0" in out


def test_build_plan_persists_a_partial_plan_when_interrupted_mid_scan(monkeypatch):
    channels = [_channel(8000 + i, f"main-{i}-user{i}") for i in range(23)]

    async def fetch_guild_channels(_guild_id):
        return channels

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))

    calls: list[int] = []

    async def fake_preview(*, bot, mongo, request):
        calls.append(request.source_channel_id)
        if len(calls) == 15:
            # Simulates the process dying mid-scan (a killed task, not a
            # classification failure -- those are caught and turned into
            # `error:` entries instead).
            raise asyncio.CancelledError()
        return SimpleNamespace()

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    monkeypatch.setattr(legacy_bulk, "PREVIEW_SLEEP_SECONDS", 0)

    mongo = _mongo()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(legacy_bulk.build_plan(
            bot=bot, mongo=mongo, source_guild_id=88, category_id=None,
            attachments="copy", limit=None,
        ))

    document = mongo.ticket_migration_batches.document
    assert document["state"] == "planning"
    assert len(document["entries"]) == 10
    assert document["counts"] == {legacy_bulk.CLASS_READY: 10}


def test_run_batch_prints_progress_lines_per_ticket(monkeypatch, capsys):
    _patch_migration_cycle(monkeypatch)
    entries = [_ready(9001), _ready(9002), _ready(9003)]
    batch = _batch_document(16, entries, state="planned")
    mongo = _mongo(batch=batch)
    bot = SimpleNamespace(rest=SimpleNamespace())

    asyncio.run(legacy_bulk.run_batch(
        bot=bot, mongo=mongo, source_guild_id=16, guild_name="Legacy Six",
        limit=None, actor_id=1, actor_name="Admin",
    ))

    out = capsys.readouterr().out
    assert "[Tickets] migrate_all_run_start guild=16 total=3" in out
    assert "[Tickets] migrate_all_run_progress guild=16 done=1 failed=0 skipped=0 total=3" in out
    assert "[Tickets] migrate_all_run_progress guild=16 done=2 failed=0 skipped=0 total=3" in out
    assert "[Tickets] migrate_all_run_progress guild=16 done=3 failed=0 skipped=0 total=3" in out
    assert "[Tickets] migrate_all_run_done guild=16 done=3 failed=0 skipped=0 total=3" in out


def test_post_console_summary_posts_an_unpinged_message_in_the_console_channel():
    posted = []

    async def create_message(channel_id, content, *, user_mentions=None):
        posted.append((channel_id, content, user_mentions))
        return SimpleNamespace(id=1)

    bot = SimpleNamespace(rest=SimpleNamespace(create_message=create_message))
    mongo = _mongo(setup_docs=(CONFIG, {"_id": "ticket_console_hub", "channel_id": 555}))

    asyncio.run(legacy_bulk._post_console_summary(bot=bot, mongo=mongo, text="the summary"))

    assert posted == [(555, "the summary", False)]


def test_long_summary_is_delivered_in_full_within_discord_limits():
    posted, replied = [], []
    text = "\n".join(f"• channel-{i} " + "🛡" * 120 for i in range(25))

    async def create_message(channel_id, content, *, user_mentions=None):
        assert len(content.encode("utf-16-le")) // 2 <= 2000
        assert user_mentions is False
        posted.append(content)

    class Ctx:
        async def respond(self, content, *, ephemeral=False):
            assert len(content.encode("utf-16-le")) // 2 <= 2000
            assert ephemeral
            replied.append(content)

    asyncio.run(legacy_bulk._finish_with_summary(
        ctx=Ctx(), bot=SimpleNamespace(rest=SimpleNamespace(create_message=create_message)),
        mongo=_mongo(setup_docs=(CONFIG, {"_id": "ticket_console_hub", "channel_id": 555})),
        source_guild_id=99, text=text,
    ))
    assert len(posted) > 1
    assert "".join(posted) == text
    assert replied == posted


def test_summary_chunks_handles_a_single_oversized_line():
    text = "🛡" * 2500
    chunks = legacy_bulk._summary_chunks(text)
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 2000 for chunk in chunks)


def test_post_console_summary_is_a_no_op_without_a_configured_console_channel():
    async def create_message(*_args, **_kwargs):
        raise AssertionError("must not post without a configured console channel")

    bot = SimpleNamespace(rest=SimpleNamespace(create_message=create_message))
    mongo = _mongo()  # no ticket_console_hub doc

    asyncio.run(legacy_bulk._post_console_summary(bot=bot, mongo=mongo, text="ignored"))


@pytest.mark.parametrize("error_type", [hikari.NotFoundError, hikari.UnauthorizedError])
def test_finish_with_summary_falls_back_to_the_console_post_on_a_dead_token(capsys, error_type):
    posted = []

    async def create_message(channel_id, content, *, user_mentions=None):
        posted.append((channel_id, content, user_mentions))
        return SimpleNamespace(id=1)

    bot = SimpleNamespace(rest=SimpleNamespace(create_message=create_message))
    mongo = _mongo(setup_docs=(CONFIG, {"_id": "ticket_console_hub", "channel_id": 555}))

    class DeadCtx:
        async def respond(self, *_args, **_kwargs):
            raise error_type(url="", headers={}, raw_body=b"", code=50027)

    asyncio.run(legacy_bulk._finish_with_summary(
        ctx=DeadCtx(), bot=bot, mongo=mongo, source_guild_id=99, text="the durable summary",
    ))

    assert posted == [(555, "the durable summary", False)]
    out = capsys.readouterr().out
    assert "[Tickets] migrate_all_reply_lost guild=99" in out


def test_finish_with_summary_replies_normally_when_the_token_is_alive():
    responded = []

    async def create_message(channel_id, content, *, user_mentions=None):
        return SimpleNamespace(id=1)

    bot = SimpleNamespace(rest=SimpleNamespace(create_message=create_message))
    mongo = _mongo(setup_docs=(CONFIG, {"_id": "ticket_console_hub", "channel_id": 555}))

    class LiveCtx:
        async def respond(self, text, *, ephemeral=False):
            responded.append((text, ephemeral))

    asyncio.run(legacy_bulk._finish_with_summary(
        ctx=LiveCtx(), bot=bot, mongo=mongo, source_guild_id=100, text="hi",
    ))

    assert responded == [("hi", True)]


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


@pytest.mark.parametrize("saved_identity", [False, True])
def test_identity_raises_deleted_applicant_when_the_applicant_account_is_gone(saved_identity):
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

    with pytest.raises(legacy_migration.DeletedApplicant):
        asyncio.run(legacy_migration._identity(
            Rest(),
            source_ticket=(
                {"user_id": 555, "username": "saved", "display_name": "Saved"}
                if saved_identity else None
            ),
            source_channel=source_channel,
            request=request,
            bot_user_id=999,
            messages=(),
        ))


def test_identity_fallback_reads_a_welcome_posted_by_a_deleted_non_bot_user():
    """Server 1: the welcome ping is posted by a now-deleted *user* account
    (``author.is_bot`` False), not the current bot -- any author qualifies.
    """
    class Rest:
        async def fetch_member(self, _guild_id, _user_id):
            raise hikari.NotFoundError(url="", headers={}, raw_body=b"", code=10007)

        async def fetch_user(self, _user_id):
            return SimpleNamespace(username="ghost", display_name="Ghost")

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    source_channel = SimpleNamespace(name="closed-0007", permission_overwrites={})
    messages = [
        SimpleNamespace(
            author=SimpleNamespace(id=0, is_bot=False, username="Deleted User"),
            content="<@555> Welcome! Thank you for your interest!",
        ),
    ]

    user_id, username, display_name = asyncio.run(legacy_migration._identity(
        Rest(),
        source_ticket=None,
        source_channel=source_channel,
        request=request,
        bot_user_id=999,
        messages=messages,
    ))

    assert user_id == 555
    assert username == "ghost"
    assert display_name == "Ghost"


def test_identity_fallback_reads_a_ticket_tool_welcome_with_an_embed_questionnaire():
    class Rest:
        async def fetch_member(self, _guild_id, _user_id):
            return SimpleNamespace(username="momspaghetti", display_name="Mom Spaghetti")

    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    source_channel = SimpleNamespace(name="momspaghetti", permission_overwrites={})
    messages = [
        SimpleNamespace(
            author=SimpleNamespace(id=596655147029790750, is_bot=True, username="Ticket Tool"),
            content="<@!555> Welcome to your \U0001F6E1 WARRIOR'S UNITED\U0001F6E1 Entry Ticket!!",
            embeds=[SimpleNamespace(title="Questionnaire", description="1) IGN? 2) TH level?")],
        ),
    ]

    user_id, username, display_name = asyncio.run(legacy_migration._identity(
        Rest(),
        source_ticket=None,
        source_channel=source_channel,
        request=request,
        bot_user_id=999,
        messages=messages,
    ))

    assert user_id == 555
    assert username == "momspaghetti"
    assert display_name == "Mom Spaghetti"


def test_welcome_message_applicant_id_falls_back_to_first_mention_without_welcome_word():
    messages = [
        SimpleNamespace(author=SimpleNamespace(id=1), content="no mention here"),
        SimpleNamespace(author=SimpleNamespace(id=1), content="<@777> please read the rules"),
    ]
    assert legacy_migration._welcome_message_applicant_id(
        messages, bot_user_id=999
    ) == 777


def test_leading_mention_id_uses_the_raw_leading_mention_not_unordered_parsed_ids():
    message = SimpleNamespace(
        content="<@111> Welcome! Please ask <@222> for help.",
        user_mentions_ids=[222, 111],
    )
    assert legacy_migration._leading_mention_id(message) == 111


# ---------------------------------------------------------------------------
# Follow-up: `not_a_ticket` classification (non-ticket channels swept up by
# the category/prefix match -- see docs/handoff-legacy-migration.md "How a
# channel is read")
# ---------------------------------------------------------------------------

def test_looks_like_non_ticket_channel_name_matches_the_observed_server_1_names():
    for name in (
        "mainclan-commands", "fwa-background-check", "mainclan-recruitment-process",
        "fwa-commands", "main-notes", "fwa-log", "main-rules", "fwa-info",
        "mainclan-general", "fwa-chat",
    ):
        assert legacy_migration._looks_like_non_ticket_channel_name(name) is True
    for name in (
        "main-1-alice", "main-42-chatty", "fwa-7-catalog",
        "main-applicant-chat", "fwa-candidate-info",
    ):
        assert legacy_migration._looks_like_non_ticket_channel_name(name) is False


def test_identity_raises_not_a_ticket_when_no_overwrite_and_no_mention_at_all():
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    source_channel = SimpleNamespace(name="mainclan-commands", permission_overwrites={})
    messages = [
        SimpleNamespace(author=SimpleNamespace(id=1), content="just chatting, no mention"),
    ]

    with pytest.raises(legacy_migration.NotALegacyTicketChannel):
        asyncio.run(legacy_migration._identity(
            SimpleNamespace(),
            source_ticket=None,
            source_channel=source_channel,
            request=request,
            bot_user_id=999,
            messages=messages,
        ))


def test_classify_maps_not_a_legacy_ticket_channel(monkeypatch):
    async def fake_preview(*, bot, mongo, request):
        raise legacy_migration.NotALegacyTicketChannel("not a ticket")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    classification, _detail, ticket_status = asyncio.run(
        legacy_bulk._classify(bot=SimpleNamespace(), mongo=SimpleNamespace(), request=request)
    )
    assert classification == legacy_bulk.CLASS_NOT_A_TICKET
    assert ticket_status is None


def test_classify_maps_deleted_applicant(monkeypatch):
    async def fake_preview(*, bot, mongo, request):
        raise legacy_migration.DeletedApplicant("applicant account deleted")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    classification, _detail, ticket_status = asyncio.run(
        legacy_bulk._classify(bot=SimpleNamespace(), mongo=SimpleNamespace(), request=request)
    )
    assert classification == legacy_bulk.CLASS_DELETED_APPLICANT
    assert ticket_status is None


def test_build_plan_classifies_non_ticket_channel_names_without_previewing():
    async def fetch_guild_channels(_guild_id):
        return [_channel(4001, "mainclan-commands")]

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))
    mongo = _mongo()

    document = asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=50, category_id=None,
        attachments="copy", limit=None,
    ))

    entry = document["entries"][0]
    assert entry["classification"] == legacy_bulk.CLASS_NOT_A_TICKET
    assert entry["status"] == "skipped"


def test_dry_run_summary_reports_the_not_a_ticket_count():
    entries = [
        legacy_bulk._entry(1, "main-1", legacy_bulk.CLASS_READY, "", "main", "approved"),
        legacy_bulk._entry(2, "mainclan-commands", legacy_bulk.CLASS_NOT_A_TICKET, "not a ticket", None),
        legacy_bulk._entry(3, "fwa-background-check", legacy_bulk.CLASS_NOT_A_TICKET, "not a ticket", None),
    ]
    document = _batch_document(9, entries)
    summary = legacy_bulk.dry_run_summary(document, guild_name="Legacy Nine")
    assert "**Not tickets:** `2`" in summary
    assert f"{legacy_bulk.CLASS_NOT_A_TICKET}: `2`" in summary


def test_dry_run_summary_reports_the_deleted_applicant_count():
    entries = [
        legacy_bulk._entry(1, "main-1", legacy_bulk.CLASS_READY, "", "main", "approved"),
        legacy_bulk._entry(
            2, "main-2", legacy_bulk.CLASS_DELETED_APPLICANT, "applicant account deleted", None,
        ),
    ]
    document = _batch_document(9, entries)
    summary = legacy_bulk.dry_run_summary(document, guild_name="Legacy Nine")
    assert "**Applicant account deleted:** `1`" in summary
    assert f"{legacy_bulk.CLASS_DELETED_APPLICANT}: `1`" in summary


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


# ---------------------------------------------------------------------------
# Follow-up: detection by category+prefix (handoff "How a channel is read")
# ---------------------------------------------------------------------------

def test_is_legacy_ticket_channel_detects_server_1_style_names_without_numbers():
    # Server 1's names carry no ticket number at all.
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(1, "main-frank"), ""
    ) is True
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(2, "fwa-carol"), ""
    ) is True
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(3, "mainclan-dave"), ""
    ) is True
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(4, "closed-0005"), ""
    ) is True
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(5, "✅--main-6-frank"), ""
    ) is True


def test_is_legacy_ticket_channel_detects_by_category_name_only():
    channel = _channel(6, "welcome-desk")
    assert legacy_migration._is_legacy_ticket_channel(channel, "Main Clan Tickets") is True
    assert legacy_migration._is_legacy_ticket_channel(channel, "FWA Tickets") is True
    assert legacy_migration._is_legacy_ticket_channel(channel, "Mainclan Tickets 2") is True
    assert legacy_migration._is_legacy_ticket_channel(channel, "General") is False


def test_is_legacy_ticket_channel_excludes_log_channels():
    assert legacy_migration._is_legacy_ticket_channel(
        _channel(7, "main-log"), "Main Clan Tickets"
    ) is False


def test_stripped_channel_name_drops_leading_emoji_dashes_and_spaces():
    assert legacy_migration._stripped_channel_name("✅ --main-6-frank") == "main-6-frank"


def test_infer_ticket_type_falls_back_to_category_name():
    assert legacy_migration._infer_ticket_type(
        None, "welcome-desk", None, category_name="FWA Tickets"
    ) == "fwa"
    assert legacy_migration._infer_ticket_type(
        None, "welcome-desk", None, category_name="Main Clan Tickets"
    ) == "main"
    with pytest.raises(legacy_migration.LegacyMigrationError, match="ticket type"):
        legacy_migration._infer_ticket_type(None, "welcome-desk", None, category_name="General")


# ---------------------------------------------------------------------------
# Follow-up: outcome inference from embed/message history
# ---------------------------------------------------------------------------

def _history_message(content="", embeds=(), timestamp=NOW):
    return SimpleNamespace(content=content, embeds=list(embeds), timestamp=timestamp)


def test_infer_status_detects_an_approval_embed():
    embed = SimpleNamespace(title="Welcome to the Family!", description="")
    assert legacy_migration._infer_status(
        None, "ticket-applicant", None, messages=[_history_message(embeds=[embed])]
    ) == "approved"


def test_infer_status_detects_a_denial_embed():
    embed = SimpleNamespace(title="Denied", description="")
    assert legacy_migration._infer_status(
        None, "ticket-applicant", None, messages=[_history_message(embeds=[embed])]
    ) == "denied"


def test_infer_status_defaults_to_closed_with_no_decision_note():
    detail = legacy_migration._infer_status_detail(
        None, "ticket-applicant", None,
        messages=[_history_message(content="just chatting")],
    )
    assert detail.status == "closed"
    assert detail.decision_note == "No decision recorded"
    assert detail.decided_at == NOW


# ---------------------------------------------------------------------------
# Follow-up: server 3/4 open-ticket import policy (owner rules #2-#3)
# ---------------------------------------------------------------------------

_SERVER_3 = 1194706934926946457
_SERVER_4 = 1078723854303756298


def test_server_3_open_ticket_imports_as_closed_no_decision():
    detail = legacy_migration._infer_status_detail(
        {"status": "open"}, "main-9-applicant", None, source_guild_id=_SERVER_3,
    )
    assert detail.status == "closed"
    assert detail.decision_note == "No decision recorded"


def test_server_4_open_ticket_still_refuses():
    with pytest.raises(legacy_migration.LegacyTicketStillOpen):
        legacy_migration._infer_status_detail(
            {"status": "open"}, "main-9-applicant", None, source_guild_id=_SERVER_4,
        )


def test_open_ticket_with_no_guild_policy_still_refuses():
    with pytest.raises(legacy_migration.LegacyTicketStillOpen):
        legacy_migration._infer_status({"status": "open"}, "main-9-applicant", None)


# ---------------------------------------------------------------------------
# Follow-up: skip the owner's test tickets (owner rule #4)
# ---------------------------------------------------------------------------

def test_is_owner_test_applicant_matches_id_or_username():
    assert legacy_migration._is_owner_test_applicant(505227988229554179, "whoever") is True
    assert legacy_migration._is_owner_test_applicant(1, "SirRuggie") is True
    assert legacy_migration._is_owner_test_applicant(1, "someone-else") is False


def test_authorized_owner_ticket_passes_the_owner_skip_gate():
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1024958361306927124,
        source_channel_id=1045185178437423114,
        target_guild_id=10, candidate_parent_id=20, staff_parent_id=21,
    )
    assert legacy_migration._skip_owner_test_ticket(
        request, 505227988229554179, "SirRuggie",
    ) is False


@pytest.mark.parametrize(
    ("source_guild_id", "source_channel_id", "user_id", "username"),
    [
        # The channel alone never grants the exception.
        (1, 1045185178437423114, 505227988229554179, "someone-else"),
        # The guild alone never grants the exception, including username match.
        (1024958361306927124, 2, 1, "SirRuggie"),
    ],
)
def test_other_owner_tickets_remain_blocked_by_the_owner_skip_gate(
    source_guild_id, source_channel_id, user_id, username,
):
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=source_guild_id, source_channel_id=source_channel_id,
        target_guild_id=10, candidate_parent_id=20, staff_parent_id=21,
    )
    assert legacy_migration._skip_owner_test_ticket(request, user_id, username) is True


def _owner_preview_request(source_guild_id, source_channel_id):
    return legacy_migration.LegacyMigrationRequest(
        source_guild_id=source_guild_id, source_channel_id=source_channel_id,
        target_guild_id=10, candidate_parent_id=20, staff_parent_id=21,
    )


def _owner_preview_bot(source_guild_id, source_channel_id):
    channel = SimpleNamespace(
        id=source_channel_id,
        guild_id=source_guild_id,
        name="main-sir-ruggie1500",
        type=hikari.ChannelType.GUILD_TEXT,
    )

    class Rest:
        async def fetch_guild(self, _guild_id):
            return SimpleNamespace()

        async def fetch_channel(self, channel_id):
            assert channel_id == source_channel_id
            return channel

    return SimpleNamespace(rest=Rest(), get_me=lambda: SimpleNamespace(id=999))


def _stub_owner_preview_inputs(monkeypatch):
    async def source_ticket(_mongo, _guild_id, _channel_id):
        return {"status": "approved"}

    async def messages(_rest, _channel_id):
        return []

    async def identity(*_args, **_kwargs):
        return 505227988229554179, "SirRuggie", "Sir Ruggie"

    monkeypatch.setattr(legacy_migration, "_legacy_source_ticket", source_ticket)
    monkeypatch.setattr(legacy_migration, "_all_messages", messages)
    monkeypatch.setattr(legacy_migration, "_identity", identity)


def test_preview_exact_owner_source_pair_passes_owner_gate_then_stays_abandoned(monkeypatch):
    """The exception only clears rule #4; rule #5 must still stop this ticket."""
    _stub_owner_preview_inputs(monkeypatch)
    request = _owner_preview_request(1024958361306927124, 1045185178437423114)

    with pytest.raises(legacy_migration.AbandonedLegacyTicket):
        asyncio.run(legacy_migration.preview_legacy_ticket(
            bot=_owner_preview_bot(request.source_guild_id, request.source_channel_id),
            mongo=SimpleNamespace(), request=request,
        ))


@pytest.mark.parametrize(
    ("source_guild_id", "source_channel_id"),
    [
        (1, 1045185178437423114),
        (1024958361306927124, 2),
    ],
)
def test_preview_near_match_owner_sources_still_raise_owner_skip(
    monkeypatch, source_guild_id, source_channel_id,
):
    _stub_owner_preview_inputs(monkeypatch)
    request = _owner_preview_request(source_guild_id, source_channel_id)

    with pytest.raises(legacy_migration.SkippedOwnerTestTicket):
        asyncio.run(legacy_migration.preview_legacy_ticket(
            bot=_owner_preview_bot(source_guild_id, source_channel_id),
            mongo=SimpleNamespace(), request=request,
        ))


def test_classify_maps_skipped_owner_test(monkeypatch):
    async def fake_preview(*, bot, mongo, request):
        raise legacy_migration.SkippedOwnerTestTicket("owner test ticket")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    classification, _detail, ticket_status = asyncio.run(
        legacy_bulk._classify(bot=SimpleNamespace(), mongo=SimpleNamespace(), request=request)
    )
    assert classification == legacy_bulk.CLASS_SKIPPED_OWNER_TEST
    assert ticket_status is None


# ---------------------------------------------------------------------------
# Follow-up: abandoned tickets skipped unless `include-abandoned` (owner rule #5)
# ---------------------------------------------------------------------------

def test_applicant_authored_a_message_checks_author_ids():
    messages = [
        SimpleNamespace(author=SimpleNamespace(id=1)),
        SimpleNamespace(author=SimpleNamespace(id=2)),
    ]
    assert legacy_migration._applicant_authored_a_message(messages, 2) is True
    assert legacy_migration._applicant_authored_a_message(messages, 3) is False


def test_classify_maps_abandoned_ticket(monkeypatch):
    async def fake_preview(*, bot, mongo, request):
        raise legacy_migration.AbandonedLegacyTicket("never wrote")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    request = legacy_migration.LegacyMigrationRequest(
        source_guild_id=1, source_channel_id=2, target_guild_id=10,
        candidate_parent_id=20, staff_parent_id=21,
    )
    classification, _detail, ticket_status = asyncio.run(
        legacy_bulk._classify(bot=SimpleNamespace(), mongo=SimpleNamespace(), request=request)
    )
    assert classification == legacy_bulk.CLASS_ABANDONED
    assert ticket_status is None


def test_build_plan_passes_include_abandoned_through_to_each_request(monkeypatch):
    async def fetch_guild_channels(_guild_id):
        return [_channel(6001, "✅main-1-alice")]

    bot = SimpleNamespace(rest=SimpleNamespace(fetch_guild_channels=fetch_guild_channels))
    captured = []

    async def fake_preview(*, bot, mongo, request):
        captured.append(request.include_abandoned)
        return SimpleNamespace(status="approved")

    monkeypatch.setattr(legacy_migration, "preview_legacy_ticket", fake_preview)
    mongo = _mongo()
    asyncio.run(legacy_bulk.build_plan(
        bot=bot, mongo=mongo, source_guild_id=6, category_id=None,
        attachments="copy", limit=None, include_abandoned=True,
    ))
    assert captured == [True]


# ---------------------------------------------------------------------------
# Follow-up: dry-run summary shows the new classifications and outcome counts
# ---------------------------------------------------------------------------

def test_dry_run_summary_reports_closed_no_decision_and_abandoned_counts():
    entries = [
        legacy_bulk._entry(1, "main-1", legacy_bulk.CLASS_READY, "", "main", "approved"),
        legacy_bulk._entry(2, "main-2", legacy_bulk.CLASS_READY, "", "main", "closed"),
        legacy_bulk._entry(3, "main-3", legacy_bulk.CLASS_ABANDONED, "never wrote", None),
        legacy_bulk._entry(4, "main-4", legacy_bulk.CLASS_SKIPPED_OWNER_TEST, "owner", None),
    ]
    document = _batch_document(9, entries)
    summary = legacy_bulk.dry_run_summary(document, guild_name="Legacy Nine")
    assert "closed, no decision: `1`" in summary
    assert "Abandoned (applicant never wrote):** `1`" in summary
    assert f"{legacy_bulk.CLASS_ABANDONED}: `1`" in summary
    assert f"{legacy_bulk.CLASS_SKIPPED_OWNER_TEST}: `1`" in summary
