import asyncio
import time
import unittest
from datetime import datetime, timezone
import test_cwl_web_roster as fixtures
from utils.cwl_location_rules import outside_family, arrival_status


class LocationRules(unittest.TestCase):
    def test_host_family_outside_archived_unknown_and_stale(self):
        for state, clan, family, expected in (
            ("current", "#HOST", {"#FAMILY"}, False),
            ("current", "#FAMILY", {"#FAMILY"}, False),
            ("current", "#OTHER", {"#FAMILY"}, True),
            ("current", "#ARCHIVED", {"#FAMILY"}, True),
            ("current", None, {"#FAMILY"}, False),
            ("stale", "#OTHER", {"#FAMILY"}, False),
            ("unavailable", "#OTHER", {"#FAMILY"}, False),
            ("current", "#OTHER", None, False),
        ):
            with self.subTest(state=state, clan=clan, family=family):
                self.assertEqual(
                    outside_family(
                        {"current_clan_status": state, "current_clan_tag": clan},
                        family,
                        {"#HOST"},
                    ),
                    expected,
                )
        for state, clan, expected in (
            ("current", "#HOST", "arrived"),
            ("current", "#OTHER", "missing"),
            ("stale", "#HOST", "unknown"),
            ("unavailable", None, "unknown"),
        ):
            self.assertEqual(
                arrival_status(
                    {
                        "assigned_clan_tag": "#HOST",
                        "current_clan_status": state,
                        "current_clan_tag": clan,
                    }
                ),
                expected,
            )


class AssignmentHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.RosterTests.asyncSetUp
    asyncTearDown = fixtures.RosterTests.asyncTearDown
    auth = fixtures.RosterTests.auth
    call = fixtures.RosterTests.call
    signup = fixtures.RosterTests.signup
    host = fixtures.RosterTests.host
    revision = fixtures.RosterTests.revision

    async def prepared(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call(
            "PATCH",
            f"/seasons/{self.sid}/roster/%23P2Y",
            self.owner,
            json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"},
        )
        self.assertEqual(response.status, 200)
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/publication",
            self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "",
            },
        )
        self.assertEqual(response.status, 201)
        with self.app["store"].tx() as db:
            db.execute("UPDATE member_season SET season_id=? WHERE id=1", (self.sid,))

    async def test_member_cached_arrival_no_cross_owner_or_live_wait(self):
        await self.prepared()
        self.app["roster_location_cache"] = {
            "#P2Y": (
                time.monotonic(),
                {
                    "current_clan_status": "current",
                    "current_clan_tag": "#C2Y",
                    "current_clan_name": "Host",
                    "current_clan_checked_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        }
        from unittest.mock import AsyncMock

        player = AsyncMock(
            side_effect=AssertionError("Cached member read fetched provider")
        )
        self.providers.player = player
        response = await self.call(
            "GET", f"/seasons/{self.sid}/my-assignments", self.member
        )
        self.assertEqual(response.status, 200)
        rows = (await response.json())["accounts"]
        self.assertEqual([r["tag"] for r in rows], ["#P2Y"])
        self.assertEqual(rows[0]["arrival_status"], "arrived")
        self.assertEqual(
            set(rows[0]),
            {
                "tag",
                "player_name",
                "town_hall",
                "pool",
                "assigned_clan_tag",
                "assigned_clan_name",
                "arrival_status",
                "current_clan_tag",
                "current_clan_name",
                "current_clan_checked_at",
                "current_clan_status",
            },
        )
        other = await self.call(
            "GET", f"/seasons/{self.sid}/my-assignments", self.auth("200")
        )
        self.assertEqual((await other.json())["accounts"], [])
        player.assert_not_called()
        self.app["roster_location_cache"]["#P2Y"] = (
            time.monotonic() - 121,
            {
                "current_clan_status": "current",
                "current_clan_tag": "#C2Y",
                "current_clan_checked_at": rows[0]["current_clan_checked_at"],
            },
        )
        block = asyncio.Event()

        async def pending(tag):
            await block.wait()

        self.providers.player = pending
        result = await asyncio.wait_for(
            self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member), 1
        )
        stale = (await result.json())["accounts"][0]
        self.assertEqual(stale["arrival_status"], "unknown")
        self.assertEqual(stale["current_clan_tag"], "#C2Y")
        self.assertEqual(
            stale["current_clan_checked_at"], rows[0]["current_clan_checked_at"]
        )
        self.assertNotIn("location_updating", stale)

    async def test_arrival_snapshot_and_roster_agree_on_host_and_archived(self):
        await self.prepared()
        self.providers.players["#P2Y"]["current_clan_tag"] = "#C2Y"
        self.app["roster_location_cache"] = {}
        result = await self.call(
            "GET", f"/seasons/{self.sid}/arrival-check", self.owner, json={}
        )
        self.assertEqual(result.status, 200)
        data = await result.json()
        self.assertFalse(data["accounts"][0]["outside_family"])
        self.assertEqual(data["accounts"][0]["arrival_status"], "arrived")
        with self.app["store"].tx() as db:
            db.execute("UPDATE clans SET archived=1 WHERE tag=?", ("#C2Y",))
        result = await self.call(
            "GET", f"/seasons/{self.sid}/arrival-check", self.owner, json={}
        )
        self.assertTrue((await result.json())["accounts"][0]["outside_family"])

    async def test_wrong_host_is_missing_but_not_outside_and_outage_not_outside(self):
        await self.prepared()
        await self.host("#J2Y", "lazy")
        self.providers.players["#P2Y"]["current_clan_tag"] = "#J2Y"
        self.app["roster_location_cache"] = {}
        arrival = await (
            await self.call("GET", f"/seasons/{self.sid}/arrival-check", self.owner)
        ).json()
        self.assertEqual(arrival["accounts"][0]["arrival_status"], "missing")
        self.assertFalse(arrival["accounts"][0]["outside_family"])
        roster = await (
            await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        ).json()
        self.assertFalse(roster["accounts"][0]["outside_family_and_hosts"])
        self.providers.players["#P2Y"]["current_clan_tag"] = "#Y9Y9Y9Y"
        self.app["roster_location_cache"] = {}
        arrival = await (
            await self.call("GET", f"/seasons/{self.sid}/arrival-check", self.owner)
        ).json()
        self.assertTrue(arrival["accounts"][0]["outside_family"])
        from unittest.mock import AsyncMock, patch

        with patch("cwl_web.app._family_tags", AsyncMock(return_value=None)):
            arrival = await (
                await self.call("GET", f"/seasons/{self.sid}/arrival-check", self.owner)
            ).json()
            roster = await (
                await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
            ).json()
        self.assertFalse(arrival["accounts"][0]["outside_family"])
        self.assertFalse(roster["accounts"][0]["outside_family_and_hosts"])
