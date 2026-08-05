import asyncio
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from extensions.events.channel import ticket_channel_monitor as monitor


class _TicketStoreMongo:
    pass


def test_wait_for_ticket_data_polls_until_persisted(monkeypatch):
    responses = [None, None, {"_id": "ticket_42", "user_id": 7}]
    sleeps = []

    async def fake_find_one(_mongo, _query):
        return responses.pop(0)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(monitor.store, "find_one", fake_find_one)
    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)

    result = asyncio.run(monitor.wait_for_ticket_data(
        _TicketStoreMongo(), 42, attempts=5, delay=0.25,
    ))

    assert result["user_id"] == 7
    assert sleeps == [0.25, 0.25]


def test_wait_for_ticket_data_stops_at_bound(monkeypatch):
    calls = 0

    async def fake_find_one(_mongo, _query):
        nonlocal calls
        calls += 1
        return None

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(monitor.store, "find_one", fake_find_one)
    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)

    result = asyncio.run(monitor.wait_for_ticket_data(
        _TicketStoreMongo(), 42, attempts=3, delay=0,
    ))

    assert result is None
    assert calls == 3


class _ClaimCollection:
    def __init__(self, *, duplicate=False):
        self.duplicate = duplicate
        self.call = None

    async def find_one_and_update(self, query, update, **kwargs):
        self.call = (query, update, kwargs)
        if self.duplicate:
            raise DuplicateKeyError("already claimed")
        return {
            "_id": query["_id"],
            "initial_delivery": {"status": "processing"},
        }


class _ClaimMongo:
    def __init__(self, *, duplicate=False):
        self.ticket_automation_state = _ClaimCollection(duplicate=duplicate)


def test_claim_is_atomic_and_uses_a_lease():
    mongo = _ClaimMongo()
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    doc = {"_id": "42", "channel_id": 42}

    result = asyncio.run(monitor.claim_automation_delivery(mongo, doc, now=now))

    query, update, kwargs = mongo.ticket_automation_state.call
    assert result["initial_delivery"]["status"] == "processing"
    assert query["_id"] == "42"
    assert update["$setOnInsert"] is doc
    assert update["$set"]["initial_delivery.status"] == "processing"
    assert update["$set"]["initial_delivery.lease_until"] == now + monitor.DELIVERY_LEASE
    assert kwargs["upsert"] is True


def test_duplicate_key_means_another_worker_owns_delivery():
    mongo = _ClaimMongo(duplicate=True)

    result = asyncio.run(monitor.claim_automation_delivery(
        mongo, {"_id": "42", "channel_id": 42},
    ))

    assert result is None


def test_send_with_retries_is_bounded(monkeypatch):
    class _Rest:
        def __init__(self):
            self.calls = 0

        async def create_message(self, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary")

    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)
    rest = _Rest()

    asyncio.run(monitor.send_with_retries(rest, channel=42, content="hello"))

    assert rest.calls == 3
    assert sleeps == [
        monitor.DELIVERY_RETRY_DELAY_SECONDS,
        monitor.DELIVERY_RETRY_DELAY_SECONDS,
    ]
