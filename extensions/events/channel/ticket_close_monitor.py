# extensions/events/channel/ticket_close_monitor.py
"""Event listener for monitoring ticket channel deletion and processing recruitment outcomes"""

import asyncio
import hikari
import lightbulb
import coc
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT, GREEN_ACCENT
from utils.emoji import emojis

# Import Components V2
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

loader = lightbulb.Loader()

# Add debug print when module loads
print("[INFO] Loading ticket_close_monitor extension...")

# Global variables to store instances
mongo_client = None
coc_client = None
bot_instance = None

# Log channel ID for recruitment outcomes
RECRUITMENT_LOG_CHANNEL = 1345589195695194113

# Define the patterns we're looking for (same as open monitor)
PATTERNS = {
    "TEST": "𝕋𝔼𝕊𝕋",  # Active
    "CLAN": "ℂ𝕃𝔸ℕ",  # Disabled for now
    "FWA": "𝔽𝕎𝔸"  # Disabled for now
}

# Define which patterns are currently active
ACTIVE_PATTERNS = ["TEST", "CLAN"]  # Only TEST is active for now


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_api: coc.Client = lightbulb.di.INJECTED
) -> None:
    """Store instances when bot starts"""
    global mongo_client, coc_client, bot_instance
    mongo_client = mongo
    coc_client = coc_api
    bot_instance = event.app
    print("[INFO] Ticket close monitor ready with MongoDB and CoC connections")


async def check_player_clan_membership(player_tag: str) -> Optional[Dict]:
    """Check if player joined any clan and get clan details"""
    try:
        player = await coc_client.get_player(player_tag)
        if player.clan:
            return {
                "tag": player.clan.tag,
                "name": player.clan.name,
                "badge_url": player.clan.badge.url if player.clan.badge else None
            }
        return None
    except Exception as e:
        print(f"[ERROR] Failed to fetch player {player_tag}: {e}")
        return None


async def get_clan_from_db(clan_tag: str) -> Optional[Dict]:
    """Get clan details from MongoDB"""
    try:
        clan = await mongo_client.clans.find_one({"tag": clan_tag})
        return clan
    except Exception as e:
        print(f"[ERROR] Failed to fetch clan {clan_tag} from DB: {e}")
        return None


async def process_no_bids_recruitment(recruit: Dict, player_clan: Dict, db_clan: Dict, bot_app):
    """Process and log recruitment outcome when no bids were placed"""

    # Calculate new expiration date
    new_expires = datetime.now(timezone.utc) + timedelta(days=12)

    # Create the recruitment outcome message
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=(
                    f"## Recruit Joined {db_clan.get('name', 'Unknown')} - "
                    f"TH{recruit.get('player_th_level', '??')}, but No Bids Placed"
                )),
                Separator(divider=True),
                Text(content="### Recruitment Outcome:"),
                Text(content=(
                    f"{db_clan.get('name', 'Unknown')} accepted the recruit, "
                    f"but no bids were placed during the window."
                )),
                Separator(divider=True, spacing=hikari.SpacingType.LARGE),
                Text(content=(
                    f"{emojis.Alert} **No points were deducted or refunded.**\n\n"
                    # f"📅 **12-day monitoring period has been refreshed**\n"
                    # f"-# New expiration: <t:{int(new_expires.timestamp())}:R>"
                )),
                Separator(divider=True),
                Text(content="### Player Details"),
                Text(content=(
                    f"• **Discord ID:** {recruit.get('discord_user_id', 'Unknown')}\n"
                    f"• **Name:** {recruit.get('player_name', 'Unknown')}\n"
                    f"• **Player Tag:** {recruit.get('player_tag', 'Unknown')}\n"
                    f"• **TH Level:** {recruit.get('player_th_level', '??')}"
                )),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    # Send to log channel
    try:
        await bot_app.rest.create_message(
            channel=RECRUITMENT_LOG_CHANNEL,
            components=components
        )
        print(f"[INFO] Logged no-bids recruitment for {recruit.get('player_tag')}")
    except Exception as e:
        print(f"[ERROR] Failed to send recruitment outcome message: {e}")


async def update_recruit_history(recruit: Dict, clan_tag: str):
    """Update recruit's history in MongoDB"""
    try:
        now = datetime.now(timezone.utc)
        new_expires_at = now + timedelta(days=12)

        await mongo_client.new_recruits.update_one(
            {"_id": recruit["_id"]},
            {
                "$set": {
                    "current_clan": clan_tag,
                    "ticket_closed_at": now,
                    # IMPORTANT: Refresh the 12-day monitoring period
                    "expires_at": new_expires_at,
                    "is_expired": False,  # Reset expiration status
                    "joined_clan_at": now  # Track when they actually joined
                },
                "$push": {
                    "recruitment_history": {
                        "clan_tag": clan_tag,
                        "recruited_at": now,
                        "bid_amount": 0,  # No bids placed
                        "recruited_by": "No Bids - Direct Join",
                        "left_at": None,
                        "duration_days": None,
                        "expires_at": new_expires_at  # Track expiration for this recruitment
                    }
                },
                "$inc": {
                    "total_clans_joined": 1
                }
            }
        )
        print(
            f"[INFO] Updated recruit history for {recruit.get('player_tag')} - 12-day monitor refreshed to {new_expires_at}")
    except Exception as e:
        print(f"[ERROR] Failed to update recruit history: {e}")


