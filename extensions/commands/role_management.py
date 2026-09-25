"""Private role changes and member lists for the /manage Roles section."""
from __future__ import annotations

from datetime import timedelta
import logging
import math
import uuid
from typing import Any

import hikari
import lightbulb

from extensions.commands.recruit import perms
from extensions.commands.recruit.dashboard.manage_roles import role_is_manageable
from extensions.components import register_action
from utils.component_state import get_state, insert_state
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
from utils.manage_ui import breadcrumb, button_emoji


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
PAGE_SIZE = 20
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
_log = logging.getLogger(__name__)


def _ids(ctx: Any) -> tuple[int | None, int | None]:
    user_id = getattr(getattr(ctx, "user", None), "id", None)
    guild_id = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return (int(user_id) if user_id is not None else None,
            int(guild_id) if guild_id is not None else None)


def _member(ctx: Any) -> Any:
    return getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)


def _guild(ctx: Any, guild_id: int) -> Any:
    bot = getattr(ctx.interaction, "app", None)
    cache = getattr(bot, "cache", None)
    return cache.get_guild(guild_id) if cache is not None else None


def _error(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=GOLDENROD_ACCENT,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## Roles\n{message}")],
    )]


async def _state(ctx: Any, mongo: MongoClient, sid: str) -> tuple[dict | None, str | None]:
    state = await get_state(mongo, sid)
    user_id, guild_id = _ids(ctx)
    if (state is None or user_id is None or guild_id is None
            or state.get("user_id") != user_id or state.get("guild_id") != guild_id):
        return None, "Open your own `/manage` Roles panel in this server."
    guild = _guild(ctx, guild_id)
    if guild is None:
        return None, "Server roles are unavailable. Reopen `/manage` and try again."
    if not await perms.is_recruiter(_member(ctx), mongo, guild):
        return None, "Recruiter access is required."
    return state, None


async def _new(mongo: MongoClient, **fields: Any) -> dict:
    state = {**fields, "_id": uuid.uuid4().hex}
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _next(mongo: MongoClient, state: dict, **changes: Any) -> dict:
    return await _new(mongo, **{**state, **changes})


def _buttons(*items: tuple[str, str, hikari.ButtonStyle, bool]) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, style, disabled in items:
        row.add_interactive_button(style, custom_id, label=label, emoji=button_emoji(label), is_disabled=disabled)
    return row


