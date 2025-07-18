# extensions/events/message/ticket_automation/fwa/core/fwa_flow.py
"""
FWA flow controller that manages progression through FWA-specific steps.
"""

from enum import Enum
from typing import Optional
import hikari

from utils.mongo import MongoClient
from ...core.state_manager import StateManager
from ...core.questionnaire_manager import send_interview_selection_prompt

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


class FWAStep(Enum):
    """FWA automation flow steps"""
    WAR_WEIGHT = "war_weight"
    ACCOUNT_COLLECTION = "account_collection"
    INTERVIEW_SELECTION = "interview_selection"
    FWA_EXPLANATION = "fwa_explanation"
    LAZY_CWL = "lazy_cwl"
    AGREEMENT = "agreement"
    # NEW STEPS - Same as normal questionnaire
    DISCORD_SKILLS = "discord_skills"
    AGE_BRACKET = "age_bracket"
    TIMEZONE = "timezone"
    COMPLETION = "completion"


class FWAFlow:
    """Manages FWA automation flow progression"""

    @classmethod
    def initialize(cls, mongo: MongoClient, bot: hikari.GatewayBot):
        """Initialize the FWA flow manager"""
        global mongo_client, bot_instance
        mongo_client = mongo
        bot_instance = bot

    @classmethod
    async def start_fwa_flow(cls, channel_id: int, thread_id: int, user_id: int):
        """Start the FWA flow with war weight request"""
        from ..handlers.war_weight import send_war_weight_request
        await send_war_weight_request(channel_id, thread_id, user_id)

    @classmethod
    async def proceed_to_next_step(
            cls,
            channel_id: int,
            thread_id: int,
            user_id: int,
            next_step: FWAStep
    ):
        """Proceed to the next step in FWA flow"""
        if not mongo_client or not bot_instance:
            print("[FWA Flow] Not initialized")
            return

        # Update state
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                f"step_data.fwa.current_fwa_step": next_step.value,
                f"step_data.fwa.{next_step.value}_started": True
            }
        )

        # Route to appropriate handler
        if next_step == FWAStep.ACCOUNT_COLLECTION:
            # Trigger existing account collection
            from ...ticket_account_collection import trigger_account_collection
            ticket_state = await StateManager.get_ticket_state(str(channel_id))
            if ticket_state:
                await trigger_account_collection(
                    channel_id=channel_id,
                    user_id=user_id,
                    ticket_info=ticket_state["ticket_info"]
                )

        elif next_step == FWAStep.INTERVIEW_SELECTION:
            # Use existing interview selection
            await send_interview_selection_prompt(channel_id, user_id)
            # After interview selection, we'll continue to FWA explanation
            await StateManager.update_ticket_state(
                str(channel_id),
                {"step_data.fwa.pending_fwa_education": True}
            )

        elif next_step == FWAStep.FWA_EXPLANATION:
            from ..handlers.fwa_explanation import send_fwa_explanation
            await send_fwa_explanation(channel_id, thread_id, user_id)

        elif next_step == FWAStep.LAZY_CWL:
            from ..handlers.lazy_cwl import send_lazy_cwl_explanation
            await send_lazy_cwl_explanation(channel_id, thread_id, user_id)

        elif next_step == FWAStep.AGREEMENT:
            from ..handlers.agreement import send_agreement_message
            await send_agreement_message(channel_id, thread_id, user_id)

        # NEW: Add discord skills, age bracket, and timezone
        elif next_step == FWAStep.DISCORD_SKILLS:
            # Use the existing discord skills handler from normal questionnaire
            from ...handlers.discord_skills import send_discord_skills_question
            await send_discord_skills_question(channel_id, user_id)

        elif next_step == FWAStep.AGE_BRACKET:
            # Use the existing age bracket handler
            from ...handlers.age_bracket import send_age_bracket_question
            await send_age_bracket_question(channel_id, user_id)

        elif next_step == FWAStep.TIMEZONE:
            # Use the existing timezone handler
            from ...handlers.timezone import send_timezone_question
            await send_timezone_question(channel_id, user_id)

        elif next_step == FWAStep.COMPLETION:
            from ..handlers.completion import send_fwa_completion
            await send_fwa_completion(channel_id, thread_id, user_id)

    @classmethod
    async def handle_interview_completion(cls, channel_id: int, user_id: int):
        """
        Called when interview (bot-driven or recruiter) is completed.
        Continues to FWA education flow.
        """
        ticket_state = await StateManager.get_ticket_state(str(channel_id))
        if not ticket_state:
            return

        # Check if we need to continue to FWA education
        fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
        if fwa_data.get("pending_fwa_education"):
            thread_id = ticket_state["ticket_info"]["thread_id"]
            await cls.proceed_to_next_step(
                channel_id,
                thread_id,
                user_id,
                FWAStep.FWA_EXPLANATION
            )

    @classmethod
    async def handle_questionnaire_completion(cls, channel_id: int, user_id: int):
        """
        Called when a questionnaire step (discord skills, age bracket, timezone) is completed.
        Routes to the next appropriate step.
        """
        ticket_state = await StateManager.get_ticket_state(str(channel_id))
        if not ticket_state:
            return

        fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
        current_step = fwa_data.get("current_fwa_step")
        thread_id = ticket_state["ticket_info"]["thread_id"]

        # Determine next step based on current step
        if current_step == FWAStep.DISCORD_SKILLS.value:
            await cls.proceed_to_next_step(channel_id, thread_id, user_id, FWAStep.AGE_BRACKET)
        elif current_step == FWAStep.AGE_BRACKET.value:
            await cls.proceed_to_next_step(channel_id, thread_id, user_id, FWAStep.TIMEZONE)
        elif current_step == FWAStep.TIMEZONE.value:
            await cls.proceed_to_next_step(channel_id, thread_id, user_id, FWAStep.COMPLETION)