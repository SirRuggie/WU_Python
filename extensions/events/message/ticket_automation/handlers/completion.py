# extensions/events/message/ticket_automation/handlers/completion.py
"""
Handles questionnaire completion.
Sends final messages and updates automation state.
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
from utils.constants import GREEN_ACCENT, BLUE_ACCENT
from ..core.state_manager import StateManager

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Self-contained completion message data
LEADERS_MESSAGE = {
    "title": "## 👑 **Leaders Checking You Out**",
    "content": (
        "Heads up! Our clan leaders will be reviewing your profile:\n\n"
        "• **In-game profile** – Town Hall, hero levels, war stars\n"
        "• **Discord activity** – How you communicate and engage\n"
        "• **Application responses** – The info you've shared with us\n\n"
        "*Make sure your profile reflects your best! Leaders appreciate active, engaged members.*"
    ),
    "footer": "You've completed the questionnaire! A recruiter will be with you shortly."
}


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_completion_message(channel_id: int, user_id: int) -> None:
    """Send the final completion message including leaders checking you out"""

    if not mongo_client or not bot_instance:
        print("[Completion] Error: Not initialized")
        return

    try:
        # Send the final "leaders checking you out" message
        await send_leaders_message(channel_id, user_id)

        # Update automation state to mark completion
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.completed": True,
                    "step_data.questionnaire.completed_at": datetime.now(timezone.utc),
                    "automation_state.current_step": "clan_selection"
                }
            }
        )

        print(f"[Completion] Questionnaire completed for user {user_id} in channel {channel_id}")

        # TODO: Trigger next automation step (clan selection)
        # This would be implemented when clan selection automation is built

    except Exception as e:
        print(f"[Completion] Error sending completion message: {e}")
        import traceback
        traceback.print_exc()


async def send_leaders_message(channel_id: int, user_id: int) -> None:
    """Send the 'leaders checking you out' message"""

    if not bot_instance:
        return

    try:
        # Build components using self-contained data
        components_list = []

        # Add user ping
        components_list.append(Text(content=f"<@{user_id}>"))
        components_list.append(Separator(divider=True))

        # Add title
        components_list.append(Text(content=LEADERS_MESSAGE["title"]))

        # Add content
        components_list.append(Separator(divider=True))
        components_list.append(Text(content=LEADERS_MESSAGE["content"]))

        # Add footer
        components_list.append(Text(content=f"-# {LEADERS_MESSAGE['footer']}"))

        # Add completion footer image (green to indicate success)
        components_list.append(Media(items=[MediaItem(media="assets/Green_Footer.png")]))

        # Create container with GREEN_ACCENT to indicate completion
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=components_list
            )
        ]

        channel = await bot_instance.rest.fetch_channel(channel_id)
        await channel.send(
            components=components,
            user_mentions=True
        )

        # Store this as a response
        await StateManager.store_response(str(channel_id), "leaders_checking_you_out", "viewed")

        # Store message ID
        await StateManager.store_message_id(
            str(channel_id),
            "questionnaire_leaders_checking_you_out",
            "completed"
        )

        print(f"[Completion] Sent leaders checking you out message")

    except Exception as e:
        print(f"[Completion] Error sending leaders message: {e}")
        import traceback
        traceback.print_exc()


async def is_final_step(channel_id: int) -> bool:
    """Check if this is the final step in the current flow"""

    if not mongo_client:
        return True

    ticket_state = await StateManager.get_ticket_state(str(channel_id))
    if not ticket_state:
        return True

    # Check if we're in FWA flow
    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
    if fwa_data.get("current_fwa_step"):
        # In FWA flow, completion handler might not be the final step
        return False

    # In normal questionnaire flow, this is the final step
    return True