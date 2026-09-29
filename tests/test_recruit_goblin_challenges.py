import asyncio
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from utils import recruit_goblin_challenges as storage
from extensions.events.message import goblin_challenge as handler, how_to_ping
from tests.test_recruit_family_codes import _Collection


class Collection(_Collection):
    async def update_one(self, query, update, upsert=False):
        if await self.find_one(query) is None and upsert:
            update = {
                **update,
                "$set": {**update.get("$setOnInsert", {}), **update.get("$set", {})},
            }
        return await super().update_one(query, update, upsert=upsert)


def db(legacy=()):
    return NS(recruit_challenges=Collection(), button_store=Collection(legacy))


def event(user=22, content="Goblin <@33>"):
    return NS(
        is_bot=False,
        channel_id=44,
        author_id=user,
        content=content,
        message=NS(
            user_mentions_ids=[33], add_reaction=AsyncMock(), respond=AsyncMock()
        ),
    )


async def open_one(mongo, user=22):
    await storage.open_challenge(
        mongo, guild_id=1, channel_id=44, user_id=user, recruiter_id=33
    )


def init(monkeypatch, mongo, send=None):
    send = send or AsyncMock(return_value=NS(id=555))
    monkeypatch.setattr(handler, "mongo_client", mongo)
    monkeypatch.setattr(handler, "bot_instance", NS(rest=NS(create_message=send)))
    return send


def test_image_only_and_bot_responses_do_not_touch_storage(monkeypatch):
    mongo = NS(recruit_challenges=NS(find_one=AsyncMock()))
    init(monkeypatch, mongo)
    assert not asyncio.run(handler.check_goblin_challenge(event(content=None)))
    bot_event = event()
    bot_event.is_bot = True
    assert not asyncio.run(handler.check_goblin_challenge(bot_event))
    mongo.recruit_challenges.find_one.assert_not_awaited()


def test_two_recruits_in_same_channel_complete_independently(monkeypatch):
    async def run():
        mongo = db()
        send = init(monkeypatch, mongo)
        await open_one(mongo, 22)
        await open_one(mongo, 23)
        assert not await handler.check_goblin_challenge(event(24))
        assert await handler.check_goblin_challenge(event(23))
        assert (
            mongo.recruit_challenges.documents[storage.key(44, 22)]["status"]
            == "pending"
        )
        assert await handler.check_goblin_challenge(event(22))
        assert send.await_count == 2
        assert all(
            row["status"] == "completed"
            for row in mongo.recruit_challenges.documents.values()
        )
        assert not await handler.check_goblin_challenge(event(22))
        assert not mongo.button_store.documents

    asyncio.run(run())


def test_send_failure_preserves_challenge_and_next_reply_succeeds(monkeypatch):
    async def run():
        mongo = db()
        send = init(monkeypatch, mongo)
        await open_one(mongo)
        send.side_effect = RuntimeError("Discord unavailable")
        await handler.check_goblin_challenge(event())
        row = mongo.recruit_challenges.documents[storage.key(44, 22)]
        assert row["status"] == "pending" and "claim_id" not in row
        send.side_effect = None
        await handler.check_goblin_challenge(event())
        assert row["status"] == "completed" and row["success_message_id"] == 555

    asyncio.run(run())


def test_concurrent_replies_only_send_one_confirmation(monkeypatch):
    async def run():
        mongo = db()
        started = asyncio.Event()
        finish = asyncio.Event()

        async def send(**kwargs):
            started.set()
            await finish.wait()
            return NS(id=555)

        mock = init(monkeypatch, mongo, AsyncMock(side_effect=send))
        await open_one(mongo)
        first = asyncio.create_task(handler.check_goblin_challenge(event()))
        await started.wait()
        await handler.check_goblin_challenge(event())
        finish.set()
        await first
        assert mock.await_count == 1

    asyncio.run(run())


def test_abandoned_claim_recovers_after_lease_and_expired_prompt_is_ignored(
    monkeypatch,
):
    async def run():
        mongo = db()
        send = init(monkeypatch, mongo)
        await open_one(mongo)
        row = mongo.recruit_challenges.documents[storage.key(44, 22)]
        await storage.claim(mongo, row)
        row["processing_until"] = storage.utcnow() - timedelta(seconds=1)
        # No process-local task/state is needed after a restart.
        await handler.check_goblin_challenge(event())
        assert send.await_count == 1
        await open_one(mongo)
        row["expires_at"] = storage.utcnow() - timedelta(seconds=1)
        assert not await handler.check_goblin_challenge(event())
        assert send.await_count == 1

    asyncio.run(run())


