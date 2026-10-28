"""Staff roster rules, weights, placement, and revision invariants."""

import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.providers import ProviderUnavailable
from cwl_web.store import Store


class Providers:
    def __init__(self):
        self.links = {"100": {"#P2Y": True, "#Q2Y": True, "#G2Y": True}}
        self.players = {
            "#P2Y": {"tag": "#P2Y", "name": "Main", "town_hall": 16, "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
            "#Q2Y": {"tag": "#Q2Y", "name": "Lazy Yes", "town_hall": 15, "current_clan_tag": "#J2Y", "current_clan_name": "Outside"},
            "#G2Y": {"tag": "#G2Y", "name": "Lazy No", "town_hall": 14, "current_clan_tag": "#J2Y", "current_clan_name": "Outside"},
        }
        self.weight_data = {"#P2Y": {"weight": 176000, "source_name": "FWA Stats", "source_modified_at": "2026-05-15T11:37:17Z"},
                            "#Q2Y": {"weight": 168000, "source_name": "FWA Stats", "source_modified_at": "2026-10-14T11:41:03Z"},
                            "#G2Y": {"weight": 159000, "source_name": "FWA Stats", "source_modified_at": "2026-10-14T11:41:03Z"}}
        self.fail_weights = False

    async def linked_tags(self, user_id):
        return self.links.get(user_id, {}).copy()

    async def player(self, value):
        return self.players[value].copy()

    async def clan(self, value):
        return {"tag": value, "name": "Host " + value}

    async def family_clans(self):
        return {"source": "fixture", "status": "ok", "checked_at": "2026-10-14T00:00:00Z",
                "clans": [{"tag": "#R2Y", "name": "Family", "type": "Tactical"}]}

    async def weights(self, tags):
        if self.fail_weights:
            raise ProviderUnavailable("FWA source unavailable")
        return {value: self.weight_data[value] for value in tags if value in self.weight_data}


class RosterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = Providers()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"), providers=self.providers, secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth("505227988229554179")
        self.member = self.auth("100")
        response = await self.call("POST", "/seasons", self.owner,
                                   json={"label": "October 2026", "signup_open": True})
        self.sid = (await response.json())["id"]

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def auth(self, uid):
        raw, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)",
                       (hashlib.sha256(raw.encode()).hexdigest(), uid, uid, 0, csrf, int(time.time()) + 900))
        return {"Cookie": "cwl_session=" + raw, "X-CSRF-Token": csrf}

    async def call(self, method, path, headers=None, **kwargs):
        return await self.client.request(method, "/api/cwl" + path, headers=headers, **kwargs)

    async def revision(self):
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        self.assertEqual(response.status, 200)
        return (await response.json())["revision"]

    async def signup(self, pool, value, preference=False):
        return await self.call("POST", f"/seasons/{self.sid}/signups", self.member,
                               json={"pool": pool, "accounts": [{"tag": value, "prefer_crystal_1_or_lower": preference}]})

    async def host(self, value, pool):
        response = await self.call("POST", "/clans", self.owner, json={"tag": value})
        self.assertEqual(response.status, 201)
        response = await self.call("POST", f"/seasons/{self.sid}/lineup", self.owner, json={"tag": value})
        self.assertEqual(response.status, 201)
        response = await self.call("PATCH", f"/seasons/{self.sid}/lineup/%23{value[1:]}/rules", self.owner,
                                   json={"revision": await self.revision(), "pool": pool, "capacity": 15,
                                         "min_weight": 150000, "max_weight": 180000})
        self.assertEqual(response.status, 200)

    async def test_saved_roster_does_not_wait_for_any_live_provider(self):
        import asyncio
        from unittest.mock import AsyncMock
        await self.signup("lazy", "#Q2Y")
        await self.host("#J2Y", "lazy")
        release = asyncio.Event()
        async def slow_player(tag):
            await release.wait()
            return self.providers.players[tag].copy()
        async def slow_clan(tag):
            await release.wait()
            return {"cwl_league": "Gold League I"}
        async def slow_family():
            await release.wait()
            return {"clans": [{"tag": "#R2Y"}]}
        self.app.get("clan_league_cache", {}).clear()
        self.app.get("roster_location_cache", {}).clear()
        self.providers.player = AsyncMock(side_effect=slow_player)
        self.providers.clan = AsyncMock(side_effect=slow_clan)
        self.providers.family_clans = AsyncMock(side_effect=slow_family)
        path = f"/seasons/{self.sid}/roster?background=1"
        started = time.monotonic()
        response = await asyncio.wait_for(self.call("GET", path, self.owner), 1)
        data = await response.json()
        self.assertEqual(response.status, 200)
        self.assertTrue(data["metadata_updating"])
        self.assertEqual(data["accounts"][0]["tag"], "#Q2Y")
        self.assertEqual(data["accounts"][0]["current_clan_status"], "unavailable")
        self.assertFalse(data["accounts"][0]["outside_family_and_hosts"])
        await self.call("GET", path, self.owner)
        self.assertEqual(len(self.app["roster_location_jobs"]), 1)
        self.assertEqual(len(self.app["clan_league_jobs"]), 1)
        self.assertLess(time.monotonic() - started, 1)
        # The fast path must enforce the same staff authorization.
        denied = await self.call("GET", path, self.member)
        self.assertEqual(denied.status, 403)
        jobs = [*self.app["roster_location_jobs"].values(),
                *self.app["clan_league_jobs"].values(), self.app["roster_family_job"]]
        release.set()
        await asyncio.gather(*jobs)
        data = await (await self.call("GET", path, self.owner)).json()
        self.assertFalse(data["metadata_updating"])
        self.assertEqual(data["clans"][0]["cwl_league"], "Gold League I")
        self.assertEqual(data["accounts"][0]["current_clan_status"], "current")
        self.providers.player.assert_awaited_once()
        self.providers.clan.assert_awaited_once()
        self.providers.family_clans.assert_awaited_once()

    async def test_outside_clan_highlight_requires_known_location_and_directory(self):
        from unittest.mock import AsyncMock
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y")

        async def flags():
            response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
            self.assertEqual(response.status, 200)
            return {row["tag"]: row["outside_family_and_hosts"] for row in (await response.json())["accounts"]}

        self.assertEqual(await flags(), {"#P2Y": False, "#Q2Y": True})
        # An active hosting-directory clan counts even without a season lineup.
        await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        self.assertFalse((await flags())["#Q2Y"])
        with self.app["store"].tx() as db:
            db.execute("UPDATE clans SET archived=1 WHERE tag='#J2Y'")
        self.assertTrue((await flags())["#Q2Y"])
        self.providers.family_clans = AsyncMock(side_effect=ProviderUnavailable("offline"))
        self.assertFalse((await flags())["#Q2Y"])
        self.providers.family_clans = AsyncMock(return_value={"clans": [{"tag": "#R2Y"}]})
        self.app["roster_location_cache"].clear()
        self.providers.players["#Q2Y"]["current_clan_tag"] = None
        self.providers.players["#Q2Y"]["current_clan_name"] = None
        self.assertFalse((await flags())["#Q2Y"])
        # Even a cached outside location must not be called current during an outage.
        self.app["roster_location_cache"]["#Q2Y"] = (0, {
            "current_clan_tag": "#OUTSIDE", "current_clan_name": "Outside",
            "current_clan_status": "current",
        })
        self.providers.player = AsyncMock(side_effect=ProviderUnavailable("offline"))
        self.assertFalse((await flags())["#Q2Y"])
        self.app["roster_location_cache"].clear()
        self.assertFalse((await flags())["#Q2Y"])

    async def test_staff_remove_signup_closed_assigned_and_revision_guard(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y", "manual_weight": 160000, "kept": True})
        self.assertEqual(response.status, 200)
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET signup_open=0 WHERE id=?", (self.sid,))
        revision = await self.revision()
        path = f"/seasons/{self.sid}/staff-signups/%23P2Y"
        response = await self.call("DELETE", path, self.member, json={"revision": revision})
        self.assertEqual(response.status, 403)
        response = await self.call("DELETE", path, self.owner, json={"revision": revision - 1})
        self.assertEqual(response.status, 409)
        response = await self.call("DELETE", path, self.owner, json={"revision": revision})
        self.assertEqual(response.status, 200)
        with self.app["store"].tx() as db:
            self.assertIsNone(db.execute("SELECT * FROM signups WHERE season_id=? AND tag='#P2Y'", (self.sid,)).fetchone())
            self.assertIsNone(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag='#P2Y'", (self.sid,)).fetchone())
            self.assertIsNotNone(db.execute("SELECT * FROM roster_audit WHERE season_id=? AND action='staff_remove_signup'", (self.sid,)).fetchone())
            self.assertIsNotNone(db.execute("SELECT * FROM player_weights WHERE tag='#P2Y'").fetchone())
        self.assertGreater(await self.revision(), revision)

    async def test_staff_remove_signup_rejects_archived_season(self):
        await self.signup("main", "#P2Y")
        revision = await self.revision()
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        response = await self.call("DELETE", f"/seasons/{self.sid}/staff-signups/%23P2Y", self.owner, json={"revision":revision})
        self.assertEqual(response.status, 423)

    async def test_auto_place_selected_pool_leaves_other_pool_unchanged(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y")
        await self.host("#C2Y", "main")
        await self.host("#R2Y", "lazy")
        response = await self.call("POST", f"/seasons/{self.sid}/roster/refresh-weights", self.owner, json={"revision":await self.revision()})
        self.assertEqual(response.status,200)
        revision = await self.revision()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner, json={"revision":revision,"pool":"main"})
        preview=await response.json()
        self.assertEqual([p["tag"] for p in preview["placements"]],["#P2Y"])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner, json={"revision":revision,"pool":"lazy","placements":preview["placements"]})
        self.assertEqual(response.status,409)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner, json={"revision":revision,"pool":"main","placements":preview["placements"]})
        self.assertEqual(response.status,200)
        with self.app["store"].tx() as db:
            row=db.execute("SELECT assigned_clan_tag FROM roster_entries WHERE season_id=? AND tag='#Q2Y'",(self.sid,)).fetchone()
            self.assertTrue(row is None or row['assigned_clan_tag'] is None)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner, json={"revision":await self.revision(),"pool":"invalid"})
        self.assertEqual(response.status,400)

    async def test_weight_blocker_explained_but_manual_placement_allowed(self):
        await self.signup('lazy', '#G2Y')
        await self.host('#C2Y', 'lazy')
        with self.app['store'].tx() as db:
            db.execute('UPDATE lineup_rules SET min_weight=160000,max_weight=174000 WHERE season_id=?', (self.sid,))
            db.execute("INSERT INTO roster_entries(season_id,tag,source_weight,source_status) VALUES (?, '#G2Y',159000,'current')", (self.sid,))
        response = await self.call('GET', f'/seasons/{self.sid}/roster', self.owner)
        data = await response.json()
        self.assertEqual(data['accounts'][0]['auto_placement_reason'], 'no_eligible_rule')
        self.assertIn('159k',data['accounts'][0]['auto_placement_note'])
        self.assertIn('160k',data['accounts'][0]['auto_placement_note'])
        response = await self.call('PATCH', f'/seasons/{self.sid}/roster/%23G2Y', self.owner,
            json={'revision':data['revision'],'assigned_clan_tag':'#C2Y','kept':True})
        self.assertEqual(response.status,200,await response.text())

    async def test_staff_only_roster_and_manual_cross_pool_override(self):
        await self.signup("lazy", "#Q2Y", True)
        await self.host("#C2Y", "main")
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.member)
        self.assertEqual(response.status, 403)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23Q2Y", self.member,
                                   json={"revision": await self.revision(), "manual_weight": 169000})
        self.assertEqual(response.status, 403)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23Q2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 169000,
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        account = (await response.json())["accounts"][0]
        self.assertEqual(account["pool"], "lazy")
        self.assertEqual(account["effective_weight"], 169000)
        self.assertEqual(account["assigned_clan_tag"], "#C2Y")
        self.assertTrue(account["kept"])
        response = await self.call("GET", f"/seasons/{self.sid}/signups", self.member)
        self.assertNotIn("assigned_clan_tag", (await response.json())["signups"][0])

    async def test_auto_preview_ignores_legacy_preferences_and_guards_stale_revision(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.signup("lazy", "#G2Y", False)
        await self.host("#C2Y", "main")
        await self.host("#R2Y", "lazy")
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner,
                                   json={"revision": await self.revision()})
        preview = await response.json()
        self.assertEqual(preview["placements"], [])
        self.assertEqual({item["reason"] for item in preview["unassigned"]}, {"missing_weight"})
        response = await self.call("POST", f"/seasons/{self.sid}/roster/refresh-weights", self.owner,
                                   json={"revision": await self.revision()})
        self.assertEqual(response.status, 200)
        revision = await self.revision()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner,
                                   json={"revision": revision})
        preview = await response.json()
        self.assertEqual({item["tag"] for item in preview["placements"]}, {"#P2Y", "#Q2Y", "#G2Y"})
        self.assertEqual(preview["unassigned"], [])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": revision, "placements": preview["placements"]})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["applied"], 3)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": revision, "placements": preview["placements"]})
        self.assertEqual(response.status, 409)

    async def test_preview_invalidated_by_new_signup_and_full_clan(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 176000})
        self.assertEqual(response.status, 200)
        revision = await self.revision()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner,
                                   json={"revision": revision})
        preview = await response.json()
        self.assertEqual(len(preview["placements"]), 1)
        await self.signup("lazy", "#Q2Y", True)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": revision, "placements": preview["placements"]})
        self.assertEqual(response.status, 409)

    async def test_source_outage_keeps_values_and_manual_override(self):
        await self.signup("main", "#P2Y")
        response = await self.call("POST", f"/seasons/{self.sid}/roster/refresh-weights", self.owner,
                                   json={"revision": await self.revision()})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 177000})
        self.assertEqual(response.status, 200)
        previous = self.app["store"].one("SELECT source_checked_at FROM roster_entries WHERE tag='#P2Y'")["source_checked_at"]
        self.providers.fail_weights = True
        response = await self.call("POST", f"/seasons/{self.sid}/roster/refresh-weights", self.owner,
                                   json={"revision": await self.revision()})
        self.assertEqual(response.status, 503)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        account = (await response.json())["accounts"][0]
        self.assertEqual(account["source_weight"], 176000)
        self.assertEqual(account["manual_weight"], 177000)
        self.assertEqual(account["effective_weight"], 177000)
        self.assertEqual(account["source_status"], "unavailable")
        self.assertEqual(account["source_modified_at"], "2026-05-15T11:37:17Z")
        self.assertEqual(account["source_name"], "FWA Stats")
        self.assertEqual(account["source_checked_at"], previous)

    async def test_war_size_can_be_below_assigned_count_without_moving_players(self):
        await self.host("#C2Y", "main")
        with self.app["store"].tx() as db:
            for index in range(16):
                value = f"#TEST{index}"
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (self.sid, value, "999", "main", 0, value, 16))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,1)",
                           (self.sid, value, "#C2Y"))
        def placements():
            return [tuple(sorted(row.items())) for row in self.app["store"].rows(
                "SELECT * FROM roster_entries WHERE season_id=? ORDER BY tag", (self.sid,))]
        before = placements()
        path = f"/seasons/{self.sid}/lineup/%23C2Y/rules"
        revision = await self.revision()
        response = await self.call("PATCH", path, self.owner, json={"revision": revision, "capacity": 15})
        self.assertEqual(response.status, 200, await response.text())
        rule = self.app["store"].one("SELECT * FROM lineup_rules WHERE season_id=? AND tag='#C2Y'", (self.sid,))
        self.assertEqual(rule["capacity"], 15)
        self.assertEqual(placements(), before)
        for invalid in ({"capacity": 16}, {"capacity": 0}, {"pool": "other"},
                        {"min_weight": 0}, {"min_weight": -1}, {"min_weight": 180000},
                        {"max_weight": 1_000_000_001}, {"lower_league": "yes"}):
            with self.subTest(invalid=invalid):
                response = await self.call("PATCH", path, self.owner,
                                           json={"revision": await self.revision(), **invalid})
                self.assertEqual(response.status, 400)
        response = await self.call("PATCH", path, self.owner, json={"revision": revision, "capacity": 30})
        self.assertEqual(response.status, 409)
        response = await self.call("PATCH", path, self.member,
                                   json={"revision": await self.revision(), "capacity": 30})
        self.assertEqual(response.status, 403)
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        response = await self.call("PATCH", path, self.owner, json={"revision": revision, "capacity": 30})
        self.assertEqual(response.status, 423)
        self.assertEqual(placements(), before)

    async def test_removed_lower_league_is_not_read_written_or_accepted(self):
        await self.host("#C2Y", "main")
        path = f"/seasons/{self.sid}/lineup/%23C2Y/rules"
        for stored in (0, 1):
            with self.subTest(stored=stored):
                with self.app["store"].tx() as db:
                    db.execute("UPDATE lineup_rules SET lower_league=? WHERE season_id=? AND tag='#C2Y'",
                               (stored, self.sid))
                response = await self.call("PATCH", path, self.owner,
                                           json={"revision": await self.revision(), "capacity": 30})
                self.assertEqual(response.status, 200, await response.text())
                self.assertEqual(self.app["store"].one(
                    "SELECT lower_league FROM lineup_rules WHERE season_id=? AND tag='#C2Y'", (self.sid,))["lower_league"], stored)
                roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
                self.assertTrue(all("lower_league" not in clan for clan in roster["clans"]))
                for removed in (True, False, None, 0, 1):
                    response = await self.call("PATCH", path, self.owner,
                                               json={"revision": roster["revision"], "lower_league": removed})
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())["error"], "Invalid hosting rule update")

    async def test_capacity_is_hard_limit_for_manual_assignment(self):
        await self.signup("lazy", "#Q2Y", True)
        await self.host("#C2Y", "main")
        filler = ["#P2Y" + c for c in "0289PYLQGRJCUV"] + ["#P2Y00"]
        with self.app["store"].tx() as db:
            for value in filler:
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (self.sid, value, "999", "main", 0, value, 16))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                           (self.sid, value, "#C2Y"))
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23Q2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 409)
        row = self.app["store"].one("SELECT assigned_clan_tag FROM roster_entries WHERE season_id=? AND tag='#Q2Y'", (self.sid,))
        self.assertIsNone(row)

    async def test_tampered_auto_plan_and_weight_restore(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("POST", f"/seasons/{self.sid}/roster/refresh-weights", self.owner,
                                   json={"revision": await self.revision()})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 177000})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": None})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        account = (await response.json())["accounts"][0]
        self.assertIsNone(account["manual_weight"])
        self.assertEqual(account["effective_weight"], 176000)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": await self.revision(), "placements": []})
        self.assertEqual(response.status, 409)
        self.assertIsNone(self.app["store"].one("SELECT assigned_clan_tag FROM roster_entries WHERE tag='#P2Y'")["assigned_clan_tag"])

    async def test_assigned_withdrawal_and_lineup_removal_conflict(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        response = await self.call("DELETE", f"/seasons/{self.sid}/lineup/%23C2Y", self.owner)
        self.assertEqual(response.status, 409)
        response = await self.call("DELETE", f"/seasons/{self.sid}/signups/%23P2Y", self.member)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.app["store"].rows("SELECT * FROM roster_entries"), [])
        self.assertTrue(self.app["store"].rows("SELECT * FROM roster_audit WHERE action='member_withdrawal'"))


    async def test_directory_host_available_without_lineup_and_bulk_assignment(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        roster = await response.json()
        self.assertEqual(roster["clans"][0]["tag"], "#C2Y")
        self.assertEqual(roster["clans"][0]["effective_capacity"], 50)
        self.assertIsNone(roster["clans"][0]["capacity"])
        self.assertFalse(roster["clans"][0]["archived"])
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": roster["revision"], "tags": ["#P2Y", "#Q2Y"],
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["updated"], 2)
        rows = self.app["store"].rows("SELECT tag,assigned_clan_tag,kept FROM roster_entries ORDER BY tag")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["assigned_clan_tag"] == "#C2Y" and row["kept"] for row in rows))
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM lineup WHERE season_id=?", (self.sid,))), 1)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": await self.revision(), "tags": ["#P2Y", "#Q2Y"],
                                         "assigned_clan_tag": None})
        self.assertEqual(response.status, 200)
        rows = self.app["store"].rows("SELECT assigned_clan_tag,kept FROM roster_entries")
        self.assertTrue(all(row["assigned_clan_tag"] is None and row["kept"] == 0 for row in rows))

    async def test_bulk_validation_staff_revision_and_capacity_rollback(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        payload = {"revision": await self.revision(), "tags": ["#P2Y", "#Q2Y"],
                   "assigned_clan_tag": "#C2Y"}
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.member,
                                   json=payload)
        self.assertEqual(response.status, 403)
        for bad in (["#P2Y", "#P2Y"], ["#P2Y", "#G2Y"]):
            response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                       json={**payload, "tags": bad})
            self.assertIn(response.status, (400, 404))
        self.assertEqual(self.app["store"].rows("SELECT * FROM roster_entries"), [])
        with self.app["store"].tx() as db:
            for index in range(49):
                player_tag = f"#FILL{index}"
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (self.sid, player_tag, "999", "main", 0, player_tag, 16))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                           (self.sid, player_tag, "#C2Y"))
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json=payload)
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM roster_entries WHERE tag IN ('#P2Y','#Q2Y')"), [])
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={**payload, "tags": ["#P2Y"]})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={**payload, "tags": ["#Q2Y"]})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].one("SELECT COUNT(*) AS n FROM roster_entries WHERE assigned_clan_tag='#C2Y'")["n"], 50)

    async def test_bulk_respects_configured_capacity_and_rolls_back(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.host("#C2Y", "main")
        with self.app["store"].tx() as db:
            for index in range(14):
                player_tag = f"#FILL{index}"
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (self.sid, player_tag, "999", "main", 0, player_tag, 16))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                           (self.sid, player_tag, "#C2Y"))
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": await self.revision(), "tags": ["#P2Y", "#Q2Y"],
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM roster_entries WHERE tag IN ('#P2Y','#Q2Y')"), [])

    async def test_archive_removes_destination_but_retains_existing_assignment(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": await self.revision(), "tags": ["#P2Y"],
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        old_revision = await self.revision()
        response = await self.call("PATCH", "/clans/%23C2Y", self.owner, json={"archived": True})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        roster = await response.json()
        self.assertGreater(roster["revision"], old_revision)
        self.assertTrue(roster["clans"][0]["archived"])
        self.assertEqual(next(a for a in roster["accounts"] if a["tag"] == "#P2Y")["assigned_clan_tag"], "#C2Y")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": roster["revision"], "manual_weight": 170000})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": await self.revision(), "tags": ["#Q2Y"],
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 409)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23Q2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 409)

    async def test_directory_change_invalidates_auto_preview_without_lineup(self):
        await self.signup("main", "#P2Y")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 176000})
        self.assertEqual(response.status, 200)
        old_revision = await self.revision()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner,
                                   json={"revision": old_revision})
        self.assertEqual(response.status, 200)
        preview = await response.json()
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        self.assertGreater(await self.revision(), old_revision)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": old_revision, "placements": preview["placements"]})
        self.assertEqual(response.status, 409)

    async def test_publication_privacy_partial_ack_and_immutable_snapshot(self):
        other = self.auth("200")
        self.providers.links["200"] = {"#G2Y": True}
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        self.assertEqual(await response.json(), {"published": None, "accounts": [], "visibility": "current", "draft_changed": False})
        await self.signup("main", "#P2Y")
        response = await self.call("POST", f"/seasons/{self.sid}/signups", other,
                                   json={"pool": "lazy", "accounts": [{"tag": "#G2Y",
                                   "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)
        await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y",
                                         "manual_weight": 176000})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        immediate = await response.json()
        self.assertIsNone(immediate["published"])
        self.assertEqual(len(immediate["accounts"]), 1)
        self.assertEqual(immediate["accounts"][0]["tag"], "#P2Y")
        self.assertIsNone(immediate["accounts"][0]["assigned_clan_tag"])
        self.assertNotIn("weight", str(immediate).lower())
        response = await self.call("GET", f"/seasons/{self.sid}/publication", self.member)
        self.assertEqual(response.status, 403)
        response = await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)
        preview = await response.json()
        self.assertEqual((preview["preview"]["assigned_count"], preview["preview"]["unassigned_count"]), (1, 1))
        self.assertFalse(preview["draft_changed"])
        payload = {"revision": preview["draft_revision"], "acknowledge_unassigned": False,
                   "joining_instructions": "Join the posted clan before war lock."}
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner, json=payload)
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM roster_publications"), [])
        payload["acknowledge_unassigned"] = True
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner, json=payload)
        self.assertEqual(response.status, 201)
        published = (await response.json())["published"]
        self.assertEqual((published["version"], published["revision"]), (1, payload["revision"]))
        response = await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)
        self.assertFalse((await response.json())["draft_changed"])
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        mine = await response.json()
        self.assertEqual(mine["published"], {
            "version": published["version"],
            "published_at": published["published_at"],
            "joining_instructions": published["joining_instructions"],
        })
        self.assertNotIn("published_by", str(mine))
        self.assertEqual(mine["accounts"], [{"tag": "#P2Y", "player_name": "Main", "town_hall": 16,
                                            "pool": "main", "assigned_clan_tag": "#C2Y",
                                            "assigned_clan_name": "Host #C2Y"}])
        self.assertNotIn("weight", str(mine).lower())
        self.assertNotIn("user_id", str(mine))
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", other)
        theirs = await response.json()
        self.assertEqual(len(theirs["accounts"]), 1)
        self.assertEqual(theirs["accounts"][0]["tag"], "#G2Y")
        self.assertIsNone(theirs["accounts"][0]["assigned_clan_tag"])
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": None})
        self.assertEqual(response.status, 200)
        response = await self.call("DELETE", f"/seasons/{self.sid}/signups/%23P2Y", self.member)
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        self.assertEqual((await response.json())["accounts"], [])
        await self.signup("lazy", "#Q2Y")
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        late = await response.json()
        self.assertEqual(late["accounts"][0]["tag"], "#Q2Y")
        self.assertIsNone(late["accounts"][0]["assigned_clan_tag"])
        response = await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)
        self.assertTrue((await response.json())["draft_changed"])
        snapshot = self.app["store"].one("SELECT * FROM publication_accounts WHERE tag='#P2Y'")
        self.assertEqual((snapshot["assigned_clan_tag"], snapshot["manual_weight"]), ("#C2Y", 176000))

    async def test_withdraw_publication_hides_all_versions_and_preserves_work(self):
        await self.signup("main", "#P2Y")
        await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                        json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        for instruction in ("First", "Second"):
            response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                      json={"revision": await self.revision(), "acknowledge_unassigned": True,
                                            "joining_instructions": instruction})
            self.assertEqual(response.status, 201)
        body = {"revision": await self.revision(), "version": 2}
        path = f"/seasons/{self.sid}/publication/withdraw"
        self.assertEqual((await self.call("POST", path, self.member, json=body)).status, 403)
        no_csrf = {"Cookie": self.owner["Cookie"]}
        self.assertEqual((await self.call("POST", path, no_csrf, json=body)).status, 403)
        for malformed in ({}, {**body, "version": True}, {**body, "revision": "1"}):
            self.assertEqual((await self.call("POST", path, self.owner, json=malformed)).status, 400)
        self.assertEqual((await self.call("POST", path, self.owner, json={**body, "version": 1})).status, 409)
        self.assertEqual((await self.call("POST", path, self.owner, json={**body, "revision": 0})).status, 409)
        before = self.app["store"].rows("SELECT * FROM roster_entries")
        response = await self.call("POST", path, self.owner, json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.call("POST", path, self.owner, json=body)).status, 409)
        self.assertEqual(before, self.app["store"].rows("SELECT * FROM roster_entries"))
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM publication_accounts")), 2)
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM roster_publications WHERE withdrawn_at IS NOT NULL")), 2)
        # Reopening the store must not revive a withdrawn publication.
        self.app["store"] = Store(self.app["store"].path)
        response = await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)
        mine = await response.json()
        self.assertIsNone(mine["published"])
        self.assertEqual(len(mine["accounts"]), 1)
        self.assertIsNone(mine["accounts"][0]["assigned_clan_tag"])
        self.assertIsNone(mine["accounts"][0]["assigned_clan_name"])
        preview = await (await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)).json()
        self.assertIsNone(preview["published"])
        self.assertEqual(preview["preview"]["assigned_count"], 1)
        # A new explicit publication is visible and continues the version history.
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                  json={"revision": await self.revision(), "acknowledge_unassigned": True,
                                        "joining_instructions": "Ready"})
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["published"]["version"], 3)
        mine = await (await self.call("GET", f"/seasons/{self.sid}/my-assignments", self.member)).json()
        self.assertEqual(mine["accounts"][0]["assigned_clan_tag"], "#C2Y")

    async def test_publication_idempotency_stale_revision_and_versions(self):
        await self.signup("main", "#P2Y")
        revision = await self.revision()
        payload = {"revision": revision, "acknowledge_unassigned": True,
                   "joining_instructions": "First instructions"}
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner, json=payload)
        self.assertEqual(response.status, 201)
        first = (await response.json())["published"]
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner, json=payload)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["published"], first)
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={**payload, "joining_instructions": "Competing instructions"})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].one("SELECT COUNT(*) AS n FROM roster_publications")["n"], 1)
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={"revision": await self.revision(), "acknowledge_unassigned": True,
                                         "joining_instructions": "Second instructions"})
        self.assertEqual(response.status, 201)
        second = (await response.json())["published"]
        self.assertEqual(second["version"], 2)
        self.assertEqual(self.app["store"].one("SELECT joining_instructions FROM roster_publications WHERE version=1")["joining_instructions"],
                         "First instructions")
        reopened = Store(self.app["store"].path)
        self.assertEqual(reopened.one("SELECT COUNT(*) AS n FROM roster_publications")["n"], 2)
        self.assertEqual(reopened.one("SELECT COUNT(*) AS n FROM publication_accounts")["n"], 2)

    async def test_empty_archived_and_bad_publication_requests(self):
        revision = await self.revision()
        payload = {"revision": revision, "acknowledge_unassigned": True,
                   "joining_instructions": ""}
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner, json=payload)
        self.assertEqual(response.status, 409)
        await self.signup("main", "#P2Y")
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={**payload, "revision": await self.revision(),
                                         "joining_instructions": "x" * 2001})
        self.assertEqual(response.status, 400)
        response = await self.call("POST", f"/seasons/{self.sid}/publication",
                                   {"Cookie": self.owner["Cookie"]},
                                   json={**payload, "revision": await self.revision()})
        self.assertEqual(response.status, 403)
        response = await self.call("PATCH", f"/seasons/{self.sid}", self.owner,
                                   json={"status": "archived"})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={**payload, "revision": await self.revision()})
        self.assertEqual(response.status, 423)

    async def test_legacy_lineup_rule_remains_visible(self):
        await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        response = await self.call("POST", f"/seasons/{self.sid}/lineup", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call("PATCH", f"/seasons/{self.sid}/lineup/%23C2Y/rules", self.owner,
                                   json={"revision": await self.revision(), "pool": "main", "capacity": 15})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        host = (await response.json())["clans"][0]
        self.assertEqual(host["pool"], "main")
        self.assertEqual(host["capacity"], 15)
        self.assertEqual(host["effective_capacity"], 15)


    async def test_full_clan_swap_and_one_step_undo_preserve_weights(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.host("#C2Y", "main")
        await self.host("#R2Y", "lazy")
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) "
                       "VALUES (?,?,?,?,?)", (self.sid, "#P2Y", "#C2Y", 0, 176000))
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) "
                       "VALUES (?,?,?,?,?)", (self.sid, "#Q2Y", "#R2Y", 1, 168000))
            for host, prefix in (("#C2Y", "A"), ("#R2Y", "B")):
                for index in range(14):
                    value = f"#FILL{prefix}{index}"
                    db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                               "VALUES (?,?,?,?,?,?,?)", (self.sid, value, "999", "main", 0, value, 16))
                    db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,1)",
                               (self.sid, value, host))
        before_revision = await self.revision()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.owner,
                                   json={"revision": before_revision, "left_tag": "#P2Y",
                                         "right_tag": "#Q2Y"})
        self.assertEqual(response.status, 200)
        rows = {row["tag"]: row for row in self.app["store"].rows(
            "SELECT tag,assigned_clan_tag,kept,manual_weight FROM roster_entries WHERE tag IN ('#P2Y','#Q2Y')")}
        self.assertEqual((rows["#P2Y"]["assigned_clan_tag"], rows["#Q2Y"]["assigned_clan_tag"]),
                         ("#R2Y", "#C2Y"))
        self.assertTrue(rows["#P2Y"]["kept"])
        self.assertEqual((rows["#P2Y"]["manual_weight"], rows["#Q2Y"]["manual_weight"]),
                         (176000, 168000))
        response = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        undo = (await response.json())["undo"]
        self.assertEqual(undo["revision"], before_revision + 1)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": undo["revision"], "undo_id": undo["id"]})
        self.assertEqual(response.status, 200)
        rows = {row["tag"]: row for row in self.app["store"].rows(
            "SELECT tag,assigned_clan_tag,kept,manual_weight FROM roster_entries WHERE tag IN ('#P2Y','#Q2Y')")}
        self.assertEqual((rows["#P2Y"]["assigned_clan_tag"], rows["#Q2Y"]["assigned_clan_tag"]),
                         ("#C2Y", "#R2Y"))
        self.assertEqual((rows["#P2Y"]["kept"], rows["#Q2Y"]["kept"]), (0, 1))
        self.assertEqual((rows["#P2Y"]["manual_weight"], rows["#Q2Y"]["manual_weight"]),
                         (176000, 168000))
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": await self.revision(), "undo_id": undo["id"]})
        self.assertEqual(response.status, 409)

    async def test_swap_rejects_invalid_accounts_hosts_and_member(self):
        await self.signup("main", "#P2Y")
        await self.signup("lazy", "#Q2Y", True)
        await self.host("#C2Y", "main")
        await self.host("#R2Y", "lazy")
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                       (self.sid, "#P2Y", "#C2Y"))
        payload = {"revision": await self.revision(), "left_tag": "#P2Y", "right_tag": "#Q2Y"}
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.member, json=payload)
        self.assertEqual(response.status, 403)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.owner,
                                   json={**payload, "right_tag": "#P2Y"})
        self.assertEqual(response.status, 400)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.owner, json=payload)
        self.assertEqual(response.status, 409)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                       (self.sid, "#Q2Y", "#C2Y"))
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.owner, json=payload)
        self.assertEqual(response.status, 409)
        with self.app["store"].tx() as db:
            db.execute("UPDATE roster_entries SET assigned_clan_tag='#R2Y' WHERE tag='#Q2Y'")
        response = await self.call("PATCH", "/clans/%23R2Y", self.owner, json={"archived": True})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/swap", self.owner,
                                   json={**payload, "revision": await self.revision()})
        self.assertEqual(response.status, 409)

    async def test_single_bulk_and_auto_undo_restore_placement_only(self):
        await self.signup("main", "#P2Y")
        await self.signup("main", "#Q2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y",
                                         "manual_weight": 176000})
        self.assertEqual(response.status, 200)
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        self.assertIsNotNone(roster["undo"])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": roster["revision"], "undo_id": roster["undo"]["id"]})
        self.assertEqual(response.status, 200)
        row = self.app["store"].one("SELECT assigned_clan_tag,kept,manual_weight FROM roster_entries WHERE tag='#P2Y'")
        self.assertEqual((row["assigned_clan_tag"], row["kept"], row["manual_weight"]),
                         (None, 0, 176000))
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/assignments", self.owner,
                                   json={"revision": await self.revision(), "tags": ["#P2Y", "#Q2Y"],
                                         "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": roster["revision"], "undo_id": roster["undo"]["id"]})
        self.assertEqual(response.status, 200)
        rows = self.app["store"].rows("SELECT assigned_clan_tag,manual_weight FROM roster_entries WHERE tag IN ('#P2Y','#Q2Y')")
        self.assertTrue(all(row["assigned_clan_tag"] is None for row in rows))
        self.assertIn(176000, [row["manual_weight"] for row in rows])
        response = await self.call("PATCH", f"/seasons/{self.sid}/lineup/%23C2Y/rules", self.owner,
                                   json={"revision": await self.revision(), "pool": "main", "capacity": 15,
                                         "min_weight": 150000, "max_weight": 180000})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-preview", self.owner,
                                   json={"revision": await self.revision()})
        preview = await response.json()
        self.assertEqual(preview["placements"], [{"tag": "#P2Y", "assigned_clan_tag": "#C2Y"}])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": preview["revision"], "placements": preview["placements"]})
        self.assertEqual(response.status, 200)
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        self.assertIsNotNone(roster["undo"])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": roster["revision"], "undo_id": roster["undo"]["id"]})
        self.assertEqual(response.status, 200)
        self.assertIsNone(self.app["store"].one("SELECT assigned_clan_tag FROM roster_entries WHERE tag='#P2Y'")["assigned_clan_tag"])

    async def test_undo_capacity_guard_rolls_back_entire_action(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": None})
        self.assertEqual(response.status, 200)
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        undo = roster["undo"]
        with self.app["store"].tx() as db:
            for index in range(15):
                value = f"#FILL{index}"
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (self.sid, value, "999", "main", 0, value, 16))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                           (self.sid, value, "#C2Y"))
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": roster["revision"], "undo_id": undo["id"]})
        self.assertEqual(response.status, 409)
        self.assertIsNone(self.app["store"].one("SELECT assigned_clan_tag FROM roster_entries WHERE tag='#P2Y'")["assigned_clan_tag"])
        self.assertIsNone(self.app["store"].one("SELECT consumed_at FROM roster_undo WHERE id=?", (undo["id"],))["consumed_at"])

    async def test_noop_auto_apply_keeps_undo_and_publication_invalidates_it(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        undo = roster["undo"]
        response = await self.call("POST", f"/seasons/{self.sid}/roster/auto-apply", self.owner,
                                   json={"revision": roster["revision"], "placements": []})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["revision"], roster["revision"])
        self.assertEqual((await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json())["undo"], undo)
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={"revision": roster["revision"], "acknowledge_unassigned": False,
                                         "joining_instructions": ""})
        self.assertEqual(response.status, 201)
        self.assertIsNone((await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json())["undo"])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": await self.revision(), "undo_id": undo["id"]})
        self.assertEqual(response.status, 409)

    async def test_undo_actor_revision_and_capacity_guard(self):
        await self.signup("main", "#P2Y")
        await self.host("#C2Y", "main")
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y"})
        self.assertEqual(response.status, 200)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO grants(user_id,granted_by) VALUES (?,?)", ("200", "505227988229554179"))
        other_editor = self.auth("200")
        roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json()
        other_roster = await (await self.call("GET", f"/seasons/{self.sid}/roster", other_editor)).json()
        self.assertIsNone(other_roster["undo"])
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", other_editor,
                                   json={"revision": roster["revision"], "undo_id": roster["undo"]["id"]})
        self.assertEqual(response.status, 404)
        response = await self.call("PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
                                   json={"revision": await self.revision(), "manual_weight": 176000})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{self.sid}/roster/undo", self.owner,
                                   json={"revision": await self.revision(), "undo_id": roster["undo"]["id"]})
        self.assertEqual(response.status, 409)
        self.assertIsNone((await (await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)).json())["undo"])



    async def test_directory_pool_default_and_season_override(self):
        response = await self.call('POST', '/clans', self.owner, json={'tag':'#C2Y','pool':'main'})
        self.assertEqual(response.status, 201)
        response = await self.call('GET', f'/seasons/{self.sid}/roster', self.owner)
        self.assertEqual((await response.json())['clans'][0]['pool'], 'main')
        await self.host('#C2Y', 'lazy')
        response = await self.call('PATCH', '/clans/%23C2Y', self.owner, json={'pool':'main'})
        self.assertEqual(response.status, 200)
        response = await self.call('GET', f'/seasons/{self.sid}/roster', self.owner)
        self.assertEqual((await response.json())['clans'][0]['pool'], 'lazy')
        response = await self.call('GET', '/clans', self.owner)
        self.assertEqual((await response.json())['clans'][0]['pool'], 'main')

    async def test_directory_pool_validation_and_permissions(self):
        response = await self.call('POST', '/clans', self.owner, json={'tag':'#C2Y','pool':'other'})
        self.assertEqual(response.status, 400)
        response = await self.call('POST', '/clans', self.member, json={'tag':'#C2Y','pool':'main'})
        self.assertEqual(response.status, 403)
        await self.host('#C2Y', 'main')
        response = await self.call('PATCH', '/clans/%23C2Y', self.owner, json={'pool':'other'})
        self.assertEqual(response.status, 400)
        response = await self.call('PATCH', '/clans/%23C2Y', self.member, json={'pool':'lazy'})
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()

