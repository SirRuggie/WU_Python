# extensions/commands/clan/report/helpers.py
"""Helper functions for clan report system"""

import re
from typing import Optional, List, Dict
from datetime import datetime

import hikari
from hikari.impl import SelectOptionBuilder as SelectOption

from utils.mongo import MongoClient
from utils.classes import Clan

# Channel IDs
APPROVAL_CHANNEL = 1348691451197784074
LOG_CHANNEL = 1345589195695194113
RECRUITMENT_PING = 1039311270614142977
# Regex for Discord message links
DISCORD_LINK_REGEX = re.compile(r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)")

# ╔══════════════════════════════════════════════════════════════╗
# ║                Progress Header Creation Utility              ║
# ╚══════════════════════════════════════════════════════════════╝

def create_progress_header(current_step: int, total_steps: int, steps: List[str]) -> str:
    """Create a progress indicator header"""
    parts = []
    for i, step in enumerate(steps):
        if i < current_step - 1:
            parts.append(f"{step} ✓")
        elif i == current_step - 1:
            parts.append(f"**{step}**")
        else:
            parts.append(step)

    return f"**Step {current_step} of {total_steps}** • " + " → ".join(parts)

# ╔══════════════════════════════════════════════════════════════╗
# ║                Parse Discord Link Utility                    ║
# ╚══════════════════════════════════════════════════════════════╝

def parse_discord_link(link: str) -> Optional[dict]:
    """Parse a Discord message link"""
    match = DISCORD_LINK_REGEX.match(link.strip())
    if match:
        return {
            "guild_id": int(match.group(1)),
            "channel_id": int(match.group(2)),
            "message_id": int(match.group(3))
        }
    return None

# ╔══════════════════════════════════════════════════════════════╗
# ║                Validate Discord ID Utility                   ║
# ╚══════════════════════════════════════════════════════════════╝

def validate_discord_id(discord_id: str) -> bool:
    """Validate a Discord user ID"""
    try:
        # Discord IDs are 17-19 digit numbers
        id_int = int(discord_id)
        return 10 ** 16 <= id_int < 10 ** 19
    except ValueError:
        return False

# ╔══════════════════════════════════════════════════════════════╗
# ║                   Get Clan By Tag Utility                    ║
# ╚══════════════════════════════════════════════════════════════╝

async def get_clan_by_tag(mongo: MongoClient, tag: str) -> Optional[Clan]:
    """Get clan data by tag"""
    clan_data = await mongo.clans.find_one({"tag": tag})
    if clan_data:
        return Clan(data=clan_data)
    return None

# ╔══════════════════════════════════════════════════════════════╗
# ║                  Get Clan Options Utility                    ║
# ╚══════════════════════════════════════════════════════════════╝

async def get_clan_options(mongo: MongoClient) -> List[SelectOption]:
    """Get clan options for select menu"""
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=data) for data in clan_data]

    # Use clans directly without sorting
    options = []
    for clan in clans[:25]:  # Discord limit
        kwargs = {
            "label": clan.name,
            "value": clan.tag,
            "description": f"Points: {clan.points:.1f}"
        }
        if clan.partial_emoji:
            kwargs["emoji"] = clan.partial_emoji

        options.append(SelectOption(**kwargs))

    return options

# ╔══════════════════════════════════════════════════════════════╗
# ║               Create Submission Data Utility                 ║
# ╚══════════════════════════════════════════════════════════════╝

async def create_submission_data(
        submission_type: str,
        clan: Clan,
        user: hikari.User,
        **kwargs
) -> Dict:
    """Create standardized submission data for approval"""
    return {
        "submission_id": f"{clan.tag}_{user.id}_{int(datetime.now().timestamp())}",
        "type": submission_type,
        "clan_tag": clan.tag,
        "clan_name": clan.name,
        "clan_logo": clan.logo or "https://cdn-icons-png.flaticon.com/512/845/845665.png",
        "user_id": str(user.id),
        "user_mention": f"<@{user.id}>",
        "timestamp": int(datetime.now().timestamp()),
        **kwargs
    }