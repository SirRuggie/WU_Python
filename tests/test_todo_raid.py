import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import coc
import pytest

from utils import todo_data


@pytest.fixture(autouse=True)
def clear_todo_cache():
    todo_data._cache.clear()
    yield
    todo_data._cache.clear()


class _RaidEntry:
    def __init__(self, *, state="ongoing", attack_log=None, members=None):
        self.state = state
        self.attack_log = list(attack_log or [])
        self.members = list(members or [])
        self.attack_count = sum(member.attack_count for member in self.members)
        self.end_time = None

    def get_member(self, player_tag):
        return next(
            (member for member in self.members if member.tag == player_tag),
            None,
        )


def _account(player_tag, clan_tag):
    return todo_data.Account(
        tag=player_tag,
        name=player_tag.removeprefix("#"),
        clan_tag=clan_tag,
        clan_name=clan_tag.removeprefix("#"),
        town_hall=17,
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 8, 7, 6, 59, 59, tzinfo=timezone.utc), False),
        (datetime(2026, 8, 7, 7, 0, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 10, 6, 59, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 10, 7, 0, 0, tzinfo=timezone.utc), False),
    ],
)
def test_raid_weekend_window_boundaries(now, expected):
    assert todo_data._raid_weekend_is_open(now) is expected


def test_unstarted_raid_rechecks_after_active_ttl_and_becomes_started(monkeypatch):
    # Live unstarted shape: Supercell can assign a defense before this clan
    # opts in. Neither that defense nor raidsCompleted makes it "started".
    unstarted = _RaidEntry(attack_log=[])
    unstarted.defense_log = [object()]
    unstarted.completed_raid_count = 1

    # Opt-in assigns the offensive target before the first actual attack.
    started = _RaidEntry(
        state=SimpleNamespace(value="ongoing"),
        attack_log=[object()],
        members=[],
    )
    assert started.attack_count == 0

    class Client:
        calls = 0

        async def get_raid_log(self, _clan_tag, *, limit):
            assert limit == 1
            self.calls += 1
            return [unstarted] if self.calls == 1 else [started]

    client = Client()
    before = time.monotonic()
    first = asyncio.run(todo_data._get_raid(client, "#CLAN"))
    after = time.monotonic()

    assert first == ("not_started", None)
    assert client.calls == 1
    expires_at, filled_at, cached = todo_data._cache["raid:#CLAN"]
    assert before + todo_data.TTL_RAID_ACTIVE <= expires_at
    assert expires_at <= after + todo_data.TTL_RAID_ACTIVE
    assert cached == first

    assert asyncio.run(todo_data._get_raid(client, "#CLAN")) == first
    assert client.calls == 1

    todo_data._cache["raid:#CLAN"] = (
        time.monotonic() - 1,
        filled_at,
        cached,
    )
    second = asyncio.run(todo_data._get_raid(client, "#CLAN"))

    assert second == ("raid", started)
    assert client.calls == 2


@pytest.mark.parametrize("response", [[], [_RaidEntry(state="ended")]])
def test_missing_current_entry_is_short_lived_during_open_weekend(
    monkeypatch, response
):
    monkeypatch.setattr(todo_data, "_raid_weekend_is_open", lambda: True)
    cached = []
    monkeypatch.setattr(
        todo_data,
        "cache_put",
        lambda key, value, ttl: cached.append((key, value, ttl)),
    )

    class Client:
        async def get_raid_log(self, _clan_tag, *, limit):
            assert limit == 1
            return response

    result = asyncio.run(todo_data._get_raid(Client(), "#CLAN"))

    assert result == ("not_started", None)
    assert cached == [
        ("raid:#CLAN", result, todo_data.TTL_RAID_ACTIVE)
    ]


def test_ended_entry_keeps_long_negative_cache_outside_weekend(monkeypatch):
    monkeypatch.setattr(todo_data, "_raid_weekend_is_open", lambda: False)
    monkeypatch.setattr(todo_data, "_seconds_until_raid_opens", lambda: 12_345)
    cached = []
    monkeypatch.setattr(
        todo_data,
        "cache_put",
        lambda key, value, ttl: cached.append((key, value, ttl)),
    )

    class Client:
        async def get_raid_log(self, _clan_tag, *, limit):
            assert limit == 1
            return [_RaidEntry(state="ended")]

    result = asyncio.run(todo_data._get_raid(Client(), "#CLAN"))

    assert result == ("none", None)
    assert cached == [("raid:#CLAN", result, 12_345)]


