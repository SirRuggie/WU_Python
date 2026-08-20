"""Operator-triggered, resumable cloning of legacy channel tickets.

Source guilds, channels, messages, and threads are strictly read-only.  Every
destination side effect has a durable source identity and a deterministic
recovery path.  The command is dry-run by default and hard-stops after five
completed pilot tickets until an administrator explicitly approves scaling.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import aiohttp
import hikari
import lightbulb
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import schema, store, thread_service, ticket
from utils.mongo import MongoClient


MIGRATION_LEASE = timedelta(minutes=15)
PILOT_LIMIT = 5
SOURCE_MARKER_PREFIX = "migration-source"
ATTACHMENT_AUDIT_LIMIT = 250
ATTACHMENT_AUDIT_CONCURRENCY = 5
ATTACHMENT_AUDIT_TIMEOUT_SECONDS = 8
DISCORD_MESSAGE_CONTENT_LIMIT = 2000
MIGRATION_SUMMARY_LIMIT = 1600
_migration_index_ready = False
_log = logging.getLogger(__name__)

_PLAYER_TAG_RE = re.compile(
    r"(?<![A-Z0-9])#[A-Z0-9]{3,9}(?![A-Z0-9])", re.IGNORECASE
)
_TICKET_NUMBER_RE = re.compile(r"(?:main|fwa)[-_ ]?(\d+)", re.IGNORECASE)


class LegacyMigrationError(RuntimeError):
    pass


class LegacyTicketStillOpen(LegacyMigrationError):
    pass


class LegacyMigrationBusy(LegacyMigrationError):
    pass


class PilotLimitReached(LegacyMigrationError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyMigrationRequest:
    source_guild_id: int
    source_channel_id: int
    target_guild_id: int
    candidate_parent_id: int
    staff_parent_id: int
    source_staff_thread_id: int | None = None
    ticket_type_override: str | None = None
    status_override: str | None = None
    user_id_override: int | None = None
    username_override: str | None = None
    player_tags_override: tuple[str, ...] = ()
    attachment_ack: str | None = None
    attachment_ack_actor_id: int | None = None
    attachment_ack_actor_name: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentAuditResult:
    source_channel_id: int
    source_message_id: int
    filename: str
    status: str
    http_status: int | None = None


@dataclass(frozen=True, slots=True)
class LegacyMigrationPreview:
    request: LegacyMigrationRequest
    source_channel: Any
    source_staff_thread: Any | None
    source_ticket: dict | None
    ticket_type: str
    status: str
    user_id: int
    username: str
    display_name: str
    player_tags: tuple[str, ...]
    created_at: datetime
    original_ticket_number: int | None
    public_message_count: int
    staff_message_count: int
    attachment_count: int
    recruiter_role_id: int
    attachment_audit: tuple[AttachmentAuditResult, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyMigrationResult:
    ticket: dict
    migration: dict
    resumed: bool


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bounded_display_join(
    values: Sequence[Any],
    *,
    limit: int,
    noun: str,
) -> str:
    """Join display values within a character budget and report omissions."""
    rendered = [str(value) for value in values]
    complete = ", ".join(rendered)
    if len(complete) <= limit:
        return complete

    shown: list[str] = []
    for index, value in enumerate(rendered):
        omitted = len(rendered) - index - 1
        suffix = (
            f" … +{omitted} {noun}{'s' if omitted != 1 else ''} omitted"
            if omitted else ""
        )
        candidate = ", ".join((*shown, value)) + suffix
        if len(candidate) > limit:
            break
        shown.append(value)

    omitted = len(rendered) - len(shown)
    suffix = f"… +{omitted} {noun}{'s' if omitted != 1 else ''} omitted"
    result = ", ".join(shown)
    if result:
        result += " "
    return result + suffix


def _migration_id(source_guild_id: int, source_channel_id: int) -> str:
    return f"legacy:{int(source_guild_id)}:{int(source_channel_id)}"


def _configured_destination(
    config: Mapping[str, Any],
    request: LegacyMigrationRequest,
    ticket_type: str,
) -> thread_service.ThreadParents:
    candidate_parent_id = _as_int(config.get(f"{ticket_type}_candidate_parent"))
    staff_parent_id = _as_int(config.get(f"{ticket_type}_staff_parent"))
    recruiter_role_id = _as_int(config.get(f"{ticket_type}_recruiter_role"))
    if not candidate_parent_id or not staff_parent_id or not recruiter_role_id:
        raise LegacyMigrationError(
            f"target {ticket_type.upper()} thread parents and recruiter role are not configured"
        )
    if (
        request.candidate_parent_id != candidate_parent_id
        or request.staff_parent_id != staff_parent_id
    ):
        raise LegacyMigrationError(
            f"destination must use the configured {ticket_type.upper()} candidate and staff parents"
        )
    return thread_service.ThreadParents(
        request.target_guild_id,
        candidate_parent_id,
        staff_parent_id,
        recruiter_role_id,
    )


def _normalized_attachment_ack(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized or None


def _attachment_identity_manifest(
    preview: LegacyMigrationPreview,
) -> list[dict[str, Any]]:
    identities = [
        {
            "source_channel_id": int(item.source_channel_id),
            "source_message_id": int(item.source_message_id),
            "filename": str(item.filename),
        }
        for item in preview.attachment_audit
    ]
    audited = len(preview.attachment_audit)
    expected = max(0, int(preview.attachment_count))
    if audited != expected:
        identities.append({
            "kind": "audit_coverage_mismatch",
            "expected": expected,
            "audited": audited,
        })
    return sorted(
        identities,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def _attachment_risk_manifest(preview: LegacyMigrationPreview) -> list[dict[str, Any]]:
    risks = [
        {
            "source_channel_id": int(item.source_channel_id),
            "source_message_id": int(item.source_message_id),
            "filename": str(item.filename),
            "status": str(item.status),
        }
        for item in preview.attachment_audit
        if item.status != "live"
    ]
    audited = len(preview.attachment_audit)
    expected = max(0, int(preview.attachment_count))
    if audited != expected:
        risks.append({
            "status": "audit_coverage_mismatch",
            "expected": expected,
            "audited": audited,
        })
    return sorted(
        risks,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def _attachment_ack_token(preview: LegacyMigrationPreview) -> str | None:
    identities = _attachment_identity_manifest(preview)
    if not identities and not preview.attachment_count:
        return None
    request = preview.request
    payload = {
        "schema_version": 1,
        "source": {
            "guild_id": request.source_guild_id,
            "channel_id": request.source_channel_id,
            "staff_thread_id": _as_int(
                getattr(preview.source_staff_thread, "id", 0)
            ) or None,
        },
        "destination": {
            "guild_id": request.target_guild_id,
            "candidate_parent_id": request.candidate_parent_id,
            "staff_parent_id": request.staff_parent_id,
        },
        "ticket": {
            "type": preview.ticket_type,
            "status": preview.status,
            "user_id": preview.user_id,
        },
        "attachment_count": preview.attachment_count,
        "attachments": identities,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "LOSS-" + hashlib.sha256(encoded).hexdigest()[:12].upper()


def _require_attachment_ack(preview: LegacyMigrationPreview) -> str | None:
    token = _attachment_ack_token(preview)
    supplied = _normalized_attachment_ack(preview.request.attachment_ack)
    if token is None:
        if supplied is not None:
            raise LegacyMigrationError(
                "the `attachment-ack` value does not match the latest preview; "
                "run a new dry run"
            )
        return None
    if supplied is not None and supplied != token:
        raise LegacyMigrationError(
            "the `attachment-ack` value does not match the latest preview; "
            "run a new dry run"
        )
    if _attachment_risk_manifest(preview) and supplied != token:
        raise LegacyMigrationError(
            "some attachments may not be copied; run a new dry run. To accept every "
            f"listed risk, copy `{token}` into `attachment-ack`"
        )
    return supplied


def _attachment_policy_for_claim(
    preview: LegacyMigrationPreview,
    current: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    token = _attachment_ack_token(preview)
    accepted_token = _require_attachment_ack(preview)
    existing = dict((current or {}).get("attachment_policy") or {})
    was_accepted = bool(existing.get("accepted"))
    previous_token = _normalized_attachment_ack(existing.get("token"))
    accepts_now = token is not None and accepted_token == token

    if was_accepted and previous_token != token and not accepts_now:
        raise LegacyMigrationError(
            "source attachments changed after you accepted the previous risks; run a "
            "new dry run and acknowledge the new preview"
        )

    policy: dict[str, Any] = {
        "schema_version": 1,
        "token": token,
        "accepted": was_accepted or accepts_now,
        "risk_count": len(_attachment_risk_manifest(preview)),
        "manifest": _attachment_identity_manifest(preview),
    }
    audit = list(existing.get("acceptance_audit") or ())
    acceptance_changed = accepts_now and (
        not was_accepted or previous_token != token
    )
    if acceptance_changed:
        actor_id = _as_int(preview.request.attachment_ack_actor_id) or None
        actor_name = str(preview.request.attachment_ack_actor_name or "").strip()
        event = {
            "event": "attachment_loss_accepted",
            "at": now,
            "actor": actor_id,
            "actor_name": actor_name or (str(actor_id) if actor_id else "unknown"),
            "token": token,
            "risk_count": policy["risk_count"],
        }
        audit.append(event)
        policy.update({
            "accepted_at": now,
            "accepted_by": actor_id,
            "accepted_by_name": event["actor_name"],
        })
    elif was_accepted:
        for field in ("accepted_at", "accepted_by", "accepted_by_name"):
            if field in existing:
                policy[field] = existing[field]
    if audit:
        policy["acceptance_audit"] = audit[-10:]
    return policy


def _message_payload_loss_is_accepted(
    state: Mapping[str, Any],
    source_channel_id: int,
    message: Any,
) -> bool:
    policy = state.get("attachment_policy") or {}
    if not policy.get("accepted"):
        return False
    remaining = [
        json.dumps(item, sort_keys=True, separators=(",", ":"))
        for item in policy.get("manifest") or ()
        if isinstance(item, Mapping) and "source_message_id" in item
    ]
    attachments = list(getattr(message, "attachments", ()) or ())
    if not attachments:
        return False
    for attachment in attachments:
        identity = json.dumps({
            "source_channel_id": int(source_channel_id),
            "source_message_id": int(message.id),
            "filename": str(getattr(attachment, "filename", "attachment")),
        }, sort_keys=True, separators=(",", ":"))
        try:
            remaining.remove(identity)
        except ValueError:
            return False
    return True


def _identity_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    aware = _aware(value)
    assert aware is not None
    aware = aware.astimezone(timezone.utc)
    return aware.replace(microsecond=(aware.microsecond // 1000) * 1000)


def _migration_identity(document: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical full identity that a durable migration resume must preserve."""
    source = document.get("source") or {}
    destination = document.get("destination") or {}
    metadata = document.get("metadata") or {}
    source_ticket_id = metadata.get("source_ticket_id")
    return {
        "source.guild_id": _as_int(source.get("guild_id")),
        "source.channel_id": _as_int(source.get("channel_id")),
        "source.staff_thread_id": _as_int(source.get("staff_thread_id")) or None,
        "source.channel_name": str(source.get("channel_name") or ""),
        "source.ticket_number": _as_int(source.get("ticket_number")) or None,
        "destination.guild_id": _as_int(destination.get("guild_id")),
        "destination.candidate_parent_id": _as_int(
            destination.get("candidate_parent_id")
        ),
        "destination.staff_parent_id": _as_int(destination.get("staff_parent_id")),
        "metadata.ticket_type": str(metadata.get("ticket_type") or ""),
        "metadata.status": str(metadata.get("status") or ""),
        "metadata.user_id": _as_int(metadata.get("user_id")),
        "metadata.username": str(metadata.get("username") or ""),
        "metadata.display_name": str(metadata.get("display_name") or ""),
        "metadata.player_tags": tuple(str(item) for item in metadata.get("player_tags") or ()),
        "metadata.created_at": _identity_datetime(metadata.get("created_at")),
        "metadata.source_ticket_id": (
            str(source_ticket_id) if source_ticket_id is not None else None
        ),
        "metadata.source_ticket_rev": max(
            0, _as_int(metadata.get("source_ticket_rev"))
        ),
    }


