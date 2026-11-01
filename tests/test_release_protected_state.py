from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from tools.release_protected_state import compare_protected

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def fixture():
    old = {
        "active": [["1", "#P", 7]],
        "digest": "strict",
        "replacement": {"1": [["#P", 7, True, 2, False]]},
    }
    new = deepcopy(old)
    new["replacement"]["1"][0][4] = True
    p = {
        "guild_id": 1,
        "player_tag": "#P",
        "current_clan_tag": "#CLAN",
        "roster_seen_at": NOW - timedelta(minutes=2),
        "roster_observed_at": NOW - timedelta(minutes=2),
        "streak_count": 3,
    }
    q = {k: v for k, v in p.items() if k != "current_clan_tag"}
    q.update(
        departed_clan_tag="#CLAN",
        departed_last_seen_at=p["roster_seen_at"],
        roster_observed_at=NOW,
    )
    return old, new, {("1", "#P"): p}, {("1", "#P"): q}


def compare(items):
    return compare_protected(
        *items, started=NOW - timedelta(seconds=1), ended=NOW + timedelta(seconds=1)
    )


def test_only_exact_sync_departure_is_accepted():
    data = fixture()
    assert len(compare(data)) == 1
    assert compare((data[0], data[0], {}, {})) == []


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "active",
        "listed",
        "priority",
        "membership",
        "raw",
        "missing",
        "late",
        "reverse",
    ],
)
def test_every_other_change_fails_closed(change):
    old, new, p, q = fixture()
    if change == "digest":
        new["digest"] = "changed"
    elif change == "active":
        new["active"][0][2] += 1
    elif change == "listed":
        new["replacement"]["1"][0][2] = False
    elif change == "priority":
        new["replacement"]["1"][0][3] += 1
    elif change == "membership":
        new["replacement"]["1"].clear()
    elif change == "raw":
        q[("1", "#P")]["streak_count"] += 1
    elif change == "missing":
        p.clear()
    elif change == "late":
        q[("1", "#P")]["roster_observed_at"] = NOW + timedelta(minutes=1)
    elif change == "reverse":
        old, new = new, old
    with pytest.raises(ValueError):
        compare((old, new, p, q))


def test_existing_marked_departure_is_preserved_exactly():
    old, new, p, q = fixture()
    p[("1", "#P")].update(
        departed_clan_tag="#ORIGINAL",
        replacement_clan_tag="#ORIGINAL",
        departed_last_seen_at=NOW - timedelta(days=1),
    )
    q[("1", "#P")].update(
        departed_clan_tag="#ORIGINAL",
        replacement_clan_tag="#ORIGINAL",
        departed_last_seen_at=NOW - timedelta(days=1),
    )
    assert len(compare((old, new, p, q))) == 1
