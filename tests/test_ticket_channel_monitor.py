import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import uuid

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from extensions.events.channel import ticket_channel_monitor as monitor


class _TicketStoreMongo:
    pass


def test_wait_for_ticket_data_polls_until_persisted(monkeypatch):
    responses = [None, None, {"_id": "ticket_42", "user_id": 7}]
    sleeps = []

    async def fake_find_one(_mongo, _query):
        return responses.pop(0)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(monitor.store, "find_one", fake_find_one)
    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)

    result = asyncio.run(monitor.wait_for_ticket_data(
        _TicketStoreMongo(), 42, attempts=5, delay=0.25,
    ))

    assert result["user_id"] == 7
    assert sleeps == [0.25, 0.25]


def test_wait_for_ticket_data_stops_at_bound(monkeypatch):
    calls = 0

    async def fake_find_one(_mongo, _query):
        nonlocal calls
        calls += 1
        return None

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(monitor.store, "find_one", fake_find_one)
    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)

    result = asyncio.run(monitor.wait_for_ticket_data(
        _TicketStoreMongo(), 42, attempts=3, delay=0,
    ))

    assert result is None
    assert calls == 3


class _ClaimCollection:
    def __init__(self, *, duplicate=False):
        self.duplicate = duplicate
        self.call = None

    async def find_one_and_update(self, query, update, **kwargs):
        self.call = (query, update, kwargs)
        if self.duplicate:
            raise DuplicateKeyError("already claimed")
        return {
            "_id": query["_id"],
            "initial_delivery": {"status": "processing"},
        }


class _ClaimMongo:
    def __init__(self, *, duplicate=False):
        self.ticket_automation_state = _ClaimCollection(duplicate=duplicate)


def test_claim_is_atomic_and_uses_a_lease():
    mongo = _ClaimMongo()
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    doc = {"_id": "42", "channel_id": 42}

    result = asyncio.run(monitor.claim_automation_delivery(mongo, doc, now=now))

    query, update, kwargs = mongo.ticket_automation_state.call
    assert result["initial_delivery"]["status"] == "processing"
    assert query["_id"] == "42"
    assert update["$setOnInsert"] == {"_id": "42", "channel_id": 42}
    assert update["$set"]["initial_delivery.status"] == "processing"
    assert update["$set"]["initial_delivery.lease_until"] == now + monitor.DELIVERY_LEASE
    assert kwargs["upsert"] is True


def test_claim_upsert_and_takeover_against_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_ticket_delivery_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(
            ticket_automation_state=database.ticket_automation_state,
        )
        now = datetime.now(timezone.utc)
        document = monitor.build_automation_document(
            channel_id=43,
            thread_id=44,
            guild_id=7,
            user_id=143,
            ticket_type="main",
            now=now,
            initial_delivery={
                "status": "retry",
                "welcome_sent": True,
                "last_error": "old failure",
            },
        )
        try:
            await client.admin.command("ping")
            first = await monitor.claim_automation_delivery(
                mongo, document, now=now,
            )
            assert first is not None
            first_owner = first["initial_delivery"]["lease_owner"]
            assert first["kind"] == "legacy_initial_delivery"
            assert first["route"] == "legacy"
            assert first["runtime"] == "legacy_channel"
            assert first["user_id"] == 143
            assert first["ticket_info"]["user_id"] == 143
            assert first["initial_delivery"]["welcome_sent"] is True
            assert "last_error" not in first["initial_delivery"]

            assert await monitor.claim_automation_delivery(
                mongo, document, now=now,
            ) is None

            changed = deepcopy(document)
            changed["user_id"] = 999
            changed["ticket_info"]["user_id"] = 999
            changed["initial_delivery"]["welcome_sent"] = False
            takeover_at = now + monitor.DELIVERY_LEASE + timedelta(seconds=1)
            second = await monitor.claim_automation_delivery(
                mongo, changed, now=takeover_at,
            )
            assert second is not None
            second_owner = second["initial_delivery"]["lease_owner"]
            assert second_owner != first_owner
            assert second["user_id"] == 143
            assert second["ticket_info"]["user_id"] == 143
            assert second["initial_delivery"]["welcome_sent"] is True

            assert not await monitor.release_automation_delivery(
                mongo, 43, first_owner, "stale owner",
            )
            assert await monitor.release_automation_delivery(
                mongo, 43, second_owner, "retry me",
            )
            retry_row = await database.ticket_automation_state.find_one(
                {"_id": "43"}
            )
            retry_after = retry_row["initial_delivery"]["retry_after"]
            assert await monitor.claim_automation_delivery(
                mongo,
                retry_row,
                now=retry_after - timedelta(microseconds=1),
            ) is None
            third = await monitor.claim_automation_delivery(
                mongo,
                retry_row,
                now=retry_after + timedelta(microseconds=1),
            )
            assert third is not None
            assert third["initial_delivery"]["lease_owner"] != second_owner
            assert third["user_id"] == 143
            assert third["initial_delivery"]["welcome_sent"] is True
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_assert_delivery_lease_handles_naive_bson_datetime_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_ticket_delivery_lease_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(
            ticket_automation_state=database.ticket_automation_state,
        )
        now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
        try:
            await client.admin.command("ping")
            await database.ticket_automation_state.insert_one({
                "_id": "44",
                "kind": "legacy_initial_delivery",
                "route": "legacy",
                "runtime": "legacy_channel",
                "channel_id": 44,
                "user_id": 144,
                "ticket_type": "main",
                "initial_delivery": {
                    "status": "processing",
                    "lease_owner": "real-mongo-owner",
                    "lease_until": now + timedelta(seconds=1),
                },
            })

            renewed = await monitor.assert_delivery_lease(
                mongo,
                44,
                "real-mongo-owner",
                now=now,
            )

            # Default PyMongo decoding is naive UTC; the production comparison
            # must normalize it without weakening the owner/status fence.
            assert renewed["initial_delivery"]["lease_until"].tzinfo is None
            assert renewed["initial_delivery"]["lease_owner"] == "real-mongo-owner"
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_markerless_automation_upgrade_is_atomic_against_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_ticket_delivery_upgrade_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(
            ticket_automation_state=database.ticket_automation_state,
        )
        now = datetime.now(timezone.utc)
        row = monitor.build_automation_document(
            channel_id=46,
            thread_id=47,
            guild_id=7,
            user_id=146,
            ticket_type="main",
            now=now,
            initial_delivery={"status": "retry", "welcome_sent": True},
        )
        for field in ("kind", "route", "runtime", "guild_id"):
            row.pop(field)
        ticket = {
            "_id": "ticket_46",
            "type": "ticket",
            "status": "open",
            "venue": "channel",
            "runtime": "legacy_channel",
            "channel_id": 46,
            "thread_id": 47,
            "guild_id": 7,
            "user_id": 146,
            "ticket_type": "main",
        }
        try:
            await client.admin.command("ping")
            await database.ticket_automation_state.insert_one(row)
            first, second = await asyncio.gather(
                monitor._upgrade_legacy_automation_identity(mongo, row, ticket),
                monitor._upgrade_legacy_automation_identity(mongo, row, ticket),
            )
            assert first["guild_id"] == second["guild_id"] == 7
            persisted = await database.ticket_automation_state.find_one({"_id": "46"})
            assert persisted["kind"] == "legacy_initial_delivery"
            assert persisted["route"] == "legacy"
            assert persisted["runtime"] == "legacy_channel"
            assert persisted["initial_delivery"]["welcome_sent"] is True
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_duplicate_key_means_another_worker_owns_delivery():
    mongo = _ClaimMongo(duplicate=True)

    result = asyncio.run(monitor.claim_automation_delivery(
        mongo, {"_id": "42", "channel_id": 42},
    ))

    assert result is None


