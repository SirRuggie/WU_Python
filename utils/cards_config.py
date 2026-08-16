"""Where the Card Hub lives: one guild id, one channel id, read from the env.

Two modules need the channel: `extensions/commands/cards.py` posts trades into
it, and `extensions/tasks/cards_sticky.py` keeps its explainer pinned to the
bottom of it. They used to disagree - the command read `CARDS_CHANNEL_ID` and
the task carried a hardcoded snowflake - so the notice telling members how to
trade could sit in a different channel from the trades themselves.

This module is the single answer, and it is deliberately the smallest thing
that can be one: standard library only, no `hikari`, no `mongo`, no import of
anything under `extensions/`. `utils/` never imports `extensions/`, so a
`utils` module can be imported by both a command and a task with no risk of a
cycle. Keep it that way - the moment this file needs a Discord object, it
belongs somewhere else.
"""

from __future__ import annotations

import os

# The channel the sticky notice has always been posted to, and now the trade
# board as well. It is a fallback rather than the only source, so an operator
# can still move the hub with an environment variable - but an unset variable
# no longer silently disables channel posting, which is what a plain
# `os.getenv` returning None used to mean.
CARDS_CHANNEL_FALLBACK = 1533915865441894430


def parse_snowflake_env(name: str) -> int | None:
    """A Discord id from the environment, or None when it is not one.

    Anything unparseable is None rather than an exception: a bad value in the
    environment must fail closed at the feature, not stop the bot booting.
    """
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value < 2**64 else None


def cards_guild_id() -> int | None:
    """The one Discord family allowed to own card inventory data.

    No fallback. This is the authority boundary for every collection and every
    trade, so an unset or malformed value has to disable the feature rather
    than guess at a server.
    """
    return parse_snowflake_env("CARDS_GUILD_ID")


def cards_channel_id() -> int:
    """The shared trade board, which is also the sticky notice's channel."""
    return parse_snowflake_env("CARDS_CHANNEL_ID") or CARDS_CHANNEL_FALLBACK
