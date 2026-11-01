"""Discord transport for approved member_roles dashboard requests."""

import asyncio
import time
from collections import OrderedDict
from .timing import read, span
import hikari
from extensions.warrior import core
from extensions.warrior.nickname_audit import edit_nickname
from utils.member_profiles import (
    MemberProfiles,
    ProfileConflict,
    ProfileOutcomeUncertain,
    member_id,
)
from utils.member_timezones import nickname, profile_fields
from utils.member_timezone_import import import_nicknames
from utils.constants import WARRIORS_UNITED_GUILD_ID as GUILD_ID


async def directory(bot):
    async with asyncio.timeout(60):
        rows = []
        async for member in bot.rest.fetch_members(GUILD_ID):
            rows.append(member)
            if len(rows) > 10000:
                raise ValueError(
                    "Member directory is too large; no import was applied."
                )
    if not rows or not any(int(m.id) == int(bot.get_me().id) for m in rows):
        raise ValueError(
            "Discord returned an incomplete directory; nothing was imported."
        )
    return rows


_RUN_ENVIRONMENTS = OrderedDict()


async def environment(bot, run_id):
    key = (id(bot), str(run_id))
    cached = _RUN_ENVIRONMENTS.get(key)
    if (
        cached
        and cached["bot"] is bot
        and time.monotonic() - cached["at"] < 60
    ):
        return cached
    roles, me = await asyncio.gather(
        read("dashboard.roles", bot.rest.fetch_roles(GUILD_ID)),
        read(
            "dashboard.bot",
            bot.rest.fetch_member(GUILD_ID, int(bot.get_me().id)),
        ),
    )
    value = dict(
        bot=bot, roles=roles, me=me, at=time.monotonic(), run_id=run_id
    )
    _RUN_ENVIRONMENTS[key] = value
    _RUN_ENVIRONMENTS.move_to_end(key)
    while len(_RUN_ENVIRONMENTS) > 32:
        _RUN_ENVIRONMENTS.popitem(last=False)
    return value


async def authorize_actor(actor, roles, guild, mongo, section):
    from utils.dashboard_access import dashboard_allowed

    permissions = core.permissions(actor, roles, guild.owner_id)
    identity = dict(
        user_id=str(actor.id),
        role_ids=set(map(int, actor.role_ids)),
        permissions=int(permissions),
        guild_owner=actor.id == guild.owner_id,
        dashboard=True,
    )
    if not await dashboard_allowed(identity, section, mongo):
        raise ValueError(
            "Your Discord access changed. This action was not run."
        )


async def request_context(bot, mongo, row):
    env = await environment(bot, row.get("parent_id") or row["_id"])
    actor, guild = await asyncio.gather(
        read(
            "dashboard.actor",
            bot.rest.fetch_member(GUILD_ID, int(row["user_id"])),
        ),
        read("dashboard.guild", bot.rest.fetch_guild(GUILD_ID)),
    )
    await authorize_actor(actor, env["roles"], guild, mongo, row["section"])
    return dict(env=env, guild=guild)


async def target_context(
    bot, actor_id, target_id, *, require_manageable=True, environment_data=None
):
    async with asyncio.timeout(20):
        if environment_data is None:
            actor, target, me, roles, guild = await asyncio.gather(
                bot.rest.fetch_member(GUILD_ID, int(actor_id)),
                bot.rest.fetch_member(GUILD_ID, int(target_id)),
                bot.rest.fetch_member(GUILD_ID, int(bot.get_me().id)),
                bot.rest.fetch_roles(GUILD_ID),
                bot.rest.fetch_guild(GUILD_ID),
            )
        else:
            env = await environment(bot, environment_data["env"]["run_id"])
            roles, me, guild = (
                env["roles"],
                env["me"],
                environment_data["guild"],
            )
            actor, target = await asyncio.gather(
                read(
                    "dashboard.fresh_actor",
                    bot.rest.fetch_member(GUILD_ID, int(actor_id)),
                ),
                read(
                    "dashboard.fresh_target",
                    bot.rest.fetch_member(GUILD_ID, int(target_id)),
                ),
            )
    if target.is_bot:
        raise ValueError("Bots cannot be standardized.")
    context = dict(
        actor=actor,
        member=target,
        me=me,
        roles=roles,
        guild=guild,
        actor_permissions=core.permissions(actor, roles, guild.owner_id),
        bot_permissions=core.permissions(me, roles, guild.owner_id),
    )
    if require_manageable:
        core.manageable_target(context)
    return context


