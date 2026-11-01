"""Bounded Standardize manifests; deterministic children never replay effects.

The existing management worker owns each child's claim before Discord transport.
This storage owner materializes just one child at a time with a fresh expiry.
"""

import hashlib
import json
import time
import uuid
from pymongo.errors import DuplicateKeyError
from utils.member_profiles import member_id

KIND = "member_profile_standardize"
TERMINAL = frozenset(("done", "failed", "uncertain"))
MAX_MEMBERS = 10000
MAX_BYTES = 2_000_000
PACE_SECONDS = 3


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
            dict(discord_id=uid, old_nickname=old, new_nickname=new, revision=revision)
        )
    if chosen - known or not result:
        raise ValueError("Choose at least one available member from this preview.")
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
        if len(rows) > MAX_MEMBERS or len(json.dumps(rows).encode()) > MAX_BYTES:
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
            raise ValueError("Preview was replaced. Review the complete changes again.")
        expiry = row["expires_at"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("Preview expired. Review the complete changes again.")
        return await self.create(
            actor_id=actor,
            guild_id=guild_id,
            request_id=nonce,
            preview=row["rows"],
            selected=selected,
        )

    async def create(self, *, actor_id, guild_id, request_id, preview, selected):
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
        active = await self.collection.find_one({"kind": KIND, "state": "queued"})
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
        except DuplicateKeyError:
            old = await self.collection.find_one({"_id": key})
            if not old or old.get("payload_hash") != digest:
                raise ValueError("Run identifier conflict.") from None
            return old
        return row

    async def advance(self, *, now=None):
        at = time.time() if now is None else now
        parent = await self.collection.find_one(
            {"kind": KIND, "state": "queued"}, sort=[("created_at", 1)]
        )
        if not parent or at < parent.get("next_at", 0):
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
                await self.collection.update_one(
                    {"_id": parent["_id"], "state": "queued", "cursor": index},
                    {"$set": {"cursor": index + 1, "next_at": at + PACE_SECONDS}},
                )
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

    async def prune(self):
        # Keep 20 terminal runs at most, for at most30days. Never touch active work.
        rows = (
            await self.collection.find({"kind": KIND, "state": "done"})
            .sort("finished_at", -1)
            .to_list(length=10001)
        )
        cutoff = time.time() - 30 * 86400
        for row in rows:
            if row in rows[:20] and row.get("finished_at", 0) >= cutoff:
                continue
            await self.collection.delete_many(
                {
                    "parent_id": row["_id"],
                    "kind": "manage_web_request",
                    "status": {"$in": list(TERMINAL)},
                }
            )
            await self.collection.delete_one(
                {"_id": row["_id"], "kind": KIND, "state": "done"}
            )
