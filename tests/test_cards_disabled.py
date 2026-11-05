"""Disabling the card feature must not touch storage or Discord transports."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from extensions.commands import cards
from extensions.tasks import cards_deadlines, cards_sticky
from utils import cards_config


class ForbiddenDependency:
    def __getattr__(self, name):
        raise AssertionError(f"Disabled cards accessed dependency: {name}")


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.delenv("CARDS_GUILD_ID", raising=False)
    # This is the value the command module captures once at process startup.
    monkeypatch.setattr(cards, "CARDS_GUILD_ID", cards_config.cards_guild_id())
    assert cards.CARDS_GUILD_ID is None
    return ForbiddenDependency()


def test_disabled_slash_command_replies_without_loading_or_posting(disabled):
    ctx = SimpleNamespace(respond=AsyncMock(), defer=AsyncMock())
    asyncio.run(cards.Cards.invoke._func(
        SimpleNamespace(), ctx,
        coc_client=disabled, mongo=disabled, bot=disabled,
    ))
    ctx.respond.assert_awaited_once_with(
        "Card trading is turned off.", ephemeral=True,
    )
    ctx.defer.assert_not_awaited()


@pytest.mark.parametrize("name", [
    "cards_account_page", "cards_account_select", "cards_req_close",
    "cards_trade_decline", "cards_trade_cancel", "cards_trade_complete",
])
def test_old_card_controls_return_only_the_disabled_reply(disabled, name):
    view = asyncio.run(getattr(cards, name)(
        SimpleNamespace(), "old-control",
        coc_client=disabled, mongo=disabled, bot=disabled,
    ))
    assert len(view) == 1
    assert len(view[0].components) == 1
    assert view[0].components[0].content == "Card trading is turned off."


def test_disabled_account_lookup_never_reads_inventory(disabled):
    account, inventory, view = asyncio.run(cards._load_target(
        SimpleNamespace(), "#OLD", coc_client=disabled, mongo=disabled,
    ))
    assert account is inventory is None
    assert view[0].components[0].content == "Card trading is turned off."


def test_disabled_startup_does_not_create_indexes_or_reconcile_data(disabled):
    asyncio.run(cards.prepare_card_inventory_storage._func(
        SimpleNamespace(), mongo=disabled,
    ))


def test_disabled_screenshot_listener_does_not_read_or_consume_uploads(
    disabled, monkeypatch,
):
    consume = AsyncMock()
    monkeypatch.setattr(cards, "_handle_card_scan_dm_upload", consume)
    asyncio.run(cards.cards_scan_dm_upload._func(
        SimpleNamespace(), coc_client=disabled, mongo=disabled, bot=disabled,
    ))
    consume.assert_not_awaited()


@pytest.mark.parametrize("task", [cards_sticky, cards_deadlines])
def test_disabled_background_pass_never_reads_writes_posts_edits_or_deletes(
    disabled, monkeypatch, task,
):
    monkeypatch.setattr(task, "bot_instance", disabled)
    monkeypatch.setattr(task, "mongo_client", disabled)
    run = task.refresh_sticky if task is cards_sticky else task.sweep_once
    asyncio.run(run())


@pytest.mark.parametrize("task,slot", [
    (cards_sticky, "sticky_task"), (cards_deadlines, "sweep_task"),
])
def test_disabled_startup_never_creates_a_worker(disabled, monkeypatch, task, slot):
    create = Mock(side_effect=AssertionError("Disabled cards started a task"))
    monkeypatch.setattr(task.asyncio, "create_task", create)
    monkeypatch.setattr(task, slot, None)
    asyncio.run(task.on_bot_started._func(
        SimpleNamespace(), bot=disabled, mongo=disabled,
    ))
    create.assert_not_called()
    assert getattr(task, slot) is None
