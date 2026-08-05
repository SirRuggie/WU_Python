# extensions/events/channel/ticket_channel_monitor.py
"""Event listener for monitoring new channel creation for ticket channels"""

import asyncio
import hikari
import lightbulb
import coc
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from utils.mongo import MongoClient
from extensions.commands.tickets import store
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

TICKET_LOOKUP_ATTEMPTS = 20
TICKET_LOOKUP_DELAY_SECONDS = 0.5
DELIVERY_ATTEMPTS = 3
DELIVERY_RETRY_DELAY_SECONDS = 1
DELIVERY_LEASE = timedelta(minutes=2)


async def wait_for_ticket_data(
        mongo: MongoClient,
        channel_id: int,
        *,
        attempts: int = TICKET_LOOKUP_ATTEMPTS,
        delay: float = TICKET_LOOKUP_DELAY_SECONDS,
):
    """Poll briefly for the ticket row created after the channel event fires."""
    lookup_id = f"ticket_{channel_id}"
    for attempt in range(max(1, attempts)):
        ticket_data = await store.find_one(mongo, {"_id": lookup_id})
        if ticket_data:
            return ticket_data
        if attempt + 1 < attempts:
            await asyncio.sleep(delay)
    return None


async def claim_automation_delivery(
        mongo: MongoClient,
        automation_doc: dict,
        *,
        now: datetime | None = None,
):
    """Claim one channel's initial-message delivery across processes.

    A non-matching upsert races with the existing ``_id`` and raises
    ``DuplicateKeyError``. That is the expected "another worker owns it" result.
    """
    now = now or datetime.now(timezone.utc)
    channel_key = automation_doc["_id"]
    query = {
        "_id": channel_key,
        "$or": [
            {"initial_delivery.status": {"$exists": False}},
            {"initial_delivery.status": "retry"},
            {
                "initial_delivery.status": "processing",
                "initial_delivery.lease_until": {"$lte": now},
            },
        ],
    }
    update = {
        "$setOnInsert": automation_doc,
        "$set": {
            "initial_delivery.status": "processing",
            "initial_delivery.lease_until": now + DELIVERY_LEASE,
            "initial_delivery.updated_at": now,
        },
        "$unset": {"initial_delivery.last_error": ""},
    }
    try:
        return await mongo.ticket_automation_state.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None


async def mark_delivery_step(mongo: MongoClient, channel_id: int, step: str) -> None:
    await mongo.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {"$set": {
            f"initial_delivery.{step}": True,
            "initial_delivery.updated_at": datetime.now(timezone.utc),
        }},
    )


async def finish_automation_delivery(mongo: MongoClient, channel_id: int) -> None:
    now = datetime.now(timezone.utc)
    await mongo.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {
            "$set": {
                "initial_delivery.status": "complete",
                "initial_delivery.completed_at": now,
                "initial_delivery.updated_at": now,
            },
            "$unset": {"initial_delivery.lease_until": ""},
        },
    )


async def release_automation_delivery(
        mongo: MongoClient,
        channel_id: int,
        error: Exception | str,
) -> None:
    await mongo.ticket_automation_state.update_one(
        {"_id": str(channel_id)},
        {
            "$set": {
                "initial_delivery.status": "retry",
                "initial_delivery.last_error": str(error)[:500],
                "initial_delivery.updated_at": datetime.now(timezone.utc),
            },
            "$unset": {"initial_delivery.lease_until": ""},
        },
    )


