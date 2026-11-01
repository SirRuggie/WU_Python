"""One Mongo storage owner for declaration destinations, reviews and send receipts.

No notification retry or restart resume exists. A new process can close an older
process's unfinished claim as uncertain, preserving the chunk currently in flight.
"""

from __future__ import annotations

import copy
import time
from uuid import uuid4
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

LANE_KIND = "declaration_ping_lane"
PREVIEW_KIND = "declaration_ping_preview"
COOLDOWN = 300


class PingConflict(ValueError):
    pass


def identity(value):
    value = str(value)
    if (
        not value.isascii()
        or not value.isdigit()
        or not 15 <= len(value) <= 22
        or int(value) <= 0
    ):
        raise ValueError("Invalid Discord identity")
    return value


class DeclarationPingStore:
    def __init__(self, mongo, guild_id):
        collection = mongo.bot_config
        self.collection = (
            collection.with_options(write_concern=WriteConcern(w="majority", j=True))
            if hasattr(collection, "with_options")
            else collection
        )
        self.guild_id = int(identity(guild_id))

    def key(self, pool):
        if pool not in ("main", "lazy"):
            raise ValueError("Choose Main or Lazy")
        return f"declaration-ping:{self.guild_id}:{pool}"

    def empty(self, pool):
        return dict(
            _id=self.key(pool),
            kind=LANE_KIND,
            guild_id=self.guild_id,
            pool=pool,
            revision=0,
            channel=None,
            active=None,
            active_test=None,
            history=[],
            last_attempt_at=0,
        )

    async def read(self, pool):
        return await self.collection.find_one(
            {"_id": self.key(pool), "kind": LANE_KIND, "guild_id": self.guild_id}
        ) or self.empty(pool)

    async def _ensure(self, pool):
        try:
            await self.collection.insert_one(self.empty(pool))
        except DuplicateKeyError:
            row = await self.collection.find_one({"_id": self.key(pool)})
            if (
                not row
                or row.get("kind") != LANE_KIND
                or row.get("guild_id") != self.guild_id
            ):
                raise PingConflict(
                    "The declaration storage identity is already owned by another record"
                )

    async def configure(
        self, pool, channel_id, name, actor_id, expected_revision, *, now=None
    ):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("A valid channel revision is required")
        channel_id, actor_id = identity(channel_id), identity(actor_id)
        await self._ensure(pool)
        result = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "revision": expected_revision,
                "active": None,
                "active_test": None,
            },
            {
                "$set": {
                    "channel": {"id": channel_id, "name": str(name)[:100]},
                    "updated_by": actor_id,
                    "updated_at": time.time() if now is None else now,
                },
                "$inc": {"revision": 1},
            },
        )
        if not result.matched_count:
            raise PingConflict(
                "The channel changed or a send is in progress. Reload before saving."
            )
        return await self.read(pool)

    async def preview(
        self,
        pool,
        actor_id,
        season_id,
        groups,
        version,
        fingerprint,
        revision,
        *,
        test_channel=None,
        actor_name="Discord staff member",
        now=None,
    ):
        at = time.time() if now is None else now
        actor_id = identity(actor_id)
        lane = await self.read(pool)
        if lane["revision"] != revision or (
            not lane["channel"] and test_channel is None
        ):
            raise PingConflict("The posting channel changed. Review again.")
        if test_channel is not None:
            identity(test_channel.get("id"))
            await self._ensure(pool)
        token = uuid4().hex
        row = dict(
            _id="declaration-preview:" + token,
            token=token,
            kind=PREVIEW_KIND,
            guild_id=self.guild_id,
            pool=pool,
            actor_id=actor_id,
            actor_name=str(actor_name)[:100],
            season_id=int(season_id),
            groups=copy.deepcopy(groups),
            version=version,
            fingerprint=fingerprint,
            channel=test_channel if test_channel is not None else lane["channel"],
            mode="test" if test_channel is not None else "live",
            revision=revision,
            created_at=at,
            expires_at=at + 300,
            used=False,
        )
        await self.collection.delete_many(
            {"kind": PREVIEW_KIND, "guild_id": self.guild_id, "expires_at": {"$lt": at}}
        )
        await self.collection.insert_one(row)
        return row

    async def review(self, pool, actor_id, season_id, token, *, now=None):
        at = time.time() if now is None else now
        if (
            not isinstance(token, str)
            or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
        ):
            raise ValueError("Review this ping before sending")
        row = await self.collection.find_one(
            {
                "_id": "declaration-preview:" + token,
                "kind": PREVIEW_KIND,
                "guild_id": self.guild_id,
                "pool": pool,
                "actor_id": identity(actor_id),
                "season_id": int(season_id),
            }
        )
        if not row or row["expires_at"] <= at or row["used"]:
            raise PingConflict(
                "This review expired or was already used. Check its receipt before reviewing again."
            )
        return row

    async def receipt(self, pool, token):
        lane = await self.read(pool)
        if lane["active"] and lane["active"]["token"] == token:
            return lane["active"]
        return next((row for row in lane["history"] if row["token"] == token), None)

    async def claim(
        self,
        pool,
        actor_id,
        season_id,
        token,
        fingerprint,
        plan,
        runtime,
        *,
        send_again=False,
        now=None,
    ):
        at = time.time() if now is None else now
        prior = await self.receipt(pool, token)
        if prior:
            if prior["actor_id"] != identity(actor_id) or prior["season_id"] != int(
                season_id
            ):
                raise PingConflict("This review belongs to another sender")
            return False, prior
        review = await self.review(pool, actor_id, season_id, token, now=at)
        if review.get("mode", "live") != "live":
            raise PingConflict("A test review cannot authorize real pings")
        if review["fingerprint"] != fingerprint:
            raise PingConflict(
                "Arrivals or assignments changed. Review the fresh list before sending."
            )
        lane = await self.read(pool)
        if lane["last_attempt_at"] and not send_again:
            raise PingConflict(
                "Review Send again deliberately before sending another ping"
            )
        if lane["last_attempt_at"] and at < lane["last_attempt_at"] + COOLDOWN:
            raise PingConflict("Wait for the five-minute pool cooldown")
        active = dict(
            token=token,
            actor_id=identity(actor_id),
            actor_name=review.get("actor_name", "Discord staff member"),
            season_id=int(season_id),
            publication_version=review["version"],
            channel=review["channel"],
            created_at=at,
            state="sending",
            pool=pool,
            count=sum(len(g["accounts"]) for g in review["groups"]),
            unlinked=sum(len(g["unlinked"]) for g in review["groups"]),
            chunks=len(plan),
            plan=copy.deepcopy(plan),
            next=0,
            attempting=None,
            posted=[],
            runtime=runtime,
        )
        result = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "active": None,
                "active_test": None,
                "revision": review["revision"],
                "$or": [
                    {"last_attempt_at": 0},
                    {"last_attempt_at": {"$lte": at - COOLDOWN}},
                ],
            },
            {"$set": {"active": active}},
        )
        if not result.matched_count:
            replay = await self.receipt(pool, token)
            if (
                replay
                and replay["actor_id"] == identity(actor_id)
                and replay["season_id"] == int(season_id)
            ):
                return False, replay
            raise PingConflict(
                "Another send is running, the channel changed, or cooldown is active"
            )
        consumed = await self.collection.update_one(
            {"_id": review["_id"], "used": False}, {"$set": {"used": True}}
        )
        if not consumed.matched_count:
            await self.finish(
                pool, token, "failed", "The review was already consumed", now=at
            )
            raise PingConflict("This review was already used")
        return True, active

    async def consume_test(
        self, pool, actor_id, season_id, token, fingerprint, *, runtime="test", now=None
    ):
        row = await self.review(pool, actor_id, season_id, token, now=now)
        if row.get("mode") != "test":
            raise PingConflict("Review a no-ping test separately")
        if row["fingerprint"] != fingerprint:
            raise PingConflict("Arrivals changed. Review the test again.")
        reserved = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "active": None,
                "active_test": None,
                "revision": row["revision"],
            },
            {"$set": {"active_test": {"token": token, "runtime": runtime}}},
        )
        if not reserved.matched_count:
            raise PingConflict("Another ping or test is running for this pool")
        result = await self.collection.update_one(
            {"_id": row["_id"], "used": False}, {"$set": {"used": True}}
        )
        if not result.matched_count:
            await self.release_test(pool, token)
            raise PingConflict("This test review was already used")
        return (
            row  # Only an in-flight lock; no receipt, history or cooldown for a test.
        )

    async def release_test(self, pool, token):
        await self.collection.update_one(
            {"_id": self.key(pool), "active_test.token": token},
            {"$set": {"active_test": None}},
        )

    async def begin_chunk(self, pool, token, index):
        result = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "active.token": token,
                "active.next": index,
                "active.attempting": None,
            },
            {"$set": {"active.attempting": index}},
        )
        if not result.matched_count:
            raise PingConflict("This send no longer owns the next chunk")

    async def posted(self, pool, token, index, message_id):
        result = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "active.token": token,
                "active.next": index,
                "active.attempting": index,
            },
            {
                "$push": {
                    "active.posted": {
                        "chunk": index,
                        "message_id": identity(message_id),
                    }
                },
                "$set": {"active.attempting": None},
                "$inc": {"active.next": 1},
            },
        )
        if not result.matched_count:
            raise PingConflict(
                "Delivery accepted, but its receipt could not be confirmed. Do not retry."
            )

    async def rejected(self, pool, token, index):
        await self.collection.update_one(
            {"_id": self.key(pool), "active.token": token, "active.attempting": index},
            {"$set": {"active.attempting": None}},
        )

    async def finish(self, pool, token, state, error=None, *, now=None):
        at = time.time() if now is None else now
        lane = await self.read(pool)
        active = lane["active"]
        if not active or active["token"] != token:
            return await self.receipt(pool, token)
        receipt = {k: v for k, v in active.items() if k not in ("plan", "runtime")}
        receipt.update(
            state=state, error=str(error)[:500] if error else None, finished_at=at
        )
        changes = {"active": None}
        if active["posted"] or active["attempting"] is not None:
            changes["last_attempt_at"] = at
        result = await self.collection.update_one(
            {
                "_id": self.key(pool),
                "active.token": token,
                "active.next": active["next"],
                "active.attempting": active["attempting"],
            },
            {
                "$set": changes,
                "$push": {"history": {"$each": [receipt], "$slice": -20}},
            },
        )
        if not result.matched_count:
            raise PingConflict("Delivery progress changed while finalizing its receipt")
        return receipt

    async def recover_other_process(self, pool, runtime, *, now=None):
        lane = await self.read(pool)
        test = lane.get("active_test")
        if test and test["runtime"] != runtime:
            await self.release_test(pool, test["token"])
        active = lane["active"]
        if active and active["runtime"] != runtime:
            await self.finish(
                pool,
                active["token"],
                "uncertain",
                "The previous process stopped. Inspect posted IDs and the in-flight chunk; no retry was attempted.",
                now=now,
            )
