# extensions/events/message/ticket_automation/fwa/handlers/fwa_explanation.py
"""
Handles FWA explanation step - explains what FWA is and waits for understanding.
Uses the EXACT same content as recruitment questions.
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
    """Initialize the FWA explanation handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot


async def send_fwa_explanation(channel_id: int, thread_id: int, user_id: int):
    """Send the FWA explanation and wait for 'Understood' response"""
    if not bot_instance:
        print("[FWA Explanation] Bot not initialized")
        return

    # Use EXACT same content as recruitment questions "What is FWA"
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"<@{user_id}>"),
                Text(content=f"## <a:FWA:1387882523358527608> **FWA Clans Quick Overview**"),
                Separator(divider=True),
                Text(content=(
                    "## 📌 FWA Clans in Clash of Clans: A Quick Overview\n"
                    f"> Minimum TH for FWA: TH13 {emojis.TH13}\n\n"
                    "FWA, or Farm War Alliance, is a unique concept in Clash of Clans. It's all about maximizing loot and clan XP, rather than focusing solely on winning wars.\n\n"
                    "### **__<a:FWA:1387882523358527608> What are the benefits?__**\n"
                    "**<:Money_Gob:1024851096847519794> Maximized Loot and XP**\n"
                    "FWA clans aim to ensure a steady stream of resources and XP, perfect for upgrading bases, troops, and heroes.\n\n"
                    "**<a:sleep_zzz:1125067436601901188> War Participation with Upgrading Heroes**\n"
                    "Unlike traditional wars, in FWA you can participate even if your heroes are down for upgrades, making continuous progress possible.\n\n"
                    "**<:CoolOP:1024001628979855360> Fair Wars**\n"
                    "War winners are decided via a lottery system, ensuring fair chances and significant loot for both sides.\n\n"
                    "**<:Waiting:1318704702443094150> Is it against the rules?**\n"
                    "No, as long as FWA clans follow the game rules and don't use any hacks or exploits, they are within the game's terms of service. It's a unique and accepted way of playing the game."
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "## ⚔️ FWA War Plans ⚔️\n"
                    "Below are your two main war plans for FWA. Follow these and all will be good\n"
                    "### 💎 WIN WAR💎\n"
                    "__1st hit:__⭐️⭐️⭐️ star your mirror.\n"
                    "__2nd hit:__⭐️⭐️ BASE #1 or any base above you for loot or wait for 8 hr cleanup call in Discord.\n"
                    "**Goal is 150 Stars!**\n\n"
                    "### ❌ LOSE WAR ❌\n"
                    "__1st hit:__⭐️⭐️star your mirror.\n"
                    "__2nd hit:__⭐️BASE #1 or any base above you for loot or wait for 8 hr cleanup call in Discord.\n"
                    "**Goal is 100 Stars!**\n\n"
                    "War Plans are posted via Discord and Clan Mail. Don't hesitate to ping an __FWA Clan Rep__ in your Clan's Chat Channel with any questions you may have."
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "## 🏰 Default FWA Base 🏰\n"
                    "Below is a picture of a TH13 default FWA War Base. Each TH Level is similar with the major difference being TH12+ where the TH is separate. It's a simple layout that allows you to strategically attack for a certain star count but still maximize the most loot available."
                )),
                Media(items=[MediaItem(media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751616880/Default_FWA_Base.jpg")]),
                Separator(divider=True),
                Text(content="💡 **To continue, type:** `Understood`")
            ]
        )
    ]

    try:
        # SEND TO MAIN CHANNEL, NOT THREAD!
        await bot_instance.rest.create_message(
            channel=channel_id,  # Changed from thread_id
            components=components,
            user_mentions=True
        )

        # Update the state section to include the questionnaire current_question:
        await StateManager.update_ticket_state(
            str(channel_id),
            {
                "step_data.fwa.started": True,
                "step_data.fwa.fwa_explanation_sent": True,
                "step_data.fwa.fwa_explanation_sent_at": datetime.now(timezone.utc),
                "step_data.fwa.awaiting_understood": True,
                "step_data.fwa.current_fwa_step": FWAStep.FWA_EXPLANATION.value,
                "step_data.questionnaire.current_question": "fwa_explanation"
            }
        )

        print(f"[FWA Explanation] Sent explanation to channel {channel_id}")

    except Exception as e:
        print(f"[FWA Explanation] Error sending explanation: {e}")