def test_expired_owner_cannot_send_or_mutate_after_takeover(monkeypatch):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    document = {
        "_id": "39",
        "kind": "legacy_initial_delivery",
        "route": "legacy",
        "runtime": "legacy_channel",
        "channel_id": 39,
        "thread_id": 40,
        "guild_id": 7,
        "user_id": 139,
        "ticket_type": "main",
        "initial_delivery": {
            "status": "retry",
            "message_plan": monitor._delivery_message_plan(
                user_id=139,
                ticket_type="main",
                recruiter_role=None,
                guild_icon_url=None,
            ),
        },
    }
    automation = _RecoveryAutomation([document], now)

    class Setup:
        async def find_one(self, _query):
            return {}

    class Rest:
        def __init__(self):
            self.messages = []

        async def create_message(self, **kwargs):
            self.messages.append(kwargs)

    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=Setup(),
    )
    rest = Rest()
    _install_ticket_lookup(monkeypatch, _committed_ticket(39))
    first = asyncio.run(monitor.claim_automation_delivery(mongo, document, now=now))
    first_owner = first["initial_delivery"]["lease_owner"]
    expired_at = now + monitor.DELIVERY_LEASE + timedelta(seconds=1)
    monkeypatch.setattr(monitor, "delivery_now", lambda: expired_at)

    with pytest.raises(monitor.DeliveryLeaseLost):
        asyncio.run(monitor.deliver_claimed_automation(rest, mongo, first))
    assert rest.messages == []

    automation.now = expired_at
    second = asyncio.run(
        monitor.claim_automation_delivery(mongo, document, now=expired_at)
    )
    second_owner = second["initial_delivery"]["lease_owner"]
    assert second_owner != first_owner

    with pytest.raises(monitor.DeliveryLeaseLost):
        asyncio.run(
            monitor.mark_delivery_step(
                mongo, 39, first_owner, "welcome_sent"
            )
        )
    with pytest.raises(monitor.DeliveryLeaseLost):
        asyncio.run(monitor.finish_automation_delivery(mongo, 39, first_owner))
    assert not asyncio.run(
        monitor.release_automation_delivery(mongo, 39, first_owner, "stale")
    )
    assert not asyncio.run(
        monitor.cancel_automation_delivery(mongo, 39, first_owner, "stale")
    )
    current = automation.rows["39"]["initial_delivery"]
    assert current["status"] == "processing"
    assert current["lease_owner"] == second_owner


def test_side_effect_fence_renews_lease_with_fresh_time(monkeypatch):
    started = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    check_time = started + timedelta(seconds=5)
    original_expiry = started + timedelta(seconds=10)
    document = {
        "_id": "40",
        "kind": "legacy_initial_delivery",
        "route": "legacy",
        "runtime": "legacy_channel",
        "channel_id": 40,
        "user_id": 140,
        "ticket_type": "main",
        "initial_delivery": {
            "status": "processing",
            "lease_owner": "owner",
            "lease_until": original_expiry,
        },
    }
    automation = _RecoveryAutomation([document], started)
    mongo = SimpleNamespace(ticket_automation_state=automation)
    monkeypatch.setattr(monitor, "delivery_now", lambda: check_time)

    renewed = asyncio.run(monitor.assert_delivery_lease(
        mongo, 40, "owner",
    ))

    assert renewed["initial_delivery"]["lease_until"] == (
        check_time + monitor.DELIVERY_LEASE
    )
    automation.now = original_expiry + timedelta(seconds=1)
    assert asyncio.run(monitor.claim_automation_delivery(
        mongo, document, now=automation.now,
    )) is None


def test_send_exception_is_never_blindly_retried(monkeypatch):
    class _Rest:
        def __init__(self):
            self.calls = 0

        async def create_message(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("ambiguous response")

    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)
    rest = _Rest()

    with pytest.raises(RuntimeError, match="ambiguous response"):
        asyncio.run(monitor.send_with_retries(rest, channel=42, content="hello"))

    assert rest.calls == 1
    assert sleeps == []


class _RecoveryCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, *_args):
        self.rows.sort(key=lambda row: row["_id"])
        return self

    def limit(self, amount):
        self.rows = self.rows[:amount]
        return self

    async def to_list(self, length=None):
        return deepcopy(self.rows if length is None else self.rows[:length])


