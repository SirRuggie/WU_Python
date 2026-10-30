"""Layered moderation routing and read-only legacy migration contracts."""
import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

from utils.member_event_settings import effective_event, normalize_settings
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiohttp import web
from pymongo.errors import DuplicateKeyError

from cwl_web import member_events as api
from utils.member_events import EVENT_TYPES, MemberEventStore, SettingsConflict
from utils.member_events import TestRateLimited as MemberEventTestRateLimited

from tests.test_moderation_backend import MemoryCollection


class LayeredSettingsTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_destinations_and_defaults_are_unchanged(self):
        legacy = MemberEventStore.default_settings()
        legacy["events"]["kick"] = {
            "enabled": True, "channel_id": "123456789012345679",
            "forum_tag_id": "123456789012345680",
        }
        normalized = normalize_settings(legacy, MemberEventStore.default_settings())
        self.assertEqual(normalized["schema_version"], 2)
        self.assertEqual(normalized["revision"], 0)
        self.assertEqual(normalized["main"], {"channel_id": None, "forum_tag_id": None})
        self.assertEqual({key: value["mode"] for key, value in normalized["categories"].items()},
                         {"members": "main", "moderation": "main"})
        for kind in EVENT_TYPES:
            self.assertEqual(effective_event(normalized, kind), legacy["events"][kind])
        self.assertEqual(normalized["ignores"], {})

    def test_all_layers_and_off_priority(self):
        settings = normalize_settings(None, MemberEventStore.default_settings())
        settings["main"] = {"channel_id": "111111111111111111", "forum_tag_id": None}
        settings["events"]["join"] = {"enabled": True, "channel_id": None, "forum_tag_id": None}
        self.assertEqual(effective_event(settings, "join")["channel_id"], "111111111111111111")
        settings["categories"]["members"] = {
            "mode": "own", "channel_id": "222222222222222222", "forum_tag_id": "333333333333333333"}
        self.assertEqual(effective_event(settings, "join")["forum_tag_id"], "333333333333333333")
        settings["events"]["join"]["channel_id"] = "444444444444444444"
        settings["events"]["join"]["forum_tag_id"] = None
        self.assertEqual(effective_event(settings, "join")["channel_id"], "444444444444444444")
        settings["categories"]["members"]["mode"] = "off"
        self.assertEqual(effective_event(settings, "join"),
                         {"enabled": False, "channel_id": None, "forum_tag_id": None})
        self.assertFalse(effective_event(settings, "leave")["enabled"])
        self.assertEqual(effective_event(settings, "kick"),
                         {"enabled": False, "channel_id": "111111111111111111", "forum_tag_id": None})

    async def test_store_read_does_not_migrate_until_cas_save(self):
        collection = MemoryCollection()
        old = MemberEventStore.default_settings()
        old["revision"] = 7
        collection.rows["legacy"] = {"_id": "legacy", "event_key": "legacy"}
        from utils.member_events import SETTINGS_ID
        collection.rows[SETTINGS_ID] = {"_id": SETTINGS_ID, "event_key": SETTINGS_ID, **old}
        store = MemberEventStore(collection)
        before = dict(collection.rows[SETTINGS_ID])
        loaded = await store.settings()
        self.assertEqual(collection.rows[SETTINGS_ID], before)
        self.assertEqual(loaded["schema_version"], 2)
        for kind in EVENT_TYPES:
            self.assertEqual(effective_event(loaded, kind), old["events"][kind])
        with self.assertRaises(SettingsConflict):
            await store.save_settings(6, loaded)
        saved = await store.save_settings(7, loaded)
        self.assertEqual(saved["revision"], 8)
        self.assertEqual(collection.rows[SETTINGS_ID]["schema_version"], 2)

    def test_save_validation_requires_complete_v2_shape_and_valid_ids(self):
        settings = normalize_settings(None, MemberEventStore.default_settings())
        checked = api._checked_settings({key: value for key, value in settings.items()
                                         if key != "schema_version"})
        self.assertEqual(checked, settings)
        settings["categories"]["members"]["mode"] = "invalid"
        with self.assertRaises(web.HTTPBadRequest):
            api._checked_settings(settings)
        settings["categories"]["members"]["mode"] = "own"
        settings["categories"]["members"]["channel_id"] = "not-a-snowflake"
        with self.assertRaises(web.HTTPBadRequest):
            api._checked_settings(settings)
        settings["categories"]["members"]["channel_id"] = None
        settings["ignores"] = {"users": ["1"]}
        with self.assertRaises(web.HTTPBadRequest):
            api._checked_settings(settings)


class TestAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_test_audit_is_separate_from_member_history(self):
        history = MemoryCollection()
        class RateCollection(MemoryCollection):
            async def insert_one(self, row):
                if row["_id"] in self.rows:
                    raise DuplicateKeyError("duplicate")
                self.rows[row["_id"]] = dict(row)

            async def find_one_and_update(self, query, update, **kwargs):
                key = query["_id"]
                previous = self.rows.get(key)
                if previous and previous["last_at"] > query["last_at"]["$lte"]:
                    raise DuplicateKeyError("rate window occupied")
                self.rows[key] = {"_id": key, **update["$set"]}
                return dict(self.rows[key])
        audit = RateCollection()
        store = MemberEventStore(history, audit)
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        # The fake models Mongo's unique _id rate key and the two stored rows.
        audit_id = await store.reserve_test("join", "123456789012345678", now)
        with self.assertRaises(MemberEventTestRateLimited):
            await store.reserve_test("join", "123456789012345678", now + timedelta(seconds=9))
        second = await store.reserve_test("join", "123456789012345678", now + timedelta(seconds=10))
        self.assertNotEqual(second, audit_id)
        await store.finish_test(audit_id, status="sent", destination="111111111111111111")
        self.assertEqual(history.rows, {})
        self.assertEqual(audit.rows[audit_id]["status"], "sent")
        self.assertEqual(audit.rows[audit_id]["destination"], "111111111111111111")


class TestSendApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.staff = {"user_id": "123456789012345678", "permissions": 8,
                      "role_ids": set()}
        self.saved = normalize_settings(None, MemberEventStore.default_settings())
        self.saved["revision"] = 3
        self.saved["events"]["kick"] = {"enabled": True,
                                         "channel_id": "111111111111111111", "forum_tag_id": None}
        self.store = NS(settings=AsyncMock(return_value=self.saved),
                        reserve_test=AsyncMock(return_value="test-audit-id"),
                        finish_test=AsyncMock())
        self.card_module = types.ModuleType("utils.member_event_cards")
        self.card_module.sample_row = lambda kind: {"event_type": kind}
        self.card_module.build_card = lambda row, test_staff_id=None: {
            "flags": 32768, "components": [{"type": 17}], "allowed_mentions": {"parse": []}}
        self.card_module.build_forum_message = lambda row, test_staff_id=None: {
            "embeds": [{"description": "Test log"}], "allowed_mentions": {"parse": []}}

    async def _call(self, kind="kick", revision=3, *, option_type="text",
                    discord_result=None):
        request = NS(json=AsyncMock(return_value={"event_type": kind, "revision": revision}))
        class Context:
            async def __aenter__(self):
                return NS(member_events=object(), member_event_test_audit=object())
            async def __aexit__(self, *args):
                pass
        option = {"id": "111111111111111111", "name": "staff-log", "type": option_type}
        from cwl_web import server_management
        with patch.dict(sys.modules, {"utils.member_event_cards": self.card_module}), \
             patch.object(api, "require_manage", new=AsyncMock(return_value=self.staff)) as auth, \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=self.store), \
             patch.object(api, "_bot_permissions", new=AsyncMock(return_value=(self.staff, object()))), \
             patch.object(api, "_validate_destination", new=AsyncMock(return_value=option)), \
             patch.object(server_management, "discord", new=AsyncMock(
                 return_value={"id": "999"} if discord_result is None else discord_result)) as discord:
            result = await api.send_test(request)
        auth.assert_awaited_once_with(request, "roles", write=True)
        return json.loads(result.text), discord

    async def test_effective_destination_one_post_and_no_history_write(self):
        result, discord = await self._call()
        self.assertTrue(result["sent"])
        self.assertEqual(result["destination"]["id"], "111111111111111111")
        discord.assert_awaited_once()
        self.assertEqual(discord.await_args.args[1:3],
                         ("POST", "/channels/111111111111111111/messages"))
        self.assertEqual(discord.await_args.kwargs["json"]["allowed_mentions"], {"parse": []})
        self.store.reserve_test.assert_awaited_once()
        self.store.finish_test.assert_awaited_once()

    async def test_forum_starter_one_post_and_saved_tag(self):
        self.saved["events"]["kick"]["forum_tag_id"] = "222222222222222222"
        result, discord = await self._call(option_type="forum")
        self.assertEqual(result["destination"]["type"], "forum")
        self.assertEqual(discord.await_args.args[2], "/channels/111111111111111111/threads")
        self.assertEqual(discord.await_args.kwargs["json"]["applied_tags"],
                         ["222222222222222222"])
        self.assertNotIn("flags", discord.await_args.kwargs["json"]["message"])

    async def test_stale_revision_rejects_before_reserve_or_post(self):
        request = NS(json=AsyncMock(return_value={"event_type": "kick", "revision": 2}))
        class Context:
            async def __aenter__(self):
                return NS(member_events=object(), member_event_test_audit=object())
            async def __aexit__(self, *args):
                pass
        with patch.object(api, "require_manage", new=AsyncMock(return_value=self.staff)), \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=self.store):
            with self.assertRaises(web.HTTPConflict):
                await api.send_test(request)
        self.store.reserve_test.assert_not_awaited()

    async def test_auth_denial_stops_before_saved_settings_or_send(self):
        request = NS(json=AsyncMock(return_value={"event_type": "kick", "revision": 3}))
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())):
            with self.assertRaises(web.HTTPForbidden):
                await api.send_test(request)
        self.store.settings.assert_not_awaited()
        self.store.reserve_test.assert_not_awaited()

    async def test_malformed_discord_result_is_uncertain_without_retry(self):
        request = NS(json=AsyncMock(return_value={"event_type": "kick", "revision": 3}))
        class Context:
            async def __aenter__(self):
                return NS(member_events=object(), member_event_test_audit=object())
            async def __aexit__(self, *args):
                pass
        from cwl_web import server_management
        option = {"id": "111111111111111111", "name": "staff-log", "type": "text"}
        with patch.dict(sys.modules, {"utils.member_event_cards": self.card_module}), \
             patch.object(api, "require_manage", new=AsyncMock(return_value=self.staff)), \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=self.store), \
             patch.object(api, "_bot_permissions", new=AsyncMock(return_value=(self.staff, object()))), \
             patch.object(api, "_validate_destination", new=AsyncMock(return_value=option)), \
             patch.object(server_management, "discord", new=AsyncMock(
                 return_value={"message": "bad"})) as discord:
            with self.assertRaises(web.HTTPServiceUnavailable) as failure:
                await api.send_test(request)
        self.assertIn("unconfirmed", failure.exception.text)
        discord.assert_awaited_once()
        self.store.finish_test.assert_awaited_once_with(
            "test-audit-id", status="uncertain", destination="111111111111111111")
