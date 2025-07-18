# extensions/events/message/ticket_automation/core/question_flow.py
"""
Manages the flow of questions in the questionnaire.
Handles routing to appropriate handlers based on question type.
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT
from ..utils.flow_map import get_next_question, is_final_question, get_flow_type
from .state_manager import StateManager

# Import specific handlers
from ..handlers import (
    attack_strategies,
    clan_expectations,
    discord_skills,
    age_bracket,
    timezone,
    completion
)

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


class QuestionFlow:
    """Manages the flow and routing of questionnaire questions"""

    # Map question types to their handlers
    QUESTION_HANDLERS = {
        # Normal questionnaire handlers
        "attack_strategies": attack_strategies.send_attack_strategies,
        "future_clan_expectations": clan_expectations.send_clan_expectations,
        "discord_basic_skills": discord_skills.send_discord_skills_question,
        "discord_basic_skills_2": None,  # Handled by standard flow
        "age_bracket": age_bracket.send_age_bracket_question,
        "timezone": timezone.send_timezone_question,
        "leaders_checking_you_out": None,  # Will be handled by completion handler
    }

    @classmethod
    def initialize(cls, mongo: MongoClient, bot: hikari.GatewayBot):
        """Initialize the question flow manager"""
        global mongo_client, bot_instance
        mongo_client = mongo
        bot_instance = bot

        # Initialize all handlers
        attack_strategies.initialize(mongo, bot)
        clan_expectations.initialize(mongo, bot)
        discord_skills.initialize(mongo, bot)
        age_bracket.initialize(mongo, bot)
        timezone.initialize(mongo, bot)
        completion.initialize(mongo, bot)

    @classmethod
    async def send_next_question(cls, channel_id: int, user_id: int, current_question: str) -> None:
        """Send the next question in the flow"""
        try:
            # Get ticket state to determine flow type
            ticket_state = await StateManager.get_ticket_state(str(channel_id))
            if not ticket_state:
                print(f"[QuestionFlow] No ticket state found for channel {channel_id}")
                return

            # Determine if we're in FWA flow
            is_fwa, fwa_step = get_flow_type(ticket_state)

            # Get the next question key using flow map
            next_question = get_next_question(current_question, is_fwa, fwa_step)

            if not next_question:
                print(f"[QuestionFlow] End of flow after {current_question}")
                # If this is the end, ensure completion is handled
                if current_question == "timezone" and not is_fwa:
                    # Normal flow ends with leaders_checking_you_out
                    await cls.send_question(channel_id, user_id, "leaders_checking_you_out")
                return

            print(f"[QuestionFlow] Next question after {current_question}: {next_question} (FWA: {is_fwa})")
            await cls.send_question(channel_id, user_id, next_question)

        except Exception as e:
            print(f"[QuestionFlow] Error sending next question: {e}")
            import traceback
            traceback.print_exc()

    @classmethod
    async def send_question(cls, channel_id: int, user_id: int, question_key: str) -> None:
        """Send a specific question"""
        try:
            print(f"[QuestionFlow] Sending question: {question_key}")

            # Update current question in state
            await StateManager.set_current_question(channel_id, question_key)

            # Special case: leaders_checking_you_out should go straight to completion handler
            if question_key == "leaders_checking_you_out":
                print(f"[QuestionFlow] Routing to completion handler for leaders message")
                await completion.send_completion_message(channel_id, user_id)
                return

            # Special case: completion (for FWA)
            if question_key == "completion":
                # Check if this is FWA completion
                ticket_state = await StateManager.get_ticket_state(str(channel_id))
                is_fwa, _ = get_flow_type(ticket_state)

                if is_fwa:
                    # Use FWA completion
                    from ..fwa.handlers.completion import send_fwa_completion
                    thread_id = ticket_state["ticket_info"]["thread_id"]
                    await send_fwa_completion(channel_id, thread_id, user_id)
                else:
                    # Use normal completion
                    await completion.send_completion_message(channel_id, user_id)
                return

            # Check if we have a specific handler for this question
            handler = cls.QUESTION_HANDLERS.get(question_key)
            if handler:
                await handler(channel_id, user_id)
            else:
                # For FWA-specific questions, route to FWA handlers
                if question_key in ["fwa_explanation", "lazy_cwl", "agreement"]:
                    await cls._handle_fwa_question(channel_id, user_id, question_key)
                else:
                    # Use standard question flow (if we still have any)
                    print(f"[QuestionFlow] No handler for question: {question_key}")

        except Exception as e:
            print(f"[QuestionFlow] Error sending question {question_key}: {e}")
            import traceback
            traceback.print_exc()

    @classmethod
    async def _handle_fwa_question(cls, channel_id: int, user_id: int, question_key: str) -> None:
        """Handle FWA-specific questions"""
        try:
            ticket_state = await StateManager.get_ticket_state(str(channel_id))
            thread_id = ticket_state["ticket_info"]["thread_id"]

            if question_key == "fwa_explanation":
                from ..fwa.handlers.fwa_explanation import send_fwa_explanation
                await send_fwa_explanation(channel_id, thread_id, user_id)
            elif question_key == "lazy_cwl":
                from ..fwa.handlers.lazy_cwl import send_lazy_cwl_explanation
                await send_lazy_cwl_explanation(channel_id, thread_id, user_id)
            elif question_key == "agreement":
                from ..fwa.handlers.agreement import send_agreement_message
                await send_agreement_message(channel_id, thread_id, user_id)

        except Exception as e:
            print(f"[QuestionFlow] Error handling FWA question {question_key}: {e}")
            import traceback
            traceback.print_exc()

    @classmethod
    def get_next_question(cls, current_question: str, is_fwa: bool = False) -> Optional[str]:
        """Get the next question in the flow"""
        return get_next_question(current_question, is_fwa)

    @classmethod
    def is_final_question(cls, question_key: str, is_fwa: bool = False) -> bool:
        """Check if this is the final question"""
        return is_final_question(question_key, is_fwa)