class _RecoveryAutomation:
    _MISSING = object()

    def __init__(self, rows, now):
        self.rows = {row["_id"]: deepcopy(row) for row in rows}
        self.now = now

    @staticmethod
    def _legacy(row):
        return row.get("kind") != "ticket_staff_context"

    @staticmethod
    def _get(row, path):
        value = row
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return _RecoveryAutomation._MISSING
            value = value[part]
        return value

    def _matches(self, row, query):
        for path, expected in query.items():
            if path == "$and":
                if not all(self._matches(row, clause) for clause in expected):
                    return False
                continue
            if path == "$or":
                if not any(self._matches(row, clause) for clause in expected):
                    return False
                continue
            actual = self._get(row, path)
            if isinstance(expected, dict):
                for operator, operand in expected.items():
                    if operator == "$exists":
                        if (actual is not self._MISSING) != bool(operand):
                            return False
                    elif operator == "$nin":
                        if actual is not self._MISSING and actual in operand:
                            return False
                    elif operator == "$in":
                        if actual is self._MISSING or actual not in operand:
                            return False
                    elif operator == "$gt":
                        if actual is self._MISSING or actual <= operand:
                            return False
                    elif operator == "$lte":
                        if actual is self._MISSING or actual > operand:
                            return False
                    elif operator == "$ne":
                        if actual is not self._MISSING and actual == operand:
                            return False
                    else:
                        raise AssertionError(f"unsupported fake query: {operator}")
            elif actual is self._MISSING or actual != expected:
                return False
        return True

    def _recoverable(self, row):
        if not self._legacy(row):
            return False
        state = row.get("initial_delivery", {})
        retry_after = state.get("retry_after")
        retry_ready = retry_after is None or retry_after <= self.now
        return (state.get("status") == "retry" and retry_ready) or (
            state.get("status") == "processing"
            and state.get("lease_until") <= self.now
        )

    def find(self, _query):
        return _RecoveryCursor(
            row for row in self.rows.values() if self._recoverable(row)
        )

    async def find_one(self, query):
        row = self.rows.get(query["_id"])
        return deepcopy(row) if row is not None and self._matches(row, query) else None

    async def insert_one(self, document):
        if document["_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one_and_update(self, query, update, **_kwargs):
        row = self.rows.get(query["_id"])
        if row is None or not self._matches(row, query):
            return None
        for path, value in update["$set"].items():
            target = row
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        for path in update.get("$unset", {}):
            target = row
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.get(part, {})
            target.pop(parts[-1], None)
        return deepcopy(row)

    async def update_one(self, query, update):
        row = self.rows.get(query["_id"])
        if row is None or not self._matches(row, query):
            return SimpleNamespace(matched_count=0, modified_count=0)
        for path, value in update.get("$set", {}).items():
            target = row
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        for path in update.get("$unset", {}):
            target = row
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.get(part, {})
            target.pop(parts[-1], None)
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def count_documents(self, _query):
        return sum(
            self._legacy(row)
            and row.get("initial_delivery", {}).get("status")
            not in {"complete", "failed", "cancelled"}
            for row in self.rows.values()
        )


def _committed_ticket(channel_id=91):
    return {
        "_id": f"ticket_{channel_id}",
        "type": "ticket",
        "status": "open",
        "channel_id": channel_id,
        "thread_id": channel_id + 1,
        "guild_id": 7,
        "user_id": channel_id + 100,
        "ticket_type": "main",
        "venue": "channel",
        "runtime": "legacy_channel",
    }


class _OnlineHistory:
    def __init__(self, rows):
        self.rows = rows

    async def collect(self, factory):
        return factory(self.rows)


class _OnlineDeliveryRest:
    def __init__(self, *, failures=0, accepted_failures=0):
        self.failures = failures
        self.accepted_failures = accepted_failures
        self.send_calls = 0
        self.messages = []
        self.send_started = None
        self.release_send = None
        self._expected_thread = None

    async def fetch_channel(self, channel_id):
        if self._expected_thread == int(channel_id):
            parent_id = int(channel_id) - 1
            self._expected_thread = None
            return SimpleNamespace(
                id=channel_id,
                parent_id=parent_id,
                guild_id=7,
                type=monitor.hikari.ChannelType.GUILD_PRIVATE_THREAD,
                name=f"staff-{parent_id}",
            )
        self._expected_thread = int(channel_id) + 1
        return SimpleNamespace(
            id=channel_id,
            guild_id=7,
            type=monitor.hikari.ChannelType.GUILD_TEXT,
            name=f"main-{channel_id}-candidate",
        )

    def fetch_messages(self, channel_id):
        return _OnlineHistory([
            message for message in self.messages
            if int(getattr(message, "channel_id", 0)) == int(channel_id)
        ])

    async def create_message(self, **kwargs):
        self.send_calls += 1
        if self.send_started is not None and not self.send_started.is_set():
            self.send_started.set()
            await self.release_send.wait()
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary Discord failure")
        message = SimpleNamespace(
            channel_id=int(kwargs["channel"]),
            author=SimpleNamespace(id=900),
            content=kwargs.get("content", ""),
            components=tuple(kwargs.get("components", ())),
        )
        self.messages.append(message)
        if self.accepted_failures:
            self.accepted_failures -= 1
            raise RuntimeError("Discord accepted the POST but the response was lost")


class _OnlineSetup:
    async def find_one(self, _query):
        return {}


def _online_delivery_bot(rest):
    return SimpleNamespace(
        rest=rest,
        cache=SimpleNamespace(get_guild=lambda _guild_id: None),
        get_me=lambda: SimpleNamespace(id=900),
    )


def test_history_reconciliation_requires_bot_and_full_step_signature():
    welcome = (
        "<@191> Welcome! Thank you for your interest! **@Main Recruiter** "
        "will be with you shortly, in the meanwhile, please answer the "
        "following questions..."
    )
    messages = [
        SimpleNamespace(
            author=SimpleNamespace(id=901),
            content=welcome,
            components=tuple(monitor._questionnaire_components("main", None)),
        ),
        SimpleNamespace(
            author=SimpleNamespace(id=900),
            content=welcome,
            components=(SimpleNamespace(
                content="Warriors United Main Clan Entry Ticket",
                components=(),
            ),),
        ),
    ]
    bot = _online_delivery_bot(SimpleNamespace(
        fetch_messages=lambda _channel_id: _OnlineHistory(messages),
    ))
    plan = monitor._delivery_message_plan(
        user_id=191,
        ticket_type="main",
        recruiter_role=None,
        guild_icon_url=None,
    )

    observed = asyncio.run(monitor._existing_delivery_steps(
        bot,
        automation_doc={
            "channel_id": 91,
            "thread_id": 92,
            "ticket_type": "main",
        },
        message_plan=plan,
    ))

    assert observed == {
        "welcome_sent": True,
        "questionnaire_sent": False,
        "staff_privacy_sent": False,
        "staff_how_heard_sent": False,
        "staff_hook_sent": False,
        "staff_fwa_donation_sent": True,
    }


def _install_ticket_lookup(monkeypatch, ticket_data):
    state = deepcopy(ticket_data)

    async def ticket(_mongo, query):
        return deepcopy(state) if query.get("_id") == state["_id"] else None

    async def acquire(
        _mongo,
        ticket_id,
        *,
        channel_id,
        thread_id,
        guild_id,
        user_id,
        ticket_type,
        token,
        step,
        target_id,
    ):
        if (
            ticket_id != state["_id"]
            or state.get("status") != "open"
            or state.get("opening_post_intent") is not None
            or int(state.get("channel_id") or 0) != int(channel_id)
            or int(state.get("thread_id") or 0) != int(thread_id)
            or int(state.get("guild_id") or 0) != int(guild_id)
            or int(state.get("user_id") or 0) != int(user_id)
            or state.get("ticket_type") != ticket_type
        ):
            return None
        state["opening_post_intent"] = {
            "token": token,
            "step": step,
            "target_id": target_id,
        }
        return deepcopy(state)

    async def clear(_mongo, ticket_id, *, token, step):
        intent = state.get("opening_post_intent") or {}
        if (
            ticket_id != state["_id"]
            or intent.get("token") != token
            or intent.get("step") != step
        ):
            return False
        state.pop("opening_post_intent", None)
        return True

    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor.store, "acquire_opening_post_intent", acquire)
    monkeypatch.setattr(monitor.store, "clear_opening_post_intent", clear)
    return state


