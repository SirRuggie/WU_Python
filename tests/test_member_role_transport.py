"""Detached fake Discord state: no live roles, messages or nickname changes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from extensions import member_role_dashboard as transport
from utils.member_profile_runs import ProfileRunStopped

ACTOR = "505227988229554179"
USER = "123456789012345678"
ROLE = "345678901234567890"
BOT = "888888888888888888"


def fixture(actor_id=ACTOR):
    roles = {
        1: S(id=1, name="Actor", position=20, permissions=268435456, is_managed=False),
        2: S(id=2, name="Bot", position=30, permissions=268435456, is_managed=False),
        int(ROLE): S(
            id=int(ROLE),
            name="Member role",
            position=5,
            permissions=0,
            is_managed=False,
        ),
    }
    state = {int(actor_id): [1], int(BOT): [2], int(USER): []}

    async def member(guild, uid):
        return S(id=int(uid), role_ids=list(state[int(uid)]), is_bot=False)

    async def add(guild, uid, rid, **kwargs):
        state[int(uid)].append(int(rid))

    async def remove(guild, uid, rid, **kwargs):
        state[int(uid)].remove(int(rid))

    bot = S(
        get_me=lambda: S(id=int(BOT)),
        rest=S(
            fetch_member=AsyncMock(side_effect=member),
            fetch_roles=AsyncMock(side_effect=lambda guild: list(roles.values())),
            fetch_guild=AsyncMock(return_value=S(owner_id=999999999999999999)),
            add_role_to_member=AsyncMock(side_effect=add),
            remove_role_from_member=AsyncMock(side_effect=remove),
        ),
    )
    values = dict(
        discord_id=USER,
        role_id=ROLE,
        operation="add",
        expected_role_ids=[],
        bot=False,
        protected=False,
        revision=0,
    )
    row = dict(
        _id="run:0",
        parent_id="run",
        kind="manage_web_request",
        status="running",
        section="roles",
        action="bulk_one",
        values=values,
        user_id=actor_id,
        guild_id=transport.GUILD_ID,
    )
    parent = dict(
        _id="run",
        kind="member_profile_standardize",
        run_type="roles",
        state="queued",
        items=[values],
        cursor=0,
        user_id=actor_id,
        guild_id=transport.GUILD_ID,
    )
    policy = dict(_id="dashboard-access-v2", revision=1, grants=[])

    async def read(query, *args, **kwargs):
        return deepcopy(parent if query.get("_id") == "run" else policy)

    coll = S(
        find_one=AsyncMock(side_effect=read),
        update_one=AsyncMock(return_value=S(matched_count=1)),
    )
    return bot, S(bot_config=coll), state, roles, row, parent, policy


def test_five_fresh_inputs_then_one_role_write_and_durable_audit():
    async def run():
        bot, mongo, state, roles, row, parent, policy = fixture()
        ctx = await transport.request_context(bot, mongo, row)
        assert bot.rest.fetch_member.await_count == 3
        bot.rest.fetch_roles.assert_awaited_once()
        bot.rest.fetch_guild.assert_awaited_once()
        result = await transport.apply(bot, mongo, row, ctx)
        assert result["changed"] and state[int(USER)] == [int(ROLE)]
        audit = mongo.bot_config.update_one.await_args.args[1]["$set"]["role_audit"]
        assert (
            audit["actor_id"] == ACTOR
            and audit["before"] is False
            and audit["after"] is True
        )
        assert bot.rest.add_role_to_member.await_count == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "problem",
    [
        "managed",
        "above_bot",
        "above_actor",
        "owner_target",
        "everyone",
        "protected",
        "bot_target",
    ],
)
def test_unsafe_or_newly_protected_role_never_writes(problem):
    async def run():
        bot, mongo, state, roles, row, parent, policy = fixture()
        if problem == "managed":
            roles[int(ROLE)].is_managed = True
        elif problem == "above_bot":
            roles[int(ROLE)].position = 40
        elif problem == "above_actor":
            roles[int(ROLE)].position = 25
        elif problem == "owner_target":
            bot.rest.fetch_guild.return_value = S(owner_id=int(USER))
        elif problem == "everyone":
            row["values"]["role_id"] = str(transport.GUILD_ID)
            roles[transport.GUILD_ID] = S(
                id=transport.GUILD_ID, position=0, permissions=0, is_managed=False
            )
        elif problem == "protected":
            roles[int(ROLE)].permissions = 8
        else:
            original = bot.rest.fetch_member.side_effect

            async def bot_member(guild, uid):
                value = await original(guild, uid)
                if int(uid) == int(USER):
                    value.is_bot = True
                return value

            bot.rest.fetch_member.side_effect = bot_member
        with pytest.raises(ValueError):
            await transport.request_context(bot, mongo, row)
        bot.rest.add_role_to_member.assert_not_awaited()
        bot.rest.remove_role_from_member.assert_not_awaited()

    asyncio.run(run())


def test_stale_member_role_state_and_stop_do_not_write():
    async def run():
        bot, mongo, state, roles, row, parent, policy = fixture()
        state[int(USER)] = [99]
        ctx = await transport.request_context(bot, mongo, row)
        with pytest.raises(ValueError):
            await transport.apply(bot, mongo, row, ctx)
        state[int(USER)] = []
        ctx = await transport.request_context(bot, mongo, row)
        parent["stop_requested"] = True
        with pytest.raises(ProfileRunStopped):
            await transport.apply(bot, mongo, row, ctx)
        bot.rest.add_role_to_member.assert_not_awaited()

    asyncio.run(run())


def test_audit_failure_after_accepted_write_is_not_an_automatic_replay():
    async def run():
        bot, mongo, state, roles, row, parent, policy = fixture()
        mongo.bot_config.update_one.side_effect = RuntimeError("receipt lost")
        ctx = await transport.request_context(bot, mongo, row)
        with pytest.raises(RuntimeError):
            await transport.apply(bot, mongo, row, ctx)
        assert state[int(USER)] == [int(ROLE)]
        # A fresh explicit read recognizes the accepted role. No second write.
        ctx = await transport.request_context(bot, mongo, row)
        result = await transport.apply(bot, mongo, row, ctx)
        assert (
            result["changed"] is False and bot.rest.add_role_to_member.await_count == 1
        )

    asyncio.run(run())


def test_revoked_role_access_is_checked_again_for_the_next_member():
    async def run():
        uid = "234567890123456789"
        bot, mongo, state, roles, row, parent, policy = fixture(uid)
        policy["grants"] = [dict(kind="user", id=uid, permissions=["member_roles"])]
        await transport.request_context(bot, mongo, row)
        policy["grants"][0]["permissions"] = []
        with pytest.raises(ValueError):
            await transport.request_context(bot, mongo, row)
        bot.rest.add_role_to_member.assert_not_awaited()
        assert (
            bot.rest.fetch_roles.await_count == 2
            and bot.rest.fetch_member.await_count == 6
        )

    asyncio.run(run())


def test_nonowner_cannot_grant_dashboard_access_even_with_confirmation():
    async def run():
        uid = "234567890123456789"
        bot, mongo, state, roles, row, parent, policy = fixture(uid)
        policy["grants"] = [
            dict(kind="user", id=uid, permissions=["member_roles"]),
            dict(kind="role", id=ROLE, permissions=["cwl_settings"]),
        ]
        row["values"]["protected"] = True
        with pytest.raises(ValueError):
            await transport.request_context(bot, mongo, row)
        bot.rest.add_role_to_member.assert_not_awaited()

    asyncio.run(run())


def test_owner_protected_role_requires_explicit_confirmation_in_durable_manifest():
    async def run():
        bot, mongo, state, roles, row, parent, policy = fixture()
        roles[int(ROLE)].permissions = 8
        roles[1].permissions |= 8  # Preserve Discord's existing actor-permission rule.
        with pytest.raises(ValueError):
            await transport.request_context(bot, mongo, row)
        row["values"]["protected"] = True
        ctx = await transport.request_context(bot, mongo, row)
        await transport.apply(bot, mongo, row, ctx)
        bot.rest.add_role_to_member.assert_awaited_once()

    asyncio.run(run())
