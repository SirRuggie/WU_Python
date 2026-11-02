"""Explicit date months and scoped NOT_IN_WAR waits through public HTTP parsers."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import logging
from urllib.parse import unquote, urlsplit
from unittest.mock import patch
import unittest
import pytest
from cwl_web import participation_sync as sync
from cwl_web.providers import LiveProviders, ProviderUnavailable
from test_cwl_web_league_provider import Response
from test_participation_invalid_month_provider import body, capture
import test_participation_waiting as waiting


@pytest.mark.parametrize("state", ["PREPARATION", "inWar", "warEnded", "ended"])
@pytest.mark.parametrize(
    "value,category",
    [
        ("2026-11-02", None),
        ("2026-10-02", "season_older"),
        ("2026-12-02", "season_later"),
    ],
)
def test_public_group_parser_date_is_explicit_month(state, value, category, caplog):
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body(state, value)))
    assert row[2] == category
    assert (row[1] is not None) == (category is None)
    if row[1] is not None:
        assert row[1][-1] is False
    assert "season_kind=date" in caplog.text
    assert f"season_shape={value[:7]}-dd" in caplog.text
    assert f"season_shape={value}" not in caplog.text


@pytest.mark.parametrize("state", ["PREPARATION", "ended"])
@pytest.mark.parametrize("value", ["2026-1-02", "2026/11/02", "2026-13-02"])
def test_nonmatching_date_stays_under_existing_no_month_rules(state, value, caplog):
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body(state, value)))
    assert row[2] == ("no_group" if state == "ended" else None)
    assert "season_kind=invalid" in caplog.text and value not in caplog.text


def war_body(value="2026-11-02"):
    return dict(
        state="inWar",
        season=value,
        teamSize=15,
        clan=dict(
            tag="#C2Y",
            name="Fixture",
            members=[dict(tag="#P2Y", name="Player", attacks=[dict(stars=3)])],
        ),
        opponent=dict(tag="#C2V", name="Other", members=[]),
    )


@contextmanager
def http(groups, wars=None):
    originals = deepcopy((groups, wars))
    calls = []

    class HTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get(self, url, **kwargs):
            calls.append(url)
            path = unquote(urlsplit(url).path)
            if path.endswith("/leaguegroup"):
                value = groups[path.split("/")[3]]
            else:
                value = (wars or {})[path.split("/")[-1]]
            return (
                Response({"message": "fixture404"}, 404)
                if value == 404
                else Response(value)
            )

    with patch(
        "cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: HTTP()
    ), patch.object(sync, "datetime", waiting.November), patch(
        "cwl_web.participation.datetime", waiting.November
    ), patch(
        "cwl_web.providers.datetime", waiting.November
    ):
        yield LiveProviders(coc_token="fixture", mongo_uri="", routes={}), calls
    assert (groups, wars) == originals


@pytest.mark.parametrize(
    "value,matched",
    [
        ("2026-11-02", True),
        ("2026-10-02", False),
        ("2026-12-02", False),
        ("2026/11/02", True),
    ],
)
def test_public_war_parser_uses_same_explicit_month_rule(value, matched, caplog):
    async def run():
        with http({}, {"#Y2Y": war_body(value)}) as (real, calls):
            war = await real.league_war("#Y2Y")
            assert sync._month_matches(war["season"], "2026-11") is matched
            sync._log_war_months([("#Y2Y", war, None)], "2026-11")

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    if value != "2026/11/02":
        assert "'date': 1" in caplog.text and value[:7] + "-dd" in caplog.text
    assert value not in caplog.text


class DateCaptureTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = waiting.WaitingTests.asyncSetUp
    asyncTearDown = waiting.WaitingTests.asyncTearDown
    auth = waiting.WaitingTests.auth
    call = waiting.WaitingTests.call
    revision = waiting.WaitingTests.revision
    signup = waiting.WaitingTests.signup
    setup_published = waiting.WaitingTests.setup_published
    account = waiting.WaitingTests.account
    prepare = waiting.WaitingTests.prepare
    base = waiting.WaitingTests.base

    async def refresh(self, groups, wars=None):
        with http(groups, wars) as (real, calls):
            self.providers.league_group = real.league_group
            self.providers.league_war = real.league_war
            await sync.sync_season(self.app, self.sid, force=True)
            return await self.account()

    async def test_not_in_war_without_own_evidence_is_normal_wait(self):
        await self.prepare()
        row, data = await self.refresh({"#C2Y": {"state": "notInWar"}})
        assert data["sync"]["status"] == "waiting" and row["source_attacks"] is None
        with self.app["store"].tx() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM participation_group_observations"
                ).fetchone()[0]
                == 0
            )
        # The public provider still raises its original failure boundary.
        with http({"#C2Y": {"state": "notInWar"}}) as (real, _):
            with pytest.raises(ProviderUnavailable) as caught:
                await real.league_group("#C2Y")
        assert caught.value.group_absent and caught.value.group_state == "NOT_IN_WAR"

    async def test_preparation_row_without_war_tags_is_own_evidence(self):
        await self.prepare()
        raw = body("PREPARATION", "2026-11-02")
        raw["rounds"] = []
        row, data = await self.refresh({"#C2Y": raw})
        assert row["source_status"] == "preparation"
        row, data = await self.refresh({"#C2Y": {"state": "notInWar"}})
        assert data["sync"]["warning"] and data["sync"]["status"] != "waiting"
        assert row["source_status"] != "waiting" and row["source_attacks"] is None
        with self.app["store"].tx() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM participation_group_observations"
                ).fetchone()[0]
                == 1
            )

    async def test_old_date_war_rejects_inferred_group(self):
        await self.prepare()
        raw = body("PREPARATION", "")
        row, data = await self.refresh({"#C2Y": raw}, {"#Y2Y": war_body("2026-10-02")})
        assert (
            data["sync"]["status"] == "season_mismatch"
            and row["source_attacks"] is None
        )
        with self.app["store"].tx() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM participation_group_observations"
                ).fetchone()[0]
                == 0
            )

    async def test_mixed_active_older_404_not_in_war_is_partial_without_warning(self):
        await self.prepare()
        assignments = [("#Q2Y", "#J2Y"), ("#G2Y", "#R2Y"), ("#L2Y", "#V2Y")]
        self.providers.players["#L2Y"] = dict(
            tag="#L2Y", name="Fixture fourth", town_hall=16
        )
        self.providers.links["100"]["#L2Y"] = True
        for player, clan in assignments:
            response = await self.signup("main", player)
            assert response.status in (200, 201), await response.text()
            response = await self.call(
                "POST", "/clans", self.owner, json=dict(tag=clan)
            )
            assert response.status == 201
            response = await self.call(
                "PATCH",
                f"/seasons/{self.sid}/roster/%23{player[1:]}",
                self.owner,
                json=dict(
                    revision=await self.revision(), assigned_clan_tag=clan, kept=True
                ),
            )
            assert response.status == 200
        active = body("inWar", "2026-11-02")
        older = body("ended", "2026-10-02")
        older["clans"][0]["tag"] = "#J2Y"
        older["clans"][0]["members"][0]["tag"] = "#Q2Y"
        groups = {
            "#C2Y": active,
            "#J2Y": older,
            "#R2Y": 404,
            "#V2Y": {"state": "notInWar"},
        }
        for _ in range(2):
            row, data = await self.refresh(groups, {"#Y2Y": war_body()})
            assert (
                data["sync"]["status"] == "partial" and data["sync"]["warning"] is None
            )
            assert data["sync"]["last_success_at"] == data["sync"]["last_checked_at"]
            assert row["source_attacks"] == 1 and row["source_stars"] == 3
            others = [r for r in data["accounts"] if r["tag"] != "#P2Y"]
            assert len(others) == 3 and all(
                r["source_status"] == "waiting" and r["source_attacks"] is None
                for r in others
            )
