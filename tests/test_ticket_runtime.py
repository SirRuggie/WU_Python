import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import uuid

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from extensions.commands import ticket_runtime as runtime


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
MISSING = object()


def _get(document, path, default=MISSING):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _set(document, path, value):
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _unset(document, path):
    parts = path.split(".")
    target = document
    for part in parts[:-1]:
        target = target.get(part, {})
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def _condition(actual, expected):
    exists = actual is not MISSING
    if not isinstance(expected, dict) or not any(
        str(key).startswith("$") for key in expected
    ):
        return exists and actual == expected
    for operator, operand in expected.items():
        if operator == "$exists":
            if exists != bool(operand):
                return False
        elif operator == "$in":
            if not exists or actual not in operand:
                return False
        elif operator == "$nin":
            if exists and actual in operand:
                return False
        elif operator == "$ne":
            if exists and actual == operand:
                return False
        elif operator == "$lte":
            if not exists or actual > operand:
                return False
        elif operator == "$not":
            pattern = operand.get("$regex") if isinstance(operand, dict) else None
            if pattern is None:
                raise AssertionError(f"unsupported $not condition: {operand!r}")
            if exists and str(actual).startswith(str(pattern).removeprefix("^")):
                return False
        else:
            raise AssertionError(f"unsupported operator: {operator}")
    return True


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
        elif key == "$and":
            if not all(_matches(document, clause) for clause in expected):
                return False
        elif not _condition(_get(document, key), expected):
            return False
    return True


def _apply(document, update, *, inserting=False):
    if inserting:
        for path, value in update.get("$setOnInsert", {}).items():
            _set(document, path, value)
    for path, value in update.get("$set", {}).items():
        _set(document, path, value)
    for path in update.get("$unset", {}):
        _unset(document, path)
    for path, amount in update.get("$inc", {}).items():
        current = _get(document, path, 0)
        _set(document, path, current + amount)
    for path, value in update.get("$max", {}).items():
        current = _get(document, path)
        if current is MISSING or value > current:
            _set(document, path, value)
    for path, value in update.get("$push", {}).items():
        current = list(_get(document, path, []))
        current.extend(deepcopy(value.get("$each", []))) if isinstance(
            value, dict
        ) and "$each" in value else current.append(deepcopy(value))
        _set(document, path, current)
    for path, value in update.get("$addToSet", {}).items():
        current = list(_get(document, path, []))
        additions = value.get("$each", []) if isinstance(value, dict) else [value]
        for item in additions:
            if item not in current:
                current.append(deepcopy(item))
        _set(document, path, current)


class Result:
    def __init__(self, matched=0, modified=None, deleted=0):
        self.matched_count = matched
        self.modified_count = matched if modified is None else modified
        self.deleted_count = deleted


class Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, spec, direction=None):
        specs = [(spec, direction)] if isinstance(spec, str) else list(spec)
        for path, order in reversed(specs):
            self.documents.sort(
                key=lambda item: str(_get(item, path, "")), reverse=int(order) < 0
            )
        return self

    def limit(self, amount):
        self.documents = self.documents[: int(amount)]
        return self

    async def to_list(self, length=None):
        rows = self.documents if length is None else self.documents[:length]
        return deepcopy(rows)


class Collection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}
        self.indexes = []
        self._lock = asyncio.Lock()

    async def find_one(self, query, *_args, **_kwargs):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query, *_args, **_kwargs):
        return Cursor(
            document for document in self.documents.values() if _matches(document, query)
        )

    async def count_documents(self, query):
        return sum(_matches(document, query) for document in self.documents.values())

    async def insert_one(self, document):
        async with self._lock:
            if document["_id"] in self.documents or any(
                item.get("workflow_id") == document.get("workflow_id")
                for item in self.documents.values()
                if document.get("workflow_id") is not None
            ):
                raise DuplicateKeyError("duplicate")
            self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, *, upsert=False, **_kwargs):
        async with self._lock:
            for key, document in self.documents.items():
                if _matches(document, query):
                    before = deepcopy(document)
                    _apply(document, update)
                    self.documents[key] = document
                    return Result(1, int(before != document))
            if not upsert:
                return Result()
            document = {
                path: deepcopy(value)
                for path, value in query.items()
                if not path.startswith("$") and not isinstance(value, dict)
            }
            _apply(document, update, inserting=True)
            self.documents[document["_id"]] = document
            return Result(0, 0)

    async def find_one_and_update(self, query, update, *, upsert=False, **_kwargs):
        async with self._lock:
            for key, document in self.documents.items():
                if _matches(document, query):
                    _apply(document, update)
                    self.documents[key] = document
                    return deepcopy(document)
            if not upsert:
                return None
            document = {
                path: deepcopy(value)
                for path, value in query.items()
                if not path.startswith("$") and not isinstance(value, dict)
            }
            _apply(document, update, inserting=True)
            self.documents[document["_id"]] = document
            return deepcopy(document)

    async def delete_one(self, query):
        async with self._lock:
            for key, document in list(self.documents.items()):
                if _matches(document, query):
                    del self.documents[key]
                    return Result(deleted=1)
        return Result()

    async def create_index(self, spec, **kwargs):
        self.indexes.append((spec, kwargs))
        return kwargs.get("name")


