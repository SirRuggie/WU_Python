"""Actual isolated HTTP permission/CSRF/bridge boundaries; all Discord reads are fake."""

import os
import unittest
from unittest.mock import AsyncMock, patch
from tests import test_cwl_web_roster as roster_fixture
from cwl_web import cwl_pool_roles as http
from utils import cwl_pool_roles as service
from test_cwl_pool_roles import USER, ROLE, TOP, BOT, bot_fixture, claim, send_for
from extensions.tasks.cwl_pool_roles import process_job

OWNER = "505227988229554179"


class PoolRolesHTTP(unittest.IsolatedAsyncioTestCase):
    auth = roster_fixture.RosterTests.auth
    revision = roster_fixture.RosterTests.revision
    call = roster_fixture.RosterTests.call

    async def asyncSetUp(self):
        await roster_fixture.RosterTests.asyncSetUp(self)
        self.providers.links[USER] = self.providers.links["100"]
        self.member = self.auth(USER)
        options = [
            {"id": str(service.GUILD_ID), "name": "@everyone", "position": 0},
            {
                "id": str(TOP),
                "name": "Bot top",
                "position": 100,
                "permissions": 1 << 28,
            },
            {"id": ROLE, "name": "CWL", "position": 1},
            {
                "id": "444444444444444444",
                "name": "Admin",
                "position": 1,
                "permissions": 8,
            },
            {
                "id": "555555555555555555",
                "name": "Managed",
                "position": 1,
                "managed": True,
            },
            {"id": "666666666666666666", "name": "Above bot", "position": 101},
        ]
        actor = {
            "user_id": OWNER,
            "roles": options,
            "guild": {"owner_id": OWNER},
            "member": {"user": {"id": OWNER}, "roles": []},
        }

        async def read(request, method, path, **kwargs):
            assert method == "GET", "Web process may never change Discord roles"
            if path == "/users/@me":
                return {"id": str(BOT)}
            if path.endswith("/members/" + str(BOT)):
                return {"user": {"id": str(BOT)}, "roles": [str(TOP)]}
            raise AssertionError(path)

        self.discord = AsyncMock(side_effect=read)
        for item in [
            patch.object(http, "identity", AsyncMock(return_value=actor)),
            patch("cwl_web.manage_roles.discord", self.discord),
            patch.dict(os.environ, {"CWL_DISCORD_BRIDGE_SECRET": "s" * 40}),
        ]:
            item.start()
            self.addCleanup(item.stop)

    async def asyncTearDown(self):
        await roster_fixture.RosterTests.asyncTearDown(self)

    async def state(self):
        response = await self.call("GET", "/pool-roles", self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def configure(self, role=ROLE):
        state = await self.state()
        row = next(r for r in state["pools"] if r["pool"] == "main")
        response = await self.call(
            "POST",
            "/pool-roles",
            self.owner,
            json={
                "pool": "main",
                "role_id": role,
                "revision": row["revision"],
                "member_basis": row["member_basis"],
            },
        )
        return response

    async def test_picker_and_server_exclude_admin_managed_everyone_and_above_bot(self):
        state = await self.state()
        self.assertEqual(state["roles"], [{"id": ROLE, "name": "CWL"}])
        for role in (
            str(service.GUILD_ID),
            "444444444444444444",
            "555555555555555555",
            "666666666666666666",
        ):
            response = await self.configure(role)
            self.assertEqual(response.status, 400)
        with self.app["store"].tx() as db:
            self.assertTrue(
                all(r["role_id"] is None for r in service.snapshot(db)["pools"])
            )

    async def test_seasons_permission_and_csrf_fail_closed_before_discord(self):
        response = await self.call("GET", "/pool-roles", self.member)
        self.assertEqual(response.status, 403)
        self.discord.assert_not_awaited()
        response = await self.call(
            "POST", "/pool-roles", {"Cookie": self.owner["Cookie"]}, json={}
        )
        self.assertEqual(response.status, 403)
        self.discord.assert_not_awaited()

    async def test_dashboard_signup_succeeds_with_broken_role_and_failure_is_recorded(
        self,
    ):
        self.assertEqual((await self.configure()).status, 200)
        before = self.discord.await_count
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/signups",
            self.member,
            json={
                "pool": "main",
                "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}],
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.discord.await_count, before)
        bot, _, role, _ = bot_fixture()
        role.permissions = 8
        await process_job(
            bot, claim(self.app["store"]), send=send_for(self.app["store"])
        )
        with self.app["store"].tx() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM signups WHERE user_id=?", (USER,)
                ).fetchone()[0],
                1,
            )
            self.assertTrue(any(r["failure"] for r in service.snapshot(db)["pools"]))

    async def test_status_poll_has_no_discord_reads_and_clear_has_no_removal_job(self):
        self.assertEqual((await self.configure()).status, 200)
        self.discord.reset_mock()
        response = await self.call("GET", "/pool-roles?status=1", self.owner)
        self.assertEqual(response.status, 200)
        self.discord.assert_not_awaited()
        row = next(r for r in (await response.json())["pools"] if r["pool"] == "main")
        self.discord.reset_mock()
        response = await self.call(
            "POST",
            "/pool-roles",
            self.owner,
            json={
                "pool": "main",
                "role_id": None,
                "revision": row["revision"],
                "member_basis": row["member_basis"],
            },
        )
        self.assertEqual(response.status, 200)
        self.discord.assert_not_awaited()
        with self.app["store"].tx() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0], 0
            )

    async def test_bridge_secret_guild_and_receipt_scope(self):
        path = "/discord/pool-roles"
        body = {"action": "claim", "guild_id": str(service.GUILD_ID)}
        response = await self.call("POST", path, json=body)
        self.assertEqual(response.status, 403)
        headers = {"X-CWL-Discord-Secret": "s" * 40}
        response = await self.call(
            "POST", path, headers, json={**body, "guild_id": "1"}
        )
        self.assertEqual(response.status, 403)
        response = await self.call("POST", path, headers, json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"job": None})
        response = await self.call(
            "POST", path, headers, json={**body, "role_id": ROLE}
        )
        self.assertEqual(response.status, 400)
        response = await self.call(
            "POST",
            path,
            headers,
            json={
                "action": "finish",
                "guild_id": str(service.GUILD_ID),
                "id": "unknown",
                "lease_token": "forged",
                "generation": 1,
            },
        )
        self.assertEqual(await response.json(), {"accepted": False})

    async def test_discord_submit_and_withdraw_use_identical_outbox(self):
        self.assertEqual((await self.configure()).status, 200)
        headers = {"X-CWL-Discord-Secret": "s" * 40}
        with patch("cwl_web.discord_member._guild_member", AsyncMock()):
            response = await self.call(
                "POST",
                "/discord/member",
                headers,
                json={
                    "action": "submit",
                    "guild_id": str(service.GUILD_ID),
                    "user_id": USER,
                    "season_id": self.sid,
                    "pool": "main",
                    "expected_revision": await self.revision(),
                    "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}],
                },
            )
            self.assertEqual(response.status, 200, await response.text())
            with self.app["store"].tx() as db:
                jobs = db.execute("SELECT * FROM cwl_pool_role_jobs").fetchall()
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["user_id"], USER)
            response = await self.call(
                "POST",
                "/discord/member",
                headers,
                json={
                    "action": "withdraw",
                    "guild_id": str(service.GUILD_ID),
                    "user_id": USER,
                    "season_id": self.sid,
                    "tag": "#P2Y",
                    "expected_pool": "main",
                    "expected_revision": await self.revision(),
                },
            )
            self.assertEqual(response.status, 200, await response.text())
        job = claim(self.app["store"])
        self.assertFalse(job["desired"])

    async def test_staff_add_tag_add_pool_change_and_remove_all_enqueue(self):
        self.assertEqual((await self.configure()).status, 200)
        self.providers.linked_owner = AsyncMock(return_value=USER)
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/staff-signups",
            self.owner,
            json={
                "user_id": USER,
                "pool": "main",
                "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}],
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/staff-signups/player",
            self.owner,
            json={
                "tag": "#Q2Y",
                "user_id": USER,
                "pool": "main",
                "has_discord": True,
                "expected_linked_user_id": USER,
                "prefer_crystal_1_or_lower": False,
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/staff-signup-changes",
            self.owner,
            json={
                "tags": ["#P2Y"],
                "action": "lazy",
                "revision": await self.revision(),
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        job = claim(self.app["store"])
        self.assertTrue(job["desired"])
        response = await self.call(
            "DELETE",
            f"/seasons/{self.sid}/staff-signups/%23Q2Y",
            self.owner,
            json={"revision": await self.revision()},
        )
        self.assertEqual(response.status, 200, await response.text())
        with self.app["store"].tx() as db:
            row = db.execute(
                "SELECT * FROM cwl_pool_role_jobs WHERE pool='main'"
            ).fetchone()
            self.assertFalse(service.desired(db, row))

    async def test_malformed_settings_and_bridge_actions_are_rejected(self):
        state = await self.state()
        row = next(r for r in state["pools"] if r["pool"] == "main")
        good = {
            "pool": "main",
            "role_id": ROLE,
            "revision": row["revision"],
            "member_basis": row["member_basis"],
        }
        for field, value in [
            ("pool", []),
            ("role_id", []),
            ("role_id", True),
            ("revision", True),
            ("revision", -1),
            ("member_basis", {}),
        ]:
            response = await self.call(
                "POST", "/pool-roles", self.owner, json={**good, field: value}
            )
            self.assertEqual(response.status, 400, await response.text())
        response = await self.call(
            "POST",
            "/discord/pool-roles",
            {"X-CWL-Discord-Secret": "s" * 40},
            json={"guild_id": str(service.GUILD_ID), "action": []},
        )
        self.assertEqual(response.status, 400)

    async def test_blank_bot_poll_uses_authenticated_loopback_without_discord(self):
        from extensions.tasks import cwl_pool_roles as transport
        from test_cwl_pool_roles import bot_fixture

        bot, _, _, _ = bot_fixture()
        with patch.dict(
            os.environ, {"CWL_DISCORD_BRIDGE_URL": str(self.client.make_url("/"))}
        ):
            await transport.poll_once(bot)
        bot.rest.fetch_roles.assert_not_awaited()
        bot.rest.add_role_to_member.assert_not_awaited()
        bot.rest.remove_role_from_member.assert_not_awaited()

    async def test_duplicate_dashboard_submit_has_one_durable_member_job(self):
        self.assertEqual((await self.configure()).status, 200)
        for _ in range(2):
            response = await self.call(
                "POST",
                f"/seasons/{self.sid}/signups",
                self.member,
                json={
                    "pool": "main",
                    "accounts": [{"tag": "#P2Y", "prefer_crystal_1_or_lower": False}],
                },
            )
            self.assertEqual(response.status, 200, await response.text())
        with self.app["store"].tx() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0], 1
            )
        bot, _, _, _ = bot_fixture()
        await process_job(
            bot, claim(self.app["store"]), send=send_for(self.app["store"])
        )
        bot.rest.add_role_to_member.assert_awaited_once()

    async def test_discord_outage_keeps_saved_settings_available_and_can_turn_off(self):
        from aiohttp import web

        self.assertEqual((await self.configure()).status, 200)
        self.discord.side_effect = web.HTTPServiceUnavailable(
            text="Discord unavailable"
        )
        response = await self.call("GET", "/pool-roles", self.owner)
        self.assertEqual(response.status, 200)
        state = await response.json()
        self.assertTrue(state["roles_error"])
        row = next(r for r in state["pools"] if r["pool"] == "main")
        self.discord.reset_mock()
        response = await self.call(
            "POST",
            "/pool-roles",
            self.owner,
            json={
                "pool": "main",
                "role_id": None,
                "revision": row["revision"],
                "member_basis": row["member_basis"],
            },
        )
        self.assertEqual(response.status, 200)
        self.discord.assert_not_awaited()

    async def test_delegated_seasons_scope_and_live_revocation(self):
        import json

        actor = http.identity.return_value
        actor["user_id"] = USER
        actor["member"] = {"user": {"id": USER}, "roles": ["777777777777777777"]}
        actor["roles"].append(
            {
                "id": "777777777777777777",
                "name": "Staff",
                "position": 10,
                "permissions": 0,
            }
        )
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)",
                (USER, OWNER, json.dumps(["cwl_settings"])),
            )
        response = await self.call("GET", "/pool-roles", self.member)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        row = next(r for r in state["pools"] if r["pool"] == "main")
        response = await self.call(
            "POST",
            "/pool-roles",
            self.member,
            json={
                "pool": "main",
                "role_id": ROLE,
                "revision": row["revision"],
                "member_basis": row["member_basis"],
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE grants SET permissions=? WHERE user_id=?",
                (json.dumps(["cwl_roster"]), USER),
            )
        self.discord.reset_mock()
        self.assertEqual(
            (await self.call("GET", "/pool-roles", self.member)).status, 403
        )
        self.discord.assert_not_awaited()
