# utils/new_recruits_helpers.py
"""Helper functions for new_recruits MongoDB operations"""

from datetime import datetime, timedelta, timezone
from typing import Optional

async def create_new_recruit(mongo, ticket_data: dict, player_data) -> str:
    """Create a new recruit entry when ticket is opened"""
    # ... rest of the function ...

async def record_recruitment(mongo, player_tag: str, clan_tag: str, clan_name: str,
                           recruited_by: str, bid_amount: int) -> bool:
    """Record when a player is recruited to a clan"""
    # ... rest of the function ...

async def record_member_left(mongo, player_tag: str, clan_tag: str) -> bool:
    """Record when a member leaves a clan"""
    # ... rest of the function ...

async def get_recent_clan_recruits(mongo, clan_tag: str, days: int = 12) -> list:
    """Get all recruits who joined a specific clan in the last X days"""
    # ... rest of the function ...

async def expire_old_recruits(mongo) -> int:
    """Mark recruits as expired after 12 days (run daily)"""
    # ... rest of the function ...