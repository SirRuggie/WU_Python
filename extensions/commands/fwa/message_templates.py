# extensions/commands/fwa/message_templates.py
"""
Message templates for FWA war plans using Components v2.
Centralizes all war message formatting for consistency.
"""

import hikari
import lightbulb
from typing import List, Optional

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
)

from utils.constants import GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT, BLUE_ACCENT
from extensions.components import register_action

# War result colors
WAR_COLORS = {
    "win": GREEN_ACCENT,  # 0x00ff00
    "lose": RED_ACCENT,  # 0xff0000
    "blacklisted": 0x000000,  # Black
    "mismatch": GOLD_ACCENT  # 0xffd700
}

# Media footer images
FOOTER_IMAGES = {
    "win": "assets/Green_Footer.png",
    "lose": "assets/Red_Footer.png",
    "blacklisted": "assets/Gray_Footer.png",
    "mismatch": "assets/Gold_Footer.png"
}


class WarMessageTemplates:
    """Collection of war message templates using Components v2"""

    @staticmethod
    def format_stars(count: int) -> str:
        """Format star emojis"""
        return " ".join(["⭐"] * count)

    @staticmethod
    def win_message(opponent: str, author: str, clan_role_id: str) -> List[Container]:
        """Generate WIN war message"""
        stars_3 = WarMessageTemplates.format_stars(3)
        stars_2 = WarMessageTemplates.format_stars(2)

        components = [
            Container(
                accent_color=WAR_COLORS["win"],
                components=[
                    Text(content=f"## 💎 <@&{clan_role_id}> **War against `{opponent}` is a WIN war!**"),
                    Separator(divider=True),
                    Text(content=f"**First attack:** {stars_3} star your mirror."),
                    Separator(divider=True),
                    Text(content=(
                        f"**Second attack options:**\n\n"
                        f"**Option 1:** {stars_2} Base #1 or any base above you for loot\n\n"
                        f"**Option 2:** Wait for 8 hours left and clean up bases with a {stars_3} attack "
                        f"(maximizing our star potential)"
                    )),
                    Separator(divider=True),
                    Text(content="### 🎯 **Goal: 150 Stars**"),
                    Media(items=[MediaItem(media=FOOTER_IMAGES["win"])]),
                    Separator(divider=True),
                    Text(content=f"-# 📣 *War declaration by {author}*")
                ]
            )
        ]

        return components

    @staticmethod
    def lose_message(opponent: str, author: str, clan_role_id: str) -> List[Container]:
        """Generate LOSE war message"""
        stars_2 = WarMessageTemplates.format_stars(2)
        stars_1 = WarMessageTemplates.format_stars(1)

        components = [
            Container(
                accent_color=WAR_COLORS["lose"],
                components=[
                    Text(content=f"## ❌ <@&{clan_role_id}> **War against `{opponent}` is a LOSE war!**"),
                    Separator(divider=True),
                    Text(content=f"**First attack:** {stars_2} star your mirror."),
                    Separator(divider=True),
                    Text(content=(
                        f"**Second attack options:**\n\n"
                        f"**Option 1:** {stars_1} Base #1 for loot\n\n"
                        f"**Option 2:** Wait for 8 hours left and clean up bases with a {stars_2} attack "
                        f"(maximizing our star potential)"
                    )),
                    Separator(divider=True),
                    Text(content="### 🎯 **Goal: 100 Stars**"),
                    Media(items=[MediaItem(media=FOOTER_IMAGES["lose"])]),
                    Separator(divider=True),
                    Text(content=f"-# 📣 *War declaration by {author}*")
                ]
            )
        ]

        return components

    @staticmethod
    def blacklisted_message(opponent: str, author: str, clan_role_id: str,
                            fwa_clan_rep_role_id: str) -> List[Container]:
        """Generate BLACKLISTED war message with enhanced visual hierarchy"""
        components = [
            Container(
                accent_color=WAR_COLORS["blacklisted"],
                components=[
                    # Main alert with emoji and better formatting
                    Text(content=f"# 🚨 <@&{clan_role_id}> **BLACKLISTED CLAN ALERT!**"),
                    Text(content=f"## ⚔️ **Switch to War Bases NOW!**"),
                    Separator(divider=True),

                    # Context with visual emphasis
                    Text(content=(
                        f"### ⚠️ **Enemy Intel**\n"
                        f"We're facing **`{opponent}`** - a clan that specifically targets FWA clans for easy wins.\n"
                        f"They're dishonorable and out to destroy us. **Don't let them succeed!**"
                    )),

                    Separator(divider=True),

                    # First Attack Section with clear visual hierarchy
                    Text(content="## 🎯 **FIRST ATTACK STRATEGY**"),
                    Text(content=(
                        "**🏆 Top Players (#1-3)**\n"
                        "➤ Attack your **mirror** (same number)\n\n"

                        "**⚔️ Core Players (#4-47)**\n"
                        "➤ Drop **2 bases down** from your mirror\n"
                        "➤ Example: #10 attacks #12\n\n"

                        "**🛡️ Bottom Players (#48-50)**\n"
                        "➤ Attack your **mirror** (same number)\n\n"

                        "*💬 Swaps allowed - coordinate in clan chat!*"
                    )),

                    Separator(divider=True),

                    # Second Attack Section
                    Text(content="## 🔥 **SECOND ATTACK STRATEGY**"),
                    Text(content=(
                        "**🏆 Top Players (#1-3)**\n"
                        "➤ Clean up **top 5 bases** for 3 stars\n\n"

                        "**⚔️ Everyone Else - Choose ONE:**\n"
                        "**Option A:** Clean & Sweep\n"
                        "• Clean up any base **below** your first target\n"
                        "• Attack a lower base you can **3-star**\n\n"

                        "**Option B:** Strategic Hold\n"
                        "• **WAIT** until 8-hour mark\n"
                        "• Clean up **any available** base\n"
                        "• Lower players go for **max loot**"
                    )),

                    Separator(divider=True),

                    # Target Claiming Section
                    Text(content="## 🏴 **CLAIM YOUR TARGET**"),
                    Text(content=(
                        "• Use the **flag emoji** 🏴 to claim\n"
                        "• **Respect all claims** - no stealing!\n"
                        "• **Attack quickly** - don't camp on flags\n"
                        "• *Claims optional but recommended*"
                    )),

                    Separator(divider=True),

                    # FWA Points Section with visual progress indicators
                    Text(content="## 🏅 **FWA POINT OBJECTIVES**"),
                    Text(content=(
                        "**Mission: Earn 3 FWA Points**\n\n"
                        "📊 **Point Breakdown:**\n"
                        "• ✅ **30+ war bases** deployed = 1 point\n"
                        "• ✅ **60%+ destruction** achieved = 1 point\n"
                        "• ✅ **Win the war** = 1 point\n\n"
                        "*These points help us in future matchmaking!*"
                    )),

                    Separator(divider=True),

                    # Help section
                    Text(content=(
                        f"### 💭 **Need Help?**\n"
                        f"Questions about the strategy? Ping an <@&{fwa_clan_rep_role_id}>\n"
                        f"Let's show them what happens when they mess with FWA! 💪"
                    )),
                    Media(items=[MediaItem(media=FOOTER_IMAGES["blacklisted"])]),
                    Separator(divider=True),
                    Text(content=f"-# 📣 *War declaration by {author}*")
                ]
            )
        ]

        return components

    @staticmethod
    def mismatch_message(opponent: str, author: str, clan_role_id: str) -> List[Container]:
        """Generate MISMATCH war message"""
        stars_3 = WarMessageTemplates.format_stars(3)

        components = [
            Container(
                accent_color=WAR_COLORS["mismatch"],
                components=[
                    Text(content=f"## 🎭 <@&{clan_role_id}> **War against {opponent} is a MISMATCH war!**"),
                    Separator(divider=True),
                    Text(content=(
                        f"**Attacking is optional** this war. You can:\n"
                        f"• Try to {stars_3} star your mirror, or\n"
                        f"• Snipe the top 2 bases for loot"
                    )),
                    Separator(divider=True),
                    Text(content="### ⚠️ **Do not change your War Base.**"),
                    Media(items=[MediaItem(media=FOOTER_IMAGES["mismatch"])]),
                    Separator(divider=True),
                    Text(content=f"-# 📣 *War declaration by {author}*")
                ]
            )
        ]

        return components


