import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

from extensions import autocomplete
from extensions.tasks import fwa_points_monitor as monitor


def _caught_up(opponent_name):
    """A record with a current, caught-up verdict - the board's happy path."""
    return {
        "coc_opponent_name": opponent_name,
        "raw_verdict": "some verdict text",
        "status": "caught_up",
        "current_war_state": "preparation",
    }


def test_build_opponent_choices_puts_chosen_clan_first():
    watch = [
        {"tag": "AAA", "name": "Clan A"},
        {"tag": "BBB", "name": "Clan B"},
    ]
    records = {
        "AAA": _caught_up("Opp A"),
        "BBB": _caught_up("Opp B"),
    }
    choices = autocomplete.build_opponent_choices(watch, records, chosen_clan_tag="BBB")
    assert choices == [("Opp B — vs Clan B", "Opp B"), ("Opp A", "Opp A")]


def test_build_opponent_choices_dedupes_by_name():
    watch = [{"tag": "AAA", "name": "A"}, {"tag": "BBB", "name": "B"}]
    records = {
        "AAA": _caught_up("Same Opp"),
        "BBB": _caught_up("Same Opp"),
    }
    choices = autocomplete.build_opponent_choices(watch, records)
    assert len(choices) == 1


def test_build_opponent_choices_filters_by_prefix_substring():
    watch = [{"tag": "AAA", "name": "A"}, {"tag": "BBB", "name": "B"}]
    records = {
        "AAA": _caught_up("Dragon Slayers"),
        "BBB": _caught_up("Rocket League"),
    }
    matching = autocomplete.build_opponent_choices(watch, records, query="DRAG")
    assert [v for _, v in matching] == ["Dragon Slayers"]

    no_match = autocomplete.build_opponent_choices(watch, records, query="zzz")
    assert no_match == []


def test_build_opponent_choices_skips_placeholder_names():
    watch = [{"tag": "AAA", "name": "A"}]
    assert autocomplete.build_opponent_choices(watch, {"AAA": _caught_up("Unknown")}) == []
    assert autocomplete.build_opponent_choices(watch, {"AAA": _caught_up("")}) == []
    assert autocomplete.build_opponent_choices(watch, {"AAA": _caught_up("   ")}) == []


def test_build_opponent_choices_preserves_raw_name_unescaped():
    watch = [{"tag": "AAA", "name": "A"}]
    raw = "Weird_Name*Clan`x"
    records = {"AAA": _caught_up(raw)}
    choices = autocomplete.build_opponent_choices(watch, records)
    assert choices == [(raw, raw)]


def test_build_opponent_choices_caps_at_25():
    watch = [{"tag": f"T{i:03d}", "name": f"Clan {i}"} for i in range(30)]
    records = {f"T{i:03d}": _caught_up(f"Opp {i}") for i in range(30)}
    choices = autocomplete.build_opponent_choices(watch, records)
    assert len(choices) == 25


def test_build_opponent_choices_stale_verdict_prefers_fresh_current_opponent():
    """A war has been noted (current_war_key != coc_war_key, catch-up
    pending) - the fresh waiting-state name must win over the stale verdict."""
    watch = [{"tag": "AAA", "name": "Clan A"}]
    records = {
        "AAA": {
            "coc_opponent_name": "Old Foes",
            "coc_war_key": "W1",
            "current_war_key": "W2",
            "current_opponent_name": "New Foes",
            "raw_verdict": "old verdict",
            "status": "caught_up",
            "current_war_state": "preparation",
        },
    }
    choices = autocomplete.build_opponent_choices(watch, records)
    assert choices == [("New Foes", "New Foes")]


def test_build_opponent_choices_caught_up_current_war_uses_verdict_name():
    """current_war_key matches the verdict's war - the verdict name applies."""
    watch = [{"tag": "AAA", "name": "Clan A"}]
    records = {
        "AAA": {
            "coc_opponent_name": "Old Foes",
            "coc_war_key": "W1",
            "current_war_key": "W1",
            "current_opponent_name": "New Foes",
            "raw_verdict": "verdict text",
            "status": "caught_up",
            "current_war_state": "preparation",
        },
    }
    choices = autocomplete.build_opponent_choices(watch, records)
    assert choices == [("Old Foes", "Old Foes")]


class _FakeAutocompleteContext:
    def __init__(self, value, clan_option_value=None):
        self.focused = SimpleNamespace(value=value)
        self._clan_option_value = clan_option_value
        self.responses = []

    def get_option(self, name):
        if name == "clan" and self._clan_option_value is not None:
            return SimpleNamespace(value=self._clan_option_value)
        return None

    async def respond(self, choices):
        self.responses.append(choices)


class _RaisingFwaPointsCollection:
    async def find_one(self, *args, **kwargs):
        raise RuntimeError("mongo is down")


class _FakeMongo:
    fwa_points = _RaisingFwaPointsCollection()
    clans = None


def test_war_plan_opponents_returns_no_choices_on_mongo_error():
    autocomplete._cache["war_plan_opponents"] = {"data": None, "timestamp": 0}

    with patch.object(monitor, "mongo_client", _FakeMongo()):
        ctx = _FakeAutocompleteContext("")
        asyncio.run(autocomplete.war_plan_opponents(ctx))

    assert ctx.responses == [[]]


def test_war_plan_opponents_plain_name_clan_option_no_crash():
    """Mobile clients can submit the clan option as plain 'Name' text (no
    '|tag|role_id'). That must not crash or be treated as a chosen-clan tag."""
    autocomplete._cache["war_plan_opponents"] = {
        "data": (
            [{"tag": "AAA", "name": "Clan A"}, {"tag": "BBB", "name": "Clan B"}],
            {"AAA": _caught_up("Opp A"), "BBB": _caught_up("Opp B")},
        ),
        "timestamp": time.time(),
    }

    ctx = _FakeAutocompleteContext("", clan_option_value="Clan A")
    asyncio.run(autocomplete.war_plan_opponents(ctx))

    assert len(ctx.responses) == 1
    values = [v for _, v in ctx.responses[0]]
    assert set(values) == {"Opp A", "Opp B"}


def test_war_plan_opponents_serves_stale_cache_on_refresh_failure():
    """A refresh failure with a previous snapshot in cache must serve the
    stale snapshot instead of going empty."""
    stale_watch = [{"tag": "AAA", "name": "Clan A"}]
    stale_records = {"AAA": _caught_up("Stale Opp")}
    autocomplete._cache["war_plan_opponents"] = {
        "data": (stale_watch, stale_records),
        "timestamp": 0,  # force refresh attempt
    }

    async def _raise():
        raise RuntimeError("scrape unavailable")

    with patch.object(autocomplete, "_board_snapshot", side_effect=_raise):
        ctx = _FakeAutocompleteContext("")
        asyncio.run(autocomplete.war_plan_opponents(ctx))

    assert ctx.responses == [[("Stale Opp", "Stale Opp")]]
