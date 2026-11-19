"""Shared role authorization and bot hierarchy checks; no transport or storage."""

import hikari


def guild_permissions(
        member: hikari.Member | hikari.InteractionMember | None,
        guild: hikari.Guild | None,
) -> hikari.Permissions:
    """Resolve guild permissions for cached and interaction member shapes."""
    if member is None:
        return hikari.Permissions.NONE

    interaction_permissions = getattr(member, "permissions", None)
    if interaction_permissions is not None:
        return hikari.Permissions(interaction_permissions)

    if guild is None:
        return hikari.Permissions.NONE
    if member.id == guild.owner_id:
        return hikari.Permissions.ADMINISTRATOR

    permissions = hikari.Permissions.NONE
    role_ids = set(member.role_ids)
    role_ids.add(guild.id)  # @everyone is omitted from Discord member payloads.
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if role is not None:
            permissions |= role.permissions
    return permissions


def actor_can_manage_role(
        member: hikari.Member | hikari.InteractionMember | None,
        guild: hikari.Guild,
        role: hikari.Role,
) -> bool:
    """Apply Discord-like hierarchy and privileged-role checks to an actor."""
    if member is None:
        return False

    permissions = guild_permissions(member, guild)
    if permissions & hikari.Permissions.ADMINISTRATOR:
        return True

    # Delegated bot tools must not grant permissions the actor does not already
    # possess, even when the role happens to sit below the actor in hierarchy.
    if role.permissions & ~permissions:
        return False

    positions = [
        actor_role.position
        for role_id in member.role_ids
        if (actor_role := guild.get_role(role_id)) is not None
    ]
    return role.position < max(positions, default=0)


def actor_can_manage_member(
        actor: hikari.Member | hikari.InteractionMember | None,
        target: hikari.Member | hikari.InteractionMember,
        guild: hikari.Guild,
) -> bool:
    """Prevent delegated role tools from bypassing member hierarchy."""
    if actor is None:
        return False

    if target.id == guild.owner_id:
        return False

    if guild_permissions(actor, guild) & hikari.Permissions.ADMINISTRATOR:
        return True

    actor_positions = [
        role.position
        for role_id in actor.role_ids
        if (role := guild.get_role(role_id)) is not None
    ]
    target_positions = [
        role.position
        for role_id in target.role_ids
        if (role := guild.get_role(role_id)) is not None
    ]
    return max(actor_positions, default=0) > max(target_positions, default=0)


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
        guild_permissions(bot_member, guild)
        & (hikari.Permissions.MANAGE_ROLES | hikari.Permissions.ADMINISTRATOR)
    )
    top_position = bot_top_role_position(guild, bot)
    return has_permission and top_position is not None and role.position < top_position


def role_is_safe_for_pool(guild, bot, role) -> bool:
    """Automatic CWL roles may never grant administrator permission."""
    return bool(
        role_is_manageable(guild, bot, role)
        and not (role.permissions & hikari.Permissions.ADMINISTRATOR)
    )


def member_role_ids(role_ids, guild_id):
    """Canonical REST/Hikari role snapshot; @everyone is implicit membership."""
    return sorted(
        {str(role_id) for role_id in role_ids if str(role_id) != str(guild_id)}
    )