# Utility functions for copy text (for buttons/interactions)
class WarCopyTexts:
    """Quick copy texts for war messages"""

    @staticmethod
    def win_copy(opponent: str) -> str:
        return (
            f"✅War vs {opponent} is a WIN war!\n"
            "🔹First Attack: 3⭐️ your mirror.\n"
            "🔹Second Attack:\n"
            "•Option 1: Hit Base #1 or any higher base for loot.\n"
            "•Option 2: Wait until 8h left, then clean up with a strong 3⭐️.\n"
        )

    @staticmethod
    def lose_copy(opponent: str) -> str:
        return (
            f"⚠️War vs {opponent} is a LOSE war!\n"
            "🔹First Attack: 2⭐️ your mirror.\n"
            "🔹Second Attack:\n"
            "•Option 1: Hit Base #1 or any top base for loot.\n"
            "•Option 2: Wait until 8h left, then go for a safe 2⭐️ cleanup.\n\n"
        )

    @staticmethod
    def blacklisted_copy(opponent: str) -> str:
        return (
            f"BLACKLISTED vs {opponent}: Switch to war bases! "
            f"1st: Mirror (1-3,48-50) or -2 (4-47). "
            f"2nd: Cleanup/3⭐ lower. "
            f"Goal: 3 FWA points (30 war bases, 60% destruction, win)"
        )

    @staticmethod
    def mismatch_copy(opponent: str) -> str:
        return (
            f"⚔️War vs {opponent} is a MISMATCH war!\n"
            "🔹Attacking is optional this war.\n"
            "•Go for a 3⭐️ on your mirror if you'd like.\n"
            "•Or just snipe the top 1–2 bases for loot.\n"
            "🚫 Do NOT change your war base. Keep your FWA base up!"
        )


