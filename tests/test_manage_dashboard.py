import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions import components
from extensions.commands import manage


def run(coro):
    return asyncio.run(coro)


def context(*, guild=2, user=1, permissions=hikari.Permissions.ADMINISTRATOR, roles=(), custom_id=None):
    member = SimpleNamespace(permissions=permissions, get_roles=lambda: [SimpleNamespace(id=role) for role in roles])
    events = []
    interaction = SimpleNamespace(
        guild_id=guild, member=member, custom_id=custom_id,
        edit_initial_response=AsyncMock(side_effect=lambda **kw: events.append(("edit", kw))),
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=user), member=member, interaction=interaction,
        defer=AsyncMock(side_effect=lambda **kw: events.append(("defer", kw))),
        respond=AsyncMock(side_effect=lambda *args, **kw: events.append(("respond", args, kw))),
        events=events,
    )
    return ctx


def walk(node):
    if isinstance(node, list):
        for item in node:
            yield from walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("components", "accessory"):
            if key in node:
                yield from walk(node[key])


def test_single_manage_command_has_optional_section_and_is_loaded():
    command_names = {
        loadable._command._command_data.name
        for loadable in manage.loader._loadables
        if hasattr(loadable, "_command")
    }
    assert command_names == {"manage"}
    assert manage.Manage._command_data.name == "manage"
    assert set(manage.Manage._command_data.options) == {"section"}
    choices = manage.Manage._command_data.options['section'].choices
    assert [(choice.name, choice.value) for choice in choices] == [
        ("Server", "server"), ("Recruit Gauntlet", "recruit-gauntlet"),
        ("Recruitment Questions", "recruitment-questions"),
        ("FWA", "fwa"), ("FWA War Messages", "fwa-war-messages"),
        ("CWL", "cwl"), ("CWL Rosters", "cwl-rosters"),
    ]


def test_home_has_six_sections_valid_discord_shape_and_access(monkeypatch):
    token = "x" * 32
    ctx = context(permissions=hikari.Permissions.MANAGE_GUILD)
    built = run(manage.manage_home_components(ctx, object(), token=token))[0].build()[0]
    nodes = list(walk(built))
    buttons = [node for node in nodes if node.get("type") == hikari.ComponentType.BUTTON]
    sections = [node for node in nodes if node.get("type") == hikari.ComponentType.SECTION]
    assert built["type"] == hikari.ComponentType.CONTAINER
    assert built["accent_color"] == manage.GOLD_ACCENT
    assert len(nodes) <= 40
    assert len(sections) == 6
    assert [button["custom_id"] for button in buttons] == [
        f"manage_recruit:{token}", f"manage_recruitment_questions:{token}", f"manage_fwa:{token}", f"manage_fwa_war_messages:{token}",
        f"manage_cwl:{token}", f"manage_cwl_rosters:{token}",
    ]
    assert [button["disabled"] for button in buttons] == [False, False, True, True, True, True]
    assert all(len(button["custom_id"]) <= 100 for button in buttons)


def test_fwa_role_opens_only_fwa_without_server_manage_permission():
    ctx = context(permissions=hikari.Permissions.NONE, roles=(manage.FWA_REP_ROLE_ID,))
    assert [key for _, key, _ in manage.destinations(ctx)] == ["fwa"]


def test_state_rejects_expired_other_owner_and_other_guild(monkeypatch):
    ctx = context()
    for row, expected in [
        (None, "expired"), ({"view": "home", "guild_id": 2, "user_id": 9}, "own"),
        ({"view": "home", "guild_id": 9, "user_id": 1}, "own"),
    ]:
        monkeypatch.setattr(manage, "get_state", AsyncMock(return_value=row))
        state, problem = run(manage._state(ctx, object(), "token"))
        assert state is None and expected in problem
    assert manage.get_state.await_count == 1


def test_command_defers_before_storage_and_opens_requested_section(monkeypatch):
    ctx = context()
    order = []
    async def create(_ctx, _mongo):
        order.append("state")
        return {"_id": "token"}
    async def open_target(_ctx, _mongo, destination, token, *, deferred):
        order.append(("open", destination, token, deferred))
    async def defer(**kw):
        order.append("defer")
    ctx.defer = AsyncMock(side_effect=defer)
    monkeypatch.setattr(manage, "_new_state", create)
    monkeypatch.setattr(manage, "_open", open_target)
    command = manage.Manage()
    command.section = "cwl"
    run(command.invoke(ctx, mongo=object()))
    assert order == ["defer", "state", ("open", "cwl", "token", True)]
    assert ctx.defer.await_count == 1


