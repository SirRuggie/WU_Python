"""Durable Clash-account identity synchronization for thread tickets.

The shared Discord-link service answers which tags belong to an applicant.  A
successful lookup replaces only the *current linked snapshot*.  Every tag ever
observed remains in ``player_tags`` and the identity audit so an unlink cannot
silently sever ticket history or flags.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

import coc

from extensions.commands.accounts import (
    LINK_FAILURE,
    AccountEntry,
    load_accounts,
)
from extensions.commands.tickets import schema, store
from utils import bot_data
from utils.mongo import MongoClient


STATE_PENDING = "pending"
STATE_READY = "ready"
STATE_EMPTY = "empty"
STATE_FAILED = "failed"
SYNC_STATES = frozenset({STATE_PENDING, STATE_READY, STATE_EMPTY, STATE_FAILED})

SOURCE_OPEN = "ticket_open"
SOURCE_OPEN_RETRY = "ticket_open_retry"
SOURCE_RECRUITER_REFRESH = "recruiter_refresh"
SOURCE_FINAL_APPROVE = "final_approve"
SOURCE_FINAL_DENY = "final_deny"
SOURCE_RECOVERY = "automatic_retry"

MAX_SOURCE_LENGTH = 80
MAX_NAME_LENGTH = 100
MAX_SYNC_RETRIES = 8
CONTEXT_REFRESH_SOURCES = frozenset({SOURCE_FINAL_APPROVE, SOURCE_RECOVERY})


class AccountSyncError(RuntimeError):
    """A linked-account result could not be durably attached to its ticket."""


@dataclass(frozen=True, slots=True)
class LinkedAccount:
    tag: str
    name: str | None = None
    town_hall: int = 0
    profile_status: str = "not_loaded"


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    state: str
    current_accounts: tuple[LinkedAccount, ...]
    current_tags: tuple[str, ...]
    observed_tags: tuple[str, ...]
    retry_required: bool
    source: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error: str | None = None
    revision: int = 0

    @property
    def successful(self) -> bool:
        return self.state in {STATE_READY, STATE_EMPTY}

    @property
    def has_linked_accounts(self) -> bool:
        return self.state == STATE_READY and bool(self.current_tags)


@dataclass(frozen=True, slots=True)
class AccountSyncResult:
    ticket: dict | None
    snapshot: AccountSnapshot
    added_tags: tuple[str, ...] = ()
    no_longer_linked_tags: tuple[str, ...] = ()

    @property
    def missing(self) -> bool:
        return self.ticket is None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def configured_coc_client() -> coc.Client | None:
    """Return the process-owned Clash client after startup has registered it."""
    return bot_data.data.get("coc_client")


def _text(value: object, *, limit: int) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    return normalized[:limit] or None


def _account_from_document(value: Mapping[str, Any]) -> LinkedAccount | None:
    try:
        tag = schema.player_tag(value.get("tag"))
    except schema.TicketSchemaError:
        return None
    if tag is None:
        return None
    return LinkedAccount(
        tag=tag,
        name=_text(value.get("name"), limit=MAX_NAME_LENGTH),
        town_hall=max(0, int(value.get("town_hall") or 0)),
        profile_status=str(value.get("profile_status") or "not_loaded")[:40],
    )


def snapshot_from_ticket(ticket: Mapping[str, Any] | None) -> AccountSnapshot:
    """Return the stable account-identity view consumed by ticket UI and flags."""
    document = dict(ticket or {})
    raw = document.get("linked_accounts")
    linked = raw if isinstance(raw, Mapping) else {}
    accounts = tuple(
        account
        for value in (linked.get("current") or ())
        if isinstance(value, Mapping)
        and (account := _account_from_document(value)) is not None
    )
    current_tags = tuple(schema.player_tags(
        linked.get("current_tags") or [account.tag for account in accounts]
    ))
    # Search, history, and flags intentionally use the append-only identity set,
    # including a tag disclosed in the questionnaire before it was linked.
    observed_tags = tuple(schema.player_tags(document.get("player_tags") or ()))
    state = str(linked.get("state") or STATE_PENDING)
    if state not in SYNC_STATES:
        state = STATE_FAILED
    return AccountSnapshot(
        state=state,
        current_accounts=accounts,
        current_tags=current_tags,
        observed_tags=observed_tags,
        retry_required=bool(linked.get("retry_required", state in {STATE_PENDING, STATE_FAILED})),
        source=_text(linked.get("source"), limit=MAX_SOURCE_LENGTH),
        last_attempt_at=linked.get("last_attempt_at") if isinstance(linked.get("last_attempt_at"), datetime) else None,
        last_success_at=linked.get("last_success_at") if isinstance(linked.get("last_success_at"), datetime) else None,
        error=_text(linked.get("error"), limit=120),
        revision=max(0, int(linked.get("revision") or 0)),
    )


def _entry_document(entry: AccountEntry) -> dict:
    account = entry.account
    tag = schema.player_tag(entry.tag)
    if tag is None:  # load_accounts never emits this, but storage must fail closed.
        raise AccountSyncError("linked-account service returned an empty player tag")
    return {
        "tag": tag,
        "name": _text(getattr(account, "name", None), limit=MAX_NAME_LENGTH),
        "town_hall": max(0, int(getattr(account, "town_hall", 0) or 0)),
        "profile_status": str(entry.status or "not_loaded")[:40],
    }


def _source(value: str) -> str:
    normalized = _text(value, limit=MAX_SOURCE_LENGTH)
    if normalized is None:
        raise ValueError("account sync source is required")
    return normalized


def _failed_update(
    ticket: Mapping[str, Any],
    *,
    source: str,
    at: datetime,
    error: str,
) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    prior = snapshot_from_ticket(ticket)
    revision = prior.revision + 1
    audit = {
        "event": "linked_accounts_sync_failed",
        "at": at,
        "source": source,
        "error": error,
        "account_revision": revision,
    }
    update = {
        "$set": {
            "linked_accounts.version": 1,
            "linked_accounts.state": STATE_FAILED,
            "linked_accounts.retry_required": True,
            "linked_accounts.source": source,
            "linked_accounts.last_attempt_at": at,
            "linked_accounts.error": error,
            "linked_accounts.revision": revision,
            "updated_at": at,
        },
        "$push": {"account_identity_audit": audit},
    }
    display_changed = prior.state != STATE_FAILED or prior.error != error
    prior_refresh_required = staff_context_refresh_required(ticket)
    if prior_refresh_required or (
        source in CONTEXT_REFRESH_SOURCES and display_changed
    ):
        update["$set"].update({
            "linked_accounts.context_refresh_required": True,
            "linked_accounts.context_refresh_revision": revision,
            "linked_accounts.context_refresh_source": (
                source
                if display_changed
                else str((ticket.get("linked_accounts") or {}).get(
                    "context_refresh_source"
                ) or source)[:MAX_SOURCE_LENGTH]
            ),
        })
    linked = ticket.get("linked_accounts") or {}
    if isinstance(linked, Mapping) and linked.get("flag_refresh_required") is True:
        update["$set"].update({
            "linked_accounts.flag_refresh_required": True,
            "linked_accounts.flag_refresh_revision": revision,
        })
    return update, (), ()


def _success_update(
    ticket: Mapping[str, Any],
    *,
    source: str,
    at: datetime,
    accounts: list[dict],
) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    prior = snapshot_from_ticket(ticket)
    current_tags = tuple(schema.player_tags(item["tag"] for item in accounts))
    observed_linked = {
        tag
        for item in (ticket.get("linked_account_identities") or ())
        if isinstance(item, Mapping)
        and (tag := schema.player_tag(item.get("tag"))) is not None
    }
    added = tuple(tag for tag in current_tags if tag not in observed_linked)
    no_longer_linked = tuple(tag for tag in prior.current_tags if tag not in set(current_tags))
    revision = prior.revision + 1
    state = STATE_READY if current_tags else STATE_EMPTY
    normalized_accounts = tuple(
        account
        for item in accounts
        if (account := _account_from_document(item)) is not None
    )
    display_changed = (
        prior.state != state
        or prior.current_accounts != normalized_accounts
        or prior.current_tags != current_tags
    )
    approval_review_tags = tuple(
        tag for tag in current_tags if tag not in set(prior.current_tags)
    )
    update: dict = {
        "$set": {
            "linked_accounts.version": 1,
            "linked_accounts.state": state,
            "linked_accounts.current": accounts,
            "linked_accounts.current_tags": list(current_tags),
            "linked_accounts.retry_required": False,
            "linked_accounts.source": source,
            "linked_accounts.last_attempt_at": at,
            "linked_accounts.last_success_at": at,
            "linked_accounts.revision": revision,
            "updated_at": at,
        },
        "$unset": {"linked_accounts.error": ""},
        "$push": {
            "account_identity_audit": {
                "event": "linked_accounts_synced",
                "at": at,
                "source": source,
                "outcome": state,
                "current_tags": list(current_tags),
                "added_tags": list(added),
                "no_longer_linked_tags": list(no_longer_linked),
                "account_revision": revision,
            },
        },
    }
    if current_tags:
        update["$addToSet"] = {"player_tags": {"$each": list(current_tags)}}
        if not ticket.get("player_tag"):
            update["$set"]["player_tag"] = current_tags[0]
    if added:
        update["$push"]["linked_account_identities"] = {"$each": [
            {
                "tag": item["tag"],
                "name": item.get("name"),
                "town_hall": item.get("town_hall", 0),
                "profile_status": item.get("profile_status"),
                "first_seen_at": at,
                "first_seen_source": source,
            }
            for item in accounts
            if item["tag"] in set(added)
        ]}
    linked = ticket.get("linked_accounts") or {}
    if added or (
        isinstance(linked, Mapping)
        and linked.get("flag_refresh_required") is True
    ):
        update["$set"].update({
            "linked_accounts.flag_refresh_required": True,
            "linked_accounts.flag_refresh_revision": revision,
        })
    prior_refresh_required = staff_context_refresh_required(ticket)
    if prior_refresh_required or (
        source in CONTEXT_REFRESH_SOURCES and display_changed
    ):
        update["$set"].update({
            "linked_accounts.context_refresh_required": True,
            "linked_accounts.context_refresh_revision": revision,
            "linked_accounts.context_refresh_source": (
                source
                if display_changed
                else str((ticket.get("linked_accounts") or {}).get(
                    "context_refresh_source"
                ) or source)[:MAX_SOURCE_LENGTH]
            ),
        })
    if (
        source == SOURCE_FINAL_APPROVE
        and str(ticket.get("ticket_type") or "").lower() == "fwa"
        and approval_review_tags
    ):
        update["$set"]["linked_accounts.approval_review"] = {
            "state": "pending",
            "account_revision": revision,
            "current_tags": list(current_tags),
            "new_tags": list(approval_review_tags),
            "requested_at": at,
        }
        update["$push"]["account_identity_audit"] = {
            "$each": [
                update["$push"]["account_identity_audit"],
                {
                    "event": "fwa_approval_identity_review_required",
                    "at": at,
                    "source": source,
                    "current_tags": list(current_tags),
                    "new_tags": list(approval_review_tags),
                    "account_revision": revision,
                },
            ]
        }
    return update, added, no_longer_linked


async def _persist_sync_result(
    mongo: MongoClient,
    ticket_id,
    *,
    origin: str,
    at: datetime,
    loaded,
    failure: str | None,
) -> AccountSyncResult:
    for _attempt in range(MAX_SYNC_RETRIES):
        ticket = await store.find_one(mongo, {"_id": ticket_id, **store.RUNTIME_FILTER})
        if ticket is None:
            return AccountSyncResult(None, snapshot_from_ticket(None))
        prior = snapshot_from_ticket(ticket)
        if failure is not None:
            update, added, removed = _failed_update(
                ticket, source=origin, at=at, error=failure
            )
        else:
            assert loaded is not None
            accounts = [_entry_document(entry) for entry in loaded.entries]
            update, added, removed = _success_update(
                ticket, source=origin, at=at, accounts=accounts
            )
        result = await store.compare_and_swap_linked_accounts(
            mongo,
            ticket_id,
            expected_revision=prior.revision,
            update=update,
        )
        if result.outcome == store.MISSING:
            return AccountSyncResult(None, snapshot_from_ticket(None))
        if result.won and result.doc is not None:
            durable = result.doc
            if flag_identity_refresh_required(durable):
                try:
                    durable = await reconcile_flag_identities(
                        mongo, durable, source=origin
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # The account snapshot is already authoritative. Keep the
                    # separate flag obligation durable and let recovery finish
                    # it; approval fails closed while that obligation exists.
                    durable = await store.find_one(
                        mongo,
                        {"_id": ticket_id, **store.RUNTIME_FILTER},
                    ) or durable
            return AccountSyncResult(
                durable,
                snapshot_from_ticket(durable),
                added_tags=added,
                no_longer_linked_tags=removed,
            )
    raise AccountSyncError("linked-account snapshot changed repeatedly; retry is required")


async def sync_ticket_accounts(
    mongo: MongoClient,
    coc_client: coc.Client,
    ticket_id,
    *,
    source: str,
    now: datetime | None = None,
) -> AccountSyncResult:
    """Force-refresh every linked account and persist the result with a CAS."""
    origin = _source(source)
    at = schema.normalize_datetime(now, field="account_sync_at")
    loaded = None
    failure: str | None = None
    try:
        ticket = await store.find_one(mongo, {"_id": ticket_id, **store.RUNTIME_FILTER})
        if ticket is None:
            return AccountSyncResult(None, snapshot_from_ticket(None))
        loaded = await load_accounts(coc_client, int(ticket.get("user_id") or 0), force=True)
        if loaded.problem:
            failure = "link_service" if loaded.problem == LINK_FAILURE else str(loaded.problem)[:120]
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Persist an actionable retry state for dependency failures.
        failure = type(exc).__name__

    try:
        return await _persist_sync_result(
            mongo,
            ticket_id,
            origin=origin,
            at=at,
            loaded=loaded,
            failure=failure,
        )
    except asyncio.CancelledError:
        raise
    except AccountSyncError:
        raise
    except Exception as exc:
        raise AccountSyncError(
            f"linked-account result could not be persisted: {type(exc).__name__}"
        ) from exc


async def record_ticket_account_failure(
    mongo: MongoClient,
    ticket_id,
    *,
    source: str,
    error: str,
    now: datetime | None = None,
) -> AccountSyncResult:
    """Persist a retryable dependency failure without requiring a Clash client."""

    origin = _source(source)
    at = schema.normalize_datetime(now, field="account_sync_at")
    failure = _text(error, limit=120) or "AccountSyncError"
    try:
        return await _persist_sync_result(
            mongo,
            ticket_id,
            origin=origin,
            at=at,
            loaded=None,
            failure=failure,
        )
    except asyncio.CancelledError:
        raise
    except AccountSyncError:
        raise
    except Exception as exc:
        raise AccountSyncError(
            f"linked-account failure could not be persisted: {type(exc).__name__}"
        ) from exc


def staff_context_refresh_required(ticket: Mapping[str, Any] | None) -> bool:
    linked = (ticket or {}).get("linked_accounts") or {}
    return bool(
        isinstance(linked, Mapping)
        and linked.get("context_refresh_required") is True
    )


def flag_identity_refresh_required(ticket: Mapping[str, Any] | None) -> bool:
    linked = (ticket or {}).get("linked_accounts") or {}
    return bool(
        isinstance(linked, Mapping)
        and linked.get("flag_refresh_required") is True
    )


def account_recovery_filter() -> dict:
    """Return the indexed predicate shared by startup and online recovery."""
    return {
        **store.RUNTIME_FILTER,
        "$or": [
            *({field: True} for field in store.ACCOUNT_RECOVERY_BOOLEAN_FIELDS),
            {
                "status": "open",
                "linked_accounts.version": {"$exists": False},
            },
        ],
    }


async def reconcile_flag_identities(
    mongo: MongoClient,
    ticket: Mapping[str, Any],
    *,
    source: str,
) -> dict:
    """Finish the durable account→flag identity obligation idempotently."""

    from extensions.commands.tickets import flag_store

    snapshot = snapshot_from_ticket(ticket)
    await flag_store.extend_matching_flags(
        mongo,
        discord_ids=ticket.get("user_id"),
        player_tags=ticket.get("player_tags") or (),
        source=source,
    )
    result = await store.update_one(
        mongo,
        {
            "_id": ticket.get("_id"),
            **store.RUNTIME_FILTER,
            "linked_accounts.revision": snapshot.revision,
            "linked_accounts.flag_refresh_required": True,
            "linked_accounts.flag_refresh_revision": snapshot.revision,
        },
        {
            "$set": {
                "linked_accounts.flag_refresh_required": False,
                "linked_accounts.flag_refreshed_at": utcnow(),
            },
            "$push": {
                "account_identity_audit": {
                    "event": "linked_accounts_flags_refreshed",
                    "at": utcnow(),
                    "account_revision": snapshot.revision,
                    "source": _source(source),
                },
            },
        },
    )
    if not getattr(result, "matched_count", 0):
        raise AccountSyncError("flag refresh lost an account snapshot race")
    latest = await store.find_one(
        mongo, {"_id": ticket.get("_id"), **store.RUNTIME_FILTER}
    )
    if latest is None:
        raise AccountSyncError("ticket disappeared after flag refresh")
    return latest


async def confirm_staff_context_queued(
    mongo: MongoClient,
    ticket_id,
    *,
    account_revision: int,
    now: datetime | None = None,
) -> bool:
    """Transfer one account-refresh obligation to the durable context outbox.

    The exact account revision is required so an older delivery worker cannot
    clear a newer snapshot's presentation obligation.
    """

    revision = max(0, int(account_revision))
    at = schema.normalize_datetime(now, field="staff_context_queued_at")
    result = await store.update_one(
        mongo,
        {
            "_id": ticket_id,
            **store.RUNTIME_FILTER,
            "linked_accounts.revision": revision,
            "linked_accounts.context_refresh_required": True,
            "linked_accounts.context_refresh_revision": revision,
        },
        {
            "$set": {
                "linked_accounts.context_refresh_required": False,
                "linked_accounts.context_refresh_queued_at": at,
                "updated_at": at,
            },
            "$push": {
                "account_identity_audit": {
                    "event": "linked_accounts_staff_context_queued",
                    "at": at,
                    "account_revision": revision,
                }
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def recover_pending_account_syncs(
    mongo: MongoClient,
    coc_client: coc.Client,
    *,
    limit: int = 25,
    after_sync: Callable[[dict], Awaitable[object]] | None = None,
) -> dict[str, int]:
    """Retry a bounded batch of durable failed/pending account observations."""
    amount = max(1, min(int(limit), 100))
    pending = await store.find(mongo, account_recovery_filter())
    pending.sort(key=lambda item: (
        (item.get("linked_accounts") or {}).get("last_attempt_at") or item.get("created_at"),
        str(item.get("_id") or ""),
    ))
    counts = {"processed": 0, "completed": 0, "failed": 0}
    for ticket in pending[:amount]:
        counts["processed"] += 1
        try:
            before = snapshot_from_ticket(ticket)
            if before.retry_required or not (
                (ticket.get("linked_accounts") or {}).get("version")
            ):
                result = await sync_ticket_accounts(
                    mongo, coc_client, ticket["_id"], source=SOURCE_RECOVERY
                )
            else:
                result = AccountSyncResult(ticket, before)
        except Exception:
            counts["failed"] += 1
            continue
        if result.snapshot.retry_required:
            counts["failed"] += 1
        else:
            if flag_identity_refresh_required(result.ticket):
                try:
                    durable = await reconcile_flag_identities(
                        mongo,
                        result.ticket or {},
                        source=SOURCE_RECOVERY,
                    )
                    result = AccountSyncResult(
                        durable,
                        snapshot_from_ticket(durable),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    counts["failed"] += 1
                    continue
            context_required = staff_context_refresh_required(result.ticket)
            if context_required and result.ticket is not None:
                if after_sync is None:
                    counts["failed"] += 1
                    continue
                try:
                    queued = await after_sync(result.ticket)
                    if not queued:
                        raise AccountSyncError(
                            "staff-context refresh was not durably queued"
                        )
                    confirmed = await confirm_staff_context_queued(
                        mongo,
                        result.ticket["_id"],
                        account_revision=result.snapshot.revision,
                    )
                    if not confirmed:
                        raise AccountSyncError(
                            "staff-context queue confirmation lost an account race"
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    counts["failed"] += 1
                    continue
            counts["completed"] += 1
    return counts
