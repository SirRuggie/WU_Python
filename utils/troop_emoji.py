"""Troop slug to application-emoji lookup.

Application emojis belong to the bot rather than to a guild, so one upload is
usable in every server the bot is in.  The name to id map lives in Mongo
because the sync command runs in production and cannot commit a generated
module; reads never touch Mongo, because the cache is primed once at startup
and again after each sync.

This module deliberately never raises.  `utils/emoji.py`'s `partial_emoji`
raises `ValueError` on a malformed id, which is a live way to take a whole
panel down, so every accessor here degrades to plain text instead.
"""

from __future__ import annotations

import re

import hikari

# Discord allows 2-32 characters of letters, numbers and underscores.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,32}$")
MANAGED_PREFIX = "troop_"

_MARKUP: dict[str, str] = {}
_PARTIAL: dict[str, hikari.CustomEmoji] = {}


def managed_name(slug: str) -> str:
    """The emoji name this bot owns for a troop slug."""
    return f"{MANAGED_PREFIX}{slug}"


def prime(rows) -> int:
    """Replace the cache from registry documents; return how many are usable.

    An unusable row is skipped rather than raising, so one bad document cannot
    prevent every other troop emoji from rendering.
    """
    markup: dict[str, str] = {}
    partial: dict[str, hikari.CustomEmoji] = {}
    for row in rows or ():
        try:
            slug = str(row["slug"])
            emoji_id = int(row["emoji_id"])
            name = str(row["name"])
        except (KeyError, TypeError, ValueError):
            continue
        if emoji_id <= 0 or not NAME_PATTERN.match(name):
            continue
        markup[slug] = f"<:{name}:{emoji_id}>"
        try:
            partial[slug] = hikari.CustomEmoji(
                name=name,
                id=hikari.Snowflake(emoji_id),
                is_animated=False,
            )
        except (TypeError, ValueError):
            continue
    _MARKUP.clear()
    _MARKUP.update(markup)
    _PARTIAL.clear()
    _PARTIAL.update(partial)
    return len(_MARKUP)


def markup(slug: str, default: str = "") -> str:
    """Inline `<:name:id>` markup for a slug, or `default` if unknown."""
    return _MARKUP.get(str(slug), default)


def partial(slug: str):
    """A CustomEmoji for a component's `emoji=` field, or UNDEFINED."""
    return _PARTIAL.get(str(slug), hikari.UNDEFINED)


def known() -> int:
    return len(_MARKUP)


def clear() -> None:
    _MARKUP.clear()
    _PARTIAL.clear()
