import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils import town_halls as store


def registry():
    return {
        "_id": "123", "schema_version": 1, "revision": 7,
        "lowest_fwa_town_hall": 12,
        "levels": {
            "1": {"emoji": ""},
            "11": {"emoji": "", "weight": {"min": 91000, "max": 110000}},
            "12": {"emoji": "<:TH_12:123456789012345678>", "weight": {"min": 111000, "max": 120000}},
            "19": {"emoji": "<a:TH_19A:1571025137896005783>", "weight": {"min": 181000, "max": 190000}},
            "20": {"emoji": ""},
        },
    }


@pytest.fixture(autouse=True)
def empty_snapshot(monkeypatch):
    monkeypatch.setattr(store, "_snapshot", None)
    monkeypatch.setattr(store, "_snapshot_guild", None)


def run(awaitable):
    return asyncio.run(awaitable)


def test_readers_filter_fwa_and_compute_display_without_changing_storage():
    doc = registry()
    before = deepcopy(doc)
    assert store.levels(doc) == [20, 19, 12, 11, 1]
    assert store.fwa_levels(doc) == [19, 12]
    ranges = store.weight_ranges(doc)
    assert ranges == {
        19: {"min": 181000, "max": 190000, "display": "181k - 190k"},
        12: {"min": 111000, "max": 120000, "display": "111k - 120k"},
    }
    ranges[19]["min"] = 1
    assert doc == before
    assert store.emoji_markup(doc, 19) == "<a:TH_19A:1571025137896005783>"
    assert store.emoji_markup(doc, 20) == store.emoji_markup(doc, 99) == ""


@pytest.mark.parametrize("key", ["0", "00", "01", "100", "1.0", "-1", 12])
def test_rejects_noncanonical_level_keys(key):
    doc = registry()
    doc["levels"][key] = {"emoji": ""}
    with pytest.raises(ValueError, match="level keys"):
        store.validate(doc)


@pytest.mark.parametrize("emoji", ["TH_19A", "@everyone", "<:TH19:x>", "<:TH19:123>", "https://example.test/emoji", None, 123, " <:TH19:123456789012345678>"])
def test_rejects_emoji_names_junk_and_non_markup(emoji):
    doc = registry()
    doc["levels"]["19"]["emoji"] = emoji
    with pytest.raises(ValueError, match="custom emoji"):
        store.validate(doc)


@pytest.mark.parametrize("low,high", [(120000, 190000), (190000, 181000), (0, 190000), (181000, 500001), (True, 190000), (181000, 190000.0)])
def test_rejects_invalid_or_overlapping_weight_ranges(low, high):
    doc = registry()
    doc["levels"]["19"]["weight"] = {"min": low, "max": high}
    with pytest.raises(ValueError):
        store.validate(doc)


@pytest.mark.parametrize("lowest", [1, 20, 21, True, "12"])
def test_lowest_fwa_must_be_a_weighted_listed_integer(lowest):
    doc = registry()
    doc["lowest_fwa_town_hall"] = lowest
    with pytest.raises(ValueError):
        store.validate(doc)


def test_level_limit_and_stored_display_rejected():
    doc = registry()
    doc["levels"].update({str(level): {"emoji": ""} for level in range(1, 32)})
    with pytest.raises(ValueError, match="30"):
        store.validate(doc)
    doc = registry()
    doc["levels"]["19"]["weight"]["display"] = "not stored"
    with pytest.raises(ValueError, match="only minimum"):
        store.validate(doc)


def test_pure_edits_preserve_original_and_validate_the_whole_document():
    doc = registry()
    before = deepcopy(doc)
    added = store.add_level(doc, 21)
    assert added["levels"]["21"] == {"emoji": ""}
    edited = store.set_emoji(doc, 20, "<:TH_20:123456789012345678>")
    weighted = store.set_weight(edited, 20, 191000, 200000)
    assert store.fwa_levels(store.set_lowest_fwa(weighted, 19)) == [20, 19]
    assert "weight" not in store.set_weight(weighted, 20, None, None)["levels"]["20"]
    with pytest.raises(ValueError, match="already in the list"):
        store.add_level(doc, 19)
    with pytest.raises(ValueError, match="lowest FWA"):
        store.set_weight(doc, 12, None, None)
    assert doc == before


def test_load_missing_is_read_only(monkeypatch):
    collection = SimpleNamespace(find_one=AsyncMock(return_value=None), replace_one=AsyncMock())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    assert run(store.load(object(), 123)) is None
    collection.find_one.assert_awaited_once_with({"_id": "123"})
    collection.replace_one.assert_not_awaited()


