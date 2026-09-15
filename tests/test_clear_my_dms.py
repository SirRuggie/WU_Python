"""Focused production-path checks for the self-service DM clear command."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import clear_my_dms, todo
from utils import todo_sessions


class _Rest:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.deleted = []

    def fetch_messages(self, _channel_id, *, before):
        self.before = before

        async def pages():
            for message in self.messages:
                yield message

        return pages()

    async def delete_message(self, channel_id, message_id):
        self.deleted.append((channel_id, message_id))


def _message(message_id, author_id):
    return SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id))


def test_purge_streams_only_bot_messages_through_fixed_confirmation_cutoff(monkeypatch):
    rest = _Rest([
        _message(501, 100),  # visible confirmation
        _message(500, 100),
        _message(499, 200),  # requester message
        _message(498, 100),
    ])
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=100))

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(clear_my_dms.asyncio, "sleep", no_wait)
    deleted = asyncio.run(clear_my_dms._delete_through_cutoff(
        bot, channel_id=77, cutoff_id=501
    ))

    assert deleted == 3
    assert rest.before == 502
    assert [message_id for _channel, message_id in rest.deleted] == [501, 500, 498]


def test_purge_spaces_only_eligible_delete_requests(monkeypatch):
    rest = _Rest([
        _message(503, 100),
        _message(502, 200),  # preserved requester message must not add a delay
        _message(501, 100),
        _message(500, 100),
    ])
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=100))
    sleeps = []

    async def paced_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(clear_my_dms, "_monotonic", lambda: 100.0)
    monkeypatch.setattr(clear_my_dms.asyncio, "sleep", paced_sleep)
    assert asyncio.run(clear_my_dms._delete_through_cutoff(
        bot, channel_id=77, cutoff_id=503
    )) == 3

    # First delete starts immediately; each further bot-authored delete waits.
    assert sleeps == pytest.approx([
        clear_my_dms.DELETE_INTERVAL_SECONDS,
        clear_my_dms.DELETE_INTERVAL_SECONDS,
    ])


def test_confirmation_makes_scope_and_todo_effect_explicit():
    text = "\n".join(
        component.content
        for component in clear_my_dms._confirmation("token")[0].components
        if hasattr(component, "content")
    )
    assert "all messages authored by WUBOT" in text
    assert "oldest" in text
    assert "Your messages are preserved" in text
    assert "automatic `/todo` panel will be stopped first" in text
    assert "Future reminders" in text
    assert "temporary completion receipt" in text


def test_requester_dm_rejects_group_or_wrong_recipient():
    async def verify(channel):
        ctx = SimpleNamespace(
            guild_id=None,
            interaction=SimpleNamespace(channel_id=44),
        )
        bot = SimpleNamespace(rest=SimpleNamespace(
            fetch_channel=lambda _id: _await(channel)
        ))
        return await clear_my_dms._requester_dm(
            ctx, bot, user_id=9, channel_id=44
        )

    async def _run():
        good = SimpleNamespace(type=hikari.ChannelType.DM, recipient=SimpleNamespace(id=9))
        wrong = SimpleNamespace(type=hikari.ChannelType.DM, recipient=SimpleNamespace(id=10))
        assert await verify(good)
        assert not await verify(wrong)

    asyncio.run(_run())


async def _await(value):
    return value


def test_todo_clear_lock_removes_sessions_and_blocks_pre_clear_activation(monkeypatch):
    panels = [{"_id": "dm:9:44", "message_id": 333}]
    removed = []

    async def active(_mongo, **_kwargs):
        return True, panels

    async def discard(_mongo, document_id):
        removed.append(document_id)
        return True

    monkeypatch.setattr(todo_sessions, "active_panels", active)
    monkeypatch.setattr(todo_sessions, "discard", discard)
    todo._dm_history_clear_cutoffs.clear()

    async def purge():
        return "purged"

    stopped, result = asyncio.run(todo.clear_dm_history_through(
        SimpleNamespace(), user_id=9, channel_id=44, cutoff_id=400, purge=purge
    ))

    assert stopped is True
    assert result == "purged"
    assert removed == ["dm:9:44"]
    assert todo._dm_history_clear_cutoffs[todo_sessions.session_id(9, 44)] == 400


def test_claim_uses_single_pending_owner_channel_cutoff_predicate():
    calls = []

    class Collection:
        async def find_one_and_update(self, query, update):
            calls.append((query, update))
            return {"cutoff_id": 123}

    result = asyncio.run(clear_my_dms._claim(
        SimpleNamespace(component_state=Collection()),
        action_id="state", user_id=9, channel_id=44,
    ))

    assert result == {"cutoff_id": 123}
    query, update = calls[0]
    assert query["status"] == "pending"
    assert query["user_id"] == 9
    assert query["channel_id"] == 44
    assert query["cutoff_id"] == {"$gt": 0}
    assert query["expires_at"]["$gt"].tzinfo is timezone.utc
    assert update["$set"]["status"] == "running"