def _install_passthrough_intents(monkeypatch):
    async def acquire(_mongo, _ticket_id, **kwargs):
        return {"opening_post_intent": {
            "token": kwargs["token"],
            "step": kwargs["step"],
            "target_id": kwargs["target_id"],
        }}

    async def clear(_mongo, _ticket_id, **_kwargs):
        return True

    monkeypatch.setattr(monitor.store, "acquire_opening_post_intent", acquire)
    monkeypatch.setattr(monitor.store, "clear_opening_post_intent", clear)


def test_committed_ticket_outbox_survives_event_timeout_and_later_drives(
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    automation = _RecoveryAutomation([], now)
    ticket_data = _committed_ticket()
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest()
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)
    real_sleep = asyncio.sleep

    async def no_delay(_delay):
        await real_sleep(0)

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)

    queued = asyncio.run(monitor.ensure_ticket_automation_delivery(
        mongo, ticket_data, now=now,
    ))
    assert queued["initial_delivery"]["status"] == "retry"

    result = asyncio.run(monitor.ensure_and_deliver_ticket_automation(
        bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
    ))
    repeated = asyncio.run(monitor.ensure_and_deliver_ticket_automation(
        bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
    ))

    assert result["completed"] == 1
    assert repeated["processed"] == 0
    assert automation.rows["91"]["initial_delivery"]["status"] == "complete"
    assert len(rest.messages) == 5


def test_accepted_but_unacknowledged_post_is_inspected_not_replayed(monkeypatch):
    now = datetime.now(timezone.utc)
    clock = [now]
    automation = _RecoveryAutomation([], now)
    ticket_data = _committed_ticket(96)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest(accepted_failures=1)
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: clock[0])
    real_sleep = asyncio.sleep

    async def no_delay(_delay):
        await real_sleep(0)

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)

    with pytest.raises(RuntimeError, match="remains retryable"):
        asyncio.run(monitor.ensure_and_deliver_ticket_automation(
            bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
        ))

    pending = automation.rows["96"]["initial_delivery"]
    assert pending["status"] == "retry"
    assert pending["needs_history_inspection"] is True
    assert pending["ambiguous_step"] == "welcome"
    assert pending["retry_after"] == now + monitor.DELIVERY_RETRY_BACKOFF
    assert len(rest.messages) == 1

    clock[0] = now + monitor.DELIVERY_RETRY_BACKOFF + timedelta(seconds=1)
    automation.now = clock[0]
    result = asyncio.run(monitor.ensure_and_deliver_ticket_automation(
        bot=bot, mongo=mongo, ticket_data=ticket_data, now=clock[0],
    ))

    assert result["completed"] == 1
    assert rest.send_calls == 5
    assert len(rest.messages) == 5
    assert sum(
        "Welcome! Thank you for your interest!" in message.content
        for message in rest.messages
    ) == 1


def test_history_fetch_failure_stays_pending_without_resend(monkeypatch):
    now = datetime.now(timezone.utc)
    clock = [now]
    automation = _RecoveryAutomation([], now)
    ticket_data = _committed_ticket(100)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )

    class HistoryUnavailableRest(_OnlineDeliveryRest):
        def fetch_messages(self, _channel_id):
            raise TimeoutError("Discord history unavailable")

    rest = HistoryUnavailableRest()
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: clock[0])

    with pytest.raises(RuntimeError, match="remains retryable"):
        asyncio.run(monitor.ensure_and_deliver_ticket_automation(
            bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
        ))

    first_retry = automation.rows["100"]["initial_delivery"]["retry_after"]
    assert rest.send_calls == 0
    clock[0] = first_retry + timedelta(seconds=1)
    automation.now = clock[0]
    result = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, only_channel_id=100, now=clock[0],
    ))

    assert result["failed"] == 1
    assert automation.rows["100"]["initial_delivery"]["status"] == "retry"
    assert automation.rows["100"]["initial_delivery"][
        "needs_history_inspection"
    ] is True
    assert rest.send_calls == 0


