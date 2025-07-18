# extensions/events/message/ticket_automation/handlers/timezone.py
"""
Handles timezone setup using Friend Time bot.
Waits for Friend Time confirmation before proceeding.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
    LinkButtonBuilder as LinkButton,
)

from utils.mongo import MongoClient
from utils.emoji import emojis
from utils.constants import BLUE_ACCENT, GREEN_ACCENT
from ..core.state_manager import StateManager

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Friend Time bot configuration
FRIEND_TIME_BOT_ID = 471091072546766849
FRIEND_TIME_SET_COMMAND_ID = 924862149292085268

# Self-contained constants
TIMEZONE_CONFIRMATION_TIMEOUT = 600  # Seconds to wait for Friend Time bot confirmation

# Self-contained question data
TIMEZONE_QUESTION = {
    "title": "## 🌍 **Set Your Timezone**",
    "content": (
        "Let's set your timezone so clan leaders know when you're active!\n\n"
        "{red_arrow} **Click the button below** to open Friend Time\n"
        "{red_arrow} **Select your timezone** from the dropdown\n"
        "{red_arrow} **Wait for confirmation** from Friend Time bot\n\n"
        "*This helps with war timing and coordinating attacks!*"
    )
}


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_timezone_question(channel_id: int, user_id: int) -> None:
    """Send the timezone setup question"""

    if not bot_instance or not mongo_client:
        print("[Timezone] Error: Bot not initialized")
        return

    try:
        # Update state
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.current_question": "timezone",
                    "step_data.questionnaire.awaiting_timezone_confirmation": True,
                    "step_data.questionnaire.awaiting_response": False
                }
            }
        )

        # Create components using self-contained data
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"<@{user_id}>"),
                    Separator(divider=True),
                    Text(content=TIMEZONE_QUESTION["title"]),
                    Separator(divider=True),
                    Text(content=(
                        "To help us match you with the right clan and events, let's set your timezone.\n\n"
                    )),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right} "
                                    "**Step 1: Find Your Time Zone**"
                                )
                            )
                        ],
                        accessory=LinkButton(
                            url="https://zones.arilyn.cc/",
                            label="Get My Time Zone 🌐",
                        ),
                    ),
                    Text(
                        content=(
                            "**Example format:** `America/New_York`\n\n"
                            "**Steps:**\n"
                            "1. Click the link above to find your timezone\n"
                            f"2. Use the command: </set me:{FRIEND_TIME_SET_COMMAND_ID}>\n"
                            "3. Paste your timezone when Friend Time bot asks\n"
                            "4. Confirm with **yes** when prompted\n\n"
                            "*I'll wait for Friend Time bot to confirm your timezone is set!*"
                        )
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                    Text(content="-# Kings Alliance Recruitment – Syncing Schedules, Building Teams!")
                ]
            )
        ]

        # Send message
        channel = await bot_instance.rest.fetch_channel(channel_id)
        msg = await channel.send(
            components=components,
            user_mentions=True
        )

        # Store message ID
        await StateManager.store_message_id(
            str(channel_id),
            "questionnaire_timezone",
            str(msg.id)
        )

        # Start monitoring for Friend Time confirmation
        asyncio.create_task(
            monitor_friend_time_confirmation(channel_id, user_id)
        )

        print(f"[Timezone] Sent timezone question to channel {channel_id}")

    except Exception as e:
        print(f"[Timezone] Error sending timezone question: {e}")
        import traceback
        traceback.print_exc()


async def monitor_friend_time_confirmation(channel_id: int, user_id: int):
    """Monitor for Friend Time bot confirmation with timeout."""
    try:
        print(f"[Timezone] Starting Friend Time monitor for channel {channel_id}")

        # Wait for the configured timeout
        await asyncio.sleep(TIMEZONE_CONFIRMATION_TIMEOUT)

        # Check if we're still waiting
        current_state = await StateManager.get_ticket_state(str(channel_id))
        if (current_state and
                current_state.get("step_data", {}).get("questionnaire", {}).get("awaiting_timezone_confirmation",
                                                                                False)):

            # Check if we already moved to the next question
            current_question = current_state.get("step_data", {}).get("questionnaire", {}).get("current_question", "")
            if current_question != "timezone":
                print(f"[Timezone] Already moved to {current_question}, skipping timeout handling")
                return

            print(
                f"[Timezone] Friend Time confirmation timeout after {TIMEZONE_CONFIRMATION_TIMEOUT}s - proceeding anyway")

            # Mark as complete with timeout
            await mongo_client.ticket_automation_state.update_one(
                {"_id": str(channel_id)},
                {
                    "$set": {
                        "step_data.questionnaire.awaiting_timezone_confirmation": False,
                        "step_data.questionnaire.timezone": "Not set (timeout)",
                        "step_data.questionnaire.responses.timezone": "Not set (timeout)"
                    }
                }
            )

            # Send completion message even for timeout
            await send_timezone_completion_message(int(channel_id), int(user_id), None)

            # Wait a bit before proceeding
            await asyncio.sleep(2)

            # Proceed to next question
            await proceed_to_next_question(channel_id, user_id)

    except Exception as e:
        print(f"[Timezone] Error in Friend Time monitor: {e}")
        import traceback
        traceback.print_exc()


async def send_timezone_completion_message(channel_id: int, user_id: int, timezone_str: Optional[str] = None):
    """Send a completion message after timezone is set"""
    if not bot_instance:
        return

    try:
        # Create completion message
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content=f"<@{user_id}>"),
                    Separator(divider=True),
                    Text(content="## ✅ **Timezone Set Successfully!**"),
                    Text(content=(
                        f"Great! Your timezone has been set{f' to **{timezone_str}**' if timezone_str else ''}.\n\n"
                        "This helps clan leaders know when you're most active and coordinate war attacks.\n\n"
                        "*Moving to the final step...*"
                    )),
                    Media(items=[MediaItem(media="assets/Green_Footer.png")])
                ]
            )
        ]

        # Send to channel
        channel = await bot_instance.rest.fetch_channel(channel_id)
        await channel.send(
            components=components,
            user_mentions=True
        )

        print(f"[Timezone] Sent completion message to channel {channel_id}")

    except Exception as e:
        print(f"[Timezone] Error sending completion message: {e}")


async def check_friend_time_confirmation(event: hikari.GuildMessageCreateEvent) -> bool:
    """
    Check if a message is a Friend Time bot timezone confirmation.
    This function should be called from message event listeners.
    """
    if not mongo_client:
        return False

    # Check if it's from Friend Time bot
    if event.author_id != FRIEND_TIME_BOT_ID:
        return False

    # Get ticket state
    ticket_state = await StateManager.get_ticket_state(str(event.channel_id))
    if not ticket_state:
        return False

    # Check if we're waiting for timezone confirmation
    if not ticket_state.get("step_data", {}).get("questionnaire", {}).get("awaiting_timezone_confirmation", False):
        return False

    print(f"[Timezone] Checking Friend Time message in channel {event.channel_id}")

    # Look for confirmation in embeds (Friend Time sends embeds)
    if event.message.embeds:
        for embed in event.message.embeds:
            if embed.description and (
                    "Congratulations!" in embed.description and "You've completed user setup!" in embed.description):
                print(f"[Timezone] Friend Time confirmation detected!")

                # Extract timezone if possible
                timezone_str = None
                if embed.fields:
                    for field in embed.fields:
                        if "time zone" in field.name.lower() or "timezone" in field.name.lower():
                            timezone_str = field.value.strip()
                            break

                # Update state
                await mongo_client.ticket_automation_state.update_one(
                    {"_id": str(event.channel_id)},
                    {
                        "$set": {
                            "step_data.questionnaire.timezone_confirmed": True,
                            "step_data.questionnaire.awaiting_timezone_confirmation": False,
                            "step_data.questionnaire.timezone": timezone_str or "Set (not extracted)",
                            "step_data.questionnaire.responses.timezone": timezone_str or "Set (not extracted)"
                        }
                    }
                )

                # Get user ID
                user_id = (
                        ticket_state.get("discord_id") or
                        ticket_state.get("user_id") or
                        ticket_state.get("ticket_info", {}).get("user_id")
                )

                if user_id:
                    try:
                        user_id = int(user_id)
                    except (ValueError, TypeError):
                        pass

                    # Send completion message
                    await send_timezone_completion_message(event.channel_id, user_id, timezone_str)

                    # Wait before proceeding
                    await asyncio.sleep(2)

                    # Proceed to next question
                    await proceed_to_next_question(str(event.channel_id), str(user_id))

                return True

    return False


async def proceed_to_next_question(channel_id: str, user_id: str) -> None:
    """Determine and proceed to the next question in the flow"""

    # Check if we're in FWA flow
    ticket_state = await StateManager.get_ticket_state(str(channel_id))
    if not ticket_state:
        return

    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
    if fwa_data.get("current_fwa_step") == "timezone":
        # We're in FWA flow, route to FWA completion
        print(f"[Timezone] Routing to FWA completion")
        from ..fwa.core.fwa_flow import FWAFlow
        await FWAFlow.handle_questionnaire_completion(int(channel_id), int(user_id))
    else:
        # Normal flow - send completion message (final step)
        from .completion import send_completion_message
        await send_completion_message(int(channel_id), int(user_id))