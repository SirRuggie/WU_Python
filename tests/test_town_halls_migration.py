import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError

from tools import migrate_town_halls as migration
from utils import town_halls
from utils.mongo_routes import PARENT_ALIASES, load_routes


def legacy():
    return {
        "_id": "123", "schema_version": 1, "revision": 9, "minimum_th": 9,
        "ranges": {
            "9": {"min": 56000, "max": 70000, "display": "old label", "emoji": ""},
            "12": {"min": 111000, "max": 120000, "emoji": "TH_12"},
            "19": {"min": 181000, "max": 190000, "emoji": "<a:Custom_19:123456789012345678>"},
            "20": {"min": 191000, "max": 200000, "emoji": "TH_20"},
        },
    }


class FakeCollection:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.inserts = 0

    async def count_documents(self, query):
        assert query == {}
        return len(self.rows)

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if row["_id"] == query["_id"]:
                return deepcopy(row)
        return None

    async def insert_one(self, row):
        if any(item["_id"] == row["_id"] for item in self.rows):
            raise DuplicateKeyError("duplicate fixture key")
        self.rows.append(deepcopy(row))
        self.inserts += 1


@pytest.fixture
def collections(monkeypatch):
    old, new = FakeCollection([legacy()]), FakeCollection([])
    monkeypatch.setattr(migration, "collection_from", lambda parent, alias: old if alias == "war_weight_settings" else pytest.fail("Unexpected legacy alias"))
    monkeypatch.setattr(town_halls, "_collection", lambda mongo: new)
    return old, new, SimpleNamespace(fwa_data=object())


def run(awaitable):
    return asyncio.run(awaitable)


def test_new_route_follows_fwa_parent_database_and_explicit_child_override():
    assert PARENT_ALIASES["town_halls"] == "fwa_data"
    routes = load_routes({"fwa_data": {"database": "fwa_data", "collection": "config"}})
    assert routes["town_halls"].database == "fwa_data"
    assert routes["town_halls"].collection == "town_halls"
    explicit = load_routes({
        "fwa_data": {"database": "fwa_data", "collection": "config"},
        "town_halls": {"database": "registry", "collection": "levels"},
    })
    assert (explicit["town_halls"].database, explicit["town_halls"].collection) == ("registry", "levels")


def test_build_copies_weights_full_markup_and_reports_names_without_guessing():
    old = legacy()
    before = deepcopy(old)
    doc, named = migration.build_registry(old, 123)
    assert list(doc["levels"]) == [str(level) for level in range(1, 21)]
    assert doc["lowest_fwa_town_hall"] == 12
    assert doc["revision"] == 0 and doc["schema_version"] == 1
    assert doc["levels"]["1"] == {"emoji": ""}
    assert doc["levels"]["12"]["emoji"] == migration.SEED_EMOJIS[12]
    assert doc["levels"]["19"]["emoji"] == "<a:Custom_19:123456789012345678>"
    assert doc["levels"]["20"]["emoji"] == ""
    assert doc["levels"]["9"]["weight"] == {"min": 56000, "max": 70000}
    assert named == [
        {"level": 12, "name": "TH_12", "seed_used": migration.SEED_EMOJIS[12]},
        {"level": 20, "name": "TH_20", "seed_used": ""},
    ]
    assert old == before


def test_build_includes_at_least_nineteen_levels():
    old = legacy()
    old["ranges"].pop("19")
    old["ranges"].pop("20")
    doc, _ = migration.build_registry(old, 123)
    assert len(doc["levels"]) == 19
    assert doc["levels"]["19"] == {"emoji": "<:TH_19A:1571025137896005783>"}


@pytest.mark.parametrize("change", ["missing12", "overlap", "malformedweight", "malformedemoji", "wrongguild", "too_many_levels"])
def test_invalid_source_stops_without_inventing_settings(change):
    old = legacy()
    if change == "missing12":
        del old["ranges"]["12"]
    elif change == "overlap":
        old["ranges"]["19"]["min"] = 120000
    elif change == "malformedweight":
        old["ranges"]["12"]["min"] = True
    elif change == "malformedemoji":
        old["ranges"]["12"]["emoji"] = "@everyone"
    elif change == "wrongguild":
        old["_id"] = "456"
    else:
        old["ranges"]["31"] = {"min": 300000, "max": 310000, "emoji": ""}
    with pytest.raises(ValueError):
        migration.build_registry(old, 123)


def test_dry_run_is_default_and_writes_nothing(collections):
    old, new, mongo = collections
    before = deepcopy(old.rows)
    report = run(migration.migrate(mongo, 123))
    assert report["status"] == "dry run" and report["apply"] is False
    assert report["counts_before"] == report["counts_after"] == {"war_weight_settings": 1, "town_halls": 0}
    assert old.rows == before and new.rows == [] and new.inserts == 0
    assert report["legacy_document_sha256_before"] == report["legacy_document_sha256_after"]
    assert report["name_only_overrides"][1]["name"] == "TH_20"


