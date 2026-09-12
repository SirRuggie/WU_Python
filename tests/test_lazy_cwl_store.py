import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils import lazy_cwl_store


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def _get_path(document, path):
    current = document
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matches(document, query):
    for key, expected in query.items():
        actual = _get_path(document, key)
        if not isinstance(expected, dict):
            if actual != expected:
                return False
            continue
        if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
            return False
        if "$in" in expected and actual not in expected["$in"]:
            return False
    return True


def _set_path(document, path, value):
    current = document
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = deepcopy(value)


class _Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, field, direction=1):
        self.documents.sort(key=lambda document: document.get(field) or "", reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        if length is None:
            return deepcopy(self.documents)
        return deepcopy(self.documents[:length])


class _Collection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}
        self.index_calls = []
        self._next_id = 1
        self.unique_partial_field = None

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((deepcopy(keys), deepcopy(kwargs)))
        if kwargs.get("unique") and kwargs.get("partialFilterExpression"):
            self.unique_partial_field = (keys, kwargs["partialFilterExpression"])
        return kwargs.get("name")

    def _violates_unique(self, document):
        if self.unique_partial_field is None:
            return False
        field, partial = self.unique_partial_field
        if not all(document.get(key) == value for key, value in partial.items()):
            return False
        for existing in self.documents.values():
            if existing.get(field) == document.get(field) and all(
                existing.get(key) == value for key, value in partial.items()
            ):
                return True
        return False

    async def insert_one(self, document):
        if self._violates_unique(document):
            raise DuplicateKeyError("duplicate key")
        if "_id" not in document:
            document["_id"] = f"id-{self._next_id}"
            self._next_id += 1
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return _Cursor(document for document in self.documents.values() if _matches(document, query))

    async def find_one_and_update(self, query, update, **kwargs):
        for document in self.documents.values():
            if not _matches(document, query):
                continue
            before_snapshot = deepcopy(document)
            for path, value in update.get("$set", {}).items():
                _set_path(document, path, value)
            for path, amount in update.get("$inc", {}).items():
                current = document
                parts = path.split(".")
                for part in parts[:-1]:
                    current = current.setdefault(part, {})
                current[parts[-1]] = current.get(parts[-1], 0) + amount
            if "$push" in update:
                for path, value in update["$push"].items():
                    document.setdefault(path, []).append(deepcopy(value))
            if "$pull" in update:
                for path, condition in update["$pull"].items():
                    items = document.get(path, [])
                    document[path] = [
                        item for item in items if not _matches(item, condition)
                    ]
            self.documents[document["_id"]] = document
            if kwargs.get("return_document") == ReturnDocument.BEFORE:
                return before_snapshot
            return deepcopy(document)
        return None


class _Mongo:
    def __init__(self, documents=()):
        self.lazy_cwl_lists = _Collection(documents)


def _list_doc(list_id, *, clan_tag="ABC", clan_name="Alpha", status="active", expires_at=None):
    return {
        "_id": list_id,
        "clan_tag": lazy_cwl_store._normalize_tag(clan_tag),
        "clan_name": clan_name,
        "status": status,
        "saved_at": NOW,
        "saved_by": 1,
        "expires_at": expires_at or NOW + timedelta(days=3),
        "purge_at": (expires_at or NOW + timedelta(days=3)) + lazy_cwl_store.PURGE_RETENTION,
        "players": [],
        "reminders": {
            "enabled": False,
            "every_minutes": None,
            "started_at": None,
            "last_sent_at": None,
            "sent_count": 0,
        },
    }


def test_expires_at_for_edge_dates():
    assert lazy_cwl_store.expires_at_for(
        datetime(2026, 9, 1, tzinfo=timezone.utc)
    ) == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert lazy_cwl_store.expires_at_for(
        datetime(2026, 9, 15, 23, 59, tzinfo=timezone.utc)
    ) == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert lazy_cwl_store.expires_at_for(
        datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
    ) == datetime(2026, 10, 16, tzinfo=timezone.utc)
    assert lazy_cwl_store.expires_at_for(
        datetime(2026, 8, 31, tzinfo=timezone.utc)
    ) == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert lazy_cwl_store.expires_at_for(
        datetime(2026, 12, 20, tzinfo=timezone.utc)
    ) == datetime(2027, 1, 16, tzinfo=timezone.utc)