def _panel(state: dict, notice: str | None = None) -> list:
    sid = state["_id"]
    selected = len(state.get("role_ids", ()))
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Roles") + "\n## Roles"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            "Choose one member and up to 25 roles. Add or Remove applies only to those roles."
        )),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"Member: {state.get('target_label', 'not selected')} · "
            f"Roles: {', '.join(state.get('role_labels', [])) or 'not selected'}"
        )),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    rows.extend([
        hikari.impl.MessageActionRowBuilder(components=[hikari.impl.SelectMenuBuilder(
            type=hikari.ComponentType.USER_SELECT_MENU, custom_id=f"roles_member:{sid}", placeholder="Choose a member",
            min_values=1, max_values=1,
        )]),
        hikari.impl.MessageActionRowBuilder(components=[hikari.impl.SelectMenuBuilder(
            type=hikari.ComponentType.ROLE_SELECT_MENU, custom_id=f"roles_role:{sid}", placeholder="Choose up to 25 roles",
            min_values=1, max_values=25,
        )]),
        _buttons(
            (f"roles_change:{sid}|add", "Add selected", hikari.ButtonStyle.SUCCESS,
             not bool(state.get("target_id") and selected)),
            (f"roles_change:{sid}|remove", "Remove selected", hikari.ButtonStyle.DANGER,
             not bool(state.get("target_id") and selected)),
        ),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        hikari.impl.TextDisplayComponentBuilder(content="### Role members\nChoose any server role to see its exact member count and browse names."),
        hikari.impl.MessageActionRowBuilder(components=[hikari.impl.SelectMenuBuilder(
            type=hikari.ComponentType.ROLE_SELECT_MENU, custom_id=f"roles_browse_role:{sid}", placeholder="Choose a role to browse",
            min_values=1, max_values=1,
        )]),
        _buttons((f"manage_home:{state['manage_token']}", "Management Home",
                  hikari.ButtonStyle.SECONDARY, False)),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


async def open_dashboard(ctx: Any, mongo: MongoClient, *, manage_token: str,
                         deferred: bool = False) -> None:
    if not deferred:
        await ctx.defer(ephemeral=True)
    user_id, guild_id = _ids(ctx)
    guild = _guild(ctx, guild_id) if guild_id is not None else None
    if (user_id is None or guild is None
            or not await perms.is_recruiter(_member(ctx), mongo, guild)):
        await ctx.interaction.edit_initial_response(
            components=_error("Recruiter access is required in this server."), **NO_MENTIONS,
        )
        return
    state = await _new(mongo, user_id=user_id, guild_id=guild_id,
                       manage_token=manage_token)
    await ctx.interaction.edit_initial_response(components=_panel(state), **NO_MENTIONS)


def _selected_ids(ctx: Any, *, maximum: int) -> tuple[int, ...] | None:
    values = getattr(ctx.interaction, "values", ())
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= maximum:
        return None
    try:
        numbers = tuple(int(value) for value in values)
    except (TypeError, ValueError):
        return None
    if any(number <= 0 for number in numbers) or len(set(numbers)) != len(numbers):
        return None
    return numbers


@register_action("roles_member", preload_state=False)
@lightbulb.di.with_di
async def member(ctx: Any, action_id: str,
                 mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    selected = _selected_ids(ctx, maximum=1)
    if selected is None:
        return _panel(state, "Choose one member.")
    guild = _guild(ctx, state["guild_id"])
    try:
        target = await ctx.interaction.app.rest.fetch_member(guild.id, selected[0])
    except (hikari.NotFoundError, hikari.ForbiddenError, hikari.HTTPError):
        return _panel(state, "That member could not be found in this server.")
    if not perms.actor_can_manage_member(_member(ctx), target, guild):
        return _panel(state, "You can only manage members below your highest role; the server owner is excluded.")
    label = _safe_label(getattr(target, "display_name", None) or getattr(target, "username", None) or str(target.id))
    return _panel(await _next(mongo, state, target_id=selected[0],
                              target_label=f"{label} ({selected[0]})"),
                  "Member selected. Now choose roles.")


@register_action("roles_role", preload_state=False)
@lightbulb.di.with_di
async def role(ctx: Any, action_id: str,
               mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    selected = _selected_ids(ctx, maximum=25)
    if selected is None:
        return _panel(state, "Choose between 1 and 25 distinct roles.")
    guild = _guild(ctx, state["guild_id"])
    bot = ctx.interaction.app
    actor = _member(ctx)
    rejected = [role_id for role_id in selected if not (
        (candidate := guild.get_role(role_id)) is not None
        and role_is_manageable(guild, bot, candidate)
        and perms.actor_can_manage_role(actor, guild, candidate)
    )]
    if rejected:
        return _panel(state, "One or more selected roles are outside your or the bot's permissions or role hierarchy.")
    labels = [_safe_label(guild.get_role(role_id).name, 40) for role_id in selected]
    return _panel(await _next(mongo, state, role_ids=list(selected), role_labels=labels),
                  f"{len(selected)} role(s) selected. Choose Add or Remove.")


def _safe_label(value: str, limit: int = 75) -> str:
    return str(value).replace("@", "＠").replace("`", "ˋ").replace("<", "‹").replace(">", "›").replace("\n", " ")[:limit]


@register_action("roles_change", preload_state=False)
@lightbulb.di.with_di
async def change(ctx: Any, action_id: str,
                 mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, separator, operation = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid)
    if problem:
        return _error(problem)
    if separator != "|" or operation not in {"add", "remove"}:
        return _panel(state, "Choose Add or Remove from this panel.")
    target_id = state.get("target_id")
    role_ids = state.get("role_ids")
    if (not isinstance(target_id, int) or not isinstance(role_ids, list)
            or not 1 <= len(role_ids) <= 25 or len(set(role_ids)) != len(role_ids)):
        return _panel(state, "Choose one member and up to 25 roles first.")
    guild = _guild(ctx, state["guild_id"])
    bot = ctx.interaction.app
    actor = _member(ctx)
    try:
        target = await bot.rest.fetch_member(guild.id, target_id)
    except (hikari.NotFoundError, hikari.ForbiddenError, hikari.HTTPError):
        return _panel(state, "Member could not be fetched. No roles were changed.")
    if not perms.actor_can_manage_member(actor, target, guild):
        return _panel(state, "You can only manage members below your highest role; the server owner is excluded.")
    changed, skipped, refused, failed = [], [], [], []
    current = set(target.role_ids)
    for role_id in role_ids:
        candidate = guild.get_role(role_id)
        label = _safe_label(candidate.name) if candidate is not None else f"Unknown role {role_id}"
        if (candidate is None or not role_is_manageable(guild, bot, candidate)
                or not perms.actor_can_manage_role(actor, guild, candidate)):
            refused.append(label)
            continue
        already = role_id in current
        if (operation == "add" and already) or (operation == "remove" and not already):
            skipped.append(label)
            continue
        try:
            if operation == "add":
                await bot.rest.add_role_to_member(guild.id, target_id, role_id,
                                                  reason=f"Added by {ctx.user.id} via /manage Roles")
                current.add(role_id)
            else:
                await bot.rest.remove_role_from_member(guild.id, target_id, role_id,
                                                       reason=f"Removed by {ctx.user.id} via /manage Roles")
                current.discard(role_id)
            changed.append(label)
        except (hikari.ForbiddenError, hikari.NotFoundError, hikari.HTTPError):
            _log.warning("Role change failed: operation=%s guild=%s target=%s role=%s",
                         operation, guild.id, target_id, role_id, exc_info=True)
            failed.append(label)
    verb = "Added" if operation == "add" else "Removed"
    details = [f"{verb}: {', '.join(changed) or 'none'}"]
    if skipped:
        details.append(f"Already correct: {', '.join(skipped)}")
    if refused:
        details.append(f"Not permitted: {', '.join(refused)}")
    if failed:
        details.append(f"Discord rejected: {', '.join(failed)}")
    notice = " · ".join(details)
    return _panel(state, notice[:1800])


@register_action("roles_browse_role", preload_state=False)
@lightbulb.di.with_di
async def browse_role(ctx: Any, action_id: str,
                      mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    selected = _selected_ids(ctx, maximum=1)
    if selected is None:
        return _panel(state, "Choose one role to browse.")
    guild = _guild(ctx, state["guild_id"])
    chosen = guild.get_role(selected[0])
    if chosen is None:
        return _panel(state, "That role no longer exists.")
    return await _fetch_browse(ctx, mongo, state, chosen)


def _browse_panel(state: dict, page: int, notice: str | None = None) -> list:
    sid = state["_id"]
    entries = state["browse_entries"]
    pages = max(1, math.ceil(len(entries) / PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    current = entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    humans = sum(not entry[2] for entry in entries)
    bots = len(entries) - humans
    names = "\n".join(
        f"{page * PAGE_SIZE + index + 1}. {_safe_label(name, 55)} (`{member_id}`){' · bot' if is_bot else ''}"
        for index, (member_id, name, is_bot) in enumerate(current)
    ) or "No members currently have this role."
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Roles", "Members") + f"\n## Role members · {state['browse_role_name']}"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**{len(entries)} total** · {humans} people · {bots} bots · Page {page + 1}/{pages}"
        )),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        hikari.impl.TextDisplayComponentBuilder(content=names),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    rows.extend([
        _buttons(
            (f"roles_page:{sid}|{page - 1}", "Previous", hikari.ButtonStyle.SECONDARY, page == 0),
            (f"roles_page:{sid}|{page + 1}", "Next", hikari.ButtonStyle.SECONDARY, page >= pages - 1),
            (f"roles_refresh:{sid}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
        ),
        _buttons(
            (f"roles_back:{sid}", "Back to Roles", hikari.ButtonStyle.SECONDARY, False),
            (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


@register_action("roles_page", preload_state=False)
@lightbulb.di.with_di
async def page(ctx: Any, action_id: str,
               mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, separator, raw_page = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid)
    if problem:
        return _error(problem)
    if state.get("view") != "browse" or separator != "|":
        return _panel(state, "Choose a role to browse first.")
    try:
        page_number = int(raw_page)
    except ValueError:
        return _browse_panel(state, 0)
    return _browse_panel(state, page_number)


@register_action("roles_refresh", preload_state=False)
@lightbulb.di.with_di
async def refresh(ctx: Any, action_id: str,
                  mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    if state.get("view") != "browse":
        return _panel(state, "Choose a role to browse first.")
    guild = _guild(ctx, state["guild_id"])
    role = guild.get_role(state["browse_role_id"])
    if role is None:
        return _panel(state, "This role no longer exists.")
    # Refresh from Discord, rather than treating the previous count as live.
    return await _fetch_browse(ctx, mongo, state, role)


async def _fetch_browse(ctx: Any, mongo: MongoClient, state: dict, role: Any) -> list:
    entries = []
    try:
        async for member_item in ctx.interaction.app.rest.fetch_members(state["guild_id"]):
            if role.id == state["guild_id"] or role.id in member_item.role_ids:
                name = getattr(member_item, "display_name", None) or getattr(member_item, "username", None) or str(member_item.id)
                user = getattr(member_item, "user", None)
                entries.append((int(member_item.id), _safe_label(name),
                                bool(getattr(member_item, "is_bot", getattr(user, "is_bot", False)))))
    except (hikari.ForbiddenError, hikari.HTTPError):
        return (_browse_panel(state, 0, "Refresh failed; showing the previous snapshot.")
                if state.get("browse_entries") is not None
                else _panel(state, "Discord could not list members. Try again."))
    entries.sort(key=lambda entry: (entry[1].casefold(), entry[0]))
    fresh = await _next(mongo, state, view="browse", browse_role_id=role.id,
                        browse_role_name=_safe_label(role.name), browse_entries=entries)
    return _browse_panel(fresh, 0)


@register_action("roles_back", preload_state=False)
@lightbulb.di.with_di
async def back(ctx: Any, action_id: str,
               mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    if state.get("view") != "browse":
        return _panel(state)
    next_state = await _next(mongo, state, view="panel", browse_entries=None,
                             browse_role_id=None, browse_role_name=None)
    return _panel(next_state)
