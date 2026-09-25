"""Load existing troop emojis at startup; the /emoji-sync uploader is retired.

Existing application emojis and registry rows remain available to displays.
This extension performs no emoji uploads, replacements, or deletions.
"""
from __future__ import annotations

import hikari
import lightbulb

from utils import troop_emoji
from utils.mongo import MongoClient

loader = lightbulb.Loader()


async def refresh_cache(mongo: MongoClient) -> int:
    rows = await mongo.emoji_registry.find({"kind": "troop"}).to_list(length=None)
    return troop_emoji.prime(rows)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def _prime_troop_emojis(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    try:
        loaded = await refresh_cache(mongo)
    except Exception as exc:  # noqa: BLE001 - never block startup on a cache
        print(f"[EmojiSync] could not prime troop emojis: {exc}")
        return
    print(f"[EmojiSync] primed {loaded} troop emojis")
