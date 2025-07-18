# extensions/events/message/ticket_automation/fwa/utils/chocolate_components.py
"""
Centralized module for FWA Chocolate Clash component generation.
This module provides reusable functions to create chocolate link components
that can be used across different parts of the bot.
"""

from typing import List, Optional
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    LinkButtonBuilder as LinkButton,
)

from utils.constants import GOLD_ACCENT


def create_chocolate_components(
        player_tag: str,
        player_name: Optional[str] = None,
        is_player: bool = True,
        clan_name: Optional[str] = None
) -> List[Container]:
    """
    Create standardized FWA Chocolate Clash components.

    Args:
        player_tag: The player or clan tag (with or without #)
        player_name: The player's name (optional, for display)
        is_player: True for player links, False for clan links
        clan_name: The clan's name (optional, for clan links)

    Returns:
        List of Container components ready to be sent
    """
    # Normalize the tag
    normalized_tag = player_tag.upper().replace("#", "").strip()

    # Build the URL
    if is_player:
        url = f"https://cc.fwafarm.com/cc_n/member.php?tag={normalized_tag}"
        emoji = "👤"
        type_text = "Player"
        display_name = player_name or "Unknown Player"
    else:
        url = f"https://cc.fwafarm.com/cc_n/clan.php?tag={normalized_tag}"
        emoji = "🏛️"
        type_text = "Clan"
        display_name = clan_name or "Unknown Clan"

    # Build type-specific information text
    if is_player:
        type_info = (
            "• Player's FWA participation history\n"
            "• Current clan status\n"
            "• War performance metrics\n"
            "• Blacklist status (if any)"
        )
    else:
        type_info = (
            "• Clan's FWA membership status\n"
            "• War sync information\n"
            "• Member compliance\n"
            "• Clan statistics"
        )

    # Build response components
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content="## 🍫 **FWA Chocolate Lookup**"),
                Separator(divider=True),
                Text(content=(
                    f"{emoji} **{type_text} Name:** {display_name}\n"
                    f"{emoji} **{type_text} Tag:** `#{normalized_tag}`\n"
                    f"🔗 **FWA Status:** Click below to check\n\n"
                    f"This will open the FWA Chocolate site to show:"
                )),
                Text(content=type_info),
                ActionRow(
                    components=[
                        LinkButton(
                            label=f"Open {type_text} on FWA Chocolate",
                            url=url
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]

    return components


async def send_chocolate_link(
        bot: hikari.GatewayBot,
        channel_id: int,
        player_tag: str,
        player_name: Optional[str] = None
) -> bool:
    """
    Helper function to send chocolate link to a channel.

    Args:
        bot: The bot instance
        channel_id: Channel ID to send to
        player_tag: Player tag
        player_name: Player name (optional)

    Returns:
        True if successful, False otherwise
    """
    try:
        components = create_chocolate_components(
            player_tag=player_tag,
            player_name=player_name,
            is_player=True
        )

        await bot.rest.create_message(
            channel=channel_id,
            components=components
        )
        return True
    except Exception as e:
        print(f"[Chocolate] Error sending chocolate link: {e}")
        return False