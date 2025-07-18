# extensions/events/message/ticket_automation/fwa/core/fwa_manager.py
"""
Main FWA automation manager that orchestrates the FWA recruitment flow.
Integrates with existing ticket automation system.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import hikari

from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, GOLD_ACCENT
from ...core.state_manager import StateManager
from ..utils.fwa_constants import FWA_TICKET_PATTERN, FWA_STEPS
from ..utils.chocolate_utils import generate_chocolate_link
from .fwa_flow import FWAFlow, FWAStep

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize_fwa(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the FWA automation system"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot

    # Initialize FWA flow
    FWAFlow.initialize(mongo, bot)

    # Initialize all FWA handlers
    from ..handlers import (
        war_weight,
        fwa_explanation,
        lazy_cwl,
        agreement,
        completion
    )

    war_weight.initialize(mongo, bot)
    fwa_explanation.initialize(mongo, bot)
    lazy_cwl.initialize(mongo, bot)
    agreement.initialize(mongo, bot)
    completion.initialize(mongo, bot)


def is_fwa_ticket(channel_name: str) -> bool:
    """Check if a channel is an FWA ticket"""
    return FWA_TICKET_PATTERN in channel_name or "𝕋-𝔽𝕎𝔸" in channel_name  # Include test pattern


async def trigger_fwa_automation(
        channel_id: int,
        thread_id: int,
        user_id: int,
        ticket_info: Dict[str, Any]
) -> bool:
    """
    Trigger FWA automation flow after screenshot upload.
    This is called from ticket_screenshot.py for FWA tickets.
    """
    if not mongo_client or not bot_instance:
        print("[FWA Manager] Not initialized")
        return False

    try:
        # Get user tag from ticket info
        user_tag = ticket_info.get("user_tag")
        if not user_tag:
            print(f"[FWA Manager] No user tag found for channel {channel_id}")
            return False

        # Send chocolate clash link immediately
        chocolate_url = generate_chocolate_link(user_tag, is_player=True)

        link_components = [
            {
                "type": hikari.ComponentType.ACTION_ROW,
                "components": [{
                    "type": hikari.ComponentType.LINK_BUTTON,
                    "url": chocolate_url,
                    "label": "View FWA Status"
                }]
            }
        ]

        # Send to thread
        await bot_instance.rest.create_message(
            channel=thread_id,
            content=f"🍫 **FWA Chocolate Clash Link:**\n{chocolate_url}",
            component=link_components
        )

        # Update state to FWA war weight collection
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                "automation_state.current_step": "fwa_war_weight",
                "step_data.fwa": {
                    "started": True,
                    "chocolate_link_sent": True,
                    "current_fwa_step": FWAStep.WAR_WEIGHT.value
                }
            }
        )

        # Start FWA flow with war weight request
        await FWAFlow.start_fwa_flow(channel_id, thread_id, user_id)

        print(f"[FWA Manager] Successfully triggered FWA automation for channel {channel_id}")
        return True

    except Exception as e:
        print(f"[FWA Manager] Error triggering automation: {e}")
        import traceback
        traceback.print_exc()
        return False


async def handle_fwa_text_response(event: hikari.GuildMessageCreateEvent, ticket_state: dict) -> bool:
    """
    Handle text responses during FWA flow.
    Returns True if message was handled, False otherwise.
    """
    if not ticket_state:
        return False

    # Get current FWA step
    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
    current_step = fwa_data.get("current_fwa_step")

    if not current_step:
        return False

    # Get ticket info for thread_id
    ticket_info = ticket_state.get("ticket_info", {})
    thread_id = ticket_info.get("thread_id")
    channel_id = event.channel_id
    user_id = event.author_id

    # Route to appropriate handler based on current step
    content = event.content.strip().lower()

    if current_step == FWAStep.FWA_EXPLANATION.value and content == "understood":
        # Proceed to Lazy CWL explanation
        await FWAFlow.proceed_to_next_step(
            channel_id,
            thread_id,
            user_id,
            FWAStep.LAZY_CWL
        )
        return True

    elif current_step == FWAStep.LAZY_CWL.value and content == "understood":
        # Proceed to Agreement
        await FWAFlow.proceed_to_next_step(
            channel_id,
            thread_id,
            user_id,
            FWAStep.AGREEMENT
        )
        return True

    elif current_step == FWAStep.AGREEMENT.value and content == "i agree":
        # NEW: Proceed to Discord Skills instead of Completion
        await FWAFlow.proceed_to_next_step(
            channel_id,
            thread_id,
            user_id,
            FWAStep.DISCORD_SKILLS  # Changed from COMPLETION
        )
        return True

    return False