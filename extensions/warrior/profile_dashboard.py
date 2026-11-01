"""Discord transport for approved member_roles dashboard requests."""

import asyncio
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


async def target_context(bot, actor_id, target_id, *, require_manageable=True):
    async with asyncio.timeout(20):
        actor, target, me, roles, guild = await asyncio.gather(
            bot.rest.fetch_member(GUILD_ID, int(actor_id)),
            bot.rest.fetch_member(GUILD_ID, int(target_id)),
            bot.rest.fetch_member(GUILD_ID, int(bot.get_me().id)),
            bot.rest.fetch_roles(GUILD_ID),
            bot.rest.fetch_guild(GUILD_ID),
        )
    if target.is_bot:
        raise ValueError("Bots are listed for completeness and cannot be standardized.")
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


async def apply(bot, mongo, row):
    if row.get("guild_id") != GUILD_ID:
        raise ValueError("Member profiles belong to the Warriors United server.")
    store = MemberProfiles(mongo)
    values = row["values"]
    if row["action"] == "import":
        try:
            async with asyncio.timeout(100):
                members = await directory(bot)
                counts = await import_nicknames(
                    store,
                    [
                        dict(discord_id=str(m.id), nickname=m.nickname, bot=m.is_bot)
                        for m in members
                    ],
                    actor_id=row["user_id"],
                )
        except ValueError:
            raise
        except Exception as error:
            raise ProfileOutcomeUncertain(
                "Import did not finish confirming all profile writes. No Discord nicknames were changed. Refresh and rerun safely after the service recovers."
            ) from error
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
    context = await target_context(
        bot,
        row["user_id"],
        uid,
        require_manageable=row["action"] == "standardize_one"
        or values.get("rename") is True,
    )
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
            raise ValueError("This reviewed Standardize run is no longer active.")
        index = parent["cursor"]
        if (
            row["_id"] != parent["_id"] + ":" + str(index)
            or parent["items"][index] != values
        ):
            raise ValueError("This member does not match the reviewed selection.")
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
            raise ValueError("Reviewed nickname no longer matches this profile.")
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
    already_matched = rename and context["member"].nickname == new_nickname
    if already_matched:
        rename = False
    if rename:
        if not context["bot_permissions"] & hikari.Permissions.MANAGE_NICKNAMES:
            raise ValueError("The bot needs Manage Nicknames.")
        if (
            "old_nickname" not in values
            or context["member"].nickname != values["old_nickname"]
        ):
            raise ValueError(
                "Nickname changed since preview. Refresh and review it again."
            )

        discord_confirmed = False

        async def change():
            nonlocal discord_confirmed
            # Recheck roles and the exact old nickname inside the serialized edit.
            fresh = await target_context(bot, row["user_id"], uid)
            if not fresh["bot_permissions"] & hikari.Permissions.MANAGE_NICKNAMES:
                raise ValueError("The bot needs Manage Nicknames.")
            if fresh["member"].nickname != values["old_nickname"]:
                raise ValueError(
                    "Nickname changed since preview. Refresh and review it again."
                )
            # No retries: a timeout may follow an accepted Discord edit.
            async with asyncio.timeout(20):
                await edit_nickname(
                    bot.rest,
                    GUILD_ID,
                    int(uid),
                    nickname=new_nickname,
                    reason="Reviewed dashboard member timezone update",
                    actor_id=row["user_id"],
                    old_nickname=fresh["member"].nickname,
                    source=(
                        "standardize"
                        if row["action"] == "standardize_one"
                        else "dashboard"
                    ),
                )
                discord_confirmed = True

        try:
            await store.commit_after(
                uid,
                fields,
                change=change,
                expected_revision=revision,
                updated_by=row["user_id"],
                source="staff",
            )
        except (
            hikari.ForbiddenError,
            hikari.NotFoundError,
            hikari.BadRequestError,
        ) as error:
            reason = str(error.message or "Check permissions and role hierarchy.")
            if isinstance(error, hikari.BadRequestError) and isinstance(
                error.errors, dict
            ):
                nick = error.errors.get("nick", {})
                details = nick.get("_errors", []) if isinstance(nick, dict) else []
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
            if rename
            else (
                "Profile saved. Nickname already matched."
                if already_matched
                else "Profile saved. Nickname unchanged."
            )
        )
    )
