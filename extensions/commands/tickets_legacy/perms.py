"""Who is allowed to act on a ticket.

Extracted because the same check is needed from slash commands AND from
component handlers, and the component dispatcher enforces nothing of its own -
`user_only` on register_action is stored and never read (docs/component-dispatcher.md).
Any button that can change a ticket has to re-check at click time; it cannot
inherit trust from the command that rendered it.
"""

import hikari

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
