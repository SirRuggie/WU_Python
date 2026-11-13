"""Non-members can sign in; only a CWL signup save needs the server (prompt 238)."""

import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.discord_member import _guild_member
from cwl_web.server_membership import CACHE_KEY, CHECK_KEY, CHECK_UNAVAILABLE, JOIN_REQUIRED
from dashboard_access_fakes import AccessCollection
from test_cwl_web_foundation import FakeProviders
from utils.cwl_member_service import MemberError

GUILD_ID = "644963518025826315"
NON_MEMBER = "200"


class FakeMembership:
    """Stands in for the live Discord member lookup."""

    def __init__(self):
        self.outside = {NON_MEMBER}
        self.unavailable = False
        self.calls = []

    async def __call__(self, request, user_id):
        self.calls.append(user_id)
        if self.unavailable:
            raise MemberError(503, "Discord membership check is unavailable")
        if user_id in self.outside:
            raise MemberError(403, "Warriors United membership required")


class NonMemberSignInTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = FakeProviders()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"), providers=self.providers,
                              secure_cookies=False, live_access=True)
        self.app["server_management_mongo"] = SimpleNamespace(bot_config=AccessCollection())
        self.app["server_management_discord"] = AsyncMock(return_value={"user": {"username": "Test member"}, "roles": []})
        self.membership = FakeMembership()
        self.app[CHECK_KEY] = self.membership
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth("505227988229554179")
        self.member = self.auth("100")
        self.outsider = self.auth(NON_MEMBER)

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

    async def season(self):
        response = await self.call("POST", "/seasons", self.owner, json={"label": "October 2026", "signup_open": True})
        self.assertEqual(response.status, 201)
        return (await response.json())["id"]

    def counts(self):
        with self.app["store"].tx() as db:
            return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("signups", "roster_entries")}

    async def sign_in(self, guilds):
        self.app["oauth"] = {"client_id": "id", "client_secret": "secret", "redirect_uri": "https://example.test/callback"}
        response = await self.call("GET", "/auth/discord", allow_redirects=False)
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
                    return FakeResponse({"id": "300", "username": "outsider", "global_name": "Outsider"})
                return FakeResponse(guilds)

        with patch("cwl_web.app.aiohttp.ClientSession", return_value=FakeSession()):
            response = await self.call("GET", f"/auth/callback?state={state}&code=code",
                                       {"Cookie": "cwl_oauth_state=" + cookie}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        raw = response.cookies["cwl_session"].value
        return self.app["store"].one("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(raw.encode()).hexdigest(),))

    async def test_sign_in_no_longer_needs_the_server(self):
        session = await self.sign_in([{"id": "1", "owner": True}])
        self.assertEqual(session["user_id"], "300")
        self.assertEqual(session["guild_owner"], 0)

    async def test_server_owner_is_still_recorded(self):
        session = await self.sign_in([{"id": GUILD_ID, "owner": True}])
        self.assertEqual(session["guild_owner"], 1)

    async def test_auth_me_reports_server_membership(self):
        member = await (await self.call("GET", "/auth/me", self.member)).json()
        outsider = await (await self.call("GET", "/auth/me", self.outsider)).json()
        self.assertIs(member["server_member"], True)
        self.assertIs(outsider["server_member"], False)

    async def test_auth_me_never_fails_or_caches_when_discord_is_down(self):
        self.membership.unavailable = True
        response = await self.call("GET", "/auth/me", self.outsider)
        self.assertEqual(response.status, 200)
        self.assertIsNone((await response.json())["server_member"])
        self.assertNotIn(NON_MEMBER, self.app.get(CACHE_KEY, {}))

    async def test_auth_me_uses_a_short_cache(self):
        await self.call("GET", "/auth/me", self.outsider)
        await self.call("GET", "/auth/me", self.outsider)
        self.assertEqual(self.membership.calls.count(NON_MEMBER), 1)
        expires, value = self.app[CACHE_KEY][NON_MEMBER]
        self.assertFalse(value)
        self.assertLessEqual(expires - time.monotonic(), 60)

    async def test_non_member_keeps_personal_reads(self):
        sid = await self.season()
        for path in ("/linked-accounts", f"/seasons/{sid}/signups", f"/seasons/{sid}/my-assignments", "/seasons"):
            response = await self.call("GET", path, self.outsider)
            self.assertEqual(response.status, 200, path)
        accounts = await (await self.call("GET", "/linked-accounts", self.outsider)).json()
        self.assertEqual([item["tag"] for item in accounts["accounts"]], ["#G2Y"])

    async def test_non_member_keeps_tasks_and_dashboard_accounts(self):
        async def snapshot(app, user_id, state):
            state.update(snapshot={"user": user_id}, updating=False)
            return {"user": user_id}

        with patch("cwl_web.todo._snapshot", snapshot):
            response = await self.call("GET", "/todo", self.outsider)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["user"], NON_MEMBER)
        self.providers.weights = AsyncMock(return_value={})
        response = await self.call("GET", "/dashboard/accounts", self.outsider)
        self.assertEqual(response.status, 200)
        self.assertNotIn(NON_MEMBER, self.membership.calls[1:])

    async def test_non_member_stays_out_of_staff_routes(self):
        sid = await self.season()
        for method, path in (("GET", f"/seasons/{sid}/roster"), ("GET", "/staff-signup-members"),
                             ("POST", "/seasons"), ("PATCH", f"/seasons/{sid}")):
            response = await self.call(method, path, self.outsider, json={})
            self.assertEqual(response.status, 403, path)

    async def test_non_member_cannot_save_a_signup(self):
        sid = await self.season()
        before = self.counts()
        body = {"pool": "lazy", "accounts": [{"tag": "#G2Y", "prefer_crystal_1_or_lower": False}]}
        for _ in range(2):
            response = await self.call("POST", f"/seasons/{sid}/signups", self.outsider, json=body)
            self.assertEqual(response.status, 403)
            self.assertEqual((await response.json())["error"], JOIN_REQUIRED)
        self.assertEqual(self.counts(), before)

    async def test_member_can_still_save_a_signup(self):
        sid = await self.season()
        body = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.counts()["signups"], 1)

    async def test_unavailable_check_refuses_without_writing(self):
        sid = await self.season()
        self.membership.unavailable = True
        before = self.counts()
        body = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.member, json=body)
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], CHECK_UNAVAILABLE)
        self.assertEqual(self.counts(), before)

    async def test_owner_is_checked_too(self):
        sid = await self.season()
        self.membership.outside.add("505227988229554179")
        body = {"pool": "main", "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}]}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.owner, json=body)
        self.assertEqual(response.status, 403)

    async def test_joining_allows_a_save_at_once(self):
        sid = await self.season()
        me = await (await self.call("GET", "/auth/me", self.outsider)).json()
        self.assertIs(me["server_member"], False)
        self.membership.outside.discard(NON_MEMBER)
        body = {"pool": "lazy", "accounts": [{"tag": "#G2Y", "prefer_crystal_1_or_lower": False}]}
        response = await self.call("POST", f"/seasons/{sid}/signups", self.outsider, json=body)
        self.assertEqual(response.status, 200)
        me = await (await self.call("GET", "/auth/me", self.outsider)).json()
        self.assertIs(me["server_member"], True)

    async def test_non_member_can_withdraw_an_existing_signup(self):
        sid = await self.season()
        self.membership.outside.discard(NON_MEMBER)
        body = {"pool": "lazy", "accounts": [{"tag": "#G2Y", "prefer_crystal_1_or_lower": False}]}
        self.assertEqual((await self.call("POST", f"/seasons/{sid}/signups", self.outsider, json=body)).status, 200)
        self.membership.outside.add(NON_MEMBER)
        response = await self.call("DELETE", f"/seasons/{sid}/signups/%23G2Y", self.outsider)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.counts()["signups"], 0)


