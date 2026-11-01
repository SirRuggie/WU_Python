"""Bounded Standardize manifests; deterministic children never replay effects.

The existing management worker owns each child's claim before Discord transport.
This storage owner materializes just one child at a time with a fresh expiry.
"""

import logging
import hashlib
import json
import time
import uuid
from pymongo.errors import DuplicateKeyError
from utils.member_profiles import member_id

KIND = "member_profile_standardize"
TERMINAL = frozenset(("done", "failed", "uncertain", "stopped"))
MAX_MEMBERS = 10000
MAX_BYTES = 2_000_000
PACE_SECONDS = 3


class ProfileRunStopped(ValueError):
    """A stopped manifest cannot start a new Discord operation."""


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def selected_manifest(preview, selected):
    if not isinstance(preview, list) or len(preview) > MAX_MEMBERS:
        raise ValueError(
            "Member preview exceeds the supported size; nothing was queued."
        )
    if not isinstance(selected, list) or len(set(selected)) != len(selected):
        raise ValueError("Choose members once each.")
    chosen = set(selected)
    known = set()
    result = []
    for item in preview:
        uid = member_id(item["discord_id"])
        if uid in known:
            raise ValueError("Duplicate member in preview.")
        known.add(uid)
        if uid not in chosen:
            continue
        if item.get("skip_reason"):
            raise ValueError("A skipped member cannot be selected.")
        old, new = item.get("old_nickname"), item.get("new_nickname")
        if old is not None and (not isinstance(old, str) or len(old) > 32):
            raise ValueError("Invalid old nickname.")
        if (
            not isinstance(new, str)
            or not 1 <= len(new) <= 32
            or any(ord(c) < 32 or ord(c) == 127 for c in new)
        ):
            raise ValueError("Invalid reviewed nickname.")
        revision = item.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("Save the member profile before standardizing.")
        result.append(
            dict(
                discord_id=uid,
                old_nickname=old,
                new_nickname=new,
                revision=revision,
                **(
                    {"name": str(item["name"])[:100]}
                    if item.get("name")
                    else {}
                ),
            )
        )
    if chosen - known or not result:
        raise ValueError(
            "Choose at least one available member from this preview."
        )
    if len(json.dumps(result).encode()) > MAX_BYTES:
        raise ValueError("Member preview is too large; nothing was queued.")
    return result


