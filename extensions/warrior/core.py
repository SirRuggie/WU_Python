"""Fresh authorization, guild settings and incremental member mutations."""

import asyncio
from datetime import datetime, timezone
import logging
import hikari
from extensions.commands.recruit import perms
from extensions.commands.tickets import store, testing_service
from utils.component_state import get_state
from .schema import SCHEMA_VERSION
from .timing import read, span

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
        await read(
            "mongo.warrior_settings",
            mongo.warrior_settings.find_one({"_id": f"warrior_settings:{guild_id}"}),
            guild_id=int(guild_id),
        )
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


async def context(bot, mongo, guild_id, actor_id, user_id, *, fresh=True):
    if testing_service.is_test_scope(mongo):
        raise SetupError(
            "Warrior Setup changes live members; it is unavailable in isolated ticket testing."
        )
    cache = None if fresh else getattr(bot, "cache", None)
    guild = cache.get_guild(guild_id) if cache is not None else None
    roles = (
        list(cache.get_roles_view_for_guild(guild_id).values())
        if cache is not None
        else []
    )
    ids = [actor_id, user_id, int(bot.get_me().id)]
    members = [
        cache.get_member(guild_id, uid) if cache is not None else None for uid in ids
    ]
    # A partial role view cannot describe the members even for display.
    required = {guild_id} | {
        int(rid) for member in members if member is not None for rid in member.role_ids
    }
    if not required.issubset({int(role.id) for role in roles}):
        roles = []

    async def available(value, operation, fetch, *args):
        if value is not None:
            return value
        return await read(operation, fetch(*args), guild_id=guild_id)

    async def config_read():
        return await read(
            "mongo.ticket_setup",
            mongo.ticket_setup.find_one({"_id": "config"}),
            guild_id=guild_id,
        )

    try:
        with span(
            "context",
            guild_id=guild_id,
            actor_id=actor_id,
            target_id=user_id,
            fresh=fresh,
        ):
            guild, roles, actor, member, me, config = await asyncio.gather(
                available(guild, "rest.guild", bot.rest.fetch_guild, guild_id),
                available(roles or None, "rest.roles", bot.rest.fetch_roles, guild_id),
                *(
                    available(
                        value, "rest.member", bot.rest.fetch_member, guild_id, uid
                    )
                    for uid, value in zip(ids, members)
                ),
                config_read(),
            )
    except hikari.NotFoundError as error:
        raise SetupError(
            "The recruit, recruiter, or bot is no longer in this server."
        ) from error
    config = config or {}
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
    data = await read("mongo.component_state", get_state(mongo, sid))
    if not data or data.get("type") != "warrior_setup":
        raise SetupError("This setup session expired. Run /warrior again.")
    if int(data["guild_id"]) != int(ctx.guild_id or 0) or int(
        data["recruiter_id"]
    ) != int(ctx.user.id):
        raise SetupError(
            "This private setup belongs to another recruiter or server. Run /warrior yourself."
        )
    return data, await context(
        bot,
        mongo,
        int(data["guild_id"]),
        int(ctx.user.id),
        int(data["user_id"]),
        fresh=False,
    )


