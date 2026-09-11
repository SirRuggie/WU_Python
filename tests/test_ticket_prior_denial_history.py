"""Store-level coverage for the unbounded automatic prior-denial lookup."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.commands import ticket_runtime
from extensions.commands.tickets import schema, store


NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def _value_matches(value, condition):
    if not isinstance(condition, dict):
        if isinstance(value, list):
            return condition in value or value == condition
        return value == condition
    for operator, expected in condition.items():
        if operator == "$in":
            values = value if isinstance(value, list) else [value]
            if not any(item in expected for item in values):
                return False
        elif operator == "$ne":
            if value == expected:
                return False
        elif operator == "$gt":
            if not isinstance(value, datetime) or value <= expected:
                return False
        elif operator == "$type":
            if expected != "date" or not isinstance(value, datetime):
                return False
        else:  # Keep this fake honest when the repository query changes.
            raise AssertionError(f"unsupported query operator: {operator}")
    return True


def _matches(document, query):
    for key, condition in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in condition):
                return False
            continue
        if not _value_matches(document.get(key), condition):
            return False
    return True


class _Tickets:
    def __init__(self, documents):
        self.documents = list(documents)
        self.calls = []

    async def find_one(self, query, *, sort):
        self.calls.append((deepcopy(query), list(sort)))
        matches = [document for document in self.documents if _matches(document, query)]
        for key, direction in reversed(sort):
            matches.sort(key=lambda document, key=key: document[key], reverse=direction < 0)
        return deepcopy(matches[0]) if matches else None


def _ticket(identifier, *, created_at, status="open", user_id=100, tags=("#ABC123",)):
    document = schema.new_ticket_document(
        ticket_type="main",
        ticket_number=1,
        guild_id=10,
        public_thread_id=1000,
        public_parent_id=1001,
        staff_thread_id=1002,
        staff_parent_id=1003,
        user_id=user_id,
        username="Applicant",
        player_tags=tags,
        created_at=created_at,
        status=status,
        source={"guild_id": 10, "channel_id": 2000},
    )
    document["_id"] = identifier
    document["runtime"] = ticket_runtime.THREAD_RUNTIME
    return document


def _mongo(*documents):
    return SimpleNamespace(tickets=_Tickets(documents))


def _pair(mongo, *, user_id=100, tags=("#ABC123",)):
    return asyncio.run(store.denial_history_pair_for(mongo, user_id=user_id, player_tags=tags))


def test_denial_history_pair_matches_older_denied_then_later_open():
    denied = _ticket("denied", created_at=NOW, status="denied")
    later = _ticket("later", created_at=NOW + timedelta(minutes=1))

    pair = _pair(_mongo(denied, later))

    assert [document["_id"] for document in pair] == ["denied", "later"]


def test_denial_history_pair_requires_two_tickets_and_a_denial():
    only_denied = _ticket("denied", created_at=NOW, status="denied")
    closed = _ticket("closed", created_at=NOW, status="closed")
    later = _ticket("later", created_at=NOW + timedelta(minutes=1))

    assert _pair(_mongo(only_denied)) is None
    assert _pair(_mongo(closed, later)) is None


def test_denial_history_pair_requires_strictly_later_timestamp_and_identity():
    denied = _ticket("denied", created_at=NOW, status="denied")
    equal_time = _ticket("equal", created_at=NOW)
    other_identity = _ticket(
        "other", created_at=NOW + timedelta(minutes=1), user_id=200, tags=("#OTHER",)
    )

    assert _pair(_mongo(denied, equal_time)) is None
    assert _pair(_mongo(denied, other_identity)) is None


def test_denial_history_pair_sorts_out_of_order_input_by_canonical_creation_time():
    oldest_denial = _ticket("oldest-denial", created_at=NOW, status="denied")
    newer_denial = _ticket("newer-denial", created_at=NOW + timedelta(minutes=2), status="denied")
    first_later = _ticket("first-later", created_at=NOW + timedelta(minutes=1))
    latest = _ticket("latest", created_at=NOW + timedelta(minutes=3))

    pair = _pair(_mongo(latest, newer_denial, first_later, oldest_denial))

    assert [document["_id"] for document in pair] == ["oldest-denial", "first-later"]


def test_denial_history_pair_is_not_limited_to_the_newest_ten_records():
    denied = _ticket("denied", created_at=NOW, status="denied")
    intervening = [
        _ticket(f"intervening-{number}", created_at=NOW + timedelta(minutes=number))
        for number in range(1, 12)
    ]
    later = _ticket("later", created_at=NOW + timedelta(minutes=12))
    mongo = _mongo(denied, later, *reversed(intervening))

    pair = _pair(mongo)

    assert [document["_id"] for document in pair] == ["denied", "intervening-1"]
    assert len(mongo.tickets.calls) == 2
    assert all("limit" not in query for query, _sort in mongo.tickets.calls)


def test_denial_history_pair_matches_normalized_verified_player_tag_across_discord_ids():
    denied = _ticket("denied", created_at=NOW, status="denied", user_id=100, tags=("abc123",))
    later = _ticket(
        "later", created_at=NOW + timedelta(minutes=1), user_id=200, tags=("#ABC123",)
    )

    pair = _pair(_mongo(denied, later), user_id=200, tags=("abc123",))

    assert [document["_id"] for document in pair] == ["denied", "later"]