def _mongo(
    *,
    rollout=(),
    legacy=(),
    thread=(),
    slots=(),
    creation=(),
    migration=(),
    automation=(),
):
    return SimpleNamespace(
        ticket_rollout=Collection(rollout),
        ticket_open_slots=Collection(slots),
        button_store=Collection(legacy),
        tickets=Collection(thread),
        ticket_creation_state=Collection(creation),
        ticket_migrations=Collection(migration),
        ticket_automation_state=Collection(automation),
        ticket_setup=Collection([{"_id": "config"}]),
    )


def _source(message=30, *, guild=10, channel=20):
    return {"guild_id": guild, "channel_id": channel, "message_id": message}


def _rollout(phase=runtime.PHASE_PILOT, revision=4):
    return {
        "_id": runtime.ROLLOUT_ID,
        "schema_version": runtime.ROLLOUT_SCHEMA_VERSION,
        "phase": phase,
        "revision": revision,
        "legacy_intake": _source(30),
        "thread_intake": _source(31, guild=11, channel=21),
        "pilot": {
            "intake": _source(40, guild=11, channel=22),
            "user_ids": [50],
            "role_ids": [60],
            "ticket_types": ["main", "fwa"],
        },
    }


def _cross_rollout(phase=runtime.PHASE_PILOT, revision=4):
    return {
        "_id": runtime.ROLLOUT_ID,
        "schema_version": runtime.ROLLOUT_SCHEMA_VERSION,
        "phase": phase,
        "revision": revision,
        "legacy_intake": {
            "guild_id": 10, "channel_id": 20, "message_id": 30,
        },
        "thread_intake": {
            "guild_id": 11, "channel_id": 21, "message_id": 31,
        },
        "pilot": {
            "intake": {"guild_id": 11, "channel_id": 22, "message_id": 40},
            "user_ids": [50],
            "role_ids": [60],
            "ticket_types": ["main", "fwa"],
        },
    }


def _ticket(identifier, *, user, route, status="open", number=1, location=100):
    document = {
        "_id": identifier,
        "type": "ticket",
        "ticket_type": "main",
        "ticket_number": number,
        "guild_id": 10,
        "user_id": user,
        "status": status,
    }
    if route == runtime.ROUTE_THREAD:
        document.update(
            {
                "venue": "thread",
                "runtime": runtime.THREAD_RUNTIME,
                "location": {"id": location, "staff_space_id": location + 1},
            }
        )
    else:
        document["channel_id"] = location
    return document


def test_cross_server_routing_uses_exact_phase_source_matrix():
    async def scenario():
        missing = _mongo()
        unconfigured = await runtime.route_public_intake(
            missing,
            requested_route=runtime.ROUTE_THREAD,
            guild_id=999,
            channel_id=999,
            message_id=999,
            user_id=50,
            ticket_type="main",
        )
        assert not unconfigured.allowed
        assert unconfigured.reason == "rollout_not_configured"

        expected = {
            runtime.PHASE_LEGACY_ONLY: (False, False),
            runtime.PHASE_PREPARED: (False, False),
            runtime.PHASE_PILOT: (False, True),
            runtime.PHASE_THREAD_DEFAULT: (True, False),
            runtime.PHASE_ROLLBACK_LEGACY: (False, False),
            runtime.PHASE_THREAD_ONLY: (True, False),
        }
        for phase, outcomes in expected.items():
            mongo = _mongo(rollout=[_cross_rollout(phase)])
            public = await runtime.route_public_intake(
                mongo,
                requested_route=runtime.ROUTE_THREAD,
                guild_id=11,
                channel_id=21,
                message_id=31,
                user_id=50,
                ticket_type="main",
            )
            pilot = await runtime.route_public_intake(
                mongo,
                requested_route=runtime.ROUTE_THREAD,
                guild_id=11,
                channel_id=22,
                message_id=40,
                user_id=50,
                ticket_type="main",
            )
            assert (public.allowed, pilot.allowed) == outcomes

            copied = await runtime.route_public_intake(
                mongo,
                requested_route=runtime.ROUTE_THREAD,
                guild_id=11,
                channel_id=21,
                message_id=999,
                user_id=50,
                ticket_type="main",
            )
            assert not copied.allowed

    asyncio.run(scenario())


