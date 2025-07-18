# extensions/events/message/ticket_automation/handlers/age_bracket.py
"""
Handles age bracket selection with themed GIF responses.
Provides different responses based on age selection.
"""

import asyncio
from typing import Optional, Dict, Any
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

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None

# Self-contained age bracket responses
AGE_BRACKET_RESPONSES = {
    "16_under": {
        "title": "🎉 **16 & Under Registered!**",
        "content": (
            "Got it! You're bringing that youthful energy!\n\n"
            "We'll find you a family-friendly clan that's the perfect fit for you.\n\n"
        ),
        "gif": "https://c.tenor.com/oxxT2JPSQccAAAAC/tenor.gif"
    },
    "17_25": {
        "title": "🎮 **17–25 Confirmed**",
        "content": (
            "Understood! You're in prime gaming years!\n\n"
            "Time to conquer the Clash world! 🏆\n\n"
        ),
        "gif": "https://c.tenor.com/twdtlMLE8UIAAAAC/tenor.gif"
    },
    "over_25": {
        "title": "🏅 **Age Locked In**",
        "content": (
            "Awesome! Experience meets strategy!\n\n"
            "Welcome to the veteran league of Clashers! 💪\n\n"
        ),
        "gif": "https://c.tenor.com/m6o-4dKGdVAAAAAC/tenor.gif"
    }
}

# Self-contained question data
AGE_BRACKET_QUESTION = {
    "title": "## ⏳ **What's Your Age Bracket?**",
    "content": "**What age bracket do you fall into?**\n\n",
}


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_age_bracket_question(channel_id: int, user_id: int) -> None:
    """Send the age bracket selection question"""

    if not bot_instance or not mongo_client:
        print("[AgeBracket] Error: Bot not initialized")
        return

    try:
        # Update state
        await mongo_client.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {
                "$set": {
                    "step_data.questionnaire.current_question": "age_bracket",
                    "step_data.questionnaire.awaiting_response": False  # No text response needed
                }
            }
        )

        # Build components using self-contained data
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"<@{user_id}>"),
                    Separator(divider=True),
                    Text(content=AGE_BRACKET_QUESTION["title"]),
                    Separator(divider=True),
                    Text(content=AGE_BRACKET_QUESTION["content"]),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right} "
                                    "**16 & Under** *(Family-Friendly Clan)*"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧒16 & Under",
                            custom_id=f"age_questionnaire:16_under_{channel_id}_{user_id}",
                        ),
                    ),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right} "
                                    "**17 – 25**"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧑17 – 25",
                            custom_id=f"age_questionnaire:17_25_{channel_id}_{user_id}",
                        ),
                    ),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right} "
                                    "**Over 25**"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧓Over 25",
                            custom_id=f"age_questionnaire:over_25_{channel_id}_{user_id}",
                        ),
                    ),
                    Text(
                        content="*Don't worry, we're not knocking on your door! Just helps us get to know you better.*"
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")])
                ]
            )
        ]

        # Send message
        channel = await bot_instance.rest.fetch_channel(channel_id)
        msg = await channel.send(
            components=components,
            user_mentions=True
        )

        # Store message ID
        await StateManager.store_message_id(
            str(channel_id),
            "questionnaire_age_bracket",
            str(msg.id)
        )

        print(f"[AgeBracket] Sent question to channel {channel_id}")

    except Exception as e:
        print(f"[AgeBracket] Error sending question: {e}")
        import traceback
        traceback.print_exc()


@register_action("age_questionnaire", no_return=True)
async def handle_age_bracket_selection(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Handle when user selects an age bracket"""

    parts = action_id.split("_")
    bracket = f"{parts[0]}_{parts[1]}"  # e.g. "16_under", "17_25", "over_25"
    channel_id = parts[2]
    user_id = parts[3]

    # Verify this is the correct user
    if ctx.user.id != int(user_id):
        await ctx.respond(
            "❌ This button is only for the ticket owner to click.",
            ephemeral=True
        )
        return

    # Use self-contained responses
    response = AGE_BRACKET_RESPONSES.get(bracket)
    if not response:
        await ctx.respond("❌ Invalid age bracket selection.", ephemeral=True)
        return

    # Store the age bracket in MongoDB
    await mongo_client.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {
            "$set": {
                "step_data.questionnaire.responses.age_bracket": bracket,
                "step_data.questionnaire.age_bracket": bracket
            }
        }
    )

    # Create response components
    response_components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=f"<@{user_id}>"),
                Separator(divider=True),
                Text(content=response["title"]),
                Text(content=response["content"]),
                Media(items=[MediaItem(media=response["gif"])]),
                Text(content="-# Age bracket registered successfully!"),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    # Delete interaction and send new message
    await ctx.interaction.delete_initial_response()

    channel = await bot_instance.rest.fetch_channel(int(channel_id))
    await channel.send(
        components=response_components,
        user_mentions=True
    )

    # Wait before next question
    await asyncio.sleep(5)

    # Determine next step based on flow
    await proceed_to_next_question(channel_id, user_id)

    print(f"[AgeBracket] User {user_id} selected age bracket: {bracket}")


async def proceed_to_next_question(channel_id: str, user_id: str) -> None:
    """Determine and proceed to the next question in the flow"""

    # Check if we're in FWA flow
    ticket_state = await mongo_client.ticket_automation_state.find_one({"_id": str(channel_id)})
    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})

    if fwa_data.get("current_fwa_step") == "age_bracket":
        # We're in FWA flow, route to timezone through FWA
        print(f"[AgeBracket] Routing to FWA timezone")
        from ..fwa.core.fwa_flow import FWAFlow
        await FWAFlow.handle_questionnaire_completion(int(channel_id), int(user_id))
    else:
        # Normal flow - send timezone question directly
        from .timezone import send_timezone_question
        await send_timezone_question(int(channel_id), int(user_id))