def _matches_committed_location_replacement(
    migration: Mapping[str, Any], preview: LegacyMigrationPreview
) -> bool:
    """Prove that the sole rev change is this migration's committed replacement."""
    ticket = preview.source_ticket or {}
    metadata = migration.get("metadata") or {}
    destination = migration.get("destination") or {}
    expected_rev = max(0, _as_int(metadata.get("source_ticket_rev")))
    if (
        not metadata.get("source_ticket_id")
        or str(ticket.get("_id")) != str(metadata.get("source_ticket_id"))
        or ticket.get("venue") != "thread"
        or _as_int(ticket.get("rev")) != expected_rev + 1
    ):
        return False
    location = ticket.get("location") or {}
    source = ticket.get("source") or {}
    durable_source = migration.get("source") or {}
    if (
        _as_int(location.get("guild_id") or ticket.get("guild_id"))
        != _as_int(destination.get("guild_id"))
        or _as_int(location.get("id")) != _as_int(destination.get("public_thread_id"))
        or _as_int(location.get("staff_space_id"))
        != _as_int(destination.get("staff_thread_id"))
        or _as_int(location.get("public_parent_id"))
        != _as_int(destination.get("candidate_parent_id"))
        or _as_int(location.get("staff_parent_id"))
        != _as_int(destination.get("staff_parent_id"))
        or _as_int(source.get("guild_id")) != _as_int(durable_source.get("guild_id"))
        or _as_int(source.get("channel_id")) != _as_int(durable_source.get("channel_id"))
        or (_as_int(source.get("staff_thread_id")) or None)
        != (_as_int(durable_source.get("staff_thread_id")) or None)
    ):
        return False
    return any(
        item.get("event") == "legacy_location_replaced"
        and _as_int(item.get("rev_before")) == expected_rev
        and _as_int(item.get("rev_after")) == expected_rev + 1
        and _as_int(((item.get("to") or {}).get("location") or {}).get("id"))
        == _as_int(destination.get("public_thread_id"))
        and _as_int(
            ((item.get("to") or {}).get("location") or {}).get("staff_space_id")
        ) == _as_int(destination.get("staff_thread_id"))
        for item in ticket.get("audit") or []
        if isinstance(item, Mapping)
    )


def _matches_committed_new_ticket_insert(
    migration: Mapping[str, Any], preview: LegacyMigrationPreview
) -> bool:
    """Prove that a newly discovered row is this migration's committed insert."""
    ticket = preview.source_ticket or {}
    metadata = migration.get("metadata") or {}
    destination = migration.get("destination") or {}
    durable_source = migration.get("source") or {}
    public_thread_id = _as_int(destination.get("public_thread_id"))
    staff_thread_id = _as_int(destination.get("staff_thread_id"))
    if (
        metadata.get("source_ticket_id") is not None
        or not public_thread_id
        or not staff_thread_id
        or str(ticket.get("_id")) != f"ticket_{public_thread_id}"
        or ticket.get("type") != "ticket"
        or ticket.get("venue") != "thread"
        or _as_int(ticket.get("rev")) != 0
        or _as_int(ticket.get("ticket_number"))
        != _as_int(destination.get("ticket_number"))
    ):
        return False

    location = ticket.get("location") or {}
    source = ticket.get("source") or {}
    if (
        _as_int(location.get("guild_id") or ticket.get("guild_id"))
        != _as_int(destination.get("guild_id"))
        or _as_int(location.get("id")) != public_thread_id
        or _as_int(ticket.get("channel_id")) != public_thread_id
        or _as_int(location.get("staff_space_id")) != staff_thread_id
        or _as_int(ticket.get("thread_id")) != staff_thread_id
        or _as_int(location.get("public_parent_id"))
        != _as_int(destination.get("candidate_parent_id"))
        or _as_int(ticket.get("category_id"))
        != _as_int(destination.get("candidate_parent_id"))
        or _as_int(location.get("staff_parent_id"))
        != _as_int(destination.get("staff_parent_id"))
        or _as_int(source.get("guild_id")) != _as_int(durable_source.get("guild_id"))
        or _as_int(source.get("channel_id"))
        != _as_int(durable_source.get("channel_id"))
        or (_as_int(source.get("staff_thread_id")) or None)
        != (_as_int(durable_source.get("staff_thread_id")) or None)
        or str(source.get("channel_name") or "")
        != str(durable_source.get("channel_name") or "")
        or (_as_int(source.get("ticket_number")) or None)
        != (_as_int(durable_source.get("ticket_number")) or None)
    ):
        return False

    return any(
        item.get("event") == "legacy_ticket_imported"
        and _as_int(item.get("rev")) == 0
        and _as_int(item.get("actor")) == _as_int(metadata.get("user_id"))
        and str(item.get("status") or "") == str(metadata.get("status") or "")
        and _as_int((item.get("source") or {}).get("guild_id"))
        == _as_int(durable_source.get("guild_id"))
        and _as_int((item.get("source") or {}).get("channel_id"))
        == _as_int(durable_source.get("channel_id"))
        and (_as_int((item.get("source") or {}).get("staff_thread_id")) or None)
        == (_as_int(durable_source.get("staff_thread_id")) or None)
        and str((item.get("source") or {}).get("channel_name") or "")
        == str(durable_source.get("channel_name") or "")
        and (_as_int((item.get("source") or {}).get("ticket_number")) or None)
        == (_as_int(durable_source.get("ticket_number")) or None)
        for item in ticket.get("audit") or []
        if isinstance(item, Mapping)
    )


async def ensure_migration_indexes(mongo: MongoClient) -> None:
    global _migration_index_ready
    if _migration_index_ready:
        return
    # Migrations create canonical ticket rows; their uniqueness must be active
    # before any destination Discord resources are created.
    await thread_service.ensure_canonical_ticket_store(mongo)
    collection = mongo.ticket_migrations
    await collection.create_index(
        [("source.guild_id", 1), ("source.channel_id", 1)],
        unique=True,
        name="legacy_source_unique",
    )
    await collection.create_index(
        [("destination.public_thread_id", 1)],
        unique=True,
        partialFilterExpression={"destination.public_thread_id": {"$exists": True}},
        name="legacy_public_thread_unique",
    )
    await collection.create_index(
        [("destination.staff_thread_id", 1)],
        unique=True,
        partialFilterExpression={"destination.staff_thread_id": {"$exists": True}},
        name="legacy_staff_thread_unique",
    )
    await collection.create_index([("state", 1), ("updated_at", -1)], name="legacy_state")
    _migration_index_ready = True


async def _all_messages(rest: hikari.api.RESTClient, channel_id: int) -> list[Any]:
    messages = await thread_service._collect_rest_iterator(
        rest.fetch_messages(channel_id)
    )
    return sorted(messages, key=lambda item: int(item.id))


def _attachment_http_status(status: int) -> str:
    if 200 <= int(status) < 400:
        return "live"
    if int(status) in {401, 403, 404, 410}:
        return "unrecoverable"
    return "unknown"


