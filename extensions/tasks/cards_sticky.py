"""Keep a short /cards explainer pinned to the bottom of a channel.

Discord has no real sticky message, so the only way to keep a notice visible is
to delete it and post it again below whatever was said since.

Three things have to be true before it moves. The notice has to be buried -
reposting one that is already last marks the channel unread for no visible
change. Enough time has to have passed since the last repost. And the channel
has to have been quiet for a few minutes, because dropping the notice into a
live conversation every ten minutes was worse than it being buried. The loop
looks every minute so it can post shortly after people stop talking rather than
on the next multiple of ten. It posts silently, so no repost ever notifies
anyone.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    InteractiveButtonBuilder as Button,  # noqa: F401 - kept for future controls
    LinkButtonBuilder as LinkButton,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from utils import cards_config
from utils.constants import BLUE_ACCENT
from utils.emoji import emojis
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# The channel the notice lives in, which is now also the trade board's channel.
# Resolved from utils/cards_config.py so the notice telling members how to
# trade can never end up in a different channel from the trades themselves.
# The stored message id is keyed by channel, so if this resolves somewhere new
# the old notice is cleaned up on the next cycle.
STICKY_CHANNEL_ID = cards_config.cards_channel_id()
# The shortest gap between two reposts. Not how often the loop looks: it wakes
# every minute so that it can post soon after a conversation ends rather than
# on the next multiple of ten.
REPOST_INTERVAL_MINUTES = 10
# How long the channel has to be silent first. Reposting into a live
# conversation pushed the notice between people mid-sentence every ten minutes,
# which is the single most irritating thing this task did.
QUIET_PERIOD_MINUTES = 5
CHECK_INTERVAL_SECONDS = 60
CONFIG_ID = "cards_sticky_message"

COLLECTION_LINK = "https://link.clashofclans.com/en/?action=OpenCollection"

# Re-uploaded on every repost, so it is stored at the size Discord actually
# renders rather than the 1536px original: 157KB instead of 1.8MB.
STICKY_BANNER = "assets/cards/sticky_banner.jpg"

# Who to ask about the command. Rendered as a mention so it is tappable, but
# posted with user_mentions=False: this message reposts all day, and a real
# mention would notify them every single time.
SUPPORT_USER_ID = 505227988229554179

# Discord has no button that runs a slash command - a button can only send an
# interaction back to us. `</cards:id>` is the closest thing: a blue chip that
# opens the command when tapped. It needs the live command id, which only
# exists after the client syncs, so it is looked up once at startup and falls
# back to plain text if that lookup fails.
_cards_mention = "`/cards`"


def cards_mention() -> str:
    return _cards_mention


async def _learn_cards_mention(bot: hikari.GatewayBot) -> None:
    global _cards_mention
    try:
        application = await bot.rest.fetch_application()
        commands = await bot.rest.fetch_application_commands(application.id)
    except Exception as exc:
        print(f"[Cards Sticky] command id lookup failed: "
              f"{type(exc).__name__}: {exc}")
        return
    for command in commands:
        if getattr(command, "name", None) == "cards":
            _cards_mention = f"</cards:{int(command.id)}>"
            print(f"[Cards Sticky] /cards mention ready: {_cards_mention}")
            return
    print("[Cards Sticky] /cards command not found; using plain text")

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
            # Full width, above everything. An emoji cannot carry this art at
            # 22px, and the notice is the one place in the whole command where
            # the vertical space is worth spending.
            Media(items=[MediaItem(media=STICKY_BANNER)]),
            # No title here: the banner above already says CLASH OF CARDS, and
            # a heading repeating it put the same words on screen twice.
            Text(content=(
                "Find family members who have the card you need, and trade "
                "for it."
            )),
            Separator(divider=True),
            Text(content=(
                f"**1 · Add your cards**\n"
                f"{emojis.scan} Tap {cards_mention()}, tap "
                "**Update collection**, then **Scan screenshots**\n"
                f"{emojis.inbox} I will DM you — send your collection "
                "pictures there"
            )),
            Text(content=(
                "-# No screenshots? Tap **Update collection** and set each "
                "number by hand."
            )),
            Separator(divider=False),
            Text(content=(
                f"**2 · See who has it**\n"
                f"{emojis.magnifier} Tap **Find trades**, then pick the card "
                "you need\n"
                "You will see who has a spare and which clan they are in"
            )),
            Text(content=(
                "-# Nobody has it? Tap **Post a request** and it waits here "
                "in this channel."
            )),
            Separator(divider=False),
            Text(content=(
                f"**3 · Send the offer**\n"
                f"{emojis.card_swap} Tap **Ask to swap**, then choose the card "
                "you give\n"
                f"{emojis.yes} They get pinged here and tap **Accept**"
            )),
            Separator(divider=False),
            # This was a footnote hanging off step 3, which left the numbered
            # list ending at "they accept" - and accepting is not the trade.
            # The same fact as a step tells you what to do next instead.
            Text(content=(
                f"**4 · Send the cards**\n"
                f"{emojis.card_give} Same clan, then trade in game\n"
                f"{emojis.yes} Then tap **Yes, I sent it**"
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id="cards_help:sticky",
                    label="I am lost",
                    emoji="🙋",
                ),
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


def _walkthrough() -> list[Container]:
    """Every tap, in order, for somebody who is stuck.

    The sticky itself has to stay short enough that people read it, which
    means it cannot also be a manual. This is the manual: one numbered step
    per tap, each naming the exact button label, so a reader can match the
    words to what is on their screen. It is only ever shown to the one person
    who asked for it, so length costs nobody anything.
    """
    return [Container(
        accent_color=BLUE_ACCENT,
        components=[
            Text(content="## 🙋 How to trade a card"),
            Text(content="-# Only you can see this."),
            Separator(divider=True),
            Text(content=(
                "### First time only\n"
                f"**1.** Tap {cards_mention()} to open it\n\n"
                f"**2.** Tap **Update collection**, then **Scan screenshots** "
                f"{emojis.scan}\n"
                f"{emojis.inbox} I send you a DM. Open it and send your "
                "collection pictures there.\n"
                "-# No screenshots? Stay on **Update collection** and set each "
                "number by hand instead."
            )),
            Separator(divider=False),
            Text(content=(
                "### Every trade\n"
                f"**3.** Tap **Find trades** {emojis.magnifier}\n\n"
                "**4.** Open the menu for the category you want, and pick "
                "the card you need\n"
                "You will see who has a spare, and which clan they are in\n\n"
                "**5.** Tap **Ask to swap** next to the person you want\n\n"
                "**6.** Choose which of your spare cards to give\n\n"
                f"**7.** They get pinged here in this channel and tap "
                f"**Accept** {emojis.yes}\n"
                "-# If nobody has the card: tap **Post a request**. Your "
                "request waits here in this channel. When a member who has a "
                "spare taps **Accept**, you get pinged."
            )),
            Separator(divider=False),
            Text(content=(
                "### After they accept\n"
                "**8.** Get into the same clan, then send the cards to each "
                "other in game — the same way you send any card\n\n"
                f"**9.** Open {cards_mention()}. I ask *Did you send your card?* "
                f"Tap **Yes, I sent it** {emojis.yes}\n"
                "-# Only your own card moves when you answer. They confirm "
                "theirs the same way. Nothing is lost if one of you is slow."
            )),
            Separator(divider=True),
            Text(content=(
                f"-# Still stuck? Message <@{SUPPORT_USER_ID}>"
            )),
        ],
    )]


@register_action("cards_help", no_return=True)
async def cards_help(ctx, action_id: str, **_kwargs) -> None:
    """Answer the sticky's help button with a private walkthrough.

    Registered with the shared dispatcher rather than listening for the raw
    event: that dispatcher handles EVERY component interaction, so an
    unregistered custom_id is refused as an out-of-date panel before any other
    listener sees it.

    `no_return=True` because the dispatcher's normal reply is an EDIT of the
    message that was clicked - which here is the sticky itself, so returning
    components would replace the notice with this walkthrough for everybody.
    A followup is a separate message and can be ephemeral.
    """
    try:
        await ctx.interaction.execute(
            components=_walkthrough(),
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.EPHEMERAL
            ),
        )
    except Exception as exc:
        print(f"[Cards Sticky] help response failed: "
              f"{type(exc).__name__}: {exc}")


def _content_key() -> str:
    """Fingerprint of the wording, so a reworded notice can be spotted.

    Burial is not the only reason to act. Without this, editing the text and
    restarting changed nothing in a quiet channel: the notice was still the
    newest message, so the burial check returned early and the old wording sat
    there until somebody happened to talk.
    """
    parts: list[str] = []
    for container in _sticky_components():
        for node in container.components:
            if hasattr(node, "content"):
                parts.append(str(node.content))
                continue
            # Not only the words. Adding the banner changed no text at all, so
            # a text-only fingerprint would have left the live notice without
            # it for ever - the burial check would keep returning early and
            # nothing would ever trigger the edit.
            for item in getattr(node, "items", ()) or ():
                parts.append(f"media:{getattr(item, 'media', '')}")
            for child in getattr(node, "components", ()) or ():
                parts.append(
                    f"control:{getattr(child, 'custom_id', '')}"
                    f"|{getattr(child, 'label', '')}"
                    f"|{getattr(child, 'url', '')}"
                )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]


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


def _snowflake_time(value: object) -> datetime | None:
    """When a message id was minted, read out of the id itself.

    A Discord snowflake encodes its own creation time, so the age of the last
    message costs no API call - the channel fetch already handed us its id.
    Fetching the message to read `created_at` would be a second round trip for
    something already in hand, and would fail outright once that message is
    deleted while the id remains perfectly readable.
    """
    try:
        return hikari.Snowflake(int(value)).created_at
    except (TypeError, ValueError, OverflowError):
        return None


def _channel_is_quiet(newest: object, *, now: datetime) -> bool:
    """Whether nobody has said anything for QUIET_PERIOD_MINUTES."""
    spoke_at = _snowflake_time(newest)
    if spoke_at is None:
        # An empty channel, or an id that will not parse. There is no
        # conversation to interrupt either way.
        return True
    return (now - spoke_at) >= timedelta(minutes=QUIET_PERIOD_MINUTES)


def _interval_elapsed(stored: dict, *, now: datetime) -> bool:
    """Whether enough time has passed since the notice was last posted."""
    posted_at = stored.get("posted_at")
    if not isinstance(posted_at, datetime):
        # Never posted, or a document written before this field existed.
        return True
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return (now - posted_at) >= timedelta(minutes=REPOST_INTERVAL_MINUTES)


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

    newest = await _newest_message_id(bot_instance, channel_id)
    if newest is UNKNOWN:
        # Do not repost on a guess. If the channel cannot be read, posting
        # into it is unlikely to work either, and a wrong guess repeats
        # every cycle for as long as the failure lasts.
        return

    if previous_id and int(previous_channel or 0) == channel_id:
        # The notice already sits at the bottom, so a repost achieves nothing -
        # unless the wording changed, in which case edit it where it stands.
        # An edit does not move the message, so it is not gated on quiet.
        if newest is not None and newest == int(previous_id):
            if stored.get("content_key") != _content_key():
                if await _rewrite_in_place(
                    bot_instance, channel_id, int(previous_id)
                ):
                    await _remember_content_key(_content_key())
            await _drain_pending(owed, channel_id)
            return

    # Buried, but that alone is no longer reason enough. Reposting on a plain
    # timer dropped the notice into the middle of whatever people were saying,
    # over and over, for as long as they kept talking. Both gates have to be
    # open: long enough since the last post, and long enough since anyone
    # spoke. The loop looks every minute, so the notice lands shortly after a
    # conversation ends rather than in the middle of the next one.
    now = datetime.now(timezone.utc)
    if not _interval_elapsed(stored, now=now):
        return
    if not _channel_is_quiet(newest, now=now):
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
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


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
    await _learn_cards_mention(bot)
    sticky_task = asyncio.create_task(sticky_loop(), name="cards-sticky")
    print(f"[Cards Sticky] task started for #{STICKY_CHANNEL_ID}: checks "
          f"every {CHECK_INTERVAL_SECONDS}s, reposts at most every "
          f"{REPOST_INTERVAL_MINUTES}m and only after "
          f"{QUIET_PERIOD_MINUTES}m of quiet")


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