def test_cross_server_claim_and_resume_are_guild_fenced_before_mutation():
    async def scenario():
        mongo = _mongo(rollout=[_cross_rollout()])
        with pytest.raises(runtime.RolloutConflict):
            await runtime.claim_open_slot(
                mongo,
                user_id=71,
                ticket_type="main",
                route=runtime.ROUTE_THREAD,
                guild_id=10,
                workflow_id="thread:71:main",
                rollout_revision=4,
                now=NOW,
            )
        assert "ticket-open:71:main" not in mongo.ticket_open_slots.documents

        reserved = {
            "_id": "ticket-open:72:main",
            "workflow_id": "thread:72:main",
            "route": runtime.ROUTE_THREAD,
            "guild_id": 11,
            "state": runtime.SLOT_RESERVED,
            "lease_until": NOW - timedelta(seconds=1),
        }
        mongo.ticket_open_slots.documents[reserved["_id"]] = deepcopy(reserved)
        wrong = await runtime.resume_open_slot(
            mongo,
            slot_id=reserved["_id"],
            workflow_id=reserved["workflow_id"],
            route=runtime.ROUTE_THREAD,
            guild_id=10,
            now=NOW,
        )
        assert not wrong.won
        right = await runtime.resume_open_slot(
            mongo,
            slot_id=reserved["_id"],
            workflow_id=reserved["workflow_id"],
            route=runtime.ROUTE_THREAD,
            guild_id=11,
            now=NOW,
        )
        assert right.won

    asyncio.run(scenario())


def test_mismatched_target_panel_guilds_are_rejected_before_rollout_write():
    async def scenario():
        malformed_document = _cross_rollout()
        malformed_document["thread_intake"]["guild_id"] = 10
        malformed_document["pilot"]["intake"]["guild_id"] = 10
        malformed = await runtime.get_rollout(
            _mongo(rollout=[malformed_document])
        )
        assert not malformed.valid

        mongo = _mongo(rollout=[_cross_rollout()])
        before = deepcopy(mongo.ticket_rollout.documents[runtime.ROLLOUT_ID])
        same_guild_thread = {
            **before["thread_intake"],
            "guild_id": before["legacy_intake"]["guild_id"],
        }
        same_guild_pilot = {
            **before["pilot"],
            "intake": {
                **before["pilot"]["intake"],
                "guild_id": before["legacy_intake"]["guild_id"],
            },
        }
        with pytest.raises(ValueError, match="different guilds"):
            await runtime.configure_rollout(
                mongo,
                expected_revision=4,
                actor_id=1,
                legacy_intake=before["legacy_intake"],
                thread_intake=same_guild_thread,
                pilot=same_guild_pilot,
                now=NOW,
            )
        assert mongo.ticket_rollout.documents[runtime.ROLLOUT_ID] == before

        empty = _mongo()
        with pytest.raises(ValueError, match="different guilds"):
            await runtime.seed_rollout(
                empty,
                actor_id=1,
                legacy_intake=before["legacy_intake"],
                thread_intake=same_guild_thread,
                pilot=same_guild_pilot,
                now=NOW,
            )
        assert runtime.ROLLOUT_ID not in empty.ticket_rollout.documents

        with pytest.raises(ValueError, match="same target guild"):
            await runtime.configure_rollout(
                mongo,
                expected_revision=4,
                actor_id=1,
                legacy_intake=before["legacy_intake"],
                thread_intake=before["thread_intake"],
                pilot={
                    **before["pilot"],
                    "intake": {
                        "guild_id": 12, "channel_id": 22, "message_id": 40,
                    },
                },
                now=NOW,
            )
        assert mongo.ticket_rollout.documents[runtime.ROLLOUT_ID] == before
        with pytest.raises(ValueError, match="separate channels"):
            await runtime.configure_rollout(
                mongo,
                expected_revision=4,
                actor_id=1,
                legacy_intake=before["legacy_intake"],
                thread_intake=before["thread_intake"],
                pilot={
                    **before["pilot"],
                    "intake": {
                        "guild_id": 11, "channel_id": 21, "message_id": 40,
                    },
                },
                now=NOW,
            )
        assert mongo.ticket_rollout.documents[runtime.ROLLOUT_ID] == before

    asyncio.run(scenario())


