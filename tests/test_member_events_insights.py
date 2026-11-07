"""Member timeline and log health endpoints."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from cwl_web import member_events_insights as api
from utils.member_events import GUILD_ID, MemberEventStore

UID = "123456789012345678"
CHANNEL = "223456789012345678"
AUDIT, MANAGE = 1 << 7, 1 << 5


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row[key], reverse=direction < 0)
        return self
    def limit(self, count):
        self.rows = self.rows[:count]
        return self
    async def to_list(self, length): return [dict(row) for row in self.rows[:length]]


class Collection:
    def __init__(self): self.rows = {}
    @staticmethod
    def matches(row, query):
        for key, expected in query.items():
            value = row.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and value not in expected["$in"]: return False
                if "$lt" in expected and not value < expected["$lt"]: return False
            elif value != expected:
                return False
        return True
    def find(self, query, projection=None):
        return Cursor([row for row in self.rows.values() if self.matches(row, query)])
    async def find_one(self, query, projection=None, *, sort=None):
        rows = [row for row in self.rows.values() if self.matches(row, query)]
        if sort: rows.sort(key=lambda row: row[sort[0][0]], reverse=sort[0][1] < 0)
        return dict(rows[0]) if rows else None
    async def count_documents(self, query):
        return sum(1 for row in self.rows.values() if self.matches(row, query))


def row_id(n): return f"{1792972800000 + n}:{n:032x}"


def add(collection, n, kind="join", user=UID, status="sent", **extra):
    rid = row_id(n)
    collection.rows[rid] = {"_id": rid, "guild_id": GUILD_ID, "user_id": user, "event_type": kind,
                            "display_name": f"Name{n}", "username": f"user{n}",
                            "occurred_at": datetime(2026, 11, 6, 12, n % 60), "delivery_status": status, **extra}
    return rid


def context(collection):
    class Context:
        async def __aenter__(self): return NS(member_events=collection)
        async def __aexit__(self, *args): pass
    return Context()


def request(path):
    return make_mocked_request("GET", path)


def timeline_request(user=UID, query=""):
    from aiohttp.web_urldispatcher import UrlMappingMatchInfo
    req = make_mocked_request("GET", f"{api.PREFIX}/members/{user}{query}")
    req._match_info = UrlMappingMatchInfo({"user_id": user}, NS(handler=api.timeline))
    return req


class TimelineTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, collection, **kwargs):
        with patch.object(api, "require_manage", new=AsyncMock()) as guard, \
                patch.object(api, "mongo", return_value=context(collection)):
            response = await api.timeline(timeline_request(**kwargs))
        self.assertEqual(guard.await_args.args[1], "roles")
        return response

    async def test_auth_denied_propagates(self):
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())), \
                self.assertRaises(web.HTTPForbidden):
            await api.timeline(timeline_request())

    async def test_bad_ids_and_params_are_400(self):
        for user in ("123", "1" * 21, "12345678901234567x", "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨"):
            with self.subTest(user=user), self.assertRaises(web.HTTPBadRequest):
                await self.call(Collection(), user=user)
        for query in ("?limit=0", "?limit=101", "?limit=x", "?before=nope"):
            with self.subTest(query=query), self.assertRaises(web.HTTPBadRequest):
                await self.call(Collection(), query=query)

    async def test_404_without_rows_or_only_non_history_rows(self):
        collection = Collection()
        with self.assertRaises(web.HTTPNotFound):
            await self.call(collection)
        add(collection, 1, "link")
        add(collection, 2, "join", user="999999999999999999")
        with self.assertRaises(web.HTTPNotFound):
            await self.call(collection)

    async def test_shape_newest_first_identity_and_kind_filter(self):
        collection = Collection()
        add(collection, 1, "join")
        add(collection, 2, "unban")
        add(collection, 3, "link")
        add(collection, 4, "message_delete")
        add(collection, 5, "roles_added", avatar_type="image/png")
        data = json.loads((await self.call(collection)).text)
        self.assertEqual([e["event_type"] for e in data["events"]], ["roles_added", "unban", "join"])
        self.assertEqual(data["member"], {"user_id": UID, "display_name": "Name5", "username": "user5",
                                          "avatar_url": f"{api.PREFIX}/{row_id(5)}/avatar"})
        self.assertIsNone(data["next_before"])
        self.assertEqual(set(api.HISTORY_TYPES), {"join", "leave", "kick", "ban", "unban", "timeout_add",
                                                  "timeout_remove", "member_update", "roles_added",
                                                  "roles_removed", "invite_use"})

    async def test_events_carry_resolved_moderator_names(self):
        collection = Collection()
        mod = "223456789012345679"
        add(collection, 1, "kick", moderator_id=mod)
        add(collection, 2, "join")
        with patch("cwl_web.moderation_names.resolve_names", new=AsyncMock(return_value={mod: "Mod Mike"})) as names:
            data = json.loads((await self.call(collection)).text)
        self.assertEqual({e["event_type"]: e["moderator_name"] for e in data["events"]},
                         {"kick": "Mod Mike", "join": None})
        self.assertIn(mod, names.await_args.args[1])

    async def test_pagination_cursor(self):
        collection = Collection()
        for n in range(1, 6):
            add(collection, n)
        first = json.loads((await self.call(collection, query="?limit=2")).text)
        self.assertEqual([e["id"] for e in first["events"]], [row_id(5), row_id(4)])
        self.assertEqual(first["next_before"], row_id(4))
        second = json.loads((await self.call(collection, query=f"?limit=2&before={first['next_before']}")).text)
        self.assertEqual([e["id"] for e in second["events"]], [row_id(3), row_id(2)])
        last = json.loads((await self.call(collection, query=f"?limit=2&before={second['next_before']}")).text)
        self.assertEqual([e["id"] for e in last["events"]], [row_id(1)])
        self.assertIsNone(last["next_before"])
        self.assertEqual(first["member"]["display_name"], "Name5")


def option(can_post=True):
    return {"id": CHANNEL, "name": "log", "type": "text", "available_tags": [], "can_post": can_post,
            "requires_tag": False, "can_manage_threads": False}


class HealthTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, collection, enabled=("join",), channel=CHANNEL):
        saved = MemberEventStore.default_settings()
        for kind, value in saved["events"].items():
            value.update(enabled=kind in enabled, channel_id=channel if kind in enabled else None)
        collection.rows["member-events-settings:%s" % GUILD_ID] = {
            "_id": "member-events-settings:%s" % GUILD_ID, "event_key": "x", "revision": 1,
            "events": saved["events"]}

    async def call(self, collection, permissions=AUDIT | MANAGE, resolve=None, bot=None):
        actor = {"permissions": permissions, "role_ids": set(), "user_id": "1"}
        bot = bot or AsyncMock(return_value=(actor, None))
        resolve = resolve or AsyncMock(return_value=option())
        with patch.object(api, "require_manage", new=AsyncMock()) as guard, \
                patch.object(api, "mongo", return_value=context(collection)), \
                patch.object(api, "_bot_permissions", new=bot), \
                patch.object(api, "_resolve_option", new=resolve):
            response = await api.health(request(api.PREFIX + "/health"))
        self.assertEqual(guard.await_args.args[1], "roles")
        self.assertEqual(response.status, 200)
        return json.loads(response.text)

    async def test_auth_denied_propagates(self):
        with patch.object(api, "require_manage", new=AsyncMock(side_effect=web.HTTPForbidden())), \
                self.assertRaises(web.HTTPForbidden):
            await api.health(request(api.PREFIX + "/health"))

    async def test_healthy_is_empty_with_last_sent(self):
        collection = Collection()
        self.settings(collection)
        add(collection, 1, status="sent", delivered_at=datetime(2026, 11, 5, 8, 0))
        add(collection, 2, status="sent", delivered_at=datetime(2026, 11, 6, 9, 30))
        add(collection, 3, status="skipped")
        data = await self.call(collection)
        self.assertEqual(data, {"items": [], "backlog": 0, "last_sent_at": "2026-11-06T09:30:00+00:00"})

    async def test_no_rows_means_null_last_sent(self):
        collection = Collection()
        self.settings(collection)
        self.assertIsNone((await self.call(collection))["last_sent_at"])

    async def test_missing_audit_log_and_manage_server(self):
        collection = Collection()
        self.settings(collection)
        data = await self.call(collection, permissions=0)
        self.assertEqual({item["key"] for item in data["items"]}, {"audit_log", "manage_server"})
        manage = next(item for item in data["items"] if item["key"] == "manage_server")
        self.assertEqual((manage["level"], manage["text"]), ("warning", "Manage Server needed for invite counts"))
        self.assertEqual((await self.call(collection, permissions=AUDIT))["items"][0]["key"], "manage_server")
        self.assertEqual((await self.call(collection, permissions=MANAGE))["items"][0]["key"], "audit_log")
        self.assertEqual((await self.call(collection, permissions=8))["items"], [])  # Administrator

    async def test_enabled_event_destination_cannot_post(self):
        collection = Collection()
        self.settings(collection, enabled=("join", "leave"))
        data = await self.call(collection, resolve=AsyncMock(return_value=option(can_post=False)))
        self.assertEqual([(i["key"], i["level"]) for i in data["items"]],
                         [("destination_join", "error"), ("destination_leave", "error")])
        self.assertNotIn("bot", " ".join(i["text"] for i in data["items"]).lower())
        self.assertNotIn(CHANNEL, json.dumps(data))

    async def test_missing_or_unset_destination(self):
        collection = Collection()
        self.settings(collection)
        data = await self.call(collection, resolve=AsyncMock(side_effect=web.HTTPNotFound()))
        self.assertEqual([i["key"] for i in data["items"]], ["destination_join"])
        unset = Collection()
        self.settings(unset, channel=None)
        resolve = AsyncMock()
        self.assertEqual([i["key"] for i in (await self.call(unset, resolve=resolve))["items"]],
                         ["destination_join"])
        resolve.assert_not_awaited()

    async def test_disabled_events_are_ignored_and_channels_resolved_once(self):
        collection = Collection()
        self.settings(collection, enabled=())
        resolve = AsyncMock(return_value=option(can_post=False))
        self.assertEqual((await self.call(collection, resolve=resolve))["items"], [])
        resolve.assert_not_awaited()
        self.settings(collection, enabled=("join", "leave", "kick"))
        await self.call(collection, resolve=resolve)
        self.assertEqual(resolve.await_count, 1)

    async def test_backlog_threshold(self):
        collection = Collection()
        self.settings(collection)
        for n in range(1, 26):
            add(collection, n, status="queued")
        data = await self.call(collection)
        self.assertEqual((data["backlog"], data["items"]), (25, []))
        add(collection, 26, status="queued")
        data = await self.call(collection)
        self.assertEqual(data["backlog"], 26)
        self.assertEqual([(i["key"], i["level"]) for i in data["items"]], [("backlog", "warning")])

    async def test_discord_failure_is_one_warning_not_500(self):
        collection = Collection()
        self.settings(collection)
        add(collection, 1, status="queued")
        for error in (web.HTTPBadGateway(), RuntimeError("boom")):
            with self.subTest(error=type(error).__name__):
                data = await self.call(collection, bot=AsyncMock(side_effect=error))
                self.assertEqual(data["items"], [{"key": "health_unavailable", "level": "warning",
                                                  "text": "Health check unavailable"}])
                self.assertEqual(data["backlog"], 1)
        data = await self.call(collection, resolve=AsyncMock(side_effect=web.HTTPBadGateway()))
        self.assertEqual([i["key"] for i in data["items"]], ["health_unavailable"])

    def test_routes_registered(self):
        self.assertEqual({(r.method, r.path) for r in api.routes},
                         {("GET", api.PREFIX + "/members/{user_id}"), ("GET", api.PREFIX + "/health")})


if __name__ == "__main__":
    unittest.main()
