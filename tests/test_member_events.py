"""Member event durability, delivery ambiguity, and staff API boundaries."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiohttp import web
from pymongo.errors import DuplicateKeyError
from aiohttp.test_utils import make_mocked_request

from cwl_web import member_events as api
from extensions.events import member_events as transport
from utils.member_events import GUILD_ID, MemberEventStore, avatar_source, event_key, safe_text


class MemberEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.row = {"_id": "1792972800000:" + "a" * 32, "guild_id": GUILD_ID,
                    "user_id": "123456789012345678", "event_type": "join",
                    "display_name": "Alice", "username": "alice",
                    "occurred_at": self.now, "avatar": None, "avatar_type": None,
                    "delivery_status": "queued"}

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
        card, attachments = transport.components({**self.row, "display_name": "<@123> @everyone"})
        built = card[0].build()[0]
        self.assertEqual(built["accent_color"], 0x2BA66A)
        self.assertEqual(attachments, [])
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
            card, _ = transport.components(row)
            text = json.dumps(card[0].build()[0])
            stamp = int(occurred.replace(tzinfo=timezone.utc).timestamp())
            joined_stamp = int(joined.replace(tzinfo=timezone.utc).timestamp())
            self.assertIn(f"<t:{stamp}:R>", text)
            self.assertIn(f"Joined server: <t:{joined_stamp}:D>", text)
            self.assertIn(f"<t:{joined_stamp}:R>", text)
            aware, _ = transport.components({**row, "occurred_at": occurred.replace(tzinfo=timezone.utc), "joined_at": joined.replace(tzinfo=timezone.utc)})
            self.assertEqual(card[0].build()[0], aware[0].build()[0])
            unknown, _ = transport.components({**row, "joined_at": None})
            self.assertIn("date unavailable", json.dumps(unknown[0].build()[0]))
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
                   save_avatar=AsyncMock(), ready=AsyncMock(return_value=row))
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
                   save_avatar=AsyncMock(), ready=AsyncMock(return_value=self.row))
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
        store = NS(claim=AsyncMock(), finish=AsyncMock())
        with patch.object(transport, "channel_ready", new=AsyncMock(return_value=False)), \
             patch.object(transport, "post_card", new=AsyncMock()) as post:
            await transport.deliver(store, NS(), self.row)
        store.claim.assert_not_awaited()
        post.assert_not_awaited()

    async def test_ambiguous_post_is_marked_uncertain_and_not_retried(self):
        store = NS(claim=AsyncMock(return_value=self.row), finish=AsyncMock())
        with patch.object(transport, "channel_ready", new=AsyncMock(return_value=True)), \
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
                       "?type=ban", "?limit=101", "?q=" + "x" * 81,
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


if __name__ == "__main__":
    unittest.main()
