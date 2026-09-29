import asyncio
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from utils import recruit_message_delivery as delivery
from utils import recruit_goblin_challenges as challenges
from tests.test_recruit_goblin_challenges import db


class History:
    def __init__(self, messages):
        self.messages = messages

    def limit(self, amount):
        self.messages = self.messages[:amount]
        return self

    def __aiter__(self):
        async def iterate():
            for message in self.messages:
                yield message

        return iterate()


def rest_client(messages=()):
    return NS(
        create_message=AsyncMock(return_value=NS(id=123)),
        fetch_my_user=AsyncMock(return_value=NS(id=99)),
        fetch_messages=lambda *args, **kwargs: History(list(messages)),
    )


async def send(mongo, rest):
    return await delivery.deliver(
        mongo,
        rest,
        kind="family_code_confirmation",
        session_id="session1",
        guild_id=1,
        channel_id=44,
        user_id=22,
        components=["unchanged"],
        user_mentions=[22],
    )


def receipt(mongo):
    return next(iter(mongo.deliveries.documents.values()))


def test_success_survives_new_worker_and_has_readable_identity():
    async def run():
        mongo, rest = db(), rest_client()
        assert (await send(mongo, rest)).id == 123
        row = receipt(mongo)
        assert row["_id"] == "family_code_confirmation:44:22:session1"
        assert len(row["discord_nonce"]) <= 25
        assert row["status"] == "sent"
        replacement = rest_client()
        assert (await send(mongo, replacement)).id == 123
        replacement.create_message.assert_not_awaited()
        assert "components" not in row

    asyncio.run(run())


def test_short_ambiguous_retry_reuses_nonce_and_discord_message():
    async def run():
        mongo, rest = db(), rest_client()
        accepted = {}

        async def discord(**kwargs):
            nonce = kwargs["nonce"]
            if nonce not in accepted:
                accepted[nonce] = NS(id=123)
                raise ConnectionError("Response lost after Discord accepted message")
            return accepted[nonce]

        rest.create_message.side_effect = discord
        with pytest.raises(ConnectionError):
            await send(mongo, rest)
        first = receipt(mongo)["first_attempt_at"]
        assert (await send(mongo, rest)).id == 123
        assert len(accepted) == 1
        assert receipt(mongo)["first_attempt_at"] == first

    asyncio.run(run())


@pytest.mark.parametrize("found", [True, False])
def test_restart_after_failed_mongo_checkpoint_reconciles_or_stops(monkeypatch, found):
    async def run():
        mongo, rest = db(), rest_client()
        original = mongo.deliveries.update_one

        async def fail_checkpoint(query, update, **kwargs):
            if update.get("$set", {}).get("status") == "sent":
                raise ConnectionError("Mongo unavailable")
            return await original(query, update, **kwargs)

        mongo.deliveries.update_one = fail_checkpoint
        with pytest.raises(ConnectionError):
            await send(mongo, rest)
        mongo.deliveries.update_one = original
        row = receipt(mongo)
        future = delivery.utcnow() + timedelta(minutes=3)
        monkeypatch.setattr(delivery, "utcnow", lambda: future)
        # A matching nonce from another author must never count as our delivery.
        messages = [
            NS(id=123, author=NS(id=99 if found else 88), nonce=row["discord_nonce"])
        ]
        new_worker = rest_client(messages)
        if found:
            assert (await send(mongo, new_worker)).id == 123
            assert row["recovered_from_history"] is True
        else:
            with pytest.raises(delivery.DeliveryUncertain):
                await send(mongo, new_worker)
            assert row["status"] == "needs_review"
        new_worker.create_message.assert_not_awaited()

    asyncio.run(run())


def test_cancellation_releases_claim_without_forgetting_ambiguous_send():
    async def run():
        mongo, rest = db(), rest_client()
        rest.create_message.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await send(mongo, rest)
        row = receipt(mongo)
        assert row["status"] == "retryable" and "lease_until" not in row
        assert row["first_attempt_at"]
        rest.create_message.side_effect = None
        await send(mongo, rest)
        assert row["status"] == "sent"

    asyncio.run(run())


def test_concurrent_delivery_only_sends_once():
    async def run():
        mongo, rest = db(), rest_client()
        entered, finish = asyncio.Event(), asyncio.Event()

        async def slow(**kwargs):
            entered.set()
            await finish.wait()
            return NS(id=123)

        rest.create_message.side_effect = slow
        first = asyncio.create_task(send(mongo, rest))
        await entered.wait()
        with pytest.raises(delivery.DeliveryUncertain):
            await send(mongo, rest)
        finish.set()
        await first
        assert rest.create_message.await_count == 1

    asyncio.run(run())


def test_shield_retry_keeps_challenge_session_and_completion():
    async def run():
        mongo = db()
        kwargs = dict(
            guild_id=1,
            channel_id=44,
            user_id=22,
            recruiter_id=33,
            source_message_id=100,
        )
        session = await challenges.open_challenge(mongo, **kwargs)
        row = mongo.recruit_challenges.documents[challenges.key(44, 22)]
        row["status"] = "completed"
        assert await challenges.open_challenge(mongo, **kwargs) == session
        assert row["status"] == "completed"
        with pytest.raises(ValueError):
            await challenges.open_challenge(
                mongo, **{**kwargs, "source_message_id": 99}
            )

    asyncio.run(run())


@pytest.mark.parametrize("history_error", [False, True])
def test_old_ambiguous_delivery_never_resends_without_evidence(
    monkeypatch, history_error
):
    async def run():
        mongo, rest = db(), rest_client()
        rest.create_message.side_effect = ConnectionError()
        with pytest.raises(ConnectionError):
            await send(mongo, rest)
        future = delivery.utcnow() + timedelta(minutes=3)
        monkeypatch.setattr(delivery, "utcnow", lambda: future)
        rest.create_message.side_effect = None
        if history_error:
            rest.fetch_my_user.side_effect = RuntimeError("History unavailable")
        with pytest.raises(delivery.DeliveryUncertain):
            await send(mongo, rest)
        assert rest.create_message.await_count == 1
        assert receipt(mongo)["status"] == "needs_review"

    asyncio.run(run())


def test_initial_definite_rejection_can_retry_later(monkeypatch):
    import hikari

    async def run():
        mongo, rest = db(), rest_client()
        rest.create_message.side_effect = hikari.ForbiddenError(
            url="https://discord.com", headers={}, raw_body=b""
        )
        with pytest.raises(hikari.ForbiddenError):
            await send(mongo, rest)
        assert "first_attempt_at" not in receipt(mongo)
        future = delivery.utcnow() + timedelta(minutes=3)
        monkeypatch.setattr(delivery, "utcnow", lambda: future)
        rest.create_message.side_effect = None
        await send(mongo, rest)
        assert receipt(mongo)["status"] == "sent"

    asyncio.run(run())
