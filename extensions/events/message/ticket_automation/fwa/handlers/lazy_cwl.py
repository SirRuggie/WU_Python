# extensions/events/message/ticket_automation/fwa/handlers/lazy_cwl.py
"""
Handles Lazy CWL explanation step - uses exact same content as recruit questions.
"""

from datetime import datetime, timezone
from typing import Optional
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SectionComponentBuilder as Section,
    LinkButtonBuilder as LinkButton,
)

from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT
from utils.emoji import emojis
from ...core.state_manager import StateManager
from ..core.fwa_flow import FWAStep

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the Lazy CWL handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_lazy_cwl_explanation(channel_id: int, thread_id: int, user_id: int):
    """Send the Lazy CWL explanation and wait for 'Understood' response"""
    if not bot_instance:
        print("[Lazy CWL] Bot not initialized")
        return

    # Use EXACT same content as recruitment questions "lazy_cwl_explanation"
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"<@{user_id}>"),
                Text(content=f"## 🛋️ **Lazy CWL Deep Dive**"),
                Separator(divider=True),
                Text(content=(
                    "**What is Lazy CWL?**\n"
                    "We partner with **Warriors United** to run CWL in a laid-back, flexible way,\n"
                    "perfect if you'd otherwise go inactive during league week. \n"
                    "No stress over attacks or donations; just jump in when you can."
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "**How It Works**\n"
                    f"{emojis.red_arrow_right} **Brand-New Clans**\n"
                    f"{emojis.blank}{emojis.white_arrow_right} Created each CWL season. Old clans reused in lower leagues.\n\n"
                    f"{emojis.red_arrow_right} **FWA Season Transition**\n"
                    f"{emojis.blank}{emojis.white_arrow_right} During the last **FWA War**, complete both attacks and **join your assigned CWL Clan** before the war ends.\n"
                    f"{emojis.blank}{emojis.white_arrow_right} Announcements will be posted to guide you.\n\n"
                    f"{emojis.red_arrow_right} **League Search**\n"
                    f"{emojis.blank}{emojis.white_arrow_right} Once everyone is in their assigned CWL Clan, we will start the search.\n"
                    f"{emojis.blank}{emojis.white_arrow_right} After the search begins, **return to your Home FWA Clan** immediately.\n"
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "**Participation & Rewards**\n"
                    f"{emojis.red_arrow_right} **Bonus Medals**\n"
                    f"{emojis.blank}{emojis.white_arrow_right} Medals are awarded through a lottery system.\n\n"
                    f"{emojis.red_arrow_right} **Participation Requirement**\n"
                    f"{emojis.blank}{emojis.white_arrow_right} Follow Lazy CWL Rules and complete **at least 4+ attacks (60%)**\n"
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "**How to Sign Up**\n"
                    "If you **WANT to participate** in CWL, signing up is **mandatory!**\n\n"
                    f"{emojis.red_arrow_right} Sign up for **each CWL season** in <#1133030890189094932> or channel name #LazyCwl-Sign-ups , visible after joining the clan.\n\n"
                    f"{emojis.red_arrow_right} **Last-minute signups are strongly discouraged** and may not be accepted. We run several Lazy CWL clans, and proper planning is crucial.\n\n"
                )),
                Section(
                    components=[
                        Text(content=f"{emojis.white_arrow_right}**More Info**")
                    ],
                    accessory=LinkButton(
                        url="https://docs.google.com/document/d/13HrxwaUkenWZ4F1QNCPzdM5n5uXYcLqQYOdQzyQksuA/edit?tab=t.0",
                        label="Deep-Dive Lazy CWL Rules",
                    ),
                ),
                Text(content=(
                    "**<a:Alert_01:1043947615429070858>IMPORTANT:**\n"
                    "*Participating in CWL outside of Arcane is **__not allowed if__** you are part of our FWA Operation.*\n\n"
                )),
                Media(items=[MediaItem(media="https://c.tenor.com/MMuc_dX1D7AAAAAC/tenor.gif")]),
                Separator(divider=True),
                Text(content="💡 **To continue, type:** `Understood`")
            ]
        )
    ]

    try:
        # Send to MAIN CHANNEL
        await bot_instance.rest.create_message(
            channel=channel_id,  # Main channel, not thread
            components=components,
            user_mentions=True
        )

        # Update state with current step
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                "step_data.fwa.lazy_cwl_sent": True,
                "step_data.fwa.lazy_cwl_sent_at": datetime.now(timezone.utc),
                "step_data.fwa.awaiting_understood_cwl": True,
                "step_data.fwa.current_fwa_step": FWAStep.LAZY_CWL.value,
                "step_data.questionnaire.current_question": "lazy_cwl"
            }
        )

        print(f"[Lazy CWL] Sent explanation to channel {channel_id}")

    except Exception as e:
        print(f"[Lazy CWL] Error sending explanation: {e}")