def test_concurrent_gateway_and_postcommit_drivers_have_one_owner(monkeypatch):
    now = datetime.now(timezone.utc)
    automation = _RecoveryAutomation([], now)
    ticket_data = _committed_ticket(92)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest()
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)
    real_sleep = asyncio.sleep

    async def no_delay(_delay):
        await real_sleep(0)

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)

    async def scenario():
        await monitor.ensure_ticket_automation_delivery(
            mongo, ticket_data, now=now,
        )
        rest.send_started = asyncio.Event()
        rest.release_send = asyncio.Event()
        first = asyncio.create_task(
            monitor.ensure_and_deliver_ticket_automation(
                bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
            )
        )
        await rest.send_started.wait()
        second = asyncio.create_task(
            monitor.ensure_and_deliver_ticket_automation(
                bot=bot, mongo=mongo, ticket_data=ticket_data, now=now,
            )
        )
        second_result = await asyncio.gather(second, return_exceptions=True)
        rest.release_send.set()
        await first
        return second_result[0]

    second_result = asyncio.run(scenario())

    assert isinstance(second_result, RuntimeError)
    assert len(rest.messages) == 5
    assert automation.rows["92"]["initial_delivery"]["status"] == "complete"


def test_slow_post_cannot_be_taken_over_within_rest_latency_budget(monkeypatch):
    started = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    in_flight = started + timedelta(seconds=181)
    clock = [started]
    document = monitor.build_automation_document(
        channel_id=103,
        thread_id=104,
        guild_id=7,
        user_id=203,
        ticket_type="main",
        now=started,
        initial_delivery={
            "status": "retry",
            "questionnaire_sent": True,
            "staff_privacy_sent": True,
            "staff_how_heard_sent": True,
            "staff_hook_sent": True,
            "staff_fwa_donation_sent": True,
            "message_plan": monitor._delivery_message_plan(
                user_id=203,
                ticket_type="main",
                recruiter_role=None,
                guild_icon_url=None,
            ),
        },
    )
    automation = _RecoveryAutomation([document], started)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest()
    _install_ticket_lookup(monkeypatch, _committed_ticket(103))
    monkeypatch.setattr(monitor, "delivery_now", lambda: clock[0])

    async def scenario():
        claimed = await monitor.claim_automation_delivery(
            mongo, document, now=started,
        )
        rest.send_started = asyncio.Event()
        rest.release_send = asyncio.Event()
        delivery = asyncio.create_task(
            monitor.deliver_claimed_automation(rest, mongo, claimed)
        )
        await rest.send_started.wait()

        clock[0] = in_flight
        automation.now = in_flight
        contender = await monitor.claim_automation_delivery(
            mongo, document, now=in_flight,
        )
        assert contender is None

        rest.release_send.set()
        await delivery

    asyncio.run(scenario())

    assert monitor.DELIVERY_LEASE > timedelta(seconds=180)
    assert rest.send_calls == 1
    assert automation.rows["103"]["initial_delivery"]["status"] == "complete"


def test_stale_cursor_checkpoint_cannot_replay_a_completed_step(monkeypatch):
    now = datetime.now(timezone.utc)
    ticket_data = _committed_ticket(97)
    current = monitor.build_automation_document(
        channel_id=97,
        thread_id=98,
        guild_id=7,
        user_id=197,
        ticket_type="main",
        now=now,
        initial_delivery={"status": "retry", "welcome_sent": True},
    )

    class StaleCursorAutomation(_RecoveryAutomation):
        def find(self, _query):
            stale = deepcopy(self.rows["97"])
            stale["initial_delivery"].pop("welcome_sent", None)
            return _RecoveryCursor([stale])

    automation = StaleCursorAutomation([current], now)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest()
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    result = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, only_channel_id=97, now=now,
    ))

    assert result["completed"] == 1
    assert rest.send_calls == 4
    assert rest.messages[0].content == ""


def test_claim_clock_is_read_after_slow_channel_preflight(monkeypatch):
    before = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    after = before + timedelta(minutes=3)
    ticket_data = _committed_ticket(98)
    row = monitor.build_automation_document(
        channel_id=98,
        thread_id=99,
        guild_id=7,
        user_id=198,
        ticket_type="main",
        now=before,
        initial_delivery={"status": "retry"},
    )
    automation = _RecoveryAutomation([row], before)
    mongo = SimpleNamespace(ticket_automation_state=automation)
    preflight_complete = False
    claim_times = []

    async def ticket(_mongo, _query):
        return ticket_data

    class Rest:
        async def fetch_channel(self, _channel_id):
            nonlocal preflight_complete
            preflight_complete = True
            return SimpleNamespace(
                guild_id=7,
                type=monitor.hikari.ChannelType.GUILD_TEXT,
                name="main-98-candidate",
            )

    async def claim(_mongo, _document, *, now):
        claim_times.append(now)
        return None

    async def no_open_tickets(_mongo, _query):
        return []

    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor.store, "find", no_open_tickets)
    monkeypatch.setattr(
        monitor, "delivery_now", lambda: after if preflight_complete else before,
    )
    monkeypatch.setattr(monitor, "claim_automation_delivery", claim)

    asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=SimpleNamespace(rest=Rest()),
        mongo=mongo,
        only_channel_id=98,
        now=before,
    ))

    assert claim_times == [after]


def test_each_batch_row_claim_uses_fresh_time(monkeypatch):
    started = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

    def row(channel_id):
        return monitor.build_automation_document(
            channel_id=channel_id,
            thread_id=channel_id + 1,
            guild_id=7,
            user_id=channel_id + 100,
            ticket_type="main",
            now=started,
            initial_delivery={"status": "retry"},
        )

    automation = _RecoveryAutomation([row(101), row(102)], started)
    mongo = SimpleNamespace(ticket_automation_state=automation)
    claim_times = []
    moments = iter([
        started + timedelta(seconds=1),
        started + timedelta(minutes=4),
    ])

    async def ticket(_mongo, query):
        channel_id = int(query["_id"].removeprefix("ticket_"))
        return {
            **_committed_ticket(channel_id),
            "status": "denied",
        }

    async def claim(_mongo, _document, *, now):
        claim_times.append(now)
        return None

    async def no_open_tickets(_mongo, _query):
        return []

    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor.store, "find", no_open_tickets)
    monkeypatch.setattr(monitor, "delivery_now", lambda: next(moments))
    monkeypatch.setattr(monitor, "claim_automation_delivery", claim)

    result = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=SimpleNamespace(rest=SimpleNamespace()),
        mongo=mongo,
        now=started,
    ))

    assert result["processed"] == 2
    assert claim_times == [
        started + timedelta(seconds=1),
        started + timedelta(minutes=4),
    ]


