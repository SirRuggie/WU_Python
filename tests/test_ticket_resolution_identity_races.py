import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import (
    account_sync,
    close,
    flag_store,
    resolve,
    store,
    thread_service,
)


def _matches(document, query):
    for key, expected in query.items():
        present = key in document
        actual = document.get(key)
        if isinstance(expected, dict) and "$exists" in expected:
            if present != bool(expected["$exists"]):
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class LockCollection:
    def __init__(self, documents=()):
        self.documents = {item["_id"]: deepcopy(item) for item in documents}
        self.pause_flag_reread = False
        self.flag_reads = 0
        self.reread_started = asyncio.Event()
        self.release_reread = asyncio.Event()

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query):
        if query.get("_id") == "flag_blacklist":
            self.flag_reads += 1
            if self.pause_flag_reread and self.flag_reads == 2:
                self.reread_started.set()
                await self.release_reread.wait()
        return next((
            deepcopy(document)
            for document in self.documents.values()
            if _matches(document, query)
        ), None)

    async def find_one_and_update(self, query, update, **_kwargs):
        for key, document in self.documents.items():
            if not _matches(document, query):
                continue
            document.update(deepcopy(update.get("$set", {})))
            for field in update.get("$unset", {}):
                document.pop(field, None)
            for field, amount in update.get("$inc", {}).items():
                document[field] = int(document.get(field, 0)) + int(amount)
            for field, value in update.get("$push", {}).items():
                document.setdefault(field, []).append(deepcopy(value))
            self.documents[key] = document
            return deepcopy(document)
        return None

    async def update_one(self, query, update, **_kwargs):
        updated = await self.find_one_and_update(query, update)
        return SimpleNamespace(matched_count=int(updated is not None))


def _ticket():
    return {
        "_id": "ticket_101",
        "type": "ticket",
        "venue": "thread",
        "status": "open",
        "user_id": 223456789012345678,
        "player_tags": ["#ABC123"],
    }


def _patch_approval(monkeypatch, collection, *, blacklisted, transitions):
    ticket = _ticket()

    async def recruiter(*_args, **_kwargs):
        return True

    async def find_ticket(*_args, **_kwargs):
        return ticket

    async def active_blacklist(*_args, **_kwargs):
        return {"_id": "flag_blacklist"} if blacklisted() else None

    async def transition(*_args, **_kwargs):
        transitions.append("approved")
        return store.Transition(store.WON, {**ticket, "status": "approved"})

    async def effects(_bot, _mongo, document):
        return store.Transition(store.WON, document)

    async def sync(*_args, **_kwargs):
        return account_sync.AccountSyncResult(
            ticket,
            account_sync.AccountSnapshot(
                state=account_sync.STATE_READY,
                current_accounts=(account_sync.LinkedAccount("#ABC123"),),
                current_tags=("#ABC123",),
                observed_tags=("#ABC123",),
                retry_required=False,
                revision=1,
            ),
        )

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", find_ticket)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", active_blacklist)
    monkeypatch.setattr(resolve.store, "transition", transition)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    monkeypatch.setattr(resolve.account_sync, "configured_coc_client", lambda: object())
    monkeypatch.setattr(resolve.account_sync, "sync_ticket_accounts", sync)
    return SimpleNamespace(ticket_flags=collection), ticket


def test_blacklist_activation_linearizes_before_concurrent_approval(monkeypatch):
    collection = LockCollection()
    flag_is_active = False
    mutation_started = asyncio.Event()
    release_mutation = asyncio.Event()
    transitions = []

    async def set_unlocked(*_args, **_kwargs):
        nonlocal flag_is_active
        flag_is_active = True
        mutation_started.set()
        await release_mutation.wait()
        return {"_id": "flag_blacklist", "active": True}

    monkeypatch.setattr(flag_store, "_set_flag_unlocked", set_unlocked)
    mongo, ticket = _patch_approval(
        monkeypatch,
        collection,
        blacklisted=lambda: flag_is_active,
        transitions=transitions,
    )

    async def run():
        mutation = asyncio.create_task(flag_store.set_flag(
            mongo,
            kind=flag_store.FLAG_BLACKLISTED,
            discord_ids=ticket["user_id"],
            player_tags=ticket["player_tags"],
            source="test",
            added_by=9,
            added_by_name="Recruiter",
        ))
        await mutation_started.wait()
        approval = asyncio.create_task(resolve.approve_ticket(
            object(), mongo, ticket_id=ticket["_id"],
            member=SimpleNamespace(id=9), actor_name="Recruiter",
        ))
        await asyncio.sleep(0.01)
        assert transitions == []
        release_mutation.set()
        await mutation
        return await approval

    result = asyncio.run(run())
    assert result.outcome == store.BLOCKED
    assert transitions == []


def test_blacklist_deactivation_linearizes_before_concurrent_approval(monkeypatch):
    ticket = _ticket()
    collection = LockCollection([{
        "_id": "flag_blacklist",
        "kind": flag_store.FLAG_BLACKLISTED,
        "active": True,
        "discord_ids": [ticket["user_id"]],
        "player_tags": ticket["player_tags"],
        "rev": 1,
        "audit": [],
    }])
    collection.pause_flag_reread = True
    transitions = []
    mongo, _ = _patch_approval(
        monkeypatch,
        collection,
        blacklisted=lambda: collection.documents["flag_blacklist"]["active"],
        transitions=transitions,
    )

    async def run():
        deactivation = asyncio.create_task(flag_store.deactivate_flag(
            mongo,
            "flag_blacklist",
            removed_by=9,
            removed_by_name="Recruiter",
            expected_rev=1,
        ))
        await collection.reread_started.wait()
        approval = asyncio.create_task(resolve.approve_ticket(
            object(), mongo, ticket_id=ticket["_id"],
            member=SimpleNamespace(id=9), actor_name="Recruiter",
        ))
        await asyncio.sleep(0.01)
        assert transitions == []
        collection.release_reread.set()
        return await deactivation, await approval

    deactivation, approval = asyncio.run(run())
    assert deactivation.outcome == store.WON
    assert approval.outcome == store.WON
    assert transitions == ["approved"]


