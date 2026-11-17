import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import hikari
import pytest
from hikari.impl.rest import RESTClientImpl

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
    assert update["$setOnInsert"] is doc
    assert update["$set"]["initial_delivery.status"] == "processing"
    assert update["$set"]["initial_delivery.lease_until"] == now + monitor.DELIVERY_LEASE
    assert kwargs["upsert"] is True


def test_duplicate_key_means_another_worker_owns_delivery():
    mongo = _ClaimMongo(duplicate=True)

    result = asyncio.run(monitor.claim_automation_delivery(
        mongo, {"_id": "42", "channel_id": 42},
    ))

    assert result is None


def test_send_with_retries_is_bounded(monkeypatch):
    class _Rest:
        def __init__(self):
            self.calls = []

        async def create_message(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) < 3:
                raise RuntimeError("temporary")

    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(monitor.asyncio, "sleep", fake_sleep)
    rest = _Rest()

    asyncio.run(monitor.send_with_retries(
        rest, channel=42, step="welcome_sent", content="hello",
    ))

    assert len(rest.calls) == 3
    assert rest.calls == [{"channel": 42, "nonce": "tw-42-w", "content": "hello"}] * 3
    assert sleeps == [
        monitor.DELIVERY_RETRY_DELAY_SECONDS,
        monitor.DELIVERY_RETRY_DELAY_SECONDS,
    ]


@pytest.mark.parametrize("channel_id", [1, 42, hikari.Snowflake(42), 2 ** 64 - 1])
def test_initial_nonce_is_stable_short_and_distinct_per_ticket_step(channel_id):
    welcome = monitor.initial_delivery_nonce(channel_id, "welcome_sent")
    questionnaire = monitor.initial_delivery_nonce(channel_id, "questionnaire_sent")
    assert welcome == f"tw-{channel_id}-w"
    assert questionnaire == f"tw-{channel_id}-q"
    assert welcome != questionnaire
    assert len(welcome) <= 25 and len(questionnaire) <= 25
    assert welcome != monitor.initial_delivery_nonce(43 if channel_id == 42 else 42, "welcome_sent")


@pytest.mark.parametrize("channel_id,step", [
    (0, "welcome_sent"), (-1, "welcome_sent"), (2 ** 64, "welcome_sent"),
    (True, "welcome_sent"), ("42", "welcome_sent"), (42.0, "welcome_sent"),
    (42, "unknown"), (42, None), (42, []),
])
def test_invalid_message_identity_is_rejected_before_send(channel_id, step):
    rest = SimpleNamespace(create_message=AsyncMock())
    with pytest.raises(ValueError):
        asyncio.run(monitor.send_with_retries(
            rest, channel=channel_id, step=step, content="hello",
        ))
    rest.create_message.assert_not_awaited()


def test_nonce_is_identical_in_fresh_processes():
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "from extensions.events.channel.ticket_channel_monitor import initial_delivery_nonce; "
        "print(initial_delivery_nonce(18446744073709551615, 'welcome_sent'))"
    )
    results = [subprocess.check_output(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        text=True, timeout=30,
    ).splitlines()[-1] for _ in range(2)]
    assert results == ["tw-18446744073709551615-w"] * 2


def test_actual_hikari_wire_enforces_nonce_and_timeout_retries_share_identity(monkeypatch):
    requests = []
    accepted = {}

    async def fake_request(_self, route, **kwargs):
        payload = kwargs["json"]
        requests.append(dict(payload))
        assert payload["enforce_nonce"] is True
        nonce = payload["nonce"]
        # Simulate Discord accepting the POST, followed by a lost response.
        accepted.setdefault(nonce, {"id": str(100 + len(accepted))})
        if len(requests) <= 2:
            raise asyncio.TimeoutError("accepted response was lost")
        return accepted[nonce]

    sleep = AsyncMock()
    monkeypatch.setattr(monitor.asyncio, "sleep", sleep)

    async def scenario():
        rest = object.__new__(RESTClientImpl)
        rest._entity_factory = MagicMock()
        with patch.object(RESTClientImpl, "_request", fake_request):
            await monitor.send_with_retries(
                rest, channel=42, step="welcome_sent", content="welcome",
                user_mentions=True, role_mentions=True,
            )
            assert len(requests) == 3 and len(accepted) == 1
            assert requests[0] == requests[1] == requests[2]
            # A resumed logical step reuses its identity; other steps/tickets
            # retain distinct identities. This is a transport simulation only.
            await monitor.send_with_retries(
                rest, channel=42, step="welcome_sent", content="welcome",
                user_mentions=True, role_mentions=True,
            )
            assert len(accepted) == 1
            await monitor.send_with_retries(
                rest, channel=42, step="questionnaire_sent", content="questions",
            )
            await monitor.send_with_retries(
                rest, channel=43, step="welcome_sent", content="welcome",
            )
        assert len(accepted) == 3
        assert requests[0]["nonce"] == "tw-42-w"
        assert requests[-2]["nonce"] == "tw-42-q"
        assert requests[-1]["nonce"] == "tw-43-w"
        assert requests[0]["allowed_mentions"] == {"parse": ["users", "roles"]}

    asyncio.run(scenario())
    assert sleep.await_count == 2
    assert all(call.args == (monitor.DELIVERY_RETRY_DELAY_SECONDS,) for call in sleep.await_args_list)


