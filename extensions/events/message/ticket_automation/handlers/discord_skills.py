# extensions/events/message/ticket_automation/handlers/discord_skills.py
"""
Handles Discord basic skills verification.
Requires users to react and reply with a mention to prove basic Discord knowledge.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any
import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.emoji import emojis
from utils.constants import GOLD_ACCENT, BLUE_ACCENT, GREEN_ACCENT
from ..core.state_manager import StateManager
from ..utils.constants import (
    REMINDER_DELETE_TIMEOUT,
    REMINDER_TIMEOUT
)

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Self-contained question data
DISCORD_SKILLS_QUESTION = {
    "title": "## 🎮 **Discord Basic Skills Check**",
    "content": (
        "Let's make sure you know the Discord basics!\n\n"
        "{red_arrow} **Step 1:** React to this message with any emoji\n"
        "{blank}{white_arrow} _Click the smiley face below to add a reaction_\n\n"
        "{red_arrow} **Step 2:** Reply and mention the bot\n"
        "{blank}{white_arrow} _Type a message with {bot_mention}_\n\n"
        "*This ensures you can interact properly in your new clan!*"
    ),
    "footer": "React to this message and mention the bot to continue!",
    "next": "age_bracket"
}


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


def create_discord_skills_components(
        title: str,
        content: str,
        accent_color: int,
        user_id: int,
        footer: Optional[str] = None
) -> List[Container]:
    """Create container components for Discord skills messages"""

    components_list = []

    # Add user mention
    components_list.append(Text(content=f"<@{user_id}>"))
    components_list.append(Separator(divider=True))

    # Add title
    components_list.append(Text(content=title))

    # Add separator if there's content
    if content:
        components_list.append(Separator(divider=True))
        components_list.append(Text(content=content))

    # Add footer if provided
    if footer:
        components_list.append(Text(content=f"-# {footer}"))

    # Add footer image based on accent color
    footer_image = "assets/Gold_Footer.png" if accent_color == GOLD_ACCENT else "assets/Green_Footer.png"
    components_list.append(Media(items=[MediaItem(media=footer_image)]))

    # Create and return container
    return [
        Container(
            accent_color=accent_color,
            components=components_list
        )
    ]


async def send_discord_skills_question(channel_id: int, user_id: int) -> None:
    """Send the Discord basic skills verification question"""

    if not mongo_client or not bot_instance:
        print("[DiscordSkills] Error: Not initialized")
        return

    try:
        question_key = "discord_basic_skills"
        question_data = DISCORD_SKILLS_QUESTION

        # Get Bot ID
        bot_id = bot_instance.get_me().id

        # Format content
        content = question_data["content"].format(
            red_arrow=str(emojis.red_arrow_right),
            white_arrow=str(emojis.white_arrow_right),
            blank=str(emojis.blank),
            bot_mention=f"<@{bot_id}>"
        )

        # Create components
        components = create_discord_skills_components(
            title=question_data["title"],
            content=content,
            accent_color=GOLD_ACCENT,
            user_id=user_id,
            footer=question_data.get("footer", "React to this message and mention the bot to continue!")
        )

        # Update state FIRST before sending message
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.current_question": question_key,
                    "step_data.questionnaire.awaiting_response": True,
                    "step_data.questionnaire.discord_skills_completed": False,
                    "step_data.questionnaire.discord_skills_reaction": False,
                    "step_data.questionnaire.discord_skills_mention": False,
                    "step_data.questionnaire.last_reminder_time": None
                }
            }
        )

        # Send message
        channel = await bot_instance.rest.fetch_channel(channel_id)
        msg = await channel.send(
            components=components,
            user_mentions=True
        )

        # Store message ID in the correct location
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    f"messages.questionnaire_{question_key}": str(msg.id),
                    "step_data.questionnaire.discord_skills_message_id": str(msg.id),
                    f"messages.questionnaire_discord_basic_skills": str(msg.id)
                }
            }
        )

        # Add initial reaction for user to copy
        await msg.add_reaction("✅")

        print(f"[DiscordSkills] Sent question to channel {channel_id}, message ID: {msg.id}")

        # Start monitoring for completion
        bot_id = bot_instance.get_me().id
        asyncio.create_task(monitor_discord_skills_completion(channel_id, user_id, msg.id, bot_id))

    except Exception as e:
        print(f"[DiscordSkills] Error sending question: {e}")
        import traceback
        traceback.print_exc()


async def monitor_discord_skills_completion(channel_id: int, user_id: int, message_id: int, bot_id: int) -> None:
    """Monitor for completion of Discord skills requirements"""

    print(f"[DiscordSkills] Starting monitor for channel {channel_id}, user {user_id}")

    try:
        while True:
            await asyncio.sleep(5)  # Check every 5 seconds

            # Get FRESH state from database
            ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
            if not ticket_state:
                print(f"[DiscordSkills] Monitor: No ticket state found")
                break

            skills_data = ticket_state.get("step_data", {}).get("questionnaire", {})
            reaction_done = skills_data.get("discord_skills_reaction", False)
            mention_done = skills_data.get("discord_skills_mention", False)

            # Check if we've moved past this question
            current_question = skills_data.get("current_question", "")
            if current_question != "discord_basic_skills":
                print(f"[DiscordSkills] Monitor: Question changed to {current_question}, exiting")
                break

            print(f"[DiscordSkills] Monitor check: reaction={reaction_done}, mention={mention_done}")

            # If both completed, move to next question
            if reaction_done and mention_done:
                print(f"[DiscordSkills] Both requirements completed!")

                # Update completion
                await mongo_client.ticket_automation_state.update_one(
                    {"_id": str(channel_id)},
                    {
                        "$set": {
                            "step_data.questionnaire.discord_skills_completed": True,
                            "step_data.questionnaire.responses.discord_basic_skills": "completed_requirements"
                        }
                    }
                )

                # Send completion message
                await send_skills_completion_message(channel_id, user_id)

                # Wait a bit then move to next question
                await asyncio.sleep(3)

                # Check if we're in FWA flow
                ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
                fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
                if fwa_data.get("current_fwa_step") == "discord_skills":
                    # We're in FWA flow, use FWA routing
                    print(f"[DiscordSkills] Routing to FWA age bracket")
                    from ..fwa.core.fwa_flow import FWAFlow
                    await FWAFlow.handle_questionnaire_completion(channel_id, user_id)
                else:
                    # Normal questionnaire flow
                    from ..core import questionnaire_manager
                    from ..utils.flow_map import get_next_question
                    next_question = get_next_question("discord_basic_skills")
                    if next_question:
                        await questionnaire_manager.send_question(channel_id, user_id, next_question)

                break

    except Exception as e:
        print(f"[DiscordSkills] Error in monitor: {e}")
        import traceback
        traceback.print_exc()


async def check_reaction_completion(channel_id: int, user_id: int, message_id: int) -> None:
    """Check if a reaction completes the Discord skills requirement"""

    if not mongo_client or not bot_instance:
        return

    # Skip bot reactions
    if user_id == bot_instance.get_me().id:
        return

    print(f"[DiscordSkills] Checking reaction: channel={channel_id}, user={user_id}, msg={message_id}")

    # Get ticket state
    ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
    if not ticket_state:
        print(f"[DiscordSkills] No ticket state found")
        return

    # Check if this is the Discord skills message
    skills_msg_id = ticket_state.get("step_data", {}).get("questionnaire", {}).get("discord_skills_message_id")
    print(f"[DiscordSkills] Stored msg_id={skills_msg_id}, checking against={message_id}")

    if not skills_msg_id or str(message_id) != skills_msg_id:
        print(f"[DiscordSkills] Message ID mismatch")
        return

    # Get expected user from multiple possible locations
    expected_user = (
            ticket_state.get("discord_id") or
            ticket_state.get("user_id") or
            ticket_state.get("ticket_info", {}).get("user_id") or
            ticket_state.get("step_data", {}).get("user_id")
    )

    if expected_user:
        try:
            expected_user = int(expected_user)
        except (ValueError, TypeError):
            print(f"[DiscordSkills] Error converting user_id: {expected_user}")
            expected_user = None

    print(f"[DiscordSkills] Expected user={expected_user}, actual user={user_id}")

    if not expected_user:
        print(f"[DiscordSkills] No expected user found in ticket state, skipping validation")
    elif user_id != expected_user:
        print(f"[DiscordSkills] User ID mismatch")
        return

    # Update reaction completed
    await mongo_client.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {"$set": {"step_data.questionnaire.discord_skills_reaction": True}}
    )
    print(f"[DiscordSkills] User {user_id} completed reaction requirement")


async def check_mention_completion(channel_id: int, user_id: int, message: hikari.Message) -> None:
    """Check if a mention completes the Discord skills requirement"""

    if not mongo_client or not bot_instance:
        return

    print(f"[DiscordSkills] Checking mention in message from user {user_id}")

    # Get ticket state
    ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
    if not ticket_state:
        return

    questionnaire_data = ticket_state.get("step_data", {}).get("questionnaire", {})
    current_question = questionnaire_data.get("current_question")

    # Check if we're on discord skills question
    if current_question != "discord_basic_skills":
        return

    # Get expected user from multiple possible locations
    expected_user = (
            ticket_state.get("discord_id") or
            ticket_state.get("user_id") or
            ticket_state.get("ticket_info", {}).get("user_id") or
            ticket_state.get("step_data", {}).get("user_id")
    )

    if expected_user:
        try:
            expected_user = int(expected_user)
        except (ValueError, TypeError):
            print(f"[DiscordSkills] Error converting user_id: {expected_user}")
            expected_user = None

    print(f"[DiscordSkills] Expected user={expected_user}, actual user={user_id}")

    if not expected_user:
        print(f"[DiscordSkills] No expected user found, continuing anyway")
    elif user_id != expected_user:
        return

    # Check if bot is mentioned
    bot_user = bot_instance.get_me()
    has_mention = bot_user.id in message.user_mentions_ids

    # Add reaction to show we processed
    try:
        if has_mention:
            await message.add_reaction("👀")  # Correct mention
            print(f"[DiscordSkills] User mentioned bot correctly!")

            # Update mention completed
            await mongo_client.ticket_automation_state.update_one(
                {"_id": str(channel_id)},
                {"$set": {"step_data.questionnaire.discord_skills_mention": True}}
            )
            print(f"[DiscordSkills] User {user_id} completed mention requirement")

            # Delete the message
            # try:
            #     await message.delete()
            # except:
            #     pass
        else:
            await message.add_reaction("❓")  # No mention
            print(f"[DiscordSkills] No bot mention found in message")

    except Exception as e:
        print(f"[DiscordSkills] Error: {e}")


async def send_skills_completion_message(channel_id: int, user_id: int) -> None:
    """Send a message confirming Discord skills completion"""

    if not bot_instance:
        return

    try:
        # Create completion components
        components = create_discord_skills_components(
            title="✅ **Discord Skills Verified!**",
            content=(
                "Great job! You've shown you can:\n"
                "• React to messages 👍\n"
                "• Mention users properly 💬\n\n"
                "These skills will help you communicate effectively in your new clan!\n\n"
                "*Moving to the next question...*"
            ),
            accent_color=GREEN_ACCENT,
            user_id=user_id
        )

        channel = await bot_instance.rest.fetch_channel(channel_id)
        await channel.send(
            components=components,
            user_mentions=True
        )

        print(f"[DiscordSkills] Sent completion message")

    except Exception as e:
        print(f"[DiscordSkills] Error sending completion message: {e}")