class BalanceRequestTests(RosterTests):
    async def setup_balance(self):
        await self.signup('lazy', '#Q2Y')
        await self.host('#J2Y', 'lazy')
        await self.host('#R2Y', 'lazy')
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) VALUES (?,?,?,?,?)',
                       (self.sid, '#Q2Y', '#J2Y', 1, 174000))
        return {'revision': await self.revision(), 'mode': 'balance', 'tags': ['#Q2Y'],
                'clan_tags': ['#R2Y'], 'include_locked': False}

    async def test_balance_lock_apply_replay_and_undo(self):
        body = await self.setup_balance()
        path = f'/seasons/{self.sid}/roster'
        response = await self.call('POST', path + '/auto-preview', self.owner, json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['unassigned'], [{'tag': '#Q2Y', 'reason': 'locked'}])
        body['include_locked'] = True
        response = await self.call('POST', path + '/auto-preview', self.owner, json=body)
        preview = await response.json()
        body['placements'] = preview['placements']
        self.assertEqual(body['placements'], [{'tag': '#Q2Y', 'assigned_clan_tag': '#R2Y'}])
        response = await self.call('POST', path + '/auto-apply', self.owner, json=body)
        self.assertEqual(response.status, 200)
        response = await self.call('POST', path + '/auto-apply', self.owner, json=body)
        self.assertEqual(response.status, 409)
        with self.app['store'].tx() as db:
            row = db.execute('SELECT * FROM roster_entries WHERE season_id=? AND tag=?', (self.sid, '#Q2Y')).fetchone()
            self.assertEqual(row['assigned_clan_tag'], '#R2Y')
            self.assertTrue(row['kept'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM signups WHERE season_id=?', (self.sid,)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM roster_undo WHERE season_id=?', (self.sid,)).fetchone()[0], 1)

    async def test_balance_rejects_tampering_and_member(self):
        body = await self.setup_balance()
        path = f'/seasons/{self.sid}/roster'
        response = await self.call('POST', path + '/auto-preview', self.member, json=body)
        self.assertEqual(response.status, 403)
        for patch, status in [({'tags': ['#Q2Y', '#Q2Y']}, 400), ({'clan_tags': ['#P2Y']}, 409),
                              ({'include_locked': 'yes'}, 400), ({'tags': []}, 400)]:
            response = await self.call('POST', path + '/auto-preview', self.owner, json={**body, **patch})
            self.assertEqual(response.status, status)
        response = await self.call('POST', path + '/auto-apply', self.owner,
                                   json={**body, 'placements': [{'tag': '#Q2Y', 'assigned_clan_tag': '#R2Y'}]})
        self.assertEqual(response.status, 409)
        response = await self.call('PATCH', path + '/assignments', self.owner,
                                   json={'revision': body['revision'], 'tags': ['#Q2Y'], 'assigned_clan_tag': None, 'include_locked': False})
        self.assertEqual(response.status, 409)
