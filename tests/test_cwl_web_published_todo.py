"""Published-only CWL discovery with isolated SQLite and fake war responses."""

import asyncio
from functools import wraps
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cwl_web.store import Store
from cwl_web.todo import load_recent_clans
from utils import clan_history, todo_data


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return run


def _counts(store):
    with store.tx() as db:
        rows = db.execute(
            "SELECT s.pool, count(*), "
            "sum(CASE WHEN r.assigned_clan_tag IS NOT NULL THEN 1 ELSE 0 END), "
            "sum(coalesce(r.kept, 0)) FROM signups s "
            "LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag "
            "GROUP BY s.pool ORDER BY s.pool"
        )
        return [tuple(row) for row in rows]


@pytest.mark.parametrize("publication", ["none", "live", "withdrawn"])
@run_async
async def test_published_assignment_requires_live_publication_and_current_owner_pool(
    tmp_path, publication
):
    store = Store(str(tmp_path / "cwl.sqlite"))
    with store.tx() as db:
        sid = db.execute(
            "INSERT INTO seasons(label, signup_open) VALUES ('Fixture', 1)"
        ).lastrowid
        db.execute("UPDATE member_season SET season_id=? WHERE id=1", (sid,))
        signups = [
            ("#P2Y", "123", "main"),
            ("#Q2Y", "456", "main"),
            ("#R2Y", "123", "lazy"),
        ]
        for tag, user, pool in signups:
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,"
                "prefer_crystal_1_or_lower,player_name,town_hall) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, tag, user, pool, 0, tag, 16),
            )
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) "
                "VALUES (?,?,?,?)",
                (sid, tag, "#C2Y", 1),
            )
        if publication != "none":
            pub = db.execute(
                "INSERT INTO roster_publications(season_id,version,revision,"
                "published_by,published_at,joining_instructions,assigned_count,"
                "unassigned_count,clans_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, 1, 1, "staff", "2026-01-01", "", 3, 0, "[]"),
            ).lastrowid
            # The second account changed owner; the third changed pool.
            published = [
                ("#P2Y", "123", "main"),
                ("#Q2Y", "123", "main"),
                ("#R2Y", "123", "main"),
            ]
            for tag, user, pool in published:
                db.execute(
                    "INSERT INTO publication_accounts(publication_id,tag,user_id,"
                    "player_name,town_hall,pool,prefer_crystal_1_or_lower,"
                    "assigned_clan_tag,assigned_clan_name,kept) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pub, tag, user, tag, 16, pool, 0, "#C2Y", "Host", 0),
                )
            if publication == "withdrawn":
                db.execute(
                    "UPDATE roster_publications SET withdrawn_at='2026-01-02' "
                    "WHERE id=?", (pub,),
                )

    before = _counts(store)
    with patch("cwl_web.todo.get_client", return_value=None):
        result, note = await load_recent_clans(
            {"store": store}, ["#P2Y", "#Q2Y", "#R2Y"], "123"
        )
    assert _counts(store) == before
    assert note
    assert set(result) == ({"#P2Y"} if publication == "live" else set())
    if result:
        candidate = result["#P2Y"][0]
        assert (candidate.clan_tag, candidate.check_war, candidate.check_cwl) == (
            "#C2Y", False, True
        )


@run_async
async def test_member_view_failure_falls_back_to_unavailable_history():
    with patch("utils.cwl_member_service.member_view", side_effect=RuntimeError), \
         patch("cwl_web.todo.get_client", return_value=None):
        candidates, note = await load_recent_clans({"store": object()}, ["#P2Y"], "123")
    assert candidates == {}
    assert note == "Recent clan history is unavailable"


def _war(tag, members, attacks):
    side = SimpleNamespace(tag=tag, name=tag, members=members, badge=None)
    opponent = SimpleNamespace(tag="#Q2Y", name="Other", members=[], badge=None)
    return SimpleNamespace(
        state="inWar", clan=side, opponent=opponent,
        attacks_per_member=attacks, end_time=None, start_time=None,
        get_member=lambda tag: next((m for m in members if m.tag == tag), None),
    )


@run_async
async def test_published_candidate_keeps_regular_war_and_cwl_scoped(monkeypatch):
    account = todo_data.Account(
        tag="#P2Y", name="Player", clan_tag="#A2Y", clan_name="Home", town_hall=16
    )
    candidates = await clan_history.load_candidates(
        None, ["#P2Y"], assigned={"#P2Y": [("#B2Y", "Host")]}
    )
    calls = []
    member = SimpleNamespace(tag="#P2Y", attacks=[])

    async def regular(_client, tag):
        calls.append(tag)
        return ("war", _war("#A2Y", [member], 2)) if tag == "#A2Y" else ("none", None)

    async def league(_client, tag):
        return ("war", _war("#B2Y", [member], 1)) if tag == "#B2Y" else ("none", None)

    monkeypatch.setattr(todo_data, "_get_war", regular)
    monkeypatch.setattr(todo_data, "_get_cwl_round", league)
    normal = await todo_data.build_war_view(object(), [account], candidates=candidates)
    cwl = await todo_data.build_cwl_view(object(), [account], candidates=candidates)
    assert [(x.clan_tag, x.used, x.limit) for x in normal.rows] == [("#A2Y", 0, 2)]
    assert [(x.clan_tag, x.used, x.limit) for x in cwl.rows] == [("#B2Y", 0, 1)]
    assert "#B2Y" not in calls

    async def absent(_client, tag):
        return ("war", _war("#B2Y", [], 1)) if tag == "#B2Y" else ("none", None)

    monkeypatch.setattr(todo_data, "_get_cwl_round", absent)
    assert not (await todo_data.build_cwl_view(object(), [account], candidates=candidates)).rows
    account = todo_data.Account(
        tag="#P2Y", name="Player", clan_tag="#B2Y", clan_name="Host", town_hall=16
    )
    monkeypatch.setattr(todo_data, "_get_cwl_round", league)
    assert len((await todo_data.build_cwl_view(object(), [account], candidates=candidates)).rows) == 1


@pytest.mark.parametrize("failure", ["read", "timeout"])
@run_async
async def test_history_failure_keeps_note_and_published_cwl_candidate(failure):
    class FailingHistory:
        def find(self, query):
            if failure == "read":
                raise RuntimeError("fake history read failure")
            return self

        async def to_list(self, length=None):
            await asyncio.Event().wait()

    mongo = SimpleNamespace(player_clan_candidates=FailingHistory())
    published = {"published": True, "assignments": [{
        "tag": "#P2Y", "assigned_clan_tag": "#C2Y",
        "assigned_clan_name": "Host",
    }]}
    original_wait_for = asyncio.wait_for

    async def fast_wait_for(awaitable, seconds):
        assert seconds == 7
        return await original_wait_for(awaitable, 0.001)

    with patch("utils.cwl_member_service.member_view", return_value=published), \
         patch("cwl_web.todo.get_client", return_value=mongo), \
         patch("cwl_web.todo.asyncio.wait_for", side_effect=fast_wait_for):
        candidates, note = await load_recent_clans(
            {"store": object()}, ["#P2Y"], "123"
        )
    assert note == "Recent clan history is unavailable"
    assert candidates == {"#P2Y": [clan_history.ClanCandidate(
        "#C2Y", "Host", check_war=False, check_cwl=True,
    )]}
