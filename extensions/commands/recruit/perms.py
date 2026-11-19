"""Authorization shared by recruiter-facing commands and components."""

import hikari

from utils.mongo import MongoClient
from utils.role_permissions import (
    guild_permissions, actor_can_manage_role, actor_can_manage_member,
)


# This is the role already used to authorize the Begin Walkthrough action.
RECRUITMENT_TEAM_ROLE_ID = 1003797104088592444


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
