"""Published candidates remain CWL-only when optional history is unavailable."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from utils import clan_history, todo_data


class Collection:
    def __init__(self, documents=(), failure=None):
        self.documents = documents
        self.failure = failure
        self.reads = 0

    def find(self, query):
        self.reads += 1
        if self.failure:
            raise self.failure
        return self

    async def to_list(self, length=None):
        assert length is None
        return list(self.documents)


def load(mongo=None, **kwargs):
    return asyncio.run(clan_history.load_candidates(
        mongo, [" #player "], create_indexes=False, **kwargs,
    ))


def test_assigned_candidates_normalize_and_filter_to_requested_players_without_mongo():
    result = load(assigned={
        " #player ": [(" #beta ", "Beta"), ("", "Empty")],
        "#UNLINKED": [("#FOREIGN", "Not this user's linked account")],
    }, raise_errors=True)

    assert result == {"#PLAYER": [clan_history.ClanCandidate(
        "#BETA", "Beta", check_war=False, check_cwl=True,
    )]}


@pytest.mark.parametrize("raise_errors", [False, True])
def test_assigned_candidates_survive_history_read_failure(raise_errors):
    collection = Collection(failure=RuntimeError("fake history outage"))
    result = load(
        SimpleNamespace(player_clan_candidates=collection),
        assigned={"#PLAYER": [("#BETA", None)]}, raise_errors=raise_errors,
    )

    assert collection.reads == 1
    assert result["#PLAYER"] == [clan_history.ClanCandidate(
        "#BETA", None, check_war=False, check_cwl=True,
    )]


@pytest.mark.parametrize("assigned", [None, {}, {"#OTHER": [("#B", None)]}])
def test_history_failure_still_raises_without_usable_assignments(assigned):
    mongo = SimpleNamespace(player_clan_candidates=Collection(
        failure=RuntimeError("fake history outage"),
    ))
    with pytest.raises(RuntimeError, match="fake history outage"):
        load(mongo, assigned=assigned, raise_errors=True)
    assert load(mongo, assigned=assigned) == {}


def test_assignment_does_not_replace_same_clan_history_flags_or_current_first_dedupe():
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    collection = Collection([{
        "player_tag": "#PLAYER", "clan_tag": "#BETA", "clan_name": "History",
        "war_until": now + timedelta(hours=1),
    }])
    mongo = SimpleNamespace(player_clan_candidates=collection)
    before = load(mongo, observed_at=now)
    assert load(mongo, observed_at=now, assigned={}) == before
    result = load(mongo, observed_at=now, assigned={
        "#PLAYER": [("#BETA", "Published"), ("#HOME", "Assigned home")],
    })
    beta = [candidate for candidate in result["#PLAYER"] if candidate.clan_tag == "#BETA"]
    assert [(item.check_war, item.check_cwl) for item in beta] == [(True, False), (False, True)]
    account = todo_data.Account("#PLAYER", "Player", "#HOME", "Current home")
    war = todo_data._accounts_by_war_clan([account], result, kind="war")
    cwl = todo_data._accounts_by_war_clan([account], result, kind="cwl")
    assert list(war) == ["#HOME", "#BETA"]
    assert list(cwl) == ["#HOME", "#BETA"]
    assert cwl["#HOME"] == [account]
    assert len(cwl["#BETA"]) == 1
    assert cwl["#BETA"][0].clan_name == "Published"


def test_assigned_only_clan_never_enters_regular_war_candidates():
    account = todo_data.Account("#PLAYER", "Player", "#HOME", "Home")
    result = load(assigned={"#PLAYER": [("#BETA", "Beta")]})
    assert list(todo_data._accounts_by_war_clan([account], result, kind="war")) == ["#HOME"]
    assert list(todo_data._accounts_by_war_clan([account], result, kind="cwl")) == ["#HOME", "#BETA"]
