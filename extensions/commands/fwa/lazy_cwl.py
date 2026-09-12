# extensions/commands/fwa/lazy_cwl.py
"""Redirect aliases for the retired /fwa lazycwl-* commands. See
extensions/commands/lazycwl_dashboard.py.

D018: the 9 old command names stay registered so muscle memory and old pins
keep working, but each invoke does the same admin check as the dashboard and
opens the new /lazycwl home instead of the retired implementation.
"""

import hikari
import lightbulb

from extensions.commands.fwa import loader, fwa
from utils.mongo import MongoClient

MOVED_NOTICE = "ℹ️ This moved to `/lazycwl`. Use it from now on."

# Not imported at module load: extensions/commands/lazycwl_dashboard.py imports
# extensions/commands/fwa/lazy_cwl_service.py, which triggers this package's
# __init__.py (`from . import lazy_cwl`) before it finishes. A module-level
# import here completed the cycle (refuter-14 MUST-FIX 1). Left as plain
# module attributes (not resolved eagerly) so tests can still monkeypatch
# `lazy_cwl.build_home` the same way they always could. `is_admin` gets the
# same lazy treatment for the same reason (builder-16, D021: shares the
# dashboard's admin-check predicate instead of a second copy).
build_home = None
is_admin = None


async def _redirect(ctx: lightbulb.Context, mongo: MongoClient) -> None:
    _is_admin = is_admin
    if _is_admin is None:
        from extensions.commands.lazycwl_dashboard import is_admin as _is_admin
    if not _is_admin(ctx.member):
        await ctx.respond("Only server admins can use this.", ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    _build_home = build_home
    if _build_home is None:
        from extensions.commands.lazycwl_dashboard import build_home as _build_home
    components = await _build_home(mongo, selected_tag=None, note=MOVED_NOTICE)
    await ctx.interaction.edit_initial_response(components=components)


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
