# extensions/events/message/message_events.py
"""
Message event handlers for how-to-ping and goblin challenge.
"""

import hikari
import lightbulb
from typing import Optional

from utils.mongo import MongoClient
from utils import bot_data

from . import goblin_challenge
from . import how_to_ping

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
        goblin_challenge.initialize(mongo_client, bot_instance)  # Initialize goblin challenge handler
        how_to_ping.initialize(bot_instance, mongo_client)  # Initialize how to ping handler
        is_initialized = True  # Mark as initialized


@loader.listener(hikari.StartingEvent)
async def on_starting(event: hikari.StartingEvent):
    """Initialize on bot startup."""
    _initialize_from_bot_data()
    print("[Message Events] Goblin challenge and How to ping handlers initialized")


@loader.listener(hikari.GuildMessageCreateEvent)
async def on_questionnaire_response(event: hikari.GuildMessageCreateEvent):
    """Handle guild messages for how-to-ping and goblin challenge."""

    # Initialize if not already done
    if not is_initialized:
        _initialize_from_bot_data()

    if not mongo_client or not bot_instance or not is_initialized:
        return

    # Check for how to ping FIRST (highest priority)
    if await how_to_ping.check_how_to_ping(event):
        print("[Message Events] Message handled by how to ping system")
        return

    # Check for goblin challenge
    if await goblin_challenge.check_goblin_challenge(event):
        print("[Message Events] Message handled by goblin challenge system")
        return