def test_backfill_normalizes_mixed_ids_binds_locations_and_quarantines_dual_open():
    async def scenario():
        legacy = _ticket("legacy-1", user="80", route=runtime.ROUTE_LEGACY, location=801)
        thread = _ticket("thread-1", user=80, route=runtime.ROUTE_THREAD, location=802)
        mirrored = _ticket("mirror", user=90, route=runtime.ROUTE_THREAD, location=900)
        mongo = _mongo(rollout=[_rollout()], legacy=[legacy, mirrored], thread=[thread])
        result = await runtime.backfill_open_slots(mongo, now=NOW)
        assert result.conflicted_slot_ids == ("ticket-open:80:main",)
        slot = mongo.ticket_open_slots.documents["ticket-open:80:main"]
        assert slot["state"] == runtime.SLOT_CLEANUP_REQUIRED
        assert slot["cleanup_reason"] == "multiple_authoritative_open_tickets"
        assert "ticket-open:90:main" not in mongo.ticket_open_slots.documents
        assert mongo.button_store.documents["legacy-1"]["runtime"] == runtime.LEGACY_RUNTIME
        assert mongo.button_store.documents["legacy-1"]["open_slot_id"] == slot["_id"]

        still_conflicted = await runtime.reconcile_open_slots(mongo, now=NOW)
        assert slot["_id"] in still_conflicted.unchanged_slot_ids
        assert mongo.ticket_open_slots.documents[slot["_id"]]["state"] == (
            runtime.SLOT_CLEANUP_REQUIRED
        )

        mongo.button_store.documents["legacy-1"]["status"] = "denied"
        repaired = await runtime.reconcile_open_slots(mongo, now=NOW)
        assert repaired.bound_slot_ids == (slot["_id"],)
        rebound = mongo.ticket_open_slots.documents[slot["_id"]]
        assert rebound["state"] == runtime.SLOT_OPEN
        assert rebound["route"] == runtime.ROUTE_THREAD
        assert rebound["ticket_id"] == "thread-1"
        assert "cleanup_reason" not in rebound
        assert mongo.tickets.documents["thread-1"]["open_slot_id"] == slot["_id"]

    asyncio.run(scenario())


def test_backfill_resumes_late_legacy_commit_from_preserved_slot():
    async def scenario():
        workflow_id = "legacy:111:7:main"
        ticket = _ticket(
            "ticket_444",
            user=7,
            route=runtime.ROUTE_LEGACY,
            location=444,
        )
        ticket.update({
            "guild_id": 111,
            "creation_workflow_id": workflow_id,
        })
        reserved = {
            "_id": "ticket-open:7:main",
            "schema_version": 1,
            "user_id": 7,
            "ticket_type": "main",
            "route": runtime.ROUTE_LEGACY,
            "guild_id": 111,
            "workflow_id": workflow_id,
            "rollout_revision": 4,
            "state": runtime.SLOT_RESERVED,
            "owner_token": "preserved-owner",
            "lease_until": NOW - timedelta(seconds=1),
        }
        uncertain = {
            "_id": "111:7:main",
            "state": runtime.SLOT_CLEANUP_REQUIRED,
            "ticket_id": "ticket_444",
            "channel_id": 444,
            "thread_id": 445,
        }
        mongo = _mongo(
            rollout=[_rollout()],
            legacy=[ticket],
            slots=[reserved],
            creation=[uncertain],
        )

        result = await runtime.backfill_open_slots(mongo, now=NOW)

        assert result.existing_slot_ids == ("ticket-open:7:main",)
        rebound = mongo.ticket_open_slots.documents["ticket-open:7:main"]
        assert rebound["state"] == runtime.SLOT_OPEN
        assert rebound["ticket_id"] == "ticket_444"
        assert rebound["location_id"] == 444
        assert "owner_token" not in rebound
        assert "lease_until" not in rebound
        assert mongo.button_store.documents["ticket_444"]["open_slot_id"] == (
            "ticket-open:7:main"
        )
        assert mongo.ticket_creation_state.documents["111:7:main"] == uncertain

    asyncio.run(scenario())


