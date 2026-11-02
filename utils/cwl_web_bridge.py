"""Durable web-to-bot handoff for native CWL roster announcements."""

from __future__ import annotations

import re
import logging
import time
from utils.manage_poll_cache import timed_step
from datetime import datetime, timezone
from typing import Awaitable, Callable

from pymongo.errors import DuplicateKeyError

from utils import cwl_campaign

REQUEST_KIND = "cwl_web_send_request"
WORKER_KIND = "cwl_web_worker"
_CYCLE = re.compile(r"20\d\d-(?:0[1-9]|1[0-2])\Z")
_POOLS = frozenset(("main", "lazy"))
# One bounded repair attempt per unchanged generation and process. No new poll
# or durable writes: configuration changes bypass this cooldown immediately.
_schedule_repair_attempts: dict[int, tuple[str, str, float]] = {}
SCHEDULE_REPAIR_RETRY_SECONDS = 300


class BridgeConflict(ValueError):
    """The reviewed request no longer matches native campaign state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_id(guild_id: int, cycle: str, pool: str) -> str:
    if not _CYCLE.fullmatch(cycle) or pool not in _POOLS:
        raise ValueError("A valid campaign month and pool are required")
    return f"cwl:web-send:{int(guild_id)}:{cycle}:{pool}"


def worker_id(guild_id: int) -> str:
    return f"cwl:web-worker:{int(guild_id)}"


def campaign_generation(loaded: dict) -> str:
    """Match the generation passed to the existing campaign sender."""
    version = f"{int(loaded.get('defaults_revision', 0))}:{int(loaded.get('revision', 0))}"
    recurring = loaded.get("recurring_version")
    return f"{version}:{recurring}" if recurring else version


def _variant(loaded: dict, pool: str) -> dict:
    roster = loaded["campaign"].get("messages", {}).get("roster", {})
    item = roster.get("variants", {}).get(pool, {})
    if not roster.get("enabled", True) or not item.get("enabled", True):
        raise BridgeConflict("The native roster announcement is disabled")
    if not item.get("destination_channel_id"):
        raise BridgeConflict("The native roster channel is not configured")
    return item


def native_receipt(loaded: dict, pool: str) -> dict | None:
    occurrence = cwl_campaign.occurrence_id(loaded["cycle"], "roster", pool)
    receipts = [
        item for item in loaded.get("deliveries", ())
        if item.get("occurrence_id") == occurrence and item.get("status") == "sent"
    ]
    if receipts:
        return receipts[-1]
    if occurrence in loaded.get("sent_occurrences", ()):
        return {"occurrence_id": occurrence, "status": "sent"}
    return None


async def queue_roster_send(
    mongo,
    *,
    guild_id: int,
    cycle: str,
    pool: str,
    publication_version: int,
    expected_generation: str,
    expected_channel_id: int,
    requested_by: int,
    retry_failed: bool = False,
    sequence_id: str | None = None,
) -> dict:
    """Queue one reviewed native occurrence; never queue a second sent post."""
    key = request_id(guild_id, cycle, pool)
    if sequence_id is not None and (
        not isinstance(sequence_id, str) or not re.fullmatch(r'[a-f0-9]{24}', sequence_id)
    ):
        raise ValueError("Invalid image sequence ID")
    if publication_version < 1 or requested_by < 1 or expected_channel_id < 1:
        raise ValueError("A published roster, actor, and channel are required")
    loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
    if campaign_generation(loaded) != expected_generation:
        raise BridgeConflict("Native campaign settings changed; review again")
    channel = int(_variant(loaded, pool)["destination_channel_id"])
    if channel != expected_channel_id:
        raise BridgeConflict("Native campaign channel changed; review again")
    if native_receipt(loaded, pool) or await _pending_ledger_receipt(
        mongo, guild_id, cycle, pool,
    ):
        raise BridgeConflict("This pool's native roster announcement was already sent")
    occurrence = cwl_campaign.occurrence_id(cycle, "roster", pool)
    if occurrence in loaded.get("uncertain_occurrences", ()):
        raise BridgeConflict("This pool's native delivery is uncertain; reconcile before retrying")

    stamp = _now()
    existing = await mongo.bot_config.find_one({"_id": key})
    if existing:
        if not retry_failed or existing.get("status") not in {"failed", "stale"}:
            raise BridgeConflict("A request for this pool and campaign month already exists")
        result = await mongo.bot_config.update_one(
            {"_id": key, "status": existing["status"]},
            {"$set": {
                "status": "pending", "publication_version": publication_version,
                "generation": expected_generation, "channel_id": channel,
                "requested_by": requested_by, "updated_at": stamp,
                "sequence_id": sequence_id,
            }, "$unset": {"error": "", "receipt": "", "started_at": ""}},
        )
        if not result.matched_count:
            raise BridgeConflict("Request status changed; refresh before retrying")
    else:
        try:
            result = await mongo.bot_config.update_one(
                {"_id": key},
                {"$setOnInsert": {
                    "kind": REQUEST_KIND, "guild_id": int(guild_id), "cycle": cycle,
                    "pool": pool, "status": "pending",
                    "publication_version": publication_version,
                    "generation": expected_generation, "channel_id": channel,
                    "requested_by": requested_by, "created_at": stamp,
                    "sequence_id": sequence_id,
                    "updated_at": stamp,
                }},
                upsert=True,
            )
        except DuplicateKeyError as exc:
            raise BridgeConflict("A request for this pool and campaign month already exists") from exc
        if not result.upserted_id:
            raise BridgeConflict("A request for this pool and campaign month already exists")
    return await mongo.bot_config.find_one({"_id": key})


async def reopen_deleted_request(mongo, *, guild_id, cycle, pool, receipt, actor_id):
    """Reopen only the staff-confirmed deleted receipt, never an uncertain send."""
    key = request_id(guild_id, cycle, pool)
    row = await mongo.bot_config.find_one({"_id": key})
    if row and row.get("status") in {"pending", "sending", "uncertain"}:
        raise BridgeConflict("Resolve the in-progress announcement before resending")
    if await _pending_ledger_receipt(mongo, guild_id, cycle, pool):
        raise BridgeConflict("The announcement receipt is still being saved; retry later")
    archived = await cwl_campaign.reopen_deleted_roster_delivery(
        mongo, guild_id, cycle, pool, channel_id=int(receipt['channel_id']),
        message_id=int(receipt['message_id']), actor_id=int(actor_id),
    )
    if row:
        if row.get('deleted_message_id') == str(receipt['message_id']) and row.get('status') == 'failed':
            return archived
        result = await mongo.bot_config.update_one(
            {'_id': key, 'status': row.get('status')},
            {'$set': {'status': 'failed', 'deleted_message_id': str(receipt['message_id']),
                      'error': 'Previous announcement was deleted; explicit resend confirmed',
                      'updated_at': _now()},
             '$push': {'previous_receipts': {'$each': [archived]}}},
        )
        if not result.matched_count:
            raise BridgeConflict('Announcement request changed; refresh before resending')
    return archived


async def _pending_ledger_receipt(mongo, guild_id: int, cycle: str, pool: str) -> dict | None:
    collection = getattr(mongo, "cwl_pending_reminders", None)
    if collection is None:
        return None
    job_id = f"cwl_campaign:{int(guild_id)}:{cycle}:roster:{pool}"
    row = await collection.find_one({"_id": job_id})
    if row and row.get("status") == "ledger_pending":
        receipt = row.get("receipt")
        if isinstance(receipt, dict) and receipt.get("status") == "sent":
            return receipt
    return None


def _latest_native_result(loaded: dict, pool: str) -> dict | None:
    occurrence = cwl_campaign.occurrence_id(loaded["cycle"], "roster", pool)
    rows = [row for row in loaded.get("deliveries", ()) if row.get("occurrence_id") == occurrence]
    return rows[-1] if rows else None


async def get_roster_send_status(mongo, guild_id: int, cycle: str, pool: str) -> dict | None:
    key = request_id(guild_id, cycle, pool)
    row = await mongo.bot_config.find_one({"_id": key})
    loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
    receipt = native_receipt(loaded, pool) or await _pending_ledger_receipt(
        mongo, guild_id, cycle, pool,
    )
    if receipt:
        return {**(row or {}), "status": "sent", "receipt": receipt}
    occurrence = cwl_campaign.occurrence_id(cycle, "roster", pool)
    if occurrence in loaded.get("uncertain_occurrences", ()):
        return {**(row or {}), "status": "uncertain"}
    if row and row.get("status") in {"pending", "sending", "stale", "uncertain"}:
        return row
    latest = _latest_native_result(loaded, pool)
    if latest and latest.get("status") in {"failed", "uncertain"}:
        return {**(row or {}), "status": latest["status"], "native_result": latest}
    return row


async def mark_worker_alive(
    mongo,
    guild_id: int,
    *,
    worker_epoch: str | None = None,
    schedule_ready: bool | None = None,
) -> None:
    await mongo.bot_config.update_one(
        {"_id": worker_id(guild_id)},
        {
            "$set": {
                "kind": WORKER_KIND,
                "guild_id": int(guild_id),
                "updated_at": _now(),
                **({"worker_epoch": worker_epoch} if worker_epoch else {}),
                **(
                    {"schedule_ready": schedule_ready}
                    if schedule_ready is not None
                    else {}
                ),
            }
        },
        upsert=True,
    )


async def process_roster_request(
    mongo,
    row: dict,
    sender: Callable[..., Awaitable[bool]],
    authorize=None,
) -> dict:
    """Claim and attempt a pending request once. A crash stays sending."""
    key = request_id(row["guild_id"], row["cycle"], row["pool"])
    allowed = True
    if authorize is not None:
        with timed_step(logging.getLogger(__name__), "roster_authorization"):
            allowed = await authorize(row)
    if not allowed:
        await mongo.bot_config.update_one(
            {'_id': key, 'status': 'pending'},
            {'$set': {'status': 'failed', 'error': 'Dashboard announcement access was removed. Nothing was sent.', 'updated_at': _now()}},
        )
        return await mongo.bot_config.find_one({"_id": key})
    started = _now()
    claimed = await mongo.bot_config.update_one(
        {"_id": key, "status": "pending"},
        {"$set": {"status": "sending", "started_at": started, "updated_at": started}},
    )
    if not claimed.matched_count:
        return await mongo.bot_config.find_one({"_id": key})

    row = await mongo.bot_config.find_one({"_id": key})
    loaded = await cwl_campaign.load_campaign(mongo, row["guild_id"], row["cycle"])
    receipt = native_receipt(loaded, row["pool"]) or await _pending_ledger_receipt(
        mongo, row["guild_id"], row["cycle"], row["pool"],
    )
    if receipt:
        status, detail = "sent", {"receipt": receipt}
    elif cwl_campaign.occurrence_id(row["cycle"], "roster", row["pool"]) in loaded.get(
        "uncertain_occurrences", ()
    ):
        status, detail = "uncertain", {"error": "Native delivery is uncertain; reconcile before retrying"}
    elif campaign_generation(loaded) != row["generation"]:
        status, detail = "stale", {"error": "Native campaign settings changed"}
    else:
        try:
            channel = int(_variant(loaded, row["pool"])["destination_channel_id"])
            if channel != row["channel_id"]:
                raise BridgeConflict("Native campaign channel changed")
        except BridgeConflict as exc:
            status, detail = "stale", {"error": str(exc)}
        else:
            try:
                with timed_step(logging.getLogger(__name__), "roster_delivery"):
                    await sender(
                        int(row["guild_id"]),
                        row["cycle"],
                        "roster",
                        [row["pool"]],
                        generation=row["generation"],
                        manual=True,
                    )
            except Exception as exc:
                status, detail = "uncertain", {"error": f"Sender outcome unknown: {type(exc).__name__}"}
            else:
                refreshed = await cwl_campaign.load_campaign(mongo, row["guild_id"], row["cycle"])
                receipt = native_receipt(refreshed, row["pool"]) or await _pending_ledger_receipt(
                    mongo, row["guild_id"], row["cycle"], row["pool"],
                )
                if receipt:
                    status, detail = "sent", {"receipt": receipt}
                else:
                    latest = _latest_native_result(refreshed, row["pool"])
                    definite_types = {
                        "ValueError", "BadRequestError", "UnauthorizedError",
                        "ForbiddenError", "NotFoundError",
                    }
                    if (
                        latest and latest.get("status") == "failed"
                        and latest.get("error_type") in definite_types
                        and str(latest.get("at", "")) >= started
                    ):
                        status, detail = "failed", {"error": latest.get("error", "Native send was rejected")}
                    else:
                        status, detail = "uncertain", {"error": "No confirmed native receipt; reconcile before retrying"}
    await mongo.bot_config.update_one(
        {"_id": key, "status": "sending", "started_at": started},
        {"$set": {"status": status, "updated_at": _now(), **detail}},
    )
    return await mongo.bot_config.find_one({"_id": key})


async def process_pending_roster_requests(
    mongo,
    sender,
    *,
    guild_id: int,
    limit: int = 10,
    authorize=None,
    worker_epoch: str | None = None,
    schedule_ready: bool | None = None,
) -> int:
    await mark_worker_alive(
        mongo, guild_id, worker_epoch=worker_epoch, schedule_ready=schedule_ready
    )
    rows = await mongo.bot_config.find(
        {
            "kind": REQUEST_KIND,
            "guild_id": int(guild_id),
            "status": "pending",
        }
    ).to_list(length=limit)
    for row in rows[:limit]:
        await process_roster_request(mongo, row, sender, authorize=authorize)
    return len(rows[:limit])


async def reconcile_campaign_changes(
    mongo,
    sync_all,
    *,
    guild_id: int,
    loaded_generations: Callable[[], dict[str, str] | None],
    runtime_id: str,
) -> bool:
    """Reuse the native scheduler when a web or Discord edit changes a campaign.

    Fingerprints detect edits; only the native scheduler's completed process
    proof acknowledges a load. Missing acknowledgements can be repaired without
    rescheduling. Failed or incomplete loads remain pending on the existing poll.
    """
    import hashlib
    import json

    if not isinstance(runtime_id, str) or not runtime_id:
        raise ValueError("A process identity is required for schedule acknowledgement")

    # Only these active records participate in change detection. Do not fetch
    # unrelated profile manifests, child receipts or campaign bodies every tick.
    rows = await mongo.bot_config.find(
        {
            "guild_id": int(guild_id),
            "kind": {"$in": ["cwl_campaign_defaults", "cwl_campaign_cycle"]},
            "activated": True,
        },
        {
            "_id": 1,
            "revision": 1,
            "updated_at": 1,
            "recurring_updated_at": 1,
            "cycle": 1,
        },
    ).to_list(length=None)
    signature = hashlib.sha256(
        json.dumps(
            sorted(
                (
                    str(row["_id"]),
                    int(row.get("revision", 0)),
                    str(row.get("updated_at", "")),
                    str(row.get("recurring_updated_at", "")),
                )
                for row in rows
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    worker = await mongo.bot_config.find_one({"_id": worker_id(guild_id)}) or {}

    def installed():
        proof = loaded_generations()
        if proof is None:
            return None
        if (
            not isinstance(proof, dict)
            or not isinstance(runtime_id, str)
            or not runtime_id
            or any(
                not isinstance(cycle, str)
                or not _CYCLE.fullmatch(cycle)
                or not isinstance(generation, str)
                or not generation
                for cycle, generation in proof.items()
            )
        ):
            raise ValueError(
                "Schedule acknowledgement requires exact installed generations"
            )
        return dict(proof)

    generations = installed()
    same_signature = worker.get("schedule_fingerprint") == signature
    same_epoch = worker.get("schedule_epoch") == runtime_id
    # A stored fingerprint is not proof that this process restored its jobs.
    # Completed startup loads can repair missing/default-only acknowledgements
    # directly. Failed or absent process proof requires one real load first.
    if not same_signature or generations is None:
        now = time.monotonic()
        prior = _schedule_repair_attempts.get(int(guild_id))
        if (
            prior
            and prior[:2] == (runtime_id, signature)
            and now - prior[2] < SCHEDULE_REPAIR_RETRY_SECONDS
        ):
            return False
        _schedule_repair_attempts[int(guild_id)] = (runtime_id, signature, now)
        await sync_all()
        generations = installed()
    if generations is None or (rows and not generations):
        raise ValueError("No schedule load completed; nothing was acknowledged")
    _schedule_repair_attempts.pop(int(guild_id), None)
    if (
        same_signature
        and same_epoch
        and worker.get("schedule_generations") == generations
    ):
        return False
    await mongo.bot_config.update_one(
        {"_id": worker_id(guild_id)},
        {
            "$set": {
                "schedule_fingerprint": signature,
                "schedule_generations": generations,
                "schedule_epoch": runtime_id,
                "schedule_sync_at": _now(),
            }
        },
        upsert=True,
    )
    return True
