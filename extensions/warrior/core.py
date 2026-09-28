"""Fresh authorization, guild settings and incremental member mutations."""

from datetime import datetime, timezone
import logging
import re
import hikari
from extensions.commands.recruit import perms
from extensions.commands.tickets import store, testing_service
from utils.component_state import get_state
from .schema import SCHEMA_VERSION

log = logging.getLogger(__name__)
STANDARD = {
    "family": 1003749467863924806,
    "recruit": 779277305671319572,
    "strike_accepted": 1003797283348946944,
    "visitor": 1003796476750745751,
}
TOWNHALLS = dict(
    zip(
        range(18, 1, -1),
        [
            1439244282392215552,
            1315835882435121152,
            1186343231303200848,
            1029879502484025474,
            1003796205630914630,
            1003796042317316166,
            1003796143630712943,
            1003796173993287690,
            1003796340578471977,
            1003795980052873276,
            1003796008121143436,
            1006456898616311808,
            1006457868037410887,
            1006458029597798420,
            1006458193418924062,
            1006458298842746890,
            1148951648484474951,
        ],
    )
)
CHANNELS = {"help": 1005916813378465832, "lounge": 671836698371424256}


class SetupError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def settings(mongo, guild_id):
    saved = (
        await mongo.warrior_settings.find_one({"_id": f"warrior_settings:{guild_id}"})
        or {}
    )
    return {
        "roles": STANDARD | saved.get("roles", {}),
        "townhalls": {str(k): v for k, v in TOWNHALLS.items()}
        | saved.get("townhalls", {}),
        "channels": CHANNELS | saved.get("channels", {}),
    }


def permissions(member, roles, owner_id):
    if int(member.id) == int(owner_id):
        return hikari.Permissions.all_permissions()
    value = hikari.Permissions.NONE
    for role in roles:
        if role.id == member.guild_id or role.id in member.role_ids:
            value |= role.permissions
    return (
        hikari.Permissions.all_permissions()
        if value & hikari.Permissions.ADMINISTRATOR
        else value
    )


def top(member, roles):
    return max((r.position for r in roles if r.id in member.role_ids), default=0)


async def context(bot, mongo, guild_id, actor_id, user_id):
    if testing_service.is_test_scope(mongo):
        raise SetupError(
            "Warrior Setup changes live members; it is unavailable in isolated ticket testing."
        )
    guild = await bot.rest.fetch_guild(guild_id)
    roles = await bot.rest.fetch_roles(guild_id)
    try:
        actor = await bot.rest.fetch_member(guild_id, actor_id)
        member = await bot.rest.fetch_member(guild_id, user_id)
        me = await bot.rest.fetch_member(guild_id, bot.get_me().id)
    except hikari.NotFoundError as error:
        raise SetupError(
            "The recruit, recruiter, or bot is no longer in this server."
        ) from error
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    allowed = {perms.RECRUITMENT_TEAM_ROLE_ID} | {
        int(config[k])
        for k in (
            "main_recruiter_role",
            "fwa_recruiter_role",
            "main_thread_recruiter_role",
            "fwa_thread_recruiter_role",
        )
        if config.get(k)
    }
    actor_perms = permissions(actor, roles, guild.owner_id)
    if not (
        allowed.intersection(actor.role_ids)
        or actor_perms & hikari.Permissions.ADMINISTRATOR
    ):
        raise SetupError("Recruitment Team or administrator permission is required.")
    if member.is_bot:
        raise SetupError("Choose a human member to set up.")
    return dict(
        guild=guild,
        roles=roles,
        actor=actor,
        member=member,
        me=me,
        actor_permissions=actor_perms,
        bot_permissions=permissions(me, roles, guild.owner_id),
    )


async def session(ctx, bot, mongo, sid):
    data = await get_state(mongo, sid)
    if not data or data.get("type") != "warrior_setup":
        raise SetupError("This setup session expired. Run /warrior again.")
    if int(data["guild_id"]) != int(ctx.guild_id or 0) or int(
        data["recruiter_id"]
    ) != int(ctx.user.id):
        raise SetupError(
            "This private setup belongs to another recruiter or server. Run /warrior yourself."
        )
    return data, await context(
        bot, mongo, int(data["guild_id"]), int(ctx.user.id), int(data["user_id"])
    )


def manageable_target(c):
    if c["member"].id == c["guild"].owner_id:
        raise SetupError("The server owner cannot be changed by this tool.")
    if not c["actor_permissions"] & hikari.Permissions.ADMINISTRATOR and top(
        c["actor"], c["roles"]
    ) <= top(c["member"], c["roles"]):
        raise SetupError("This member is at or above your highest role.")
    if top(c["me"], c["roles"]) <= top(c["member"], c["roles"]):
        raise SetupError("This member is at or above the bot’s highest role.")