class _FailFirstOutboxInsert(_RecoveryAutomation):
    def __init__(self, rows, now):
        super().__init__(rows, now)
        self.failed = False

    async def insert_one(self, document):
        if not self.failed:
            self.failed = True
            raise TimeoutError("outbox insert unavailable")
        return await super().insert_one(document)


@pytest.mark.parametrize("failure_mode", ["mongo", "discord"])
def test_online_retry_recovers_postcommit_failures_without_restart(
    monkeypatch, failure_mode,
):
    now = datetime.now(timezone.utc)
    automation_type = (
        _FailFirstOutboxInsert if failure_mode == "mongo" else _RecoveryAutomation
    )
    automation = automation_type([], now)
    ticket_data = _committed_ticket(93 if failure_mode == "mongo" else 94)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=_OnlineSetup(),
    )
    rest = _OnlineDeliveryRest(failures=3 if failure_mode == "discord" else 0)
    bot = _online_delivery_bot(rest)
    _install_ticket_lookup(monkeypatch, ticket_data)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)
    monkeypatch.setattr(
        monitor, "DELIVERY_BACKGROUND_RETRY_DELAYS_SECONDS", (0,),
    )
    monkeypatch.setattr(monitor, "DELIVERY_RETRY_BACKOFF", timedelta(0))
    real_sleep = asyncio.sleep

    async def no_delay(_delay):
        await real_sleep(0)

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)

    async def scenario():
        task = monitor.schedule_ticket_automation_delivery_retry(
            bot=bot, mongo=mongo, ticket_data=ticket_data,
        )
        await asyncio.wait_for(task, timeout=1)
        await real_sleep(0)

    asyncio.run(scenario())

    channel_key = str(ticket_data["channel_id"])
    assert automation.rows[channel_key]["initial_delivery"]["status"] == "complete"
    assert len(rest.messages) == 5
    assert channel_key not in {
        str(channel_id) for channel_id in monitor._delivery_retry_tasks
    }


def test_delivery_retry_workers_stop_before_dependencies(monkeypatch):
    ticket_data = _committed_ticket(95)

    async def unavailable(_mongo, _query):
        raise TimeoutError("Mongo unavailable")

    monkeypatch.setattr(monitor.store, "find_one", unavailable)
    monkeypatch.setattr(
        monitor, "DELIVERY_BACKGROUND_RETRY_DELAYS_SECONDS", (3_600,),
    )

    async def scenario():
        task = monitor.schedule_ticket_automation_delivery_retry(
            bot=SimpleNamespace(), mongo=SimpleNamespace(), ticket_data=ticket_data,
        )
        await asyncio.sleep(0)
        assert not task.done()
        stopping = asyncio.create_task(
            monitor.stop_ticket_automation_delivery_retries()
        )
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="scheduling is stopping"):
            monitor.schedule_ticket_automation_delivery_retry(
                bot=SimpleNamespace(),
                mongo=SimpleNamespace(),
                ticket_data=_committed_ticket(99),
            )
        await stopping
        assert task.cancelled()
        assert monitor._delivery_retry_tasks == {}
        await monitor.start_ticket_automation_delivery_retries()
        assert monitor._delivery_retry_stopping is False

    asyncio.run(scenario())


def test_monitor_recovery_resumes_each_eligible_delivery_once(monkeypatch):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    clock = [now]

    def row(identifier, status, *, lease=None, **steps):
        delivery = {"status": status, **steps}
        if lease is not None:
            delivery["lease_until"] = lease
        return {
            "_id": str(identifier),
            "kind": "legacy_initial_delivery",
            "route": "legacy",
                "runtime": "legacy_channel",
                "channel_id": identifier,
                "thread_id": identifier + 1,
                "guild_id": 7,
                "user_id": identifier + 100,
            "ticket_type": "main",
            "initial_delivery": delivery,
        }

    rows = [
        row(41, "retry", welcome_sent=True),
        row(
            42,
            "processing",
            lease=now - timedelta(seconds=1),
            questionnaire_sent=True,
        ),
        row(43, "processing", lease=now + timedelta(minutes=1)),
        row(44, "complete"),
        {**row(45, "retry"), "kind": "ticket_staff_context"},
    ]
    automation = _RecoveryAutomation(rows, now)

    class Setup:
        async def find_one(self, _query):
            return {}

    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=Setup(),
    )

    async def ticket(_mongo, query):
        channel_id = int(query["_id"].removeprefix("ticket_"))
        return {
            "_id": query["_id"],
            "type": "ticket",
            "status": "open",
                "channel_id": channel_id,
                "thread_id": channel_id + 1,
                "guild_id": 7,
            "user_id": channel_id + 100,
            "ticket_type": "main",
        }

    async def tickets(_mongo, _query):
        return [
            await ticket(_mongo, {"_id": f"ticket_{channel_id}"})
            for channel_id in range(41, 46)
        ]

    async def no_sleep(_delay):
        return None

    class Rest:
        def __init__(self):
            self.messages = []

        async def fetch_channel(self, channel_id):
            if getattr(self, "expected_thread", None) == channel_id:
                self.expected_thread = None
                return SimpleNamespace(
                    id=channel_id,
                    parent_id=channel_id - 1,
                    guild_id=7,
                    type=monitor.hikari.ChannelType.GUILD_PRIVATE_THREAD,
                    name=f"staff-{channel_id - 1}",
                )
            self.expected_thread = channel_id + 1
            return SimpleNamespace(
                id=channel_id,
                guild_id=7,
                type=monitor.hikari.ChannelType.GUILD_TEXT,
                name=f"main-{channel_id}-member",
            )

        def fetch_messages(self, _channel_id):
            return SimpleNamespace(
                collect=lambda factory: _collected(factory, [])
            )

        async def create_message(self, **kwargs):
            self.messages.append(kwargs)

    async def _collected(factory, rows):
        return factory(rows)

    rest = Rest()
    bot = SimpleNamespace(
        rest=rest,
        cache=SimpleNamespace(get_guild=lambda _guild_id: None),
        get_me=lambda: SimpleNamespace(id=900),
    )
    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor.store, "find", tickets)
    _install_passthrough_intents(monkeypatch)
    monkeypatch.setattr(monitor.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(monitor, "delivery_now", lambda: clock[0])

    first = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=now,
    ))
    second = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=now,
    ))

    assert first == {
        "processed": 2,
        "completed": 2,
        "cancelled": 0,
        "failed": 0,
        "pending": 1,
        "synthesized": 0,
    }
    assert second == {
        "processed": 0,
        "completed": 0,
        "cancelled": 0,
        "failed": 0,
        "pending": 1,
        "synthesized": 0,
    }
    assert len(rest.messages) == 8
    assert automation.rows["41"]["initial_delivery"]["status"] == "complete"
    assert automation.rows["42"]["initial_delivery"]["status"] == "complete"

    automation.now = now + timedelta(minutes=3)
    clock[0] = automation.now
    final = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=automation.now,
    ))
    assert final == {
        "processed": 1,
        "completed": 1,
        "cancelled": 0,
        "failed": 0,
        "pending": 0,
        "synthesized": 0,
    }
    assert len(rest.messages) == 13


