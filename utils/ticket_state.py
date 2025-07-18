# utils/ticket_state.py

from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, timezone


class TicketStep(Enum):
    """Enum for ticket automation steps"""
    AWAITING_SCREENSHOT = "awaiting_screenshot"
    ACCOUNT_COLLECTION = "account_collection"
    QUESTIONNAIRE = "questionnaire"
    CLAN_SELECTION = "clan_selection"
    REVIEW = "review"
    FINAL_PLACEMENT = "final_placement"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TicketStatus(Enum):
    """Enum for ticket automation status"""
    ACTIVE = "active"
    HALTED = "halted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TicketState:
    """Manages ticket automation state"""

    STEP_ORDER = [
        TicketStep.AWAITING_SCREENSHOT,
        TicketStep.ACCOUNT_COLLECTION,
        TicketStep.QUESTIONNAIRE,
        TicketStep.CLAN_SELECTION,
        TicketStep.REVIEW,
        TicketStep.FINAL_PLACEMENT,
        TicketStep.COMPLETED
    ]

    @staticmethod
    def get_next_step(current_step: str) -> Optional[str]:
        """Get the next step in the automation flow"""
        try:
            current = TicketStep(current_step)
            current_index = TicketState.STEP_ORDER.index(current)

            if current_index < len(TicketState.STEP_ORDER) - 1:
                return TicketState.STEP_ORDER[current_index + 1].value
            return None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def create_initial_state(
            channel_id: int,
            thread_id: int,
            user_id: int,
            ticket_type: str,
            ticket_number: int,
            user_tag: Optional[str] = None,
            player_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create initial ticket automation state document"""
        return {
            "_id": str(channel_id),
            "ticket_info": {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "user_tag": user_tag,
                "player_name": player_name,
                "ticket_type": ticket_type,
                "ticket_number": ticket_number,
                "created_at": datetime.now(timezone.utc)
            },
            "automation_state": {
                "current_step": TicketStep.AWAITING_SCREENSHOT.value,
                "status": TicketStatus.ACTIVE.value,
                "completed_steps": [],
                "halted_reason": None,
                "halted_at": None
            },
            "step_data": {
                "screenshot": {
                    "uploaded": False,
                    "reminder_sent": False,
                    "reminder_count": 0,
                    "last_reminder": None
                },
                "account_collection": {
                    "started": False,
                    "completed": False,
                    "additional_accounts": []
                },
                "questionnaire": {
                    "started": False,
                    "completed": False,
                    "interview_type": None,  # "bot_driven" or "recruiter"
                    "current_question": None,
                    "awaiting_response": False,
                    "responses": {
                        # Will be populated with:
                        # "attack_strategies": "user response",
                        # "future_clan_expectations": "user response",
                        # "discord_basic_skills": "completed_requirements",
                        # "discord_basic_skills_2": "user response",
                        # "age_bracket_timezone": "user response",
                        # "leaders_checking_you_out": "acknowledged"
                    },
                    # Special tracking for discord skills
                    "discord_skills_reaction": False,
                    "discord_skills_mention": False
                },
                "clan_selection": {
                    "started": False,
                    "completed": False,
                    "selected_clan": None
                },
                "review": {
                    "started": False,
                    "completed": False,
                    "reviewer": None,
                    "notes": None
                },
                "final_placement": {
                    "completed": False,
                    "placed_clan": None,
                    "placed_by": None,
                    "placed_at": None
                }
            },
            "messages": {
                "screenshot_reminder": None,
                "account_collection": None,
                "interview_selection": None,
                "questionnaire_attack_strategies": None,
                "questionnaire_future_clan_expectations": None,
                "questionnaire_discord_basic_skills": None,
                "questionnaire_discord_basic_skills_2": None,
                "questionnaire_age_bracket_timezone": None,
                "questionnaire_leaders_checking_you_out": None,
                "clan_selection": None
            },
            "interaction_history": []
        }

    @staticmethod
    def update_step_completion(
            state: Dict[str, Any],
            step: str,
            data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update state when a step is completed"""
        update = {
            "$set": {
                f"step_data.{step}.completed": True,
                f"step_data.{step}.completed_at": datetime.now(timezone.utc)
            },
            "$addToSet": {
                "automation_state.completed_steps": step
            },
            "$push": {
                "interaction_history": {
                    "timestamp": datetime.now(timezone.utc),
                    "action": f"{step}_completed",
                    "details": data or {}
                }
            }
        }

        # Move to next step
        next_step = TicketState.get_next_step(state["automation_state"]["current_step"])
        if next_step:
            update["$set"]["automation_state.current_step"] = next_step

        return update

    @staticmethod
    def halt_automation(
            reason: str,
            details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create update to halt automation"""
        return {
            "$set": {
                "automation_state.status": TicketStatus.HALTED.value,
                "automation_state.halted_reason": reason,
                "automation_state.halted_at": datetime.now(timezone.utc)
            },
            "$push": {
                "interaction_history": {
                    "timestamp": datetime.now(timezone.utc),
                    "action": "automation_halted",
                    "reason": reason,
                    "details": details or {}
                }
            }
        }

    @staticmethod
    def resume_automation() -> Dict[str, Any]:
        """Create update to resume automation"""
        return {
            "$set": {
                "automation_state.status": TicketStatus.ACTIVE.value,
                "automation_state.halted_reason": None,
                "automation_state.halted_at": None
            },
            "$push": {
                "interaction_history": {
                    "timestamp": datetime.now(timezone.utc),
                    "action": "automation_resumed",
                    "details": {}
                }
            }
        }

    @staticmethod
    def is_halted(state: Dict[str, Any]) -> bool:
        """Check if automation is halted"""
        return state.get("automation_state", {}).get("status") == TicketStatus.HALTED.value

    @staticmethod
    def get_current_step(state: Dict[str, Any]) -> Optional[str]:
        """Get the current step from state"""
        return state.get("automation_state", {}).get("current_step")

    @staticmethod
    def get_questionnaire_response(state: Dict[str, Any], question: str) -> Optional[str]:
        """Get a specific questionnaire response"""
        return state.get("step_data", {}).get("questionnaire", {}).get("responses", {}).get(question)