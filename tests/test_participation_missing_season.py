"""Current-month inference is bounded, keeps explicit dates and fails closed."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from cwl_web import participation_sync as sync
from test_participation_waiting import November, WaitingTests


def group(state, season=None):
    return dict(
        state=state,
        season=season,
        rounds=[{"war_tags": ["#Y2Y"]}],
        clans=[{"tag": "#C2Y", "members": [{"tag": "#P2Y"}]}],
    )


@pytest.mark.parametrize(
    "state", ["PREPARATION", "INWAR", "WAR", "ENDED", "NOTINWAR", "UNKNOWN"]
)
@pytest.mark.parametrize("season", [None, "2026-11", "2026-10", "2026-12", ""])
def test_state_and_explicit_month_matrix(state, season):
    original = group(state, season)
    provider = SimpleNamespace(
        league_group=AsyncMock(return_value=original), clan=AsyncMock(return_value={})
    )
    with patch.object(sync, "datetime", November):
        row = asyncio.run(sync._fetch_groups(provider, ["#C2Y"], "2026-11"))[0]
    if state not in {"PREPARATION", "INWAR", "WAR", "ENDED"} and (
        season is None or season == ""
    ):
        assert row[2] == "unavailable"
    elif season == "2026-11":
        assert row[1] is not None
    elif season == "2026-10":
        assert row[2] == "season_older"
    elif season == "2026-12":
        assert row[2] == "season_later"
    elif (season is None or season == "") and state in {"PREPARATION", "INWAR", "WAR"}:
        assert row[1] is not None
    elif (season is None or season == "") and state == "ENDED":
        assert row[2] == "no_group" and row[1] is None
    else:
        assert row[2] == "unavailable"
    assert original == group(state, season), "Never rewrite provider evidence"


@pytest.mark.parametrize("cycle", ["2026-10", "2026-12", "2027-01"])
@pytest.mark.parametrize("state", ["PREPARATION", "INWAR", "ENDED"])
def test_past_or_future_cycle_never_infers_missing_month(cycle, state):
    provider = SimpleNamespace(league_group=AsyncMock(return_value=group(state)))
    with patch.object(sync, "datetime", November):
        row = asyncio.run(sync._fetch_groups(provider, ["#C2Y"], cycle))[0]
    assert row[1] is None and row[2] == (
        "no_group" if cycle == "2026-12" else "unavailable"
    )


class CaptureTests(WaitingTests):
    async def test_current_missing_month_active_captures_matching_war_without_early_complete(
        self,
    ):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="INWAR", season=None)
        self.set_war("#Y2Y", state="ENDED")
        self.league.wars["#Y2Y"]["season"] = "2026-11"
        row, data = await self.result()
        assert row["source_attacks"] == 1
        assert not row["source_complete"]
        assert data["sync"]["status"] != "complete"

    async def test_current_missing_month_active_captures_but_mismatching_war_does_not(
        self,
    ):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="PREPARATION", season=None)
        self.set_war("#Y2Y", state="PREPARATION")
        self.league.wars["#Y2Y"]["season"] = "2026-10"
        row, data = await self.result()
        assert data["sync"]["status"] == "season_mismatch"
        assert row["source_complete"] is False
        with self.app["store"].tx() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM participation_war_observations"
                ).fetchone()[0]
                == 0
            )

    async def test_missing_month_ended_without_war_waits_and_does_not_capture(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="ENDED", season=None)
        row, data = await self.result()
        assert data["sync"]["status"] == "waiting"
        assert row["source_attacks"] is None
        assert self.league.war_calls == []

    async def test_missing_month_ended_after_matching_war_is_not_waiting(self):
        await self.prepare()
        self.set_group([["#Y2Q"]], state="ENDED", season=None)
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_group_observations VALUES(?,?,'#C2Y',?,'WAR','[[\"#Y2Y\"]]','[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11", "2026-11"),
            )
            db.execute(
                "INSERT INTO participation_war_fetches VALUES(?,?,'#Y2Y',0,'[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11"),
            )
        _, data = await self.result()
        assert data["sync"]["status"] != "waiting"

    async def test_active_and_waiting_clans_show_partial_without_outage_warning(self):
        await self.prepare()
        self.set_group([["#0"]], state="PREPARATION", season=None)
        await self.signup("main", "#Q2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        assert response.status == 201
        response = await self.call(
            "PATCH",
            f"/seasons/{self.sid}/roster/%23Q2Y",
            self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#J2Y",
                "kept": True,
            },
        )
        assert response.status == 200
        other = group("ENDED")
        other["clans"] = [{"tag": "#J2Y", "members": [{"tag": "#Q2Y"}]}]
        self.league.groups["#J2Y"] = other
        row, data = await self.result()
        assert data["sync"]["status"] == "partial"
        assert data["sync"]["warning"] is None
        assert not row["source_complete"]

    async def test_archived_season_never_fetches_or_infers_a_group(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="PREPARATION", season=None)
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        self.providers.league_group = AsyncMock()
        response = await self.sync()
        assert response.status == 423
        self.providers.league_group.assert_not_awaited()


def test_rollover_stops_inference_for_the_previous_selected_month():
    from datetime import datetime, timezone

    class December(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 12, 1, 0, 0, 1, tzinfo=timezone.utc)

    provider = SimpleNamespace(
        league_group=AsyncMock(return_value=group("PREPARATION"))
    )
    with patch.object(sync, "datetime", December):
        row = asyncio.run(sync._fetch_groups(provider, ["#C2Y"], "2026-11"))[0]
    assert row[1] is None and row[2] == "unavailable"


@pytest.mark.parametrize("state", ["PREPARATION", "ENDED"])
def test_missing_month_never_overrides_invalid_group_shape(state):
    malformed = group(state)
    malformed["clans"] = []
    provider = SimpleNamespace(league_group=AsyncMock(return_value=malformed))
    with patch.object(sync, "datetime", November):
        row = asyncio.run(sync._fetch_groups(provider, ["#C2Y"], "2026-11"))[0]
    assert row[1] is None and row[2] == "unavailable"
