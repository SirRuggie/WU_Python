# extensions/commands/fwa/lazy_cwl.py
"""Redirect aliases for the retired /fwa lazycwl-* commands. See
extensions/commands/lazycwl_dashboard.py.

The 9 old command names stay registered so muscle memory and old pins
keep working, but each invoke does the same admin check as the dashboard and
opens the new /lazycwl home instead of the retired implementation.
"""

import hikari
import lightbulb

from extensions.commands.fwa import loader, fwa
from utils.mongo import MongoClient

MOVED_NOTICE = "ℹ️ This moved to `/lazycwl`. Use it from now on."

# Resolve the dashboard lazily to avoid a circular import through the FWA package.
is_admin = None
open_dashboard = None


async def _redirect(ctx: lightbulb.Context, mongo: MongoClient) -> None:
    _is_admin = is_admin
    if _is_admin is None:
        from extensions.commands.lazycwl_dashboard import is_admin as _is_admin
    if not _is_admin(ctx.member):
        await ctx.respond("Only server admins can use this.", ephemeral=True)
        return

    _open_dashboard = open_dashboard
    if _open_dashboard is None:
        from extensions.commands.lazycwl_dashboard import open_dashboard as _open_dashboard
    await _open_dashboard(ctx, mongo, note=MOVED_NOTICE)


@fwa.register()
class LazyCwlSnapshot(
    lightbulb.SlashCommand,
    name="lazycwl-snapshot",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlPing(
    lightbulb.SlashCommand,
    name="lazycwl-ping",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlStatus(
    lightbulb.SlashCommand,
    name="lazycwl-status",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlRoster(
    lightbulb.SlashCommand,
    name="lazycwl-roster",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlReset(
    lightbulb.SlashCommand,
    name="lazycwl-reset",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlAutopingsStart(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-start",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlAutopingsStop(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-stop",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlAutopingsStatus(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-status",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


@fwa.register()
class LazyCwlRemovePlayer(
    lightbulb.SlashCommand,
    name="lazycwl-remove-player",
    description="Moved to /lazycwl",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _redirect(ctx, mongo)


loader.command(fwa)
