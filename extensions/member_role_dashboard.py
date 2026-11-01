"""Fresh Discord role safeguards for reviewed durable Members actions."""

import asyncio
import logging
from types import SimpleNamespace as NS
import hikari
from extensions.commands.recruit import perms
from utils.constants import WARRIORS_UNITED_GUILD_ID as GUILD_ID
from utils.dashboard_access import OWNER_IDS, AccessRepository, dashboard_allowed
from utils.member_profiles import member_id
from utils.member_profile_runs import ProfileRuns
from utils.role_permissions import role_is_manageable


async def request_context(bot, mongo, row):
    values = row.get("values")
    if not isinstance(values, dict) or values.get("operation") not in ("add", "remove"):
        raise ValueError("Choose a reviewed role change.")
    uid = member_id(values.get("discord_id"))
    role_id = member_id(values.get("role_id"))
    async with asyncio.timeout(20):
        actor, target, me, role_rows, guild_row = await asyncio.gather(
            bot.rest.fetch_member(GUILD_ID, int(member_id(row["user_id"]))),
            bot.rest.fetch_member(GUILD_ID, int(uid)),
            bot.rest.fetch_member(GUILD_ID, int(bot.get_me().id)),
            bot.rest.fetch_roles(GUILD_ID),
            bot.rest.fetch_guild(GUILD_ID),
        )
    roles = {int(role.id): role for role in role_rows}
    guild = NS(
        id=GUILD_ID,
        owner_id=guild_row.owner_id,
        get_role=roles.get,
        get_member=lambda key: me if int(key) == int(me.id) else None,
    )
    identity = dict(
        user_id=str(actor.id),
        role_ids=set(map(int, actor.role_ids)),
        permissions=int(perms.guild_permissions(actor, guild)),
        guild_owner=int(actor.id) == int(guild.owner_id),
        dashboard=True,
    )
    if not await dashboard_allowed(identity, "roles", mongo):
        raise ValueError("Your role access changed. No role was changed.")
    if getattr(target, "is_bot", False):
        raise ValueError("Bots cannot be selected for a bulk role change.")
    candidate = roles.get(int(role_id))
    if not role_is_manageable(guild, bot, candidate) or not perms.actor_can_manage_role(
        actor, guild, candidate
    ):
        raise ValueError("This role cannot be changed by you or the bot.")
    if not perms.actor_can_manage_member(actor, target, guild):
        raise ValueError("This person is above your role or is the server owner.")
    policy = await AccessRepository(mongo.bot_config).read()
    access_roles = {
        grant["id"]
        for grant in (policy or {}).get("grants", [])
        if grant["kind"] == "role"
    }
    if role_id in access_roles and str(actor.id) not in OWNER_IDS:
        raise ValueError("Only a dashboard owner can change access roles.")
    protected = role_id in access_roles or bool(
        candidate.permissions & hikari.Permissions.ADMINISTRATOR
    )
    if protected and values.get("protected") is not True:
        raise ValueError(
            "This role now needs a protected-role confirmation. Review again."
        )
    return dict(actor=actor, target=target, role=candidate)


async def apply(bot, mongo, row, ctx):
    owner = ProfileRuns(mongo)
    await owner.reviewed_child(row, run_type="roles")
    values = row["values"]
    target = ctx["target"]
    role = ctx["role"]
    desired = values["operation"] == "add"
    held = int(role.id) in target.role_ids
    if held == desired:
        return dict(message="Already up to date.", changed=False)
    if sorted(map(str, target.role_ids)) != values["expected_role_ids"]:
        raise ValueError(
            "This person’s roles changed after review. No role was changed."
        )
    # A Stop during preparation must prevent this member from starting.
    await owner.reviewed_child(row, run_type="roles")
    method = (
        bot.rest.add_role_to_member if desired else bot.rest.remove_role_from_member
    )
    await method(GUILD_ID, target.id, role.id, reason="Reviewed Members role change")
    logging.getLogger(__name__).info(
        "Member role confirmed request=%s actor=%s member=%s role=%s added=%s",
        row["_id"],
        row["user_id"],
        target.id,
        role.id,
        desired,
    )
    await owner.record_role_change(row, before=held, after=desired)
    return dict(message="Role added." if desired else "Role removed.", changed=True)
