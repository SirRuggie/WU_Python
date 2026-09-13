"""`store.browse`/`store.browse_count` -- the console's Browse tickets panel.

A self-contained fake collection lives here rather than reusing the one in
`tests/test_ticket_storage_foundation.py`: that file is off limits for this
change, and `store.browse` is the first caller in `store.py` to use
`.skip()`, which the shared fake `Cursor` there does not implement.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.commands import ticket_runtime
from extensions.commands.tickets import schema, store

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _matches(document: dict, filt: dict) -> bool:
    for key, expected in filt.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$gte" in expected and not (value is not None and value >= expected["$gte"]):
                return False
            if "$lt" in expected and not (value is not None and value < expected["$lt"]):
                return False
        elif value != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, spec):
        for field, direction in reversed(spec):
            self.documents.sort(
                key=lambda item: (item.get(field) is None, item.get(field)),
                reverse=direction < 0,
            )
        return self

    def skip(self, amount):
        self.documents = self.documents[amount:]
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    async def to_list(self, length=None):
        return list(self.documents if length is None else self.documents[:length])


class _Collection:
    def __init__(self, documents):
        self.documents = list(documents)
        self.queries: list[dict] = []

    def find(self, filt, projection=None):
        self.last_projection = projection
        self.queries.append(filt)
        return _Cursor([doc for doc in self.documents if _matches(doc, filt)])

    async def count_documents(self, filt):
        self.queries.append(filt)
        return sum(1 for doc in self.documents if _matches(doc, filt))


def _mongo(*documents):
    return SimpleNamespace(tickets=_Collection(documents))


def _ticket(
    number: int,
    *,
    status: str = "open",
    ticket_type: str = "main",
    days_ago: int = 0,
    source: dict | None = None,
) -> dict:
    doc = schema.new_ticket_document(
        ticket_type=ticket_type,
        ticket_number=number,
        guild_id=10,
        public_thread_id=1000 + number,
        public_parent_id=20,
        staff_thread_id=2000 + number,
        staff_parent_id=21,
        user_id=3000 + number,
        username=f"Applicant {number}",
        player_tags=(f"TAG{number}",),
        created_at=NOW - timedelta(days=days_ago),
        status=status,
        source=source or ({"guild_id": 10, "channel_id": 999} if status != "open" else None),
    )
    doc["runtime"] = ticket_runtime.THREAD_RUNTIME
    return doc


def test_browse_filter_omits_status_key_for_all_so_it_implies_thread_v2_created():
    """A bare "All status" browse must not carry a `status` key at all --
    that is what lets it use `thread_v2_created` (whose partial filter is
    just RUNTIME_FILTER) instead of falling back to an in-memory sort, since
    `thread_v2_status_created` needs equality on `status` to serve the sort.
    """
    filt = store._browse_filter(None, None, None)
    assert "status" not in filt
    assert "ticket_type" not in filt
    assert "created_at" not in filt
    assert filt == store.RUNTIME_FILTER


def test_browse_filter_adds_status_in_and_type_in_and_created_gte():
    since = NOW - timedelta(days=7)
    filt = store._browse_filter(["open"], ["fwa"], since)
    assert filt["status"] == {"$in": ["open"]}
    assert filt["ticket_type"] == {"$in": ["fwa"]}
    assert filt["created_at"] == {"$gte": since}
    for key, value in store.RUNTIME_FILTER.items():
        assert filt[key] == value


def test_browse_returns_newest_first_and_respects_page_and_page_size():
    tickets = [_ticket(index, days_ago=index) for index in range(1, 6)]  # 1 newest .. 5 oldest
    mongo = _mongo(*tickets)

    page_one = asyncio.run(store.browse(mongo, page=1, page_size=2))
    assert [doc["ticket_number"] for doc in page_one] == [1, 2]

    page_two = asyncio.run(store.browse(mongo, page=2, page_size=2))
    assert [doc["ticket_number"] for doc in page_two] == [3, 4]

    page_three = asyncio.run(store.browse(mongo, page=3, page_size=2))
    assert [doc["ticket_number"] for doc in page_three] == [5]


def test_browse_filters_by_status_type_and_since():
    tickets = [
        _ticket(1, status="open", ticket_type="main", days_ago=1),
        _ticket(2, status="approved", ticket_type="main", days_ago=2),
        _ticket(3, status="denied", ticket_type="fwa", days_ago=3),
        _ticket(4, status="open", ticket_type="fwa", days_ago=40),
    ]
    mongo = _mongo(*tickets)

    open_only = asyncio.run(store.browse(mongo, statuses=["open"], page_size=10))
    assert {doc["ticket_number"] for doc in open_only} == {1, 4}

    fwa_only = asyncio.run(store.browse(mongo, ticket_types=["fwa"], page_size=10))
    assert {doc["ticket_number"] for doc in fwa_only} == {3, 4}

    recent = asyncio.run(
        store.browse(mongo, since=NOW - timedelta(days=7), page_size=10)
    )
    assert {doc["ticket_number"] for doc in recent} == {1, 2, 3}


def test_browse_count_ignores_page_and_page_size():
    tickets = [_ticket(index) for index in range(1, 8)]
    mongo = _mongo(*tickets)

    total = asyncio.run(store.browse_count(mongo))
    assert total == 7

    page = asyncio.run(store.browse(mongo, page=1, page_size=3))
    assert len(page) == 3


def test_browse_filter_adds_until_as_lt_alongside_since():
    since = NOW - timedelta(days=60)
    until = NOW - timedelta(days=30)
    filt = store._browse_filter(None, None, since, until)
    assert filt["created_at"] == {"$gte": since, "$lt": until}


def test_browse_filter_until_alone_omits_gte():
    until = NOW - timedelta(days=30)
    filt = store._browse_filter(None, None, None, until)
    assert filt["created_at"] == {"$lt": until}


def test_browse_and_browse_count_respect_the_until_upper_bound():
    tickets = [
        _ticket(1, days_ago=100),
        _ticket(2, days_ago=50),
        _ticket(3, days_ago=10),
    ]
    mongo = _mongo(*tickets)
    since = NOW - timedelta(days=70)
    until = NOW - timedelta(days=20)

    results = asyncio.run(store.browse(mongo, since=since, until=until, page_size=10))
    assert {doc["ticket_number"] for doc in results} == {2}
    assert asyncio.run(store.browse_count(mongo, since=since, until=until)) == 1


def test_browse_and_browse_count_only_see_thread_runtime_tickets():
    thread_ticket = _ticket(1)
    legacy_channel_ticket = {
        **_ticket(2),
        "_id": "ticket_legacy",
        "venue": "channel",
        "runtime": "channel",
    }
    mongo = _mongo(thread_ticket, legacy_channel_ticket)

    results = asyncio.run(store.browse(mongo, page_size=10))
    assert [doc["_id"] for doc in results] == [thread_ticket["_id"]]
    assert asyncio.run(store.browse_count(mongo)) == 1