def test_tasks_show_a_war_in_a_clan_outside_the_family(monkeypatch):
    """Tasks have no family filter: any current clan's war shows (D2)."""
    import asyncio
    from test_todo_clan_history import _Member, _War, _account
    from utils import todo_data

    war = _War("#HOME", "Not Family", [_Member("#PLAYER", attacks=1)], 2)

    async def fake_war(_client, clan_tag):
        return ("war", war) if clan_tag == "#HOME" else ("none", None)

    async def no_cwl(_client, _clan_tag):
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    monkeypatch.setattr(todo_data, "_get_cwl_round", no_cwl)
    todo_data._cache.clear()
    view = asyncio.run(todo_data.build_war_view(object(), [_account()]))
    assert [(row.clan_tag, row.used, row.limit) for row in view.rows] == [("#HOME", 1, 2)]


class ProductionWiringTests(unittest.TestCase):
    def test_production_app_uses_the_live_discord_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=str(Path(tmp) / "cwl.sqlite"), secure_cookies=False)
            self.assertIs(app[CHECK_KEY], _guild_member)

    def test_fixture_app_has_no_discord_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=str(Path(tmp) / "cwl.sqlite"), dev_fixture=True, secure_cookies=False)
            self.assertNotIn(CHECK_KEY, app)


if __name__ == "__main__":
    unittest.main()
