"""Normal waiting needs an older valid month, not an unavailable or later group."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from cwl_web import participation_sync
import test_cwl_web_participation_sync as fixtures


class November(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 1, 12, tzinfo=timezone.utc)


class WaitingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.SyncTests.asyncSetUp
    asyncTearDown = fixtures.SyncTests.asyncTearDown
    auth = fixtures.SyncTests.auth
    call = fixtures.SyncTests.call
    revision = fixtures.SyncTests.revision
    signup = fixtures.SyncTests.signup
    setup_published = fixtures.SyncTests.setup_published
    set_group = fixtures.SyncTests.set_group
    set_war = fixtures.SyncTests.set_war
    sync = fixtures.SyncTests.sync
    account = fixtures.SyncTests.account
    base = fixtures.SyncTests.base

    async def prepare(self, cycle="2026-11"):
        await self.setup_published()
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE participation_sync_settings SET cycle=? WHERE season_id=?",
                (cycle, self.sid),
            )

    async def result(self):
        with patch("cwl_web.participation_sync.datetime", November):
            response = await self.sync()
            self.assertEqual(response.status, 200, await response.text())
            return await self.account()

    async def test_older_valid_group_is_neutral_for_current_month_without_zero_results(
        self,
    ):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        row, data = await self.result()
        self.assertEqual(data["sync"]["status"], "waiting")
        self.assertEqual(
            data["sync"]["warning"], "November CWL hasn't started in Clash yet"
        )
        self.assertIsNone(row["source_attacks"])
        self.assertEqual(self.league.war_calls, [])

    async def test_current_group_is_a_normal_wait_for_selected_next_month(self):
        await self.prepare("2026-12")
        self.set_group([["#Y2Y"]], season="2026-11")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "waiting")
        self.assertEqual(
            data["sync"]["warning"], "December CWL hasn't started in Clash yet"
        )

    async def test_later_reported_month_is_a_real_warning(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-12")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "season_mismatch")
        self.assertIn("later CWL month", data["sync"]["warning"])
        self.assertNotIn("hasn't started", data["sync"]["warning"])

    async def test_past_selected_month_is_not_mislabeled_as_waiting(self):
        await self.prepare("2026-09")
        self.set_group([["#Y2Y"]], season="2026-08")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "season_mismatch")

    async def test_any_prior_selected_month_war_response_keeps_real_warning(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_war_fetches VALUES(?,?,'#Y2Y',0,'[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11"),
            )
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "season_mismatch")

    async def test_cold_provider_outage_remains_unavailable(self):
        await self.prepare()
        self.league.fail_groups.add("#C2Y")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "unavailable")

    async def test_malformed_older_group_does_not_become_a_normal_wait(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        self.league.groups["#C2Y"]["clans"] = []
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "unavailable")

    async def test_one_older_clan_does_not_hide_another_clan_outage(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        await self.signup("main", "#Q2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        self.assertEqual(response.status, 201)
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
        self.assertEqual(response.status, 200, await response.text())
        self.league.fail_groups.add("#J2Y")
        _, data = await self.result()
        self.assertNotEqual(data["sync"]["status"], "waiting")
        self.assertTrue(data["sync"]["warning"])

    async def test_cached_wait_expires_at_month_rollover_and_after_a_war_is_seen(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        await self.result()

        class January(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2027, 1, 1, tzinfo=timezone.utc)

        with self.app["store"].tx() as db, patch(
            "cwl_web.participation_sync.datetime", January
        ):
            self.assertEqual(
                participation_sync.settings_view(db, self.sid)["status"],
                "season_mismatch",
            )
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_war_fetches VALUES(?,?,'#Y2Y',0,'[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11"),
            )
        with self.app["store"].tx() as db, patch(
            "cwl_web.participation_sync.datetime", November
        ):
            self.assertEqual(
                participation_sync.settings_view(db, self.sid)["status"],
                "season_mismatch",
            )

    async def test_complete_current_month_data_still_captures_results(self):
        await self.prepare()
        self.set_group([[f"#Y2{n}"] for n in "YQGJLPV"], season="2026-11")
        for n in "YQGJLPV":
            self.set_war(f"#Y2{n}")
        row, data = await self.result()
        self.assertEqual(data["sync"]["status"], "complete")
        self.assertEqual(row["source_attacks"], 7)
        self.assertEqual(row["source_stars"], 21)

    async def test_one_old_clan_and_current_war_data_keeps_warning_and_scores(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        await self.signup("main", "#Q2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        self.assertEqual(response.status, 201)
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
        self.assertEqual(response.status, 200, await response.text())
        self.league.groups["#J2Y"] = {
            "season": "2026-11",
            "state": "WAR",
            "rounds": [{"war_tags": ["#Y2Y"]}],
            "clans": [{"tag": "#J2Y", "members": [{"tag": "#Q2Y"}]}],
        }
        self.set_war("#Y2Y", state="WAR")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "season_mismatch")
        other = next(row for row in data["accounts"] if row["tag"] == "#Q2Y")
        self.assertEqual(other["source_attacks"], 1)
        self.assertTrue(data["sync"]["warning"])

    def test_next_month_rule_crosses_the_year_without_accepting_an_arbitrary_future_month(
        self,
    ):
        class December(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 12, 31, tzinfo=timezone.utc)

        with patch("cwl_web.participation_sync.datetime", December):
            self.assertTrue(participation_sync._upcoming_cycle("2027-01"))
            self.assertTrue(participation_sync._upcoming_cycle("2026-12"))
            self.assertFalse(participation_sync._upcoming_cycle("2027-02"))

    async def test_ancient_group_is_not_claimed_to_be_the_normal_last_month_wait(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-09")
        _, data = await self.result()
        self.assertEqual(data["sync"]["status"], "season_mismatch")

    async def test_cached_wait_is_stale_without_a_recent_check(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], season="2026-10")
        await self.result()
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE participation_sync_settings SET last_checked_at='2026-11-01T10:00:00+00:00' WHERE season_id=?",
                (self.sid,),
            )
        with self.app["store"].tx() as db, patch(
            "cwl_web.participation_sync.datetime", November
        ):
            view = participation_sync.settings_view(db, self.sid)
        self.assertEqual(view["status"], "stale")
        self.assertIn("30 minutes", view["warning"])
