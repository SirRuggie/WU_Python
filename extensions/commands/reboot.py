# extensions/commands/reboot.py
"""
Bot reboot command - Owner-only emergency restart
"""

import os
import hikari
import lightbulb
import uuid
from datetime import datetime, timezone

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GREEN_ACCENT

# Hardcoded owner ID - ONLY this user can reboot the bot
OWNER_ID = 505227988229554179

loader = lightbulb.Loader()


@loader.command
class Reboot(
    lightbulb.SlashCommand,
    name="reboot",
    description="Restart the bot (Owner only)",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR
):
    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        # Hardcoded owner check
        if ctx.user.id != OWNER_ID:
            await ctx.respond(
                components=[
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content=(
                                "## ❌ Permission Denied\n\n"
                                "This command is restricted to the bot owner only."
                            ))
                        ]
                    )
                ],
                flags=hikari.MessageFlag.EPHEMERAL
            )
            return

        # Create action ID for confirmation
        action_id = str(uuid.uuid4())

        # Store data for the action
        await mongo.button_store.insert_one({
            "_id": action_id,
            "user_id": ctx.user.id
        })

        # Create warning message
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=(
                        "## ⚠️ Confirm Bot Reboot\n\n"
                        "This will **restart the entire bot process**.\n\n"
                        "**What happens:**\n"
                        "• All active connections will be closed\n"
                        "• Bot will disconnect from Discord\n"
                        "• Process manager will auto-restart the bot\n"
                        "• Downtime: ~5-10 seconds\n\n"
                        "⚠️ **Are you sure you want to reboot?**"
                    )),
                    Separator(divider=True),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.DANGER,
                                label="Yes, Reboot Bot",
                                custom_id=f"reboot_confirm:{action_id}",
                                emoji="🔄"
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Cancel",
                                custom_id=f"reboot_cancel:{action_id}",
                                emoji="❌"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]

        await ctx.respond(components=components, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("reboot_confirm", no_return=True)
@lightbulb.di.with_di
async def handle_reboot_confirm(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle confirmation of bot reboot"""
    # Get stored data
    stored_data = await mongo.button_store.find_one({"_id": action_id})
    if not stored_data:
        return await ctx.respond("❌ Session expired. Please run the command again.")

    # Double verify owner
    if ctx.user.id != OWNER_ID:
        return await ctx.respond("❌ Only the bot owner can reboot!")

    # Verify user matches command invoker
    if ctx.user.id != stored_data["user_id"]:
        return await ctx.respond("❌ Only the command user can confirm reboot!")

    # Show rebooting message
    reboot_components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=(
                    "## 🔄 Rebooting Bot...\n\n"
                    f"Initiated by {ctx.user.mention}\n\n"
                    "*The bot will reconnect in a few seconds.*"
                ))
            ]
        )
    ]

    await ctx.respond(components=reboot_components, edit=True)

    # Clean up stored data
    await mongo.button_store.delete_one({"_id": action_id})

    # Store reboot flag for startup notification
    await mongo.bot_config.update_one(
        {"_id": "reboot_status"},
        {"$set": {
            "reboot_pending": True,
            "user_id": ctx.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )

    # Close bot gracefully (triggers StoppingEvent)
    await bot.close()

    # Exit process (process manager will restart)
    os._exit(0)


@register_action("reboot_cancel", no_return=True)
@lightbulb.di.with_di
async def handle_reboot_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle cancellation of bot reboot"""
    # Get stored data
    stored_data = await mongo.button_store.find_one({"_id": action_id})
    if not stored_data:
        return await ctx.respond("❌ Session expired.")

    # Verify user
    if ctx.user.id != stored_data["user_id"]:
        return await ctx.respond("❌ Only the command user can cancel!")

    # Send cancellation message
    cancel_components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=(
                    "## ✅ Reboot Cancelled\n\n"
                    "The bot will continue running normally."
                ))
            ]
        )
    ]

    await ctx.respond(components=cancel_components, edit=True)

    # Clean up stored data
    await mongo.button_store.delete_one({"_id": action_id})