def test_ensure_indexes_creates_the_three_named_indexes():
    mongo = _Mongo()

    asyncio.run(lazy_cwl_store.ensure_indexes(mongo))

    names = [kwargs.get("name") for _, kwargs in mongo.lazy_cwl_lists.index_calls]
    assert names == [
        lazy_cwl_store.ONE_ACTIVE_PER_CLAN_INDEX,
        lazy_cwl_store.TTL_PURGE_INDEX,
        lazy_cwl_store.STATUS_EXPIRES_INDEX,
    ]
    keys, kwargs = mongo.lazy_cwl_lists.index_calls[0]
    assert keys == "clan_tag"
    assert kwargs["unique"] is True
    assert kwargs["partialFilterExpression"] == {"status": "active"}
    ttl_keys, ttl_kwargs = mongo.lazy_cwl_lists.index_calls[1]
    assert ttl_keys == "purge_at"
    assert ttl_kwargs["expireAfterSeconds"] == 0
    compound_keys, _ = mongo.lazy_cwl_lists.index_calls[2]
    assert compound_keys == [("status", 1), ("expires_at", 1)]


def test_save_list_happy_path_and_duplicate():
    mongo = _Mongo()
    asyncio.run(lazy_cwl_store.ensure_indexes(mongo))

    created = asyncio.run(lazy_cwl_store.save_list(
        mongo,
        clan_tag=" #abc ",
        clan_name="Alpha",
        players=[{"tag": "#p1", "name": "Foo", "town_hall": 15,
                  "discord_id": None, "added_manually": False, "added_at": NOW}],
        saved_by=42,
        now=NOW,
    ))

    assert created["clan_tag"] == "#ABC"
    assert created["status"] == "active"
    assert created["expires_at"] == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert created["purge_at"] == created["expires_at"] + lazy_cwl_store.PURGE_RETENTION
    assert created["reminders"] == {
        "enabled": False, "every_minutes": None,
        "started_at": None, "last_sent_at": None, "sent_count": 0,
    }

    with pytest.raises(lazy_cwl_store.AlreadySavedError) as excinfo:
        asyncio.run(lazy_cwl_store.save_list(
            mongo, clan_tag="#ABC", clan_name="Alpha",
            players=[], saved_by=1, now=NOW,
        ))
    assert excinfo.value.existing_doc["clan_tag"] == "#ABC"


def test_save_list_normalises_players():
    """refuter-01 defect 1: players must go through the same normaliser as
    add_player — tag upper+strip, added_manually default False, added_at
    default now, discord_id default None."""
    mongo = _Mongo()

    created = asyncio.run(lazy_cwl_store.save_list(
        mongo, clan_tag="ABC", clan_name="Alpha",
        players=[{"tag": "#p1", "name": "Foo", "town_hall": 15}],
        saved_by=1, now=NOW,
    ))

    assert created["players"] == [{
        "tag": "#P1",
        "name": "Foo",
        "town_hall": 15,
        "discord_id": None,
        "added_manually": False,
        "added_at": NOW,
    }]


