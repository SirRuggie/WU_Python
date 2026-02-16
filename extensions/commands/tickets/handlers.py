# extensions/commands/tickets/handlers.py
"""
Ticket button and interaction handlers
"""

import hikari
import hikari.errors
import lightbulb
from typing import List, Dict
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

# Global semaphore to prevent concurrent channel creation
channel_creation_semaphore = asyncio.Semaphore(1)

# Cooldown tracking - user_id: timestamp
user_cooldowns: Dict[int, datetime] = {}
COOLDOWN_DURATION = 30  # seconds
COOLDOWN_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes
last_cleanup = datetime.now(timezone.utc)


def cleanup_expired_cooldowns():
    """Remove expired cooldown entries to prevent memory leak"""
    global last_cleanup
    current_time = datetime.now(timezone.utc)
    
    # Only cleanup if enough time has passed
    if (current_time - last_cleanup).total_seconds() < COOLDOWN_CLEANUP_INTERVAL:
        return
    
    # Remove expired entries
    expired_users = []
    for user_id, cooldown_time in user_cooldowns.items():
        if (current_time - cooldown_time).total_seconds() > COOLDOWN_DURATION:
            expired_users.append(user_id)
    
    for user_id in expired_users:
        user_cooldowns.pop(user_id, None)
    
    if expired_users:
        print(f"[Tickets] Cleaned up {len(expired_users)} expired cooldown entries")
    
    last_cleanup = current_time


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

        # Get category info for better logging
        try:
            category = await bot.rest.fetch_channel(category_id)
            category_name = category.name
        except:
            category_name = "Unknown"

        # Discord limit is 50 channels per category
        used_slots = len(channels_in_category)
        remaining_slots = 50 - used_slots

        # Enhanced logging
        print(f"[Tickets] Category Space Check:")
        print(f"  - Category: {category_name} (ID: {category_id})")
        print(f"  - Type: {ticket_type.upper()}")
        print(f"  - Channels Used: {used_slots}/50")
        print(f"  - Remaining Slots: {remaining_slots}")

        # Show first 5 channel names as examples
        if channels_in_category:
            print(f"  - Example channels:")
            for i, channel in enumerate(channels_in_category[:5]):
                print(f"    • {channel.name}")
            if len(channels_in_category) > 5:
                print(f"    ... and {len(channels_in_category) - 5} more")

        # Check if we need to notify admin
        if remaining_slots <= CHANNEL_WARNING_THRESHOLD:
            try:
                admin_user = await bot.rest.fetch_user(admin_id)
                dm_channel = await admin_user.fetch_dm_channel()

                # Enhanced warning message with more details
                await dm_channel.send(
                    f"⚠️ **Low Channel Space Warning**\n\n"
                    f"**Category:** {category_name}\n"
                    f"**Type:** {ticket_type.upper()} tickets\n"
                    f"**Category ID:** `{category_id}`\n\n"
                    f"**Space Usage:**\n"
                    f"• Used: {used_slots}/50 channels\n"
                    f"• Remaining: **{remaining_slots} slots**\n\n"
                    f"⚠️ **Action Required:**\n"
                    f"Please run `/ticket change-category type:{ticket_type}` to set up a new category.\n\n"
                    f"*This warning triggers when 5 or fewer slots remain.*"
                )

                print(f"[Tickets] ⚠️ Admin notified about low space in {category_name}")
            except Exception as e:
                print(f"[Tickets] Failed to DM admin about low channel space: {e}")

        return remaining_slots

    except Exception as e:
        print(f"[Tickets] Error checking category space: {e}")
        return -1  # Return -1 to indicate error