class ProfileRuns:
    def __init__(self, mongo):
        self.mongo = mongo
        self.collection = mongo.bot_config

    async def preview(self, *, actor_id, guild_id, rows):
        from datetime import datetime, timezone, timedelta

        actor = member_id(actor_id)
        if (
            len(rows) > MAX_MEMBERS
            or len(json.dumps(rows).encode()) > MAX_BYTES
        ):
            raise ValueError(
                "Full preview exceeds the supported size; nothing was queued."
            )
        nonce = str(uuid.uuid4())
        at = datetime.now(timezone.utc)
        await self.mongo.component_state.create_index(
            "expires_at", name="component_state_expiry", expireAfterSeconds=0
        )
        document = dict(
            _id="member-profile-preview:" + actor,
            type="member_profile_preview",
            component_state=True,
            user_id=actor,
            guild_id=int(guild_id),
            nonce=nonce,
            state="draft",
            rows=rows,
            created_at=at,
            expires_at=at + timedelta(minutes=10),
        )
        await self.mongo.component_state.replace_one(
            {"_id": document["_id"]}, document, upsert=True
        )
        return nonce

    async def confirm(self, *, actor_id, guild_id, nonce, selected):
        from datetime import datetime, timezone

        actor = member_id(actor_id)
        row = await self.mongo.component_state.find_one(
            {
                "_id": "member-profile-preview:" + actor,
                "type": "member_profile_preview",
                "user_id": actor,
                "guild_id": int(guild_id),
                "nonce": nonce,
            }
        )
        if not row:
            raise ValueError(
                "Preview was replaced. Review the complete changes again."
            )
        expiry = row["expires_at"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError(
                "Preview expired. Review the complete changes again."
            )
        items = selected_manifest(row["rows"], selected)
        selection_hash = fingerprint(items)
        key = "member-profile-run:" + fingerprint(
            [actor, str(uuid.UUID(nonce))]
        )
        consumed = await self.mongo.component_state.update_one(
            {"_id": row["_id"], "nonce": nonce, "state": "draft"},
            {
                "$set": {
                    "state": "consumed",
                    "selection_hash": selection_hash,
                    "run_id": key,
                }
            },
        )
        if not consumed.matched_count:
            current = await self.mongo.component_state.find_one(
                {
                    "_id": row["_id"],
                    "nonce": nonce,
                    "state": "consumed",
                    "selection_hash": selection_hash,
                }
            )
            existing = (
                await self.collection.find_one(
                    {
                        "_id": key,
                        "kind": KIND,
                        "user_id": actor,
                        "guild_id": int(guild_id),
                    }
                )
                if current
                else None
            )
            if existing:
                return existing
            raise ValueError(
                "This confirmation was already used. Review current progress or create a new preview; it will not be replayed."
            )
        return await self.create(
            actor_id=actor,
            guild_id=guild_id,
            request_id=nonce,
            preview=row["rows"],
            selected=selected,
        )

    async def create(
        self, *, actor_id, guild_id, request_id, preview, selected
    ):
        actor = member_id(actor_id)
        request_id = str(uuid.UUID(request_id))
        items = selected_manifest(preview, selected)
        payload = dict(user_id=actor, guild_id=int(guild_id), items=items)
        digest = fingerprint(payload)
        key = "member-profile-run:" + fingerprint([actor, request_id])
        # One global paced lane; a second run must wait rather than race members.
        await self.collection.create_index(
            "profile_lane",
            name="member_profile_single_run",
            unique=True,
            partialFilterExpression={"kind": KIND, "state": "queued"},
        )
        await self.prune()
        existing = await self.collection.find_one({"_id": key})
        if existing:
            if existing.get("payload_hash") != digest:
                raise ValueError(
                    "This run identifier already belongs to another selection."
                )
            return existing
        active = await self.collection.find_one(
            {"kind": KIND, "state": "queued"}
        )
        if active:
            raise ValueError(
                "Another Standardize run is still working. Review its progress first."
            )
        row = dict(
            _id=key,
            kind=KIND,
            profile_lane="standardize",
            payload_hash=digest,
            state="queued",
            cursor=0,
            created_at=time.time(),
            next_at=0,
            **payload,
        )
        try:
            await self.collection.insert_one(row)
            logging.getLogger(__name__).info(
                "Management timing stage=queued run=%s members=%s",
                key,
                len(items),
            )
        except DuplicateKeyError:
            old = await self.collection.find_one({"_id": key})
            if not old or old.get("payload_hash") != digest:
                raise ValueError("Run identifier conflict.") from None
            return old
        return row

    async def queued(self):
        return await self.collection.find_one(
            {"kind": KIND, "state": "queued"}, {"_id": 1, "next_at": 1}
        )

    async def advance(self, *, now=None):
        at = time.time() if now is None else now
        await self.prune()
        parent = await self.collection.find_one(
            {"kind": KIND, "state": "queued"}, sort=[("created_at", 1)]
        )
        if not parent:
            return
        if parent.get("stop_requested"):
            await self._settle_stop(parent, at)
            return
        if at < parent.get("next_at", 0):
            return
        index = parent["cursor"]
        if index >= len(parent["items"]):
            await self.collection.update_one(
                {"_id": parent["_id"], "state": "queued", "cursor": index},
                {"$set": {"state": "done", "finished_at": at}},
            )
            await self.prune()
            return
        item = parent["items"][index]
        child_id = parent["_id"] + ":" + str(index)
        child = await self.collection.find_one({"_id": child_id})
        if child:
            if child["status"] in TERMINAL:
                # Pace from the confirmed completion, not from a later scheduler tick.
                next_index = index + 1
                done = next_index >= len(parent["items"])
                changes = dict(
                    cursor=next_index,
                    next_at=child.get("finished_at", at) + PACE_SECONDS,
                )
                if done:
                    changes.update(state="done", finished_at=at)
                await self.collection.update_one(
                    {"_id": parent["_id"], "state": "queued", "cursor": index},
                    {"$set": changes},
                )
                if done:
                    await self.prune()
            # Pending/running/uncertain children are never re-created or reset.
            return
        child = dict(
            _id=child_id,
            kind="manage_web_request",
            parent_id=parent["_id"],
            section="member_profiles",
            action="standardize_one",
            values=item,
            revision=item["revision"],
            user_id=parent["user_id"],
            guild_id=parent["guild_id"],
            status="pending",
            created_at=at,
            expires_at=at + 900,
        )
        try:
            await self.collection.insert_one(child)
        except DuplicateKeyError:
            pass

    async def stop(self, run_id, *, actor_id, guild_id):
        actor = member_id(actor_id)
        query = {
            "_id": run_id,
            "kind": KIND,
            "guild_id": int(guild_id),
        }
        parent = await self.collection.find_one(query)
        if not parent:
            raise ValueError("This run is no longer available.")
        await self.collection.update_one(
            dict(query, state="queued", stop_requested={"$ne": True}),
            {
                "$set": {
                    "stop_requested": True,
                    "stopped_by": actor,
                    "stop_requested_at": time.time(),
                }
            },
        )
        parent = await self.collection.find_one(query)
        if parent.get("state") == "queued" and parent.get("stop_requested"):
            await self._settle_stop(parent, time.time())
        return await self.collection.find_one(query)

    async def _settle_stop(self, parent, at):
        # Keep the single queued lane until the already claimed member finishes.
        await self.collection.update_many(
            {
                "parent_id": parent["_id"],
                "kind": "manage_web_request",
                "status": "pending",
            },
            {
                "$set": {
                    "status": "stopped",
                    "finished_at": at,
                    "message": "Stopped before this member started.",
                }
            },
        )
        running = await self.collection.find_one(
            {
                "parent_id": parent["_id"],
                "kind": "manage_web_request",
                "status": "running",
            }
        )
        if not running:
            await self.collection.update_one(
                {
                    "_id": parent["_id"],
                    "state": "queued",
                    "stop_requested": True,
                },
                {"$set": {"state": "stopped", "finished_at": at}},
            )

    async def prune(self):
        # Keep 20 terminal runs at most, for at most 30 days. Never touch active work.
        rows = (
            await self.collection.find(
                {"kind": KIND, "state": {"$in": ["done", "stopped"]}}
            )
            .sort("finished_at", -1)
            .to_list(length=10001)
        )
        now = time.time()
        cutoff = now - 30 * 86400
        for row in rows:
            uncertain = await self.collection.find_one(
                {
                    "parent_id": row["_id"],
                    "kind": "manage_web_request",
                    "status": "uncertain",
                }
            )
            if (row in rows[:20] or uncertain) and row.get(
                "finished_at", 0
            ) >= cutoff:
                continue
            await self.collection.delete_many(
                {
                    "parent_id": row["_id"],
                    "kind": "manage_web_request",
                    "status": {"$in": list(TERMINAL)},
                }
            )
            await self.collection.delete_one(
                {
                    "_id": row["_id"],
                    "kind": KIND,
                    "state": {"$in": ["done", "stopped"]},
                }
            )

        # Older crashed requests had no completion timestamp. Establish it once
        # before sorting/pruning, retaining the newest uncertain receipt correctly.
        await self.collection.update_many(
            {
                "kind": "manage_web_request",
                "section": "member_profiles",
                "parent_id": {"$exists": False},
                "status": {"$in": list(TERMINAL)},
                "finished_at": None,
            },
            {"$set": {"finished_at": now}},
        )
        standalone = (
            await self.collection.find(
                {
                    "kind": "manage_web_request",
                    "section": "member_profiles",
                    "parent_id": {"$exists": False},
                    "status": {"$in": list(TERMINAL)},
                }
            )
            .sort("finished_at", -1)
            .to_list(length=10001)
        )
        for index, row in enumerate(standalone):
            if (index < 20 or row.get("status") == "uncertain") and row.get(
                "finished_at", 0
            ) >= cutoff:
                continue
            await self.collection.delete_one(
                {
                    "_id": row["_id"],
                    "kind": "manage_web_request",
                    "section": "member_profiles",
                    "parent_id": {"$exists": False},
                    "status": {"$in": list(TERMINAL)},
                }
            )