def test_apply_inserts_once_and_second_apply_is_no_write(collections):
    old, new, mongo = collections
    before = deepcopy(old.rows)
    first = run(migration.migrate(mongo, 123, apply=True))
    assert first["status"] == "migrated" and first["inserted"] is True
    assert first["counts_before"] == {"war_weight_settings": 1, "town_halls": 0}
    assert first["counts_after"] == {"war_weight_settings": 1, "town_halls": 1}
    saved = deepcopy(new.rows)
    second = run(migration.migrate(mongo, 123, apply=True))
    assert second["status"] == "already migrated" and second["inserted"] is False
    assert second["counts_before"] == second["counts_after"] == {"war_weight_settings": 1, "town_halls": 1}
    assert new.inserts == 1 and new.rows == saved and old.rows == before


def test_failed_validation_before_apply_never_inserts(collections):
    old, new, mongo = collections
    del old.rows[0]["ranges"]["12"]
    before = deepcopy(old.rows)
    with pytest.raises(ValueError, match="lowest FWA"):
        run(migration.migrate(mongo, 123, apply=True))
    assert old.rows == before and new.inserts == 0 and new.rows == []


def test_existing_registry_stays_idempotent_when_legacy_is_now_unusable(collections):
    old, new, mongo = collections
    run(migration.migrate(mongo, 123, apply=True))
    saved = deepcopy(new.rows)
    del old.rows[0]["ranges"]["12"]
    report = run(migration.migrate(mongo, 123, apply=True))
    assert report["status"] == "already migrated"
    assert new.inserts == 1 and new.rows == saved


def test_legacy_change_during_report_is_detected_without_restoration(collections):
    old, new, mongo = collections
    original = old.find_one
    calls = 0

    async def changed(query, projection=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            old.rows[0]["revision"] += 1
        return await original(query, projection)

    old.find_one = changed
    with pytest.raises(ValueError, match="changed during the migration"):
        run(migration.migrate(mongo, 123))
    assert old.rows[0]["revision"] == 10 and new.rows == []


def test_same_numeric_value_with_changed_bson_type_is_not_called_unchanged(collections):
    old, new, mongo = collections
    original = old.find_one
    calls = 0

    async def changed(query, projection=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            old.rows[0]["ranges"]["12"]["min"] = 111000.0
        return await original(query, projection)

    old.find_one = changed
    with pytest.raises(ValueError, match="changed during the migration"):
        run(migration.migrate(mongo, 123))
    assert new.rows == []


def test_competing_migration_reports_saved_registry_not_uninserted_proposal(collections, monkeypatch):
    old, new, mongo = collections
    other, _ = migration.build_registry(legacy(), 123)
    other["levels"]["19"]["emoji"] = "<:Other_19:123456789012345678>"

    async def competing_insert(*args):
        new.rows.append(deepcopy(other))
        return False

    monkeypatch.setattr(town_halls, "create_for_migration", competing_insert)
    report = run(migration.migrate(mongo, 123, apply=True))
    assert report["status"] == "already migrated" and report["inserted"] is False
    assert next(row for row in report["levels"] if row["level"] == 19)["emoji"] == other["levels"]["19"]["emoji"]
    assert old.rows == [legacy()] and new.inserts == 0


def test_migration_duplicate_key_is_success_only_after_confirmed_insert(monkeypatch):
    doc, _ = migration.build_registry(legacy(), 123)
    coll = SimpleNamespace(
        find_one=AsyncMock(side_effect=[None, {"_id": "123"}]),
        insert_one=AsyncMock(side_effect=DuplicateKeyError("competing fixture insert")),
    )
    monkeypatch.setattr(town_halls, "_collection", lambda mongo: coll)
    assert run(town_halls.create_for_migration(object(), 123, doc)) is False
    assert coll.insert_one.await_count == 1
    coll.find_one = AsyncMock(side_effect=[None, None])
    with pytest.raises(DuplicateKeyError):
        run(town_halls.create_for_migration(object(), 123, doc))


def test_uncertain_migration_insert_is_not_retried(monkeypatch):
    doc, _ = migration.build_registry(legacy(), 123)
    coll = SimpleNamespace(find_one=AsyncMock(return_value=None), insert_one=AsyncMock(side_effect=TimeoutError("uncertain")))
    monkeypatch.setattr(town_halls, "_collection", lambda mongo: coll)
    with pytest.raises(TimeoutError):
        run(town_halls.create_for_migration(object(), 123, doc))
    assert coll.insert_one.await_count == 1


def test_cli_without_apply_is_dry_run_and_writes_new_private_report(monkeypatch, tmp_path):
    import dotenv
    monkeypatch.setattr(migration, "ROOT", tmp_path)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused.invalid")
    fake = AsyncMock(return_value={"status": "dry run", "counts_before": {}, "counts_after": {}})
    monkeypatch.setattr(migration, "_run", fake)
    assert migration.main(["--guild-id", "123"]) == 0
    assert fake.call_args.kwargs == {"apply": False}
    reports = list((tmp_path / ".local").glob("*.json"))
    assert len(reports) == 1 and json.loads(reports[0].read_text())["status"] == "dry run"
    assert reports[0].stat().st_mode & 0o777 == 0o600