def test_old_completion_cannot_clear_a_replacement_prompt():
    async def run():
        mongo = db()
        await open_one(mongo)
        old = await mongo.recruit_challenges.find_one({"_id": storage.key(44, 22)})
        token = await storage.claim(mongo, old)
        await open_one(mongo)
        await storage.complete(mongo, old, token, 999)
        await storage.release(mongo, old, token)
        row = mongo.recruit_challenges.documents[storage.key(44, 22)]
        assert row["status"] == "pending" and row["session_id"] != old["session_id"]

    asyncio.run(run())


def legacy(id="old", user=22, created=None):
    return {
        "_id": id,
        "challenge_type": "goblin_ping",
        "status": "pending",
        "channel_id": 44,
        "user_id": user,
        "recruiter_id": 33,
        "created_at": created or storage.utcnow(),
    }


def test_migration_is_repeatable_newest_wins_and_unrelated_rows_untouched():
    async def run():
        older = legacy("older", created=storage.utcnow() - timedelta(hours=1))
        newer = legacy("newer")
        newer["recruiter_id"] = 88
        unrelated = {"_id": "ticket", "type": "ticket"}
        invalid = {"_id": "malformed", "challenge_type": "goblin_ping"}
        mongo = db([older, newer, unrelated, invalid])
        assert await storage.prepare_storage(mongo) == 2
        row = mongo.recruit_challenges.documents[storage.key(44, 22)]
        assert row["recruiter_id"] == 88 and row["schema_version"] == 1
        assert row["expires_at"] == newer["created_at"] + storage.TTL
        assert set(mongo.button_store.documents) == {"ticket", "malformed"}
        assert await storage.prepare_storage(mongo) == 0

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["index", "copy"])
def test_migration_failure_keeps_legacy_source(failure):
    async def run():
        mongo = db([legacy()])
        if failure == "index":
            mongo.recruit_challenges.index_error = RuntimeError("index failure")
        else:
            mongo.recruit_challenges.update_one = AsyncMock(
                side_effect=RuntimeError("copy failure")
            )
        with pytest.raises(RuntimeError):
            await storage.prepare_storage(mongo)
        assert "old" in mongo.button_store.documents

    asyncio.run(run())


def test_migration_never_overwrites_new_system_session():
    async def run():
        mongo = db([legacy()])
        await open_one(mongo)
        before = await mongo.recruit_challenges.find_one({"_id": storage.key(44, 22)})
        await storage.prepare_storage(mongo)
        assert mongo.recruit_challenges.documents[storage.key(44, 22)] == before
        assert not mongo.button_store.documents

    asyncio.run(run())


def test_how_to_ping_is_limited_to_active_recruit(monkeypatch):
    async def run():
        mongo = db()
        await open_one(mongo)
        monkeypatch.setattr(how_to_ping, "mongo_client", mongo)
        monkeypatch.setattr(how_to_ping, "bot_instance", object())
        send = AsyncMock()
        monkeypatch.setattr(how_to_ping, "send_ping_explanation", send)
        assert not await how_to_ping.check_how_to_ping(event(23, "how to ping"))
        assert await how_to_ping.check_how_to_ping(event(22, "how to ping"))
        send.assert_awaited_once_with(44, 22)

    asyncio.run(run())


def test_interrupted_migration_resumes_without_overwriting_copy():
    async def run():
        mongo = db([legacy()])
        delete = mongo.button_store.delete_one
        mongo.button_store.delete_one = AsyncMock(
            side_effect=RuntimeError("interrupted delete")
        )
        with pytest.raises(RuntimeError):
            await storage.prepare_storage(mongo)
        before = await mongo.recruit_challenges.find_one({"_id": storage.key(44, 22)})
        assert before and "old" in mongo.button_store.documents
        mongo.button_store.delete_one = delete
        await storage.prepare_storage(mongo)
        assert mongo.recruit_challenges.documents[storage.key(44, 22)] == before
        assert not mongo.button_store.documents

    asyncio.run(run())


def test_migration_preserves_naive_utc_expiry_and_does_not_revive_old_prompt(
    monkeypatch,
):
    async def run():
        old = legacy(
            created=(storage.utcnow() - timedelta(days=2)).replace(tzinfo=None)
        )
        mongo = db([old])
        init(monkeypatch, mongo)
        await storage.prepare_storage(mongo)
        row = mongo.recruit_challenges.documents[storage.key(44, 22)]
        assert row["expires_at"] < storage.utcnow()
        assert not await handler.check_goblin_challenge(event())

    asyncio.run(run())


