"""Shared bot role-hierarchy checks for the current Roles manager."""

import hikari
from extensions.commands.recruit import perms


def bot_top_role_position(guild: hikari.Guild, bot: hikari.GatewayBot) -> int | None:
    """Return the bot member's highest cached role position."""
    me = bot.get_me()
    bot_member = guild.get_member(me.id) if me else None
    if bot_member is None:
        return None

    positions = [
        role.position
        for role_id in bot_member.role_ids
        if (role := guild.get_role(role_id)) is not None
    ]
    return max(positions, default=0)


def role_is_manageable(
    guild: hikari.Guild,
    bot: hikari.GatewayBot,
    role: hikari.Role | None,
) -> bool:
    """Whether Discord will allow this bot to add or remove ``role``.

    A native role select cannot be filtered by the application, so this must be
    checked after every selection as well as when the removal menu is built.
    """
    if role is None or role.id == guild.id or role.is_managed:
        return False

    me = bot.get_me()
    bot_member = guild.get_member(me.id) if me else None
    if bot_member is None:
        return False

    has_permission = bool(
        perms.guild_permissions(bot_member, guild)
        & (hikari.Permissions.MANAGE_ROLES | hikari.Permissions.ADMINISTRATOR)
    )
    top_position = bot_top_role_position(guild, bot)
    return has_permission and top_position is not None and role.position < top_position
