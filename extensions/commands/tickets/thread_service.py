"""Thread-only ticket creation and lifecycle services.

Discord and MongoDB cannot participate in one transaction.  This module uses a
durable, reusable applicant lease plus deterministic thread names to make every
Discord side effect discoverable after a timeout or process restart.  Legacy
channel tickets are deliberately not supported here; they are read-only inputs
to :mod:`legacy_migration`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import store
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient


_log = logging.getLogger(__name__)

CREATION_LEASE = timedelta(minutes=10)
COMPLETE_STATE_RETENTION = timedelta(days=1)
AUTO_ARCHIVE_MINUTES = 10080

_creation_index_ready = False
_creation_lock = asyncio.Lock()

_REQUIRED_BOT_PARENT_PERMISSIONS = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.READ_MESSAGE_HISTORY
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.SEND_MESSAGES_IN_THREADS
    | hikari.Permissions.MANAGE_THREADS
)
_REQUIRED_CANDIDATE_PARENT_PERMISSIONS = (
    _REQUIRED_BOT_PARENT_PERMISSIONS
    | hikari.Permissions.CREATE_PRIVATE_THREADS
    | hikari.Permissions.ATTACH_FILES
)
_REQUIRED_STAFF_PARENT_PERMISSIONS = (
    _REQUIRED_BOT_PARENT_PERMISSIONS | hikari.Permissions.CREATE_PUBLIC_THREADS
)


class ThreadTicketError(RuntimeError):
    """A safe, operator-actionable thread ticket failure."""


class ThreadConfigurationError(ThreadTicketError):
    """Thread parents, roles, or permissions are unsafe or incomplete."""


class ThreadCreationBusy(ThreadTicketError):
    """Another worker currently owns this applicant's creation lease."""


@dataclass(frozen=True, slots=True)
class ThreadParents:
    guild_id: int
    candidate_parent_id: int
    staff_parent_id: int
    recruiter_role_id: int


@dataclass(frozen=True, slots=True)
class CreatedThreadTicket:
    ticket: dict
    resumed: bool
    delivery_pending: bool = False


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


def _creation_id(_guild_id: int, user_id: int, ticket_type: str) -> str:
    # One-open-ticket semantics are global after all source guilds consolidate.
    # The durable lease must use the same key or two guilds could create two
    # Discord pairs before Mongo's open-ticket index rejects the second record.
    return f"thread:{int(user_id)}:{ticket_type}"


def _slug(value: str, *, fallback: str = "candidate", limit: int = 42) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return (value or fallback)[:limit].rstrip("-")


def thread_names(ticket_type: str, ticket_number: int, username: str) -> tuple[str, str]:
    suffix = f"{ticket_type}-{int(ticket_number)}-{_slug(username)}"
    return suffix[:100], f"staff-{suffix}"[:100]


def _permission_names(value: hikari.Permissions) -> str:
    names = [permission.name for permission in hikari.Permissions if permission & value]
    return ", ".join(names) or "unknown permissions"


def _overwrite_values(overwrites: Any) -> Iterable[Any]:
    if isinstance(overwrites, Mapping):
        return overwrites.values()
    return overwrites or ()


def _effective_permissions(
    *,
    guild_id: int,
    owner_id: int,
    member: Any,
    roles: Sequence[Any],
    channel: Any,
) -> hikari.Permissions:
    """Calculate Discord channel permissions from REST models.

    Hikari 2.3 does not expose a public permission calculator.  This follows
    Discord's documented order: base roles, everyone overwrite, aggregate role
    overwrites, then the member overwrite.
    """
    member_id = _as_int(getattr(member, "id", 0))
    if member_id == owner_id:
        return hikari.Permissions.all_permissions()

    role_ids = {_as_int(item) for item in getattr(member, "role_ids", ())}
    role_ids.add(guild_id)
    permissions = hikari.Permissions.NONE
    for role in roles:
        if _as_int(getattr(role, "id", 0)) in role_ids:
            permissions |= hikari.Permissions(getattr(role, "permissions", 0))
    if permissions & hikari.Permissions.ADMINISTRATOR:
        return hikari.Permissions.all_permissions()

    overwrites = list(_overwrite_values(getattr(channel, "permission_overwrites", ())))

    def apply(deny: hikari.Permissions, allow: hikari.Permissions) -> None:
        nonlocal permissions
        permissions &= ~deny
        permissions |= allow

    everyone = next(
        (item for item in overwrites if _as_int(getattr(item, "id", 0)) == guild_id),
        None,
    )
    if everyone is not None:
        apply(
            hikari.Permissions(getattr(everyone, "deny", 0)),
            hikari.Permissions(getattr(everyone, "allow", 0)),
        )

    role_deny = hikari.Permissions.NONE
    role_allow = hikari.Permissions.NONE
    for item in overwrites:
        if _as_int(getattr(item, "id", 0)) in role_ids and _as_int(getattr(item, "id", 0)) != guild_id:
            role_deny |= hikari.Permissions(getattr(item, "deny", 0))
            role_allow |= hikari.Permissions(getattr(item, "allow", 0))
    apply(role_deny, role_allow)

    member_overwrite = next(
        (item for item in overwrites if _as_int(getattr(item, "id", 0)) == member_id),
        None,
    )
    if member_overwrite is not None:
        apply(
            hikari.Permissions(getattr(member_overwrite, "deny", 0)),
            hikari.Permissions(getattr(member_overwrite, "allow", 0)),
        )
    return permissions


