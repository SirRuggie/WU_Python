"""Storage owner for one reviewed in-place roster-post update workflow.

A preview has one update transition. Interrupted updates are never replayed;
the existing publishing service remains the only Discord edit path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

KIND = "cwl_roster_post_update"
ACTIVE = ("pending_preview", "previewing", "pending_update", "updating")
PENDING_INDEX = "cwl_post_update_pending"
UPDATE_START_MAX_AGE = timedelta(minutes=5)
UPDATE_EXPIRED_MESSAGE = "Not updated. Preview again."


def now():
    return datetime.now(timezone.utc)


class PostUpdateConflict(ValueError):
    pass


class PostUpdateStore:
    def __init__(self, mongo):
        self.collection = mongo.bot_config
        self.indexes_ready = False

    async def worker_ready(self, guild_id):
        from utils.cwl_web_bridge import worker_id

        row = (
            await self.collection.find_one(
                {"_id": worker_id(guild_id)},
                {
                    "_id": 1,
                    "post_update_protocol": 1,
                    "post_update_ready": 1,
                    "post_update_ready_at": 1,
                    "updated_at": 1,
                },
            )
            or {}
        )
        if (
            type(row.get("post_update_protocol")) is not int
            or row["post_update_protocol"] != 1
            or row.get("post_update_ready") is not True
        ):
            return False
        try:
            stamps = [
                datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                for field in ("updated_at", "post_update_ready_at")
            ]
            return all(0 <= (now() - stamp).total_seconds() < 60 for stamp in stamps)
        except (KeyError, TypeError, ValueError):
            return False

    async def active_claim(
        self, *, workflow_id, guild_id, user_id, season_id, cycle, pool, worker_epoch
    ):
        if (
            not isinstance(workflow_id, str)
            or type(guild_id) is not int
            or guild_id < 1
            or type(user_id) is not int
            or user_id < 1
            or not isinstance(worker_epoch, str)
            or not worker_epoch.strip()
            or not isinstance(cycle, str)
            or pool not in ("main", "lazy")
        ):
            raise ValueError("Invalid claimed post-review scope")
        row = await self.collection.find_one(
            {
                "_id": workflow_id,
                "kind": KIND,
                "guild_id": guild_id,
                "user_id": user_id,
                "season_id": str(season_id),
                "cycle": cycle,
                "pool": pool,
                "worker_epoch": worker_epoch,
            },
            {"_id": 1, "status": 1},
        )
        return bool(row and row["status"] in ("previewing", "updating"))

    async def ensure_indexes(self):
        if self.indexes_ready:
            return
        await self.collection.create_index(
            [("kind", 1), ("guild_id", 1), ("status", 1), ("created_at", 1)],
            name=PENDING_INDEX,
            partialFilterExpression={"kind": KIND, "status": {"$in": list(ACTIVE)}},
        )
        await self.collection.create_index(
            "expires_at",
            name="cwl_post_update_expiry",
            expireAfterSeconds=0,
            partialFilterExpression={"kind": KIND},
        )
        await self.collection.create_index(
            "expires_at",
            name="cwl_post_update_scratch_expiry",
            expireAfterSeconds=0,
            partialFilterExpression={
                "kind": "cwl_campaign_draft",
                "purpose": "post_update",
            },
        )
        self.indexes_ready = True

    async def create(
        self,
        *,
        guild_id,
        user_id,
        season_id,
        cycle,
        pool,
        nonce,
        generation,
        draft_id,
        candidate,
        future_months,
    ):
        if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
            raise ValueError("Invalid post-update review identity")
        if pool not in ("main", "lazy") or type(future_months) is not bool:
            raise ValueError("Choose a roster pool and save scope")
        if (
            type(guild_id) is not int
            or guild_id < 1
            or type(user_id) is not int
            or user_id < 1
        ):
            raise ValueError("An authenticated editor is required")
        if not isinstance(cycle, str) or not re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])", cycle
        ):
            raise ValueError("Choose the campaign month")
        if (
            not re.fullmatch(r"[0-9]{1,18}", str(season_id))
            or not isinstance(generation, str)
            or not 1 <= len(generation) <= 256
        ):
            raise ValueError("Invalid season or campaign generation")
        if not isinstance(draft_id, str) or not 1 <= len(draft_id) <= 256:
            raise ValueError("An owned draft is required")
        if not isinstance(candidate, dict) or set(candidate) != {
            "title",
            "body",
            "buttons",
        }:
            raise ValueError("Only roster text and buttons can change")
        if any(
            not isinstance(candidate[field], str)
            or not candidate[field].strip()
            or len(candidate[field]) > 4000
            for field in ("title", "body")
        ):
            raise ValueError("Check the roster text length")
        if (
            not isinstance(candidate["buttons"], list)
            or len(candidate["buttons"]) > 5
            or len(json.dumps(candidate)) > 20000
        ):
            raise ValueError("Choose up to five link buttons")
        key = f"cwl:post-update:{guild_id}:{user_id}:{nonce}"
        payload = {
            "season_id": str(season_id),
            "cycle": cycle,
            "pool": pool,
            "generation": generation,
            "candidate": candidate,
            "future_months": future_months,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row = {
            "_id": key,
            "kind": KIND,
            "guild_id": guild_id,
            "user_id": user_id,
            **copy.deepcopy(payload),
            "digest": digest,
            "draft_id": draft_id,
            "status": "pending_preview",
            "created_at": now(),
            "updated_at": now(),
            "expires_at": now() + timedelta(days=1),
        }
        await self.ensure_indexes()
        try:
            await self.collection.insert_one(row)
            return row, True
        except DuplicateKeyError:
            previous = await self.owned(
                key, guild_id=guild_id, user_id=user_id, season_id=season_id, pool=pool
            )
            if previous["digest"] != digest:
                raise PostUpdateConflict(
                    "This review identity already belongs to different edits"
                )
            return previous, False

    async def owned(self, key, *, guild_id, user_id, season_id, pool):
        row = await self.collection.find_one(
            {
                "_id": key,
                "kind": KIND,
                "guild_id": int(guild_id),
                "user_id": int(user_id),
                "season_id": str(season_id),
                "pool": pool,
            }
        )
        if not row:
            raise PostUpdateConflict(
                "This post review is unavailable or belongs to another editor"
            )
        return row

    async def pending(self, guild_id, limit=10):
        await self.ensure_indexes()
        return (
            await self.collection.find(
                {
                    "kind": KIND,
                    "guild_id": int(guild_id),
                    "status": {"$in": ["pending_preview", "pending_update"]},
                }
            )
            .hint(PENDING_INDEX)
            .sort("created_at", 1)
            .limit(min(10, max(1, limit)))
            .to_list(length=min(10, max(1, limit)))
        )

    async def claim(self, row, *, runtime_id):
        if (
            not isinstance(runtime_id, str)
            or not runtime_id.strip()
            or len(runtime_id) > 128
        ):
            raise ValueError("A worker process identity is required")
        expected = row["status"]
        if expected not in ("pending_preview", "pending_update"):
            return None
        clock = now()
        query = {"_id": row["_id"], "kind": KIND, "status": expected}
        if expected == "pending_update":
            # Competes atomically with claiming. Missing timestamps from older
            # queued rows fail closed; TTL is retention, not start authority.
            await self.collection.update_one(
                {
                    **query,
                    "$or": [
                        {"update_requested_at": {"$lte": clock - UPDATE_START_MAX_AGE}},
                        {"update_requested_at": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "status": "failed",
                        "error": UPDATE_EXPIRED_MESSAGE,
                        "updated_at": clock,
                        "expires_at": clock + timedelta(days=90),
                    }
                },
            )
            query["update_requested_at"] = {"$gt": now() - UPDATE_START_MAX_AGE}
        status = "previewing" if expected == "pending_preview" else "updating"
        result = await self.collection.update_one(
            query,
            {
                "$set": {
                    "status": status,
                    "worker_epoch": runtime_id,
                    "updated_at": now(),
                },
                "$unset": {"expires_at": ""},
            },
        )
        if not result.matched_count:
            return None
        return await self.collection.find_one({"_id": row["_id"]})

    async def finish(self, row, *, status, **fields):
        if row["status"] not in ("previewing", "updating") or status not in (
            "ready",
            "done",
            "failed",
            "uncertain",
        ):
            raise ValueError("Invalid post-update completion")
        if set(fields) - {
            "target",
            "live_preview",
            "has_changes",
            "draft_preview",
            "message_url",
            "error",
            "error_code",
            "saved_scope",
            "campaign_saved",
            "recurring_saved",
            "save_warning",
        }:
            raise ValueError("Invalid post-update result fields")
        if status == "ready" and not fields.get("target"):
            raise ValueError("A ready preview must have its observed target")
        created = row["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        expiry = (
            created + timedelta(days=1)
            if status == "ready"
            else now() + timedelta(days=90)
        )
        result = await self.collection.update_one(
            {
                "_id": row["_id"],
                "kind": KIND,
                "status": row["status"],
                "worker_epoch": row["worker_epoch"],
            },
            {
                "$set": {
                    "status": status,
                    "updated_at": now(),
                    "expires_at": expiry,
                    **copy.deepcopy(fields),
                }
            },
        )
        return bool(result.matched_count)

    async def request_update(self, row, *, future_months=None):
        """One CAS consumes a preview; double taps return the same workflow."""
        if future_months is None:
            future_months = row["future_months"]
        if type(future_months) is not bool:
            raise ValueError("Choose whether to use the copy for future months")
        if row["status"] in ("pending_update", "updating", "done", "uncertain"):
            return row
        if row.get("has_changes") is False:
            raise PostUpdateConflict("No changes")
        if row["status"] != "ready" or not row.get("target"):
            raise PostUpdateConflict("Preview this post before updating it")
        expiry = row.get("expires_at")
        if not isinstance(expiry, datetime):
            raise PostUpdateConflict("Preview expired. Preview again.")
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now():
            raise PostUpdateConflict("Preview expired. Preview again.")
        await self.collection.update_one(
            {
                "_id": row["_id"],
                "kind": KIND,
                "status": "ready",
                "digest": row["digest"],
            },
            {
                "$set": {
                    "status": "pending_update",
                    "update_requested_at": now(),
                    "updated_at": now(),
                    "future_months": future_months,
                },
                "$unset": {"expires_at": ""},
            },
        )
        return await self.collection.find_one({"_id": row["_id"]})

    async def recover_interrupted(self, *, guild_id, runtime_id):
        """Run once on worker startup; never reset a possible edit to pending."""
        if (
            not isinstance(runtime_id, str)
            or not runtime_id.strip()
            or len(runtime_id) > 128
        ):
            raise ValueError("A worker process identity is required")
        await self.ensure_indexes()
        for old, status, message in (
            ("previewing", "failed", "Worker restarted during preview. Preview again."),
            (
                "updating",
                "uncertain",
                "Not sure it updated. Check the post.",
            ),
        ):
            await self.collection.update_many(
                {
                    "kind": KIND,
                    "guild_id": int(guild_id),
                    "status": old,
                    "worker_epoch": {"$ne": runtime_id},
                },
                {
                    "$set": {
                        "status": status,
                        "error": message,
                        "updated_at": now(),
                        "expires_at": now() + timedelta(days=90),
                    }
                },
            )
