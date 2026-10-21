"""Official CWL result sync, raw-cache retention, and manual override boundaries."""

import asyncio
import unittest

import test_cwl_web_roster as roster_fixtures
from cwl_web.providers import ProviderUnavailable
from cwl_web import participation_sync


class FakeLeague:
    def __init__(self):
        self.groups = {}
        self.wars = {}
        self.group_calls = []
        self.war_calls = []
        self.fail_groups = set()
        self.fail_wars = set()

    async def league_group(self, clan_tag):
        self.group_calls.append(clan_tag)
        if clan_tag in self.fail_groups:
            raise ProviderUnavailable("Clash group unavailable")
        return self.groups[clan_tag]

    async def league_war(self, war_tag):
        self.war_calls.append(war_tag)
        if war_tag in self.fail_wars:
            raise ProviderUnavailable("Clash war unavailable")
        return self.wars[war_tag]


def side(clan_tag, members):
    return {"tag": clan_tag, "name": clan_tag, "members": members}


def member(player_tag, stars):
    return {
        "tag": player_tag, "name": player_tag,
        "attacks": None if stars is None else [{"stars": value} for value in stars],
    }


class SyncTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = roster_fixtures.RosterTests.asyncSetUp
    asyncTearDown = roster_fixtures.RosterTests.asyncTearDown
    auth = roster_fixtures.RosterTests.auth
    call = roster_fixtures.RosterTests.call
    revision = roster_fixtures.RosterTests.revision
    signup = roster_fixtures.RosterTests.signup

    @property
    def base(self):
        return f"/seasons/{self.sid}/participation"

    async def setup_published(self):
        await self.signup("main", "#P2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#C2Y", "kept": True,
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        response = await self.call(
            "POST", f"/seasons/{self.sid}/publication", self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "",
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        response = await self.call(
            "POST", self.base + "/sync-settings", self.owner,
            json={"cycle": "2026-10", "enabled": False},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.league = FakeLeague()
        self.providers.league_group = self.league.league_group
        self.providers.league_war = self.league.league_war

    def set_group(self, rounds, state="ENDED", season="2026-10"):
        self.league.groups["#C2Y"] = {
            "tag": "#C2Y", "season": season, "state": state,
            "rounds": [{"war_tags": tags} for tags in rounds],
            "clans": [{"tag": "#C2Y", "members": [{"tag": "#P2Y"}]}],
        }

    def set_war(self, war_tag, clan_side="clan", state="ENDED", attacks=(3,)):
        host = side("#C2Y", [member("#P2Y", attacks)])
        other = side("#J2Y", [member("#Q2Y", (1,))])
        self.league.wars[war_tag] = {
            "tag": war_tag, "state": state,
            "clan": host if clan_side == "clan" else other,
            "opponent": other if clan_side == "clan" else host,
        }

    async def sync(self):
        return await self.call("POST", self.base + "/sync", self.owner, json={})

    async def account(self):
        response = await self.call("GET", self.base, self.owner)
        self.assertEqual(response.status, 200)
        data = await response.json()
        return next(row for row in data["accounts"] if row["tag"] == "#P2Y"), data

    async def test_sync_current_signups_without_a_published_roster(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM publication_accounts WHERE publication_id IN (SELECT id FROM roster_publications WHERE season_id=?)', (self.sid,))
            db.execute('DELETE FROM roster_publications WHERE season_id=?', (self.sid,))
        response = await self.sync()
        self.assertEqual(response.status, 200, await response.text())
        account, _ = await self.account()
        self.assertEqual(account['attacks'], 1)
        self.assertTrue(account['source_complete'])

    async def test_twenty_five_hosting_clans_are_not_rejected(self):
        await self.setup_published()
        with self.app['store'].tx() as db:
            original = dict(db.execute("SELECT * FROM publication_accounts WHERE tag='#P2Y'").fetchone())
            for index in range(24):
                row = {**original, 'tag': f'#TEST{index}', 'assigned_clan_tag': f'#HOST{index}'}
                db.execute('INSERT INTO publication_accounts(' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', tuple(row.values()))
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,'100','main',0,'Fixture',16)", (self.sid, row['tag']))
                db.execute('INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)', (self.sid, row['tag'], row['assigned_clan_tag']))
        response = await self.sync()
        self.assertEqual(response.status, 200, await response.text())

    async def test_ended_wars_count_real_attacks_dedup_and_side_orientation(self):
        await self.setup_published()
        self.set_group([["#Y2Y", "#J2Y"], ["#L2Y"], ["#0"]])
        self.set_war("#Y2Y", attacks=(3,))
        self.set_war("#J2Y", attacks=(3,))  # Different war in the same round.
        self.league.wars["#J2Y"]["clan"] = side("#R2Y", [member("#Q2Y", (1,))])
        self.league.wars["#J2Y"]["opponent"] = side("#G2Y", [member("#G2Y", (2,))])
        self.set_war("#L2Y", clan_side="opponent", attacks=(2,))
        response = await self.sync()
        self.assertEqual(response.status, 200, await response.text())
        row, data = await self.account()
        self.assertEqual((row["source_attacks"], row["source_stars"]), (2, 5))
        self.assertEqual((row["attacks"], row["stars"]), (2, 5))
        self.assertFalse(row["source_complete"])  # #0 means a round is not observed.
        self.assertEqual(row["source_status"], "partial")
        self.assertEqual(row["revision"], 0)
        self.assertIsNone(row["updated_by"])
        self.assertEqual(row["recorded_publication_version"], 1)
        self.assertCountEqual(self.league.war_calls, ["#Y2Y", "#J2Y", "#L2Y"])
        self.assertEqual(len(self.league.war_calls), 3)
        self.assertEqual(data["sync"]["cycle_source"], "settings")
        self.assertEqual(len(self.app["store"].rows(
            "SELECT * FROM participation_war_observations WHERE season_id=?",
            (self.sid,),
        )), 2)

    async def test_registered_player_rotated_out_of_six_wars_is_complete(self):
        await self.setup_published()
        war_tags = ["#Y2Y", "#J2Y", "#L2Y", "#R2Y", "#G2Y", "#V2Y", "#C2Y"]
        self.set_group([[tag] for tag in war_tags])
        for index, war_tag in enumerate(war_tags):
            self.set_war(war_tag, attacks=(2,))
            if index:
                self.league.wars[war_tag]["clan"] = side(
                    "#C2Y", [member("#Q2Y", (1,))],
                )
        self.assertEqual((await self.sync()).status, 200)
        row, data = await self.account()
        self.assertEqual((row["source_attacks"], row["source_stars"]), (1, 2))
        self.assertTrue(row["source_complete"])
        self.assertEqual(row["source_status"], "complete")
        self.assertEqual(data["sync"]["status"], "complete")

    async def test_absent_from_group_and_wars_is_not_invented_zero(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.league.groups["#C2Y"]["clans"][0]["members"] = [{"tag": "#Q2Y"}]
        self.set_war("#Y2Y")
        self.league.wars["#Y2Y"]["clan"] = side(
            "#C2Y", [member("#Q2Y", (1,))],
        )
        self.assertEqual((await self.sync()).status, 200)
        row, _ = await self.account()
        self.assertIsNone(row["source_attacks"])
        self.assertFalse(row["source_complete"])
        self.assertEqual(row["source_status"], "no_data")

    async def test_season_mismatch_never_fetches_wars_or_creates_zero(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]], season="2026-09")
        self.set_war("#Y2Y")
        response = await self.sync()
        self.assertEqual(response.status, 200)
        row, data = await self.account()
        self.assertIsNone(row["source_attacks"])
        self.assertEqual(data["sync"]["status"], "season_mismatch")
        self.assertEqual(self.league.war_calls, [])
        self.assertFalse(self.app["store"].rows(
            "SELECT * FROM participation_war_observations WHERE season_id=?",
            (self.sid,),
        ))

    async def test_preparation_unknown_then_observed_zero_in_war(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]], state="PREPARATION")
        self.set_war("#Y2Y", state="PREPARATION", attacks=None)
        self.assertEqual((await self.sync()).status, 200)
        row, _ = await self.account()
        self.assertIsNone(row["source_attacks"])
        self.assertEqual(row["source_status"], "preparation")
        self.set_group([["#Y2Y"]], state="WAR")
        self.set_war("#Y2Y", state="inWar", attacks=())
        self.assertEqual((await self.sync()).status, 200)
        row, _ = await self.account()
        self.assertEqual((row["source_attacks"], row["source_stars"]), (0, 0))
        self.assertFalse(row["source_complete"])

    async def test_cached_ended_war_survives_outage_without_fresh_timestamp(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        self.assertEqual((await self.sync()).status, 200)
        first, data = await self.account()
        self.assertEqual(first["source_status"], "complete")
        checked = first["source_checked_at"]
        successful = data["sync"]["last_success_at"]
        self.league.fail_wars.add("#Y2Y")
        self.assertEqual((await self.sync()).status, 200)
        self.assertEqual(self.league.war_calls, ["#Y2Y"])  # Finalized evidence is cached.
        second, data = await self.account()
        self.assertEqual((second["source_attacks"], second["source_stars"]), (1, 3))
        self.assertEqual(second["source_checked_at"], checked)
        self.assertEqual(second["source_status"], "stale")
        self.assertEqual(data["sync"]["last_success_at"], successful)
        self.assertTrue(second["source_complete"])

    async def test_active_war_outage_keeps_last_observation_as_stale(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]], state="WAR")
        self.set_war("#Y2Y", state="WAR", attacks=(2,))
        self.assertEqual((await self.sync()).status, 200)
        first, _ = await self.account()
        checked = first["source_checked_at"]
        self.league.fail_wars.add("#Y2Y")
        self.assertEqual((await self.sync()).status, 200)
        second, data = await self.account()
        self.assertEqual(self.league.war_calls, ["#Y2Y", "#Y2Y"])
        self.assertEqual((second["source_attacks"], second["source_stars"]), (1, 2))
        self.assertEqual(second["source_checked_at"], checked)
        self.assertEqual(second["source_status"], "stale")
        self.assertEqual(data["sync"]["status"], "stale")

    async def test_settings_change_during_fetch_discards_observations(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        original = self.league.league_group

        async def change_enabled_then_fetch(clan_tag):
            with self.app["store"].tx() as db:
                db.execute(
                    "UPDATE participation_sync_settings SET enabled=1 WHERE season_id=?",
                    (self.sid,),
                )
            return await original(clan_tag)

        self.providers.league_group = change_enabled_then_fetch
        response = await self.sync()
        self.assertEqual(response.status, 409, await response.text())
        self.assertFalse(self.app["store"].rows(
            "SELECT * FROM participation_war_observations WHERE season_id=?",
            (self.sid,),
        ))
        row, _ = await self.account()
        self.assertIsNone(row["source_attacks"])

    async def test_notes_only_does_not_override_source_then_manual_and_reset(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]], state="WAR")
        self.set_war("#Y2Y", state="WAR", attacks=(2,))
        self.assertEqual((await self.sync()).status, 200)
        original, data = await self.account()
        body = {
            "publication_version": 1, "revision": original["revision"],
            "attacks": original["attacks"], "stars": original["stars"],
            "notes": "Called attacks", "source_checked_at": original["source_checked_at"],
        }
        response = await self.call(
            "PATCH", self.base + "/%23P2Y", self.owner, json=body,
        )
        self.assertEqual(response.status, 200, await response.text())
        result = (await response.json())["account"]
        self.assertFalse(result["attacks_override"])
        self.assertFalse(result["stars_override"])
        self.set_war("#Y2Y", state="WAR", attacks=(3,))
        self.assertEqual((await self.sync()).status, 200)
        changed, _ = await self.account()
        self.assertEqual((changed["attacks"], changed["stars"]), (1, 3))
        response = await self.call(
            "PATCH", self.base + "/%23P2Y", self.owner,
            json={
                "publication_version": 1, "revision": changed["revision"],
                "attacks": 2, "stars": changed["stars"], "notes": changed["notes"],
                "source_checked_at": changed["source_checked_at"],
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        manual = (await response.json())["account"]
        self.assertTrue(manual["attacks_override"])
        self.assertFalse(manual["stars_override"])
        self.assertEqual((manual["attacks"], manual["stars"]), (2, 3))
        reset = await self.call(
            "POST", self.base + "/%23P2Y/reset-to-source", self.owner,
            json={
                "publication_version": 1, "revision": manual["revision"],
                "source_checked_at": manual["source_checked_at"],
            },
        )
        self.assertEqual(reset.status, 200, await reset.text())
        clean = (await reset.json())["account"]
        self.assertFalse(clean["attacks_override"])
        self.assertFalse(clean["stars_override"])
        self.assertEqual((clean["attacks"], clean["stars"]), (1, 3))

    async def test_source_only_identity_survives_withdrawal_and_later_publication(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        self.assertEqual((await self.sync()).status, 200)
        row, _ = await self.account()
        self.assertEqual(row["revision"], 0)
        self.assertEqual(row["assigned_clan_tag"], "#C2Y")
        self.assertIsNone(row["updated_by"])
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": None, "kept": False,
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await self.call(
            "DELETE", f"/seasons/{self.sid}/signups/%23P2Y", self.member,
        )).status, 200)
        await self.signup("lazy", "#Q2Y", True)
        response = await self.call(
            "POST", f"/seasons/{self.sid}/publication", self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "",
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        historical, _ = await self.account()
        self.assertFalse(historical["in_latest_publication"])
        self.assertTrue(historical["roster_changed"])
        self.assertEqual(historical["assigned_clan_tag"], "#C2Y")
        self.assertEqual(historical["source_attacks"], 1)

    async def test_staff_auth_and_archived_no_fetch(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        self.assertEqual((await self.call(
            "POST", self.base + "/sync", self.member, json={},
        )).status, 403)
        no_csrf = {key: value for key, value in self.owner.items() if key != "X-CSRF-Token"}
        self.assertEqual((await self.call(
            "POST", self.base + "/sync", no_csrf, json={},
        )).status, 403)
        self.assertEqual((await self.call(
            "POST", f"/seasons/{self.sid}", self.owner, json={},
        )).status, 405)
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}", self.owner,
            json={"status": "archived"},
        )
        self.assertEqual(response.status, 200)
        before = len(self.league.group_calls)
        self.assertEqual((await self.sync()).status, 423)
        self.assertEqual(len(self.league.group_calls), before)
        self.assertEqual((await self.call(
            "POST", self.base + "/sync-settings", self.owner,
            json={"cycle": "2026-11", "enabled": True},
        )).status, 423)

    async def test_worker_excludes_disabled_and_archived_seasons(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        original = participation_sync.INTERVAL_SECONDS
        participation_sync.INTERVAL_SECONDS = 0.01
        lifecycle = participation_sync.lifecycle(self.app)
        try:
            await lifecycle.__anext__()
            await asyncio.sleep(0.04)
            self.assertEqual(self.league.group_calls, [])
            response = await self.call(
                "POST", self.base + "/sync-settings", self.owner,
                json={"cycle": "2026-10", "enabled": True},
            )
            self.assertEqual(response.status, 200)
            await asyncio.sleep(0.04)
            self.assertGreater(len(self.league.group_calls), 0)
            response = await self.call(
                "PATCH", f"/seasons/{self.sid}", self.owner,
                json={"status": "archived"},
            )
            self.assertEqual(response.status, 200)
            before = len(self.league.group_calls)
            await asyncio.sleep(0.04)
            self.assertEqual(len(self.league.group_calls), before)
        finally:
            await lifecycle.aclose()
            participation_sync.INTERVAL_SECONDS = original

    async def test_worker_cancels_on_app_shutdown(self):
        await self.setup_published()
        self.set_group([["#Y2Y"]])
        self.set_war("#Y2Y")
        response = await self.call(
            "POST", self.base + "/sync-settings", self.owner,
            json={"cycle": "2026-10", "enabled": True},
        )
        self.assertEqual(response.status, 200)
        original = participation_sync.INTERVAL_SECONDS
        participation_sync.INTERVAL_SECONDS = 0.01
        lifecycle = participation_sync.lifecycle(self.app)
        try:
            await lifecycle.__anext__()
            await asyncio.sleep(0.06)
            self.assertGreater(len(self.league.group_calls), 0)
            await lifecycle.aclose()
            current = len(self.league.group_calls)
            await asyncio.sleep(0.04)
            self.assertEqual(len(self.league.group_calls), current)
        finally:
            await lifecycle.aclose()
            participation_sync.INTERVAL_SECONDS = original
