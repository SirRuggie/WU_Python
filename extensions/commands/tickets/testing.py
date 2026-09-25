"""Private operator panel for isolated thread-ticket exercises.

The panel is deliberately a thin interaction surface.  It never writes ticket
records itself: the control module selects the test database and the regular
thread-ticket creation path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
    ModalActionRowBuilder as ModalActionRow,
    SelectMenuBuilder as SelectMenu,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from extensions.commands.tickets import perms, ticket
from extensions.commands.tickets import testing_service
from utils.component_state import get_state, insert_state
from utils.constants import GOLDENROD_ACCENT, RED_ACCENT
from utils.manage_ui import button_emoji
from utils.mongo import MongoClient
from utils import ticket_testing_control as control


PANEL_TTL = timedelta(minutes=30)
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_CLEANUP_MINUTES = 60
MIN_WINDOW_MINUTES = 1
MAX_WINDOW_MINUTES = 1440


def _id(action: str, state_id: str) -> str:
    return f"ticket_testing_{action}:{state_id}"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _when(value: Any) -> str:
    if not isinstance(value, datetime):
        return "not scheduled"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"<t:{int(value.timestamp())}:R>"


def _values(ctx: Any) -> tuple[int, ...]:
    return tuple(sorted({_int(value) for value in (getattr(ctx.interaction, "values", ()) or ()) if _int(value) > 0}))


def _modal_value(ctx: Any, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()) or ():
        for item in row:
            if getattr(item, "custom_id", None) == custom_id:
                return str(getattr(item, "value", "") or "")
    return ""


def _button(
    style: hikari.ButtonStyle, custom_id: str, label: str, *,
    disabled: bool = False, icon: str | None = None,
) -> Button:
    return Button(
        style=style, custom_id=custom_id, label=label, is_disabled=disabled,
        emoji=button_emoji(icon or label),
    )


def _panel(state_id: str, window: dict | None, *, admin: bool, notice: str | None = None) -> list[Container]:
    # active_window returns None for expired, cleared, or closed windows.
    active = window is not None
    expires = _when(window.get("expires_at")) if window else "not open"
    status = "Open" if active else "Closed"
    body: list[Any] = [
        Text(content="## Ticket testing"),
        Text(content=(
            "This opens isolated test tickets only. Test threads are cleaned up after "
            "the configured window. Use the normal questions and staff controls; "
            "approval and denial are simulated."
        )),
        Separator(divider=True),
        Text(content=f"**Test window:** {status} · expires {expires}"),
    ]
    if active:
        body.append(Text(content=f"**Automatic cleanup:** {_when(window.get('cleanup_at'))}"))
    if notice:
        body.extend([Separator(divider=True), Text(content=notice)])

    open_row = ActionRow(components=[
        _button(hikari.ButtonStyle.PRIMARY, _id("open_main", state_id), "Open Main test ticket", disabled=not active, icon="Open"),
        _button(hikari.ButtonStyle.PRIMARY, _id("open_fwa", state_id), "Open FWA test ticket", disabled=not active, icon="Open"),
    ])
    body.append(open_row)

    if admin:
        body.extend([
            Separator(divider=True),
            Text(content="### Administrator controls"),
            Text(content=(
                "Opening a window adds you automatically. Selected testers can use "
                "`/tickets testing` and try both applicant and staff actions.\n"
                f"**Members:** {', '.join(f'<@{uid}>' for uid in (window or {}).get('allowed_user_ids', [])) or 'None'}\n"
                f"**Roles:** {', '.join(f'<@&{rid}>' for rid in (window or {}).get('allowed_role_ids', [])) or 'None'}\n"
                f"**Include administrators:** {'Yes' if (window or {}).get('allow_admins') else 'No'}\n"
                "Each dropdown replaces its current access list."
            )),
            ActionRow(components=[
                _button(hikari.ButtonStyle.SUCCESS, _id("open_window", state_id), "Open test window", disabled=active, icon="Settings"),
                _button(hikari.ButtonStyle.SECONDARY, _id("add_self", state_id), "Add myself", disabled=not active, icon="Edit"),
                _button(hikari.ButtonStyle.SECONDARY, _id("toggle_admins", state_id), "Toggle include admins", disabled=not active, icon="Edit"),
            ]),
            ActionRow(components=[SelectMenu(
                type=hikari.ComponentType.USER_SELECT_MENU,
                custom_id=_id("users", state_id), placeholder="Allow selected members",
                min_values=0, max_values=25, is_disabled=not active,
            )]),
            ActionRow(components=[SelectMenu(
                type=hikari.ComponentType.ROLE_SELECT_MENU,
                custom_id=_id("roles", state_id), placeholder="Allow selected roles",
                min_values=0, max_values=25, is_disabled=not active,
            )]),
            ActionRow(components=[
                _button(hikari.ButtonStyle.DANGER, _id("close_window", state_id), "Close test window", disabled=not active, icon="No"),
                _button(hikari.ButtonStyle.DANGER, _id("clear", state_id), "Clear test tickets", icon="No"),
            ]),
        ])
    return [Container(accent_color=GOLDENROD_ACCENT, components=body)]


async def _new_state(mongo: MongoClient, ctx: Any, *, admin: bool) -> str:
    state_id = uuid.uuid4().hex
    await insert_state(testing_service.test_mongo(mongo), {
        "_id": state_id, "type": "ticket_testing_panel",
        "owner_id": int(ctx.user.id), "guild_id": _int(getattr(ctx, "guild_id", 0)),
        "admin": bool(admin),
    }, ttl=PANEL_TTL)
    return state_id


async def _access(ctx: Any, mongo: MongoClient, state_id: str) -> tuple[dict | None, dict | None, bool, str | None]:
    state = await get_state(testing_service.test_mongo(mongo), state_id)
    if not state or state.get("type") != "ticket_testing_panel":
        return None, None, False, "This testing panel has expired. Run `/tickets testing` again."
    if _int(state.get("owner_id")) != _int(ctx.user.id):
        return state, None, False, "This private panel belongs to another member."
    if _int(state.get("guild_id")) != _int(getattr(ctx, "guild_id", 0)):
        return state, None, False, "This panel can only be used in its original server."
    admin = await perms.is_target_admin(getattr(ctx, "member", None), mongo)
    scoped = testing_service.test_mongo(mongo)
    window = await testing_service.active_window(scoped)
    if window and _int(window.get("guild_id")) != _int(getattr(ctx, "guild_id", 0)):
        return state, None, False, "This test window belongs to another server."
    if admin:
        return state, window, True, None
    role_ids = tuple(getattr(getattr(ctx, "member", None), "role_ids", ()) or ())
    if not window or not testing_service.user_allowed(
        window, _int(ctx.user.id), role_ids, is_admin=False,
    ):
        return state, window, False, "You are not allowed to use the current test window."
    return state, window, False, None


async def _refresh(ctx: Any, mongo: MongoClient, state_id: str, notice: str | None = None):
    state, window, admin, problem = await _access(ctx, mongo, state_id)
    if problem:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem)])]
    return _panel(state_id, window, admin=admin, notice=notice)


@ticket.register()
class Testing(lightbulb.SlashCommand, name="testing", description="Open the isolated ticket testing panel"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        admin = await perms.is_target_admin(getattr(ctx, "member", None), mongo)
        scoped = testing_service.test_mongo(mongo)
        window = await testing_service.active_window(scoped)
        if not admin:
            role_ids = tuple(getattr(getattr(ctx, "member", None), "role_ids", ()) or ())
            if (
                not window
                or _int(window.get("guild_id")) != _int(getattr(ctx, "guild_id", 0))
                or not testing_service.user_allowed(window, _int(ctx.user.id), role_ids, is_admin=False)
            ):
                await ctx.respond("You are not allowed to use the current ticket test window.", ephemeral=True)
                return
        state_id = await _new_state(mongo, ctx, admin=admin)
        await ctx.respond(components=_panel(state_id, window, admin=admin), ephemeral=True)


@register_action("ticket_testing_open_window", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_window(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    _state, _window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        await ctx.respond(problem or "Administrator permission is required.", ephemeral=True)
        return
    await ctx.respond_with_modal(title="Open ticket test window", custom_id=_id("open_window_submit", action_id), components=[
        ModalActionRow().add_text_input("duration", "Window duration (minutes)", value=str(DEFAULT_WINDOW_MINUTES), min_length=1, max_length=4),
        ModalActionRow().add_text_input("cleanup", "Cleanup after window ends (minutes)", value=str(DEFAULT_CLEANUP_MINUTES), min_length=1, max_length=5),
    ])


async def _modal_panel(ctx: Any, components: list[Container]) -> None:
    await ctx.interaction.edit_initial_response(components=components)


@register_action("ticket_testing_open_window_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_window_submit(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any) -> None:
    # Parent creation can make REST calls. Acknowledge the modal before doing
    # them so Discord does not time out the administrator's submission.
    await ctx.defer(ephemeral=True)
    _state, _window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        await _modal_panel(ctx, [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])])
        return
    duration, cleanup = _int(_modal_value(ctx, "duration")), _int(_modal_value(ctx, "cleanup"))
    if not MIN_WINDOW_MINUTES <= duration <= MAX_WINDOW_MINUTES or not 0 <= cleanup <= 10080:
        await _modal_panel(ctx, await _refresh(ctx, mongo, action_id, "Use 1–1440 minutes for the window and 0–10080 minutes for cleanup after it ends."))
        return
    try:
        await control.start_window(bot, mongo, ctx, duration_minutes=duration, cleanup_minutes=cleanup)
    except ValueError as exc:
        await _modal_panel(ctx, await _refresh(ctx, mongo, action_id, str(exc)))
        return
    await _modal_panel(ctx, await _refresh(ctx, mongo, action_id, "Test window opened."))


async def _admin_update(ctx: Any, action_id: str, mongo: MongoClient, bot: hikari.GatewayBot, **kwargs: Any):
    _state, window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])]
    if not window:
        return await _refresh(ctx, mongo, action_id, "Open a test window first.")
    try:
        await control.update_access(bot, mongo, ctx, **kwargs)
    except ValueError as exc:
        return await _refresh(ctx, mongo, action_id, str(exc))
    return await _refresh(ctx, mongo, action_id, "Test window access updated.")


@register_action("ticket_testing_add_self", preload_state=False)
@lightbulb.di.with_di
async def add_self(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any):
    return await _admin_update(ctx, action_id, mongo, bot, add_self=True)


@register_action("ticket_testing_users", preload_state=False)
@lightbulb.di.with_di
async def users(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any):
    return await _admin_update(ctx, action_id, mongo, bot, user_ids=_values(ctx))


@register_action("ticket_testing_roles", preload_state=False)
@lightbulb.di.with_di
async def roles(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any):
    return await _admin_update(ctx, action_id, mongo, bot, role_ids=_values(ctx))


@register_action("ticket_testing_toggle_admins", preload_state=False)
@lightbulb.di.with_di
async def toggle_admins(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any):
    _state, window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])]
    if not window:
        return await _refresh(ctx, mongo, action_id, "Open a test window first.")
    return await _admin_update(ctx, action_id, mongo, bot, allow_admins=not bool(window.get("allow_admins")))


@register_action("ticket_testing_close_window", preload_state=False)
@lightbulb.di.with_di
async def close_window(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any):
    _state, _window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])]
    try:
        await control.end_window(bot, mongo, ctx)
    except ValueError as exc:
        return await _refresh(ctx, mongo, action_id, str(exc))
    return await _refresh(ctx, mongo, action_id, "Test window closed.")


@register_action("ticket_testing_clear", preload_state=False)
@lightbulb.di.with_di
async def clear(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    _state, window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])]
    return [Container(accent_color=RED_ACCENT, components=[
        Text(content="## Clear isolated test tickets?"),
        Text(content="This ends the test window and deletes its test threads and ticket records. Production tickets are never touched."),
        ActionRow(components=[
            _button(hikari.ButtonStyle.DANGER, _id("clear_confirm", action_id), "Confirm clear test tickets"),
            _button(hikari.ButtonStyle.SECONDARY, _id("back", action_id), "Back"),
        ]),
    ])]


@register_action("ticket_testing_clear_confirm", preload_state=False)
@lightbulb.di.with_di
async def clear_confirm(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    _state, _window, admin, problem = await _access(ctx, mongo, action_id)
    if problem or not admin:
        return [Container(accent_color=RED_ACCENT, components=[Text(content=problem or "Administrator permission is required.")])]
    await testing_service.request_clear(testing_service.test_mongo(mongo))
    return await _refresh(ctx, mongo, action_id, "Test-ticket cleanup requested.")


@register_action("ticket_testing_back", preload_state=False)
@lightbulb.di.with_di
async def back(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    return await _refresh(ctx, mongo, action_id)


async def _open_ticket(ctx: Any, action_id: str, mongo: MongoClient, bot: hikari.GatewayBot, ticket_type: str) -> None:
    _state, window, _admin, problem = await _access(ctx, mongo, action_id)
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    if not window:
        await ctx.respond("The test window is closed.", ephemeral=True)
        return
    try:
        # The control path owns the interaction acknowledgement and response so
        # ticket creation retains the same parent and permission checks as prod.
        await control.open_test_ticket(ctx, bot, mongo, ticket_type)
    except ValueError as exc:
        await ctx.respond(str(exc), ephemeral=True)


@register_action("ticket_testing_open_main", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_main(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any) -> None:
    await _open_ticket(ctx, action_id, mongo, bot, "main")


@register_action("ticket_testing_open_fwa", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_fwa(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any) -> None:
    await _open_ticket(ctx, action_id, mongo, bot, "fwa")
