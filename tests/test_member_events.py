"""Member event durability, delivery ambiguity, and staff API boundaries."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import hikari
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from aiohttp.test_utils import make_mocked_request

from cwl_web import member_events as api
from extensions.events import member_events as transport
from utils.member_event_cards import build_card, build_forum_message, sample_row
from utils.member_event_settings import EVENT_TYPES, normalize_settings
from utils.member_events import GUILD_ID, MemberEventStore, avatar_source, event_key, safe_text
from tests.test_moderation_backend import MemoryCollection


def settings():
    return normalize_settings(None, MemberEventStore.default_settings())


class MemberEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.row = {"_id": "1792972800000:" + "a" * 32, "guild_id": GUILD_ID,
                    "user_id": "123456789012345678", "event_type": "join",
                    "display_name": "Alice", "username": "alice",
                    "occurred_at": self.now, "avatar": None, "avatar_type": None,
                    "delivery_status": "queued", "channel_id": transport.CHANNEL_ID,
                    "forum_tag_id": None}

    def test_join_and_leave_episodes_deduplicate_without_losing_rapid_rejoin(self):
        joined_one = self.now
        joined_two = self.now + timedelta(seconds=3)
        self.assertEqual(event_key(GUILD_ID, 123, "join", self.now, joined_one),
                         event_key(GUILD_ID, 123, "join", self.now + timedelta(seconds=1), joined_one))
        self.assertNotEqual(event_key(GUILD_ID, 123, "leave", self.now, joined_one),
                            event_key(GUILD_ID, 123, "leave", self.now + timedelta(seconds=4), joined_two))
        self.assertNotEqual(event_key(GUILD_ID, 123, "join", self.now, joined_one),
                            event_key(GUILD_ID, 123, "leave", self.now, joined_one))

    def test_safe_text_keeps_emoji_joiners_but_still_strips_and_escapes(self):
        family = "👨\u200d👩\u200d👧 fam"
        self.assertEqual(safe_text(family), family)
        self.assertEqual(safe_text("a\x00b\u200bc\u202ed"), "abcd")
        self.assertEqual(safe_text("**@everyone** <@1>"), "\\*\\*@\u200beveryone\\*\\* \\<@\u200b1\\>")
        for kind in ("invite_use", "invite_create"):
            row = {**sample_row(kind), "details": {**sample_row(kind)["details"], "name": family}}
            self.assertIn(family, json.dumps(build_card(row), ensure_ascii=False))

    def test_avatar_source_and_rendering_reject_external_identity_markup(self):
        self.assertIsNone(avatar_source(GUILD_ID, 123, "../../escape"))
        self.assertEqual(avatar_source(GUILD_ID, 123, "a" * 32),
                         f"https://cdn.discordapp.com/avatars/123/{'a' * 32}.png?size=128")
        text = safe_text("<@123> @everyone **bad**\nline")
        self.assertNotIn("<@123>", text)
        self.assertNotIn("@everyone", text)
        self.assertNotIn("**bad**", text)
        built = build_card({**self.row, "display_name": "<@123> @everyone"})["components"][0]
        self.assertEqual(built["accent_color"], 0x2BA66A)
        self.assertNotIn("@everyone", json.dumps(built))
        json.dumps(built)

    def test_card_uses_utc_for_naive_saved_times_and_shows_join_date(self):
        import os
        import time
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            occurred = datetime(2026, 10, 27, 2, 59, 36)
            joined = datetime(2025, 7, 30, 13, 45, 12)
            row = {**self.row, "event_type": "leave", "occurred_at": occurred, "joined_at": joined}
            card = build_card(row)
            text = json.dumps(card)
            stamp = int(occurred.replace(tzinfo=timezone.utc).timestamp())
            joined_stamp = int(joined.replace(tzinfo=timezone.utc).timestamp())
            self.assertIn(f"<t:{stamp}:f>", text)
            self.assertIn(f"<t:{joined_stamp}:f>", text)
            self.assertIn(f"<t:{joined_stamp}:R>", text)
            aware = build_card({**row, "occurred_at": occurred.replace(tzinfo=timezone.utc), "joined_at": joined.replace(tzinfo=timezone.utc)})
            self.assertEqual(card, aware)
            unknown = build_card({**row, "joined_at": None})
            self.assertIn("Date unavailable", json.dumps(unknown))
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    async def test_capture_precedes_avatar_fetch_and_failure_still_delivers_identity(self):
        member = NS(guild_id=GUILD_ID, user=NS(id=123456789012345678, username="alice", avatar_hash="a" * 32),
                    display_name="Alice", guild_avatar_hash=None, joined_at=self.now)
        event = NS(member=member)
        row = dict(self.row)
        store = NS(ensure_indexes=AsyncMock(), capture=AsyncMock(return_value=row),
                   save_avatar=AsyncMock(), ready=AsyncMock(return_value=row),
                   settings=AsyncMock(return_value=settings()), count_joins=AsyncMock(return_value=0),
                   save_details=AsyncMock())
        order = []
        async def capture(**kwargs):
            order.append("capture")
            self.assertIsNone(kwargs["avatar"])
            return row
        async def download(url):
            order.append("avatar")
            return None, None
        store.capture.side_effect = capture
        with patch.object(transport, "MemberEventStore", return_value=store), \
             patch.object(transport, "ensure_indexes", new=AsyncMock()), \
             patch.object(transport, "download_avatar", side_effect=download), \
             patch.object(transport, "INVITE_WAIT_SECONDS", 0.01), \
             patch.object(transport, "deliver", new_callable=AsyncMock) as deliver:
            await transport.record(event, "join", NS(member_events=object()), NS())
        self.assertEqual(order, ["capture", "avatar"])
        store.save_avatar.assert_not_awaited()
        deliver.assert_awaited_once_with(store, unittest.mock.ANY, row)

    async def test_store_deduplicates_gateway_replay_and_never_reclaims_uncertain(self):
        class Collection:
            def __init__(self): self.rows = {}
            async def insert_one(self, row):
                if any(existing["event_key"] == row["event_key"] for existing in self.rows.values()):
                    raise DuplicateKeyError("duplicate")
                self.rows[row["_id"]] = dict(row)
            async def find_one_and_update(self, query, update, **kwargs):
                row = self.rows.get(query["_id"])
                if row is None or row["delivery_status"] != query["delivery_status"]: return None
                row.update(update["$set"])
                return dict(row)
            async def update_one(self, query, update):
                row = self.rows.get(query["_id"])
                if row and row["delivery_status"] == query["delivery_status"]:
                    row.update(update["$set"])
        collection = Collection()
        store = MemberEventStore(collection)
        fields = dict(guild_id=GUILD_ID, user_id=123456789012345678, kind="join",
                      display_name="Alice", username="alice", avatar=None, avatar_type=None,
                      at=self.now, joined_at=self.now, channel_id=transport.CHANNEL_ID)
        first = await store.capture(**fields)
        self.assertIsNone(await store.capture(**fields))
        self.assertEqual(len(collection.rows), 1)
        self.assertIsNone(await store.claim(first["_id"]))
        await store.save_avatar(first["_id"], b"saved-pfp", "image/png")
        self.assertEqual(collection.rows[first["_id"]]["avatar"], b"saved-pfp")
        await store.ready(first["_id"])
        await store.save_avatar(first["_id"], b"late-pfp", "image/png")
        self.assertEqual(collection.rows[first["_id"]]["avatar"], b"saved-pfp")
        self.assertIsNotNone(await store.claim(first["_id"]))
        await store.finish(first["_id"], status="uncertain")
        self.assertIsNone(await store.claim(first["_id"]))
        second = await store.capture(**{**fields, "at": self.now + timedelta(seconds=3),
                                        "joined_at": self.now + timedelta(seconds=3)})
        self.assertIsNotNone(second)
        self.assertEqual(len(collection.rows), 2)

    async def test_avatar_download_collects_partial_chunks_with_limit(self):
        class Content:
            def __init__(self, parts): self.parts = parts
            async def iter_chunked(self, count):
                for part in self.parts: yield part
        class Response:
            status = 200
            headers = {"Content-Type": "image/png"}
            def __init__(self, parts): self.content = Content(parts)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        class Session:
            def __init__(self, parts, **kwargs): self.parts = parts
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def get(self, url, **kwargs):
                self.allow_redirects = kwargs.get("allow_redirects")
                return Response(self.parts)
        with patch.object(transport.aiohttp, "ClientSession", side_effect=lambda **kwargs: Session([b"a", b"bc"], **kwargs)):
            self.assertEqual(await transport.download_avatar("https://cdn.discordapp.com/example"), (b"abc", "image/png"))
        with patch.object(transport.aiohttp, "ClientSession", side_effect=lambda **kwargs: Session([b"a" * (256 * 1024), b"b"], **kwargs)):
            self.assertEqual(await transport.download_avatar("https://cdn.discordapp.com/example"), (None, None))

    async def test_uncached_leave_resolves_saved_join_episode(self):
        user = NS(id=123456789012345678, username="alice", avatar_hash=None, global_name="Alice")
        event = NS(guild_id=GUILD_ID, old_member=None, user=user)
        captured = {}
        async def capture(**kwargs):
            captured.update(kwargs)
            return self.row
        store = NS(capture=AsyncMock(side_effect=capture), latest_joined_at=AsyncMock(return_value=self.now),
                   latest_identity=AsyncMock(return_value=None),
                   settings=AsyncMock(return_value=settings()),
                   save_avatar=AsyncMock(), ready=AsyncMock(return_value=self.row),
                   enrich_recent_kick=AsyncMock())
        with patch.object(transport, "MemberEventStore", return_value=store), \
             patch.object(transport, "ensure_indexes", new=AsyncMock()), \
             patch.object(transport, "download_avatar", new=AsyncMock(return_value=(None, None))), \
             patch.object(transport, "deliver", new=AsyncMock()):
            await transport.record(event, "leave", NS(member_events=object()), NS())
        store.latest_joined_at.assert_awaited_once()
        self.assertEqual(captured["joined_at"], self.now)
        self.assertEqual(captured["kind"], "leave")

    async def test_recovery_releases_only_stale_captures(self):
        now = datetime.now(timezone.utc)
        old = {**self.row, "_id": "old", "delivery_status": "capturing",
               "channel_id": transport.CHANNEL_ID, "occurred_at": now - timedelta(seconds=20)}
        fresh = {**self.row, "_id": "fresh", "delivery_status": "capturing",
                 "channel_id": transport.CHANNEL_ID, "occurred_at": now}
        wrong_channel = {**old, "_id": "wrong", "channel_id": transport.CHANNEL_ID + 1}
        class Collection:
            async def update_many(self, query, update):
                for row in (old, fresh, wrong_channel):
                    if (row["guild_id"] == query["guild_id"] and
                        row["channel_id"] == query["channel_id"] and
                        row["delivery_status"] == query["delivery_status"] and
                        row["occurred_at"] <= query["occurred_at"]["$lte"]):
                        row.update(update["$set"])
        await MemberEventStore(Collection()).release_stale_captures(GUILD_ID, transport.CHANNEL_ID)
        self.assertEqual(old["delivery_status"], "queued")
        self.assertEqual(fresh["delivery_status"], "capturing")
        self.assertEqual(wrong_channel["delivery_status"], "capturing")

    async def test_search_page_and_avatar_are_scoped_to_same_guild(self):
        class Cursor:
            def __init__(self, rows): self.rows = rows
            def sort(self, key, direction):
                self.rows.sort(key=lambda r: r[key], reverse=direction < 0)
                return self
            def limit(self, count):
                self.rows = self.rows[:count]
                return self
            async def to_list(self, length): return self.rows[:length]
        class Collection:
            def __init__(self, rows): self.rows = rows; self.queries = []
            def find(self, query, projection=None):
                self.queries.append(query)
                rows = [r for r in self.rows if r["guild_id"] == query["guild_id"]]
                if "_id" in query: rows = [r for r in rows if r["_id"] < query["_id"]["$lt"]]
                if "event_type" in query: rows = [r for r in rows if r["event_type"] == query["event_type"]]
                return Cursor([dict(r) for r in rows])
            async def find_one(self, query, projection=None, **kwargs):
                self.queries.append(query)
                return next((r for r in self.rows if r["_id"] == query.get("_id") and r["guild_id"] == query["guild_id"]), None)
        ids = [f"179297280000{i}:{i:032x}" for i in range(4)]
        rows = [{**self.row, "_id": key, "guild_id": GUILD_ID} for key in ids]
        rows.append({**self.row, "_id": "1792972800005:" + "f" * 32, "guild_id": GUILD_ID + 1})
        rows[0]["avatar"], rows[0]["avatar_type"] = b"saved-avatar", "image/png"
        collection = Collection(rows)
        store = MemberEventStore(collection)
        page, cursor = await store.search(guild_id=GUILD_ID, kind="join", limit=2)
        self.assertEqual([r["_id"] for r in page], ids[3:1:-1])
        self.assertEqual(cursor, ids[2])
        next_page, next_cursor = await store.search(guild_id=GUILD_ID, kind="join", before=cursor, limit=2)
        self.assertEqual([r["_id"] for r in next_page], ids[1::-1])
        self.assertIsNone(next_cursor)
        self.assertEqual((await store.avatar(ids[0], GUILD_ID))["avatar"], b"saved-avatar")
        self.assertIsNone(await store.avatar(ids[0], GUILD_ID + 1))
        self.assertTrue(all(q["guild_id"] in (GUILD_ID, GUILD_ID + 1) for q in collection.queries))

    async def test_channel_mismatch_never_claims_or_posts(self):
        store = NS(claim=AsyncMock(), finish=AsyncMock(),
                   settings=AsyncMock(return_value=settings()),
                   skip_queued=AsyncMock())
        with patch.object(transport, "channel_ready", new=AsyncMock(return_value=False)), \
             patch.object(transport, "post_card", new=AsyncMock()) as post:
            await transport.deliver(store, NS(), self.row)
        store.claim.assert_not_awaited()
        post.assert_not_awaited()

    async def test_ambiguous_post_is_marked_uncertain_and_not_retried(self):
        store = NS(claim=AsyncMock(return_value=self.row), finish=AsyncMock(),
                   settings=AsyncMock(return_value=settings()),
                   skip_queued=AsyncMock())
        with patch.object(transport, "channel_ready", new=AsyncMock(return_value=NS(type=0))), \
             patch.object(transport, "post_card", new=AsyncMock(side_effect=TimeoutError)) as post:
            with self.assertRaises(TimeoutError):
                await transport.deliver(store, NS(), self.row)
        self.assertEqual(post.await_count, 1)
        store.finish.assert_awaited_once_with(self.row["_id"], status="uncertain")

    async def test_api_checks_auth_before_query_and_avatar(self):
        request = make_mocked_request("GET", api.PREFIX + "?q=Alice")
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())):
            with self.assertRaises(web.HTTPForbidden):
                await api.listing(request)
        request = make_mocked_request("GET", api.PREFIX + "/" + self.row["_id"] + "/avatar",
                                      match_info={"event_id": self.row["_id"]})
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())):
            with self.assertRaises(web.HTTPForbidden):
                await api.avatar(request)

    async def test_api_rejects_malformed_dates_cursor_filters_and_limit(self):
        for suffix in ("?from=2026-02-30", "?to=9999-12-31", "?before=bad",
                       "?type=unknown", "?limit=101", "?q=" + "x" * 81,
                       "?from=2026-10-27&to=2026-10-26"):
            with self.subTest(suffix=suffix), patch.object(api, "require_manage", new=AsyncMock()):
                with self.assertRaises(web.HTTPBadRequest):
                    await api.listing(make_mocked_request("GET", api.PREFIX + suffix))

    async def test_api_uses_exact_guild_and_no_store_cache(self):
        called = {}
        async def search(**kwargs):
            called.update(kwargs)
            return [self.row], None
        fake_store = NS(search=search)
        class Context:
            async def __aenter__(self): return NS(member_events=object())
            async def __aexit__(self, *args): pass
        request = make_mocked_request("GET", api.PREFIX + "?q=Ali&type=join&from=2026-10-26&to=2026-10-26")
        with patch.object(api, "require_manage", new=AsyncMock()) as authorized, \
             patch.object(api, "mongo", return_value=Context()), \
             patch.object(api, "MemberEventStore", return_value=fake_store):
            response = await api.listing(request)
        authorized.assert_awaited_once_with(request, "roles")
        self.assertEqual(called["guild_id"], GUILD_ID)
        self.assertEqual((called["end"] - called["start"]).days, 1)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(response.text)["events"][0]["user_id"], self.row["user_id"])


class InviteCursor:
    def __init__(self, rows): self.rows = rows
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class InviteCollection:
    def __init__(self): self.rows = {}
    async def create_index(self, *args, **kwargs): pass
    def find(self, query):
        return InviteCursor([row for row in self.rows.values() if row["guild_id"] == query["guild_id"]])
    async def find_one(self, query): return self.rows.get(query["_id"])
    async def replace_one(self, query, row, upsert=False): self.rows[query["_id"]] = dict(row)
    async def delete_one(self, query): self.rows.pop(query["_id"], None)
    async def delete_many(self, query):
        keep = set(query["code"]["$nin"])
        for key in [k for k, row in self.rows.items()
                    if row["guild_id"] == query["guild_id"] and row["code"] not in keep]:
            del self.rows[key]


def invite(code, uses, max_uses=None, **extra):
    return NS(code=code, uses=uses, max_uses=max_uses, inviter=NS(id=987654321098765432, username="host", global_name=None),
              channel=NS(id=223456789012345678, name="welcome"), channel_id=223456789012345678,
              expires_at=None, **extra)


async def enable(collection, *kinds, **extra):
    saved = normalize_settings(None, MemberEventStore.default_settings())
    for kind in kinds:
        saved["events"][kind] = {"enabled": True, "channel_id": "223456789012345678", "forum_tag_id": None}
    saved.update(extra)
    await MemberEventStore(collection).save_settings(0, saved)


class NewLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        self.uid = 123456789012345678
        self.history = MemoryCollection()
        self.invites = InviteCollection()
        self.mongo = NS(member_events=self.history, member_invites=self.invites)
        self.patches = [patch.object(transport, "ensure_indexes", new=AsyncMock()),
                        patch.object(transport, "deliver", new=AsyncMock())]
        self.deliver = self.patches[1].start()
        self.patches[0].start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def rows(self, kind):
        return [row for row in self.history.rows.values() if row.get("event_type") == kind]

    async def test_old_settings_row_without_new_keys_reads_and_saves(self):
        old = MemberEventStore.default_settings()
        old["events"] = {k: v for k, v in old["events"].items() if k in ("join", "leave", "kick", "ban")}
        old["revision"] = 3
        old["categories"] = {"members": {"mode": "own", "channel_id": "111111111111111111", "forum_tag_id": None},
                             "moderation": {"mode": "main", "channel_id": None, "forum_tag_id": None}}
        old["ignores"] = {}
        self.history.rows["member-events-settings:%d" % GUILD_ID] = {
            "_id": "member-events-settings:%d" % GUILD_ID, "event_key": "x", **old}
        store = MemberEventStore(self.history)
        loaded = await store.settings()
        self.assertEqual(set(loaded["categories"]), {"members", "moderation", "roles", "messages",
                                                     "channels", "server", "invites"})
        self.assertEqual(loaded["categories"]["roles"], {"mode": "main", "channel_id": None, "forum_tag_id": None})
        self.assertEqual(loaded["categories"]["members"]["mode"], "own")
        self.assertEqual(loaded["ignores"], {"channel_ids": [], "role_ids": []})
        self.assertEqual(loaded["invite_names"], {})
        for kind in EVENT_TYPES:
            if kind in ("join", "leave"):
                continue
            self.assertEqual(loaded["events"][kind], {"enabled": False, "channel_id": None, "forum_tag_id": None})
        self.assertIsNone(loaded["ignored_bot_ids"])  # Never saved: the runtime default applies.
        saved = await store.save_settings(3, loaded)
        self.assertEqual(saved["revision"], 4)
        self.assertEqual(self.history.rows["member-events-settings:%d" % GUILD_ID]["invite_names"], {})
        self.assertNotIn("ignored_bot_ids", self.history.rows["member-events-settings:%d" % GUILD_ID])
        saved = await store.save_settings(4, {**loaded, "ignored_bot_ids": []})  # Staff chose an empty list.
        self.assertEqual(self.history.rows["member-events-settings:%d" % GUILD_ID]["ignored_bot_ids"], [])
        self.assertEqual((await store.settings())["ignored_bot_ids"], [])

    async def test_bot_actor_doc_keeps_100_newest_and_is_not_history_or_expiring(self):
        store = MemberEventStore(self.history)
        start = datetime(2026, 11, 6, tzinfo=timezone.utc)
        for index in range(101):
            await store.note_bot_actor(10 ** 17 + index, f"bot{index}", start + timedelta(minutes=index))
        bots = await store.bot_actors()
        self.assertEqual(len(bots), 100)
        self.assertNotIn(str(10 ** 17), bots)  # The oldest was dropped.
        self.assertIn(str(10 ** 17 + 100), bots)
        doc = self.history.rows["member-events-bot-actors:%d" % GUILD_ID]
        self.assertNotIn("expires_at", doc)
        self.assertNotIn("event_type", doc)
        await store.note_bot_actor(10 ** 17 + 5, "renamed", start + timedelta(hours=3))  # Seen again, new name.
        self.assertEqual((await store.bot_actors())[str(10 ** 17 + 5)]["name"], "renamed")
        await store.advance_audit_cursor(500)
        self.assertNotIn("expires_at", self.history.rows["member-events-audit-cursor:%d" % GUILD_ID])
        # State docs never reach history (they carry no event type).
        from utils.member_events import HISTORY_TYPES
        self.assertTrue(all(row.get("event_type") not in HISTORY_TYPES for row in self.history.rows.values()))
        found, _ = await store.search(guild_id=GUILD_ID)
        self.assertEqual(found, [])

    async def test_audit_cursor_only_moves_forward(self):
        store = MemberEventStore(self.history)
        self.assertIsNone(await store.audit_cursor())
        await store.advance_audit_cursor(1000)
        await store.advance_audit_cursor(900)
        self.assertEqual(await store.audit_cursor(), 1000)
        await store.advance_audit_cursor(1001)
        self.assertEqual(await store.audit_cursor(), 1001)

    async def test_timeout_add_and_remove_come_from_the_audit_entry_once(self):
        await enable(self.history, "timeout_add", "timeout_remove")
        member = NS(user=NS(username="alice", global_name="Alice", avatar_hash=None), display_name="Alice",
                    joined_at=self.now - timedelta(days=400), guild_avatar_hash=None)
        bot = NS(cache=NS(get_member=lambda guild, uid: member))
        key = hikari.AuditLogChangeKey.COMMUNICATION_DISABLED_UNTIL

        def entry(entry_id, new, old):
            return NS(guild_id=GUILD_ID, target_id=self.uid, id=entry_id, user_id=999, reason="spam",
                      action_type=hikari.AuditLogEventType.MEMBER_UPDATE, created_at=self.now,
                      changes=[NS(key=key, new_value=new, old_value=old)])
        until = self.now + timedelta(hours=1, seconds=1)
        await transport.audited(NS(entry=entry(1001, until, None)), self.mongo, bot)
        await transport.audited(NS(entry=entry(1001, until, None)), self.mongo, bot)  # Gateway replay.
        added = self.rows("timeout_add")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["details"]["duration_seconds"], 3600)
        self.assertEqual(added[0]["details"]["until"], until.isoformat())
        self.assertEqual((added[0]["moderator_id"], added[0]["reason"]), ("999", "spam"))
        self.assertIsNone(added[0]["avatar"])
        self.assertEqual(self.deliver.await_count, 1)
        await transport.audited(NS(entry=entry(1002, None, until)), self.mongo, bot)
        self.assertEqual(len(self.rows("timeout_remove")), 1)
        nick = NS(guild_id=GUILD_ID, target_id=self.uid, id=1003, user_id=999, reason=None,
                  action_type=hikari.AuditLogEventType.MEMBER_UPDATE, created_at=self.now,
                  changes=[NS(key=hikari.AuditLogChangeKey.NICK, new_value="x", old_value="y")])
        await transport.audited(NS(entry=nick), self.mongo, bot)
        self.assertEqual(len(self.history.rows), 3)  # settings + two timeout rows only.

    async def test_timeout_history_is_kept_when_delivery_is_off(self):
        member = NS(user=NS(username="alice", global_name=None, avatar_hash=None), display_name="Alice",
                    joined_at=None, guild_avatar_hash=None)
        entry = NS(guild_id=GUILD_ID, target_id=self.uid, id=7, user_id=999, reason=None,
                   action_type=hikari.AuditLogEventType.MEMBER_UPDATE, created_at=self.now,
                   changes=[NS(key=hikari.AuditLogChangeKey.COMMUNICATION_DISABLED_UNTIL,
                               new_value=self.now + timedelta(minutes=5), old_value=None)])
        await transport.audited(NS(entry=entry), self.mongo, NS(cache=NS(get_member=lambda g, u: member)))
        row = self.rows("timeout_add")[0]
        self.assertEqual(row["delivery_status"], "skipped")
        self.deliver.assert_not_awaited()

    def test_profile_changes_cover_contract_fields_only(self):
        def member(**changes):
            user = dict(username="alice", global_name="Alice", avatar_hash="a" * 32, discriminator="0")
            user.update({k: v for k, v in changes.items() if k in user})
            return NS(user=NS(**user), nickname=changes.get("nickname"), guild_avatar_hash=changes.get("guild_avatar_hash"),
                      role_ids=changes.get("role_ids", []), communication_disabled_until=changes.get("until"))
        base = member()
        self.assertEqual(transport.profile_changes(base, member(role_ids=[1, 2])), [])
        self.assertEqual(transport.profile_changes(base, member(until=self.now)), [])
        self.assertEqual(transport.profile_changes(base, member(nickname="Al")),
                         [{"field": "nickname", "before": None, "after": "Al"}])
        fields = [c["field"] for c in transport.profile_changes(
            base, member(username="al", global_name="Al", avatar_hash="b" * 32, guild_avatar_hash="c" * 32))]
        self.assertEqual(fields, ["username", "global_name", "avatar", "guild_avatar"])
        avatar = transport.profile_changes(base, member(avatar_hash="b" * 32))[0]
        self.assertEqual((avatar["before"], avatar["after"]), (None, None))  # Hashes are never shown.
        self.assertEqual(transport.profile_changes(base, member(discriminator="1234"))[0]["field"], "discriminator")

    async def test_member_update_skips_unknown_old_member_and_posts_nickname_change_with_actor(self):
        await enable(self.history, "member_update")
        user = NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None, discriminator="0")
        old = NS(user=user, nickname="Old", guild_avatar_hash=None, display_name="Old")
        new = NS(user=user, nickname="New", guild_avatar_hash=None, display_name="New",
                 joined_at=self.now - timedelta(days=3), guild_id=GUILD_ID)
        audit = NS(entries={1: NS(target_id=self.uid, user_id=999, created_at=datetime.now(timezone.utc),
                                  changes=[NS(key=hikari.AuditLogChangeKey.NICK)])})

        async def pages(*args, **kwargs):
            yield audit
        bot = NS(rest=NS(fetch_audit_log=pages))
        with patch.object(transport.asyncio, "sleep", new=AsyncMock()):
            await transport.record_profile_change(NS(guild_id=GUILD_ID, old_member=None, member=new), self.mongo, bot)
            self.assertEqual(self.rows("member_update"), [])
            await transport.record_profile_change(NS(guild_id=GUILD_ID, old_member=old, member=new), self.mongo, bot)
            same = NS(user=user, nickname="Old", guild_avatar_hash=None, display_name="Old", joined_at=None)
            await transport.record_profile_change(NS(guild_id=GUILD_ID, old_member=old, member=same), self.mongo, bot)
        (row,) = self.rows("member_update")
        self.assertEqual(row["details"]["changes"], [{"field": "nickname", "before": "Old", "after": "New"}])
        self.assertEqual(row["details"]["actor_id"], "999")
        self.assertIsNone(row["avatar"])
        self.deliver.assert_awaited_once()

    def test_url_extraction_trims_punctuation_and_bounds(self):
        text = "see (https://a.example/x). and <https://b.example/y>, https://a.example/x http://c.example/z>"
        self.assertEqual(transport.extract_urls(text),
                         ["https://a.example/x", "https://b.example/y", "http://c.example/z"])
        self.assertEqual(transport.extract_urls("no links here, just https:// alone"), [])
        many = " ".join(f"https://e.example/{i}" for i in range(30))
        self.assertEqual(len(transport.extract_urls(many)), 10)
        self.assertEqual(len(transport.extract_urls("https://e.example/" + "a" * 500)[0]), 200)

    async def test_link_ignore_rules_bot_skip_and_message_dedupe(self):
        await enable(self.history, "link", ignores={"channel_ids": ["333333333333333333"],
                                                    "role_ids": ["444444444444444444"]})
        threads = {555555555555555555: NS(type=hikari.ChannelType.GUILD_PUBLIC_THREAD, parent_id=333333333333333333),
                   666666666666666666: NS(type=hikari.ChannelType.GUILD_TEXT, parent_id=333333333333333333)}  # Category.
        bot = NS(cache=NS(get_thread=lambda cid: threads.get(cid), get_guild_channel=lambda cid: threads.get(cid)))

        def event(message_id, channel=777777777777777777, bot_author=False, roles=(), webhook=None, content="x https://e.example/a"):
            author = NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None, is_bot=bot_author)
            member = NS(display_name="Alice", role_ids=list(roles), joined_at=None, guild_avatar_hash=None)
            return NS(message=NS(id=message_id, guild_id=GUILD_ID, channel_id=channel, author=author, member=member,
                                 webhook_id=webhook, content=content, created_at=self.now))
        for case in (event(1, channel=333333333333333333), event(2, channel=555555555555555555),
                     event(3, roles=[444444444444444444]), event(4, bot_author=True),
                     event(5, webhook=888888888888888888), event(6, content="plain text")):
            await transport.record_link(case, self.mongo, bot)
        self.assertEqual(self.rows("link"), [])
        await transport.record_link(event(7, channel=666666666666666666), self.mongo, bot)  # Category id is not a parent.
        await transport.record_link(event(7, channel=666666666666666666), self.mongo, bot)  # Replay.
        (row,) = self.rows("link")
        self.assertEqual(row["details"]["message_id"], "7")
        self.assertEqual(row["details"]["urls"], ["https://e.example/a"])
        self.deliver.assert_awaited_once()

    async def test_link_is_not_stored_when_delivery_is_off(self):
        author = NS(id=self.uid, username="a", global_name=None, avatar_hash=None, is_bot=False)
        message = NS(id=1, guild_id=GUILD_ID, channel_id=1, author=author, member=None, webhook_id=None,
                     content="https://e.example", created_at=self.now)
        await transport.record_link(NS(message=message), self.mongo, NS(cache=None))
        self.assertEqual(self.rows("link"), [])

    def test_attribution_single_ambiguous_vanity_and_vanished(self):
        from utils.member_invites import attribute_join
        row = lambda uses, max_uses=None: {"uses": uses, "max_uses": max_uses}
        before = {"aa": row(1), "bb": row(2), "vanity": row(9)}
        self.assertEqual(attribute_join(before, {"aa": row(2), "bb": row(2), "vanity": row(9)}), "aa")
        self.assertIsNone(attribute_join(before, {"aa": row(2), "bb": row(3), "vanity": row(9)}))  # Ambiguous.
        self.assertIsNone(attribute_join(before, {"aa": row(3), "bb": row(2), "vanity": row(9)}))  # Two joins.
        self.assertIsNone(attribute_join(before, before))
        self.assertEqual(attribute_join(before, {"aa": row(1), "bb": row(2), "vanity": row(10)}), "vanity")
        spent = {"cc": row(4, 5)}
        self.assertEqual(attribute_join(spent, {}), "cc")  # Vanished at max_uses - 1.
        self.assertIsNone(attribute_join({"cc": row(2, 5)}, {}))  # Expired or deleted, not spent.
        self.assertIsNone(attribute_join({"cc": row(4, 0)}, {}))
        self.assertEqual(attribute_join({"cc": row(4, 5), "dd": row(0)}, {"dd": row(0)}), "cc")

    async def join(self, fetch, uid=None):
        uid = uid or self.uid
        user = NS(id=uid, username="newbie", global_name=None, avatar_hash=None)
        member = NS(guild_id=GUILD_ID, user=user, display_name="Newbie", joined_at=self.now,
                    guild_avatar_hash=None)
        bot = NS(rest=NS(fetch_guild_invites=fetch, fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")),
                         ), cache=None)
        await transport.record_invite_use(NS(member=member), self.mongo, bot)

    async def test_invite_use_attributes_one_invite_and_updates_snapshot(self):
        await enable(self.history, "invite_use", invite_names={"aa": "Spring"})
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("aa", 1, 5), invite("bb", 0)]),
            fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))))
        await self.join(AsyncMock(return_value=[invite("aa", 2, 5), invite("bb", 0)]))
        (row,) = self.rows("invite_use")
        self.assertEqual((row["details"]["code"], row["details"]["name"], row["details"]["uses"]), ("aa", "Spring", 2))
        self.assertEqual(row["details"]["inviter_name"], "host")
        self.assertFalse(row["details"]["unknown"])
        self.assertEqual(self.invites.rows[f"{GUILD_ID}:aa"]["uses"], 2)

    async def test_invite_use_attributes_when_vanity_fetch_is_forbidden(self):
        await enable(self.history, "invite_use")
        for error in (hikari.ForbiddenError("u", {}, b""), hikari.BadRequestError("u", {}, b"")):
            rest = NS(fetch_guild_invites=AsyncMock(return_value=[invite("aa", 1, 5)]),
                      fetch_vanity_url=AsyncMock(side_effect=error))
            await transport.refresh_invites(self.mongo, NS(cache=None, rest=rest))
            self.assertEqual(self.invites.rows[f"{GUILD_ID}:aa"]["uses"], 1)
            user = NS(id=self.uid, username="newbie", global_name=None, avatar_hash=None)
            member = NS(guild_id=GUILD_ID, user=user, display_name="Newbie", joined_at=self.now, guild_avatar_hash=None)
            rest.fetch_guild_invites = AsyncMock(return_value=[invite("aa", 2, 5)])
            await transport.record_invite_use(NS(member=member), self.mongo, NS(rest=rest, cache=None))
            self.assertEqual(self.rows("invite_use")[-1]["details"]["code"], "aa")
            self.assertFalse(self.rows("invite_use")[-1]["details"]["unknown"])

    async def test_invite_use_unknown_when_ambiguous_or_fetch_fails_and_never_raises(self):
        await enable(self.history, "invite_use")
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("aa", 1), invite("bb", 1)]),
            fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))))
        await self.join(AsyncMock(return_value=[invite("aa", 2), invite("bb", 2)]), uid=123456789012345601)
        forbidden = AsyncMock(side_effect=hikari.ForbiddenError("u", {}, b""))
        with self.assertLogs(transport.log, "WARNING") as logs:
            await self.join(forbidden, uid=123456789012345602)
        self.assertEqual(len(logs.records), 1)
        rows = self.rows("invite_use")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["details"]["unknown"] for row in rows))
        self.assertEqual(self.invites.rows[f"{GUILD_ID}:aa"]["uses"], 2)  # Failure left the snapshot alone.
        no_counts = AsyncMock(return_value=[NS(code="aa")])  # Without Manage Server there are no counts.
        with self.assertLogs(transport.log, "WARNING"):
            await self.join(no_counts, uid=123456789012345603)

    async def test_vanity_and_vanished_single_use_invite_are_attributed(self):
        await enable(self.history, "invite_use")
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("once", 0, 1)]),
            fetch_vanity_url=AsyncMock(return_value=NS(code="wu", uses=40)))))
        vanity_bot = NS(cache=None, rest=NS(fetch_guild_invites=AsyncMock(return_value=[invite("once", 0, 1)]),
                                           fetch_vanity_url=AsyncMock(return_value=NS(code="wu", uses=41))))
        user = NS(id=123456789012345611, username="u", global_name=None, avatar_hash=None)
        member = NS(guild_id=GUILD_ID, user=user, display_name="U", joined_at=self.now, guild_avatar_hash=None)
        await transport.record_invite_use(NS(member=member), self.mongo, vanity_bot)
        await self.join(AsyncMock(return_value=[]), uid=123456789012345612)  # "once" is gone: it was spent.
        by = {row["user_id"]: row["details"] for row in self.rows("invite_use")}
        self.assertTrue(by["123456789012345611"]["vanity"])
        self.assertEqual(by["123456789012345611"]["code"], "wu")
        self.assertEqual((by["123456789012345612"]["code"], by["123456789012345612"]["uses"]), ("once", 1))

    async def test_concurrent_joins_do_not_share_one_diff(self):
        await enable(self.history, "invite_use")
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("aa", 0), invite("bb", 0)]),
            fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))))
        states = iter([[invite("aa", 1), invite("bb", 0)], [invite("aa", 1), invite("bb", 1)]])

        async def fetch(guild):
            await asyncio.sleep(0)
            return next(states)
        await asyncio.gather(self.join(fetch, uid=123456789012345621), self.join(fetch, uid=123456789012345622))
        codes = sorted(row["details"]["code"] for row in self.rows("invite_use"))
        self.assertEqual(codes, ["aa", "bb"])

    async def test_invite_create_and_delete_update_snapshot_and_post(self):
        await enable(self.history, "invite_create", "invite_delete", invite_names={"aa": "Spring"})
        created = NS(guild_id=GUILD_ID, invite=NS(**{**vars(invite("aa", 0, 10)), "created_at": self.now}))
        await transport.record_invite_create(created, self.mongo, NS(cache=None))
        self.assertIn(f"{GUILD_ID}:aa", self.invites.rows)
        (made,) = self.rows("invite_create")
        self.assertEqual((made["details"]["name"], made["details"]["max_uses"]), ("Spring", 10))
        await transport.record_invite_delete(NS(guild_id=GUILD_ID, code="aa", channel_id=1, old_invite=None),
                                             self.mongo, NS(cache=None))
        self.assertNotIn(f"{GUILD_ID}:aa", self.invites.rows)
        (gone,) = self.rows("invite_delete")
        self.assertEqual(gone["details"]["uses"], 0)
        self.assertEqual(self.deliver.await_count, 2)


A = hikari.AuditLogEventType
K = hikari.AuditLogChangeKey
HUMAN, APP, WICK = 999, 998, 997


class BatchTwoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uid = 123456789012345678
        self.history = MemoryCollection()
        self.invites = InviteCollection()
        self.mongo = NS(member_events=self.history, member_invites=self.invites)
        self.patches = [patch.object(transport, "ensure_indexes", new=AsyncMock()),
                        patch.object(transport, "deliver", new=AsyncMock()),
                        patch.object(transport.asyncio, "sleep", new=AsyncMock())]
        self.patches[0].start()
        self.deliver = self.patches[1].start()
        self.patches[2].start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        for state in (transport._bot_users, transport._recent_deletes, transport._recent_bulk,
                      transport._bot_unbans, transport._invite_waits, transport._invite_born,
                      transport._recent_app_adds, transport._delete_counts):
            state.clear()
        users = {HUMAN: NS(is_bot=False), APP: NS(is_bot=True)}
        for key, value in (("pending", False), ("live_max", 0)):
            transport._audit_state[key] = value
        self.addCleanup(transport._audit_state.update, pending=True, live_max=0)
        self.bot = NS(get_me=lambda: NS(id=APP),  # The default ignored bot is this one.
                      cache=NS(get_user=users.get, get_role=lambda r: None, get_guild_channel=lambda c: None,
                               get_thread=lambda c: None, get_guild=lambda g: None,
                               get_member=lambda g, u: None),
                      rest=NS(fetch_user=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")),
                              fetch_member=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b""))))

    def rows(self, kind):
        return [row for row in self.history.rows.values() if row.get("event_type") == kind]

    def entry(self, action, entry_id, *changes, user=HUMAN, target=423456789012345678, options=None, reason=None):
        return NS(guild_id=GUILD_ID, target_id=target, id=entry_id, user_id=user, reason=reason,
                  action_type=action, created_at=datetime.now(timezone.utc), changes=list(changes), options=options)

    async def audit(self, *args, **kwargs):
        await transport.audited(NS(entry=self.entry(*args, **kwargs)), self.mongo, self.bot)

    async def test_audit_kinds_post_once_skip_apps_and_replays(self):
        name = lambda old, new: NS(key=K.NAME, old_value=old, new_value=new)
        cases = [
            (A.ROLE_CREATE, "role_create", [name(None, "Raiders")], "Raiders"),
            (A.ROLE_UPDATE, "role_update", [name("Raiders", "Raid leads")], "Raid leads"),
            (A.ROLE_DELETE, "role_delete", [name("Raiders", None)], "Raiders"),
            (A.CHANNEL_CREATE, "channel_create", [name(None, "general")], "general"),
            (A.CHANNEL_UPDATE, "channel_update", [name("old", "general")], "general"),
            (A.CHANNEL_DELETE, "channel_delete", [name("general", None)], "general"),
            (A.THREAD_DELETE, "thread_delete", [name("plans", None)], "plans"),
            (A.GUILD_UPDATE, "server_update", [name("Old", "Warriors United")], "Warriors United"),
            (A.EMOJI_CREATE, "emoji", [name(None, "wu")], "wu"),
            (A.STICKER_UPDATE, "sticker", [name("a", "b")], "b"),
            (A.WEBHOOK_DELETE, "webhook", [name("Hook", None)], "Hook"),
            (A.AUTO_MODERATION_RULE_CREATE, "automod", [name(None, "No invites")], "No invites"),
            (A.INTEGRATION_UPDATE, "app", [name("Bot", "Bot 2")], "Bot 2"),
            (A.CHANNEL_OVERWRITE_UPDATE, "channel_permissions", [], ""),
        ]
        await enable(self.history, *(case[1] for case in cases))
        for index, (action, kind, changes, shown) in enumerate(cases):
            with self.subTest(kind=kind):
                options = NS(id=555555555555555555, type=hikari.PermissionOverwriteType.ROLE, role_name="Mods")
                await self.audit(action, 1000 + index, *changes, options=options)
                await self.audit(action, 1000 + index, *changes, options=options)  # Gateway replay.
                (row,) = self.rows(kind)
                self.assertEqual((row["display_name"], row["moderator_id"], row["user_id"]), (shown, str(HUMAN), "0"))
                await self.audit(action, 2000 + index, *changes, user=APP, options=options)  # App-made: skipped.
                self.assertEqual(len(self.rows(kind)), 1)
        self.assertEqual(self.deliver.await_count, len(cases))
        perm = self.rows("channel_permissions")[0]["details"]
        self.assertEqual((perm["subject_type"], perm["subject_name"], perm["action"]), ("role", "Mods", "changed"))
        updated = self.rows("role_update")[0]["details"]
        self.assertEqual(updated["changes"], [{"field": "name", "before": "Raiders", "after": "Raid leads"}])

    async def test_disabled_kind_does_no_work_and_unknown_actor_counts_as_human(self):
        await enable(self.history, "role_create", "emoji", ignored_bot_ids=["776"])
        await self.audit(A.CHANNEL_CREATE, 1, NS(key=K.NAME, old_value=None, new_value="x"))  # Not enabled.
        self.assertEqual(self.rows("channel_create"), [])
        self.bot.rest.fetch_user.assert_not_awaited()
        await self.audit(A.ROLE_CREATE, 2, NS(key=K.NAME, old_value=None, new_value="Raiders"), user=777)
        self.assertEqual(len(self.rows("role_create")), 1)  # Lookup failed: treated as human.
        app = AsyncMock(return_value=NS(is_bot=True))
        self.bot.rest.fetch_user = app
        for entry_id in (3, 4):
            await self.audit(A.EMOJI_CREATE, entry_id, NS(key=K.NAME, old_value=None, new_value="wu"), user=776)
        self.assertEqual(self.rows("emoji"), [])
        app.assert_awaited_once()  # One fetch, then cached in process.

    async def test_position_only_updates_and_non_lock_thread_updates_are_skipped(self):
        await enable(self.history, "role_update", "channel_update", "thread_lock")
        move = NS(key=K.POSITION, old_value=1, new_value=2)
        await self.audit(A.ROLE_UPDATE, 1, move)
        await self.audit(A.CHANNEL_UPDATE, 2, move)
        await self.audit(A.ROLE_UPDATE, 3)
        self.assertEqual((self.rows("role_update"), self.rows("channel_update")), ([], []))
        await self.audit(A.ROLE_UPDATE, 4, move, NS(key=K.HOIST, old_value=False, new_value=True))
        self.assertEqual(self.rows("role_update")[0]["details"]["changes"],
                         [{"field": "hoist", "before": "No", "after": "Yes"}])
        await self.audit(A.THREAD_UPDATE, 5, NS(key=K.ARCHIVED, old_value=True, new_value=False))  # Reopened.
        await self.audit(A.THREAD_UPDATE, 6, NS(key=K.NAME, old_value="a", new_value="b"))
        await self.audit(A.THREAD_UPDATE, 7, NS(key=K.ARCHIVED, old_value=False, new_value=True), user=APP)
        self.assertEqual(self.rows("thread_lock"), [])
        await self.audit(A.THREAD_UPDATE, 8, NS(key=K.LOCKED, old_value=False, new_value=True))
        await self.audit(A.THREAD_UPDATE, 9, NS(key=K.ARCHIVED, old_value=False, new_value=True))
        self.assertEqual(sorted(row["details"]["action"] for row in self.rows("thread_lock")),
                         ["archived", "locked"])

    async def test_app_add_always_posts_even_when_the_actor_is_an_app(self):
        await enable(self.history, "app")
        await self.audit(A.BOT_ADD, 1, user=APP)
        await self.audit(A.INTEGRATION_CREATE, 2, NS(key=K.NAME, old_value=None, new_value="Tool"), user=APP)
        await self.audit(A.INTEGRATION_DELETE, 3, NS(key=K.NAME, old_value="Tool", new_value=None), user=APP)
        self.assertEqual([row["details"]["action"] for row in self.rows("app")], ["added"])  # One card per app.

    async def test_bot_add_and_integration_create_for_one_app_post_one_card(self):
        await enable(self.history, "app")
        name = NS(key=K.NAME, old_value=None, new_value="Tool")
        await self.audit(A.INTEGRATION_CREATE, 1, name, target=555, user=APP)
        await self.audit(A.BOT_ADD, 2, target=555, user=APP)
        self.assertEqual(len(self.rows("app")), 1)
        await self.audit(A.BOT_ADD, 3, target=556, user=APP)  # A different app still posts.
        await self.audit(A.INTEGRATION_DELETE, 4, NS(key=K.NAME, old_value="Tool", new_value=None), target=555)
        self.assertEqual(sorted(r["details"]["action"] for r in self.rows("app")), ["added", "added", "removed"])

    async def test_bot_add_pairs_with_integration_create_by_application_id(self):
        await enable(self.history, "app")
        app = lambda value: NS(key=K.APPLICATION_ID, old_value=None, new_value=value)
        await self.audit(A.BOT_ADD, 1, target=555, user=APP)
        await self.audit(A.INTEGRATION_CREATE, 2, app(999), target=999, user=APP)  # Other app: posts.
        await self.audit(A.INTEGRATION_CREATE, 3, app(555), target=888, user=APP)  # Integration id differs.
        self.assertEqual(len(self.rows("app")), 2)

    async def test_bot_add_pairs_with_integration_create_without_an_id_only_when_alone(self):
        await enable(self.history, "app")
        await self.audit(A.BOT_ADD, 1, target=555, user=APP)
        await self.audit(A.BOT_ADD, 2, target=556, user=APP)
        await self.audit(A.INTEGRATION_CREATE, 3, target=888, user=APP)  # Two candidates: unsure, posts.
        self.assertEqual(len(self.rows("app")), 3)
        transport._recent_app_adds.clear()
        await self.audit(A.BOT_ADD, 4, target=557, user=APP)
        await self.audit(A.INTEGRATION_CREATE, 5, target=889, user=APP)  # Lone BOT_ADD: same app.
        self.assertEqual(len(self.rows("app")), 4)

    async def test_delete_audit_fact_attributes_at_most_one_delete(self):
        await enable(self.history, "message_delete")
        channel = 777777777777777777
        event = lambda old: NS(guild_id=GUILD_ID, channel_id=channel, message_id=old.id, old_message=old)
        transport.note_message_audit(self.entry(A.MESSAGE_DELETE, 70, target=self.uid,
                                                options=NS(channel_id=channel)))
        await transport.record_message_delete(event(self.message(6)), self.mongo, self.bot)
        await transport.record_message_delete(event(self.message(8)), self.mongo, self.bot)  # Self-delete.
        moderators = {r["details"]["message_id"]: r["moderator_id"] for r in self.rows("message_delete")}
        self.assertEqual(moderators, {"6": str(HUMAN), "8": None})

    async def test_delete_audit_count_allows_that_many_attributions(self):
        await enable(self.history, "message_delete")
        channel = 777777777777777777
        event = lambda old: NS(guild_id=GUILD_ID, channel_id=channel, message_id=old.id, old_message=old)
        transport.note_message_audit(self.entry(A.MESSAGE_DELETE, 71, target=self.uid,
                                                options=NS(channel_id=channel, count=2)))
        for mid in (6, 7, 8):
            await transport.record_message_delete(event(self.message(mid)), self.mongo, self.bot)
        moderators = {r["details"]["message_id"]: r["moderator_id"] for r in self.rows("message_delete")}
        self.assertEqual(moderators, {"6": str(HUMAN), "7": str(HUMAN), "8": None})

    async def test_running_audit_count_attributes_only_new_deletes(self):
        await enable(self.history, "message_delete")
        channel = 777777777777777777
        event = lambda old: NS(guild_id=GUILD_ID, channel_id=channel, message_id=old.id, old_message=old)
        for count in (1, 2, 2):  # Discord updates one entry with a running total.
            transport.note_message_audit(self.entry(A.MESSAGE_DELETE, 73, target=self.uid,
                                                    options=NS(channel_id=channel, count=count)))
        for mid in (6, 7, 8):
            await transport.record_message_delete(event(self.message(mid)), self.mongo, self.bot)
        moderators = {r["details"]["message_id"]: r["moderator_id"] for r in self.rows("message_delete")}
        self.assertEqual(moderators, {"6": str(HUMAN), "7": str(HUMAN), "8": None})

    async def test_roles_added_and_removed_use_names_skip_apps_and_keep_history_when_off(self):
        added = NS(key=K.ADD_ROLE_TO_MEMBER, old_value=None, new_value={1: NS(name="CWL player"), 2: NS(name="Member")})
        removed = NS(key=K.REMOVE_ROLE_FROM_MEMBER, old_value=None, new_value={3: NS(name="Recruit")})
        await self.audit(A.MEMBER_ROLE_UPDATE, 1, added, removed, target=self.uid)
        self.assertEqual(self.rows("roles_added")[0]["details"]["roles"], ["CWL player", "Member"])
        self.assertEqual(self.rows("roles_removed")[0]["details"]["roles"], ["Recruit"])
        self.assertEqual(self.rows("roles_added")[0]["delivery_status"], "skipped")  # Off, but in history.
        self.assertEqual(self.rows("roles_added")[0]["moderator_id"], str(HUMAN))
        self.deliver.assert_not_awaited()
        await self.audit(A.MEMBER_ROLE_UPDATE, 2, added, target=self.uid, user=APP)
        self.assertEqual(len(self.rows("roles_added")), 1)
        await self.audit(A.MEMBER_ROLE_UPDATE, 1, added, removed, target=self.uid)  # Replay.
        self.assertEqual((len(self.rows("roles_added")), len(self.rows("roles_removed"))), (1, 1))

    def add_bot(self, user_id, name="Wick"):
        users = self.bot.cache.get_user.__self__  # The dict behind users.get.
        users[user_id] = NS(is_bot=True, username=name.lower(), global_name=name)

    async def test_only_listed_bots_are_skipped_and_every_bot_actor_is_remembered(self):
        self.add_bot(WICK)
        role = NS(key=K.NAME, old_value=None, new_value="Raiders")
        await enable(self.history, "role_create")  # Never saved a list: default = this bot (APP).
        await self.audit(A.ROLE_CREATE, 1, role, user=APP)
        await self.audit(A.ROLE_CREATE, 2, role, user=WICK)  # Wick-like bot is logged.
        await self.audit(A.ROLE_CREATE, 3, role, user=HUMAN)
        self.assertEqual([r["moderator_id"] for r in sorted(self.rows("role_create"), key=lambda r: r["_id"])],
                         [str(WICK), str(HUMAN)])
        actors = await MemberEventStore(self.history).bot_actors()
        self.assertEqual({k: v["name"] for k, v in actors.items()}, {str(APP): str(APP), str(WICK): "Wick"})
        self.assertNotIn("ignored_bot_ids", self.history.rows["member-events-settings:%d" % GUILD_ID])
        # A saved list is used as is: Wick ignored, the own bot (not listed) is logged.
        await MemberEventStore(self.history).save_settings(1, {
            **await MemberEventStore(self.history).settings(), "ignored_bot_ids": [str(WICK)]})
        await self.audit(A.ROLE_CREATE, 4, role, user=WICK)
        await self.audit(A.ROLE_CREATE, 5, role, user=APP)
        self.assertEqual(sorted(r["audit_entry_id"] for r in self.rows("role_create")), ["2", "3", "5"])

    async def test_saved_empty_list_logs_the_own_bot_and_unknown_own_id_ignores_nobody(self):
        role = NS(key=K.NAME, old_value=None, new_value="Raiders")
        await enable(self.history, "role_create", ignored_bot_ids=[])
        await self.audit(A.ROLE_CREATE, 1, role, user=APP)
        self.assertEqual(len(self.rows("role_create")), 1)
        self.history.rows.clear()
        await enable(self.history, "role_create")  # Field missing, but own id cannot be read.
        self.bot.get_me = lambda: None
        self.bot.rest.fetch_my_user = AsyncMock(side_effect=RuntimeError("down"))
        await self.audit(A.ROLE_CREATE, 2, role, user=APP)
        self.assertEqual(len(self.rows("role_create")), 1)

    async def test_other_audit_paths_use_the_ignored_list_too(self):
        self.add_bot(WICK)
        added = NS(key=K.ADD_ROLE_TO_MEMBER, old_value=None, new_value={1: NS(name="Member")})
        await enable(self.history, "roles_added", "unban", ignored_bot_ids=[str(WICK)])
        await self.audit(A.MEMBER_ROLE_UPDATE, 1, added, target=self.uid, user=WICK)
        await self.audit(A.MEMBER_ROLE_UPDATE, 2, added, target=self.uid, user=APP)
        self.assertEqual([r["moderator_id"] for r in self.rows("roles_added")], [str(APP)])
        await self.audit(A.MEMBER_BAN_REMOVE, 3, target=self.uid, user=WICK)
        self.assertEqual(self.rows("unban"), [])

    async def test_live_audit_entries_advance_the_cursor_forward_only(self):
        await enable(self.history, "role_create")
        role = NS(key=K.NAME, old_value=None, new_value="Raiders")
        store = MemberEventStore(self.history)
        await self.audit(A.ROLE_CREATE, 1000, role)
        await self.audit(A.ROLE_CREATE, 900, role)
        self.assertEqual(await store.audit_cursor(), 1000)
        await self.audit(A.CHANNEL_CREATE, 1001, role)  # Disabled kind: handled, cursor still moves.
        self.assertEqual(await store.audit_cursor(), 1001)
        transport._audit_state["pending"] = True  # Before recovery has read the cursor.
        await self.audit(A.ROLE_CREATE, 1500, role)
        self.assertEqual((await store.audit_cursor(), transport._audit_state["live_max"]), (1001, 1500))

    def audit_log(self, *entries, error=None):
        async def pages(guild, **kwargs):
            if error:
                raise error
            for chunk in (entries[i:i + 100] for i in range(0, len(entries), 100)):
                yield NS(entries={e.id: e for e in chunk})
        self.bot.rest.fetch_audit_log = pages

    async def recover(self):
        transport._audit_state.update(pending=True, live_max=0)
        await transport.recover_audit(self.mongo, self.bot)

    async def test_recovery_replays_missed_entries_oldest_first_marked_recovered(self):
        await enable(self.history, "role_create")
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(1000)
        role = lambda i: self.entry(A.ROLE_CREATE, i, NS(key=K.NAME, old_value=None, new_value=f"r{i}"))
        self.audit_log(role(1003), role(1002), role(1001), role(1000), role(999))  # Newest first, like Discord.
        await self.recover()
        order = [call.args[2]["audit_entry_id"] for call in self.deliver.await_args_list]
        self.assertEqual(order, ["1001", "1002", "1003"])
        self.assertTrue(all(r["details"]["recovered"] for r in self.rows("role_create")))
        self.assertEqual(await store.audit_cursor(), 1003)
        self.assertFalse(transport._audit_state["pending"])

    async def test_recovery_caps_at_24_hours_and_500_entries(self):
        await enable(self.history, "role_create")
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(1)
        role = lambda i, age=0: NS(**{**vars(self.entry(A.ROLE_CREATE, i, NS(key=K.NAME, old_value=None, new_value="r"))),
                                      "created_at": datetime.now(timezone.utc) - timedelta(hours=age)})
        self.audit_log(role(30), role(29), role(28, age=25), role(27, age=26))
        await self.recover()
        self.assertEqual(sorted(r["audit_entry_id"] for r in self.rows("role_create")), ["29", "30"])
        self.history.rows.clear()
        await enable(self.history, "role_create")
        await store.advance_audit_cursor(1)
        self.audit_log(*[role(5000 - i) for i in range(600)])
        await self.recover()
        ids = sorted(int(r["audit_entry_id"]) for r in self.rows("role_create"))
        self.assertEqual((len(ids), ids[0], ids[-1]), (500, 4501, 5000))  # The newest 500.

    async def test_recovery_never_posts_an_entry_the_live_handler_already_posted(self):
        await enable(self.history, "role_create")
        store = MemberEventStore(self.history)
        entry = self.entry(A.ROLE_CREATE, 1001, NS(key=K.NAME, old_value=None, new_value="Raiders"))
        await transport.audited(NS(entry=entry), self.mongo, self.bot)
        self.assertEqual(self.deliver.await_count, 1)
        self.history.rows.pop("member-events-audit-cursor:%d" % GUILD_ID)
        await store.advance_audit_cursor(1000)  # Cursor behind the live entry (for example, a restart).
        self.audit_log(entry)
        await self.recover()
        self.assertEqual((len(self.rows("role_create")), self.deliver.await_count), (1, 1))
        self.assertNotIn("recovered", self.rows("role_create")[0]["details"])

    async def test_recovery_forbidden_logs_one_warning_and_never_raises(self):
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(1000)
        self.audit_log(error=hikari.ForbiddenError("u", {}, b""))
        with self.assertLogs(transport.log, "WARNING") as logs:
            await self.recover()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(await store.audit_cursor(), 1000)
        self.assertFalse(transport._audit_state["pending"])  # Live entries move the cursor again.
        await enable(self.history, "role_create")
        await self.audit(A.ROLE_CREATE, 1200, NS(key=K.NAME, old_value=None, new_value="r"))
        self.assertEqual(await store.audit_cursor(), 1200)  # The gap before it stays unrecovered.

    async def test_failed_recovery_keeps_entries_handled_live_during_the_hold(self):
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(1000)
        await enable(self.history, "role_create")
        transport._audit_state.update(pending=True, live_max=0)
        await self.audit(A.ROLE_CREATE, 1500, NS(key=K.NAME, old_value=None, new_value="r"))
        self.assertEqual(await store.audit_cursor(), 1000)  # Held while recovery has not read it.
        self.audit_log(error=hikari.ForbiddenError("u", {}, b""))
        with self.assertLogs(transport.log, "WARNING"):
            await transport.recover_audit(self.mongo, self.bot)
        self.assertEqual(await store.audit_cursor(), 1500)

    async def test_replayed_unban_with_a_handled_audit_id_posts_nothing_and_keeps_ban_state(self):
        await enable(self.history, "unban", "ban")
        store = MemberEventStore(self.history)
        self.assertEqual(await store.ban_episode(GUILD_ID, self.uid, banned=True), 1)
        await self.audit(A.MEMBER_BAN_REMOVE, 200, target=self.uid)  # Live unban of episode 1.
        self.assertEqual(await store.ban_episode(GUILD_ID, self.uid, banned=True), 2)  # Banned again.
        self.history.rows.pop("member-events-audit-cursor:%d" % GUILD_ID, None)
        await store.advance_audit_cursor(150)  # Cursor behind, as after a failed recovery.
        self.audit_log(self.entry(A.MEMBER_BAN_REMOVE, 200, target=self.uid))
        await self.recover()
        (row,) = self.rows("unban")
        self.assertEqual((row["audit_entry_id"], self.deliver.await_count), ("200", 1))
        state = self.history.rows["ban-state:%d:%d" % (GUILD_ID, self.uid)]
        self.assertEqual((state["banned"], state["sequence"]), (True, 2))
        await self.audit(A.MEMBER_BAN_REMOVE, 200, target=self.uid)  # A live duplicate is skipped too.
        self.assertEqual((len(self.rows("unban")), self.deliver.await_count), (1, 1))
        self.assertTrue(self.history.rows["ban-state:%d:%d" % (GUILD_ID, self.uid)]["banned"])
        self.assertEqual(await store.audit_cursor(), 200)

    async def test_replay_skips_every_kind_of_entry_that_already_has_a_row(self):
        await enable(self.history, "role_create", "roles_added", "timeout_add")
        role = NS(key=K.NAME, old_value=None, new_value="Raiders")
        added = NS(key=K.ADD_ROLE_TO_MEMBER, old_value=None, new_value={1: NS(name="Member")})
        until = datetime.now(timezone.utc) + timedelta(hours=1)
        timeout = NS(key=hikari.AuditLogChangeKey.COMMUNICATION_DISABLED_UNTIL, old_value=None, new_value=until)
        entries = [self.entry(A.ROLE_CREATE, 301, role),
                   self.entry(A.MEMBER_ROLE_UPDATE, 302, added, target=self.uid),
                   self.entry(A.MEMBER_UPDATE, 303, timeout, target=self.uid)]
        for entry in entries:
            await transport.audited(NS(entry=entry), self.mongo, self.bot)
        before = (len(self.history.rows), self.deliver.await_count)
        for entry in entries:
            self.assertTrue(await transport.handle_audit_entry(entry, self.mongo, self.bot, recovered=True))
        self.assertEqual((len(self.history.rows), self.deliver.await_count), before)

    async def test_audit_cursor_advance_is_numeric_monotonic_and_race_safe(self):
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(9)
        await store.advance_audit_cursor(10)  # "10" < "9" as text; must still move.
        self.assertEqual(await store.audit_cursor(), 10)
        await store.advance_audit_cursor(9)
        self.assertEqual(await store.audit_cursor(), 10)
        real = self.history.update_one
        async def yielding(*args, **kwargs):
            turn = asyncio.get_running_loop().create_future()  # sleep is mocked here; yield by hand.
            asyncio.get_running_loop().call_soon(turn.set_result, None)
            await turn  # Let the other advances interleave.
            return await real(*args, **kwargs)
        self.history.update_one = yielding
        await asyncio.gather(*(store.advance_audit_cursor(n) for n in (500, 120, 90000, 3, 70000, 1000)))
        self.assertEqual(await store.audit_cursor(), 90000)

    async def test_audit_cursor_adopts_an_older_string_only_document(self):
        self.history.rows["member-events-audit-cursor:%d" % GUILD_ID] = {
            "_id": "member-events-audit-cursor:%d" % GUILD_ID, "last_audit_id": "900"}
        store = MemberEventStore(self.history)
        self.assertEqual(await store.audit_cursor(), 900)
        await store.advance_audit_cursor(80)
        self.assertEqual(await store.audit_cursor(), 900)
        await store.advance_audit_cursor(1200)
        self.assertEqual(await store.audit_cursor(), 1200)

    async def test_app_add_pairing_holds_across_a_restart_in_either_order(self):
        await enable(self.history, "app")
        app = lambda value: NS(key=K.APPLICATION_ID, old_value=None, new_value=value)
        await self.audit(A.INTEGRATION_CREATE, 402, app(555), target=888, user=APP)  # Live, newer entry.
        self.assertEqual(len(self.rows("app")), 1)
        self.assertEqual(self.rows("app")[0]["details"]["application_id"], "555")
        transport._recent_app_adds.clear()  # Restart: memory is gone.
        store = MemberEventStore(self.history)
        await store.advance_audit_cursor(400)
        self.audit_log(self.entry(A.INTEGRATION_CREATE, 402, app(555), target=888, user=APP),
                       self.entry(A.BOT_ADD, 401, target=555, user=APP))  # Newest first.
        await self.recover()
        self.assertEqual((len(self.rows("app")), self.deliver.await_count), (1, 1))
        transport._recent_app_adds.clear()
        await self.audit(A.BOT_ADD, 403, target=777, user=APP)  # A different app still posts.
        self.assertEqual(len(self.rows("app")), 2)

    async def test_first_run_sets_the_cursor_to_the_newest_entry_and_recovers_nothing(self):
        await enable(self.history, "role_create")
        role = lambda i: self.entry(A.ROLE_CREATE, i, NS(key=K.NAME, old_value=None, new_value="r"))
        self.audit_log(role(77), role(76))
        await self.recover()
        self.assertEqual(await MemberEventStore(self.history).audit_cursor(), 77)
        self.assertEqual(self.rows("role_create"), [])
        self.deliver.assert_not_awaited()

    async def test_started_hook_runs_recovery_in_the_background_after_the_snapshot(self):
        order = []
        async def snapshot(mongo, bot): order.append("snapshot")
        async def recovery(mongo, bot):
            order.append("recovery")
        with patch.object(transport, "refresh_invites", new=snapshot), \
             patch.object(transport, "recover_audit", new=recovery):
            await transport.invites_started(NS(), self.mongo, self.bot)
            self.assertEqual(order, ["snapshot"])  # Recovery is a task, not awaited.
            await transport._audit_task
        self.assertEqual(order, ["snapshot", "recovery"])

    def unban_event(self):
        return NS(guild_id=GUILD_ID, user=NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None))

    async def test_unban_enriched_by_audit_in_either_order_and_once(self):
        await enable(self.history, "unban")
        audit = self.entry(A.MEMBER_BAN_REMOVE, 50, target=self.uid, reason="appealed")

        async def during_hold(seconds):
            if seconds == 1 and self.rows("unban") and not self.rows("unban")[0].get("moderator_id"):
                await transport.audited(NS(entry=audit), self.mongo, self.bot)
        transport.asyncio.sleep.side_effect = during_hold
        await transport.unbanned(self.unban_event(), self.mongo, self.bot)  # Gateway first, audit during the hold.
        (row,) = self.rows("unban")
        self.assertEqual((row["moderator_id"], row["reason"], row["audit_entry_id"]), (str(HUMAN), "appealed", "50"))
        self.assertEqual(self.deliver.await_count, 1)
        await transport.audited(NS(entry=audit), self.mongo, self.bot)  # Replay.
        self.assertEqual((len(self.rows("unban")), self.deliver.await_count), (1, 1))
        # A second ban cycle: audit first, then the gateway event is a duplicate.
        transport.asyncio.sleep.side_effect = None
        await MemberEventStore(self.history).ban_episode(GUILD_ID, self.uid, banned=True)
        await transport.audited(NS(entry=self.entry(A.MEMBER_BAN_REMOVE, 51, target=self.uid, reason="again")),
                                self.mongo, self.bot)
        await transport.unbanned(self.unban_event(), self.mongo, self.bot)
        self.assertEqual([r["reason"] for r in sorted(self.rows("unban"), key=lambda r: r["_id"])],
                         ["appealed", "again"])
        self.assertEqual(self.deliver.await_count, 2)

    async def test_unban_made_by_an_app_is_dropped_in_both_orders(self):
        audit = lambda entry_id: NS(entry=self.entry(A.MEMBER_BAN_REMOVE, entry_id, target=self.uid, user=APP))

        async def during_hold(seconds):
            if self.rows("unban"):
                await transport.audited(audit(60), self.mongo, self.bot)
        transport.asyncio.sleep.side_effect = during_hold
        await transport.unbanned(self.unban_event(), self.mongo, self.bot)
        self.assertEqual(self.rows("unban"), [])
        transport.asyncio.sleep.side_effect = None
        await MemberEventStore(self.history).ban_episode(GUILD_ID, self.uid, banned=True)
        await transport.audited(audit(61), self.mongo, self.bot)
        await transport.unbanned(self.unban_event(), self.mongo, self.bot)
        self.assertEqual(self.rows("unban"), [])
        self.deliver.assert_not_awaited()

    def message(self, mid=1, content="hello", is_bot=False, roles=(), webhook=None, attachments=()):
        author = NS(id=self.uid, username="alice", global_name="Alice", avatar_hash=None, is_bot=is_bot)
        member = NS(display_name="Alice", role_ids=list(roles), joined_at=None, guild_avatar_hash=None)
        return NS(id=mid, author=author, member=member, content=content, webhook_id=webhook,
                  attachments=list(attachments), channel_id=777777777777777777, created_at=datetime.now(timezone.utc))

    async def test_message_delete_needs_cache_skips_apps_honours_ignores_and_finds_moderator(self):
        await enable(self.history, "message_delete", ignores={"channel_ids": ["333333333333333333"],
                                                              "role_ids": ["444444444444444444"]})
        file = NS(filename="screenshot.png", media_type="image/png")

        def event(old, channel=777777777777777777):
            return NS(guild_id=GUILD_ID, channel_id=channel, message_id=1, old_message=old)
        for case in (event(None), event(self.message(is_bot=True)), event(self.message(webhook=1)),
                     event(self.message(), channel=333333333333333333),
                     event(self.message(roles=[444444444444444444]))):
            await transport.record_message_delete(case, self.mongo, self.bot)
        self.assertEqual(self.rows("message_delete"), [])
        await transport.record_message_delete(event(self.message(5, attachments=[file])), self.mongo, self.bot)
        self.assertIsNone(self.rows("message_delete")[0]["moderator_id"])  # Self-delete: no audit entry.
        transport.note_message_audit(self.entry(A.MESSAGE_DELETE, 70, target=self.uid,
                                                options=NS(channel_id=777777777777777777)))
        message = self.message(6, content="spam " * 200, attachments=[file])
        await transport.record_message_delete(event(message), self.mongo, self.bot)
        await transport.record_message_delete(event(message), self.mongo, self.bot)  # Replay.
        row = next(r for r in self.rows("message_delete") if r["details"]["message_id"] == "6")
        self.assertEqual(len(self.rows("message_delete")), 2)
        self.assertEqual(row["moderator_id"], str(HUMAN))
        self.assertEqual(len(row["details"]["content"]), 500)
        self.assertEqual(row["details"]["attachments"], [{"name": "screenshot.png", "type": "image/png"}])
        self.assertEqual(self.deliver.await_count, 2)
        transport._recent_deletes.clear()
        transport.note_message_audit(self.entry(A.MESSAGE_DELETE, 72, target=self.uid,
                                                options=NS(channel_id=111111111111111111)))  # Other channel.
        await transport.record_message_delete(event(self.message(7)), self.mongo, self.bot)
        self.assertIsNone(next(r for r in self.rows("message_delete") if r["details"]["message_id"] == "7")["moderator_id"])

    async def test_message_edit_posts_only_real_content_changes_by_humans(self):
        await enable(self.history, "message_edit", ignores={"channel_ids": [], "role_ids": ["444444444444444444"]})

        def event(old, content):
            return NS(guild_id=GUILD_ID, channel_id=777777777777777777, old_message=old, content=content,
                      member=None)
        for case in (event(None, "x"), event(self.message(), hikari.UNDEFINED), event(self.message(content="a"), "a"),
                     event(self.message(is_bot=True), "b"), event(self.message(webhook=1), "b"),
                     event(self.message(roles=[444444444444444444]), "b")):
            await transport.record_message_edit(case, self.mongo, self.bot)
        self.assertEqual(self.rows("message_edit"), [])
        edit = event(self.message(9, content="before"), "after " + "x" * 600)
        await transport.record_message_edit(edit, self.mongo, self.bot)
        await transport.record_message_edit(edit, self.mongo, self.bot)  # Replay.
        (row,) = self.rows("message_edit")
        self.assertEqual((row["details"]["before"], len(row["details"]["after"]), row["details"]["message_id"]),
                         ("before", 500, "9"))
        await transport.record_message_edit(event(self.message(9, content="after"), "after again"), self.mongo, self.bot)
        self.assertEqual(len(self.rows("message_edit")), 2)

    async def test_bulk_delete_has_count_moderator_and_a_capped_human_transcript(self):
        await enable(self.history, "message_bulk_delete", ignores={"channel_ids": ["333333333333333333"], "role_ids": []})
        cached = {m.id: m for m in (self.message(11, "first"), self.message(12, "from app", is_bot=True),
                                    self.message(10, "zeroth\nline two"))}
        event = NS(guild_id=GUILD_ID, channel_id=777777777777777777, message_ids=[10, 11, 12, 13], old_messages=cached)
        transport.note_message_audit(self.entry(A.MESSAGE_BULK_DELETE, 80, target=777777777777777777))
        await transport.record_bulk_delete(event, self.mongo, self.bot)
        await transport.record_bulk_delete(event, self.mongo, self.bot)  # Replay.
        (row,) = self.rows("message_bulk_delete")
        self.assertEqual((row["details"]["count"], row["moderator_id"]), (4, str(HUMAN)))
        lines = row["details"]["transcript"].split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("zeroth / line two", lines[0])
        self.assertNotIn("from app", row["details"]["transcript"])
        big = {i: self.message(i, "y" * 5000) for i in range(100, 160)}
        text = transport.build_transcript(big.values())
        self.assertLessEqual(len(text.encode()), 200 * 1024)
        self.assertTrue(text.endswith("[transcript truncated]"))
        ignored = NS(**{**vars(event), "channel_id": 333333333333333333})
        await transport.record_bulk_delete(ignored, self.mongo, self.bot)
        empty = NS(guild_id=GUILD_ID, channel_id=777777777777777777, message_ids=[20, 21], old_messages={})
        await transport.record_bulk_delete(empty, self.mongo, self.bot)
        self.assertEqual(len(self.rows("message_bulk_delete")), 2)
        self.assertNotIn("transcript", self.rows("message_bulk_delete")[-1]["details"])  # Uncached: count only.

    async def test_transcript_with_marker_never_exceeds_the_cap_at_the_boundary(self):
        empty = len(transport.build_transcript([self.message(100, "")]).encode())
        for width in sorted({*range(4990, 5011), *range(5115 - empty, 5125 - empty)}):  # 5119 - empty is the old cap's edge.
            with self.subTest(width=width):
                text = transport.build_transcript(self.message(i, "y" * width) for i in range(100, 160))
                self.assertLessEqual(len(text.encode()), transport.TRANSCRIPT_LIMIT)
                self.assertTrue(text.endswith("[transcript truncated]"))
        one = len(transport.build_transcript([self.message(1, "y" * 100)]).encode()) + 1
        fits = transport.build_transcript(self.message(i, "y" * 100) for i in range(1, 100))
        self.assertEqual(len(fits.encode()), 99 * one - 1)  # Under the cap: untouched.
        self.assertNotIn("truncated", fits)

    async def test_rejoin_does_not_read_the_previous_joins_invite_future(self):
        loop = asyncio.get_running_loop()
        future = transport._invite_future(self.uid)
        future.set_result("Old")
        transport._invite_born[self.uid] = loop.time() - 60  # Left over from an earlier join.
        transport.discard_stale_invite(self.uid)
        self.assertNotIn(self.uid, transport._invite_waits)
        fresh = transport._invite_future(self.uid)
        fresh.set_result("New")  # This join's own label arrived first: kept.
        transport.discard_stale_invite(self.uid)
        self.assertIs(transport._invite_waits[self.uid], fresh)
        transport._invite_waits.pop(self.uid)
        stale = transport._invite_future(self.uid)
        stale.set_result("Old")
        transport._invite_born[self.uid] = loop.time() - 60
        await enable(self.history, "join")
        transport.asyncio.sleep.side_effect = None
        await self.join(self.uid)
        (row,) = self.rows("join")
        self.assertNotIn("invite", row["details"])

    async def join(self, uid, *, with_invite=None):
        user = NS(id=uid, username=f"user{uid % 100}", global_name=None, avatar_hash=None)
        member = NS(guild_id=GUILD_ID, user=user, display_name="Newbie", joined_at=datetime.now(timezone.utc),
                    guild_avatar_hash=None)
        event = NS(member=member)
        tasks = [transport.record(event, "join", self.mongo, self.bot)]
        if with_invite is not None:
            rest = NS(fetch_guild_invites=AsyncMock(return_value=[invite(with_invite, 2)]),
                      fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))
            tasks.append(transport.record_invite_use(event, self.mongo, NS(cache=None, rest=rest)))
        await asyncio.gather(*tasks)

    def day(self, offset):
        return datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=offset)

    async def test_join_card_gets_rejoin_count_and_invite_label_within_the_wait(self):
        await enable(self.history, "join", "invite_use", invite_names={"aa": "Spring"})
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("aa", 1)]),
            fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))))
        store = MemberEventStore(self.history)
        for index in range(2):
            await store.capture(guild_id=GUILD_ID, user_id=self.uid, kind="join", display_name="N", username="n",
                                avatar=None, avatar_type=None, at=self.day(index), joined_at=self.day(index))
        with patch.object(transport, "INVITE_WAIT_SECONDS", 2):
            await self.join(self.uid, with_invite="aa")
        latest = max(self.rows("join"), key=lambda row: row["_id"])
        self.assertEqual(latest["details"], {"join_count": 3, "invite": "Spring"})
        self.assertEqual(latest["delivery_status"], "queued")

    async def test_join_does_not_hold_other_joins_and_times_out_without_a_label(self):
        await enable(self.history, "join", "invite_use")
        await transport.refresh_invites(self.mongo, NS(cache=None, rest=NS(
            fetch_guild_invites=AsyncMock(return_value=[invite("aa", 1)]),
            fetch_vanity_url=AsyncMock(side_effect=hikari.NotFoundError("u", {}, b"")))))
        finished = []

        async def run(uid, **kwargs):
            await self.join(uid, **kwargs)
            finished.append(uid)
        with patch.object(transport, "INVITE_WAIT_SECONDS", 0.3):
            await asyncio.gather(run(123456789012345601), run(123456789012345602, with_invite="aa"))
        self.assertEqual(finished[0], 123456789012345602)  # Attributed join is not delayed by the other.
        by = {row["user_id"]: row["details"] for row in self.rows("join")}
        self.assertEqual(by["123456789012345601"], {"join_count": 1})  # Timed out: no invite line.
        self.assertEqual(by["123456789012345602"], {"join_count": 1, "invite": "aa"})
        self.assertEqual(transport._invite_waits, {})
        self.assertEqual(transport._invite_born, {})

    async def test_expires_at_is_set_per_kind_and_only_for_those_kinds(self):
        store = MemberEventStore(self.history)
        at = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        days = {"link": 30, "message_delete": 30, "message_edit": 30, "message_bulk_delete": 30,
                "invite_create": 90, "invite_delete": 90, "invite_use": 90}
        for index, kind in enumerate(EVENT_TYPES):
            row = await store.capture(guild_id=GUILD_ID, user_id=1, kind=kind, display_name="n", username="n",
                                      avatar=None, avatar_type=None, at=at, dedupe_key=f"k{index}")
            if kind in days:
                self.assertEqual(row["expires_at"], at + timedelta(days=days[kind]), kind)
            else:
                self.assertNotIn("expires_at", row, kind)
        await store.save_settings(0, await store.settings())
        self.assertNotIn("expires_at", self.history.rows["member-events-settings:%d" % GUILD_ID])
        await store.ensure_indexes()
        self.assertIn((("expires_at",), {"expireAfterSeconds": 0, "name": "member_event_expiry"}),
                      self.history.indexes)

    def test_history_types_and_message_cache_setting(self):
        from pathlib import Path
        from utils.member_events import HISTORY_TYPES
        self.assertEqual(HISTORY_TYPES, ("join", "leave", "kick", "ban", "unban", "timeout_add", "timeout_remove",
                                         "member_update", "roles_added", "roles_removed", "invite_use"))
        self.assertIn("cache_settings=hikari.impl.CacheSettings(max_messages=10000)",
                      (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class CardFitTests(unittest.TestCase):
    TOTAL = {"role_create": 12, "webhook": 12, "channel_permissions": 20}

    def row(self, kind, count):
        changes = [{"field": f"field_{i}", "before": "*" * 100, "after": "_" * 100} for i in range(count)]
        return {**sample_row(kind), "details": {"action": "updated", "target_id": "123456789012345678",
                                                "changes": changes}}

    @staticmethod
    def texts(card):
        found = []
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("content"), str):
                    found.append(node["content"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(card)
        return found

    def check(self, kind, parts):
        total = self.TOTAL[kind]
        shown = sum(1 for part in parts if part.startswith("**Field "))
        hidden = sum(int(part.split()[0][1:]) for part in parts if part.endswith(" more") and part.startswith("+"))
        self.assertEqual(shown + hidden, total)
        for part in parts:
            self.assertNotEqual(part.strip(), "…")
            body = part.rstrip("…")
            self.assertEqual((len(body) - len(body.rstrip("\\"))) % 2, 0, part[-12:])  # No dangling backslash.
        return shown, hidden

    def test_oversized_cards_keep_whole_escapes_and_an_exact_more_count(self):
        for kind, count in self.TOTAL.items():
            with self.subTest(kind=kind):
                row = self.row(kind, count)
                parts = self.texts(build_card(row))
                self.assertLessEqual(sum(map(len, parts)), 3800)
                shown, hidden = self.check(kind, [line for part in parts for line in part.split("\n")
                                                  if line.startswith("+") or line.startswith("**Field ")])
                self.assertGreater(hidden, 0)
                forum = build_forum_message(row)["embeds"][0]["description"]
                self.check(kind, [line for line in forum.split("\n") if line.startswith(("+", "**Field "))])

    def test_cut_never_splits_an_escape(self):
        from utils.member_event_cards import _cut
        text = "ab\\*cd"
        self.assertEqual(_cut(text, 4), "ab…")  # Would end on a lone backslash.
        self.assertEqual(_cut("ab\\\\cd", 5), "ab\\\\…")  # An escaped backslash is whole.
        self.assertEqual(_cut("ab@​cd", 4), "ab…")  # "@" keeps its zero-width space.

    def test_fit_drops_trailing_fields_and_counts_them(self):
        from utils.member_event_cards import _fit
        lines = ["**n**", "title", "main", *("f" * 30 for _ in range(6)), "+2 more", "footer"]
        out = _fit(lines, 140)
        self.assertEqual(out[-1], "footer")
        kept = sum(1 for line in out if line == "f" * 30)
        self.assertLess(kept, 6)
        self.assertEqual(kept + int(out[-2].split()[0][1:]), 8)
