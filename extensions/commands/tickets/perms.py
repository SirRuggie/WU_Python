"""Who is allowed to act on a ticket.

Extracted because the same check is needed from slash commands AND from
component handlers, and the component dispatcher enforces nothing of its own -
`user_only` on register_action is stored and never read (docs/component-dispatcher.md).
Any button that can change a ticket has to re-check at click time; it cannot
inherit trust from the command that rendered it.
"""

import hikari

from utils.mongo import MongoClient
from extensions.commands.tickets import schema, testing_service


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def recruiter_role_ids(mongo: MongoClient) -> tuple[int | None, int | None]:
    """(main, fwa) recruiter roles from the ticket config document."""
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    return (
        _as_int(config.get("main_thread_recruiter_role")) or None,
        _as_int(config.get("fwa_thread_recruiter_role")) or None,
    )


async def staff_viewer_role_ids(mongo: MongoClient) -> set[int]:
    """Explicit private-channel viewers; these roles do not authorize actions."""
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    return {_as_int(value) for value in (config.get("ticket_staff_viewer_role_ids") or ()) if _as_int(value)}


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
    if testing_service.is_test_scope(mongo):
        window = await testing_service.active_window(mongo)
        return bool(
            window
            and _as_int(getattr(member, "guild_id", 0)) == _as_int(window.get("guild_id"))
            and testing_service.user_allowed(
                window, _as_int(getattr(member, "id", 0)),
                getattr(member, "role_ids", ()) or (),
                bool(getattr(member, "permissions", 0) & hikari.Permissions.ADMINISTRATOR),
            )
        )
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))
    member_guild_id = _as_int(getattr(member, "guild_id", 0))
    if not target_guild_id or member_guild_id != target_guild_id:
        return False
    main_role = _as_int(config.get("main_thread_recruiter_role"))
    fwa_role = _as_int(config.get("fwa_thread_recruiter_role"))
    role_ids = {_as_int(value) for value in member.role_ids}
    return bool(
        (main_role and main_role in role_ids)
        or (fwa_role and fwa_role in role_ids)
        or member.permissions & hikari.Permissions.ADMINISTRATOR
    )


async def is_ticket_staff(member: hikari.Member | None, mongo: MongoClient) -> bool:
    """Recruiter, or a holder of a Warrior Desk (account/staff) role.

    Console access only: viewing the hub and tools and selecting tickets. It
    does not authorise recruit actions, staff-create or flag writes by ID.
    """
    if await is_recruiter(member, mongo):
        return True
    if member is None or testing_service.is_test_scope(mongo):
        return False
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))
    if not target_guild_id or _as_int(getattr(member, "guild_id", 0)) != target_guild_id:
        return False
    role_ids = {_as_int(value) for value in member.role_ids}
    desk_roles = {
        _as_int(config.get(f"{kind}_thread_recruiter_role"))
        for kind in schema.DESK_TICKET_TYPES
    }
    return bool(role_ids & (desk_roles - {0}))


async def can_handle(
    member: hikari.Member | None, mongo: MongoClient, ticket_type: str
) -> bool:
    """May this member act on a ticket of ``ticket_type``?

    Administrator in the bound guild. Recruit types (main, fwa) accept either
    recruit role, as before; account and staff need their own role.
    """
    if member is None:
        return False
    if testing_service.is_test_scope(mongo):
        return await is_recruiter(member, mongo)
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))
    if not target_guild_id or _as_int(getattr(member, "guild_id", 0)) != target_guild_id:
        return False
    if member.permissions & hikari.Permissions.ADMINISTRATOR:
        return True
    kind = str(ticket_type or "").strip().lower()
    if kind not in schema.TICKET_TYPES:
        return False
    if kind in schema.RECRUIT_TICKET_TYPES:
        return await is_recruiter(member, mongo)
    role = _as_int(config.get(f"{kind}_thread_recruiter_role"))
    return bool(role and role in {_as_int(value) for value in member.role_ids})
