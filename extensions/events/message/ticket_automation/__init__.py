# extensions/events/message/ticket_automation/__init__.py
# DISABLED - 2025-07-25 - Not currently needed, using manual /recruit questions instead
"""
Ticket automation system for recruitment process.
"""

from typing import Optional
import hikari
from utils.mongo import MongoClient

# Import core functions that need to be exposed
from .core.questionnaire_manager import (
    trigger_questionnaire,
    send_interview_selection_prompt
)

# Global instances for initialization
_mongo_client: Optional[MongoClient] = None
_bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo_client: MongoClient, bot: hikari.GatewayBot):
    """
    Initialize the ticket automation system.

    Args:
        mongo_client: MongoDB client instance
        bot: Hikari bot instance
    """
    global _mongo_client, _bot_instance
    _mongo_client = mongo_client
    _bot_instance = bot

    # Initialize all sub-modules
    from .core import questionnaire_manager, state_manager, question_flow
    from .handlers import (
        interview_selection,
        attack_strategies,
        clan_expectations,
        discord_skills,
        age_bracket,
        timezone,
        completion
    )

    # Initialize core modules
    questionnaire_manager.initialize(mongo_client, bot)
    state_manager.StateManager.initialize(mongo_client, bot)
    question_flow.QuestionFlow.initialize(mongo_client, bot)

    # Initialize all handlers (they take mongo and bot, not state_manager)
    interview_selection.initialize(mongo_client, bot)
    attack_strategies.initialize(mongo_client, bot)
    clan_expectations.initialize(mongo_client, bot)
    discord_skills.initialize(mongo_client, bot)
    age_bracket.initialize(mongo_client, bot)
    timezone.initialize(mongo_client, bot)
    completion.initialize(mongo_client, bot)

    print("[Ticket Automation] All modules initialized")


# Export public API
__all__ = [
    'initialize',
    'trigger_questionnaire',
    'send_interview_selection_prompt'
]