def test_monitor_recovery_synthesizes_missing_row_without_replaying_history(
    monkeypatch,
):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    automation = _RecoveryAutomation([], now)
    ticket_data = {
        "_id": "ticket_61",
        "type": "ticket",
        "status": "open",
        "channel_id": 61,
        "thread_id": 62,
        "guild_id": 7,
        "user_id": 161,
        "ticket_type": "main",
    }

    class Setup:
        async def find_one(self, _query):
            return {}

    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=Setup(),
    )

    async def tickets(_mongo, query):
        return [ticket_data] if query == {"status": "open"} else []

    async def ticket(_mongo, query):
        return ticket_data if query["_id"] == ticket_data["_id"] else None

    class History:
        def __init__(self, rows):
            self.rows = rows

        async def collect(self, factory):
            return factory(self.rows)

    history = [
        SimpleNamespace(
            author=SimpleNamespace(id=900),
            content=(
                "<@161> Welcome! Thank you for your interest! "
                "**@Main Recruiter** will be with you shortly, in the "
                "meanwhile, please answer the following questions..."
            ),
            components=(),
        ),
        SimpleNamespace(
            author=SimpleNamespace(id=900),
            content="",
            components=tuple(monitor._questionnaire_components("main", None)),
        ),
    ]
    plan = monitor._delivery_message_plan(
        user_id=161,
        ticket_type="main",
        recruiter_role=None,
        guild_icon_url=None,
    )
    staff_history = [
        SimpleNamespace(
            author=SimpleNamespace(id=900),
            content=plan[field],
            components=(),
        )
        for field in (
            "staff_privacy_content",
            "staff_how_heard_content",
            "staff_hook_content",
        )
    ]

    class Rest:
        def __init__(self):
            self.messages = []

        async def fetch_channel(self, channel_id):
            if channel_id == 62:
                return SimpleNamespace(
                    guild_id=7,
                    parent_id=61,
                    type=monitor.hikari.ChannelType.GUILD_PRIVATE_THREAD,
                    name="staff-61",
                )
            return SimpleNamespace(
                guild_id=7,
                type=monitor.hikari.ChannelType.GUILD_TEXT,
                name="main-61-member",
            )

        def fetch_messages(self, channel_id):
            return History(staff_history if channel_id == 62 else history)

        async def create_message(self, **kwargs):
            self.messages.append(kwargs)

    rest = Rest()
    bot = SimpleNamespace(
        rest=rest,
        cache=SimpleNamespace(get_guild=lambda _guild_id: None),
        get_me=lambda: SimpleNamespace(id=900),
    )
    monkeypatch.setattr(monitor.store, "find", tickets)
    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    first = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=now,
    ))
    second = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=now,
    ))

    assert first == {
        "processed": 1,
        "completed": 1,
        "cancelled": 0,
        "failed": 0,
        "pending": 0,
        "synthesized": 1,
    }
    assert second == {
        "processed": 0,
        "completed": 0,
        "cancelled": 0,
        "failed": 0,
        "pending": 0,
        "synthesized": 0,
    }
    assert rest.messages == []
    delivery = automation.rows["61"]["initial_delivery"]
    assert delivery["status"] == "complete"
    assert delivery["welcome_sent"] is True
    assert delivery["questionnaire_sent"] is True


def test_monitor_recovery_discovers_missing_rows_beyond_batch_limit(monkeypatch):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    automation = _RecoveryAutomation([], now)
    tickets_by_id = {
        f"ticket_{channel_id}": {
            "_id": f"ticket_{channel_id}",
            "type": "ticket",
                "status": "open",
                "channel_id": channel_id,
                "thread_id": channel_id + 1000,
                "guild_id": 7,
            "user_id": channel_id + 100,
            "ticket_type": "main",
        }
        for channel_id in range(100, 126)
    }

    class Setup:
        async def find_one(self, _query):
            return {}

    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=Setup(),
    )

    async def tickets(_mongo, _query):
        return list(tickets_by_id.values())

    async def ticket(_mongo, query):
        return tickets_by_id.get(query["_id"])

    class History:
        def __init__(self, rows):
            self.rows = rows

        async def collect(self, factory):
            return factory(self.rows)

    class Rest:
        async def fetch_channel(self, channel_id):
            if channel_id >= 1100:
                return SimpleNamespace(
                    guild_id=7,
                    parent_id=channel_id - 1000,
                    type=monitor.hikari.ChannelType.GUILD_PRIVATE_THREAD,
                    name=f"staff-{channel_id - 1000}",
                )
            return SimpleNamespace(
                guild_id=7,
                type=monitor.hikari.ChannelType.GUILD_TEXT,
                name=f"main-{channel_id}-member",
            )

        def fetch_messages(self, channel_id):
            if channel_id >= 1100:
                plan = monitor._delivery_message_plan(
                    user_id=channel_id - 900,
                    ticket_type="main",
                    recruiter_role=None,
                    guild_icon_url=None,
                )
                return History([
                    SimpleNamespace(
                        author=SimpleNamespace(id=900),
                        content=plan[field],
                        components=(),
                    )
                    for field in (
                        "staff_privacy_content",
                        "staff_how_heard_content",
                        "staff_hook_content",
                    )
                ])
            return History([
                SimpleNamespace(
                    author=SimpleNamespace(id=900),
                    content=(
                        f"<@{channel_id + 100}> Welcome! Thank you for your "
                        "interest! **@Main Recruiter** will be with you shortly, "
                        "in the meanwhile, please answer the following questions..."
                    ),
                    components=(),
                ),
                SimpleNamespace(
                    author=SimpleNamespace(id=900),
                    content="",
                    components=tuple(
                        monitor._questionnaire_components("main", None)
                    ),
                ),
            ])

        async def create_message(self, **_kwargs):
            raise AssertionError("existing opening messages must not be replayed")

    bot = SimpleNamespace(
        rest=Rest(),
        cache=SimpleNamespace(get_guild=lambda _guild_id: None),
        get_me=lambda: SimpleNamespace(id=900),
    )
    monkeypatch.setattr(monitor.store, "find", tickets)
    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    first = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, limit=25, now=now,
    ))
    second = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, limit=25, now=now,
    ))

    assert first["synthesized"] == first["processed"] == 25
    assert first["completed"] == 25
    assert second["synthesized"] == second["processed"] == 1
    assert second["completed"] == 1
    assert len(automation.rows) == 26
    assert all(
        row["initial_delivery"]["status"] == "complete"
        for row in automation.rows.values()
    )


