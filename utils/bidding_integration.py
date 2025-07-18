# utils/bidding_integration.py
"""Helper functions to integrate recruit_tickets with clan_bidding collections"""

from datetime import datetime, timezone
from typing import List, Dict, Optional


async def get_new_recruits_for_bidding(mongo) -> List[Dict]:
    """
    Get all new recruits eligible for bidding
    (active tickets, within 12-day window, no existing bid)
    """
    # Get active new recruits
    active_recruits = await mongo.recruit_tickets.find({
        "ticket_status": "open",
        "is_new_recruit": True,
        "new_recruit_expires": {"$gt": datetime.now(timezone.utc)}
    }).to_list(length=None)

    # Get player tags that already have bids
    existing_bids = await mongo.clan_bidding.distinct("player_tag")

    # Filter out recruits that already have bids
    eligible_recruits = [
        recruit for recruit in active_recruits
        if recruit["player_tag"] not in existing_bids
    ]

    return eligible_recruits


async def create_bid_for_recruit(mongo, player_tag: str) -> bool:
    """
    Initialize a bid entry for a recruit when bidding starts
    """
    # First verify the recruit exists and is eligible
    recruit = await mongo.recruit_tickets.find_one({
        "player_tag": player_tag,
        "ticket_status": "open",
        "is_new_recruit": True
    })

    if not recruit:
        return False

    # Check if bid already exists
    existing_bid = await mongo.clan_bidding.find_one({"player_tag": player_tag})
    if existing_bid:
        return False

    # Create bid entry (matching your existing schema)
    bid_doc = {
        "player_tag": player_tag,
        "bids": [],
        "is_finalized": False,
        "winner": "",
        "amount": 0
    }

    # Insert bid document
    await mongo.clan_bidding.insert_one(bid_doc)

    # Update recruit ticket to indicate active bid
    await mongo.recruit_tickets.update_one(
        {"player_tag": player_tag},
        {"$set": {"has_active_bid": True}}
    )

    return True


async def finalize_bid_and_recruit(mongo, player_tag: str, winning_clan_tag: str, recruited_by: str) -> bool:
    """
    Finalize a bid and update recruit status when someone wins
    """
    # Get bid data
    bid = await mongo.clan_bidding.find_one({"player_tag": player_tag})
    if not bid or bid["is_finalized"]:
        return False

    # Determine winner and amount from bids
    winning_bid = next((b for b in bid["bids"] if b["clan_tag"] == winning_clan_tag), None)
    if not winning_bid:
        return False

    # Update clan_bidding
    await mongo.clan_bidding.update_one(
        {"player_tag": player_tag},
        {
            "$set": {
                "is_finalized": True,
                "winner": winning_clan_tag,
                "amount": winning_bid["amount"]
            }
        }
    )

    # Update recruit_tickets
    await mongo.recruit_tickets.update_one(
        {"player_tag": player_tag, "ticket_status": "open"},
        {
            "$set": {
                "recruited_to_clan": winning_clan_tag,
                "recruited_by": recruited_by,
                "is_new_recruit": False,
                "recruited_at": datetime.now(timezone.utc)
            }
        }
    )

    return True


async def get_recruit_bidding_summary(mongo, ticket_channel_id: str) -> Dict:
    """
    Get a summary of all recruits and their bidding status for a ticket
    """
    # Get all recruits in the ticket
    recruits = await mongo.recruit_tickets.find(
        {"ticket_channel_id": ticket_channel_id}
    ).to_list(length=None)

    summary = {
        "ticket_channel_id": ticket_channel_id,
        "total_recruits": len(recruits),
        "recruits_with_bids": 0,
        "recruits_without_bids": 0,
        "finalized_bids": 0,
        "details": []
    }

    for recruit in recruits:
        # Get bid info
        bid = await mongo.clan_bidding.find_one({"player_tag": recruit["player_tag"]})

        recruit_info = {
            "player_tag": recruit["player_tag"],
            "player_name": recruit.get("player_name", "Unknown"),
            "th_level": recruit.get("player_th_level", 0),
            "has_bid": bid is not None,
            "bid_count": len(bid["bids"]) if bid else 0,
            "is_finalized": bid["is_finalized"] if bid else False,
            "winning_clan": bid.get("winner") if bid and bid["is_finalized"] else None,
            "winning_amount": bid.get("amount") if bid and bid["is_finalized"] else 0
        }

        summary["details"].append(recruit_info)

        if bid:
            summary["recruits_with_bids"] += 1
            if bid["is_finalized"]:
                summary["finalized_bids"] += 1
        else:
            summary["recruits_without_bids"] += 1

    return summary


async def close_ticket_and_cleanup_bids(mongo, ticket_channel_id: str) -> Dict:
    """
    Close a ticket and clean up any unfinalized bids
    """
    # Get all recruits in the ticket
    recruits = await mongo.recruit_tickets.find(
        {"ticket_channel_id": ticket_channel_id, "ticket_status": "open"}
    ).to_list(length=None)

    player_tags = [r["player_tag"] for r in recruits]

    # Close all recruit entries
    recruit_result = await mongo.recruit_tickets.update_many(
        {"ticket_channel_id": ticket_channel_id, "ticket_status": "open"},
        {
            "$set": {
                "ticket_status": "closed",
                "closed_at": datetime.now(timezone.utc)
            }
        }
    )

    # Cancel any unfinalized bids
    bid_result = await mongo.clan_bidding.update_many(
        {
            "player_tag": {"$in": player_tags},
            "is_finalized": False
        },
        {
            "$set": {
                "is_finalized": True,
                "winner": "CANCELLED",
                "amount": 0
            }
        }
    )

    return {
        "recruits_closed": recruit_result.modified_count,
        "bids_cancelled": bid_result.modified_count
    }


# Example usage in your bot:
"""
# When starting bidding on a recruit
success = await create_bid_for_recruit(mongo, player_tag)

# When checking eligible recruits for bidding
eligible = await get_new_recruits_for_bidding(mongo)

# When a clan wins a bid
await finalize_bid_and_recruit(mongo, player_tag, clan_tag, recruiter_discord_id)

# When closing a ticket
results = await close_ticket_and_cleanup_bids(mongo, ticket_channel_id)
"""