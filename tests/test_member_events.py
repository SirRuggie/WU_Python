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
from utils.member_event_cards import build_card
from utils.member_event_settings import normalize_settings
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
                   settings=AsyncMock(return_value=settings()))
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
        self.assertEqual(set(loaded["categories"]), {"members", "moderation", "messages", "invites"})
        self.assertEqual(loaded["categories"]["members"]["mode"], "own")
        self.assertEqual(loaded["ignores"], {"channel_ids": [], "role_ids": []})
        self.assertEqual(loaded["invite_names"], {})
        for kind in ("timeout_add", "timeout_remove", "member_update", "link",
                     "invite_create", "invite_delete", "invite_use"):
            self.assertEqual(loaded["events"][kind], {"enabled": False, "channel_id": None, "forum_tag_id": None})
        saved = await store.save_settings(3, loaded)
        self.assertEqual(saved["revision"], 4)
        self.assertEqual(self.history.rows["member-events-settings:%d" % GUILD_ID]["invite_names"], {})

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


if __name__ == "__main__":
    unittest.main()
