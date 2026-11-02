"""Unreadable-war masking and stored-tag final proof, with no live providers."""

import asyncio, json
from contextlib import asynccontextmanager
from unittest.mock import patch
import pytest
from cwl_web import participation_sync as sync
import test_participation_waiting as fixtures


@asynccontextmanager
async def capture():
    case = fixtures.WaitingTests()
    await case.asyncSetUp()
    try:
        await case.prepare()
        yield case
    finally:
        await case.asyncTearDown()


async def second_clan(case):
    await case.signup("main", "#Q2Y")
    response = await case.call("POST", "/clans", case.owner, json={"tag": "#J2Y"})
    assert response.status == 201
    response = await case.call(
        "PATCH",
        f"/seasons/{case.sid}/roster/%23Q2Y",
        case.owner,
        json={
            "revision": await case.revision(),
            "assigned_clan_tag": "#J2Y",
            "kept": True,
        },
    )
    assert response.status == 200
    case.league.groups["#J2Y"] = {
        "season": None,
        "state": "ENDED",
        "rounds": [],
        "clans": [{"tag": "#J2Y", "members": [{"tag": "#Q2Y"}]}],
    }


@pytest.mark.parametrize(
    "state",
    [
        "NOT_IN_WAR",
        "ACCESS_DENIED",
        "IN_MATCHMAKING",
        "GROUP_NOT_FOUND",
        "CLAN_NOT_FOUND",
        "ENTER_WAR",
        "MATCHED",
        "UNKNOWN",
        "EMPTY_BODY",
        None,
        "",
    ],
)
@pytest.mark.parametrize("later", [False, True])
def test_waiting_clan_never_masks_unreadable_war(state, later):
    async def run():
        async with capture() as c:
            await second_clan(c)
            c.set_group([["#Y2Y"], ["#Y2Q"]], state="WAR", season="2026-11")
            c.set_war("#Y2Y", state="WAR")
            c.set_war("#Y2Q", state="WAR")
            if later:
                with patch.object(
                    sync, "now", return_value="2026-11-01T11:59:00+00:00"
                ):
                    await c.result()
            c.set_war("#Y2Q", state=state)
            if state == "EMPTY_BODY":
                c.league.wars["#Y2Q"] = {}
            with patch.object(sync, "now", return_value="2026-11-01T12:00:00+00:00"):
                row, data = await c.result()
            assert data["sync"]["status"] == "stale" and data["sync"]["warning"]
            assert not row["source_complete"]
            assert data["sync"]["last_success_at"] == (
                "2026-11-01T11:59:00+00:00" if later else None
            )
            waiting = next(r for r in data["accounts"] if r["tag"] == "#Q2Y")
            assert waiting["source_status"] == "waiting"

    asyncio.run(run())


def test_benign_cached_ended_war_with_waiting_clan_is_neutral_partial():
    async def run():
        async with capture() as c:
            await second_clan(c)
            c.set_group([["#Y2Y"]], state="WAR", season="2026-11")
            c.set_war("#Y2Y", state="ENDED")
            await c.result()
            calls = list(c.league.war_calls)
            row, data = await c.result()
            assert c.league.war_calls == calls
            assert row["source_status"] == "stale" and not row["source_complete"]
            assert (
                data["sync"]["status"] == "partial" and data["sync"]["warning"] is None
            )

    asyncio.run(run())


def test_lagging_stored_tags_allow_final_seventh_round_and_bonus():
    async def run():
        async with capture() as c:
            tags = [f"#Y2{x}" for x in "YQGJLPV"]
            c.set_group([[t] for t in tags[:6]], state="WAR", season="2026-11")
            for t in tags:
                c.set_war(t, state="ENDED")
            row, _ = await c.result()
            assert row["source_attacks"] == 6 and not row["source_complete"]
            c.set_group([[t] for t in tags], state="ENDED", season=None)
            row, _ = await c.result()
            assert (
                row["source_attacks"] == 7
                and row["source_stars"] == 21
                and row["source_complete"]
            )
            from utils.cwl_bonus_raffle import eligibility

            assert (
                eligibility(dict(row, in_current_roster=True, roster_changed=False), 4)
                is None
            )

    asyncio.run(run())


def test_wait_without_any_fresh_group_never_stamps_success():
    async def run():
        async with capture() as c:
            c.set_group([], state="ENDED", season=None)
            _, data = await c.result()
            assert (
                data["sync"]["status"] == "waiting"
                and data["sync"]["last_success_at"] is None
            )

    asyncio.run(run())


def test_rejected_inferred_clan_is_not_fresh_even_if_its_old_war_refetched():
    async def run():
        async with capture() as c:
            await second_clan(c)
            c.set_group([["#Y2Q"]], state="WAR", season="2026-11")
            c.set_war("#Y2Q", state="WAR")
            await c.result()
            c.set_group([["#Y2Y"]], state="PREPARATION", season=None)
            c.set_war("#Y2Y", state="WAR")
            c.league.wars["#Y2Y"]["season"] = "2026-10"
            c.league.groups["#J2Y"] = {
                "season": "2026-11",
                "state": "WAR",
                "rounds": [{"war_tags": ["#Y2Q"]}],
                "clans": [{"tag": "#J2Y", "members": [{"tag": "#Q2Y"}]}],
            }
            row, data = await c.result()
            assert row["source_status"] == "stale" and "Cached" in row["source_warning"]
            assert data["sync"]["warning"] and not row["source_complete"]
            with c.app["store"].tx() as db:
                stored = db.execute(
                    "SELECT war_tags_json FROM participation_group_observations WHERE season_id=? AND cycle=? AND clan_tag=?",
                    (c.sid, "2026-11", "#C2Y"),
                ).fetchone()
            assert json.loads(stored["war_tags_json"]) == [["#Y2Q"]]

    asyncio.run(run())