def test_save_list_duplicate_via_index_reaches_insert_one_and_recovers(monkeypatch):
    """refuter-01 defect 4: force the race so insert_one is actually
    attempted (spied) and its DuplicateKeyError is converted to
    AlreadySavedError with the re-read existing doc."""
    mongo = _Mongo([_list_doc("existing", clan_tag="ABC")])
    mongo.lazy_cwl_lists.unique_partial_field = ("clan_tag", {"status": "active"})

    real_get_active = lazy_cwl_store.get_active
    calls = {"n": 0}

    async def racing_get_active(mongo_arg, clan_tag):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_get_active(mongo_arg, clan_tag)

    monkeypatch.setattr(lazy_cwl_store, "get_active", racing_get_active)

    real_insert_one = mongo.lazy_cwl_lists.insert_one
    insert_calls = {"n": 0}

    async def spying_insert_one(document):
        insert_calls["n"] += 1
        return await real_insert_one(document)

    monkeypatch.setattr(mongo.lazy_cwl_lists, "insert_one", spying_insert_one)

    with pytest.raises(lazy_cwl_store.AlreadySavedError) as excinfo:
        asyncio.run(lazy_cwl_store.save_list(
            mongo, clan_tag="ABC", clan_name="Alpha",
            players=[], saved_by=1, now=NOW,
        ))

    assert insert_calls["n"] == 1
    assert excinfo.value.existing_doc["clan_tag"] == "#ABC"


def test_already_saved_error_survives_missing_existing_doc(monkeypatch):
    """refuter-01 defect 3: if the doc that caused the DuplicateKeyError is
    gone by the re-read (finished concurrently), AlreadySavedError must
    still raise cleanly with existing_doc=None, not AttributeError."""
    mongo = _Mongo()
    mongo.lazy_cwl_lists.unique_partial_field = ("clan_tag", {"status": "active"})

    async def missing_get_active(mongo_arg, clan_tag):
        return None

    monkeypatch.setattr(lazy_cwl_store, "get_active", missing_get_active)

    async def failing_insert_one(document):
        raise DuplicateKeyError("duplicate key")

    monkeypatch.setattr(mongo.lazy_cwl_lists, "insert_one", failing_insert_one)

    with pytest.raises(lazy_cwl_store.AlreadySavedError) as excinfo:
        asyncio.run(lazy_cwl_store.save_list(
            mongo, clan_tag="ABC", clan_name="Alpha",
            players=[], saved_by=1, now=NOW,
        ))

    assert excinfo.value.existing_doc is None


def test_add_player_happy_duplicate_and_no_active_list():
    mongo = _Mongo([_list_doc("list-1", clan_tag="ABC")])

    updated = asyncio.run(lazy_cwl_store.add_player(
        mongo, "abc",
        {"tag": "#p1", "name": "Foo", "town_hall": 12, "discord_id": 7},
        now=NOW,
    ))
    assert len(updated["players"]) == 1
    assert updated["players"][0]["tag"] == "#P1"
    assert updated["players"][0]["added_manually"] is True

    with pytest.raises(lazy_cwl_store.PlayerAlreadyListedError):
        asyncio.run(lazy_cwl_store.add_player(
            mongo, "abc", {"tag": "#p1", "name": "Foo", "town_hall": 12}, now=NOW,
        ))

    with pytest.raises(lazy_cwl_store.NoActiveListError):
        asyncio.run(lazy_cwl_store.add_player(
            mongo, "zzz", {"tag": "#p2", "name": "Bar", "town_hall": 10}, now=NOW,
        ))


def test_remove_players():
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = [
        {"tag": "#P1", "name": "Foo", "town_hall": 10, "discord_id": None,
         "added_manually": False, "added_at": NOW},
        {"tag": "#P2", "name": "Bar", "town_hall": 11, "discord_id": None,
         "added_manually": False, "added_at": NOW},
    ]
    mongo = _Mongo([doc])

    removed = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["p1", "p3"]))

    assert removed == 1
    remaining = asyncio.run(lazy_cwl_store.get_active(mongo, "abc"))
    assert [p["tag"] for p in remaining["players"]] == ["#P2"]


def test_remove_players_case_insensitive_and_absent_tag():
    """Brief scenario: list holds "#P1", removing lower-case "#p1" removes
    it and reports 1; removing an absent tag reports 0."""
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = [
        {"tag": "#P1", "name": "Foo", "town_hall": 10, "discord_id": None,
         "added_manually": False, "added_at": NOW},
    ]
    mongo = _Mongo([doc])

    removed = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["#p1"]))
    assert removed == 1
    remaining = asyncio.run(lazy_cwl_store.get_active(mongo, "abc"))
    assert remaining["players"] == []

    removed_absent = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["#ZZZ"]))
    assert removed_absent == 0


