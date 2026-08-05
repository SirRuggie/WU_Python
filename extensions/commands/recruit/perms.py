"""Authorization shared by recruiter-facing commands and components."""

import hikari

from utils.mongo import MongoClient


# This is the role already used to authorize the Begin Walkthrough action.
RECRUITMENT_TEAM_ROLE_ID = 1003797104088592444


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


async def is_recruiter(
        member: hikari.Member | hikari.InteractionMember | None,
        mongo: MongoClient,
        guild: hikari.Guild | None = None,
) -> bool:
    """Return whether ``member`` may use recruiter role-management tools.

    Ticket configuration has separate Main and FWA recruiter roles. The
    onboarding walkthrough also has a long-standing Recruitment Team role, so
    role management accepts all three plus Discord administrators.
    """
    if member is None:
        return False

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    configured_roles = {
        role_id
        for role_id in (
            config.get("main_recruiter_role"),
            config.get("fwa_recruiter_role"),
            RECRUITMENT_TEAM_ROLE_ID,
        )
        if role_id
    }

    return bool(
        configured_roles.intersection(member.role_ids)
        or guild_permissions(member, guild) & hikari.Permissions.ADMINISTRATOR
    )
