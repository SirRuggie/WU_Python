"""Private entry point for Warriors United management workspaces."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
import uuid

import hikari
import lightbulb

from extensions.components import register_action
from utils.component_state import get_state, insert_state
from utils.constants import GOLD_ACCENT
from utils.mongo import MongoClient


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
FWA_REP_ROLE_ID = 993015846442127420
DESTINATIONS = (
    ("Recruit Gauntlet", "recruit", "Onboarding messages, rules, and artwork"),
    ("FWA", "fwa", "Base links, images, and Town Hall guidance"),
    ("FWA War Messages", "fwa_war_messages", "Win, lose, mismatch, and blacklist announcements"),
    ("CWL", "cwl", "Announcements, schedules, and delivery"),
    ("CWL Rosters", "cwl_rosters", "Saved rosters and return reminders"),
)
SECTION_CHOICES = (
    lightbulb.Choice("Server", "server"),
    lightbulb.Choice("Recruit Gauntlet", "recruit-gauntlet"),
    lightbulb.Choice("FWA", "fwa"),
    lightbulb.Choice("FWA War Messages", "fwa-war-messages"),
    lightbulb.Choice("CWL", "cwl"),
    lightbulb.Choice("CWL Rosters", "cwl-rosters"),
)
SECTION_DESTINATION = {
    "recruit-gauntlet": "recruit",
    "fwa": "fwa",
    "fwa-war-messages": "fwa_war_messages",
    "cwl": "cwl",
    "cwl-rosters": "cwl_rosters",
}


def _user_id(ctx: Any) -> int | None:
    user = getattr(ctx, "user", None)
    return int(user.id) if user is not None else None


def _guild_id(ctx: Any) -> int | None:
    guild = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return int(guild) if guild is not None else None


def _member(ctx: Any) -> Any:
    return getattr(getattr(ctx, "interaction", None), "member", None) or getattr(ctx, "member", None)


def _allowed(ctx: Any, destination: str) -> bool:
    member = _member(ctx)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    admin = bool(permissions & hikari.Permissions.ADMINISTRATOR)
    if destination == "recruit":
        return admin or bool(permissions & hikari.Permissions.MANAGE_GUILD)
    if destination == "fwa_war_messages":
        roles = member.get_roles() if member and hasattr(member, "get_roles") else ()
        role_ids = {int(role.id) for role in roles} | {int(role) for role in getattr(member, "role_ids", ())}
        return 769130325460254740 in role_ids
    if destination == "fwa":
        roles = member.get_roles() if member and hasattr(member, "get_roles") else ()
        return any(int(role.id) == FWA_REP_ROLE_ID for role in roles)
    if destination in {"cwl", "cwl_rosters"}:
        return admin
    raise ValueError(f"Unknown management destination: {destination}")


async def _new_state(ctx: Any, mongo: MongoClient) -> dict:
    guild_id, user_id = _guild_id(ctx), _user_id(ctx)
    if guild_id is None or user_id is None:
        raise ValueError("Open `/manage` inside a server.")
    state = {"_id": uuid.uuid4().hex, "user_id": user_id, "guild_id": guild_id, "view": "home"}
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _state(ctx: Any, mongo: MongoClient, token: str) -> tuple[dict | None, str | None]:
    state = await get_state(mongo, token)
    if not state:
        return None, "This management panel expired. Run `/manage` again."
    if state.get("view") != "home" or state.get("guild_id") != _guild_id(ctx) or state.get("user_id") != _user_id(ctx):
        return None, "Open your own `/manage` panel in this server."
    return state, None


def error(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=0xAA4444,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## Server Management\n{message}")],
    )]


def destinations(ctx: Any) -> list[tuple[str, str, str]]:
    return [entry for entry in DESTINATIONS if _allowed(ctx, entry[1])]


def _destination_section(label: str, key: str, description: str, token: str, allowed: bool) -> hikari.impl.SectionComponentBuilder:
    action = f"manage_{key}:{token}"
    requirements = {
        "recruit": "Manage Server permission",
        "fwa": "FWA Representative role",
        "fwa_war_messages": "FWA Clan Rep role",
        "cwl": "Administrator permission",
        "cwl_rosters": "Administrator permission",
    }
    button = hikari.impl.InteractiveButtonBuilder(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id=action,
        label="Open" if allowed else "Locked",
        is_disabled=not allowed,
    )
    detail = description if allowed else f"{description} · Requires {requirements[key]}"
    return hikari.impl.SectionComponentBuilder(
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"### {label}\n{detail}")],
        accessory=button,
    )


async def manage_home_components(ctx: Any, mongo: MongoClient, *, token: str | None = None,
                                 notice: str | None = None) -> list:
    if token is None:
        token = (await _new_state(ctx, mongo))["_id"]
    children: list = [
        hikari.impl.TextDisplayComponentBuilder(content="## Server Management"),
        hikari.impl.TextDisplayComponentBuilder(content="Choose a workspace to manage Warriors United content and operations."),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
    ]
    if notice:
        children.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    for index, (label, key, description) in enumerate(DESTINATIONS):
        if index:
            children.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
        children.append(_destination_section(label, key, description, token, _allowed(ctx, key)))
    children += [
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        hikari.impl.TextDisplayComponentBuilder(content="-# Private to you · expires after 30 minutes"),
    ]
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=children)]


async def _open(ctx: Any, mongo: MongoClient, destination: str, token: str, *,
                deferred: bool) -> None:
    if destination == "recruit":
        from extensions.commands import content
        await content.open_dashboard(
            ctx, mongo, bot=getattr(ctx.interaction, "app", None),
            manage_token=token, deferred=deferred,
        )
    elif destination == "fwa":
        from extensions.commands.clan.dashboard import fwa_data
        if not deferred:
            await ctx.defer(ephemeral=True)
        await ctx.interaction.edit_initial_response(
            components=await fwa_data.build_fwa_management_screen(ctx, mongo, manage_token=token),
            **NO_MENTIONS,
        )
    elif destination == "fwa_war_messages":
        from extensions.commands import fwa_war_messages
        await fwa_war_messages.open_dashboard(ctx, mongo, manage_token=token, deferred=deferred)
    elif destination == "cwl":
        from extensions.commands import cwl_dashboard
        if not deferred:
            await ctx.defer(ephemeral=True)
        await cwl_dashboard.open_dashboard(ctx, mongo, manage_token=token)
    elif destination == "cwl_rosters":
        from extensions.commands import lazycwl_dashboard
        await lazycwl_dashboard.open_dashboard(ctx, mongo, manage_token=token, deferred=deferred)
    else:
        raise ValueError(f"Unknown management destination: {destination}")


class Manage(lightbulb.SlashCommand, name="manage", description="Open Warriors United management tools"):
    section = lightbulb.string("section", "Optional management workspace", default=None, choices=SECTION_CHOICES)
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: Any, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        if self.section not in {None, "server", *SECTION_DESTINATION}:
            await ctx.respond("Choose one of the available management sections.", ephemeral=True)
            return
        destination = SECTION_DESTINATION.get(self.section)
        if destination and not _allowed(ctx, destination):
            await ctx.respond("You do not have access to that workspace.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        try:
            state = await _new_state(ctx, mongo)
        except ValueError as exc:
            await ctx.interaction.edit_initial_response(content=str(exc))
            return
        token = state["_id"]
        if destination is None:
            components = await manage_home_components(ctx, mongo, token=token)
            await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)
        else:
            await _open(ctx, mongo, destination, token, deferred=True)


@register_action("manage_home", preload_state=False)
@lightbulb.di.with_di
async def home(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    return error(problem) if problem else await manage_home_components(ctx, mongo, token=action_id)


async def _destination_action(ctx: Any, action_id: str, mongo: MongoClient, destination: str) -> None:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        await ctx.interaction.edit_initial_response(components=error(problem), **NO_MENTIONS)
        return
    if not _allowed(ctx, destination):
        await ctx.interaction.edit_initial_response(
            components=error("Your access to this workspace changed. Run `/manage` to see the sections available to you."),
            **NO_MENTIONS,
        )
        return
    await _open(ctx, mongo, destination, action_id, deferred=True)


def _register_destination(name: str, destination: str):
    @register_action(name, preload_state=False, no_return=True)
    @lightbulb.di.with_di
    async def handler(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
        await _destination_action(ctx, action_id, mongo, destination)
    return handler


recruit_destination = _register_destination("manage_recruit", "recruit")
fwa_destination = _register_destination("manage_fwa", "fwa")
fwa_war_messages_destination = _register_destination("manage_fwa_war_messages", "fwa_war_messages")
cwl_destination = _register_destination("manage_cwl", "cwl")
cwl_rosters_destination = _register_destination("manage_cwl_rosters", "cwl_rosters")

loader.command(Manage)
