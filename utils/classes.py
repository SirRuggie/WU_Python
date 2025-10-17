import random
from utils.emoji import EmojiType


class Clan:
    def __init__(self, data: dict):
        self._data = data
        self.announcement_id: int = data.get("announcement_id")
        self.chat_channel_id: int = data.get("chat_channel_id")
        self.emoji: str = data.get("emoji")

        # only attempt to parse if it at least has two colons
        if self.emoji and self.emoji.count(":") >= 2:
            try:
                emoji_type = EmojiType(self.emoji)
                self.partial_emoji = emoji_type.partial_emoji
                # Test if the emoji is valid by trying to convert to string
                str(self.partial_emoji)
            except (IndexError, ValueError, TypeError, AttributeError) as e:
                print(f"[Clan] Failed to parse emoji for {self.name} ({self.tag}): {e}")
                self.partial_emoji = None
        else:
            self.partial_emoji = None
        self.tag: str = data.get("tag")
        self.leader_id: int = data.get("leader_id")
        self.leader_role_id: int = data.get("leader_role_id")
        self.leadership_channel_id: int = data.get("leadership_channel_id")
        self.logo: str = data.get("logo")
        self.banner: str = data.get("banner")
        self.name: str = data.get("name")
        self.profile: str = data.get("profile")
        self.role_id: int = data.get("role_id")
        self.rules_channel_id: int = data.get("rules_channel_id")
        self.th_requirements: int = data.get("th_requirements")
        self.thread_id = data.get("thread_id")
        self.thread_message_id: int = data.get("thread_message_id", 0)
        self.type: str = data.get("type")

class BaseLinks:
    def __init__(self, links_dict):
        for th, link in links_dict.items():
            setattr(self, th, link)
    def __getattr__(self, name):
        return ""

class FWA:
    def __init__(self, data):
        self._data = data
        self.fwa_base_links = BaseLinks(data.get("fwa_base_links", {}))
        self.base_information = data.get("base_information", {})
        print(f"[FWA Class] Initialized with base_information keys: {list(self.base_information.keys())}")


class NewRecruit:
    """Represents a new recruit being tracked for 12 days"""

    def __init__(self, data: dict):
        self._data = data

        # Player info
        self.player_tag: str = data.get("player_tag")
        self.player_name: str = data.get("player_name")
        self.player_th_level: int = data.get("player_th_level")

        # Discord/Ticket info
        self.discord_user_id: str = data.get("discord_user_id")
        self.ticket_channel_id: str = data.get("ticket_channel_id")
        self.ticket_thread_id: str = data.get("ticket_thread_id")

        # Timestamps
        self.created_at = data.get("created_at")
        self.expires_at = data.get("expires_at")

        # Recruitment
        self.recruitment_history: list = data.get("recruitment_history", [])
        self.current_clan: str = data.get("current_clan")
        self.total_clans_joined: int = data.get("total_clans_joined", 0)
        self.is_expired: bool = data.get("is_expired", False)

    @property
    def is_in_clan(self) -> bool:
        """Check if currently in a clan"""
        return self.current_clan is not None

    @property
    def latest_recruitment(self) -> dict:
        """Get the most recent recruitment info"""
        if self.recruitment_history:
            return self.recruitment_history[-1]
        return None

    @property
    def days_until_expiry(self) -> float:
        """Calculate days until this recruit expires"""
        if not self.expires_at:
            return 0
        from datetime import datetime, timezone
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, delta.total_seconds() / 86400)