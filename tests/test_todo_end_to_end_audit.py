"""Adversarial end-to-end checks for /todo data association and rendering."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import coc

from extensions.commands import todo
from utils import clan_history, todo_data


def setup_function():
    todo_data._cache.clear()


def teardown_function():
    todo_data._cache.clear()


def _account(*, clan_tag: str = "#HOME") -> todo_data.Account:
    return todo_data.Account(
        tag="#PLAYER",
        name="Player",
        clan_tag=clan_tag,
        clan_name=clan_tag.removeprefix("#"),
        town_hall=17,
    )


def _parsed_official_war(
    *,
    start: datetime,
    end: datetime,
    state: str = "inWar",
    clan_tag: str = "#HOME",
    clan_member: str = "#PLAYER",
    opponent_tag: str = "#ENEMY",
    opponent_member: str = "#OTHER",
):
    """Parse the relevant official `/currentwar` JSON through coc.py itself."""
    stamp = lambda value: value.strftime("%Y%m%dT%H%M%S.000Z")
    side = lambda tag, name, member: {
        "tag": tag,
        "name": name,
        "clanLevel": 20,
        "attacks": 0,
        "stars": 0,
        "destructionPercentage": 0,
        "members": [{
            "tag": member,
            "name": member.removeprefix("#"),
            "townhallLevel": 17,
            "mapPosition": 1,
            "opponentAttacks": 0,
            "bestOpponentAttack": {},
        }],
    }
    raw = {
        "state": state,
        "teamSize": 1,
        "attacksPerMember": 2,
        "preparationStartTime": stamp(start - timedelta(days=1)),
        "startTime": stamp(start),
        "endTime": stamp(end),
        "clan": side(clan_tag, clan_tag.removeprefix("#"), clan_member),
        "opponent": side(
            opponent_tag, opponent_tag.removeprefix("#"), opponent_member
        ),
    }
    return raw, coc.ClanWar(
        data=raw,
        client=SimpleNamespace(raw_attribute=True),
        clan_tag=clan_tag,
    )


def _text(components: list) -> str:
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(child)

    payload = [component.build() for component in components]
    return "\n".join(
        str(node.get("content", ""))
        for node in walk(payload)
        if "content" in node
    )


def test_stale_candidate_cannot_claim_player_found_only_on_opponent_side(monkeypatch):
    """A history candidate must prove membership on that clan's side of its war."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _raw, war = _parsed_official_war(
        start=now - timedelta(hours=2),
        end=now + timedelta(hours=22),
        clan_tag="#OLD",
        clan_member="#OTHER",
        opponent_tag="#HOME",
        opponent_member="#PLAYER",
    )

    async def current_war(_client, clan_tag, **_kwargs):
        return ("war", war) if clan_tag == "#OLD" else ("none", None)

    monkeypatch.setattr(todo_data, "_get_war", current_war)
    candidates = {
        "#PLAYER": [clan_history.ClanCandidate("#OLD", "Old")],
    }

    view = asyncio.run(todo_data.build_war_view(
        object(), [_account()], candidates=candidates,
    ))

    assert view.rows == []


def test_api_deadline_epoch_reaches_the_rendered_discord_timestamp_exactly(monkeypatch):
    """No cache, formatter, grouping, or host timezone may alter the API deadline."""
    raw_end = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(hours=2)
    raw_start = raw_end - timedelta(days=1)
    raw, war = _parsed_official_war(start=raw_start, end=raw_end)

    async def current_war(_client, _clan_tag, **_kwargs):
        return "war", war

    monkeypatch.setattr(todo_data, "_get_war", current_war)
    view = asyncio.run(todo_data.build_war_view(object(), [_account()]))
    expected = int(raw_end.replace(tzinfo=timezone.utc).timestamp())

    assert len(view.rows) == 1
    assert war._raw_data["endTime"] == raw["endTime"]
    assert view.rows[0].ends_at == expected
    data = {key: todo_data.ViewData() for key in todo.VIEW_ORDER}
    data[todo.VIEW_WAR] = view
    rendered = _text(todo.render_dashboard(todo.VIEW_WAR, 0, data))
    assert f"ends <t:{expected}:R>" in rendered


def test_parsed_preparation_start_reaches_render_and_expired_battle_is_removed(monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    raw, preparation = _parsed_official_war(
        start=now + timedelta(minutes=30),
        end=now + timedelta(hours=24, minutes=30),
        state="preparation",
    )

    async def prep_war(_client, _clan_tag, **_kwargs):
        return "war", preparation

    monkeypatch.setattr(todo_data, "_get_war", prep_war)
    view = asyncio.run(todo_data.build_war_view(object(), [_account()]))
    expected_start = int(
        preparation.start_time.time.replace(tzinfo=timezone.utc).timestamp()
    )
    assert raw["startTime"] == preparation.start_time.raw_time
    assert view.rows[0].state == "preparation"
    data = {key: todo_data.ViewData() for key in todo.VIEW_ORDER}
    data[todo.VIEW_WAR] = view
    assert f"starts <t:{expected_start}:R>" in _text(
        todo.render_dashboard(todo.VIEW_WAR, 0, data)
    )

    _old_raw, expired = _parsed_official_war(
        start=now - timedelta(days=1, minutes=1),
        end=now - timedelta(minutes=1),
        state="inWar",
    )

    async def old_war(_client, _clan_tag, **_kwargs):
        return "war", expired

    monkeypatch.setattr(todo_data, "_get_war", old_war)
    assert asyncio.run(
        todo_data.build_war_view(object(), [_account()])
    ).rows == []


def test_cwl_transition_does_not_let_expired_previous_round_hide_new_preparation():
    """Newest prep is actionable when the previous API state lags past its end."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _new_raw, newest = _parsed_official_war(
        clan_tag="#HOME",
        state="preparation",
        start=now + timedelta(hours=20),
        end=now + timedelta(hours=44),
    )
    _old_raw, previous = _parsed_official_war(
        clan_tag="#HOME",
        state="inWar",
        start=now - timedelta(hours=25),
        end=now - timedelta(hours=1),
    )

    class Client:
        async def get_league_group(self, clan_tag):
            assert clan_tag == "#HOME"
            return SimpleNamespace(
                state=SimpleNamespace(value="inWar"),
                rounds=[["#PREVIOUS"], ["#NEWEST"]],
            )

        async def get_league_war(self, war_tag):
            return {"#NEWEST": newest, "#PREVIOUS": previous}[war_tag]

    kind, selected = asyncio.run(todo_data._get_cwl_round(Client(), "#HOME"))

    assert kind == "war"
    assert selected is newest
