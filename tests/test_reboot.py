import asyncio
import inspect
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import reboot


EXPECTED_REBOOT_OWNER_IDS = (
    505227988229554179,
    644005027052126208,
)


class _Context:
    def __init__(self, user_id: int):
        self.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
        self.responses = []

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


class _BotConfig:
    def __init__(self):
        self.updates = []

    async def update_one(self, *args, **kwargs):
        self.updates.append((args, kwargs))


class _Bot:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def test_reboot_owner_allowlist_is_explicit_and_complete():
    assert reboot.REBOOT_OWNER_IDS == frozenset(EXPECTED_REBOOT_OWNER_IDS)


@pytest.mark.parametrize("user_id", EXPECTED_REBOOT_OWNER_IDS)
def test_each_reboot_owner_can_open_confirmation(monkeypatch, user_id):
    stored = []

    async def insert_state(_mongo, document):
        stored.append(document)

    monkeypatch.setattr(reboot, "insert_state", insert_state)
    ctx = _Context(user_id)

    asyncio.run(reboot.Reboot.invoke._func(
        SimpleNamespace(),
        ctx,
        bot=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert stored and stored[0]["user_id"] == user_id
    assert len(ctx.responses) == 1
    assert ctx.responses[0][1]["flags"] == hikari.MessageFlag.EPHEMERAL


def test_non_owner_cannot_open_reboot_confirmation(monkeypatch):
    async def insert_state(*_args, **_kwargs):
        raise AssertionError("a non-owner must not create reboot state")

    monkeypatch.setattr(reboot, "insert_state", insert_state)
    ctx = _Context(123)

    asyncio.run(reboot.Reboot.invoke._func(
        SimpleNamespace(),
        ctx,
        bot=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert len(ctx.responses) == 1
    assert ctx.responses[0][1]["flags"] == hikari.MessageFlag.EPHEMERAL


@pytest.mark.parametrize("user_id", EXPECTED_REBOOT_OWNER_IDS)
def test_each_reboot_owner_passes_confirmation_recheck(monkeypatch, user_id):
    deleted = []
    exits = []

    async def get_state(_mongo, action_id):
        assert action_id == "action-id"
        return {"user_id": user_id}

    async def delete_state(_mongo, action_id):
        deleted.append(action_id)

    monkeypatch.setattr(reboot, "get_state", get_state)
    monkeypatch.setattr(reboot, "delete_state", delete_state)
    monkeypatch.setattr(reboot.os, "_exit", exits.append)

    ctx = _Context(user_id)
    bot = _Bot()
    bot_config = _BotConfig()
    mongo = SimpleNamespace(bot_config=bot_config)
    handler = inspect.unwrap(reboot.handle_reboot_confirm)

    asyncio.run(handler(
        ctx,
        "action-id",
        bot=bot,
        mongo=mongo,
    ))

    assert bot.closed is True
    assert deleted == ["action-id"]
    assert exits == [0]
    assert bot_config.updates[0][0][1]["$set"]["user_id"] == user_id