def test_claim_cross_checks_preexisting_open_ticket_before_winning():
    async def scenario():
        ticket = _ticket("legacy-open", user="91", route=runtime.ROUTE_LEGACY, location=911)
        mongo = _mongo(rollout=[_cross_rollout()], legacy=[ticket])
        claim = await runtime.claim_open_slot(
            mongo,
            user_id=91,
            ticket_type="main",
            route=runtime.ROUTE_THREAD,
            guild_id=11,
            workflow_id="thread:91:main",
            rollout_revision=4,
            now=NOW,
        )
        assert not claim.won
        assert claim.slot["route"] == runtime.ROUTE_LEGACY
        assert claim.slot["location_id"] == 911

    asyncio.run(scenario())


def test_claim_ignores_a_preexisting_ticket_whose_thread_is_missing():
    """thread_missing (set by the GuildThreadDeleteEvent listener) must not
    keep an unusable open ticket blocking a fresh claim forever -- that is
    exactly what lets the applicant open a new ticket after Discord deletes
    their thread."""
    async def scenario():
        ticket = _ticket("thread-open", user=91, route=runtime.ROUTE_THREAD, location=911)
        ticket["thread_missing"] = {"thread_role": "candidate"}
        mongo = _mongo(rollout=[_cross_rollout()], thread=[ticket])
        claim = await runtime.claim_open_slot(
            mongo,
            user_id=91,
            ticket_type="main",
            route=runtime.ROUTE_THREAD,
            guild_id=11,
            workflow_id="thread:91:main",
            rollout_revision=4,
            now=NOW,
        )
        assert claim.won

    asyncio.run(scenario())


def test_next_claim_repairs_exact_terminal_slot_when_release_checkpoint_failed():
    async def scenario():
        terminal = _ticket(
            "legacy-terminal",
            user=92,
            route=runtime.ROUTE_LEGACY,
            status="denied",
            location=921,
        )
        terminal.update({
            "venue": "channel",
            "runtime": runtime.LEGACY_RUNTIME,
            "open_slot_id": "ticket-open:92:main",
            "creation_workflow_id": "legacy:92:main",
        })
        stranded = {
            "_id": "ticket-open:92:main",
            "workflow_id": "legacy:92:main",
            "route": runtime.ROUTE_LEGACY,
            "state": runtime.SLOT_OPEN,
            "ticket_id": terminal["_id"],
            "updated_at": NOW,
        }
        mongo = _mongo(
            rollout=[_rollout()], legacy=[terminal], slots=[stranded]
        )

        claim = await runtime.claim_open_slot(
            mongo,
            user_id=92,
            ticket_type="main",
            route=runtime.ROUTE_THREAD,
            guild_id=11,
            workflow_id="thread:92:main",
            rollout_revision=4,
            now=NOW,
        )

        assert claim.won
        replacement = mongo.ticket_open_slots.documents[stranded["_id"]]
        assert replacement["state"] == runtime.SLOT_RESERVED
        assert replacement["route"] == runtime.ROUTE_THREAD
        assert replacement["workflow_id"] == "thread:92:main"

    asyncio.run(scenario())


def test_number_allocator_scans_both_stores_pending_slots_and_migrations_as_numbers():
    async def scenario():
        mongo = _mongo(
            legacy=[_ticket("l1", user=1, route=runtime.ROUTE_LEGACY, number="9")],
            thread=[_ticket("t1", user=2, route=runtime.ROUTE_THREAD, number=1000)],
            slots=[{
                "_id": "ticket-open:3:main",
                "workflow_id": "w3",
                "ticket_type": "main",
                "ticket_number": "1200",
            }],
            creation=[{
                "_id": "thread:4:main",
                "ticket_type": "main",
                "ticket_number": 1500,
            }],
            migration=[{
                "_id": "migration:1",
                "metadata": {"ticket_type": "main"},
                "destination": {"ticket_number": "1700"},
            }],
        )
        assert await runtime.reserve_ticket_number(mongo, "main") == 1701
        next_numbers = await asyncio.gather(
            runtime.reserve_ticket_number(mongo, "main"),
            runtime.reserve_ticket_number(mongo, "main"),
        )
        assert sorted(next_numbers) == [1702, 1703]

    asyncio.run(scenario())


