"""Isolated HTTP ownership, permission, freshness and current-season checks."""

import copy
import json
import unittest
from unittest.mock import patch

from test_cwl_web_manage_bridge import ManageBridgeTests
from test_cwl_post_update_store import Collection
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge
from utils.cwl_post_update_store import PostUpdateStore, KIND
from cwl_web.manage_bridge import GUILD_ID

COPY = {
    "title": "Reviewed title",
    "body": "Reviewed body",
    "buttons": [{"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}],
}


class PostUpdateHTTPTests(unittest.IsolatedAsyncioTestCase):
    auth = ManageBridgeTests.auth
    call = ManageBridgeTests.call
    revision = ManageBridgeTests.revision
    asyncTearDown = ManageBridgeTests.asyncTearDown

    async def asyncSetUp(self):
        await ManageBridgeTests.asyncSetUp(self)
        self.mongo.bot_config = Collection()
        response = await self.call(
            "POST", self.base + "/bind", self.owner, json={"cycle": "2026-10"}
        )
        self.assertEqual(response.status, 200)
        self.route = self.base + "/main/post-updates"
        self.mongo.bot_config.documents[campaign.cycle_id(GUILD_ID, "2026-10")] = {
            "_id": campaign.cycle_id(GUILD_ID, "2026-10"),
            "kind": "cwl_campaign_cycle",
            "guild_id": GUILD_ID,
            "cycle": "2026-10",
            "activated": True,
            "revision": 1,
            "campaign": campaign.default_campaign(),
            "updated_at": "2026-10-01T00:00:00+00:00",
            "deliveries": [
                {
                    "status": "sent",
                    "occurrence_id": "2026-10|roster|main",
                    "channel_id": 300,
                    "message_id": 400,
                }
            ],
        }
        await bridge.mark_worker_alive(self.mongo, GUILD_ID, post_update_ready=True)

    async def body(self, nonce="a" * 32):
        loaded = await campaign.load_campaign(self.mongo, GUILD_ID, "2026-10")
        return {
            "nonce": nonce,
            "generation": bridge.campaign_generation(loaded),
            "candidate": copy.deepcopy(COPY),
        }

    async def queued(self):
        response = await self.call(
            "POST", self.route, self.owner, json=await self.body()
        )
        self.assertEqual(response.status, 202, await response.text())
        return next(
            row
            for row in self.mongo.bot_config.documents.values()
            if row.get("kind") == KIND
        )

    async def test_preview_changes_no_saved_campaign_and_never_exposes_private_target(
        self,
    ):
        key = campaign.cycle_id(GUILD_ID, "2026-10")
        before = copy.deepcopy(self.mongo.bot_config.documents[key])
        row = await self.queued()
        self.assertEqual(self.mongo.bot_config.documents[key], before)
        response = await self.call("GET", self.route + "/" + "a" * 32, self.owner)
        data = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["status"], "pending_preview")
        self.assertEqual(data["generation"], "0:1")
        for field in (
            "target",
            "draft_id",
            "fingerprint",
            "user_id",
            "worker_epoch",
            "digest",
        ):
            self.assertNotIn(field, data)
        self.assertEqual(row["user_id"], 505227988229554179)

    async def test_staff_csrf_and_actor_scope_are_server_enforced(self):
        self.assertEqual(
            (
                await self.call("POST", self.route, self.member, json=await self.body())
            ).status,
            403,
        )
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.route,
                    {"Cookie": self.owner["Cookie"]},
                    json=await self.body(),
                )
            ).status,
            403,
        )
        await self.queued()
        second = self.auth("644005027052126208")
        self.assertEqual(
            (await self.call("GET", self.route + "/" + "a" * 32, second)).status, 404
        )
        self.assertEqual(
            (await self.call("GET", self.route + "/" + "a" * 32, self.member)).status,
            403,
        )
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)",
                ("100", "fixture-owner", json.dumps(["cwl_send"])),
            )
        allowed = await self.call(
            "POST", self.route, self.member, json=await self.body("b" * 32)
        )
        self.assertEqual(allowed.status, 202, await allowed.text())
        with self.app["store"].tx() as db:
            db.execute("DELETE FROM grants WHERE user_id=?", ("100",))
        self.assertEqual(
            (await self.call("GET", self.route + "/" + "b" * 32, self.member)).status,
            403,
        )

    async def test_old_bot_heartbeat_and_expired_feature_capability_cannot_queue(self):
        worker = self.mongo.bot_config.documents[bridge.worker_id(GUILD_ID)]
        worker.pop("post_update_protocol")
        self.assertEqual(
            (
                await self.call("POST", self.route, self.owner, json=await self.body())
            ).status,
            503,
        )
        await bridge.mark_worker_alive(self.mongo, GUILD_ID, post_update_ready=True)
        worker["post_update_ready_at"] = "2020-01-01T00:00:00+00:00"
        await bridge.mark_worker_alive(
            self.mongo, GUILD_ID
        )  # old-bot heartbeat must not renew feature proof
        self.assertEqual(
            (
                await self.call("POST", self.route, self.owner, json=await self.body())
            ).status,
            503,
        )
        self.assertFalse(
            any(
                row.get("kind") == KIND
                for row in self.mongo.bot_config.documents.values()
            )
        )

    async def test_only_reviewed_fields_and_boolean_scope_then_doubletap_same_workflow(
        self,
    ):
        body = await self.body()
        body["channel_id"] = 123
        self.assertEqual(
            (await self.call("POST", self.route, self.owner, json=body)).status, 400
        )
        row = await self.queued()
        store = PostUpdateStore(self.mongo)
        claimed = await store.claim(row, runtime_id="fixture")
        await store.finish(
            claimed,
            status="ready",
            target={
                "channel_name": "announcements",
                "message_url": "https://discord.com/channels/1/2/3",
            },
        )
        url = self.route + "/" + "a" * 32 + "/update"
        self.assertEqual(
            (
                await self.call(
                    "POST", url, self.owner, json={"future_months": "false"}
                )
            ).status,
            400,
        )
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    url,
                    self.owner,
                    json={"future_months": False, "message_id": 5},
                )
            ).status,
            400,
        )
        self.assertEqual(
            (
                await self.call("POST", url, self.owner, json={"future_months": False})
            ).status,
            202,
        )
        self.assertEqual(
            (
                await self.call("POST", url, self.owner, json={"future_months": True})
            ).status,
            202,
        )
        saved = self.mongo.bot_config.documents[row["_id"]]
        self.assertEqual(saved["status"], "pending_update")
        self.assertFalse(saved["future_months"])

    async def test_archived_scope_rejects_queue_and_internal_validation_is_fresh_authenticated_read(
        self,
    ):
        row = await self.queued()
        store = PostUpdateStore(self.mongo)
        claimed = await store.claim(row, runtime_id="fixture")
        body = {
            key: claimed[key]
            for key in (
                "guild_id",
                "user_id",
                "season_id",
                "cycle",
                "pool",
                "worker_epoch",
            )
        }
        body["workflow_id"] = claimed["_id"]
        headers = {"X-CWL-Discord-Secret": "q" * 40}
        with patch.dict("os.environ", {"CWL_DISCORD_BRIDGE_SECRET": "q" * 40}):
            invalid = await self.call(
                "POST", "/discord/post-updates/validate", {}, json=body
            )
            self.assertEqual(invalid.status, 403)
            response = await self.call(
                "POST", "/discord/post-updates/validate", headers, json=body
            )
            self.assertEqual(response.status, 200, await response.text())
            self.assertTrue((await response.json())["valid"])
            malicious = {**body, "workflow_id": {"$ne": None}}
            self.assertEqual(
                (
                    await self.call(
                        "POST",
                        "/discord/post-updates/validate",
                        headers,
                        json=malicious,
                    )
                ).status,
                400,
            )
            with self.app["store"].tx() as db:
                db.execute(
                    "UPDATE seasons SET status='archived' WHERE id=?", (self.sid,)
                )
            response = await self.call(
                "POST", "/discord/post-updates/validate", headers, json=body
            )
            self.assertEqual(response.status, 200)
            self.assertFalse((await response.json())["valid"])
        self.assertEqual(
            (
                await self.call(
                    "POST", self.route, self.owner, json=await self.body("b" * 32)
                )
            ).status,
            409,
        )

    async def test_editor_without_send_scope_cannot_even_open_private_review(self):
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)",
                ("100", "fixture-owner", json.dumps(["cwl_roster"])),
            )
        response = await self.call("GET", self.route + "/" + "a" * 32, self.member)
        self.assertEqual(response.status, 403)
        self.assertNotIn("cwl:post-update", await response.text())

    async def test_internal_validation_rejects_changed_binding_while_claim_and_draft_remain_valid(
        self,
    ):
        row = await self.queued()
        claimed = await PostUpdateStore(self.mongo).claim(row, runtime_id="fixture")
        body = {
            key: claimed[key]
            for key in (
                "guild_id",
                "user_id",
                "season_id",
                "cycle",
                "pool",
                "worker_epoch",
            )
        }
        body["workflow_id"] = claimed["_id"]
        with patch.dict("os.environ", {"CWL_DISCORD_BRIDGE_SECRET": "q" * 40}):
            headers = {"X-CWL-Discord-Secret": "q" * 40}
            good = await self.call(
                "POST", "/discord/post-updates/validate", headers, json=body
            )
            self.assertTrue((await good.json())["valid"])
            with self.app["store"].tx() as db:
                db.execute(
                    "UPDATE manage_campaign_bindings SET cycle='2026-11' WHERE season_id=?",
                    (self.sid,),
                )
            rejected = await self.call(
                "POST", "/discord/post-updates/validate", headers, json=body
            )
            self.assertEqual(rejected.status, 200)
            self.assertFalse((await rejected.json())["valid"])
            self.assertEqual(
                self.mongo.bot_config.documents[row["_id"]]["status"], "previewing"
            )


    async def test_validation_errors_keep_400_error_schema_and_plain_copy(self):
        original = PostUpdateStore.create
        cases = [
            ({"future_months": 1}, "Choose Main or Lazy and which months"),
            ({"cycle": "2026-13"}, "Choose the month"),
            ({"generation": ""}, "Invalid season or saved settings"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                async def invalid_input(store, **values):
                    return await original(store, **dict(values, **changes))

                # Exercise the real store validation through the HTTP adapter;
                # other validated request fields and authorization stay intact.
                with patch.object(PostUpdateStore, "create", new=invalid_input):
                    response = await self.call(
                        "POST", self.route, self.owner, json=await self.body()
                    )
                self.assertEqual(response.status, 400)
                payload = await response.json()
                self.assertEqual(set(payload), {"error", "issue_reference"})
                self.assertEqual(payload["error"], message)
                self.assertRegex(payload["issue_reference"], r"^[0-9a-f]{12}$")
                self.assertFalse(
                    any(
                        row.get("kind") == KIND
                        for row in self.mongo.bot_config.documents.values()
                    )
                )

    async def test_changed_month_keeps_409_error_schema_with_plain_copy(self):
        row = await self.queued()
        before = copy.deepcopy(self.mongo.bot_config.documents[row["_id"]])
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE manage_campaign_bindings SET cycle='2026-11' WHERE season_id=?",
                (self.sid,),
            )
        response = await self.call("GET", self.route + "/" + "a" * 32, self.owner)
        self.assertEqual(response.status, 409)
        self.assertEqual(
            await response.json(), {"error": "Month changed. Open a new preview."}
        )
        self.assertEqual(self.mongo.bot_config.documents[row["_id"]], before)
