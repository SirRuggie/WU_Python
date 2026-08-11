"""Keep a short /cards explainer pinned to the bottom of a channel.

Discord has no real sticky message, so the only way to keep a notice visible is
to delete it and post it again below whatever was said since. This does that on
a timer, but only when the notice has actually been buried: reposting a message
that is already last marks the channel unread and bumps it up everyone's sidebar
for no visible change, and push-notifies anyone set to All Messages.
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
# once and skipped rather than retried into a rate limit. NotFoundError is in
# here to match the other task modules; the one place it is survivable - a
# previous notice already deleted - catches it ahead of this tuple.
PERMANENT_DISCORD_ERRORS = (
    hikari.BadRequestError,
    hikari.UnauthorizedError,
    hikari.ForbiddenError,
    hikari.NotFoundError,
)

# "I could not find out", as distinct from "the channel is empty". Reposting on
# a failed read would repost every cycle for as long as the failure lasted.
UNKNOWN = object()

# A delete that fails transiently would otherwise leave a notice nothing tracks,
# and every later cycle would add another. Bounded so a permanently undeletable
# message cannot grow the document without limit.
MAX_PENDING_DELETES = 10

sticky_task = None
bot_instance = None
mongo_client = None


def _sticky_components() -> list[Container]:
    """The notice itself.

    One line saying what it is for, then one line per step. The DM is mentioned
    exactly once: saying it twice is what made earlier drafts read long, and
    "check your DMs" on its own leaves a first-timer waiting in the channel for
    something that is never going to appear there, so the line names who sends
    it.

    The family reads this in a dozen countries, so the wording stays plain:
    short sentences, no contractions in the instructions, no idioms, and
    "pictures" rather than "pics".
    """
    return [Container(
        accent_color=BLUE_ACCENT,
        components=[
            Text(content=(
                "## 🃏 Clash of Cards\n"
                "Run **`/cards`** — find family members who have the card "
                "you need."
            )),
            Separator(divider=True),
            Text(content=(
                "📸 **Scan screenshots** → **I will DM you** → send your "
                "collection pictures there\n"
                "✍️ Or add cards by hand — tap any card on the board\n"
                "🔁 **Find trades** → who has it, and what clan they are in\n"
                "🤝 Pick one → I send that player your offer"
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
    """Newest message id, None when the channel is empty, UNKNOWN on failure.

    Reads the channel rather than its messages. hikari's message iterator asks
    Discord for a 100-message page no matter what limit is applied afterwards,
    so `fetch_messages(...).limit(1)` downloads and deserializes a hundred
    messages every cycle to learn one snowflake.
    """
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except PERMANENT_DISCORD_ERRORS as exc:
        print(f"[Cards Sticky] cannot read #{channel_id}: {type(exc).__name__}: {exc}")
        return UNKNOWN
    except Exception as exc:
        print(f"[Cards Sticky] channel fetch failed: {type(exc).__name__}: {exc}")
        return UNKNOWN
    latest = getattr(channel, "last_message_id", None)
    return int(latest) if latest else None


async def _delete_previous(
    bot: hikari.GatewayBot, channel_id: int, message_id: int
) -> bool:
    """True when the message is gone, False when it is still owed a delete."""
    try:
        await bot.rest.delete_message(channel_id, message_id)
    except hikari.NotFoundError:
        # Someone already removed it. That is the state we wanted anyway.
        return True
    except PERMANENT_DISCORD_ERRORS as exc:
        # Nothing will make this succeed, so stop tracking it rather than
        # retrying the same failure every ten minutes forever.
        print(f"[Cards Sticky] could not delete {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return True
    except Exception as exc:
        print(f"[Cards Sticky] delete error {message_id}: {type(exc).__name__}: {exc}")
        return False
    return True


async def refresh_sticky() -> None:
    """Move the notice back to the bottom, if something has been said under it."""
    if not bot_instance or not mongo_client:
        print("[Cards Sticky] bot or MongoDB not initialized")
        return

    channel_id = int(STICKY_CHANNEL_ID)
    stored = await _stored_sticky(mongo_client)
    previous_id = stored.get("message_id")
    previous_channel = stored.get("channel_id")
    owed = [int(value) for value in (stored.get("pending_deletes") or ())]

    if previous_id and int(previous_channel or 0) == channel_id:
        newest = await _newest_message_id(bot_instance, channel_id)
        if newest is UNKNOWN:
            # Do not repost on a guess. If the channel cannot be read, posting
            # into it is unlikely to work either, and a wrong guess repeats
            # every cycle for as long as the failure lasts.
            return
        # The notice already sits at the bottom, so a repost achieves nothing.
        if newest is not None and newest == int(previous_id):
            await _drain_pending(owed, channel_id)
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

    # Record the new message, and hand the old one over as owed work, in the
    # same write. A crash between the two would otherwise leave a notice
    # nothing tracks, and every later cycle would add another.
    if previous_id:
        owed.append(int(previous_id))
    owed = owed[-MAX_PENDING_DELETES:]
    try:
        await mongo_client.bot_config.update_one(
            {"_id": CONFIG_ID},
            {"$set": {
                "channel_id": channel_id,
                "message_id": int(message.id),
                "posted_at": datetime.now(timezone.utc),
                "pending_deletes": owed,
            }},
            upsert=True,
        )
    except Exception as exc:
        print(f"[Cards Sticky] config write failed: {type(exc).__name__}: {exc}")

    await _drain_pending(owed, int(previous_channel or channel_id))


async def _drain_pending(owed: list[int], channel_id: int) -> None:
    """Delete every notice still owed one, keeping whatever would not go."""
    if not owed:
        return
    remaining = [
        message_id for message_id in owed
        if not await _delete_previous(bot_instance, channel_id, message_id)
    ]
    if remaining == owed:
        return
    try:
        await mongo_client.bot_config.update_one(
            {"_id": CONFIG_ID},
            {"$set": {"pending_deletes": remaining}},
        )
    except Exception as exc:
        print(f"[Cards Sticky] pending write failed: {type(exc).__name__}: {exc}")


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