def test_shield_receipt_is_atomic_and_survives_challenge_expiry():
    async def run():
        mongo = db()
        args = dict(message_id=777, channel_id=44, user_id=22, guild_id=1)
        claims = await asyncio.gather(
            *[storage.claim_shield(mongo, **args) for _ in range(8)]
        )
        receipts = [c for c in claims if c]
        assert len(receipts) == 1
        await storage.complete_shield(mongo, receipts[0], 888)
        # The receipt is durable Mongo state, not an in-process flag or the
        # expiring challenge. Recreating a handler cannot re-enable it.
        receipt = mongo.recruit_challenges.documents["goblin_prompt:777"]
        assert receipt["status"] == "sent" and "expires_at" not in receipt
        assert await storage.claim_shield(mongo, **args) is None
        assert await storage.claim_shield(mongo, **{**args, "message_id": 778})

    asyncio.run(run())


def test_shield_failed_attempt_can_retry_and_old_worker_cannot_finish_new_claim():
    async def run():
        mongo = db()
        args = dict(message_id=777, channel_id=44, user_id=22, guild_id=1)
        first = await storage.claim_shield(mongo, **args)
        await storage.release_shield(mongo, first)
        retry = await storage.claim_shield(mongo, **args)
        assert retry and retry != first
        await storage.complete_shield(mongo, first, 888)
        assert (
            mongo.recruit_challenges.documents["goblin_prompt:777"]["status"]
            == "sending"
        )
        await storage.complete_shield(mongo, retry, 889)
        assert (
            mongo.recruit_challenges.documents["goblin_prompt:777"]["prompt_message_id"]
            == 889
        )

    asyncio.run(run())


def test_shield_abandoned_claim_is_recoverable_after_restart():
    async def run():
        mongo = db()
        args = dict(message_id=777, channel_id=44, user_id=22, guild_id=1)
        await storage.claim_shield(mongo, **args)
        mongo.recruit_challenges.documents["goblin_prompt:777"][
            "processing_until"
        ] = storage.utcnow() - timedelta(seconds=1)
        assert await storage.claim_shield(mongo, **args)

    asyncio.run(run())


def test_repeated_shield_handler_does_not_reset_or_resend(monkeypatch):
    from extensions.commands.recruit import questions

    async def run():
        mongo = db()
        rest = NS(
            fetch_member=AsyncMock(return_value=NS(id=22, mention="<@22>")),
            create_message=AsyncMock(return_value=NS(id=888)),
            edit_message=AsyncMock(),
        )
        context = NS(
            user=NS(id=22),
            member=NS(id=33),
            guild_id=1,
            channel_id=44,
            interaction=NS(message=NS(id=777, components=[])),
            respond=AsyncMock(),
        )
        # An uneditable source deliberately leaves the visible button behind.
        await questions.on_shield_basics_button(
            "22:33", bot=NS(rest=rest), mongo=mongo, ctx=context
        )
        session = mongo.recruit_challenges.documents[storage.key(44, 22)]["session_id"]
        for _ in range(3):
            await questions.on_shield_basics_button(
                "22:33", bot=NS(rest=rest), mongo=mongo, ctx=context
            )
        assert rest.create_message.await_count == 1
        assert (
            mongo.recruit_challenges.documents[storage.key(44, 22)]["session_id"]
            == session
        )
        # A deliberately new Discord Basics message starts a fresh challenge.
        context.interaction.message.id = 779
        await questions.on_shield_basics_button(
            "22:33", bot=NS(rest=rest), mongo=mongo, ctx=context
        )
        assert rest.create_message.await_count == 2
        assert (
            mongo.recruit_challenges.documents[storage.key(44, 22)]["session_id"]
            != session
        )

    asyncio.run(run())


def test_shield_handler_send_failure_allows_another_click():
    from extensions.commands.recruit import questions

    async def run():
        mongo = db()
        rest = NS(
            fetch_member=AsyncMock(return_value=NS(id=22, mention="<@22>")),
            create_message=AsyncMock(side_effect=RuntimeError("failed")),
            edit_message=AsyncMock(),
        )
        context = NS(
            user=NS(id=22),
            member=NS(id=33),
            guild_id=1,
            channel_id=44,
            interaction=NS(message=NS(id=777, components=[])),
            respond=AsyncMock(),
        )
        with pytest.raises(RuntimeError):
            await questions.on_shield_basics_button(
                "22:33", bot=NS(rest=rest), mongo=mongo, ctx=context
            )
        assert (
            mongo.recruit_challenges.documents["goblin_prompt:777"]["status"] == "ready"
        )
        rest.edit_message.assert_not_awaited()
        rest.create_message.side_effect = None
        rest.create_message.return_value = NS(id=888)
        await questions.on_shield_basics_button(
            "22:33", bot=NS(rest=rest), mongo=mongo, ctx=context
        )
        assert (
            mongo.recruit_challenges.documents["goblin_prompt:777"]["status"] == "sent"
        )

    asyncio.run(run())
