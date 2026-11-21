"""Stale shared decisions cannot write; current decisions are private detail actions."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from extensions.commands.tickets import console, lifecycle


def test_old_shared_choices_only_use_guarded_console_refresh(monkeypatch):
    refresh=AsyncMock()
    monkeypatch.setattr(console,"ticket_hub_page",refresh)
    asyncio.run(console.ticket_hub_legacy_refresh(NS(),"ticket_1",mongo=NS(),bot=NS()))
    assert refresh.await_args.args[1]=="refresh"


def test_old_shared_modal_cannot_close_or_deny(monkeypatch):
    change=AsyncMock();deny=AsyncMock()
    monkeypatch.setattr(lifecycle,"change",change)
    monkeypatch.setattr(console.resolve,"deny_ticket",deny)
    ctx=NS(defer=AsyncMock(),interaction=NS(edit_initial_response=AsyncMock()))
    asyncio.run(console.ticket_hub_legacy_submit(ctx,"ticket_1"))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    change.assert_not_awaited();deny.assert_not_awaited()
    assert ctx.interaction.edit_initial_response.await_args.kwargs["user_mentions"] is False
