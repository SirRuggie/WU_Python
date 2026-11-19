"""Schema2, real storage-call CAS contracts and fixture-only bases migration."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pymongo import ReturnDocument

from utils import town_halls as store
from tools import migrate_town_halls as migration

LINK = "https://link.clashofclans.com/en?action=OpenLayout&id=TH19%3AWB%3Atest"


def registry():
    return {"_id": "123", "schema_version": 1, "revision": 7,
            "lowest_fwa_town_hall": 12,
            "levels": {"11": {"emoji": ""}, "12": {"emoji": "", "weight": {"min": 111000, "max": 120000}},
                       "19": {"emoji": "<:TH19:123456789012345678>", "weight": {"min": 181000, "max": 190000}}}}


def v2():
    return store.set_base_field(registry(), 19, "merged.link", LINK)


def run(value):
    return asyncio.run(value)


def get(row, path):
    target = row
    for part in path.split("."):
        if not isinstance(target, dict) or part not in target:
            return False, None
        target = target[part]
    return True, target


class AtomicCollection:
    """Small generic dotted-field Mongo fixture, not a registry implementation."""
    def __init__(self, row):
        self.row = deepcopy(row)
        self.calls = []
        self.fail_after_commit = False

    async def count_documents(self, query):
        return int(self.row is not None)

    async def find_one(self, query, projection=None):
        return deepcopy(self.row) if self.row and self.row["_id"] == query["_id"] else None

    async def find_one_and_update(self, query, update, *, upsert, return_document):
        assert not upsert and return_document == ReturnDocument.AFTER
        self.calls.append((deepcopy(query), deepcopy(update)))
        for path, expected in query.items():
            exists, actual = get(self.row, path)
            if isinstance(expected, dict):
                if "$exists" in expected and exists != expected["$exists"]:
                    return None
                if "$lte" in expected and (not exists or actual > expected["$lte"]):
                    return None
            elif not exists or actual != expected:
                return None
        for operator, fields in update.items():
            for path, value in fields.items():
                target = self.row
                parts = path.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                key = parts[-1]
                if operator == "$set":
                    target[key] = deepcopy(value)
                elif operator == "$unset":
                    target.pop(key, None)
                elif operator == "$inc":
                    target[key] = target.get(key, 0) + value
                elif operator == "$max":
                    target[key] = max(target.get(key, value), value)
                else:
                    raise AssertionError(operator)
        if self.fail_after_commit:
            raise TimeoutError("uncertain fixture write")
        return deepcopy(self.row)


def install(monkeypatch, row=None):
    collection = AtomicCollection(row or v2())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    return collection


def save_base(collection, path, value, original=None):
    if original is None:
        original = store.base_field_snapshot(v2(), 19, path)
    return store.save_base_fields(object(), 123, 19, {path: value}, {path: original}, 456)


def test_variants_are_link_gated_shared_images_and_high_to_low():
    doc = v2()
    for path, value in [("non_merged.link", LINK + "2"), ("war_image", "https://images.example.test/shared.jpg"), ("active_image", "https://images.example.test/active.jpg")]:
        doc = store.set_base_field(doc, 19, path, value)
    doc["levels"]["11"]["bases"] = {"merged": {"link": LINK}}
    doc["levels"]["12"]["bases"] = {"war_image": "https://images.example.test/no-link.jpg"}
    rows = store.base_variants(doc)
    assert [row["key"] for row in rows] == ["th19", "th19_new"]
    assert rows[0]["war_image"] == rows[1]["war_image"]
    assert [option["label"] for option in store.menu_options(doc)] == ["TH19 Merged", "TH19 Non-merged"]
    assert store.parse_variant_value("th19_new") == (19, "non_merged")
    assert store.parse_variant_value("th18") == (18, "merged")


@pytest.mark.parametrize("path,value", [("merged.war_image", "https://example.test/x"), ("merged.link", "https://evil.test/?action=OpenLayout&id=x"), ("war_image", "http://example.test/x"), ("merged.instructions", "x" * 4001), ("non_merged.upgrade_notes", None)])
def test_shape_validation_rejects_invalid_paths_urls_and_text(path, value):
    before = v2()
    with pytest.raises(ValueError):
        store.set_base_field(before, 19, path, value)
    assert before == v2()


@pytest.mark.parametrize("value", ["TH19", "th019", "th0", "th100", "th19_new.extra", None])
def test_variant_parser_rejects_noncanonical_values(value):
    with pytest.raises(ValueError):
        store.parse_variant_value(value)


def test_menu_caps_once_at_highest25(caplog):
    doc = v2()
    doc["levels"] = {str(level): {"emoji": "", "bases": {"merged": {"link": LINK}, "non_merged": {"link": LINK}}} for level in range(12, 42)}
    doc["levels"]["12"]["weight"] = {"min": 111000, "max": 120000}
    with caplog.at_level("WARNING"):
        options = store.menu_options(doc)
    assert len(options) == 25 and options[0]["value"] == "th41"
    assert len(caplog.records) == 1


@pytest.mark.parametrize("order", ["base-first", "weight-first"])
def test_base_and_weight_both_save_in_either_order_without_lost_fields(monkeypatch, order):
    collection = install(monkeypatch)
    draft = store.set_weight(v2(), 19, 182000, 191000)
    async def edit():
        if order == "base-first":
            await save_base(collection, "merged.instructions", "New instructions")
            await store.save(object(), 123, draft, 789, 7)
        else:
            await store.save(object(), 123, draft, 789, 7)
            await save_base(collection, "merged.instructions", "New instructions")
    run(edit())
    assert collection.row["revision"] == 9
    assert collection.row["levels"]["19"]["weight"]["min"] == 182000
    assert collection.row["levels"]["19"]["bases"]["merged"]["instructions"] == "New instructions"
    assert collection.row["nonbase_revision"] == (9 if order == "base-first" else 8)
    assert all("replace" not in str(update) for _, update in collection.calls)


def test_different_base_fields_both_save_but_same_field_conflicts(monkeypatch):
    collection = install(monkeypatch)
    run(save_base(collection, "merged.instructions", "a"))
    run(save_base(collection, "non_merged.instructions", "b"))
    with pytest.raises(store.TownHallsConflict, match="This base changed"):
        run(save_base(collection, "merged.instructions", "stale"))
    assert collection.row["revision"] == 9 and collection.row["nonbase_revision"] == 7
    assert collection.row["levels"]["19"]["bases"]["merged"]["instructions"] == "a"


def test_admin_admin_still_conflicts_after_base_revision(monkeypatch):
    collection = install(monkeypatch)
    run(save_base(collection, "merged.instructions", "base"))
    a = store.set_emoji(v2(), 19, "")
    run(store.save(object(), 123, a, 789, 7))
    with pytest.raises(store.TownHallsConflict):
        run(store.save(object(), 123, store.set_weight(v2(), 19, 182000, 191000), 456, 7))
    assert collection.row["revision"] == 9


@pytest.mark.parametrize("base", [True, False])
def test_uncertain_committed_write_never_retries(monkeypatch, base):
    collection = install(monkeypatch)
    collection.fail_after_commit = True
    with pytest.raises(TimeoutError):
        run(save_base(collection, "merged.instructions", "a") if base else store.save(object(), 123, store.set_emoji(v2(), 19, ""), 456, 7))
    assert len(collection.calls) == 1 and collection.row["revision"] == 8


def test_migration_dry_apply_second_apply_and_legacy_bytes(monkeypatch):
    collection = install(monkeypatch, registry())
    legacy = {"_id": "fwa_config", "fwa_base_links": {"th19": LINK, "th19_new": LINK + "2", "th11": LINK}, "base_information": {"th22": "new level", "th19": "instructions"}, "base_upgrade_notes": {}, "war_base_images": {"th19": "https://images.example.test/merged.jpg", "th19_new": "https://images.example.test/non.jpg"}, "active_base_images": {"th19_new": "https://images.example.test/active.jpg"}, "unrelated": {"kept": True}}
    before = deepcopy(legacy)
    class Legacy:
        async def find_one(self, query):
            assert query == {"_id": "fwa_config"}
            return deepcopy(legacy)
    mongo = SimpleNamespace(fwa_data=Legacy())
    dry = run(migration.migrate(mongo, 123, bases=True))
    assert not collection.calls and dry["status"] == "dry run"
    assert dry["counts_before"] == dry["counts_after"]
    assert dry["copied_below_lowest_fwa"] == [11]
    assert dry["image_differences"][0]["selected"] == "Merged"
    applied = run(migration.migrate(mongo, 123, bases=True, apply=True))
    assert applied["applied"] and collection.row["schema_version"] == 2
    assert collection.row["nonbase_revision"] == 7 and collection.row["revision"] == 8
    assert collection.row["levels"]["19"]["bases"]["war_image"].endswith("merged.jpg")
    assert collection.row["levels"]["19"]["bases"]["active_image"].endswith("active.jpg")
    assert collection.row["levels"]["22"]["emoji"] == ""
    assert all(row["level"] >= 12 for row in store.base_variants(collection.row))
    second = run(migration.migrate(mongo, 123, bases=True, apply=True))
    assert second["status"] == "already migrated" and len(collection.calls) == 1
    assert legacy == before and applied["legacy_document_sha256_before"] == applied["legacy_document_sha256_after"]
