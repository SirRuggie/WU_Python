import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import content
from extensions.commands.setup import recruit_join_family as join_family
from extensions.components import registered_functions


GUILD_ID = join_family.JOIN_FAMILY_GUILD_ID
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
    return asyncio.run(join_family.on_join_family_acknowledge("any-published-id", ctx=ctx, bot=bot))


def test_join_family_renderer_and_editor_schema_are_stable():
    document = content.DOCUMENTS["join-family"]
    rendered = join_family.build_join_family(action_id="published")
    sections = [node.content for node in content.text_nodes(rendered)]

    assert len(sections) == 4
    assert content.editable_blocks(document, sections) == (
        (0, "Heading"), (1, "Welcome"), (2, "What happens next"), (3, "Call to action"),
    )
    assert content.media_slots(document) == (("welcome", "Welcome banner"),)
    button = rendered[-1].components[-1].components[0]
    assert button.custom_id == "join_family_acknowledge:published"

    preview = join_family.build_join_family(sections, preview=True)
    assert preview[-1].components[-1].components[0].is_disabled is True
    assert content.acknowledgement_setup("join-family") == (
        join_family.JOIN_FAMILY_ROLE_ID, join_family.ABOUT_US_CHANNEL_ID,
    )


def test_join_family_action_is_persistent_and_does_not_edit_public_post():
    action = registered_functions["join_family_acknowledge"]
    assert action.no_return is True
    assert action.preload_state is False


def test_join_family_grants_the_configured_role_after_rest_guild_check():
    ctx = _ctx()
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_channel.assert_awaited_once_with(join_family.ABOUT_US_CHANNEL_ID)
    bot.rest.add_role_to_member.assert_awaited_once_with(
        guild=GUILD_ID, user=USER_ID, role=join_family.JOIN_FAMILY_ROLE_ID,
    )
    sent = ctx.interaction.execute.await_args.kwargs
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
    assert sent["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
    assert any("welcome" in child.content.lower() for child in sent["components"][0].components if hasattr(child, "content"))
    button = sent["components"][0].components[-1].components[0]
    assert button.url == f"https://discord.com/channels/{GUILD_ID}/{join_family.ABOUT_US_CHANNEL_ID}"
    assert button.label == "Continue to About Us"


def test_join_family_refuses_a_panel_used_from_another_guild_before_granting():
    ctx = _ctx(guild_id=999)
    bot = _bot()

    _run(ctx, bot)

    bot.rest.fetch_member.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    assert "only be used" in ctx.interaction.execute.await_args.kwargs["content"]


def test_join_family_is_idempotent_for_existing_role():
    ctx = _ctx()
    bot = _bot(member_roles=(join_family.JOIN_FAMILY_ROLE_ID,))

    _run(ctx, bot)

    bot.rest.add_role_to_member.assert_not_awaited()
    assert any("already have" in child.content for child in ctx.interaction.execute.await_args.kwargs["components"][0].components if hasattr(child, "content"))


def test_join_family_role_grant_failure_is_private_and_keeps_public_post_unchanged():
    ctx = _ctx()
    bot = _bot()
    bot.rest.add_role_to_member.side_effect = RuntimeError("do not expose")

    _run(ctx, bot)

    sent = ctx.interaction.execute.await_args.kwargs
    assert "do not expose" not in sent["content"]
    assert "could not grant" in sent["content"]
    assert sent["flags"] & hikari.MessageFlag.EPHEMERAL
