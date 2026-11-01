import asyncio, time
from types import SimpleNamespace as S
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest, hikari
from extensions.warrior import profile_dashboard as actions
from utils import dashboard_access

UID = "123456789012345678"
ACTOR = "234567890123456789"
BOT = "345678901234567890"
GUILD = actions.GUILD_ID


def transport():
    roles = [
        S(id=GUILD, permissions=hikari.Permissions.NONE, position=0),
        S(
            id=101,
            permissions=hikari.Permissions.MANAGE_NICKNAMES,
            position=10,
        ),
        S(id=102, permissions=hikari.Permissions.ADMINISTRATOR, position=20),
        S(id=103, permissions=hikari.Permissions.NONE, position=1),
    ]
    people = {
        int(ACTOR): S(
            id=int(ACTOR),
            guild_id=GUILD,
            role_ids=[102],
            nickname="Staff",
            is_bot=False,
        ),
        int(BOT): S(
            id=int(BOT),
            guild_id=GUILD,
            role_ids=[101],
            nickname="Bot",
            is_bot=True,
        ),
        int(UID): S(
            id=int(UID),
            guild_id=GUILD,
            role_ids=[103],
            nickname="Old",
            is_bot=False,
        ),
    }

    async def member(guild, uid):
        return deepcopy(people[uid])

    rest = S(
        fetch_member=AsyncMock(side_effect=member),
        fetch_roles=AsyncMock(return_value=roles),
        fetch_guild=AsyncMock(
            return_value=S(id=GUILD, owner_id=456789012345678901)
        ),
        edit_member=AsyncMock(),
    )
    return S(rest=rest, get_me=lambda: S(id=int(BOT))), people


def test_run_metadata_cache_expires_but_each_target_and_actor_is_fresh(
    monkeypatch,
):
    async def run():
        bot, people = transport()
        clock = [0]
        monkeypatch.setattr(actions, "time", S(monotonic=lambda: clock[0]))
        actions._RUN_ENVIRONMENTS.clear()
        env = await actions.environment(bot, "run")
        context = dict(env=env, guild=await bot.rest.fetch_guild(GUILD))
        first = await actions.target_context(
            bot, ACTOR, UID, environment_data=context
        )
        people[int(UID)].nickname = "Updated"
        second = await actions.target_context(
            bot, ACTOR, UID, environment_data=context
        )
        assert (
            first["member"].nickname == "Old"
            and second["member"].nickname == "Updated"
        )
        assert bot.rest.fetch_roles.await_count == 1
        assert (
            sum(
                c.args[1] == int(BOT)
                for c in bot.rest.fetch_member.await_args_list
            )
            == 1
        )
        assert (
            sum(
                c.args[1] == int(UID)
                for c in bot.rest.fetch_member.await_args_list
            )
            == 2
        )
        clock[0] = 61
        await actions.target_context(bot, ACTOR, UID, environment_data=context)
        assert bot.rest.fetch_roles.await_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("change", ["nickname", "access", "role"])
def test_lease_time_changes_fail_before_any_edit_or_profile_write(
    monkeypatch, change
):
    async def run():
        bot, people = transport()
        actions._RUN_ENVIRONMENTS.clear()
        access = [True]

        async def allowed(actor, section, mongo):
            return access[0] and bool(
                actor["permissions"] & int(hikari.Permissions.ADMINISTRATOR)
            )

        monkeypatch.setattr(dashboard_access, "dashboard_allowed", allowed)
        row = dict(
            _id="fixture-request",
            guild_id=GUILD,
            section="member_profiles",
            action="save",
            user_id=ACTOR,
            revision=1,
            values=dict(
                discord_id=UID,
                fields=dict(zone_id="gmt-5", country="US"),
                rename=True,
                name="Name",
                old_nickname="Old",
            ),
        )
        context = await actions.request_context(bot, None, row)
        written = []

        async def commit(*args, change, **kwargs):
            if mode == "nickname":
                people[int(UID)].nickname = "Changed while claiming"
            elif mode == "role":
                people[int(ACTOR)].role_ids = []
            else:
                access[0] = False
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()
            written.append(True)

        mode = change
        monkeypatch.setattr(
            actions, "MemberProfiles", lambda _: S(commit_after=commit)
        )
        with pytest.raises(ValueError):
            await actions.apply(bot, None, row, request_context=context)
        bot.rest.edit_member.assert_not_awaited()
        assert not written
        assert (
            sum(
                c.args[1] == int(UID)
                for c in bot.rest.fetch_member.await_args_list
            )
            == 1
        )

    asyncio.run(run())