def test_identity_guard_accepts_naive_mongo_lease_datetimes():
    expired = datetime.now() - timedelta(minutes=5)
    lock_id = "ticket_identity_lock:discord:223456789012345678"
    collection = LockCollection([{
        "_id": lock_id,
        "kind": "identity_lock",
        "active": False,
        "lease_owner": "dead-worker",
        "lease_until": expired,
    }])
    mongo = SimpleNamespace(ticket_flags=collection)

    async def run():
        async with flag_store.identity_guard(
            mongo, discord_ids=223456789012345678,
        ):
            assert collection.documents[lock_id]["lease_owner"] != "dead-worker"

    asyncio.run(run())
    assert "lease_owner" not in collection.documents[lock_id]


def test_approval_pins_ticket_revision_at_blacklist_decision_boundary(monkeypatch):
    ticket = {**_ticket(), "rev": 7}
    observed = []
    mongo = SimpleNamespace(ticket_flags=LockCollection())

    async def recruiter(*_args, **_kwargs):
        return True

    async def find(*_args, **_kwargs):
        return ticket

    async def no_blacklist(*_args, **_kwargs):
        return None

    async def transition(*_args, **kwargs):
        observed.append(kwargs["expected_rev"])
        return store.Transition(store.LOST, ticket, "ticket changed")

    async def sync(*_args, **_kwargs):
        return account_sync.AccountSyncResult(
            ticket,
            account_sync.AccountSnapshot(
                state=account_sync.STATE_READY,
                current_accounts=(account_sync.LinkedAccount("#ABC123"),),
                current_tags=("#ABC123",),
                observed_tags=("#ABC123",),
                retry_required=False,
                revision=1,
            ),
        )

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(resolve.store, "find_one", find)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", no_blacklist)
    monkeypatch.setattr(resolve.store, "transition", transition)
    monkeypatch.setattr(resolve.account_sync, "configured_coc_client", lambda: object())
    monkeypatch.setattr(resolve.account_sync, "sync_ticket_accounts", sync)
    result = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=9),
        actor_name="Recruiter",
    ))

    assert result.outcome == store.LOST
    assert observed == [7]


def test_slash_approve_reports_lock_contention_without_blacklist_claim(monkeypatch):
    responses = []
    ticket = _ticket()

    class Context:
        channel_id = 101
        member = SimpleNamespace(id=9)
        user = SimpleNamespace(username="Recruiter")

        async def defer(self, **_kwargs):
            return None

        async def respond(self, content, **_kwargs):
            responses.append(content)

    async def recruiter(*_args, **_kwargs):
        return True

    async def find(*_args, **_kwargs):
        return ticket

    async def busy(*_args, **_kwargs):
        return store.Transition(
            store.BLOCKED,
            ticket,
            "applicant identity is being updated; try again",
        )

    monkeypatch.setattr(close.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(close.store, "find_by_location", find)
    monkeypatch.setattr(close.resolve, "approve_ticket", busy)
    asyncio.run(close.Approve.invoke._func(
        SimpleNamespace(), Context(), mongo=object(), bot=object(),
    ))

    assert len(responses) == 1
    assert "try again" in responses[0]
    assert "blacklist" not in responses[0].casefold()


def test_candidate_authored_resolution_marker_cannot_suppress_notification():
    marker = "ticket-resolution:ticket_101:1:approved"

    class Messages:
        def __init__(self, messages):
            self.messages = messages

        async def to_list(self):
            return list(self.messages)

    messages = [SimpleNamespace(
        author=SimpleNamespace(id=223456789012345678),
        content=f"-# {marker}",
        components=[],
    )]
    rest = SimpleNamespace(fetch_messages=lambda _channel_id: Messages(messages))
    assert asyncio.run(resolve._notification_exists(
        rest, 101, marker, bot_user_id=7,
    )) is False

    messages.append(SimpleNamespace(
        author=SimpleNamespace(id=7),
        content="",
        components=[SimpleNamespace(
            content="",
            components=[SimpleNamespace(content=f"-# {marker}")],
        )],
    ))
    assert asyncio.run(resolve._notification_exists(
        rest, 101, marker, bot_user_id=7,
    )) is True


def test_user_owned_matching_private_thread_cannot_hijack_recovery():
    class Rest:
        async def fetch_channel(self, _thread_id):
            return SimpleNamespace(
                id=101,
                guild_id=10,
                parent_id=20,
                owner_id=223456789012345678,
                name="main-1-applicant",
                type=hikari.ChannelType.GUILD_PRIVATE_THREAD,
            )

    with pytest.raises(thread_service.ThreadTicketError, match="wrong owner"):
        asyncio.run(thread_service._fetch_or_recover_thread(
            Rest(),
            thread_id=101,
            guild_id=10,
            parent_id=20,
            name="main-1-applicant",
            private=True,
            expected_owner_id=7,
        ))
