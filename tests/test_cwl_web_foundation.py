"""Focused authorization and signup invariants for the isolated CWL service."""

import asyncio
import hashlib
import secrets
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.app import _discord_avatar_url
from cwl_web.providers import LiveProviders, ProviderUnavailable
from unittest.mock import AsyncMock, patch


class FakeProviders:
    def __init__(self):
        self.links = {"100": {"#P2Y": True, "#Q2Y": True}, "200": {"#G2Y": True}}
        self.players = {
            "#P2Y": {"tag": "#P2Y", "name": "Alpha", "town_hall": 16, "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
            "#Q2Y": {"tag": "#Q2Y", "name": "Beta", "town_hall": 15, "current_clan_tag": "#J2Y", "current_clan_name": "Outside"},
            "#G2Y": {"tag": "#G2Y", "name": "Gamma", "town_hall": 14, "current_clan_tag": "#R2Y", "current_clan_name": "Family"},
        }

    async def family_clans(self):
        return {"source": "fixture", "status": "ok", "checked_at": "2026-10-14T00:00:00Z",
                "clans": [{"tag": "#R2Y", "name": "Family"}]}

    async def linked_tags(self, user_id):
        return self.links.get(user_id, {}).copy()

    async def player(self, value):
        return self.players[value].copy()

    async def clan(self, value):
        return {"tag": value, "name": "Family" if value == "#R2Y" else "Hosting"}


class WebFoundationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = FakeProviders()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"), providers=self.providers, secure_cookies=False)
        self.app["server_management_mongo"] = SimpleNamespace(bot_config=SimpleNamespace(update_one=AsyncMock(), delete_one=AsyncMock()))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth("505227988229554179")
        self.member = self.auth("100")
        self.other = self.auth("200")

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def auth(self, uid, owner=False):
        raw, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)", (hashlib.sha256(raw.encode()).hexdigest(), uid, uid, int(owner), csrf, int(time.time()) + 900))
        return {"Cookie": "cwl_session=" + raw, "X-CSRF-Token": csrf}

    async def call(self, method, path, headers=None, **kwargs):
        return await self.client.request(method, "/api/cwl" + path, headers=headers, **kwargs)

    async def season(self):
        response = await self.call("POST", "/seasons", self.owner, json={"label": "October 2026", "signup_open": True})
        self.assertEqual(response.status, 201)
        return (await response.json())["id"]

    async def test_fwa_is_lazy_only_based_on_current_clan_not_historical_clan(self):
        sid = await self.season()
        self.providers.family_clans = AsyncMock(return_value={"clans": [{"tag": "#R2Y", "name": "Family", "type": "FWA"}]})
        item = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
        body = {"pool": "main", "accounts": [item]}
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)).status, 409)
        self.assertEqual(self.app['store'].rows('SELECT * FROM signups'), [])
        body['pool'] = 'lazy'
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)).status, 200)
        body.update(pool='main', accounts=[{**item, 'move_from_pool': 'lazy'}])
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)).status, 409)
        self.providers.players['#P2Y']['current_clan_tag'] = '#J2Y'
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)).status, 200)
        row = self.app['store'].one('SELECT * FROM signups')
        self.assertEqual(row['pool'], 'main')
        self.assertEqual(row['signup_clan_type'], 'FWA')  # History is retained, not a current restriction.

    async def test_existing_signup_fwa_category_and_non_fwa_signups(self):
        sid = await self.season()
        body = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}, {"tag": "#Q2Y", "prefer_crystal_1_or_lower": False}]}
        await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)
        self.providers.family_clans = AsyncMock(return_value={"clans": [{"tag": "#R2Y", "name": "Family", "type": "FWA"}]})
        rows = (await (await self.call("GET", f"/seasons/{sid}/signups", self.member)).json())["signups"]
        self.assertTrue(next(r for r in rows if r["tag"] == "#P2Y")["fwa_main_warning"])
        self.assertFalse(next(r for r in rows if r["tag"] == "#Q2Y")["fwa_main_warning"])

    async def test_signup_restriction_is_visible_without_exposing_unpublished_clan(self):
        sid = await self.season()
        body = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)).status, 200)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?) ON CONFLICT(season_id,tag) DO UPDATE SET assigned_clan_tag=excluded.assigned_clan_tag", (sid, "#P2Y", "#PRIVATE"))
        response = await self.call("GET", f"/seasons/{sid}/signups", self.member)
        data = await response.json()
        self.assertTrue(data["signups"][0]["has_staff_placement"])
        self.assertNotIn("#PRIVATE", str(data))
        other = await (await self.call("GET", f"/seasons/{sid}/signups?all=1", self.other)).json()
        self.assertEqual(other["signups"], [])
        blocked = await self.call("DELETE", f"/seasons/{sid}/signups/%23P2Y", self.member)
        self.assertEqual(blocked.status, 200)
        data = await (await self.call("GET", f"/seasons/{sid}/signups", self.member)).json()
        self.assertEqual(data['signups'], [])
        alerts = await (await self.call('GET', f'/seasons/{sid}/signup-activity', self.owner)).json()
        self.assertEqual(alerts['items'][0]['assigned_clan_tag'], '#PRIVATE')

    async def test_staff_can_add_closed_signups_and_member_sees_them(self):
        sid = await self.season()
        await self.call("PATCH", f"/seasons/{sid}", self.owner, json={"signup_open": False})
        self.providers.links["100"]["#P2Y"] = False
        body = {"user_id":"100", "pool":"lazy", "accounts":[{"tag":"#P2Y", "prefer_crystal_1_or_lower":True}]}
        blocked = await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)
        self.assertEqual(blocked.status, 423)
        added = await self.call("POST", f"/seasons/{sid}/staff-signups", self.owner, json=body)
        self.assertEqual(added.status, 201)
        rows = await (await self.call("GET", f"/seasons/{sid}/signups", self.member)).json()
        self.assertEqual(rows["signups"][0]["user_id"], "100")
        self.assertTrue(rows["signups"][0]["prefer_crystal_1_or_lower"])
        self.assertEqual(rows["signups"][0]["player_name"], "Alpha")
        audit = self.app["store"].one("SELECT * FROM roster_audit WHERE action='staff_signup'")
        self.assertIsNotNone(audit)
        self.assertEqual(audit["actor_id"], "505227988229554179")

    async def test_staff_signup_rejects_duplicates_atomically_and_unlinked_accounts(self):
        sid = await self.season()
        body = {"user_id":"100", "pool":"main", "accounts":[{"tag":"#P2Y", "prefer_crystal_1_or_lower":False}]}
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/staff-signups", self.owner, json=body)).status,201)
        body["accounts"].insert(0, {"tag":"#Q2Y", "prefer_crystal_1_or_lower":False})
        body["pool"]="lazy"
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/staff-signups", self.owner, json=body)).status,409)
        rows=self.app["store"].rows("SELECT * FROM signups WHERE season_id=?",(sid,))
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["pool"],"main")
        body["accounts"]=[{"tag":"#G2Y", "prefer_crystal_1_or_lower":False}]
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/staff-signups", self.owner, json=body)).status,409)

    async def test_staff_signup_requires_cwl_access_and_nonarchived_season(self):
        sid=await self.season()
        body={"user_id":"100", "pool":"main", "accounts":[{"tag":"#P2Y", "prefer_crystal_1_or_lower":False}]}
        for path in (f"/seasons/{sid}/staff-signups/accounts?user_id=100", "/staff-signup-members"):
            self.assertEqual((await self.call("GET",path,self.member)).status,403)
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups",self.member,json=body)).status,403)
        await self.call("POST","/access",self.owner,json={"user_id":"200","permissions":["clans"]})
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups",self.other,json=body)).status,403)
        await self.call("POST","/access",self.owner,json={"user_id":"200","permissions":["cwl"]})
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups",self.other,json=body)).status,201)
        await self.call("PATCH",f"/seasons/{sid}",self.owner,json={"status":"archived"})
        body["accounts"][0]["tag"]="#Q2Y"
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups",self.owner,json=body)).status,423)

    async def test_staff_signup_account_list_marks_existing_and_search_contains(self):
        sid=await self.season()
        body={"user_id":"100","pool":"main","accounts":[{"tag":"#P2Y","prefer_crystal_1_or_lower":False}]}
        await self.call("POST",f"/seasons/{sid}/staff-signups",self.owner,json=body)
        data=await (await self.call("GET",f"/seasons/{sid}/staff-signups/accounts?user_id=100",self.owner)).json()
        self.assertEqual(next(a for a in data["accounts"] if a["tag"]=="#P2Y")["signed_up_pool"],"main")
        rows=[{"user":{"id":"100","username":"PlayerOne","discriminator":"0"},"nick":"Friendly Warrior","roles":["123"]}]
        with patch("cwl_web.manage_roles.searchable_members",AsyncMock(return_value=rows)):
            found=await (await self.call("GET","/staff-signup-members?q=warrior",self.owner)).json()
        self.assertEqual(found["options"][0]["id"],"100")
        self.assertEqual(found["options"][0]["role_ids"],[])

    async def test_signup_member_names_include_every_signed_up_member_beyond_search_limit(self):
        sid = await self.season()
        rows = [{"user": {"id": str(1000+i), "username": f"Member{i}"}, "roles": []} for i in range(120)]
        with self.app["store"].tx() as db:
            for i in range(55, 120):
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,?,?,0,'Test player',18)", (sid, f"#TEST{i}", str(1000+i), "main"))
        with patch("cwl_web.manage_roles.searchable_members", AsyncMock(return_value=rows)):
            ordinary = await (await self.call("GET", "/staff-signup-members", self.owner)).json()
            scoped = await (await self.call("GET", f"/staff-signup-members?season_id={sid}", self.owner)).json()
            denied = await self.call("GET", f"/staff-signup-members?season_id={sid}", self.member)
            malformed = await self.call("GET", "/staff-signup-members?season_id=invalid", self.owner)
        self.assertEqual(len(ordinary["options"]), 50)
        self.assertTrue(ordinary["truncated"])
        self.assertEqual({item["id"] for item in scoped["options"]}, {str(1000+i) for i in range(55,120)})
        self.assertFalse(scoped["truncated"])
        self.assertEqual(denied.status, 403)
        self.assertEqual(malformed.status, 400)

    async def test_tag_signup_without_discord_and_manual_association(self):
        sid=await self.season()
        self.providers.linked_owner=AsyncMock(return_value=None)
        await self.call("PATCH",f"/seasons/{sid}",self.owner,json={"signup_open":False})
        lookup=await (await self.call("GET",f"/seasons/{sid}/staff-signups/player?tag=P2Y",self.owner)).json()
        self.assertEqual(lookup["account"]["name"],"Alpha");self.assertIsNone(lookup["linked_user_id"])
        body={"tag":"#P2Y","pool":"main","prefer_crystal_1_or_lower":False,"has_discord":False,"user_id":"","expected_linked_user_id":None}
        response=await self.call("POST",f"/seasons/{sid}/staff-signups/player",self.owner,json=body)
        self.assertEqual(response.status,201)
        row=self.app["store"].one("SELECT * FROM signups WHERE season_id=? AND tag=?",(sid,"#P2Y"))
        self.assertEqual(row["user_id"],"")
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups/player",self.owner,json=body)).status,409)
        body.update(tag="#Q2Y",has_discord=True,user_id="123456789012345678")
        self.assertEqual((await self.call("POST",f"/seasons/{sid}/staff-signups/player",self.owner,json=body)).status,201)
        member=self.auth("123456789012345678")
        records=await (await self.call("GET",f"/seasons/{sid}/signups",member)).json()
        self.assertEqual([r["tag"] for r in records["signups"]],["#Q2Y"])
        roster=await (await self.call("GET",f"/seasons/{sid}/roster",self.owner)).json()
        self.assertEqual(len(roster["accounts"]),2)

    async def test_tag_signup_links_cannot_be_reassigned_or_silently_changed(self):
        sid=await self.season();owner="123456789012345678"
        self.providers.linked_owner=AsyncMock(return_value=owner)
        body={"tag":"#P2Y","pool":"lazy","prefer_crystal_1_or_lower":True,"has_discord":True,"user_id":"223456789012345678","expected_linked_user_id":owner}
        path=f"/seasons/{sid}/staff-signups/player"
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,409)
        body.update(user_id=owner,expected_linked_user_id=None)
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,409)
        body['expected_linked_user_id']=owner
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,201)

    async def test_tag_signup_permissions_validation_archive_and_link_outage(self):
        sid=await self.season();path=f"/seasons/{sid}/staff-signups/player"
        self.providers.linked_owner=AsyncMock(return_value=None)
        body={"tag":"#P2Y","pool":"main","prefer_crystal_1_or_lower":False,"has_discord":False,"user_id":"","expected_linked_user_id":None}
        self.assertEqual((await self.call("POST",path,self.member,json=body)).status,403)
        self.assertEqual((await self.call("GET",path+"?tag=P2Y",self.member)).status,403)
        body.update(has_discord=True,user_id="bad")
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,400)
        body.update(has_discord=False,user_id="")
        self.providers.linked_owner=AsyncMock(side_effect=ProviderUnavailable("Links unavailable"))
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,503)
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM signups")),0)
        await self.call("PATCH",f"/seasons/{sid}",self.owner,json={"status":"archived"})
        self.assertEqual((await self.call("POST",path,self.owner,json=body)).status,423)

    async def test_fixture_login_is_disabled_without_explicit_mode(self):
        response = await self.call("POST", "/dev/login")
        self.assertEqual(response.status, 404)
        response = await self.call("GET", "/config")
        self.assertEqual((await response.json())["dev_fixture"], False)

    async def test_owner_grants_and_no_automatic_admin(self):
        response = await self.call("POST", "/seasons", self.member, json={"label": "October 2026", "signup_open": True})
        self.assertEqual(response.status, 403)
        response = await self.call("POST", "/access", self.member, json={"user_id": "200"})
        self.assertEqual(response.status, 403)
        response = await self.call("POST", "/access", self.owner, json={"user_id": "100", "permissions": ["cwl"]})
        self.assertEqual(response.status, 201)
        response = await self.call("POST", "/seasons", self.member, json={"label": "October 2026", "signup_open": True})
        self.assertEqual(response.status, 201)
        response = await self.call("DELETE", "/access/100", self.owner)
        self.assertEqual(response.status, 200)
        response = await self.call("PATCH", "/seasons/1", self.member, json={"signup_open": False})
        self.assertEqual(response.status, 403)

    async def test_scoped_grants_replace_access_without_broadening(self):
        for permissions in (None, [], ['everything'], ['tickets', 42]):
            response = await self.call('POST', '/access', self.owner, json={'user_id': '100', 'permissions': permissions})
            self.assertEqual(response.status, 400)
        response = await self.call('POST', '/access', self.owner, json={'user_id': '100', 'permissions': ['tickets']})
        self.assertEqual(response.status, 201)
        response = await self.call('GET', '/auth/me', self.member)
        data = await response.json()
        self.assertFalse(data['can_edit'])
        self.assertEqual(data['dashboard_permissions'], ['tickets'])
        response = await self.call('POST', '/seasons', self.member, json={'label': 'No access'})
        self.assertEqual(response.status, 403)
        response = await self.call('POST', '/access', self.owner, json={'user_id': '100', 'permissions': ['cwl']})
        self.assertEqual(response.status, 201)
        response = await self.call('GET', '/auth/me', self.member)
        data = await response.json()
        self.assertTrue(data['can_edit'])
        self.assertEqual(data['dashboard_permissions'], ['cwl'])
        response = await self.call('GET', '/access', self.member)
        self.assertEqual(response.status, 403)

    async def test_confirmed_pool_transfer_both_directions_preserves_signup_clan(self):
        sid = await self.season()
        account = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [account]})
        self.assertEqual(response.status, 200)
        self.providers.players["#P2Y"]["current_clan_tag"] = "#J2Y"
        for target, source in (("lazy", "main"), ("main", "lazy")):
            moved = {**account, "move_from_pool": source}
            response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                       json={"pool": target, "accounts": [moved]})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["moved"], 1)
            rows = self.app["store"].rows("SELECT pool,signup_clan_tag FROM signups")
            self.assertEqual(rows, [{"pool": target, "signup_clan_tag": "#R2Y"}])

    async def test_pool_transfer_requires_fresh_matching_confirmation(self):
        sid = await self.season()
        account = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
        stale = {**account, "move_from_pool": "main"}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [stale]})
        self.assertEqual(response.status, 409)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [account]})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [stale]})
        self.assertEqual(response.status, 409)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [{**account, "move_from_pool": "lazy"}]})
        self.assertEqual(response.status, 409)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [stale]})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [stale]})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT pool FROM signups"), [{"pool": "lazy"}])

    async def test_transfer_batch_rolls_back_and_cannot_move_other_member(self):
        sid = await self.season()
        first = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
        second = {"tag": "#Q2Y", "prefer_crystal_1_or_lower": False}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [first]})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [second, {**first, "move_from_pool": "lazy"}]})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT tag,pool FROM signups"), [{"tag": "#P2Y", "pool": "main"}])
        self.providers.links["200"]["#P2Y"] = True
        response = await self.call("POST", f"/seasons/{sid}/signups", self.other,
                                   json={"pool": "lazy", "accounts": [{**first, "move_from_pool": "main"}]})
        self.assertEqual(response.status, 409)
        response = await self.call("PATCH", f"/seasons/{sid}", self.owner, json={"signup_open": False})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [{**first, "move_from_pool": "main"}]})
        self.assertEqual(response.status, 423)
        self.assertEqual(self.app["store"].rows("SELECT tag,pool FROM signups"), [{"tag": "#P2Y", "pool": "main"}])

    async def test_outside_family_account_moves_both_directions(self):
        sid = await self.season()
        account = {"tag": "#Q2Y", "prefer_crystal_1_or_lower": True}
        for pool, source in (("main", None), ("lazy", "main"), ("main", "lazy")):
            item = {**account}
            if source is not None:
                item["move_from_pool"] = source
            response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                       json={"pool": pool, "accounts": [item]})
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["moved"], 0 if source is None else 1)
            response = await self.call("GET", f"/seasons/{sid}/signups", self.member)
            signup = (await response.json())["signups"][0]
            self.assertEqual(signup["pool"], pool)
            self.assertEqual(signup["family_clan_status"], "outside")
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "lazy", "accounts": [{**account, "move_from_pool": "lazy"}]})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].rows("SELECT pool FROM signups"), [{"pool": "main"}])

    async def test_invalid_or_null_transfer_source_is_rejected(self):
        sid = await self.season()
        account = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
        for bad in (None, "fwa", 0):
            response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                       json={"pool": "lazy", "accounts": [{**account, "move_from_pool": bad}]})
            self.assertEqual(response.status, 400)
        self.assertEqual(self.app["store"].rows("SELECT * FROM signups"), [])

    async def test_csrf_and_idor(self):
        sid = await self.season()
        response = await self.call("POST", f"/seasons/{sid}/signups", {"Cookie": self.member["Cookie"]}, json={"pool": "main", "accounts": []})
        self.assertEqual(response.status, 403)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "main", "accounts": [{"tag": "#G2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 403)

    async def test_cross_pool_duplicate_and_atomic_replacement(self):
        sid = await self.season()
        main = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json=main)
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": True}]})
        self.assertEqual(response.status, 409)
        rows = self.app["store"].rows("SELECT tag,pool FROM signups")
        self.assertEqual(rows, [{"tag": "#P2Y", "pool": "main"}])
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json=main)
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM signups")), 1)

    async def test_lazy_accepts_outside_family_and_unverified_links(self):
        sid = await self.season()
        self.providers.links["100"]["#P2Y"] = False
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": True}]})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", "/linked-accounts", self.member)
        account = next(a for a in (await response.json())["accounts"] if a["tag"] == "#P2Y")
        self.assertFalse(account["verified"])
        self.assertTrue(account["lazy_eligible"])
        self.assertEqual(account["family_clan_status"], "approved")
        self.providers.links["100"]["#Q2Y"] = False
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "lazy", "accounts": [{"tag": "#Q2Y", "prefer_crystal_1_or_lower": True}]})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{sid}/signups?all=1", self.owner)
        statuses = {item["tag"]: item["family_clan_status"] for item in (await response.json())["signups"]}
        self.assertEqual(statuses, {"#P2Y": "approved", "#Q2Y": "outside"})
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": True}]})
        self.assertEqual(response.status, 200)

    async def test_unverified_linked_account_can_join_main(self):
        sid = await self.season()
        self.providers.links["100"]["#Q2Y"] = False
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "main", "accounts": [{"tag": "#Q2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)

    async def test_signup_family_status_uses_saved_signup_clan(self):
        sid = await self.season()
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)
        self.providers.players["#P2Y"]["current_clan_tag"] = "#J2Y"
        self.providers.players["#P2Y"]["current_clan_name"] = "Outside"
        response = await self.call("GET", "/linked-accounts", self.member)
        account = next(a for a in (await response.json())["accounts"] if a["tag"] == "#P2Y")
        self.assertEqual(account["family_clan_status"], "outside")
        response = await self.call("GET", f"/seasons/{sid}/signups?all=1", self.owner)
        signup = (await response.json())["signups"][0]
        self.assertEqual(signup["signup_clan_tag"], "#R2Y")
        self.assertEqual(signup["family_clan_status"], "approved")

    async def test_closed_signup_and_provider_outage(self):
        sid = await self.season()
        response = await self.call("PATCH", f"/seasons/{sid}", self.owner, json={"signup_open": False})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json={"pool": "main", "accounts": []})
        self.assertEqual(response.status, 423)
        async def outage(_):
            raise ProviderUnavailable("Links unavailable")
        self.providers.linked_tags = outage
        response = await self.call("GET", "/linked-accounts", self.member)
        self.assertEqual(response.status, 503)


    async def test_concurrent_opposing_pool_writes(self):
        sid = await self.season()
        main = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        lazy = {"pool": "lazy", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": True}]}
        responses = await asyncio.gather(
            self.call("POST", f"/seasons/{sid}/signups", self.member, json=main),
            self.call("POST", f"/seasons/{sid}/signups", self.member, json=lazy),
        )
        self.assertEqual(sorted(r.status for r in responses), [200, 409])
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM signups")), 1)

    async def test_disappeared_link_preserves_registered_signup(self):
        sid = await self.season()
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)
        del self.providers.links["100"]["#P2Y"]
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": []})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.app["store"].rows("SELECT * FROM signups")), 1)

    async def test_conflict_batch_rolls_back_all_accounts(self):
        sid = await self.season()
        self.providers.links["200"]["#P2Y"] = True
        response = await self.call("POST", f"/seasons/{sid}/signups", self.other,
                                   json={"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [
                                       {"tag": "#Q2Y", "prefer_crystal_1_or_lower": False},
                                       {"tag": "#P2Y", "prefer_crystal_1_or_lower": False},
                                   ]})
        self.assertEqual(response.status, 409)
        self.assertEqual([r["tag"] for r in self.app["store"].rows("SELECT tag FROM signups")], ["#P2Y"])

    async def test_staff_all_and_member_privacy(self):
        sid = await self.season()
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                   json={"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{sid}/signups?all=1", self.other)
        self.assertEqual((await response.json())["signups"], [])
        response = await self.call("GET", f"/seasons/{sid}/signups?all=1", self.owner)
        self.assertEqual(len((await response.json())["signups"]), 1)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_guild_owner_session_and_persistence(self):
        guild_owner = self.auth("300", owner=True)
        response = await self.call("POST", "/seasons", guild_owner,
                                   json={"label": "November 2026", "signup_open": False})
        self.assertEqual(response.status, 201)
        reopened = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"), providers=self.providers)
        self.assertEqual(reopened["store"].one("SELECT label FROM seasons WHERE id=1")["label"], "November 2026")

    async def test_oauth_browser_recovery_and_authorization_url(self):
        from urllib.parse import parse_qs, urlparse
        self.app["oauth"] = {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://example.test/callback"}
        response = await self.call("GET", "/auth/discord", allow_redirects=False)
        url = response.headers["Location"]
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params["prompt"], ["none"])
        self.assertIn("scope=identify%20guilds", url)
        response = await self.call("GET", "/auth/discord?retry=1", allow_redirects=False)
        self.assertEqual(parse_qs(urlparse(response.headers["Location"]).query)["prompt"], ["consent"])
        response = await self.call("GET", "/auth/callback?error=access_denied", {"Accept": "text/html"}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/?signin_error=discord")
        self.assertIn("no-store", response.headers["Cache-Control"])

    async def test_oauth_destination_survives_browser_failure(self):
        self.app["oauth"] = {"client_id":"id", "client_secret":"secret", "redirect_uri":"https://example.test/callback"}
        started = await self.call("GET", "/auth/discord?view=signup&season=12", allow_redirects=False)
        self.assertEqual(started.cookies["wu_login_page"].value, "/?view=signup&season=12")
        self.assertTrue(started.cookies["wu_login_page"]["httponly"])
        response = await self.call("GET", "/auth/callback?error=access_denied", {"Accept":"text/html", "Cookie":"wu_login_page=/?view=signup&season=12"}, allow_redirects=False)
        self.assertEqual(response.headers["Location"], "/?view=signup&season=12&signin_error=discord")

    async def test_oauth_state_is_one_time_and_expires_server_side(self):
        self.app["oauth"] = {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://example.test/callback"}
        response = await self.call("GET", "/auth/discord", allow_redirects=False)
        self.assertEqual(response.status, 302)
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(response.headers["Location"]).query)["state"][0]
        cookie = response.cookies["cwl_oauth_state"].value
        state_header = {"Cookie": "cwl_oauth_state=" + cookie}
        with self.app["store"].tx() as db:
            db.execute("UPDATE oauth_states SET expires_at=0")
        response = await self.call("GET", f"/auth/callback?state={state}&code=dummy", state_header)
        self.assertEqual(response.status, 403)

    async def test_oauth_guild_owner_is_resolved_from_discord(self):
        self.app["oauth"] = {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://example.test/callback"}
        response = await self.call("GET", "/auth/discord", allow_redirects=False)
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(response.headers["Location"]).query)["state"][0]
        cookie = response.cookies["cwl_oauth_state"].value

        class FakeResponse:
            status = 200
            def __init__(self, payload):
                self.payload = payload
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def json(self):
                return self.payload

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            def post(self, url, **kwargs):
                return FakeResponse({"access_token": "test-token"})
            def get(self, url, **kwargs):
                if url.endswith("/users/@me"):
                    return FakeResponse({"id": "300", "username": "owner_handle", "global_name": "Current owner", "avatar": "a_0123456789abcdef0123456789abcdef"})
                return FakeResponse([{"id": "644963518025826315", "owner": True}])

        with patch("cwl_web.app.aiohttp.ClientSession", return_value=FakeSession()):
            response = await self.call("GET", f"/auth/callback?state={state}&code=code",
                                       {"Cookie": "cwl_oauth_state=" + cookie + "; wu_login_page=/?view=signup&season=12"}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/?view=signup&season=12")
        self.assertEqual(response.cookies["wu_login_page"]["max-age"], "0")
        raw = response.cookies["cwl_session"].value
        self.assertEqual(int(response.cookies["cwl_session"]["max-age"]), 30 * 86400)
        self.assertTrue(response.cookies["cwl_session"]["httponly"])
        self.assertEqual(response.cookies["cwl_session"]["samesite"], "Lax")
        session = self.app["store"].one("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(raw.encode()).hexdigest(),))
        self.assertAlmostEqual(session["expires_at"] - time.time(), 30 * 86400, delta=5)
        with patch("cwl_web.app.time.time", return_value=time.time() + 29 * 86400):
            later = await self.call("GET", "/auth/me", {"Cookie": "cwl_session=" + raw})
            self.assertEqual(later.status, 200)
        with patch("cwl_web.app.time.time", return_value=time.time() + 31 * 86400):
            expired = await self.call("GET", "/auth/me", {"Cookie": "cwl_session=" + raw})
            self.assertEqual(expired.status, 401)
        response = await self.call("GET", "/auth/me", {"Cookie": "cwl_session=" + raw})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["is_owner"])
        self.assertEqual(payload["user"], {"id": "300", "username": "owner_handle", "display_name": "Current owner",
                                           "avatar_url": "https://cdn.discordapp.com/avatars/300/a_0123456789abcdef0123456789abcdef.gif"})

        signed_out = await self.call("POST", "/auth/logout", {"Cookie": "cwl_session=" + raw, "X-CSRF-Token": session["csrf"]}, json={})
        self.assertEqual(signed_out.status, 200)
        reused = await self.call("GET", "/auth/me", {"Cookie": "cwl_session=" + raw})
        self.assertEqual(reused.status, 401)

    async def test_discord_avatar_urls_and_display_name_fallback(self):
        image = "0123456789abcdef0123456789abcdef"
        self.assertEqual(_discord_avatar_url({"id": "300", "avatar": image}),
                         f"https://cdn.discordapp.com/avatars/300/{image}.png")
        self.assertEqual(_discord_avatar_url({"id": "300", "avatar": "a_" + image}),
                         f"https://cdn.discordapp.com/avatars/300/a_{image}.gif")
        self.assertEqual(_discord_avatar_url({"id": "300", "avatar": None, "discriminator": "1234"}),
                         "https://cdn.discordapp.com/embed/avatars/4.png")
        migrated_id = str(5 << 22)
        self.assertEqual(_discord_avatar_url({"id": migrated_id, "avatar": None, "discriminator": "0"}),
                         "https://cdn.discordapp.com/embed/avatars/5.png")
        self.assertEqual(_discord_avatar_url({"id": "300", "avatar": "https://evil.test/pic"}),
                         "https://cdn.discordapp.com/embed/avatars/0.png")
        response = await self.call("GET", "/auth/me", self.member)
        self.assertEqual((await response.json())["user"],
                         {"id": "100", "username": "100", "display_name": "100", "avatar_url": None})

    async def test_old_session_database_migrates_without_losing_sessions_or_signups(self):
        path = Path(self.tmp.name) / "old.sqlite"
        raw = "old-session"
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    username TEXT NOT NULL, guild_owner INTEGER NOT NULL, csrf TEXT NOT NULL,
                    expires_at INTEGER NOT NULL);
                CREATE TABLE seasons (id INTEGER PRIMARY KEY, label TEXT NOT NULL UNIQUE,
                    signup_open INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'draft');
                CREATE TABLE signups (season_id INTEGER NOT NULL, tag TEXT NOT NULL,
                    user_id TEXT NOT NULL, pool TEXT NOT NULL, prefer_crystal_1_or_lower INTEGER NOT NULL,
                    player_name TEXT NOT NULL, town_hall INTEGER NOT NULL, signup_clan_tag TEXT,
                    signup_clan_name TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(season_id,tag));
            """)
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                       (hashlib.sha256(raw.encode()).hexdigest(), "100", "old_name", 0, "csrf", int(time.time()) + 900))
            db.execute("INSERT INTO seasons(id,label) VALUES (1,'Existing season')")
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (1,'#P2Y','100','main',0,'Alpha',16)")
        old_app = create_app(db_path=str(path), providers=self.providers, secure_cookies=False)
        old_client = TestClient(TestServer(old_app))
        await old_client.start_server()
        try:
            response = await old_client.get("/api/cwl/auth/me", headers={"Cookie": "cwl_session=" + raw})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["user"],
                             {"id": "100", "username": "old_name", "display_name": "old_name", "avatar_url": None})
            self.assertEqual(old_app["store"].one("SELECT player_name FROM signups")["player_name"], "Alpha")
            self.assertEqual({row["name"] for row in old_app["store"].rows("PRAGMA table_info(sessions)")},
                             {"token_hash", "user_id", "username", "guild_owner", "csrf", "expires_at", "display_name", "avatar_url"})
        finally:
            await old_client.close()

    async def test_family_clan_directory_is_read_only(self):
        response = await self.call("GET", "/approved-clans", self.owner)
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["source"], "fixture")
        self.assertEqual(payload["clans"], [{"tag": "#R2Y", "name": "Family", "cwl_league": None, "cwl_league_stale": False}])
        response = await self.call("POST", "/approved-clans", self.owner, json={"tag": "#J2Y"})
        self.assertEqual(response.status, 405)
        response = await self.call("DELETE", "/approved-clans/%23R2Y", self.owner)
        self.assertEqual(response.status, 405)

    async def test_family_directory_outage_marks_unknown_without_blocking(self):
        sid = await self.season()
        async def outage():
            raise ProviderUnavailable("Family-clan directory unavailable")
        self.providers.family_clans = outage
        response = await self.call("GET", "/linked-accounts", self.member)
        self.assertEqual(response.status, 200)
        accounts = (await response.json())["accounts"]
        self.assertEqual({item["family_clan_status"] for item in accounts}, {"unknown"})
        for pool, value in (("lazy", "#P2Y"), ("main", "#Q2Y")):
            response = await self.call("POST", f"/seasons/{sid}/signups", self.member,
                                       json={"pool": pool, "accounts": [{"tag": value, "prefer_crystal_1_or_lower": True}]})
            self.assertEqual(response.status, 200 if pool == "lazy" else 503)
        response = await self.call("GET", f"/seasons/{sid}/signups?all=1", self.owner)
        signups = (await response.json())["signups"]
        self.assertEqual({item["family_clan_status"] for item in signups}, {"unknown"})
        response = await self.call("GET", "/approved-clans", self.owner)
        self.assertEqual(response.status, 503)


    async def test_missing_family_directory_configuration_fails_closed(self):
        provider = LiveProviders(mongo_uri="", routes={})
        with self.assertRaises(ProviderUnavailable):
            await provider.family_clans()

    async def test_live_family_filter_excludes_hosting_and_unknown_types(self):
        calls = []
        class Cursor:
            async def to_list(self, length):
                assert length == 201
                return [
                    {"tag": "#R2Y", "name": "FWA Home", "type": "FWA"},
                    {"tag": "#P2Y", "name": "Main Home", "type": "Tactical"},
                    {"tag": "#Q2Y", "name": "CWL Host", "type": "CWL Hosting"},
                    {"tag": "#G2Y", "name": "Other", "type": "Unknown"},
                ]
        class Collection:
            def find(self, query, projection, **kwargs):
                calls.append(query)
                return Cursor()
        class Client:
            def __init__(self, *args, **kwargs):
                pass
            async def close(self):
                pass
        with patch("cwl_web.providers.AsyncMongoClient", Client), patch("cwl_web.providers.collection_for", return_value=Collection()):
            data = await LiveProviders(mongo_uri="mongodb://unused", routes={}).family_clans()
        self.assertEqual({item["tag"] for item in data["clans"]}, {"#R2Y", "#P2Y"})
        self.assertEqual(calls, [{"type": {"$in": ["FWA", "Tactical", "Flexible Fun", "Competitive"]}}])

    async def test_live_link_adapter_filters_other_users_and_retains_verification_metadata(self):
        items = [
            {"user_id": "999", "player_tag": "#P2Y", "is_verified": True},
            {"user_id": "100", "player_tag": "#Q2Y", "is_verified": False},
            {"user_id": "100", "player_tag": "#G2Y", "is_verified": True},
        ]
        with patch("cwl_web.providers._lookup_shared_links", new=AsyncMock(return_value=items)), patch("cwl_web.providers._lookup_clashperk_links", new=AsyncMock(return_value=[])):
            links = await LiveProviders(coc_token="unused").linked_tags("100")
        self.assertEqual(links, {"#Q2Y": False, "#G2Y": True})


if __name__ == "__main__":
    unittest.main()
