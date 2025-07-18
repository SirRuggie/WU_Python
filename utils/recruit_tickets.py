# utils/recruit_tickets.py
"""Helper functions for recruit ticket MongoDB operations"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional


async def get_recruits_by_discord_user(mongo, discord_user_id: str) -> List[Dict]:
    """Get all recruit tickets for a Discord user"""
    return await mongo.recruit_tickets.find(
        {"discord_user_id": discord_user_id}
    ).sort("created_at", -1).to_list(length=None)


async def get_active_recruits_by_discord_user(mongo, discord_user_id: str) -> List[Dict]:
    """Get only active (open) recruit tickets for a Discord user"""
    return await mongo.recruit_tickets.find({
        "discord_user_id": discord_user_id,
        "ticket_status": "open"
    }).sort("created_at", -1).to_list(length=None)


async def get_tickets_by_player_tag(mongo, player_tag: str) -> List[Dict]:
    """Get all tickets associated with a player tag"""
    # Normalize the tag (remove # and uppercase)
    normalized_tag = player_tag.upper().replace("#", "")

    return await mongo.recruit_tickets.find({
        "$or": [
            {"player_tag": player_tag},
            {"player_tag": f"#{normalized_tag}"},
            {"player_tag": normalized_tag}
        ]
    }).sort("created_at", -1).to_list(length=None)


async def get_active_new_recruits(mongo) -> List[Dict]:
    """Get all active new recruits (not expired)"""
    return await mongo.recruit_tickets.find({
        "ticket_status": "open",
        "is_new_recruit": True,
        "new_recruit_expires": {"$gt": datetime.now(timezone.utc)}
    }).sort("created_at", -1).to_list(length=None)


async def get_expired_new_recruits(mongo) -> List[Dict]:
    """Get new recruits whose 12-day period has expired"""
    return await mongo.recruit_tickets.find({
        "ticket_status": "open",
        "is_new_recruit": True,
        "new_recruit_expires": {"$lte": datetime.now(timezone.utc)}
    }).to_list(length=None)


async def mark_recruit_as_recruited(mongo, player_tag: str, clan_tag: str, recruited_by: str) -> bool:
    """Mark a recruit as successfully recruited to a clan"""
    result = await mongo.recruit_tickets.update_one(
        {
            "player_tag": player_tag,
            "ticket_status": "open"
        },
        {
            "$set": {
                "recruited_to_clan": clan_tag,
                "recruited_by": recruited_by,
                "is_new_recruit": False,
                "recruited_at": datetime.now(timezone.utc)
            }
        }
    )
    return result.modified_count > 0


async def close_ticket(mongo, ticket_channel_id: str) -> int:
    """Close all recruit entries for a ticket channel"""
    result = await mongo.recruit_tickets.update_many(
        {
            "ticket_channel_id": ticket_channel_id,
            "ticket_status": "open"
        },
        {
            "$set": {
                "ticket_status": "closed",
                "closed_at": datetime.now(timezone.utc)
            }
        }
    )
    return result.modified_count


async def get_players_in_ticket(mongo, ticket_channel_id: str) -> List[Dict]:
    """Get all players associated with a specific ticket"""
    return await mongo.recruit_tickets.find(
        {"ticket_channel_id": ticket_channel_id}
    ).to_list(length=None)


async def check_duplicate_player(mongo, player_tag: str) -> Optional[Dict]:
    """Check if a player already has an open ticket"""
    return await mongo.recruit_tickets.find_one({
        "player_tag": player_tag,
        "ticket_status": "open"
    })


async def update_has_active_bid(mongo, player_tag: str, has_bid: bool = True) -> bool:
    """Update the has_active_bid flag for a recruit"""
    result = await mongo.recruit_tickets.update_one(
        {
            "player_tag": player_tag,
            "ticket_status": "open"
        },
        {
            "$set": {
                "has_active_bid": has_bid
            }
        }
    )
    return result.modified_count > 0


async def get_recruits_with_bids(mongo) -> List[Dict]:
    """Get all recruits that have active bids (cross-reference with clan_bidding)"""
    # First get all player tags that have bids
    bid_pipeline = [
        {"$match": {"is_finalized": False}},
        {"$group": {"_id": "$player_tag"}}
    ]
    players_with_bids = await mongo.clan_bidding.aggregate(bid_pipeline).to_list(length=None)
    player_tags = [p["_id"] for p in players_with_bids]

    # Then get recruit tickets for those players
    return await mongo.recruit_tickets.find({
        "player_tag": {"$in": player_tags},
        "ticket_status": "open"
    }).to_list(length=None)


async def get_recruit_with_bid_info(mongo, player_tag: str) -> Optional[Dict]:
    """Get recruit ticket info along with bid data"""
    # Get recruit ticket
    recruit = await mongo.recruit_tickets.find_one({
        "player_tag": player_tag,
        "ticket_status": "open"
    })

    if not recruit:
        return None

    # Get bid data from clan_bidding collection
    bid_data = await mongo.clan_bidding.find_one({"player_tag": player_tag})

    # Combine the data
    recruit["bid_info"] = bid_data if bid_data else None
    return recruit


async def get_recruit_stats(mongo, discord_user_id: str) -> Dict:
    """Get statistics for a Discord user's recruitment activity"""
    pipeline = [
        {"$match": {"discord_user_id": discord_user_id}},
        {"$group": {
            "_id": "$discord_user_id",
            "total_tickets": {"$sum": 1},
            "open_tickets": {
                "$sum": {"$cond": [{"$eq": ["$ticket_status", "open"]}, 1, 0]}
            },
            "recruited_count": {
                "$sum": {"$cond": [{"$ne": ["$recruited_to_clan", None]}, 1, 0]}
            },
            "unique_players": {"$addToSet": "$player_tag"}
        }}
    ]

    results = await mongo.recruit_tickets.aggregate(pipeline).to_list(length=1)
    if results:
        stats = results[0]
        stats["unique_players_count"] = len(stats.get("unique_players", []))
        del stats["unique_players"]  # Remove the actual list for privacy
        return stats

    return {
        "total_tickets": 0,
        "open_tickets": 0,
        "recruited_count": 0,
        "unique_players_count": 0
    }

# Note: This file handles recruit_tickets collection operations.
# For bidding operations, use clan_bidding collection directly or
# see utils/bidding_integration.py for integrated operations.