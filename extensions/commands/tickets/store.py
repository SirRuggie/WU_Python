"""Durable ticket repository, indexes, and compare-and-swap transitions."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import schema
from utils.mongo import MongoClient


_log = logging.getLogger(__name__)

TICKET_FILTER = {"type": "ticket"}
RUNTIME_FILTER = {"type": "ticket", "venue": "thread"}
ACCOUNT_RECOVERY_BOOLEAN_FIELDS = (
    "linked_accounts.retry_required",
    "linked_accounts.context_refresh_required",
    "linked_accounts.flag_refresh_required",
)
STORE_BUTTON = "button_store"
STORE_TICKETS = "tickets"
CANONICAL_ACTIVATION_VERSION = 3
# Missing or invalid rollout state must never make an unverified collection
# authoritative. `/ticket migrate-store` explicitly activates `tickets` only
# after the copy and canonical indexes are verified.
DEFAULT_STORE = STORE_BUTTON

WON = "won"
LOST = "lost"
MISSING = "missing"
BLOCKED = "blocked"
UNAUTHORIZED = "unauthorized"
EFFECT_FAILED = "effect_failed"


class TicketStoreError(RuntimeError):
    pass


class TicketConflictError(TicketStoreError):
    """An idempotency key already belongs to a different ticket."""


class OpenTicketExistsError(TicketConflictError):
    def __init__(self, existing: dict | None = None):
        super().__init__("an open ticket already exists for this applicant and type")
        self.existing = existing


class IndexConflictError(TicketStoreError):
    def __init__(self, conflicts: Mapping[str, list]):
        super().__init__("ticket index conflicts must be repaired before index creation")
        self.conflicts = dict(conflicts)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


new_ticket_document = schema.new_ticket_document
normalize_ticket_document = schema.normalize_ticket_document


def is_markerless_legacy_terminal(ticket: Mapping) -> bool:
    """Whether a terminal import has no live resolution worker to wait for."""
    effects = ticket.get("resolution_effects")
    return bool(
        ticket.get("venue") == "thread"
        and ticket.get("status") in schema.TERMINAL_STATUSES
        and ticket.get("source")
        and not effects
        and any(
            isinstance(item, Mapping)
            and item.get("event") in {
                "legacy_ticket_imported",
                "legacy_location_replaced",
            }
            for item in (ticket.get("audit") or ())
        )
    )


async def active_store(mongo: MongoClient) -> str:
    config = await mongo.ticket_setup.find_one(
        {"_id": "config"},
        {"ticket_store": 1, "ticket_store_activation_version": 1},
    ) or {}
    if (
        config.get("ticket_store") == STORE_TICKETS
        and config.get("ticket_store_activation_version")
        == CANONICAL_ACTIVATION_VERSION
    ):
        return STORE_TICKETS
    return DEFAULT_STORE


async def _reader(mongo: MongoClient):
    return mongo.tickets if await active_store(mongo) == STORE_TICKETS else mongo.button_store


async def _both(mongo: MongoClient):
    if await active_store(mongo) == STORE_TICKETS:
        return mongo.tickets, mongo.button_store
    return mongo.button_store, mongo.tickets


async def find_one(mongo: MongoClient, filt: dict):
    return await (await _reader(mongo)).find_one(filt)


async def find(mongo: MongoClient, filt: dict) -> list[dict]:
    return await (await _reader(mongo)).find(filt).to_list(length=None)


def _mixed_id(value) -> list:
    normalized = as_int(value)
    return [normalized, str(normalized)] if normalized else []


async def find_by_location(mongo: MongoClient, location_id) -> dict | None:
    ids = _mixed_id(location_id)
    if not ids:
        return None
    return await find_one(mongo, {
        **RUNTIME_FILTER,
        "$or": [
            {"location.id": {"$in": ids}},
            {"location.staff_space_id": {"$in": ids}},
            {"channel_id": {"$in": ids}},
            {"thread_id": {"$in": ids}},
        ],
    })


async def find_open_for_applicant(
    mongo: MongoClient,
    user_id,
    ticket_type: str,
) -> dict | None:
    ids = _mixed_id(user_id)
    if not ids:
        return None
    return await find_one(mongo, {
        **RUNTIME_FILTER,
        "user_id": {"$in": ids},
        "ticket_type": schema.ticket_type(ticket_type),
        "status": "open",
    })


async def list_open(mongo: MongoClient, *, limit: int = 25) -> list[dict]:
    amount = max(1, min(int(limit), 25))
    cursor = (await _reader(mongo)).find({**RUNTIME_FILTER, "status": "open"})
    return await cursor.sort([("created_at", -1), ("_id", -1)]).limit(amount).to_list(
        length=amount
    )


class SearchQueryError(ValueError):
    pass


def _search_identity(query: str) -> dict:
    value = str(query or "").strip()
    if not value:
        return {}
    if value.isdecimal():
        if not 17 <= len(value) <= 20:
            raise SearchQueryError("Discord IDs must contain 17 to 20 numbers")
        return {"user_id": {"$in": [int(value), value]}}
    if value.startswith("#"):
        try:
            tag = schema.player_tag(value)
        except schema.TicketSchemaError as exc:
            raise SearchQueryError(str(exc)) from exc
        if not 3 <= len(tag.removeprefix("#")) <= 9:
            raise SearchQueryError("player tags must contain 3 to 9 letters or numbers")
        return {"$or": [{"player_tags": tag}, {"player_tag": tag}, {"tag": tag}]}
    if not 2 <= len(value) <= 32 or re.fullmatch(r"[\w .-]+", value) is None:
        raise SearchQueryError(
            "Use a Discord ID, player tag, or a 2-32 character username"
        )
    normalized = schema.username_search(value)
    return {"$or": [
        {"username_search": normalized},
        {"username": re.compile(rf"^{re.escape(value)}$", re.IGNORECASE)},
    ]}


async def search(
    mongo: MongoClient,
    query: str = "",
    *,
    statuses: Iterable[str] | None = None,
    ticket_types: Iterable[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    filt: dict = {**RUNTIME_FILTER, **_search_identity(query)}
    if statuses:
        filt["status"] = {"$in": [schema.ticket_status(value) for value in statuses]}
    if ticket_types:
        filt["ticket_type"] = {
            "$in": [schema.ticket_type(value) for value in ticket_types]
        }
    amount = max(1, min(int(limit), 10))
    cursor = (await _reader(mongo)).find(filt)
    return await cursor.sort([("created_at", -1), ("_id", -1)]).limit(amount).to_list(
        length=amount
    )


async def history_for(
    mongo: MongoClient,
    *,
    user_id=None,
    player_tags: Iterable[str] = (),
    exclude_id=None,
    limit: int = 10,
) -> list[dict]:
    identities: list[dict] = []
    ids = _mixed_id(user_id)
    if ids:
        identities.append({"user_id": {"$in": ids}})
    tags = schema.player_tags(player_tags)
    if tags:
        identities.extend([
            {"player_tags": {"$in": tags}},
            {"player_tag": {"$in": tags}},
            {"tag": {"$in": tags}},
        ])
    if not identities:
        return []
    filt: dict = {**RUNTIME_FILTER, "$or": identities}
    if exclude_id is not None:
        filt["_id"] = {"$ne": exclude_id}
    amount = max(1, min(int(limit), 10))
    cursor = (await _reader(mongo)).find(filt)
    return await cursor.sort([("created_at", -1), ("_id", -1)]).limit(amount).to_list(
        length=amount
    )


async def console_counts(mongo: MongoClient) -> dict:
    """Return chart totals as ``total/status/by_type`` dictionaries."""
    pipeline = [
        {"$match": {
            **RUNTIME_FILTER,
            "status": {"$in": sorted(schema.TICKET_STATUSES)},
        }},
        {"$group": {
            "_id": {"status": "$status", "ticket_type": "$ticket_type"},
            "count": {"$sum": 1},
        }},
    ]
    cursor = await (await _reader(mongo)).aggregate(pipeline)
    rows = await cursor.to_list(length=None)
    status = {value: 0 for value in sorted(schema.TICKET_STATUSES)}
    by_type = {
        kind: {value: 0 for value in sorted(schema.TICKET_STATUSES)}
        for kind in sorted(schema.TICKET_TYPES)
    }
    for row in rows:
        state = (row.get("_id") or {}).get("status")
        kind = (row.get("_id") or {}).get("ticket_type")
        count = int(row.get("count") or 0)
        if state in status:
            status[state] += count
        if kind in by_type and state in by_type[kind]:
            by_type[kind][state] += count
    return {"total": sum(status.values()), "status": status, "by_type": by_type}


def _identity_fingerprint(doc: Mapping) -> tuple:
    location = doc.get("location") or {}
    source = doc.get("source") or {}
    return (
        str(doc.get("_id")),
        doc.get("ticket_type"),
        as_int(doc.get("ticket_number")),
        as_int(doc.get("user_id")),
        as_int(location.get("id")),
        as_int(location.get("staff_space_id")),
        as_int(source.get("guild_id")),
        as_int(source.get("channel_id")),
    )


async def _mirror_to(collection, doc: dict) -> None:
    try:
        await collection.replace_one({"_id": doc["_id"]}, dict(doc), upsert=True)
    except Exception:
        _log.exception(
            "ticket mirror failed for %s - primary remains authoritative", doc.get("_id")
        )


async def insert_one(mongo: MongoClient, doc: dict) -> dict:
    """Create once; exact retries return the committed record without replacing it."""
    normalized = normalize_ticket_document(doc)
    if normalized.get("venue") != "thread":
        raise schema.TicketSchemaError("runtime ticket inserts must be thread tickets")
    primary, secondary = await _both(mongo)
    try:
        await primary.update_one(
            {"_id": normalized["_id"]},
            {"$setOnInsert": normalized},
            upsert=True,
        )
    except DuplicateKeyError as exc:
        existing = await primary.find_one({
            "type": "ticket",
            "user_id": normalized.get("user_id"),
            "ticket_type": normalized.get("ticket_type"),
            "status": "open",
        })
        if existing is not None:
            raise OpenTicketExistsError(existing) from exc
        raise TicketConflictError("a unique ticket identity is already in use") from exc

    committed = await primary.find_one({"_id": normalized["_id"]})
    if committed is None:
        raise TicketStoreError("primary ticket write was not readable after commit")
    if _identity_fingerprint(committed) != _identity_fingerprint(normalized):
        raise TicketConflictError(
            f"ticket id {normalized['_id']} already belongs to another ticket"
        )
    await _mirror_to(secondary, committed)
    return committed


async def update_one(mongo: MongoClient, filt: dict, update: dict):
    primary, secondary = await _both(mongo)
    result = await primary.update_one(filt, update)
    try:
        await secondary.update_one(filt, update)
    except Exception:
        _log.exception("ticket update mirror failed for filter %r", filt)
    return result


async def update_many(mongo: MongoClient, filt: dict, update: dict):
    primary, secondary = await _both(mongo)
    result = await primary.update_many(filt, update)
    try:
        await secondary.update_many(filt, update)
    except Exception:
        _log.exception("ticket update-many mirror failed for filter %r", filt)
    return result


@dataclasses.dataclass(frozen=True, slots=True)
class Transition:
    outcome: str
    doc: dict | None
    reason: str | None = None
    blocker: dict | None = None

    @property
    def won(self) -> bool:
        return self.outcome == WON


def _rev_filter(rev: int) -> int | dict:
    # Historical rows have no rev. They are logically revision zero.
    return {"$in": [0, None]} if rev == 0 else rev


async def _conditional(
    mongo: MongoClient,
    filt: dict,
    update: dict,
    ticket_id,
) -> Transition:
    primary, secondary = await _both(mongo)
    doc = await primary.find_one_and_update(
        filt, update, return_document=ReturnDocument.AFTER
    )
    if doc is not None:
        await _mirror_to(secondary, doc)
        return Transition(WON, doc)
    current = await primary.find_one({"_id": ticket_id, **RUNTIME_FILTER})
    return Transition(LOST, current) if current is not None else Transition(MISSING, None)


async def compare_and_swap_linked_accounts(
    mongo: MongoClient,
    ticket_id,
    *,
    expected_revision: int,
    update: dict,
) -> Transition:
    """Atomically persist one linked-account observation without changing decision rev.

    Ticket ``rev`` protects recruiter decisions and the component state rendered from
    them.  Account refreshes use their own revision so a background refresh cannot
    invalidate an otherwise current Approve/Deny panel.  The CAS still prevents two
    workers from replacing each other's complete account snapshots.
    """
    revision = max(0, int(expected_revision))
    revision_filter = (
        {"$or": [
            {"linked_accounts.revision": 0},
            {"linked_accounts.revision": {"$exists": False}},
        ]}
        if revision == 0
        else {"linked_accounts.revision": revision}
    )
    return await _conditional(
        mongo,
        {
            "_id": ticket_id,
            **RUNTIME_FILTER,
            **revision_filter,
        },
        update,
        ticket_id,
    )


async def transition(
    mongo: MongoClient,
    ticket_id,
    *,
    to_status: str,
    actor_id: int,
    actor_name: str,
    expect: str | None = "open",
    expected_rev: int | None = None,
    extra: dict | None = None,
    overrides: dict | None = None,
    effect_kind: str | None = None,
    prior_effect_marker: str | None = None,
    prior_effects_legacy_baseline: bool = False,
    linked_account_snapshot: Mapping | None = None,
    linked_account_retry: Mapping | None = None,
    expected_linked_account_revision: int | None = None,
) -> Transition:
    """CAS a ticket status using the status and revision the actor observed."""
    target = schema.ticket_status(to_status)
    if target == "open":
        raise schema.TicketSchemaError("resolved tickets cannot be reopened")
    actor = schema.snowflake(actor_id, field="actor_id")
    name = str(actor_name or "").strip() or str(actor)

    primary, _ = await _both(mongo)
    current = await primary.find_one({"_id": ticket_id, **RUNTIME_FILTER})
    if current is None:
        return Transition(MISSING, None)

    if expect is None:
        expect = (overrides or {}).get("status")
    expected_status = schema.ticket_status(expect)
    if current.get("status") != expected_status:
        return Transition(LOST, current)

    current_rev = max(0, int(current.get("rev") or 0))
    if expected_rev is None:
        expected_rev = (overrides or {}).get("rev", current_rev)
    expected_rev = max(0, int(expected_rev))
    if current_rev != expected_rev:
        return Transition(LOST, current)
    if (
        overrides is not None
        and not prior_effect_marker
        and not (
            prior_effects_legacy_baseline
            and is_markerless_legacy_terminal(current)
        )
    ):
        return Transition(LOST, current)

    now = utcnow()
    marker = f"ticket-resolution:{ticket_id}:{expected_rev + 1}:{target}"
    audit = {
        "event": "status_transition",
        "at": now,
        "actor": actor,
        "actor_name": name,
        "from": expected_status,
        "to": target,
        "override": overrides is not None,
        "rev_before": expected_rev,
        "rev_after": expected_rev + 1,
        "effect_marker": marker,
    }
    if overrides is not None:
        audit["overrode"] = {
            "status": expected_status,
            "by": overrides.get("by"),
            "by_name": overrides.get("by_name"),
            "at": overrides.get("at"),
            "rev": expected_rev,
        }
    if linked_account_snapshot is not None:
        audit["linked_accounts"] = {
            "state": str(linked_account_snapshot.get("state") or "failed"),
            "revision": max(0, int(linked_account_snapshot.get("revision") or 0)),
            "current_tags": schema.player_tags(
                linked_account_snapshot.get("current_tags") or ()
            ),
            "retry_required": bool(linked_account_snapshot.get("retry_required")),
        }

    protected = {
        "_id", "type", "schema_version", "venue", "location", "guild_id",
        "channel_id", "thread_id", "category_id", "user_id", "ticket_type",
        "ticket_number", "status", "rev", "audit", "created_at",
    }
    supplied = {key: value for key, value in dict(extra or {}).items() if key not in protected}
    set_fields = {
        "status": target,
        "updated_at": now,
        "handled_at": now,
        "handled_by": actor,
        "handled_by_name": name,
        "resolution_effects": {
            "version": 1,
            "marker": marker,
            "kind": str(effect_kind or ("approve" if target == "approved" else "deny_custom")),
            "notification": {"state": "pending"},
            "staff_context": {"state": "pending"},
            "archive": {"state": "pending"},
            "hub": {"state": "pending"},
            "complete": False,
            "updated_at": now,
        },
        **supplied,
    }
    if linked_account_retry is not None:
        retry_source = str(linked_account_retry.get("source") or "final_denial")[:80]
        retry_error = str(linked_account_retry.get("error") or "AccountSyncError")[:120]
        set_fields.update({
            "linked_accounts.version": 1,
            "linked_accounts.state": "failed",
            "linked_accounts.retry_required": True,
            "linked_accounts.source": retry_source,
            "linked_accounts.last_attempt_at": now,
            "linked_accounts.error": retry_error,
        })
    unset_fields = {field: "" for field in schema.CLAIM_FIELDS}
    if target == "approved":
        set_fields.setdefault("approved_at", now)
        set_fields.setdefault("approved_by", actor)
        set_fields.setdefault("approved_by_name", name)
        unset_fields.update({
            "denied_at": "", "denied_by": "", "denied_by_name": "",
            "denial_type": "", "denial_reason": "",
        })
    else:
        set_fields.setdefault("denied_at", now)
        set_fields.setdefault("denied_by", actor)
        set_fields.setdefault("denied_by_name", name)
        unset_fields.update({
            "approved_at": "", "approved_by": "", "approved_by_name": "",
        })

    transition_filter = {
        "_id": ticket_id,
        "type": "ticket",
        "venue": "thread",
        "status": expected_status,
        "rev": _rev_filter(expected_rev),
    }
    if expected_linked_account_revision is not None:
        # A terminal decision is based on the just-refreshed account view.  Do
        # not let a concurrent refresh replace that view between the flag gate
        # and this write; callers must re-read and make a fresh decision.
        account_revision = max(0, int(expected_linked_account_revision))
        if account_revision == 0:
            transition_filter["$or"] = [
                {"linked_accounts.revision": 0},
                {"linked_accounts.revision": {"$exists": False}},
            ]
        else:
            transition_filter["linked_accounts.revision"] = account_revision
    if overrides is not None:
        # A terminal decision's Discord effects are part of the decision being
        # overturned. Keep this in the same atomic predicate as status/rev so a
        # superseded worker cannot still be preparing its applicant notice when
        # the replacement decision commits.
        if prior_effect_marker:
            transition_filter.update({
                "resolution_effects.marker": str(prior_effect_marker),
                "resolution_effects.complete": True,
            })
        else:
            # Terminal legacy imports predate live resolution workers. They are
            # safe to override only while their provenance remains intact and
            # no resolution marker/checkpoint appeared after the operator read
            # the row.
            transition_filter.update({
                "source.guild_id": {"$exists": True},
                "source.channel_id": {"$exists": True},
                "audit.event": {"$in": [
                    "legacy_ticket_imported",
                    "legacy_location_replaced",
                ]},
                "resolution_effects.marker": {"$exists": False},
                "resolution_effects.complete": {"$exists": False},
            })

    push_fields: dict = {"audit": audit}
    increments = {"rev": 1}
    if linked_account_retry is not None:
        increments["linked_accounts.revision"] = 1
        push_fields["account_identity_audit"] = {
            "event": "linked_accounts_sync_failed",
            "at": now,
            "source": set_fields["linked_accounts.source"],
            "error": set_fields["linked_accounts.error"],
            "retry_queued_with_decision": True,
        }

    return await _conditional(
        mongo,
        transition_filter,
        {
            "$set": set_fields,
            "$unset": unset_fields,
            "$inc": increments,
            "$push": push_fields,
        },
        ticket_id,
    )


async def replace_legacy_location(
    mongo: MongoClient,
    existing_ticket_id,
    canonical_doc: Mapping,
    *,
    expected_rev: int | None = None,
) -> Transition:
    """CAS-convert one legacy ticket row to its cloned thread location in place.

    The logical ticket ``_id`` is intentionally stable.  Creating a second row
    for the new public thread would make one historical ticket appear twice in
    search and would make resume semantics ambiguous.
    """
    replacement = normalize_ticket_document(canonical_doc)
    if replacement.get("venue") != "thread":
        raise schema.TicketSchemaError("replacement location must be a thread pair")
    if replacement.get("status") not in schema.TERMINAL_STATUSES:
        raise schema.TicketSchemaError("only terminal legacy tickets may be cloned")
    if not replacement.get("source"):
        raise schema.TicketSchemaError("a cloned legacy ticket requires source identity")

    primary, secondary = await _both(mongo)
    current = await primary.find_one({"_id": existing_ticket_id, "type": "ticket"})
    if current is None:
        return Transition(MISSING, None)
    current_location = current.get("location") or {}
    target_location = replacement["location"]
    if (
        current.get("venue") == "thread"
        and as_int(current_location.get("id")) == as_int(target_location.get("id"))
        and as_int(current_location.get("staff_space_id"))
        == as_int(target_location.get("staff_space_id"))
    ):
        return Transition(WON, current, "already migrated")
    if current.get("status") != replacement.get("status"):
        return Transition(LOST, current, "source status changed")

    rev = max(0, int(current.get("rev") or 0))
    if expected_rev is not None and rev != int(expected_rev):
        return Transition(LOST, current, "source ticket changed")
    now = utcnow()
    set_fields = {
        key: replacement[key]
        for key in (
            "schema_version", "venue", "ticket_type", "ticket_number", "guild_id",
            "location", "channel_id", "thread_id", "category_id", "user_id",
            "username", "username_search", "display_name", "player_tags",
            "player_tag", "source",
        )
        if key in replacement
    }
    set_fields.update({"migrated_at": now, "updated_at": now})
    audit = {
        "event": "legacy_location_replaced",
        "at": now,
        "from": {
            "venue": current.get("venue", "channel"),
            "location": current_location or {
                "guild_id": current.get("guild_id"),
                "id": current.get("channel_id"),
                "staff_space_id": current.get("thread_id"),
            },
        },
        "to": {"venue": "thread", "location": target_location},
        "rev_before": rev,
        "rev_after": rev + 1,
    }
    try:
        updated = await primary.find_one_and_update(
            {
                "_id": existing_ticket_id,
                "type": "ticket",
                "status": replacement["status"],
                "rev": _rev_filter(rev),
            },
            {
                "$set": set_fields,
                "$unset": {field: "" for field in schema.CLAIM_FIELDS},
                "$inc": {"rev": 1},
                "$push": {"audit": audit},
            },
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise TicketConflictError("the destination thread pair is already indexed") from exc
    if updated is None:
        latest = await primary.find_one({"_id": existing_ticket_id, "type": "ticket"})
        return Transition(LOST, latest)
    await _mirror_to(secondary, updated)
    return Transition(WON, updated)


MAX_ANSWER_SNAPSHOTS = 50
MAX_ANSWER_LENGTH = 2000


async def append_candidate_activity(
    mongo: MongoClient,
    ticket_id,
    *,
    message_id,
    author_id,
    content: str,
    player_tags: Iterable[str] = (),
    occurred_at: datetime | None = None,
    kind: str = "answer",
) -> Transition:
    """Idempotently append one bounded candidate answer and merge discovered tags."""
    message = schema.snowflake(message_id, field="message_id")
    author = schema.snowflake(author_id, field="author_id")
    at = schema.normalize_datetime(occurred_at, field="occurred_at")
    tags = schema.player_tags(player_tags)
    answer = {
        "message_id": message,
        "author_id": author,
        "kind": str(kind or "answer").strip()[:40],
        "content": str(content or "").strip()[:MAX_ANSWER_LENGTH],
        "at": at,
    }
    primary, secondary = await _both(mongo)
    update: dict = {
        "$push": {
            "answers": {"$each": [answer], "$slice": -MAX_ANSWER_SNAPSHOTS}
        },
        "$max": {"last_activity_at": at},
        "$set": {"updated_at": utcnow()},
        "$inc": {"answer_count": 1, "rev": 1},
    }
    if tags:
        update["$addToSet"] = {"player_tags": {"$each": tags}}
    updated = await primary.find_one_and_update(
        {
            "_id": ticket_id,
            "type": "ticket",
            "venue": "thread",
            "status": "open",
            "answers.message_id": {"$ne": message},
        },
        update,
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        current = await primary.find_one({"_id": ticket_id, **RUNTIME_FILTER})
        if current is None:
            return Transition(MISSING, None)
        if any(as_int(item.get("message_id")) == message for item in current.get("answers", [])):
            return Transition(WON, current, "already recorded")
        return Transition(LOST, current, "ticket is no longer open")
    await _mirror_to(secondary, updated)
    return Transition(WON, updated)


async def status_counts(collection) -> dict[str, int]:
    docs = await collection.find(TICKET_FILTER, {"status": 1}).to_list(length=None)
    return dict(Counter(doc.get("status") or "(missing)" for doc in docs))


def _duplicates(values: Mapping[tuple, list[str]]) -> list[dict]:
    return [
        {"key": key, "ticket_ids": ids}
        for key, ids in values.items()
        if len(ids) > 1
    ]


def index_conflicts_for_documents(docs: Iterable[Mapping]) -> dict[str, list]:
    """Preflight every unique index after mixed-ID/schema normalization."""
    buckets: dict[str, defaultdict] = {
        "location": defaultdict(list),
        "staff_location": defaultdict(list),
        "ticket_number": defaultdict(list),
        "open_applicant": defaultdict(list),
        "source": defaultdict(list),
    }
    schema_errors: list[dict] = []
    for raw in docs:
        try:
            doc = normalize_ticket_document(raw)
        except Exception as exc:
            schema_errors.append({"ticket_id": str(raw.get("_id")), "error": str(exc)})
            continue
        ticket_id = str(doc["_id"])
        location = doc.get("location") or {}
        source = doc.get("source") or {}
        if as_int(location.get("id")):
            buckets["location"][as_int(location["id"])].append(ticket_id)
        if as_int(location.get("staff_space_id")):
            buckets["staff_location"][as_int(location["staff_space_id"])].append(ticket_id)
        if doc.get("ticket_type") and as_int(doc.get("ticket_number")):
            buckets["ticket_number"][(doc["ticket_type"], int(doc["ticket_number"]))].append(ticket_id)
        if (
            doc.get("venue") == "thread"
            and doc.get("status") == "open"
            and as_int(doc.get("user_id"))
            and doc.get("ticket_type")
        ):
            buckets["open_applicant"][(int(doc["user_id"]), doc["ticket_type"])].append(ticket_id)
        if as_int(source.get("guild_id")) and as_int(source.get("channel_id")):
            buckets["source"][(int(source["guild_id"]), int(source["channel_id"]))].append(ticket_id)

    conflicts = {name: _duplicates(values) for name, values in buckets.items()}
    conflicts = {name: rows for name, rows in conflicts.items() if rows}
    if schema_errors:
        conflicts["schema"] = schema_errors
    return conflicts


async def index_conflicts(collection) -> dict[str, list]:
    docs = await collection.find(TICKET_FILTER).to_list(length=None)
    return index_conflicts_for_documents(docs)


async def ensure_indexes(mongo: MongoClient) -> list[str]:
    """Install production indexes only after a collision-free preflight."""
    conflicts = await index_conflicts(mongo.tickets)
    if conflicts:
        raise IndexConflictError(conflicts)
    collection = mongo.tickets
    specs = [
        await collection.create_index(
            [("location.id", 1)],
            unique=True,
            partialFilterExpression={"type": "ticket", "location.id": {"$exists": True}},
            name="ticket_location_unique",
        ),
        await collection.create_index(
            [("location.staff_space_id", 1)],
            unique=True,
            partialFilterExpression={
                "type": "ticket", "location.staff_space_id": {"$exists": True}
            },
            name="ticket_staff_location_unique",
        ),
        await collection.create_index(
            [("ticket_type", 1), ("ticket_number", 1)],
            unique=True,
            partialFilterExpression={
                "type": "ticket", "ticket_type": {"$exists": True},
                "ticket_number": {"$exists": True},
            },
            name="ticket_number_unique",
        ),
        await collection.create_index(
            [("user_id", 1), ("ticket_type", 1)],
            unique=True,
            partialFilterExpression={
                "type": "ticket", "venue": "thread", "status": "open",
                "user_id": {"$exists": True},
                "ticket_type": {"$exists": True},
            },
            name="one_open_ticket_per_applicant_type",
        ),
        await collection.create_index(
            [("source.guild_id", 1), ("source.channel_id", 1)],
            unique=True,
            partialFilterExpression={
                "type": "ticket", "source.guild_id": {"$exists": True},
                "source.channel_id": {"$exists": True},
            },
            name="ticket_source_unique",
        ),
        await collection.create_index(
            [("status", 1), ("created_at", -1)], name="status_created"
        ),
        await collection.create_index(
            [("ticket_type", 1), ("status", 1), ("created_at", -1)],
            name="type_status_created",
        ),
        await collection.create_index(
            [("user_id", 1), ("created_at", -1)], name="user_created"
        ),
        await collection.create_index(
            [("player_tags", 1), ("created_at", -1)], name="player_tags_created"
        ),
        await collection.create_index(
            [("username_search", 1), ("created_at", -1)], name="username_created"
        ),
    ]
    for field in ACCOUNT_RECOVERY_BOOLEAN_FIELDS:
        specs.append(await collection.create_index(
            [(field, 1)],
            partialFilterExpression={**RUNTIME_FILTER, field: True},
            name="account_recovery_" + field.rsplit(".", 1)[-1],
        ))
    return [str(name) for name in specs]
