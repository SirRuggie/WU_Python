# extensions/commands/tickets/handlers.py
"""
Ticket button and interaction handlers
"""

import hikari
import hikari.errors
import lightbulb
from typing import List, Dict
from datetime import datetime, timedelta, timezone
import asyncio
import re

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT
from extensions.components import register_action
from extensions.commands.tickets import loader
from extensions.commands.tickets import store

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
# Extra seconds pushed onto a user's cooldown after a 429 on channel creation. The
# guild channel-create bucket slides to a 60s window, so a plain 30s cooldown would
# let the retry land back inside the same window; 60 + 30 clears it.
RATE_LIMIT_BACKOFF = 60  # seconds
COOLDOWN_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes
last_cleanup = datetime.now(timezone.utc)
CREATION_LEASE = timedelta(minutes=10)
CREATION_RETENTION = timedelta(days=30)
UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS = 3
UNCERTAIN_CHANNEL_LOOKUP_DELAY_SECONDS = 1
_creation_index_ready = False


def _creation_id(guild_id: int, user_id: int, ticket_type: str) -> str:
    return f"{int(guild_id)}:{int(user_id)}:{ticket_type}"


def _error_detail(error: Exception) -> str:
    detail = " ".join(str(error).split()) or "no error detail"
    detail = re.sub(
        r"(?i)\b(mongodb(?:\+srv)?|https?)://[^@\s]+@",
        r"\1://***@",
        detail,
    )
    detail = re.sub(
        r"(?i)\b(access_token|token|api_key|secret|password)=([^&\s]+)",
        r"\1=***",
        detail,
    )
    return detail[:180]


async def ensure_creation_index(mongo: MongoClient) -> None:
    """Install the bounded-state TTL before any Discord side effect."""
    global _creation_index_ready
    if _creation_index_ready:
        return
    await mongo.ticket_creation_state.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="ttl_expires_at",
    )
    _creation_index_ready = True


async def find_open_ticket(mongo: MongoClient, user_id: int, ticket_type: str):
    """Return an existing committed ticket so a retry cannot duplicate it."""
    return await store.find_one(mongo, {
        "type": "ticket",
        "ticket_type": ticket_type,
        "user_id": {"$in": [int(user_id), str(int(user_id))]},
        "status": "open",
    })


async def claim_ticket_creation(
        mongo: MongoClient,
        guild_id: int,
        user_id: int,
        ticket_type: str,
        *,
        now: datetime | None = None,
) -> tuple[bool, dict]:
    """Atomically own one user's ticket creation across workers and restarts."""
    await ensure_creation_index(mongo)
    now = now or datetime.now(timezone.utc)
    creation_id = _creation_id(guild_id, user_id, ticket_type)
    collection = mongo.ticket_creation_state
    current = await collection.find_one({"_id": creation_id})

    # Any state tied to a Discord channel is intentionally sticky. The normal
    # open-ticket lookup resolves completed work; an incomplete channel requires
    # compensation or operator cleanup, never a second channel.
    if current and current.get("channel_id"):
        return False, current
    if current and current.get("state") == "cleanup_required":
        return False, current

    query = {
        "_id": creation_id,
        "$or": [
            {"lease_until": {"$lte": now}},
            {"lease_until": {"$exists": False}},
        ],
    }
    update = {
        "$setOnInsert": {
            "guild_id": int(guild_id),
            "user_id": int(user_id),
            "ticket_type": ticket_type,
            "created_at": now,
        },
        "$set": {
            "state": "creating",
            "lease_until": now + CREATION_LEASE,
            "expires_at": now + CREATION_RETENTION,
            "updated_at": now,
        },
        "$unset": {"last_error": ""},
    }
    try:
        claimed = await collection.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        claimed = None
    if claimed is not None:
        return True, claimed
    return False, (await collection.find_one({"_id": creation_id}) or {
        "_id": creation_id,
        "state": "creating",
    })