def test_dispatch_routes_owner_bound_destination_after_one_defer(monkeypatch):
    from extensions.components import registered_functions
    ctx = context(custom_id="manage_cwl:token")
    source = registered_functions["manage_cwl"]
    monkeypatch.setitem(registered_functions, "manage_cwl", replace(source, fn=source.fn.__wrapped__._func))
    monkeypatch.setattr(manage, "get_state", AsyncMock(return_value={"view": "home", "guild_id": 2, "user_id": 1}))
    opened = AsyncMock()
    monkeypatch.setattr(manage, "_open", opened)
    run(components._dispatch(ctx, mongo=object()))
    assert ctx.events[0] == ("defer", {"edit": True})
    opened.assert_awaited_once()
    assert opened.await_args.args[2:] == ("cwl", "token")
    assert opened.await_args.kwargs["deferred"] is True
    assert ctx.defer.await_count == 1


def test_revoked_destination_edits_deferred_panel_without_opening(monkeypatch):
    from extensions.components import registered_functions
    ctx = context(custom_id="manage_cwl:token", permissions=hikari.Permissions.NONE)
    source = registered_functions["manage_cwl"]
    monkeypatch.setitem(registered_functions, "manage_cwl", replace(source, fn=source.fn.__wrapped__._func))
    monkeypatch.setattr(manage, "get_state", AsyncMock(return_value={"view": "home", "guild_id": 2, "user_id": 1}))
    opened = AsyncMock()
    monkeypatch.setattr(manage, "_open", opened)
    run(components._dispatch(ctx, mongo=object()))
    assert ctx.events[0] == ("defer", {"edit": True})
    assert ctx.events[-1][0] == "edit"
    assert "access" in str(ctx.events[-1][1]["components"]).lower()
    opened.assert_not_awaited()
    ctx.respond.assert_not_awaited()


def _button_ids(panel):
    return [
        node["custom_id"] for node in walk([item.build()[0] for item in panel])
        if node.get("type") == hikari.ComponentType.BUTTON and "custom_id" in node
    ]


def test_fwa_managed_overview_detail_and_image_back_preserve_home(monkeypatch):
    from extensions.commands.clan.dashboard import fwa_data
    monkeypatch.setattr(fwa_data, "get_fwa_data", AsyncMock(return_value={}))
    ctx = context(roles=(manage.FWA_REP_ROLE_ID,))
    overview = run(fwa_data.build_fwa_management_screen(ctx, object(), manage_token="home-token"))
    assert "manage_home:home-token" in _button_ids(overview)
    menu = [node for node in walk([item.build()[0] for item in overview])
            if node.get("type") == hikari.ComponentType.ACTION_ROW and node.get("components")
            and node["components"][0].get("type") == hikari.ComponentType.TEXT_SELECT_MENU][0]
    assert menu["components"][0]["custom_id"] == "fwa_th_select:home-token"

    detail = fwa_data.build_th_edit_components("th16", "", "", "", "", "", manage_token="home-token")
    assert {"manage_home:home-token", "fwa_back_to_main:home-token"} <= set(_button_ids(detail))
    ctx.interaction.message = SimpleNamespace(components=detail)
    images = run(fwa_data.fwa_update_images.__wrapped__._func(ctx=ctx, action_id="th16"))
    assert {"manage_home:home-token", "fwa_th_select_return:th16|home-token"} <= set(_button_ids(images))


def test_bare_manage_defers_once_and_edits_home(monkeypatch):
    ctx = context()
    order = []
    async def create(_ctx, _mongo):
        order.append("state")
        return {"_id": "home-token"}
    async def home_panel(_ctx, _mongo, *, token):
        order.append(("home", token))
        return ["HOME"]
    async def defer(**kw):
        order.append("defer")
    ctx.defer = AsyncMock(side_effect=defer)
    monkeypatch.setattr(manage, "_new_state", create)
    monkeypatch.setattr(manage, "manage_home_components", home_panel)
    command = manage.Manage()
    command.section = None
    run(command.invoke(ctx, mongo=object()))
    assert order == ["defer", "state", ("home", "home-token")]
    assert ctx.defer.await_count == 1
    ctx.interaction.edit_initial_response.assert_awaited_once()
    assert ctx.interaction.edit_initial_response.await_args.kwargs["components"] == ["HOME"]


def test_open_shortcuts_forward_deferred_context(monkeypatch):
    from extensions.commands import content, lazycwl_dashboard
    ctx = context()
    app = object()
    ctx.interaction.app = app
    content_open = AsyncMock()
    roster_open = AsyncMock()
    monkeypatch.setattr(content, "open_dashboard", content_open)
    monkeypatch.setattr(lazycwl_dashboard, "open_dashboard", roster_open)
    run(manage._open(ctx, object(), "recruit", "token", deferred=True))
    assert content_open.await_args.kwargs == {
        "bot": app, "manage_token": "token", "deferred": True,
    }
    run(manage._open(ctx, object(), "cwl_rosters", "token", deferred=True))
    assert roster_open.await_args.kwargs == {"manage_token": "token", "deferred": True}
    ctx.defer.assert_not_awaited()


