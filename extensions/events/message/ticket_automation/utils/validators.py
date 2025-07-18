# extensions/events/message/ticket_automation/utils/validators.py
"""
Validation utilities for ticket automation system.
"""

from typing import Optional, Union
from datetime import datetime, timezone


# Remove pytz import - not needed for Friend Time bot integration

async def validate_user_id(user_id: Union[str, int, None]) -> Optional[int]:
    """
    Validate and convert user ID to integer.

    Args:
        user_id: User ID as string, int, or None

    Returns:
        Optional[int]: Validated user ID or None
    """
    if user_id is None:
        return None

    try:
        return int(user_id)
    except (ValueError, TypeError):
        print(f"[Validator] Invalid user ID format: {user_id}")
        return None


def is_automation_active(ticket_state: dict) -> bool:
    """
    Check if automation is active for a ticket.

    Args:
        ticket_state: Ticket state dictionary from MongoDB

    Returns:
        bool: True if automation is active
    """
    automation_state = ticket_state.get("automation_state", {})
    return automation_state.get("status") == "active"


def validate_channel_id(channel_id: Union[str, int, None]) -> Optional[str]:
    """
    Validate channel ID and convert to string for MongoDB _id.

    Args:
        channel_id: Channel ID as string, int, or None

    Returns:
        Optional[str]: Validated channel ID as string or None
    """
    if channel_id is None:
        return None

    return str(channel_id)


def is_friend_time_bot(author_id: int) -> bool:
    """
    Check if a message is from Friend Time bot.

    Args:
        author_id: Discord author ID

    Returns:
        bool: True if from Friend Time bot
    """
    FRIEND_TIME_BOT_ID = 481439443015942166
    return author_id == FRIEND_TIME_BOT_ID


def validate_timestamp(timestamp: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Validate and convert timestamp to timezone-aware datetime.

    Args:
        timestamp: Timestamp as string, datetime, or None

    Returns:
        Optional[datetime]: Validated timezone-aware datetime or None
    """
    if timestamp is None:
        return None

    if isinstance(timestamp, str):
        try:
            # Handle ISO format from MongoDB
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            # Ensure it's timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            print(f"[Validator] Invalid timestamp format: {timestamp}")
            return None

    elif isinstance(timestamp, datetime):
        # Ensure it's timezone-aware
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    return None


def is_valid_ticket_type(ticket_type: str) -> bool:
    """
    Validate ticket type.

    Args:
        ticket_type: Ticket type string

    Returns:
        bool: True if valid ticket type
    """
    valid_types = {"recruitment", "fwa", "support", "general"}
    return ticket_type.lower() in valid_types


def validate_questionnaire_step(step: str) -> bool:
    """
    Validate questionnaire step name.

    Args:
        step: Step name

    Returns:
        bool: True if valid step
    """
    valid_steps = {
        "interview_selection",
        "attack_strategies",
        "clan_expectations",
        "discord_skills",
        "age_bracket",
        "timezone",
        "completion"
    }
    return step in valid_steps