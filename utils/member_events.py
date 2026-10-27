"""Permanent join/leave identity snapshots and delivery receipts.

The Mongo collection is this feature's only storage owner. A row in ``sending``
may already have reached Discord, so recovery only processes ``queued`` rows.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

GUILD_ID = 644963518025826315
MAX_AVATAR_BYTES = 256 * 1024
ID_PATTERN = re.compile(r"\d{13}:[0-9a-f]{32}\Z")
AVATAR_HASH = re.compile(r"(?:a_)?[0-9a-fA-F]{32}\Z")


def event_key(guild_id: int, user_id: int, kind: str, at: datetime, joined_at=None) -> str:
    """Collapse gateway replay while allowing later join/leave episodes."""
    if isinstance(joined_at, datetime):
        normalized = joined_at.replace(tzinfo=joined_at.tzinfo or timezone.utc).astimezone(timezone.utc)
        episode = normalized.isoformat(timespec="microseconds")
    else:
        episode = str(int(at.timestamp()) // 10)
    return f"{guild_id}:{user_id}:{kind}:{episode}"


def safe_text(value: object, limit: int = 120) -> str:
    """Render untrusted Discord names as inert V2 Markdown text."""
    value = str(value or "").replace("\n", " ").replace("\r", " ").strip()[:limit]
    value = "".join(ch for ch in value if ch.isprintable())
    return re.sub(r"([\\`*_~|>\[\]()])", r"\\\1", value).replace("<", "\\<").replace("@", "@\u200b")


def avatar_source(guild_id: int, user_id: int, user_hash: object, guild_hash: object = None) -> str | None:
    """Only Discord CDN paths built from trusted snowflakes and validated hashes."""
    if guild_hash and AVATAR_HASH.fullmatch(str(guild_hash)):
        ext = "gif" if str(guild_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{guild_hash}.{ext}?size=128"
    if user_hash and AVATAR_HASH.fullmatch(str(user_hash)):
        ext = "gif" if str(user_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{user_hash}.{ext}?size=128"
    return None


class MemberEventStore:
    def __init__(self, collection):
        self.collection = collection.with_options(write_concern=WriteConcern(w="majority", wtimeout=10000)) if hasattr(collection, "with_options") else collection

    async def ensure_indexes(self):
        await self.collection.create_index("event_key", unique=True, name="member_event_key")
        await self.collection.create_index([("guild_id", 1), ("_id", -1)], name="member_event_recent")
        await self.collection.create_index([("guild_id", 1), ("user_id", 1), ("_id", -1)], name="member_event_user")
        await self.collection.create_index([("guild_id", 1), ("delivery_status", 1), ("_id", 1)], name="member_event_queue")

    async def capture(self, *, guild_id: int, user_id: int, kind: str, display_name: str,
                      username: str, avatar: bytes | None, avatar_type: str | None,
                      at: datetime, joined_at=None, channel_id: int):
        if guild_id != GUILD_ID or kind not in ("join", "leave"):
            raise ValueError("Member event is outside the configured guild")
        if avatar is not None and (len(avatar) > MAX_AVATAR_BYTES or avatar_type not in ("image/png", "image/jpeg", "image/gif", "image/webp")):
            raise ValueError("Avatar does not meet the storage bounds")
        key = event_key(guild_id, user_id, kind, at, joined_at)
        row = {
            "_id": f"{int(at.timestamp() * 1000):013d}:{uuid.uuid4().hex}",
            "event_key": key, "guild_id": guild_id, "user_id": str(user_id),
            "event_type": kind, "display_name": str(display_name)[:120],
            "username": str(username)[:120], "avatar": avatar,
            "avatar_type": avatar_type if avatar else None,
            "occurred_at": at, "joined_at": joined_at, "channel_id": channel_id,
            "delivery_status": "capturing", "message_id": None,
        }
        try:
            await self.collection.insert_one(row)
        except DuplicateKeyError:
            return None
        return row

    async def latest_joined_at(self, guild_id: int, user_id: int, at: datetime):
        row = await self.collection.find_one(
            {"guild_id": guild_id, "user_id": str(user_id), "event_type": "join",
             "occurred_at": {"$lte": at}},
            {"joined_at": 1}, sort=[("_id", -1)],
        )
        value = row.get("joined_at") if row else None
        return value if isinstance(value, datetime) else None

    async def save_avatar(self, row_id: str, avatar: bytes, avatar_type: str):
        if len(avatar) > MAX_AVATAR_BYTES or avatar_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise ValueError("Avatar does not meet the storage bounds")
        await self.collection.update_one(
            {"_id": row_id, "delivery_status": "capturing"},
            {"$set": {"avatar": avatar, "avatar_type": avatar_type}},
        )

    async def ready(self, row_id: str):
        return await self.collection.find_one_and_update(
            {"_id": row_id, "delivery_status": "capturing"},
            {"$set": {"delivery_status": "queued"}},
            return_document=ReturnDocument.AFTER,
        )

    async def release_stale_captures(self, guild_id: int, channel_id: int):
        # Avatar fetch is capped at five seconds; a crashed handler cannot hold
        # identity-only history indefinitely. Only recovery promotes old rows.
        threshold = datetime.now(timezone.utc) - timedelta(seconds=15)
        await self.collection.update_many(
            {"guild_id": guild_id, "channel_id": channel_id,
             "delivery_status": "capturing", "occurred_at": {"$lte": threshold}},
            {"$set": {"delivery_status": "queued"}},
        )

    async def queued(self, guild_id: int, channel_id: int, limit=100):
        return await self.collection.find({"guild_id": guild_id, "channel_id": channel_id,
                                           "delivery_status": "queued"}).sort("_id", 1).limit(limit).to_list(length=limit)

    async def claim(self, row_id: str):
        return await self.collection.find_one_and_update(
            {"_id": row_id, "delivery_status": "queued"},
            {"$set": {"delivery_status": "sending", "claimed_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )

    async def finish(self, row_id: str, *, status: str, message_id=None):
        if status not in ("sent", "uncertain"):
            raise ValueError("Invalid delivery status")
        await self.collection.update_one(
            {"_id": row_id, "delivery_status": "sending"},
            {"$set": {"delivery_status": status, "message_id": str(message_id) if message_id else None,
                      "delivered_at": datetime.now(timezone.utc) if status == "sent" else None}},
        )

    async def search(self, *, guild_id: int, query="", kind="", start=None, end=None, before=None, limit=50):
        filters = {"guild_id": guild_id}
        if kind:
            filters["event_type"] = kind
        if before:
            filters["_id"] = {"$lt": before}
        if start or end:
            bounds = {}
            if start:
                bounds["$gte"] = start
            if end:
                bounds["$lt"] = end
            filters["occurred_at"] = bounds
        if query:
            needle = re.escape(query)
            filters["$or"] = [{"display_name": {"$regex": needle, "$options": "i"}},
                              {"username": {"$regex": needle, "$options": "i"}},
                              {"user_id": query}]
        rows = await self.collection.find(filters, {"avatar": 0}).sort("_id", -1).limit(limit + 1).to_list(length=limit + 1)
        next_cursor = rows[limit - 1]["_id"] if len(rows) > limit else None
        return rows[:limit], next_cursor

    async def avatar(self, row_id: str, guild_id: int):
        return await self.collection.find_one({"_id": row_id, "guild_id": guild_id}, {"avatar": 1, "avatar_type": 1})


def public_event(row: dict, *, api_prefix: str) -> dict:
    at = row["occurred_at"]
    if isinstance(at, datetime):
        at = at.replace(tzinfo=at.tzinfo or timezone.utc).isoformat()
    return {
        "id": row["_id"], "user_id": row["user_id"], "event_type": row["event_type"],
        "display_name": row["display_name"], "username": row["username"],
        "avatar_url": f"{api_prefix}/{row['_id']}/avatar" if row.get("avatar_type") else None,
        "occurred_at": at, "delivery_status": "queued" if row["delivery_status"] == "capturing" else row["delivery_status"],
    }