@pytest.mark.parametrize(
    ("weekend_open", "expected_kind", "expected_ttl"),
    [(True, "not_started", todo_data.TTL_RAID_ACTIVE), (False, "none", 12_345)],
)
def test_not_found_uses_weekend_aware_classification(
    monkeypatch, weekend_open, expected_kind, expected_ttl
):
    monkeypatch.setattr(
        todo_data, "_raid_weekend_is_open", lambda: weekend_open
    )
    monkeypatch.setattr(todo_data, "_seconds_until_raid_opens", lambda: 12_345)
    cached = []
    monkeypatch.setattr(
        todo_data,
        "cache_put",
        lambda key, value, ttl: cached.append((key, value, ttl)),
    )

    class Client:
        async def get_raid_log(self, _clan_tag, *, limit):
            assert limit == 1
            raise coc.NotFound(data={"reason": "notFound"})

    result = asyncio.run(todo_data._get_raid(Client(), "#CLAN"))

    assert result == (expected_kind, None)
    assert cached == [("raid:#CLAN", result, expected_ttl)]


def test_raid_403_is_an_error_not_not_started(monkeypatch):
    cached = []
    monkeypatch.setattr(
        todo_data,
        "cache_put",
        lambda key, value, ttl: cached.append((key, value, ttl)),
    )

    class Client:
        async def get_raid_log(self, _clan_tag, *, limit):
            assert limit == 1
            raise coc.PrivateWarLog(data={"reason": "accessDenied"})

    result = asyncio.run(todo_data._get_raid(Client(), "#CLAN"))

    assert result == ("error", None)
    assert cached == [("raid:#CLAN", result, todo_data.TTL_ERROR)]


def test_all_unstarted_clans_have_specific_unavailable_message(monkeypatch):
    requested = []

    async def not_started(_client, clan_tag):
        requested.append(clan_tag)
        return "not_started", None

    monkeypatch.setattr(todo_data, "_get_raid", not_started)
    view = asyncio.run(todo_data.build_raid_view(
        object(),
        [_account("#ONE", "#FIRST"), _account("#TWO", "#SECOND")],
    ))

    assert sorted(requested) == ["#FIRST", "#SECOND"]
    assert view.rows == []
    assert view.notes == []
    assert view.ok is True
    assert view.unavailable == "None of your clans have started Raid Weekend yet."


def test_mixed_started_and_unstarted_clans_only_show_started_rows(monkeypatch):
    started = _RaidEntry(attack_log=[object()], members=[])

    async def raid_for(_client, clan_tag):
        if clan_tag == "#STARTED":
            return "raid", started
        return "not_started", None

    monkeypatch.setattr(todo_data, "_get_raid", raid_for)
    view = asyncio.run(todo_data.build_raid_view(
        object(),
        [
            _account("#PLAYER1", "#STARTED"),
            _account("#PLAYER2", "#PENDING"),
        ],
    ))

    assert [
        (row.tag, row.clan_tag, row.used, row.limit)
        for row in view.rows
    ] == [("#PLAYER1", "#STARTED", 0, 5)]
    assert view.unavailable == ""
    assert view.notes == []
    assert view.ok is True


def test_completed_started_clan_remains_caught_up_when_another_is_unstarted(
    monkeypatch,
):
    completed_member = SimpleNamespace(
        tag="#DONE",
        attack_count=5,
        attack_limit=5,
        bonus_attack_limit=0,
    )
    started = _RaidEntry(
        attack_log=[object()],
        members=[completed_member],
    )

    async def raid_for(_client, clan_tag):
        if clan_tag == "#STARTED":
            return "raid", started
        return "not_started", None

    monkeypatch.setattr(todo_data, "_get_raid", raid_for)
    view = asyncio.run(todo_data.build_raid_view(
        object(),
        [_account("#DONE", "#STARTED"), _account("#WAIT", "#PENDING")],
    ))

    assert view.rows == []
    assert view.unavailable == ""
    assert view.ok is True