async def apply(bot, mongo, row, *, request_context=None):
    if row.get("guild_id") != GUILD_ID:
        raise ValueError(
            "Member profiles belong to the Warriors United server."
        )
    store = MemberProfiles(mongo)
    values = row["values"]
    if row["action"] == "import":
        import logging

        started = time.monotonic()
        progress = {}
        try:
            async with asyncio.timeout(100):
                members = await directory(bot)
                counts = await import_nicknames(
                    store,
                    [
                        dict(
                            discord_id=str(m.id),
                            nickname=m.nickname,
                            bot=m.is_bot,
                        )
                        for m in members
                    ],
                    actor_id=row["user_id"],
                    progress=progress,
                )
        except ValueError:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Nickname import stopped early cause=%s elapsed=%.2fs counts=%s",
                type(error).__name__,
                time.monotonic() - started,
                progress,
            )
            outcome = ProfileOutcomeUncertain(
                "Import stopped early. No nicknames changed. Press Import again to continue."
            )
            outcome.counts = dict(progress)
            raise outcome from error
        logging.getLogger(__name__).info(
            "Nickname import finished elapsed=%.2fs counts=%s",
            time.monotonic() - started,
            counts,
        )
        return dict(
            message="Nickname import finished. No nicknames were changed.",
            counts=counts,
        )
    if row["action"] == "save" and not isinstance(values.get("fields"), dict):
        raise ValueError("Choose valid profile fields.")
    uid = member_id(values.get("discord_id"))
    revision = row["revision"]
    if type(revision) is not int or revision < 0:
        raise ValueError("Invalid profile revision. Refresh before saving.")
    if row["action"] == "standardize_one":
        parent = await mongo.bot_config.find_one(
            {
                "_id": row.get("parent_id"),
                "kind": "member_profile_standardize",
                "user_id": row["user_id"],
                "guild_id": GUILD_ID,
            }
        )
        if parent and parent.get("stop_requested"):
            from utils.member_profile_runs import ProfileRunStopped

            raise ProfileRunStopped("Stopped before this member started.")
        if not parent or parent.get("state") != "queued":
            raise ValueError(
                "This reviewed Standardize run is no longer active."
            )
        index = parent["cursor"]
        if (
            row["_id"] != parent["_id"] + ":" + str(index)
            or parent["items"][index] != values
        ):
            raise ValueError(
                "This member does not match the reviewed selection."
            )
        current = await store.get(uid)
        if not current or current["revision"] != revision:
            raise ProfileConflict(
                "Profile changed since preview. Review the member again."
            )
        fields = profile_fields(current)
        new_nickname = values["new_nickname"]
        # The exact reviewed string is authoritative; prevent malformed internal rows.
        suffix = " | " + fields["gmt_label"] + " " + fields["flag"]
        if not new_nickname.endswith(suffix) or len(new_nickname) > 32:
            raise ValueError(
                "Reviewed nickname no longer matches this profile."
            )
        rename = True
    elif row["action"] == "save":
        fields = profile_fields(values.get("fields") or {})
        rename = values.get("rename", False)
        if type(rename) is not bool:
            raise ValueError("Choose whether to change the nickname.")
        new_nickname = (
            nickname(values.get("name"), fields["zone_id"], fields["country"])
            if rename
            else None
        )
    else:
        raise ValueError("Unknown member profile action.")
    already_matched = False
    if rename:
        if "old_nickname" not in values:
            raise ValueError(
                "Nickname changed since preview. Refresh and review it again."
            )
        discord_confirmed = False

        async def prepare():
            nonlocal already_matched
            # One fresh target and actor read inside the serialized edit.
            with span(
                "dashboard.discord_reads", request_id=row.get("_id", "direct")
            ):
                fresh = await target_context(
                    bot, row["user_id"], uid, environment_data=request_context
                )
            if request_context is not None:
                await authorize_actor(
                    fresh["actor"],
                    fresh["roles"],
                    fresh["guild"],
                    mongo,
                    row["section"],
                )
            if fresh["member"].nickname == new_nickname:
                already_matched = True
                return
            if (
                not fresh["bot_permissions"]
                & hikari.Permissions.MANAGE_NICKNAMES
            ):
                raise ValueError("The bot needs Manage Nicknames.")
            if fresh["member"].nickname != values["old_nickname"]:
                raise ValueError(
                    "Nickname changed since preview. Refresh and review it again."
                )

        async def change():
            nonlocal discord_confirmed
            if already_matched:
                return
            if request_context is not None:
                env = _RUN_ENVIRONMENTS.get(
                    (id(bot), str(request_context["env"]["run_id"]))
                )
                if not env or time.monotonic() - env["at"] >= 60:
                    raise ValueError(
                        "Permission checks expired. Review this member again."
                    )
            # No retries: a timeout may follow an accepted Discord edit.
            async with asyncio.timeout(20):
                await read(
                    "dashboard.edit",
                    edit_nickname(
                        bot.rest,
                        GUILD_ID,
                        int(uid),
                        nickname=new_nickname,
                        reason="Reviewed dashboard member timezone update",
                        actor_id=row["user_id"],
                        old_nickname=values["old_nickname"],
                        source=(
                            "standardize"
                            if row["action"] == "standardize_one"
                            else "dashboard"
                        ),
                    ),
                    request_id=row.get("_id", "direct"),
                )
                discord_confirmed = True

        try:
            await store.commit_after(
                uid,
                fields,
                change=change,
                prepare=prepare,
                expected_revision=revision,
                updated_by=row["user_id"],
                source="staff",
            )
        except (
            hikari.ForbiddenError,
            hikari.NotFoundError,
            hikari.BadRequestError,
        ) as error:
            reason = str(
                error.message or "Check permissions and role hierarchy."
            )
            if isinstance(error, hikari.BadRequestError) and isinstance(
                error.errors, dict
            ):
                nick = error.errors.get("nick", {})
                details = (
                    nick.get("_errors", []) if isinstance(nick, dict) else []
                )
                messages = [
                    str(item["message"])
                    for item in details
                    if isinstance(item, dict) and item.get("message")
                ]
                if messages:
                    reason += ". nick: " + "; ".join(messages)[:900]
            raise ValueError(
                "Discord refused the nickname: "
                + reason.rstrip(" .!?")
                + ". No profile was saved."
            ) from error
        except Exception as error:
            if discord_confirmed:
                raise ProfileOutcomeUncertain(
                    "Nickname changed in Discord; profile save was not confirmed. Check the profile before another edit."
                ) from error
            raise
    else:
        await target_context(
            bot,
            row["user_id"],
            uid,
            require_manageable=False,
            environment_data=request_context,
        )
        try:
            await store.write(
                uid,
                fields,
                expected_revision=revision,
                updated_by=row["user_id"],
                source="staff",
            )
        except ValueError:
            raise
        except Exception as error:
            raise ProfileOutcomeUncertain(
                "Profile save was not confirmed. The nickname was not changed; refresh the profile before another edit."
            ) from error
    return dict(
        message=(
            "Profile and nickname saved."
            if rename and not already_matched
            else (
                "Profile saved. Nickname already matched."
                if already_matched
                else "Profile saved. Nickname unchanged."
            )
        )
    )
