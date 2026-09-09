"""Durable ticket repository, indexes, and compare-and-swap transitions."""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping

from pymongo import ReturnDocument
from pymongo.errors import (
    DuplicateKeyError,
    ExecutionTimeout,
    OperationFailure,
    WriteConcernError,
    WTimeoutError,
)

from extensions.commands import ticket_runtime
from extensions.commands.tickets import schema
from utils.mongo import MongoClient


_log = logging.getLogger(__name__)

RUNTIME_FILTER = {
    "type": "ticket",
    "venue": "thread",
    "runtime": ticket_runtime.THREAD_RUNTIME,
}
TICKET_FILTER = {"type": "ticket"}
ACCOUNT_RECOVERY_BOOLEAN_FIELDS = (
    "linked_accounts.retry_required",
    "linked_accounts.context_refresh_required",
    "linked_accounts.flag_refresh_required",
)
STORE_BUTTON = "button_store"
STORE_TICKETS = "tickets"
CANONICAL_ACTIVATION_VERSION = 3
# `audit` and `account_identity_audit` are unbounded per-action history on a
# collection that may never carry a TTL; every $push into either one must
# slice to this bound at the push site (rule 8).
MAX_AUDIT_ENTRIES = 200
# Coexistence has two explicit authorities: this v2 repository always owns
# ``tickets`` and the namespaced legacy repository always owns ``button_store``.
DEFAULT_STORE = STORE_TICKETS

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


class GuardedFieldWriteError(TicketStoreError):
    """A generic update tried to set one half of a duplicated identity field."""


class OpenTicketExistsError(TicketConflictError):
    def __init__(self, existing: dict | None = None):
        super().__init__("an open ticket already exists for this applicant and type")
        self.existing = existing


class IndexConflictError(TicketStoreError):
    def __init__(self, conflicts: Mapping[str, list]):
        super().__init__("ticket index conflicts must be repaired before index creation")
        self.conflicts = dict(conflicts)


# One conflicting row makes `ensure_indexes` fail every time it runs, and it
# runs on the hot path of ticket creation (`thread_service.ensure_creation_indexes`
# never caches its own failure). Without a retry window, every interaction
# repeats the full-collection preflight scan and 13 create_index round trips.
# Cache the failure like `utils/clan_history.py:ensure_indexes` does and let
# it retry only after the window (rules 4, 12).
INDEX_RETRY_SECONDS = 60 * 60
_indexes_failed = False
_index_retry_at = 0.0
_last_index_error: Exception | None = None


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
    return STORE_TICKETS


async def _reader(mongo: MongoClient):
    return mongo.tickets


def _normalized(document: Mapping | None) -> dict | None:
    """Apply the current schema shape to a document read off the wire.

    `schema_version` is written on every insert, but nothing enforced it on
    read, so callers kept special-casing historical shapes (`_mixed_id`)
    instead of trusting the canonical one. Normalising here makes every
    reader see schema-version-3 shape regardless of what is actually stored.
    """
    if document is None:
        return None
    return normalize_ticket_document(document)


def _normalized_many(documents: Iterable[Mapping]) -> list[dict]:
    return [normalize_ticket_document(document) for document in documents]


async def find_one(mongo: MongoClient, filt: dict):
    raw = await (await _reader(mongo)).find_one({**dict(filt), **RUNTIME_FILTER})
    return _normalized(raw)


async def find(mongo: MongoClient, filt: dict, *, include_legacy: bool = False) -> list[dict]:
    """Read ticket documents, thread-runtime only by default.

    RUNTIME_FILTER's own ``venue``/``runtime`` keys are merged in last, so
    they always win over anything the caller passed for those keys -- a
    caller filtering for channel-era rows (``venue`` != ``thread``) would
    silently get zero results. Pass ``include_legacy=True`` for a
    diagnostics-only read that must also see those rows; it drops
    RUNTIME_FILTER down to the bare ``type`` check so the caller's own venue
    filter is honoured. Every ticket-lifecycle reader keeps the default.

    ``include_legacy=True`` also skips schema normalisation and returns raw
    documents as stored: ``normalize_ticket_document`` raises
    ``TicketSchemaError`` on a legacy row with ``status == "closed"``, and
    such rows exist in production. The only caller (manage.py's diagnostics
    reconciliation) wants raw statuses, not the canonical shape.
    """
    base = TICKET_FILTER if include_legacy else RUNTIME_FILTER
    raw = await (await _reader(mongo)).find(
        {**dict(filt), **base}
    ).to_list(length=None)
    if include_legacy:
        return raw
    return _normalized_many(raw)


