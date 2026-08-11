"""Keep a short /cards explainer pinned to the bottom of a channel.

Discord has no real sticky message, so the only way to keep a notice visible is
to delete it and post it again below whatever was said since. This does that on
a timer, but only when the notice has actually been buried: reposting an already
last message would churn the channel history and re-ping anyone who has it
unmuted, for no visible change.
"""

import asyncio
from datetime import datetime, timezone

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,  # noqa: F401 - kept for future controls
    LinkButtonBuilder as LinkButton,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from utils.constants import BLUE_ACCENT
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# The channel the notice lives in. Swapping this to the cards channel is a
# one-line change; the stored message id is keyed by channel, so the old notice
# in the previous channel is cleaned up on the next cycle.
STICKY_CHANNEL_ID = 947166650321494067
REPOST_INTERVAL_MINUTES = 10
CONFIG_ID = "cards_sticky_message"

COLLECTION_LINK = "https://link.clashofclans.com/en/?action=OpenCollection"

# Discord raises these for reasons a retry will never fix, so they are logged
# once and skipped rather than retried into a rate limit.
PERMANENT_DISCORD_ERRORS = (
    hikari.BadRequestError,
    hikari.UnauthorizedError,
    hikari.ForbiddenError,
)

sticky_task = None
bot_instance = None
mongo_client = None


def _sticky_components() -> list[Container]:
    """The notice itself.

    Three lines, one per path, and the DM told exactly once. Saying it twice is
    what made earlier drafts read long, and "check your DMs" on its own leaves a
    first-timer waiting in the channel for something that is never going to
    appear there - so the line names who sends it.
    """
    return [Container(
        accent_color=BLUE_ACCENT,
        components=[
            Text(content=(
                "## 🃏 Clash of Cards\n"
                "Run **`/cards`** — see your board, find your trades."
            )),
            Separator(divider=True),
            Text(content=(
                "📸 **Scan screenshots** → **I'll DM you** → drop your "
                "collection pics in that DM\n"
                "✍️ Skip the scan? Tap any card on the board and set it by hand\n"
                "🔁 **Find trades** → who's holding the cards you're missing"
            )),
            ActionRow(components=[
                LinkButton(url=COLLECTION_LINK, label="Open collection"),
            ]),
        ],
    )]


async def _stored_sticky(mongo: MongoClient) -> dict:
    try:
        return await mongo.bot_config.find_one({"_id": CONFIG_ID}) or {}
    except Exception as exc:
        print(f"[Cards Sticky] config read failed: {type(exc).__name__}: {exc}")
        return {}


async def _newest_message_id(bot: hikari.GatewayBot, channel_id: int):
    """The id of the latest message in the channel, or None if it can't be read."""
    try:
        latest = await bot.rest.fetch_messages(channel_id).limit(1)
    except PERMANENT_DISCORD_ERRORS as exc:
        print(f"[Cards Sticky] cannot read #{channel_id}: {type(exc).__name__}: {exc}")
        return None
    except Exception as exc:
        print(f"[Cards Sticky] message fetch failed: {type(exc).__name__}: {exc}")
        return None
    return int(latest[0].id) if latest else None


async def _delete_previous(bot: hikari.GatewayBot, channel_id: int, message_id: int):
    try:
        await bot.rest.delete_message(channel_id, message_id)
    except hikari.NotFoundError:
        # Someone already removed it. That is the state we wanted anyway.
        pass
    except PERMANENT_DISCORD_ERRORS as exc:
        print(f"[Cards Sticky] could not delete {message_id}: "
              f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        print(f"[Cards Sticky] delete error {message_id}: {type(exc).__name__}: {exc}")


async def refresh_sticky() -> None:
    """Move the notice back to the bottom, if something has been said under it."""
    if not bot_instance or not mongo_client:
        print("[Cards Sticky] bot or MongoDB not initialized")
        return

    channel_id = int(STICKY_CHANNEL_ID)
    stored = await _stored_sticky(mongo_client)
    previous_id = stored.get("message_id")
    previous_channel = stored.get("channel_id")

    # The notice already sits at the bottom of the same channel, so there is
    # nothing for a repost to achieve.
    if previous_id and int(previous_channel or 0) == channel_id:
        newest = await _newest_message_id(bot_instance, channel_id)
        if newest is not None and newest == int(previous_id):
            return

    try:
        message = await bot_instance.rest.create_message(
            channel=channel_id,
            components=_sticky_components(),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2,
        )
    except PERMANENT_DISCORD_ERRORS as exc:
        print(f"[Cards Sticky] cannot post in #{channel_id}: "
              f"{type(exc).__name__}: {exc}")
        return
    except Exception as exc:
        print(f"[Cards Sticky] post failed: {type(exc).__name__}: {exc}")
        return

    # Record the new message before removing the old one. A crash between the
    # two leaves one stale notice a human can delete; the other order would
    # leave a notice nothing tracks, and every cycle would add another.
    try:
        await mongo_client.bot_config.update_one(
            {"_id": CONFIG_ID},
            {"$set": {
                "channel_id": channel_id,
                "message_id": int(message.id),
                "posted_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as exc:
        print(f"[Cards Sticky] config write failed: {type(exc).__name__}: {exc}")

    if previous_id:
        await _delete_previous(
            bot_instance, int(previous_channel or channel_id), int(previous_id)
        )


async def sticky_loop() -> None:
    while True:
        try:
            await refresh_sticky()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[Cards Sticky] loop error: {type(exc).__name__}: {exc}")
        await asyncio.sleep(REPOST_INTERVAL_MINUTES * 60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global bot_instance, mongo_client, sticky_task

    bot_instance = bot
    mongo_client = mongo

    # Start exactly one loop. Two would each repost on their own timer, and the
    # channel would collect a stale notice every cycle.
    if sticky_task and not sticky_task.done():
        print("[Cards Sticky] task already running; start skipped")
        return
    sticky_task = asyncio.create_task(sticky_loop(), name="cards-sticky")
    print(f"[Cards Sticky] task started for #{STICKY_CHANNEL_ID} "
          f"every {REPOST_INTERVAL_MINUTES}m")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global sticky_task

    if sticky_task and not sticky_task.done():
        sticky_task.cancel()
        try:
            await sticky_task
        except asyncio.CancelledError:
            pass
        print("[Cards Sticky] task stopped")
