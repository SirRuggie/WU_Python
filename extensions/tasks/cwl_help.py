"""Silent CWL signup-help stickies in the two member chat channels."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.tasks.sticky_transport import DiscordStickyTransport
from utils.constants import WU_GOLD
from utils.mongo import MongoClient
from utils.sticky_message import StickyMessage, StickyTarget, aware

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
GUILD_ID = 644963518025826315
CHANNEL_IDS = (801950200133976124, 872692009066958879)
COMMANDER_ROLE_ID = 1574854005417316483
CHECK_SECONDS = 60
STICKY_AFTER = timedelta(minutes=30)
BODY = (
    "If you need help with signing up for CWL or anything else about the event, "
    f"ask your question here. Ping <@&{COMMANDER_ROLE_ID}> and they will get with "
    "you as soon as possible."
)
STICKIES = {
    channel_id: StickyMessage(StickyTarget(GUILD_ID, channel_id), quiet=STICKY_AFTER)
    for channel_id in CHANNEL_IDS
}
_bot = None
_mongo = None
_task = None


def _sticky_components():
    return [Container(accent_color=WU_GOLD, components=[
        Text(content="### CWL Signup Help"),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=BODY),
    ])]


@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def on_help_message(event: hikari.GuildMessageCreateEvent,
                          mongo: MongoClient = lightbulb.di.INJECTED):
    if int(event.guild_id) != GUILD_ID or int(event.channel_id) not in STICKIES:
        return
    author = getattr(event.message, "author", None)
    if author is None or getattr(author, "is_bot", False):
        return
    # The event carries the destination; REST sweeps independently revalidate it.
    await STICKIES[int(event.channel_id)].note_human(
        mongo, aware(getattr(event.message, "created_at", None)) or datetime.now(timezone.utc),
    )


async def sweep_once(bot=None, mongo=None, *, now: datetime | None = None):
    bot, mongo = bot or _bot, mongo or _mongo
    now = now or datetime.now(timezone.utc)
    if bot is None or mongo is None:
        return
    for channel_id, sticky in STICKIES.items():
        try:
            transport = DiscordStickyTransport(bot, sticky.target, _sticky_components)
            if await transport.validated_channel() is None:
                continue
            await sticky.drain_pending(mongo, now)
            await sticky.drain_deletes(transport, mongo, now)
            await sticky.refresh(transport, mongo, now)
            await sticky.drain_deletes(transport, mongo, now)
        except Exception:
            # One unavailable channel does not stop the other channel's check.
            log.exception("CWL help sticky check failed for %s", channel_id)


async def _loop():
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        await asyncio.sleep(CHECK_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(event: hikari.StartedEvent,
                     bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                     mongo: MongoClient = lightbulb.di.INJECTED):
    global _bot, _mongo, _task
    _bot, _mongo = bot, mongo
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="cwl-help")


@loader.listener(hikari.StoppingEvent)
async def on_stopping(event: hikari.StoppingEvent):
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
