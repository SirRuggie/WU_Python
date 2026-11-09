"""/fwa weight saves: shared ledger rule, loopback bridge and bot client, fixture data only."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.discord_weight import GUILD_ID
from cwl_web.providers import ProviderUnavailable
from utils import clan_weight_client as client
from utils.clan_weight_store import DISCORD_SOURCE, ClanWeightStore, WeightConflict
from utils.dashboard_access import GROUPS, PERMISSIONS

SECRET = "isolated-test-secret-that-is-long-enough-0002"
STAFF = "300"


class Providers:
    """Isolated stand-in for ClashKing + ClashPerk links and the Clash API."""

    def __init__(self):
        self.links = {"100": {"#P2Y": True, "#Q2Y": False, "#V2Y": True}, "200": {}}
        self.players = {
            "#P2Y": {"tag": "#P2Y", "name": "Alpha", "town_hall": 15,
                     "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
            "#Q2Y": {"tag": "#Q2Y", "name": "Beta", "town_hall": 17,
                     "current_clan_tag": None, "current_clan_name": None},
            "#U2Y": {"tag": "#U2Y", "name": "Unlinked", "town_hall": 16,
                     "current_clan_tag": "#J2Y", "current_clan_name": "Elsewhere"},
        }
        self.links_down = False
        self.player_down = False

    async def linked_tags(self, user_id):
        if self.links_down:
            raise ProviderUnavailable("Could not load all linked accounts. Try again shortly.")
        return dict(self.links.get(user_id, {}))

    async def player(self, value):
        if self.player_down:
            raise ProviderUnavailable("Clash API returned 503")
        if value not in self.players:
            error = ProviderUnavailable("Clash API returned 404")
            error.status_code = 404
            raise error
        return dict(self.players[value])


class LedgerRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ClanWeightStore(str(Path(self.tmp.name) / "w.sqlite"))
        self.player = {"name": "Alpha", "town_hall": 15,
                       "current_clan_tag": "#R2Y", "current_clan_name": "Family"}

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, weight, revision=0, player=None, tag="#P2Y"):
        return self.ledger.save_discord(
            tag, {"weight": weight, "revision": revision, "storages": 5},
            player or self.player, "300", "Staff")

    def test_first_row_for_non_member_records_current_clan_and_source(self):
        row, changed = self.save(174000)
        self.assertTrue(changed)
        self.assertEqual((row["weight"], row["revision"], row["last_clan_tag"], row["storages"]),
                         (174000, 1, "#R2Y", 5))
        with self.ledger.connect() as db:
            history = [dict(r) for r in db.execute("SELECT * FROM clan_player_weight_history")]
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["source"], history[0]["actor_id"], history[0]["actor_name"]),
                         (DISCORD_SOURCE, "300", "Staff"))

    def test_no_clan_records_no_clan_even_after_a_clan_save(self):
        no_clan = {**self.player, "current_clan_tag": None, "current_clan_name": None}
        row, _ = self.save(174000, player=no_clan, tag="#Q2Y")
        self.assertEqual((row["last_clan_tag"], row["last_clan_name"]), ("", ""))
        self.save(150000)
        row, _ = self.save(151000, revision=1, player=no_clan)
        self.assertEqual((row["last_clan_tag"], row["last_clan_name"]), ("", ""))
        with self.ledger.connect() as db:
            clans = [r[0] for r in db.execute(
                "SELECT clan_tag FROM clan_player_weight_history WHERE tag='#P2Y' ORDER BY id")]
        self.assertEqual(clans, ["#R2Y", ""])  # History keeps where each save happened.

    def test_equal_weight_is_not_rewritten(self):
        self.save(174000)
        row, changed = self.save(174000, revision=0)  # Stale revision, same value: no write, no conflict.
        self.assertFalse(changed)
        self.assertEqual(row["revision"], 1)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM clan_player_weight_history").fetchone()[0], 1)

    def test_stale_revision_conflicts_and_invalid_weight_rejected(self):
        self.save(174000)
        with self.assertRaises(WeightConflict):
            self.save(175000, revision=0)
        with self.assertRaises(ValueError):
            self.save(174250, revision=1)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT weight FROM clan_player_weights").fetchone()[0], 174000)

    def test_new_permission_is_separate_and_in_clan_management(self):
        self.assertIn("discord_weights", PERMISSIONS)
        self.assertIn("discord_weights", GROUPS["Clan management"])
        self.assertIn("clan_weights", GROUPS["Clan management"])


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = Providers()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"),
                              providers=self.providers, secure_cookies=False)
        self.grants = {STAFF: {"discord_weights"}}

        async def permissions(user_id):
            return self.grants.get(user_id, set())

        self.app["discord_weight_permissions"] = permissions
        self.server = TestServer(self.app, host="127.0.0.1")
        self.http = TestClient(self.server)
        await self.http.start_server()
        self.env = patch.dict(os.environ, {
            "CWL_DISCORD_BRIDGE_SECRET": SECRET,
            "CWL_DISCORD_BRIDGE_URL": f"http://127.0.0.1:{self.server.port}",
        })
        self.env.start()

    async def asyncTearDown(self):
        await self.http.close()
        self.env.stop()
        self.tmp.cleanup()

    def rows(self, sql):
        with self.app["store"].tx() as db:
            return [dict(r) for r in db.execute(sql)]

    async def test_secret_and_guild_are_required(self):
        response = await self.http.post("/api/cwl/discord/weight", json={
            "action": "access", "actor_id": STAFF, "guild_id": GUILD_ID})
        self.assertEqual(response.status, 403)
        response = await self.http.post("/api/cwl/discord/weight", json={
            "action": "access", "actor_id": STAFF, "guild_id": "1"},
            headers={"X-CWL-Discord-Secret": SECRET})
        self.assertEqual(response.status, 403)
        response = await self.http.post("/api/cwl/discord/weight", json={
            "action": "access", "actor_id": STAFF, "guild_id": GUILD_ID},
            headers={"X-CWL-Discord-Secret": "s\u00e9cret-with-non-ascii"})
        self.assertEqual(response.status, 403)  # Not a 500 from compare_digest.

    async def test_permission_is_checked_on_every_action(self):
        self.assertEqual(await client.request("access", actor_id=STAFF), {"allowed": True})
        self.grants[STAFF] = {"clan_weights"}  # Dashboard weights access alone is not enough.
        for action, extra in (("access", {}), ("accounts", {"target_id": "100"}),
                              ("lookup", {"tag": "#P2Y"}),
                              ("save", {"tag": "#P2Y", "weight": 174000, "revision": 0})):
            with self.assertRaises(client.WeightClientError) as caught:
                await client.request(action, actor_id=STAFF, **extra)
            self.assertEqual(caught.exception.code, "forbidden")
            self.assertEqual(str(caught.exception), "You need weight saving access.")
        self.assertEqual(self.rows("SELECT * FROM clan_player_weights"), [])

    async def test_accounts_lists_links_with_saved_weights_and_tolerates_missing_player(self):
        self.app["clan_weight_trial"].save_discord(
            "#P2Y", {"weight": 170000, "revision": 0, "storages": 5},
            self.providers.players["#P2Y"], "1", "Seed")
        data = await client.request("accounts", actor_id=STAFF, target_id="100")
        tags = [row["tag"] for row in data["accounts"]]
        self.assertEqual(tags, ["#Q2Y", "#P2Y", "#V2Y"])  # Highest TH first; unknown last.
        alpha = data["accounts"][1]
        self.assertEqual((alpha["weight"], alpha["revision"], alpha["town_hall"]), (170000, 1, 15))
        missing = data["accounts"][2]
        self.assertEqual((missing["available"], missing["name"], missing["weight"]), (False, None, None))
        self.assertEqual((await client.request("accounts", actor_id=STAFF, target_id="200"))["accounts"], [])

    async def test_links_outage_is_not_reported_as_no_links(self):
        self.providers.links_down = True
        with self.assertRaises(client.WeightClientError) as caught:
            await client.request("accounts", actor_id=STAFF, target_id="100")
        self.assertEqual(caught.exception.code, "links_unavailable")
        self.assertFalse(caught.exception.uncertain)

    async def test_lookup_validates_tag_and_reports_missing_player(self):
        for value, code in (("not a tag", "invalid_tag"), ("#2PP", "not_found")):
            with self.assertRaises(client.WeightClientError) as caught:
                await client.request("lookup", actor_id=STAFF, tag=value)
            self.assertEqual(caught.exception.code, code)
        data = await client.request("lookup", actor_id=STAFF, tag="u2y")
        self.assertEqual((data["account"]["tag"], data["account"]["clan_name"]), ("#U2Y", "Elsewhere"))

    async def test_save_creates_unlinked_non_member_row_then_conflicts_when_stale(self):
        data = await client.request("save", actor_id=STAFF, actor_name="Staff",
                                    tag="#U2Y", weight=160000, revision=0)
        self.assertTrue(data["changed"])
        self.assertEqual((data["account"]["weight"], data["account"]["revision"]), (160000, 1))
        row = self.rows("SELECT * FROM clan_player_weights")[0]
        self.assertEqual((row["tag"], row["last_clan_tag"], row["actor_id"], row["storages"]),
                         ("#U2Y", "#J2Y", STAFF, 5))
        with self.assertRaises(client.WeightClientError) as caught:
            await client.request("save", actor_id=STAFF, tag="#U2Y", weight=161000, revision=0)
        self.assertEqual(caught.exception.code, "conflict")
        self.assertFalse(caught.exception.uncertain)
        same = await client.request("save", actor_id=STAFF, tag="#U2Y", weight=160000, revision=0)
        self.assertFalse(same["changed"])
        self.assertEqual(len(self.rows("SELECT * FROM clan_player_weight_history")), 1)

    async def test_save_rejects_bad_weight_and_outage_before_writing(self):
        for weight in (174250, 999, "174000", None):
            with self.assertRaises(client.WeightClientError) as caught:
                await client.request("save", actor_id=STAFF, tag="#P2Y", weight=weight, revision=0)
            self.assertIn(caught.exception.code, {"invalid_weight", "error"})
        self.providers.player_down = True
        with self.assertRaises(client.WeightClientError) as caught:
            await client.request("save", actor_id=STAFF, tag="#P2Y", weight=174000, revision=0)
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(self.rows("SELECT * FROM clan_player_weights"), [])

    async def test_save_bumps_draft_roster_revision(self):
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO seasons(id,label) VALUES(1,'November')")
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                       "VALUES(1,'#P2Y','100','lazy',0,'Alpha',15)")
            before = db.execute("SELECT revision FROM roster_meta WHERE season_id=1").fetchone()
        await client.request("save", actor_id=STAFF, tag="#P2Y", weight=174000, revision=0)
        with self.app["store"].tx() as db:
            after = db.execute("SELECT revision FROM roster_meta WHERE season_id=1").fetchone()[0]
        self.assertGreater(after, before[0] if before else 0)


class FixturePermissionTests(unittest.IsolatedAsyncioTestCase):
    """Without the injected checker, fixture apps use the local grants table."""

    async def test_local_grants_separate_bot_and_dashboard_weight_access(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = create_app(db_path=str(Path(tmp.name) / "cwl.sqlite"), providers=Providers(), secure_cookies=False)
        with app["store"].tx() as db:
            db.execute("INSERT INTO grants(user_id,granted_by,permissions) VALUES ('301','owner',?)",
                       (json.dumps(["clan_weights"]),))
            db.execute("INSERT INTO grants(user_id,granted_by,permissions) VALUES ('302','owner',?)",
                       (json.dumps(["discord_weights"]),))
        server = TestServer(app, host="127.0.0.1")
        http = TestClient(server)
        await http.start_server()
        self.addAsyncCleanup(http.close)
        headers = {"X-CWL-Discord-Secret": SECRET}
        with patch.dict(os.environ, {"CWL_DISCORD_BRIDGE_SECRET": SECRET}):
            statuses = []
            for actor in ("301", "302", "999"):
                response = await http.post("/api/cwl/discord/weight", headers=headers, json={
                    "action": "access", "actor_id": actor, "guild_id": GUILD_ID})
                statuses.append(response.status)
        self.assertEqual(statuses, [403, 200, 403])


class LivePermissionTests(unittest.IsolatedAsyncioTestCase):
    """Production path: Access document from Mongo plus a fresh Discord role lookup."""

    def request(self, document, member=None, error=None):
        class Collection:
            async def find_one(self, _query):
                return document

        async def discord(method, path, **_):
            if error:
                raise error
            return member

        app = {"live_access": True, "dev_fixture": False,
               "server_management_mongo": type("M", (), {"bot_config": Collection()})(),
               "server_management_discord": discord, "store": None}
        return type("R", (), {"app": app, "get": lambda self, key, default=None: None})()

    async def test_role_and_user_grants_resolve_independently(self):
        from cwl_web.discord_weight import actor_permissions

        document = {"_id": "dashboard-access-v2", "revision": 3, "grants": [
            {"kind": "role", "id": "55", "permissions": ["discord_weights"]},
            {"kind": "user", "id": "301", "permissions": ["clan_weights"]},
        ]}
        self.assertEqual(await actor_permissions(self.request(document, {"roles": ["55"]}), "400"),
                         {"discord_weights"})
        self.assertEqual(await actor_permissions(self.request(document, {"roles": []}), "301"),
                         {"clan_weights"})

    async def test_role_lookup_failure_fails_closed(self):
        from cwl_web.discord_weight import BridgeError, actor_permissions
        from aiohttp import web

        document = {"_id": "dashboard-access-v2", "revision": 3, "grants": [
            {"kind": "role", "id": "55", "permissions": ["discord_weights"]}]}
        self.assertEqual(await actor_permissions(
            self.request(document, error=web.HTTPNotFound()), "400"), set())
        with self.assertRaises(BridgeError) as caught:
            await actor_permissions(self.request(document, error=web.HTTPServiceUnavailable()), "400")
        self.assertEqual(caught.exception.status, 503)
        # A direct user grant still works while the role lookup is down.
        document["grants"].append({"kind": "user", "id": "401", "permissions": ["discord_weights"]})
        self.assertEqual(await actor_permissions(
            self.request(document, error=web.HTTPServiceUnavailable()), "401"), {"discord_weights"})


if __name__ == "__main__":
    unittest.main()
