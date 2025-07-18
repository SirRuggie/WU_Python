# extensions/events/channel/ticket_channel_monitor.py
"""Event listener for monitoring new channel creation for ticket channels"""

import asyncio
import aiohttp
import hikari
import lightbulb
import coc
from datetime import datetime, timedelta, timezone
from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT
from utils.emoji import emojis

# Import Components V2
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

# Import FWA chocolate components
try:
    from extensions.events.message.ticket_automation.fwa.utils.chocolate_components import (
        send_chocolate_link
    )

    HAS_FWA_CHOCOLATE = True
except ImportError:
    HAS_FWA_CHOCOLATE = False
    print("[WARNING] FWA chocolate components not found, chocolate links will be disabled")

loader = lightbulb.Loader()

# Add debug print when module loads
print("[INFO] Loading ticket_channel_monitor extension...")

# Global variables to store instances
mongo_client = None
coc_client = None

# Define the patterns we're looking for
# These are the special characters/patterns to match
PATTERNS = {
    "TEST": "𝕋𝔼𝕊𝕋",  # Active
    "CLAN": "ℂ𝕃𝔸ℕ",  # Disabled for now
    "FWA": "𝔽𝕎𝔸",  # Disabled for now
    "FWA_TEST": "𝕋-𝔽𝕎𝔸"  # Add this!
}

