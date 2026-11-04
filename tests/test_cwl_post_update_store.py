"""Owned workflow transitions; no Discord, provider or production connections."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError
from test_cwl_dashboard_integration import MemoryCollection
from utils.cwl_post_update_store import (
    KIND,
    PENDING_INDEX,
    PostUpdateConflict,
    PostUpdateStore,
    now,
)


class Cursor:
    def __init__(self, rows, owner):
        self.rows = deepcopy(rows)
        self.owner = owner

    def hint(self, name):
        self.owner.hints.append(name)
        return self

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row[key], reverse=direction < 0)
        return self

    def limit(self, size):
        self.rows = self.rows[:size]
        return self

    async def to_list(self, length=None):
        return deepcopy(self.rows[:length])


class Collection(MemoryCollection):
    def __init__(self):
        super().__init__()
        self.indexes = []
        self.hints = []

    @classmethod
    def _matches(cls, document, query):
        # Model the native atomic freshness predicate, not equality on $gt.
        for key, value in query.items():
            if isinstance(value, dict) and "$gt" in value:
                actual = cls._path(document, key, None)
                if actual is None or actual <= value["$gt"]:
                    return False
            elif not super()._matches(document, {key: value}):
                return False
        return True

    async def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))
        return kwargs["name"]

    async def find_one(self, query, projection=None):
        row = await super().find_one(query)
        if row is not None and projection:
            row = {
                key: value
                for key, value in row.items()
                if projection.get(key, key == "_id")
            }
        return row

    async def insert_one(self, row):
        if row["_id"] in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[row["_id"]] = deepcopy(row)

    def find(self, query=None, projection=None):
        return Cursor(
            [row for row in self.documents.values() if self._matches(row, query or {})],
            self,
        )

    async def update_many(self, query, change):
        keys = [
            row["_id"] for row in self.documents.values() if self._matches(row, query)
        ]
        for key in keys:
            await self.update_one({"_id": key}, change)
        return SimpleNamespace(matched_count=len(keys))


def fixture():
    return PostUpdateStore(SimpleNamespace(bot_config=Collection()))


async def create(store, nonce="a" * 32, **changes):
    values = dict(
        guild_id=100,
        user_id=200,
        season_id="42",
        cycle="2026-11",
        pool="main",
        nonce=nonce,
        generation="1:2",
        draft_id="draft-1",
        candidate={
            "title": "Roster",
            "body": "Edited text",
            "buttons": [
                {"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}
            ],
        },
        future_months=True,
    )
    values.update(changes)
    return await store.create(**values)


def test_preview_identity_is_idempotent_actor_scoped_and_conflicting_payload_is_rejected():
    async def run():
        store = fixture()
        row, new = await create(store)
        assert new
        again, new = await create(store, draft_id="different-unused-draft")
        assert not new and again["_id"] == row["_id"] and again["draft_id"] == "draft-1"
        with pytest.raises(PostUpdateConflict):
            await create(store, future_months=False)
        for scope in ({"user_id": 201}, {"season_id": "43"}, {"pool": "lazy"}):
            arguments = dict(guild_id=100, user_id=200, season_id="42", pool="main")
            arguments.update(scope)
            with pytest.raises(PostUpdateConflict):
                await store.owned(row["_id"], **arguments)
        indexes = store.collection.indexes
        assert len(indexes) == 3
        assert next(
            options
            for _, options in indexes
            if options["name"] == "cwl_post_update_expiry"
        )["partialFilterExpression"] == {"kind": KIND}

    asyncio.run(run())


def test_preview_can_be_consumed_once_and_claimed_once_despite_double_tap():
    async def run():
        store = fixture()
        row, _ = await create(store)
        work = await store.claim(row, runtime_id="process-a")
        assert work["status"] == "previewing"
        assert await store.finish(
            work, status="ready", target={"fingerprint": "observed", "message_id": 400}
        )
        ready = await store.collection.find_one({"_id": row["_id"]})
        queued = await asyncio.gather(
            store.request_update(ready), store.request_update(deepcopy(ready))
        )
        assert all(row["status"] == "pending_update" for row in queued)
        claims = await asyncio.gather(
            *(store.claim(row, runtime_id="process-a") for row in queued)
        )
        assert len([row for row in claims if row]) == 1
        active = next(row for row in claims if row)
        assert "expires_at" not in active
        assert await store.finish(
            active,
            status="done",
            message_url="https://discord.com/channels/100/300/400",
        )
        assert not await store.finish(
            active, status="failed", error="Late stale completion"
        )
        assert not await store.pending(100)
        assert store.collection.hints[-1] == PENDING_INDEX

    asyncio.run(run())


def test_worker_restart_never_requeues_an_interrupted_possible_edit():
    async def run():
        store = fixture()
        preview, _ = await create(store)
        await store.claim(preview, runtime_id="old")
        update, _ = await create(store, nonce="b" * 32)
        working = await store.claim(update, runtime_id="old")
        await store.finish(working, status="ready", target={"fingerprint": "seen"})
        ready = await store.collection.find_one({"_id": update["_id"]})
        queued = await store.request_update(ready)
        await store.claim(queued, runtime_id="old")
        current, _ = await create(store, nonce="c" * 32)
        await store.claim(current, runtime_id="new")
        await store.recover_interrupted(guild_id=100, runtime_id="new")
        assert store.collection.documents[preview["_id"]]["status"] == "failed"
        assert store.collection.documents[update["_id"]]["status"] == "uncertain"
        assert store.collection.documents[current["_id"]]["status"] == "previewing"
        assert not await store.pending(100)

    asyncio.run(run())


def test_expired_preview_and_unobserved_target_cannot_update():
    async def run():
        store = fixture()
        row, _ = await create(store)
        with pytest.raises(PostUpdateConflict):
            await store.request_update(row)
        work = await store.claim(row, runtime_id="process")
        with pytest.raises(ValueError):
            await store.finish(work, status="ready")
        assert await store.finish(
            work, status="ready", target={"fingerprint": "observed"}
        )
        row = store.collection.documents[row["_id"]]
        row["expires_at"] = now() - timedelta(seconds=1)
        with pytest.raises(PostUpdateConflict, match="Preview expired"):
            await store.request_update(row)
        assert row["status"] == "ready"

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"pool": "other"},
        {"nonce": "../secret"},
        {"future_months": "true"},
        {"candidate": {"body": "x", "title": "y", "buttons": [], "channel_id": 999}},
        {"season_id": "bad"},
        {"cycle": "2026-13"},
    ],
)
def test_malformed_or_privilege_expanding_request_never_persists(change):
    async def run():
        store = fixture()
        with pytest.raises(ValueError):
            await create(store, **change)
        assert not store.collection.documents

    asyncio.run(run())


@pytest.mark.parametrize("runtime_id", ["", "   ", None, 123])
def test_worker_identity_required_before_claim_or_recovery(runtime_id):
    async def run():
        store = fixture()
        row, _ = await create(store)
        before = deepcopy(store.collection.documents)
        with pytest.raises(ValueError, match="process identity"):
            await store.claim(row, runtime_id=runtime_id)
        with pytest.raises(ValueError, match="process identity"):
            await store.recover_interrupted(guild_id=100, runtime_id=runtime_id)
        assert store.collection.documents == before

    asyncio.run(run())


@pytest.mark.parametrize(
    "age_seconds,starts", [(299.999, True), (300, False), (86400 - 1, False)]
)
def test_queued_update_has_atomic_five_minute_start_deadline(
    monkeypatch, age_seconds, starts
):
    from utils import cwl_post_update_store as module

    async def run():
        store = fixture()
        row, _ = await create(store)
        active = await store.claim(row, runtime_id="one")
        await store.finish(
            active, status="ready", target={"fingerprint": "old"}, has_changes=True
        )
        ready = await store.collection.find_one({"_id": row["_id"]})
        queued = await store.request_update(ready)
        clock = queued["update_requested_at"] + timedelta(seconds=age_seconds)
        monkeypatch.setattr(module, "now", lambda: clock)
        claims = await asyncio.gather(
            store.claim(queued, runtime_id="one"), store.claim(queued, runtime_id="two")
        )
        assert sum(item is not None for item in claims) == int(starts)
        final = await store.collection.find_one({"_id": row["_id"]})
        assert final["status"] == ("updating" if starts else "failed")
        if not starts:
            assert final["error"] == "Not updated. Preview again."
        else:
            monkeypatch.setattr(module, "now", lambda: clock + timedelta(days=1))
            assert await store.claim(queued, runtime_id="late") is None
            assert (await store.collection.find_one({"_id": row["_id"]}))[
                "status"
            ] == "updating"

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"pool": "other"}, "Select Main or Lazy and which months"),
        ({"future_months": 1}, "Select Main or Lazy and which months"),
        ({"cycle": "2026-13"}, "Select the month"),
        ({"season_id": "invalid"}, "Invalid season or saved settings"),
        ({"generation": ""}, "Invalid season or saved settings"),
        ({"generation": []}, "Invalid season or saved settings"),
    ],
)
def test_malformed_review_fields_keep_rejection_without_technical_copy(changes, message):
    async def run():
        store = fixture()
        with pytest.raises(ValueError) as raised:
            await create(store, **changes)
        assert str(raised.value) == message
        assert store.collection.documents == {}
        assert store.collection.indexes == []

    asyncio.run(run())
