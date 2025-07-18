# extensions/commands/tickets/handlers.py
"""
Ticket button and interaction handlers
"""

import hikari
import lightbulb
from typing import List
from datetime import datetime, timezone
import asyncio

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT
from extensions.components import register_action
from extensions.commands.tickets import loader

# Default configuration values
DEFAULT_MAIN_CATEGORY = 1395400463897202738
DEFAULT_FWA_CATEGORY = 1395653165470191667
DEFAULT_ADMIN_TO_NOTIFY = 505227988229554179
CHANNEL_WARNING_THRESHOLD = 5


async def check_category_space(bot: hikari.GatewayBot, category_id: int, ticket_type: str, admin_id: int,
                               guild_id: int) -> int:
    """Check how many more channels can be created in a category and notify admin if low"""
    try:
        # Get all channels in the guild
        guild_channels = await bot.rest.fetch_guild_channels(guild_id)

        # Count channels in this specific category
        channels_in_category = [
            ch for ch in guild_channels
            if hasattr(ch, 'parent_id') and ch.parent_id == category_id
        ]

        # Discord limit is 50 channels per category
        remaining_slots = 50 - len(channels_in_category)

        # Check if we need to notify admin
        if remaining_slots <= CHANNEL_WARNING_THRESHOLD:
            try:
                admin_user = await bot.rest.fetch_user(admin_id)
                dm_channel = await admin_user.fetch_dm_channel()

                await dm_channel.send(
                    f"⚠️ **Low Channel Space Warning**\n\n"
                    f"The {ticket_type.upper()} ticket category is running low on space!\n"
                    f"**Remaining slots:** {remaining_slots}/50\n\n"
                    f"Please run `/tickets change-category type:{ticket_type}` to set up a new category."
                )
            except Exception as e:
                print(f"Failed to DM admin about low channel space: {e}")

        return remaining_slots

    except Exception as e:
        print(f"Error checking category space: {e}")
        return -1  # Return -1 to indicate error