@loader.listener(hikari.GuildChannelDeleteEvent)
async def on_channel_delete(event: hikari.GuildChannelDeleteEvent) -> None:
    """Handle channel deletion events for ticket closures"""

    # Get the channel that was deleted
    channel = event.channel
    channel_name = channel.name
    channel_id = str(channel.id)

    # Debug logging
    print(f"[DEBUG] Channel deleted: {channel_name} (ID: {channel_id})")

    # Check if the channel name contains any of the active patterns
    matched = False
    for pattern_key in ACTIVE_PATTERNS:
        if pattern_key in PATTERNS and PATTERNS[pattern_key] in channel_name:
            matched = True
            print(f"[DEBUG] Deleted channel matches pattern: {pattern_key}")
            break

    # If no match, return early
    if not matched:
        return

    # Wait a moment to ensure database operations complete
    await asyncio.sleep(1)

    # Look up all recruits associated with this ticket channel
    try:
        recruits = await mongo_client.new_recruits.find({
            "ticket_channel_id": channel_id,
            "is_expired": False
        }).to_list(length=None)

        if not recruits:
            print(f"[DEBUG] No active recruits found for channel {channel_id}")
            return

        print(f"[INFO] Found {len(recruits)} recruit(s) for closed ticket {channel_id}")

        # Process each recruit
        for recruit in recruits:
            player_tag = recruit.get("player_tag")
            if not player_tag:
                continue

            print(f"[DEBUG] Processing recruit: {player_tag}")

            # Check if any bids were placed
            bid_data = await mongo_client.clan_bidding.find_one({
                "player_tag": player_tag,
                "is_finalized": False
            })

            # For this scenario, we only handle no bids + joined our clan
            if bid_data and bid_data.get("bids", []):
                print(f"[DEBUG] Recruit {player_tag} has bids - skipping no-bid processing")
                # TODO: Handle with-bids scenario
                await process_with_bids_recruitment(recruit, bid_data, player_clan, db_clan, event.app)
                continue

            # Check what clan the player joined
            player_clan = await check_player_clan_membership(player_tag)

            if not player_clan:
                print(f"[DEBUG] Player {player_tag} has not joined any clan")
                # Process the "didn't join any clan" scenario
                # FIX: Pass bid_data as second argument
                await process_no_clan_joined(recruit, bid_data, event.app)
                continue

            print(f"[DEBUG] Player {player_tag} joined clan: {player_clan['name']} ({player_clan['tag']})")

            # Check if the clan is in our database
            db_clan = await get_clan_from_db(player_clan["tag"])

            if not db_clan:
                print(f"[DEBUG] Clan {player_clan['tag']} not in our database")
                # Process external clan join
                await process_external_clan_join(recruit, player_clan, bid_data, event.app)

                # Update recruit record
                await mongo_client.new_recruits.update_one(
                    {"_id": recruit["_id"]},
                    {
                        "$set": {
                            "ticket_closed_at": datetime.now(timezone.utc),
                            "recruitment_outcome": "external_clan",
                            "external_clan_tag": player_clan["tag"],
                            "external_clan_name": player_clan["name"]
                        }
                    }
                )

                # Cancel any bids if they exist
                if bid_data:
                    await mongo_client.clan_bidding.update_one(
                        {"player_tag": player_tag, "is_finalized": False},
                        {"$set": {"is_finalized": True, "winner": "EXTERNAL_CLAN", "amount": 0}}
                    )
                continue

            print(f"[INFO] Processing no-bid recruitment: {player_tag} -> {db_clan['name']}")

            # Process the recruitment outcome
            await process_no_bids_recruitment(recruit, player_clan, db_clan, event.app)

            # Update recruit history
            await update_recruit_history(recruit, player_clan["tag"])

            # Mark any unfinalized bids as cancelled (though there shouldn't be any in this scenario)
            await mongo_client.clan_bidding.update_one(
                {
                    "player_tag": player_tag,
                    "is_finalized": False
                },
                {
                    "$set": {
                        "is_finalized": True,
                        "winner": "NO_BIDS_CANCELLED",
                        "amount": 0
                    }
                }
            )

    except Exception as e:
        print(f"[ERROR] Failed to process ticket closure: {e}")


