"""Approved application-emoji size error without changing the REST path."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import steal


def test_oversized_emoji_response_uses_approved_copy(monkeypatch):
    emoji = hikari.CustomEmoji(id=123, name='sample', is_animated=False)
    monkeypatch.setattr(hikari.emojis.Emoji, 'parse', lambda _value: emoji)
    monkeypatch.setattr(hikari.CustomEmoji, 'read', AsyncMock(return_value=b'image'))
    error = hikari.BadRequestError('https://discord.test', {}, b'', 'File cannot be larger than 256KB')
    rest = SimpleNamespace(
        fetch_my_user=AsyncMock(return_value=SimpleNamespace(id=1)),
        fetch_application_emojis=AsyncMock(return_value=[]),
        create_application_emoji=AsyncMock(side_effect=error),
    )
    ctx = SimpleNamespace(defer=AsyncMock(), respond=AsyncMock())
    command = SimpleNamespace(emoji='<:sample:123>', new_name=None, compress=False)
    asyncio.run(steal.StealEmoji.invoke(command, ctx, SimpleNamespace(rest=rest)))
    rest.create_application_emoji.assert_awaited_once()
    ctx.respond.assert_awaited_once_with('❌ The emoji is larger than 256KB. Use the command again with `compress: True`.')