def test_terminal_delivery_cancels_but_missing_identity_stays_pending(monkeypatch):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

    def row(identifier):
        return {
            "_id": str(identifier),
            "kind": "legacy_initial_delivery",
            "route": "legacy",
                "runtime": "legacy_channel",
                "channel_id": identifier,
                "thread_id": identifier + 1,
                "guild_id": 7,
                "user_id": identifier + 100,
            "ticket_type": "main",
            "initial_delivery": {"status": "retry"},
        }

    automation = _RecoveryAutomation([row(71), row(72)], now)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=SimpleNamespace(),
    )
    terminal = {
        "_id": "ticket_71",
        "type": "ticket",
            "status": "denied",
            "channel_id": 71,
            "thread_id": 72,
            "guild_id": 7,
        "user_id": 171,
        "ticket_type": "main",
    }

    async def tickets(_mongo, _query):
        return []

    async def ticket(_mongo, query):
        return terminal if query["_id"] == terminal["_id"] else None

    class Rest:
        async def fetch_channel(self, _channel_id):
            raise AssertionError("terminal or missing delivery must not touch Discord")

    bot = SimpleNamespace(rest=Rest(), cache=None)
    monkeypatch.setattr(monitor.store, "find", tickets)
    monkeypatch.setattr(monitor.store, "find_one", ticket)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    result = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot, mongo=mongo, now=now,
    ))

    assert result == {
        "processed": 2,
        "completed": 0,
        "cancelled": 1,
        "failed": 1,
        "pending": 1,
        "synthesized": 0,
    }
    assert automation.rows["71"]["initial_delivery"]["status"] == "cancelled"
    assert automation.rows["72"]["initial_delivery"]["status"] == "retry"
    assert "unavailable" in automation.rows["72"]["initial_delivery"]["last_error"]


@pytest.mark.parametrize("send_fails", [False, True])
def test_channel_create_event_uses_owned_delivery_calls(monkeypatch, send_fails):
    calls = []
    owner = "event-owner"

    class Setup:
        async def find_one(self, _query):
            return {}

    mongo = SimpleNamespace(ticket_setup=Setup())

    async def ticket_data(*_args, **_kwargs):
        return {
            "_id": "ticket_81",
            "channel_id": 81,
            "guild_id": 7,
            "user_id": 181,
            "thread_id": 82,
            "ticket_type": "main",
            "status": "open",
        }

    def schedule(**kwargs):
        calls.append(("schedule", kwargs["ticket_data"]["channel_id"]))

    async def execute(**kwargs):
        calls.append(("execute", kwargs["ticket_data"]["channel_id"]))
        if send_fails:
            raise RuntimeError("delivery failed")
        return {"completed": 1}

    async def claim(_mongo, document, **_kwargs):
        claimed = deepcopy(document)
        claimed["initial_delivery"] = {
            "status": "processing",
            "lease_owner": owner,
            "lease_until": datetime.now(timezone.utc) + timedelta(minutes=2),
        }
        return claimed

    async def assert_lease(_mongo, channel_id, owner_token, **_kwargs):
        calls.append(("assert", channel_id, owner_token))

    async def send(_rest, **kwargs):
        calls.append(("send", kwargs["channel"]))
        if send_fails:
            raise RuntimeError("delivery failed")

    async def mark(_mongo, channel_id, owner_token, step):
        calls.append(("mark", channel_id, owner_token, step))

    async def finish(_mongo, channel_id, owner_token):
        calls.append(("finish", channel_id, owner_token))

    async def release(_mongo, channel_id, owner_token, error):
        calls.append(("release", channel_id, owner_token, str(error)))
        return True

    async def no_sleep(_delay):
        return None

    rest = SimpleNamespace()
    event = SimpleNamespace(
        guild_id=7,
        channel=SimpleNamespace(
            id=81,
            name="main-81-member",
            type=monitor.hikari.ChannelType.GUILD_TEXT,
        ),
        app=SimpleNamespace(
            cache=SimpleNamespace(get_guild=lambda _guild_id: None),
            rest=rest,
        ),
    )
    monkeypatch.setattr(monitor, "mongo_client", mongo)
    monkeypatch.setattr(monitor, "wait_for_ticket_data", ticket_data)
    monkeypatch.setattr(
        monitor, "schedule_ticket_automation_delivery_retry", schedule,
    )
    monkeypatch.setattr(
        monitor, "ensure_and_deliver_ticket_automation", execute,
    )
    monkeypatch.setattr(monitor, "claim_automation_delivery", claim)
    monkeypatch.setattr(monitor, "assert_delivery_lease", assert_lease)
    monkeypatch.setattr(monitor, "send_with_retries", send)
    monkeypatch.setattr(monitor, "mark_delivery_step", mark)
    monkeypatch.setattr(monitor, "finish_automation_delivery", finish)
    monkeypatch.setattr(monitor, "release_automation_delivery", release)
    monkeypatch.setattr(monitor.asyncio, "sleep", no_sleep)

    asyncio.run(monitor.on_channel_create(event))

    assert calls == [("schedule", 81), ("execute", 81)]