# Additional handler for other recruitment outcome scenarios
async def process_no_clan_joined(recruit: Dict, bid_data: Optional[Dict], bot_app):
    """Process when player didn't join any clan after ticket closure"""

    # Determine if bids were placed
    has_bids = bid_data and bid_data.get("bids", [])

    # Create the message for no clan joined
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=(
                    f"## 🚫 Didn't Get Bid On - Left Server / Ticket Closed - TH{recruit.get('player_th_level', '??')}"
                    if not has_bids else
                    f"## ❌ Had Bids But Left - Ticket Closed - TH{recruit.get('player_th_level', '??')}"
                )),
                Separator(divider=True),
                Text(content="### Recruitment Details:"),
                Text(content=(
                    f"❌ Recruit left before any bids were placed.\n"
                    f"No points were gained or lost."
                    if not has_bids else
                    f"⚠️ Recruit had {len(bid_data['bids'])} bid(s) placed but left without joining.\n"
                    f"No points were deducted. All bids cancelled."
                )),
                Separator(divider=True),
                Text(content="### Player Details"),
                Text(content=(
                    f"• **Discord ID:** <@{recruit.get('discord_user_id', 'Unknown')}>\n"
                    f"• **Name:** {recruit.get('player_name', 'Unknown')}\n"
                    f"• **Player Tag:** {recruit.get('player_tag', 'Unknown')}\n"
                    f"• **TH Level:** {recruit.get('player_th_level', '??')}"
                )),
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]

    # Send to log channel
    try:
        await bot_app.rest.create_message(
            channel=RECRUITMENT_LOG_CHANNEL,
            components=components
        )
        print(f"[INFO] Logged no clan joined for {recruit.get('player_tag')}")
    except Exception as e:
        print(f"[ERROR] Failed to send no clan joined message: {e}")


async def process_external_clan_join(recruit: Dict, player_clan: Dict, bid_data: Optional[Dict], bot_app):
    """Process when player joined a clan not in our database"""

    # Determine if bids were placed
    has_bids = bid_data and bid_data.get("bids", [])

    # Create message for external clan join
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=(
                    f"## Recruit Joined External Clan - TH{recruit.get('player_th_level', '??')}"
                )),
                Separator(divider=True),
                Text(content="### Recruitment Outcome:"),
                Text(content=(
                    f"Player joined **{player_clan['name']}** ({player_clan['tag']})\n"
                    f"This clan is not part of our alliance.\n\n"
                    f"No points were deducted or awarded."
                    if not has_bids else
                    f"Player joined **{player_clan['name']}** ({player_clan['tag']})\n"
                    f"This clan is not part of our alliance.\n\n"
                    f"⚠️ {len(bid_data['bids'])} bid(s) were cancelled. No points deducted."
                )),
                Separator(divider=True),
                Text(content="### Player Details"),
                Text(content=(
                    f"• **Discord ID:** <@{recruit.get('discord_user_id', 'Unknown')}>\n"
                    f"• **Name:** {recruit.get('player_name', 'Unknown')}\n"
                    f"• **Player Tag:** {recruit.get('player_tag', 'Unknown')}\n"
                    f"• **TH Level:** {recruit.get('player_th_level', '??')}"
                )),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    # Send to log channel
    try:
        await bot_app.rest.create_message(
            channel=RECRUITMENT_LOG_CHANNEL,
            components=components
        )
        print(f"[INFO] Logged external clan join for {recruit.get('player_tag')}")
    except Exception as e:
        print(f"[ERROR] Failed to send external clan join message: {e}")


async def process_with_bids_recruitment(recruit: Dict, bid_data: Dict, player_clan: Dict, db_clan: Dict, bot_app):
    """Process recruitment when bids were placed - to be implemented"""
    # TODO: Implement logic for when bids were placed
    # This would include:
    # 1. Check if the winner matches the clan they joined
    # 2. Deduct points from winning clan
    # 3. Send appropriate success/failure messages
    # 4. IMPORTANT: Refresh 12-day monitor if they joined a tracked clan
    # 5. Update recruitment history with bid details

    # For now, just log it
    print(f"[TODO] Process with-bids recruitment for {recruit['player_tag']}")
    pass


async def process_expired_recruitment(recruit: Dict):
    """Process recruitment when 12-day window expired - to be implemented"""
    # TODO: Implement logic for expired recruitments
    # This handles when the refreshed 12-day period ends
    # 1. Check if player is still in the clan
    # 2. Mark recruitment as successful if they stayed
    # 3. Archive the recruitment data
    # 4. Send completion notification
    pass


async def process_left_clan_early(recruit: Dict, clan_tag: str, duration_days: int):
    """Process when recruit left clan before 12 days - to be implemented"""
    # TODO: Implement logic for early departures
    # This would include:
    # 1. Calculate how many days they stayed (out of 12)
    # 2. Calculate pro-rated point refund
    # 3. Update clan points balance
    # 4. Send early departure notification
    # 5. Update recruitment history with departure info
    pass