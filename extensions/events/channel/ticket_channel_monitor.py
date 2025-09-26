# extensions/events/channel/ticket_channel_monitor.py
"""Event listener for monitoring new channel creation for ticket channels"""

import asyncio
import hikari
import lightbulb
import coc
from datetime import datetime, timezone
from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT, GOLDENROD_ACCENT
from utils.emoji import emojis

# Import Components V2
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
)

loader = lightbulb.Loader()

# Add debug print when module loads
print("[INFO] Loading ticket_channel_monitor extension...")

# Global variables to store instances
mongo_client = None
coc_client = None

# Define the patterns we're looking for
PATTERNS = {
    "MAIN": "main",
    "FWA": "fwa",
}

# Define which patterns are currently active
ACTIVE_PATTERNS = ["MAIN", "FWA"]


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_api: coc.Client = lightbulb.di.INJECTED
) -> None:
    """Store instances when bot starts"""
    global mongo_client, coc_client
    mongo_client = mongo
    coc_client = coc_api
    print("[INFO] Ticket channel monitor ready with MongoDB and CoC connections")


@loader.listener(hikari.GuildChannelCreateEvent)
async def on_channel_create(event: hikari.GuildChannelCreateEvent) -> None:
    """Handle channel creation events"""

    # Get the channel name
    channel_name = event.channel.name

    guild = event.app.cache.get_guild(event.guild_id)
    guild_icon_url = guild.make_icon_url() if guild else None

    # Debug logging
    print(f"[DEBUG] New channel created: {channel_name} (ID: {event.channel.id})")

    # Check if the channel name contains any of the active patterns
    matched = False
    matched_pattern = None
    for pattern_key in ACTIVE_PATTERNS:
        if pattern_key in PATTERNS and PATTERNS[pattern_key] in channel_name:
            matched = True
            matched_pattern = pattern_key
            print(f"[DEBUG] Channel matches pattern: {pattern_key}")
            break

    # If no match, return early
    if not matched:
        print(f"[DEBUG] Channel {channel_name} does not match any active patterns")
        return

    # Wait a bit for thread creation to complete
    await asyncio.sleep(3)

    # Get the channel ID
    channel_id = event.channel.id

    # Try to find the ticket data from MongoDB - it's stored immediately by ticket creation
    ticket_data = None
    user_id = None
    thread_id = None

    if mongo_client:
        try:
            # The ticket is stored with "_id": f"ticket_{channel_id}"
            lookup_id = f"ticket_{channel_id}"
            print(f"[DEBUG] Looking for ticket with _id: {lookup_id}")
            ticket_data = await mongo_client.button_store.find_one({"_id": lookup_id})
            if ticket_data:
                user_id = ticket_data.get("user_id")  # This is stored as int
                thread_id = ticket_data.get("thread_id")  # This is stored as int
                print(
                    f"[DEBUG] Found ticket data: user_id={user_id}, thread_id={thread_id}, ticket_type={ticket_data.get('ticket_type')}")
            else:
                print(f"[ERROR] No ticket data found for channel {channel_id}")
                return
        except Exception as e:
            print(f"[ERROR] Failed to fetch ticket data from MongoDB: {e}")
            return

    if not user_id:
        print(f"[ERROR] Could not find user_id in ticket data for channel {channel_id}")
        return

    # If we didn't get thread_id from MongoDB, try to find it
    if not thread_id:
        try:
            # Fetch active threads for the guild
            active_threads = await event.app.rest.fetch_active_threads(event.guild_id)

            # Look for a thread in our channel
            for thread in active_threads:
                if thread.parent_id == channel_id:
                    thread_id = thread.id
                    print(f"[DEBUG] Found thread {thread_id} in channel {channel_id}")
                    break

        except Exception as e:
            print(f"[DEBUG] Error fetching threads: {e}")

    # Create automation state document
    if mongo_client:
        try:
            now = datetime.now(timezone.utc)
            automation_doc = {
                "_id": str(channel_id),
                "channel_id": channel_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "ticket_type": matched_pattern.lower(),
                "created_at": now,
                "updated_at": now,
                "automation_state": {
                    "current_step": "initial",
                    "halted": False,
                    "halt_reason": None,
                    "completed": False,
                    "completed_at": None
                },
                "ticket_info": {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "player_tags": [],
                    "user_tag": None,
                    "clan_tags": []
                },
                "step_data": {
                    "account_collection": {
                        "started": False,
                        "completed": False,
                        "accounts": []
                    },
                    "questionnaire": {
                        "started": False,
                        "completed": False,
                        "current_question": None,
                        "responses": {}
                    },
                    "fwa": {
                        "is_fwa_ticket": matched_pattern == "FWA",
                        "started": False,
                        "completed": False
                    },
                    "manual_review": {
                        "required": False,
                        "reviewed": False,
                        "reviewer": None,
                        "review_notes": None
                    },
                    "final_placement": {
                        "assigned_clan": None,
                        "assigned_at": None,
                        "approved_by": None
                    }
                },
                "messages": {
                    "initial_prompt": str(channel_id)
                },
                "interaction_history": [
                    {
                        "timestamp": now,
                        "action": "ticket_created",
                        "details": f"Ticket created for user {user_id}"
                    }
                ]
            }

            # Insert the automation state
            await mongo_client.ticket_automation_state.insert_one(automation_doc)
            print(f"[DEBUG] Created ticket automation state for channel {channel_id}")

        except Exception as e:
            print(f"[ERROR] Failed to create ticket automation state: {e}")

    # Prepare the message components based on ticket type
    is_fwa = matched_pattern == "FWA"
    is_main = matched_pattern == "MAIN"

    if is_fwa:
        # Get FWA recruiter role from config
        config = await mongo_client.ticket_setup.find_one({"_id": "config"}) or {} if mongo_client else {}
        fwa_recruiter_role = config.get("fwa_recruiter_role")

        # Send initial welcome message
        welcome_message = f"<@{user_id}> Welcome! Thank you for your interest! "
        if fwa_recruiter_role:
            welcome_message += f"<@&{fwa_recruiter_role}> "
        else:
            welcome_message += "**@FWA Recruiter** "
        welcome_message += "will be with you shortly, in the meanwhile, please answer the following questions..."

        try:
            await event.app.rest.create_message(
                channel=channel_id,
                content=welcome_message,
                user_mentions=True,
                role_mentions=True if fwa_recruiter_role else False
            )
            print(f"[DEBUG] Sent FWA welcome message to channel {channel_id}")
        except Exception as e:
            print(f"[ERROR] Failed to send FWA welcome message: {e}")

        # Sleep 1 second
        await asyncio.sleep(1)

        # Send FWA entry questionnaire embed
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Section(
                        components=[
                            Text(content="## **Warriors United FWA Clan Entry Ticket**"),
                            Text(content=(
                                "1) In-game name & Player Tag\n"
                                "2) Age & Timezone. Country name would be good too.\n"
                                "3) Do you have multiple accounts?\n"
                                "4) If yes to #3, please provide all Player Tags.\n"
                                "5) What exactly are you looking for in a Clan?\n"
                                "6) Are you familiar with LazyCWL and the day to day FWA Process?"
                            )),
                        ],
                        accessory=Thumbnail(
                            media=guild_icon_url or "https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836911/misc_images/WU_Logo.png"
                        )
                    ),
                    # Main image
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836857/misc_images/WU_FWA_Ticket.jpg")
                        ]
                    ),
                    Text(content="-# Patience is key! A Recruiter will be with you soon.")
                ]
            )
        ]

        # Send message in the new channel
        try:
            await event.app.rest.create_message(
                channel=channel_id,
                components=components,
                user_mentions=True  # Enable user mentions so the ping works
            )
            print(f"[DEBUG] Successfully sent FWA questionnaire to channel {channel_id}")
        except Exception as e:
            print(f"[ERROR] Failed to send FWA questionnaire to channel {channel_id}: {e}")

    elif is_main:
        # Get MAIN recruiter role from config (for now using same config structure)
        config = await mongo_client.ticket_setup.find_one({"_id": "config"}) or {} if mongo_client else {}
        main_recruiter_role = config.get("main_recruiter_role")  # You'll need to add this to config later

        # Send initial welcome message (identical structure for now)
        welcome_message = f"<@{user_id}> Welcome! Thank you for your interest! "
        if main_recruiter_role:
            welcome_message += f"<@&{main_recruiter_role}> "
        else:
            welcome_message += "**@Main Recruiter** "
        welcome_message += "will be with you shortly, in the meanwhile, please answer the following questions..."

        try:
            await event.app.rest.create_message(
                channel=channel_id,
                content=welcome_message,
                user_mentions=True,
                role_mentions=True if main_recruiter_role else False
            )
            print(f"[DEBUG] Sent MAIN welcome message to channel {channel_id}")
        except Exception as e:
            print(f"[ERROR] Failed to send MAIN welcome message: {e}")

        # Sleep 1 second
        await asyncio.sleep(1)

        # Send MAIN entry questionnaire embed (identical structure for now, you can customize later)
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Section(
                        components=[
                            Text(content="## **Warriors United Main Clan Entry Ticket**"),
                            Text(content=(
                                "1) In-game name & Player Tag\n"
                                "2) Age & Timezone. Country name would be good too.\n"
                                "3) Do you have multiple accounts?\n"
                                "4) If yes to #3, please provide all Player Tags.\n"
                                "5) What exactly are you looking for in a Clan?"
                            )),
                        ],
                        accessory=Thumbnail(
                            media=guild_icon_url or "https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836911/misc_images/WU_Logo.png"
                        )
                    ),
                    # Main image
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836911/misc_images/WU_Logo.png")
                        ]
                    ),
                    Text(content="-# Patience is key! A Recruiter will be with you soon.")
                ]
            )
        ]

        # Send message in the new channel
        try:
            await event.app.rest.create_message(
                channel=channel_id,
                components=components,
                user_mentions=True  # Enable user mentions so the ping works
            )
            print(f"[DEBUG] Successfully sent MAIN questionnaire to channel {channel_id}")
        except Exception as e:
            print(f"[ERROR] Failed to send MAIN questionnaire to channel {channel_id}: {e}")