async def _audit_attachment_urls(
    spaces: Sequence[tuple[int, Sequence[Any]]],
) -> tuple[AttachmentAuditResult, ...]:
    """Bounded, read-only CDN audit used by dry-run before any migration write."""
    pending: list[tuple[int, Any, Any]] = []
    for channel_id, messages in spaces:
        for message in messages:
            for attachment in getattr(message, "attachments", ()):
                pending.append((int(channel_id), message, attachment))
    if not pending:
        return ()

    selected = pending[:ATTACHMENT_AUDIT_LIMIT]
    overflow = pending[ATTACHMENT_AUDIT_LIMIT:]
    semaphore = asyncio.Semaphore(ATTACHMENT_AUDIT_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=ATTACHMENT_AUDIT_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def audit_one(channel_id: int, message: Any, attachment: Any) -> AttachmentAuditResult:
            filename = str(getattr(attachment, "filename", "attachment"))
            url = str(getattr(attachment, "url", "") or "")
            if not url:
                return AttachmentAuditResult(
                    channel_id, int(message.id), filename, "unknown"
                )
            try:
                async with semaphore:
                    async with session.get(
                        url,
                        headers={"Range": "bytes=0-0"},
                        allow_redirects=True,
                    ) as response:
                        await response.content.read(1)
                        http_status = int(response.status)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return AttachmentAuditResult(
                    channel_id, int(message.id), filename, "unknown"
                )
            return AttachmentAuditResult(
                channel_id,
                int(message.id),
                filename,
                _attachment_http_status(http_status),
                http_status,
            )

        results = list(await asyncio.gather(*(
            audit_one(channel_id, message, attachment)
            for channel_id, message, attachment in selected
        )))
    results.extend(
        AttachmentAuditResult(
            channel_id,
            int(message.id),
            str(getattr(attachment, "filename", "attachment")),
            "not_audited",
        )
        for channel_id, message, attachment in overflow
    )
    return tuple(results)


async def _legacy_source_ticket(
    mongo: MongoClient, source_guild_id: int, source_channel_id: int
) -> dict | None:
    ids = [int(source_channel_id), str(int(source_channel_id))]
    query = {
        "type": "ticket",
        "$or": [
            {"channel_id": {"$in": ids}},
            {"location.id": {"$in": ids}},
            {
                "source.guild_id": int(source_guild_id),
                "source.channel_id": int(source_channel_id),
            },
        ],
    }
    ticket_rows, legacy_rows = await asyncio.gather(
        mongo.tickets.find(query).limit(2).to_list(length=2),
        mongo.button_store.find(query).limit(2).to_list(length=2),
    )
    matches = [*ticket_rows, *legacy_rows]
    identities = {str(item.get("_id")) for item in matches}
    if len(identities) > 1:
        raise LegacyMigrationError(
            "conflicting source ticket records exist in canonical and legacy storage"
        )
    if not matches:
        return None
    active = await store.active_store(mongo)
    if active != store.STORE_TICKETS:
        raise LegacyMigrationError(
            "ticket storage is not ready; run `/ticket migrate-store` first"
        )
    if not ticket_rows and legacy_rows:
        raise LegacyMigrationError(
            "the source ticket exists only in legacy storage; run `/ticket migrate-store` first"
        )
    return ticket_rows[0]


async def _discover_staff_thread(
    rest: hikari.api.RESTClient,
    *,
    source_guild_id: int,
    source_channel_id: int,
    explicit_id: int | None,
    stored_id: int | None,
) -> Any | None:
    selected_id = _as_int(explicit_id) or _as_int(stored_id)
    if selected_id:
        thread = await rest.fetch_channel(selected_id)
        if _as_int(getattr(thread, "guild_id", 0)) != source_guild_id:
            raise LegacyMigrationError("source staff thread is in a different guild")
        if _as_int(getattr(thread, "parent_id", 0)) != source_channel_id:
            raise LegacyMigrationError("source staff thread is not under the source ticket channel")
        if getattr(thread, "type", None) != hikari.ChannelType.GUILD_PRIVATE_THREAD:
            raise LegacyMigrationError("source staff thread must be recruiter-only/private")
        return thread

    active = await rest.fetch_active_threads(source_guild_id)
    candidates = [
        item for item in active
        if _as_int(getattr(item, "parent_id", 0)) == source_channel_id
        and getattr(item, "type", None) == hikari.ChannelType.GUILD_PRIVATE_THREAD
    ]
    archived = await thread_service._collect_rest_iterator(
        rest.fetch_private_archived_threads(source_channel_id)
    )
    for item in archived:
        if all(_as_int(item.id) != _as_int(found.id) for found in candidates):
            candidates.append(item)
    if len(candidates) > 1:
        preferred = [item for item in candidates if str(getattr(item, "name", "")).startswith("private-")]
        if len(preferred) == 1:
            return preferred[0]
        raise LegacyMigrationError(
            "multiple recruiter-only source threads exist; select one with "
            "`source-staff-thread`"
        )
    return candidates[0] if candidates else None


def _infer_status(
    source_ticket: Mapping[str, Any] | None,
    channel_name: str,
    override: str | None,
) -> str:
    stored = str((source_ticket or {}).get("status") or "").casefold()
    selected = str(override or "").casefold()
    if stored in {"open", "new"}:
        raise LegacyTicketStillOpen("still-open legacy tickets cannot be migrated")
    if stored == "closed":
        if selected in {"approved", "denied"}:
            return selected
        raise LegacyMigrationError(
            "the stored status is closed; choose Approved or Denied explicitly"
        )
    if stored in {"approved", "denied"}:
        if selected in {"approved", "denied"}:
            return selected
        return stored
    if channel_name.casefold().startswith(("new", "🆕")):
        raise LegacyTicketStillOpen("still-open legacy tickets cannot be migrated")
    if selected in {"approved", "denied"}:
        return selected
    if channel_name.startswith("✅"):
        return "approved"
    if channel_name.startswith("❌"):
        return "denied"
    raise LegacyMigrationError(
        "the final outcome could not be detected; choose Approved or Denied"
    )


def _infer_ticket_type(
    source_ticket: Mapping[str, Any] | None, channel_name: str, override: str | None
) -> str:
    selected = str(override or "").casefold()
    if selected in {"main", "fwa"}:
        return selected
    stored = str((source_ticket or {}).get("ticket_type") or "").casefold()
    if stored in {"main", "fwa"}:
        return stored
    lowered = channel_name.casefold()
    for value in ("main", "fwa"):
        if value in lowered:
            return value
    raise LegacyMigrationError("the ticket type could not be detected; choose Main or FWA")


def _member_overwrite_ids(channel: Any, *, guild_id: int, bot_user_id: int) -> list[int]:
    overwrites = getattr(channel, "permission_overwrites", {}) or {}
    values = overwrites.values() if isinstance(overwrites, Mapping) else overwrites
    ids = []
    for item in values:
        if getattr(item, "type", None) != hikari.PermissionOverwriteType.MEMBER:
            continue
        value = _as_int(getattr(item, "id", 0))
        if value and value not in {guild_id, bot_user_id}:
            ids.append(value)
    return sorted(set(ids))


async def _identity(
    rest: hikari.api.RESTClient,
    *,
    source_ticket: Mapping[str, Any] | None,
    source_channel: Any,
    request: LegacyMigrationRequest,
    bot_user_id: int,
) -> tuple[int, str, str]:
    user_id = _as_int(request.user_id_override) or _as_int((source_ticket or {}).get("user_id"))
    if not user_id:
        candidates = _member_overwrite_ids(
            source_channel,
            guild_id=request.source_guild_id,
            bot_user_id=bot_user_id,
        )
        if len(candidates) == 1:
            user_id = candidates[0]
    if not user_id:
        raise LegacyMigrationError(
            "the candidate Discord ID could not be detected; enter it in `user-id`"
        )

    username = str(
        request.username_override or (source_ticket or {}).get("username") or ""
    ).strip()
    display_name = str((source_ticket or {}).get("display_name") or "").strip()
    if not username or not display_name:
        try:
            member = await rest.fetch_member(request.source_guild_id, user_id)
        except (hikari.NotFoundError, hikari.ForbiddenError):
            member = await rest.fetch_user(user_id)
        username = username or str(getattr(member, "username", ""))
        display_name = display_name or str(getattr(member, "display_name", "") or username)
    if not username:
        raise LegacyMigrationError("candidate username could not be resolved")
    return user_id, username[:32], (display_name or username)[:80]


def _original_ticket_number(source_ticket: Mapping[str, Any] | None, name: str) -> int | None:
    source = (source_ticket or {}).get("source") or {}
    if (source_ticket or {}).get("venue") == "thread":
        original = _as_int(source.get("ticket_number"))
        if original:
            return original
    stored = _as_int((source_ticket or {}).get("ticket_number"))
    if stored:
        return stored
    match = _TICKET_NUMBER_RE.search(name)
    return int(match.group(1)) if match else None


def _player_tags(
    source_ticket: Mapping[str, Any] | None,
    messages: Sequence[Any],
    overrides: Iterable[str],
    *,
    applicant_user_id: int,
) -> tuple[str, ...]:
    explicit = tuple(overrides)
    if any(str(value or "").strip() for value in explicit):
        return tuple(schema.player_tags(explicit))

    values: list[str] = []
    source = source_ticket or {}
    stored = source.get("player_tags")
    if isinstance(stored, str):
        values.append(stored)
    else:
        values.extend(stored or ())
    for field in ("player_tag", "tag"):
        if source.get(field):
            values.append(source[field])
    for message in messages:
        author_id = _as_int(getattr(getattr(message, "author", None), "id", 0))
        if author_id != applicant_user_id:
            continue
        values.extend(_PLAYER_TAG_RE.findall(getattr(message, "content", "") or ""))
    return tuple(schema.player_tags(values))


async def preview_legacy_ticket(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    request: LegacyMigrationRequest,
) -> LegacyMigrationPreview:
    """Read and validate a source ticket without writing Discord or Mongo."""
    me = bot.get_me()
    if me is None:
        raise LegacyMigrationError("bot identity is unavailable")
    await asyncio.gather(
        bot.rest.fetch_guild(request.source_guild_id),
        bot.rest.fetch_guild(request.target_guild_id),
    )
    source_channel = await bot.rest.fetch_channel(request.source_channel_id)
    if getattr(source_channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
        raise LegacyMigrationError("source must be a legacy guild text ticket channel")
    if _as_int(getattr(source_channel, "guild_id", 0)) != request.source_guild_id:
        raise LegacyMigrationError("source channel is not in the selected source guild")

    source_ticket = await _legacy_source_ticket(
        mongo, request.source_guild_id, request.source_channel_id
    )
    channel_name = str(getattr(source_channel, "name", "legacy-ticket"))
    status = _infer_status(source_ticket, channel_name, request.status_override)
    ticket_type = _infer_ticket_type(
        source_ticket, channel_name, request.ticket_type_override
    )
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))
    if not target_guild_id or target_guild_id != request.target_guild_id:
        raise LegacyMigrationError(
            "destination must be the configured thread-ticket target guild"
        )
    parents = _configured_destination(config, request, ticket_type)
    await thread_service.validate_thread_parents(
        bot.rest,
        parents,
        bot_user_id=int(me.id),
        require_webhooks=True,
    )

    source_staff = await _discover_staff_thread(
        bot.rest,
        source_guild_id=request.source_guild_id,
        source_channel_id=request.source_channel_id,
        explicit_id=request.source_staff_thread_id,
        stored_id=(
            _as_int(((source_ticket or {}).get("source") or {}).get("staff_thread_id"))
            if (source_ticket or {}).get("venue") == "thread"
            else _as_int((source_ticket or {}).get("thread_id"))
        ) or None,
    )
    public_messages = await _all_messages(bot.rest, request.source_channel_id)
    staff_messages = (
        await _all_messages(bot.rest, int(source_staff.id)) if source_staff is not None else []
    )
    user_id, username, display_name = await _identity(
        bot.rest,
        source_ticket=source_ticket,
        source_channel=source_channel,
        request=request,
        bot_user_id=int(me.id),
    )
    created_at = (source_ticket or {}).get("created_at")
    if not isinstance(created_at, datetime):
        created_at = hikari.Snowflake(request.source_channel_id).created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    all_messages = [*public_messages, *staff_messages]
    attachment_audit = await _audit_attachment_urls((
        (request.source_channel_id, public_messages),
        (
            int(source_staff.id) if source_staff is not None else 0,
            staff_messages,
        ),
    ))
    return LegacyMigrationPreview(
        request=request,
        source_channel=source_channel,
        source_staff_thread=source_staff,
        source_ticket=source_ticket,
        ticket_type=ticket_type,
        status=status,
        user_id=user_id,
        username=username,
        display_name=display_name,
        player_tags=_player_tags(
            source_ticket,
            all_messages,
            request.player_tags_override,
            applicant_user_id=user_id,
        ),
        created_at=created_at,
        original_ticket_number=_original_ticket_number(source_ticket, channel_name),
        public_message_count=len(public_messages),
        staff_message_count=len(staff_messages),
        attachment_count=sum(len(getattr(item, "attachments", ())) for item in all_messages),
        recruiter_role_id=parents.recruiter_role_id,
        attachment_audit=attachment_audit,
    )


