# extensions/commands/tickets/handlers.py
"""
Ticket button and interaction handlers
"""

import hikari
import hikari.errors
import lightbulb
from typing import List, Dict
from datetime import datetime, timedelta, timezone
import asyncio
import re
import uuid

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT
from extensions.commands import ticket_runtime
from extensions.components import register_action
from extensions.commands.tickets_legacy import loader
from extensions.commands.tickets_legacy import store

# Default configuration values
DEFAULT_MAIN_CATEGORY = 1395400463897202738
DEFAULT_FWA_CATEGORY = 1395653165470191667
DEFAULT_ADMIN_TO_NOTIFY = 505227988229554179
CHANNEL_WARNING_THRESHOLD = 5

# Global semaphore to prevent concurrent channel creation
channel_creation_semaphore = asyncio.Semaphore(1)

# Cooldown tracking - user_id: timestamp
user_cooldowns: Dict[int, datetime] = {}
COOLDOWN_DURATION = 30  # seconds
# Extra seconds pushed onto a user's cooldown after a 429 on channel creation. The
# guild channel-create bucket slides to a 60s window, so a plain 30s cooldown would
# let the retry land back inside the same window; 60 + 30 clears it.
RATE_LIMIT_BACKOFF = 60  # seconds
COOLDOWN_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes
last_cleanup = datetime.now(timezone.utc)
CREATION_LEASE = timedelta(minutes=10)
CREATION_RETENTION = timedelta(days=30)
UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS = 3
UNCERTAIN_CHANNEL_LOOKUP_DELAY_SECONDS = 1
_creation_index_ready = False
LEGACY_COMMIT_RECOVERY_LIMIT = 50
LEGACY_COMMIT_RETRY_DELAYS_SECONDS = (5, 15, 30, 60, 300)
_legacy_commit_recovery_tasks: dict[str, asyncio.Task] = {}
_legacy_commit_recovery_stopping = False


class CreationLeaseLost(RuntimeError):
    """The durable creation owner changed before this worker's next write."""


def _creation_id(guild_id: int, user_id: int, ticket_type: str) -> str:
    return f"{int(guild_id)}:{int(user_id)}:{ticket_type}"


def _error_detail(error: Exception) -> str:
    detail = " ".join(str(error).split()) or "no error detail"
    detail = re.sub(
        r"(?i)\b(mongodb(?:\+srv)?|https?)://[^@\s]+@",
        r"\1://***@",
        detail,
    )
    detail = re.sub(
        r"(?i)\b(access_token|token|api_key|secret|password)=([^&\s]+)",
        r"\1=***",
        detail,
    )
    return detail[:180]


async def ensure_creation_index(mongo: MongoClient) -> None:
    """Expire completed attempts only; unresolved evidence is never TTL data."""
    global _creation_index_ready
    if _creation_index_ready:
        return
    await mongo.ticket_creation_state.update_many(
        {"state": {"$ne": "complete"}, "expires_at": {"$exists": True}},
        {"$unset": {"expires_at": ""}},
    )
    await mongo.ticket_creation_state.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="ttl_expires_at",
    )
    _creation_index_ready = True


async def find_open_ticket(mongo: MongoClient, user_id: int, ticket_type: str):
    """Return an open ticket from either runtime before claiming a global slot."""
    mixed_user_id = [int(user_id), str(int(user_id))]
    legacy = await store.find_one(mongo, {
        "type": "ticket",
        "ticket_type": ticket_type,
        "user_id": {"$in": mixed_user_id},
        "status": "open",
    })
    if legacy is not None:
        return legacy
    return await mongo.tickets.find_one({
        "type": "ticket",
        "venue": "thread",
        "ticket_type": ticket_type,
        "user_id": {"$in": mixed_user_id},
        "status": "open",
    })


def _ticket_location_id(ticket: dict) -> int:
    location = ticket.get("location") or {}
    return store.as_int(
        location.get("id")
        or ticket.get("public_thread_id")
        or ticket.get("channel_id")
        or ticket.get("staff_thread_id")
        or ticket.get("thread_id")
    )


def _public_workflow_id(
        route: str,
        guild_id: int,
        user_id: int,
        ticket_type: str,
) -> str:
    if route == ticket_runtime.ROUTE_THREAD:
        return f"thread:{int(user_id)}:{ticket_type}"
    return f"legacy:{_creation_id(guild_id, user_id, ticket_type)}"


async def _existing_public_open_slot(
        mongo: MongoClient,
        user_id: int,
        ticket_type: str,
):
    """Read sticky ownership without acquiring or extending its lease."""
    return await mongo.ticket_open_slots.find_one({
        "_id": f"ticket-open:{int(user_id)}:{ticket_type}",
        "state": {"$in": sorted(ticket_runtime.ACTIVE_SLOT_STATES)},
    })


async def claim_public_open_slot(
        mongo: MongoClient,
        *,
        route: str,
        rollout_revision: int,
        guild_id: int,
        user_id: int,
        ticket_type: str,
):
    """Claim a new slot or resume its sticky runtime after a phase change."""
    workflow_id = _public_workflow_id(
        route, guild_id, user_id, ticket_type
    )
    for attempt in range(2):
        claimed = await ticket_runtime.claim_open_slot(
            mongo,
            user_id=user_id,
            ticket_type=ticket_type,
            route=route,
            guild_id=guild_id,
            workflow_id=workflow_id,
            rollout_revision=rollout_revision,
            lease_seconds=600,
        )
        if claimed.won:
            return claimed

        slot = claimed.slot
        if (
            attempt == 0
            and slot.get("state") == ticket_runtime.SLOT_RELEASE_PENDING
        ):
            await ticket_runtime.reconcile_open_slots(mongo)
            continue
        if slot.get("state") == ticket_runtime.SLOT_RESERVED:
            sticky_route = slot.get("route")
            sticky_workflow = slot.get("workflow_id")
            if (
                sticky_route in {
                    ticket_runtime.ROUTE_LEGACY,
                    ticket_runtime.ROUTE_THREAD,
                }
                and sticky_workflow
            ):
                return await ticket_runtime.resume_open_slot(
                    mongo,
                    slot_id=str(slot["_id"]),
                    workflow_id=str(sticky_workflow),
                    route=str(sticky_route),
                    lease_seconds=600,
                )
        return claimed
    return claimed


async def cancel_claimed_open_slot(mongo: MongoClient, slot_claim) -> bool:
    if not slot_claim.won or not slot_claim.owner_token:
        return False
    return await ticket_runtime.cancel_open_slot(
        mongo,
        slot_id=str(slot_claim.slot["_id"]),
        owner_token=str(slot_claim.owner_token),
        workflow_id=str(slot_claim.slot["workflow_id"]),
    )


async def cancel_slot_if_creation_absent(
        mongo: MongoClient,
        slot_claim,
        creation_id: str,
) -> bool:
    """Cancel only after Mongo proves no local creation evidence exists."""
    try:
        current = await mongo.ticket_creation_state.find_one({"_id": creation_id})
    except Exception as error:
        print(
            "[Tickets:Legacy] slot_cancel_evidence_check_failed "
            f"creation_id={creation_id} error={type(error).__name__}"
        )
        return False
    if current is not None:
        return False
    return await cancel_claimed_open_slot(mongo, slot_claim)


async def _queue_committed_initial_delivery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket_data: dict,
) -> bool:
    """Best-effort materialize the delivery row after ticket commit."""

    try:
        from extensions.events.channel import ticket_channel_monitor

        ticket_channel_monitor.schedule_ticket_automation_delivery_retry(
            bot=bot,
            mongo=mongo,
            ticket_data=ticket_data,
        )
        await ticket_channel_monitor.ensure_ticket_automation_delivery(
            mongo, ticket_data
        )
        return True
    except Exception as error:
        print(
            "[Tickets:Legacy] initial_delivery_queue_deferred "
            f"ticket_id={ticket_data['_id']} error={type(error).__name__}"
        )
        return False


async def _drive_committed_initial_delivery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket_data: dict,
) -> bool:
    """Best-effort drive the exact queued row without changing commit success."""

    try:
        from extensions.events.channel import ticket_channel_monitor

        await ticket_channel_monitor.ensure_and_deliver_ticket_automation(
            bot=bot,
            mongo=mongo,
            ticket_data=ticket_data,
        )
        return True
    except Exception as error:
        ticket_channel_monitor.schedule_ticket_automation_delivery_retry(
            bot=bot,
            mongo=mongo,
            ticket_data=ticket_data,
        )
        print(
            "[Tickets:Legacy] initial_delivery_deferred "
            f"ticket_id={ticket_data['_id']} error={type(error).__name__}"
        )
        return False


