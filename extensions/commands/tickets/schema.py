"""Canonical durable ticket shape and normalization helpers.

Only this module decides how a ticket is represented.  Runtime writers create
thread tickets with :func:`new_ticket_document`; the store migration uses
``normalize_ticket_document`` to make historical channel-era rows searchable
without throwing their original fields away.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Iterable, Mapping


SCHEMA_VERSION = 3
TICKET_TYPES = frozenset({"main", "fwa"})
TICKET_STATUSES = frozenset({"open", "approved", "denied"})
TERMINAL_STATUSES = frozenset({"approved", "denied"})
CLAIM_FIELDS = frozenset({"claimed_by", "claimed_by_name", "claimed_at"})

_PLAYER_TAG = re.compile(r"^#[A-Z0-9]{3,9}$")
_SOURCE_ID_FIELDS = frozenset({
    "guild_id",
    "channel_id",
    "staff_thread_id",
    "public_thread_id",
    "public_parent_id",
    "staff_parent_id",
})


class TicketSchemaError(ValueError):
    """A ticket cannot be safely represented in the canonical schema."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_datetime(value: datetime | None, *, field: str) -> datetime:
    if value is None:
        return utcnow()
    if not isinstance(value, datetime):
        raise TicketSchemaError(f"{field} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def snowflake(value, *, field: str, required: bool = True) -> int | None:
    """Normalize historically mixed string/int Discord snowflakes."""
    if value is None or value == "":
        if required:
            raise TicketSchemaError(f"{field} is required")
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TicketSchemaError(f"{field} must be an integer Discord ID") from exc
    if normalized <= 0:
        raise TicketSchemaError(f"{field} must be a positive Discord ID")
    return normalized


def ticket_type(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in TICKET_TYPES:
        raise TicketSchemaError(f"ticket_type must be one of {sorted(TICKET_TYPES)}")
    return normalized


def ticket_status(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in TICKET_STATUSES:
        raise TicketSchemaError(f"status must be one of {sorted(TICKET_STATUSES)}")
    return normalized


def player_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(str(value).split()).upper()
    if not normalized:
        return None
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"
    if not _PLAYER_TAG.fullmatch(normalized):
        raise TicketSchemaError("player tags must contain 3-9 letters or numbers")
    return normalized


def player_tags(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = player_tag(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def username_search(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def normalize_source(source: Mapping | None) -> dict | None:
    if source is None:
        return None
    if not isinstance(source, Mapping):
        raise TicketSchemaError("source must be a mapping")
    result = deepcopy(dict(source))
    result.setdefault("kind", "legacy_channel")
    for key in _SOURCE_ID_FIELDS:
        if key in result and result[key] not in (None, ""):
            result[key] = snowflake(result[key], field=f"source.{key}")
    if result.get("guild_id") is None or result.get("channel_id") is None:
        raise TicketSchemaError("source.guild_id and source.channel_id are required")
    return result


def new_ticket_document(
    *,
    ticket_type: str,
    ticket_number: int,
    guild_id,
    public_thread_id,
    public_parent_id,
    staff_thread_id,
    staff_parent_id,
    user_id,
    username: str,
    display_name: str | None = None,
    player_tags: Iterable[str] | str = (),
    created_at: datetime | None = None,
    status: str = "open",
    source: Mapping | None = None,
) -> dict:
    """Build a complete thread-ticket document.

    Terminal-at-creation rows are reserved for legacy clones.  A live ticket
    always starts open and reaches a terminal value through ``store.transition``.
    """
    kind = globals()["ticket_type"](ticket_type)
    state = ticket_status(status)
    source_doc = normalize_source(source)
    if state != "open" and source_doc is None:
        raise TicketSchemaError("only migrated tickets may start terminal")

    try:
        number = int(ticket_number)
    except (TypeError, ValueError) as exc:
        raise TicketSchemaError("ticket_number must be a positive integer") from exc
    if number <= 0:
        raise TicketSchemaError("ticket_number must be a positive integer")

    guild = snowflake(guild_id, field="guild_id")
    public_thread = snowflake(public_thread_id, field="public_thread_id")
    public_parent = snowflake(public_parent_id, field="public_parent_id")
    staff_thread = snowflake(staff_thread_id, field="staff_thread_id")
    staff_parent = snowflake(staff_parent_id, field="staff_parent_id")
    applicant = snowflake(user_id, field="user_id")
    created = normalize_datetime(created_at, field="created_at")
    tags = globals()["player_tags"](player_tags)
    name = str(username or "").strip()
    if not name:
        raise TicketSchemaError("username is required")

    creation_event = {
        "event": "legacy_ticket_imported" if source_doc is not None else "ticket_created",
        "at": created,
        "actor": applicant,
        "actor_name": name,
        "status": state,
        "rev": 0,
    }
    if source_doc is not None:
        creation_event["source"] = deepcopy(source_doc)
    document = {
        "_id": f"ticket_{public_thread}",
        "type": "ticket",
        "schema_version": SCHEMA_VERSION,
        "venue": "thread",
        "ticket_type": kind,
        "ticket_number": number,
        "guild_id": guild,
        "location": {
            "guild_id": guild,
            "id": public_thread,
            "public_parent_id": public_parent,
            "staff_space_id": staff_thread,
            "staff_parent_id": staff_parent,
        },
        # Compatibility aliases used by the existing approve/deny command paths.
        "channel_id": public_thread,
        "thread_id": staff_thread,
        "category_id": public_parent,
        "user_id": applicant,
        "username": name,
        "username_search": username_search(name),
        "display_name": str(display_name or name).strip(),
        "player_tags": tags,
        "player_tag": tags[0] if tags else None,
        "created_at": created,
        "updated_at": created,
        "last_activity_at": created,
        "status": state,
        "rev": 0,
        "audit": [creation_event],
        "answers": [],
        "answer_count": 0,
    }
    if source_doc is not None:
        document["source"] = source_doc
    return document


def _optional_snowflake(value, *, field: str) -> int | None:
    try:
        return snowflake(value, field=field, required=False)
    except TicketSchemaError:
        return None


def normalize_ticket_document(document: Mapping) -> dict:
    """Add the canonical searchable shape to any historical ticket row.

    The migration is additive except for obsolete claim fields.  The single
    legacy ``closed`` row cannot be classified safely and blocks migration until
    an operator explicitly maps it to approved or denied.
    """
    if not isinstance(document, Mapping):
        raise TicketSchemaError("ticket document must be a mapping")
    out = deepcopy(dict(document))
    prior_schema = int(out.get("schema_version") or 0)
    if not out.get("_id"):
        raise TicketSchemaError("ticket _id is required")
    out["type"] = "ticket"
    out["schema_version"] = SCHEMA_VERSION

    raw_status = str(out.get("status") or "open").strip().casefold()
    if raw_status == "closed":
        raise TicketSchemaError(
            "legacy status 'closed' requires explicit approved/denied classification"
        )
    out["status"] = ticket_status(raw_status)

    if out.get("ticket_type") is not None:
        out["ticket_type"] = ticket_type(out["ticket_type"])
    if out.get("ticket_number") is not None:
        try:
            out["ticket_number"] = int(out["ticket_number"])
        except (TypeError, ValueError) as exc:
            raise TicketSchemaError("ticket_number must be an integer") from exc

    venue = str(out.get("venue") or "channel").strip().casefold()
    if venue not in {"channel", "thread"}:
        raise TicketSchemaError("historical venue must be channel or thread")
    out["venue"] = venue

    location = deepcopy(dict(out.get("location") or {}))
    guild = _optional_snowflake(
        location.get("guild_id", out.get("guild_id")), field="guild_id"
    )
    location_id = _optional_snowflake(
        location.get("id", out.get("channel_id")), field="location.id"
    )
    staff_id = _optional_snowflake(
        location.get("staff_space_id", out.get("thread_id")),
        field="location.staff_space_id",
    )
    parent_id = _optional_snowflake(
        location.get("public_parent_id", out.get("category_id")),
        field="location.public_parent_id",
    )
    staff_parent = _optional_snowflake(
        location.get("staff_parent_id"), field="location.staff_parent_id"
    )
    if guild is not None:
        out["guild_id"] = guild
        location["guild_id"] = guild
    if location_id is not None:
        out["channel_id"] = location_id
        location["id"] = location_id
    if staff_id is not None:
        out["thread_id"] = staff_id
        location["staff_space_id"] = staff_id
    if parent_id is not None:
        out["category_id"] = parent_id
        location["public_parent_id"] = parent_id
    if staff_parent is not None:
        location["staff_parent_id"] = staff_parent
    out["location"] = location

    applicant = _optional_snowflake(out.get("user_id"), field="user_id")
    if applicant is not None:
        out["user_id"] = applicant
    name = str(out.get("username") or out.get("display_name") or "").strip()
    if name:
        out["username"] = name
        out["username_search"] = username_search(name)
        out.setdefault("display_name", name)

    raw_tags = out.get("player_tags")
    if not raw_tags:
        raw_tags = [out.get("player_tag") or out.get("tag")]
    try:
        tags = player_tags(raw_tags)
    except TicketSchemaError:
        # A malformed historical tag must not prevent the rest of a row from
        # being indexed. Preserve it in legacy_player_tag for manual repair.
        out["legacy_player_tag"] = out.get("player_tag") or out.get("tag")
        tags = []
    out["player_tags"] = tags
    out["player_tag"] = tags[0] if tags else None

    out["rev"] = max(0, int(out.get("rev") or 0))
    out["audit"] = list(out.get("audit") or [])
    if prior_schema < SCHEMA_VERSION and not any(
        item.get("event") == "schema_backfilled" for item in out["audit"]
    ):
        out["audit"].append({
            "event": "schema_backfilled",
            "at": out.get("updated_at") or out.get("created_at") or utcnow(),
            "from_schema_version": prior_schema,
            "to_schema_version": SCHEMA_VERSION,
            "rev": out["rev"],
        })
    out["answers"] = list(out.get("answers") or [])[-50:]
    out["answer_count"] = max(
        len(out["answers"]), int(out.get("answer_count") or 0)
    )
    if out.get("created_at") is not None:
        out.setdefault("last_activity_at", out["created_at"])
    for field in CLAIM_FIELDS:
        out.pop(field, None)

    if out.get("source") is not None:
        out["source"] = normalize_source(out["source"])
    return out
