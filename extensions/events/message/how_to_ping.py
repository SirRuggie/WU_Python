# extensions/events/message/how_to_ping.py
"""
Handles "How to ping" messages to explain Discord pinging.
"""

import asyncio
import logging
import aiohttp

import hikari
from utils.background import log_failure
import lightbulb
from typing import Optional

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from utils.constants import WU_GOLD
from utils.mongo import MongoClient
from utils import recruit_goblin_challenges as storage

_log = logging.getLogger(__name__)

# Global instances
bot_instance: Optional[hikari.GatewayBot] = None
mongo_client: Optional[MongoClient] = None


def initialize(bot: hikari.GatewayBot, mongo: Optional[MongoClient] = None):
    """Initialize the handler"""
    global bot_instance, mongo_client
    bot_instance = bot
    mongo_client = mongo
    _log.debug("How-to-ping handler initialized")


async def check_how_to_ping(event: hikari.GuildMessageCreateEvent) -> bool:
    """
    Check if a message contains "how to ping" and respond with instructions.
    Returns True if the message was handled by this system.
    """
    if not bot_instance or not mongo_client:
        return False
    
    # Skip bot messages
    if event.is_bot:
        return False
    
    # Check message content (case-insensitive)
    if not event.content:
        return False
        
    content_lower = event.content.lower()
    
    # Check for "how to ping" in the message
    if "how to ping" in content_lower:
        # Only respond if there's an active goblin challenge in this channel
        challenge = await mongo_client.recruit_challenges.find_one(
            storage.active_query(event.channel_id, event.author_id)
        )

        if not challenge:
            # No active challenge, don't respond
            return False
        
        _log.debug("How-to-ping request matched an active challenge")
        
        # Send the explanation
        await send_ping_explanation(event.channel_id, event.author_id)
        
        # Add reaction to acknowledge
        try:
            await event.message.add_reaction("📌")
        except asyncio.CancelledError:
            raise
        except (hikari.HTTPError, hikari.RateLimitTooLongError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            log_failure(_log, "ping-acknowledgement", error)
            pass
        except Exception as error:
            log_failure(_log, "ping-acknowledgement-unexpected", error)
            raise
        
        return True
    
    return False


async def send_ping_explanation(channel_id: int, user_id: int):
    """Send the ping explanation message"""
    if not bot_instance:
        return
    
    try:
        components = [
            Container(
                accent_color=WU_GOLD,
                components=[
                    Text(content="## 📌 **How to ping in Discord**"),
                    Separator(divider=True),
                    Text(
                        content=(
                            "A ping is, essentially, a notification—primarily for smartphones.\n\n"
                            "When someone sends a \"ping,\" that particular person gets a popup on their phone "
                            "(or desktop application), if they belong to the group pinged.\n\n"
                            "**All pings on discord start with the \"@\" symbol.**\n\n"
                            "Whenever you ping someone, make sure you are in the correct channel! "
                            "Meaning, if you have a question for person \"X\" about war, make sure you are in the proper clan channel.\n\n"
                            "**To ping a specific user:** use @nickname (i.e. @dragonslayer). "
                            "As you start typing their nickname, it should autofill for you. "
                            "Alternatively, you can use their discord username.\n\n"
                            "**To ping a role:** use @role (i.e. @recruiter).\n"
                            "Either of the above pings can be used in just about any standard channel.\n\n"
                            f"Now that ya know <@{user_id}>. Type the word Goblin and ping the recruiter helping you within this ticket...👍🏻"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png")
                        ]
                    ),
                ]
            )
        ]
        
        channel = await bot_instance.rest.fetch_channel(channel_id)
        await channel.send(
            components=components,
            user_mentions=[user_id]
        )
        
        _log.debug("How-to-ping explanation sent")
        
    except Exception as e:
        log_failure(_log, "ping-explanation", e)
