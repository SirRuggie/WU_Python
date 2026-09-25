import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import gauntlet_help
from extensions.components import registered_functions


def run(coro):
    return asyncio.run(coro)


def _built(components):
    return components[0].build()[0]["components"]


def _text(components):
    return " ".join(item["content"] for item in _built(components) if "content" in item)


def _buttons(components):
    return [
        component
        for row in _built(components)
        for component in row.get("components", [])
        if component["type"] == hikari.ComponentType.BUTTON
    ]


def _ctx(*, user_id=1, guild_id=gauntlet_help.GUILD_ID, permissions=hikari.Permissions.ADMINISTRATOR,
         value=None):
    fields = () if value is None else ((SimpleNamespace(custom_id="reminder_minutes", value=value),),)
    interaction = SimpleNamespace(
        guild_id=guild_id, member=SimpleNamespace(permissions=permissions), components=fields,
        message=None, edit_initial_response=AsyncMock(), create_initial_response=AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id), interaction=interaction, defer=AsyncMock(),
        respond=AsyncMock(), respond_with_modal=AsyncMock(),
    )


def test_panel_explains_fixed_channel_and_reminder_lifecycle():
    state = {"_id": "draft", "manage_token": "home"}
    components = gauntlet_help.panel(state, {"reminder_minutes": 30, "enabled": True})
    text = _text(components)
    assert f"<#{gauntlet_help.HELP_CHANNEL_ID}>" in text
    assert "30 minutes" in text
    assert "deletes after 10 minutes" in text
    assert "next Gauntlet step resets" in text
    assert "application ticket" in text
    assert "30 minutes of quiet" in text
    buttons = _buttons(components)
    assert {button["custom_id"] for button in buttons} == {
        "gauntlet_help_edit:draft", "content_back_root:draft", "manage_home:home",
    }
    assert all(button.get("emoji") for button in buttons)


def test_actions_are_stateless_and_modal_contracts_are_declared():
    assert registered_functions["gauntlet_help"].preload_state is False
    for name in ("gauntlet_help_edit", "gauntlet_help_save"):
        action = registered_functions[name]
        assert action.preload_state is False and action.no_return
    assert registered_functions["gauntlet_help_edit"].opens_modal
    assert registered_functions["gauntlet_help_save"].is_modal


def test_edit_modal_prefills_current_delay(monkeypatch):
    state = {"_id": "draft", "guild_id": gauntlet_help.GUILD_ID, "manage_token": "home"}
    monkeypatch.setattr(gauntlet_help, "_content_state", AsyncMock(return_value=(state, None)))
    monkeypatch.setattr(gauntlet_help, "_settings", AsyncMock(return_value={"reminder_minutes": 60, "enabled": True}))
    ctx = _ctx()
    run(gauntlet_help.edit_delay(ctx, "draft", mongo=object()))
    payload = ctx.respond_with_modal.await_args.kwargs
    assert payload["custom_id"] == "gauntlet_help_save:draft"
    assert payload["components"][0].build()[0]["components"][0]["value"] == "60"


def test_save_rejects_noncanonical_or_out_of_range_values(monkeypatch):
    state = {"_id": "draft", "guild_id": gauntlet_help.GUILD_ID, "manage_token": "home"}
    monkeypatch.setattr(gauntlet_help, "_content_state", AsyncMock(return_value=(state, None)))
    monkeypatch.setattr(gauntlet_help, "_settings", AsyncMock(return_value={"reminder_minutes": 30, "enabled": True}))
    ctx = _ctx(value="01")
    run(gauntlet_help.save_delay(ctx, "draft", mongo=object()))
    rendered = ctx.interaction.edit_initial_response.await_args.kwargs["components"]
    assert "whole number from 1 to 10,080" in _text(rendered)


def test_save_persists_valid_delay_and_confirms(monkeypatch):
    state = {"_id": "draft", "guild_id": gauntlet_help.GUILD_ID, "manage_token": "home"}
    saved = AsyncMock()
    monkeypatch.setattr(gauntlet_help, "_content_state", AsyncMock(return_value=(state, None)))
    monkeypatch.setattr(gauntlet_help, "_settings", AsyncMock(return_value={"reminder_minutes": 45, "enabled": True}))
    import utils.gauntlet_help as service
    monkeypatch.setattr(service, "save_settings", saved)
    ctx = _ctx(user_id=99, value="45")
    run(gauntlet_help.save_delay(ctx, "draft", mongo="mongo"))
    saved.assert_awaited_once_with("mongo", gauntlet_help.GUILD_ID, 45, 99)
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    rendered = ctx.interaction.edit_initial_response.await_args.kwargs["components"]
    assert "Reminder delay saved: 45 minutes." in _text(rendered)
