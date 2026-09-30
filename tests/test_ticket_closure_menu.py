import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from extensions.commands.tickets import console, lifecycle


@pytest.mark.parametrize("choice", ["approve", "deny", "close"])
def test_menu_routes_to_confirmation_or_reason_modal(monkeypatch, choice):
    async def run():
        ctx = NS(
            interaction=NS(values=[choice]),
            defer=AsyncMock(),
            respond_with_modal=AsyncMock(),
        )
        approve = AsyncMock()
        deny = AsyncMock()
        monkeypatch.setattr(console, "ticket_hub_approve", approve)
        monkeypatch.setattr(console, "ticket_hub_deny", deny)
        await console.ticket_hub_closure(ctx, "ticket_1", mongo=NS())
        if choice == "approve":
            ctx.defer.assert_awaited_once_with(edit=True)
            approve.assert_awaited_once()
            deny.assert_not_awaited()
        elif choice == "deny":
            ctx.defer.assert_not_awaited()
            deny.assert_awaited_once()
        else:
            ctx.defer.assert_not_awaited()
            assert (
                ctx.respond_with_modal.call_args.kwargs["custom_id"]
                == "ticket_v2_hub_close_submit:ticket_1"
            )

    asyncio.run(run())


@pytest.mark.parametrize("authorized", [True, False])
def test_close_submit_checks_shared_ticket_and_responds_privately(
    monkeypatch, authorized
):
    async def run():
        ctx = NS(
            defer=AsyncMock(),
            interaction=NS(edit_initial_response=AsyncMock()),
            member=NS(),
            user=NS(id=12, username="Recruiter"),
            guild_id=3,
        )
        doc = {"_id": "ticket_1", "rev": 8} if authorized else None
        monkeypatch.setattr(console, "_shared_ticket", AsyncMock(return_value=doc))
        monkeypatch.setattr(console, "_modal_value", lambda *args: "Recruit withdrew")
        change = AsyncMock(return_value=NS())
        monkeypatch.setattr(lifecycle, "change", change)
        monkeypatch.setattr(
            console, "_transition_result_panel", AsyncMock(return_value=[])
        )
        await console.ticket_hub_close_submit(ctx, "ticket_1", mongo=NS(), bot=NS())
        ctx.defer.assert_awaited_once_with(ephemeral=True)
        if authorized:
            assert change.call_args.kwargs["kind"] == "close"
            assert change.call_args.kwargs["expected_rev"] == 8
            assert change.call_args.kwargs["reason"] == "Recruit withdrew"
        else:
            change.assert_not_awaited()
        assert (
            ctx.interaction.edit_initial_response.call_args.kwargs["user_mentions"]
            is False
        )

    asyncio.run(run())
