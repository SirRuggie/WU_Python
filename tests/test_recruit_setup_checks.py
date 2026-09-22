import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands.setup import setup
from extensions.commands.setup import (
    recruit_aboutus,
    recruit_check,
    recruit_familyparticulars,
    recruit_strikesystem,
)
from utils.recruit_setup_checks import (
    inspect_recruit_setup,
    require_manage_server,
    require_ready,
)


def _run(coro):
    return asyncio.run(coro)


def _role(role_id, position, permissions=hikari.Permissions.NONE, *, managed=False):
    return SimpleNamespace(
        id=role_id, position=position, permissions=permissions, is_managed=managed,
    )


def _ctx(*, app_permissions=None, channel_type=hikari.ChannelType.GUILD_TEXT, manage_server=True):
    permissions = hikari.Permissions.MANAGE_GUILD if manage_server else hikari.Permissions.NONE
    context = SimpleNamespace()
    context.interaction = SimpleNamespace(
        guild_id=1,
        app_permissions=(
            hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.ATTACH_FILES
            if app_permissions is None else app_permissions
        ),
        channel=SimpleNamespace(type=channel_type),
        member=SimpleNamespace(permissions=permissions),
    )
    context.responses = []

    async def respond(content=None, **kwargs):
        context.responses.append((content, kwargs))

    context.respond = respond
    context.deferred = []

    async def defer(**kwargs):
        context.deferred.append(kwargs)

    context.defer = defer
    return context


def _bot(*, roles=None, member=None, channel=None):
    roles = roles or (
        _role(1, 0),
        _role(100, 10, hikari.Permissions.MANAGE_ROLES),
        _role(200, 5),
    )
    rest = SimpleNamespace(
        fetch_roles=AsyncMock(return_value=roles),
        fetch_my_member=AsyncMock(return_value=member or SimpleNamespace(role_ids=(100,))),
        fetch_channel=AsyncMock(return_value=channel or SimpleNamespace(
            guild_id=1, type=hikari.ChannelType.GUILD_TEXT,
        )),
    )
    return SimpleNamespace(rest=rest)


def test_inspect_ready_uses_only_read_calls_and_includes_everyone_role():
    ctx = _ctx()
    bot = _bot()

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert check.ready
    assert bot.rest.fetch_roles.await_args.args == (1,)
    assert bot.rest.fetch_my_member.await_args.args == (1,)
    assert bot.rest.fetch_channel.await_args.args == (300,)
    assert set(vars(bot.rest)) == {"fetch_roles", "fetch_my_member", "fetch_channel"}


def test_inspect_administrator_does_not_bypass_role_hierarchy():
    ctx = _ctx()
    bot = _bot(roles=(
        _role(1, 0),
        _role(100, 5, hikari.Permissions.ADMINISTRATOR),
        _role(200, 10),
    ))

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert not check.ready
    assert check.issues == ("My highest role must be above the acknowledgement role.",)


def test_inspect_administrator_bypasses_current_channel_permission_bits():
    ctx = _ctx(app_permissions=hikari.Permissions.ADMINISTRATOR)
    bot = _bot()

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert check.ready


def test_inspect_administrator_still_rejects_a_forum_channel():
    ctx = _ctx(
        app_permissions=hikari.Permissions.ADMINISTRATOR,
        channel_type=hikari.ChannelType.GUILD_FORUM,
    )
    bot = _bot()

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert check.issues == (
        "Recruit posts can only be sent in a text, announcement, or thread channel.",
    )


def test_inspect_thread_requires_thread_send_not_parent_send():
    ctx = _ctx(
        app_permissions=(
            hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.SEND_MESSAGES_IN_THREADS
            | hikari.Permissions.ATTACH_FILES
        ),
        channel_type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
    )
    bot = _bot()

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert check.ready


def test_inspect_requires_attach_files_for_the_local_recruit_media():
    ctx = _ctx(app_permissions=(
        hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
    ))
    bot = _bot()

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert check.issues == ("I need Attach Files permission here.",)


def test_inspect_reports_missing_role_and_cross_guild_channel():
    ctx = _ctx()
    bot = _bot(channel=SimpleNamespace(guild_id=2, type=hikari.ChannelType.GUILD_TEXT))

    check = _run(inspect_recruit_setup(ctx, bot, role_id=999, next_channel_id=300))

    assert check.issues == (
        "The acknowledgement role is missing from this server.",
        "The next onboarding channel is not in this server.",
    )