async def reserve_ticket_number(mongo: MongoClient, ticket_type: str) -> int:
    """Allocate a unique number before creating Discord resources."""
    field = f"{ticket_type}_ticket_counter"
    config = await mongo.ticket_setup.find_one_and_update(
        {"_id": "config"},
        {"$inc": {field: 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(config[field])


async def update_creation_state(
        mongo: MongoClient,
        creation_id: str,
        **fields,
) -> None:
    now = datetime.now(timezone.utc)
    fields["updated_at"] = now
    fields["lease_until"] = now + CREATION_LEASE
    result = await mongo.ticket_creation_state.update_one(
        {"_id": creation_id, "state": "creating"},
        {"$set": fields},
    )
    if not getattr(result, "matched_count", 0):
        raise RuntimeError("ticket creation lease was lost")


async def complete_creation_state(
        mongo: MongoClient,
        creation_id: str,
        channel_id: int,
        thread_id: int,
        ticket_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    await mongo.ticket_creation_state.update_one(
        {"_id": creation_id},
        {
            "$set": {
                "state": "complete",
                "channel_id": int(channel_id),
                "thread_id": int(thread_id),
                "ticket_id": ticket_id,
                "completed_at": now,
                "updated_at": now,
                "expires_at": now + CREATION_RETENTION,
            },
            "$unset": {"lease_until": "", "last_error": ""},
        },
    )


async def rollback_ticket_creation(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        creation_id: str,
        channel_id: int | None,
        error: Exception,
) -> bool:
    """Compensate Discord work; retain a blocker if cleanup itself fails."""
    if channel_id is not None:
        try:
            await bot.rest.delete_channel(
                channel_id,
                reason="Rolling back incomplete ticket creation",
            )
        except hikari.NotFoundError:
            pass
        except Exception as cleanup_error:
            now = datetime.now(timezone.utc)
            try:
                await mongo.ticket_creation_state.update_one(
                    {"_id": creation_id},
                    {
                        "$set": {
                            "state": "cleanup_required",
                            "channel_id": int(channel_id),
                            "last_error": type(error).__name__,
                            "cleanup_error": type(cleanup_error).__name__,
                            "updated_at": now,
                            "expires_at": now + CREATION_RETENTION,
                        },
                        "$unset": {"lease_until": ""},
                    },
                )
            except Exception as state_error:
                print(
                    "[Tickets] ALERT creation_cleanup_state_failed "
                    f"creation_id={creation_id} channel_id={channel_id} "
                    f"error={type(state_error).__name__}"
                )
            print(
                "[Tickets] ALERT creation_rollback_failed "
                f"creation_id={creation_id} channel_id={channel_id} "
                f"error={type(cleanup_error).__name__}"
            )
            return False

    try:
        await mongo.ticket_creation_state.delete_one({"_id": creation_id})
    except Exception as state_error:
        # The lease remains and blocks duplicates until it can expire.
        print(
            "[Tickets] WARNING creation_state_release_failed "
            f"creation_id={creation_id} error={type(state_error).__name__}"
        )
    return True


async def release_missing_channel_blocker(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        creation_state: dict,
) -> bool:
    """Clear an incomplete claim only when Discord proves its channel is gone."""
    channel_id = creation_state.get("channel_id")
    channel_name = creation_state.get("channel_name")
    missing = False
    try:
        if channel_id:
            await bot.rest.fetch_channel(channel_id)
        elif channel_name:
            channels = await bot.rest.fetch_guild_channels(
                creation_state["guild_id"]
            )
            matches = [
                item for item in channels
                if str(getattr(item, "name", "")).casefold() == channel_name.casefold()
                and getattr(item, "parent_id", None) is not None
                and int(item.parent_id) == int(creation_state["category_id"])
            ]
            if not matches:
                missing = True
            elif len(matches) == 1:
                channel_id = int(matches[0].id)
                creation_state["channel_id"] = channel_id
                await mongo.ticket_creation_state.update_one(
                    {"_id": creation_state["_id"]},
                    {"$set": {
                        "channel_id": channel_id,
                        "updated_at": datetime.now(timezone.utc),
                    }},
                )
                print(
                    "[Tickets] uncertain_creation_channel_found "
                    f"creation_id={creation_state['_id']} channel_id={channel_id}"
                )
            else:
                print(
                    "[Tickets] ALERT ambiguous_creation_channels "
                    f"creation_id={creation_state['_id']} matches={len(matches)}"
                )
        else:
            return False
    except hikari.NotFoundError:
        missing = True
    except Exception as error:
        print(
            "[Tickets] WARNING creation_channel_check_failed "
            f"creation_id={creation_state['_id']} "
            f"channel_id={channel_id or 'unknown'} "
            f"error={type(error).__name__}"
        )
        return False

    if missing:
        delete_filter = {
            "_id": creation_state["_id"],
        }
        if channel_id:
            delete_filter["channel_id"] = channel_id
        else:
            delete_filter["channel_name"] = channel_name
        try:
            result = await mongo.ticket_creation_state.delete_one(delete_filter)
        except Exception as error:
            print(
                "[Tickets] WARNING missing_channel_blocker_release_failed "
                f"creation_id={creation_state['_id']} "
                f"error={type(error).__name__}"
            )
            return False
        if not getattr(result, "deleted_count", 0):
            return False
        print(
            "[Tickets] stale_creation_blocker_released "
            f"creation_id={creation_state['_id']} "
            f"channel_id={channel_id or 'unknown'}"
        )
        return True
    return False


async def locate_uncertain_channel(
        bot: hikari.GatewayBot,
        guild_id: int,
        category_id: int,
        channel_name: str,
):
    """Find the unique channel Discord may have created before a lost response."""
    for attempt in range(UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS):
        channels = await bot.rest.fetch_guild_channels(guild_id)
        matches = [
            item for item in channels
            if str(getattr(item, "name", "")).casefold() == channel_name.casefold()
            and getattr(item, "parent_id", None) is not None
            and int(item.parent_id) == int(category_id)
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"ambiguous Discord channel result ({len(matches)} matches)"
            )
        if matches:
            return matches[0]
        if attempt + 1 < UNCERTAIN_CHANNEL_LOOKUP_ATTEMPTS:
            await asyncio.sleep(UNCERTAIN_CHANNEL_LOOKUP_DELAY_SECONDS)
    return None


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
        # int() on both sides: parent_id is a Snowflake and category_id may arrive as
        # a string from Mongo, and a type mismatch here fails open (reports 50 free).
        channels_in_category = [
            ch for ch in guild_channels
            if getattr(ch, 'parent_id', None) is not None
            and int(ch.parent_id) == int(category_id)
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
        print(f"  - Guild Channels Total: {len(guild_channels)}/500")  # free, already fetched above

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
    if ticket_type not in {"main", "fwa"}:
        await ctx.interaction.edit_initial_response(
            content="❌ That ticket type is not available."
        )
        return

    # Get current configuration from database
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}

    print(f"[Tickets] Creating {ticket_type} ticket for user {ctx.user.username}")
    print(f"[Tickets] Config loaded: {config}")

    # Get the appropriate category and role. The counter is reserved atomically
    # inside the creation semaphore after idempotency checks pass.
    if ticket_type == "main":
        category_id = config.get("main_category", DEFAULT_MAIN_CATEGORY)
        recruiter_role = config.get("main_recruiter_role")
        ticket_prefix = "main"
        ticket_title = "Main Clan"
    else:
        category_id = config.get("fwa_category", DEFAULT_FWA_CATEGORY)
        recruiter_role = config.get("fwa_recruiter_role")
        ticket_prefix = "fwa"
        ticket_title = "FWA Clan"

    # Coerce here, not at the comparison site: a string category id from a manual
    # Mongo edit makes the parent_id comparison in check_category_space always False,
    # which silently reports 50 free slots on a category that is actually full.
    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        print(f"[Tickets] ERROR: {ticket_type} category id is not numeric: {category_id!r}")
        await ctx.interaction.edit_initial_response(
            content=f"❌ The {ticket_title} ticket category is misconfigured.\n"
                    f"Please contact an administrator."
        )
        return

    print(f"[Tickets] Using category {category_id}, recruiter role: {recruiter_role}")

    admin_to_notify = config.get("admin_to_notify", DEFAULT_ADMIN_TO_NOTIFY)

    # Check category space before creating
    remaining_slots = await check_category_space(bot, category_id, ticket_type, admin_to_notify, ctx.guild_id)

    if remaining_slots < 0:
        # check_category_space returns -1 when the check itself failed. Fail closed:
        # attempting a create we could not validate is how channels get orphaned.
        await ctx.interaction.edit_initial_response(
            content=f"❌ Could not verify space in the {ticket_title} ticket category.\n"
                    f"Please try again in a moment or contact an administrator."
        )
        return

    if remaining_slots == 0:
        # Send error response
        await ctx.interaction.edit_initial_response(
            content=f"❌ The {ticket_title} ticket category is full!\nPlease contact an administrator."
        )
        return

    creation_id = _creation_id(ctx.guild_id, user_id, ticket_type)
    creation_claimed = False
    channel = None
    thread = None
    channel_name = None
    channel_create_started = False
    ticket_data = None
    ticket_persisted = False

    # Use the in-process semaphore to reduce Discord rate pressure. The Mongo
    # lease below is the cross-process/restart idempotency boundary.
    async with channel_creation_semaphore:
        try:
            existing_ticket = await find_open_ticket(mongo, user_id, ticket_type)
            if existing_ticket:
                await ctx.interaction.edit_initial_response(
                    content=(
                        f"✅ You already have an open {ticket_title} ticket.\n"
                        f"Please check <#{existing_ticket['channel_id']}>"
                    )
                )
                return

            creation_claimed, creation_state = await claim_ticket_creation(
                mongo,
                ctx.guild_id,
                user_id,
                ticket_type,
            )
            if (
                not creation_claimed
                and (
                    creation_state.get("channel_id")
                    or creation_state.get("state") == "cleanup_required"
                )
                and await release_missing_channel_blocker(bot, mongo, creation_state)
            ):
                creation_claimed, creation_state = await claim_ticket_creation(
                    mongo,
                    ctx.guild_id,
                    user_id,
                    ticket_type,
                )
            if not creation_claimed:
                existing_channel = creation_state.get("channel_id")
                if existing_channel:
                    await ctx.interaction.edit_initial_response(
                        content=(
                            "⚠️ A previous ticket attempt already created a channel "
                            f"(<#{existing_channel}>). Another was not created.\n"
                            "Please contact an administrator if it needs cleanup."
                        )
                    )
                elif creation_state.get("state") == "cleanup_required":
                    await ctx.interaction.edit_initial_response(
                        content=(
                            "⚠️ A previous ticket attempt could not be reconciled safely.\n"
                            "Another was not created. Please contact an administrator."
                        )
                    )
                else:
                    await ctx.interaction.edit_initial_response(
                        content=(
                            f"⏳ Your {ticket_title} ticket is already being created.\n"
                            "Please wait a moment instead of submitting it again."
                        )
                    )
                return

            ticket_number = await reserve_ticket_number(mongo, ticket_type)
            await update_creation_state(
                mongo,
                creation_id,
                ticket_number=ticket_number,
                category_id=category_id,
            )
            print(
                f"[Tickets] Reserved {ticket_type} ticket number {ticket_number} "
                f"for user {user_id}"
            )

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
            await update_creation_state(
                mongo,
                creation_id,
                channel_name=channel_name,
            )

            channel_create_started = True
            channel = await bot.rest.create_guild_text_channel(
                guild=ctx.guild_id,
                name=channel_name,
                category=category_id,
                permission_overwrites=permission_overwrites,
                reason=f"{ticket_title} ticket for {ctx.user.username}"
            )
            await update_creation_state(
                mongo,
                creation_id,
                channel_id=int(channel.id),
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
            await update_creation_state(
                mongo,
                creation_id,
                thread_id=int(thread.id),
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
                "guild_id": ctx.guild_id,
                "channel_id": channel.id,
                "thread_id": thread.id,
                "category_id": category_id,
                "user_id": ctx.user.id,
                "username": ctx.user.username,
                "created_at": datetime.now(timezone.utc),
                "status": "open",
            }
            await store.insert_one(mongo, ticket_data)
            ticket_persisted = True
            await complete_creation_state(
                mongo,
                creation_id,
                channel.id,
                thread.id,
                ticket_data["_id"],
            )

            # Everything below is post-commit setup. A message failure must not
            # turn a real, durable ticket into an apparent creation failure.
            try:
                await asyncio.sleep(0.5)

                if recruiter_role:
                    await bot.rest.create_message(
                        thread.id,
                        content=(
                            f"<@&{recruiter_role}> <@&1078723854316355595> "
                            "this is a private thread for the candidate. They cannot see this thread, "
                            "so DO NOT ping them, as it will add them.\n\n"
                        ),
                        role_mentions=True
                    )
                    print(f"[Tickets] Posted message in thread {thread.id} and pinged role {recruiter_role}")
                else:
                    await bot.rest.create_message(
                        thread.id,
                        content=(
                            "⚠️ No recruiter role configured for this ticket type. "
                            "Please configure roles using `/ticket config`"
                        )
                    )
                    print(f"[Tickets] No recruiter role configured for {ticket_type} tickets")

                first_message = (
                    "Hello there 👋🏻...how you hear about Warriors United?"
                    if ticket_type == "main"
                    else "Hello there 👋🏻...how you hear about our FWA Operation?"
                )
                await bot.rest.create_message(thread.id, content=first_message)
                await bot.rest.create_message(
                    thread.id,
                    content=(
                        "What was the hook that reeled you in? The thing that said "
                        "\"yeah, I need to check these guys out!!!\""
                    ),
                )
                if ticket_type == "fwa":
                    await bot.rest.create_message(
                        thread.id,
                        content=(
                            "Donations are better with the update allowing loot to be used "
                            "but clan chats are and can be sporadic."
                        ),
                    )
                print(f"[Tickets] Posted initial messages in thread {thread.id} for {ticket_type} ticket")
            except Exception as setup_error:
                print(
                    "[Tickets] WARNING ticket_postcommit_setup_failed "
                    f"ticket_id={ticket_data['_id']} "
                    f"error={type(setup_error).__name__}"
                )

            # Send success message as response
            await ctx.interaction.edit_initial_response(
                content=f"✅ Your {ticket_title} ticket has been created!\nPlease check <#{channel.id}>"
            )

        except hikari.errors.RateLimitTooLongError as e:
            # Preserve the existing rate-limit behavior and release any creation
            # lease because Discord did not accept the operation.
            user_cooldowns[user_id] = current_time + timedelta(seconds=RATE_LIMIT_BACKOFF)
            if creation_claimed and not ticket_persisted:
                await rollback_ticket_creation(
                    bot,
                    mongo,
                    creation_id,
                    int(channel.id) if channel is not None else None,
                    e,
                )
            print(f"[Tickets] Rate limit exceeded maximum wait time: {e}")
            await ctx.interaction.edit_initial_response(
                content=(
                    "⏰ **Discord Rate Limit Active**\n\n"
                    "Too many channels were created recently. Please try again in a few minutes."
                )
            )
        except Exception as e:
            discord_check_failed = None
            if (
                creation_claimed
                and channel is None
                and channel_name is not None
                and channel_create_started
            ):
                try:
                    channel = await locate_uncertain_channel(
                        bot,
                        ctx.guild_id,
                        category_id,
                        channel_name,
                    )
                    if channel is not None:
                        print(
                            "[Tickets] creation_channel_confirmed_after_error "
                            f"creation_id={creation_id} channel_id={channel.id}"
                        )
                except Exception as check_error:
                    discord_check_failed = check_error

            commit_check_failed = None
            if not ticket_persisted and ticket_data is not None:
                try:
                    committed = await store.find_one(
                        mongo,
                        {"_id": ticket_data["_id"]},
                    )
                except Exception as check_error:
                    committed = None
                    commit_check_failed = check_error
                if committed is not None:
                    ticket_persisted = True
                    print(
                        "[Tickets] creation_commit_confirmed_after_error "
                        f"ticket_id={ticket_data['_id']} "
                        f"original_error={type(e).__name__}"
                    )

            print(
                "[Tickets] creation_failed "
                f"creation_id={creation_id} error={type(e).__name__} "
                f"detail={_error_detail(e)}"
            )
            if ticket_persisted:
                # The primary ticket record is the commit point. Even if the
                # completion marker or interaction response failed, retry lookup
                # returns this ticket rather than creating another.
                await ctx.interaction.edit_initial_response(
                    content=(
                        f"✅ Your {ticket_title} ticket was created.\n"
                        f"Please check <#{channel.id}>"
                    )
                )
                return

            if discord_check_failed is not None:
                now = datetime.now(timezone.utc)
                try:
                    await mongo.ticket_creation_state.update_one(
                        {"_id": creation_id},
                        {
                            "$set": {
                                "state": "cleanup_required",
                                "channel_name": channel_name,
                                "category_id": category_id,
                                "last_error": type(e).__name__,
                                "channel_check_error": type(discord_check_failed).__name__,
                                "updated_at": now,
                                "expires_at": now + CREATION_RETENTION,
                            },
                            "$unset": {"lease_until": ""},
                        },
                    )
                except Exception as state_error:
                    print(
                        "[Tickets] ALERT creation_channel_uncertain_state_failed "
                        f"creation_id={creation_id} error={type(state_error).__name__}"
                    )
                print(
                    "[Tickets] ALERT creation_channel_uncertain "
                    f"creation_id={creation_id} "
                    f"error={type(discord_check_failed).__name__}"
                )
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⚠️ Discord could not confirm whether the ticket channel was created.\n"
                        "Another ticket was not created. Please contact an administrator."
                    )
                )
                return

            if commit_check_failed is not None and channel is not None:
                # A timed-out Mongo write can have committed server-side. When
                # Mongo is also unavailable for confirmation, deleting Discord
                # would risk leaving a durable record pointing at nothing. Keep
                # the blocker and require reconciliation instead.
                now = datetime.now(timezone.utc)
                try:
                    await mongo.ticket_creation_state.update_one(
                        {"_id": creation_id},
                        {
                            "$set": {
                                "state": "cleanup_required",
                                "channel_id": int(channel.id),
                                "thread_id": (
                                    int(thread.id) if thread is not None else None
                                ),
                                "last_error": type(e).__name__,
                                "commit_check_error": type(commit_check_failed).__name__,
                                "updated_at": now,
                                "expires_at": now + CREATION_RETENTION,
                            },
                            "$unset": {"lease_until": ""},
                        },
                    )
                except Exception as state_error:
                    print(
                        "[Tickets] ALERT creation_commit_uncertain_state_failed "
                        f"creation_id={creation_id} channel_id={channel.id} "
                        f"error={type(state_error).__name__}"
                    )
                print(
                    "[Tickets] ALERT creation_commit_uncertain "
                    f"creation_id={creation_id} channel_id={channel.id} "
                    f"error={type(commit_check_failed).__name__}"
                )
                await ctx.interaction.edit_initial_response(
                    content=(
                        "⚠️ Ticket creation could not be confirmed safely.\n"
                        "Another ticket was not created. Please contact an administrator."
                    )
                )
                return

            cleanup_ok = True
            if creation_claimed:
                cleanup_ok = await rollback_ticket_creation(
                    bot,
                    mongo,
                    creation_id,
                    int(channel.id) if channel is not None else None,
                    e,
                )
            if cleanup_ok:
                content = (
                    "❌ Your ticket could not be created. Nothing was left behind.\n"
                    "Please try again in a moment or contact an administrator."
                )
            else:
                content = (
                    "⚠️ Ticket creation stopped, but Discord cleanup also failed.\n"
                    "Another ticket was not created. Please contact an administrator."
                )
            await ctx.interaction.edit_initial_response(content=content)
