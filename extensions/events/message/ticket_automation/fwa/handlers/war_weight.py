# extensions/events/message/ticket_automation/fwa/handlers/war_weight.py
"""
Handles war weight screenshot request and validation for FWA tickets.
"""

import asyncio
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
from utils.constants import GOLD_ACCENT, GREEN_ACCENT
from utils.emoji import emojis
from ...core.state_manager import StateManager
from ..core.fwa_flow import FWAFlow, FWAStep

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the war weight handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_war_weight_request(channel_id: int, thread_id: int, user_id: int):
    """Send the war weight screenshot request"""
    if not bot_instance:
        print("[FWA War Weight] Bot not initialized")
        return

    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=f"<@{user_id}>"),
                Separator(divider=True),
                Text(content="## ⚖️ **War Weight Check**"),
                Separator(divider=True),
                Text(content=(
                    "We need your **current war weight** to ensure fair matchups. Please:\n\n"
                    f"{emojis.red_arrow_right} **Post** a Friendly Challenge in-game.\n"
                    f"{emojis.red_arrow_right} **Scout** that challenge you posted\n"
                    f"{emojis.red_arrow_right} **Tap** on your Town Hall, then hit **Info**.\n"
                    f"{emojis.red_arrow_right} **Upload** a screenshot of the Town Hall info popup here.\n\n"
                    "*See the example below for reference.*"
                )),
                Media(
                    items=[
                        MediaItem(
                            media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751550804/TH_Weight.png"
                        ),
                    ]
                ),
                Text(content=f"-# Waiting for your war weight screenshot...")
            ]
        )
    ]

    try:
        await bot_instance.rest.create_message(
            channel=thread_id,
            components=components
        )

        # Update state
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                "step_data.fwa.war_weight_requested": True,
                "step_data.fwa.war_weight_requested_at": datetime.now(timezone.utc)
            }
        )

        print(f"[FWA War Weight] Sent request to thread {thread_id}")

    except Exception as e:
        print(f"[FWA War Weight] Error sending request: {e}")


async def handle_war_weight_upload(
        channel_id: int,
        thread_id: int,
        user_id: int,
        message: hikari.Message
) -> bool:
    """
    Handle war weight screenshot upload.
    Returns True if handled, False otherwise.
    """
    if not bot_instance or not mongo_client:
        return False

    # Check if message has attachments or embeds (screenshot)
    if not message.attachments and not message.embeds:
        return False

    # Get ticket state
    ticket_state = await StateManager.get_ticket_state(str(channel_id))
    if not ticket_state:
        return False

    # Check if we're waiting for war weight
    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
    if (fwa_data.get("current_fwa_step") != FWAStep.WAR_WEIGHT.value or
            fwa_data.get("war_weight_uploaded")):
        return False

    # Send success message
    success_components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=(
                    "✅ **War Weight Screenshot Uploaded Successfully!**\n\n"
                    "Thank you for providing your war weight information."
                )),
                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]

    await bot_instance.rest.create_message(
        channel=thread_id,
        components=success_components
    )

    # Update state
    await StateManager.update_ticket_state(
        str(channel_id),
        {
            "step_data.fwa.war_weight_uploaded": True,
            "step_data.fwa.war_weight_uploaded_at": datetime.now(timezone.utc),
            "step_data.fwa.war_weight_message_id": message.id
        }
    )

    # Wait before proceeding
    await asyncio.sleep(2)

    # Proceed to account collection
    await FWAFlow.proceed_to_next_step(
        channel_id,
        thread_id,
        user_id,
        FWAStep.ACCOUNT_COLLECTION
    )

    return True