def _mixed_id(value) -> list:
    normalized = as_int(value)
    return [normalized, str(normalized)] if normalized else []


async def find_by_location(mongo: MongoClient, location_id) -> dict | None:
    # `channel_id`/`thread_id` are the guarded compatibility aliases of
    # `location.id`/`location.staff_space_id` for every thread-runtime
    # document (see GUARDED_IDENTITY_FIELDS) -- they are always equal, so
    # matching on the two `location.*` fields already covers both aliases.
    # Dropping those branches lets the `$or` run entirely off the unique
    # partial indexes on `location.id`/`location.staff_space_id` instead of
    # falling back to a collection scan.
    ids = _mixed_id(location_id)
    if not ids:
        return None
    return await find_one(mongo, {
        **RUNTIME_FILTER,
        "$or": [
            {"location.id": {"$in": ids}},
            {"location.staff_space_id": {"$in": ids}},
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
    """Open tickets, oldest first -- the console hub picker only ever shows
    the first `limit`, and it must be the longest-waiting applicants that
    stay visible, not the ones who just opened a ticket."""
    amount = max(1, min(int(limit), 25))
    cursor = (await _reader(mongo)).find({**RUNTIME_FILTER, "status": "open"})
    raw = await cursor.sort([("created_at", 1), ("_id", 1)]).limit(amount).to_list(
        length=amount
    )
    return _normalized_many(raw)


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
        return {"$or": [
            {"player_tags": tag},
            {"mentioned_tags": tag},
            {"player_tag": tag},
            {"tag": tag},
        ]}
    if not 2 <= len(value) <= 32 or re.fullmatch(r"[\w .-]+", value) is None:
        raise SearchQueryError(
            "Use a Discord ID, player tag, or a 2-32 character username"
        )
    # `username_search` is pre-normalized (casefolded, whitespace-collapsed)
    # the same way on write and here, and thread_v2_username_created indexes
    # exactly that field. A case-insensitive $regex on the raw `username`
    # cannot use that index (no collation), so a query landing here would
    # scan the whole collection for no matches the indexed field would not
    # already catch (rule 12).
    return {"username_search": schema.username_search(value)}


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
    raw = await cursor.sort([("created_at", -1), ("_id", -1)]).limit(amount).to_list(
        length=amount
    )
    return _normalized_many(raw)


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
    raw = await cursor.sort([("created_at", -1), ("_id", -1)]).limit(amount).to_list(
        length=amount
    )
    return _normalized_many(raw)


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


async def insert_one(mongo: MongoClient, doc: dict) -> dict:
    """Create once; exact retries return the committed record without replacing it."""
    normalized = normalize_ticket_document(
        {**dict(doc), "runtime": ticket_runtime.THREAD_RUNTIME}
    )
    if normalized.get("venue") != "thread":
        raise schema.TicketSchemaError("runtime ticket inserts must be thread tickets")
    if normalized.get("status") == "open" and (
        not normalized.get("open_slot_id")
        or not normalized.get("creation_workflow_id")
    ):
        raise schema.TicketSchemaError(
            "live thread tickets require a shared open-slot binding"
        )
    primary = mongo.tickets
    try:
        await primary.update_one(
            {"_id": normalized["_id"]},
            {"$setOnInsert": normalized},
            upsert=True,
        )
    except DuplicateKeyError as exc:
        existing = await primary.find_one({
            **RUNTIME_FILTER,
            "user_id": normalized.get("user_id"),
            "ticket_type": normalized.get("ticket_type"),
            "status": "open",
        })
        if existing is not None:
            raise OpenTicketExistsError(existing) from exc
        raise TicketConflictError("a unique ticket identity is already in use") from exc

    committed = await primary.find_one(
        {"_id": normalized["_id"], **RUNTIME_FILTER}
    )
    if committed is None:
        if await primary.find_one({"_id": normalized["_id"]}) is not None:
            raise TicketConflictError(
                f"ticket id {normalized['_id']} belongs to another runtime"
            )
        raise TicketStoreError("primary ticket write was not readable after commit")
    if _identity_fingerprint(committed) != _identity_fingerprint(normalized):
        raise TicketConflictError(
            f"ticket id {normalized['_id']} already belongs to another ticket"
        )
    return committed


# location.id/channel_id, location.staff_space_id/thread_id,
# location.guild_id/guild_id, and player_tags[0]/player_tag are each stored
# twice (rule 5/6). `transition()` keeps its own writes off these by
# stripping them out of `extra`; the generic `update_one`/`update_many`
# passthrough has no such filter, so it is rejected here instead — a caller
# that genuinely needs to change one of these goes through transition(),
# compare_and_swap_linked_accounts(), or another dedicated setter that
# writes both halves together under the `rev` CAS.
GUARDED_IDENTITY_FIELDS = frozenset({
    "location", "guild_id", "channel_id", "thread_id",
    "player_tag", "player_tags",
})


def _reject_guarded_identity_writes(update: Mapping) -> None:
    for operator, fields in update.items():
        if not str(operator).startswith("$") or not isinstance(fields, Mapping):
            continue
        for key in fields:
            if str(key).split(".", 1)[0] in GUARDED_IDENTITY_FIELDS:
                raise GuardedFieldWriteError(
                    f"update_one/update_many cannot write duplicated identity "
                    f"field '{key}'; use transition() or a dedicated setter"
                )


async def update_one(mongo: MongoClient, filt: dict, update: dict):
    _reject_guarded_identity_writes(update)
    return await mongo.tickets.update_one(
        {**dict(filt), **RUNTIME_FILTER}, update
    )


async def update_many(mongo: MongoClient, filt: dict, update: dict):
    _reject_guarded_identity_writes(update)
    return await mongo.tickets.update_many(
        {**dict(filt), **RUNTIME_FILTER}, update
    )


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
    doc = await mongo.tickets.find_one_and_update(
        filt, update, return_document=ReturnDocument.AFTER
    )
    if doc is not None:
        return Transition(WON, doc)
    current = await mongo.tickets.find_one({"_id": ticket_id, **RUNTIME_FILTER})
    return Transition(LOST, current) if current is not None else Transition(MISSING, None)


async def compare_and_swap_linked_accounts(
    mongo: MongoClient,
    ticket_id,
    *,
    expected_revision: int,
    update: dict,
    fetched_at: datetime | None = None,
) -> Transition:
    """Atomically persist one linked-account observation without changing decision rev.

    Ticket ``rev`` protects recruiter decisions and the component state rendered from
    them.  Account refreshes use their own revision so a background refresh cannot
    invalidate an otherwise current Approve/Deny panel.  The CAS still prevents two
    workers from replacing each other's complete account snapshots.

    ``fetched_at``, when given, is the caller's lookup start time.  The revision
    filter alone cannot stop a slower, older lookup from overwriting a faster,
    newer one: both can observe the same revision, the newer one wins the CAS
    first, and the older one's retry then re-reads the now-current revision and
    matches it too.  Requiring the document's stored ``linked_accounts.fetched_at``
    to be no newer than this lookup's rejects that stale write.
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
    filt = {"_id": ticket_id, **RUNTIME_FILTER}
    if fetched_at is None:
        filt.update(revision_filter)
    else:
        filt["$and"] = [
            revision_filter,
            {"$or": [
                {"linked_accounts.fetched_at": {"$exists": False}},
                {"linked_accounts.fetched_at": {"$lte": fetched_at}},
            ]},
        ]
    return await _conditional(mongo, filt, update, ticket_id)


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

    primary = mongo.tickets
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
        # An override always overturns a prior terminal decision (open cannot
        # be a `from` here - transition() below refuses re-opening). Record it
        # under its own event name with the fields a reader would look for,
        # alongside `overrode` which keeps the prior decision's own identity.
        audit["event"] = "overturn"
        audit["by"] = actor
        audit["reason"] = str((extra or {}).get("denial_reason") or "") or None
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
        "_id", "type", "schema_version", "venue", "runtime", "location", "guild_id",
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
        **RUNTIME_FILTER,
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

    push_fields: dict = {
        "audit": {"$each": [audit], "$slice": -MAX_AUDIT_ENTRIES},
    }
    increments = {"rev": 1}
    if linked_account_retry is not None:
        increments["linked_accounts.revision"] = 1
        push_fields["account_identity_audit"] = {
            "$each": [{
                "event": "linked_accounts_sync_failed",
                "at": now,
                "source": set_fields["linked_accounts.source"],
                "error": set_fields["linked_accounts.error"],
                "retry_queued_with_decision": True,
            }],
            "$slice": -MAX_AUDIT_ENTRIES,
        }

    outcome = await _conditional(
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
    if outcome.won:
        try:
            await ticket_runtime.mark_slot_release_pending(
                mongo,
                ticket_id=ticket_id,
                terminal_status=target,
            )
        except Exception:
            # The decision is already authoritative. Startup reconciliation can
            # observe the terminal row and repair/release its exact bound slot.
            _log.exception("ticket slot terminal checkpoint failed for %s", ticket_id)
        else:
            try:
                await ticket_runtime.release_open_slot(mongo, ticket_id=ticket_id)
            except Exception:
                _log.exception("ticket slot release deferred for %s", ticket_id)
        # Thread-system state (ticket_creation_state) only exists for
        # thread-venue tickets. transition() is also used by the legacy
        # channel package, whose tickets carry venue "channel"; calling this
        # for them would upsert a bogus row that nothing ever cleans up.
        if str((outcome.doc or {}).get("venue") or "") == "thread":
            # Local import: thread_service imports this module at top level,
            # so a top-level import here would be circular.
            from extensions.commands.tickets import thread_service

            await thread_service.mark_creation_complete_for_terminal_ticket(
                mongo, outcome.doc
            )
    return outcome


MAX_ANSWER_SNAPSHOTS = 50
MAX_ANSWER_LENGTH = 2000


async def append_candidate_activity(
    mongo: MongoClient,
    ticket_id,
    *,
    message_id,
    author_id,
    content: str,
    mentioned_tags: Iterable[str] = (),
    occurred_at: datetime | None = None,
    kind: str = "answer",
) -> Transition:
    """Idempotently append one bounded candidate answer and merge mentioned tags.

    Tags scraped from applicant messages are unverified — anyone can type any
    tag. They are stored on ``mentioned_tags`` as a search/display hint only
    and never join ``player_tags``, the verified identity used for flag and
    blacklist matching.

    This never touches ``rev``: ``rev`` is the console's resolution CAS
    counter, and an applicant typing another answer while a recruiter has a
    detail panel open must not make that recruiter's Approve/Deny look like
    it raced someone else. Anything that needs to observe fresh activity
    bumps ``activity_revision`` instead.
    """
    message = schema.snowflake(message_id, field="message_id")
    author = schema.snowflake(author_id, field="author_id")
    at = schema.normalize_datetime(occurred_at, field="occurred_at")
    tags = schema.player_tags(mentioned_tags)
    answer = {
        "message_id": message,
        "author_id": author,
        "kind": str(kind or "answer").strip()[:40],
        "content": str(content or "").strip()[:MAX_ANSWER_LENGTH],
        "at": at,
    }
    primary = mongo.tickets
    update: dict = {
        "$push": {
            "answers": {"$each": [answer], "$slice": -MAX_ANSWER_SNAPSHOTS}
        },
        "$max": {"last_activity_at": at},
        "$set": {"updated_at": utcnow()},
        "$inc": {"answer_count": 1, "activity_revision": 1},
    }
    if tags:
        update["$addToSet"] = {"mentioned_tags": {"$each": tags}}
    updated = await primary.find_one_and_update(
        {
            "_id": ticket_id,
            **RUNTIME_FILTER,
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
    return Transition(WON, updated)


async def mark_thread_missing(
    mongo: MongoClient,
    ticket_id,
    *,
    thread_role: str,
) -> Transition:
    """Record that one thread of a ticket's pair is gone from Discord.

    A field, not a status -- ``status`` still reflects the recruiter's
    decision (open/approved/denied). This only records that the candidate's
    or staff's Discord thread itself was deleted, so re-click/My ticket can
    let the applicant open a new one instead of pointing at a dead thread
    forever, and resolution effects can skip instead of retrying every 60s.
    Idempotent: re-marking an already-flagged ticket just refreshes the
    timestamp, never raises. A staff marker never downgrades a candidate
    marker: once the candidate thread is known missing (slot released, new
    ticket allowed), a later staff-thread deletion must not overwrite that
    fact and bring the ticket back into the open authority set.
    """
    role = str(thread_role or "").strip()
    if role not in {"candidate", "staff"}:
        raise ValueError("thread_role must be 'candidate' or 'staff'")
    now = utcnow()
    filter_doc = {"_id": ticket_id, **RUNTIME_FILTER}
    if role == "staff":
        filter_doc["thread_missing.thread_role"] = {"$ne": "candidate"}
    updated = await mongo.tickets.find_one_and_update(
        filter_doc,
        {"$set": {
            "thread_missing": {"thread_role": role, "detected_at": now},
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        if role == "staff":
            existing = await mongo.tickets.find_one({"_id": ticket_id, **RUNTIME_FILTER})
            if existing is not None:
                # Candidate marker already present; keep it, treat as done.
                return Transition(WON, existing)
        return Transition(MISSING, None)
    return Transition(WON, updated)


async def claim_creation_dm(mongo: MongoClient, ticket_id) -> bool:
    """CAS-claim the one-time send of the ticket creation DM.

    A retried REST call after a crash between send and record must not DM
    the applicant twice, so the marker is written before the DM is sent and
    the filter only matches while it is still unset. Returns True when this
    call won the claim (send the DM); False when it was already claimed.
    """
    updated = await mongo.tickets.find_one_and_update(
        {"_id": ticket_id, **RUNTIME_FILTER, "creation_dm_sent_at": {"$exists": False}},
        {"$set": {"creation_dm_sent_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return updated is not None


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
        if any(raw.get(key) != value for key, value in RUNTIME_FILTER.items()):
            continue
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
    docs = await collection.find(RUNTIME_FILTER).to_list(length=None)
    return index_conflicts_for_documents(docs)


# Atlas failover raises a bare OperationFailure with one of these codes
# (ExecutionTimeout, ShutdownInProgress, PrimarySteppedDown,
# ExceededTimeLimit, InterruptedAtShutdown, InterruptedDueToReplStateChange).
# These clear on their own once a primary is elected, so caching them would
# block ticket intake for the retry window after Mongo has already recovered.
# 6, 7, 89, 134, 9001 are pymongo's own retryable codes (HostUnreachable,
# HostNotFound, NetworkTimeout, ReadConcernMajorityNotAvailableYet,
# SocketException); a mongos-fronted deployment surfaces them as a bare
# OperationFailure rather than a connection error.
TRANSIENT_OPERATION_FAILURE_CODES = frozenset(
    {6, 7, 50, 89, 91, 134, 189, 262, 9001, 11600, 11602}
)


def is_cacheable_index_error(exc: Exception) -> bool:
    """Only an outcome that needs operator repair should be cached.

    ``IndexConflictError`` (a conflicting row) and a stable pymongo
    ``OperationFailure`` (an incompatible existing index) are stable until
    someone fixes the data or the index definition, so caching them avoids
    repeating the full-collection preflight scan on every interaction.

    ``ExecutionTimeout``, ``WriteConcernError`` and ``WTimeoutError`` all
    subclass ``OperationFailure`` but are transient, as is a bare
    ``OperationFailure`` whose ``.code`` is in
    ``TRANSIENT_OPERATION_FAILURE_CODES`` (Atlas failover/step-down). A
    transient Atlas outage also raises ``ServerSelectionTimeoutError``,
    ``AutoReconnect``, ``NetworkTimeout`` or another ``PyMongoError`` that is
    not an ``OperationFailure`` at all -- none of these must be cached or
    ticket intake would stay blocked for the retry window after Mongo has
    already recovered.
    """
    if isinstance(exc, IndexConflictError):
        return True
    if not isinstance(exc, OperationFailure):
        return False
    if isinstance(exc, (ExecutionTimeout, WriteConcernError, WTimeoutError)):
        return False
    return exc.code not in TRANSIENT_OPERATION_FAILURE_CODES


async def ensure_indexes(mongo: MongoClient) -> list[str]:
    """Install v2-only indexes after preflight.

    Mongo raises an index-options conflict if an old same-named definition is
    broader. That failure is intentional and blocks intake for operator review;
    this service never drops or silently replaces production indexes.

    A failure here that needs operator repair (a conflicting row, an
    incompatible existing index) is cached for ``INDEX_RETRY_SECONDS`` so a
    caller on the ticket-creation hot path does not repeat the
    full-collection preflight scan and every create_index round trip on each
    interaction; it retries automatically once the window passes. A
    transient connection failure is never cached -- see
    ``is_cacheable_index_error`` -- so the next interaction retries
    immediately instead of waiting out the window.
    """
    global _indexes_failed, _index_retry_at, _last_index_error
    if _indexes_failed and time.monotonic() < _index_retry_at:
        assert _last_index_error is not None
        raise _last_index_error

    try:
        names = await _install_indexes(mongo)
    except Exception as exc:
        if is_cacheable_index_error(exc):
            _indexes_failed = True
            _index_retry_at = time.monotonic() + INDEX_RETRY_SECONDS
            _last_index_error = exc
        raise
    _indexes_failed = False
    _last_index_error = None
    return names


async def _install_indexes(mongo: MongoClient) -> list[str]:
    conflicts = await index_conflicts(mongo.tickets)
    if conflicts:
        raise IndexConflictError(conflicts)
    collection = mongo.tickets
    specs = [
        await collection.create_index(
            [("location.id", 1)],
            unique=True,
            partialFilterExpression={
                **RUNTIME_FILTER,
                "location.id": {"$exists": True},
            },
            name="thread_v2_ticket_location_unique",
        ),
        await collection.create_index(
            [("location.staff_space_id", 1)],
            unique=True,
            partialFilterExpression={
                **RUNTIME_FILTER,
                "location.staff_space_id": {"$exists": True},
            },
            name="thread_v2_ticket_staff_location_unique",
        ),
        # find_by_location's $or scans every guild message to resolve which
        # ticket a channel/thread belongs to. Its two branches query
        # location.id/location.staff_space_id with a non-null $in, which
        # entails existence -- so the unique partial indexes above (whose
        # partial filter is exactly RUNTIME_FILTER plus that field existing)
        # already serve the read path; a separate non-unique index on the
        # same keys would be redundant.
        await collection.create_index(
            [("ticket_type", 1), ("ticket_number", 1)],
            unique=True,
            partialFilterExpression={
                **RUNTIME_FILTER,
                "ticket_type": {"$exists": True},
                "ticket_number": {"$exists": True},
            },
            name="thread_v2_ticket_number_unique",
        ),
        await collection.create_index(
            [("user_id", 1), ("ticket_type", 1)],
            unique=True,
            partialFilterExpression={
                **RUNTIME_FILTER,
                "status": "open",
                "user_id": {"$exists": True},
                "ticket_type": {"$exists": True},
            },
            name="thread_v2_one_open_ticket_per_applicant_type",
        ),
        await collection.create_index(
            [("source.guild_id", 1), ("source.channel_id", 1)],
            unique=True,
            partialFilterExpression={
                **RUNTIME_FILTER,
                "source.guild_id": {"$exists": True},
                "source.channel_id": {"$exists": True},
            },
            name="thread_v2_ticket_source_unique",
        ),
        await collection.create_index(
            [("status", 1), ("created_at", -1)],
            partialFilterExpression=RUNTIME_FILTER,
            name="thread_v2_status_created",
        ),
        await collection.create_index(
            [("ticket_type", 1), ("status", 1), ("created_at", -1)],
            partialFilterExpression=RUNTIME_FILTER,
            name="thread_v2_type_status_created",
        ),
        await collection.create_index(
            [("user_id", 1), ("created_at", -1)],
            partialFilterExpression=RUNTIME_FILTER,
            name="thread_v2_user_created",
        ),
        await collection.create_index(
            [("player_tags", 1), ("created_at", -1)],
            partialFilterExpression=RUNTIME_FILTER,
            name="thread_v2_player_tags_created",
        ),
        await collection.create_index(
            [("username_search", 1), ("created_at", -1)],
            partialFilterExpression=RUNTIME_FILTER,
            name="thread_v2_username_created",
        ),
    ]
    for field in ACCOUNT_RECOVERY_BOOLEAN_FIELDS:
        specs.append(await collection.create_index(
            [(field, 1)],
            partialFilterExpression={**RUNTIME_FILTER, field: True},
            name="thread_v2_account_recovery_" + field.rsplit(".", 1)[-1],
        ))
    return [str(name) for name in specs]