def test_exhausted_retries_keep_nonce_and_raise_last_error(monkeypatch):
    errors = [RuntimeError("first"), TimeoutError("second"), RuntimeError("last")]
    rest = SimpleNamespace(create_message=AsyncMock(side_effect=errors))
    sleep = AsyncMock()
    monkeypatch.setattr(monitor.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="last"):
        asyncio.run(monitor.send_with_retries(
            rest, channel=42, step="questionnaire_sent", content="questions",
        ))
    assert rest.create_message.await_count == 3
    assert {call.kwargs["nonce"] for call in rest.create_message.await_args_list} == {"tw-42-q"}
    assert sleep.await_count == 2


def test_cancellation_does_not_retry_or_sleep(monkeypatch):
    rest = SimpleNamespace(create_message=AsyncMock(side_effect=asyncio.CancelledError))
    sleep = AsyncMock()
    monkeypatch.setattr(monitor.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor.send_with_retries(
            rest, channel=42, step="welcome_sent", content="welcome",
        ))
    assert rest.create_message.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize("ticket_type", ["main", "fwa"])
@pytest.mark.parametrize("role_id", [None, 123])
@pytest.mark.parametrize("welcome_sent", [False, True])
def test_both_ticket_types_bind_steps_without_changing_mentions_or_checkpoints(
    monkeypatch, ticket_type, role_id, welcome_sent,
):
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={
        f"{ticket_type}_recruiter_role": role_id,
    })))
    monkeypatch.setattr(monitor, "mongo_client", mongo)
    monkeypatch.setattr(monitor, "wait_for_ticket_data", AsyncMock(return_value={
        "_id": "ticket_42", "user_id": 7, "thread_id": 99,
    }))
    monkeypatch.setattr(monitor, "claim_automation_delivery", AsyncMock(return_value={
        "initial_delivery": {"welcome_sent": welcome_sent},
    }))
    marked, finished, released = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(monitor, "mark_delivery_step", marked)
    monkeypatch.setattr(monitor, "finish_automation_delivery", finished)
    monkeypatch.setattr(monitor, "release_automation_delivery", released)
    monkeypatch.setattr(monitor.asyncio, "sleep", AsyncMock())
    rest = SimpleNamespace(create_message=AsyncMock())
    event = SimpleNamespace(
        channel=SimpleNamespace(name=f"{ticket_type}-42", id=42), guild_id=1,
        app=SimpleNamespace(rest=rest, cache=SimpleNamespace(get_guild=lambda guild_id: None)),
    )
    asyncio.run(monitor.on_channel_create(event))
    calls = rest.create_message.await_args_list
    assert len(calls) == (1 if welcome_sent else 2)
    if not welcome_sent:
        welcome = calls[0].kwargs
        role_text = f"<@&{role_id}> " if role_id else f"**@{'FWA' if ticket_type == 'fwa' else 'Main'} Recruiter** "
        assert welcome == {
            "channel": 42, "nonce": "tw-42-w",
            "content": "<@7> Welcome! Thank you for your interest! " + role_text + "will be with you shortly, in the meanwhile, please answer the following questions...",
            "user_mentions": True, "role_mentions": bool(role_id),
        }
    questions = calls[-1].kwargs
    assert questions["channel"] == 42 and questions["nonce"] == "tw-42-q"
    assert questions["user_mentions"] is True
    assert "role_mentions" not in questions
    assert questions["components"]
    assert [call.args for call in marked.await_args_list] == (
        [(mongo, 42, "questionnaire_sent")] if welcome_sent else
        [(mongo, 42, "welcome_sent"), (mongo, 42, "questionnaire_sent")]
    )
    finished.assert_awaited_once_with(mongo, 42)
    released.assert_not_awaited()