def test_remove_players_returns_zero_when_real_collection_already_empty(monkeypatch):
    """refuter-02 NOTED: renamed from
    test_remove_players_count_reflects_actual_write_not_stale_read. The
    get_active monkeypatch below is vestigial — remove_players has never
    called get_active — but is kept as a regression guard: even if a stale
    get_active read claims the tag is present, the count must still come
    from the real collection's BEFORE image (here: empty), so it is 0."""
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = []  # tag already gone from the real collection
    mongo = _Mongo([doc])

    stale_doc = deepcopy(doc)
    stale_doc["players"] = [{
        "tag": "#P1", "name": "Foo", "town_hall": 10,
        "discord_id": None, "added_manually": False, "added_at": NOW,
    }]

    async def stale_get_active(mongo_arg, clan_tag):
        return stale_doc

    monkeypatch.setattr(lazy_cwl_store, "get_active", stale_get_active)

    removed = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["#p1"]))

    assert removed == 0


def test_remove_players_derives_count_from_before_image_no_second_read(monkeypatch):
    """refuter-02 must-fix 1: the count must come from the BEFORE image of
    the single find_one_and_update call, using the same predicate the
    $pull used. remove_players must not perform a second read at all —
    that second find_one was the source of the non-atomic stale-count bug
    (a status flip or concurrent add_player landing between the two reads
    could over- or under-count)."""
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = [
        {"tag": "#P1", "name": "Foo", "town_hall": 10, "discord_id": None,
         "added_manually": False, "added_at": NOW},
        {"tag": "#P2", "name": "Bar", "town_hall": 11, "discord_id": None,
         "added_manually": False, "added_at": NOW},
    ]
    mongo = _Mongo([doc])

    calls = {"n": 0}
    real_find_one = mongo.lazy_cwl_lists.find_one

    async def spying_find_one(query):
        calls["n"] += 1
        return await real_find_one(query)

    monkeypatch.setattr(mongo.lazy_cwl_lists, "find_one", spying_find_one)

    removed = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["#p1"]))

    assert removed == 1
    assert calls["n"] == 0
    remaining = asyncio.run(lazy_cwl_store.get_active(mongo, "abc"))
    assert [p["tag"] for p in remaining["players"]] == ["#P2"]


def test_normalize_tag_is_hash_aware():
    """refuter-02 NOTED: add_player's duplicate check and remove_players'
    tag matching must treat "P1" and "#P1" as the same tag."""
    mongo = _Mongo([_list_doc("list-1", clan_tag="ABC")])

    asyncio.run(lazy_cwl_store.add_player(
        mongo, "abc", {"tag": "#P1", "name": "Foo", "town_hall": 10}, now=NOW,
    ))

    with pytest.raises(lazy_cwl_store.PlayerAlreadyListedError):
        asyncio.run(lazy_cwl_store.add_player(
            mongo, "abc", {"tag": "P1", "name": "Foo", "town_hall": 10}, now=NOW,
        ))

    removed = asyncio.run(lazy_cwl_store.remove_players(mongo, "abc", ["p1"]))
    assert removed == 1


def test_save_list_normalises_naive_added_at_to_utc():
    """refuter-02 NOTED: caller-supplied added_at must be routed through
    _utc, not stored naive."""
    mongo = _Mongo()
    naive = datetime(2026, 9, 10, 8, 0)  # no tzinfo

    created = asyncio.run(lazy_cwl_store.save_list(
        mongo, clan_tag="ABC", clan_name="Alpha",
        players=[{"tag": "#P1", "name": "Foo", "town_hall": 10, "added_at": naive}],
        saved_by=1, now=NOW,
    ))

    stored = created["players"][0]["added_at"]
    assert stored.tzinfo is not None
    assert stored == naive.replace(tzinfo=timezone.utc)