# Validation functions
def validate_opponent_name(name: str, max_length: int = 50) -> bool:
    """Validate opponent clan name"""
    if not name or not name.strip():
        return False
    if len(name) > max_length:
        return False
    # Check for inappropriate characters
    forbidden_chars = ['@', '#', '<', '>', '`']
    return not any(char in name for char in forbidden_chars)


def sanitize_opponent_name(name: str) -> str:
    """Sanitize opponent name for safe display"""
    # Remove excess whitespace
    name = ' '.join(name.split())
    # Remove Discord markdown characters
    for char in ['*', '_', '~', '|', '`']:
        name = name.replace(char, '')
    return name.strip()


# Component action for copy button (if needed)
@register_action("copy_war_message", group="fwa")
async def copy_war_message_action(
        ctx: lightbulb.components.MenuContext,
        war_type: str,
        opponent: str,
        **kwargs
):
    """Handle copy button for war messages"""
    copy_funcs = {
        "win": WarCopyTexts.win_copy,
        "lose": WarCopyTexts.lose_copy,
        "blacklisted": WarCopyTexts.blacklisted_copy,
        "mismatch": WarCopyTexts.mismatch_copy
    }

    if war_type in copy_funcs:
        copy_text = copy_funcs[war_type](opponent)
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="### 📋 **Copy Text**"),
                    Text(content=f"```{copy_text}```"),
                    Text(content="-# Message copied to clipboard (paste it manually)")
                ]
            )
        ]
        await ctx.respond(components=components, ephemeral=True)
    else:
        await ctx.respond("Invalid war type", ephemeral=True)