def test_resume_cancel_and_reconcile_require_exact_durable_proof():
    async def scenario():
        reserved = {
            "_id": "ticket-open:100:main",
            "workflow_id": "thread:100:main",
            "route": runtime.ROUTE_THREAD,
            "state": runtime.SLOT_RESERVED,
            "owner_token": "old",
            "lease_until": NOW - timedelta(seconds=1),
            "updated_at": NOW,
        }
        terminal = _ticket(
            "legacy-terminal", user=101, route=runtime.ROUTE_LEGACY, status="approved"
        )
        terminal.update(
            {
                "open_slot_id": "ticket-open:101:main",
                "creation_workflow_id": "legacy:101:main",
            }
        )
        terminal_slot = {
            "_id": "ticket-open:101:main",
            "workflow_id": "legacy:101:main",
            "route": runtime.ROUTE_LEGACY,
            "state": runtime.SLOT_RELEASE_PENDING,
            "ticket_id": "legacy-terminal",
            "updated_at": NOW,
        }
        spoofed = {
            **terminal_slot,
            "_id": "ticket-open:102:main",
            "workflow_id": "legacy:102:main",
            "ticket_id": "legacy-terminal",
        }
        mongo = _mongo(legacy=[terminal], slots=[reserved, terminal_slot, spoofed])
        first = await runtime.reconcile_open_slots(mongo, now=NOW)
        assert reserved["_id"] in first.unchanged_slot_ids
        assert terminal_slot["_id"] in first.released_slot_ids
        assert spoofed["_id"] in first.cleanup_required_slot_ids
        resumed = await runtime.resume_open_slot(
            mongo,
            slot_id=reserved["_id"],
            workflow_id=reserved["workflow_id"],
            route=runtime.ROUTE_THREAD,
            now=NOW,
        )
        assert resumed.won
        assert not await runtime.cancel_open_slot(
            mongo,
            slot_id=reserved["_id"],
            owner_token="wrong",
            workflow_id=reserved["workflow_id"],
        )
        assert await runtime.cancel_open_slot(
            mongo,
            slot_id=reserved["_id"],
            owner_token=resumed.owner_token,
            workflow_id=reserved["workflow_id"],
        )

    asyncio.run(scenario())


def test_reconcile_terminal_delete_preserves_reused_live_slot_in_memory():
    async def scenario():
        slot_id = "ticket-open:104:main"
        terminal = _ticket(
            "legacy-terminal-race",
            user=104,
            route=runtime.ROUTE_LEGACY,
            status="approved",
        )
        terminal.update({
            "open_slot_id": slot_id,
            "creation_workflow_id": "legacy:old:104:main",
        })
        stale = {
            "_id": slot_id,
            "workflow_id": "legacy:old:104:main",
            "route": runtime.ROUTE_LEGACY,
            "state": runtime.SLOT_OPEN,
            "ticket_id": terminal["_id"],
            "updated_at": NOW,
        }
        replacement = {
            "_id": slot_id,
            "workflow_id": "thread:new:104:main",
            "route": runtime.ROUTE_THREAD,
            "state": runtime.SLOT_OPEN,
            "ticket_id": "thread-live-replacement",
            "updated_at": NOW + timedelta(seconds=1),
        }

        class ReplaceBeforeDelete(Collection):
            async def delete_one(self, query):
                self.documents[slot_id] = deepcopy(replacement)
                return await super().delete_one(query)

        mongo = _mongo(legacy=[terminal], slots=[])
        mongo.ticket_open_slots = ReplaceBeforeDelete([stale])
        result = await runtime.reconcile_open_slots(mongo, now=NOW)

        assert result.released_slot_ids == ()
        assert result.unchanged_slot_ids == (slot_id,)
        assert mongo.ticket_open_slots.documents[slot_id] == replacement

    asyncio.run(scenario())


