"""Regression tests for component handlers that own their responses."""

import asyncio
from types import SimpleNamespace

import pytest

from extensions import components
from extensions.commands.clan import list as clan_list
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

    async def respond(self, **kwargs):
        self.responses.append(kwargs)


def _response_text(ctx):
    return str(ctx.responses[0]["components"][0].build())


def test_clan_list_missing_selection_edits_deferred_response():
    ctx = _Context()
    member = SimpleNamespace(id=2)
    bot = SimpleNamespace(rest=SimpleNamespace(
        fetch_member=lambda *_args: _async_value(member)
    ))

    result = asyncio.run(clan_list.on_clan_chosen(
        "state_2", bot=bot, coc_client=object(), mongo=_Mongo(None), ctx=ctx
    ))

    assert result is None
    assert len(ctx.responses) == 1
    assert ctx.responses[0]["edit"] is True
    assert "couldn’t find that clan" in _response_text(ctx)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (None, "Clan not found"),
        ({"tag": "#NOLOGO", "name": "No Logo", "emoji": ""}, "No Logo Found"),
    ],
)
def test_cloudinary_emoji_errors_edit_deferred_response(document, message):
    ctx = _Context("#NOLOGO")

    result = asyncio.run(update_clan_info.emoji_from_cloudinary(
        ctx=ctx, action_id="#NOLOGO", mongo=_Mongo(document), bot=object()
    ))

    assert result is None
    assert len(ctx.responses) == 1
    assert ctx.responses[0]["edit"] is True
    assert message in _response_text(ctx)


def test_handlers_still_own_success_responses():
    assert components.registered_functions["clan_select_menu"].no_return is True
    assert components.registered_functions["emoji_from_cloudinary"].no_return is True


async def _async_value(value):
    return value
