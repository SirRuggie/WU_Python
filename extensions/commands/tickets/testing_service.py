"""Mongo boundary for Discord ticket exercises.

Every mutable collection exposed here belongs to the separate ``ticket_testing``
database. A test workflow must select this scope before claiming a slot or
reserving a number; a retry retains the same scope and the test marker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pymongo import ReturnDocument


DATABASE_NAME = "ticket_testing"
MODE = "test"
COUNTER_ID = "test_ticket_numbers"


class TestTicketMongo:
    """Narrow, fail-closed collection facade for test ticket operations."""

    is_ticket_test_scope = True
    _collections = frozenset({
        "tickets", "ticket_creation_state", "ticket_open_slots",
        "ticket_rollout", "ticket_flags", "ticket_automation_state",
        "ticket_setup", "ticket_migrations", "button_store",
        "component_state", "bot_config",
    })

    def __init__(self, mongo: Any):
        self._database = mongo.get_database(DATABASE_NAME)
        for name in self._collections:
            setattr(self, name, self._database.get_collection(name))

    def __getattr__(self, name: str):
        raise AttributeError(f"{name} is unavailable in the test ticket scope")


def test_mongo(mongo: Any) -> TestTicketMongo:
    if is_test_scope(mongo):
        return mongo
    return TestTicketMongo(mongo)


def is_test_scope(mongo: Any) -> bool:
    return getattr(mongo, "is_ticket_test_scope", False) is True


def is_test_ticket(ticket: Mapping[str, Any] | None) -> bool:
    return bool(ticket and ticket.get("mode") == MODE)


async def snapshot_ticket_config(mongo: Any, scoped: TestTicketMongo) -> dict:
    """Copy production parent/role IDs into the test database for retries."""
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    source = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    fields = {
        key: source.get(key)
        for key in (
            "ticket_target_guild_id", "main_candidate_parent", "main_staff_parent",
            "main_thread_recruiter_role", "fwa_candidate_parent", "fwa_staff_parent",
            "fwa_thread_recruiter_role",
        )
    }
    fields.update({"mode": MODE, "copied_at": datetime.now(timezone.utc)})
    await scoped.ticket_setup.update_one(
        {"_id": "config"}, {"$set": fields}, upsert=True,
    )
    return {"_id": "config", **fields}


async def reserve_test_ticket_number(scoped: TestTicketMongo) -> int:
    """Reserve a global TEST number in the test database only."""
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    row = await scoped.ticket_rollout.find_one_and_update(
        {"_id": COUNTER_ID},
        {
            "$setOnInsert": {"mode": MODE, "kind": "test_ticket_counter"},
            "$inc": {"number": 1},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if row is None:
        raise RuntimeError("test ticket number reservation failed")
    return int(row["number"])


def number_label(ticket_number: int) -> str:
    return f"TEST{int(ticket_number):03d}"


WINDOW_ID = "test_window"


async def open_window(
    scoped: TestTicketMongo,
    *,
    guild_id: int,
    actor_id: int,
    duration_minutes: int,
    allowed_user_ids=(),
    allowed_role_ids=(),
    allow_admins: bool = True,
    cleanup_minutes: int = 60,
) -> dict:
    """Open a bounded opt-in window in the test database."""
    from datetime import timedelta
    import uuid

    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    if not 1 <= int(duration_minutes) <= 1440:
        raise ValueError("duration_minutes must be 1-1440")
    if not 0 <= int(cleanup_minutes) <= 10080:
        raise ValueError("cleanup_minutes must be 0-10080")
    now = datetime.now(timezone.utc)
    user_ids = sorted({int(value) for value in allowed_user_ids if int(value) > 0})
    role_ids = sorted({int(value) for value in allowed_role_ids if int(value) > 0})
    window = {
        "mode": MODE,
        "generation": uuid.uuid4().hex,
        "guild_id": int(guild_id),
        "opened_by": int(actor_id),
        "opened_at": now,
        "expires_at": now + timedelta(minutes=int(duration_minutes)),
        "cleanup_at": now + timedelta(minutes=int(duration_minutes) + int(cleanup_minutes)),
        "allowed_user_ids": user_ids,
        "allowed_role_ids": role_ids,
        "allow_admins": bool(allow_admins),
        "clear_requested_at": None,
        "cleanup_minutes": int(cleanup_minutes),
    }
    await scoped.ticket_automation_state.update_one(
        {"_id": WINDOW_ID}, {"$set": window}, upsert=True,
    )
    return {"_id": WINDOW_ID, **window}


async def active_window(scoped: TestTicketMongo, now: datetime | None = None) -> dict | None:
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    now = now or datetime.now(timezone.utc)
    row = await scoped.ticket_automation_state.find_one({"_id": WINDOW_ID, "mode": MODE})
    if row is None or row.get("clear_requested_at") is not None:
        return None
    expires_at = row.get("expires_at")
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return row if expires_at > now else None


def user_allowed(window: Mapping[str, Any] | None, user_id: int, role_ids=(), is_admin: bool = False) -> bool:
    if not window or window.get("mode") != MODE:
        return False
    if int(user_id) in {int(value) for value in window.get("allowed_user_ids") or ()}:
        return True
    if {int(value) for value in role_ids} & {
        int(value) for value in window.get("allowed_role_ids") or ()
    }:
        return True
    return bool(is_admin and window.get("allow_admins"))


async def request_clear(scoped: TestTicketMongo) -> None:
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    now = datetime.now(timezone.utc)
    await scoped.ticket_automation_state.update_one(
        {"_id": WINDOW_ID, "mode": MODE},
        {"$set": {"clear_requested_at": now, "cleanup_at": now}},
    )
    await scoped.tickets.update_many(
        {"mode": MODE}, {"$set": {"cleanup_at": now}},
    )
    await scoped.ticket_creation_state.update_many(
        {"mode": MODE}, {"$set": {"cleanup_at": now}},
    )


class TestRESTGuard:
    """Allow writes only to threads persisted in the test database."""

    _thread_mutations = frozenset({
        "add_thread_member", "remove_thread_member", "create_message",
        "edit_message", "delete_message", "edit_channel", "delete_channel",
    })
    _blocked_mutations = frozenset({
        "add_role_to_member", "remove_role_from_member", "create_dm_channel",
        "create_guild_channel", "edit_guild", "delete_guild_channel",
        "create_role", "edit_role", "delete_role", "ban_user", "kick_user",
    })

    def __init__(self, rest: Any, scoped: TestTicketMongo):
        self._rest = rest
        self._scoped = scoped
        self._new_thread_ids: set[int] = set()

    async def _test_parents(self) -> dict:
        row = await self._scoped.ticket_automation_state.find_one({
            "_id": "test_parents", "mode": MODE,
        }) or {}
        if not row.get("marker") or not row.get("guild_id"):
            raise PermissionError("test parents are not durably configured")
        return row

    async def _owned_thread(self, thread_id: int) -> bool:
        thread_id = int(thread_id)
        found = thread_id in self._new_thread_ids
        if not found:
            filt = {"mode": MODE, "$or": [
                {"location.id": thread_id}, {"location.staff_space_id": thread_id},
            ]}
            found = bool(await self._scoped.tickets.find_one(filt, {"_id": 1}))
        if not found:
            found = bool(await self._scoped.ticket_creation_state.find_one({
                "mode": MODE,
                "$or": [
                    {"candidate_thread_id": thread_id}, {"staff_thread_id": thread_id},
                ],
            }, {"_id": 1}))
        if not found:
            return False
        parents = await self._test_parents()
        thread = await self._rest.fetch_channel(thread_id)
        parent_id = int(getattr(thread, "parent_id", 0) or 0)
        if (int(getattr(thread, "guild_id", 0) or 0) != int(parents["guild_id"])
            or parent_id not in {int(parents.get("candidate_parent_id") or 0),
                                 int(parents.get("staff_parent_id") or 0)}
            or "TEST" not in str(getattr(thread, "name", ""))):
            return False
        parent = await self._rest.fetch_channel(parent_id)
        return (int(getattr(parent, "guild_id", 0) or 0) == int(parents["guild_id"])
                and getattr(parent, "topic", None) == parents["marker"])

    def __getattr__(self, name: str):
        method = getattr(self._rest, name)
        if name in self._blocked_mutations:
            async def blocked(*args, **kwargs):
                raise PermissionError(f"{name} is forbidden in ticket test mode")
            return blocked
        if name == "create_thread":
            async def create_thread(*args, **kwargs):
                parent_id = int(args[0] if args else kwargs.get("channel"))
                configured = await self._test_parents()
                parents = {
                    int(configured.get("candidate_parent_id") or 0),
                    int(configured.get("staff_parent_id") or 0),
                }
                thread_name = str(args[2] if len(args) > 2 else kwargs.get("name") or "")
                if parent_id not in parents or "TEST" not in thread_name:
                    raise PermissionError("test thread creation requires a configured test parent and name")
                parent = await self._rest.fetch_channel(parent_id)
                if (int(getattr(parent, "guild_id", 0)) != int(configured["guild_id"])
                    or getattr(parent, "topic", None) != configured["marker"]):
                    raise PermissionError("test parent ownership could not be verified")
                created = await method(*args, **kwargs)
                self._new_thread_ids.add(int(created.id))
                return created
            return create_thread
        if name in self._thread_mutations:
            async def guarded(*args, **kwargs):
                channel_id = kwargs.get("channel", kwargs.get("channel_id", args[0] if args else None))
                if channel_id is None or not await self._owned_thread(int(channel_id)):
                    raise PermissionError(f"{name} requires a persisted test thread")
                if name in {"create_message", "edit_message"}:
                    kwargs = dict(kwargs)
                    kwargs["role_mentions"] = False
                    kwargs["mentions_everyone"] = False
                    try:
                        from utils.ticket_testing_context import prefix_payload
                    except ImportError:
                        pass
                    else:
                        kwargs = prefix_payload(kwargs)
                return await method(*args, **kwargs)
            return guarded
        if callable(method) and not name.startswith(("fetch_", "get_")):
            async def blocked_unknown(*args, **kwargs):
                raise PermissionError(f"{name} is unavailable in ticket test mode")
            return blocked_unknown
        return method


class TestBotGuard:
    def __init__(self, bot: Any, scoped: TestTicketMongo):
        self._bot = bot
        self.rest = TestRESTGuard(bot.rest, scoped)

    def __getattr__(self, name: str):
        return getattr(self._bot, name)


def test_bot(bot: Any, scoped: TestTicketMongo) -> TestBotGuard:
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    return TestBotGuard(bot, scoped)


async def claim_test_slot(
    scoped: TestTicketMongo, *, guild_id: int, user_id: int, ticket_type: str,
):
    """Claim an isolated slot without consulting the production rollout."""
    import secrets
    from datetime import timedelta
    from pymongo.errors import DuplicateKeyError
    from extensions.commands import ticket_runtime

    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    if ticket_type not in {"main", "fwa"}:
        raise ValueError("ticket_type must be main or fwa")
    window = await active_window(scoped)
    if window is None or int(window.get("guild_id") or 0) != int(guild_id):
        raise ValueError("ticket test window is not active in this guild")
    await ticket_runtime.ensure_indexes(scoped)
    now = datetime.now(timezone.utc)
    slot_id = f"ticket-open:{int(user_id)}:{ticket_type}"
    workflow_id = f"thread:{int(user_id)}:{ticket_type}"
    for _ in range(3):
        current = await scoped.ticket_open_slots.find_one({"_id": slot_id})
        if current is not None:
            if current.get("mode") != MODE:
                raise ValueError("unmarked test slot cannot be used")
            if current.get("window_generation") != window.get("generation"):
                raise ValueError("a previous test ticket is waiting for cleanup")
            ticket = await scoped.tickets.find_one({
                "_id": current.get("ticket_id"), "mode": MODE,
            }) if current.get("ticket_id") else None
            if ticket is not None and ticket.get("status") in {"approved", "denied", "closed"}:
                await scoped.ticket_open_slots.delete_one({
                    "_id": slot_id, "ticket_id": current.get("ticket_id"),
                    "mode": MODE,
                })
                continue
            if current.get("state") == ticket_runtime.SLOT_RESERVED:
                return await ticket_runtime.resume_open_slot(
                    scoped, slot_id=slot_id, workflow_id=workflow_id,
                    route=ticket_runtime.ROUTE_THREAD, guild_id=guild_id,
                    now=now, lease_seconds=600,
                )
            return ticket_runtime.SlotClaim(False, None, current)
        token = secrets.token_urlsafe(24)
        document = {
            "_id": slot_id, "schema_version": 1, "mode": MODE,
            "window_generation": window.get("generation"),
            "user_id": int(user_id), "ticket_type": ticket_type,
            "route": ticket_runtime.ROUTE_THREAD, "guild_id": int(guild_id),
            "workflow_id": workflow_id, "rollout_revision": 1,
            "state": ticket_runtime.SLOT_RESERVED, "owner_token": token,
            "lease_until": now + timedelta(minutes=10),
            "created_at": now, "updated_at": now,
        }
        try:
            await scoped.ticket_open_slots.insert_one(document)
        except DuplicateKeyError:
            continue
        return ticket_runtime.SlotClaim(True, token, document)
    raise RuntimeError("test ticket slot changed while it was being claimed")


async def cleanup_due(bot: Any, scoped: TestTicketMongo, *, now: datetime | None = None) -> int:
    """Delete only marked test threads, retrying each bound pair after failures.

    A row stays in the test database until both thread deletions are confirmed.
    The checkpoint is keyed by test ticket/lease ID and retains successful
    per-thread work across restarts. No production collection is queried.
    """
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    now = now or datetime.now(timezone.utc)
    window = await scoped.ticket_automation_state.find_one({"_id": WINDOW_ID, "mode": MODE}) or {}
    clearing = window.get("clear_requested_at") is not None
    query = {"mode": MODE} if clearing else {"mode": MODE, "cleanup_at": {"$lte": now}}
    tickets = await scoped.tickets.find(query).limit(100).to_list(length=100)
    leases = await scoped.ticket_creation_state.find(query).limit(100).to_list(length=100)
    completed = 0
    for source, row in (("ticket", row) for row in tickets):
        try:
            if await _cleanup_row(bot, scoped, source, row):
                completed += 1
        except Exception as error:
            await _record_cleanup_error(scoped, source, row, error)
    ticket_ids = {str(row.get("_id")) for row in tickets}
    for row in leases:
        if str(row.get("ticket_id") or "") in ticket_ids:
            continue
        try:
            if await _cleanup_row(bot, scoped, "lease", row):
                completed += 1
        except Exception as error:
            await _record_cleanup_error(scoped, "lease", row, error)
    return completed


async def _record_cleanup_error(scoped, source, row, error):
    await scoped.ticket_automation_state.update_one(
        {"_id": f"test_cleanup:{source}:{row['_id']}"},
        {"$set": {"mode": MODE, "kind": "test_cleanup", "state": "retry",
                  "last_error": type(error).__name__,
                  "updated_at": datetime.now(timezone.utc)},
         "$inc": {"attempts": 1}},
        upsert=True,
    )


async def _cleanup_row(bot: Any, scoped: TestTicketMongo, source: str, row: Mapping[str, Any]) -> bool:
    import hikari

    if row.get("mode") != MODE:
        return False
    checkpoint_id = f"test_cleanup:{source}:{row['_id']}"
    checkpoint = await scoped.ticket_automation_state.find_one({"_id": checkpoint_id}) or {}
    candidate_id = int(
        (row.get("location") or {}).get("id") or row.get("candidate_thread_id") or 0
    )
    staff_id = int(
        (row.get("location") or {}).get("staff_space_id") or row.get("staff_thread_id") or 0
    )
    candidate_parent = int(
        (row.get("location") or {}).get("public_parent_id") or row.get("candidate_parent_id") or 0
    )
    staff_parent = int(
        (row.get("location") or {}).get("staff_parent_id") or row.get("staff_parent_id") or 0
    )
    parents = await scoped.ticket_automation_state.find_one({
        "_id": "test_parents", "mode": MODE,
    }) or {}
    if not parents.get("marker") or not parents.get("guild_id"):
        raise RuntimeError("test cleanup cannot verify private parent ownership")
    if candidate_parent != int(parents.get("candidate_parent_id") or 0) or staff_parent != int(parents.get("staff_parent_id") or 0):
        raise RuntimeError("test cleanup refused a row bound outside the private test parents")
    ids = (("candidate", candidate_id, candidate_parent), ("staff", staff_id, staff_parent))
    for role, thread_id, parent_id in ids:
        if not thread_id or checkpoint.get(role) is True:
            continue
        if not parent_id:
            raise RuntimeError("test cleanup cannot verify thread parent")
        try:
            channel = await bot.rest.fetch_channel(thread_id)
        except hikari.NotFoundError:
            channel = None
        if channel is not None:
            name = str(getattr(channel, "name", ""))
            if (int(getattr(channel, "parent_id", 0) or 0) != parent_id
                or int(getattr(channel, "guild_id", 0) or 0) != int(parents["guild_id"])
                or "TEST" not in name):
                raise RuntimeError("test cleanup refused a thread with unverified parent or name")
            parent = await bot.rest.fetch_channel(parent_id)
            if (int(getattr(parent, "guild_id", 0) or 0) != int(parents["guild_id"])
                or getattr(parent, "topic", None) != parents["marker"]):
                raise RuntimeError("test cleanup refused a parent with invalid ownership marker")
            await bot.rest.delete_channel(thread_id, reason="Clearing isolated test ticket")
        await scoped.ticket_automation_state.update_one(
            {"_id": checkpoint_id},
            {"$set": {"mode": MODE, "kind": "test_cleanup", role: True,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    if source == "ticket":
        await scoped.tickets.delete_one({"_id": row["_id"], "mode": MODE})
        await scoped.ticket_open_slots.delete_many({"ticket_id": row["_id"], "mode": MODE})
    else:
        await scoped.ticket_creation_state.delete_one({"_id": row["_id"], "mode": MODE})
        await scoped.ticket_open_slots.delete_many({"workflow_id": row["_id"], "mode": MODE})
    await scoped.ticket_automation_state.update_one(
        {"_id": checkpoint_id},
        {"$set": {"state": "complete", "completed_at": datetime.now(timezone.utc)}},
    )
    return True


async def ensure_test_indexes(scoped: TestTicketMongo) -> None:
    """Install isolated indexes without touching production index caches."""
    if not is_test_scope(scoped):
        raise ValueError("a test database scope is required")
    from extensions.commands import ticket_runtime
    from extensions.commands.tickets import console, flag_store, store, thread_service
    from utils.component_state import TTL_INDEX_NAME

    await ticket_runtime.ensure_indexes(scoped)
    await store._install_indexes(scoped)
    await flag_store.ensure_indexes(scoped)
    await thread_service.ensure_creation_indexes(scoped)
    await console.ensure_staff_context_indexes(scoped)
    await scoped.component_state.create_index(
        "expires_at", expireAfterSeconds=0, name=TTL_INDEX_NAME,
    )
