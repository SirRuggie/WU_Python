"""Invite snapshot storage and join attribution for the invite-use log.

The bot owns this collection; the web process only reads it. Attribution is a
diff of two snapshots, so it names an invite only when exactly one fits.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pymongo.write_concern import WriteConcern

UNKNOWN = None  # attribute_join result when the diff is empty or ambiguous.


def snapshot_id(guild_id: int, code: str) -> str:
    return f"{guild_id}:{code}"


def attribute_join(before: dict[str, dict], after: dict[str, dict]) -> str | None:
    """Return the one invite code that explains a single join, else None.

    A use is a rise of exactly 1. An invite that vanished while one use short of
    its limit was spent by this join. Vanity URLs are entries like any other.
    """
    candidates = []
    for code, old in before.items():
        new = after.get(code)
        if new is None:
            limit = old.get("max_uses") or 0
            if limit and int(old.get("uses", 0)) == limit - 1:
                candidates.append(code)
        elif int(new.get("uses", 0)) - int(old.get("uses", 0)) == 1:
            candidates.append(code)
        elif int(new.get("uses", 0)) > int(old.get("uses", 0)):
            return UNKNOWN  # More than one use: several joins shared this diff.
    return candidates[0] if len(candidates) == 1 else UNKNOWN


def snapshot_row(guild_id: int, code: str, *, uses, max_uses, inviter_id=None, inviter_name=None,
                 channel_id=None, channel_name=None, expires_at=None, vanity=False, now=None) -> dict:
    return {
        "_id": snapshot_id(guild_id, code), "guild_id": guild_id, "code": code,
        "uses": int(uses or 0), "max_uses": int(max_uses) if max_uses else None,
        "inviter_id": str(inviter_id) if inviter_id else None,
        "inviter_name": str(inviter_name)[:120] if inviter_name else None,
        "channel_id": str(channel_id) if channel_id else None,
        "channel_name": str(channel_name)[:120] if channel_name else None,
        "expires_at": expires_at if isinstance(expires_at, datetime) else None,
        "vanity": bool(vanity), "updated_at": now or datetime.now(timezone.utc),
    }


class MemberInviteStore:
    def __init__(self, collection):
        self.collection = collection.with_options(
            write_concern=WriteConcern(w="majority", wtimeout=10000)) if hasattr(collection, "with_options") else collection

    async def ensure_indexes(self):
        await self.collection.create_index("guild_id", name="member_invite_guild")

    async def load(self, guild_id: int) -> dict[str, dict]:
        rows = await self.collection.find({"guild_id": guild_id}).to_list(length=1000)
        return {row["code"]: row for row in rows}

    async def get(self, guild_id: int, code: str) -> dict | None:
        return await self.collection.find_one({"_id": snapshot_id(guild_id, code)})

    async def upsert(self, row: dict):
        await self.collection.replace_one({"_id": row["_id"]}, row, upsert=True)

    async def delete(self, guild_id: int, code: str):
        await self.collection.delete_one({"_id": snapshot_id(guild_id, code)})

    async def replace_all(self, guild_id: int, rows: list[dict]):
        """Make the snapshot match a freshly fetched invite list."""
        for row in rows:
            await self.upsert(row)
        await self.collection.delete_many(
            {"guild_id": guild_id, "code": {"$nin": [row["code"] for row in rows]}})


def public_invite(row: dict, names: dict) -> dict:
    expires = row.get("expires_at")
    return {
        "code": row["code"], "name": names.get(row["code"]),
        "inviter_id": row.get("inviter_id"), "inviter_name": row.get("inviter_name"),
        "channel_id": row.get("channel_id"), "channel_name": row.get("channel_name"),
        "uses": int(row.get("uses") or 0),
        "max_uses": int(row["max_uses"]) if row.get("max_uses") else None,
        "expires_at": expires.replace(tzinfo=expires.tzinfo or timezone.utc).isoformat()
        if isinstance(expires, datetime) else None,
        "vanity": bool(row.get("vanity")),
    }
