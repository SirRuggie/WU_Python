"""Discord adapter for shared durable help stickies (no loader of its own)."""

from __future__ import annotations

import hikari

from utils.sticky_message import aware


class DiscordStickyTransport:
    def __init__(self, bot, target, components, *, history_reader=None, history_limit=1000):
        self.bot = bot
        self.target = target
        self.components = components
        self.history_reader = history_reader
        self.history_limit = history_limit

    async def validated_channel(self):
        channel = await self.bot.rest.fetch_channel(self.target.channel_id)
        if (int(getattr(channel, "id", 0)) != self.target.channel_id
                or int(getattr(channel, "guild_id", 0)) != self.target.guild_id):
            return None
        return channel

    async def latest_human_at(self):
        if self.history_reader is not None:
            return await self.history_reader(self.bot, self.target.channel_id)
        # CWL may have missed gateway events during downtime. Let Hikari page
        # beyond one 100-message response; if our bound is exhausted without a
        # human, quiet is unknown and refresh must fail closed. Gauntlet keeps
        # its injected legacy history reader unchanged.
        seen = 0
        async for message in self.bot.rest.fetch_messages(self.target.channel_id).limit(self.history_limit):
            seen += 1
            author = getattr(message, "author", None)
            if author is None:
                raise ValueError("Message author unavailable; human quiet is unknown")
            if not getattr(author, "is_bot", False):
                at = aware(getattr(message, "created_at", None))
                if at is None:
                    raise ValueError("Human message has no usable creation time")
                return at
        if seen >= self.history_limit:
            raise RuntimeError("Sticky human history bound exhausted; quiet is unknown")
        return None

    async def message_exists(self, message_id: int) -> bool:
        try:
            await self.bot.rest.fetch_message(self.target.channel_id, message_id)
        except hikari.NotFoundError:
            return False
        return True

    async def create(self):
        if await self.validated_channel() is None:
            raise ValueError("Sticky channel ownership changed")
        return await self.bot.rest.create_message(
            channel=self.target.channel_id, components=self.components(),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )

    async def delete(self, message_id: int) -> None:
        if await self.validated_channel() is None:
            raise ValueError("Sticky channel ownership changed")
        try:
            await self.bot.rest.delete_message(self.target.channel_id, message_id)
        except hikari.NotFoundError:
            pass