async def _claim_migration(
    mongo: MongoClient,
    preview: LegacyMigrationPreview,
) -> tuple[str, dict, bool]:
    # Validate the exact preview-bound loss policy before any Mongo or Discord write.
    _require_attachment_ack(preview)
    collection = mongo.ticket_migrations
    request = preview.request
    migration_id = _migration_id(request.source_guild_id, request.source_channel_id)
    owner = uuid.uuid4().hex
    now = utcnow()
    current = await collection.find_one({"_id": migration_id})
    attachment_policy = _attachment_policy_for_claim(preview, current, now)
    await ensure_migration_indexes(mongo)

    immutable = {
        "kind": "legacy_thread_migration",
        "schema_version": 1,
        "source": {
            "guild_id": request.source_guild_id,
            "channel_id": request.source_channel_id,
            "staff_thread_id": (
                int(preview.source_staff_thread.id)
                if preview.source_staff_thread is not None
                else None
            ),
            "channel_name": str(preview.source_channel.name),
            "ticket_number": preview.original_ticket_number,
        },
        "destination": {
            "guild_id": request.target_guild_id,
            "candidate_parent_id": request.candidate_parent_id,
            "staff_parent_id": request.staff_parent_id,
        },
        "metadata": {
            "ticket_type": preview.ticket_type,
            "status": preview.status,
            "user_id": preview.user_id,
            "username": preview.username,
            "display_name": preview.display_name,
            "player_tags": list(preview.player_tags),
            "created_at": preview.created_at,
            "source_ticket_id": (
                preview.source_ticket.get("_id") if preview.source_ticket else None
            ),
            "source_ticket_rev": int((preview.source_ticket or {}).get("rev") or 0),
        },
    }
    if current:
        durable_identity = _migration_identity(current)
        preview_identity = _migration_identity(immutable)
        if _matches_committed_location_replacement(current, preview):
            # Preserve the originally confirmed revision. The +1 revision is
            # the already-committed location replacement this same migration
            # is resuming, not permission to accept unrelated source drift.
            preview_identity["metadata.source_ticket_rev"] = durable_identity[
                "metadata.source_ticket_rev"
            ]
        elif _matches_committed_new_ticket_insert(current, preview):
            # A no-record source becomes discoverable through source.* after
            # the canonical insert commits. Keep the originally confirmed
            # absence binding only when this exact deterministic row and pair
            # prove that they were created by this migration.
            preview_identity["metadata.source_ticket_id"] = durable_identity[
                "metadata.source_ticket_id"
            ]
        if durable_identity != preview_identity:
            raise LegacyMigrationError(
                "a migration for this source already exists with different source, "
                "destination, or applicant details"
            )
        if current.get("state") == "complete":
            return owner, current, True
        lease_until = _aware(current.get("lease_until"))
        if lease_until is not None and lease_until > now:
            raise LegacyMigrationBusy("this legacy ticket is already being migrated")
        claimed = await collection.find_one_and_update(
            {
                "_id": migration_id,
                "state": {"$ne": "complete"},
                "$or": [
                    {"lease_until": {"$lte": now}},
                    {"lease_until": {"$exists": False}},
                ],
            },
            {"$set": {
                "state": "resuming",
                "lease_owner": owner,
                "lease_until": now + MIGRATION_LEASE,
                "updated_at": now,
                "attachment_policy": attachment_policy,
            }},
            return_document=ReturnDocument.AFTER,
        )
        if claimed is None:
            raise LegacyMigrationBusy("this legacy ticket is already being migrated")
        return owner, claimed, True

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    bound_target = _as_int(config.get("ticket_target_guild_id"))
    if not bound_target or bound_target != request.target_guild_id:
        raise LegacyMigrationError(
            "legacy migration must use the configured ticket destination server"
        )
    if not config.get("legacy_migration_pilot_approved"):
        selected = await collection.count_documents({"kind": "legacy_thread_migration"})
        if selected >= PILOT_LIMIT:
            raise PilotLimitReached(
                "five pilot tickets are already selected; finish and verify them before "
                "enabling more migrations"
            )
        # Bring older deployments forward, then reserve one of five global
        # pilot slots atomically. A failed insert may consume a slot, which is
        # deliberately fail-safe and can never permit a sixth pilot source.
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$max": {"legacy_migration_pilot_slots_reserved": selected}},
        )
        reservation = await mongo.ticket_setup.find_one_and_update(
            {
                "_id": "config",
                "legacy_migration_pilot_approved": {"$ne": True},
                "$or": [
                    {"legacy_migration_pilot_slots_reserved": {"$lt": PILOT_LIMIT}},
                    {"legacy_migration_pilot_slots_reserved": {"$exists": False}},
                ],
            },
            {"$inc": {"legacy_migration_pilot_slots_reserved": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if reservation is None:
            latest = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
            if not latest.get("legacy_migration_pilot_approved"):
                raise PilotLimitReached(
                    "five pilot tickets are already selected; finish and verify them before "
                    "enabling more migrations"
                )
    document = {
        "_id": migration_id,
        **immutable,
        "state": "creating",
        "progress": {
            "public": {"last_source_message_id": None, "copied": 0, "losses": []},
            "staff": {"last_source_message_id": None, "copied": 0, "losses": []},
        },
        "attachment_policy": attachment_policy,
        "lease_owner": owner,
        "lease_until": now + MIGRATION_LEASE,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await collection.insert_one(document)
    except DuplicateKeyError as error:
        raise LegacyMigrationBusy("this legacy ticket is already being migrated") from error
    return owner, document, False


async def _migration_update(
    mongo: MongoClient,
    migration_id: str,
    owner: str,
    fields: Mapping[str, Any],
) -> dict:
    now = utcnow()
    doc = await mongo.ticket_migrations.find_one_and_update(
        {"_id": migration_id, "lease_owner": owner, "state": {"$ne": "complete"}},
        {"$set": {**fields, "updated_at": now, "lease_until": now + MIGRATION_LEASE}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise LegacyMigrationBusy("legacy migration lease was lost")
    return doc


def _migration_thread_names(
    ticket_type: str, ticket_number: int, username: str
) -> tuple[str, str]:
    # Migrated pairs intentionally match all future pairs. Their source identity
    # lives in Mongo, not in a one-off Discord naming convention.
    return thread_service.thread_names(ticket_type, ticket_number, username)


async def _quarantine_incomplete_migration_threads(
    rest: hikari.api.RESTClient,
    threads: Iterable[Any | None],
) -> None:
    """Best-effort quarantine of destination-only migration threads."""
    for thread in threads:
        if thread is None:
            continue
        try:
            await rest.edit_channel(
                thread.id,
                locked=True,
                archived=True,
                reason="Quarantining interrupted legacy migration for resume",
            )
        except Exception:
            _log.exception("failed to quarantine migration thread %s", thread.id)


async def _ensure_destination_pair(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    state: dict,
    owner: str,
) -> tuple[Any, Any, dict]:
    me = bot.get_me()
    if me is None:
        raise LegacyMigrationError("bot identity is unavailable")
    bot_user_id = int(me.id)
    migration_id = state["_id"]
    number = _as_int((state.get("destination") or {}).get("ticket_number"))
    if not number:
        number = await thread_service.reserve_ticket_number(
            mongo, state["metadata"]["ticket_type"]
        )
        public_name, staff_name = _migration_thread_names(
            state["metadata"]["ticket_type"], number, state["metadata"]["username"]
        )
        state = await _migration_update(mongo, migration_id, owner, {
            "destination.ticket_number": number,
            "destination.public_name": public_name,
            "destination.staff_name": staff_name,
            "state": "creating_threads",
        })
    destination = state["destination"]
    public_name = destination["public_name"]
    staff_name = destination["staff_name"]
    public = staff = None
    try:
        public = await thread_service._fetch_or_recover_thread(
            bot.rest,
            thread_id=_as_int(destination.get("public_thread_id")),
            guild_id=destination["guild_id"],
            parent_id=destination["candidate_parent_id"],
            name=public_name,
            private=True,
            expected_owner_id=bot_user_id,
        )
        if public is None:
            public = await bot.rest.create_thread(
                destination["candidate_parent_id"],
                hikari.ChannelType.GUILD_PRIVATE_THREAD,
                public_name,
                auto_archive_duration=thread_service.AUTO_ARCHIVE_MINUTES,
                invitable=False,
                reason=f"Legacy ticket migration {migration_id}",
            )
        public = await thread_service._unarchive_if_needed(bot.rest, public)
        state = await _migration_update(mongo, migration_id, owner, {
            "destination.public_thread_id": int(public.id),
        })
        destination = state["destination"]

        staff = await thread_service._fetch_or_recover_thread(
            bot.rest,
            thread_id=_as_int(destination.get("staff_thread_id")),
            guild_id=destination["guild_id"],
            parent_id=destination["staff_parent_id"],
            name=staff_name,
            private=False,
            expected_owner_id=bot_user_id,
        )
        if staff is None:
            staff = await bot.rest.create_thread(
                destination["staff_parent_id"],
                hikari.ChannelType.GUILD_PUBLIC_THREAD,
                staff_name,
                auto_archive_duration=thread_service.AUTO_ARCHIVE_MINUTES,
                reason=f"Legacy staff migration {migration_id}",
            )
        staff = await thread_service._unarchive_if_needed(bot.rest, staff)
        state = await _migration_update(mongo, migration_id, owner, {
            "destination.staff_thread_id": int(staff.id),
            "state": "copying",
        })
        return public, staff, state
    except asyncio.CancelledError:
        await _quarantine_incomplete_migration_threads(bot.rest, (public, staff))
        raise
    except Exception:
        await _quarantine_incomplete_migration_threads(bot.rest, (public, staff))
        raise


def _safe_webhook_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9 _-]+", "-", value).strip()
    return (value or "WU ticket migration")[:80]


async def _temporary_webhook(
    rest: hikari.api.RESTClient, parent_id: int, migration_id: str, space: str
) -> Any:
    name = _safe_webhook_name(f"WU migration {migration_id[-16:]} {space}")
    for webhook in await rest.fetch_channel_webhooks(parent_id):
        if str(getattr(webhook, "name", "")) == name:
            await rest.delete_webhook(webhook.id, reason="Removing stale migration webhook")
    webhook = await rest.create_webhook(
        parent_id, name, reason=f"Temporary webhook for {migration_id}"
    )
    if not getattr(webhook, "token", None):
        await rest.delete_webhook(webhook.id, reason="Unusable migration webhook")
        raise LegacyMigrationError("Discord did not return a token for the migration webhook")
    return webhook


def _plain_mentions(
    content: str,
    message: Any,
    role_names: Mapping[int, str],
    channel_names: Mapping[int, str],
) -> str:
    users = {
        _as_int(key): str(getattr(user, "display_name", None) or getattr(user, "username", "user"))
        for key, user in (getattr(message, "user_mentions", {}) or {}).items()
    }
    content = re.sub(
        r"<@!?(\d+)>",
        lambda match: "@" + users.get(int(match.group(1)), f"user-{match.group(1)}"),
        content,
    )
    content = re.sub(
        r"<@&(\d+)>",
        lambda match: "@" + role_names.get(int(match.group(1)), f"role-{match.group(1)}"),
        content,
    )
    content = re.sub(
        r"<#(\d+)>",
        lambda match: "#" + channel_names.get(int(match.group(1)), f"channel-{match.group(1)}"),
        content,
    )
    return re.sub(r"@(everyone|here)\b", lambda match: "@\u200b" + match.group(1), content)


def _author_name(message: Any) -> str:
    author = message.author
    name = str(getattr(author, "display_name", None) or getattr(author, "username", "Unknown user"))
    if name.casefold() == "clyde":
        name += " (original)"
    return name[:80]


def _author_avatar(message: Any) -> str | None:
    value = getattr(message.author, "display_avatar_url", None)
    return str(value) if value else None


def _message_parts(
    *,
    content: str,
    source_guild_id: int,
    source_channel_id: int,
    source_message_id: int,
    timestamp: datetime,
) -> list[tuple[str, str]]:
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    base_marker = (
        f"{SOURCE_MARKER_PREFIX}:{source_guild_id}:{source_channel_id}:{source_message_id}"
    )
    content = content or "[Original message had no text content]"
    # Reserve space for the visible original timestamp and durable replay marker.
    first_prefix = f"-# Originally sent {stamp}\n"
    reserve = max(len(first_prefix), 80) + len(base_marker) + 32
    width = max(200, 2000 - reserve)
    raw_parts = [content[index:index + width] for index in range(0, len(content), width)] or [""]
    total = len(raw_parts)
    parts: list[tuple[str, str]] = []
    for index, value in enumerate(raw_parts, start=1):
        marker = f"{base_marker}:{index}/{total}"
        prefix = first_prefix if index == 1 else f"-# Continued from original message {source_message_id}\n"
        parts.append((marker, f"{prefix}{value}\n-# {marker}"))
    return parts


async def _destination_has_marker(
    rest: hikari.api.RESTClient, thread_id: int, marker: str
) -> bool:
    messages = await thread_service._collect_rest_iterator(
        rest.fetch_messages(thread_id)
    )
    return any(marker in (getattr(item, "content", "") or "") for item in messages)


async def _destination_markers(
    rest: hikari.api.RESTClient, thread_id: int
) -> set[str]:
    """Load all durable clone identities once; never rely on Discord's last 100."""
    messages = await thread_service._collect_rest_iterator(
        rest.fetch_messages(thread_id)
    )
    pattern = re.compile(
        rf"{re.escape(SOURCE_MARKER_PREFIX)}:\d+:\d+:\d+:\d+/\d+"
    )
    markers: set[str] = set()
    for item in messages:
        markers.update(pattern.findall(getattr(item, "content", "") or ""))
    return markers


async def _execute_clone_part(
    *,
    rest: hikari.api.RESTClient,
    webhook: Any,
    thread_id: int,
    marker: str,
    content: str,
    message: Any,
    include_payload: bool,
    allow_payload_loss: bool = False,
    known_markers: set[str] | None = None,
) -> list[str]:
    already_copied = (
        marker in known_markers
        if known_markers is not None
        else await _destination_has_marker(rest, thread_id, marker)
    )
    if already_copied:
        return []
    attachments = list(getattr(message, "attachments", ())) if include_payload else []
    embeds = list(getattr(message, "embeds", ())) if include_payload else []
    kwargs = {
        "thread": thread_id,
        "username": _author_name(message),
        "attachments": attachments,
        "embeds": embeds,
        "mentions_everyone": False,
        "user_mentions": False,
        "role_mentions": False,
        "flags": hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
    }
    avatar_url = _author_avatar(message)
    if avatar_url is not None:
        kwargs["avatar_url"] = avatar_url
    try:
        await rest.execute_webhook(webhook.id, webhook.token, content, **kwargs)
        if known_markers is not None:
            known_markers.add(marker)
        return []
    except Exception as error:
        # A response may be lost after Discord commits. Reconcile before any retry.
        if await _destination_has_marker(rest, thread_id, marker):
            if known_markers is not None:
                known_markers.add(marker)
            return []
        if not attachments and not embeds:
            raise
        # Never turn transient Discord/network failures into accepted loss.
        # A text-only note is allowed only after an operator explicitly binds
        # the current attachment manifest to this durable migration.
        unavailable_http = (
            isinstance(error, aiohttp.ClientResponseError)
            and int(error.status) in {400, 401, 403, 404, 410, 413, 415, 422}
        )
        if not (
            isinstance(error, (FileNotFoundError, hikari.BadRequestError))
            or unavailable_http
        ):
            raise
        if not attachments or not allow_payload_loss:
            raise LegacyMigrationError(
                "an attachment could not be copied, so this source message remains pending. "
                "Run a new dry run. If you accept the listed loss, copy its exact token "
                "into `attachment-ack` and confirm again"
            ) from error
        losses = [str(getattr(item, "filename", "attachment")) for item in attachments]
        loss_prefix = "\n-# Unavailable during migration: "
        marker_suffix = f"\n-# {marker}"
        loss_budget = (
            DISCORD_MESSAGE_CONTENT_LIMIT - len(loss_prefix) - len(marker_suffix)
        )
        displayed_losses = _bounded_display_join(
            losses,
            limit=loss_budget,
            noun="filename",
        )
        suffix = loss_prefix + displayed_losses + marker_suffix
        without_marker = content.rsplit(f"\n-# {marker}", 1)[0]
        note = without_marker[
            : max(0, DISCORD_MESSAGE_CONTENT_LIMIT - len(suffix))
        ] + suffix
        fallback_kwargs = {
            "thread": thread_id,
            "username": _author_name(message),
            "embeds": embeds,
            "mentions_everyone": False,
            "user_mentions": False,
            "role_mentions": False,
            "flags": hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
        }
        if avatar_url is not None:
            fallback_kwargs["avatar_url"] = avatar_url
        await rest.execute_webhook(
            webhook.id, webhook.token, note, **fallback_kwargs
        )
        if known_markers is not None:
            known_markers.add(marker)
        return losses


async def _copy_space(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    state: dict,
    owner: str,
    space: str,
    source_channel_id: int | None,
    destination_thread_id: int,
    webhook: Any,
    role_names: Mapping[int, str],
    channel_names: Mapping[int, str],
) -> dict:
    if not source_channel_id:
        return state
    progress = (state.get("progress") or {}).get(space) or {}
    checkpoint = _as_int(progress.get("last_source_message_id"))
    copied = int(progress.get("copied") or 0)
    losses = list(progress.get("losses") or [])
    messages = await _all_messages(bot.rest, source_channel_id)
    known_markers = await _destination_markers(bot.rest, destination_thread_id)
    for message in messages:
        if int(message.id) <= checkpoint:
            continue
        sanitized = _plain_mentions(
            getattr(message, "content", "") or "",
            message,
            role_names,
            channel_names,
        )
        parts = _message_parts(
            content=sanitized,
            source_guild_id=state["source"]["guild_id"],
            source_channel_id=source_channel_id,
            source_message_id=int(message.id),
            timestamp=message.timestamp,
        )
        message_losses: list[str] = []
        for index, (marker, content) in enumerate(parts):
            message_losses.extend(await _execute_clone_part(
                rest=bot.rest,
                webhook=webhook,
                thread_id=destination_thread_id,
                marker=marker,
                content=content,
                message=message,
                include_payload=index == 0,
                allow_payload_loss=(
                    index == 0
                    and _message_payload_loss_is_accepted(
                        state, source_channel_id, message
                    )
                ),
                known_markers=known_markers,
            ))
        copied += 1
        if message_losses and len(losses) < 50:
            losses.append({"message_id": int(message.id), "items": message_losses[:10]})
        state = await _migration_update(mongo, state["_id"], owner, {
            f"progress.{space}.last_source_message_id": int(message.id),
            f"progress.{space}.copied": copied,
            f"progress.{space}.losses": losses,
            "state": f"copying_{space}",
        })
    return state


async def _delete_webhook_safely(rest: hikari.api.RESTClient, webhook: Any | None) -> None:
    if webhook is None:
        return
    try:
        await rest.delete_webhook(webhook.id, reason="Legacy ticket copy complete")
    except hikari.NotFoundError:
        return


async def _cleanup_interrupted_migration(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    state: Mapping[str, Any],
    owner: str,
    threads: Iterable[Any | None],
    webhooks: Iterable[Any | None],
    error: BaseException,
) -> None:
    """Clean destination resources and release one resumable migration lease."""
    webhook_list = tuple(webhooks)
    results = await asyncio.gather(
        *(_delete_webhook_safely(bot.rest, webhook) for webhook in webhook_list),
        return_exceptions=True,
    )
    for webhook, result in zip(webhook_list, results):
        if webhook is not None and isinstance(result, BaseException):
            _log.error(
                "failed to delete migration webhook %s after %s",
                getattr(webhook, "id", "unknown"),
                type(result).__name__,
            )
    await _quarantine_incomplete_migration_threads(bot.rest, threads)
    try:
        await mongo.ticket_migrations.update_one(
            {"_id": state["_id"], "lease_owner": owner},
            {
                "$set": {
                    "state": "retry",
                    "last_error": type(error).__name__,
                    "updated_at": utcnow(),
                },
                "$unset": {"lease_owner": "", "lease_until": "", "webhooks": ""},
            },
        )
    except Exception:
        _log.exception("failed to release interrupted legacy migration %s", state.get("_id"))


async def migrate_legacy_ticket(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    preview: LegacyMigrationPreview,
) -> LegacyMigrationResult:
    """Clone one validated terminal source and archive its thread pair."""
    owner, state, resumed = await _claim_migration(mongo, preview)
    if state.get("state") == "complete":
        ticket_doc = await store.find_one(mongo, {"_id": state["ticket_id"]})
        if ticket_doc is None:
            raise LegacyMigrationError("completed migration has no ticket record")
        await thread_service._queue_staff_context_outbox(mongo, ticket_doc)
        return LegacyMigrationResult(ticket_doc, state, resumed=True)

    public = staff = None
    public_webhook = staff_webhook = None
    try:
        public, staff, state = await _ensure_destination_pair(bot, mongo, state, owner)
        destination = state["destination"]
        public_webhook = await _temporary_webhook(
            bot.rest, destination["candidate_parent_id"], state["_id"], "public"
        )
        staff_webhook = await _temporary_webhook(
            bot.rest, destination["staff_parent_id"], state["_id"], "staff"
        )
        state = await _migration_update(mongo, state["_id"], owner, {
            "webhooks.public_id": int(public_webhook.id),
            "webhooks.staff_id": int(staff_webhook.id),
        })
        roles, channels = await asyncio.gather(
            bot.rest.fetch_roles(preview.request.source_guild_id),
            bot.rest.fetch_guild_channels(preview.request.source_guild_id),
        )
        role_names = {int(item.id): str(item.name) for item in roles}
        channel_names = {int(item.id): str(item.name) for item in channels}
        state = await _copy_space(
            bot=bot,
            mongo=mongo,
            state=state,
            owner=owner,
            space="public",
            source_channel_id=preview.request.source_channel_id,
            destination_thread_id=int(public.id),
            webhook=public_webhook,
            role_names=role_names,
            channel_names=channel_names,
        )
        state = await _copy_space(
            bot=bot,
            mongo=mongo,
            state=state,
            owner=owner,
            space="staff",
            source_channel_id=(
                int(preview.source_staff_thread.id)
                if preview.source_staff_thread is not None
                else None
            ),
            destination_thread_id=int(staff.id),
            webhook=staff_webhook,
            role_names=role_names,
            channel_names=channel_names,
        )
        if preview.source_staff_thread is None:
            marker = f"legacy-staff-seed:{state['_id']}"
            await thread_service._send_once(
                bot.rest,
                int(staff.id),
                marker,
                (
                    f"Migrated from #{preview.source_channel.name}. The source ticket had no "
                    "recruiter-only thread history."
                ),
            )

        await asyncio.gather(
            _delete_webhook_safely(bot.rest, public_webhook),
            _delete_webhook_safely(bot.rest, staff_webhook),
        )
        public_webhook = staff_webhook = None
        # The claimed state, not a fresh preview, is authoritative on resume.
        # `_claim_migration` has already compared the complete immutable identity.
        metadata = state["metadata"]
        destination = state["destination"]
        source = {
            key: state["source"].get(key)
            for key in (
                "guild_id", "channel_id", "staff_thread_id", "channel_name",
                "ticket_number",
            )
        }
        canonical = store.new_ticket_document(
            ticket_type=metadata["ticket_type"],
            ticket_number=int(destination["ticket_number"]),
            guild_id=destination["guild_id"],
            public_thread_id=int(public.id),
            public_parent_id=destination["candidate_parent_id"],
            staff_thread_id=int(staff.id),
            staff_parent_id=destination["staff_parent_id"],
            user_id=metadata["user_id"],
            username=metadata["username"],
            display_name=metadata["display_name"],
            player_tags=metadata["player_tags"],
            created_at=metadata["created_at"],
            status=metadata["status"],
            source=source,
        )
        if preview.source_ticket is not None:
            transition = await store.replace_legacy_location(
                mongo,
                preview.source_ticket["_id"],
                canonical,
                expected_rev=int(preview.source_ticket.get("rev") or 0),
            )
            if not transition.won or transition.doc is None:
                raise LegacyMigrationError(
                    transition.reason or "source ticket changed during migration"
                )
            ticket_doc = transition.doc
        else:
            ticket_doc = await store.insert_one(mongo, canonical)
        # The durable context outbox is a required pre-completion boundary.
        # Delivery remains best-effort while this terminal pair is still active.
        await thread_service._queue_staff_context_outbox(mongo, ticket_doc)
        await thread_service.notify_console_after_change(
            bot, mongo, ticket_doc, reason="legacy ticket migrated"
        )
        await thread_service.archive_ticket_pair(bot.rest, ticket_doc)
        now = utcnow()
        completed = await mongo.ticket_migrations.find_one_and_update(
            {"_id": state["_id"], "lease_owner": owner},
            {
                "$set": {
                    "state": "complete",
                    "ticket_id": ticket_doc["_id"],
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {
                    "lease_owner": "",
                    "lease_until": "",
                    "last_error": "",
                    "webhooks": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if completed is None:
            raise LegacyMigrationBusy("migration completion lease was lost")
        return LegacyMigrationResult(ticket_doc, completed, resumed=resumed)
    except asyncio.CancelledError as error:
        await _cleanup_interrupted_migration(
            bot=bot,
            mongo=mongo,
            state=state,
            owner=owner,
            threads=(public, staff),
            webhooks=(public_webhook, staff_webhook),
            error=error,
        )
        raise
    except Exception as error:
        await _cleanup_interrupted_migration(
            bot=bot,
            mongo=mongo,
            state=state,
            owner=owner,
            threads=(public, staff),
            webhooks=(public_webhook, staff_webhook),
            error=error,
        )
        raise


async def recover_pending_legacy_migrations(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    limit: int = PILOT_LIMIT,
) -> dict[str, int]:
    """Resume only previously confirmed migrations whose durable lease expired."""
    await ensure_migration_indexes(mongo)
    amount = max(1, min(int(limit), 25))
    now = utcnow()
    cursor = mongo.ticket_migrations.find({
        "kind": "legacy_thread_migration",
        "state": {"$ne": "complete"},
        "$or": [
            {"lease_until": {"$lte": now}},
            {"lease_until": {"$exists": False}},
        ],
    })
    pending = await cursor.sort("updated_at", 1).limit(amount).to_list(length=amount)
    counts = {"processed": 0, "completed": 0, "failed": 0}
    for state in pending:
        counts["processed"] += 1
        source = state.get("source") or {}
        destination = state.get("destination") or {}
        metadata = state.get("metadata") or {}
        attachment_policy = state.get("attachment_policy") or {}
        request = LegacyMigrationRequest(
            source_guild_id=_as_int(source.get("guild_id")),
            source_channel_id=_as_int(source.get("channel_id")),
            source_staff_thread_id=_as_int(source.get("staff_thread_id")) or None,
            target_guild_id=_as_int(destination.get("guild_id")),
            candidate_parent_id=_as_int(destination.get("candidate_parent_id")),
            staff_parent_id=_as_int(destination.get("staff_parent_id")),
            ticket_type_override=str(metadata.get("ticket_type") or "") or None,
            status_override=str(metadata.get("status") or "") or None,
            user_id_override=_as_int(metadata.get("user_id")) or None,
            username_override=str(metadata.get("username") or "") or None,
            player_tags_override=tuple(metadata.get("player_tags") or ()),
            attachment_ack=(
                str(attachment_policy.get("token") or "") or None
                if attachment_policy.get("accepted")
                else None
            ),
            attachment_ack_actor_id=(
                _as_int(attachment_policy.get("accepted_by")) or None
            ),
            attachment_ack_actor_name=(
                str(attachment_policy.get("accepted_by_name") or "") or None
            ),
        )
        try:
            preview = await preview_legacy_ticket(bot=bot, mongo=mongo, request=request)
            await migrate_legacy_ticket(bot=bot, mongo=mongo, preview=preview)
        except Exception:
            counts["failed"] += 1
            _log.exception("startup legacy migration recovery failed for %s", state.get("_id"))
        else:
            counts["completed"] += 1
    return counts


def _numeric(value: str | None, field: str, *, optional: bool = False) -> int | None:
    value = str(value or "").strip()
    if optional and not value:
        return None
    if not value.isdecimal() or not 17 <= len(value) <= 20:
        raise LegacyMigrationError(f"{field} must be a valid Discord ID")
    return int(value)


def _attachment_audit_summary(preview: LegacyMigrationPreview) -> str:
    audit = preview.attachment_audit
    live = sum(item.status == "live" for item in audit)
    dead = [item for item in audit if item.status == "unrecoverable"]
    unknown = sum(item.status in {"unknown", "not_audited"} for item in audit)
    unknown += abs(max(0, int(preview.attachment_count)) - len(audit))
    line = (
        f"**Attachment check:** available `{live}`, cannot be copied `{len(dead)}`, "
        f"unknown or not checked `{unknown}`"
    )
    if dead:
        details = ", ".join(
            f"`{item.source_message_id}:{item.filename[:36]}`"
            for item in dead[:5]
        )
        line += f"\n**Cannot be copied:** {details}"
        if len(dead) > 5:
            line += f" +{len(dead) - 5} more"
    token = _attachment_ack_token(preview)
    if _attachment_risk_manifest(preview):
        line += (
            f"\n**Attachment risk acceptance required:** `{token}` — if you accept every "
            "listed risk, copy this exact token into `attachment-ack`."
        )
    elif token:
        line += (
            "\n**Attachment risk acceptance:** not required. If a later attempt reports "
            "a risk, run a new preview and follow its instructions."
        )
    return line


def _migration_summary(preview: LegacyMigrationPreview) -> str:
    """Build a bounded operator summary while retaining all preview metadata."""
    request = preview.request
    before_tags = (
        f"**Source:** `{request.source_guild_id}` / "
        f"`#{preview.source_channel.name}` (`{request.source_channel_id}`)\n"
        f"**Outcome:** `{preview.status}` • `{preview.ticket_type}` • <@{preview.user_id}>\n"
        f"**Messages:** candidate `{preview.public_message_count}`, "
        f"staff `{preview.staff_message_count}`\n"
        f"**Attachments:** `{preview.attachment_count}` • **Tags:** `"
    )
    after_tags = "`\n" + _attachment_audit_summary(preview)
    tag_budget = MIGRATION_SUMMARY_LIMIT - len(before_tags) - len(after_tags)
    tag_display = (
        _bounded_display_join(preview.player_tags, limit=tag_budget, noun="tag")
        if preview.player_tags else "none found"
    )
    return before_tags + tag_display + after_tags


def _option_value(ctx: lightbulb.AutocompleteContext[str], name: str) -> str:
    option = ctx.get_option(name)
    return str(option.value or "") if option is not None else ""


async def _guild_administrator(
    rest: hikari.api.RESTClient,
    guild_id: int,
    user_id: int,
) -> bool:
    """Verify owner/Administrator from REST data in the selected guild."""
    try:
        guild, member, roles = await asyncio.gather(
            rest.fetch_guild(int(guild_id)),
            rest.fetch_member(int(guild_id), int(user_id)),
            rest.fetch_roles(int(guild_id)),
        )
    except (hikari.NotFoundError, hikari.ForbiddenError):
        return False
    if _as_int(getattr(guild, "owner_id", 0)) == int(user_id):
        return True
    role_ids = {_as_int(value) for value in getattr(member, "role_ids", ())}
    role_ids.add(int(guild_id))
    permissions = hikari.Permissions.NONE
    for role in roles:
        if _as_int(getattr(role, "id", 0)) in role_ids:
            permissions |= hikari.Permissions(getattr(role, "permissions", 0))
    return bool(permissions & hikari.Permissions.ADMINISTRATOR)


def _autocomplete_operator(ctx: lightbulb.AutocompleteContext[str]) -> tuple[int, int] | None:
    interaction = ctx.interaction
    member = getattr(interaction, "member", None)
    guild_id = _as_int(getattr(interaction, "guild_id", 0))
    user_id = _as_int(getattr(getattr(interaction, "user", None), "id", 0))
    if (
        not guild_id
        or not user_id
        or member is None
        or not getattr(member, "permissions", hikari.Permissions.NONE)
        & hikari.Permissions.ADMINISTRATOR
    ):
        return None
    return guild_id, user_id


async def _guild_choices(ctx: lightbulb.AutocompleteContext[str]) -> None:
    operator = _autocomplete_operator(ctx)
    if operator is None:
        await ctx.respond([])
        return
    _operator_guild_id, actor_id = operator
    app = ctx.client.app
    query = str(ctx.focused.value or "").casefold()
    guilds = []
    cache = getattr(app, "cache", None)
    if cache is not None:
        guilds = list(cache.get_available_guilds_view().values())
    if not guilds:
        guilds = await thread_service._collect_rest_iterator(
            app.rest.fetch_my_guilds().limit(200)
        )
    matching = [
        guild for guild in guilds
        if query in str(guild.name).casefold() or query in str(guild.id)
    ][:25]
    authorized = await asyncio.gather(*(
        _guild_administrator(app.rest, int(guild.id), actor_id)
        for guild in matching
    ))
    choices = [
        (f"{guild.name} — {guild.id}"[:100], str(guild.id))
        for guild, allowed in zip(matching, authorized)
        if allowed
    ][:25]
    await ctx.respond(choices)


async def _channel_choices(
    ctx: lightbulb.AutocompleteContext[str], guild_option: str
) -> None:
    operator = _autocomplete_operator(ctx)
    if operator is None:
        await ctx.respond([])
        return
    _operator_guild_id, actor_id = operator
    guild_id = _as_int(_option_value(ctx, guild_option))
    if not guild_id or not await _guild_administrator(
        ctx.client.app.rest, guild_id, actor_id
    ):
        await ctx.respond([])
        return
    query = str(ctx.focused.value or "").casefold()
    channels = await ctx.client.app.rest.fetch_guild_channels(guild_id)
    choices = [
        (f"#{channel.name} — {channel.id}"[:100], str(channel.id))
        for channel in channels
        if getattr(channel, "type", None) == hikari.ChannelType.GUILD_TEXT
        and (query in str(channel.name).casefold() or query in str(channel.id))
    ][:25]
    await ctx.respond(choices)


async def _source_channel_choices(ctx: lightbulb.AutocompleteContext[str]) -> None:
    await _channel_choices(ctx, "source-guild")


async def _configured_parent_choices(
    ctx: lightbulb.AutocompleteContext[str],
    mongo: MongoClient,
    *,
    field: str,
) -> None:
    operator = _autocomplete_operator(ctx)
    if operator is None:
        await ctx.respond([])
        return
    _operator_guild_id, actor_id = operator
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    bound_guild_id = _as_int(config.get("ticket_target_guild_id"))
    selected_guild_id = _as_int(_option_value(ctx, "target-guild"))
    guild_id = selected_guild_id or bound_guild_id
    if (
        not guild_id
        or guild_id != bound_guild_id
        or not await _guild_administrator(ctx.client.app.rest, guild_id, actor_id)
    ):
        await ctx.respond([])
        return

    configured: dict[int, list[str]] = {}
    for ticket_type, label in (("main", "Main"), ("fwa", "FWA")):
        channel_id = _as_int(config.get(f"{ticket_type}_{field}"))
        if channel_id:
            configured.setdefault(channel_id, []).append(label)
    query = str(ctx.focused.value or "").casefold()
    choices: list[tuple[str, str]] = []
    for channel_id, labels in configured.items():
        try:
            channel = await ctx.client.app.rest.fetch_channel(channel_id)
        except (hikari.NotFoundError, hikari.ForbiddenError):
            continue
        if (
            _as_int(getattr(channel, "guild_id", 0)) != guild_id
            or getattr(channel, "type", None) != hikari.ChannelType.GUILD_TEXT
        ):
            continue
        name = str(getattr(channel, "name", channel_id))
        display = f"{'/'.join(labels)}: #{name} — {channel_id}"
        if query in display.casefold() or query in str(channel_id):
            choices.append((display[:100], str(channel_id)))
    await ctx.respond(choices[:25])


@lightbulb.di.with_di
async def _candidate_parent_choices(
    ctx: lightbulb.AutocompleteContext[str],
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    await _configured_parent_choices(ctx, mongo, field="candidate_parent")


@lightbulb.di.with_di
async def _staff_parent_choices(
    ctx: lightbulb.AutocompleteContext[str],
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    await _configured_parent_choices(ctx, mongo, field="staff_parent")


async def _source_staff_choices(ctx: lightbulb.AutocompleteContext[str]) -> None:
    operator = _autocomplete_operator(ctx)
    if operator is None:
        await ctx.respond([])
        return
    _operator_guild_id, actor_id = operator
    guild_id = _as_int(_option_value(ctx, "source-guild"))
    channel_id = _as_int(_option_value(ctx, "source-channel"))
    if (
        not guild_id
        or not channel_id
        or not await _guild_administrator(ctx.client.app.rest, guild_id, actor_id)
    ):
        await ctx.respond([])
        return
    query = str(ctx.focused.value or "").casefold()
    active = await ctx.client.app.rest.fetch_active_threads(guild_id)
    archived = await thread_service._collect_rest_iterator(
        ctx.client.app.rest.fetch_private_archived_threads(channel_id).limit(100)
    )
    threads = [
        item for item in [*active, *archived]
        if _as_int(getattr(item, "parent_id", 0)) == channel_id
        and getattr(item, "type", None) == hikari.ChannelType.GUILD_PRIVATE_THREAD
    ]
    await ctx.respond([
        (f"{item.name} — {item.id}"[:100], str(item.id))
        for item in threads
        if query in str(item.name).casefold() or query in str(item.id)
    ][:25])


@ticket.register()
class MigrateLegacyTicket(
    lightbulb.SlashCommand,
    name="migrate-legacy",
    description="Preview or copy one approved/denied legacy ticket to archived threads (Admin only)",
):
    source_guild = lightbulb.string(
        "source-guild", "Select a bot-accessible source server", autocomplete=_guild_choices
    )
    source_channel = lightbulb.string(
        "source-channel", "Select the legacy ticket channel", autocomplete=_source_channel_choices
    )
    target_guild = lightbulb.string(
        "target-guild", "Select the destination server", autocomplete=_guild_choices
    )
    candidate_parent = lightbulb.string(
        "candidate-parent", "Select the configured candidate-thread parent", autocomplete=_candidate_parent_choices
    )
    staff_parent = lightbulb.string(
        "staff-parent", "Select the configured recruiter-thread parent", autocomplete=_staff_parent_choices
    )
    source_staff_thread = lightbulb.string(
        "source-staff-thread",
        "Select the recruiter-only source thread; leave blank to detect it automatically",
        default=None,
        autocomplete=_source_staff_choices,
    )
    ticket_type = lightbulb.string(
        "type",
        "Auto detects the type. Choose Main or FWA only to override the detected value",
        default="auto",
        choices=[
            lightbulb.Choice(name="Auto", value="auto"),
            lightbulb.Choice(name="Main", value="main"),
            lightbulb.Choice(name="FWA", value="fwa"),
        ],
    )
    status = lightbulb.string(
        "status",
        "Auto detects outcome. Approved or Denied overrides it. Open/new tickets are refused",
        default="auto",
        choices=[
            lightbulb.Choice(name="Auto", value="auto"),
            lightbulb.Choice(name="Approved", value="approved"),
            lightbulb.Choice(name="Denied", value="denied"),
        ],
    )
    user_id = lightbulb.string(
        "user-id", "Override the candidate Discord ID; leave blank to use legacy data", default=None
    )
    username = lightbulb.string(
        "username", "Override the candidate username; leave blank to use legacy data", default=None
    )
    player_tags = lightbulb.string(
        "player-tags", "Override all player tags; separate multiple tags with commas", default=None
    )
    attachment_ack = lightbulb.string(
        "attachment-ack",
        "To accept listed attachment risks, paste the exact LOSS token from the latest preview",
        default=None,
    )
    confirm = lightbulb.boolean(
        "confirm", "False previews only. True creates or resumes this ticket", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member or not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ Administrator permission is required.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            request = LegacyMigrationRequest(
                source_guild_id=int(_numeric(self.source_guild, "source guild")),
                source_channel_id=int(_numeric(self.source_channel, "source channel")),
                source_staff_thread_id=_numeric(
                    self.source_staff_thread, "source staff thread", optional=True
                ),
                target_guild_id=int(_numeric(self.target_guild, "target guild")),
                candidate_parent_id=int(_numeric(self.candidate_parent, "candidate parent")),
                staff_parent_id=int(_numeric(self.staff_parent, "staff parent")),
                ticket_type_override=(None if self.ticket_type == "auto" else self.ticket_type),
                status_override=(None if self.status == "auto" else self.status),
                user_id_override=_numeric(self.user_id, "candidate user", optional=True),
                username_override=self.username,
                player_tags_override=tuple(
                    value.strip() for value in str(self.player_tags or "").split(",") if value.strip()
                ),
                attachment_ack=self.attachment_ack,
                attachment_ack_actor_id=int(ctx.user.id),
                attachment_ack_actor_name=str(
                    getattr(ctx.member, "display_name", None)
                    or getattr(ctx.user, "username", None)
                    or ctx.user.id
                ),
            )
            if _as_int(ctx.guild_id) != request.target_guild_id:
                raise LegacyMigrationError(
                    "run this command in the selected destination server"
                )
            if not await _guild_administrator(
                bot.rest, request.source_guild_id, int(ctx.user.id)
            ):
                raise LegacyMigrationError(
                    "you must own or be an administrator of the selected source server"
                )
            preview = await preview_legacy_ticket(bot=bot, mongo=mongo, request=request)
            summary = _migration_summary(preview)
            if not self.confirm:
                await ctx.respond(
                    "🔎 **DRY RUN — nothing was written.**\n" + summary
                    + "\nRe-run with `confirm: true` to create or resume this one ticket.",
                    ephemeral=True,
                )
                return
            result = await migrate_legacy_ticket(bot=bot, mongo=mongo, preview=preview)
            location = result.ticket.get("location") or {}
            await ctx.respond(
                "✅ **Legacy ticket migrated and archived.**\n"
                + summary
                + f"\n**Candidate:** <#{location.get('id')}> • **Staff:** <#{location.get('staff_space_id')}>\n"
                "Source channels and messages were not modified.",
                ephemeral=True,
            )
        except LegacyTicketStillOpen as error:
            await ctx.respond(f"🛑 {error}. Nothing was written.", ephemeral=True)
        except (LegacyMigrationError, thread_service.ThreadTicketError, schema.TicketSchemaError) as error:
            await ctx.respond(f"❌ Migration stopped safely: {error}", ephemeral=True)
        except Exception as error:
            print(
                "[Tickets] legacy_migration_failed "
                f"source={self.source_guild}/{self.source_channel} error={type(error).__name__}"
            )
            await ctx.respond(
                "❌ Migration stopped safely after an unexpected error. Resume the same source to continue.",
                ephemeral=True,
            )


@ticket.register()
class ApproveLegacyMigrationPilot(
    lightbulb.SlashCommand,
    name="approve-migration-pilot",
    description="Allow more migrations after the five-ticket pilot is verified (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Set true only after you verify every archived pilot ticket", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member or not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ Administrator permission is required.", ephemeral=True)
            return
        if not self.confirm:
            await ctx.respond(
                "🛑 Nothing changed. Verify every pilot ticket, then set `confirm: true`.",
                ephemeral=True,
            )
            return
        await ctx.defer(ephemeral=True)
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        bound_target = _as_int(config.get("ticket_target_guild_id"))
        if not bound_target or bound_target != _as_int(ctx.guild_id):
            await ctx.respond(
                "🛑 Run pilot approval in the migration destination guild.",
                ephemeral=True,
            )
            return
        selected = await mongo.ticket_migrations.count_documents({
            "kind": "legacy_thread_migration"
        })
        completed = await mongo.ticket_migrations.count_documents({
            "kind": "legacy_thread_migration", "state": "complete"
        })
        if not 1 <= selected <= PILOT_LIMIT or completed != selected:
            await ctx.respond(
                f"🛑 Pilot approval requires 1–{PILOT_LIMIT} selected migrations, all complete; "
                f"found {completed}/{selected} complete.",
                ephemeral=True,
            )
            return
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$set": {
                "legacy_migration_pilot_approved": True,
                "legacy_migration_pilot_approved_at": utcnow(),
                "legacy_migration_pilot_approved_by": int(ctx.user.id),
            }},
            upsert=True,
        )
        await ctx.respond(
            "✅ Pilot verified. Additional single-ticket migrations are enabled.",
            ephemeral=True,
        )
