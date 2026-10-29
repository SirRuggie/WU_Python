"""Moderation archive settings, provenance, and queue isolation regressions."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import hikari
from aiohttp import web
from pymongo.errors import DuplicateKeyError

from cwl_web import member_events as api
from extensions.events import member_events as transport
from utils.member_events import GUILD_ID, MemberEventStore, SettingsConflict, effective_permissions


class MemoryCursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row[key], reverse=direction < 0)
        return self
    def limit(self, count):
        self.rows = self.rows[:count]
        return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class MemoryCollection:
    def __init__(self): self.rows = {}
    @staticmethod
    def matches(row, query):
        for key, expected in query.items():
            value = row.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]: return False
                if "$gte" in expected and (value is None or value < expected["$gte"]): return False
                if "$lte" in expected and (value is None or value > expected["$lte"]): return False
                if "$in" in expected and value not in expected["$in"]: return False
                if "$regex" in expected:
                    import re
                    if not re.search(expected["$regex"], str(value)): return False
            elif value != expected:
                return False
        return True
    async def find_one(self, query, projection=None, *, sort=None):
        rows = [row for row in self.rows.values() if self.matches(row, query)]
        if sort: rows.sort(key=lambda row: row.get(sort[0][0]), reverse=sort[0][1] < 0)
        return dict(rows[0]) if rows else None
    def find(self, query, projection=None):
        return MemoryCursor([row for row in self.rows.values() if self.matches(row, query)])
    async def insert_one(self, row):
        if row["_id"] in self.rows or any(existing.get("event_key") == row.get("event_key")
                                         for existing in self.rows.values()):
            raise DuplicateKeyError("duplicate")
        self.rows[row["_id"]] = dict(row)
    async def find_one_and_update(self, query, update, **kwargs):
        row = next((row for row in self.rows.values() if self.matches(row, query)), None)
        if row is None: return None
        row.update(update.get("$set", {}))
        for key, value in update.get("$inc", {}).items(): row[key] += value
        return dict(row)
    async def update_one(self, query, update):
        row = next((row for row in self.rows.values() if self.matches(row, query)), None)
        if row: row.update(update.get("$set", {}))
        return NS(matched_count=int(row is not None))


class ModerationBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.uid = 123456789012345678
        self.channel_id = transport.CHANNEL_ID
        self.row = {"_id": "1792972800000:" + "a" * 32, "guild_id": GUILD_ID,
                    "user_id": str(self.uid), "event_type": "kick", "display_name": "Alice",
                    "username": "alice", "avatar": None, "avatar_type": None,
                    "joined_at": None, "occurred_at": self.now,
                    "channel_id": self.channel_id, "forum_tag_id": None,
                    "delivery_status": "queued"}

    async def test_settings_revision_cas_and_defaults_do_not_enable_moderation(self):
        collection = MemoryCollection()
        store = MemberEventStore(collection)
        defaults = await store.settings()
        self.assertTrue(defaults["events"]["join"]["enabled"])
        self.assertEqual(defaults["events"]["leave"]["channel_id"], str(self.channel_id))
        self.assertFalse(defaults["events"]["kick"]["enabled"])
        self.assertFalse(defaults["events"]["ban"]["enabled"])
        events = defaults["events"]
        saved = await store.save_settings(0, events)
        self.assertEqual(saved["revision"], 1)
        with self.assertRaises(SettingsConflict):
            await store.save_settings(0, events)
        updated = await store.save_settings(1, events)
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(SettingsConflict):
            await store.save_settings(1, events)

    async def test_ban_unban_reban_is_distinct_even_with_same_old_join(self):
        store = MemberEventStore(MemoryCollection())
        first = await store.ban_episode(GUILD_ID, self.uid, banned=True)
        duplicate = await store.ban_episode(GUILD_ID, self.uid, banned=True)
        self.assertEqual(first, duplicate)
        await store.ban_episode(GUILD_ID, self.uid, banned=False)
        second = await store.ban_episode(GUILD_ID, self.uid, banned=True)
        self.assertEqual(second, first + 1)
        fields = dict(guild_id=GUILD_ID, user_id=self.uid, kind="ban",
                      display_name="Alice", username="alice", avatar=None, avatar_type=None,
                      at=self.now, joined_at=self.now, channel_id=None)
        one = await store.capture(**fields, episode=first)
        two = await store.capture(**fields, episode=second)
        self.assertNotEqual(one["event_key"], two["event_key"])
        self.assertNotEqual(one["_id"], two["_id"])

    async def test_missed_unban_is_recovered_by_distinct_audit_id(self):
        collection = MemoryCollection()
        store = MemberEventStore(collection)
        first_episode = await store.ban_episode(GUILD_ID, self.uid, banned=True)
        base = dict(guild_id=GUILD_ID, user_id=self.uid, kind="ban",
                    display_name="Alice", username="alice", avatar=None, avatar_type=None,
                    joined_at=self.now, channel_id=None)
        first = await store.capture(**base, at=self.now, episode=first_episode,
                                    audit_entry_id=111)
        await store.note_ban_audit(GUILD_ID, self.uid, 111)
        later = self.now.replace(hour=1)
        # No BanDelete event was seen while offline. BanCreate alone reuses the
        # old state and is correctly suppressed as ambiguous gateway evidence.
        same_episode = await store.ban_episode(GUILD_ID, self.uid, banned=True)
        self.assertEqual(same_episode, first_episode)
        self.assertIsNone(await store.capture(**base, at=later, episode=same_episode))
        await store.record_ban_audit(GUILD_ID, self.uid, 222, later, 999, "second action")
        self.assertFalse(await store.enrich_ban(GUILD_ID, self.uid, later, 999, "second action", 222))
        self.assertFalse(await store.ban_audit_exists(GUILD_ID, 222))
        new_episode = await store.advance_ban_episode_for_audit(GUILD_ID, self.uid, 222)
        second = await store.capture(**base, at=later, episode=new_episode,
                                     audit_entry_id=222, moderator_id=999, reason="second action")
        self.assertEqual(new_episode, first_episode + 1)
        self.assertNotEqual(first["event_key"], second["event_key"])
        self.assertTrue(await store.ban_audit_exists(GUILD_ID, 222))
        self.assertEqual(await store.advance_ban_episode_for_audit(GUILD_ID, self.uid, 222), new_episode)
        self.assertIsNone(await store.capture(**base, at=later, episode=new_episode,
                                               audit_entry_id=222))

    async def test_audit_first_ban_and_later_gateway_event_are_one_record(self):
        collection = MemoryCollection()
        store = MemberEventStore(collection)
        await store.record_ban_audit(GUILD_ID, self.uid, 333, self.now, 999, "confirmed")
        episode = await store.advance_ban_episode_for_audit(GUILD_ID, self.uid, 333)
        fields = dict(guild_id=GUILD_ID, user_id=self.uid, kind="ban",
                      display_name="Alice", username="alice", avatar=None, avatar_type=None,
                      at=self.now, joined_at=None, channel_id=None)
        row = await store.capture(**fields, episode=episode, audit_entry_id=333)
        self.assertIsNotNone(row)
        self.assertEqual(await store.ban_episode(GUILD_ID, self.uid, banned=True), episode)
        self.assertIsNone(await store.capture(**fields, episode=episode))
        self.assertEqual(sum(1 for value in collection.rows.values()
                             if value.get("event_type") == "ban"), 1)

    async def test_explicit_ban_audit_keeps_its_own_reason_amid_rapid_actions(self):
        collection = MemoryCollection()
        store = MemberEventStore(collection)
        mongo = NS(member_events=collection)
        user = NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None)
        bot = NS(rest=NS(fetch_user=AsyncMock(return_value=user)))
        await store.record_ban_audit(GUILD_ID, self.uid, 111, self.now, 10, "first reason")
        await store.record_ban_audit(GUILD_ID, self.uid, 222,
                                     self.now + timedelta(seconds=1), 20, "second reason")
        episode = await store.advance_ban_episode_for_audit(GUILD_ID, self.uid, 222)
        with patch.object(transport, "ensure_indexes", new=AsyncMock()), \
             patch.object(transport, "download_avatar", new=AsyncMock(return_value=(None, None))), \
             patch.object(transport.asyncio, "sleep", new=AsyncMock()):
            await transport.record_identity(
                "ban", GUILD_ID, self.uid, mongo, bot, user=user,
                at=self.now, moderator_id=20, reason="second reason",
                audit_entry_id=222, episode_override=episode,
            )
        bans = [row for row in collection.rows.values() if row.get("event_type") == "ban"]
        self.assertEqual(len(bans), 1)
        self.assertEqual(bans[0]["audit_entry_id"], "222")
        self.assertEqual(bans[0]["moderator_id"], "20")
        self.assertEqual(bans[0]["reason"], "second reason")
        self.assertFalse(collection.rows[f"ban-audit:{GUILD_ID}:111"]["consumed"])
        self.assertTrue(collection.rows[f"ban-audit:{GUILD_ID}:222"]["consumed"])

    async def test_ban_listeners_reconcile_missed_unban_in_both_orders(self):
        collection = MemoryCollection()
        mongo = NS(member_events=collection)
        user = NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None)
        bot = NS(rest=NS(fetch_user=AsyncMock(return_value=user)))

        async def audit(audit_id, at):
            entry = NS(guild_id=GUILD_ID, target_id=self.uid,
                       action_type=hikari.AuditLogEventType.MEMBER_BAN_ADD,
                       created_at=at, user_id=999, reason=f"ban {audit_id}", id=audit_id)
            await transport.audited(NS(entry=entry), mongo, bot)

        async def gateway():
            await transport.banned(NS(guild_id=GUILD_ID, user=user), mongo, bot)

        def bans():
            return [row for row in collection.rows.values() if row.get("event_type") == "ban"]

        with patch.object(transport, "ensure_indexes", new=AsyncMock()), \
             patch.object(transport, "download_avatar", new=AsyncMock(return_value=(None, None))), \
             patch.object(transport.asyncio, "sleep", new=AsyncMock()):
            # Audit first, then BanCreate: one durable event.
            await audit(111, self.now)
            await gateway()
            self.assertEqual(len(bans()), 1)
            self.assertEqual(bans()[0]["audit_entry_id"], "111")

            # No BanDelete was observed. BanCreate alone is ambiguous, but a
            # distinct confirmed audit entry must restore the missing episode.
            await gateway()
            self.assertEqual(len(bans()), 1)
            await audit(222, self.now + timedelta(hours=1))
            await audit(222, self.now + timedelta(hours=1))
            self.assertEqual(len(bans()), 2)
            self.assertEqual({row["audit_entry_id"] for row in bans()}, {"111", "222"})

    def test_admin_only_permission_and_staff_hidden_channel(self):
        admin = {"permissions": 8, "role_ids": set(), "user_id": "100"}
        staff = {"permissions": 8, "role_ids": set(), "user_id": "200"}
        channel = {"id": str(self.channel_id), "guild_id": str(GUILD_ID),
                   "type": 15, "name": "Mod log", "flags": 16,
                   "available_tags": [{"id": "123456789012345679", "name": "Ban", "moderated": True}],
                   "permission_overwrites": []}
        from utils.member_events import effective_permissions
        option = api._channel_option(channel, admin, effective_permissions, staff)
        self.assertTrue(option["can_post"])
        self.assertTrue(option["can_manage_threads"])
        self.assertTrue(option["requires_tag"])
        hidden_staff = {"permissions": 0, "role_ids": set(), "user_id": "200"}
        self.assertIsNone(api._channel_option(channel, admin, effective_permissions, hidden_staff))
        self.assertIsNone(api._channel_option({**channel, "guild_id": "999"}, admin,
                                               effective_permissions, staff))

    def test_forum_post_inherits_parent_permissions_and_rejects_unsafe_destinations(self):
        rights = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES_IN_THREADS | hikari.Permissions.ATTACH_FILES
        actor = {"permissions": int(rights), "role_ids": set(), "user_id": "100"}
        parent = {"id": "123456789012345678", "guild_id": str(GUILD_ID), "type": 15, "flags": 16}
        post = {"id": "123456789012345679", "guild_id": str(GUILD_ID), "parent_id": parent["id"], "type": 11, "name": "Member log", "thread_metadata": {"archived": True}}
        option = api._channel_option(post, actor, effective_permissions, actor, parent)
        self.assertEqual(option["type"], "forum_post")
        self.assertTrue(option["can_post"])
        self.assertFalse(option["requires_tag"])
        self.assertFalse(api._channel_option({**post, "thread_metadata": {"locked": True}}, actor, effective_permissions, actor, parent)["can_post"])
        for bad_parent in (None, {**parent, "type": 0}, {**parent, "guild_id": "999"}, {**parent, "id": "999"}):
            self.assertIsNone(api._channel_option(post, actor, effective_permissions, actor, bad_parent))
        hidden = {**actor, "permissions": 0}
        self.assertIsNone(api._channel_option(post, actor, effective_permissions, hidden, parent))
        denied_parent = {**parent, "permission_overwrites": [{"id": str(GUILD_ID), "type": 0, "allow": "0", "deny": str(int(hikari.Permissions.SEND_MESSAGES_IN_THREADS))}]}
        self.assertFalse(api._channel_option(post, actor, effective_permissions, actor, denied_parent)["can_post"])
        self.assertIsNone(api._channel_option({**post, "type": 12}, actor, effective_permissions, actor, parent))

    async def test_post_lookup_checks_access_and_malformed_ids_before_discord(self):
        request = NS(match_info={"channel_id": "invalid"})
        with patch.object(api, "require_manage", new=AsyncMock(return_value={})), patch.object(api, "_bot_permissions", new=AsyncMock()) as permissions:
            with self.assertRaises(web.HTTPBadRequest):
                await api.destination(request)
            permissions.assert_not_awaited()
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())), patch.object(api, "_resolve_option", new=AsyncMock()) as resolve:
            with self.assertRaises(web.HTTPForbidden):
                await api.destination(request)
            resolve.assert_not_awaited()

    async def test_post_id_resolution_and_save_revalidate_parent(self):
        from cwl_web import server_management
        import json
        actor = {"permissions": 8, "role_ids": set(), "user_id": "100"}
        parent = {"id": "123456789012345678", "guild_id": str(GUILD_ID), "type": 15, "flags": 16}
        post = {"id": str(self.channel_id), "guild_id": str(GUILD_ID), "parent_id": parent["id"], "type": 11, "name": "History"}
        events = MemberEventStore.default_settings()["events"]
        request = NS(match_info={"channel_id": str(self.channel_id)}, json=AsyncMock(return_value={"revision": 0, "events": events}))
        class Context:
            async def __aenter__(self): return NS(member_events=object())
            async def __aexit__(self, *args): pass
        store = NS(save_settings=AsyncMock(return_value={"revision": 1, "events": events}))
        async def discord(_request, method, path):
            return parent if path.endswith(parent["id"]) else post
        with patch.object(api, "require_manage", new=AsyncMock(return_value=actor)), patch.object(api, "_bot_permissions", new=AsyncMock(return_value=(actor, effective_permissions))), patch.object(server_management, "discord", side_effect=discord), patch.object(api, "mongo", return_value=Context()), patch.object(api, "MemberEventStore", return_value=store):
            result = json.loads((await api.destination(request)).text)
            self.assertEqual(result["type"], "forum_post")
            self.assertEqual((await api.save_settings(request)).status, 200)
            parent["guild_id"] = "999"
            with self.assertRaises(web.HTTPBadRequest):
                await api.save_settings(request)
            self.assertEqual(store.save_settings.await_count, 1)

    async def test_existing_post_delivery_checks_parent_and_uses_reply_transport(self):
        post = NS(id=self.channel_id, guild_id=GUILD_ID, type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                  parent_id=123456789012345678, is_locked=False)
        parent = NS(id=post.parent_id, guild_id=GUILD_ID, type=hikari.ChannelType.GUILD_FORUM, permission_overwrites={})
        rights = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES_IN_THREADS | hikari.Permissions.ATTACH_FILES
        bot = NS(rest=NS(fetch_channel=AsyncMock(side_effect=lambda cid: post if cid == self.channel_id else parent),
                        fetch_my_user=AsyncMock(return_value=NS(id=100)), fetch_member=AsyncMock(return_value=NS(role_ids=[])),
                        fetch_roles=AsyncMock(return_value=[NS(id=GUILD_ID, permissions=rights)])))
        self.assertIs(await transport.channel_ready(bot, self.row), post)
        settings = MemberEventStore.default_settings()
        settings["events"]["kick"] = {"enabled": True, "channel_id": str(self.channel_id), "forum_tag_id": None}
        store = NS(settings=AsyncMock(return_value=settings), claim=AsyncMock(return_value=self.row), finish=AsyncMock())
        with patch.object(transport, "post_card", new=AsyncMock(return_value="123")) as send:
            self.assertTrue(await transport.deliver(store, bot, self.row))
            send.assert_awaited_once_with(self.row, forum=False)
        post.is_locked = True
        self.assertIsNone(await transport.channel_ready(bot, self.row))
        post.is_locked = False
        parent.guild_id = 999
        self.assertIsNone(await transport.channel_ready(bot, self.row))

    async def test_disable_or_move_skips_only_unsent_rows(self):
        store = NS(settings=AsyncMock(), skip_queued=AsyncMock(return_value=True),
                   claim=AsyncMock(), finish=AsyncMock())
        settings = MemberEventStore.default_settings()
        settings["events"]["kick"] = {"enabled": False, "channel_id": None, "forum_tag_id": None}
        store.settings.return_value = settings
        with patch.object(transport, "channel_ready", new=AsyncMock()) as ready:
            self.assertTrue(await transport.deliver(store, NS(), self.row))
        store.skip_queued.assert_awaited_once_with(self.row["_id"])
        store.claim.assert_not_awaited()
        ready.assert_not_awaited()
        store.skip_queued.reset_mock()
        settings["events"]["kick"] = {"enabled": True,
                                       "channel_id": "123456789012345679", "forum_tag_id": None}
        self.assertTrue(await transport.deliver(store, NS(), self.row))
        store.skip_queued.assert_awaited_once()

    async def test_recovery_scans_past_unavailable_destination(self):
        rows = [{**self.row, "_id": "1792972800000:" + "a" * 32},
                {**self.row, "_id": "1792972800001:" + "b" * 32,
                 "channel_id": 123456789012345679}]
        store = NS(release_stale_captures=AsyncMock(), queued=AsyncMock(side_effect=[rows, []]))
        seen = []
        async def deliver(_store, _bot, row):
            seen.append(row["_id"])
            return row["_id"] == rows[1]["_id"]
        with patch.object(transport, "MemberEventStore", return_value=store), \
             patch.object(transport, "ensure_indexes", new=AsyncMock()), \
             patch.object(transport, "deliver", side_effect=deliver):
            await transport.recover(NS(member_events=object()), NS())
        self.assertEqual(seen, [row["_id"] for row in rows])

    async def test_settings_save_requires_live_forum_tag_and_cas(self):
        tag_id = "123456789012345679"
        channel = {"id": str(self.channel_id), "guild_id": str(GUILD_ID),
                   "type": 15, "name": "History", "flags": 16,
                   "available_tags": [{"id": tag_id, "name": "Member", "moderated": False}],
                   "permission_overwrites": []}
        events = MemberEventStore.default_settings()["events"]
        bot_actor = {"permissions": 8, "role_ids": set(), "user_id": "1"}
        staff = {"permissions": 8, "role_ids": set(), "user_id": "2"}
        class Context:
            async def __aenter__(self): return NS(member_events=object())
            async def __aexit__(self, *args): pass
        store = NS(save_settings=AsyncMock(return_value={"revision": 1, "events": events}))
        request = NS(json=AsyncMock(return_value={"revision": 0, "events": events}))
        from cwl_web import server_management
        with patch.object(api, "require_manage", new=AsyncMock(return_value=staff)), \
             patch.object(api, "_bot_permissions", new=AsyncMock(return_value=(bot_actor, effective_permissions))), \
             patch.object(server_management, "discord", new=AsyncMock(return_value=channel)), \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=store):
            with self.assertRaises(web.HTTPBadRequest):
                await api.save_settings(request)
            for kind in ("join", "leave"):
                events[kind]["forum_tag_id"] = tag_id
            response = await api.save_settings(request)
            self.assertEqual(response.status, 200)
            self.assertEqual(store.save_settings.await_count, 1)
            store.save_settings.side_effect = SettingsConflict("stale")
            with self.assertRaises(web.HTTPConflict):
                await api.save_settings(request)
            channel["guild_id"] = "999"
            with self.assertRaises(web.HTTPBadRequest):
                await api.save_settings(request)

    async def test_settings_get_retains_saved_values_when_inventory_unavailable(self):
        saved = MemberEventStore.default_settings()
        store = NS(settings=AsyncMock(return_value=saved))
        class Context:
            async def __aenter__(self): return NS(member_events=object())
            async def __aexit__(self, *args): pass
        request = NS()
        with patch.object(api, "require_manage", new=AsyncMock(return_value={"permissions": 8, "role_ids": set(), "user_id": "2"})), \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=store), \
             patch.object(api, "_bot_permissions", new=AsyncMock(side_effect=web.HTTPServiceUnavailable())):
            response = await api.settings(request)
        import json
        result = json.loads(response.text)
        self.assertFalse(result["channels_available"])
        self.assertIsNone(result["channels"])
        self.assertEqual(result["events"], saved["events"])

    async def test_only_exact_kick_audit_creates_kick(self):
        target = self.uid
        entry = NS(guild_id=GUILD_ID, target_id=target,
                   action_type=hikari.AuditLogEventType.MEMBER_KICK,
                   created_at=self.now, user_id=999, reason="reviewed", id=111)
        event = NS(entry=entry)
        bot = NS(cache=None)
        with patch.object(transport, "record_identity", new=AsyncMock()) as record:
            await transport.audited(event, NS(), bot)
        record.assert_awaited_once()
        self.assertEqual(record.await_args.args[:3], ("kick", GUILD_ID, target))
        self.assertEqual(record.await_args.kwargs["audit_entry_id"], 111)
        entry.action_type = hikari.AuditLogEventType.MEMBER_BAN_REMOVE
        with patch.object(transport, "record_identity", new=AsyncMock()) as record:
            await transport.audited(event, NS(), bot)
        record.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