def test_rate_limit_wait_is_awaited_and_failure_is_not_retried(monkeypatch):
    async def run():
        bot, _ = transport()
        committed = []
        monkeypatch.setattr(
            actions,
            "target_context",
            AsyncMock(
                return_value=dict(
                    member=S(nickname="Old"),
                    bot_permissions=hikari.Permissions.MANAGE_NICKNAMES,
                )
            ),
        )

        async def commit(*args, change, **kwargs):
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()
            committed.append(True)

        monkeypatch.setattr(
            actions, "MemberProfiles", lambda _: S(commit_after=commit)
        )
        row = dict(
            _id="fixture",
            guild_id=GUILD,
            section="member_profiles",
            action="save",
            user_id=ACTOR,
            revision=1,
            values=dict(
                discord_id=UID,
                fields=dict(zone_id="gmt-5", country="US"),
                rename=True,
                name="Name",
                old_nickname="Old",
            ),
        )

        async def limited(*args, **kwargs):
            await asyncio.sleep(0.03)

        bot.rest.edit_member.side_effect = limited
        start = time.perf_counter()
        await actions.apply(bot, None, row)
        assert time.perf_counter() - start >= 0.03 and len(committed) == 1
        error = hikari.RateLimitTooLongError(
            route=S(),
            is_global=False,
            retry_after=60,
            max_retry_after=20,
            reset_at=0,
            limit=1,
            period=60,
        )
        bot.rest.edit_member.reset_mock()
        bot.rest.edit_member.side_effect = error
        with pytest.raises(hikari.RateLimitTooLongError):
            await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_awaited_once()
        assert len(committed) == 1

    asyncio.run(run())


def test_fast_scheduler_owns_one_background_driver_and_shutdown_cancels_it(
    monkeypatch,
):
    from extensions.tasks import cwl_reminder as bridge
    from utils import manage_web_worker as worker

    async def run():
        blocked = asyncio.Event()
        entered = asyncio.Event()

        async def drive(*args):
            entered.set()
            await blocked.wait()

        call = AsyncMock(side_effect=drive)
        monkeypatch.setattr(worker, "fast_poll", call)
        monkeypatch.setattr(bridge, "bot_instance", object())
        monkeypatch.setattr(bridge, "mongo_client", object())
        monkeypatch.setattr(bridge, "_management_driver", None)
        monkeypatch.setattr(bridge, "startup_reconciler", None)
        monkeypatch.setattr(bridge, "scheduler", S(running=False))
        await bridge._poll_web_management_fast()
        await entered.wait()
        await bridge._poll_web_management_fast()
        await bridge._poll_web_management_fast()
        assert call.await_count == 1
        task = bridge._management_driver
        await bridge.on_bot_stopping(None)
        assert task.cancelled() and bridge._management_driver is None

    asyncio.run(run())


def test_cached_request_context_success_edits_once_after_preparation(
    monkeypatch,
):
    async def run():
        bot, _ = transport()
        actions._RUN_ENVIRONMENTS.clear()
        monkeypatch.setattr(
            dashboard_access, "dashboard_allowed", AsyncMock(return_value=True)
        )
        row = dict(
            _id="cached-success",
            parent_id="cached-parent",
            guild_id=GUILD,
            section="member_profiles",
            action="save",
            user_id=ACTOR,
            revision=1,
            values=dict(
                discord_id=UID,
                fields=dict(zone_id="gmt-5", country="US"),
                rename=True,
                name="Name",
                old_nickname="Old",
            ),
        )
        context = await actions.request_context(bot, None, row)
        written = []

        async def commit(*args, change, prepare, **kwargs):
            await prepare()
            await change()
            written.append(True)

        monkeypatch.setattr(
            actions, "MemberProfiles", lambda _: S(commit_after=commit)
        )
        result = await actions.apply(bot, None, row, request_context=context)
        assert written == [True]
        assert result["message"] == "Profile and nickname saved."
        bot.rest.edit_member.assert_awaited_once()
        assert (
            sum(
                c.args[1] == int(UID)
                for c in bot.rest.fetch_member.await_args_list
            )
            == 1
        )

    asyncio.run(run())
