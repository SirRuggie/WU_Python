"""Keep a short /cards explainer pinned to the bottom of a channel.

Discord has no real sticky message, so the only way to keep a notice visible is
to delete it and post it again below whatever was said since. This does that on
a timer, but only when the notice has actually been buried: reposting a message
that is already last marks the channel unread and bumps it up everyone's sidebar
for no visible change. It posts silently, so no repost ever notifies anyone.
"""

import asyncio
import hashlib
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
from utils.emoji import emojis
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# The channel the notice lives in. Swapping this to the cards channel is a
# one-line change; the stored message id is keyed by channel, so the old notice
# in the previous channel is cleaned up on the next cycle.
STICKY_CHANNEL_ID = 1533915865441894430
REPOST_INTERVAL_MINUTES = 10
CONFIG_ID = "cards_sticky_message"

COLLECTION_LINK = "https://link.clashofclans.com/en/?action=OpenCollection"

# Who to ask about the command. Rendered as a mention so it is tappable, but
# posted with user_mentions=False: this message reposts all day, and a real
# mention would notify them every single time.
SUPPORT_USER_ID = 505227988229554179

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
    """The notice itself, as three numbered steps.

    Somebody read the previous version and still asked how to send a trade,
    because it described what the feature is rather than which buttons to
    press in what order. Each step is now its own block with its own heading,
    separated by real gaps, and every bold phrase is the exact label on the
    button - so a reader can match the words to the screen.

    The emoji are the ones the command itself uses, so the mark beside a step
    is the mark on the button it is telling you to press. Where the command
    has no matching emoji (entering cards by hand), the line carries none
    rather than an invented one.

    The family reads this in a dozen countries, so the wording stays plain:
    short sentences, no contractions in the instructions, no idioms, and
    "pictures" rather than "pics".
    """
    return [Container(
        accent_color=BLUE_ACCENT,
        components=[
            Text(content=(
                "## 🃏 Clash of Cards\n"
                "Find family members who have the card you need, and trade "
                "for it."
            )),
            Separator(divider=True),
            Text(content=(
                f"**1 · Add your cards**\n"
                f"{emojis.scan} Run **`/cards`** and tap **Scan screenshots**\n"
                f"{emojis.inbox} I will DM you — send your collection pictures "
                "in that DM"
            )),
            Text(content=(
                "-# No screenshots? Tap any card on the board and set the "
                "number by hand."
            )),
            Separator(divider=False),
            Text(content=(
                f"**2 · See who has it**\n"
                f"{emojis.magnifier} Tap **Find trades**, then pick the card "
                "you need\n"
                "You will see who has a spare and which clan they are in"
            )),
            Separator(divider=False),
            Text(content=(
                f"**3 · Send the offer**\n"
                f"{emojis.card_swap} Tap **Ask to swap**, then choose the card "
                "you give\n"
                f"{emojis.yes} They get a DM and tap **Accept**"
            )),
            Separator(divider=False),
            Text(content=(
                "-# You must both be in the same clan to send the cards in "
                "game."
            )),
            Separator(divider=True),
            ActionRow(components=[
                LinkButton(url=COLLECTION_LINK, label="Open collection"),
            ]),
            Separator(divider=True),
            # `-#` only renders small at the very start of a line, so this note
            # has to be its own text node rather than tacked onto the one above.
            Text(content=(
                f"-# Any problems or requests for this command? "
                f"Message <@{SUPPORT_USER_ID}>"
            )),
        ],
    )]


def _content_key() -> str:
    """Fingerprint of the wording, so a reworded notice can be spotted.

    Burial is not the only reason to act. Without this, editing the text and
    restarting changed nothing in a quiet channel: the notice was still the
    newest message, so the burial check returned early and the old wording sat
    there until somebody happened to talk.
    """
    text = "\x00".join(
        node.content
        for container in _sticky_components()
        for node in container.components
        if hasattr(node, "content")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _rewrite_in_place(
    bot: hikari.GatewayBot, channel_id: int, message_id: int
) -> bool:
    """Edit the standing notice. Cheaper than a repost and does not move it."""
    try:
        await bot.rest.edit_message(
            channel=channel_id,
            message=message_id,
            components=_sticky_components(),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
    except Exception as exc:
        print(f"[Cards Sticky] edit failed {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False
    return True


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
        # The notice already sits at the bottom, so a repost achieves nothing -
        # unless the wording changed, in which case edit it where it stands.
        if newest is not None and newest == int(previous_id):
            if stored.get("content_key") != _content_key():
                if await _rewrite_in_place(
                    bot_instance, channel_id, int(previous_id)
                ):
                    await _remember_content_key(_content_key())
            await _drain_pending(owed, channel_id)
            return

    try:
        message = await bot_instance.rest.create_message(
            channel=channel_id,
            components=_sticky_components(),
            # Two separate controls, both needed. allowed_mentions below stops
            # the support mention pinging that one person; SUPPRESS_NOTIFICATIONS
            # is the "silent message" flag, which stops the post itself
            # notifying everyone watching the channel. A notice that reposts all
            # day should do neither.
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
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
                "content_key": _content_key(),
            }},
            upsert=True,
        )
    except Exception as exc:
        print(f"[Cards Sticky] config write failed: {type(exc).__name__}: {exc}")

    await _drain_pending(owed, int(previous_channel or channel_id))


async def _remember_content_key(key: str) -> None:
    try:
        await mongo_client.bot_config.update_one(
            {"_id": CONFIG_ID}, {"$set": {"content_key": key}}
        )
    except Exception as exc:
        print(f"[Cards Sticky] key write failed: {type(exc).__name__}: {exc}")


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
