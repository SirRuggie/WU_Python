import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.commands.fwa import lazy_cwl


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if expected.get("$type") == "string" and not isinstance(actual, str):
                return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return deepcopy(self.documents)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = {
            document["_id"]: deepcopy(document) for document in (documents or [])
        }
        self.find_queries = []
        self.updates = []
        self.indexes = []

    def find(self, query):
        self.find_queries.append(deepcopy(query))
        return FakeCursor([
            document for document in self.documents.values()
            if _matches(document, query)
        ])

    async def find_one(self, query):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    async def update_one(self, query, update):
        self.updates.append((deepcopy(query), deepcopy(update)))
        for document in self.documents.values():
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                for key in update.get("$unset", {}):
                    document.pop(key, None)
                for key, amount in update.get("$inc", {}).items():
                    document[key] = document.get(key, 0) + amount
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def update_many(self, query, update):
        modified = 0
        for document in self.documents.values():
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                modified += 1
        return SimpleNamespace(modified_count=modified)

    async def create_index(self, keys, **kwargs):
        self.indexes.append((deepcopy(keys), deepcopy(kwargs)))
        return kwargs["name"]


class FakeScheduler:
    def __init__(self, fail_add=False):
        self.add_calls = []
        self.removed = []
        self.shutdown_calls = []
        self.fail_add = fail_add

    def add_job(self, function, **kwargs):
        if self.fail_add:
            raise RuntimeError("scheduler unavailable")
        self.add_calls.append((function, kwargs))

    def remove_job(self, job_id):
        self.removed.append(job_id)

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


