# extensions/events/message/ticket_automation/fwa/handlers/completion.py
"""
Handles FWA completion - notifies that FWA leaders are reviewing.
"""

from datetime import datetime, timezone
from typing import Optional
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, GOLD_ACCENT
from utils.emoji import emojis
from ...core.state_manager import StateManager
from ..core.fwa_flow import FWAStep

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Import the existing log channel ID
from ...utils.constants import LOG_CHANNEL_ID


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the completion handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_fwa_completion(channel_id: int, thread_id: int, user_id: int):
    """Send the FWA completion message and update ticket state"""
    if not bot_instance or not mongo_client:
        print("[FWA Completion] Not initialized")
        return

    # Get ticket state for summary
    ticket_state = await StateManager.get_ticket_state(str(channel_id))
    if not ticket_state:
        print(f"[FWA Completion] No ticket state found for channel {channel_id}")
        return

    # Send completion message
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=f"<@{user_id}>"),
                Separator(divider=True),
                Text(content=f"## {emojis.FWA} **Application Complete!**"),
                Separator(divider=True),
                Text(content=(
                    "**The FWA Leaders are Reviewing Your Application**\n\n"
                    "Please be patient as this process may take some time. "
                    "Leaders will also need to evaluate roster adjustments to "
                    "accommodate your application.\n\n"
                    "We kindly ask that you **do not ping anyone** during this time. "
                    "Our leaders will reach out when they have an update.\n\n"
                    "Thank you for your interest in joining our FWA operation!"
                )),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    try:
        # Send to MAIN CHANNEL
        await bot_instance.rest.create_message(
            channel=channel_id,  # Main channel
            components=components,
            user_mentions=True
        )

        # Update final state
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                "step_data.fwa.completed": True,
                "step_data.fwa.completed_at": datetime.now(timezone.utc),
                "step_data.fwa.current_fwa_step": FWAStep.COMPLETION.value,
                "automation_state.completed": True,
                "automation_state.completed_at": datetime.now(timezone.utc)
            }
        )

        # Log to recruitment channel if configured
        if LOG_CHANNEL_ID:
            await log_fwa_completion(channel_id, user_id, ticket_state)

        print(f"[FWA Completion] Sent completion message to channel {channel_id}")

    except Exception as e:
        print(f"[FWA Completion] Error: {e}")


async def log_fwa_completion(channel_id: int, user_id: int, ticket_state: dict):
    """Log FWA recruitment completion to the log channel"""
    if not bot_instance:
        return

    try:
        # Create log embed or message
        log_message = (
            f"## 🏰 FWA Recruitment Completed\n"
            f"**User:** <@{user_id}>\n"
            f"**Channel:** <#{channel_id}>\n"
            f"**Completed:** <t:{int(datetime.now(timezone.utc).timestamp())}:R>"
        )

        await bot_instance.rest.create_message(
            channel=LOG_CHANNEL_ID,
            content=log_message
        )
    except Exception as e:
        print(f"[FWA Completion] Error logging completion: {e}")