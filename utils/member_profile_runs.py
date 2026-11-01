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
                **({"name": str(item["name"])[:100]} if item.get("name") else {}),
            )
        )
    if chosen - known or not result:
        raise ValueError("Choose at least one available member from this preview.")
    if len(json.dumps(result).encode()) > MAX_BYTES:
        raise ValueError("Member preview is too large; nothing was queued.")
    return result


_LAST_PRUNE = {}


def role_manifest(preview, selected):
    """Normalize only the server-reviewed single-role selection."""
    if not isinstance(preview, list) or not 1 <= len(preview) <= MAX_MEMBERS:
        raise ValueError("Choose a bounded reviewed selection.")
    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) != len(set(selected))
    ):
        raise ValueError("Choose each member once.")
    chosen = set(selected)
    known, result, operation = set(), [], None
    for row in preview:
        if not isinstance(row, dict):
            raise ValueError("Invalid role preview.")
        uid = member_id(row.get("discord_id"))
        if uid in known:
            raise ValueError("Duplicate member in preview.")
        known.add(uid)
        if uid not in chosen:
            continue
        role = member_id(row.get("role_id"))
        action = row.get("operation")
        expected = row.get("expected_role_ids")
        if (
            action not in ("add", "remove")
            or row.get("bot") is not False
            or type(row.get("protected", False)) is not bool
        ):
            raise ValueError("Bots and unreviewed changes cannot be selected.")
        if (
            not isinstance(expected, list)
            or len(expected) > 250
            or len(set(expected)) != len(expected)
        ):
            raise ValueError("Invalid reviewed member roles.")
        expected = sorted(member_id(value) for value in expected)
        if operation is None:
            operation = (role, action)
        if operation != (role, action):
            raise ValueError("Review one role action at a time.")
        result.append(
            dict(
                discord_id=uid,
                role_id=role,
                operation=action,
                expected_role_ids=expected,
                bot=False,
                protected=row.get("protected", False),
                revision=0,
            )
        )
    if chosen != {row["discord_id"] for row in result}:
        raise ValueError("Selection no longer matches the review.")
    if len(json.dumps(result).encode()) > MAX_BYTES:
        raise ValueError("Reviewed role change is too large.")
    return result


def run_manifest(preview, selected, run_type):
    if run_type == "roles":
        return role_manifest(preview, selected)
    if run_type != "profiles":
        raise ValueError("Unknown member change.")
    return selected_manifest(preview, selected)


