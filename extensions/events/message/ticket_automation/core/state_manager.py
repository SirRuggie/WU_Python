# extensions/events/message/ticket_automation/core/state_manager.py
"""
Centralized state management for ticket automation.
All database operations should go through this module.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone

from utils.mongo import MongoClient

# Global instances
mongo_client: Optional[MongoClient] = None


class StateManager:
    """Manages ticket automation state with MongoDB"""

    @classmethod
    def initialize(cls, mongo: MongoClient, bot):
        """Initialize the state manager"""
        global mongo_client
        mongo_client = mongo

    @classmethod
    async def get_ticket_state(cls, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket state from database"""
        if not mongo_client:
            return None
        return await mongo_client.ticket_automation_state.find_one({"_id": channel_id})

    @classmethod
    async def update_ticket_state(cls, channel_id: str, update_data: Dict[str, Any]) -> bool:
        """Update ticket state in database"""
        if not mongo_client:
            return False

        result = await mongo_client.ticket_automation_state.update_one(
            {"_id": channel_id},
            {"$set": update_data}
        )
        return result.modified_count > 0

    @classmethod
    async def create_ticket_state(cls, channel_id: str, initial_data: Dict[str, Any]) -> bool:
        """Create initial ticket state"""
        if not mongo_client:
            return False

        try:
            await mongo_client.ticket_automation_state.insert_one({
                "_id": channel_id,
                **initial_data,
                "created_at": datetime.now(timezone.utc)
            })
            return True
        except:
            return False

    @classmethod
    async def delete_ticket_state(cls, channel_id: str) -> bool:
        """Delete ticket state"""
        if not mongo_client:
            return False

        result = await mongo_client.ticket_automation_state.delete_one({"_id": channel_id})
        return result.deleted_count > 0

    @classmethod
    async def update_step(cls, channel_id: int, step_name: str, step_data: Dict[str, Any]) -> bool:
        """Update the current automation step"""
        if not mongo_client:
            return False

        try:
            # Prepare the update data
            update_dict = {
                "automation_state.current_step": step_name,
                "automation_state.last_updated": datetime.now(timezone.utc)
            }

            # Add step-specific data
            for key, value in step_data.items():
                update_dict[f"step_data.{step_name}.{key}"] = value

            result = await mongo_client.ticket_automation_state.update_one(
                {"_id": str(channel_id)},
                {"$set": update_dict}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"[StateManager] Error updating step: {e}")
            return False

    @classmethod
    async def set_current_question(cls, channel_id: str, question: str) -> bool:
        """Update current questionnaire question"""
        return await cls.update_ticket_state(
            channel_id,
            {"step_data.questionnaire.current_question": question}
        )

    @classmethod
    async def get_current_question(cls, channel_id: str) -> Optional[str]:
        """Get current questionnaire question"""
        state = await cls.get_ticket_state(channel_id)
        if state:
            return state.get("step_data", {}).get("questionnaire", {}).get("current_question")
        return None

    @classmethod
    async def store_response(cls, channel_id: str, question: str, response: Any) -> bool:
        """Store user response for a question"""
        return await cls.update_ticket_state(
            channel_id,
            {f"step_data.questionnaire.responses.{question}": response}
        )

    @classmethod
    async def get_response(cls, channel_id: str, question: str) -> Any:
        """Get user response for a question"""
        state = await cls.get_ticket_state(channel_id)
        if state:
            return state.get("step_data", {}).get("questionnaire", {}).get("responses", {}).get(question)
        return None

    @classmethod
    async def update_automation_status(cls, channel_id: str, status: str) -> bool:
        """Update automation status"""
        return await cls.update_ticket_state(
            channel_id,
            {"automation_state.status": status}
        )

    @classmethod
    async def store_message_id(cls, channel_id: str, message_key: str, message_id: str) -> bool:
        """Store message ID for later reference"""
        return await cls.update_ticket_state(
            channel_id,
            {f"messages.{message_key}": message_id}
        )

    @classmethod
    async def get_message_id(cls, channel_id: str, message_key: str) -> Optional[str]:
        """Get stored message ID"""
        state = await cls.get_ticket_state(str(channel_id))
        if state:
            msg_id = state.get("messages", {}).get(message_key)
            if msg_id:
                print(f"[StateManager] Found message ID for key '{message_key}': {msg_id}")
            else:
                print(
                    f"[StateManager] No message ID found for key '{message_key}'. Available keys: {list(state.get('messages', {}).keys())}")
            return msg_id
        return None




    @classmethod
    async def update_questionnaire_data(cls, channel_id: int, data: dict) -> bool:
        """Update questionnaire data in the ticket automation state."""
        if not mongo_client:
            return False

        try:
            # Build the update dict with proper paths
            update_dict = {}
            for key, value in data.items():
                update_dict[f"step_data.questionnaire.{key}"] = value

            result = await mongo_client.ticket_automation_state.update_one(
                {"_id": str(channel_id)},
                {"$set": update_dict},
                upsert=True
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"[StateManager] Error updating questionnaire data: {e}")
            return False





    @classmethod
    async def add_interaction(cls, channel_id: str, interaction_type: str, user_id: int,
                              details: Optional[Dict[str, Any]] = None) -> bool:
        """Log an interaction"""
        if not mongo_client:
            return False

        interaction = {
            "type": interaction_type,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc),
            "details": details or {}
        }

        result = await mongo_client.ticket_automation_state.update_one(
            {"_id": channel_id},
            {"$push": {"interactions": interaction}}
        )
        return result.modified_count > 0

    @classmethod
    async def get_user_id(cls, channel_id: str) -> Optional[int]:
        """Get user ID from ticket state"""
        state = await cls.get_ticket_state(str(channel_id))
        if state:
            # Try multiple locations for user ID
            user_id = (
                    state.get("discord_id") or
                    state.get("ticket_info", {}).get("user_id") or
                    state.get("user_id")
            )

            # Convert to int if stored as string
            if user_id:
                try:
                    return int(user_id)
                except (ValueError, TypeError):
                    pass
        return None

    @classmethod
    async def halt_automation(cls, channel_id: int, reason: str) -> bool:
        """Halt the automation process"""
        if not mongo_client:
            return False

        try:
            result = await mongo_client.ticket_automation_state.update_one(
                {"_id": str(channel_id)},
                {
                    "$set": {
                        "automation_state.status": "halted",
                        "automation_state.halt_reason": reason,
                        "automation_state.halted_at": datetime.now(timezone.utc)
                    }
                }
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"[StateManager] Error halting automation: {e}")
            return False


# Add this function at the module level (not inside StateManager class)
async def is_awaiting_text_response(channel_id: int) -> bool:
    """Check if waiting for text input from user"""
    if not mongo_client:
        return False

    state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
    if not state:
        return False

    # Check if we're in questionnaire
    questionnaire = state.get("step_data", {}).get("questionnaire", {})

    # Check for collecting flags FIRST (these are always text input)
    collecting_strategies = questionnaire.get("collecting_strategies", False)
    collecting_expectations = questionnaire.get("collecting_expectations", False)

    if collecting_strategies or collecting_expectations:
        return True

    # Then check if awaiting response for text questions
    if not questionnaire.get("awaiting_response"):
        return False

    # Text-based questions that collect continuous input
    current_question = questionnaire.get("current_question")
    text_questions = ["attack_strategies", "future_clan_expectations"]

    return current_question in text_questions