async def refresh_target(bot, c):
    member = await read(
        "rest.member",
        bot.rest.fetch_member(c["guild"].id, c["member"].id),
        guild_id=int(c["guild"].id),
    )
    return dict(c, member=member)


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
    result = {"added": [], "removed": [], "unchanged": [], "failed": []}
    try:
        c = await context(bot, mongo, c["guild"].id, c["actor"].id, c["member"].id)
        manageable_target(c)
        observed_roles = set(c["member"].role_ids)
        refresh_before_write = False
        for operation, ids in (
            ("added", set(map(int, add))),
            ("removed", set(map(int, remove))),
        ):
            for rid in sorted(ids):
                # A known no-op needs no additional REST context. Every possible
                # write after an earlier attempt still refreshes all five inputs.
                wants_role = operation == "added"
                if refresh_before_write and ((rid in observed_roles) != wants_role):
                    c = await context(
                        bot, mongo, c["guild"].id, c["actor"].id, c["member"].id
                    )
                    observed_roles = set(c["member"].role_ids)
                    refresh_before_write = False
                manageable_target(c)
                role = next((r for r in c["roles"] if int(r.id) == rid), None)
                name = role.name if role else f"Missing role {rid}"
                if not role_allowed(c, role):
                    result["failed"].append(f"{name} (missing or not permitted)")
                    continue
                if (rid in observed_roles) == wants_role:
                    result["unchanged"].append(name)
                    continue
                try:
                    refresh_before_write = True
                    fn = (
                        bot.rest.add_role_to_member
                        if operation == "added"
                        else bot.rest.remove_role_from_member
                    )
                    await read(
                        "rest.role_write",
                        fn(
                            c["guild"].id,
                            c["member"].id,
                            rid,
                            reason=f'Warrior Setup by {c["actor"].id}',
                        ),
                        guild_id=int(c["guild"].id),
                        target_id=int(c["member"].id),
                        role_id=rid,
                    )
                    result[operation].append(name)
                    if wants_role:
                        observed_roles.add(rid)
                    else:
                        observed_roles.discard(rid)
                except hikari.HTTPError as error:
                    log.warning(
                        "warrior role mutation failed guild=%s member=%s role=%s error=%s",
                        c["guild"].id,
                        c["member"].id,
                        rid,
                        type(error).__name__,
                    )
                    result["failed"].append(f"{name} ({type(error).__name__})")
    except asyncio.CancelledError:
        result["failed"].append(
            "Role batch interrupted. Check current member roles before repeating it."
        )
        raise
    except Exception as error:
        had_results = any(result.values())
        result["failed"].append(
            f"Stopped before further changes ({type(error).__name__}): {str(error)[:250]}"
        )
        if not had_results:
            raise
    finally:
        try:
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
                                {
                                    "at": now(),
                                    "actor_id": int(c["actor"].id),
                                    "result": result,
                                }
                            ],
                            "$slice": -100,
                        }
                    },
                },
                upsert=True,
            )
        except Exception as error:
            log.error(
                "warrior role audit unavailable guild=%s actor=%s target=%s applied=%s error=%s",
                c["guild"].id,
                c["actor"].id,
                c["member"].id,
                len(result["added"]) + len(result["removed"]),
                type(error).__name__,
            )
            result["failed"].append(
                "Role audit save not confirmed. Confirmed role changes are listed separately; check the member before another attempt."
            )
    return result


def result_text(result):
    # Surface an interruption even when a large successful batch fills the panel.
    keys = ["failed", *(key for key in result if key != "failed")]
    text = "\n".join(
        f"**{key.title()}:** " + ", ".join(result[key])
        for key in keys
        if result.get(key)
    )
    return (text[:2799] + "…" if len(text) > 2800 else text) or "No changes needed."


async def open_ticket(mongo, guild_id, user_id, *, ticket_id=None):
    """Select an onboarding ticket, or validate a run's original ticket.

    Prefer the unique open ticket for a new run; otherwise use the most recently
    approved ticket. Existing runs never switch tickets when another is opened.
    """
    query = {
        **store.RUNTIME_FILTER,
        "guild_id": int(guild_id),
        "user_id": {"$in": [int(user_id), str(user_id)]},
        "venue": "thread",
    }
    if ticket_id is not None:
        query.update(_id=ticket_id, status={"$in": ["open", "approved"]})
        rows = await mongo.tickets.find(query).to_list(length=1)
    else:
        rows = await mongo.tickets.find({**query, "status": "open"}).to_list(length=3)
        rows = [
            r
            for r in rows
            if not r.get("thread_missing") and not testing_service.is_test_ticket(r)
        ]
        if len(rows) > 1:
            raise SetupError(
                "This member has multiple open tickets. Resolve the duplicate before starting the walkthrough."
            )
        if not rows:
            rows = (
                await mongo.tickets.find(
                    {
                        **query,
                        "status": "approved",
                        "$or": [
                            {"thread_missing": {"$exists": False}},
                            {"thread_missing": None},
                            {"thread_missing": False},
                            {"thread_missing": {}},
                        ],
                    }
                )
                .sort([("handled_at", -1), ("created_at", -1), ("_id", -1)])
                .to_list(length=3)
            )
            rows = [r for r in rows if not testing_service.is_test_ticket(r)][:1]
    rows = [
        r
        for r in rows
        if not r.get("thread_missing") and not testing_service.is_test_ticket(r)
    ]
    if not rows:
        raise SetupError(
            "The walkthrough’s original ticket must still be open or approved and available."
            if ticket_id is not None
            else "There is no open or approved live ticket for this member in this server."
        )
    return rows[0]


async def clans(mongo, c):
    ids = {int(r.id) for r in c["roles"]}
    rows = await read(
        "mongo.clans",
        mongo.clans.find().to_list(length=None),
        guild_id=int(c["guild"].id),
    )
    return sorted(
        [r for r in rows if int(r.get("role_id") or 0) in ids],
        key=lambda r: str(r.get("name", "")),
    )