@register_action("create_ticket", opens_modal=False, no_return=True)
@lightbulb.di.with_di
async def handle_create_ticket(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle ticket creation button clicks"""

    # Determine ticket type from action_id
    ticket_type = action_id  # Will be "main" or "fwa"

    # Get current configuration from database
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}

    print(f"[Tickets] Creating {ticket_type} ticket for user {ctx.user.username}")
    print(f"[Tickets] Config loaded: {config}")

    # Get the appropriate category and role
    if ticket_type == "main":
        category_id = config.get("main_category", DEFAULT_MAIN_CATEGORY)
        recruiter_role = config.get("main_recruiter_role")
        ticket_prefix = "main"
        ticket_title = "Main Clan"
        # Get and increment ticket counter
        ticket_number = config.get("main_ticket_counter", 0) + 1
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$set": {"main_ticket_counter": ticket_number}},
            upsert=True
        )
    else:
        category_id = config.get("fwa_category", DEFAULT_FWA_CATEGORY)
        recruiter_role = config.get("fwa_recruiter_role")
        ticket_prefix = "fwa"
        ticket_title = "FWA Clan"
        # Get and increment ticket counter
        ticket_number = config.get("fwa_ticket_counter", 0) + 1
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$set": {"fwa_ticket_counter": ticket_number}},
            upsert=True
        )

    print(f"[Tickets] Using category {category_id}, recruiter role: {recruiter_role}, ticket number: {ticket_number}")

    admin_to_notify = config.get("admin_to_notify", DEFAULT_ADMIN_TO_NOTIFY)

    # Check category space before creating
    remaining_slots = await check_category_space(bot, category_id, ticket_type, admin_to_notify, ctx.guild_id)

    if remaining_slots == 0:
        # Send error as ephemeral response
        await ctx.respond(
            f"❌ The {ticket_title} ticket category is full!\nPlease contact an administrator.",
            ephemeral=True
        )
        return

    try:
        # Create permission overwrites for the ticket channel
        permission_overwrites = [
            # Deny @everyone
            hikari.PermissionOverwrite(
                id=ctx.guild_id,  # @everyone role has same ID as guild
                type=hikari.PermissionOverwriteType.ROLE,
                deny=(
                        hikari.Permissions.VIEW_CHANNEL |
                        hikari.Permissions.SEND_MESSAGES |
                        hikari.Permissions.READ_MESSAGE_HISTORY
                ),
            ),
            # Allow the ticket creator
            hikari.PermissionOverwrite(
                id=ctx.user.id,
                type=hikari.PermissionOverwriteType.MEMBER,
                allow=(
                        hikari.Permissions.VIEW_CHANNEL |
                        hikari.Permissions.SEND_MESSAGES |
                        hikari.Permissions.READ_MESSAGE_HISTORY |
                        hikari.Permissions.ATTACH_FILES |
                        hikari.Permissions.EMBED_LINKS
                ),
            ),
        ]

        # Add recruiter role permissions if configured
        if recruiter_role:
            permission_overwrites.append(
                hikari.PermissionOverwrite(
                    id=recruiter_role,
                    type=hikari.PermissionOverwriteType.ROLE,
                    allow=(
                            hikari.Permissions.VIEW_CHANNEL |
                            hikari.Permissions.SEND_MESSAGES |
                            hikari.Permissions.READ_MESSAGE_HISTORY |
                            hikari.Permissions.ATTACH_FILES |
                            hikari.Permissions.EMBED_LINKS |
                            hikari.Permissions.MANAGE_MESSAGES |
                            hikari.Permissions.MANAGE_CHANNELS
                    ),
                )
            )

        # Create the ticket channel with new naming format: ✅{type}-{number}-{username}
        channel_name = f"✅{ticket_prefix}-{ticket_number}-{ctx.user.username}"

        channel = await bot.rest.create_guild_text_channel(
            guild=ctx.guild_id,
            name=channel_name,
            category=category_id,
            permission_overwrites=permission_overwrites,
            reason=f"{ticket_title} ticket for {ctx.user.username}"
        )

        # Create the thread under the ticket channel
        thread = await bot.rest.create_thread(
            channel.id,
            hikari.ChannelType.GUILD_PRIVATE_THREAD,
            f"private-{ctx.user.username}",
            auto_archive_duration=10080,  # 7 days
            invitable=False,
            reason="Private thread for recruiters"
        )

        print(f"[Tickets] Created thread {thread.id} for ticket {channel.id}")

        # Ensure the bot joins the thread
        try:
            await bot.rest.add_thread_member(thread.id, bot.get_me().id)
            print(f"[Tickets] Bot joined thread {thread.id}")
        except Exception as e:
            print(f"[Tickets] Failed to add bot to thread: {e}")

        # Store ticket information
        ticket_data = {
            "_id": f"ticket_{channel.id}",
            "type": "ticket",
            "ticket_type": ticket_type,
            "ticket_number": ticket_number,
            "channel_id": channel.id,
            "thread_id": thread.id,
            "category_id": category_id,
            "user_id": ctx.user.id,
            "username": ctx.user.username,
            "created_at": datetime.now(timezone.utc),
            "status": "open",
        }
        await mongo.button_store.insert_one(ticket_data)

        # Small delay to ensure thread is fully created
        await asyncio.sleep(0.5)

        # Send message in the private thread for recruiters
        thread_message = await bot.rest.create_message(
            thread.id,
            content=(
                f"**{'@Main Recruiter' if ticket_type == 'main' else '@FWA Recruiter'} (3)**, "
                "this is a private thread for the candidate. They cannot see this thread, "
                "so DO NOT ping them, as it will add them.\n\n"
            )
        )

        print(f"[Tickets] Posted message in thread {thread.id}")

        # Add recruiters to the thread if role is configured
        if recruiter_role:
            print(f"[Tickets] Adding recruiters with role {recruiter_role} to thread")
            # Get recruiters with the role
            members = await bot.rest.fetch_members(ctx.guild_id)
            recruiters = [
                member for member in members
                if recruiter_role in member.role_ids
            ]

            print(f"[Tickets] Found {len(recruiters)} recruiters to add")

            # Add recruiters to the thread (up to 3)
            for recruiter in recruiters[:3]:
                try:
                    await bot.rest.add_thread_member(thread.id, recruiter.id)
                    print(f"[Tickets] Added recruiter {recruiter.username} to thread")
                except Exception as e:
                    print(f"[Tickets] Failed to add recruiter {recruiter.username}: {e}")
        else:
            print(f"[Tickets] No recruiter role configured for {ticket_type} tickets")

        # Send success message as ephemeral response
        await ctx.respond(
            f"✅ Your {ticket_title} ticket has been created!\nPlease check <#{channel.id}>",
            ephemeral=True
        )

    except Exception as e:
        print(f"Error creating ticket: {e}")
        # Send error as ephemeral response
        await ctx.respond(
            f"❌ There was an error creating your ticket.\nPlease try again or contact an administrator.\nError: {str(e)}",
            ephemeral=True
        )


# Load configuration on startup
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Load ticket configuration from database on startup"""
    config = await mongo.ticket_setup.find_one({"_id": "config"})
    if config:
        print(f"[Tickets] Loaded configuration from database")
        print(f"[Tickets] Main Role: {config.get('main_recruiter_role')}")
        print(f"[Tickets] FWA Role: {config.get('fwa_recruiter_role')}")
        print(f"[Tickets] Admin: {config.get('admin_to_notify', DEFAULT_ADMIN_TO_NOTIFY)}")
        print(
            f"[Tickets] Categories: Main={config.get('main_category', DEFAULT_MAIN_CATEGORY)}, FWA={config.get('fwa_category', DEFAULT_FWA_CATEGORY)}")
        print(
            f"[Tickets] Counters: Main={config.get('main_ticket_counter', 0)}, FWA={config.get('fwa_ticket_counter', 0)}")
    else:
        print(f"[Tickets] No configuration found in database, using defaults")