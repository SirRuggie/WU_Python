"""Shared reminder editor preserves links and delegates scheduling to Manage."""

from reminder_ack_fixture import reconcile_installed
import copy
import unittest
from unittest.mock import AsyncMock, patch

from test_cwl_web_manage_bridge import ManageBridgeTests
from utils import cwl_campaign, cwl_web_bridge
from cwl_web.manage_bridge import GUILD_ID


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    auth = ManageBridgeTests.auth
    call = ManageBridgeTests.call
    revision = ManageBridgeTests.revision
    asyncTearDown = ManageBridgeTests.asyncTearDown

    async def asyncSetUp(self):
        await ManageBridgeTests.asyncSetUp(self)
        clock = patch.object(cwl_campaign, "cycle_key", return_value="2029-11")
        clock.start()
        self.addCleanup(clock.stop)
        self.base = f"/seasons/{self.sid}/manage-reminders"
        result = await self.call(
            "POST",
            f"/seasons/{self.sid}/manage-bridge/bind",
            self.owner,
            json={"cycle": "2029-11"},
        )
        self.assertEqual(result.status, 200)

    async def test_invalid_top_level_fields_have_plain_http_error(self):
        state = await self.state()
        response = await self.call('PATCH', self.base, self.owner,
            json={'generation': state['generation'], 'patch': {'unexpected': True}})
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())['error'], 'Invalid automatic message fields')

    async def state(self):
        response = await self.call("GET", self.base, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_unbound_editor_opens_and_saves_recurring_without_month_selection(
        self,
    ):
        with self.app["store"].tx() as db:
            db.execute(
                "DELETE FROM manage_campaign_bindings WHERE season_id=?", (self.sid,)
            )
        with patch.object(cwl_campaign, "cycle_key", return_value="2029-11"):
            state = await self.state()
            self.assertIsNotNone(state["campaign"])
            response = await self.call(
                "PATCH",
                self.base,
                self.owner,
                json={
                    "generation": state["generation"],
                    "patch": {
                        "messages": {
                            "signup": {
                                "variants": {
                                    "main": {"title": "Recurring signup title"}
                                }
                            }
                        }
                    },
                },
            )
            self.assertEqual(response.status, 200, await response.text())
        future = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-12")
        self.assertEqual(
            future["campaign"]["messages"]["signup"]["variants"]["main"]["title"],
            "Recurring signup title",
        )
        with self.app["store"].tx() as db:
            self.assertIsNone(
                db.execute(
                    "SELECT cycle FROM manage_campaign_bindings WHERE season_id=?",
                    (self.sid,),
                ).fetchone()
            )

    async def test_preview_save_shared_links_and_stale_generation(self):
        original = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-11")
        state = await self.state()
        body = {
            "generation": state["generation"],
            "patch": {
                "messages": {
                    "signup": {
                        "variants": {
                            "main": {
                                "title": "Fixture signups",
                                "body": "Fixture announcement",
                                "role_ids": ["1080521665584308286"],
                            }
                        }
                    }
                }
            },
        }
        response = await self.call(
            "POST", self.base + "/preview", self.owner, json=body
        )
        self.assertEqual(response.status, 200, await response.text())
        preview = await response.json()
        self.assertTrue(preview["preview"])
        self.assertTrue(preview["activated"])
        self.assertIn("scheduled", {row["status"] for row in preview["schedule"]})
        self.assertEqual(
            await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-11"), original
        )
        response = await self.call("PATCH", self.base, self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        after = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-11")
        self.assertEqual(
            after["campaign"]["messages"]["signup"]["variants"]["main"]["title"],
            "Fixture signups",
        )
        for mid, message in original["campaign"]["messages"].items():
            for pool, item in message["variants"].items():
                self.assertEqual(
                    after["campaign"]["messages"][mid]["variants"][pool]["buttons"],
                    item["buttons"],
                )
        self.assertEqual(
            (await self.call("PATCH", self.base, self.owner, json=body)).status, 409
        )
        self.assertFalse((await self.state())["schedule_synced"])
        sync = AsyncMock()
        self.assertTrue(await reconcile_installed(self.mongo, sync, guild_id=GUILD_ID))
        self.assertTrue((await self.state())["schedule_synced"])
        self.assertFalse(await reconcile_installed(self.mongo, sync, guild_id=GUILD_ID))
        self.assertEqual(sync.await_count, 1)

    async def test_locked_buttons_roles_validation_and_permissions(self):
        generation = (await self.state())["generation"]
        for fields in (
            {"buttons": []},
            {"destination_channel_id": "bad"},
            {"role_ids": ["bad"]},
            {"role_ids": ["999999999999999999"]},
            {"enabled": "yes"},
        ):
            body = {
                "generation": generation,
                "patch": {"messages": {"signup": {"variants": {"lazy": fields}}}},
            }
            result = await self.call("PATCH", self.base, self.owner, json=body)
            self.assertEqual(result.status, 400, await result.text())
        self.assertEqual((await self.call("GET", self.base, self.member)).status, 403)
        no_csrf = {k: v for k, v in self.owner.items() if k != "X-CSRF-Token"}
        self.assertEqual(
            (
                await self.call(
                    "PATCH",
                    self.base,
                    no_csrf,
                    json={"generation": generation, "patch": {}},
                )
            ).status,
            403,
        )
        self.assertEqual((await self.state())["generation"], generation)

    async def test_sequence_and_repeat_protect_sent_and_pause(self):
        before = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-11")
        oid = cwl_campaign.occurrence_id("2029-11", "signup", "main")
        await cwl_campaign.record_delivery(
            self.mongo, GUILD_ID, "2029-11", {"occurrence_id": oid, "status": "sent"}
        )
        body = {
            "generation": (await self.state())["generation"],
            "repeat_monthly": True,
            "patch": {
                "reminder_sequence": {
                    "enabled": True,
                    "mode": "evenly",
                    "count": 8,
                    "interval_hours": 48,
                    "final_hours": 3,
                    "min_gap_hours": 3,
                },
                "messages": {
                    "signup": {
                        "variants": {"main": {"title": "Do not overwrite sent content"}}
                    }
                },
            },
        }
        response = await self.call("PATCH", self.base, self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        self.assertIn(oid, state["protected_sent"])
        self.assertEqual(
            state["campaign"]["messages"]["signup"]["variants"]["main"]["title"],
            before["campaign"]["messages"]["signup"]["variants"]["main"]["title"],
        )
        self.assertIn("reminder:8", state["campaign"]["messages"])
        for pool in ("main", "lazy"):
            self.assertEqual(
                state["campaign"]["messages"]["reminder:8"]["variants"][pool][
                    "buttons"
                ],
                before["campaign"]["messages"]["reminder:5"]["variants"][pool][
                    "buttons"
                ],
            )
        pause = {"generation": state["generation"], "paused": True}
        response = await self.call("POST", self.base + "/pause", self.owner, json=pause)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        self.assertTrue(state["campaign"]["paused"])
        self.assertEqual(
            (
                await self.call("POST", self.base + "/pause", self.owner, json=pause)
            ).status,
            409,
        )
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.base + "/pause",
                    self.owner,
                    json={"generation": state["generation"], "paused": False},
                )
            ).status,
            200,
        )

    async def test_failed_reconcile_retries_and_archived_writes_blocked(self):
        timer = patch.object(cwl_web_bridge.time, "monotonic", return_value=100.0)
        clock = timer.start()
        self.addCleanup(timer.stop)
        repair_state = patch.object(cwl_web_bridge, "_schedule_repair_attempts", {})
        repair_state.start()
        self.addCleanup(repair_state.stop)
        state = await self.state()
        result = await self.call(
            "PATCH",
            self.base,
            self.owner,
            json={"generation": state["generation"], "patch": {}},
        )
        self.assertEqual(result.status, 200, await result.text())
        sync = AsyncMock(side_effect=RuntimeError("fixture scheduler offline"))
        with self.assertRaises(RuntimeError):
            await reconcile_installed(self.mongo, sync, guild_id=GUILD_ID)
        self.assertFalse((await self.state())["schedule_synced"])
        retry = AsyncMock()
        self.assertFalse(await reconcile_installed(self.mongo, retry, guild_id=GUILD_ID))
        retry.assert_not_awaited()
        self.assertFalse((await self.state())["schedule_synced"])
        clock.return_value += cwl_web_bridge.SCHEDULE_REPAIR_RETRY_SECONDS
        await reconcile_installed(self.mongo, retry, guild_id=GUILD_ID)
        retry.assert_awaited_once()
        self.assertTrue((await self.state())["schedule_synced"])
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        state = await self.state()
        self.assertEqual(
            (
                await self.call(
                    "PATCH",
                    self.base,
                    self.owner,
                    json={"generation": state["generation"], "patch": {}},
                )
            ).status,
            409,
        )
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.base + "/pause",
                    self.owner,
                    json={"generation": state["generation"], "paused": True},
                )
            ).status,
            409,
        )

    async def test_transitional_schedule_display_and_native_pause_history(self):
        campaign = cwl_campaign.default_campaign()
        campaign["schedules"] = {
            "signup": {"mode": "monthly", "day": 19, "hour": 12, "minute": 30}
        }
        await self.mongo.bot_config.update_one(
            {"_id": cwl_campaign.cycle_id(GUILD_ID, "2029-11")},
            {
                "$set": {
                    "kind": "cwl_campaign_cycle",
                    "guild_id": GUILD_ID,
                    "cycle": "2029-11",
                    "revision": 1,
                    "activated": True,
                    "campaign": campaign,
                }
            },
            upsert=True,
        )
        state = await self.state()
        self.assertEqual(state["campaign"]["messages"]["signup"]["schedule"]["day"], 19)
        response = await self.call(
            "PATCH",
            self.base,
            self.owner,
            json={
                "generation": state["generation"],
                "patch": {
                    "messages": {
                        "signup": {
                            "schedule": {
                                "mode": "monthly",
                                "day": 20,
                                "hour": 12,
                                "minute": 0,
                            }
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        saved = await response.json()
        self.assertEqual(saved["campaign"]["messages"]["signup"]["schedule"]["day"], 20)
        self.assertTrue(saved["signup_open"])
        paused = await self.call(
            "POST",
            self.base + "/pause",
            self.owner,
            json={"generation": saved["generation"], "paused": True},
        )
        state = await paused.json()
        self.assertTrue(all(row["status"] == "paused" for row in state["schedule"]))
        self.assertTrue(
            any(event.get("action") == "paused" for event in state["history"])
        )

    async def test_sequence_invalid_and_reconcile_racing_edit_not_acknowledged(self):
        state = await self.state()
        bad = {
            "generation": state["generation"],
            "patch": {
                "reminder_sequence": {"enabled": True, "mode": "evenly", "count": 11}
            },
        }
        self.assertEqual(
            (await self.call("PATCH", self.base, self.owner, json=bad)).status, 400
        )
        await self.call(
            "PATCH",
            self.base,
            self.owner,
            json={"generation": state["generation"], "patch": {}},
        )

        async def edit_while_syncing():
            await cwl_campaign.set_paused(self.mongo, GUILD_ID, True, "2029-11", 123)

        await reconcile_installed(self.mongo, edit_while_syncing, guild_id=GUILD_ID)
        self.assertFalse((await self.state())["schedule_synced"])
        await reconcile_installed(self.mongo, AsyncMock(), guild_id=GUILD_ID)
        self.assertTrue((await self.state())["schedule_synced"])

    async def test_schedule_ack_requires_current_process_generation_and_online_is_separate(
        self,
    ):
        loaded = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, "2029-11")
        generation = cwl_web_bridge.campaign_generation(loaded)
        worker = {
            "schedule_generations": {"2029-11": generation},
            "schedule_epoch": "process-a",
            "worker_epoch": "process-a",
            "schedule_ready": True,
        }
        await self.mongo.bot_config.update_one(
            {"_id": cwl_web_bridge.worker_id(GUILD_ID)}, {"$set": worker}, upsert=True
        )
        await cwl_web_bridge.mark_worker_alive(
            self.mongo, GUILD_ID, worker_epoch="process-a", schedule_ready=True
        )
        self.assertTrue((await self.state())["schedule_synced"])
        for patch in (
            {"worker_epoch": "process-b"},
            {"schedule_ready": False},
            {"schedule_generations": {"2029-11": "stale"}},
        ):
            await self.mongo.bot_config.update_one(
                {"_id": cwl_web_bridge.worker_id(GUILD_ID)},
                {"$set": {**worker, **patch}},
            )
            self.assertFalse((await self.state())["schedule_synced"])
        await self.mongo.bot_config.update_one(
            {"_id": cwl_web_bridge.worker_id(GUILD_ID)},
            {"$set": {**worker, "updated_at": "2000-01-01T00:00:00+00:00"}},
        )
        state = await self.state()
        self.assertFalse(state["worker_ready"])
        self.assertTrue(state["schedule_synced"])
