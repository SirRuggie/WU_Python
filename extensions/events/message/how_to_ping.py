# extensions/events/message/how_to_ping.py
"""
Handles "How to ping" messages to explain Discord pinging.
"""

import hikari
import lightbulb
from typing import Optional

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from utils.constants import BLUE_ACCENT
from utils.mongo import MongoClient

# Global instances
bot_instance: Optional[hikari.GatewayBot] = None
mongo_client: Optional[MongoClient] = None


def initialize(bot: hikari.GatewayBot, mongo: Optional[MongoClient] = None):
    """Initialize the handler"""
    global bot_instance, mongo_client
    bot_instance = bot
    mongo_client = mongo
    print("[HowToPing] Handler initialized")


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
        challenge = await mongo_client.button_store.find_one({
            "channel_id": event.channel_id,
            "challenge_type": "goblin_ping",
            "status": "pending"
        })
        
        if not challenge:
            # No active challenge, don't respond
            return False
        
        print(f"[HowToPing] Detected 'how to ping' from user {event.author_id} in channel {event.channel_id} with active challenge")
        
        # Send the explanation
        await send_ping_explanation(event.channel_id, event.author_id)
        
        # Add reaction to acknowledge
        try:
            await event.message.add_reaction("📌")
        except:
            pass
        
        return True
    
    return False


async def send_ping_explanation(channel_id: int, user_id: int):
    """Send the ping explanation message"""
    if not bot_instance:
        return
    
    try:
        components = [
            Container(
                accent_color=BLUE_ACCENT,
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
                            MediaItem(media="assets/Blue_Footer.png")
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
        
        print(f"[HowToPing] Sent ping explanation to user {user_id}")
        
    except Exception as e:
        print(f"[HowToPing] Error sending ping explanation: {e}")