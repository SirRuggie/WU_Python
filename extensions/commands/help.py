# extensions/commands/help.py
"""
Integrated help command with AI support using Anthropic Claude.
Lists all bot commands and provides an AI assistant for questions.
"""

import os
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

import hikari
import lightbulb

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ModalActionRowBuilder as ModalActionRow,
)

from extensions.components import register_action
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT
from utils.mongo import MongoClient
from utils.emoji import emojis

loader = lightbulb.Loader()

# AI Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
AI_MODEL = "claude-3-haiku-20240307"
MAX_TOKENS = 1500

# Help categories
HELP_CATEGORIES = {
    "clan": {
        "name": "Clan Management",
        "emoji": "🏰",
        "description": "Commands to manage your clans"
    },
    "recruit": {
        "name": "Recruitment",
        "emoji": "👥",
        "description": "Commands for recruiting new players"
    },
    "fwa": {
        "name": "FWA",
        "emoji": "⚔️",
        "description": "Farm War Alliance base layouts"
    },
    "general": {
        "name": "General",
        "emoji": "📋",
        "description": "Other helpful commands"
    }
}

# Predefined command list (since dynamic discovery might be complex)
COMMAND_LIST = {
    "clan": [
        ("/clan dashboard", "Open the Clan Management Dashboard - has buttons for clan points, FWA data, and more"),
        ("/clan list", "Shows a list of all clans with their info"),
        ("/clan info-hub", "Display clan information hub - has buttons for Main, Feeder, Zen, FWA, and Trial clans"),
        ("/clan recruit-points",
         "Report recruitment activities for clan points - choose from Discord posts, DMs, helping, etc."),
    ],
    "recruit": [
        ("/recruit questions",
         "Send recruit questions to a new recruit - includes FWA questions, attack strategies, etc."),
        ("/recruit bidding", "Start a bidding process for available recruits - clan leaders bid points"),
    ],
    "fwa": [
        ("/fwa bases", "Select and display FWA base layouts - pick a user then select TH level"),
        ("/fwa upload-images", "Upload war and active base images for a TH level"),
        ("/fwa war-plans", "Manage FWA war plans - add or view war strategies"),
    ],
    "general": [
        ("/help", "Show this help menu - you're using it right now!"),
        ("/say", "Send a message as the bot (only for staff)"),
        ("/den-den-mushi", "Broadcast a message to everyone"),
    ]
}


async def create_help_menu_components(selected_category: Optional[str] = None) -> list:
    """Create the help menu components with category selector."""
    components = []

    # Header
    components.extend([
        Text(content="# 📚 Bot Help Center"),
        Text(content="Pick a category below OR ask the AI helper for help! 🤖"),
        Text(content="💡 **Tip:** The AI helper can tell you exactly which buttons to click!"),
        Separator(),
    ])

    # Category selector
    select_options = []
    for cat_id, cat_info in HELP_CATEGORIES.items():
        select_options.append(
            SelectOption(
                label=cat_info["name"],
                value=cat_id,
                description=cat_info["description"],
                emoji=cat_info["emoji"],
                is_default=(cat_id == selected_category)
            )
        )

    components.extend([
        ActionRow(
            components=[
                TextSelectMenu(
                    custom_id="help_category_select:menu",
                    placeholder="Pick a category to see commands...",
                    options=select_options
                )
            ]
        ),
        Separator(),
    ])

    # Action buttons
    components.append(
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id="help_ai_assistant:main",
                    label="Ask the AI Helper",
                    emoji="🤖"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="help_refresh:main",
                    label="Refresh",
                    emoji="🔄"
                ),
            ]
        )
    )

    return [Container(accent_color=BLUE_ACCENT, components=components)]


async def create_category_view(category: str) -> list:
    """Create a view showing commands in a specific category."""
    cat_info = HELP_CATEGORIES.get(category, {"name": "Unknown", "emoji": "❓"})
    commands = COMMAND_LIST.get(category, [])

    components = [
        Text(content=f"# {cat_info['emoji']} {cat_info['name']} Commands"),
        Separator(),
    ]

    # List commands
    for cmd_name, cmd_desc in commands:
        components.append(
            Text(content=f"**{cmd_name}**\n{cmd_desc}")
        )
        components.append(Separator(divider=False, spacing=hikari.SpacingType.SMALL))

    # Back button
    components.extend([
        Separator(),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="help_back:category",
                    label="Back to Categories",
                    emoji="◀️"
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id="help_ai_assistant:category",
                    label="Ask the AI Helper",
                    emoji="🤖"
                ),
            ]
        )
    ])

    return [Container(accent_color=BLUE_ACCENT, components=components)]