class ProfileRuns:
    def __init__(self, mongo):
        self.mongo = mongo
        self.collection = mongo.bot_config

    async def preview(self, *, actor_id, guild_id, rows, run_type="profiles"):
        from datetime import datetime, timezone, timedelta

        actor = member_id(actor_id)
        if run_type not in ("profiles", "roles"):
            raise ValueError("Unknown member change.")
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
            run_type=run_type,
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

    async def confirm(
        self,
        *,
        actor_id,
        guild_id,
        nonce,
        selected,
        run_type="profiles",
        protected_confirmed=False,
    ):
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
        if not row or row.get("run_type", "profiles") != run_type:
            raise ValueError("Preview was replaced. Review the complete changes again.")
        expiry = row["expires_at"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("Preview expired. Review the complete changes again.")
        items = run_manifest(row["rows"], selected, run_type)
        if (
            run_type == "roles"
            and any(item["protected"] for item in items)
            and protected_confirmed is not True
        ):
            raise ValueError("Confirm this protected role before changing it.")
        selection_hash = fingerprint(items)
        key = "member-profile-run:" + fingerprint([actor, str(uuid.UUID(nonce))])
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
            run_type=run_type,
            protected_confirmed=protected_confirmed,
        )

    async def create(
        self,
        *,
        actor_id,
        guild_id,
        request_id,
        preview,
        selected,
        run_type="profiles",
        protected_confirmed=False,
    ):
        actor = member_id(actor_id)
        request_id = str(uuid.UUID(request_id))
        items = run_manifest(preview, selected, run_type)
        if (
            run_type == "roles"
            and any(item["protected"] for item in items)
            and protected_confirmed is not True
        ):
            raise ValueError("Confirm this protected role before changing it.")
        payload = dict(user_id=actor, guild_id=int(guild_id), items=items)
        if run_type == "roles":
            payload["run_type"] = "roles"
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
                "Another member change run is still working. Review its progress first."
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

    async def ensure_work_index(self):
        await self.collection.create_index(
            [("kind", 1), ("status", 1), ("state", 1)],
            name="management_ready_work",
            partialFilterExpression={
                "$or": [
                    {"kind": "manage_web_request", "status": "pending"},
                    {"kind": KIND, "state": "queued"},
                ]
            },
        )

    async def ready_work(self):
        return await self.collection.find_one(
            {
                "$or": [
                    {"kind": "manage_web_request", "status": "pending"},
                    {"kind": KIND, "state": "queued"},
                ]
            },
            {"_id": 1, "kind": 1, "next_at": 1},
            hint="management_ready_work",
        )

    async def queued(self):
        return await self.collection.find_one(
            {"kind": KIND, "state": "queued"}, {"_id": 1, "next_at": 1}
        )

    async def advance(self, *, now=None):
        at = time.time() if now is None else now
        prune_started = time.perf_counter()
        await self.prune_throttled(at)
        prune_ms = 1000 * (time.perf_counter() - prune_started)
        parent_started = time.perf_counter()
        parent = await self.collection.find_one(
            {"kind": KIND, "state": "queued"}, sort=[("created_at", 1)]
        )
        if not parent:
            return
        logging.getLogger(__name__).info(
            "Management timing stage=profile_parent run=%s elapsed_ms=%.2f prune_ms=%.2f next_in_ms=%.2f cursor=%s",
            parent.get("_id", "-"),
            1000 * (time.perf_counter() - parent_started),
            prune_ms,
            1000 * max(0, parent.get("next_at", 0) - at),
            parent.get("cursor"),
        )
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
        child = await self.timed(
            "profile_child_lookup",
            self.collection.find_one({"_id": child_id}),
            parent["_id"],
        )
        if child:
            if child["status"] in TERMINAL:
                # Pace from the confirmed completion, not from a later scheduler tick.
                next_index = index + 1
                done = next_index >= len(parent["items"])
                changes = dict(
                    cursor=next_index,
                    next_at=max(
                        child.get("finished_at", at) + PACE_SECONDS,
                        child.get("retry_not_before", 0),
                    ),
                )
                if done:
                    changes.update(state="done", finished_at=at)
                await self.timed(
                    "profile_cursor",
                    self.collection.update_one(
                        {"_id": parent["_id"], "state": "queued", "cursor": index},
                        {"$set": changes},
                    ),
                    parent["_id"],
                )
                if done:
                    await self.prune()
            # Pending/running/uncertain children are never re-created or reset.
            return
        child = dict(
            _id=child_id,
            kind="manage_web_request",
            parent_id=parent["_id"],
            section="roles" if parent.get("run_type") == "roles" else "member_profiles",
            action=(
                "bulk_one" if parent.get("run_type") == "roles" else "standardize_one"
            ),
            values=item,
            revision=item["revision"],
            user_id=parent["user_id"],
            guild_id=parent["guild_id"],
            status="pending",
            created_at=at,
            expires_at=at + 900,
        )
        try:
            await self.timed(
                "profile_child_insert", self.collection.insert_one(child), parent["_id"]
            )
        except DuplicateKeyError:
            pass

    async def stop(self, run_id, *, actor_id, guild_id, run_type="profiles"):
        actor = member_id(actor_id)
        query = {
            "_id": run_id,
            "kind": KIND,
            "guild_id": int(guild_id),
            "run_type": "roles" if run_type == "roles" else {"$ne": "roles"},
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
            await self.prune()

    async def record_role_change(self, row, *, before, after):
        receipt = dict(
            actor_id=row["user_id"],
            discord_id=row["values"]["discord_id"],
            role_id=row["values"]["role_id"],
            operation=row["values"]["operation"],
            before=bool(before),
            after=bool(after),
            confirmed_at=time.time(),
        )
        saved = await self.collection.update_one(
            {"_id": row["_id"], "kind": "manage_web_request", "status": "running"},
            {"$set": {"role_audit": receipt}},
        )
        if not saved.matched_count:
            from utils.member_profiles import ProfileOutcomeUncertain

            raise ProfileOutcomeUncertain(
                "Role changed but its receipt could not be confirmed. Refresh the person before trying again."
            )
        return receipt

    async def get(self, run_id, *, guild_id, run_type="profiles"):
        parent = await self.collection.find_one(
            {
                "_id": run_id,
                "kind": KIND,
                "guild_id": int(guild_id),
                "run_type": "roles" if run_type == "roles" else {"$ne": "roles"},
            }
        )
        if not parent:
            raise ValueError("This run is no longer available.")
        return parent

    async def status(self, run_id, *, guild_id, run_type="profiles"):
        parent = await self.get(run_id, guild_id=guild_id, run_type=run_type)
        children = await self.collection.find(
            {"parent_id": run_id, "kind": "manage_web_request"}
        ).to_list(length=MAX_MEMBERS)
        return parent, children

    async def reviewed_child(self, row, *, run_type):
        parent = await self.get(
            row.get("parent_id"), guild_id=row["guild_id"], run_type=run_type
        )
        if parent.get("stop_requested"):
            raise ProfileRunStopped("Stopped before this member started.")
        index = parent.get("cursor", -1)
        if (
            parent.get("state") != "queued"
            or parent.get("user_id") != row.get("user_id")
            or not 0 <= index < len(parent["items"])
            or row["_id"] != parent["_id"] + ":" + str(index)
            or parent["items"][index] != row.get("values")
        ):
            raise ValueError("This member does not match the reviewed selection.")
        return parent

    async def timed(self, stage, operation, run="-"):
        started = time.perf_counter()
        try:
            return await operation
        finally:
            logging.getLogger(__name__).info(
                "Management timing stage=%s run=%s elapsed_ms=%.2f",
                stage,
                run,
                1000 * (time.perf_counter() - started),
            )

    async def summaries(self, guild_id, *, active_only=False, run_type="profiles"):
        query = {
            "kind": KIND,
            "guild_id": guild_id,
            "run_type": "roles" if run_type == "roles" else {"$ne": "roles"},
        }
        if active_only:
            query["state"] = "queued"
        # Manifests contain every member's reviewed data. The picker needs none
        # of those large arrays, nor child receipts.
        projection = {
            "_id": 1,
            "state": 1,
            "user_id": 1,
            "stopped_by": 1,
            "stop_requested": 1,
            "created_at": 1,
        }
        return await self.timed(
            "profile_history_query",
            self.collection.find(query, projection)
            .sort("created_at", -1)
            .to_list(length=21),
        )

    async def prune_throttled(self, at):
        # One process-wide cadence per collection; terminal transitions still prune.
        key = id(self.mongo)
        previous = _LAST_PRUNE.get(key)
        if previous is not None and at - previous < 60:
            return
        _LAST_PRUNE[key] = at
        if len(_LAST_PRUNE) > 32:
            _LAST_PRUNE.pop(next(iter(_LAST_PRUNE)))
        await self.prune()

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
            if (row in rows[:20] or uncertain) and row.get("finished_at", 0) >= cutoff:
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