def test_set_reminders_on_then_off():
    mongo = _Mongo([_list_doc("list-1", clan_tag="ABC")])

    on = asyncio.run(lazy_cwl_store.set_reminders(
        mongo, "abc", enabled=True, every_minutes=30, now=NOW,
    ))
    assert on["reminders"]["enabled"] is True
    assert on["reminders"]["started_at"] == NOW
    assert on["reminders"]["sent_count"] == 0

    bumped = asyncio.run(lazy_cwl_store.record_reminder_sent(mongo, "list-1", now=NOW + timedelta(minutes=30)))
    assert bumped is None

    off = asyncio.run(lazy_cwl_store.set_reminders(
        mongo, "abc", enabled=False, every_minutes=None, now=NOW + timedelta(hours=1),
    ))
    assert off["reminders"]["enabled"] is False
    assert off["reminders"]["sent_count"] == 1


def test_record_reminder_sent_increments():
    mongo = _Mongo([_list_doc("list-1", clan_tag="ABC")])

    asyncio.run(lazy_cwl_store.record_reminder_sent(mongo, "list-1", now=NOW))
    asyncio.run(lazy_cwl_store.record_reminder_sent(mongo, "list-1", now=NOW + timedelta(minutes=5)))

    stored = mongo.lazy_cwl_lists.documents["list-1"]
    assert stored["reminders"]["sent_count"] == 2
    assert stored["reminders"]["last_sent_at"] == NOW + timedelta(minutes=5)


def test_finish():
    mongo = _Mongo([_list_doc("list-1", clan_tag="ABC")])

    finished = asyncio.run(lazy_cwl_store.finish(mongo, "abc", now=NOW))

    assert finished["status"] == "finished"
    assert finished["finished_at"] == NOW
    assert finished["reminders"]["enabled"] is False
    assert asyncio.run(lazy_cwl_store.get_active(mongo, "abc")) is None


def test_expire_due_flips_only_due_active_rows():
    mongo = _Mongo([
        _list_doc("due", clan_tag="ABC", expires_at=NOW - timedelta(days=1)),
        _list_doc("not-due", clan_tag="DEF", expires_at=NOW + timedelta(days=1)),
        _list_doc("already-finished", clan_tag="GHI", status="finished", expires_at=NOW - timedelta(days=1)),
    ])
    mongo.lazy_cwl_lists.documents["due"]["reminders"]["enabled"] = True

    flipped = asyncio.run(lazy_cwl_store.expire_due(mongo, now=NOW))

    assert [doc["_id"] for doc in flipped] == ["due"]
    assert flipped[0]["status"] == "expired"
    assert flipped[0]["reminders"]["enabled"] is False
    assert mongo.lazy_cwl_lists.documents["not-due"]["status"] == "active"
    assert mongo.lazy_cwl_lists.documents["already-finished"]["status"] == "finished"


def test_list_reminder_enabled_filter():
    doc1 = _list_doc("list-1", clan_tag="ABC")
    doc1["reminders"]["enabled"] = True
    doc2 = _list_doc("list-2", clan_tag="DEF")
    doc2["reminders"]["enabled"] = False
    doc3 = _list_doc("list-3", clan_tag="GHI", status="finished")
    doc3["reminders"]["enabled"] = True
    mongo = _Mongo([doc1, doc2, doc3])

    enabled = asyncio.run(lazy_cwl_store.list_reminder_enabled(mongo))

    assert [doc["_id"] for doc in enabled] == ["list-1"]


def test_list_active_sorted_by_clan_name():
    mongo = _Mongo([
        _list_doc("z", clan_tag="ZZZ", clan_name="Zeta"),
        _list_doc("a", clan_tag="AAA", clan_name="Alpha"),
        _list_doc("f", clan_tag="FFF", clan_name="Finished", status="finished"),
    ])

    active = asyncio.run(lazy_cwl_store.list_active(mongo))

    assert [doc["clan_name"] for doc in active] == ["Alpha", "Zeta"]
