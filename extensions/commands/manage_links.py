"""Discreet administrator-only tools for shared Discord/Clash account links."""

import logging

import hikari
import lightbulb

from utils import clashperk_link_writes, link_management

loader = lightbulb.Loader()
group = lightbulb.Group(
    "manage-links", "Manage linked Clash accounts",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    contexts=[hikari.ApplicationContextType.GUILD],
    integration_types=[hikari.ApplicationIntegrationType.GUILD_INSTALL],
)
_log = logging.getLogger(__name__)


async def execute(ctx: lightbulb.Context, source: hikari.User, selection: str,
                  destination: hikari.User | None = None) -> None:
    # Enforce at execution too: server command overrides cannot grant non-admins access.
    member = ctx.interaction.member
    if (ctx.guild_id is None or member is None
            or not member.permissions & hikari.Permissions.ADMINISTRATOR):
        await ctx.respond("Only server administrators can manage account links.", ephemeral=True)
        return
    if source.is_bot or (destination is not None and destination.is_bot):
        await ctx.respond("Select human Discord users for account links.", ephemeral=True)
        return
    if destination is not None and source.id == destination.id:
        await ctx.respond("Select a different destination user.", ephemeral=True)
        return
    await ctx.defer(ephemeral=True)
    try:
        result = await link_management.manage_links(
            int(source.id), selection, int(destination.id) if destination else None,
        )
    except link_management.LinkError as exc:
        await ctx.respond(str(exc), ephemeral=True)
        return
    verb = "Transferred" if destination else "Unlinked"
    summary = f"{verb} **{len(result.completed)} of {len(result.selected)}** selected accounts from <@{source.id}>"
    if destination:
        summary += f" to <@{destination.id}>"
    summary += "."
    if result.problem:
        summary += f"\n{result.problem}\nRemaining accounts were not processed."
    if destination:
        summary += "\nNew links were made. They are not verified. The old verification and the private link settings were not kept."
    # Keep a complete per-tag receipt, even for lists too large for a Discord message.
    completed = set(result.completed)
    report = "\n".join(
        f"{tag}: {'completed' if tag in completed else 'not completed; see summary'}"
        for tag in result.selected
    )
    _log.info("Link management actor=%s guild=%s source=%s destination=%s completed=%s problem=%s",
              ctx.user.id, ctx.guild_id, source.id, destination.id if destination else None,
              result.completed, result.problem)
    # Link inventories are cached briefly; invalidate affected users now.
    from extensions.commands.linked_accounts import forget
    forget(int(source.id), int(destination.id) if destination else None)
    await ctx.respond(
        summary, attachment=hikari.Bytes(report.encode(), "link-results.txt"),
        ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False,
    )


@group.register()
class Unlink(lightbulb.SlashCommand, name="unlink", description="Unlink one or all accounts from a Discord user"):
    user = lightbulb.user("user", "Discord user whose accounts should be unlinked")
    player = lightbulb.string("player", "A player tag, or all to unlink every account", max_length=20)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await execute(ctx, self.user, self.player)


@group.register()
class Transfer(lightbulb.SlashCommand, name="transfer", description="Unlink and relink accounts to another user as unverified"):
    user = lightbulb.user("user", "Current Discord owner")
    new_user = lightbulb.user("new-user", "New Discord owner")
    player = lightbulb.string("player", "A player tag, or all to transfer every account", max_length=20)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await execute(ctx, self.user, self.player, self.new_user)


async def link_clashperk(ctx: lightbulb.Context, user: hikari.User, player: str) -> None:
    member = ctx.interaction.member
    if (ctx.guild_id is None or member is None
            or not member.permissions & hikari.Permissions.ADMINISTRATOR):
        await ctx.respond("Only server administrators can manage account links.", ephemeral=True)
        return
    if user.is_bot:
        await ctx.respond("Select a human Discord user.", ephemeral=True)
        return
    await ctx.defer(ephemeral=True)
    result = await clashperk_link_writes.create_link(int(user.id), player)
    _log.info("ClashPerk link actor=%s guild=%s user=%s tag=%s status=%s",
              ctx.user.id, ctx.guild_id, user.id, result.tag, result.status)
    if result.wrote:
        from extensions.commands.linked_accounts import forget
        forget(int(user.id))
    text = f"`{result.tag}` → <@{user.id}>\n{result.message}"
    if result.verified is not None:
        text += "\nVerified in ClashPerk." if result.verified else "\nNot verified in ClashPerk."
    await ctx.respond(text, ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)


@group.register()
class Link(lightbulb.SlashCommand, name="link", description="Link a Clash account to a Discord user in ClashPerk"):
    user = lightbulb.user("user", "Discord user who owns the account")
    player = lightbulb.string("player", "Player tag", max_length=20)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await link_clashperk(ctx, self.user, self.player)


loader.command(group)
