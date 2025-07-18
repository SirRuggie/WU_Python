# extensions/events/message/ticket_automation/handlers/attack_strategies.py
"""
Handles attack strategies question with AI-powered processing.
Continuously processes user input and updates the display in real-time.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Any
import hikari
import lightbulb

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
)

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.emoji import emojis
from utils.constants import BLUE_ACCENT, GREEN_ACCENT
from ..core.state_manager import StateManager
from ..ai.processors import process_attack_strategies_with_ai

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Question content - defined once to avoid duplication
QUESTION_TITLE = "## ⚔️ **Attack Strategy Breakdown**"
QUESTION_CONTENT = lambda: (
    "Help us understand your go-to attack strategies!\n\n"
    f"{emojis.red_arrow_right} **Main Village strategies**\n"
    f"{emojis.blank}{emojis.white_arrow_right} _e.g. Hybrid, Queen Charge w/ Hydra, Lalo_\n\n"
    f"{emojis.red_arrow_right} **Clan Capital Attack Strategies**\n"
    f"{emojis.blank}{emojis.white_arrow_right} _e.g. Super Miners w/ Freeze_\n\n"
    f"{emojis.red_arrow_right} **Highest Clan Capital Hall level you've attacked**\n"
    f"{emojis.blank}{emojis.white_arrow_right} _e.g. CH 8, CH 9, etc._\n\n"
    "*Your detailed breakdown helps us match you to the perfect clan!*"
)


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


def create_attack_strategy_components(
        current_summary: str,
        title: str,
        detailed_content: str,
        show_done_button: bool = True,
        include_user_ping: bool = True,
        channel_id: Optional[int] = None,
        user_id: Optional[int] = None
) -> List[Container]:
    """Create container components for attack strategy messages"""

    # Format summary with emojis
    formatted_summary = current_summary.replace("{red_arrow}", str(emojis.red_arrow_right))
    formatted_summary = formatted_summary.replace("{white_arrow}", str(emojis.white_arrow_right))
    formatted_summary = formatted_summary.replace("{blank}", str(emojis.blank))

    components_list = []

    # Add user mention if requested
    if include_user_ping and user_id:
        components_list.append(Text(content=f"<@{user_id}>"))
        components_list.append(Separator(divider=True))

    # Add title
    components_list.append(Text(content=title))

    if not formatted_summary:
        # Initial message with detailed instructions
        components_list.append(Separator(divider=True))
        components_list.append(Text(content=detailed_content))

        # Add instruction at the bottom
        components_list.append(Text(
            content="\n💡 _Type your strategies below and I'll organize them for you. Click Done when finished._"
        ))
    else:
        # Once user starts typing, show their organized summary
        components_list.append(
            Text(
                content="📝 **Tell us about your attack strategies!**\n\n*Continue typing or click Done when finished.*")
        )

        # Add current summary
        components_list.append(Separator(divider=True))
        components_list.append(Text(content="**📋 Your Attack Strategies:**"))
        components_list.append(Text(content=formatted_summary))

    # Add footer image
    components_list.append(
        Media(items=[MediaItem(media="assets/Blue_Footer.png")])
    )

    # Add Done button if requested
    if show_done_button:
        custom_id = f"attack_strategies_done:{channel_id}_{user_id}" if channel_id and user_id else "attack_strategies_done:done"

        done_button = Button(
            style=hikari.ButtonStyle.SUCCESS,
            label="Done",
            custom_id=custom_id,
        )
        done_button.set_emoji("✅")

        # Add button in a Section
        components_list.append(
            Section(
                components=[
                    Text(content="Ready to continue? Click the button when you've finished entering your strategies.")
                ],
                accessory=done_button
            )
        )

    # Create and return container
    return [
        Container(
            accent_color=BLUE_ACCENT,
            components=components_list
        )
    ]


async def send_attack_strategies(channel_id: int, user_id: int) -> None:
    """Send the attack strategies collection question"""

    if not mongo_client or not bot_instance:
        print("[AttackStrategies] Error: Not initialized")
        return

    try:
        # Update state
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.current_question": "attack_strategies",
                    "step_data.questionnaire.awaiting_response": True,
                    "step_data.questionnaire.collecting_strategies": True,
                    "step_data.questionnaire.strategies_started_at": datetime.now(timezone.utc)
                }
            }
        )

        # Build the question content inline
        title = QUESTION_TITLE
        detailed_content = QUESTION_CONTENT()

        # Create components
        components = create_attack_strategy_components(
            current_summary="",  # Empty initially
            title=title,
            detailed_content=detailed_content,
            show_done_button=True,
            include_user_ping=True,
            channel_id=channel_id,
            user_id=user_id
        )

        # Send message
        channel = await bot_instance.rest.fetch_channel(channel_id)
        msg = await channel.send(
            components=components,
            user_mentions=True
        )

        # Store message ID
        await StateManager.store_message_id(
            str(channel_id),
            "questionnaire_attack_strategies",
            str(msg.id)
        )

        print(f"[AttackStrategies] Sent question to channel {channel_id}, message ID: {msg.id}")

    except Exception as e:
        print(f"[AttackStrategies] Error sending question: {e}")
        import traceback
        traceback.print_exc()


async def process_user_input(channel_id: int, user_id: int, content: str) -> None:
    """Process user input and update the strategies summary"""

    if not mongo_client:
        return

    try:
        # Get current state
        ticket_state = await StateManager.get_ticket_state(str(channel_id))
        if not ticket_state:
            return

        # Get current summary
        current_summary = ticket_state.get("step_data", {}).get("questionnaire", {}).get("attack_summary", "")

        # Process with AI (using the imported processor)
        updated_summary = await process_attack_strategies_with_ai(current_summary, content)

        # Update the summary in state
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.attack_summary": updated_summary,
                    "step_data.questionnaire.responses.attack_strategies": updated_summary,
                    "step_data.questionnaire.last_strategies_input": content,
                    "step_data.questionnaire.last_input_at": datetime.now(timezone.utc)
                }
            }
        )

        # Get message ID
        message_id = ticket_state.get("messages", {}).get("questionnaire_attack_strategies")
        if not message_id:
            print("[AttackStrategies] No message ID found to update")
            return

        # Build title and content again for consistency
        title = QUESTION_TITLE
        detailed_content = QUESTION_CONTENT()

        # Update the message with new summary
        new_components = create_attack_strategy_components(
            current_summary=updated_summary,
            title=title,
            detailed_content=detailed_content,
            show_done_button=True,
            include_user_ping=True,
            channel_id=channel_id,
            user_id=user_id
        )

        await bot_instance.rest.edit_message(
            channel=channel_id,
            message=int(message_id),
            components=new_components,
            user_mentions=True
        )

        print(f"[AttackStrategies] Updated message with new summary")

    except Exception as e:
        print(f"[AttackStrategies] Error processing input: {e}")
        import traceback
        traceback.print_exc()


@register_action("attack_strategies_done", no_return=True)
async def handle_attack_strategies_done(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Handle when user clicks Done on attack strategies"""

    channel_id = ctx.channel_id
    user_id = ctx.user.id

    # Verify this is the correct user
    ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
    if not ticket_state:
        await ctx.respond("❌ Ticket state not found.", ephemeral=True)
        return

    stored_user_id = (
            ticket_state.get("discord_id") or
            ticket_state.get("ticket_info", {}).get("user_id") or
            ticket_state.get("user_id")
    )

    if stored_user_id:
        try:
            stored_user_id = int(stored_user_id)
        except (ValueError, TypeError):
            print(f"[AttackStrategies] Error converting user_id: {stored_user_id}")
            pass

    if not stored_user_id or user_id != stored_user_id:
        await ctx.respond("❌ You cannot interact with this ticket.", ephemeral=True)
        return

    # Stop collecting strategies
    await mongo_client.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {
            "$set": {
                "step_data.questionnaire.collecting_strategies": False,
                "step_data.questionnaire.awaiting_response": False
            }
        }
    )

    # Get the current attack summary
    current_summary = ticket_state.get("step_data", {}).get("questionnaire", {}).get("attack_summary", "")

    # Build content again
    title = QUESTION_TITLE
    detailed_content = QUESTION_CONTENT()

    # Create final components without Done button and without ping
    final_components = create_attack_strategy_components(
        current_summary=current_summary,
        title=title,
        detailed_content=detailed_content,
        show_done_button=False,
        include_user_ping=False  # No ping on final version
    )

    # Update the message to remove the Done button
    await ctx.interaction.edit_initial_response(components=final_components)

    # Wait and move to next question
    await asyncio.sleep(2)

    # Move to next question
    from ..core import questionnaire_manager
    next_question = "future_clan_expectations"  # Next question after attack strategies
    if next_question:
        await questionnaire_manager.send_question(channel_id, user_id, next_question)

    print(f"[AttackStrategies] User {user_id} completed attack strategies")