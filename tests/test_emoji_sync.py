"""Retired uploader and preserved troop emoji lookup cache."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import hikari

from extensions.commands import emoji_sync
from utils import troop_emoji
from utils.cards import CARDS


def test_uploader_is_retired_but_saved_registry_still_loads():
    assert not hasattr(emoji_sync, "EmojiSync")
    rows = [{"slug": "barbarian", "emoji_id": 123456789012345678, "name": "troop_barbarian"}]
    collection = SimpleNamespace(find=Mock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=rows))))
    try:
        assert asyncio.run(emoji_sync.refresh_cache(SimpleNamespace(emoji_registry=collection))) == 1
        collection.find.assert_called_once_with({"kind": "troop"})
        assert troop_emoji.markup("barbarian") == "<:troop_barbarian:123456789012345678>"
    finally:
        troop_emoji.clear()


def test_every_managed_name_is_a_legal_discord_emoji_name():
    for card in CARDS:
        name = troop_emoji.managed_name(card.id)
        assert troop_emoji.NAME_PATTERN.match(name), name
        assert 2 <= len(name) <= 32, name


def test_managed_names_cannot_collide_with_the_hand_curated_set():
    from utils.emoji import emojis

    hand = {
        str(value).split(":")[1]
        for value in vars(emojis).values()
        if str(value).startswith("<")
    }
    managed = {troop_emoji.managed_name(card.id) for card in CARDS}

    assert not (hand & managed)
    assert all(not name.startswith(troop_emoji.MANAGED_PREFIX) for name in hand)


def test_prime_skips_unusable_rows_without_raising():
    troop_emoji.clear()
    loaded = troop_emoji.prime([
        {"slug": "barbarian", "emoji_id": 123456789012345678, "name": "troop_barbarian"},
        {"slug": "archer", "emoji_id": 0, "name": "troop_archer"},          # bad id
        {"slug": "giant", "emoji_id": "nope", "name": "troop_giant"},        # unparseable
        {"slug": "goblin", "emoji_id": 1, "name": "bad name!"},              # illegal name
        {"emoji_id": 2, "name": "troop_nameless"},                           # no slug
    ])

    assert loaded == 1
    assert troop_emoji.markup("barbarian") == "<:troop_barbarian:123456789012345678>"
    assert isinstance(troop_emoji.partial("barbarian"), hikari.CustomEmoji)


def test_unknown_slug_degrades_to_text_and_never_raises():
    troop_emoji.clear()

    assert troop_emoji.markup("nope") == ""
    assert troop_emoji.markup("nope", "fallback") == "fallback"
    assert troop_emoji.partial("nope") is hikari.UNDEFINED


def test_prime_replaces_rather_than_merges():
    troop_emoji.clear()
    troop_emoji.prime([
        {"slug": "barbarian", "emoji_id": 111111111111111111, "name": "troop_barbarian"},
    ])
    troop_emoji.prime([
        {"slug": "archer", "emoji_id": 222222222222222222, "name": "troop_archer"},
    ])

    assert troop_emoji.markup("barbarian") == ""
    assert troop_emoji.known() == 1
