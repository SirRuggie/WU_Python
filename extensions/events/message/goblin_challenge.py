# extensions/events/message/goblin_challenge.py
"""
Handles the goblin ping challenge for recruit questions.
Monitors for users to say "goblin" and ping their recruiter.
"""

import asyncio
import hikari
import logging
from typing import Optional
from utils import recruit_goblin_challenges as storage


from utils.mongo import MongoClient
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from utils.constants import GREEN_ACCENT

_log = logging.getLogger(__name__)

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot
    print("[GoblinChallenge] Handler initialized")


async def prepare_storage() -> None:
    if not mongo_client:
        return
    try:
        migrated = await storage.prepare_storage(mongo_client)
        _log.info("Goblin challenge storage ready: migrated=%s", migrated)
    except Exception:
        _log.exception("Goblin challenge storage preparation failed; legacy rows preserved for retry")


async def check_goblin_challenge(event: hikari.GuildMessageCreateEvent) -> bool:
    """
    Check if a message completes a goblin challenge.
    Returns True if the message was handled by this system.
    """
    if not mongo_client:
        return False

    # Skip bot messages
    if event.is_bot or not event.content:
        return False

    challenge = await mongo_client.recruit_challenges.find_one(
        storage.active_query(event.channel_id, event.author_id)
    )

    if not challenge:
        # No active challenge in this channel, silently return
        return False

    # Only log if we found a relevant challenge
    print(f"[GoblinChallenge] Found active challenge ID {challenge.get('_id')} in channel {event.channel_id} for user {challenge.get('user_id')}")

    # Check if it's the right user
    if event.author_id != challenge.get("user_id"):
        return False

    # Check message content (case-insensitive)
    content_lower = event.content.lower()
    has_goblin = "goblin" in content_lower

    # Check if recruiter is mentioned
    recruiter_id = challenge.get("recruiter_id")
    has_recruiter_ping = recruiter_id in event.message.user_mentions_ids

    print(f"[GoblinChallenge] Checking message: has_goblin={has_goblin}, has_recruiter_ping={has_recruiter_ping}")

    if has_goblin and has_recruiter_ping:
        claim_id = await storage.claim(mongo_client, challenge)
        if claim_id is None:
            return True
        try:
            # Bound delivery below the durable claim lease. A stopped process
            # leaves a claim that becomes eligible again after two minutes.
            async with asyncio.timeout(60):
                message = await send_success_message(event.channel_id, event.author_id, recruiter_id)
        except Exception:
            await storage.release(mongo_client, challenge, claim_id)
            _log.exception("Goblin confirmation failed; challenge retained channel=%s user=%s",
                           event.channel_id, event.author_id)
            return True
        await storage.complete(mongo_client, challenge, claim_id, message.id)

        # Add reaction to the user's message
        try:
            await event.message.add_reaction("✅")
        except:
            pass

        return True

    elif has_goblin and not has_recruiter_ping:
        # They said goblin but didn't ping the recruiter
        try:
            await event.message.add_reaction("❓")
            await event.message.respond(
                f"<@{event.author_id}> Nice try! You said 'goblin' but you forgot to ping your recruiter <@{recruiter_id}>. Try again!",
                mentions_everyone=False,
                user_mentions=[event.author_id]
            )
        except:
            pass
        return True

    elif has_recruiter_ping and not has_goblin:
        # They pinged but didn't say goblin
        try:
            await event.message.add_reaction("❓")
            await event.message.respond(
                f"<@{event.author_id}> You pinged your recruiter, but you forgot to say the magic word! (Hint: it rhymes with 'boblin')",
                mentions_everyone=False,
                user_mentions=[event.author_id]
            )
        except:
            pass
        return True

    return False


async def send_success_message(channel_id: int, user_id: int, recruiter_id: int):
    """Send a success message when the goblin challenge is completed"""
    if not bot_instance:
        raise RuntimeError("Goblin bot is not initialized")

    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=f"## 🎉 **Excellent Work!** · <@{user_id}>"),
                Separator(divider=True),
                Text(
                    content=(
                        "You've successfully:\n"
                        "✅ Said the magic word 'Goblin'\n"
                        f"✅ Pinged your recruiter <@{recruiter_id}>\n\n"
                        "**You've now proven all three Discord communication skills!**\n"
                        "1️⃣ Sending messages ✓\n"
                        "2️⃣ Pinging users ✓\n"
                        "3️⃣ Reacting to messages ✓\n\n"
                        "Awesome!!\n"
                        "You're officially 100% smarter than the average Discord user! 🧠✨\n\n"
                        "You'll be utilizing those three methods of discord communication very frequently while in the WU Server. "
                        "Be it a member or a Role, a ping; and/or a reaction to a message; can be worth a thousand words. "
                        "In some cases, it's the best way to get one's attention and all Leadership are cool with it...👍🏻\n\n"
                        "**Make sense?**"
                    )
                ),
                Media(
                    items=[
                        MediaItem(media="assets/Green_Footer.png")  # Use a valid image asset
                    ]
                ),
                Text(content=f"-# Challenge completed! Great job on mastering Discord basics."),
            ]
        )
    ]

    return await bot_instance.rest.create_message(
        channel=channel_id,
        components=components,
        user_mentions=[user_id, recruiter_id]
    )
