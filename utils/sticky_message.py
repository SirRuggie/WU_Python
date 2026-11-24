"""Durable sticky-message state, shared by Gauntlet and CWL help.

Discord transport is injected by the task layer. A posting/unknown intent is
never leased or retried: Discord may already have accepted that create.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
BATCH_SIZE = 20


def aware(value: datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return None


@dataclass(frozen=True)
class StickyTarget:
    guild_id: int
    channel_id: int
    # Explicit legacy keys preserve Gauntlet's existing document and receipts.
    state_key: str | None = None
    delete_kind: str = "sticky_message_delete"
    delete_prefix: str | None = None
    require_initial_quiet: bool = True
    require_missing_quiet: bool = True
    history_before_gates: bool = True

    @property
    def key(self) -> str:
        return self.state_key or f"sticky_message:{self.guild_id}:{self.channel_id}"

    def delete_key(self, message_id: int) -> str:
        prefix = self.delete_prefix or f"sticky_message_delete:{self.guild_id}:{self.channel_id}"
        return f"{prefix}:{int(message_id)}"

    @property
    def delete_scope(self) -> dict:
        scope = {"kind": self.delete_kind, "guild_id": self.guild_id}
        if self.delete_prefix is None:
            scope["channel_id"] = self.channel_id
        return scope


class StickyMessage:
    """One owner for sticky state, create claims and durable deletion receipts."""

    def __init__(self, target: StickyTarget, *, quiet: timedelta, clock=None):
        self.target = target
        self.quiet = quiet
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def read(self, mongo) -> dict:
        return await mongo.bot_config.find_one({"_id": self.target.key}) or {}

    async def note_human(self, mongo, at: datetime) -> None:
        await mongo.bot_config.update_one(
            {"_id": self.target.key},
            {"$max": {"last_human_at": at}, "$setOnInsert": {
                "enabled": True, "guild_id": self.target.guild_id,
            }},
            upsert=True,
        )

    async def recover(self, mongo, message_id: int, posted_at: datetime) -> None:
        """Record an observed successful create without sending another one."""
        row = await self.read(mongo)
        previous = int(row.get("sticky_message_id") or 0)
        await mongo.bot_config.update_one(
            {"_id": self.target.key},
            {"$set": {
                "sticky_state": "posted", "sticky_message_id": int(message_id),
                "sticky_posted_at": posted_at,
                "pending_sticky_delete_id": previous if previous != int(message_id) else 0,
            }, "$unset": {"sticky_token": ""}},
        )

    async def queue_delete(self, mongo, message_id: int, at: datetime) -> None:
        await mongo.bot_config.update_one(
            {"_id": self.target.delete_key(message_id)},
            {"$setOnInsert": {
                **self.target.delete_scope, "message_id": int(message_id),
                "delete_at": at, "attempts": 0,
            }},
            upsert=True,
        )

    async def drain_pending(self, mongo, now: datetime) -> None:
        row = await self.read(mongo)
        previous = int(row.get("pending_sticky_delete_id") or 0)
        if not previous:
            return
        await self.queue_delete(mongo, previous, now)
        await mongo.bot_config.update_one(
            {"_id": self.target.key, "pending_sticky_delete_id": previous},
            {"$unset": {"pending_sticky_delete_id": ""}},
        )

    async def drain_deletes(self, transport, mongo, now: datetime) -> None:
        # This also validates cleanup while the feature is disabled.
        if await transport.validated_channel() is None:
            return
        cursor = mongo.bot_config.find({
            **self.target.delete_scope, "delete_at": {"$lte": now},
        }).sort("delete_at", 1).limit(BATCH_SIZE)
        for row in await cursor.to_list(length=BATCH_SIZE):
            key = row["_id"]
            try:
                await transport.delete(int(row["message_id"]))
            except Exception:
                attempts = min(int(row.get("attempts", 0)) + 1, 8)
                await mongo.bot_config.update_one({"_id": key}, {"$set": {
                    "attempts": attempts,
                    "delete_at": now + timedelta(minutes=min(2 ** attempts, 60)),
                }})
                log.exception("Sticky message deletion delayed: %s", key)
                continue
            await mongo.bot_config.delete_one({"_id": key})

    async def refresh(self, transport, mongo, now: datetime, *, enabled: bool = True) -> None:
        if not enabled:
            return
        channel = await transport.validated_channel()
        if channel is None:
            return
        row = await self.read(mongo)
        if "last_human_at" not in row:
            latest = await transport.latest_human_at()
            await self.note_human(mongo, latest or now)
            row = await self.read(mongo)

        previous = row.get("sticky_message_id")
        last_human = aware(row.get("last_human_at")) or now
        newest = getattr(channel, "last_message_id", None)
        if previous and newest and int(newest) == int(previous):
            return
        if self.target.history_before_gates:
            # A restart may miss gateway events. Read history before deciding
            # that only bots buried a sticky, or that humans are still quiet.
            latest = await transport.latest_human_at()
            if latest and latest > last_human:
                await self.note_human(mongo, latest)
                last_human = latest
        if previous:
            try:
                missing = not await transport.message_exists(int(previous))
            except Exception:
                log.exception("Sticky verification failed: %s", self.target.key)
                return
            if not missing:
                if now - last_human < self.quiet:
                    return
                posted = aware(row.get("sticky_posted_at"))
                if posted and last_human <= posted:
                    return
            elif self.target.require_missing_quiet and now - last_human < self.quiet:
                return
        elif self.target.require_initial_quiet and now - last_human < self.quiet:
            return

        latest = await transport.latest_human_at()
        if latest and latest > last_human:
            await self.note_human(mongo, latest)
            last_human = latest
            if (previous or self.target.require_initial_quiet) and now - latest < self.quiet:
                return

        # Atomic durable intent. A concurrent sweep or human activity observed
        # before this claim invalidates this candidate rather than posting twice.
        token = uuid.uuid4().hex
        claimed = await mongo.bot_config.update_one(
            {"_id": self.target.key, "sticky_state": {"$nin": ["posting", "unknown"]},
             "sticky_message_id": previous, "last_human_at": last_human},
            {"$set": {"sticky_state": "posting", "sticky_token": token}},
        )
        if not claimed.matched_count:
            return
        try:
            message = await transport.create()
        except Exception:
            await mongo.bot_config.update_one(
                {"_id": self.target.key, "sticky_token": token},
                {"$set": {"sticky_state": "unknown"}},
            )
            log.exception("Sticky create outcome unknown; automatic retry suppressed: %s", self.target.key)
            return
        await mongo.bot_config.update_one(
            {"_id": self.target.key, "sticky_token": token},
            {"$set": {
                "sticky_state": "posted", "sticky_message_id": int(message.id),
                "sticky_posted_at": aware(getattr(message, "created_at", None)) or self.clock(),
                "pending_sticky_delete_id": int(previous) if previous else 0,
            }, "$unset": {"sticky_token": ""}},
        )
        await self.drain_pending(mongo, now)
