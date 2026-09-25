import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import content
from extensions.commands.setup import recruit_familyparticulars as family_particulars
from extensions.components import registered_functions


GUILD_ID = family_particulars.FAMILY_PARTICULARS_GUILD_ID
USER_ID = 1234


def _ctx(guild_id=GUILD_ID):
    interaction = SimpleNamespace(guild_id=guild_id, execute=AsyncMock())
    return SimpleNamespace(user=SimpleNamespace(id=USER_ID), interaction=interaction)


def _bot(*, member_roles=(), target_guild=GUILD_ID):
    rest = SimpleNamespace(
        fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=target_guild)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(role_ids=member_roles)),
        add_role_to_member=AsyncMock(),
    )
    return SimpleNamespace(rest=rest)


def _run(ctx, bot):
    mongo = SimpleNamespace(bot_config=SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0)),
        insert_one=AsyncMock(),
    ))
    return asyncio.run(family_particulars.on_familyparticulars_acknowledge("published-id", ctx=ctx, bot=bot, mongo=mongo))


def test_family_particulars_default_copy_and_target_are_updated():
    parts = family_particulars.build_familyparticulars()
    acknowledgement = content.text_nodes(parts)[-1].content
    assert "Click **I understand - Continue**" in acknowledgement
    assert "Reacting" not in acknowledgement
    assert "open an application ticket" in acknowledgement
    assert "Choose only one application ticket option." in acknowledgement
    assert family_particulars.CLAN_RULES_READ_ROLE_ID == 1553110621711634502
    assert family_particulars.APPLY_HERE_CHANNEL_ID == 1547242779711766528
    assert len(content.text_nodes(parts)) == 28


def test_family_particulars_action_is_stateless_and_persistent():
    action = registered_functions["familyparticulars_acknowledge"]
    assert action.no_return is True
    assert action.preload_state is False


def test_family_particulars_grants_role_after_rest_guild_check():
    ctx = _ctx()
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_channel.assert_awaited_once_with(family_particulars.APPLY_HERE_CHANNEL_ID)
    bot.rest.fetch_member.assert_awaited_once_with(GUILD_ID, USER_ID)
    bot.rest.add_role_to_member.assert_awaited_once_with(
        guild=GUILD_ID, user=USER_ID, role=family_particulars.CLAN_RULES_READ_ROLE_ID,
    )
    sent = ctx.interaction.execute.await_args.kwargs
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
    assert sent["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
    button = sent["components"][0].components[-1].components[0]
    assert button.url == f"https://discord.com/channels/{GUILD_ID}/{family_particulars.APPLY_HERE_CHANNEL_ID}"
    assert button.label == "Continue to Apply"


def test_family_particulars_refuses_another_interaction_guild_before_member_lookup():
    ctx = _ctx(guild_id=999)
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_member.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    assert "only be used" in ctx.interaction.execute.await_args.kwargs["content"]


def test_family_particulars_refuses_target_channel_in_another_guild():
    ctx = _ctx()
    bot = _bot(target_guild=999)

    _run(ctx, bot)

    bot.rest.fetch_member.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    assert "only be used" in ctx.interaction.execute.await_args.kwargs["content"]


def test_family_particulars_is_idempotent_for_existing_role():
    ctx = _ctx()
    bot = _bot(member_roles=(family_particulars.CLAN_RULES_READ_ROLE_ID,))

    _run(ctx, bot)

    bot.rest.add_role_to_member.assert_not_awaited()
    sent = ctx.interaction.execute.await_args.kwargs
    assert sent["components"]
    assert "accepted" not in str(sent["components"]).lower()


def test_family_particulars_member_fetch_failure_is_private_and_does_not_grant():
    ctx = _ctx()
    bot = _bot()
    bot.rest.fetch_member.side_effect = RuntimeError("do not expose")

    _run(ctx, bot)

    bot.rest.add_role_to_member.assert_not_awaited()
    sent = ctx.interaction.execute.await_args.kwargs
    assert "do not expose" not in sent["content"]
    assert "could not verify" in sent["content"]
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL


def test_family_particulars_role_grant_failure_is_private_and_keeps_public_post_unchanged():
    ctx = _ctx()
    bot = _bot()
    bot.rest.add_role_to_member.side_effect = RuntimeError("do not expose")

    _run(ctx, bot)

    sent = ctx.interaction.execute.await_args.kwargs
    assert "do not expose" not in sent["content"]
    assert "could not grant" in sent["content"]
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