def test_inspect_fails_closed_when_discord_rest_cannot_read_roles():
    ctx = _ctx()
    bot = _bot()
    bot.rest.fetch_roles = AsyncMock(side_effect=hikari.ForbiddenError(
        "https://discord.test", {}, {}, "Missing access",
    ))

    check = _run(inspect_recruit_setup(ctx, bot, role_id=200, next_channel_id=300))

    assert not check.ready
    assert check.issues == ("I could not read my server roles. Check my server access and try again.",)
    bot.rest.fetch_channel.assert_awaited_once_with(300)


def test_require_ready_replies_ephemerally_without_mutating_discord():
    ctx = _ctx(app_permissions=(
        hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.ATTACH_FILES
    ))
    bot = _bot()

    ready = _run(require_ready(ctx, bot, role_id=200, next_channel_id=300))

    assert ready is False
    assert ctx.responses == [(
        "I did not post the recruit panel because setup needs attention:\n- I need Send Messages permission here.",
        {"ephemeral": True},
    )]


def test_recruit_check_is_registered_and_denies_before_reading():
    ctx = _ctx(manage_server=False)
    bot = _bot()
    media = SimpleNamespace(configured=False)

    _run(recruit_check.RecruitCheck().invoke(ctx, bot, media))

    assert setup.subcommands["recruit-check"] is recruit_check.RecruitCheck
    assert ctx.responses == [(
        "You need Manage Server permission to use recruit setup.", {"ephemeral": True},
    )]
    bot.rest.fetch_roles.assert_not_awaited()
    bot.rest.fetch_my_member.assert_not_awaited()
    bot.rest.fetch_channel.assert_not_awaited()


def test_require_manage_server_denies_without_deferring_or_reading_bot_state():
    ctx = _ctx(manage_server=False)

    allowed = _run(require_manage_server(ctx))

    assert allowed is False
    assert ctx.deferred == []
    assert ctx.responses == [(
        "You need Manage Server permission to use recruit setup.", {"ephemeral": True},
    )]


def test_recruit_post_commands_deny_before_defer_storage_or_discord_reads():
    async def check():
        commands = (
            recruit_aboutus.RecruitAboutUs,
            recruit_strikesystem.RecruitStrikeSystem,
            recruit_familyparticulars.RecruitFamilyParticulars,
        )
        for command in commands:
            ctx = _ctx(manage_server=False)
            bot = _bot()
            bot.rest.create_message = AsyncMock()
            mongo = SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock()))

            await command().invoke(ctx, bot, mongo)

            assert ctx.deferred == []
            assert ctx.responses == [(
                "You need Manage Server permission to use recruit setup.", {"ephemeral": True},
            )]
            bot.rest.fetch_roles.assert_not_awaited()
            bot.rest.fetch_my_member.assert_not_awaited()
            bot.rest.fetch_channel.assert_not_awaited()
            bot.rest.create_message.assert_not_awaited()
            mongo.bot_config.find_one.assert_not_awaited()

    _run(check())


def test_recruit_check_panel_is_components_v2_and_reports_r2_status():
    ready = _run(inspect_recruit_setup(_ctx(), _bot(), role_id=200, next_channel_id=300))

    panel = recruit_check.check_panel((ready, ready, ready), media_configured=False)

    assert len(panel) == 1
    assert panel[0].type == hikari.ComponentType.CONTAINER
    text = "\n".join(item.content for item in panel[0].components)
    assert text.count("ready") == 3
    assert "R2 is not configured" in text


def test_recruit_check_returns_private_components_v2_result_after_reads():
    ctx = _ctx()
    bot = _bot()
    media = SimpleNamespace(configured=True)

    _run(recruit_check.RecruitCheck().invoke(ctx, bot, media))

    assert ctx.deferred == [{"ephemeral": True}]
    content, kwargs = ctx.responses[0]
    assert content is None
    assert kwargs["ephemeral"] is True
    assert kwargs["components"][0].type == hikari.ComponentType.CONTAINER
    assert bot.rest.fetch_roles.await_count == 3
    assert bot.rest.fetch_my_member.await_count == 3
    assert bot.rest.fetch_channel.await_count == 3