async def send_with_retries(rest, **kwargs) -> None:
    """Send one message with a short bounded retry window."""
    last_error = None
    for attempt in range(DELIVERY_ATTEMPTS):
        try:
            await rest.create_message(**kwargs)
            return
        except Exception as exc:  # noqa: BLE001 - Discord errors are retried uniformly
            last_error = exc
            if attempt + 1 < DELIVERY_ATTEMPTS:
                await asyncio.sleep(DELIVERY_RETRY_DELAY_SECONDS)
    raise last_error or RuntimeError("message delivery failed")


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

    # Get the channel ID
    channel_id = event.channel.id

    # Try to find the ticket data from MongoDB - it's stored immediately by ticket creation
    ticket_data = None
    user_id = None
    thread_id = None

    if mongo_client:
        try:
            print(f"[DEBUG] Waiting for ticket with _id: ticket_{channel_id}")
            ticket_data = await wait_for_ticket_data(mongo_client, channel_id)
            if ticket_data:
                user_id = ticket_data.get("user_id")  # This is stored as int
                thread_id = ticket_data.get("thread_id")  # This is stored as int
                print(
                    f"[DEBUG] Found ticket data: user_id={user_id}, thread_id={thread_id}, ticket_type={ticket_data.get('ticket_type')}")
            else:
                print(
                    f"[ERROR] No ticket data found for channel {channel_id} after "
                    f"{TICKET_LOOKUP_ATTEMPTS} attempts"
                )
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

    # Create and atomically claim the automation state document.
    claimed_automation = None
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

            claimed_automation = await claim_automation_delivery(
                mongo_client, automation_doc,
            )
            if not claimed_automation:
                print(
                    f"[DEBUG] Initial ticket delivery for channel {channel_id} "
                    "is already complete or owned by another worker"
                )
                return
            print(f"[DEBUG] Claimed ticket automation delivery for channel {channel_id}")

        except Exception as e:
            print(f"[ERROR] Failed to claim ticket automation state: {e}")
            return

    delivery_state = (claimed_automation or {}).get("initial_delivery", {})

    # Prepare the message components based on ticket type
    is_fwa = matched_pattern == "FWA"
    is_main = matched_pattern == "MAIN"

    if is_fwa:
        # Get FWA recruiter role from config
        try:
            config = await mongo_client.ticket_setup.find_one({"_id": "config"}) or {}
        except Exception as e:
            print(f"[ERROR] Failed to load FWA ticket configuration: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return
        fwa_recruiter_role = config.get("fwa_recruiter_role")

        # Send initial welcome message
        welcome_message = f"<@{user_id}> Welcome! Thank you for your interest! "
        if fwa_recruiter_role:
            welcome_message += f"<@&{fwa_recruiter_role}> "
        else:
            welcome_message += "**@FWA Recruiter** "
        welcome_message += "will be with you shortly, in the meanwhile, please answer the following questions..."

        try:
            if not delivery_state.get("welcome_sent"):
                await send_with_retries(
                    event.app.rest,
                channel=channel_id,
                content=welcome_message,
                user_mentions=True,
                role_mentions=True if fwa_recruiter_role else False
                )
                await mark_delivery_step(mongo_client, channel_id, "welcome_sent")
                print(f"[DEBUG] Sent FWA welcome message to channel {channel_id}")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"[ERROR] Failed to send FWA welcome message: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return

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
            if not delivery_state.get("questionnaire_sent"):
                await send_with_retries(
                    event.app.rest,
                    channel=channel_id,
                    components=components,
                    user_mentions=True,
                )
                await mark_delivery_step(mongo_client, channel_id, "questionnaire_sent")
                print(f"[DEBUG] Successfully sent FWA questionnaire to channel {channel_id}")
            await finish_automation_delivery(mongo_client, channel_id)
        except Exception as e:
            print(f"[ERROR] Failed to send FWA questionnaire to channel {channel_id}: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return

    elif is_main:
        # Get MAIN recruiter role from config (for now using same config structure)
        try:
            config = await mongo_client.ticket_setup.find_one({"_id": "config"}) or {}
        except Exception as e:
            print(f"[ERROR] Failed to load MAIN ticket configuration: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return
        main_recruiter_role = config.get("main_recruiter_role")  # You'll need to add this to config later

        # Send initial welcome message (identical structure for now)
        welcome_message = f"<@{user_id}> Welcome! Thank you for your interest! "
        if main_recruiter_role:
            welcome_message += f"<@&{main_recruiter_role}> "
        else:
            welcome_message += "**@Main Recruiter** "
        welcome_message += "will be with you shortly, in the meanwhile, please answer the following questions..."

        try:
            if not delivery_state.get("welcome_sent"):
                await send_with_retries(
                    event.app.rest,
                channel=channel_id,
                content=welcome_message,
                user_mentions=True,
                role_mentions=True if main_recruiter_role else False
                )
                await mark_delivery_step(mongo_client, channel_id, "welcome_sent")
                print(f"[DEBUG] Sent MAIN welcome message to channel {channel_id}")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"[ERROR] Failed to send MAIN welcome message: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return

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
            if not delivery_state.get("questionnaire_sent"):
                await send_with_retries(
                    event.app.rest,
                    channel=channel_id,
                    components=components,
                    user_mentions=True,
                )
                await mark_delivery_step(mongo_client, channel_id, "questionnaire_sent")
                print(f"[DEBUG] Successfully sent MAIN questionnaire to channel {channel_id}")
            await finish_automation_delivery(mongo_client, channel_id)
        except Exception as e:
            print(f"[ERROR] Failed to send MAIN questionnaire to channel {channel_id}: {e}")
            await release_automation_delivery(mongo_client, channel_id, e)
            return