def test_reconcile_terminal_delete_preserves_reused_live_slot_on_mongodb7():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(
            uri,
            serverSelectionTimeoutMS=5_000,
            tz_aware=True,
        )
        database_name = f"wu_ticket_runtime_slot_race_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        slot_id = "ticket-open:105:main"
        terminal = _ticket(
            "legacy-terminal-mongo-race",
            user=105,
            route=runtime.ROUTE_LEGACY,
            status="denied",
        )
        terminal.update({
            "open_slot_id": slot_id,
            "creation_workflow_id": "legacy:old:105:main",
        })
        stale = {
            "_id": slot_id,
            "workflow_id": "legacy:old:105:main",
            "route": runtime.ROUTE_LEGACY,
            "state": runtime.SLOT_OPEN,
            "ticket_id": terminal["_id"],
            "updated_at": NOW,
        }
        replacement = {
            "_id": slot_id,
            "workflow_id": "thread:new:105:main",
            "route": runtime.ROUTE_THREAD,
            "state": runtime.SLOT_OPEN,
            "ticket_id": "thread-live-mongo-replacement",
            "updated_at": NOW + timedelta(seconds=1),
        }

        class ReplaceBeforeDelete:
            def __init__(self, collection):
                self.collection = collection

            def __getattr__(self, name):
                return getattr(self.collection, name)

            async def delete_one(self, query):
                await self.collection.replace_one(
                    {"_id": slot_id},
                    replacement,
                )
                return await self.collection.delete_one(query)

        try:
            await client.admin.command("ping")
            await database.button_store.insert_one(terminal)
            await database.ticket_open_slots.insert_one(stale)
            mongo = SimpleNamespace(
                ticket_open_slots=ReplaceBeforeDelete(
                    database.ticket_open_slots
                ),
                button_store=database.button_store,
                tickets=database.tickets,
            )
            result = await runtime.reconcile_open_slots(mongo, now=NOW)
            durable = await database.ticket_open_slots.find_one({"_id": slot_id})

            assert result.released_slot_ids == ()
            assert result.unchanged_slot_ids == (slot_id,)
            assert durable == replacement
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("route", "workflow_id", "creation_id"),
    [
        (runtime.ROUTE_THREAD, "thread:103:main", "thread:103:main"),
    ],
)
def test_expired_slot_cannot_be_taken_from_a_live_creation_worker(
    route, workflow_id, creation_id
):
    async def scenario():
        slot = {
            "_id": "ticket-open:103:main",
            "workflow_id": workflow_id,
            "route": route,
            "state": runtime.SLOT_RESERVED,
            "owner_token": "original",
            "lease_until": NOW - timedelta(minutes=3),
            "updated_at": NOW - timedelta(minutes=3),
        }
        creation = {
            "_id": creation_id,
            "state": "creating",
            "lease_until": NOW + timedelta(minutes=5),
        }
        mongo = _mongo(slots=[slot], creation=[creation])
        resumed = await runtime.resume_open_slot(
            mongo,
            slot_id=slot["_id"],
            workflow_id=workflow_id,
            route=route,
            now=NOW,
        )
        assert not resumed.won
        assert mongo.ticket_open_slots.documents[slot["_id"]]["owner_token"] == "original"

    asyncio.run(scenario())


def test_legacy_monitor_schema_and_open_conflicts_block_promotion_and_drain():
    async def scenario():
        historical = {
            "channel_id": 201,
            "automation_state": {"current_step": "initial"},
            "ticket_info": {"user_id": 20},
        }
        automations = [
            {
                "_id": "201",
                **historical,
                "initial_delivery": {"status": "retry"},
            },
            {
                "_id": "202",
                **{**historical, "channel_id": 202},
                "initial_delivery": {
                    "status": "processing",
                    "lease_until": NOW - timedelta(seconds=1),
                },
            },
            {
                "_id": "203",
                **{**historical, "channel_id": 203},
                "initial_delivery": {
                    "status": "processing",
                    "lease_until": NOW + timedelta(minutes=1),
                },
            },
            {
                "_id": "204",
                **{**historical, "channel_id": 204},
                "initial_delivery": {"status": "complete"},
            },
            {
                "_id": "thread-context",
                "kind": "ticket_staff_context",
                "channel_id": 205,
                "automation_state": {},
                "ticket_info": {},
                "initial_delivery": {"status": "retry"},
            },
        ]
        conflict = {
            "_id": "ticket-open:20:main",
            "user_id": 20,
            "ticket_type": "main",
            "state": runtime.SLOT_CLEANUP_REQUIRED,
            "cleanup_reason": "multiple_authoritative_open_tickets",
            "conflicting_tickets": [
                {"route": runtime.ROUTE_LEGACY, "ticket_id": "legacy-20"},
                {"route": runtime.ROUTE_THREAD, "ticket_id": "thread-20"},
            ],
        }
        mongo = _mongo(
            rollout=[_rollout()], slots=[conflict], automation=automations
        )

        blockers = await runtime.runtime_blocker_status(mongo)
        assert blockers.legacy_pending_deliveries == 3
        assert blockers.pending_delivery_ids == ("201", "202", "203")
        assert blockers.unresolved_conflicts == 1
        assert blockers.conflict_slot_ids == (conflict["_id"],)
        drain = await runtime.legacy_drain_status(mongo)
        assert not drain.drained
        assert drain.legacy_pending_deliveries == 3
        assert drain.unresolved_conflicts == 1
        recoverable = await mongo.ticket_automation_state.find(
            runtime.legacy_recoverable_delivery_query(now=NOW)
        ).sort([("_id", 1)]).to_list(length=None)
        assert [row["_id"] for row in recoverable] == ["201", "202"]

        mongo.ticket_rollout.documents[runtime.ROLLOUT_ID]["phase"] = (
            runtime.PHASE_THREAD_DEFAULT
        )
        with pytest.raises(runtime.LegacyDrainBlocked):
            await runtime.transition_rollout(
                mongo,
                expected_phase=runtime.PHASE_THREAD_DEFAULT,
                expected_revision=4,
                to_phase=runtime.PHASE_THREAD_ONLY,
                actor_id=1,
                now=NOW,
            )
        mongo.ticket_rollout.documents[runtime.ROLLOUT_ID]["phase"] = (
            runtime.PHASE_PILOT
        )

        with pytest.raises(runtime.RuntimeReadinessBlocked):
            await runtime.transition_rollout(
                mongo,
                expected_phase=runtime.PHASE_PILOT,
                expected_revision=4,
                to_phase=runtime.PHASE_THREAD_DEFAULT,
                actor_id=1,
                now=NOW,
            )

        mongo.ticket_open_slots.documents.clear()
        with pytest.raises(runtime.RuntimeReadinessBlocked):
            await runtime.transition_rollout(
                mongo,
                expected_phase=runtime.PHASE_PILOT,
                expected_revision=4,
                to_phase=runtime.PHASE_THREAD_DEFAULT,
                actor_id=1,
                now=NOW,
            )
        for row in mongo.ticket_automation_state.documents.values():
            if row["_id"].isdigit():
                row["initial_delivery"]["status"] = "complete"
        state = await runtime.transition_rollout(
            mongo,
            expected_phase=runtime.PHASE_PILOT,
            expected_revision=4,
            to_phase=runtime.PHASE_THREAD_DEFAULT,
            actor_id=1,
            now=NOW,
        )
        assert state.phase == runtime.PHASE_THREAD_DEFAULT

    asyncio.run(scenario())


