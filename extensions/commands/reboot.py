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
from utils.component_state import delete_state, get_state, insert_state
from utils.mongo import MongoClient
from utils.constants import WU_GOLD, WU_GREEN, WU_RED

# Explicit allowlist: Discord Administrator alone must never grant process
# restart access.
REBOOT_OWNER_IDS = frozenset({
    505227988229554179,
    644005027052126208,
})


def _is_reboot_owner(user_id: object) -> bool:
    try:
        return int(user_id) in REBOOT_OWNER_IDS
    except (TypeError, ValueError):
        return False

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
        if not _is_reboot_owner(ctx.user.id):
            await ctx.respond(
                components=[
                    Container(
                        accent_color=WU_RED,
                        components=[
                            Text(content=(
                                "## ❌ Permission Denied\n\n"
                                "Only the owner can use this command."
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
        await insert_state(mongo, {
            "_id": action_id,
            "user_id": ctx.user.id
        })

        # Create warning message
        components = [
            Container(
                accent_color=WU_RED,
                components=[
                    Text(content=(
                        "## ⚠️ Confirm Bot Reboot\n\n"
                        "This will **restart WUBOT**.\n\n"
                        "**What happens:**\n"
                        "• WUBOT closes all connections\n"
                        "• WUBOT disconnects from Discord\n"
                        "• The process manager starts WUBOT again\n"
                        "• WUBOT is off for 5 to 10 seconds\n\n"
                        "⚠️ **Do you want to restart WUBOT?**"
                    )),
                    Separator(divider=True),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.DANGER,
                                label="Yes, restart WUBOT",
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


@register_action("reboot_confirm", no_return=True, requires_state=True)
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
    stored_data = await get_state(mongo, action_id)
    if not stored_data:
        return await ctx.respond("❌ The session expired. Run the command again.")

    # Double verify owner at the destructive action boundary.
    if not _is_reboot_owner(ctx.user.id):
        return await ctx.respond("❌ Only the bot owner can reboot!")

    # Verify user matches command invoker
    if ctx.user.id != stored_data["user_id"]:
        return await ctx.respond("❌ Only the command user can confirm reboot!")

    # Show rebooting message
    reboot_components = [
        Container(
            accent_color=WU_GOLD,
            components=[
                Text(content=(
                    "## 🔄 Restarting WUBOT...\n\n"
                    f"Started by {ctx.user.mention}\n\n"
                    "*WUBOT connects again in a few seconds.*"
                ))
            ]
        )
    ]

    await ctx.respond(components=reboot_components, edit=True)

    # Clean up stored data
    await delete_state(mongo, action_id)

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


@register_action("reboot_cancel", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_reboot_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle cancellation of bot reboot"""
    # Get stored data
    stored_data = await get_state(mongo, action_id)
    if not stored_data:
        return await ctx.respond("❌ Session expired.")

    # Verify user
    if ctx.user.id != stored_data["user_id"]:
        return await ctx.respond("❌ Only the command user can cancel!")

    # Send cancellation message
    cancel_components = [
        Container(
            accent_color=WU_GREEN,
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
    await delete_state(mongo, action_id)