async def validate_thread_parents(
    rest: hikari.api.RESTClient,
    parents: ThreadParents,
    *,
    bot_user_id: int,
    require_webhooks: bool = False,
    applicant_user_id: int | None = None,
) -> tuple[Any, Any]:
    """Fail closed unless both parents and bot/recruiter access are safe."""
    if parents.candidate_parent_id == parents.staff_parent_id:
        raise ThreadConfigurationError("candidate and staff parents must be different channels")

    candidate, staff = await asyncio.gather(
        rest.fetch_channel(parents.candidate_parent_id),
        rest.fetch_channel(parents.staff_parent_id),
    )
    for label, channel in (("candidate", candidate), ("staff", staff)):
        if getattr(channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
            raise ThreadConfigurationError(f"{label} parent must be a guild text channel")
        if _as_int(getattr(channel, "guild_id", 0)) != parents.guild_id:
            raise ThreadConfigurationError(f"{label} parent is not in the configured guild")

    guild, bot_member, roles = await asyncio.gather(
        rest.fetch_guild(parents.guild_id),
        rest.fetch_member(parents.guild_id, bot_user_id),
        rest.fetch_roles(parents.guild_id),
    )
    owner_id = _as_int(getattr(guild, "owner_id", 0))
    required_candidate = _REQUIRED_CANDIDATE_PARENT_PERMISSIONS
    required_staff = _REQUIRED_STAFF_PARENT_PERMISSIONS
    if require_webhooks:
        required_candidate |= hikari.Permissions.MANAGE_WEBHOOKS | hikari.Permissions.ATTACH_FILES
        required_staff |= hikari.Permissions.MANAGE_WEBHOOKS | hikari.Permissions.ATTACH_FILES

    bot_parent_permissions: dict[str, hikari.Permissions] = {}
    for label, channel, required in (
        ("candidate", candidate, required_candidate),
        ("staff", staff, required_staff),
    ):
        actual = _effective_permissions(
            guild_id=parents.guild_id,
            owner_id=owner_id,
            member=bot_member,
            roles=roles,
            channel=channel,
        )
        bot_parent_permissions[label] = actual
        missing = required & ~actual
        if missing:
            raise ThreadConfigurationError(
                f"bot is missing {_permission_names(missing)} in the {label} parent"
            )

    recruiter_role = next(
        (role for role in roles if _as_int(getattr(role, "id", 0)) == parents.recruiter_role_id),
        None,
    )
    if recruiter_role is None:
        raise ThreadConfigurationError("configured recruiter role is not in the target guild")
    if (
        not bool(getattr(recruiter_role, "is_mentionable", False))
        and not bot_parent_permissions["candidate"]
        & hikari.Permissions.MENTION_ROLES
    ):
        raise ThreadConfigurationError(
            "recruiter role must be mentionable or bot needs Mention Everyone in the candidate parent"
        )
    required_recruiter = (
        hikari.Permissions.VIEW_CHANNEL
        | hikari.Permissions.READ_MESSAGE_HISTORY
        | hikari.Permissions.SEND_MESSAGES_IN_THREADS
        | hikari.Permissions.MANAGE_THREADS
    )
    recruiter_member = type("RoleMember", (), {
        "id": 0,
        "role_ids": (parents.recruiter_role_id,),
    })()
    for label, channel in (("candidate", candidate), ("staff", staff)):
        recruiter_permissions = _effective_permissions(
            guild_id=parents.guild_id,
            owner_id=owner_id,
            member=recruiter_member,
            roles=roles,
            channel=channel,
        )
        missing = required_recruiter & ~recruiter_permissions
        if missing:
            raise ThreadConfigurationError(
                f"recruiter role is missing {_permission_names(missing)} in the {label} parent"
            )

    everyone_role = next(
        (role for role in roles if _as_int(getattr(role, "id", 0)) == parents.guild_id),
        None,
    )
    if everyone_role is None:
        raise ThreadConfigurationError("target guild @everyone role could not be verified")
    everyone_member = type("EveryoneMember", (), {"id": 0, "role_ids": ()})()
    everyone_permissions = _effective_permissions(
        guild_id=parents.guild_id,
        owner_id=owner_id,
        member=everyone_member,
        roles=(everyone_role,),
        channel=staff,
    )
    if everyone_permissions & hikari.Permissions.VIEW_CHANNEL:
        raise ThreadConfigurationError("staff parent is visible to @everyone")

    roles_by_id = {
        _as_int(getattr(role, "id", 0)): role
        for role in roles
        if _as_int(getattr(role, "id", 0))
    }
    bot_role_ids = {_as_int(value) for value in getattr(bot_member, "role_ids", ())}
    for role_id, role in roles_by_id.items():
        if role_id in {parents.guild_id, parents.recruiter_role_id}:
            continue
        role_permissions = hikari.Permissions(getattr(role, "permissions", 0))
        if role_permissions & hikari.Permissions.ADMINISTRATOR:
            continue
        if role_id in bot_role_ids and bool(getattr(role, "is_managed", False)):
            continue
        effective = _effective_permissions(
            guild_id=parents.guild_id,
            owner_id=owner_id,
            member=type("RoleMember", (), {"id": 0, "role_ids": (role_id,)})(),
            roles=roles,
            channel=staff,
        )
        if effective & hikari.Permissions.VIEW_CHANNEL:
            raise ThreadConfigurationError(
                f"non-recruiter role {role_id} can view the staff parent"
            )

    member_overwrite_ids: set[int] = set()
    for overwrite in _overwrite_values(getattr(staff, "permission_overwrites", ())):
        overwrite_id = _as_int(getattr(overwrite, "id", 0))
        overwrite_type = getattr(overwrite, "type", None)
        is_member = overwrite_type == hikari.PermissionOverwriteType.MEMBER
        if overwrite_type is None:
            is_member = overwrite_id not in roles_by_id
        if (
            is_member
            and overwrite_id
            and overwrite_id != _as_int(getattr(bot_member, "id", 0))
            and hikari.Permissions(getattr(overwrite, "allow", 0))
            & hikari.Permissions.VIEW_CHANNEL
        ):
            member_overwrite_ids.add(overwrite_id)

    for member_id in sorted(member_overwrite_ids):
        if member_id == owner_id:
            continue
        try:
            member = await rest.fetch_member(parents.guild_id, member_id)
        except hikari.NotFoundError:
            continue
        except Exception as error:
            raise ThreadConfigurationError(
                "staff parent member overwrites could not be inspected"
            ) from error
        role_ids = {_as_int(value) for value in getattr(member, "role_ids", ())}
        authorized = bool(role_ids & {parents.recruiter_role_id}) or any(
            hikari.Permissions(getattr(roles_by_id[role_id], "permissions", 0))
            & hikari.Permissions.ADMINISTRATOR
            for role_id in role_ids
            if role_id in roles_by_id
        )
        effective = _effective_permissions(
            guild_id=parents.guild_id,
            owner_id=owner_id,
            member=member,
            roles=roles,
            channel=staff,
        )
        if effective & hikari.Permissions.VIEW_CHANNEL and not authorized:
            raise ThreadConfigurationError(
                f"non-recruiter member {member_id} can view the staff parent"
            )

    if applicant_user_id is not None:
        try:
            applicant = await rest.fetch_member(parents.guild_id, int(applicant_user_id))
        except (hikari.NotFoundError, hikari.ForbiddenError) as error:
            raise ThreadConfigurationError(
                "applicant is not an accessible member of the ticket guild"
            ) from error
        applicant_permissions = _effective_permissions(
            guild_id=parents.guild_id,
            owner_id=owner_id,
            member=applicant,
            roles=roles,
            channel=candidate,
        )
        required_applicant = (
            hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY
            | hikari.Permissions.SEND_MESSAGES_IN_THREADS
        )
        missing = required_applicant & ~applicant_permissions
        if missing:
            raise ThreadConfigurationError(
                "applicant is missing "
                f"{_permission_names(missing)} in the candidate parent"
            )
    return candidate, staff


def parents_from_config(config: Mapping[str, Any], guild_id: int, ticket_type: str) -> ThreadParents:
    prefix = "main" if ticket_type == "main" else "fwa"
    target_guild = _as_int(config.get("ticket_target_guild_id"))
    if not target_guild:
        raise ThreadConfigurationError("missing ticket configuration: ticket_target_guild_id")
    if target_guild != int(guild_id):
        raise ThreadConfigurationError("thread ticketing is configured for a different guild")
    candidate_parent = _as_int(config.get(f"{prefix}_candidate_parent"))
    staff_parent = _as_int(config.get(f"{prefix}_staff_parent"))
    recruiter_role = _as_int(config.get(f"{prefix}_recruiter_role"))
    missing = [
        label
        for label, value in (
            (f"{prefix}_candidate_parent", candidate_parent),
            (f"{prefix}_staff_parent", staff_parent),
            (f"{prefix}_recruiter_role", recruiter_role),
        )
        if not value
    ]
    if missing:
        raise ThreadConfigurationError("missing ticket configuration: " + ", ".join(missing))
    return ThreadParents(int(guild_id), candidate_parent, staff_parent, recruiter_role)


async def ensure_creation_indexes(mongo: MongoClient) -> None:
    global _creation_index_ready
    if _creation_index_ready:
        return
    # Install canonical uniqueness before the first Discord side effect. This
    # is the final guard against duplicate pairs if multiple bot processes run.
    await ensure_canonical_ticket_store(mongo)
    await mongo.ticket_creation_state.create_index(
        "expires_at", expireAfterSeconds=0, name="ttl_expires_at"
    )
    _creation_index_ready = True


async def ensure_canonical_ticket_store(mongo: MongoClient) -> None:
    """Fail closed while the legacy collection is still the active writer."""
    active = await store.active_store(mongo)
    if active != store.STORE_TICKETS:
        raise ThreadConfigurationError(
            "ticket storage is not ready; an administrator must run `/ticket migrate-store`"
        )
    await store.ensure_indexes(mongo)


async def reserve_ticket_number(mongo: MongoClient, ticket_type: str) -> int:
    """Allocate above both the durable counter and canonical stored numbers."""
    if ticket_type not in {"main", "fwa"}:
        raise ThreadConfigurationError("ticket type must be main or fwa")
    field = f"{ticket_type}_ticket_counter"
    for _attempt in range(5):
        cursor = mongo.tickets.find(
            {
                "type": "ticket",
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            {"ticket_number": 1},
        )
        rows = await cursor.sort([("ticket_number", -1)]).limit(1).to_list(length=1)
        canonical_max = max(
            (_as_int(row.get("ticket_number")) for row in rows),
            default=0,
        )
        # Both operations are atomic on the shared config document. Concurrent
        # workers may interleave here, but $max can only raise the floor and
        # find_one_and_update gives every worker a distinct increment.
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$max": {field: canonical_max}},
            upsert=True,
        )
        config = await mongo.ticket_setup.find_one_and_update(
            {"_id": "config"},
            {"$inc": {field: 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        allocated = int(config[field])

        # Close the cross-collection race where a canonical import lands after
        # the first maximum read but before this allocation is returned.
        newest = mongo.tickets.find(
            {
                "type": "ticket",
                "ticket_type": ticket_type,
                "ticket_number": {"$exists": True},
            },
            {"ticket_number": 1},
        )
        latest = await newest.sort([("ticket_number", -1)]).limit(1).to_list(length=1)
        latest_number = max(
            (_as_int(row.get("ticket_number")) for row in latest),
            default=0,
        )
        if allocated > latest_number:
            return allocated
    raise ThreadTicketError(
        "a ticket number could not be allocated while imports were running"
    )


async def _claim_creation(
    mongo: MongoClient,
    *,
    guild_id: int,
    user_id: int,
    username: str,
    display_name: str | None,
    ticket_type: str,
    parents: ThreadParents,
    now: datetime,
) -> tuple[str, dict, bool]:
    """Acquire or resume a reusable applicant lease."""
    await ensure_creation_indexes(mongo)
    collection = mongo.ticket_creation_state
    creation_id = _creation_id(guild_id, user_id, ticket_type)
    owner = uuid.uuid4().hex
    base = {
        "schema_version": 2,
        "kind": "thread_ticket_creation",
        "guild_id": int(guild_id),
        "user_id": int(user_id),
        "username": username,
        "display_name": display_name or username,
        "ticket_type": ticket_type,
        "candidate_parent_id": parents.candidate_parent_id,
        "staff_parent_id": parents.staff_parent_id,
        "recruiter_role_id": parents.recruiter_role_id,
        "state": "creating",
        "lease_owner": owner,
        "lease_until": now + CREATION_LEASE,
        "updated_at": now,
    }

    while True:
        current = await collection.find_one({"_id": creation_id})
        if current is None:
            try:
                await collection.insert_one({"_id": creation_id, "created_at": now, **base})
                return owner, {"_id": creation_id, "created_at": now, **base}, False
            except DuplicateKeyError:
                continue

        if current.get("state") == "complete":
            result = await collection.update_one(
                {"_id": creation_id, "state": "complete", "ticket_id": current.get("ticket_id")},
                {
                    "$set": base,
                    "$unset": {
                        "ticket_id": "",
                        "ticket_number": "",
                        "candidate_thread_id": "",
                        "staff_thread_id": "",
                        "candidate_name": "",
                        "staff_name": "",
                        "completed_at": "",
                        "expires_at": "",
                        "delivery": "",
                        "last_error": "",
                    },
                },
            )
            if getattr(result, "matched_count", 0):
                return owner, {"_id": creation_id, **base}, False
            continue

        bound = bool(
            current.get("ticket_number")
            or current.get("candidate_thread_id")
            or current.get("staff_thread_id")
        )
        if bound:
            stored_binding = (
                _as_int(current.get("guild_id")),
                _as_int(current.get("candidate_parent_id")),
                _as_int(current.get("staff_parent_id")),
                _as_int(current.get("recruiter_role_id")),
            )
            requested_binding = (
                int(guild_id),
                parents.candidate_parent_id,
                parents.staff_parent_id,
                parents.recruiter_role_id,
            )
            if stored_binding != requested_binding:
                raise ThreadConfigurationError(
                    "an unfinished ticket is bound to its original validated thread parents"
                )

        lease_until = _aware(current.get("lease_until"))
        if lease_until is not None and lease_until > now:
            raise ThreadCreationBusy("this ticket is already being created")
        resumed = bool(current.get("ticket_number") or current.get("candidate_thread_id"))
        claimed = await collection.find_one_and_update(
            {
                "_id": creation_id,
                "state": {"$ne": "complete"},
                "$or": [
                    {"lease_until": {"$lte": now}},
                    {"lease_until": {"$exists": False}},
                ],
            },
            {"$set": {**base, "last_resumed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if claimed is not None:
            return owner, claimed, resumed


async def _state_update(mongo: MongoClient, creation_id: str, owner: str, **fields: Any) -> dict:
    now = utcnow()
    result = await mongo.ticket_creation_state.find_one_and_update(
        {"_id": creation_id, "lease_owner": owner, "state": {"$ne": "complete"}},
        {"$set": {**fields, "updated_at": now, "lease_until": now + CREATION_LEASE}},
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise ThreadCreationBusy("ticket creation lease was lost")
    return result


async def _collect_rest_iterator(iterator) -> list:
    """Collect a Hikari LazyIterator while retaining lightweight test doubles."""
    collect = getattr(iterator, "collect", None)
    if callable(collect):
        return list(await collect(list))
    to_list = getattr(iterator, "to_list", None)
    if callable(to_list):
        return list(await to_list())
    return list(await iterator)


async def _find_named_thread(
    rest: hikari.api.RESTClient,
    *,
    guild_id: int,
    parent_id: int,
    name: str,
    private: bool,
    expected_owner_id: int,
) -> Any | None:
    active = await rest.fetch_active_threads(guild_id)
    matches = [
        item
        for item in active
        if _as_int(getattr(item, "parent_id", 0)) == parent_id
        and str(getattr(item, "name", "")) == name
    ]
    for item in matches:
        _validate_recovered_thread(
            item,
            guild_id=guild_id,
            parent_id=parent_id,
            name=name,
            private=private,
            expected_owner_id=expected_owner_id,
        )
    archived_iter = (
        rest.fetch_private_archived_threads(parent_id)
        if private
        else rest.fetch_public_archived_threads(parent_id)
    )
    archived = await _collect_rest_iterator(archived_iter)
    for item in archived:
        if str(getattr(item, "name", "")) != name:
            continue
        _validate_recovered_thread(
            item,
            guild_id=guild_id,
            parent_id=parent_id,
            name=name,
            private=private,
            expected_owner_id=expected_owner_id,
        )
        if all(
            _as_int(getattr(item, "id", 0)) != _as_int(getattr(found, "id", 0))
            for found in matches
        ):
            matches.append(item)
    if len(matches) > 1:
        raise ThreadTicketError(f"multiple destination threads match {name!r}; creation is blocked")
    return matches[0] if matches else None


def _validate_recovered_thread(
    thread: Any,
    *,
    guild_id: int,
    parent_id: int,
    name: str,
    private: bool,
    expected_owner_id: int,
) -> None:
    """Bind a recovered Discord thread to its complete durable identity."""
    if _as_int(getattr(thread, "guild_id", 0)) != int(guild_id):
        raise ThreadTicketError("recovered destination thread is in the wrong guild")
    if _as_int(getattr(thread, "parent_id", 0)) != int(parent_id):
        raise ThreadTicketError("recovered destination thread has the wrong parent")
    expected_type = (
        hikari.ChannelType.GUILD_PRIVATE_THREAD
        if private
        else hikari.ChannelType.GUILD_PUBLIC_THREAD
    )
    if getattr(thread, "type", None) != expected_type:
        raise ThreadTicketError("recovered destination thread has the wrong thread type")
    if str(getattr(thread, "name", "")) != name:
        raise ThreadTicketError("recovered destination thread has the wrong name")
    if _as_int(getattr(thread, "owner_id", 0)) != int(expected_owner_id):
        raise ThreadTicketError("recovered destination thread has the wrong owner")


async def _fetch_or_recover_thread(
    rest: hikari.api.RESTClient,
    *,
    thread_id: int,
    guild_id: int,
    parent_id: int,
    name: str,
    private: bool,
    expected_owner_id: int,
) -> Any | None:
    if thread_id:
        try:
            channel = await rest.fetch_channel(thread_id)
        except hikari.NotFoundError:
            channel = None
        if channel is not None:
            _validate_recovered_thread(
                channel,
                guild_id=guild_id,
                parent_id=parent_id,
                name=name,
                private=private,
                expected_owner_id=expected_owner_id,
            )
            return channel
    return await _find_named_thread(
        rest,
        guild_id=guild_id,
        parent_id=parent_id,
        name=name,
        private=private,
        expected_owner_id=expected_owner_id,
    )


async def _unarchive_if_needed(rest: hikari.api.RESTClient, thread: Any) -> Any:
    needs_unlock = bool(getattr(thread, "is_locked", False))
    if bool(getattr(thread, "is_archived", False)):
        edited = await rest.edit_channel(
            thread.id, archived=False, reason="Resuming ticket creation"
        )
        thread = edited or thread
    if needs_unlock or bool(getattr(thread, "is_locked", False)):
        edited = await rest.edit_channel(
            thread.id, locked=False, reason="Resuming ticket creation"
        )
        thread = edited or thread
    return thread


async def _quarantine_incomplete_creation_threads(
    rest: hikari.api.RESTClient,
    threads: Iterable[Any | None],
) -> None:
    """Best-effort quarantine for destination threads that are safe to resume."""
    for thread in threads:
        if thread is None:
            continue
        try:
            await rest.edit_channel(
                thread.id,
                locked=True,
                archived=True,
                reason="Quarantining incomplete ticket creation for safe resume",
            )
        except Exception:
            _log.exception("failed to quarantine incomplete ticket thread %s", thread.id)


async def _mark_interrupted_creation_retry(
    mongo: MongoClient,
    state: Mapping[str, Any],
    owner: str,
    error: BaseException,
) -> None:
    """Release one owned creation lease without masking the workflow failure."""
    try:
        await mongo.ticket_creation_state.update_one(
            {"_id": state["_id"], "lease_owner": owner},
            {
                "$set": {
                    "state": "retry",
                    "last_error": type(error).__name__,
                    "updated_at": utcnow(),
                },
                "$unset": {
                    "lease_owner": "",
                    "lease_until": "",
                    "expires_at": "",
                },
            },
        )
    except Exception:
        _log.exception("failed to release interrupted ticket creation %s", state.get("_id"))


async def _cleanup_interrupted_creation(
    *,
    rest: hikari.api.RESTClient,
    mongo: MongoClient,
    state: Mapping[str, Any],
    owner: str,
    threads: Iterable[Any | None],
    error: BaseException,
) -> None:
    await _quarantine_incomplete_creation_threads(rest, threads)
    await _mark_interrupted_creation_retry(mongo, state, owner, error)


async def _ensure_live_thread_pair(
    *,
    rest: hikari.api.RESTClient,
    mongo: MongoClient,
    state: dict,
    owner: str,
    bot_user_id: int,
) -> tuple[Any, Any, dict]:
    creation_id = state["_id"]
    ticket_number = state.get("ticket_number")
    if not ticket_number:
        ticket_number = await reserve_ticket_number(mongo, state["ticket_type"])
        candidate_name, staff_name = thread_names(
            state["ticket_type"], ticket_number, state["username"]
        )
        state = await _state_update(
            mongo,
            creation_id,
            owner,
            ticket_number=ticket_number,
            candidate_name=candidate_name,
            staff_name=staff_name,
        )
    candidate_name = state.get("candidate_name") or thread_names(
        state["ticket_type"], ticket_number, state["username"]
    )[0]
    staff_name = state.get("staff_name") or thread_names(
        state["ticket_type"], ticket_number, state["username"]
    )[1]

    candidate = staff = None
    try:
        candidate = await _fetch_or_recover_thread(
            rest,
            thread_id=_as_int(state.get("candidate_thread_id")),
            guild_id=state["guild_id"],
            parent_id=state["candidate_parent_id"],
            name=candidate_name,
            private=True,
            expected_owner_id=bot_user_id,
        )
        if candidate is None:
            candidate = await rest.create_thread(
                state["candidate_parent_id"],
                hikari.ChannelType.GUILD_PRIVATE_THREAD,
                candidate_name,
                auto_archive_duration=AUTO_ARCHIVE_MINUTES,
                invitable=False,
                reason=f"{state['ticket_type'].upper()} ticket {ticket_number}",
            )
        candidate = await _unarchive_if_needed(rest, candidate)
        state = await _state_update(
            mongo, creation_id, owner, candidate_thread_id=int(candidate.id)
        )
        await rest.add_thread_member(candidate.id, state["user_id"])

        staff = await _fetch_or_recover_thread(
            rest,
            thread_id=_as_int(state.get("staff_thread_id")),
            guild_id=state["guild_id"],
            parent_id=state["staff_parent_id"],
            name=staff_name,
            private=False,
            expected_owner_id=bot_user_id,
        )
        if staff is None:
            staff = await rest.create_thread(
                state["staff_parent_id"],
                hikari.ChannelType.GUILD_PUBLIC_THREAD,
                staff_name,
                auto_archive_duration=AUTO_ARCHIVE_MINUTES,
                reason=f"Recruiter workspace for {state['ticket_type'].upper()} ticket {ticket_number}",
            )
        staff = await _unarchive_if_needed(rest, staff)
        state = await _state_update(mongo, creation_id, owner, staff_thread_id=int(staff.id))
        return candidate, staff, state
    except asyncio.CancelledError:
        await _quarantine_incomplete_creation_threads(rest, (candidate, staff))
        raise
    except Exception:
        await _quarantine_incomplete_creation_threads(rest, (candidate, staff))
        raise


async def _message_marker_exists(rest: hikari.api.RESTClient, channel_id: int, marker: str) -> bool:
    messages = await _collect_rest_iterator(rest.fetch_messages(channel_id))
    return any(marker in (getattr(message, "content", "") or "") for message in messages)


async def _send_once(
    rest: hikari.api.RESTClient,
    channel_id: int,
    marker: str,
    content: str,
    *,
    user_mentions: bool | Sequence[int] = False,
    role_mentions: bool | Sequence[int] = False,
) -> None:
    if await _message_marker_exists(rest, channel_id, marker):
        return
    await rest.create_message(
        channel_id,
        content=f"{content}\n-# {marker}",
        mentions_everyone=False,
        user_mentions=user_mentions,
        role_mentions=role_mentions,
    )


def _questionnaire_components(ticket_type: str, guild_icon_url: str | None) -> list:
    logo = guild_icon_url or (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "v1752836911/misc_images/WU_Logo.png"
    )
    is_fwa = ticket_type == "fwa"
    title = (
        "## **Warriors United FWA Clan Entry Ticket**"
        if is_fwa
        else "## **Warriors United Main Clan Entry Ticket**"
    )
    questions = (
        "1) Your in-game name and player tag\n"
        "2) Your age, time zone, and country\n"
        "3) Do you have multiple accounts?\n"
        "4) If yes, list every player tag.\n"
        "5) What are you looking for in a clan?"
        + (
            "\n6) Are you familiar with LazyCWL and the daily FWA process?"
            if is_fwa
            else ""
        )
    )
    hero = (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "v1752836857/misc_images/WU_FWA_Ticket.jpg"
        if is_fwa
        else logo
    )
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Section(
                    components=[Text(content=title), Text(content=questions)],
                    accessory=Thumbnail(media=logo),
                ),
                Media(items=[MediaItem(media=hero)]),
                Text(content="-# A recruiter will reply as soon as possible."),
            ],
        )
    ]


async def _questionnaire_exists(
    rest: hikari.api.RESTClient,
    channel_id: int,
    ticket_type: str,
) -> bool:
    needle = (
        "Warriors United FWA Clan Entry Ticket"
        if ticket_type == "fwa"
        else "Warriors United Main Clan Entry Ticket"
    )
    def contains(component: Any) -> bool:
        if needle in str(getattr(component, "content", "")):
            return True
        return any(contains(child) for child in getattr(component, "components", ()) or ())

    messages = await _collect_rest_iterator(rest.fetch_messages(channel_id))
    return any(
        any(contains(component) for component in getattr(message, "components", ()) or ())
        for message in messages
    )


async def _deliver_opening_messages(rest: hikari.api.RESTClient, ticket: dict) -> None:
    public_id = _as_int(ticket.get("location", {}).get("id") or ticket.get("channel_id"))
    staff_id = _as_int(ticket.get("location", {}).get("staff_space_id") or ticket.get("thread_id"))
    ticket_number = int(ticket["ticket_number"])
    ticket_type = ticket["ticket_type"]
    user_id = _as_int(ticket["user_id"])
    recruiter_role = _as_int(ticket.get("recruiter_role_id"))
    candidate_marker = f"ticket-setup:{public_id}:candidate"
    staff_marker = f"ticket-setup:{public_id}:staff"
    role_text = f" <@&{recruiter_role}>" if recruiter_role else ""
    await _send_once(
        rest,
        public_id,
        candidate_marker,
        (
            f"<@{user_id}> Welcome, and thank you for your interest. "
            f"{role_text.strip() or 'A recruiter'} will reply soon. "
            "Please answer the questions below while you wait."
        ),
        user_mentions=[user_id],
        role_mentions=[recruiter_role] if recruiter_role else False,
    )
    if not await _questionnaire_exists(rest, public_id, ticket_type):
        guild = await rest.fetch_guild(_as_int(ticket.get("guild_id")))
        icon = getattr(guild, "make_icon_url", lambda: None)()
        await rest.create_message(
            public_id,
            components=_questionnaire_components(ticket_type, str(icon) if icon else None),
            mentions_everyone=False,
            user_mentions=False,
            role_mentions=False,
        )
    await _send_once(
        rest,
        staff_id,
        staff_marker,
        (
            f"Recruiter-only workspace for {ticket_type.upper()} ticket #{ticket_number}.\n"
            f"Candidate thread: <#{public_id}>\n"
            "Do not add or mention the candidate in this staff thread."
        ),
        user_mentions=False,
        role_mentions=False,
    )


async def _set_committed_creation_state(
    mongo: MongoClient,
    ticket: Mapping[str, Any],
    *,
    state: str,
    error: Exception | None = None,
) -> None:
    """Make committed-ticket delivery progress durable across every crash boundary."""
    location = ticket.get("location") or {}
    creation_id = _creation_id(
        _as_int(ticket.get("guild_id")),
        _as_int(ticket.get("user_id")),
        str(ticket.get("ticket_type")),
    )
    now = utcnow()
    complete = state == "complete"
    fields = {
        "state": state,
        "kind": "thread_ticket_creation",
        "schema_version": 2,
        "ticket_id": ticket["_id"],
        "ticket_number": int(ticket["ticket_number"]),
        "guild_id": _as_int(ticket.get("guild_id")),
        "user_id": _as_int(ticket.get("user_id")),
        "username": str(ticket.get("username") or "candidate"),
        "display_name": str(
            ticket.get("display_name") or ticket.get("username") or "candidate"
        ),
        "ticket_type": str(ticket.get("ticket_type")),
        "candidate_parent_id": _as_int(location.get("public_parent_id")),
        "staff_parent_id": _as_int(location.get("staff_parent_id")),
        "recruiter_role_id": _as_int(ticket.get("recruiter_role_id")),
        "candidate_thread_id": _as_int(location.get("id") or ticket.get("channel_id")),
        "staff_thread_id": _as_int(
            location.get("staff_space_id") or ticket.get("thread_id")
        ),
        "updated_at": now,
        "delivery.state": "complete" if complete else "retry" if error else "pending",
    }
    if complete:
        fields.update({
            "completed_at": now,
            "expires_at": now + COMPLETE_STATE_RETENTION,
            "delivery.completed_at": now,
        })
    elif error is not None:
        fields.update({
            "last_error": type(error).__name__,
            "delivery.last_error": type(error).__name__,
        })
    await mongo.ticket_creation_state.update_one(
        {"_id": creation_id},
        {
            "$set": fields,
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                **({"last_error": "", "delivery.last_error": ""} if error is None else {}),
                **({"expires_at": ""} if not complete else {}),
            },
        },
        upsert=True,
    )


async def _mark_committed_creation_complete(
    mongo: MongoClient, ticket: Mapping[str, Any]
) -> None:
    await _queue_staff_context_outbox(mongo, ticket)
    await _set_committed_creation_state(mongo, ticket, state="complete")


async def _queue_staff_context_outbox(
    mongo: MongoClient,
    ticket: Mapping[str, Any],
) -> str:
    """Bind recoverable staff-context work before a workflow can complete."""
    from extensions.commands.tickets import console  # local import avoids cycle

    state_id = await console.queue_staff_identity_context(mongo, ticket)
    expected = f"ticket_staff_context:{ticket.get('_id')}"
    if state_id != expected:
        raise ThreadTicketError(
            "ticket staff-context work could not be bound before completion"
        )
    return state_id


async def _finish_committed_creation(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket: dict,
    *,
    reconcile_pair: bool,
) -> bool:
    """Deliver idempotent setup messages; never turn a committed row into failure."""
    state_durable = True
    try:
        await _set_committed_creation_state(mongo, ticket, state="delivery_pending")
    except Exception:
        state_durable = False
        _log.exception("ticket delivery-pending checkpoint failed for %s", ticket.get("_id"))
    try:
        if reconcile_pair:
            await reconcile_ticket_pair(bot.rest, ticket)
        await _deliver_opening_messages(bot.rest, ticket)
    except Exception as error:
        try:
            await _set_committed_creation_state(
                mongo, ticket, state="delivery_retry", error=error
            )
        except Exception:
            _log.exception("ticket delivery-retry checkpoint failed for %s", ticket.get("_id"))
        _log.exception("ticket opening-message delivery failed for %s", ticket.get("_id"))
        return False
    try:
        await _mark_committed_creation_complete(mongo, ticket)
    except Exception:
        _log.exception("ticket delivery completion checkpoint failed for %s", ticket.get("_id"))
        return False
    return state_durable


async def _reconcile_existing_ticket(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket: dict,
) -> CreatedThreadTicket:
    """Heal every post-commit Discord/state step before returning an open ticket."""
    delivery_complete = await _finish_committed_creation(
        bot, mongo, ticket, reconcile_pair=True
    )
    await notify_console_after_change(
        bot, mongo, ticket, reason="ticket creation reconciled"
    )
    return CreatedThreadTicket(
        ticket, resumed=True, delivery_pending=not delivery_complete
    )


async def notify_console_after_change(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket: dict,
    *,
    reason: str,
) -> None:
    """Late import keeps the core ticket service independent from console UI."""
    try:
        from extensions.commands.tickets import console  # local import avoids cycle
    except (AttributeError, ImportError):
        _log.info("ticket console integration is not loaded yet")
        return
    try:
        await console.deliver_staff_identity_context(bot, mongo, ticket)
    except Exception:
        _log.exception("ticket staff-context update failed for %s", ticket.get("_id"))
    try:
        await console.request_hub_refresh_best_effort(bot, mongo, reason=reason)
    except Exception:
        _log.exception("ticket hub refresh request failed for %s", ticket.get("_id"))


async def _committed_ticket_for_creation_state(
    mongo: MongoClient,
    *,
    guild_id: int,
    user_id: int,
    ticket_type: str,
) -> dict | None:
    """Resolve a committed row before any bound Discord pair is reused."""
    state = await mongo.ticket_creation_state.find_one({
        "_id": _creation_id(guild_id, user_id, ticket_type)
    })
    if state is None:
        return None
    ticket_id = state.get("ticket_id")
    if ticket_id:
        committed = await store.find_one(
            mongo, {"_id": ticket_id, **store.RUNTIME_FILTER}
        )
        if committed is not None:
            return committed
    candidate_id = _as_int(state.get("candidate_thread_id"))
    return (
        await store.find_by_location(mongo, candidate_id)
        if candidate_id
        else None
    )


async def create_live_thread_ticket(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    guild_id: int,
    user_id: int,
    username: str,
    display_name: str | None,
    ticket_type: str,
    config: Mapping[str, Any],
) -> CreatedThreadTicket:
    """Create or resume one live thread ticket without duplicating resources."""
    if ticket_type not in {"main", "fwa"}:
        raise ThreadConfigurationError("ticket type must be main or fwa")
    # This call also installs the canonical ticket uniqueness indexes before
    # any destination thread can be created.
    await ensure_creation_indexes(mongo)
    parents = parents_from_config(config, guild_id, ticket_type)
    existing = await store.find_open_for_applicant(
        mongo, user_id=int(user_id), ticket_type=ticket_type
    )
    if existing is not None:
        return await _reconcile_existing_ticket(bot, mongo, existing)

    me = bot.get_me()
    if me is None:
        raise ThreadTicketError("bot identity is not available")
    await validate_thread_parents(
        bot.rest,
        parents,
        bot_user_id=int(me.id),
        applicant_user_id=int(user_id),
    )

    async with _creation_lock:
        # At most one iteration retires a terminal committed pair; the next
        # iteration allocates a new number and pair for the repeat application.
        for _pair_attempt in range(2):
            existing = await store.find_open_for_applicant(
                mongo, user_id=int(user_id), ticket_type=ticket_type
            )
            if existing is not None:
                return await _reconcile_existing_ticket(bot, mongo, existing)

            bound_ticket = await _committed_ticket_for_creation_state(
                mongo,
                guild_id=guild_id,
                user_id=user_id,
                ticket_type=ticket_type,
            )
            if bound_ticket is not None:
                if bound_ticket.get("status") == "open":
                    return await _reconcile_existing_ticket(bot, mongo, bound_ticket)
                await _mark_committed_creation_complete(mongo, bound_ticket)

            owner, state, resumed = await _claim_creation(
                mongo,
                guild_id=guild_id,
                user_id=user_id,
                username=username,
                display_name=display_name,
                ticket_type=ticket_type,
                parents=parents,
                now=utcnow(),
            )
            candidate = staff = None
            try:
                candidate, staff, state = await _ensure_live_thread_pair(
                    rest=bot.rest,
                    mongo=mongo,
                    state=state,
                    owner=owner,
                    bot_user_id=int(me.id),
                )
                ticket = store.new_ticket_document(
                    ticket_type=ticket_type,
                    ticket_number=int(state["ticket_number"]),
                    guild_id=int(guild_id),
                    public_thread_id=int(candidate.id),
                    public_parent_id=parents.candidate_parent_id,
                    staff_thread_id=int(staff.id),
                    staff_parent_id=parents.staff_parent_id,
                    user_id=int(user_id),
                    username=username,
                    display_name=display_name,
                )
                ticket["recruiter_role_id"] = parents.recruiter_role_id
                try:
                    ticket = await store.insert_one(mongo, ticket)
                except Exception:
                    committed = await store.find_by_location(mongo, int(candidate.id))
                    if committed is None:
                        raise
                    ticket = committed

                if ticket.get("status") != "open":
                    await _mark_committed_creation_complete(mongo, ticket)
                    continue

                delivery_complete = await _finish_committed_creation(
                    bot, mongo, ticket, reconcile_pair=False
                )
                await notify_console_after_change(
                    bot, mongo, ticket, reason="ticket created"
                )
                return CreatedThreadTicket(
                    ticket,
                    resumed=resumed,
                    delivery_pending=not delivery_complete,
                )
            except asyncio.CancelledError as error:
                await _cleanup_interrupted_creation(
                    rest=bot.rest,
                    mongo=mongo,
                    state=state,
                    owner=owner,
                    threads=(candidate, staff),
                    error=error,
                )
                raise
            except Exception as error:
                await _cleanup_interrupted_creation(
                    rest=bot.rest,
                    mongo=mongo,
                    state=state,
                    owner=owner,
                    threads=(candidate, staff),
                    error=error,
                )
                raise
        raise ThreadTicketError("terminal ticket replay could not allocate a fresh pair")


def _ticket_thread_ids(ticket: Mapping[str, Any]) -> tuple[int, int]:
    location = ticket.get("location") or {}
    public_id = _as_int(location.get("id") or ticket.get("channel_id"))
    staff_id = _as_int(location.get("staff_space_id") or ticket.get("thread_id"))
    if not public_id or not staff_id:
        raise ThreadTicketError("ticket does not contain a complete thread pair")
    return public_id, staff_id


async def archive_ticket_pair(rest: hikari.api.RESTClient, ticket: Mapping[str, Any]) -> None:
    """Lock and archive both terminal-ticket threads, idempotently."""
    public_id, staff_id = _ticket_thread_ids(ticket)
    errors: list[Exception] = []
    for thread_id in (public_id, staff_id):
        try:
            channel = await rest.fetch_channel(thread_id)
            if bool(getattr(channel, "is_archived", False)) and bool(getattr(channel, "is_locked", False)):
                continue
            await rest.edit_channel(
                thread_id,
                locked=True,
                archived=True,
                reason="Archiving resolved ticket",
            )
        except Exception as error:
            errors.append(error)
    if errors:
        raise ThreadTicketError(
            f"failed to archive {len(errors)} thread(s): {type(errors[0]).__name__}"
        ) from errors[0]


async def reconcile_ticket_pair(rest: hikari.api.RESTClient, ticket: Mapping[str, Any]) -> None:
    """Make Discord state agree with the ticket's permanent Mongo status."""
    status = ticket.get("status")
    public_id, staff_id = _ticket_thread_ids(ticket)
    if status in {"approved", "denied"}:
        await archive_ticket_pair(rest, ticket)
        return
    if status != "open":
        raise ThreadTicketError(f"unsupported ticket status {status!r}")
    for thread_id in (public_id, staff_id):
        channel = await rest.fetch_channel(thread_id)
        if bool(getattr(channel, "is_archived", False)) or bool(getattr(channel, "is_locked", False)):
            await rest.edit_channel(
                thread_id,
                locked=False,
                archived=False,
                reason="Restoring active open ticket",
            )


async def recover_pending_thread_ticket_creations(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    limit: int = 50,
) -> dict[str, int]:
    """Resume expired, operator-authorized live creation attempts at startup."""
    await ensure_creation_indexes(mongo)
    amount = max(1, min(int(limit), 100))
    now = utcnow()
    cursor = mongo.ticket_creation_state.find({
        "kind": "thread_ticket_creation",
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
        ticket_type = str(state.get("ticket_type") or "")
        config = {
            "ticket_target_guild_id": state.get("guild_id"),
            f"{ticket_type}_candidate_parent": state.get("candidate_parent_id"),
            f"{ticket_type}_staff_parent": state.get("staff_parent_id"),
            f"{ticket_type}_recruiter_role": state.get("recruiter_role_id"),
        }
        try:
            result = await create_live_thread_ticket(
                bot=bot,
                mongo=mongo,
                guild_id=_as_int(state.get("guild_id")),
                user_id=_as_int(state.get("user_id")),
                username=str(state.get("username") or "candidate"),
                display_name=str(state.get("display_name") or "") or None,
                ticket_type=ticket_type,
                config=config,
            )
        except Exception:
            counts["failed"] += 1
            _log.exception("startup ticket creation recovery failed for %s", state.get("_id"))
        else:
            if result.delivery_pending:
                counts["failed"] += 1
                continue
            counts["completed"] += 1
    return counts