def _ticket_payload_from_creation(state: dict) -> dict:
    """Validate the canonical ticket payload against its fenced Discord evidence."""

    payload = state.get("ticket_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("legacy commit recovery payload is unavailable")
    payload = dict(payload)
    creation_id = str(state.get("_id") or "")
    channel_id = store.as_int(state.get("channel_id"))
    thread_id = store.as_int(state.get("thread_id"))
    ticket_id = str(state.get("ticket_id") or "")
    expected_creation_id = _creation_id(
        store.as_int(payload.get("guild_id")),
        store.as_int(payload.get("user_id")),
        str(payload.get("ticket_type") or ""),
    )
    expected_slot_id = (
        f"ticket-open:{store.as_int(payload.get('user_id'))}:"
        f"{payload.get('ticket_type')}"
    )
    expected_workflow_id = f"legacy:{expected_creation_id}"
    if (
        not channel_id
        or not thread_id
        or ticket_id != f"ticket_{channel_id}"
        or str(payload.get("_id") or "") != ticket_id
        or payload.get("type") != "ticket"
        or payload.get("status") != "open"
        or payload.get("venue") != "channel"
        or payload.get("runtime") != store.LEGACY_RUNTIME
        or state.get("route") != ticket_runtime.ROUTE_LEGACY
        or creation_id != expected_creation_id
        or str(state.get("open_slot_id") or "") != expected_slot_id
        or str(payload.get("open_slot_id") or "") != expected_slot_id
        or str(state.get("creation_workflow_id") or "")
        != expected_workflow_id
        or str(payload.get("creation_workflow_id") or "")
        != expected_workflow_id
    ):
        raise RuntimeError("legacy commit recovery identity is invalid")
    exact_fields = (
        "guild_id",
        "user_id",
        "channel_id",
        "thread_id",
        "category_id",
        "ticket_number",
        "rollout_revision",
    )
    if any(
        store.as_int(state.get(field)) != store.as_int(payload.get(field))
        for field in exact_fields
    ):
        raise RuntimeError("legacy commit recovery numeric identity mismatch")
    if (
        store.as_int(state.get("attempt_generation")) <= 0
        or store.as_int(state.get("attempt_generation"))
        != store.as_int(payload.get("creation_generation"))
    ):
        raise RuntimeError("legacy commit recovery generation mismatch")
    for field in (
        "ticket_type",
        "open_slot_id",
        "creation_workflow_id",
        "runtime",
    ):
        if str(state.get(field) or "") != str(payload.get(field) or ""):
            raise RuntimeError(f"legacy commit recovery identity mismatch: {field}")
    if not isinstance(payload.get("created_at"), datetime):
        raise RuntimeError("legacy commit recovery creation time is invalid")
    return payload


def _slot_matches_recovered_ticket(slot: dict, state: dict, ticket: dict) -> bool:
    return (
        str(slot.get("_id") or "") == str(state.get("open_slot_id") or "")
        and slot.get("route") == ticket_runtime.ROUTE_LEGACY
        and str(slot.get("workflow_id") or "")
        == str(state.get("creation_workflow_id") or "")
        and store.as_int(slot.get("guild_id")) == store.as_int(ticket.get("guild_id"))
        and store.as_int(slot.get("user_id")) == store.as_int(ticket.get("user_id"))
        and str(slot.get("ticket_type") or "") == str(ticket.get("ticket_type") or "")
        and store.as_int(slot.get("rollout_revision"))
        == store.as_int(ticket.get("rollout_revision"))
    )


async def _bind_recovered_open_slot(
    mongo: MongoClient,
    state: dict,
    ticket: dict,
    *,
    owner_token: str | None = None,
) -> None:
    slot_id = str(state.get("open_slot_id") or "")
    workflow_id = str(state.get("creation_workflow_id") or "")
    slot = await mongo.ticket_open_slots.find_one({"_id": slot_id})
    if slot is None or not _slot_matches_recovered_ticket(slot, state, ticket):
        raise RuntimeError("legacy commit recovery slot identity mismatch")
    if slot.get("state") == ticket_runtime.SLOT_OPEN:
        if (
            str(slot.get("ticket_id")) != str(ticket["_id"])
            or store.as_int(slot.get("location_id")) != store.as_int(ticket["channel_id"])
        ):
            raise RuntimeError("legacy commit recovery slot belongs to another ticket")
        return
    if slot.get("state") != ticket_runtime.SLOT_RESERVED:
        raise RuntimeError("legacy commit recovery slot is not resumable")
    claimed = await ticket_runtime.resume_open_slot(
        mongo,
        slot_id=slot_id,
        workflow_id=workflow_id,
        route=ticket_runtime.ROUTE_LEGACY,
        owner_token=owner_token,
        lease_seconds=600,
    )
    if claimed.won:
        try:
            await ticket_runtime.bind_open_slot(
                mongo,
                slot_id=slot_id,
                owner_token=str(claimed.owner_token),
                ticket_id=ticket["_id"],
                location_id=store.as_int(ticket["channel_id"]),
            )
            return
        except ticket_runtime.SlotConflict:
            pass
    latest = await mongo.ticket_open_slots.find_one({"_id": slot_id})
    if (
        latest is None
        or not _slot_matches_recovered_ticket(latest, state, ticket)
        or latest.get("state") != ticket_runtime.SLOT_OPEN
        or str(latest.get("ticket_id")) != str(ticket["_id"])
        or store.as_int(latest.get("location_id"))
        != store.as_int(ticket["channel_id"])
    ):
        raise RuntimeError("legacy commit recovery slot binding is pending")


async def _retire_recovered_terminal_slot(
    mongo: MongoClient,
    state: dict,
    ticket: dict,
    *,
    owner_token: str | None = None,
) -> None:
    """Converge a terminal late commit without recreating opening delivery."""

    slot_id = str(state.get("open_slot_id") or "")
    slot = await mongo.ticket_open_slots.find_one({"_id": slot_id})
    if slot is None:
        return
    if not _slot_matches_recovered_ticket(slot, state, ticket):
        raise RuntimeError("legacy terminal recovery slot identity mismatch")
    if slot.get("state") == ticket_runtime.SLOT_RESERVED:
        await _bind_recovered_open_slot(
            mongo,
            state,
            ticket,
            owner_token=owner_token,
        )
    elif slot.get("state") in {
        ticket_runtime.SLOT_OPEN,
        ticket_runtime.SLOT_RELEASE_PENDING,
    }:
        if (
            str(slot.get("ticket_id") or "") != str(ticket["_id"])
            or store.as_int(slot.get("location_id"))
            != store.as_int(ticket["channel_id"])
        ):
            raise RuntimeError("legacy terminal recovery slot ticket mismatch")
    else:
        raise RuntimeError("legacy terminal recovery slot is not releasable")
    if not await store.release_terminal_open_slot(
        mongo,
        ticket["_id"],
        str(ticket["status"]),
    ):
        raise RuntimeError("legacy terminal recovery slot release is pending")


async def _complete_recovered_creation_state(
    mongo: MongoClient,
    state: dict,
    ticket: dict,
) -> None:
    now = datetime.now(timezone.utc)
    identity = {
        "_id": str(state["_id"]),
        "guild_id": store.as_int(ticket["guild_id"]),
        "user_id": store.as_int(ticket["user_id"]),
        "ticket_type": str(ticket["ticket_type"]),
        "ticket_number": store.as_int(ticket["ticket_number"]),
        "ticket_id": str(ticket["_id"]),
        "channel_id": store.as_int(ticket["channel_id"]),
        "thread_id": store.as_int(ticket["thread_id"]),
        "category_id": store.as_int(ticket["category_id"]),
        "route": ticket_runtime.ROUTE_LEGACY,
        "runtime": store.LEGACY_RUNTIME,
        "rollout_revision": store.as_int(ticket["rollout_revision"]),
        "attempt_generation": store.as_int(ticket["creation_generation"]),
        "open_slot_id": str(ticket["open_slot_id"]),
        "creation_workflow_id": str(ticket["creation_workflow_id"]),
    }
    completed = await mongo.ticket_creation_state.find_one_and_update(
        {
            **identity,
            "state": {"$in": ["creating", "cleanup_required"]},
        },
        {
            "$set": {
                "state": "complete",
                "completed_at": now,
                "updated_at": now,
                "expires_at": now + CREATION_RETENTION,
            },
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                "last_error": "",
                "cleanup_error": "",
                "commit_check_error": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if completed is not None:
        return
    current = await mongo.ticket_creation_state.find_one({"_id": str(state["_id"])})
    if current is None or current.get("state") != "complete" or any(
        str(current.get(field)) != str(expected)
        for field, expected in identity.items()
    ):
        raise RuntimeError("legacy commit recovery completion CAS failed")


async def _creation_recovery_fence(mongo: MongoClient, state: dict) -> bool:
    """Prove this exact commit generation still owns local recovery."""

    query = {
        "_id": str(state["_id"]),
        "state": state.get("state"),
        "ticket_id": str(state.get("ticket_id") or ""),
        "attempt_generation": store.as_int(state.get("attempt_generation")),
        "channel_id": store.as_int(state.get("channel_id")),
        "thread_id": store.as_int(state.get("thread_id")),
        "open_slot_id": str(state.get("open_slot_id") or ""),
        "creation_workflow_id": str(state.get("creation_workflow_id") or ""),
    }
    return await mongo.ticket_creation_state.find_one(query) is not None


async def recover_uncertain_legacy_ticket_creation(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    creation_id: str,
    slot_owner_token: str | None = None,
    creation_owner_token: str | None = None,
    expected_ticket_id: str | None = None,
    expected_generation: int | None = None,
) -> bool:
    """Converge one durable commit intent without deleting Discord evidence."""

    state = await mongo.ticket_creation_state.find_one({"_id": str(creation_id)})
    if state is None:
        return True
    if expected_ticket_id is not None and str(state.get("ticket_id") or "") != str(
        expected_ticket_id
    ):
        return True
    if expected_generation is not None and store.as_int(
        state.get("attempt_generation")
    ) != int(expected_generation):
        return True
    if state.get("state") == "complete":
        return True
    if state.get("state") not in {"creating", "cleanup_required"}:
        raise RuntimeError("legacy commit recovery state is not recoverable")
    if state.get("state") == "creating":
        lease_until = state.get("lease_until")
        if isinstance(lease_until, datetime) and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=timezone.utc)
        lease_owner = str(state.get("lease_owner") or "")
        caller_owns_lease = bool(
            creation_owner_token
            and lease_owner == str(creation_owner_token)
        )
        if (
            not caller_owns_lease
            and isinstance(lease_until, datetime)
            and lease_until > datetime.now(timezone.utc)
        ):
            raise RuntimeError("legacy commit recovery creation lease is active")
    ticket = _ticket_payload_from_creation(state)
    if not await _creation_recovery_fence(mongo, state):
        return True
    authoritative = await store.ensure_exact_ticket(
        mongo,
        ticket,
        allow_terminal=True,
    )
    if str(authoritative.get("status") or "") in store.TERMINAL_STATUSES:
        if not await _creation_recovery_fence(mongo, state):
            return True
        await _retire_recovered_terminal_slot(
            mongo,
            state,
            authoritative,
            owner_token=slot_owner_token,
        )
        if not await _creation_recovery_fence(mongo, state):
            return True
        await _complete_recovered_creation_state(mongo, state, authoritative)
        return True
    if not await _creation_recovery_fence(mongo, state):
        return True
    await _bind_recovered_open_slot(
        mongo,
        state,
        authoritative,
        owner_token=slot_owner_token,
    )
    if not await _creation_recovery_fence(mongo, state):
        return True
    if not await _queue_committed_initial_delivery(bot, mongo, authoritative):
        raise RuntimeError("legacy commit recovery delivery queue is pending")
    if not await _creation_recovery_fence(mongo, state):
        return True
    await _complete_recovered_creation_state(mongo, state, authoritative)
    return True


async def _retry_uncertain_legacy_ticket_creation(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    creation_id: str,
    slot_owner_token: str | None = None,
    creation_owner_token: str | None = None,
    expected_ticket_id: str | None = None,
    expected_generation: int | None = None,
) -> None:
    attempt = 0
    while True:
        try:
            if await recover_uncertain_legacy_ticket_creation(
                bot=bot,
                mongo=mongo,
                creation_id=creation_id,
                slot_owner_token=slot_owner_token,
                creation_owner_token=creation_owner_token,
                expected_ticket_id=expected_ticket_id,
                expected_generation=expected_generation,
            ):
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            attempt += 1
            delays = LEGACY_COMMIT_RETRY_DELAYS_SECONDS
            delay = delays[min(attempt - 1, len(delays) - 1)]
            if attempt <= len(delays) or (attempt - len(delays)) % 12 == 0:
                print(
                    "[Tickets:Legacy] commit_recovery_retry "
                    f"creation_id={creation_id} attempt={attempt} "
                    f"delay_seconds={delay} error={type(error).__name__}"
                )
            await asyncio.sleep(delay)


def schedule_uncertain_legacy_ticket_recovery(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    creation_id: str,
    slot_owner_token: str | None = None,
    creation_owner_token: str | None = None,
    expected_ticket_id: str | None = None,
    expected_generation: int | None = None,
) -> asyncio.Task:
    if _legacy_commit_recovery_stopping:
        raise RuntimeError("legacy commit recovery scheduling is stopping")
    key = (
        f"{creation_id}|{expected_ticket_id or '*'}|"
        f"{expected_generation if expected_generation is not None else '*'}"
    )
    current = _legacy_commit_recovery_tasks.get(key)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(
        _retry_uncertain_legacy_ticket_creation(
            bot=bot,
            mongo=mongo,
            creation_id=str(creation_id),
            # The task key includes the generation, but the durable lookup id
            # remains the canonical applicant/type creation id.
            expected_ticket_id=expected_ticket_id,
            expected_generation=expected_generation,
            slot_owner_token=slot_owner_token,
            creation_owner_token=creation_owner_token,
        ),
        name=f"legacy-commit-recovery:{creation_id}:{expected_generation}",
    )
    _legacy_commit_recovery_tasks[key] = task

    def discard(done: asyncio.Task) -> None:
        if _legacy_commit_recovery_tasks.get(key) is done:
            _legacy_commit_recovery_tasks.pop(key, None)
        if not done.cancelled() and done.exception() is not None:
            print(
                "[Tickets:Legacy] commit_recovery_worker_failed "
                f"creation_id={key} error={type(done.exception()).__name__}"
            )

    task.add_done_callback(discard)
    return task


async def recover_pending_uncertain_legacy_creations(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    limit: int = LEGACY_COMMIT_RECOVERY_LIMIT,
) -> dict[str, int]:
    query = {
        "state": {"$in": ["creating", "cleanup_required"]},
        "ticket_id": {"$exists": True},
        "ticket_payload": {"$exists": True},
        "commit_started_at": {"$exists": True},
    }
    bounded = max(1, int(limit))
    completed = 0
    failed = 0
    processed = 0
    after_id: str | None = None
    while True:
        page_query = dict(query)
        if after_id is not None:
            page_query["_id"] = {"$gt": after_id}
        rows = await mongo.ticket_creation_state.find(page_query).sort(
            [("_id", 1)]
        ).limit(bounded).to_list(length=bounded)
        if not rows:
            break
        for state in rows:
            creation_id = str(state["_id"])
            try:
                await recover_uncertain_legacy_ticket_creation(
                    bot=bot,
                    mongo=mongo,
                    creation_id=creation_id,
                    expected_ticket_id=str(state["ticket_id"]),
                    expected_generation=store.as_int(
                        state.get("attempt_generation")
                    ),
                )
                completed += 1
            except Exception:
                failed += 1
                try:
                    schedule_uncertain_legacy_ticket_recovery(
                        bot=bot,
                        mongo=mongo,
                        creation_id=creation_id,
                        expected_ticket_id=str(state["ticket_id"]),
                        expected_generation=store.as_int(
                            state.get("attempt_generation")
                        ),
                    )
                except RuntimeError:
                    pass
            processed += 1
        after_id = str(rows[-1]["_id"])
        if len(rows) < bounded:
            break
    return {"processed": processed, "completed": completed, "failed": failed}


async def stop_uncertain_legacy_ticket_recoveries() -> None:
    global _legacy_commit_recovery_stopping
    _legacy_commit_recovery_stopping = True
    tasks = list(_legacy_commit_recovery_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _legacy_commit_recovery_tasks.clear()


async def start_uncertain_legacy_ticket_recoveries() -> None:
    global _legacy_commit_recovery_stopping
    await stop_uncertain_legacy_ticket_recoveries()
    _legacy_commit_recovery_stopping = False


async def claim_ticket_creation(
        mongo: MongoClient,
        guild_id: int,
        user_id: int,
        ticket_type: str,
        *,
        slot_id: str | None = None,
        workflow_id: str | None = None,
        now: datetime | None = None,
) -> tuple[bool, dict]:
    """Atomically own one user's ticket creation across workers and restarts."""
    await ensure_creation_index(mongo)
    now = now or datetime.now(timezone.utc)
    creation_id = _creation_id(guild_id, user_id, ticket_type)
    collection = mongo.ticket_creation_state
    current = await collection.find_one({"_id": creation_id})
    owner = uuid.uuid4().hex

    if current:
        stored_slot = current.get("open_slot_id")
        stored_workflow = current.get("creation_workflow_id")
        if (
            (stored_slot and slot_id and str(stored_slot) != str(slot_id))
            or (
                stored_workflow
                and workflow_id
                and str(stored_workflow) != str(workflow_id)
            )
        ):
            return False, current

    # A committed attempt may be reused only after its exact authoritative
    # legacy ticket is terminal. This also heals a crash between ticket commit
    # and the local `complete` marker. The old ticket/channel remain untouched;
    # only this creation lease is reset for the applicant's next ticket.
    if current and current.get("channel_id"):
        if (
            current.get("ticket_id")
            and store.as_int(current.get("guild_id")) == int(guild_id)
            and store.as_int(current.get("user_id")) == int(user_id)
            and current.get("ticket_type") == ticket_type
        ):
            exact_terminal = await store.find_one(mongo, {
                "_id": current["ticket_id"],
                "guild_id": int(guild_id),
                "user_id": {"$in": [int(user_id), str(int(user_id))]},
                "ticket_type": ticket_type,
                "channel_id": {
                    "$in": [
                        store.as_int(current["channel_id"]),
                        str(store.as_int(current["channel_id"])),
                    ]
                },
                "status": {"$in": sorted(store.TERMINAL_STATUSES)},
            })
            if exact_terminal is not None:
                claim_filter = {
                    "_id": creation_id,
                    "state": current.get("state"),
                    "ticket_id": current["ticket_id"],
                    "channel_id": current["channel_id"],
                }
                if current.get("lease_owner") is not None:
                    claim_filter["lease_owner"] = current["lease_owner"]
                elif current.get("state") != "complete":
                    claim_filter["lease_owner"] = {"$exists": False}
                claimed = await collection.find_one_and_update(
                    claim_filter,
                    {
                        "$set": {
                            "guild_id": int(guild_id),
                            "user_id": int(user_id),
                            "ticket_type": ticket_type,
                            "state": "creating",
                            "lease_owner": owner,
                            "lease_until": now + CREATION_LEASE,
                            "updated_at": now,
                            "attempt_started_at": now,
                            **({"open_slot_id": str(slot_id)} if slot_id else {}),
                            **(
                                {"creation_workflow_id": str(workflow_id)}
                                if workflow_id
                                else {}
                            ),
                        },
                        "$unset": {
                            "ticket_id": "",
                            "ticket_number": "",
                            "channel_id": "",
                            "thread_id": "",
                            "category_id": "",
                            "channel_name": "",
                            "completed_at": "",
                            "route": "",
                            "runtime": "",
                            "rollout_revision": "",
                            "expires_at": "",
                            "last_error": "",
                            "cleanup_error": "",
                            "channel_check_error": "",
                            "commit_check_error": "",
                            "channel_create_started_at": "",
                            "channel_create_state": "",
                            "channel_created_at": "",
                            "thread_create_started_at": "",
                            "thread_create_state": "",
                            "thread_created_at": "",
                            "commit_started_at": "",
                            "ticket_payload": "",
                            "rollback_started_at": "",
                            "configured_category_id": "",
                        },
                        "$inc": {"attempt_generation": 1},
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if claimed is not None:
                    return True, claimed
                current = await collection.find_one({"_id": creation_id})
        return False, (current or {"_id": creation_id, "state": "creating"})
    if current and current.get("channel_name"):
        return False, current
    if current and current.get("state") == "cleanup_required":
        return False, current

    query = {
        "_id": creation_id,
        "state": {"$ne": "complete"},
        "$or": [
            {"lease_until": {"$lte": now}},
            {"lease_until": {"$exists": False}},
        ],
    }
    update = {
        "$setOnInsert": {
            "guild_id": int(guild_id),
            "user_id": int(user_id),
            "ticket_type": ticket_type,
            "created_at": now,
            "attempt_started_at": now,
        },
        "$set": {
            "state": "creating",
            "lease_owner": owner,
            "lease_until": now + CREATION_LEASE,
            "updated_at": now,
            **({"open_slot_id": str(slot_id)} if slot_id else {}),
            **(
                {"creation_workflow_id": str(workflow_id)}
                if workflow_id
                else {}
            ),
        },
        "$unset": {"last_error": "", "expires_at": ""},
        "$inc": {"attempt_generation": 1},
    }
    try:
        claimed = await collection.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        claimed = None
    if claimed is not None:
        return True, claimed
    return False, (await collection.find_one({"_id": creation_id}) or {
        "_id": creation_id,
        "state": "creating",
    })


async def reserve_ticket_number(mongo: MongoClient, ticket_type: str) -> int:
    """Allocate a number from the cross-runtime monotonic counter."""
    return await ticket_runtime.reserve_ticket_number(mongo, ticket_type=ticket_type)


async def update_creation_state(
        mongo: MongoClient,
        creation_id: str,
        lease_owner: str,
        *,
        unset_fields: tuple[str, ...] = (),
        **fields,
) -> dict:
    now = datetime.now(timezone.utc)
    fields["updated_at"] = now
    fields["lease_until"] = now + CREATION_LEASE
    update: dict = {"$set": fields, "$unset": {"expires_at": ""}}
    update["$unset"].update({field: "" for field in unset_fields})
    result = await mongo.ticket_creation_state.find_one_and_update(
        {
            "_id": creation_id,
            "state": "creating",
            "lease_owner": str(lease_owner),
        },
        update,
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise CreationLeaseLost("ticket creation lease was lost")
    return result


async def complete_creation_state(
        mongo: MongoClient,
        creation_id: str,
        lease_owner: str,
        channel_id: int,
        thread_id: int,
        ticket_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    result = await mongo.ticket_creation_state.find_one_and_update(
        {
            "_id": creation_id,
            "state": "creating",
            "lease_owner": str(lease_owner),
        },
        {
            "$set": {
                "state": "complete",
                "channel_id": int(channel_id),
                "thread_id": int(thread_id),
                "ticket_id": ticket_id,
                "completed_at": now,
                "updated_at": now,
                "expires_at": now + CREATION_RETENTION,
            },
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                "last_error": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise CreationLeaseLost("ticket creation lease was lost before completion")


async def mark_creation_uncertain(
        mongo: MongoClient,
        creation_id: str,
        lease_owner: str,
        **fields,
) -> bool:
    """Durably retain ambiguous Discord/Mongo evidence without a TTL."""
    now = datetime.now(timezone.utc)
    result = await mongo.ticket_creation_state.find_one_and_update(
        {
            "_id": creation_id,
            "state": "creating",
            "lease_owner": str(lease_owner),
        },
        {
            "$set": {
                "state": "cleanup_required",
                "updated_at": now,
                **fields,
            },
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                "expires_at": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    return result is not None


async def rollback_ticket_creation(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        creation_id: str,
        channel_id: int | None,
        error: Exception,
        *,
        lease_owner: str,
        slot_id: str | None = None,
        slot_owner: str | None = None,
        workflow_id: str | None = None,
) -> bool:
    """Compensate Discord work; retain a blocker if cleanup itself fails."""
    try:
        await update_creation_state(
            mongo,
            creation_id,
            lease_owner,
            rollback_started_at=datetime.now(timezone.utc),
            last_error=type(error).__name__,
        )
    except CreationLeaseLost:
        print(
            "[Tickets:Legacy] stale_worker_rollback_blocked "
            f"creation_id={creation_id}"
        )
        return False

    if channel_id is not None:
        try:
            await bot.rest.delete_channel(
                channel_id,
                reason="Rolling back incomplete ticket creation",
            )
        except hikari.NotFoundError:
            pass
        except Exception as cleanup_error:
            try:
                await mark_creation_uncertain(
                    mongo,
                    creation_id,
                    lease_owner,
                    channel_id=int(channel_id),
                    last_error=type(error).__name__,
                    cleanup_error=type(cleanup_error).__name__,
                )
            except Exception as state_error:
                print(
                    "[Tickets] ALERT creation_cleanup_state_failed "
                    f"creation_id={creation_id} channel_id={channel_id} "
                    f"error={type(state_error).__name__}"
                )
            print(
                "[Tickets] ALERT creation_rollback_failed "
                f"creation_id={creation_id} channel_id={channel_id} "
                f"error={type(cleanup_error).__name__}"
            )
            return False

    try:
        released = await mongo.ticket_creation_state.delete_one({
            "_id": creation_id,
            "state": "creating",
            "lease_owner": str(lease_owner),
        })
    except Exception as state_error:
        # The durable state and shared slot remain for reconciliation.
        print(
            "[Tickets] WARNING creation_state_release_failed "
            f"creation_id={creation_id} error={type(state_error).__name__}"
        )
        return False
    if not getattr(released, "deleted_count", 0):
        print(
            "[Tickets:Legacy] stale_worker_state_release_blocked "
            f"creation_id={creation_id}"
        )
        return False
    if slot_id and slot_owner and workflow_id:
        try:
            cancelled = await ticket_runtime.cancel_open_slot(
                mongo,
                slot_id=slot_id,
                owner_token=slot_owner,
                workflow_id=workflow_id,
            )
        except Exception as slot_error:
            print(
                "[Tickets:Legacy] slot_cancel_failed "
                f"slot_id={slot_id} error={type(slot_error).__name__}"
            )
            return False
        if not cancelled:
            print(
                "[Tickets:Legacy] slot_cancel_lost "
                f"slot_id={slot_id}"
            )
            return False
    return True


async def release_missing_channel_blocker(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        creation_state: dict,
) -> bool:
    """Clear an incomplete claim only when Discord proves its channel is gone."""
    now = datetime.now(timezone.utc)
    # A prepared/committed ticket id makes Mongo outcome ambiguous. Only the
    # exact terminal-ticket path in `claim_ticket_creation` may retire it.
    if creation_state.get("ticket_id"):
        return False
    lease_until = creation_state.get("lease_until")
    if isinstance(lease_until, datetime):
        if lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=timezone.utc)
        if creation_state.get("state") == "creating" and lease_until > now:
            return False
    channel_id = creation_state.get("channel_id")
    channel_name = creation_state.get("channel_name")
    missing = False
    channel_exists = False
    try:
        if channel_id:
            await bot.rest.fetch_channel(channel_id)
            channel_exists = True
        elif channel_name:
            channels = await bot.rest.fetch_guild_channels(
                creation_state["guild_id"]
            )
            matches = [
                item for item in channels
                if str(getattr(item, "name", "")).casefold() == channel_name.casefold()
                and getattr(item, "parent_id", None) is not None
                and int(item.parent_id) == int(creation_state["category_id"])
            ]
            if not matches:
                missing = True
            elif len(matches) == 1:
                channel_id = int(matches[0].id)
                creation_state["channel_id"] = channel_id
                await mongo.ticket_creation_state.update_one(
                    {
                        "_id": creation_state["_id"],
                        "state": creation_state.get("state"),
                        "channel_name": channel_name,
                    },
                    {
                        "$set": {
                            "channel_id": channel_id,
                            "state": "cleanup_required",
                            "updated_at": now,
                        },
                        "$unset": {
                            "lease_owner": "",
                            "lease_until": "",
                            "expires_at": "",
                        },
                    },
                )
                print(
                    "[Tickets] uncertain_creation_channel_found "
                    f"creation_id={creation_state['_id']} channel_id={channel_id}"
                )
            else:
                print(
                    "[Tickets] ALERT ambiguous_creation_channels "
                    f"creation_id={creation_state['_id']} matches={len(matches)}"
                )
        else:
            return False
    except hikari.NotFoundError:
        missing = True
    except Exception as error:
        print(
            "[Tickets] WARNING creation_channel_check_failed "
            f"creation_id={creation_state['_id']} "
            f"channel_id={channel_id or 'unknown'} "
            f"error={type(error).__name__}"
        )
        return False

    if channel_exists:
        owner_filter = (
            {"$exists": False}
            if creation_state.get("lease_owner") is None
            else creation_state["lease_owner"]
        )
        await mongo.ticket_creation_state.update_one(
            {
                "_id": creation_state["_id"],
                "state": creation_state.get("state"),
                "channel_id": channel_id,
                "lease_owner": owner_filter,
            },
            {
                "$set": {
                    "state": "cleanup_required",
                    "updated_at": now,
                },
                "$unset": {
                    "lease_owner": "",
                    "lease_until": "",
                    "expires_at": "",
                },
            },
        )
        return False

    if (
        missing
        and creation_state.get("channel_create_state") == "requested"
    ):
        owner_filter = (
            {"$exists": False}
            if creation_state.get("lease_owner") is None
            else creation_state["lease_owner"]
        )
        await mongo.ticket_creation_state.update_one(
            {
                "_id": creation_state["_id"],
                "state": creation_state.get("state"),
                "channel_name": channel_name,
                "lease_owner": owner_filter,
            },
            {
                "$set": {
                    "state": "cleanup_required",
                    "updated_at": now,
                    "channel_check_error": "unconfirmed_create_request",
                },
                "$unset": {
                    "lease_owner": "",
                    "lease_until": "",
                    "expires_at": "",
                },
            },
        )
        return False

    if missing:
        delete_filter = {
            "_id": creation_state["_id"],
            "state": creation_state.get("state"),
        }
        if creation_state.get("lease_owner") is None:
            delete_filter["lease_owner"] = {"$exists": False}
        else:
            delete_filter["lease_owner"] = creation_state["lease_owner"]
        if channel_id:
            delete_filter["channel_id"] = channel_id
        else:
            delete_filter["channel_name"] = channel_name
        try:
            result = await mongo.ticket_creation_state.delete_one(delete_filter)
        except Exception as error:
            print(
                "[Tickets] WARNING missing_channel_blocker_release_failed "
                f"creation_id={creation_state['_id']} "
                f"error={type(error).__name__}"
            )
            return False
        if not getattr(result, "deleted_count", 0):
            return False
        print(
            "[Tickets] stale_creation_blocker_released "
            f"creation_id={creation_state['_id']} "
            f"channel_id={channel_id or 'unknown'}"
        )
        return True
    return False


async def locate_uncertain_channel(
        bot: hikari.GatewayBot,
        guild_id: int,
        category_id: int,
        channel_name: str,
):
    """Find the unique channel Discord may have created before a lost response."""
    for attempt in range(UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS):
        channels = await bot.rest.fetch_guild_channels(guild_id)
        matches = [
            item for item in channels
            if str(getattr(item, "name", "")).casefold() == channel_name.casefold()
            and getattr(item, "parent_id", None) is not None
            and int(item.parent_id) == int(category_id)
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"ambiguous Discord channel result ({len(matches)} matches)"
            )
        if matches:
            return matches[0]
        if attempt + 1 < UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS:
            await asyncio.sleep(UNCERTAIN_CHANNEL_LOOKUP_DELAY_SECONDS)
    return None


def cleanup_expired_cooldowns():
    """Remove expired cooldown entries to prevent memory leak"""
    global last_cleanup
    current_time = datetime.now(timezone.utc)

    # Only cleanup if enough time has passed
    if (current_time - last_cleanup).total_seconds() < COOLDOWN_CLEANUP_INTERVAL:
        return

    # Remove expired entries
    expired_users = []
    for user_id, cooldown_time in user_cooldowns.items():
        if (current_time - cooldown_time).total_seconds() > COOLDOWN_DURATION:
            expired_users.append(user_id)

    for user_id in expired_users:
        user_cooldowns.pop(user_id, None)

    if expired_users:
        print(f"[Tickets] Cleaned up {len(expired_users)} expired cooldown entries")

    last_cleanup = current_time


async def check_category_space(bot: hikari.GatewayBot, category_id: int, ticket_type: str, admin_id: int,
                               guild_id: int) -> int:
    """Check how many more channels can be created in a category and notify admin if low"""
    try:
        # Get all channels in the guild
        guild_channels = await bot.rest.fetch_guild_channels(guild_id)

        # Count channels in this specific category
        # int() on both sides: parent_id is a Snowflake and category_id may arrive as
        # a string from Mongo, and a type mismatch here fails open (reports 50 free).
        channels_in_category = [
            ch for ch in guild_channels
            if getattr(ch, 'parent_id', None) is not None
            and int(ch.parent_id) == int(category_id)
        ]

        # Get category info for better logging
        try:
            category = await bot.rest.fetch_channel(category_id)
            category_name = category.name
        except:
            category_name = "Unknown"

        # Discord limit is 50 channels per category
        used_slots = len(channels_in_category)
        remaining_slots = 50 - used_slots

        # Enhanced logging
        print(f"[Tickets] Category Space Check:")
        print(f"  - Category: {category_name} (ID: {category_id})")
        print(f"  - Type: {ticket_type.upper()}")
        print(f"  - Channels Used: {used_slots}/50")
        print(f"  - Remaining Slots: {remaining_slots}")
        print(f"  - Guild Channels Total: {len(guild_channels)}/500")  # free, already fetched above

        # Show first 5 channel names as examples
        if channels_in_category:
            print(f"  - Example channels:")
            for i, channel in enumerate(channels_in_category[:5]):
                print(f"    • {channel.name}")
            if len(channels_in_category) > 5:
                print(f"    ... and {len(channels_in_category) - 5} more")

        # Check if we need to notify admin
        if remaining_slots <= CHANNEL_WARNING_THRESHOLD:
            try:
                admin_user = await bot.rest.fetch_user(admin_id)
                dm_channel = await admin_user.fetch_dm_channel()

                # Enhanced warning message with more details
                await dm_channel.send(
                    f"⚠️ **Low Channel Space Warning**\n\n"
                    f"**Category:** {category_name}\n"
                    f"**Type:** {ticket_type.upper()} tickets\n"
                    f"**Category ID:** `{category_id}`\n\n"
                    f"**Space Usage:**\n"
                    f"• Used: {used_slots}/50 channels\n"
                    f"• Remaining: **{remaining_slots} slots**\n\n"
                    f"⚠️ **Action Required:**\n"
                    f"Please run `/ticket change-category type:{ticket_type}` to set up a new category.\n\n"
                    f"*This warning triggers when 5 or fewer slots remain.*"
                )

                print(f"[Tickets] ⚠️ Admin notified about low space in {category_name}")
            except Exception as e:
                print(f"[Tickets] Failed to DM admin about low channel space: {e}")

        return remaining_slots

    except Exception as e:
        print(f"[Tickets] Error checking category space: {e}")
        return -1  # Return -1 to indicate error


async def _create_thread_runtime_ticket(
        ctx: lightbulb.components.MenuContext,
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        ticket_type: str,
        now: datetime,
        slot_claim,
) -> None:
    """Promote the stable public panel into the thread runtime after cutover."""
    # Local import keeps the two extension loaders independent at startup.
    from extensions.commands import tickets as thread_tickets
    from extensions.commands.tickets import thread_service

    if not thread_tickets.thread_intake_ready():
        await ctx.interaction.edit_initial_response(
            content=(
                "❌ Thread ticketing is still starting. Your place is saved; "
                "please try again in a moment."
            )
        )
        return

    try:
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    except Exception as error:
        await cancel_claimed_open_slot(mongo, slot_claim)
        print(
            "[Tickets:Legacy] promoted_config_load_failed "
            f"guild={ctx.guild_id} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticket configuration could not be loaded. Nothing was created."
        )
        return
    display_name = (
        getattr(ctx.member, "display_name", None)
        if getattr(ctx, "member", None)
        else None
    )
    try:
        result = await thread_service.create_live_thread_ticket(
            bot=bot,
            mongo=mongo,
            guild_id=int(ctx.guild_id),
            user_id=int(ctx.user.id),
            username=ctx.user.username,
            display_name=display_name,
            ticket_type=ticket_type,
            config=config,
            open_slot_claim=slot_claim,
        )
    except thread_service.ThreadCreationBusy:
        await ctx.interaction.edit_initial_response(
            content="⏳ Your ticket is already being created. Please try again in a moment."
        )
        return
    except thread_service.ThreadConfigurationError as error:
        await ctx.interaction.edit_initial_response(
            content=f"❌ Thread ticketing is not ready: {error}. Please contact an administrator."
        )
        return
    except hikari.RateLimitTooLongError:
        user_cooldowns[int(ctx.user.id)] = now + timedelta(seconds=RATE_LIMIT_BACKOFF)
        await ctx.interaction.edit_initial_response(
            content="⏰ Discord is rate-limiting ticket creation. Please try again in a few minutes."
        )
        return
    except Exception as error:
        print(
            "[Tickets:Legacy] promoted_thread_creation_failed "
            f"guild={ctx.guild_id} user={ctx.user.id} "
            f"type={ticket_type} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content=(
                "❌ Your ticket could not be completed safely. The attempt was saved "
                "and can resume without duplicates. Please try again or contact an administrator."
            )
        )
        return

    ticket = result.ticket
    location = ticket.get("location") or {}
    location_id = int(
        location.get("id")
        or ticket.get("public_thread_id")
        or ticket.get("channel_id")
    )
    wording = "already open" if result.resumed else "created"
    delivery_note = (
        " Setup messages are retrying automatically."
        if result.delivery_pending
        else ""
    )
    await ctx.interaction.edit_initial_response(
        content=(
            f"✅ Your {ticket_type.upper()} ticket is {wording}: <#{location_id}>"
            f"{delivery_note}"
        )
    )


def _thread_intake_is_ready() -> bool:
    """Read v2 startup readiness without coupling the extension loaders."""
    from extensions.commands import tickets as thread_tickets

    return thread_tickets.thread_intake_ready()


@register_action(
    "create_ticket", opens_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def handle_create_ticket(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle ticket creation button clicks"""

    # Defer interaction immediately to prevent timeout
    await ctx.defer(ephemeral=True)

    # Determine ticket type from action_id
    ticket_type = action_id  # Will be "main" or "fwa"
    if ticket_type not in {"main", "fwa"}:
        await ctx.interaction.edit_initial_response(
            content="❌ That ticket type is not available."
        )
        return

    interaction_message = getattr(ctx.interaction, "message", None)
    message_id = store.as_int(getattr(interaction_message, "id", 0))
    member_roles = tuple(
        int(role_id)
        for role_id in (getattr(getattr(ctx, "member", None), "role_ids", ()) or ())
    )
    try:
        route = await ticket_runtime.route_public_intake(
            mongo,
            requested_route=ticket_runtime.ROUTE_LEGACY,
            guild_id=store.as_int(ctx.guild_id),
            channel_id=store.as_int(ctx.channel_id),
            message_id=message_id,
            user_id=int(ctx.user.id),
            member_role_ids=member_roles,
            ticket_type=ticket_type,
        )
    except Exception as error:
        print(
            "[Tickets:Legacy] intake_gate_failed "
            f"guild={ctx.guild_id} channel={ctx.channel_id} "
            f"message={message_id} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticketing is temporarily unavailable. Nothing was created."
        )
        return
    if not route.allowed:
        await ctx.interaction.edit_initial_response(
            content=(
                "❌ This ticket panel has been retired. "
                "Use the current ticket panel or contact a recruiter."
            )
        )
        return

    user_id = int(ctx.user.id)
    try:
        existing_ticket = await find_open_ticket(mongo, user_id, ticket_type)
    except Exception as error:
        print(
            "[Tickets:Legacy] open_ticket_lookup_failed "
            f"guild={ctx.guild_id} user={user_id} "
            f"type={ticket_type} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticketing is temporarily unavailable. Nothing was created."
        )
        return
    if existing_ticket is not None:
        location_id = _ticket_location_id(existing_ticket)
        location = f" <#{location_id}>" if location_id else ""
        await ctx.interaction.edit_initial_response(
            content=(
                f"✅ You already have an open {ticket_type.upper()} ticket.{location}"
            )
        )
        return

    try:
        sticky_slot = await _existing_public_open_slot(mongo, user_id, ticket_type)
    except Exception as error:
        print(
            "[Tickets:Legacy] open_slot_lookup_failed "
            f"guild={ctx.guild_id} user={user_id} "
            f"type={ticket_type} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticketing is temporarily unavailable. Nothing was created."
        )
        return
    effective_route = (
        sticky_slot.get("route")
        if sticky_slot is not None
        else route.route
    )

    # Recovery/readiness is checked before a promoted click creates or resumes
    # any slot and before it enters the local cooldown. Existing sticky slots are
    # deliberately left untouched so startup recovery can resume them later.
    if effective_route == ticket_runtime.ROUTE_THREAD and not _thread_intake_is_ready():
        if sticky_slot is None:
            content = (
                "❌ Thread ticketing is still starting. Nothing was created; "
                "please try again in a moment."
            )
        else:
            content = (
                "❌ Thread ticketing is still starting. Your prior ticket attempt "
                "remains saved; please try again in a moment."
            )
        await ctx.interaction.edit_initial_response(
            content=content
        )
        return

    cleanup_expired_cooldowns()
    current_time = datetime.now(timezone.utc)
    if user_id in user_cooldowns:
        time_since_last = (current_time - user_cooldowns[user_id]).total_seconds()
        if time_since_last < COOLDOWN_DURATION:
            remaining = int(COOLDOWN_DURATION - time_since_last)
            await ctx.interaction.edit_initial_response(
                content=f"⏳ Please wait {remaining} seconds before creating another ticket."
            )
            return
    user_cooldowns[user_id] = current_time
    await ctx.interaction.edit_initial_response(content="🎫 Creating your ticket...")

    try:
        slot_claim = await claim_public_open_slot(
            mongo,
            route=route.route,
            rollout_revision=int(route.revision),
            guild_id=int(ctx.guild_id),
            user_id=user_id,
            ticket_type=ticket_type,
        )
    except Exception as error:
        print(
            "[Tickets:Legacy] public_slot_claim_failed "
            f"guild={ctx.guild_id} user={user_id} "
            f"type={ticket_type} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticketing is temporarily unavailable. Nothing was created."
        )
        return

    if not slot_claim.won:
        existing_location = store.as_int(slot_claim.slot.get("location_id"))
        if existing_location:
            message = (
                f"✅ You already have an open {ticket_type.upper()} ticket. "
                f"Please check <#{existing_location}>"
            )
        elif slot_claim.slot.get("state") == ticket_runtime.SLOT_CLEANUP_REQUIRED:
            message = (
                "⚠️ A previous ticket attempt needs staff cleanup before another "
                "can be created. Please contact an administrator."
            )
        else:
            message = (
                f"⏳ Your {ticket_type.upper()} ticket is already being created. "
                "Please try again in a moment."
            )
        await ctx.interaction.edit_initial_response(content=message)
        return

    sticky_route = str(slot_claim.slot.get("route") or "")
    if sticky_route == ticket_runtime.ROUTE_THREAD:
        await _create_thread_runtime_ticket(
            ctx, bot, mongo, ticket_type, current_time, slot_claim
        )
        return
    if sticky_route != ticket_runtime.ROUTE_LEGACY:
        await cancel_claimed_open_slot(mongo, slot_claim)
        await ctx.interaction.edit_initial_response(
            content="❌ This ticket panel cannot determine the active ticket system."
        )
        return

    # Get current configuration from database
    try:
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    except Exception as error:
        await cancel_claimed_open_slot(mongo, slot_claim)
        print(
            "[Tickets:Legacy] config_load_failed "
            f"guild={ctx.guild_id} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Ticket configuration could not be loaded. Nothing was created."
        )
        return

    print(f"[Tickets] Creating {ticket_type} ticket for user {ctx.user.username}")
    print(f"[Tickets] Config loaded: {config}")

    # Get the appropriate category and role. The counter is reserved atomically
    # inside the creation semaphore after idempotency checks pass.
    if ticket_type == "main":
        category_id = config.get("main_category", DEFAULT_MAIN_CATEGORY)
        recruiter_role = config.get("main_recruiter_role")
        ticket_prefix = "main"
        ticket_title = "Main Clan"
    else:
        category_id = config.get("fwa_category", DEFAULT_FWA_CATEGORY)
        recruiter_role = config.get("fwa_recruiter_role")
        ticket_prefix = "fwa"
        ticket_title = "FWA Clan"

    # Coerce here, not at the comparison site: a string category id from a manual
    # Mongo edit makes the parent_id comparison in check_category_space always False,
    # which silently reports 50 free slots on a category that is actually full.
    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        await cancel_claimed_open_slot(mongo, slot_claim)
        print(f"[Tickets] ERROR: {ticket_type} category id is not numeric: {category_id!r}")
        await ctx.interaction.edit_initial_response(
            content=f"❌ The {ticket_title} ticket category is misconfigured.\n"
                    f"Please contact an administrator."
        )
        return

    print(f"[Tickets] Using category {category_id}, recruiter role: {recruiter_role}")

    admin_to_notify = config.get("admin_to_notify", DEFAULT_ADMIN_TO_NOTIFY)

    # Check category space before creating
    remaining_slots = await check_category_space(bot, category_id, ticket_type, admin_to_notify, ctx.guild_id)

    if remaining_slots < 0:
        await cancel_claimed_open_slot(mongo, slot_claim)
        # check_category_space returns -1 when the check itself failed. Fail closed:
        # attempting a create we could not validate is how channels get orphaned.
        await ctx.interaction.edit_initial_response(
            content=f"❌ Could not verify space in the {ticket_title} ticket category.\n"
                    f"Please try again in a moment or contact an administrator."
        )
        return

    if remaining_slots == 0:
        await cancel_claimed_open_slot(mongo, slot_claim)
        # Send error response
        await ctx.interaction.edit_initial_response(
            content=f"❌ The {ticket_title} ticket category is full!\nPlease contact an administrator."
        )
        return

    creation_id = _creation_id(ctx.guild_id, user_id, ticket_type)
    workflow_id = str(slot_claim.slot["workflow_id"])
    slot_rollout_revision = int(
        slot_claim.slot.get("rollout_revision", route.revision)
    )
    creation_claimed = False
    slot_id = str(slot_claim.slot["_id"])
    slot_owner = str(slot_claim.owner_token)
    channel = None
    thread = None
    channel_name = None
    channel_create_started = False
    ticket_data = None
    ticket_persisted = False
    commit_intent_started = False
    creation_owner = None
    creation_state = None

    # Use the in-process semaphore to reduce Discord rate pressure. The Mongo
    # lease below is the cross-process/restart idempotency boundary.
    async with channel_creation_semaphore:
        try:
            existing_ticket = await find_open_ticket(mongo, user_id, ticket_type)
            if existing_ticket:
                await ticket_runtime.cancel_open_slot(
                    mongo,
                    slot_id=slot_id,
                    owner_token=slot_owner,
                    workflow_id=workflow_id,
                )
                location_id = _ticket_location_id(existing_ticket)
                await ctx.interaction.edit_initial_response(
                    content=(
                        f"✅ You already have an open {ticket_title} ticket.\n"
                        f"Please check <#{location_id}>"
                    )
                )
                return

            creation_claimed, creation_state = await claim_ticket_creation(
                mongo,
                ctx.guild_id,
                user_id,
                ticket_type,
                slot_id=slot_id,
                workflow_id=workflow_id,
            )
            if (
                not creation_claimed
                and (
                    creation_state.get("channel_id")
                    or creation_state.get("channel_name")
                    or creation_state.get("state") == "cleanup_required"
                )
                and await release_missing_channel_blocker(bot, mongo, creation_state)
            ):
                creation_claimed, creation_state = await claim_ticket_creation(
                    mongo,
                    ctx.guild_id,
                    user_id,
                    ticket_type,
                    slot_id=slot_id,
                    workflow_id=workflow_id,
                )
            if not creation_claimed:
                existing_channel = creation_state.get("channel_id")
                if existing_channel:
                    await ctx.interaction.edit_initial_response(
                        content=(
                            "⚠️ A previous ticket attempt already created a channel "
                            f"(<#{existing_channel}>). Another was not created.\n"
                            "Please contact an administrator if it needs cleanup."
                        )
                    )
                elif creation_state.get("state") == "cleanup_required":
                    await ctx.interaction.edit_initial_response(
                        content=(
                            "⚠️ A previous ticket attempt could not be reconciled safely.\n"
                            "Another was not created. Please contact an administrator."
                        )
                    )
                else:
                    await ctx.interaction.edit_initial_response(
                        content=(
                            f"⏳ Your {ticket_title} ticket is already being created.\n"
                            "Please wait a moment instead of submitting it again."
                        )
                    )
                return

            creation_owner = str(creation_state["lease_owner"])

            stored_category_id = store.as_int(creation_state.get("category_id"))
            if stored_category_id and stored_category_id != int(category_id):
                await mark_creation_uncertain(
                    mongo,
                    creation_id,
                    creation_owner,
                    last_error="category_binding_changed",
                    configured_category_id=int(category_id),
                )
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⚠️ A previous ticket attempt could not be reconciled safely.\n"
                        "Another was not created. Please contact an administrator."
                    )
                )
                return

            ticket_number = store.as_int(creation_state.get("ticket_number"))
            if not ticket_number:
                ticket_number = await reserve_ticket_number(mongo, ticket_type)
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                ticket_number=ticket_number,
                category_id=category_id,
                route=ticket_runtime.ROUTE_LEGACY,
                runtime=store.LEGACY_RUNTIME,
                open_slot_id=slot_id,
                creation_workflow_id=workflow_id,
                rollout_revision=slot_rollout_revision,
            )
            print(
                f"[Tickets] Reserved {ticket_type} ticket number {ticket_number} "
                f"for user {user_id}"
            )

            # Create permission overwrites for the ticket channel
            permission_overwrites = [
                # Deny @everyone
                hikari.PermissionOverwrite(
                    id=ctx.guild_id,  # @everyone role has same ID as guild
                    type=hikari.PermissionOverwriteType.ROLE,
                    deny=(
                            hikari.Permissions.VIEW_CHANNEL |
                            hikari.Permissions.SEND_MESSAGES |
                            hikari.Permissions.READ_MESSAGE_HISTORY
                    ),
                ),
                # Allow the ticket creator
                hikari.PermissionOverwrite(
                    id=ctx.user.id,
                    type=hikari.PermissionOverwriteType.MEMBER,
                    allow=(
                            hikari.Permissions.VIEW_CHANNEL |
                            hikari.Permissions.SEND_MESSAGES |
                            hikari.Permissions.READ_MESSAGE_HISTORY |
                            hikari.Permissions.ATTACH_FILES |
                            hikari.Permissions.EMBED_LINKS |
                            hikari.Permissions.ADD_REACTIONS
                    ),
                ),
            ]

            # Add recruiter role permissions if configured
            if recruiter_role:
                permission_overwrites.append(
                    hikari.PermissionOverwrite(
                        id=recruiter_role,
                        type=hikari.PermissionOverwriteType.ROLE,
                        allow=(
                                hikari.Permissions.VIEW_CHANNEL |
                                hikari.Permissions.SEND_MESSAGES |
                                hikari.Permissions.READ_MESSAGE_HISTORY |
                                hikari.Permissions.ATTACH_FILES |
                                hikari.Permissions.EMBED_LINKS |
                                hikari.Permissions.MANAGE_MESSAGES |
                                hikari.Permissions.MANAGE_CHANNELS |
                                hikari.Permissions.ADD_REACTIONS
                        ),
                    )
                )

            # Create the ticket channel with new naming format: 🆕{type}-{number}-{username}
            channel_name = f"🆕{ticket_prefix}-{ticket_number}-{ctx.user.username}"
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                channel_name=channel_name,
                channel_create_started_at=datetime.now(timezone.utc),
                channel_create_state="requested",
            )

            channel_create_started = True
            channel = await bot.rest.create_guild_text_channel(
                guild=ctx.guild_id,
                name=channel_name,
                category=category_id,
                permission_overwrites=permission_overwrites,
                reason=f"{ticket_title} ticket for {ctx.user.username}"
            )
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                channel_id=int(channel.id),
                channel_create_state="created",
                channel_created_at=datetime.now(timezone.utc),
            )

            # Create the thread under the ticket channel
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                thread_create_started_at=datetime.now(timezone.utc),
                thread_create_state="requested",
            )
            thread = await bot.rest.create_thread(
                channel.id,
                hikari.ChannelType.GUILD_PRIVATE_THREAD,
                f"private-{ctx.user.username}",
                auto_archive_duration=10080,  # 7 days
                invitable=False,
                reason="Private thread for recruiters"
            )
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                thread_id=int(thread.id),
                thread_create_state="created",
                thread_created_at=datetime.now(timezone.utc),
            )

            print(f"[Tickets] Created thread {thread.id} for ticket {channel.id}")

            # Ensure the bot joins the thread
            try:
                await bot.rest.add_thread_member(thread.id, bot.get_me().id)
                print(f"[Tickets] Bot joined thread {thread.id}")
            except Exception as e:
                print(f"[Tickets] Failed to add bot to thread: {e}")

            # Store ticket information
            ticket_data = {
                "_id": f"ticket_{channel.id}",
                "type": "ticket",
                "ticket_type": ticket_type,
                "ticket_number": ticket_number,
                "guild_id": ctx.guild_id,
                "channel_id": channel.id,
                "thread_id": thread.id,
                "category_id": category_id,
                "user_id": ctx.user.id,
                "username": ctx.user.username,
                "created_at": datetime.now(timezone.utc),
                "status": "open",
                "venue": "channel",
                "runtime": store.LEGACY_RUNTIME,
                "open_slot_id": slot_id,
                "creation_workflow_id": workflow_id,
                "rollout_revision": slot_rollout_revision,
                "creation_generation": store.as_int(
                    creation_state.get("attempt_generation")
                ),
            }
            await update_creation_state(
                mongo,
                creation_id,
                creation_owner,
                ticket_id=ticket_data["_id"],
                ticket_payload=dict(ticket_data),
                commit_started_at=datetime.now(timezone.utc),
            )
            commit_intent_started = True
            await store.insert_one(mongo, ticket_data)
            ticket_persisted = True
            # The authoritative ticket is also the durable source for startup
            # synthesis. Materialize its exact delivery row immediately so a
            # slow gateway channel event cannot lose the candidate opening.
            await _queue_committed_initial_delivery(bot, mongo, ticket_data)
            await ticket_runtime.bind_open_slot(
                mongo,
                slot_id=slot_id,
                owner_token=slot_owner,
                ticket_id=ticket_data["_id"],
                location_id=int(channel.id),
            )
            await complete_creation_state(
                mongo,
                creation_id,
                creation_owner,
                channel.id,
                thread.id,
                ticket_data["_id"],
            )

            # Everything below is post-commit setup. A message failure must not
            # turn a real, durable ticket into an apparent creation failure.
            await _drive_committed_initial_delivery(bot, mongo, ticket_data)

            # Send success message as response
            await ctx.interaction.edit_initial_response(
                content=f"✅ Your {ticket_title} ticket has been created!\nPlease check <#{channel.id}>"
            )

        except hikari.errors.RateLimitTooLongError as e:
            # Preserve the existing rate-limit behavior and release any creation
            # lease because Discord did not accept the operation.
            user_cooldowns[user_id] = current_time + timedelta(seconds=RATE_LIMIT_BACKOFF)
            if creation_claimed and not ticket_persisted:
                await rollback_ticket_creation(
                    bot,
                    mongo,
                    creation_id,
                    int(channel.id) if channel is not None else None,
                    e,
                    lease_owner=str(creation_owner),
                    slot_id=slot_id,
                    slot_owner=slot_owner,
                    workflow_id=workflow_id,
                )
            elif not ticket_persisted and creation_state is None:
                await cancel_slot_if_creation_absent(
                    mongo, slot_claim, creation_id
                )
            print(f"[Tickets] Rate limit exceeded maximum wait time: {e}")
            await ctx.interaction.edit_initial_response(
                content=(
                    "⏰ **Discord Rate Limit Active**\n\n"
                    "Too many channels were created recently. Please try again in a few minutes."
                )
            )
        except Exception as e:
            discord_check_failed = None
            if (
                creation_claimed
                and channel is None
                and channel_name is not None
                and channel_create_started
            ):
                try:
                    channel = await locate_uncertain_channel(
                        bot,
                        ctx.guild_id,
                        category_id,
                        channel_name,
                    )
                    if channel is not None:
                        print(
                            "[Tickets] creation_channel_confirmed_after_error "
                            f"creation_id={creation_id} channel_id={channel.id}"
                        )
                except Exception as check_error:
                    discord_check_failed = check_error

            commit_check_failed = None
            if not ticket_persisted and ticket_data is not None:
                try:
                    committed = await store.find_one(
                        mongo,
                        {"_id": ticket_data["_id"]},
                    )
                except Exception as check_error:
                    committed = None
                    commit_check_failed = check_error
                if committed is not None:
                    try:
                        await store.ensure_exact_ticket(
                            mongo,
                            ticket_data,
                            allow_terminal=True,
                        )
                    except Exception as identity_error:
                        committed = None
                        commit_check_failed = identity_error
                    else:
                        ticket_persisted = True
                        print(
                            "[Tickets] creation_commit_confirmed_after_error "
                            f"ticket_id={ticket_data['_id']} "
                            f"original_error={type(e).__name__}"
                        )

            print(
                "[Tickets] creation_failed "
                f"creation_id={creation_id} error={type(e).__name__} "
                f"detail={_error_detail(e)}"
            )
            if ticket_persisted:
                # The primary ticket record is the commit point. Even if the
                # completion marker or interaction response failed, retry lookup
                # returns this ticket rather than creating another.
                try:
                    await recover_uncertain_legacy_ticket_creation(
                        bot=bot,
                        mongo=mongo,
                        creation_id=creation_id,
                        slot_owner_token=slot_owner,
                        creation_owner_token=str(creation_owner),
                        expected_ticket_id=ticket_data["_id"],
                        expected_generation=store.as_int(
                            creation_state.get("attempt_generation")
                        ),
                    )
                except Exception as recovery_error:
                    print(
                        "[Tickets:Legacy] confirmed_commit_recovery_deferred "
                        f"creation_id={creation_id} "
                        f"error={type(recovery_error).__name__}"
                    )
                    try:
                        schedule_uncertain_legacy_ticket_recovery(
                            bot=bot,
                            mongo=mongo,
                            creation_id=creation_id,
                            slot_owner_token=slot_owner,
                            creation_owner_token=str(creation_owner),
                            expected_ticket_id=ticket_data["_id"],
                            expected_generation=store.as_int(
                                creation_state.get("attempt_generation")
                            ),
                        )
                    except RuntimeError:
                        pass
                await ctx.interaction.edit_initial_response(
                    content=(
                        f"✅ Your {ticket_title} ticket was created.\n"
                        f"Please check <#{channel.id}>"
                    )
                )
                return

            if channel_create_started and channel is None:
                check_error = (
                    type(discord_check_failed).__name__
                    if discord_check_failed is not None
                    else "channel_not_confirmed_after_create_error"
                )
                try:
                    await mark_creation_uncertain(
                        mongo,
                        creation_id,
                        str(creation_owner),
                        channel_name=channel_name,
                        category_id=category_id,
                        last_error=type(e).__name__,
                        channel_check_error=check_error,
                    )
                except Exception as state_error:
                    print(
                        "[Tickets] ALERT creation_channel_uncertain_state_failed "
                        f"creation_id={creation_id} error={type(state_error).__name__}"
                    )
                print(
                    "[Tickets] ALERT creation_channel_uncertain "
                    f"creation_id={creation_id} "
                    f"error={check_error}"
                )
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⚠️ Discord could not confirm whether the ticket channel was created.\n"
                        "Another ticket was not created. Please contact an administrator."
                    )
                )
                return

            if commit_intent_started:
                # Once the authoritative write is attempted, one negative read
                # cannot prove it did not commit or will not finish later. Keep
                # every Discord/slot identifier for online/startup reconciliation.
                commit_check_error = (
                    type(commit_check_failed).__name__
                    if commit_check_failed is not None
                    else "authoritative_ticket_not_visible"
                )
                retained = False
                try:
                    retained = await mark_creation_uncertain(
                        mongo,
                        creation_id,
                        str(creation_owner),
                        channel_id=int(channel.id),
                        thread_id=(
                            int(thread.id) if thread is not None else None
                        ),
                        ticket_id=ticket_data["_id"],
                        last_error=type(e).__name__,
                        commit_check_error=commit_check_error,
                    )
                except Exception as state_error:
                    print(
                        "[Tickets] ALERT creation_commit_uncertain_state_failed "
                        f"creation_id={creation_id} channel_id={channel.id} "
                        f"error={type(state_error).__name__}"
                    )
                if retained:
                    try:
                        recovered = await recover_uncertain_legacy_ticket_creation(
                            bot=bot,
                            mongo=mongo,
                            creation_id=creation_id,
                            slot_owner_token=slot_owner,
                            expected_ticket_id=ticket_data["_id"],
                            expected_generation=store.as_int(
                                creation_state.get("attempt_generation")
                            ),
                        )
                    except Exception as recovery_error:
                        recovered = False
                        print(
                            "[Tickets:Legacy] commit_recovery_deferred "
                            f"creation_id={creation_id} "
                            f"error={type(recovery_error).__name__}"
                        )
                        try:
                            schedule_uncertain_legacy_ticket_recovery(
                                bot=bot,
                                mongo=mongo,
                                creation_id=creation_id,
                                slot_owner_token=slot_owner,
                                creation_owner_token=str(creation_owner),
                                expected_ticket_id=ticket_data["_id"],
                                expected_generation=store.as_int(
                                    creation_state.get("attempt_generation")
                                ),
                            )
                        except RuntimeError:
                            pass
                    if recovered:
                        await ctx.interaction.edit_initial_response(
                            content=(
                                f"✅ Your {ticket_title} ticket was created.\n"
                                f"Please check <#{channel.id}>"
                            )
                        )
                        return
                elif ticket_data is not None:
                    try:
                        schedule_uncertain_legacy_ticket_recovery(
                            bot=bot,
                            mongo=mongo,
                            creation_id=creation_id,
                            slot_owner_token=slot_owner,
                            creation_owner_token=str(creation_owner),
                            expected_ticket_id=ticket_data["_id"],
                            expected_generation=store.as_int(
                                creation_state.get("attempt_generation")
                            ),
                        )
                    except RuntimeError:
                        pass
                print(
                    "[Tickets] ALERT creation_commit_uncertain "
                    f"creation_id={creation_id} channel_id={channel.id} "
                    f"error={commit_check_error}"
                )
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⚠️ Ticket creation could not be confirmed safely.\n"
                        "Another ticket was not created. Please contact an administrator."
                    )
                )
                return

            cleanup_ok = True
            if creation_claimed:
                cleanup_ok = await rollback_ticket_creation(
                    bot,
                    mongo,
                    creation_id,
                    int(channel.id) if channel is not None else None,
                    e,
                    lease_owner=str(creation_owner),
                    slot_id=slot_id,
                    slot_owner=slot_owner,
                    workflow_id=workflow_id,
                )
            elif creation_state is None:
                cleanup_ok = await cancel_slot_if_creation_absent(
                    mongo, slot_claim, creation_id
                )
            else:
                # A pre-existing or uncertain local attempt owns this slot's
                # durable evidence. Never turn an interaction failure into a
                # slot cancellation that permits a duplicate.
                cleanup_ok = False
            if cleanup_ok:
                content = (
                    "❌ Your ticket could not be created. Nothing was left behind.\n"
                    "Please try again in a moment or contact an administrator."
                )
            else:
                content = (
                    "⚠️ Ticket creation stopped, but Discord cleanup also failed.\n"
                    "Another ticket was not created. Please contact an administrator."
                )
            await ctx.interaction.edit_initial_response(content=content)
