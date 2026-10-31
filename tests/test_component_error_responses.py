"""Regression tests for component handlers that own their responses."""

import asyncio
from types import SimpleNamespace

import pytest

from extensions import components
from extensions.commands.clan.dashboard import update_clan_info


class _Clans:
    def __init__(self, document):
        self.document = document

    async def find_one(self, query):
        return self.document


class _Mongo:
    def __init__(self, document):
        self.clans = _Clans(document)


class _Context:
    def __init__(self, tag="#MISSING"):
        self.guild_id = 1
        self.interaction = SimpleNamespace(values=[tag])
        self.responses = []

    async def respond(self, *args, **kwargs):
        self.responses.append({"content": args[0] if args else "", **kwargs})


def _response_text(ctx):
    return ctx.responses[0]["content"]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (None, "no longer in the family directory"),
        ({"tag": "#NOLOGO", "name": "No Logo", "emoji": ""}, "Logo: Not set"),
    ],
)
def test_old_emoji_controls_redirect_without_creating_emoji(document, message):
    ctx = _Context("#NOLOGO")
    ctx.member = SimpleNamespace(get_roles=lambda: [
        SimpleNamespace(id=update_clan_info.CLAN_MANAGEMENT_ROLE_ID)
    ])

    result = asyncio.run(update_clan_info.emoji_from_logo(
        ctx=ctx, action_id="#NOLOGO", mongo=_Mongo(document), bot=object()
    ))

    assert result is None
    assert len(ctx.responses) == 1
    assert ctx.responses[0]["ephemeral"] is True
    assert message in _response_text(ctx)


def test_handlers_still_own_success_responses():
    assert components.registered_functions["emoji_from_logo"].no_return is True