def test_next_run_preserves_future_cadence_and_skips_missed_intervals():
    anchor = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    snapshot = {
        "last_auto_ping_at": anchor,
        "auto_ping_interval_minutes": 60,
    }

    assert lazy_cwl.calculate_next_autoping_run(
        snapshot,
        datetime(2026, 8, 4, 12, 25, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc)
    assert lazy_cwl.calculate_next_autoping_run(
        snapshot,
        datetime(2026, 8, 4, 14, 5, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)


def test_next_run_uses_start_time_before_first_check():
    snapshot = {
        "auto_ping_started_at": datetime(2026, 8, 4, 12, 0),
        "last_auto_ping_at": None,
        "auto_ping_interval_minutes": 30,
    }

    assert lazy_cwl.calculate_next_autoping_run(
        snapshot,
        datetime(2026, 8, 4, 12, 10, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)


def test_snapshot_invariants_repair_stale_and_duplicate_rows():
    older = datetime(2026, 8, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 8, 2, tzinfo=timezone.utc)
    collection = FakeCollection([
        {
            "_id": "inactive",
            "clan_tag": "#OLD",
            "active": False,
            "auto_ping_enabled": True,
        },
        {
            "_id": "older",
            "clan_tag": "#abc",
            "snapshot_date": older,
            "active": True,
            "auto_ping_enabled": True,
        },
        {
            "_id": "newer",
            "clan_tag": "#ABC",
            "snapshot_date": newer,
            "active": True,
            "auto_ping_enabled": False,
        },
    ])
    mongo = SimpleNamespace(lazy_cwl_snapshots=collection)

    asyncio.run(lazy_cwl.ensure_snapshot_invariants(mongo))

    assert collection.documents["inactive"]["auto_ping_enabled"] is False
    assert collection.documents["older"]["active"] is False
    assert collection.documents["older"]["auto_ping_enabled"] is False
    assert collection.documents["newer"]["active"] is True
    assert collection.documents["newer"]["clan_tag"] == "#ABC"
    assert collection.indexes == [
        (
            [("clan_tag", 1)],
            {
                "name": lazy_cwl.ACTIVE_SNAPSHOT_INDEX,
                "unique": True,
                "partialFilterExpression": {
                    "active": True,
                    "clan_tag": {"$type": "string"},
                },
            },
        )
    ]


def test_concurrent_snapshot_insert_is_reported_as_already_existing():
    existing_date = datetime(2026, 8, 4, tzinfo=timezone.utc)

    class DuplicateCollection(FakeCollection):
        async def insert_one(self, document):
            raise lazy_cwl.DuplicateKeyError("duplicate active clan")

    collection = DuplicateCollection([{
        "_id": "winner",
        "clan_tag": "#ABC",
        "clan_name": "Clan",
        "snapshot_date": existing_date,
        "active": True,
    }])
    mongo = SimpleNamespace(lazy_cwl_snapshots=collection)

    class FakeCocClient:
        async def get_clan(self, clan_tag):
            return SimpleNamespace(name="Clan", members=[])

    result = asyncio.run(lazy_cwl.process_single_clan_snapshot(
        "#abc", 123, FakeCocClient(), mongo
    ))

    assert result["success"] is False
    assert result["already_exists"] is True
    assert result["clan_tag"] == "#ABC"
    assert result["existing_date"] == "August 04, 2026 at 12:00 AM UTC"


def test_restore_uses_only_active_enabled_rows_and_persisted_cadence(monkeypatch):
    now = datetime.now(timezone.utc)
    collection = FakeCollection([
        {
            "_id": "active",
            "clan_name": "Active Clan",
            "active": True,
            "auto_ping_enabled": True,
            "auto_ping_started_at": now - timedelta(hours=1),
            "last_auto_ping_at": now - timedelta(minutes=10),
            "auto_ping_interval_minutes": 30,
        },
        {
            "_id": "inactive",
            "clan_name": "Inactive Clan",
            "active": False,
            "auto_ping_enabled": True,
            "auto_ping_started_at": now - timedelta(hours=1),
        },
    ])
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        lazy_cwl,
        "mongo_client",
        SimpleNamespace(lazy_cwl_snapshots=collection),
    )
    monkeypatch.setattr(lazy_cwl, "scheduler", scheduler)

    asyncio.run(lazy_cwl.restore_autopings())

    assert collection.find_queries == [{
        "active": True,
        "auto_ping_enabled": True,
    }]
    assert len(scheduler.add_calls) == 1
    _, kwargs = scheduler.add_calls[0]
    assert kwargs["id"] == "autopings_active"
    assert kwargs["next_run_time"] > now
    assert kwargs["next_run_time"] == lazy_cwl.calculate_next_autoping_run(
        collection.documents["active"], now=kwargs["next_run_time"] - timedelta(minutes=20)
    )
    assert kwargs["coalesce"] is True
    assert kwargs["max_instances"] == 1
    assert kwargs["misfire_grace_time"] == 300


def test_auto_ping_count_increments_only_when_a_message_was_sent(monkeypatch):
    snapshot = {
        "_id": "snapshot",
        "clan_name": "Clan",
        "active": True,
        "auto_ping_enabled": True,
    }
    collection = FakeCollection([snapshot])
    mongo = SimpleNamespace(lazy_cwl_snapshots=collection)
    scheduler = FakeScheduler()
    results = iter([
        {
            "success": True,
            "clan_name": "Clan",
            "all_present": True,
            "missing_count": 0,
            "total_count": 1,
        },
        {
            "success": True,
            "clan_name": "Clan",
            "all_present": False,
            "missing_count": 1,
            "total_count": 1,
        },
    ])

    async def fake_ping(*args):
        return next(results)

    monkeypatch.setattr(lazy_cwl, "mongo_client", mongo)
    monkeypatch.setattr(lazy_cwl, "scheduler", scheduler)
    monkeypatch.setattr(lazy_cwl, "bot_instance", SimpleNamespace())
    monkeypatch.setattr(lazy_cwl, "coc_client", SimpleNamespace())
    monkeypatch.setattr(lazy_cwl, "process_single_snapshot_ping", fake_ping)

    asyncio.run(lazy_cwl.auto_ping_job("snapshot"))
    assert collection.documents["snapshot"].get("auto_ping_count", 0) == 0
    assert collection.documents["snapshot"].get("last_auto_ping_at") is not None

    asyncio.run(lazy_cwl.auto_ping_job("snapshot"))
    assert collection.documents["snapshot"]["auto_ping_count"] == 1


def test_autoping_job_clears_stale_enabled_flag_on_inactive_snapshot(monkeypatch):
    collection = FakeCollection([{
        "_id": "snapshot",
        "clan_name": "Clan",
        "active": False,
        "auto_ping_enabled": True,
    }])
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        lazy_cwl,
        "mongo_client",
        SimpleNamespace(lazy_cwl_snapshots=collection),
    )
    monkeypatch.setattr(lazy_cwl, "scheduler", scheduler)
    monkeypatch.setattr(lazy_cwl, "bot_instance", SimpleNamespace())
    monkeypatch.setattr(lazy_cwl, "coc_client", SimpleNamespace())

    asyncio.run(lazy_cwl.auto_ping_job("snapshot"))

    assert collection.documents["snapshot"]["auto_ping_enabled"] is False
    assert scheduler.removed == ["autopings_snapshot"]


def test_reset_clears_active_and_autoping_flags():
    collection = FakeCollection([{
        "_id": "snapshot",
        "clan_name": "Clan",
        "clan_tag": "#TAG",
        "players": [],
        "active": True,
        "auto_ping_enabled": True,
    }])
    mongo = SimpleNamespace(lazy_cwl_snapshots=collection)
    scheduler = FakeScheduler()

    result = asyncio.run(lazy_cwl.process_single_snapshot_reset(
        "snapshot", mongo, scheduler
    ))

    assert result["success"] is True
    assert collection.documents["snapshot"]["active"] is False
    assert collection.documents["snapshot"]["auto_ping_enabled"] is False
    assert scheduler.removed == ["autopings_snapshot"]


def test_shutdown_stops_scheduler_once_and_clears_global(monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(lazy_cwl, "scheduler", scheduler)

    asyncio.run(lazy_cwl.on_bot_stopping(SimpleNamespace()))
    asyncio.run(lazy_cwl.on_bot_stopping(SimpleNamespace()))

    assert scheduler.shutdown_calls == [False]
    assert lazy_cwl.scheduler is None


def test_failed_scheduler_registration_rolls_back_enabled_flag():
    snapshot = {
        "_id": "snapshot",
        "clan_name": "Clan",
        "clan_tag": "#TAG",
        "active": True,
        "auto_ping_enabled": False,
    }
    collection = FakeCollection([snapshot])
    mongo = SimpleNamespace(lazy_cwl_snapshots=collection)

    result = asyncio.run(lazy_cwl.process_single_autoping_start(
        snapshot,
        30,
        mongo,
        FakeScheduler(fail_add=True),
        0,
    ))

    assert result["success"] is False
    assert collection.documents["snapshot"]["auto_ping_enabled"] is False
    assert "auto_ping_job_id" not in collection.documents["snapshot"]
