"""Repository for the production channel-ticket runtime.

Legacy channel tickets remain authoritative in ``button_store`` while the
thread runtime is piloted beside them.  Every query is constrained to channel
tickets, and no write is mirrored into the thread runtime's ``tickets``
collection.  Rows created before runtime markers existed remain legacy rows.
"""

import asyncio
import dataclasses
import uuid
from collections import Counter
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient

LEGACY_RUNTIME = "legacy_channel"
LEGACY_FILTER = {
    "type": "ticket",
    "$or": [
        # New channel-runtime rows carry both ownership markers.
        {"venue": "channel", "runtime": LEGACY_RUNTIME},
        # Pre-coexistence production rows had neither marker.
        {"venue": {"$exists": False}, "runtime": {"$exists": False}},
        # Accept either marker independently for interrupted rollout writes.
        {"venue": "channel", "runtime": {"$exists": False}},
        {"venue": {"$exists": False}, "runtime": LEGACY_RUNTIME},
    ],
}
TICKET_FILTER = LEGACY_FILTER

STORE_BUTTON = "button_store"


def utcnow() -> datetime:
    """One source of truth for resolution timestamps."""
    return datetime.now(timezone.utc)


def as_int(value) -> int:
    """Channel/user ids have been stored as both int and str across schema versions.

    Canonical home; manage.py imports this as its `_as_int`.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def active_store(mongo: MongoClient) -> str:
    """Return the fixed authoritative collection for channel-era tickets."""
    return STORE_BUTTON


def _legacy_filter(filt: dict) -> dict:
    """Constrain a caller filter without letting it weaken runtime isolation."""
    return {"$and": [dict(filt), dict(LEGACY_FILTER)]}


def is_legacy_ticket_document(document: dict | None) -> bool:
    if not document or document.get("type") != "ticket":
        return False
    venue = document.get("venue")
    runtime = document.get("runtime")
    return venue in {None, "channel"} and runtime in {None, LEGACY_RUNTIME}


# --- reads -------------------------------------------------------------------

async def find_one(mongo: MongoClient, filt: dict):
    return await mongo.button_store.find_one(_legacy_filter(filt))


async def find(mongo: MongoClient, filt: dict) -> list[dict]:
    """All matching ticket documents. Callers all wanted a list anyway."""
    return await mongo.button_store.find(_legacy_filter(filt)).to_list(length=None)


# --- writes ------------------------------------------------------------------

_EXACT_TEXT_FIELDS = (
    "_id",
    "type",
    "ticket_type",
    "username",
    "venue",
    "runtime",
    "open_slot_id",
    "creation_workflow_id",
)
_EXACT_INT_FIELDS = (
    "ticket_number",
    "guild_id",
    "channel_id",
    "thread_id",
    "category_id",
    "user_id",
    "rollout_revision",
    "creation_generation",
)


def _normalize_exact_ticket(doc: dict) -> dict:
    normalized = dict(doc)
    if normalized.get("type") != "ticket":
        raise ValueError("legacy ticket type must be 'ticket'")
    normalized.setdefault("venue", "channel")
    normalized.setdefault("runtime", LEGACY_RUNTIME)
    if normalized.get("venue") != "channel" or normalized.get("runtime") != LEGACY_RUNTIME:
        raise ValueError("legacy ticket authority markers are invalid")
    if normalized.get("status") != "open":
        raise ValueError("new legacy ticket status must be open")
    return normalized


def _assert_exact_ticket_identity(
    existing: dict,
    expected: dict,
    *,
    allow_terminal: bool = False,
) -> None:
    if not is_legacy_ticket_document(existing):
        raise ValueError("ticket id belongs to a non-legacy runtime")
    for field in _EXACT_TEXT_FIELDS:
        if str(existing.get(field) or "") != str(expected.get(field) or ""):
            raise ValueError(f"legacy ticket identity mismatch: {field}")
    for field in _EXACT_INT_FIELDS:
        if as_int(existing.get(field)) != as_int(expected.get(field)):
            raise ValueError(f"legacy ticket identity mismatch: {field}")
    existing_created = existing.get("created_at")
    expected_created = expected.get("created_at")
    if not isinstance(existing_created, datetime) or not isinstance(
        expected_created, datetime
    ):
        raise ValueError("legacy ticket identity mismatch: created_at")
    existing_utc = (
        existing_created.replace(tzinfo=timezone.utc)
        if existing_created.tzinfo is None
        else existing_created.astimezone(timezone.utc)
    )
    expected_utc = (
        expected_created.replace(tzinfo=timezone.utc)
        if expected_created.tzinfo is None
        else expected_created.astimezone(timezone.utc)
    )
    if int(existing_utc.timestamp() * 1000) != int(
        expected_utc.timestamp() * 1000
    ):
        raise ValueError("legacy ticket identity mismatch: created_at")
    status = str(existing.get("status") or "").strip().lower()
    if status != "open" and not (allow_terminal and status in TERMINAL_STATUSES):
        raise ValueError("legacy ticket identity mismatch: status")


async def ensure_exact_ticket(
    mongo: MongoClient,
    doc: dict,
    *,
    allow_terminal: bool = False,
) -> dict:
    """Insert once or accept only the exact matching late commit."""

    normalized = _normalize_exact_ticket(doc)
    existing = await mongo.button_store.find_one({"_id": normalized["_id"]})
    if existing is None:
        try:
            await mongo.button_store.insert_one(normalized)
            return normalized
        except DuplicateKeyError:
            existing = await mongo.button_store.find_one({"_id": normalized["_id"]})
            if existing is None:
                raise
    _assert_exact_ticket_identity(
        existing,
        normalized,
        allow_terminal=allow_terminal,
    )
    return existing

async def insert_one(mongo: MongoClient, doc: dict) -> None:
    """Idempotently persist one exact channel ticket without replacement."""

    await ensure_exact_ticket(mongo, doc)


async def update_one(mongo: MongoClient, filt: dict, update: dict):
    return await mongo.button_store.update_one(_legacy_filter(filt), update)


async def update_many(mongo: MongoClient, filt: dict, update: dict):
    return await mongo.button_store.update_many(_legacy_filter(filt), update)


# --- conditional writes ------------------------------------------------------
#
# Everything below exists because an unconditional $set loses updates. Two
# recruiters resolving one ticket in the same second both used to succeed, both
# ran their side effects, and the last write silently won. The pattern here is
# the one already proven in manage.py's cleanup filter: re-assert the status you
# believe you are transitioning FROM, inside the filter, so Mongo arbitrates
# rather than the network.
#
# The rule that makes it worth anything: SIDE EFFECTS RUN ONLY ON "won".

WON = "won"
LOST = "lost"
MISSING = "missing"
BUSY = "busy"
TERMINAL_STATUSES = frozenset({"approved", "denied"})
OPENING_DELIVERY_BUSY_MESSAGE = (
    "⏳ Ticket opening messages are still finishing. No decision was recorded; "
    "retry shortly."
)
RESOLUTION_DELIVERY_BUSY_MESSAGE = (
    "⏳ The previous decision is still being delivered. No new decision was "
    "recorded; retry shortly."
)


@dataclasses.dataclass(frozen=True, slots=True)
class Transition:
    """Result of a conditional ticket write.

    outcome == WON     -> this caller caused the change. `doc` is the post-image.
                          Side effects are permitted, and only here.
    outcome == LOST    -> the precondition did not hold. `doc` is the CURRENT
                          document, so the caller can say who got there first and
                          when. Nothing was written.
    outcome == BUSY    -> an opening-message POST owns the authority row. The
                          decision was not recorded and no side effect may run.
    outcome == MISSING -> no such ticket. `doc` is None. Nothing was written.
    """

    outcome: str
    doc: dict | None

    @property
    def won(self) -> bool:
        return self.outcome == WON

    @property
    def busy(self) -> bool:
        return self.outcome == BUSY


def transition_busy_message(result: Transition) -> str:
    """Explain which same-row delivery fence prevented the decision."""

    delivery = (result.doc or {}).get("resolution_delivery") or {}
    if delivery and delivery.get("state") != "complete":
        return RESOLUTION_DELIVERY_BUSY_MESSAGE
    return OPENING_DELIVERY_BUSY_MESSAGE


def _identity_id(value: int) -> dict:
    """Match the canonical Discord id across historical int/string storage."""
    canonical = int(value)
    return {"$in": [canonical, str(canonical)]}


async def acquire_opening_post_intent(
    mongo: MongoClient,
    ticket_id,
    *,
    channel_id: int,
    thread_id: int,
    guild_id: int,
    user_id: int,
    ticket_type: str,
    token: str,
    step: str,
    target_id: int,
) -> dict | None:
    """Linearize one opening-message POST against every terminal writer.

    The intent deliberately has no lease or expiry. An ambiguous Discord result
    may only be settled after an exact history scan proves whether the POST
    landed; elapsed time can never authorize a decision or a duplicate POST.
    """
    token = str(token or "").strip()
    step = str(step or "").strip()
    if not token or not step:
        raise ValueError("opening post intent requires token and step")
    target_id = int(target_id)
    if target_id <= 0:
        raise ValueError("opening post intent requires a target channel")

    return await mongo.button_store.find_one_and_update(
        _legacy_filter({
            "_id": ticket_id,
            "status": "open",
            "guild_id": _identity_id(guild_id),
            "channel_id": _identity_id(channel_id),
            "thread_id": _identity_id(thread_id),
            "user_id": _identity_id(user_id),
            "ticket_type": str(ticket_type),
            "opening_post_intent": {"$exists": False},
        }),
        {"$set": {"opening_post_intent": {
            "token": token,
            "step": step,
            "target_id": target_id,
            "created_at": utcnow(),
        }}},
        return_document=ReturnDocument.AFTER,
    )


async def clear_opening_post_intent(
    mongo: MongoClient,
    ticket_id,
    *,
    token: str,
    step: str,
) -> bool:
    """Clear only the exact intent a successfully reconciled POST owns."""
    result = await mongo.button_store.update_one(
        _legacy_filter({
            "_id": ticket_id,
            "opening_post_intent.token": str(token),
            "opening_post_intent.step": str(step),
        }),
        {"$unset": {"opening_post_intent": ""}},
    )
    return bool(result.modified_count)


async def _conditional(
        mongo: MongoClient,
        filt: dict,
        update: dict,
        ticket_id,
) -> Transition:
    """Run a legacy-only compare-and-swap against ``button_store``."""
    doc = await mongo.button_store.find_one_and_update(
        _legacy_filter(filt), update, return_document=ReturnDocument.AFTER
    )
    if doc is not None:
        return Transition(WON, doc)

    # Nothing matched. Distinguish "someone beat me to it" from "no such ticket",
    # because they need completely different things said to the user.
    current = await mongo.button_store.find_one(
        _legacy_filter({"_id": ticket_id})
    )
    return Transition(LOST, current) if current is not None else Transition(MISSING, None)


async def transition(
        mongo: MongoClient,
        ticket_id,
        *,
        to_status: str,
        actor_id: int,
        actor_name: str,
        expect: str | None = "open",
        extra: dict | None = None,
        overrides: dict | None = None,
        resolution_effect: dict | None = None,
) -> Transition:
    """Move a ticket to `to_status`, only if it is currently `expect`.

    expect=None removes only the status precondition. That is the override path -
    a recruiter deliberately overturning a resolution someone else already made,
    which is normal in recruiting (a mistaken deny, an appeal, a leader's call)
    and should not require hand-editing Mongo. Opening-message intent fencing
    still applies to overrides.

    `overrides` is the prior resolution the actor was SHOWN before confirming.
    It is recorded verbatim in the audit entry. Note the small TOCTOU: a third
    write landing between the actor reading the warning and confirming it would
    not be reflected. That is accepted deliberately - the audit records what the
    human was told and acted on, which is the more useful record of a decision.
    """
    now = datetime.now(timezone.utc)

    audit = {
        "at": now,
        "actor": actor_id,
        "actor_name": actor_name,
        "to": to_status,
        "from": expect if expect is not None else (overrides or {}).get("status"),
        "override": overrides is not None,
    }
    if overrides:
        audit["overrode"] = {
            "status": overrides.get("status"),
            "by": overrides.get("by"),
            "by_name": overrides.get("by_name"),
            "at": overrides.get("at"),
        }

    filt = {"_id": ticket_id}
    if expect is not None:
        filt["status"] = expect

    terminal = to_status in TERMINAL_STATUSES
    delivery = None
    if terminal:
        filt["opening_post_intent"] = {"$exists": False}
        filt["$or"] = [
            {"resolution_delivery": {"$exists": False}},
            {"resolution_delivery.state": {"$in": ["complete", "cancelled"]}},
        ]
        plan = dict(resolution_effect or {})
        if not plan.get("kind"):
            if to_status == "approved":
                plan["kind"] = "approve"
            else:
                denial_type = str((extra or {}).get("denial_type") or "custom")
                plan["kind"] = {
                    "fwa_default": "deny_fwa",
                    "main_default": "deny_main",
                    "custom": "deny_custom",
                }.get(denial_type, "deny_custom")
                plan.setdefault("reason", (extra or {}).get("denial_reason"))
        delivery = {
            "effect_id": uuid.uuid4().hex,
            "decision_status": to_status,
            "state": "pending",
            "requested_at": now,
            "updated_at": now,
            "actor_id": int(actor_id),
            "actor_name": str(actor_name),
            "plan": plan,
        }

    result = None
    for attempt in range(3):
        result = await _conditional(
            mongo,
            filt,
            {
                "$set": {
                    "status": to_status,
                    **(extra or {}),
                    **(
                        {"resolution_delivery": delivery}
                        if delivery is not None
                        else {}
                    ),
                },
                "$push": {"audit": audit},
            },
            ticket_id,
        )
        if result.won or not terminal:
            break
        current = result.doc
        expected_status = expect is None or (
            current is not None and current.get("status") == expect
        )
        resolution_busy = (
            current is not None
            and bool(current.get("resolution_delivery"))
            and (current.get("resolution_delivery") or {}).get("state")
            not in {"complete", "cancelled"}
        )
        if not (
            current is not None
            and expected_status
            and ("opening_post_intent" in current or resolution_busy)
        ):
            break
        if attempt < 2:
            await asyncio.sleep((0.05, 0.15)[attempt])
    assert result is not None
    if (
        terminal
        and not result.won
        and result.doc is not None
        and (expect is None or result.doc.get("status") == expect)
        and (
            "opening_post_intent" in result.doc
            or (
                bool(result.doc.get("resolution_delivery"))
                and (result.doc.get("resolution_delivery") or {}).get("state")
                not in {"complete", "cancelled"}
            )
        )
    ):
        return Transition(BUSY, result.doc)
    return result


async def claim(mongo: MongoClient, ticket_id, actor_id: int, actor_name: str) -> Transition:
    """Advisory claim. Discord cannot enforce ownership inside a thread, so this
    records and signals intent - it does not prevent anyone acting.

    `{"claimed_by": None}` matches documents where the field is null OR absent,
    which is every ticket written before this existed. No backfill needed.
    """
    now = datetime.now(timezone.utc)
    return await _conditional(
        mongo,
        {"_id": ticket_id, "status": "open", "claimed_by": None},
        {
            "$set": {"claimed_by": actor_id, "claimed_by_name": actor_name, "claimed_at": now},
            "$push": {"audit": {
                "at": now, "actor": actor_id, "actor_name": actor_name, "to": "claimed",
            }},
        },
        ticket_id,
    )


async def release(
        mongo: MongoClient,
        ticket_id,
        actor_id: int,
        actor_name: str,
        *,
        force: bool = False,
) -> Transition:
    """Give up a claim. `force` lets an admin release someone else's."""
    now = datetime.now(timezone.utc)
    filt = {"_id": ticket_id, "claimed_by": {"$ne": None}}
    if not force:
        filt["claimed_by"] = actor_id

    return await _conditional(
        mongo,
        filt,
        {
            "$set": {"claimed_by": None, "claimed_by_name": None, "claimed_at": None},
            "$push": {"audit": {
                "at": now, "actor": actor_id, "actor_name": actor_name,
                "to": "released", "forced": force,
            }},
        },
        ticket_id,
    )


# --- reconciliation helpers --------------------------------------------------

async def status_counts(collection, filt: dict | None = None) -> dict[str, int]:
    """{status: count} for ticket documents in one collection.

    Takes a collection rather than the client because both /ticket diagnostics
    and the backfill need to compare the two sides directly.
    """
    query = (
        {"$and": [dict(TICKET_FILTER), dict(filt)]}
        if filt
        else TICKET_FILTER
    )
    docs = await collection.find(query, {"status": 1}).to_list(length=None)
    return dict(Counter(d.get("status") or "(missing)" for d in docs))
