# extensions/events/message/ticket_automation/handlers/interview_selection.py

from typing import Optional
import hikari
import lightbulb
from datetime import datetime, timezone

from extensions.components import register_action
from utils.mongo import MongoClient
from ..core.state_manager import StateManager
from ..core import questionnaire_manager
from ..utils.constants import RECRUITMENT_STAFF_ROLE

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the interview selection handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


@register_action("select_bot_interview", no_return=True)
async def handle_bot_interview_selection(ctx: lightbulb.components.MenuContext, action_id: str, **kwargs):
    """Handle when user selects bot-driven interview"""

    # Extract channel_id and user_id from action_id
    parts = action_id.split("_")
    channel_id = parts[0]
    user_id = parts[1]

    # Verify this is the correct user
    if ctx.user.id != int(user_id):
        await ctx.respond(
            "❌ This is not your recruitment process.",
            ephemeral=True
        )
        return

    # Update the state
    await StateManager.update_questionnaire_data(int(channel_id), {
        "interview_type": "bot",
        "started": True
    })

    # Record interaction
    await StateManager.add_interaction(int(channel_id), "selected_bot_interview", {"user_id": user_id})

    # Check if this is an FWA ticket
    if bot_instance:
        channel = bot_instance.cache.get_guild_channel(int(channel_id))
        if channel:
            channel_name = channel.name if channel else ""
            print(f"[Interview Selection] Channel name: {channel_name}")

            is_fwa = any(pattern in channel_name for pattern in ["𝔽𝕎𝔸", "𝕋-𝔽𝕎𝔸"])
            print(f"[Interview Selection] Is FWA ticket: {is_fwa}")

            if is_fwa:
                # For FWA tickets, dynamically import and use FWA modules
                try:
                    from ..fwa.core import FWAFlow, FWAStep
                    print(f"[Interview Selection] FWA modules imported successfully")

                    # Get ticket state and continue to FWA education
                    print(f"[Interview Selection] This is an FWA ticket, proceeding to FWA flow...")
                    ticket_state = await StateManager.get_ticket_state(str(channel_id))
                    if ticket_state:
                        thread_id = ticket_state["ticket_info"]["thread_id"]
                        print(f"[Interview Selection] Thread ID: {thread_id}")
                        print(f"[Interview Selection] Continuing to FWA education flow")
                        await FWAFlow.proceed_to_next_step(
                            int(channel_id),
                            int(thread_id),
                            int(user_id),
                            FWAStep.FWA_EXPLANATION
                        )
                        return
                    else:
                        print(f"[Interview Selection] ERROR: No ticket state found!")
                except ImportError as e:
                    print(f"[Interview Selection] ERROR: Failed to import FWA modules: {e}")
                    print(f"[Interview Selection] Falling back to regular flow")

    # Regular flow - Send first question using questionnaire manager
    await questionnaire_manager.send_question(int(channel_id), int(user_id), "attack_strategies")


@register_action("select_recruiter_interview", no_return=True)
async def handle_recruiter_interview_selection(ctx: lightbulb.components.MenuContext, action_id: str, **kwargs):
    """Handle when user selects recruiter interview"""

    # Extract channel_id and user_id from action_id
    parts = action_id.split("_")
    channel_id = parts[0]
    user_id = parts[1]

    # Verify this is the correct user
    if ctx.user.id != int(user_id):
        await ctx.respond(
            "❌ This is not your recruitment process.",
            ephemeral=True
        )
        return

    # Update the state
    await StateManager.update_questionnaire_data(int(channel_id), {
        "interview_type": "recruiter",
        "started": True
    })

    # Check if this is an FWA ticket
    if bot_instance:
        channel = bot_instance.cache.get_guild_channel(int(channel_id))
        if channel:
            channel_name = channel.name if channel else ""
            is_fwa = any(pattern in channel_name for pattern in ["𝔽𝕎𝔸", "𝕋-𝔽𝕎𝔸"])

            if is_fwa:
                # For FWA tickets, mark that we need to continue to FWA education after recruiter interview
                await StateManager.update_ticket_state(
                    str(channel_id),
                    {"step_data.fwa.pending_fwa_education": True}
                )

    # Halt automation for manual handling
    await StateManager.halt_automation(int(channel_id), "User selected recruiter interview")

    # Notify recruitment staff
    await ctx.respond(
        f"<@&{RECRUITMENT_STAFF_ROLE}> {ctx.user.mention} has requested a live interview!",
        role_mentions=True
    )