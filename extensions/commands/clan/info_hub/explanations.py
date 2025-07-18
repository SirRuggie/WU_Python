# extensions/commands/clan/info_hub/explanations.py
"""
Handlers for explaining Zen and FWA concepts in the clan info hub.
Based on content from recruit questions.
"""

import hikari
import lightbulb
import coc

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.constants import GREEN_ACCENT, BLUE_ACCENT
from utils.emoji import emojis
from utils.mongo import MongoClient


# Handler for "What is Zen?" button
@register_action("what_is_zen_info", ephemeral=True, no_return=True)
async def show_what_is_zen(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Display information about Zen war clans"""

    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(
                    content=f"## <:BabyYoda:1390465217997312234> **Zen War Clans: A Quick Overview**"),
                Separator(divider=True),
                Text(content=(
                    "## Concept\n"
                    "We are a laid-back farm/war clan — **NOT A CAMPING CLAN**.\n"
                    "As Heroes are not required here, we understand that some may not feel confident to attack in war, "
                    "but we encourage everyone to find their Zen and make their war attacks. "
                    "Our ultimate goal? A stress-free, Zen-like experience.\n\n"
                    "## Purpose\n"
                    " Our goal is to cultivate a Zen war environment. "
                    "Here, heroes can be down, ensuring every member has the chance to partake in war attacks, "
                    "freeing the mind from the stress of sitting out due to hero upgrades.\n\n"
                    "## Core Rules\n"
                    "> **NOTE:** Each clan has their own set of unique Zen rules. This is **ONLY** a general rule. "
                    "Once you have been assigned to a clan, refer to your clan's specific rules.\n"
                    f"{emojis.gold_arrow_right} **No camping Allowed:** This clan is dedicated to warring. "
                    "Active participation is a must.\n"
                    f"{emojis.gold_arrow_right} **Minimum Participation:** Even with heroes down, every member is required to execute at least one war attack. "
                    "Failure to participate in war earns a strike."
                )),
                Media(
                    items=[
                        MediaItem(media="assets/Green_Footer.png")
                    ]),
            ]
        ),
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=(
                    "## War Plan\n"
                    f"{emojis.gold_arrow_right} **First Attack:** Hit your mirror (same position on the enemy roster) for as many stars as possible. "
                    "Use your strongest army! Remember, heroes can be down, but bases should still be hit.\n"
                    f"{emojis.gold_arrow_right} **Second Attack:** Pick any base you're confident you can **⭐️⭐️⭐️**"
                )),
                Media(
                    items=[
                        MediaItem(media="assets/Green_Footer.png")
                    ]),
            ]
        ),
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=(
                    "## Strike System\n"
                    f"{emojis.gold_arrow_right} Zen Clans expect participation in wars, clan games, raid weekends, and other clan activities to stay active.\n"
                    f"{emojis.gold_arrow_right} Strike rules vary by clan (e.g., 1 or 2 war attacks).\n"
                    f"{emojis.gold_arrow_right} The norm is 4 strikes leading to removal, but check your clan's specific rules.\n"
                )),
                Media(
                    items=[
                        MediaItem(media="https://c.tenor.com/58O460v-6nEAAAAC/tenor.gif")
                    ]),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="back_to_zen_clans:",
                            label="← Back to Zen Clans",
                        )
                    ]
                ),
            ]
        )
    ]

    await ctx.interaction.edit_initial_response(components=components)


# Handler for "What is FWA?" button
@register_action("what_is_fwa_info", ephemeral=True, no_return=True)
async def show_what_is_fwa(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Display information about FWA clans"""

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
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
                Media(
                    items=[
                        MediaItem(media="assets/Blue_Footer.png")
                    ]),
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
                Media(
                    items=[
                        MediaItem(media="assets/Blue_Footer.png")
                    ]),
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=(
                    "## 🏰 Default FWA Base 🏰\n"
                    "Below is a picture of a TH13 default FWA War Base. Each TH Level is similar with the major difference being TH12+ where the TH is separate. It's a simple layout that allows you to strategically attack for a certain star count but still maximize the most loot available."
                )),
                Media(
                    items=[
                        MediaItem(
                            media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751616880/Default_FWA_Base.jpg")
                    ]),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="back_to_fwa_clans:",
                            label="← Back to FWA Clans",
                        )
                    ]
                ),
            ]
        )
    ]

    await ctx.interaction.edit_initial_response(components=components)


# Handler for back to Zen clans
@register_action("back_to_zen_clans", ephemeral=True, no_return=True)
@lightbulb.di.with_di
async def back_to_zen_clans(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to Zen clans list"""
    from .handlers import build_clan_list_components

    components = await build_clan_list_components(
        ctx, "Zen", GREEN_ACCENT, mongo, coc_client, bot
    )

    await ctx.interaction.edit_initial_response(components=components)


# Handler for back to FWA clans
@register_action("back_to_fwa_clans", ephemeral=True, no_return=True)
@lightbulb.di.with_di
async def back_to_fwa_clans(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to FWA clans list"""
    from .handlers import build_clan_list_components

    components = await build_clan_list_components(
        ctx, "FWA", BLUE_ACCENT, mongo, coc_client, bot
    )

    await ctx.interaction.edit_initial_response(components=components)