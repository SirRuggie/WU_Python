# extensions/events/message/ticket_automation/utils/helpers.py
"""
Helper functions for ticket automation.
Provides common utilities used across different handlers.
"""

import re
from datetime import datetime, timezone, timedelta

def get_current_timestamp() -> datetime:
    """
    Get the current UTC timestamp.

    Returns:
        datetime: Current timezone-aware datetime in UTC
    """
    return datetime.now(timezone.utc)

from typing import Optional, Union


def format_user_mention(user_id: Union[int, str]) -> str:
    """Format a user ID as a Discord mention"""
    return f"<@{user_id}>"


def format_channel_mention(channel_id: Union[int, str]) -> str:
    """Format a channel ID as a Discord mention"""
    return f"<#{channel_id}>"


def format_role_mention(role_id: Union[int, str]) -> str:
    """Format a role ID as a Discord mention"""
    return f"<@&{role_id}>"


def calculate_time_difference(start_time: datetime, end_time: Optional[datetime] = None) -> str:
    """
    Calculate and format time difference between two timestamps.

    Args:
        start_time: Start datetime
        end_time: End datetime (defaults to now if not provided)

    Returns:
        Formatted string like "5 minutes" or "2 hours 30 minutes"
    """
    if not end_time:
        end_time = datetime.now(timezone.utc)

    # Ensure both are timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    diff = end_time - start_time
    total_seconds = int(diff.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds} seconds"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        time_str = f"{hours} hour{'s' if hours != 1 else ''}"
        if minutes > 0:
            time_str += f" {minutes} minute{'s' if minutes != 1 else ''}"
        return time_str


def clean_message_content(content: str) -> str:
    """
    Clean and normalize message content.
    Removes extra whitespace, normalizes line breaks.
    """
    # Remove leading/trailing whitespace
    content = content.strip()

    # Normalize multiple spaces to single space
    content = re.sub(r'\s+', ' ', content)

    # Normalize multiple newlines to double newline
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content


def truncate_text(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length, adding suffix if truncated.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def extract_user_id_from_mention(mention: str) -> Optional[int]:
    """
    Extract user ID from a Discord mention.

    Args:
        mention: Discord mention string like <@123456789>

    Returns:
        User ID as int, or None if invalid
    """
    match = re.match(r'<@!?(\d+)>', mention)
    if match:
        return int(match.group(1))
    return None


def extract_channel_id_from_mention(mention: str) -> Optional[int]:
    """
    Extract channel ID from a Discord mention.

    Args:
        mention: Discord mention string like <#123456789>

    Returns:
        Channel ID as int, or None if invalid
    """
    match = re.match(r'<#(\d+)>', mention)
    if match:
        return int(match.group(1))
    return None


def format_timestamp(dt: datetime, style: str = "f") -> str:
    """
    Format datetime as Discord timestamp.

    Args:
        dt: Datetime to format
        style: Discord timestamp style
               t - Short Time (16:20)
               T - Long Time (16:20:30)
               d - Short Date (20/04/2021)
               D - Long Date (20 April 2021)
               f - Short Date/Time (20 April 2021 16:20)
               F - Long Date/Time (Tuesday, 20 April 2021 16:20)
               R - Relative Time (2 hours ago)

    Returns:
        Discord timestamp string
    """
    timestamp = int(dt.timestamp())
    return f"<t:{timestamp}:{style}>"


def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string into a timedelta.

    Args:
        duration_str: Duration like "5m", "2h", "1d"

    Returns:
        timedelta or None if invalid
    """
    pattern = r'^(\d+)([smhd])$'
    match = re.match(pattern, duration_str.lower().strip())

    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)

    return None


def is_valid_clash_tag(tag: str) -> bool:
    """
    Validate a Clash of Clans player/clan tag.

    Args:
        tag: Tag to validate

    Returns:
        True if valid, False otherwise
    """
    # Remove # if present
    tag = tag.upper().replace('#', '')

    # Check format: 8-9 characters, alphanumeric excluding certain letters
    pattern = r'^[0-9PYCLQGRJUV]{8,9}$'
    return bool(re.match(pattern, tag))