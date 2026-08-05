"""Direct staff commands for adding, removing, and bulk-managing roles."""

import logging

import hikari
import lightbulb

from extensions.commands.recruit import perms
from extensions.commands.recruit.dashboard.manage_roles import (
    manage_roles_handler,
    role_is_manageable,
)
from utils.constants import GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)


loader = lightbulb.Loader()
role = lightbulb.Group("role", "Manage server roles for members")
_log = logging.getLogger(__name__)


def _message_components(
        title: str,
        body: str,
        accent_color: hikari.Color,
        footer: str,
) -> list:
    """Build the standard Components V2 response used by direct commands."""
    return [
        Container(
            accent_color=accent_color,
            components=[
                Text(content=f"## {title}"),
                Separator(divider=True),
                Text(content=body),
                Media(items=[MediaItem(media=footer)]),
            ],
        )
    ]


def _error_components(title: str, body: str) -> list:
    return _message_components(title, body, RED_ACCENT, "assets/Red_Footer.png")


async def _command_context(
        ctx: lightbulb.Context,
        target: hikari.User,
        mongo: MongoClient,
        bot: hikari.GatewayBot,
) -> tuple[hikari.Guild | None, hikari.Member | None, list | None]:
    """Authorize the actor and resolve the target guild member."""
    if ctx.guild_id is None or ctx.member is None:
        return None, None, _error_components(
            "❌ Server Only",
            "Role management can only be used inside the Warriors United server.",
        )

    guild = bot.cache.get_guild(ctx.guild_id)
    if guild is None:
        return None, None, _error_components(
            "❌ Server Unavailable",
            "The server is not available in the bot cache. Please try again.",
        )

    if not await perms.is_recruiter(ctx.member, mongo, guild):
        return None, None, _error_components(
            "❌ Recruiter Access Required",
            "Only configured recruiters, the Recruitment Team, and administrators can use `/role`.",
        )

    member = guild.get_member(target.id)
    if member is None:
        try:
            member = await bot.rest.fetch_member(guild.id, target.id)
        except (hikari.NotFoundError, hikari.ForbiddenError):
            member = None

    if member is None:
        return guild, None, _error_components(
            "❌ Member Not Found",
            "That user is not currently a member of this server.",
        )

    if not perms.actor_can_manage_member(ctx.member, member, guild):
        return guild, member, _error_components(
            "❌ Member Cannot Be Managed",
            (
                "You can only change roles for members below your highest role. "
                "Administrators can manage any eligible member."
            ),
        )

    return guild, member, None


async def _change_one_role(
        ctx: lightbulb.Context,
        target: hikari.User,
        selected_role: hikari.Role,
        adding: bool,
        mongo: MongoClient,
        bot: hikari.GatewayBot,
) -> list:
    guild, member, problem = await _command_context(ctx, target, mongo, bot)
    if problem is not None:
        return problem

    if selected_role.guild_id != guild.id:
        return _error_components(
            "❌ Wrong Server Role",
            "The selected role does not belong to this server.",
        )

    if not role_is_manageable(guild, bot, selected_role):
        return _error_components(
            "❌ Role Cannot Be Managed",
            (
                f"{selected_role.mention} is managed by an integration or is at or above "
                "the bot's highest role. Move the bot role higher before trying again."
            ),
        )

    if not perms.actor_can_manage_role(ctx.member, guild, selected_role):
        return _error_components(
            "❌ Role Not Permitted",
            (
                f"You cannot manage {selected_role.mention}. Recruiters can only change "
                "roles below their highest role and cannot manage privileged roles."
            ),
        )

    already_has_role = selected_role.id in member.role_ids
    if adding and already_has_role:
        return _message_components(
            "⏭️ No Change Needed",
            f"{member.mention} already has {selected_role.mention}.",
            GOLD_ACCENT,
            "assets/Gold_Footer.png",
        )
    if not adding and not already_has_role:
        return _message_components(
            "⏭️ No Change Needed",
            f"{member.mention} does not have {selected_role.mention}.",
            GOLD_ACCENT,
            "assets/Gold_Footer.png",
        )

    operation = "add" if adding else "remove"
    try:
        reason = f"Role {operation} by {ctx.user.username} ({ctx.user.id}) via /role"
        if adding:
            await member.add_role(selected_role, reason=reason)
        else:
            await member.remove_role(selected_role, reason=reason)
    except Exception:
        _log.exception(
            "direct role %s failed role=%s member=%s actor=%s",
            operation, selected_role.id, member.id, ctx.user.id,
        )
        return _error_components(
            "❌ Role Change Failed",
            (
                "Discord refused the role change. Confirm the bot has Manage Roles "
                "and that its role is above the selected role. The failure was logged."
            ),
        )

    verb = "Added" if adding else "Removed"
    preposition = "to" if adding else "from"
    return _message_components(
        f"✅ Role {verb}",
        (
            f"**{verb}:** {selected_role.mention}\n"
            f"**{preposition.title()}:** {member.mention}\n"
            f"**By:** {ctx.member.mention}"
        ),
        GREEN_ACCENT,
        "assets/Green_Footer.png",
    )


@role.register()
class AddRole(
    lightbulb.SlashCommand,
    name="add",
    description="Add one server role to a member",
):
    member = lightbulb.user("member", "Member whose roles you want to change")
    selected_role = lightbulb.role("role", "Role to add")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        components = await _change_one_role(
            ctx, self.member, self.selected_role, True, mongo, bot,
        )
        await ctx.respond(components=components, ephemeral=True)


@role.register()
class RemoveRole(
    lightbulb.SlashCommand,
    name="remove",
    description="Remove one server role from a member",
):
    member = lightbulb.user("member", "Member whose roles you want to change")
    selected_role = lightbulb.role("role", "Role to remove")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        components = await _change_one_role(
            ctx, self.member, self.selected_role, False, mongo, bot,
        )
        await ctx.respond(components=components, ephemeral=True)


@role.register()
class ManageRoles(
    lightbulb.SlashCommand,
    name="manage",
    description="Open bulk role management for a member",
):
    member = lightbulb.user("member", "Member whose roles you want to change")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        guild, member, problem = await _command_context(ctx, self.member, mongo, bot)
        if problem is not None:
            await ctx.respond(components=problem, ephemeral=True)
            return

        action_id = str(ctx.interaction.id)
        data = {
            "_id": action_id,
            "user_id": member.id,
            "recruiter_id": ctx.user.id,
            "guild_id": guild.id,
            "channel_id": ctx.channel_id,
            "origin": "role_command",
            "remove_roles_page": 0,
        }
        await mongo.button_store.insert_one(data)

        components = await manage_roles_handler(
            ctx=ctx,
            action_id=action_id,
            user_id=member.id,
            mongo=mongo,
            bot=bot,
            guild_id=guild.id,
            recruiter_id=ctx.user.id,
            channel_id=ctx.channel_id,
            origin="role_command",
        )
        await ctx.respond(components=components, ephemeral=True)


loader.command(role)
