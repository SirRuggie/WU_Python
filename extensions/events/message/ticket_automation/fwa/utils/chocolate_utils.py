# extensions/events/message/ticket_automation/fwa/utils/chocolate_utils.py
"""
Utilities for FWA Chocolate Clash integration.
Reuses logic from the chocolate.py command.
"""

from .fwa_constants import CHOCOLATE_BASE_URL


def normalize_tag(tag: str) -> str:
    """
    Normalize a clan/player tag by removing # and converting to uppercase.

    Args:
        tag: Raw tag string

    Returns:
        Normalized tag without # and in uppercase
    """
    return tag.upper().replace("#", "").strip()


def is_valid_tag(tag: str) -> bool:
    """
    Check if a tag has basic valid format.

    Args:
        tag: Tag to validate

    Returns:
        True if tag appears valid, False otherwise
    """
    normalized = normalize_tag(tag)
    # Just check for reasonable length and that it's not empty
    return 2 <= len(normalized) <= 15


def generate_chocolate_link(tag: str, is_player: bool = True) -> str:
    """
    Generate a Chocolate Clash link for a player or clan.

    Args:
        tag: Player or clan tag
        is_player: True for player links, False for clan links

    Returns:
        Full URL to Chocolate Clash page
    """
    normalized_tag = normalize_tag(tag)

    if is_player:
        return f"{CHOCOLATE_BASE_URL}member.php?tag={normalized_tag}"
    else:
        return f"{CHOCOLATE_BASE_URL}clan.php?tag={normalized_tag}"