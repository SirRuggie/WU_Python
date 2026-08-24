"""Shared durability primitives for the legacy and thread ticket runtimes.

This module deliberately knows nothing about Discord views or command routing.  It
owns the small amount of state which *must* be shared while both runtimes coexist:
rollout routing, one-open-ticket slots, and monotonically increasing ticket
numbers.  Legacy ticket documents remain authoritative in ``button_store`` and
thread ticket documents remain authoritative in ``tickets``.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError


ROLLOUT_ID = "ticket-runtime"
ROLLOUT_SCHEMA_VERSION = 1

PHASE_LEGACY_ONLY = "legacy_only"
PHASE_PREPARED = "prepared"
PHASE_PILOT = "pilot"
PHASE_THREAD_DEFAULT = "thread_default"
PHASE_ROLLBACK_LEGACY = "rollback_legacy"
PHASE_THREAD_ONLY = "thread_only"
VALID_PHASES = frozenset(
    {
        PHASE_LEGACY_ONLY,
        PHASE_PREPARED,
        PHASE_PILOT,
        PHASE_THREAD_DEFAULT,
        PHASE_ROLLBACK_LEGACY,
        PHASE_THREAD_ONLY,
    }
)

ROUTE_LEGACY = "legacy"
ROUTE_THREAD = "thread"
ROUTE_REJECT = "reject"
VALID_ROUTES = frozenset({ROUTE_LEGACY, ROUTE_THREAD})

SLOT_RESERVED = "reserved"
SLOT_OPEN = "open"
SLOT_RELEASE_PENDING = "release_pending"
SLOT_CLEANUP_REQUIRED = "cleanup_required"
ACTIVE_SLOT_STATES = frozenset(
    {SLOT_RESERVED, SLOT_OPEN, SLOT_RELEASE_PENDING, SLOT_CLEANUP_REQUIRED}
)

THREAD_RUNTIME = "thread_v2"
LEGACY_RUNTIME = "legacy_channel"
COUNTER_DOCUMENT_ID = "ticket_runtime_counters"

_DEFAULT_LEASE_SECONDS = 120
_VALID_TICKET_TYPES = frozenset({"main", "fwa"})
_ALLOWED_PHASE_TRANSITIONS = {
    PHASE_LEGACY_ONLY: frozenset({PHASE_PREPARED}),
    PHASE_PREPARED: frozenset({PHASE_LEGACY_ONLY, PHASE_PILOT}),
    PHASE_PILOT: frozenset({PHASE_THREAD_DEFAULT, PHASE_ROLLBACK_LEGACY}),
    PHASE_THREAD_DEFAULT: frozenset({PHASE_ROLLBACK_LEGACY, PHASE_THREAD_ONLY}),
    PHASE_ROLLBACK_LEGACY: frozenset(
        {PHASE_PREPARED, PHASE_PILOT, PHASE_THREAD_DEFAULT}
    ),
    PHASE_THREAD_ONLY: frozenset({PHASE_ROLLBACK_LEGACY}),
}


class TicketRuntimeError(RuntimeError):
    """Base exception for shared ticket runtime failures."""


class RolloutConflict(TicketRuntimeError):
    """The rollout document changed before a compare-and-swap completed."""


class InvalidRolloutTransition(TicketRuntimeError):
    """A requested rollout phase transition is not permitted."""


class LegacyDrainBlocked(TicketRuntimeError):
    """Thread-only activation was attempted while legacy work remains."""


class RuntimeReadinessBlocked(TicketRuntimeError):
    """Thread intake was attempted while shared recovery blockers remain."""


class SlotConflict(TicketRuntimeError):
    """A slot mutation did not match its owner and expected state."""


class BackfillLimitExceeded(TicketRuntimeError):
    """Startup found more un-slotted tickets than the audited bound."""


@dataclass(frozen=True, slots=True)
class IntakeSource:
    guild_id: int
    channel_id: int
    message_id: int

    def matches(self, *, guild_id: int, channel_id: int, message_id: int) -> bool:
        return (
            self.guild_id == int(guild_id)
            and self.channel_id == int(channel_id)
            and self.message_id == int(message_id)
        )


@dataclass(frozen=True, slots=True)
class RolloutState:
    phase: str
    revision: int
    valid: bool
    legacy_intake: IntakeSource | None = None
    thread_intake: IntakeSource | None = None
    pilot_intake: IntakeSource | None = None
    pilot_user_ids: tuple[int, ...] = ()
    pilot_role_ids: tuple[int, ...] = ()
    pilot_ticket_types: tuple[str, ...] = ("main", "fwa")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: str
    allowed: bool
    phase: str
    revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class SlotClaim:
    won: bool
    owner_token: str | None
    slot: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DrainStatus:
    legacy_open_tickets: int
    legacy_slots: int
    legacy_pending_workflows: int
    legacy_pending_deliveries: int = 0
    unresolved_conflicts: int = 0
    pending_delivery_ids: tuple[str, ...] = ()
    conflict_slot_ids: tuple[str, ...] = ()

    @property
    def drained(self) -> bool:
        return not (
            self.legacy_open_tickets
            or self.legacy_slots
            or self.legacy_pending_workflows
            or self.unresolved_conflicts
        )


@dataclass(frozen=True, slots=True)
class RuntimeBlockerStatus:
    legacy_pending_deliveries: int
    unresolved_conflicts: int
    pending_delivery_ids: tuple[str, ...] = ()
    conflict_slot_ids: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.legacy_pending_deliveries or self.unresolved_conflicts)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    released_slot_ids: tuple[str, ...]
    bound_slot_ids: tuple[str, ...]
    cleanup_required_slot_ids: tuple[str, ...]
    unchanged_slot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackfillResult:
    created_slot_ids: tuple[str, ...]
    existing_slot_ids: tuple[str, ...]
    conflicted_slot_ids: tuple[str, ...]
    skipped_ticket_ids: tuple[str, ...]


_DURABILITY_LOCK = asyncio.Lock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _intake_source(value: Any) -> IntakeSource | None:
    if not isinstance(value, Mapping):
        return None
    guild_id = _positive_int(value.get("guild_id"))
    channel_id = _positive_int(value.get("channel_id"))
    message_id = _positive_int(value.get("message_id"))
    if guild_id is None or channel_id is None or message_id is None:
        return None
    return IntakeSource(guild_id, channel_id, message_id)


def _id_tuple(values: Any) -> tuple[int, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(sorted({item for value in values if (item := _positive_int(value))}))


def _parse_rollout(document: Mapping[str, Any] | None) -> RolloutState:
    if not document:
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    phase = document.get("phase")
    revision = document.get("revision")
    if (
        document.get("schema_version") != ROLLOUT_SCHEMA_VERSION
        or phase not in VALID_PHASES
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    pilot = document.get("pilot") if isinstance(document.get("pilot"), Mapping) else {}
    ticket_types = pilot.get("ticket_types", ("main", "fwa"))
    if not isinstance(ticket_types, Sequence) or isinstance(ticket_types, (str, bytes)):
        ticket_types = ()
    normalized_types = tuple(
        sorted({str(item).strip().lower() for item in ticket_types} & _VALID_TICKET_TYPES)
    )
    legacy_intake = _intake_source(document.get("legacy_intake"))
    thread_intake = _intake_source(document.get("thread_intake"))
    pilot_intake = _intake_source(pilot.get("intake"))
    pilot_user_ids = _id_tuple(pilot.get("user_ids"))
    pilot_role_ids = _id_tuple(pilot.get("role_ids"))
    if (
        legacy_intake is None
        or thread_intake is None
        or pilot_intake is None
        or legacy_intake.guild_id == thread_intake.guild_id
        or thread_intake.guild_id != pilot_intake.guild_id
        or thread_intake.channel_id == pilot_intake.channel_id
        or not normalized_types
        or (not pilot_user_ids and not pilot_role_ids)
    ):
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    return RolloutState(
        phase=phase,
        revision=revision,
        valid=True,
        legacy_intake=legacy_intake,
        thread_intake=thread_intake,
        pilot_intake=pilot_intake,
        pilot_user_ids=pilot_user_ids,
        pilot_role_ids=pilot_role_ids,
        pilot_ticket_types=normalized_types,
    )


async def ensure_indexes(mongo: Any) -> None:
    """Create non-TTL indexes required by the shared durability layer."""

    await mongo.ticket_open_slots.create_index(
        [("ticket_id", ASCENDING)],
        name="ticket_open_slot_ticket_unique",
        unique=True,
        partialFilterExpression={"ticket_id": {"$exists": True}},
    )
    await mongo.ticket_open_slots.create_index(
        [("workflow_id", ASCENDING)],
        name="ticket_open_slot_workflow_unique",
        unique=True,
    )
    await mongo.ticket_open_slots.create_index(
        [("state", ASCENDING), ("updated_at", ASCENDING)],
        name="ticket_open_slot_reconcile",
    )
    await mongo.ticket_rollout.create_index(
        [("phase", ASCENDING), ("revision", ASCENDING)],
        name="ticket_rollout_phase_revision",
    )


async def get_rollout(mongo: Any) -> RolloutState:
    return _parse_rollout(await mongo.ticket_rollout.find_one({"_id": ROLLOUT_ID}))


def _source_document(value: IntakeSource | Mapping[str, Any]) -> dict[str, int]:
    source = value if isinstance(value, IntakeSource) else _intake_source(value)
    if source is None:
        raise ValueError("intake source requires positive guild/channel/message IDs")
    return {
        "guild_id": source.guild_id,
        "channel_id": source.channel_id,
        "message_id": source.message_id,
    }


def _pilot_document(value: Mapping[str, Any]) -> dict[str, Any]:
    source = _source_document(value.get("intake", {}))
    users = list(_id_tuple(value.get("user_ids", ())))
    roles = list(_id_tuple(value.get("role_ids", ())))
    raw_types = value.get("ticket_types", ("main", "fwa"))
    if not isinstance(raw_types, Sequence) or isinstance(raw_types, (str, bytes)):
        raise ValueError("pilot.ticket_types must be a sequence")
    ticket_types = sorted(
        {str(item).strip().lower() for item in raw_types} & _VALID_TICKET_TYPES
    )
    if not ticket_types:
        raise ValueError("pilot requires at least one ticket type")
    if not users and not roles:
        raise ValueError("pilot requires at least one exact user or role")
    return {
        "intake": source,
        "user_ids": users,
        "role_ids": roles,
        "ticket_types": ticket_types,
    }


async def seed_rollout(
    mongo: Any,
    *,
    actor_id: int,
    legacy_intake: IntakeSource | Mapping[str, Any],
    thread_intake: IntakeSource | Mapping[str, Any],
    pilot: Mapping[str, Any],
    now: datetime | None = None,
) -> RolloutState:
    """Insert the initial fail-safe rollout document without overwriting one."""

    moment = now or utcnow()
    legacy_document = _source_document(legacy_intake)
    thread_document = _source_document(thread_intake)
    pilot_document = _pilot_document(pilot)
    if legacy_document["guild_id"] == thread_document["guild_id"]:
        raise ValueError("legacy and thread intake must use different guilds")
    if thread_document["guild_id"] != pilot_document["intake"]["guild_id"]:
        raise ValueError("thread public and pilot intake must use the same target guild")
    if thread_document["channel_id"] == pilot_document["intake"]["channel_id"]:
        raise ValueError("thread public and pilot intake must use separate channels")
    document = {
        "_id": ROLLOUT_ID,
        "schema_version": ROLLOUT_SCHEMA_VERSION,
        "phase": PHASE_LEGACY_ONLY,
        "revision": 1,
        "legacy_intake": legacy_document,
        "thread_intake": thread_document,
        "pilot": pilot_document,
        "created_at": moment,
        "created_by": int(actor_id),
        "updated_at": moment,
        "updated_by": int(actor_id),
    }
    try:
        await mongo.ticket_rollout.insert_one(document)
    except DuplicateKeyError:
        state = await get_rollout(mongo)
        if not state.valid:
            raise RolloutConflict("the existing rollout document is invalid") from None
        return state
    return _parse_rollout(document)


async def configure_rollout(
    mongo: Any,
    *,
    expected_revision: int,
    actor_id: int,
    legacy_intake: IntakeSource | Mapping[str, Any],
    thread_intake: IntakeSource | Mapping[str, Any],
    pilot: Mapping[str, Any],
    now: datetime | None = None,
) -> RolloutState:
    """CAS-update source and allowlist configuration without changing phase."""

    moment = now or utcnow()
    legacy_document = _source_document(legacy_intake)
    thread_document = _source_document(thread_intake)
    pilot_document = _pilot_document(pilot)
    if legacy_document["guild_id"] == thread_document["guild_id"]:
        raise ValueError("legacy and thread intake must use different guilds")
    if thread_document["guild_id"] != pilot_document["intake"]["guild_id"]:
        raise ValueError("thread public and pilot intake must use the same target guild")
    if thread_document["channel_id"] == pilot_document["intake"]["channel_id"]:
        raise ValueError("thread public and pilot intake must use separate channels")
    updated = await mongo.ticket_rollout.find_one_and_update(
        {
            "_id": ROLLOUT_ID,
            "schema_version": ROLLOUT_SCHEMA_VERSION,
            "revision": int(expected_revision),
            "phase": {"$in": list(VALID_PHASES)},
        },
        {
            "$set": {
                "legacy_intake": legacy_document,
                "thread_intake": thread_document,
                "pilot": pilot_document,
                "updated_at": moment,
                "updated_by": int(actor_id),
            },
            "$inc": {"revision": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise RolloutConflict("rollout configuration changed before update")
    state = _parse_rollout(updated)
    if not state.valid:
        raise TicketRuntimeError("rollout update produced invalid state")
    return state


def legacy_pending_delivery_query() -> dict[str, Any]:
    """Match unfinished deliveries owned by the legacy channel monitor.

    Current rows carry explicit ownership markers.  The second branch recognizes
    monitor rows written before those markers existed without matching v2
    automation documents.
    """

    return {
        "$and": [
            {
                "$or": [
                    {
                        "kind": "legacy_initial_delivery",
                        "route": ROUTE_LEGACY,
                        "runtime": LEGACY_RUNTIME,
                    },
                    {
                        "kind": {"$exists": False},
                        "channel_id": {"$exists": True},
                        "automation_state": {"$exists": True},
                        "ticket_info": {"$exists": True},
                        "initial_delivery": {"$exists": True},
                    },
                ]
            },
            {
                "initial_delivery.status": {
                    "$nin": ["complete", "failed", "cancelled"]
                }
            },
        ]
    }


def legacy_recoverable_delivery_query(
    *, now: datetime | None = None
) -> dict[str, Any]:
    """Match pending legacy deliveries whose lease can be claimed now."""

    moment = now or utcnow()
    return {
        "$and": [
            legacy_pending_delivery_query(),
            {
                "$or": [
                    {"initial_delivery.status": {"$exists": False}},
                    {
                        "$and": [
                            {"initial_delivery.status": "retry"},
                            {"$or": [
                                {"initial_delivery.retry_after": {"$lte": moment}},
                                {"initial_delivery.retry_after": {"$exists": False}},
                            ]},
                        ]
                    },
                    {
                        "initial_delivery.status": "processing",
                        "initial_delivery.lease_until": {"$lte": moment},
                    },
                ]
            },
        ]
    }


def unresolved_open_conflict_query() -> dict[str, Any]:
    """Match shared slots quarantined for more than one open authority."""

    return {
        "state": SLOT_CLEANUP_REQUIRED,
        "cleanup_reason": "multiple_authoritative_open_tickets",
    }


async def _bounded_document_ids(
    collection: Any, query: Mapping[str, Any], *, limit: int = 10
) -> tuple[str, ...]:
    cursor = collection.find(dict(query))
    rows = await cursor.sort([("_id", ASCENDING)]).limit(limit).to_list(length=limit)
    return tuple(str(row.get("_id")) for row in rows)


async def runtime_blocker_status(mongo: Any) -> RuntimeBlockerStatus:
    """Return the shared blockers that make thread intake unsafe."""

    delivery_query = legacy_pending_delivery_query()
    conflict_query = unresolved_open_conflict_query()
    pending_deliveries, conflicts = await asyncio.gather(
        mongo.ticket_automation_state.count_documents(delivery_query),
        mongo.ticket_open_slots.count_documents(conflict_query),
    )
    delivery_ids, conflict_ids = await asyncio.gather(
        _bounded_document_ids(mongo.ticket_automation_state, delivery_query),
        _bounded_document_ids(mongo.ticket_open_slots, conflict_query),
    )
    return RuntimeBlockerStatus(
        legacy_pending_deliveries=int(pending_deliveries),
        unresolved_conflicts=int(conflicts),
        pending_delivery_ids=delivery_ids,
        conflict_slot_ids=conflict_ids,
    )


async def legacy_drain_status(mongo: Any) -> DrainStatus:
    """Count every durable legacy blocker before entering thread-only mode."""

    open_tickets = await mongo.button_store.count_documents(
        _authority_query(route=ROUTE_LEGACY)
    )
    legacy_slots = await mongo.ticket_open_slots.count_documents(
        {"route": ROUTE_LEGACY, "state": {"$in": list(ACTIVE_SLOT_STATES)}}
    )
    pending_creation = await mongo.ticket_creation_state.count_documents(
        {
            "state": {"$nin": ["complete", "failed", "cancelled"]},
            "$or": [
                {"route": ROUTE_LEGACY},
                {"runtime": ROUTE_LEGACY},
                {
                    "route": {"$exists": False},
                    "runtime": {"$exists": False},
                    "kind": {"$nin": ["thread_ticket_creation"]},
                    "_id": {"$not": {"$regex": "^thread:"}},
                },
            ],
        }
    )
    blockers = await runtime_blocker_status(mongo)
    return DrainStatus(
        legacy_open_tickets=int(open_tickets),
        legacy_slots=int(legacy_slots),
        legacy_pending_workflows=(
            int(pending_creation) + blockers.legacy_pending_deliveries
        ),
        legacy_pending_deliveries=blockers.legacy_pending_deliveries,
        unresolved_conflicts=blockers.unresolved_conflicts,
        pending_delivery_ids=blockers.pending_delivery_ids,
        conflict_slot_ids=blockers.conflict_slot_ids,
    )


async def _transition_rollout(
    mongo: Any,
    *,
    expected_phase: str,
    expected_revision: int,
    to_phase: str,
    actor_id: int,
    now: datetime | None = None,
) -> RolloutState:
    """CAS a legal phase transition, enforcing the legacy drain barrier."""

    if expected_phase not in VALID_PHASES or to_phase not in VALID_PHASES:
        raise InvalidRolloutTransition("unknown rollout phase")
    if to_phase not in _ALLOWED_PHASE_TRANSITIONS[expected_phase]:
        raise InvalidRolloutTransition(
            f"transition {expected_phase!r} -> {to_phase!r} is not permitted"
        )
    if to_phase == PHASE_THREAD_DEFAULT:
        blockers = await runtime_blocker_status(mongo)
        if blockers.blocked:
            raise RuntimeReadinessBlocked(
                "legacy delivery or shared open-ticket conflict remains"
            )
    if to_phase == PHASE_THREAD_ONLY:
        drain = await legacy_drain_status(mongo)
        if not drain.drained:
            raise LegacyDrainBlocked(
                "legacy tickets, slots, workflows, or conflicts remain; "
                "thread-only is unsafe"
            )
    moment = now or utcnow()
    updated = await mongo.ticket_rollout.find_one_and_update(
        {
            "_id": ROLLOUT_ID,
            "schema_version": ROLLOUT_SCHEMA_VERSION,
            "phase": expected_phase,
            "revision": int(expected_revision),
        },
        {
            "$set": {
                "phase": to_phase,
                "updated_at": moment,
                "updated_by": int(actor_id),
            },
            "$inc": {"revision": 1},
            "$push": {
                "phase_history": {
                    "from": expected_phase,
                    "to": to_phase,
                    "at": moment,
                    "actor_id": int(actor_id),
                }
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise RolloutConflict("rollout phase changed before transition")
    state = _parse_rollout(updated)
    if not state.valid:
        raise TicketRuntimeError("rollout transition produced invalid state")
    return state


async def transition_rollout(
    mongo: Any,
    *,
    expected_phase: str,
    expected_revision: int,
    to_phase: str,
    actor_id: int,
    now: datetime | None = None,
) -> RolloutState:
    """Serialize phase CAS with local creation claims in the one-process pilot."""

    async with _DURABILITY_LOCK:
        return await _transition_rollout(
            mongo,
            expected_phase=expected_phase,
            expected_revision=expected_revision,
            to_phase=to_phase,
            actor_id=actor_id,
            now=now,
        )


def pilot_access_allowed(
    state: RolloutState,
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    user_id: int,
    member_role_ids: Iterable[int],
    ticket_type: str,
) -> bool:
    if state.phase != PHASE_PILOT or state.pilot_intake is None:
        return False
    if not state.pilot_intake.matches(
        guild_id=guild_id, channel_id=channel_id, message_id=message_id
    ):
        return False
    normalized_type = str(ticket_type).strip().lower()
    if normalized_type not in state.pilot_ticket_types:
        return False
    roles = {_positive_int(role_id) for role_id in member_role_ids}
    return int(user_id) in state.pilot_user_ids or bool(
        roles.intersection(state.pilot_role_ids)
    )


async def route_public_intake(
    mongo: Any,
    *,
    requested_route: str = ROUTE_LEGACY,
    guild_id: int,
    channel_id: int,
    message_id: int,
    user_id: int,
    member_role_ids: Iterable[int] = (),
    ticket_type: str,
) -> RouteDecision:
    """Resolve a public intake click without silently crossing runtimes.

    Before cross-server setup, legacy intake keeps its production behavior.
    Once ``legacy_ticket_guild_id`` exists, that explicit binding is enforced.
    A copied/stale configured panel never falls through into either runtime.
    """

    state = await get_rollout(mongo)
    requested = str(requested_route).strip().lower()
    if requested not in VALID_ROUTES:
        return RouteDecision(
            ROUTE_REJECT, False, state.phase, state.revision, "invalid_requested_route"
        )

    if not state.valid:
        if requested == ROUTE_LEGACY:
            setup = await mongo.ticket_setup.find_one(
                {"_id": "config"},
                {"legacy_ticket_guild_id": 1},
            ) or {}
            if "legacy_ticket_guild_id" in setup:
                legacy_guild = _positive_int(setup.get("legacy_ticket_guild_id"))
                if legacy_guild is None or legacy_guild != int(guild_id):
                    return RouteDecision(
                        ROUTE_REJECT,
                        False,
                        state.phase,
                        state.revision,
                        "wrong_legacy_guild",
                    )
            return RouteDecision(
                ROUTE_LEGACY,
                True,
                state.phase,
                state.revision,
                (
                    "safe_legacy_default"
                    if "legacy_ticket_guild_id" in setup
                    else "pre_setup_legacy_compatibility"
                ),
            )
        return RouteDecision(
            ROUTE_REJECT, False, state.phase, state.revision, "rollout_not_configured"
        )

    legacy_source_matches = bool(
        state.legacy_intake
        and state.legacy_intake.matches(
            guild_id=guild_id, channel_id=channel_id, message_id=message_id
        )
    )
    thread_source_matches = bool(
        state.thread_intake
        and state.thread_intake.matches(
            guild_id=guild_id, channel_id=channel_id, message_id=message_id
        )
    )
    if state.phase in {PHASE_LEGACY_ONLY, PHASE_PREPARED, PHASE_ROLLBACK_LEGACY}:
        if requested == ROUTE_LEGACY and legacy_source_matches:
            return RouteDecision(
                ROUTE_LEGACY, True, state.phase, state.revision, "legacy_is_default"
            )
        return RouteDecision(
            ROUTE_REJECT,
            False,
            state.phase,
            state.revision,
            (
                "wrong_legacy_intake_source"
                if requested == ROUTE_LEGACY
                else "thread_intake_disabled"
            ),
        )

    if state.phase == PHASE_PILOT:
        if requested == ROUTE_LEGACY and legacy_source_matches:
            return RouteDecision(
                ROUTE_LEGACY, True, state.phase, state.revision, "legacy_is_default"
            )
        if requested == ROUTE_LEGACY:
            return RouteDecision(
                ROUTE_REJECT,
                False,
                state.phase,
                state.revision,
                "wrong_legacy_intake_source",
            )
        allowed = pilot_access_allowed(
            state,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            user_id=user_id,
            member_role_ids=member_role_ids,
            ticket_type=ticket_type,
        )
        return RouteDecision(
            ROUTE_THREAD if allowed else ROUTE_REJECT,
            allowed,
            state.phase,
            state.revision,
            "pilot_allowed" if allowed else "pilot_denied",
        )

    if requested != ROUTE_THREAD:
        return RouteDecision(
            ROUTE_REJECT, False, state.phase, state.revision, "legacy_intake_retired"
        )
    allowed = thread_source_matches
    return RouteDecision(
        ROUTE_THREAD if allowed else ROUTE_REJECT,
        allowed,
        state.phase,
        state.revision,
        "thread_default" if allowed else "wrong_thread_intake_source",
    )


def _slot_id(user_id: int, ticket_type: str) -> str:
    normalized_type = str(ticket_type).strip().lower()
    if normalized_type not in _VALID_TICKET_TYPES:
        raise ValueError(f"unsupported ticket type: {ticket_type!r}")
    normalized_user = _positive_int(user_id)
    if normalized_user is None:
        raise ValueError("user_id must be a positive integer")
    return f"ticket-open:{normalized_user}:{normalized_type}"


async def _insert_open_slot(
    mongo: Any,
    *,
    user_id: int,
    ticket_type: str,
    route: str,
    guild_id: int,
    workflow_id: str,
    rollout_revision: int,
    ticket_number: int | None = None,
    owner_token: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
) -> SlotClaim:
    """Atomically reserve the one global applicant/type creation slot."""

    if route not in VALID_ROUTES:
        raise ValueError(f"unsupported route: {route!r}")
    if not workflow_id or not str(workflow_id).strip():
        raise ValueError("workflow_id is required")
    moment = now or utcnow()
    token = owner_token or secrets.token_urlsafe(24)
    document: dict[str, Any] = {
        "_id": _slot_id(user_id, ticket_type),
        "schema_version": 1,
        "user_id": int(user_id),
        "ticket_type": str(ticket_type).strip().lower(),
        "route": route,
        "guild_id": int(guild_id),
        "workflow_id": str(workflow_id),
        "rollout_revision": int(rollout_revision),
        "state": SLOT_RESERVED,
        "owner_token": token,
        "lease_until": moment + timedelta(seconds=max(1, int(lease_seconds))),
        "created_at": moment,
        "updated_at": moment,
    }
    if ticket_number is not None:
        document["ticket_number"] = int(ticket_number)
    try:
        await mongo.ticket_open_slots.insert_one(document)
    except DuplicateKeyError:
        existing = await mongo.ticket_open_slots.find_one({"_id": document["_id"]})
        if existing is None:
            existing = await mongo.ticket_open_slots.find_one(
                {"workflow_id": document["workflow_id"]}
            )
        if existing is None:
            raise SlotConflict("slot collision could not be read") from None
        return SlotClaim(False, None, existing)
    return SlotClaim(True, token, document)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _creation_state_id(workflow_id: str, route: str) -> str:
    if route == ROUTE_LEGACY and workflow_id.startswith("legacy:"):
        return workflow_id.removeprefix("legacy:")
    return workflow_id


async def _resume_open_slot(
    mongo: Any,
    *,
    slot_id: str,
    workflow_id: str,
    route: str,
    guild_id: int | None = None,
    owner_token: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
) -> SlotClaim:
    """Acquire an expired reservation without changing its sticky route/workflow."""

    if route not in VALID_ROUTES:
        raise ValueError(f"unsupported route: {route!r}")
    moment = now or utcnow()
    token = owner_token or secrets.token_urlsafe(24)
    existing = await mongo.ticket_open_slots.find_one({"_id": str(slot_id)})
    if existing is None:
        raise SlotConflict("open slot no longer exists")
    if (
        existing.get("state") != SLOT_RESERVED
        or existing.get("route") != route
        or str(existing.get("workflow_id") or "") != str(workflow_id)
        or (
            guild_id is not None
            and _positive_int(existing.get("guild_id")) != _positive_int(guild_id)
        )
    ):
        return SlotClaim(False, None, existing)
    same_owner = bool(owner_token and existing.get("owner_token") == owner_token)
    if not same_owner:
        creation = await mongo.ticket_creation_state.find_one(
            {"_id": _creation_state_id(str(workflow_id), route)}
        ) or {}
        creation_lease = _aware_datetime(creation.get("lease_until"))
        if (
            creation
            and creation.get("state") not in {"complete", "failed", "cancelled"}
            and creation_lease is not None
            and creation_lease > moment
        ):
            return SlotClaim(False, None, existing)
    lease_match: list[dict[str, Any]] = [
        {"lease_until": {"$lte": moment}},
        {"lease_until": {"$exists": False}},
    ]
    if owner_token:
        lease_match.append({"owner_token": owner_token})
    resume_filter: dict[str, Any] = {
            "_id": str(slot_id),
            "workflow_id": str(workflow_id),
            "route": route,
            "state": SLOT_RESERVED,
            "$or": lease_match,
    }
    if guild_id is not None:
        resume_filter["guild_id"] = int(guild_id)
    resumed = await mongo.ticket_open_slots.find_one_and_update(
        resume_filter,
        {
            "$set": {
                "owner_token": token,
                "lease_until": moment
                + timedelta(seconds=max(1, int(lease_seconds))),
                "updated_at": moment,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if resumed is not None:
        return SlotClaim(True, token, resumed)
    latest = await mongo.ticket_open_slots.find_one({"_id": str(slot_id)})
    if latest is None:
        raise SlotConflict("open slot no longer exists")
    return SlotClaim(False, None, latest)


async def resume_open_slot(
    mongo: Any,
    *,
    slot_id: str,
    workflow_id: str,
    route: str,
    guild_id: int | None = None,
    owner_token: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
) -> SlotClaim:
    """Serialize takeover checks with creation claims in the one-process pilot."""

    async with _DURABILITY_LOCK:
        return await _resume_open_slot(
            mongo,
            slot_id=slot_id,
            workflow_id=workflow_id,
            route=route,
            guild_id=guild_id,
            owner_token=owner_token,
            now=now,
            lease_seconds=lease_seconds,
        )


async def cancel_open_slot(
    mongo: Any,
    *,
    slot_id: str,
    owner_token: str,
    workflow_id: str,
) -> bool:
    """Cancel an untouched reservation after its caller proves rollback is safe."""

    result = await mongo.ticket_open_slots.delete_one(
        {
            "_id": str(slot_id),
            "state": SLOT_RESERVED,
            "owner_token": str(owner_token),
            "workflow_id": str(workflow_id),
            "ticket_id": {"$exists": False},
        }
    )
    return bool(result.deleted_count)


async def bind_open_slot(
    mongo: Any,
    *,
    slot_id: str,
    owner_token: str,
    ticket_id: Any,
    location_id: int,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Bind a reserved slot to its authoritative ticket record."""

    moment = now or utcnow()
    document = await mongo.ticket_open_slots.find_one_and_update(
        {
            "_id": slot_id,
            "state": SLOT_RESERVED,
            "owner_token": owner_token,
        },
        {
            "$set": {
                "state": SLOT_OPEN,
                "ticket_id": ticket_id,
                "location_id": int(location_id),
                "updated_at": moment,
            },
            "$unset": {"owner_token": "", "lease_until": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise SlotConflict("slot is stale or owned by another workflow")
    return document


async def mark_slot_release_pending(
    mongo: Any,
    *,
    ticket_id: Any,
    terminal_status: str,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Durably mark a terminal ticket's slot before attempting deletion."""

    terminal = str(terminal_status).strip().lower()
    if terminal not in {"approved", "denied"}:
        raise ValueError("terminal_status must be approved or denied")
    slot = await mongo.ticket_open_slots.find_one(
        {"ticket_id": ticket_id, "state": SLOT_OPEN}
    )
    if slot is None:
        raise SlotConflict("no open slot is bound to that ticket")
    ticket = await _ticket_for_slot(mongo, slot)
    if str((ticket or {}).get("status") or "").strip().lower() != terminal:
        raise SlotConflict("authoritative ticket is not at the requested terminal status")
    moment = now or utcnow()
    document = await mongo.ticket_open_slots.find_one_and_update(
        {
            "_id": slot.get("_id"),
            "ticket_id": ticket_id,
            "workflow_id": slot.get("workflow_id"),
            "state": SLOT_OPEN,
        },
        {
            "$set": {
                "state": SLOT_RELEASE_PENDING,
                "terminal_status": terminal,
                "terminal_committed_at": moment,
                "updated_at": moment,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise SlotConflict("no open slot is bound to that ticket")
    return document


async def release_open_slot(
    mongo: Any,
    *,
    ticket_id: Any,
    now: datetime | None = None,
) -> bool:
    """Release only after re-reading the exact bound authoritative terminal."""

    slot = await mongo.ticket_open_slots.find_one(
        {"ticket_id": ticket_id, "state": SLOT_RELEASE_PENDING}
    )
    if slot is None:
        return False
    ticket = await _ticket_for_slot(mongo, slot)
    if str((ticket or {}).get("status") or "") not in {"approved", "denied"}:
        return False
    result = await mongo.ticket_open_slots.delete_one(
        {
            "_id": slot.get("_id"),
            "ticket_id": ticket_id,
            "workflow_id": slot.get("workflow_id"),
            "state": SLOT_RELEASE_PENDING,
        }
    )
    return bool(result.deleted_count)


def _nested_value(document: Mapping[str, Any], path: str) -> Any:
    value: Any = document
    for key in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


async def _maximum_field(
    collection: Any,
    query: Mapping[str, Any],
    field: str,
) -> int:
    cursor = collection.find(dict(query), {field: 1})
    # Historical channel records contain both BSON strings and integers. BSON
    # sort order is type-based, so a bounded sorted sample can miss the numeric
    # maximum (for example "9" versus 1000). Scan the narrow projection instead.
    rows = await cursor.to_list(length=None)
    values = [_positive_int(_nested_value(row, field)) or 0 for row in rows]
    return max(values, default=0)


async def _observed_ticket_number_floor(mongo: Any, ticket_type: str) -> int:
    values = await asyncio.gather(
        _maximum_field(
            mongo.button_store,
            {
                "type": "ticket",
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            "ticket_number",
        ),
        _maximum_field(
            mongo.tickets,
            {
                "type": "ticket",
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            "ticket_number",
        ),
        _maximum_field(
            mongo.ticket_creation_state,
            {
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            "ticket_number",
        ),
        _maximum_field(
            mongo.ticket_open_slots,
            {
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            "ticket_number",
        ),
        _maximum_field(
            mongo.ticket_migrations,
            {
                "metadata.ticket_type": ticket_type,
                "destination.ticket_number": {"$exists": True},
            },
            "destination.ticket_number",
        ),
    )
    return max(values, default=0)


async def reserve_ticket_number(mongo: Any, ticket_type: str) -> int:
    """Allocate above both stores and every durable in-flight reservation.

    The counter lives outside the user-editable ticket configuration, so an old
    counter reset cannot move it backwards.  The compatibility counter is only
    raised, never used as authority.
    """

    normalized_type = str(ticket_type).strip().lower()
    if normalized_type not in _VALID_TICKET_TYPES:
        raise ValueError(f"unsupported ticket type: {ticket_type!r}")
    field = f"{normalized_type}_ticket_counter"
    for _attempt in range(8):
        floor = await _observed_ticket_number_floor(mongo, normalized_type)
        await mongo.ticket_rollout.update_one(
            {"_id": COUNTER_DOCUMENT_ID},
            {
                "$setOnInsert": {
                    "schema_version": 1,
                    "kind": "ticket_number_counters",
                },
                "$max": {field: floor},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )
        counter = await mongo.ticket_rollout.find_one_and_update(
            {"_id": COUNTER_DOCUMENT_ID},
            {"$inc": {field: 1}, "$set": {"updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if counter is None:
            raise TicketRuntimeError("shared ticket counter disappeared")
        allocated = int(counter[field])
        await mongo.ticket_setup.update_one(
            {"_id": "config"}, {"$max": {field: allocated}}, upsert=True
        )
        newest = await _observed_ticket_number_floor(mongo, normalized_type)
        if allocated > newest:
            return allocated
    raise TicketRuntimeError(
        "ticket numbers changed continuously while a number was being allocated"
    )


def _ticket_location(ticket: Mapping[str, Any]) -> int | None:
    location = ticket.get("location")
    if isinstance(location, Mapping):
        for field in ("id", "staff_space_id"):
            value = _positive_int(location.get(field))
            if value is not None:
                return value
    for field in (
        "public_thread_id",
        "channel_id",
        "staff_thread_id",
        "thread_id",
    ):
        value = _positive_int(ticket.get(field))
        if value is not None:
            return value
    return None


def _authority_query(
    *,
    route: str,
    user_id: int | None = None,
    ticket_type: str | None = None,
    status: str | None = "open",
) -> dict[str, Any]:
    query: dict[str, Any] = {"type": "ticket"}
    if status is not None:
        query["status"] = str(status)
    if route == ROUTE_THREAD:
        query.update({"venue": "thread", "runtime": THREAD_RUNTIME})
    elif route == ROUTE_LEGACY:
        query["$or"] = [
            {"venue": "channel", "runtime": LEGACY_RUNTIME},
            {"venue": {"$exists": False}, "runtime": {"$exists": False}},
            {"venue": "channel", "runtime": {"$exists": False}},
            {"venue": {"$exists": False}, "runtime": LEGACY_RUNTIME},
        ]
    else:
        raise ValueError(f"unsupported authority route: {route!r}")
    if user_id is not None:
        normalized = int(user_id)
        query["user_id"] = {"$in": [normalized, str(normalized)]}
    if ticket_type is not None:
        query["ticket_type"] = str(ticket_type).strip().lower()
    return query


async def _open_authoritative_tickets(
    mongo: Any,
    *,
    user_id: int | None = None,
    ticket_type: str | None = None,
    limit: int,
) -> list[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = []
    for route, collection in (
        (ROUTE_LEGACY, mongo.button_store),
        (ROUTE_THREAD, mongo.tickets),
    ):
        cursor = collection.find(
            _authority_query(
                route=route, user_id=user_id, ticket_type=ticket_type
            )
        )
        rows = await cursor.sort([("_id", ASCENDING)]).limit(limit).to_list(
            length=limit
        )
        found.extend((route, row) for row in rows)
    return found


def _ticket_ref(route: str, ticket: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route": route,
        "ticket_id": ticket.get("_id"),
        "location_id": _ticket_location(ticket),
    }


async def _stamp_authority_binding(
    mongo: Any,
    *,
    route: str,
    ticket_id: Any,
    slot_id: str,
    workflow_id: str,
    now: datetime,
) -> bool:
    collection = mongo.tickets if route == ROUTE_THREAD else mongo.button_store
    query = _authority_query(route=route)
    query["_id"] = ticket_id
    ownership = (
        {"venue": "thread", "runtime": THREAD_RUNTIME}
        if route == ROUTE_THREAD
        else {"venue": "channel", "runtime": LEGACY_RUNTIME}
    )
    result = await collection.update_one(
        query,
        {
            "$set": {
                **ownership,
                "open_slot_id": slot_id,
                "creation_workflow_id": workflow_id,
                "runtime_bound_at": now,
            }
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def _backfill_ticket_slot(
    mongo: Any,
    *,
    route: str,
    ticket: Mapping[str, Any],
    rollout_revision: int,
    now: datetime,
) -> tuple[str, str]:
    user_id = _positive_int(ticket.get("user_id"))
    ticket_type = str(ticket.get("ticket_type") or "").strip().lower()
    ticket_id = ticket.get("_id")
    if user_id is None or ticket_type not in _VALID_TICKET_TYPES or ticket_id is None:
        return "skipped", str(ticket_id)
    slot_id = _slot_id(user_id, ticket_type)
    workflow_id = str(
        ticket.get("creation_workflow_id") or f"backfill:{route}:{ticket_id}"
    )
    document: dict[str, Any] = {
        "_id": slot_id,
        "schema_version": 1,
        "user_id": user_id,
        "ticket_type": ticket_type,
        "route": route,
        "guild_id": _positive_int(ticket.get("guild_id")),
        "workflow_id": workflow_id,
        "rollout_revision": int(rollout_revision),
        "state": SLOT_OPEN,
        "ticket_id": ticket_id,
        "created_at": ticket.get("created_at") or now,
        "updated_at": now,
        "backfilled_at": now,
    }
    location_id = _ticket_location(ticket)
    if location_id is not None:
        document["location_id"] = location_id
    ticket_number = _positive_int(ticket.get("ticket_number"))
    if ticket_number is not None:
        document["ticket_number"] = ticket_number
    inserted = False
    try:
        await mongo.ticket_open_slots.insert_one(document)
        inserted = True
    except DuplicateKeyError:
        existing = await mongo.ticket_open_slots.find_one({"_id": slot_id})
        if existing is None:
            existing = await mongo.ticket_open_slots.find_one(
                {"workflow_id": workflow_id}
            )
        if existing is None:
            raise SlotConflict("backfill collision could not be read") from None

    if inserted:
        bound = await _stamp_authority_binding(
            mongo,
            route=route,
            ticket_id=ticket_id,
            slot_id=slot_id,
            workflow_id=workflow_id,
            now=now,
        )
        if bound:
            return "created", slot_id
        await mongo.ticket_open_slots.update_one(
            {"_id": slot_id, "ticket_id": ticket_id},
            {
                "$set": {
                    "state": SLOT_CLEANUP_REQUIRED,
                    "cleanup_reason": "authority_binding_failed",
                    "updated_at": now,
                }
            },
        )
        return "conflicted", slot_id

    same_ticket = (
        existing.get("route") == route
        and str(existing.get("ticket_id")) == str(ticket_id)
    )
    same_workflow = (
        existing.get("route") == route
        and str(existing.get("workflow_id")) == workflow_id
        and existing.get("ticket_id") is None
    )
    if same_ticket or same_workflow:
        refreshed = {key: value for key, value in document.items() if key != "_id"}
        refreshed["created_at"] = existing.get("created_at") or document["created_at"]
        await mongo.ticket_open_slots.update_one(
            {"_id": existing.get("_id")},
            {
                "$set": refreshed,
                "$unset": {
                    "owner_token": "",
                    "lease_until": "",
                    "cleanup_reason": "",
                },
            },
        )
        bound = await _stamp_authority_binding(
            mongo,
            route=route,
            ticket_id=ticket_id,
            slot_id=str(existing.get("_id")),
            workflow_id=workflow_id,
            now=now,
        )
        if not bound:
            await mongo.ticket_open_slots.update_one(
                {"_id": existing.get("_id")},
                {
                    "$set": {
                        "state": SLOT_CLEANUP_REQUIRED,
                        "cleanup_reason": "authority_binding_failed",
                        "updated_at": now,
                    }
                },
            )
            return "conflicted", str(existing.get("_id"))
        return "existing", str(existing.get("_id"))

    conflict_refs = [_ticket_ref(route, ticket)]
    if existing.get("ticket_id") is not None:
        conflict_refs.append(
            {
                "route": existing.get("route"),
                "ticket_id": existing.get("ticket_id"),
                "location_id": existing.get("location_id"),
            }
        )
    await mongo.ticket_open_slots.update_one(
        {"_id": existing.get("_id")},
        {
            "$set": {
                "state": SLOT_CLEANUP_REQUIRED,
                "cleanup_reason": "multiple_authoritative_open_tickets",
                "updated_at": now,
            },
            "$addToSet": {"conflicting_tickets": {"$each": conflict_refs}},
            "$unset": {"owner_token": "", "lease_until": ""},
        },
    )
    return "conflicted", str(existing.get("_id"))


async def backfill_open_slots(
    mongo: Any,
    *,
    limit: int = 5000,
    now: datetime | None = None,
) -> BackfillResult:
    """Create slots for every pre-rollout open ticket or fail before partial work."""

    bounded = max(1, int(limit))
    legacy_count, thread_count = await asyncio.gather(
        mongo.button_store.count_documents(
            _authority_query(route=ROUTE_LEGACY)
        ),
        mongo.tickets.count_documents(_authority_query(route=ROUTE_THREAD)),
    )
    if int(legacy_count) + int(thread_count) > bounded:
        raise BackfillLimitExceeded(
            f"{int(legacy_count) + int(thread_count)} open tickets exceed limit {bounded}"
        )
    tickets = await _open_authoritative_tickets(mongo, limit=bounded)
    invalid_ids = [
        str(ticket.get("_id"))
        for _route, ticket in tickets
        if (
            _positive_int(ticket.get("user_id")) is None
            or str(ticket.get("ticket_type") or "").strip().lower()
            not in _VALID_TICKET_TYPES
            or ticket.get("_id") is None
        )
    ]
    if invalid_ids:
        raise TicketRuntimeError(
            "open ticket identity is invalid: " + ", ".join(invalid_ids[:10])
        )
    state = await get_rollout(mongo)
    moment = now or utcnow()
    buckets: dict[str, list[str]] = {
        "created": [],
        "existing": [],
        "conflicted": [],
        "skipped": [],
    }
    async with _DURABILITY_LOCK:
        for route, ticket in tickets:
            outcome, identifier = await _backfill_ticket_slot(
                mongo,
                route=route,
                ticket=ticket,
                rollout_revision=state.revision,
                now=moment,
            )
            buckets[outcome].append(identifier)
    return BackfillResult(
        created_slot_ids=tuple(buckets["created"]),
        existing_slot_ids=tuple(buckets["existing"]),
        conflicted_slot_ids=tuple(buckets["conflicted"]),
        skipped_ticket_ids=tuple(buckets["skipped"]),
    )


def _route_allowed_for_claim(
    state: RolloutState,
    route: str,
    guild_id: int,
) -> bool:
    if not state.valid:
        return route == ROUTE_LEGACY
    legacy_guild_id = state.legacy_intake.guild_id if state.legacy_intake else None
    thread_guild_id = state.thread_intake.guild_id if state.thread_intake else None
    if state.phase in {
        PHASE_LEGACY_ONLY,
        PHASE_PREPARED,
        PHASE_ROLLBACK_LEGACY,
    }:
        return route == ROUTE_LEGACY and int(guild_id) == legacy_guild_id
    if state.phase == PHASE_PILOT:
        return (
            route == ROUTE_LEGACY and int(guild_id) == legacy_guild_id
        ) or (
            route == ROUTE_THREAD and int(guild_id) == thread_guild_id
        )
    return route == ROUTE_THREAD and int(guild_id) == thread_guild_id


async def claim_open_slot(
    mongo: Any,
    *,
    user_id: int,
    ticket_type: str,
    route: str,
    guild_id: int,
    workflow_id: str,
    rollout_revision: int,
    ticket_number: int | None = None,
    owner_token: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
) -> SlotClaim:
    """Claim only after cross-checking both authoritative stores."""

    moment = now or utcnow()
    normalized_type = str(ticket_type).strip().lower()
    async with _DURABILITY_LOCK:
        state = await get_rollout(mongo)
        if state.revision != int(rollout_revision):
            raise RolloutConflict("rollout changed before the ticket slot was claimed")
        if not state.valid and route == ROUTE_LEGACY:
            setup = await mongo.ticket_setup.find_one(
                {"_id": "config"},
                {"legacy_ticket_guild_id": 1},
            ) or {}
            if "legacy_ticket_guild_id" in setup:
                legacy_guild_id = _positive_int(setup.get("legacy_ticket_guild_id"))
                if legacy_guild_id is None or legacy_guild_id != int(guild_id):
                    raise RolloutConflict(
                        "the requested runtime is disabled in this ticket guild"
                    )
        if not _route_allowed_for_claim(state, route, guild_id):
            raise RolloutConflict("the requested runtime is disabled in this rollout phase")
        authoritative = await _open_authoritative_tickets(
            mongo,
            user_id=int(user_id),
            ticket_type=normalized_type,
            limit=4,
        )
        if authoritative:
            for authority_route, ticket in authoritative:
                await _backfill_ticket_slot(
                    mongo,
                    route=authority_route,
                    ticket=ticket,
                    rollout_revision=state.revision,
                    now=moment,
                )
            existing = await mongo.ticket_open_slots.find_one(
                {"_id": _slot_id(user_id, normalized_type)}
            )
            if existing is None:
                raise SlotConflict("an open ticket has invalid identity; creation is blocked")
            return SlotClaim(False, None, existing)

        # A terminal commit is authoritative even if its best-effort release
        # checkpoint failed. Repair that exact collision online so the next
        # application is not blocked until process restart.
        existing = await mongo.ticket_open_slots.find_one(
            {"_id": _slot_id(user_id, normalized_type)}
        )
        if existing is not None and not await _release_terminal_slot_collision(
            mongo, existing
        ):
            return SlotClaim(False, None, existing)

        claim = await _insert_open_slot(
            mongo,
            user_id=user_id,
            ticket_type=normalized_type,
            route=route,
            guild_id=guild_id,
            workflow_id=workflow_id,
            rollout_revision=rollout_revision,
            ticket_number=ticket_number,
            owner_token=owner_token,
            now=moment,
            lease_seconds=lease_seconds,
        )
        if not claim.won:
            # Close the small terminal-commit race between the collision read
            # above and the atomic insert. Retry once after exact proof.
            if not await _release_terminal_slot_collision(mongo, claim.slot):
                return claim
            claim = await _insert_open_slot(
                mongo,
                user_id=user_id,
                ticket_type=normalized_type,
                route=route,
                guild_id=guild_id,
                workflow_id=workflow_id,
                rollout_revision=rollout_revision,
                ticket_number=ticket_number,
                owner_token=owner_token,
                now=moment,
                lease_seconds=lease_seconds,
            )
            if not claim.won:
                return claim
        # Close the check/insert window for any writer not yet migrated to slots.
        raced = await _open_authoritative_tickets(
            mongo,
            user_id=int(user_id),
            ticket_type=normalized_type,
            limit=4,
        )
        if not raced:
            return claim
        for authority_route, ticket in raced:
            await _backfill_ticket_slot(
                mongo,
                route=authority_route,
                ticket=ticket,
                rollout_revision=state.revision,
                now=moment,
            )
        existing = await mongo.ticket_open_slots.find_one(
            {"_id": _slot_id(user_id, normalized_type)}
        )
        return SlotClaim(False, None, existing or claim.slot)


async def _ticket_for_slot(mongo: Any, slot: Mapping[str, Any]) -> Mapping[str, Any] | None:
    route = slot.get("route")
    if route not in VALID_ROUTES:
        return None
    collection = mongo.tickets if route == ROUTE_THREAD else mongo.button_store
    authority = _authority_query(route=str(route), status=None)
    binding = {
        "open_slot_id": slot.get("_id"),
        "creation_workflow_id": slot.get("workflow_id"),
    }
    if slot.get("ticket_id") is not None:
        ticket = await collection.find_one(
            {**authority, **binding, "_id": slot["ticket_id"]}
        )
        if ticket is not None:
            return ticket
    return await collection.find_one({**authority, **binding})


async def _release_terminal_slot_collision(
    mongo: Any, slot: Mapping[str, Any]
) -> bool:
    """Release a colliding slot only after exact terminal authority is proven."""

    if slot.get("state") not in {SLOT_OPEN, SLOT_RELEASE_PENDING}:
        return False
    ticket = await _ticket_for_slot(mongo, slot)
    if str((ticket or {}).get("status") or "").strip().lower() not in {
        "approved",
        "denied",
    }:
        return False
    result = await mongo.ticket_open_slots.delete_one(
        {
            "_id": slot.get("_id"),
            "state": slot.get("state"),
            "ticket_id": slot.get("ticket_id"),
            "workflow_id": slot.get("workflow_id"),
        }
    )
    return bool(result.deleted_count)


def _conflict_ticket_refs(slot: Mapping[str, Any]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    values = slot.get("conflicting_tickets")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return refs
    for value in values:
        if not isinstance(value, Mapping):
            continue
        route = value.get("route")
        ticket_id = value.get("ticket_id")
        if route in VALID_ROUTES and ticket_id is not None:
            refs.add((str(route), str(ticket_id)))
    return refs


async def _all_conflict_refs_terminal(
    mongo: Any, refs: set[tuple[str, str]]
) -> bool:
    """Prove every recorded side of a real duplicate is now terminal."""

    if len(refs) < 2:
        return False
    for route, ticket_id in refs:
        collection = mongo.tickets if route == ROUTE_THREAD else mongo.button_store
        query = _authority_query(route=route, status=None)
        query["_id"] = ticket_id
        ticket = await collection.find_one(query)
        if str((ticket or {}).get("status") or "").strip().lower() not in {
            "approved",
            "denied",
        }:
            return False
    return True


async def _reconcile_duplicate_open_conflict(
    mongo: Any, slot: Mapping[str, Any], *, now: datetime
) -> str:
    """Resolve a quarantined duplicate only after its winner is unambiguous."""

    slot_id = str(slot.get("_id"))
    refs = _conflict_ticket_refs(slot)
    user_id = _positive_int(slot.get("user_id"))
    ticket_type = str(slot.get("ticket_type") or "").strip().lower()
    if len(refs) < 2 or user_id is None or ticket_type not in _VALID_TICKET_TYPES:
        return "unchanged"

    open_tickets = await _open_authoritative_tickets(
        mongo, user_id=user_id, ticket_type=ticket_type, limit=4
    )
    if len(open_tickets) > 1:
        await mongo.ticket_open_slots.update_one(
            {
                "_id": slot.get("_id"),
                "state": SLOT_CLEANUP_REQUIRED,
                "cleanup_reason": "multiple_authoritative_open_tickets",
            },
            {
                "$set": {"updated_at": now},
                "$addToSet": {
                    "conflicting_tickets": {
                        "$each": [
                            _ticket_ref(route, ticket)
                            for route, ticket in open_tickets
                        ]
                    }
                },
            },
        )
        return "unchanged"

    if not open_tickets:
        if not await _all_conflict_refs_terminal(mongo, refs):
            return "unchanged"
        result = await mongo.ticket_open_slots.delete_one(
            {
                "_id": slot.get("_id"),
                "state": SLOT_CLEANUP_REQUIRED,
                "cleanup_reason": "multiple_authoritative_open_tickets",
            }
        )
        return "released" if result.deleted_count else "unchanged"

    route, ticket = open_tickets[0]
    ticket_id = ticket.get("_id")
    if (route, str(ticket_id)) not in refs:
        return "unchanged"
    workflow_id = str(
        ticket.get("creation_workflow_id") or f"backfill:{route}:{ticket_id}"
    )
    if not await _stamp_authority_binding(
        mongo,
        route=route,
        ticket_id=ticket_id,
        slot_id=slot_id,
        workflow_id=workflow_id,
        now=now,
    ):
        return "unchanged"
    update: dict[str, Any] = {
        "state": SLOT_OPEN,
        "route": route,
        "ticket_id": ticket_id,
        "workflow_id": workflow_id,
        "guild_id": _positive_int(ticket.get("guild_id")),
        "updated_at": now,
    }
    location_id = _ticket_location(ticket)
    if location_id is not None:
        update["location_id"] = location_id
    ticket_number = _positive_int(ticket.get("ticket_number"))
    if ticket_number is not None:
        update["ticket_number"] = ticket_number
    result = await mongo.ticket_open_slots.update_one(
        {
            "_id": slot.get("_id"),
            "state": SLOT_CLEANUP_REQUIRED,
            "cleanup_reason": "multiple_authoritative_open_tickets",
        },
        {
            "$set": update,
            "$unset": {
                "owner_token": "",
                "lease_until": "",
                "cleanup_reason": "",
                "conflicting_tickets": "",
            },
        },
    )
    return "bound" if result.modified_count else "unchanged"


async def reconcile_open_slots(
    mongo: Any,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> ReconcileResult:
    """Repair committed slot state without guessing that Discord work vanished.

    Missing authority is quarantined as ``cleanup_required`` and never released.
    A slot is deleted only after an authoritative terminal ticket is observed.
    """

    moment = now or utcnow()
    cursor = mongo.ticket_open_slots.find(
        {"state": {"$in": list(ACTIVE_SLOT_STATES)}}
    )
    slots = await cursor.sort([("updated_at", ASCENDING)]).limit(
        max(1, int(limit))
    ).to_list(length=max(1, int(limit)))
    released: list[str] = []
    bound: list[str] = []
    cleanup: list[str] = []
    unchanged: list[str] = []

    for slot in slots:
        slot_id = str(slot.get("_id"))
        if (
            slot.get("state") == SLOT_CLEANUP_REQUIRED
            and slot.get("cleanup_reason") == "multiple_authoritative_open_tickets"
        ):
            outcome = await _reconcile_duplicate_open_conflict(
                mongo, slot, now=moment
            )
            if outcome == "released":
                released.append(slot_id)
            elif outcome == "bound":
                bound.append(slot_id)
            else:
                unchanged.append(slot_id)
            continue
        ticket = await _ticket_for_slot(mongo, slot)
        status = str((ticket or {}).get("status") or "").strip().lower()
        if ticket is not None and status in {"approved", "denied"}:
            result = await mongo.ticket_open_slots.delete_one(
                {
                    "_id": slot.get("_id"),
                    "state": slot.get("state"),
                    "workflow_id": slot.get("workflow_id"),
                    "ticket_id": slot.get("ticket_id"),
                    "route": slot.get("route"),
                }
            )
            (released if result.deleted_count else unchanged).append(slot_id)
            continue

        if ticket is not None and status == "open":
            if slot.get("state") in {SLOT_RESERVED, SLOT_CLEANUP_REQUIRED}:
                update: dict[str, Any] = {
                    "state": SLOT_OPEN,
                    "ticket_id": ticket.get("_id"),
                    "updated_at": moment,
                }
                location_id = _ticket_location(ticket)
                if location_id is not None:
                    update["location_id"] = location_id
                result = await mongo.ticket_open_slots.update_one(
                    {"_id": slot.get("_id"), "state": slot.get("state")},
                    {
                        "$set": update,
                        "$unset": {
                            "owner_token": "",
                            "lease_until": "",
                            "cleanup_reason": "",
                        },
                    },
                )
                (bound if result.modified_count else unchanged).append(slot_id)
            else:
                unchanged.append(slot_id)
            continue

        authority_missing = slot.get("state") in {
            SLOT_OPEN,
            SLOT_RELEASE_PENDING,
        }
        if authority_missing:
            result = await mongo.ticket_open_slots.update_one(
                {"_id": slot.get("_id"), "state": slot.get("state")},
                {
                    "$set": {
                        "state": SLOT_CLEANUP_REQUIRED,
                        "cleanup_reason": "authoritative_ticket_missing",
                        "updated_at": moment,
                    },
                    "$unset": {"owner_token": "", "lease_until": ""},
                },
            )
            (cleanup if result.modified_count else unchanged).append(slot_id)
        else:
            # A reserved workflow may already have Discord side effects that are
            # not yet committed to Mongo. Expiry makes it resumable; it is not
            # proof that cleanup or release is safe.
            unchanged.append(slot_id)

    return ReconcileResult(
        released_slot_ids=tuple(released),
        bound_slot_ids=tuple(bound),
        cleanup_required_slot_ids=tuple(cleanup),
        unchanged_slot_ids=tuple(unchanged),
    )


async def recover_ticket_runtime(
    mongo: Any,
    *,
    limit: int = 5000,
    now: datetime | None = None,
) -> tuple[BackfillResult, ReconcileResult]:
    """Startup gate: indexes, complete open-ticket backfill, then reconcile."""

    await ensure_indexes(mongo)
    backfill = await backfill_open_slots(mongo, limit=limit, now=now)
    reconciled = await reconcile_open_slots(mongo, limit=limit, now=now)
    return backfill, reconciled


def thread_ticket_fields(slot: Mapping[str, Any]) -> dict[str, Any]:
    """Fields every authoritative thread ticket must persist at insertion."""

    if slot.get("route") != ROUTE_THREAD:
        raise ValueError("slot is not owned by the thread runtime")
    return {
        "venue": "thread",
        "runtime": THREAD_RUNTIME,
        "open_slot_id": slot["_id"],
        "creation_workflow_id": slot["workflow_id"],
        "rollout_revision": int(slot.get("rollout_revision", 0)),
    }


def thread_collection(mongo: Any) -> Any:
    """Return the sole authoritative collection for thread-runtime tickets."""

    return mongo.tickets


async def insert_thread_ticket(mongo: Any, document: Mapping[str, Any]) -> Any:
    """Insert a v2 ticket into ``tickets`` only; mirroring is forbidden."""

    payload = dict(document)
    if payload.get("type") != "ticket":
        raise ValueError("thread ticket type must be 'ticket'")
    if payload.get("venue") != "thread" or payload.get("runtime") != THREAD_RUNTIME:
        raise ValueError("thread ticket authority fields are missing")
    if not payload.get("open_slot_id") or not payload.get("creation_workflow_id"):
        raise ValueError("thread ticket must be bound to a creation slot")
    return await mongo.tickets.insert_one(payload)


__all__ = [
    "ACTIVE_SLOT_STATES",
    "BackfillLimitExceeded",
    "BackfillResult",
    "COUNTER_DOCUMENT_ID",
    "DrainStatus",
    "IntakeSource",
    "InvalidRolloutTransition",
    "LEGACY_RUNTIME",
    "LegacyDrainBlocked",
    "PHASE_LEGACY_ONLY",
    "PHASE_PILOT",
    "PHASE_PREPARED",
    "PHASE_ROLLBACK_LEGACY",
    "PHASE_THREAD_DEFAULT",
    "PHASE_THREAD_ONLY",
    "ROLLOUT_ID",
    "ROLLOUT_SCHEMA_VERSION",
    "ROUTE_LEGACY",
    "ROUTE_REJECT",
    "ROUTE_THREAD",
    "ReconcileResult",
    "RolloutConflict",
    "RolloutState",
    "RouteDecision",
    "RuntimeBlockerStatus",
    "RuntimeReadinessBlocked",
    "SLOT_CLEANUP_REQUIRED",
    "SLOT_OPEN",
    "SLOT_RELEASE_PENDING",
    "SLOT_RESERVED",
    "SlotClaim",
    "SlotConflict",
    "THREAD_RUNTIME",
    "TicketRuntimeError",
    "bind_open_slot",
    "backfill_open_slots",
    "cancel_open_slot",
    "claim_open_slot",
    "configure_rollout",
    "ensure_indexes",
    "get_rollout",
    "insert_thread_ticket",
    "legacy_drain_status",
    "legacy_pending_delivery_query",
    "legacy_recoverable_delivery_query",
    "mark_slot_release_pending",
    "pilot_access_allowed",
    "reconcile_open_slots",
    "recover_ticket_runtime",
    "release_open_slot",
    "reserve_ticket_number",
    "resume_open_slot",
    "route_public_intake",
    "runtime_blocker_status",
    "seed_rollout",
    "thread_collection",
    "thread_ticket_fields",
    "transition_rollout",
    "unresolved_open_conflict_query",
    "utcnow",
]
