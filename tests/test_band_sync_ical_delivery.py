import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.tasks import band_sync_ical as sync


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue

        exists = key in document
        actual = document.get(key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$exists" and exists is not bool(operand):
                    return False
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$ne" and actual == operand:
                    return False
                if operator == "$lte" and (actual is None or actual > operand):
                    return False
            continue
        if actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}

    async def find_one(self, query, projection=None):
        for document in self.documents.values():
            if _matches(document, query):
                if projection:
                    return {key: deepcopy(value) for key, value in document.items()
                            if key == "_id" or projection.get(key)}
                return deepcopy(document)
        return None

    def find(self, query, projection=None):
        return FakeCursor(
            document for document in self.documents.values()
            if _matches(document, query)
        )

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise sync.DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, upsert=False):
        target = None
        for document in self.documents.values():
            if _matches(document, query):
                target = document
                break
        if target is None:
            return SimpleNamespace(modified_count=0, upserted_id=None)

        for key, value in update.get("$set", {}).items():
            target[key] = deepcopy(value)
        for key, instruction in update.get("$addToSet", {}).items():
            values = instruction.get("$each", [])
            target.setdefault(key, [])
            for value in values:
                if value not in target[key]:
                    target[key].append(deepcopy(value))
        return SimpleNamespace(modified_count=1, upserted_id=None)


class FakeRest:
    def __init__(self, failures=None):
        self.failures = dict(failures or {})
        self.attempts = []

    async def fetch_user(self, user_id):
        return SimpleNamespace(id=user_id)

    async def create_dm_channel(self, user_id):
        return user_id

    async def create_message(self, channel, embed):
        self.attempts.append(channel)
        remaining = self.failures.get(channel, 0)
        if remaining:
            self.failures[channel] = remaining - 1
            raise RuntimeError("temporary Discord failure")


def _event(uid="sync-1", start=None):
    start = start or datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    return {
        "uid": uid,
        "start": start,
        "end": start + timedelta(minutes=40),
        "summary": "FWA high sync",
        "calendar": "Sync3",
    }


def _config(recipients):
    return {
        "dm_user_ids": recipients,
        "offsets": [60, 10],
        "announce_on_discovery": True,
    }


def _deliveries(collection):
    return [document for document in collection.documents.values()
            if document.get("kind") == "delivery"]


def test_dm_all_deduplicates_recipients_in_configured_order(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))

    sent = asyncio.run(sync.dm_all([2, "2", 1, 2], object()))

    assert sent == 2
    assert rest.attempts == [2, 1]


def test_partial_delivery_retries_only_failed_recipient(monkeypatch):
    rest = FakeRest({2: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    collection = FakeCollection()
    event = _event()
    now = event["start"] - timedelta(hours=2)

    asyncio.run(sync.process_event(collection, event, _config([1, 2]), now))

    statuses = {document["recipient_id"]: document["status"]
                for document in _deliveries(collection)}
    assert statuses == {1: "sent", 2: "failed"}
    assert rest.attempts == [1, 2]

    asyncio.run(sync.process_event(
        collection, event, _config([1, 2]), now + timedelta(minutes=1)
    ))

    statuses = {document["recipient_id"]: document["status"]
                for document in _deliveries(collection)}
    assert statuses == {1: "sent", 2: "sent"}
    assert rest.attempts == [1, 2, 2]


def test_stale_pending_lease_is_reclaimed(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    delivery = sync._delivery_doc(event, sync.DISCOVERY_OFFSET, 7)
    delivery.update({
        "status": "pending",
        "lease_until": datetime.now(timezone.utc) - timedelta(seconds=1),
    })
    collection = FakeCollection([delivery])

    asyncio.run(sync.deliver_outstanding(collection, event))

    assert collection.documents[delivery["_id"]]["status"] == "sent"
    assert rest.attempts == [7]


def test_zero_delivery_reschedule_remains_retryable(monkeypatch):
    rest = FakeRest({9: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_event = _event(start=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc))
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    collection = FakeCollection([state])
    moved = _event(start=old_event["start"] + timedelta(hours=1))
    now = moved["start"] - timedelta(hours=2)

    asyncio.run(sync.process_event(collection, moved, _config([9]), now))

    state_after_failure = collection.documents[sync._event_state_id(moved["uid"])]
    delivery = _deliveries(collection)[0]
    assert sync.normalize_start(state_after_failure["start_at"]) == moved["start"]
    assert delivery["delivery_type"] == "change"
    assert delivery["status"] == "failed"
    assert rest.attempts == [9]

    asyncio.run(sync.process_event(
        collection, moved, _config([9]), now + timedelta(minutes=1)
    ))

    assert collection.documents[delivery["_id"]]["status"] == "sent"
    assert rest.attempts == [9, 9]


def test_startup_recovers_from_mongo_failure_and_starts_one_poller(monkeypatch):
    class StartupCollection:
        def __init__(self):
            self.find_failures = 1
            self.index_calls = 0

        async def create_index(self, *args, **kwargs):
            self.index_calls += 1
            return "ttl_expire_at"

        async def find_one(self, query):
            if self.find_failures:
                self.find_failures -= 1
                raise RuntimeError("Mongo starting")
            return {"_id": sync.CONFIG_ID, "enabled": False}

    collection = StartupCollection()

    class Database:
        def get_collection(self, _name):
            return collection

    class Mongo:
        def get_database(self, _name):
            return Database()

    loop_started = asyncio.Event()
    loop_calls = 0

    async def fake_poller(_mongo):
        nonlocal loop_calls
        loop_calls += 1
        loop_started.set()
        await asyncio.Event().wait()

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(sync, "mongo_client", Mongo())
    monkeypatch.setattr(sync, "poller_task", None)
    monkeypatch.setattr(sync, "poller_loop", fake_poller)

    reconciler = sync.StartupReconciler(
        "ical_test",
        sync._reconcile_ical_startup,
        retry_delays=(0,),
        sleep=no_wait,
    )

    async def scenario():
        await reconciler.start()
        await loop_started.wait()
        await sync._reconcile_ical_startup()
        assert sync.poller_task and not sync.poller_task.done()
        sync.poller_task.cancel()
        await asyncio.gather(sync.poller_task, return_exceptions=True)
        sync.poller_task = None

    asyncio.run(scenario())

    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 2
    assert loop_calls == 1
    assert collection.index_calls == 3


def test_shutdown_awaits_poller_cancellation(monkeypatch):
    cancelled = asyncio.Event()

    async def poller():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def scenario():
        monkeypatch.setattr(sync, "startup_reconciler", None)
        monkeypatch.setattr(sync, "poller_task", asyncio.create_task(poller()))
        await asyncio.sleep(0)
        await sync.on_bot_stopping(SimpleNamespace())
        assert cancelled.is_set()
        assert sync.poller_task is None

    asyncio.run(scenario())