def test_save_uses_exact_guild_revision_cas_without_upsert(monkeypatch):
    from pymongo import ReturnDocument
    doc = registry()
    committed = deepcopy(doc)
    committed.update(revision=8, nonbase_revision=8, updated_by=456)
    collection = SimpleNamespace(find_one_and_update=AsyncMock(return_value=committed), find_one=AsyncMock())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    saved = run(store.save(object(), 123, doc, 456, 7))
    args, kwargs = collection.find_one_and_update.call_args
    assert args[0] == {"_id": "123", "revision": 7}
    assert kwargs == {"upsert": False, "return_document": ReturnDocument.AFTER}
    assert args[1]["$inc"] == {"revision": 1}
    assert args[1]["$set"]["nonbase_revision"] == 8
    assert args[1]["$set"]["updated_by"] == 456
    assert args[1]["$set"]["updated_at"].utcoffset().total_seconds() == 0
    assert not any(path.endswith(".bases") or ".bases." in path for path in args[1]["$set"])
    assert saved == committed and saved is not committed
    assert doc == registry()
    collection.find_one.assert_not_awaited()


@pytest.mark.parametrize("missing,error", [(True, store.TownHallsMissing), (False, store.TownHallsConflict)])
def test_save_missing_and_conflict_never_upsert_or_retry(monkeypatch, missing, error):
    existing = registry()
    existing.update(revision=8, nonbase_revision=8)
    collection = SimpleNamespace(find_one_and_update=AsyncMock(return_value=None), find_one=AsyncMock(return_value=None if missing else existing))
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    with pytest.raises(error):
        run(store.save(object(), 123, registry(), 456, 7))
    assert collection.find_one_and_update.await_count == 1
    assert collection.find_one_and_update.call_args.kwargs["upsert"] is False


@pytest.mark.parametrize("guild,revision", [(456, 7), (123, 6), (123, True)])
def test_rejects_cross_guild_or_inconsistent_revision_before_write(monkeypatch, guild, revision):
    collection = SimpleNamespace(replace_one=AsyncMock())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    with pytest.raises(ValueError):
        run(store.save(object(), guild, registry(), 456, revision))
    collection.replace_one.assert_not_awaited()


def test_two_concurrent_edits_cannot_silently_overwrite(monkeypatch):
    a = store.add_level(registry(), 21)
    b = store.add_level(registry(), 21)
    committed = deepcopy(a)
    committed.update(revision=8, nonbase_revision=8)
    collection = SimpleNamespace(find_one_and_update=AsyncMock(side_effect=[committed, None]),
                                 find_one=AsyncMock(return_value=committed))
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    async def compete():
        return await asyncio.gather(store.save(object(), 123, a, 456, 7), store.save(object(), 123, b, 789, 7), return_exceptions=True)
    results = run(compete())
    assert sum(isinstance(item, store.TownHallsConflict) for item in results) == 1
    assert collection.find_one_and_update.await_count == 2
    assert all(call.args[0] == {"_id": "123", "revision": 7} for call in collection.find_one_and_update.call_args_list)
    assert list(committed["levels"]).count("21") == 1


def test_snapshot_empty_then_refresh_and_failure_keeps_last_good(monkeypatch, caplog):
    assert store.town_hall_emoji(19) == ""
    monkeypatch.setattr(store, "load", AsyncMock(return_value=registry()))
    assert run(store.refresh_snapshot(object(), 123)) is True
    assert store.town_hall_emoji(19) == "<a:TH_19A:1571025137896005783>"
    copy = store.snapshot(123)
    copy["levels"].clear()
    assert store.snapshot(123) == registry()
    assert store.snapshot(456) is None
    monkeypatch.setattr(store, "load", AsyncMock(side_effect=RuntimeError("upstream unavailable")))
    with caplog.at_level("WARNING"):
        assert run(store.refresh_snapshot(object(), 123)) is False
    assert len(caplog.records) == 1 and "upstream unavailable" not in caplog.text
    assert store.snapshot(123) == registry()


def test_missing_or_stale_refresh_cannot_erase_newer_snapshot(monkeypatch):
    monkeypatch.setattr(store, "load", AsyncMock(return_value=registry()))
    assert run(store.refresh_snapshot(object(), 123))
    old = registry()
    old["revision"] = 6
    monkeypatch.setattr(store, "load", AsyncMock(return_value=old))
    assert run(store.refresh_snapshot(object(), 123)) is False
    monkeypatch.setattr(store, "load", AsyncMock(return_value=None))
    assert run(store.refresh_snapshot(object(), 123, log_failure=False)) is False
    assert store.snapshot(123) == registry()


@pytest.mark.parametrize("guild", ["not-a-guild", "0123", "１２３", "", 0, -1, True, 2**64])
def test_invalid_guild_cannot_create_migration_document(monkeypatch, guild):
    collection = SimpleNamespace(find_one=AsyncMock(), insert_one=AsyncMock())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    doc = registry()
    doc["_id"] = str(guild)
    with pytest.raises(ValueError, match="server ID"):
        run(store.create_for_migration(object(), guild, doc))
    collection.insert_one.assert_not_awaited()
    collection.find_one.assert_not_awaited()


def test_cross_guild_migration_candidate_cannot_write(monkeypatch):
    collection = SimpleNamespace(find_one=AsyncMock(), insert_one=AsyncMock())
    monkeypatch.setattr(store, "_collection", lambda mongo: collection)
    with pytest.raises(ValueError, match="different server"):
        run(store.create_for_migration(object(), 456, registry()))
    collection.insert_one.assert_not_awaited()
    collection.find_one.assert_not_awaited()
