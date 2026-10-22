"""Explicit CWL announcement delivery, privacy, and retry invariants."""

import asyncio
import hashlib
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.announcements import AnnouncementRejected, AnnouncementUncertain, DiscordTransport
from cwl_web.store import Store


MAIN_CHANNEL = "123456789012345678"
LAZY_CHANNEL = "123456789012345679"
FOREIGN_CHANNEL = "123456789012345680"


class Providers:
    async def linked_tags(self, user_id):
        return {"#P2Y": True, "#Q2Y": True} if user_id == "100" else {}

    async def player(self, value):
        return {"tag": value, "name": "Private " + value, "town_hall": 16,
                "current_clan_tag": None, "current_clan_name": None}

    async def family_clans(self):
        return {"source": "fixture", "status": "ok", "checked_at": "2026-10-14T00:00:00Z", "clans": []}


class Transport:
    def __init__(self):
        self.channels = {
            MAIN_CHANNEL: {"id": MAIN_CHANNEL, "name": "main-news", "type": 0},
            LAZY_CHANNEL: {"id": LAZY_CHANNEL, "name": "lazy-news", "type": 5},
            FOREIGN_CHANNEL: {"id": FOREIGN_CHANNEL, "name": "foreign", "type": 0},
        }
        self.calls = []
        self.failure = None

    async def list_channels(self):
        return [self.channels[MAIN_CHANNEL], self.channels[LAZY_CHANNEL]]

    async def get_channel(self, channel_id):
        if channel_id == FOREIGN_CHANNEL:
            raise AnnouncementRejected("Wrong guild")
        if channel_id not in self.channels:
            raise AnnouncementRejected("Missing")
        return self.channels[channel_id]

    async def send(self, channel_id, content, nonce):
        self.calls.append((channel_id, content, nonce))
        if self.failure:
            raise self.failure
        return str(900000000000000000 + len(self.calls))


class AnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url_env = patch.dict(os.environ, {"CWL_WEB_PUBLIC_URL": "https://cwl.example.test/"})
        self.url_env.start()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"),
                              providers=Providers(), secure_cookies=False)
        self.transport = Transport()
        self.app["announcement_transport"] = self.transport
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.owner = self.auth("505227988229554179")
        self.member = self.auth("100")
        response = await self.call("POST", "/seasons", self.owner,
                                   json={"label": "October 2026", "signup_open": True})
        self.sid = (await response.json())["id"]

    async def asyncTearDown(self):
        await self.client.close()
        self.url_env.stop()
        self.tmp.cleanup()

    def auth(self, uid):
        raw, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) "
                       "VALUES (?,?,?,?,?,?)", (hashlib.sha256(raw.encode()).hexdigest(),
                       uid, uid, 0, csrf, int(time.time()) + 900))
        return {"Cookie": "cwl_session=" + raw, "X-CSRF-Token": csrf}

    async def call(self, method, path, headers=None, **kwargs):
        return await self.client.request(method, "/api/cwl" + path, headers=headers, **kwargs)

    async def publish(self):
        for pool, value in (("main", "#P2Y"), ("lazy", "#Q2Y")):
            response = await self.call("POST", f"/seasons/{self.sid}/signups", self.member,
                                       json={"pool": pool, "accounts": [{"tag": value,
                                             "prefer_crystal_1_or_lower": False}]})
            self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)
        revision = (await response.json())["draft_revision"]
        response = await self.call("POST", f"/seasons/{self.sid}/publication", self.owner,
                                   json={"revision": revision, "acknowledge_unassigned": True,
                                         "joining_instructions": "Private instructions"})
        self.assertEqual(response.status, 201)
        return (await response.json())["published"]["version"]

    async def test_withdrawn_publication_cannot_be_announced(self):
        version = await self.publish()
        await self.set_channel("main", MAIN_CHANNEL)
        preview = await (await self.call("GET", f"/seasons/{self.sid}/publication", self.owner)).json()
        response = await self.call("POST", f"/seasons/{self.sid}/publication/withdraw", self.owner,
                                   json={"revision": preview["draft_revision"], "version": version})
        self.assertEqual(response.status, 200)
        response = await self.call("GET", f"/seasons/{self.sid}/announcements", self.owner)
        self.assertIsNone((await response.json())["latest_publication"])
        response = await self.call("POST", f"/seasons/{self.sid}/announcements/main/send", self.owner,
                                   json={"version": version, "channel_id": MAIN_CHANNEL})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.transport.calls, [])

    async def set_channel(self, pool, channel_id, headers=None):
        return await self.call("PATCH", f"/seasons/{self.sid}/announcements/{pool}/channel",
                               headers or self.owner, json={"channel_id": channel_id})

    async def send(self, pool, version, channel_id, headers=None):
        return await self.call("POST", f"/seasons/{self.sid}/announcements/{pool}/send",
                               headers or self.owner,
                               json={"version": version, "channel_id": channel_id})

    async def test_no_automatic_send_preview_is_pool_specific_and_private(self):
        response = await self.call("GET", "/announcement-channels", self.owner)
        self.assertEqual(response.status, 200)
        self.assertEqual(len((await response.json())["channels"]), 2)
        response = await self.call("GET", f"/seasons/{self.sid}/announcements", self.owner)
        self.assertIsNone((await response.json())["latest_publication"])
        response = await self.call("GET", f"/seasons/{self.sid}/announcements", self.member)
        self.assertEqual(response.status, 403)
        response = await self.set_channel("main", MAIN_CHANNEL)
        self.assertEqual(response.status, 200)
        response = await self.set_channel("lazy", LAZY_CHANNEL)
        self.assertEqual(response.status, 200)
        version = await self.publish()
        self.assertEqual(self.transport.calls, [])
        response = await self.call("GET", f"/seasons/{self.sid}/announcements", self.owner)
        status = await response.json()
        self.assertEqual(status["latest_publication"]["version"], version)
        for pool in ("main", "lazy"):
            preview = status["pools"][pool]["preview"]
            self.assertEqual((preview["account_count"], preview["assigned_count"],
                              preview["unassigned_count"]), (1, 0, 1))
            self.assertIn("https://cwl.example.test/", preview["content"])
            self.assertNotIn("#P2Y", preview["content"])
            self.assertNotIn("#Q2Y", preview["content"])
            self.assertNotIn("Private instructions", preview["content"])
            self.assertNotIn("@", preview["content"])
        self.assertNotEqual(status["pools"]["main"]["preview"]["content"],
                            status["pools"]["lazy"]["preview"]["content"])

    async def test_channel_validation_staff_csrf_and_distinct_destinations(self):
        response = await self.set_channel("main", FOREIGN_CHANNEL)
        self.assertEqual(response.status, 400)
        response = await self.set_channel("main", MAIN_CHANNEL, self.member)
        self.assertEqual(response.status, 403)
        response = await self.set_channel("main", MAIN_CHANNEL,
                                          {"Cookie": self.owner["Cookie"]})
        self.assertEqual(response.status, 403)
        response = await self.set_channel("main", MAIN_CHANNEL)
        self.assertEqual(response.status, 200)
        response = await self.set_channel("lazy", MAIN_CHANNEL)
        self.assertEqual(response.status, 409)
        response = await self.set_channel("lazy", LAZY_CHANNEL)
        self.assertEqual(response.status, 200)
        version = await self.publish()
        response = await self.send("main", version, MAIN_CHANNEL, self.member)
        self.assertEqual(response.status, 403)
        response = await self.send("main", version, MAIN_CHANNEL,
                                   {"Cookie": self.owner["Cookie"]})
        self.assertEqual(response.status, 403)
        response = await self.send("main", version + 1, MAIN_CHANNEL)
        self.assertEqual(response.status, 409)
        response = await self.send("main", version, LAZY_CHANNEL)
        self.assertEqual(response.status, 409)
        self.assertEqual(self.transport.calls, [])

    async def test_explicit_send_receipt_duplicate_and_separate_pools(self):
        version = await self.publish()
        await self.set_channel("main", MAIN_CHANNEL)
        await self.set_channel("lazy", LAZY_CHANNEL)
        response = await self.send("main", version, MAIN_CHANNEL)
        self.assertEqual(response.status, 201)
        receipt = (await response.json())["delivery"]
        self.assertEqual((receipt["status"], receipt["pool"], receipt["attempts"]), ("sent", "main", 1))
        self.assertEqual(len(self.transport.calls), 1)
        response = await self.send("main", version, MAIN_CHANNEL)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["delivery"], receipt)
        self.assertEqual(len(self.transport.calls), 1)
        response = await self.send("lazy", version, LAZY_CHANNEL)
        self.assertEqual(response.status, 201)
        self.assertEqual(len(self.transport.calls), 2)
        self.assertNotEqual(self.transport.calls[0][2], self.transport.calls[1][2])
        reopened = Store(self.app["store"].path)
        self.assertEqual(reopened.one("SELECT COUNT(*) AS n FROM announcement_deliveries")["n"], 2)
        self.assertTrue(reopened.one("SELECT message_id FROM announcement_deliveries WHERE pool='main'")["message_id"])

    async def test_concurrent_send_reserves_once(self):
        version = await self.publish()
        await self.set_channel("main", MAIN_CHANNEL)
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def delayed_send(channel_id, content, nonce):
            calls.append((channel_id, nonce))
            entered.set()
            await release.wait()
            return "900000000000000001"

        self.transport.send = delayed_send
        first_task = asyncio.create_task(self.send("main", version, MAIN_CHANNEL))
        await asyncio.wait_for(entered.wait(), timeout=2)
        response = await self.send("main", version, MAIN_CHANNEL)
        self.assertEqual(response.status, 409)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.app["store"].one("SELECT status FROM announcement_deliveries")["status"], "sending")
        release.set()
        response = await first_task
        self.assertEqual(response.status, 201)
        self.assertEqual(self.app["store"].one("SELECT status FROM announcement_deliveries")["status"], "sent")

    async def test_uncertain_blocks_resend_and_definite_rejection_can_retry(self):
        version = await self.publish()
        await self.set_channel("main", MAIN_CHANNEL)
        await self.set_channel("lazy", LAZY_CHANNEL)
        self.transport.failure = AnnouncementUncertain("timeout after POST")
        response = await self.send("main", version, MAIN_CHANNEL)
        self.assertEqual(response.status, 503)
        self.assertEqual(self.app["store"].one("SELECT status FROM announcement_deliveries WHERE pool='main'")["status"], "uncertain")
        self.transport.failure = None
        response = await self.send("main", version, MAIN_CHANNEL)
        self.assertEqual(response.status, 409)
        self.assertEqual(len(self.transport.calls), 1)
        self.transport.failure = AnnouncementRejected("permission denied")
        response = await self.send("lazy", version, LAZY_CHANNEL)
        self.assertEqual(response.status, 409)
        self.assertEqual(self.app["store"].one("SELECT status FROM announcement_deliveries WHERE pool='lazy'")["status"], "failed")
        self.transport.failure = None
        response = await self.send("lazy", version, LAZY_CHANNEL)
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["delivery"]["attempts"], 2)
        self.assertEqual(len(self.transport.calls), 3)


class DiscordTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_uses_enforced_nonce_and_disables_all_mentions(self):
        class Response:
            status = 201

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def json(self):
                return {"id": "900000000000000001", "channel_id": MAIN_CHANNEL,
                        "nonce": "deterministicnonce"}

        class Session:
            def __init__(self, calls, **kwargs):
                self.calls = calls

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def post(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return Response()

        calls = []
        with patch("cwl_web.announcements.aiohttp.ClientSession",
                   side_effect=lambda **kwargs: Session(calls, **kwargs)):
            message_id = await DiscordTransport(token="not-a-real-token").send(
                MAIN_CHANNEL, "Safe announcement", "deterministicnonce")
        self.assertEqual(message_id, "900000000000000001")
        self.assertEqual(len(calls), 1)
        url, options = calls[0]
        self.assertEqual(url, f"https://discord.com/api/v10/channels/{MAIN_CHANNEL}/messages")
        self.assertEqual(options["json"]["allowed_mentions"], {"parse": []})
        self.assertEqual(options["json"]["nonce"], "deterministicnonce")
        self.assertTrue(options["json"]["enforce_nonce"])
