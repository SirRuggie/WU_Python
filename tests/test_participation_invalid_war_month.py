"""Full capture through the real public war parser over stubbed HTTP bodies."""

import logging
import unittest
from copy import deepcopy
from unittest.mock import patch
import pytest
from cwl_web import participation_sync as sync
from cwl_web.providers import LiveProviders
from test_cwl_web_league_provider import Response
import test_participation_waiting as waiting

November = waiting.November
from test_participation_invalid_month_provider import ABSENT


class WarMonthTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = waiting.WaitingTests.asyncSetUp
    asyncTearDown = waiting.WaitingTests.asyncTearDown
    auth = waiting.WaitingTests.auth
    call = waiting.WaitingTests.call
    revision = waiting.WaitingTests.revision
    signup = waiting.WaitingTests.signup
    setup_published = waiting.WaitingTests.setup_published
    set_group = waiting.WaitingTests.set_group
    account = waiting.WaitingTests.account
    prepare = waiting.WaitingTests.prepare
    base = waiting.WaitingTests.base

    async def capture(self, value):
        if not hasattr(self, "league"):
            await self.prepare()
        self.set_group([[f"#Y2{n}"] for n in "YQGJLPV"], state="WAR", season="")
        raw = dict(
            state="warEnded",
            teamSize=15,
            clan=dict(
                tag="#C2Y",
                name="Fixture",
                stars=3,
                destructionPercentage=100,
                members=[dict(tag="#P2Y", name="Player", attacks=[dict(stars=3)])],
            ),
            opponent=dict(
                tag="#J2Y", name="Other", stars=0, destructionPercentage=0, members=[]
            ),
        )
        if value is not ABSENT:
            raw["season"] = value
        original = deepcopy(raw)
        calls = []

        class HTTP:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get(self, url, **kwargs):
                calls.append(url)
                return Response(raw)

        real = LiveProviders(coc_token="fixture", mongo_uri="", routes={})
        self.providers.league_war = real.league_war
        with patch(
            "cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: HTTP()
        ), patch.object(sync, "datetime", November):
            result = await sync.sync_season(self.app, self.sid, force=True)
            if value != "2026-10":
                active, _ = await self.account()
                assert active["source_attacks"] == 7 and active["source_stars"] == 21
                self.league.groups["#C2Y"]["state"] = "ENDED"
                await sync.sync_season(self.app, self.sid, force=True)
        assert raw == original
        assert len(calls) == (7 if value == "2026-10" else 14) and all(
            "/clanwarleagues/wars/" in url for url in calls
        )
        row, data = await self.account()
        with self.app["store"].tx() as db:
            groups = db.execute(
                "SELECT count(*) FROM participation_group_observations"
            ).fetchone()[0]
            captures = db.execute(
                "SELECT count(*) FROM bonus_allowance_wars"
            ).fetchone()[0]
        return row, data, groups, captures

    async def test_unreadable_wars_complete_inferred_group_through_real_parser(self):
        for value in [ABSENT, None, "", "2026-11-01", "November", "2026-11"]:
            with self.subTest(value=value):
                # Each subcase needs a fresh isolated fixture and no cached ended war.
                with self.app["store"].tx() as db:
                    db.execute("DELETE FROM participation_war_fetches")
                    db.execute("DELETE FROM bonus_allowance_wars")
                    db.execute("DELETE FROM participation_war_observations")
                row, data, groups, captures = await self.capture(value)
                assert row["source_complete"] is True
                assert row["source_attacks"] == 7 and row["source_stars"] == 21
                assert groups == 1 and captures == 7

    async def test_valid_older_war_rejects_inferred_group_without_store(self):
        row, data, groups, captures = await self.capture("2026-10")
        assert groups == 0 and captures == 0
        assert row["source_complete"] is False
        assert data["sync"]["status"] != "complete"


def test_summary_masks_caps_shapes_and_reports_rejection(caplog):
    raw = [
        "secret/@everyone\nprivate",
        "2026-11-01",
        "November",
        " ",
        "123",
        "12x",
        "x12",
        "2026-10",
        None,
        "",
    ]
    with caplog.at_level(logging.INFO):
        sync._log_war_months(
            [(str(i), dict(season=value), None) for i, value in enumerate(raw)],
            "2026-11",
        )
    assert len(caplog.records) == 1
    record = caplog.records[0]
    counts, shapes, mismatches = record.args
    assert counts == dict(none=1, empty=1, invalid=7, valid=1)
    assert len(shapes) == 5 and all(len(shape) <= 12 for shape in shapes)
    assert mismatches == 1
    assert (
        "secret" not in caplog.text
        and "@everyone" not in caplog.text
        and "November" not in caplog.text
    )
