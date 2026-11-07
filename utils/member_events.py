"""Permanent member and moderation identity snapshots and delivery receipts.

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

from .member_event_settings import EVENT_TYPES, normalize_settings

GUILD_ID = 644963518025826315
MAX_AVATAR_BYTES = 256 * 1024
ID_PATTERN = re.compile(r"\d{13}:[0-9a-f]{32}\Z")
# EVENT_TYPES covers every deliverable log. Only HISTORY_TYPES are searchable;
# link and invite rows are delivery receipts, and IDENTITY_TYPES carry avatars.
HISTORY_TYPES = ("join", "leave", "kick", "ban", "unban", "timeout_add", "timeout_remove",
                 "member_update", "roles_added", "roles_removed", "invite_use")
# Days a row lives before the Mongo TTL index removes it; absent kinds are kept.
RETENTION_DAYS = {"link": 30, "message_delete": 30, "message_edit": 30, "message_bulk_delete": 30,
                  "invite_create": 90, "invite_delete": 90, "invite_use": 90}
IDENTITY_TYPES = ("join", "leave", "kick", "ban")
DEFAULT_CHANNEL_ID = 1004519991648997447
SETTINGS_ID = f"member-events-settings:{GUILD_ID}"
BOT_ACTORS_ID = f"member-events-bot-actors:{GUILD_ID}"
AUDIT_CURSOR_ID = f"member-events-audit-cursor:{GUILD_ID}"
MAX_BOT_ACTORS = 100
AUDIT_MARKER_TTL = timedelta(hours=48)
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
    value = "".join(ch for ch in value if ch.isprintable() or ch == "\u200d")
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


def effective_permissions(base: int, role_ids, user_id: int, overwrites, guild_id: int = GUILD_ID) -> int:
    """Discord overwrite precedence for a bot member, shared by web and gateway."""
    def value(item, key, default=0):
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)
    rights = int(base)
    if rights & 8:  # Administrator ignores channel overwrites.
        return rights
    roles = {str(role) for role in role_ids}
    entries = list(overwrites.values()) if isinstance(overwrites, dict) else list(overwrites or ())
    for entry in entries:
        if str(value(entry, "id")) == str(guild_id):
            rights = (rights & ~int(value(entry, "deny"))) | int(value(entry, "allow"))
    deny = allow = 0
    for entry in entries:
        if int(value(entry, "type", -1)) == 0 and str(value(entry, "id")) in roles:
            deny |= int(value(entry, "deny"))
            allow |= int(value(entry, "allow"))
    rights = (rights & ~deny) | allow
    for entry in entries:
        if int(value(entry, "type", -1)) == 1 and str(value(entry, "id")) == str(user_id):
            rights = (rights & ~int(value(entry, "deny"))) | int(value(entry, "allow"))
    return rights


class MemberEventStore:
    def __init__(self, collection, test_audit=None):
        self.collection = collection.with_options(write_concern=WriteConcern(w="majority", wtimeout=10000)) if hasattr(collection, "with_options") else collection
        self.test_audit = test_audit.with_options(write_concern=WriteConcern(w="majority", wtimeout=10000)) if hasattr(test_audit, "with_options") else test_audit

    async def ensure_indexes(self):
        await self.collection.create_index("event_key", unique=True, name="member_event_key")
        await self.collection.create_index([("guild_id", 1), ("_id", -1)], name="member_event_recent")
        await self.collection.create_index([("guild_id", 1), ("user_id", 1), ("_id", -1)], name="member_event_user")
        await self.collection.create_index([("guild_id", 1), ("delivery_status", 1), ("_id", 1)], name="member_event_queue")
        await self.collection.create_index("expires_at", expireAfterSeconds=0, name="member_event_expiry")
        await self.collection.create_index(
            [("guild_id", 1), ("audit_entry_id", 1)], name="member_event_audit_entry",
            partialFilterExpression={"audit_entry_id": {"$type": "string"}})

    @staticmethod
    def default_settings():
        return {"revision": 0, "events": {
            kind: {"enabled": kind in ("join", "leave"),
                   "channel_id": str(DEFAULT_CHANNEL_ID) if kind in ("join", "leave") else None,
                   "forum_tag_id": None}
            for kind in EVENT_TYPES
        }}

    async def settings(self):
        row = await self.collection.find_one({"_id": SETTINGS_ID})
        return normalize_settings(row, self.default_settings())

    async def save_settings(self, revision: int, settings: dict):
        # Accept the original events-only call for older integrations. New
        # writes always persist the normalized schema after the CAS succeeds.
        if "events" not in settings:
            settings = {"events": settings}
        normalized = normalize_settings({"revision": revision, **settings}, self.default_settings())
        values = {key: normalized[key] for key in (
            "schema_version", "main", "categories", "events", "ignores", "invite_names")}
        if normalized["ignored_bot_ids"] is not None:  # Absent keeps the own-bot default.
            values["ignored_bot_ids"] = normalized["ignored_bot_ids"]
        if revision == 0:
            try:
                await self.collection.insert_one({"_id": SETTINGS_ID, "event_key": SETTINGS_ID,
                                                  "revision": 1, **values})
            except DuplicateKeyError:
                raise SettingsConflict("Member log settings changed") from None
            return {**normalized, "revision": 1}
        row = await self.collection.find_one_and_update(
            {"_id": SETTINGS_ID, "revision": revision},
            {"$set": values, "$inc": {"revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not row:
            raise SettingsConflict("Member log settings changed")
        return normalize_settings(row, self.default_settings())

    async def bot_actors(self) -> dict:
        row = await self.collection.find_one({"_id": BOT_ACTORS_ID})
        bots = row.get("bots") if row else None
        return dict(bots) if isinstance(bots, dict) else {}

    async def note_bot_actor(self, user_id, name: str, now: datetime | None = None):
        """Remember a bot seen as an audit actor; keeps the 100 most recent."""
        now = now or datetime.now(timezone.utc)
        bots = await self.bot_actors()
        uid, name = str(user_id), str(name or user_id)[:80]
        seen = bots.get(uid)
        if seen and seen.get("name") == name and isinstance(seen.get("last_seen"), datetime) and (
                now - seen["last_seen"].replace(tzinfo=seen["last_seen"].tzinfo or timezone.utc)
        ) < timedelta(hours=1):
            return  # Fresh enough; avoid a write per audit entry.
        bots.pop(uid, None)
        bots[uid] = {"name": name, "last_seen": now}
        ordered = sorted(bots.items(), key=lambda item: item[1]["last_seen"].replace(
            tzinfo=item[1]["last_seen"].tzinfo or timezone.utc))
        bots = dict(ordered[-MAX_BOT_ACTORS:])
        await self._write_state(BOT_ACTORS_ID, {"bots": bots})

    async def audit_cursor(self) -> int | None:
        row = await self.collection.find_one({"_id": AUDIT_CURSOR_ID})
        if not row:
            return None
        try:
            return int(row["last_audit_num"]) if row.get("last_audit_num") is not None else int(row["last_audit_id"])
        except (KeyError, TypeError, ValueError):
            return None

    async def advance_audit_cursor(self, entry_id, now: datetime | None = None):
        """Move the newest-processed audit entry forward; never backward.

        The id is kept as an integer in ``last_audit_num`` so Mongo compares it
        numerically, and each move is one filtered update, safe when advances race.
        """
        number = int(entry_id)
        values = {"last_audit_num": number, "last_audit_id": str(number),
                  "updated_at": now or datetime.now(timezone.utc)}
        for _ in range(5):
            if (await self.collection.update_one(
                    {"_id": AUDIT_CURSOR_ID, "last_audit_num": {"$lt": number}}, {"$set": values})).matched_count:
                return
            row = await self.collection.find_one({"_id": AUDIT_CURSOR_ID})
            if row is None:
                try:
                    await self.collection.insert_one({"_id": AUDIT_CURSOR_ID, "event_key": AUDIT_CURSOR_ID,
                                                      "guild_id": GUILD_ID, **values})
                    return
                except DuplicateKeyError:
                    continue
            if row.get("last_audit_num") is not None:
                return  # Already at or past this entry.
            try:  # Older document with only the string id: adopt it, then move on.
                legacy = int(row["last_audit_id"])
            except (KeyError, TypeError, ValueError):
                legacy = 0
            await self.collection.update_one(
                {"_id": AUDIT_CURSOR_ID, "last_audit_num": {"$exists": False}},
                {"$set": {**values, "last_audit_num": max(number, legacy), "last_audit_id": str(max(number, legacy))}})

    @staticmethod
    def _audit_marker_id(guild_id: int, audit_entry_id) -> str:
        return f"member-events-audit:{guild_id}:{int(audit_entry_id)}"

    async def audit_handled(self, guild_id: int, audit_entry_id) -> bool:
        """True once this audit entry was fully handled (see ``mark_audit_handled``)."""
        return bool(await self.collection.find_one(
            {"_id": self._audit_marker_id(guild_id, audit_entry_id)}, {"_id": 1}))

    async def audit_row_exists(self, guild_id: int, audit_entry_id) -> bool:
        """True when a persisted log row carries this audit entry id (the second replay guard).

        Ban rows and ban-audit facts are left out: the ban handler finishes them idempotently.
        """
        return bool(await self.collection.find_one(
            {"guild_id": guild_id, "audit_entry_id": str(int(audit_entry_id)),
             "event_type": {"$exists": True, "$ne": "ban"}}, {"_id": 1}))

    async def mark_audit_handled(self, guild_id: int, audit_entry_id, now: datetime | None = None):
        """Record that an audit entry is done, whatever its outcome, so a replay skips it.

        Written after every row of the entry. The marker has no event_type, so it never
        reaches history or counts, and the expiry index removes it after 48 hours.
        """
        now = now or datetime.now(timezone.utc)
        key = self._audit_marker_id(guild_id, audit_entry_id)
        values = {"handled_at": now, "expires_at": now + AUDIT_MARKER_TTL}
        row = await self.collection.find_one_and_update({"_id": key}, {"$set": values})
        if row is None:
            try:
                await self.collection.insert_one({"_id": key, "event_key": key, **values})
            except DuplicateKeyError:
                await self.collection.update_one({"_id": key}, {"$set": values})

    async def app_add_posted(self, guild_id: int, application_id: str, at: datetime, window: timedelta):
        """True when an "App added" row for this application sits within ``window`` of ``at``."""
        rows = await self.collection.find(
            {"guild_id": guild_id, "event_type": "app",
             "occurred_at": {"$gte": at - window, "$lte": at + window}},
        ).limit(50).to_list(length=50)
        for row in rows:
            details = row.get("details") or {}
            if details.get("action") == "added" and details.get("application_id") == application_id:
                return True
        return False

    async def _write_state(self, state_id: str, values: dict):
        """State docs carry no event_type or expires_at: never in history, never expired."""
        row = await self.collection.find_one_and_update({"_id": state_id}, {"$set": values})
        if row is None:
            try:
                await self.collection.insert_one({"_id": state_id, "event_key": state_id,
                                                  "guild_id": GUILD_ID, **values})
            except DuplicateKeyError:
                await self.collection.update_one({"_id": state_id}, {"$set": values})

    async def reserve_test(self, kind: str, staff_id: str, now: datetime):
        """Atomically rate-limit a test without touching event history."""
        if self.test_audit is None:
            raise RuntimeError("Member-event test audit storage is unavailable")
        rate_id = f"member-event-test-rate:{GUILD_ID}:{kind}"
        audit_id = f"member-event-test:{uuid.uuid4().hex}"
        try:
            await self.test_audit.find_one_and_update(
                {"_id": rate_id, "last_at": {"$lte": now - timedelta(seconds=10)}},
                {"$set": {"last_at": now, "staff_id": staff_id, "audit_id": audit_id}},
                upsert=True, return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise TestRateLimited("Wait 10 seconds before sending another test for this event.") from None
        await self.test_audit.insert_one({"_id": audit_id, "guild_id": GUILD_ID,
                                          "event_type": kind, "staff_id": staff_id,
                                          "at": now, "status": "attempting"})
        return audit_id

    async def cancel_test(self, audit_id: str, *, kind: str, destination: str):
        """Release only this unsent claim; never clear a newer caller's cooldown."""
        await self.finish_test(audit_id, status="cancelled", destination=destination)
        await self.test_audit.delete_one({
            "_id": f"member-event-test-rate:{GUILD_ID}:{kind}", "audit_id": audit_id,
        })

    async def finish_test(self, audit_id: str, *, status: str, destination: str):
        await self.test_audit.update_one(
            {"_id": audit_id, "status": "attempting"},
            {"$set": {"status": status, "destination": destination}},
        )

    async def capture(self, *, guild_id: int, user_id: int, kind: str, display_name: str,
                      username: str, avatar: bytes | None, avatar_type: str | None,
                      at: datetime, joined_at=None, channel_id: int | None = None,
                      forum_tag_id: int | None = None, reason: str | None = None,
                      moderator_id: int | None = None, audit_entry_id: int | None = None,
                      episode: int | None = None, account_created_at: datetime | None = None,
                      member_count: int | None = None, roles: list[str] | None = None,
                      details: dict | None = None, dedupe_key: str | None = None):
        if guild_id != GUILD_ID or kind not in EVENT_TYPES:
            raise ValueError("Member event is outside the configured guild")
        if avatar is not None and (len(avatar) > MAX_AVATAR_BYTES or avatar_type not in ("image/png", "image/jpeg", "image/gif", "image/webp")):
            raise ValueError("Avatar does not meet the storage bounds")
        key = (dedupe_key or
               (f"{guild_id}:audit:{audit_entry_id}" if audit_entry_id else None) or
               event_key(guild_id, user_id, kind, at, joined_at if kind in ("join", "leave") else None))
        if kind == "ban" and episode is not None:
            key = f"{guild_id}:ban:{user_id}:{episode}"
        row = {
            "_id": f"{int(at.timestamp() * 1000):013d}:{uuid.uuid4().hex}",
            "event_key": key, "guild_id": guild_id, "user_id": str(user_id),
            "event_type": kind, "display_name": str(display_name)[:120],
            "username": str(username)[:120], "avatar": avatar,
            "avatar_type": avatar_type if avatar else None,
            "occurred_at": at, "joined_at": joined_at, "channel_id": channel_id,
            "forum_tag_id": forum_tag_id, "reason": str(reason)[:500] if reason else None,
            "account_created_at": account_created_at if isinstance(account_created_at, datetime) else None,
            "member_count": member_count if isinstance(member_count, int) and member_count >= 0 else None,
            "roles": [str(role)[:100] for role in roles[:30]] if isinstance(roles, list) else None,
            "moderator_id": str(moderator_id) if moderator_id else None,
            "audit_entry_id": str(audit_entry_id) if audit_entry_id else None,
            "details": details if isinstance(details, dict) else None,
            "delivery_status": "capturing", "message_id": None,
        }
        if kind in RETENTION_DAYS:
            row["expires_at"] = at + timedelta(days=RETENTION_DAYS[kind])
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

    async def count_joins(self, guild_id: int, user_id: int) -> int:
        return await self.collection.count_documents(
            {"guild_id": guild_id, "user_id": str(user_id), "event_type": "join"})

    async def save_details(self, row_id: str, details: dict):
        await self.collection.update_one(
            {"_id": row_id, "delivery_status": "capturing"}, {"$set": {"details": details}})

    async def enrich_unban(self, event_key: str, moderator_id: int | None, reason: str | None,
                           audit_entry_id: int):
        """Add the audit facts to an unsent unban whose gateway event came first."""
        values = {"audit_entry_id": str(audit_entry_id)}
        if moderator_id:
            values["moderator_id"] = str(moderator_id)
        if reason:
            values["reason"] = str(reason)[:500]
        result = await self.collection.update_one(
            {"event_key": event_key, "event_type": "unban", "audit_entry_id": None,
             "delivery_status": {"$in": ["capturing", "queued"]}},
            {"$set": values},
        )
        return bool(result.matched_count)

    async def discard_unsent(self, event_key: str):
        """Drop a row that was never sent, for an event that must not be logged."""
        await self.collection.delete_one(
            {"event_key": event_key, "delivery_status": {"$in": ["capturing", "queued"]}})

    async def ban_episode(self, guild_id: int, user_id: int, *, banned: bool):
        key = f"ban-state:{guild_id}:{user_id}"
        row = await self.collection.find_one({"_id": key})
        if not row:
            try:
                await self.collection.insert_one({"_id": key, "event_key": key,
                                                  "guild_id": guild_id, "user_id": str(user_id),
                                                  "sequence": 1, "banned": banned})
                return 1
            except DuplicateKeyError:
                row = await self.collection.find_one({"_id": key})
        if banned and not row["banned"]:
            updated = await self.collection.find_one_and_update(
                {"_id": key, "banned": False},
                {"$set": {"banned": True}, "$inc": {"sequence": 1}},
                return_document=ReturnDocument.AFTER,
            )
            return updated["sequence"] if updated else (await self.collection.find_one({"_id": key}))["sequence"]
        if not banned and row["banned"]:
            await self.collection.update_one({"_id": key, "banned": True},
                                             {"$set": {"banned": False}})
        return row["sequence"]

    async def ban_audit_exists(self, guild_id: int, audit_entry_id: int):
        return bool(await self.collection.find_one(
            {"guild_id": guild_id, "event_type": "ban",
             "audit_entry_id": str(audit_entry_id)}, {"_id": 1},
        ))

    async def note_ban_audit(self, guild_id: int, user_id: int, audit_entry_id: int):
        key = f"ban-state:{guild_id}:{user_id}"
        await self.collection.update_one({"_id": key},
                                         {"$set": {"last_audit_entry_id": str(audit_entry_id)}})

    async def advance_ban_episode_for_audit(self, guild_id: int, user_id: int, audit_entry_id: int):
        """A distinct confirmed ban must survive a missed unban gateway event."""
        key = f"ban-state:{guild_id}:{user_id}"
        audit_id = str(audit_entry_id)
        row = await self.collection.find_one({"_id": key})
        if not row:
            try:
                await self.collection.insert_one({"_id": key, "event_key": key,
                                                  "guild_id": guild_id, "user_id": str(user_id),
                                                  "sequence": 1, "banned": True,
                                                  "last_audit_entry_id": audit_id})
                return 1
            except DuplicateKeyError:
                pass
        updated = await self.collection.find_one_and_update(
            {"_id": key, "last_audit_entry_id": {"$ne": audit_id}},
            {"$set": {"banned": True, "last_audit_entry_id": audit_id},
             "$inc": {"sequence": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated:
            return updated["sequence"]
        return (await self.collection.find_one({"_id": key}))["sequence"]

    async def record_ban_audit(self, guild_id: int, user_id: int, audit_entry_id: int,
                               at: datetime, moderator_id: int | None, reason: str | None):
        key = f"ban-audit:{guild_id}:{audit_entry_id}"
        row = {"_id": key, "event_key": key, "guild_id": guild_id,
               "user_id": str(user_id), "occurred_at": at,
               "moderator_id": str(moderator_id) if moderator_id else None,
               "reason": str(reason)[:500] if reason else None, "consumed": False}
        try:
            await self.collection.insert_one(row)
        except DuplicateKeyError:
            pass
        return row

    async def pending_ban_audit(self, guild_id: int, user_id: int, at: datetime):
        rows = await self.collection.find(
            {"_id": {"$regex": f"^ban-audit:{guild_id}:"},
             "guild_id": guild_id, "user_id": str(user_id), "consumed": False,
             "occurred_at": {"$gte": at - timedelta(seconds=30),
                             "$lte": at + timedelta(seconds=30)}},
        ).limit(5).to_list(length=5)
        if not rows:
            return None
        when = at.replace(tzinfo=at.tzinfo or timezone.utc)
        return min(rows, key=lambda row: abs((row["occurred_at"].replace(
            tzinfo=row["occurred_at"].tzinfo or timezone.utc) - when).total_seconds()))

    async def consume_ban_audit(self, key: str):
        await self.collection.update_one({"_id": key, "consumed": False},
                                         {"$set": {"consumed": True}})

    async def latest_departure_identity(self, guild_id: int, user_id: int):
        return await self.collection.find_one(
            {"guild_id": guild_id, "user_id": str(user_id),
             "event_type": {"$in": ["join", "leave"]}},
            {"display_name": 1, "username": 1, "avatar": 1, "avatar_type": 1,
             "joined_at": 1, "occurred_at": 1, "account_created_at": 1,
             "member_count": 1, "roles": 1}, sort=[("_id", -1)],
        )

    async def latest_identity(self, guild_id: int, user_id: int):
        return await self.collection.find_one(
            {"guild_id": guild_id, "user_id": str(user_id), "event_type": {"$in": IDENTITY_TYPES}},
            {"display_name": 1, "username": 1, "avatar": 1, "avatar_type": 1,
             "joined_at": 1, "occurred_at": 1, "account_created_at": 1,
             "member_count": 1, "roles": 1}, sort=[("_id", -1)],
        )

    async def enrich_ban(self, guild_id: int, user_id: int, at: datetime,
                         moderator_id: int | None, reason: str | None, audit_entry_id: int):
        # Ban gateway and audit events can arrive in either order. Match only
        # an unenriched ban of this exact user close to the audit event time.
        earliest, latest = at - timedelta(seconds=30), at + timedelta(seconds=30)
        rows = await self.collection.find(
            {"guild_id": guild_id, "user_id": str(user_id), "event_type": "ban",
             "audit_entry_id": None, "occurred_at": {"$gte": earliest, "$lte": latest}},
            {"_id": 1, "occurred_at": 1},
        ).limit(5).to_list(length=5)
        if not rows:
            return False
        def distance(row):
            occurred = row["occurred_at"].replace(tzinfo=row["occurred_at"].tzinfo or timezone.utc)
            return abs((occurred - at.replace(tzinfo=at.tzinfo or timezone.utc)).total_seconds())
        chosen = min(rows, key=distance)
        values = {"audit_entry_id": str(audit_entry_id)}
        if moderator_id:
            values["moderator_id"] = str(moderator_id)
        if reason:
            values["reason"] = str(reason)[:500]
        result = await self.collection.update_one(
            {"_id": chosen["_id"], "event_type": "ban", "audit_entry_id": None},
            {"$set": values},
        )
        return bool(result.matched_count)

    async def save_identity(self, row_id: str, display_name: str, username: str):
        await self.collection.update_one(
            {"_id": row_id, "delivery_status": "capturing"},
            {"$set": {"display_name": str(display_name)[:120],
                      "username": str(username)[:120]}},
        )

    async def save_avatar(self, row_id: str, avatar: bytes, avatar_type: str):
        if len(avatar) > MAX_AVATAR_BYTES or avatar_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise ValueError("Avatar does not meet the storage bounds")
        await self.collection.update_one(
            {"_id": row_id, "delivery_status": "capturing"},
            {"$set": {"avatar": avatar, "avatar_type": avatar_type}},
        )

    async def ready(self, row_id: str, *, enabled=True):
        return await self.collection.find_one_and_update(
            {"_id": row_id, "delivery_status": "capturing"},
            {"$set": {"delivery_status": "queued" if enabled else "skipped"}},
            return_document=ReturnDocument.AFTER,
        )

    async def release_stale_captures(self, guild_id: int, channel_id: int | None = None):
        # Avatar fetch is capped at five seconds; a crashed handler cannot hold
        # identity-only history indefinitely. Only recovery promotes old rows.
        threshold = datetime.now(timezone.utc) - timedelta(seconds=15)
        base = {"guild_id": guild_id, "delivery_status": "capturing",
                "occurred_at": {"$lte": threshold}}
        if channel_id is not None:
            await self.collection.update_many({**base, "channel_id": channel_id},
                                              {"$set": {"delivery_status": "queued"}})
            return
        await self.collection.update_many({**base, "channel_id": {"$ne": None}},
                                          {"$set": {"delivery_status": "queued"}})
        await self.collection.update_many({**base, "channel_id": None},
                                          {"$set": {"delivery_status": "skipped"}})

    async def queued(self, guild_id: int, channel_id: int | None = None,
                     limit=100, after: str | None = None):
        query = {"guild_id": guild_id, "delivery_status": "queued"}
        if channel_id is not None:
            query["channel_id"] = channel_id
        if after:
            query["_id"] = {"$gt": after}
        return await self.collection.find(query).sort("_id", 1).limit(limit).to_list(length=limit)

    async def skip_queued(self, row_id: str):
        result = await self.collection.update_one(
            {"_id": row_id, "delivery_status": "queued"},
            {"$set": {"delivery_status": "skipped"}},
        )
        return bool(result.matched_count)

    async def enrich_recent_kick(self, guild_id: int, user_id: int, at: datetime,
                                 display_name: str, username: str, joined_at,
                                 avatar: bytes | None, avatar_type: str | None,
                                 roles: list[str] | None = None):
        row = await self.collection.find_one(
            {"guild_id": guild_id, "user_id": str(user_id), "event_type": "kick",
             "occurred_at": {"$gte": at - timedelta(seconds=30),
                             "$lte": at + timedelta(seconds=30)}},
            {"display_name": 1, "username": 1, "avatar": 1, "joined_at": 1, "roles": 1},
            sort=[("_id", -1)],
        )
        if not row:
            return False
        values = {}
        if row.get("display_name") in ("", str(user_id)):
            values["display_name"] = str(display_name)[:120]
            values["username"] = str(username)[:120]
        if not isinstance(row.get("joined_at"), datetime) and isinstance(joined_at, datetime):
            values["joined_at"] = joined_at
        if not row.get("avatar") and avatar and avatar_type:
            values["avatar"] = avatar
            values["avatar_type"] = avatar_type
        if row.get("roles") is None and roles is not None:
            values["roles"] = [str(role)[:100] for role in roles[:30]]
        if values:
            await self.collection.update_one({"_id": row["_id"], "event_type": "kick"},
                                             {"$set": values})
        return bool(values)

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
        filters = {"guild_id": guild_id, "event_type": kind if kind else {"$in": HISTORY_TYPES}}
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
        "joined_at": row.get("joined_at").replace(tzinfo=row["joined_at"].tzinfo or timezone.utc).isoformat() if isinstance(row.get("joined_at"), datetime) else None,
        "reason": row.get("reason"), "moderator_id": row.get("moderator_id"),
        "details": {k: v for k, v in row["details"].items() if k != "transcript"}
        if isinstance(row.get("details"), dict) else row.get("details"),
    }


class SettingsConflict(Exception):
    pass


class TestRateLimited(Exception):
    pass
