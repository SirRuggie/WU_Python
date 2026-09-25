import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import content
from extensions.commands.setup import recruit_strikesystem as strike_system
from extensions.components import registered_functions


GUILD_ID = strike_system.STRIKE_SYSTEM_GUILD_ID
USER_ID = 1234


def _ctx(guild_id=GUILD_ID):
    interaction = SimpleNamespace(guild_id=guild_id, execute=AsyncMock())
    return SimpleNamespace(user=SimpleNamespace(id=USER_ID), interaction=interaction)


def _bot(*, member_roles=(), target_guild=GUILD_ID, cache_member=None):
    rest = SimpleNamespace(
        fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=target_guild)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(role_ids=member_roles)),
        add_role_to_member=AsyncMock(),
    )
    cache = SimpleNamespace(get_member=lambda _guild_id, _user_id: cache_member)
    return SimpleNamespace(rest=rest, cache=cache)


def _run(ctx, bot):
    mongo = SimpleNamespace(bot_config=SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0)),
        insert_one=AsyncMock(),
    ))
    return asyncio.run(strike_system.on_strikesystem_acknowledge("any-published-id", ctx=ctx, bot=bot, mongo=mongo))


def test_strikesystem_next_step_and_target_are_updated():
    parts = strike_system.build_strikesystem()
    text = content.text_nodes(parts)[-1].content
    assert "Choose **I understand - Continue**" in text
    assert "https://" not in text
    assert text == "Choose **I understand - Continue** to confirm you have read and agree to follow the Warriors United Strike System, then continue to Family Particulars for the next Recruit Gauntlet step."
    assert strike_system.STRIKE_SYSTEM_ROLE_ID == 1553110508746448956
    assert strike_system.FAMILY_PARTICULARS_CHANNEL_ID == 1547242699873325116


def test_strikesystem_action_is_persistent_and_does_not_edit_public_post():
    action = registered_functions["strikesystem_acknowledge"]
    assert action.no_return is True
    assert action.preload_state is False


def test_strikesystem_grants_the_configured_role_after_rest_guild_check():
    ctx = _ctx()
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_channel.assert_awaited_once_with(strike_system.FAMILY_PARTICULARS_CHANNEL_ID)
    bot.rest.add_role_to_member.assert_awaited_once_with(
        guild=GUILD_ID, user=USER_ID, role=strike_system.STRIKE_SYSTEM_ROLE_ID,
    )
    sent = ctx.interaction.execute.await_args.kwargs
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
    assert sent["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
    assert any("Next step unlocked" in child.content for child in sent["components"][0].components if hasattr(child, "content"))
    button = sent["components"][0].components[-1].components[0]
    assert button.url == f"https://discord.com/channels/{GUILD_ID}/{strike_system.FAMILY_PARTICULARS_CHANNEL_ID}"
    assert button.label == "Continue to Family Particulars"


def test_strikesystem_refuses_a_panel_used_from_another_guild_before_granting():
    ctx = _ctx(guild_id=999)
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_member.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    assert "only be used" in ctx.interaction.execute.await_args.kwargs["content"]


def test_strikesystem_is_idempotent_for_existing_role():
    ctx = _ctx()
    bot = _bot(member_roles=(strike_system.STRIKE_SYSTEM_ROLE_ID,))

    _run(ctx, bot)

    bot.rest.add_role_to_member.assert_not_awaited()
    assert any("already have" in child.content for child in ctx.interaction.execute.await_args.kwargs["components"][0].components if hasattr(child, "content"))


def test_strikesystem_role_grant_failure_is_private_and_keeps_public_post_unchanged():
    ctx = _ctx()
    bot = _bot()
    bot.rest.add_role_to_member.side_effect = RuntimeError("do not expose")

    _run(ctx, bot)

    sent = ctx.interaction.execute.await_args.kwargs
    assert "do not expose" not in sent["content"]
    assert "could not grant" in sent["content"]
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
