# extensions/commands/recruit/dashboard/server_walkthrough.py
"""
Handle the Server walk thru action from the recruit dashboard
"""

import lightbulb
import hikari

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT, GOLD_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    LinkButtonBuilder as LinkButton,
)

# Define important server channels and resources
SERVER_RESOURCES = {
    "rules": {
        "channel_id": 901627019190657040,  # Update with actual channel ID
        "name": "📜 Rules & Guidelines",
        "description": "Server rules and community guidelines"
    },
    "announcements": {
        "channel_id": 901627019190657041,
        "name": "📢 Announcements",
        "description": "Important server announcements"
    },
    "clan_chat": {
        "channel_id": 901627019190657042,
        "name": "💬 Clan Chat",
        "description": "General clan discussion"
    },
    "war_planning": {
        "channel_id": 901627019190657043,
        "name": "⚔️ War Planning",
        "description": "War strategies and planning"
    },
    "bot_commands": {
        "channel_id": 901627019190657044,
        "name": "🤖 Bot Commands",
        "description": "Use bot commands here"
    },
    "support": {
        "channel_id": 901627019190657045,
        "name": "🎫 Support",
        "description": "Get help from staff"
    }
}


@register_action("server_walkthrough")
@lightbulb.di.with_di
async def server_walkthrough_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display server walkthrough information"""

    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Build channel list
    channel_list = []
    for key, resource in SERVER_RESOURCES.items():
        channel_id = resource["channel_id"]
        channel = guild.get_channel(channel_id) if guild else None

        if channel:
            channel_list.append(
                f"• **{resource['name']}** - <#{channel_id}>\n"
                f"  _{resource['description']}_"
            )

    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=f"## 🎯 **Server Walkthrough for {member.display_name}**"),
                Separator(divider=True),

                Text(content=(
                    "### Welcome to Warriors United! 🎉\n\n"
                    "Here's a quick guide to help you navigate our server:"
                )),

                Separator(divider=True),

                # Important channels
                Text(content="### 📍 **Important Channels:**"),
                Text(content="\n\n".join(channel_list) if channel_list else "_Channel configuration needed_"),

                Separator(divider=True),

                # Getting started guide
                Text(content=(
                    "### 🚀 **Getting Started:**\n\n"
                    "**1. Read the Rules** 📜\n"
                    "Start by reading our server rules to understand our community guidelines.\n\n"

                    "**2. Set Your Nickname** ✏️\n"
                    "Your nickname should follow the format: `IGN | Timezone Flag`\n\n"

                    "**3. Join Your Clan Chat** 💬\n"
                    "Head to your clan's specific chat channel to meet your clanmates.\n\n"

                    "**4. Link Your Accounts** 🔗\n"
                    "Use `/link` command to connect your Clash of Clans accounts.\n\n"

                    "**5. Check War Schedule** ⚔️\n"
                    "Review the war schedule and rules for your clan."
                )),

                Separator(divider=True),

                # Quick tips
                Text(content=(
                    "### 💡 **Quick Tips:**\n"
                    "• Use `/help` to see all available bot commands\n"
                    "• Check pins in each channel for important information\n"
                    "• Don't hesitate to ask questions in support\n"
                    "• Make sure to enable notifications for your clan"
                )),

                # Action buttons
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            custom_id=f"send_welcome_message:{action_id}",
                            label="Send Welcome Message",
                            emoji="📨"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"complete_onboarding:{action_id}",
                            label="Complete Onboarding",
                            emoji="✅"
                        ),
                    ]
                ),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"refresh_dashboard:{action_id}",
                            label="Back to Dashboard",
                            emoji="↩️"
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]

    return components


@register_action("send_welcome_message")
@lightbulb.di.with_di
async def send_welcome_message_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Send a welcome message in the appropriate channel"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    channel_id = data.get("channel_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Get the member's clan role(s)
    clan_data = await mongo.clans.find().to_list(length=None)
    member_clans = []

    for clan_doc in clan_data:
        if clan_doc.get("role_id") in member.role_ids:
            member_clans.append(clan_doc.get("name"))

    clan_names = " & ".join(member_clans) if member_clans else "the Alliance"

    # Create welcome message
    welcome_components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=f"## 🎉 **Welcome {member.mention}!**"),
                Separator(divider=True),
                Text(content=(
                    f"Welcome to **Warriors United** and {clan_names}! 🏰\n\n"
                    f"We're excited to have you join our community. "
                    f"If you have any questions or need help getting started, "
                    f"don't hesitate to reach out to your clan leadership or use our support channels.\n\n"
                    f"**Remember to:**\n"
                    f"• Check clan mail regularly 📬\n"
                    f"• Follow war plans carefully ⚔️\n"
                    f"• Communicate with your clanmates 💬\n"
                    f"• Have fun and clash on! 🎮"
                )),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    try:
        # Send the welcome message
        channel = guild.get_channel(channel_id) if guild else None
        if channel:
            await channel.send(
                user_mentions=[user_id],
                components=welcome_components
            )

            return [
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content="## ✅ **Welcome Message Sent!**"),
                        Text(content=f"Welcome message has been posted in <#{channel_id}>"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    custom_id=f"server_walkthrough:{action_id}",
                                    label="Back to Walkthrough",
                                    emoji="↩️"
                                )
                            ]
                        ),
                        Media(items=[MediaItem(media="assets/Green_Footer.png")])
                    ]
                )
            ]
        else:
            return [error_response("Channel not found", action_id)]

    except Exception as e:
        return [error_response(f"Failed to send message: {str(e)[:100]}", action_id)]


@register_action("complete_onboarding")
@lightbulb.di.with_di
async def complete_onboarding_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Mark the onboarding as complete"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    recruiter_id = data.get("recruiter_id")

    # Log the completion (you can expand this to track onboarding stats)
    await mongo.onboarding_logs.insert_one({
        "user_id": user_id,
        "recruiter_id": recruiter_id,
        "completed_at": hikari.datetime.now(),
        "guild_id": data.get("guild_id")
    })

    # Clean up the button store data
    await mongo.button_store.delete_one({"_id": action_id})

    return [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ✅ **Onboarding Complete!**"),
                Separator(divider=True),
                Text(content=(
                    "🎉 **Congratulations!**\n\n"
                    "The recruit onboarding process has been completed successfully.\n\n"
                    "**Summary:**\n"
                    "✅ Nickname configured\n"
                    "✅ Roles assigned\n"
                    "✅ Townhall roles set\n"
                    "✅ Clan roles added\n"
                    "✅ Server walkthrough completed\n\n"
                    "_The dashboard session has been closed._"
                )),
                Media(items=[MediaItem(media="assets/Green_Footer.png")]),
                Text(content=f"-# Onboarding completed by <@{recruiter_id}>")
            ]
        )
    ]


# Helper function for error responses
def error_response(message: str, action_id: str) -> Container:
    return Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ❌ **Error: {message}**"),
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"refresh_dashboard:{action_id}",
                        label="Back to Dashboard",
                        emoji="↩️"
                    )
                ]
            ),
            Media(items=[MediaItem(media="assets/Red_Footer.png")])
        ]
    )