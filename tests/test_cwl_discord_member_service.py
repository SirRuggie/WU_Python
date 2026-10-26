"""Discord bridge integration through the same durable dashboard Store."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.discord_member import GUILD_ID
from utils.cwl_member_service import MemberError


SECRET = "isolated-test-secret-that-is-long-enough-0001"


class Providers:
    def __init__(self):
        self.links = {"100": {"#P2Y": True, "#Q2Y": True}, "200": {"#G2Y": True}}
        self.players = {
            "#P2Y": {"tag": "#P2Y", "name": "Alpha", "town_hall": 16,
                      "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
            "#Q2Y": {"tag": "#Q2Y", "name": "Beta", "town_hall": 15,
                      "current_clan_tag": "#J2Y", "current_clan_name": "Elsewhere"},
            "#G2Y": {"tag": "#G2Y", "name": "Gamma", "town_hall": 14,
                      "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
        }
        self.fail_player = False

    async def linked_tags(self, user_id):
        return dict(self.links.get(user_id, {}))

    async def player(self, value):
        if self.fail_player:
            raise RuntimeError("Clash provider offline")
        return dict(self.players[value])

    async def family_clans(self):
        return {"clans": [{"tag": "#R2Y", "name": "Family", "type": "FWA"}]}


class DiscordMemberBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = Providers()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"),
                              providers=self.providers, secure_cookies=False)
        self.member_check = AsyncMock()
        self.app["discord_member_check"] = self.member_check
        self.env = patch.dict("os.environ", {"CWL_DISCORD_BRIDGE_SECRET": SECRET})
        self.env.start()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO seasons(label,signup_open) VALUES ('October',1)")
            self.sid = db.execute("SELECT id FROM seasons").fetchone()[0]
            db.execute("UPDATE member_season SET season_id=? WHERE id=1", (self.sid,))

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    async def call(self, action="view", uid="100", **fields):
        body = {"action": action, "guild_id": GUILD_ID, "user_id": uid, **fields}
        response = await self.client.post(
            "/api/cwl/discord/member", json=body,
            headers={"X-CWL-Discord-Secret": SECRET},
        )
        return response.status, await response.json()

    async def test_open_is_read_only_and_only_verified_accounts_are_offered(self):
        self.providers.links["100"]["#Q2Y"] = False
        status, result = await self.call()
        self.assertEqual(status, 200)
        self.assertEqual([item["tag"] for item in result["accounts"]], ["#P2Y"])
        self.assertEqual(result["revision"], 0)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])
        self.member_check.assert_awaited_once()

    async def test_save_uses_dashboard_rows_and_fwa_policy_with_stale_review(self):
        status, view = await self.call()
        selection = [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "main", "accounts": selection}
        self.assertEqual((await self.call("submit", **fields))[0], 409)
        fields["pool"] = "lazy"
        self.assertEqual((await self.call("submit", **fields))[0], 200)
        rows = self.app["store"].rows("SELECT tag,user_id,pool FROM signups")
        self.assertEqual(rows, [{"tag": "#P2Y", "user_id": "100", "pool": "lazy"}])
        self.assertEqual((await self.call("submit", **fields))[0], 409)
        self.assertEqual(self.app["store"].one("SELECT revision FROM roster_meta WHERE season_id=?",
                                               (self.sid,))["revision"], 1)

    async def test_published_only_and_provider_outage_preserves_saved_data(self):
        status, view = await self.call()
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        self.assertEqual((await self.call("submit", **fields))[0], 200)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                       (self.sid, "#P2Y", "#PRIVATE"))
        status, view = await self.call()
        self.assertEqual(status, 200)
        self.assertIsNone(view["published"])
        self.assertNotIn("#PRIVATE", str(view))
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_publications(season_id,version,revision,published_by,published_at,"
                       "joining_instructions,assigned_count,unassigned_count,clans_json) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       (self.sid, 1, 1, "staff", "2026-10-25T00:00:00Z", "", 1, 0, "[]"))
            publication_id = db.execute("SELECT id FROM roster_publications").fetchone()[0]
            db.execute("INSERT INTO publication_accounts(publication_id,tag,user_id,player_name,town_hall,"
                       "pool,prefer_crystal_1_or_lower,assigned_clan_tag,assigned_clan_name,kept) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (publication_id, "#P2Y", "100", "Alpha", 16, "lazy", 0, "#R2Y", "Hosting", 0))
        self.providers.fail_player = True
        status, view = await self.call()
        self.assertEqual(status, 200)
        self.assertEqual(view["accounts_status"], "unavailable")
        self.assertEqual(view["signups"][0]["tag"], "#P2Y")
        self.assertEqual(view["assignments"][0]["assigned_clan_tag"], "#R2Y")
        self.assertEqual((await self.call(uid="200"))[1]["assignments"], [])
        self.assertEqual((await self.call("submit", **{**fields, "expected_revision": 1}))[0], 503)

    async def test_partial_family_category_fails_main_but_keeps_lazy_available(self):
        self.providers.family_clans = AsyncMock(return_value={
            "clans": [{"tag": "#R2Y", "name": "Family"}]})
        _, view = await self.call()
        self.assertEqual(view["accounts"][0]["family_clan_status"], "unknown")
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "main", "accounts": [
                      {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        self.assertEqual((await self.call("submit", **fields))[0], 503)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])
        fields["pool"] = "lazy"
        self.assertEqual((await self.call("submit", **fields))[0], 200)

    async def test_closed_hidden_and_moved_seasons_reject_mutations(self):
        _, view = await self.call()
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET signup_open=0 WHERE id=?", (self.sid,))
        self.assertEqual((await self.call("submit", **fields))[0], 423)
        with self.app["store"].tx() as db:
            db.execute("UPDATE member_season SET season_id=NULL WHERE id=1")
        self.assertEqual((await self.call("submit", **fields))[0], 403)
        self.assertEqual((await self.call("view", season_id=self.sid))[0], 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])

    async def test_multi_account_and_confirmed_pool_change_clear_working_assignment(self):
        _, view = await self.call()
        selection = [
            {"tag": "#P2Y", "prefer_crystal_1_or_lower": False},
            {"tag": "#Q2Y", "prefer_crystal_1_or_lower": True},
        ]
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "main", "accounts": selection}
        self.assertEqual((await self.call("submit", **fields))[0], 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])
        fields["pool"] = "lazy"
        self.assertEqual((await self.call("submit", **fields))[0], 200)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) "
                       "VALUES (?,?,?,1)", (self.sid, "#Q2Y", "#R2Y"))
        _, fresh = await self.call()
        move = {"season_id": self.sid, "expected_revision": fresh["revision"],
                "pool": "main", "accounts": [
                    {"tag": "#Q2Y", "prefer_crystal_1_or_lower": True,
                     "move_from_pool": "lazy"}]}
        self.assertEqual((await self.call("submit", **move))[0], 200)
        row = self.app["store"].one(
            "SELECT assigned_clan_tag,kept FROM roster_entries WHERE season_id=? AND tag=?",
            (self.sid, "#Q2Y"))
        self.assertEqual(row, {"assigned_clan_tag": None, "kept": 0})
        audit = self.app["store"].one(
            "SELECT action,before_json FROM roster_audit WHERE action='member_pool_change'")
        self.assertEqual(audit["action"], "member_pool_change")
        self.assertIn("#R2Y", audit["before_json"])

    async def test_withdrawal_requires_owner_pool_and_fresh_revision(self):
        _, view = await self.call()
        fields = {"season_id": self.sid, "expected_revision": view["revision"],
                  "pool": "lazy", "accounts": [
                      {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        self.assertEqual((await self.call("submit", **fields))[0], 200)
        _, fresh = await self.call()
        remove = {"season_id": self.sid, "expected_revision": fresh["revision"],
                  "expected_pool": "lazy", "tag": "#P2Y"}
        self.assertEqual((await self.call("withdraw", uid="200", **remove))[0], 409)
        self.assertEqual((await self.call("withdraw", **{**remove, "expected_pool": "main"}))[0], 409)
        self.assertEqual((await self.call("withdraw", **remove))[0], 200)
        self.assertEqual((await self.call("withdraw", **remove))[0], 409)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])

    async def test_membership_and_bridge_secret_are_required(self):
        self.member_check.side_effect = MemberError(403, "Warriors United membership required")
        self.assertEqual((await self.call())[0], 403)
        self.member_check.side_effect = None
        response = await self.client.post("/api/cwl/discord/member",
                                          json={"action": "view", "user_id": "100", "guild_id": GUILD_ID})
        self.assertEqual(response.status, 403)
