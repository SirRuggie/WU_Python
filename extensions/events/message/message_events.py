# extensions/events/message/message_events.py
"""
Message event handlers for ticket automation.
"""

import hikari
import lightbulb
from typing import Optional

from utils.mongo import MongoClient
from utils import bot_data

# Import from refactored structure
from .ticket_automation import trigger_questionnaire, initialize as init_automation
from .ticket_automation.fwa import initialize_fwa, handle_fwa_text_response
from .ticket_automation.core import StateManager
from .ticket_automation.handlers import (
    timezone as timezone_handler,
    attack_strategies as attack_strategies_handler,
    clan_expectations as clan_expectations_handler,
    discord_skills as discord_skills_handler
)
from .ticket_automation.core.state_manager import is_awaiting_text_response

# Global instances - will be initialized from bot_data
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None
is_initialized: bool = False  # Track initialization status
loader = lightbulb.Loader()


# Initialize on module load using bot_data
def _initialize_from_bot_data():
    """Initialize using bot_data if available."""
    global mongo_client, bot_instance, is_initialized

    # Check if already initialized
    if is_initialized:
        return

    if "mongo" in bot_data.data:
        mongo_client = bot_data.data["mongo"]
    if "bot" in bot_data.data:
        bot_instance = bot_data.data["bot"]

    if mongo_client and bot_instance:
        StateManager.initialize(mongo_client, bot_instance)
        # Initialize all handlers
        init_automation(mongo_client, bot_instance)
        initialize_fwa(mongo_client, bot_instance)  # ADD THIS LINE!
        is_initialized = True  # Mark as initialized


@loader.listener(hikari.StartingEvent)
async def on_starting(event: hikari.StartingEvent):
    """Initialize on bot startup."""
    _initialize_from_bot_data()
    print("[Message Events] Ticket automation initialized")
    print("[Message Events] FWA automation initialized")  # Add this for confirmation


@loader.listener(hikari.GuildMessageCreateEvent)
async def on_questionnaire_response(event: hikari.GuildMessageCreateEvent):
    """Listen for questionnaire responses in ticket channels."""

    # Initialize if not already done
    if not is_initialized:
        _initialize_from_bot_data()

    if not mongo_client or not bot_instance or not is_initialized:
        return

    # Get ticket state using StateManager
    ticket_state = await StateManager.get_ticket_state(str(event.channel_id))
    if not ticket_state:
        return

    # SPECIAL HANDLING FOR BOT MESSAGES - Check Friend Time bot
    if event.is_bot:
        # Check if we're waiting for timezone confirmation
        if ticket_state.get("step_data", {}).get("questionnaire", {}).get("awaiting_timezone_confirmation", False):
            # Log bot messages for debugging
            content_preview = event.content[:100] if event.content else "(no content - possibly embed)"
            print(
                f"[Message Events] Bot message in channel {event.channel_id} from {event.author.username}: {content_preview}...")

            # Check for Friend Time bot confirmation
            if await timezone_handler.check_friend_time_confirmation(event):
                print("[Message Events] Friend Time confirmation processed")
                return
        # Skip other bot messages
        return

    # From here on, we're only dealing with user messages
    print(f"[Message Events] User message in channel {event.channel_id} from {event.author.username}")

    # Check for FWA text responses FIRST (before questionnaire check)
    if await handle_fwa_text_response(event, ticket_state):
        print("[Message Events] Message handled by FWA system")
        return

    # Check if automation is active
    automation_state = ticket_state.get("automation_state", {})
    if automation_state.get("status") != "active":
        print(f"[Message Events] Automation not active, status: {automation_state.get('status')}")
        return

    # Check if we're in questionnaire step
    if automation_state.get("current_step") != "questionnaire":
        print(f"[Message Events] Not in questionnaire step, current step: {automation_state.get('current_step')}")
        return

    # Get questionnaire data
    questionnaire_data = ticket_state.get("step_data", {}).get("questionnaire", {})
    current_question = questionnaire_data.get("current_question")

    print(f"[Message Events] Current question: {current_question}")

    if not current_question:
        return

    # Special handling for discord skills - check ANY message during this question
    if current_question == "discord_basic_skills":
        print(f"[Message Events] Processing Discord skills message from user {event.author_id}")

        # Get expected user from multiple locations
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
                print(f"[Message Events] Error converting expected_user: {expected_user}")
                expected_user = None

        print(f"[Message Events] Expected user: {expected_user}, Message author: {event.author_id}")

        # Check if it's the right user or if we don't have an expected user
        if not expected_user or event.author_id == expected_user:
            print(f"[Message Events] Calling check_mention_completion")
            # Check this message for mentions
            await discord_skills_handler.check_mention_completion(
                event.channel_id,
                event.author_id,
                event.message  # Pass the message object
            )
        else:
            print(f"[Message Events] User mismatch, skipping")
        return

    # Check if we're collecting attack strategies or clan expectations
    collecting_strategies = questionnaire_data.get("collecting_strategies", False)
    collecting_expectations = questionnaire_data.get("collecting_expectations", False)

    # Check if we're awaiting text response OR collecting AI responses
    if not (await is_awaiting_text_response(event.channel_id) or collecting_strategies or collecting_expectations):
        return

    # Validate user - check multiple locations
    expected_user = (
            ticket_state.get("discord_id") or
            ticket_state.get("user_id") or
            ticket_state.get("ticket_info", {}).get("user_id") or
            ticket_state.get("step_data", {}).get("user_id")
    )

    if expected_user:
        try:
            expected_user = int(expected_user)
            if event.author_id != expected_user:
                print(f"[Message Events] User mismatch: {event.author_id} != {expected_user}")
                return
        except (ValueError, TypeError):
            print(f"[Message Events] Error converting expected_user: {expected_user}")
            pass

    print(f"[Message Events] Processing response for question: {current_question}")
    print(
        f"[Message Events] Collecting strategies: {collecting_strategies}, Collecting expectations: {collecting_expectations}")

    # Route to appropriate handler based on collecting flags OR current question
    if collecting_strategies or current_question == "attack_strategies":
        print(f"[Message Events] Routing to attack strategies handler")
        await attack_strategies_handler.process_user_input(event.channel_id, event.author_id, event.content)
        # Delete the user's message after processing
        # try:
        #     await event.message.delete()
        # except:
        #     pass
    elif collecting_expectations or current_question == "future_clan_expectations":
        print(f"[Message Events] Routing to clan expectations handler")
        await clan_expectations_handler.process_user_input(event.channel_id, event.author_id, event.content)
        # Delete the user's message after processing
        # try:
        #     await event.message.delete()
        # except:
        #     pass
    # Other text-based questions are handled by their respective handlers


@loader.listener(hikari.GuildReactionAddEvent)
async def on_discord_skills_reaction(event: hikari.GuildReactionAddEvent):
    """Handle reactions for Discord skills verification."""

    # Initialize if not already done
    if not is_initialized:
        _initialize_from_bot_data()

    if not mongo_client or not bot_instance or not is_initialized:
        return

    # Call the handler to check the reaction
    await discord_skills_handler.check_reaction_completion(
        event.channel_id,
        event.user_id,
        event.message_id
    )