def test_rollout_cas_and_thread_only_drain_barrier():
    async def scenario():
        mongo = _mongo(legacy=[_ticket("open", user=110, route=runtime.ROUTE_LEGACY)])
        state = await runtime.seed_rollout(
            mongo,
            actor_id=1,
            legacy_intake=_source(30),
            thread_intake=_source(31, guild=11, channel=21),
            pilot={
                "intake": _source(40, guild=11, channel=22),
                "user_ids": [50],
                "role_ids": [],
                "ticket_types": ["main"],
            },
            now=NOW,
        )
        for target in (
            runtime.PHASE_PREPARED,
            runtime.PHASE_PILOT,
            runtime.PHASE_THREAD_DEFAULT,
        ):
            state = await runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=target,
                actor_id=1,
                now=NOW,
            )
        with pytest.raises(runtime.LegacyDrainBlocked):
            await runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=runtime.PHASE_THREAD_ONLY,
                actor_id=1,
                now=NOW,
            )
        mongo.button_store.documents.clear()
        state = await runtime.transition_rollout(
            mongo,
            expected_phase=state.phase,
            expected_revision=state.revision,
            to_phase=runtime.PHASE_THREAD_ONLY,
            actor_id=1,
            now=NOW,
        )
        assert state.phase == runtime.PHASE_THREAD_ONLY
        with pytest.raises(runtime.RolloutConflict):
            await runtime.configure_rollout(
                mongo,
                expected_revision=1,
                actor_id=1,
                legacy_intake=_source(30),
                thread_intake=_source(31, guild=11, channel=21),
                pilot={
                    "intake": _source(40, guild=11, channel=22),
                    "user_ids": [50],
                    "ticket_types": ["main"],
                },
            )

    asyncio.run(scenario())


def test_indexes_are_non_ttl_and_thread_insert_never_mirrors():
    async def scenario():
        mongo = _mongo()
        await runtime.ensure_indexes(mongo)
        assert mongo.ticket_open_slots.indexes
        assert all(
            "expireAfterSeconds" not in options
            for _spec, options in mongo.ticket_open_slots.indexes
        )
        slot = {
            "_id": "ticket-open:120:main",
            "workflow_id": "thread:120:main",
            "route": runtime.ROUTE_THREAD,
            "rollout_revision": 4,
        }
        ticket = {
            "_id": "thread-ticket",
            "type": "ticket",
            "ticket_type": "main",
            "status": "open",
            **runtime.thread_ticket_fields(slot),
        }
        # `ticket_runtime` never owns ticket insertion (that is
        # `tickets/store.py`'s job, which normalizes on write); this checks
        # only that this runtime's own fields keep the write off the legacy
        # mirror collection.
        await mongo.tickets.insert_one(ticket)
        assert "thread-ticket" in mongo.tickets.documents
        assert "thread-ticket" not in mongo.button_store.documents

    asyncio.run(scenario())