@register_action("create_ticket", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def handle_create_ticket(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle ticket creation button clicks"""

    # Defer interaction immediately to prevent timeout
    await ctx.defer(ephemeral=True)

    # Periodic cleanup of expired cooldowns
    cleanup_expired_cooldowns()

    # Check cooldown (30 seconds)
    user_id = ctx.user.id
    current_time = datetime.now(timezone.utc)
    
    if user_id in user_cooldowns:
        time_since_last = (current_time - user_cooldowns[user_id]).total_seconds()
        if time_since_last < COOLDOWN_DURATION:
            remaining = int(COOLDOWN_DURATION - time_since_last)
            await ctx.interaction.edit_initial_response(
                content=f"⏳ Please wait {remaining} seconds before creating another ticket."
            )
            return
    
    # Update cooldown
    user_cooldowns[user_id] = current_time

    # Send status update
    await ctx.interaction.edit_initial_response(
        content="🎫 Creating your ticket..."
    )

    # Determine ticket type from action_id
    ticket_type = action_id  # Will be "main" or "fwa"

    # Get current configuration from database
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}

    print(f"[Tickets] Creating {ticket_type} ticket for user {ctx.user.username}")
    print(f"[Tickets] Config loaded: {config}")

    # Get the appropriate category and role (don't increment counter yet)
    if ticket_type == "main":
        category_id = config.get("main_category", DEFAULT_MAIN_CATEGORY)
        recruiter_role = config.get("main_recruiter_role")
        ticket_prefix = "main"
        ticket_title = "Main Clan"
        # Get ticket counter (don't increment yet)
        ticket_number = config.get("main_ticket_counter", 0) + 1
    else:
        category_id = config.get("fwa_category", DEFAULT_FWA_CATEGORY)
        recruiter_role = config.get("fwa_recruiter_role")
        ticket_prefix = "fwa"
        ticket_title = "FWA Clan"
        # Get ticket counter (don't increment yet)
        ticket_number = config.get("fwa_ticket_counter", 0) + 1

    print(f"[Tickets] Using category {category_id}, recruiter role: {recruiter_role}, ticket number: {ticket_number}")

    admin_to_notify = config.get("admin_to_notify", DEFAULT_ADMIN_TO_NOTIFY)

    # Check category space before creating
    remaining_slots = await check_category_space(bot, category_id, ticket_type, admin_to_notify, ctx.guild_id)

    if remaining_slots == 0:
        # Send error response
        await ctx.interaction.edit_initial_response(
            content=f"❌ The {ticket_title} ticket category is full!\nPlease contact an administrator."
        )
        return

    # Use semaphore to prevent concurrent channel creation
    async with channel_creation_semaphore:
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
                            hikari.Permissions.EMBED_LINKS | 
                            hikari.Permissions.ADD_REACTIONS
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
                                hikari.Permissions.MANAGE_CHANNELS |
                                hikari.Permissions.ADD_REACTIONS
                        ),
                    )
                )

            # Create the ticket channel with new naming format: 🆕{type}-{number}-{username}
            channel_name = f"🆕{ticket_prefix}-{ticket_number}-{ctx.user.username}"

            try:
                channel = await bot.rest.create_guild_text_channel(
                    guild=ctx.guild_id,
                    name=channel_name,
                    category=category_id,
                    permission_overwrites=permission_overwrites,
                    reason=f"{ticket_title} ticket for {ctx.user.username}"
                )
            except hikari.errors.RateLimitTooLongError as e:
                # Remove cooldown so user can try again later
                user_cooldowns.pop(user_id, None)
                
                print(f"[Tickets] Rate limit exceeded maximum wait time: {e}")
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⏰ **Discord Rate Limit Active**\n\n"
                        "Too many channels created recently. Please try again in a few minutes.\n\n"
                        "This is Discord's protection against spam."
                    )
                )
                return

            # Now that channel creation succeeded, increment the counter
            if ticket_type == "main":
                await mongo.ticket_setup.update_one(
                    {"_id": "config"},
                    {"$set": {"main_ticket_counter": ticket_number}},
                    upsert=True
                )
            else:
                await mongo.ticket_setup.update_one(
                    {"_id": "config"},
                    {"$set": {"fwa_ticket_counter": ticket_number}},
                    upsert=True
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
            if recruiter_role:
                # Ping the actual role using <@&ROLE_ID> format
                thread_message = await bot.rest.create_message(
                    thread.id,
                    content=(
                        f"<@&{recruiter_role}> "
                        "this is a private thread for the candidate. They cannot see this thread, "
                        "so DO NOT ping them, as it will add them.\n\n"
                    ),
                    role_mentions=True
                )
                print(f"[Tickets] Posted message in thread {thread.id} and pinged role {recruiter_role}")
            else:
                # If no role configured, just post a message
                thread_message = await bot.rest.create_message(
                    thread.id,
                    content=(
                        "⚠️ No recruiter role configured for this ticket type. "
                        "Please configure roles using `/ticket config`"
                    )
                )
                print(f"[Tickets] No recruiter role configured for {ticket_type} tickets")

            # Send initial messages with suggested question based on ticket type
            first_message = ""
            second_message = "What was the hook that reeled you in? The thing that said \"yeah, I need to check these guys out!!!\""
            fwa_donation_message = "Donations are better with the update allowing loot to be used but clan chats are and can be sporadic."

            if ticket_type == "main":
                first_message = "Hello there 👋🏻...how you hear about Warriors United?"
            elif ticket_type == "fwa":
                first_message = "Hello there 👋🏻...how you hear about our FWA Operation?"
            
            if first_message:
                # Send first message
                await bot.rest.create_message(
                    thread.id,
                    content=first_message
                )
                # Send second message
                await bot.rest.create_message(
                    thread.id,
                    content=second_message
                )
                # Send third FWA message
                if ticket_type == "fwa":
                    await bot.rest.create_message(
                        thread.id,
                        content=fwa_donation_message
                    )
                print(f"[Tickets] Posted initial messages in thread {thread.id} for {ticket_type} ticket")

            # Send success message as response
            await ctx.interaction.edit_initial_response(
                content=f"✅ Your {ticket_title} ticket has been created!\nPlease check <#{channel.id}>"
            )

        except hikari.errors.RateLimitTooLongError:
            # This is already handled above in the channel creation try-except
            pass
        except Exception as e:
            print(f"Error creating ticket: {e}")
            # Remove cooldown on error
            user_cooldowns.pop(user_id, None)
            
            # Send error response
            await ctx.interaction.edit_initial_response(
                content=f"❌ There was an error creating your ticket.\nPlease try again or contact an administrator.\nError: {str(e)}"
            )
