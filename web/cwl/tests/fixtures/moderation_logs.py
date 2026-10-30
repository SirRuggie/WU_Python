"""Loopback-only moderation settings/history fixture; all Discord calls are fake."""
import json
import base64
import hashlib
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ["WU_FIXTURE_BACKEND"])
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(Path(__file__).parent)]
import qa_network_guard  # noqa: E402
from aiohttp import web  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402
from cwl_web import create_app  # noqa: E402
from cwl_web.member_events import GUILD_ID  # noqa: E402
from test_moderation_backend import MemoryCollection, MemoryCursor  # noqa: E402
from utils.member_events import DEFAULT_CHANNEL_ID, MemberEventStore, SETTINGS_ID  # noqa: E402

PORT = int(sys.argv[2])
assert 8900 <= PORT <= 8999 and PORT not in (8766, 8767)
STATIC = Path(sys.argv[1]).resolve()
folder = tempfile.TemporaryDirectory(prefix="wu-moderation-logs-")
staff_id = "505227988229554179"
bot_id = "100000000000000099"
text_id = str(DEFAULT_CHANNEL_ID)
forum_id = "111111111111111111"
post_id = "222222222222222222"
locked_id = "333333333333333333"
tag_id = "444444444444444444"


class Collection(MemoryCollection):
    @staticmethod
    def matches(row, query):
        if not row:
            return False
        for key, expected in query.items():
            if key == "$or":
                if not any(Collection.matches(row, item) for item in expected):
                    return False
                continue
            value = row.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                for bound in ("$gte", "$lte", "$lt"):
                    if bound in expected and (value is None or not {
                        "$gte": lambda: value >= expected[bound],
                        "$lte": lambda: value <= expected[bound],
                        "$lt": lambda: value < expected[bound],
                    }[bound]()):
                        return False
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$regex" in expected:
                    import re
                    if not re.search(expected["$regex"], str(value or ""), re.I):
                        return False
            elif value != expected:
                return False
        return True

    def find(self, query, projection=None):
        rows = [deepcopy(row) for row in self.rows.values() if self.matches(row, query)]
        if projection and projection.get("avatar") == 0:
            for row in rows:
                row.pop("avatar", None)
        return MemoryCursor(rows)


class AuditCollection(Collection):
    async def insert_one(self, row):
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate audit ID")
        self.rows[row["_id"]] = deepcopy(row)

    async def find_one_and_update(self, query, update, **kwargs):
        key = query["_id"]
        prior = self.rows.get(key)
        if prior and prior["last_at"] > query["last_at"]["$lte"]:
            raise DuplicateKeyError("rate window occupied")
        self.rows[key] = {"_id": key, **deepcopy(update["$set"])}
        return deepcopy(self.rows[key])


class Mongo:
    def __init__(self):
        self.member_events = Collection()
        self.member_event_test_audit = AuditCollection()
        self.ticket_setup = Collection()
        self.bot_config = Collection()


mongo = Mongo()
legacy = MemberEventStore.default_settings()
mongo.member_events.rows[SETTINGS_ID] = {
    "_id": SETTINGS_ID, "event_key": SETTINGS_ID, **deepcopy(legacy), "revision": 1,
}
now = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
for index, (kind, name, reason, moderator) in enumerate([
    ("join", "Amber Archer", None, None),
    ("leave", "Blaze Builder", None, None),
    ("kick", "Cinder Captain", "Repeated spam", "987654321098765432"),
    ("ban", "Delta Defender", "Unsafe links", "987654321098765432"),
]):
    row_id = f"{int((now - timedelta(hours=index)).timestamp() * 1000):013d}:{index + 1:032x}"
    mongo.member_events.rows[row_id] = {
        "_id": row_id, "event_key": f"sample:{kind}", "guild_id": GUILD_ID,
        "user_id": str(123456789012345678 + index), "event_type": kind,
        "display_name": name, "username": name.lower().replace(" ", "_"),
        "avatar": base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1sAAAAASUVORK5CYII="), "avatar_type": "image/png",
        "occurred_at": now - timedelta(hours=index),
        "joined_at": now - timedelta(days=300), "reason": reason,
        "moderator_id": moderator, "delivery_status": "sent",
        "message_id": str(555555555555555555 + index),
        "channel_id": text_id, "forum_tag_id": None,
    }