# Define which patterns are currently active
ACTIVE_PATTERNS = ["TEST", "FWA_TEST", "CLAN", "FWA"]


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
        return

    # Wait 3 seconds before proceeding
    await asyncio.sleep(5)

    # Get the channel ID
    channel_id = event.channel.id

    # Try to find any threads in this channel
    thread_id = None
    try:
        # Fetch active threads for the guild
        active_threads = await event.app.rest.fetch_active_threads(event.guild_id)

        # Look for a thread in our channel
        for thread in active_threads:
            if thread.parent_id == channel_id:
                thread_id = thread.id
                print(f"[DEBUG] Found thread {thread_id} in channel {channel_id}")
                break

        # If no active thread found, try to fetch the channel to see if it's a thread
        if not thread_id:
            # Sometimes the "channel" itself might be a thread
            channel_info = await event.app.rest.fetch_channel(channel_id)
            if channel_info.type in [hikari.ChannelType.GUILD_PUBLIC_THREAD,
                                     hikari.ChannelType.GUILD_PRIVATE_THREAD,
                                     hikari.ChannelType.GUILD_NEWS_THREAD]:
                # The channel itself is a thread
                thread_id = channel_id
                channel_id = channel_info.parent_id
                print(f"[DEBUG] The created channel is actually a thread")

        # If still no thread found, wait a bit more and check again
        # (sometimes thread creation is delayed)
        if not thread_id:
            await asyncio.sleep(2)  # Wait 2 more seconds
            try:
                active_threads = await event.app.rest.fetch_active_threads(event.guild_id)
                for thread in active_threads:
                    if thread.parent_id == channel_id:
                        thread_id = thread.id
                        print(f"[DEBUG] Found thread {thread_id} after additional wait")
                        break
            except Exception as e:
                print(f"[DEBUG] Error on second thread fetch attempt: {e}")

        # Also check for archived threads (in case it was instantly archived)
        if not thread_id:
            try:
                # Check if the channel is a forum channel
                if event.channel.type == hikari.ChannelType.GUILD_FORUM:
                    # For forum channels, threads are the posts
                    threads = await event.app.rest.fetch_public_archived_threads(channel_id)
                    if threads:
                        # Get the most recent thread
                        thread_id = threads[0].id
                        print(f"[DEBUG] Found forum post/thread: {thread_id}")
            except Exception as e:
                print(f"[DEBUG] Error checking for forum threads: {e}")

    except Exception as e:
        print(f"[DEBUG] Error fetching threads: {e}")

    # Make API call to get ticket information
    api_data = None
    player_data = None
    stored_in_db = False

    try:
        async with aiohttp.ClientSession() as session:
            api_url = f"https://api.clashk.ing/ticketing/open/json/{channel_id}"
            print(f"[DEBUG] Making API call to: {api_url}")

            async with session.get(api_url) as response:
                if response.status == 200:
                    api_data = await response.json()
                    print(f"[DEBUG] API response: {api_data}")

                    # Fetch player data using coc.py if apply_account exists
                    # Add retry logic here (3 attempts)
                    if api_data.get('apply_account') and coc_client:
                        player_tag = api_data.get('apply_account')
                        print(f"[DEBUG] Fetching player data for tag: {player_tag}")

                        max_retries = 3
                        retry_count = 0

                        while retry_count < max_retries:
                            try:
                                player_data = await coc_client.get_player(player_tag)
                                print(f"[DEBUG] Player found: {player_data.name} (TH{player_data.town_hall})")
                                break  # Success, exit retry loop
                            except coc.NotFound:
                                print(f"[ERROR] Player not found: {player_tag}")
                                break  # Don't retry for not found
                            except Exception as e:
                                retry_count += 1
                                print(f"[ERROR] Failed to fetch player (attempt {retry_count}/{max_retries}): {e}")
                                if retry_count < max_retries:
                                    await asyncio.sleep(1)  # Wait 1 second before retry
                                else:
                                    print(f"[ERROR] Max retries reached for player fetch")
                else:
                    print(f"[ERROR] API returned status {response.status}")
    except Exception as e:
        print(f"[ERROR] Failed to call API: {e}")

    # Store in MongoDB if we have API data and player info
    if api_data and api_data.get('apply_account') and mongo_client:
        try:
            # Create new recruit entry
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            recruit_doc = {
                # Player info
                "player_tag": api_data.get('apply_account'),
                "player_name": player_data.name if player_data else None,
                "player_th_level": player_data.town_hall if player_data else None,

                # Discord/Ticket (store as strings)
                "discord_user_id": str(api_data.get('user')),
                "ticket_channel_id": str(api_data.get('channel')),
                "ticket_thread_id": str(api_data.get('thread')),

                # Timestamps
                "created_at": now,
                "expires_at": now + timedelta(days=12),

                # Initial state
                "recruitment_history": [],
                "current_clan": None,
                "total_clans_joined": 0,
                "is_expired": False,

                "activeBid": False
            }

            # Insert into MongoDB
            result = await mongo_client.new_recruits.insert_one(recruit_doc)
            print(f"[DEBUG] Stored new recruit in MongoDB: {result.inserted_id}")
            stored_in_db = True

            # Create ticket automation state
            try:
                automation_doc = {
                    "_id": str(channel_id),
                    "ticket_info": {
                        "channel_id": str(channel_id),
                        "thread_id": str(api_data.get('thread', '')),
                        "user_id": str(api_data.get('user')),
                        "user_tag": api_data.get('apply_account'),  # Add this for FWA
                        "ticket_type": matched_pattern,  # TEST, CLAN, or FWA
                        "ticket_number": api_data.get('number'),
                        "created_at": now,
                        "last_updated": now
                    },
                    "player_info": {
                        "player_tag": api_data.get('apply_account'),
                        "player_name": player_data.name if player_data else None,
                        "town_hall": player_data.town_hall if player_data else None,
                        "clan_tag": player_data.clan.tag if player_data and player_data.clan else None,
                        "clan_name": player_data.clan.name if player_data and player_data.clan else None
                    },
                    "automation_state": {
                        "current_step": "awaiting_screenshot",
                        "current_step_index": 1,
                        "total_steps": 5,
                        "status": "active",
                        "completed_steps": [
                            {
                                "step_name": "ticket_created",
                                "completed_at": now,
                                "data": {"api_response": api_data}
                            }
                        ]
                    },
                    "step_data": {
                        "screenshot": {
                            "uploaded": False,
                            "uploaded_at": None,
                            "reminder_sent": False,
                            "reminder_count": 0,
                            "last_reminder_at": None
                        },
                        "clan_selection": {
                            "selected_clan_type": None,
                            "selected_at": None
                        },
                        "questionnaire": {
                            "responses": {},
                            "completed_at": None
                        },
                        "final_placement": {
                            "assigned_clan": None,
                            "assigned_at": None,
                            "approved_by": None
                        }
                    },
                    "messages": {
                        "initial_prompt": str(event.channel.id)  # The message we're about to send
                    },
                    "interaction_history": [
                        {
                            "timestamp": now,
                            "action": "ticket_created",
                            "details": f"Ticket created for user {api_data.get('user')}"
                        }
                    ]
                }

                # Insert the automation state
                await mongo_client.ticket_automation_state.insert_one(automation_doc)
                print(f"[DEBUG] Created ticket automation state for channel {channel_id}")

            except Exception as e:
                print(f"[ERROR] Failed to create ticket automation state: {e}")
                # Don't fail the whole process if automation state fails

        except Exception as e:
            print(f"[ERROR] Failed to store in MongoDB: {e}")
            stored_in_db = False
    else:
        stored_in_db = False

    # Prepare the message components
    if api_data and stored_in_db:
        # Check if this is an FWA ticket
        is_fwa = matched_pattern in ["FWA", "FWA_TEST"]

        if is_fwa:
            # For FWA tickets, send war weight request using exact recruit questions format
            components = [
                Container(
                    accent_color=GOLD_ACCENT,
                    components=[
                        Text(content=f"## ⚖️ **War Weight Check** · <@{api_data.get('user', '')}>"),
                        Separator(divider=True),
                        Text(content=(
                            "We need your **current war weight** to ensure fair matchups. Please:\n\n"
                            f"{emojis.red_arrow_right} **Post** a Friendly Challenge in-game.\n"
                            f"{emojis.red_arrow_right} **Scout** that challenge you posted\n"
                            f"{emojis.red_arrow_right} **Tap** on your Town Hall, then hit **Info**.\n"
                            f"{emojis.red_arrow_right} **Upload** a screenshot of the Town Hall info popup here.\n\n"
                            "*See the example below for reference.*"
                        )),
                        Media(
                            items=[
                                MediaItem(
                                    media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751550804/TH_Weight.png"),
                            ]
                        ),
                        Text(content=f"-# Requested by Kings Alliance FWA Recruitment"),
                    ]
                )
            ]

            # Send chocolate link to thread using centralized function
            if player_data and thread_id and HAS_FWA_CHOCOLATE:
                await send_chocolate_link(
                    bot=event.app,
                    channel_id=thread_id,
                    player_tag=player_data.tag,
                    player_name=player_data.name
                )
                print(f"[DEBUG] Sent chocolate link to thread {thread_id}")
        else:
            # Regular ticket - existing screenshot request
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content=f"<@{api_data.get('user', '')}>\n\n"),
                        Separator(divider=True, spacing=hikari.SpacingType.LARGE),
                        Text(content=(
                            f"{emojis.Alert_Strobing} **SCREENSHOT REQUIRED** {emojis.Alert_Strobing}\n"
                            "-# Provide a screenshot of your base."
                        )),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                        Text(content=(
                            f"-# **Kings Alliance Recruitment** - Your base layout says a lot about you—make it a good one!"
                        ))
                    ]
                )
            ]
    else:
        # Fallback error message if something went wrong
        # Try to get user ID from the channel name pattern
        user_mention = ""
        if api_data and api_data.get('user'):
            user_mention = f"<@{api_data.get('user')}> "

        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=f"{emojis.Alert} **Error Processing Ticket** {emojis.Alert}"),
                    Separator(divider=True),
                    Text(content=(
                        f"{user_mention}**Channel ID:** `{channel_id}`\n"
                        f"**Thread ID:** `{thread_id if thread_id else 'No thread found'}`\n\n"
                        f"**Status:** {'❌ Failed to store in database' if api_data else '❌ API unavailable'}\n\n"
                        f"Please contact an administrator if this issue persists."
                    )),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]

    # Send message in the new channel
    try:
        await event.app.rest.create_message(
            channel=event.channel.id,
            components=components,
            user_mentions=True  # Enable user mentions so the ping works
        )
        print(f"[DEBUG] Successfully sent message to channel {event.channel.id}")
    except Exception as e:
        print(f"[ERROR] Failed to send message to channel {event.channel.id}: {e}")