def role_allowed(c, role):
    return bool(
        role
        and role.id != c["guild"].id
        and not role.is_managed
        and c["bot_permissions"] & hikari.Permissions.MANAGE_ROLES
        and role.position < top(c["me"], c["roles"])
        and (
            c["actor_permissions"] & hikari.Permissions.ADMINISTRATOR
            or (
                role.position < top(c["actor"], c["roles"])
                and not role.permissions & ~c["actor_permissions"]
            )
        )
    )


async def change_roles(bot, mongo, c, *, add=(), remove=()):
    manageable_target(c)
    result = {"added": [], "removed": [], "unchanged": [], "failed": []}
    roles = {int(r.id): r for r in c["roles"]}
    for operation, ids in (
        ("added", set(map(int, add))),
        ("removed", set(map(int, remove))),
    ):
        for rid in sorted(ids):
            role = roles.get(rid)
            name = role.name if role else f"Missing role {rid}"
            if not role_allowed(c, role):
                result["failed"].append(f"{name} (missing or not permitted)")
                continue
            current = await bot.rest.fetch_member(c["guild"].id, c["member"].id)
            if (rid in current.role_ids) == (operation == "added"):
                result["unchanged"].append(name)
                continue
            try:
                fn = (
                    bot.rest.add_role_to_member
                    if operation == "added"
                    else bot.rest.remove_role_from_member
                )
                await fn(
                    c["guild"].id,
                    c["member"].id,
                    rid,
                    reason=f'Warrior Setup by {c["actor"].id}',
                )
                result[operation].append(name)
            except hikari.HTTPError as error:
                log.warning(
                    "warrior role mutation failed guild=%s member=%s role=%s error=%s",
                    c["guild"].id,
                    c["member"].id,
                    rid,
                    type(error).__name__,
                )
                result["failed"].append(f"{name} ({type(error).__name__})")
    await mongo.warrior_audit.update_one(
        {"_id": f'warrior_audit:{c["guild"].id}:{c["member"].id}'},
        {
            "$setOnInsert": {
                "schema_version": SCHEMA_VERSION,
                "guild_id": int(c["guild"].id),
                "user_id": int(c["member"].id),
            },
            "$push": {
                "events": {
                    "$each": [
                        {"at": now(), "actor_id": int(c["actor"].id), "result": result}
                    ],
                    "$slice": -100,
                }
            },
        },
        upsert=True,
    )
    return result


def result_text(result):
    return (
        "\n".join(
            f"**{key.title()}:** " + ", ".join(values)
            for key, values in result.items()
            if values
        )[:2800]
        or "No changes needed."
    )


def nickname(ign, zone, country):
    ign, zone, country = ign.strip(), zone.strip().upper(), country.strip()
    if re.fullmatch("[A-Za-z]{2}", country):
        country = "".join(chr(ord(x) + 127397) for x in country.upper())
    elif not (len(country) == 2 and all(0x1F1E6 <= ord(x) <= 0x1F1FF for x in country)):
        raise SetupError(
            "Use a two-letter country code, such as US, or a country flag."
        )
    value = f"{ign} | {zone} {country}"
    if not ign or not zone or len(value) > 32 or "\n" in value:
        raise SetupError(
            f"The combined nickname must fit within 32 characters (currently {len(value)}). Shorten the name or time zone."
        )
    return value


async def open_ticket(mongo, guild_id, user_id):
    rows = await mongo.tickets.find(
        {
            **store.RUNTIME_FILTER,
            "guild_id": int(guild_id),
            "user_id": {"$in": [int(user_id), str(user_id)]},
            "status": "open",
            "venue": "thread",
        }
    ).to_list(length=3)
    rows = [
        r
        for r in rows
        if not r.get("thread_missing") and not testing_service.is_test_ticket(r)
    ]
    if len(rows) != 1:
        raise SetupError(
            "There is no open live ticket for this member in this server."
            if not rows
            else "This member has multiple open tickets. Resolve the duplicate before starting the walkthrough."
        )
    return rows[0]


async def clans(mongo, c):
    ids = {int(r.id) for r in c["roles"]}
    rows = await mongo.clans.find().to_list(length=None)
    return sorted(
        [r for r in rows if int(r.get("role_id") or 0) in ids],
        key=lambda r: str(r.get("name", "")),
    )
