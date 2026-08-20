"""Who is allowed to act on a ticket.

Extracted because the same check is needed from slash commands AND from
component handlers, and the component dispatcher enforces nothing of its own -
`user_only` on register_action is stored and never read (docs/component-dispatcher.md).
Any button that can change a ticket has to re-check at click time; it cannot
inherit trust from the command that rendered it.
"""

import hikari

from utils.mongo import MongoClient


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def recruiter_role_ids(mongo: MongoClient) -> tuple[int | None, int | None]:
    """(main, fwa) recruiter roles from the ticket config document."""
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    return (
        _as_int(config.get("main_recruiter_role")) or None,
        _as_int(config.get("fwa_recruiter_role")) or None,
    )


async def is_target_admin(member: hikari.Member | None, mongo: MongoClient) -> bool:
    """Administrator acting inside the one guild bound to global ticket data."""
    if member is None:
        return False
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    return bool(
        _as_int(config.get("ticket_target_guild_id"))
        and _as_int(getattr(member, "guild_id", 0))
        == _as_int(config.get("ticket_target_guild_id"))
        and member.permissions & hikari.Permissions.ADMINISTRATOR
    )


async def is_recruiter(member: hikari.Member | None, mongo: MongoClient) -> bool:
    """Recruiter role, or Administrator, in the one bound ticket guild.

    Ticket data is global and private. An administrator in any other bot guild
    must not inherit access to the target guild's applicant history or actions.
    """
    if member is None:
        return False  # DM or uncached member; nothing to authorise against
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))
    member_guild_id = _as_int(getattr(member, "guild_id", 0))
    if not target_guild_id or member_guild_id != target_guild_id:
        return False
    main_role = _as_int(config.get("main_recruiter_role"))
    fwa_role = _as_int(config.get("fwa_recruiter_role"))
    role_ids = {_as_int(value) for value in member.role_ids}
    return bool(
        (main_role and main_role in role_ids)
        or (fwa_role and fwa_role in role_ids)
        or member.permissions & hikari.Permissions.ADMINISTRATOR
    )