def test_managed_content_back_and_home_warn_before_unsaved_edits_are_left(monkeypatch):
    from extensions.commands import content
    state = {
        "_id": "draft", "user_id": 1, "guild_id": 2,
        "view": "document", "document": "about-us", "manage_token": "home-token",
    }
    ctx = context(permissions=hikari.Permissions.MANAGE_GUILD)
    monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
    new_draft = AsyncMock()
    monkeypatch.setattr(content, "new_draft", new_draft)
    home_prompt = run(content.manage_review.__wrapped__._func(ctx=ctx, action_id="draft", mongo=object()))
    back_prompt = run(content.back_to_root.__wrapped__._func(ctx=ctx, action_id="draft", mongo=object()))
    assert "manage_home:home-token" in _button_ids(home_prompt)
    assert "content_back_root_confirm:draft" in _button_ids(back_prompt)
    for prompt in (home_prompt, back_prompt):
        assert "Unsaved edits" in str(prompt[0].build()[0])
        assert "Keep editing" in str(prompt[0].build()[0])
    new_draft.assert_not_awaited()


def test_every_management_home_button_has_registered_action():
    panel = run(manage.manage_home_components(context(), object(), token="token"))
    button_actions = {
        custom_id.partition(":")[0]
        for custom_id in (
            node["custom_id"] for node in walk([item.build()[0] for item in panel])
            if node.get("type") == hikari.ComponentType.BUTTON
        )
    }
    assert button_actions <= components.registered_functions.keys()


def test_fwa_war_messages_home_button_routes_through_dispatcher(monkeypatch):
    ctx = context(
        permissions=hikari.Permissions.NONE,
        roles=(769130325460254740,),
        custom_id="manage_fwa_war_messages:token",
    )
    source = components.registered_functions["manage_fwa_war_messages"]
    monkeypatch.setitem(
        components.registered_functions, "manage_fwa_war_messages",
        replace(source, fn=source.fn.__wrapped__._func),
    )
    monkeypatch.setattr(manage, "get_state", AsyncMock(return_value={
        "view": "home", "guild_id": 2, "user_id": 1,
    }))
    from extensions.commands import fwa_war_messages
    stored = AsyncMock()
    monkeypatch.setattr(fwa_war_messages, "insert_state", stored)
    run(components._dispatch(ctx, mongo=object()))
    assert ctx.events[0] == ("defer", {"edit": True})
    assert ctx.defer.await_count == 1
    stored.assert_awaited_once()
    saved = stored.await_args.args[1]
    assert saved["manage_token"] == "token"
    assert saved["user_id"] == 1 and saved["guild_id"] == 2
    assert ctx.events[-1][0] == "edit"
    rendered = ctx.events[-1][1]["components"][0].build()[0]
    assert rendered["components"][0]["content"] == "## FWA War Messages"


def test_old_dashboard_slash_entries_are_absent_but_manage_and_actions_remain():
    from extensions.commands import content, cwl_dashboard, lazycwl_dashboard, clan
    command_names = {
        loadable._command._command_data.name
        for loader in (content.loader, cwl_dashboard.loader)
        for loadable in loader._loadables
        if hasattr(loadable, "_command")
    }
    assert command_names == set()
    assert not content.content.subcommands
    assert not cwl_dashboard.cwl.subcommands
    assert set(clan.clan.subcommands) == {"info", "list"}
    assert manage.Manage._command_data.name == "manage"
    assert {
        "content_document", "content_save", "cwl_tab", "cwl_apply_review",
        "lazycwl_home", "manage_recruit", "manage_cwl", "manage_cwl_rosters",
    } <= components.registered_functions.keys()


def test_recruitment_questions_button_opens_real_editor(monkeypatch):
    from extensions.commands import recruitment_questions
    action = "manage_recruitment_questions"
    ctx = context(custom_id=f"{action}:token", permissions=hikari.Permissions.MANAGE_GUILD)
    source = components.registered_functions[action]
    monkeypatch.setitem(components.registered_functions, action,
                        replace(source, fn=source.fn.__wrapped__._func))
    monkeypatch.setattr(manage, "get_state", AsyncMock(return_value={
        "view": "home", "guild_id": 2, "user_id": 1,
    }))
    stored = AsyncMock()
    monkeypatch.setattr(recruitment_questions, "insert_state", stored)
    run(components._dispatch(ctx, mongo=object()))
    assert ctx.events[0] == ("defer", {"edit": True})
    assert ctx.defer.await_count == 1
    stored.assert_awaited_once()
    assert stored.await_args.args[1]["manage_token"] == "token"
    rendered = ctx.interaction.edit_initial_response.await_args.kwargs["components"][0].build()[0]
    assert rendered["components"][0]["content"] == "## Recruitment Questions"
