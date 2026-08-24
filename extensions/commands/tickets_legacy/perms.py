"""Who is allowed to act on a ticket.

Extracted because the same check is needed from slash commands AND from
component handlers, and the component dispatcher enforces nothing of its own -
`user_only` on register_action is stored and never read (docs/component-dispatcher.md).
Any button that can change a ticket has to re-check at click time; it cannot
inherit trust from the command that rendered it.
"""

import hikari

from extensions.commands import ticket_runtime
from utils.mongo import MongoClient


async def recruiter_role_ids(mongo: MongoClient) -> tuple[int | None, int | None]:
    """(main, fwa) recruiter roles from the ticket config document."""
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    return config.get("main_recruiter_role"), config.get("fwa_recruiter_role")


async def is_recruiter(member: hikari.Member | None, mongo: MongoClient) -> bool:
    """Recruiter role, or Administrator.

    Mirrors the inline check in close.py verbatim so authorisation does not
    quietly differ between commands.
    """
    if member is None:
        return False  # DM or uncached member; nothing to authorise against
    main_role, fwa_role = await recruiter_role_ids(mongo)
    role_ids = member.role_ids
    return bool(
        (main_role and main_role in role_ids)
        or (fwa_role and fwa_role in role_ids)
        or member.permissions & hikari.Permissions.ADMINISTRATOR
    )


async def is_legacy_control_guild(mongo: MongoClient, guild_id: int | None) -> bool:
    """Bind global legacy configuration writes after rollout is configured."""
    if guild_id is None:
        return False
    try:
        rollout = await ticket_runtime.get_rollout(mongo)
    except Exception:
        rollout = None
    if rollout is not None and rollout.valid:
        return bool(
            rollout.legacy_intake
            and rollout.legacy_intake.guild_id == int(guild_id)
        )
    try:
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    except Exception:
        return False
    if "legacy_ticket_guild_id" not in config:
        # Pre-cross-server deployments had no guild authority marker. Preserve
        # their legacy controls until setup writes the explicit legacy binding.
        return True
    try:
        return int(config.get("legacy_ticket_guild_id")) == int(guild_id)
    except (TypeError, ValueError):
        return False