async def call_claude_api(user_question: str) -> str:
    """Call Claude API for help with bot commands."""

    if not ANTHROPIC_API_KEY:
        return "❌ Oops! The AI helper isn't set up yet. Please ask a staff member for help!"

    # Create bot context from command list
    bot_context = "Here are all the bot commands I can help you with:\n\n"
    for category, commands in COMMAND_LIST.items():
        cat_info = HELP_CATEGORIES.get(category, {"name": category.title()})
        bot_context += f"📂 **{cat_info['name']} Commands:**\n"
        for cmd_name, cmd_desc in commands:
            bot_context += f"  • {cmd_name}\n    → {cmd_desc}\n"
        bot_context += "\n"

    system_prompt = f"""You are a friendly Discord bot helper! You help people use bot commands in simple, easy-to-understand ways.

{bot_context}

Important Rules:
- Use VERY simple words (like you're explaining to a 5th grader)
- Be super specific about WHERE to find things
- Give step-by-step instructions
- Use emojis to make it fun and clear 😊

When someone asks "where" or "how" to find something:
1. Tell them the EXACT command name
2. Tell them EXACTLY what to click/select
3. Number your steps (Step 1, Step 2, etc.)

Examples of good answers:
- "FWA questions? Use `/recruit questions` → pick a Discord user → they'll get questions about FWA bases!"
- "To see clan info: Type `/clan info-hub` → click the 'FWA' button to see FWA clans"
- "Want to bid on recruits? Type `/recruit bidding` → pick the Discord user → follow the steps!"
- "Add clan points? Type `/clan dashboard` → click 'Clan Points' → pick your clan → add points!"
- "See FWA bases? Type `/fwa bases` → pick a Discord user → select their Town Hall level"

Always:
- Break down big words into smaller ones
- Use arrows (→) to show what happens next
- Say which buttons to press or menus to pick
- If something has multiple steps, list them as 1, 2, 3...
- End with "Need more help? Just ask!" 

Never use big technical words. Instead of "parameters" say "the blanks you fill in". Instead of "syntax" say "how to type it".

If they ask about something not in the commands, say: "Hmm, I don't know about that command. 🤔 Here's what I CAN help you with: [list 2-3 related commands they might want]. Want to try one of these instead?"

Remember: Make it so easy that anyone can understand! 🌟"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": AI_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": user_question
            }
        ],
        "system": system_prompt
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANTHROPIC_API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["content"][0]["text"]
                else:
                    error_text = await response.text()
                    print(f"[Help AI] API error {response.status}: {error_text}")
                    return "❌ Oops! Something went wrong. Try asking your question in a different way!"
    except Exception as e:
        print(f"[Help AI] Error calling Claude API: {e}")
        return "❌ The AI helper is taking a break! Please try again in a moment."


@loader.command
class Help(
    lightbulb.SlashCommand,
    name="help",
    description="Get help with bot commands or ask questions",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond(
            components=await create_help_menu_components(),
            ephemeral=True
        )


@register_action("help_category_select", opens_modal=False)
async def handle_category_select(ctx, action_id: str, **kwargs) -> list:
    """Handle category selection from dropdown."""
    # Get selected value from interaction
    selected_category = ctx.interaction.values[0]

    # Return the category view components
    return await create_category_view(selected_category)


@register_action("help_back", no_return=True)
async def handle_back_button(ctx, action_id: str, **kwargs) -> None:
    """Handle back button to return to main menu."""
    # The interaction is already deferred by component handler
    await ctx.interaction.edit_initial_response(
        components=await create_help_menu_components()
    )


@register_action("help_refresh", no_return=True)
async def handle_refresh(ctx, action_id: str, **kwargs) -> None:
    """Refresh the help menu."""
    # The interaction is already deferred by component handler
    await ctx.interaction.edit_initial_response(
        components=await create_help_menu_components()
    )


@register_action("help_ai_assistant", opens_modal=True, no_return=True)
async def handle_ai_assistant(ctx, action_id: str, **kwargs) -> None:
    """Open modal for AI assistant question."""
    question_input = ModalActionRow().add_text_input(
        "ai_question",  # custom_id (positional)
        "Ask me anything about the bot!",  # label (positional)
        placeholder="Examples: How do I see FWA bases? Where are recruit questions? How do I bid?",
        required=True,
        style=hikari.TextInputStyle.PARAGRAPH,
        min_length=5,
        max_length=500
    )

    await ctx.respond_with_modal(
        title="Ask the Bot Helper",
        custom_id="help_ai_modal:question",
        components=[question_input]
    )


@register_action("help_ai_modal", no_return=True, is_modal=True)
async def handle_ai_modal_submit(ctx: lightbulb.components.ModalContext, action_id: str, **kwargs) -> None:
    """Handle AI assistant modal submission."""
    # Get the question
    question = ""
    for row in ctx.interaction.components:
        for comp in row:
            if comp.custom_id == "ai_question":
                question = comp.value
                break

    if not question:
        await ctx.respond("Please provide a question!", ephemeral=True)
        return

    # Defer while processing
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_CREATE,
        flags=hikari.MessageFlag.EPHEMERAL
    )

    # Get AI response
    ai_response = await call_claude_api(question)

    # Create response components
    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## 🤖 AI Helper Response"),
                Separator(),
                Text(content=f"**You asked:**\n{question}"),
                Separator(),
                Text(content=f"**Here's my answer:**\n{ai_response}"),
                Separator(),
                Text(content="💡 **Still confused?** Try asking in a different way!"),
                Separator(),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id="help_ai_assistant:response",
                            label="Ask Something Else",
                            emoji="💭"
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="help_ai_back_to_menu:response",
                            label="Back to Help Menu",
                            emoji="📚"
                        ),
                    ]
                )
            ]
        )
    ]

    await ctx.interaction.edit_initial_response(
        content="",
        components=components
    )


@register_action("help_ai_back_to_menu", no_return=True)
async def handle_ai_back_to_menu(ctx, action_id: str, **kwargs) -> None:
    """Handle back to menu from AI response."""
    # The interaction is already deferred by component handler
    await ctx.interaction.edit_initial_response(
        components=await create_help_menu_components()
    )


# Add the command to the loader
loader.command(Help)