channels = {
    text_id: {"id": text_id, "guild_id": str(GUILD_ID), "name": "member-log",
              "type": 0, "permission_overwrites": []},
    forum_id: {"id": forum_id, "guild_id": str(GUILD_ID), "name": "moderation-forum",
               "type": 15, "flags": 16, "available_tags": [
                   {"id": tag_id, "name": "Staff review", "moderated": False}],
               "permission_overwrites": []},
    post_id: {"id": post_id, "guild_id": str(GUILD_ID), "name": "existing-log-post",
              "type": 11, "parent_id": forum_id,
              "thread_metadata": {"locked": False}, "permission_overwrites": []},
    locked_id: {"id": locked_id, "guild_id": str(GUILD_ID), "name": "locked-post",
                "type": 11, "parent_id": forum_id,
                "thread_metadata": {"locked": True}, "permission_overwrites": []},
    "555555555555555555": {"id": "555555555555555555", "guild_id": str(GUILD_ID),
                           "name": "private-post", "type": 12, "parent_id": forum_id,
                           "permission_overwrites": []},
}
ledger = []
requests = []
flags = {"inventory_unavailable": False, "permission_denied": False}


async def fake_discord(method, path, **kwargs):
    ledger.append({"method": method, "path": path, "payload": deepcopy(kwargs.get("json"))})
    if flags["permission_denied"] and method == "GET" and path.endswith("/members/" + staff_id):
        raise web.HTTPForbidden(text="Fixture permission removed")
    if method == "GET" and path == "/users/@me":
        return {"id": bot_id}
    if method == "GET" and path == f"/guilds/{GUILD_ID}/members/{bot_id}":
        return {"roles": []}
    if method == "GET" and path == f"/guilds/{GUILD_ID}/members/987654321098765432":
        return {"nick": "Fixture moderator", "user": {"id": "987654321098765432", "username": "fixture-moderator"}}
    if method == "GET" and path == f"/guilds/{GUILD_ID}/members/{staff_id}":
        return {"roles": []}
    if method == "GET" and path == f"/guilds/{GUILD_ID}/roles":
        return [{"id": str(GUILD_ID), "permissions": "8"}]
    if method == "GET" and path == f"/guilds/{GUILD_ID}":
        return {"id": str(GUILD_ID), "owner_id": staff_id}
    if method == "GET" and path == f"/guilds/{GUILD_ID}/channels":
        if flags["inventory_unavailable"]:
            raise web.HTTPServiceUnavailable(text="Fixture inventory unavailable")
        return [channels[text_id], channels[forum_id], channels["555555555555555555"]]
    if method == "GET" and path == f"/guilds/{GUILD_ID}/threads/active":
        return {"threads": [channels[locked_id]]}
    if method == "GET" and path.startswith("/channels/"):
        item = channels.get(path.rsplit("/", 1)[-1])
        if item:
            return item
        raise web.HTTPNotFound(text="Fixture channel missing")
    if method == "POST" and path.startswith("/channels/"):
        return {"message": {"id": "666666666666666666"}} if path.endswith("/threads") else {
            "id": "666666666666666666"}
    raise AssertionError(f"Unexpected fake Discord call: {method} {path}")


app = create_app(db_path=folder.name + "/isolated.sqlite", dev_fixture=True,
                 dev_identity={"id": staff_id, "username": "Moderation fixture",
                               "guild_owner": True},
                 secure_cookies=False, static_dir=STATIC)
assert Path(app["store"].path).is_relative_to(folder.name)
app["server_management_mongo"] = mongo
app["server_management_discord"] = fake_discord


@web.middleware
async def record_requests(request, handler):
    if request.path.startswith("/api/"):
        requests.append({"method": request.method, "path": request.path})
    return await handler(request)


app.middlewares.insert(0, record_requests)


def state():
    history = {key: value for key, value in mongo.member_events.rows.items()
               if value.get("event_type")}
    return {
        "history_count": len(history),
        "history_ids": sorted(history),
        "history_sha256": hashlib.sha256(json.dumps(history, sort_keys=True,
                                                      default=str).encode()).hexdigest(),
        "settings_revision": mongo.member_events.rows[SETTINGS_ID]["revision"],
        "audit_count": len(mongo.member_event_test_audit.rows),
        "posts": [entry for entry in ledger if entry["method"] == "POST"],
        "requests": requests,
    }


baseline = deepcopy(state())


async def qa_state(request):
    return web.json_response({"baseline": baseline, "current": state()})


async def scenario(request):
    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPNotFound()
    for key in flags:
        if key in request.query:
            flags[key] = request.query[key] == "1"
    return web.json_response(flags)


app.router.add_get("/qa/state", qa_state)
app.router.add_get("/qa/scenario", scenario)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=PORT)
