"""The optional published assignment bridge never delays or fails /todo."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands import todo
from utils import clan_history, cwl_member_client, todo_data
from utils.constants import WARRIORS_UNITED_GUILD_ID


def published_view():
    return {
        "published": {"version": 2},
        "assignments": [
            {"tag": " #player ", "assigned_clan_tag": " #beta ", "assigned_clan_name": "Beta"},
            {"tag": "#UNLINKED", "assigned_clan_tag": "#OTHER"},
            {"tag": "#NOCLAN", "assigned_clan_tag": None},
            None,
        ],
    }


def test_bridge_uses_wu_guild_including_dm_calls_and_does_not_load_accounts(monkeypatch):
    request = AsyncMock(return_value=published_view())
    monkeypatch.setattr(cwl_member_client, "request", request)
    result = asyncio.run(todo._load_published_assignments(77))
    request.assert_awaited_once_with(
        "view", user_id=77, guild_id=WARRIORS_UNITED_GUILD_ID, include_accounts=False,
    )
    assert str(WARRIORS_UNITED_GUILD_ID) == "644963518025826315"
    assert result == {" #player ": [(" #beta ", "Beta")], "#UNLINKED": [("#OTHER", None)]}


@pytest.mark.parametrize("published", [None, {}])
def test_bridge_ignores_assignments_without_a_live_publication(monkeypatch, published):
    request = AsyncMock(return_value={**published_view(), "published": published})
    monkeypatch.setattr(cwl_member_client, "request", request)
    assert asyncio.run(todo._load_published_assignments(77)) == {}
    assert request.await_count == 1


def test_bridge_failure_logs_one_line_and_returns_no_assignments(monkeypatch, capsys):
    request = AsyncMock(side_effect=cwl_member_client.MemberClientError("fake\nerror"))
    monkeypatch.setattr(cwl_member_client, "request", request)
    assert asyncio.run(todo._load_published_assignments(77)) == {}
    assert capsys.readouterr().out.splitlines() == [
        "[todo] published assignments unavailable: MemberClientError",
    ]
    assert request.await_count == 1


def test_bridge_timeout_is_three_seconds_and_cancels_the_read(monkeypatch, capsys):
    cancelled = []
    real_wait_for = asyncio.wait_for

    async def request(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    async def short_timeout(awaitable, *, timeout):
        assert timeout == 3
        return await real_wait_for(awaitable, timeout=0.001)

    monkeypatch.setattr(cwl_member_client, "request", request)
    monkeypatch.setattr(todo.asyncio, "wait_for", short_timeout)
    assert asyncio.run(todo._load_published_assignments(77)) == {}
    assert cancelled == [True]
    assert capsys.readouterr().out.splitlines() == [
        "[todo] published assignments unavailable: TimeoutError",
    ]


@pytest.mark.parametrize("bridge_fails", [False, True])
def test_load_keeps_bridge_parallel_and_failure_preserves_prior_candidates(monkeypatch, bridge_fails):
    account = todo_data.Account("#PLAYER", "Player", "#HOME", "Home")
    history = clan_history.ClanCandidate("#HISTORY", "History")
    real_load = clan_history.load_candidates
    entered = set()
    load_calls = []
    seen_views = {}
    request_calls = []
    release = None
    mongo = object()

    async def accounts(*args, **kwargs):
        entered.add("players")
        return [account], []

    async def candidates(store, tags, **kwargs):
        load_calls.append((store, kwargs))
        if store is not None:
            entered.add("history")
            return {"#PLAYER": [history]}
        return await real_load(store, tags, **kwargs)

    async def watch(*args, **kwargs):
        entered.add("watch")

    async def request(*args, **kwargs):
        request_calls.append((args, kwargs))
        entered.add("bridge")
        await release.wait()
        if bridge_fails:
            raise cwl_member_client.MemberClientError("fake outage")
        return published_view()

    def view(name):
        async def build(*args, **kwargs):
            seen_views[name] = kwargs.get("candidates")
            return todo_data.ViewData()
        return build

    monkeypatch.setattr(todo_data, "cache_get", lambda key: ["#PLAYER"] if key == "links:77" else None)
    monkeypatch.setattr(todo_data, "fetch_accounts", accounts)
    monkeypatch.setattr(clan_history, "load_candidates", candidates)
    monkeypatch.setattr(clan_history, "watch_players", watch)
    monkeypatch.setattr(clan_history, "record_presence", AsyncMock())
    monkeypatch.setattr(todo, "_load_clan_logos", AsyncMock())
    monkeypatch.setattr(cwl_member_client, "request", request)
    monkeypatch.setattr(todo_data, "build_war_view", view("war"))
    monkeypatch.setattr(todo_data, "build_cwl_view", view("cwl"))
    monkeypatch.setattr(todo_data, "build_raid_view", view("raid"))
    monkeypatch.setattr(todo_data, "build_blocked_view", view("blocked"))
    monkeypatch.setattr(todo, "_load_fwa_records", AsyncMock(return_value={}))

    async def exercise():
        nonlocal release
        release = asyncio.Event()
        task = asyncio.create_task(todo._load(object(), object(), 77, mongo=mongo))
        for _ in range(50):
            if entered == {"players", "history", "watch", "bridge"}:
                break
            await asyncio.sleep(0)
        assert entered == {"players", "history", "watch", "bridge"}
        release.set()
        return await task

    data, problem, fwa = asyncio.run(exercise())
    assert problem is None and fwa == {}
    assert set(data) == set(todo.VIEW_ORDER)
    assert len(request_calls) == 1
    assert request_calls[0][1]["guild_id"] == WARRIORS_UNITED_GUILD_ID
    assert load_calls[0] == (mongo, {})
    for name in ["war", "cwl", "blocked"]:
        expected = [history] if bridge_fails else [
            history, clan_history.ClanCandidate("#BETA", "Beta", check_war=False, check_cwl=True),
        ]
        assert seen_views[name] == {"#PLAYER": expected}
    assert len(load_calls) == (1 if bridge_fails else 2)
    assert seen_views["raid"] is None


@pytest.mark.parametrize("failure", [RuntimeError("fake unavailable"), TimeoutError()])
def test_actual_load_bridge_failure_renders_prior_view_with_identical_game_and_history_reads(
    monkeypatch, failure,
):
    """Use real view builders/rendering; every transport and Mongo read is fake."""
    calls = []
    now = datetime.now(timezone.utc)
    member = SimpleNamespace(tag="#PLAYER", attacks=[object()])

    class Side:
        tag = "#HOME"
        name = "Home"
        badge = None
        members = [member]

        @staticmethod
        def get_member(tag):
            return member if tag == "#PLAYER" else None

    war = SimpleNamespace(
        state="inWar", clan=Side(),
        opponent=SimpleNamespace(tag="#OPP", name="Opponent", members=[]),
        attacks_per_member=2, start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=12),
    )

    class Client:
        async def get_player(self, tag):
            calls.append(("player", tag))
            return SimpleNamespace(
                tag=tag, name="Player", town_hall=17,
                clan=SimpleNamespace(tag="#HOME", name="Home", badge=None),
            )

        async def get_clan_war(self, tag):
            calls.append(("war", tag))
            return war

        async def get_league_group(self, tag):
            calls.append(("cwl", tag))
            return SimpleNamespace(state="notInWar", rounds=[])

        async def get_raid_log(self, tag, *, limit):
            calls.append(("raid", tag, limit))
            return []

    class History:
        def find(self, query):
            calls.append(("history", tuple(query["player_tag"]["$in"])))
            return self

        async def to_list(self, length=None):
            return []

    mongo = SimpleNamespace(player_clan_candidates=History())
    request = AsyncMock(return_value={"published": None, "assignments": []})
    monkeypatch.setattr(cwl_member_client, "request", request)
    monkeypatch.setattr(todo, "resolve_tags", AsyncMock(return_value=["#PLAYER"]))
    monkeypatch.setattr(todo, "_load_clan_logos", AsyncMock())
    monkeypatch.setattr(todo, "_load_fwa_records", AsyncMock(return_value={}))
    monkeypatch.setattr(clan_history, "ensure_indexes", AsyncMock(return_value=True))
    monkeypatch.setattr(clan_history, "watch_players", AsyncMock())
    monkeypatch.setattr(clan_history, "record_presence", AsyncMock())
    try:
        todo_data._cache.clear()
        before, problem, fwa = asyncio.run(todo._load(object(), Client(), 77, mongo=mongo))
        assert problem is None and fwa == {}
        original_calls = list(calls)
        expected = {
            view: [component.build() for component in todo.render_dashboard(
                view, 0, before, checked_at=123,
            )]
            for view in todo.VIEW_ORDER
        }
        calls.clear()
        todo_data._cache.clear()
        request.side_effect = failure
        after, problem, fwa = asyncio.run(todo._load(object(), Client(), 77, mongo=mongo))
        assert problem is None and fwa == {}
        assert calls == original_calls
        assert len([call for call in calls if call[0] == "history"]) == 1
        assert request.await_count == 2
        assert clan_history.watch_players.await_count == 2
        assert clan_history.record_presence.await_count == 2
        assert clan_history.ensure_indexes.await_count == 2
        assert after == before
        assert {
            view: [component.build() for component in todo.render_dashboard(
                view, 0, after, checked_at=123,
            )]
            for view in todo.VIEW_ORDER
        } == expected
    finally:
        todo_data._cache.clear()
