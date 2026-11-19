# extensions/commands/clan/info_hub/helpers.py

from typing import List, Optional
from utils.mongo import MongoClient
from utils.classes import Clan
from utils.emoji import emojis
from utils.town_halls import town_hall_emoji


async def get_clans_by_type(mongo: MongoClient, clan_type: str) -> List[Clan]:
    """Get all clans of a specific type from MongoDB"""
    # Query for clans by type
    clan_data = await mongo.clans.find({"type": clan_type}).to_list(length=None)

    # Convert to Clan objects
    clans = [Clan(data=data) for data in clan_data]

    return clans


def format_th_requirement(th_level: Optional[int], th_attribute: Optional[str]) -> str:
    """Format TH requirement display"""
    if not th_level:
        return "📋 TH Requirement: Not Set"

    th_emoji = town_hall_emoji(th_level)

    # Format the requirement text
    base_text = f"{th_emoji} TH{th_level}".strip()

    if th_attribute:
        if th_attribute == "Max":
            return f"{base_text} Max Only"
        elif th_attribute == "Non-Rushed":
            return f"{base_text}+ Non-Rushed"
        elif th_attribute == "Rushed":
            return f"{base_text}+ (Rushed OK)"
        else:
            return f"{base_text}+"
    else:
        return f"{base_text}+"


def get_league_emoji(league_name: str) -> str:
    """Get the appropriate emoji for a league"""
    league_emojis = {
        "Champion League I": emojis.Champ1.partial_emoji,
        "Champion League II": emojis.Champ2.partial_emoji,
        "Champion League III": emojis.Champ3.partial_emoji,
        "Master League I": emojis.Master1.partial_emoji,
        "Master League II": emojis.Master2.partial_emoji,
        "Master League III": emojis.Master3.partial_emoji,
        "Crystal League I": emojis.Crystal1.partial_emoji,
        "Crystal League II": emojis.Crystal2.partial_emoji,
        "Crystal League III": emojis.Crystal3.partial_emoji,
        "Gold League I": emojis.Gold1.partial_emoji,
        "Gold League II": emojis.Gold2.partial_emoji,
        "Gold League III": emojis.Gold3.partial_emoji,
        "Silver League I": emojis.Silver1.partial_emoji,
        "Silver League II": emojis.Silver2.partial_emoji,
        "Silver League III": emojis.Silver3.partial_emoji,
        "Bronze League I": "🥉",
        "Bronze League II": "🥉",
        "Bronze League III": "🥉",
        "Unranked": "🏅"
    }

    return league_emojis.get(league_name, "🏅")


async def get_clans_by_status(mongo: MongoClient, status: str) -> List[Clan]:
    """Get all clans with a specific status from MongoDB"""
    # Query for clans by status
    clan_data = await mongo.clans.find({"status": status}).to_list(length=None)

    # Convert to Clan objects
    clans = [Clan(data=data) for data in clan_data]

    return clans