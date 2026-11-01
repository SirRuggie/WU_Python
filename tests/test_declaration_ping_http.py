"""HTTP integration with fixture SQLite, owned Mongo and a fake transport only."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp import web
from pymongo import AsyncMongoClient
import test_cwl_web_roster as roster_tests
from utils.declaration_ping_store import DeclarationPingStore
from cwl_web.server_management import GUILD_ID

URI = os.getenv("WU_DECLARATION_TEST_MONGO_URI")
CHANNEL = "234567890123456789"


@unittest.skipUnless(URI, "isolated declaration Mongo fixture not supplied")
class DeclarationPingHTTP(unittest.IsolatedAsyncioTestCase):
    auth = roster_tests.RosterTests.auth
    call = roster_tests.RosterTests.call
    signup = roster_tests.RosterTests.signup
    revision = roster_tests.RosterTests.revision

    async def asyncSetUp(self):
        assert URI == "mongodb://127.0.0.1:27154"
        await roster_tests.RosterTests.asyncSetUp(self)
        self.mongo = AsyncMongoClient(URI)
        self.db = self.mongo["wu_declaration_http_" + uuid4().hex]
        self.app["server_management_mongo"] = SimpleNamespace(
            bot_config=self.db.bot_config
        )
        self.storage = DeclarationPingStore(
            self.app["server_management_mongo"], GUILD_ID
        )
        self.transport = SimpleNamespace(
            send=AsyncMock(return_value="345678901234567890")
        )
        self.app["declaration_transport"] = self.transport
        self.channel = {"id": CHANNEL, "name": "fixture", "type": 0}
        self.patchers = [
            patch(
                "cwl_web.declaration_destinations.destination",
                AsyncMock(return_value=self.channel),
            ),
            patch(
                "cwl_web.declaration_destinations.channels",
                AsyncMock(return_value=[dict(self.channel, can_send=True)]),
            ),
            patch(
                "cwl_web.declaration_destinations.authorized",
                AsyncMock(return_value=True),
            ),
        ]
        for p in self.patchers:
            p.start()
        await self.signup("lazy", "#Q2Y")
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#Q2Y','#R2Y')",
                (self.sid,),
            )
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/publication",
            self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "fixture",
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        self.path = f"/seasons/{self.sid}/declaration-pings/lazy"
        response = await self.call(
            "PUT", self.path, self.owner, json={"channel_id": CHANNEL, "revision": 0}
        )
        self.assertEqual(response.status, 200, await response.text())

    async def asyncTearDown(self):
        await self.client.close()
        for p in reversed(self.patchers):
            p.stop()
        await self.mongo.drop_database(self.db.name)
        await self.mongo.close()
        self.tmp.cleanup()

    async def review(self, mode="live"):
        response = await self.call(
            "POST",
            self.path + "/preview",
            self.owner,
            json={"revision": 1, "mode": mode},
        )
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def send(self, review, **changes):
        return await self.call(
            "POST",
            self.path + "/send",
            self.owner,
            json={
                "token": review["token"],
                "confirm": True,
                "send_again": False,
                **changes,
            },
        )

    async def settled(self):
        while self.app["declaration_tasks"]:
            await asyncio.gather(*list(self.app["declaration_tasks"]))

    async def test_review_fresh_double_submit_and_no_implicit_send(self):
        review = await self.review()
        self.assertEqual(review["count"], 1)
        self.transport.send.assert_not_awaited()
        self.assertEqual((await self.send(review, confirm=False)).status, 400)
        self.transport.send.assert_not_awaited()
        replies = await asyncio.gather(self.send(review), self.send(review))
        self.assertTrue(all(r.status in (200, 202, 409) for r in replies))
        await self.settled()
        self.assertEqual(self.transport.send.await_count, 1)
        self.assertEqual((await self.send(review)).status, 200)
        self.assertEqual(self.transport.send.await_count, 1)
        lane = await self.storage.read("lazy")
        self.assertEqual(lane["history"][0]["state"], "done")
        self.assertEqual(len(lane["history"][0]["posted"]), 1)

    async def test_arrival_changes_after_review_are_not_sent(self):
        review = await self.review()
        self.providers.players["#Q2Y"]["current_clan_tag"] = "#R2Y"
        response = await self.send(review)
        self.assertEqual(response.status, 409, await response.text())
        self.transport.send.assert_not_awaited()

    async def test_destination_revision_and_permission_guards(self):
        review = await self.review()
        response = await self.call(
            "PUT", self.path, self.owner, json={"channel_id": CHANNEL, "revision": 0}
        )
        self.assertEqual(response.status, 409)
        await self.storage.configure(
            "lazy", "345678901234567890", "other", "505227988229554179", 1
        )
        self.assertEqual((await self.send(review)).status, 409)
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.path + "/preview",
                    self.member,
                    json={"revision": 2, "mode": "live"},
                )
            ).status,
            403,
        )
        no_csrf = {"Cookie": self.owner["Cookie"]}
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.path + "/send",
                    no_csrf,
                    json={
                        "token": review["token"],
                        "confirm": True,
                        "send_again": False,
                    },
                )
            ).status,
            403,
        )
        self.transport.send.assert_not_awaited()

    async def test_test_channel_has_zero_mentions_and_no_receipt(self):
        from utils.cwl_roster_image_store import RosterImageStore

        RosterImageStore(self.app["store"]).configure_test_channel(
            CHANNEL, "test", "owner", 0
        )
        review = await self.review("test")
        response = await self.send(review)
        self.assertEqual(response.status, 202, await response.text())
        await self.settled()
        self.assertEqual(self.transport.send.await_count, 1)
        call = self.transport.send.await_args
        self.assertTrue(call.kwargs["test"])
        self.assertEqual(
            call.args[1]["allowed_mentions"], {"parse": [], "users": [], "roles": []}
        )
        lane = await self.storage.read("lazy")
        self.assertEqual(lane["history"], [])
        self.assertEqual(lane["last_attempt_at"], 0)
        self.assertIsNone(lane["active_test"])
        self.assertEqual((await self.send(review)).status, 200)
        self.assertEqual(self.transport.send.await_count, 1)

    async def test_timeout_records_uncertain_chunk_without_retry(self):
        from extensions.cwl_declaration_transport import PingUncertain

        self.transport.send.side_effect = PingUncertain("May have posted")
        review = await self.review()
        self.assertEqual((await self.send(review)).status, 202)
        await self.settled()
        lane = await self.storage.read("lazy")
        row = lane["history"][0]
        self.assertEqual(
            (row["state"], row["attempting"], row["posted"]), ("uncertain", 0, [])
        )
        await self.send(review)
        self.assertEqual(self.transport.send.await_count, 1)

    async def test_bot_permission_refusal_prevents_claim(self):
        review = await self.review()
        with patch(
            "cwl_web.declaration_destinations.destination",
            AsyncMock(side_effect=web.HTTPBadRequest(text="No permission")),
        ):
            self.assertEqual((await self.send(review)).status, 400)
        self.assertIsNone((await self.storage.read("lazy"))["active"])
        self.transport.send.assert_not_awaited()

    async def test_readonly_staff_state_and_revoked_send_scope(self):
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES('100','505227988229554179','[\"cwl_roster\"]')"
            )
        response = await self.call("GET", self.path, self.member)
        self.assertEqual(response.status, 200, await response.text())
        self.assertFalse((await response.json())["can_send"])
        self.assertEqual(
            (
                await self.call(
                    "POST",
                    self.path + "/preview",
                    self.member,
                    json={"revision": 1, "mode": "live"},
                )
            ).status,
            403,
        )
        self.transport.send.assert_not_awaited()

    async def test_interrupted_final_receipt_is_visible_and_close_sends_nothing(self):
        review = await self.review()
        with patch.object(
            DeclarationPingStore,
            "finish",
            AsyncMock(side_effect=RuntimeError("fixture receipt outage")),
        ):
            self.assertEqual((await self.send(review)).status, 202)
            await asyncio.gather(
                *list(self.app["declaration_tasks"]), return_exceptions=True
            )
            await asyncio.sleep(0)
        response = await self.call("GET", self.path, self.owner)
        data = await response.json()
        self.assertEqual(data["active"]["state"], "uncertain")
        self.assertEqual(len(data["active"]["posted"]), 1)
        response = await self.call(
            "POST",
            self.path + "/close-interrupted",
            self.owner,
            json={"token": review["token"], "confirm": True},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertIsNone((await self.storage.read("lazy"))["active"])
        self.assertEqual(self.transport.send.await_count, 1)

    async def test_partial_refusal_records_exact_posted_chunks(self):
        from extensions.cwl_declaration_transport import PingRejected
        from utils.declaration_pings import messages

        review = await self.review()
        plan = messages(review["groups"])
        self.transport.send.side_effect = [
            "345678901234567890",
            PingRejected("fixture 403"),
        ]
        with patch("cwl_web.declaration_pings.messages", return_value=plan * 2):
            self.assertEqual((await self.send(review)).status, 202)
            await self.settled()
        row = (await self.storage.read("lazy"))["history"][0]
        self.assertEqual(row["state"], "partial")
        self.assertEqual(
            row["posted"], [{"chunk": 0, "message_id": "345678901234567890"}]
        )
        self.assertIsNone(row["attempting"])
        self.assertEqual(self.transport.send.await_count, 2)

    async def test_other_pool_signup_and_weight_change_do_not_block_lazy(self):
        review = await self.review()
        await self.signup("main", "#P2Y")
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE roster_entries SET manual_weight=123 WHERE season_id=?",
                (self.sid,),
            )
        response = await self.send(review)
        self.assertEqual(response.status, 202, await response.text())
        await self.settled()
        self.assertEqual(self.transport.send.await_count, 1)

    async def test_real_pool_changes_visible_before_ping(self):
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE roster_entries SET assigned_clan_tag=NULL WHERE season_id=? AND tag='#Q2Y'",
                (self.sid,),
            )
        response = await self.call("GET", self.path, self.owner)
        changes = (await response.json())["lineup_changes"]
        self.assertEqual([r["tag"] for r in changes], ["#Q2Y"])
        response = await self.call(
            "POST",
            self.path + "/preview",
            self.owner,
            json={"revision": 1, "mode": "live"},
        )
        self.assertEqual(response.status, 409)
        self.assertIn("#Q2Y", await response.text())
        self.transport.send.assert_not_awaited()

    async def test_reviewed_list_finishes_after_concurrent_lineup_edit(self):
        from utils.declaration_pings import messages

        review = await self.review()

        async def delivered(*args, **kwargs):
            with self.app["store"].tx() as db:
                db.execute(
                    "UPDATE roster_entries SET assigned_clan_tag=NULL WHERE season_id=?",
                    (self.sid,),
                )
            return "345678901234567890"

        self.transport.send.side_effect = delivered
        with patch(
            "cwl_web.declaration_pings.messages",
            return_value=messages(review["groups"]) * 2,
        ):
            self.assertEqual((await self.send(review)).status, 202)
            await self.settled()
        self.assertEqual(self.transport.send.await_count, 2)
        self.assertEqual(
            (await self.storage.read("lazy"))["history"][0]["state"], "done"
        )

    async def test_receipt_readback_failure_cannot_record_done(self):
        review = await self.review()

        async def failed_post(*args, **kwargs):
            raise web.HTTPConflict(text="Destination changed during delivery")

        self.transport.send.side_effect = failed_post
        original = DeclarationPingStore.receipt

        async def readback(storage, *args, **kwargs):
            if self.transport.send.await_count:
                raise RuntimeError("fixture readback unavailable")
            return await original(storage, *args, **kwargs)

        with patch.object(DeclarationPingStore, "receipt", readback):
            self.assertEqual((await self.send(review)).status, 202)
            await self.settled()
        row = (await self.storage.read("lazy"))["history"][0]
        self.assertEqual(row["state"], "uncertain")
        self.assertIn("Destination changed during delivery", row["error"])
