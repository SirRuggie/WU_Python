# extensions/commands/fwa/links.py
"""
FWA Links command for quick access to verification and war weight entry pages.
"""

import hikari
import lightbulb
import uuid
from typing import List

from extensions.commands.fwa import loader, fwa
from extensions.components import register_action
from utils.mongo import MongoClient
from utils.classes import Clan
from utils.constants import GOLD_ACCENT

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton,
    SectionComponentBuilder as Section,
)


@fwa.register()
class Links(
    lightbulb.SlashCommand,
    name="links",
    description="Quick access to FWA verification and war weight entry links"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer()
        
        action_id = str(uuid.uuid4())
        
        # Store action ID in button store for later use
        await mongo.button_store.insert_one({
            "_id": action_id,
            "type": "fwa_links"
        })
        
        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## 🔗 **FWA Needed Links**"),
                    Separator(divider=True),
                    Text(content=(
                        "In the FWA Clans, there are important links and maintenance tasks "
                        "that need regular checking. Choose one of the options provided, "
                        "and then select the specific clan when asked."
                    )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753732596/misc_images/FWA.png"
                            ),
                        ]
                    ),
                    Separator(divider=True),
                    Section(
                        components=[
                            Text(content="Click to verify win status for FWA clans")
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Verify Win",
                            emoji="✅",
                            custom_id=f"fwa_verify_win:{action_id}",
                        ),
                    ),
                    Section(
                        components=[
                            Text(content="Click to enter war weights for FWA clans")
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Enter War Weights",
                            emoji="⚖️",
                            custom_id=f"fwa_war_weights:{action_id}",
                        ),
                    ),
                ]
            ),
        ]
        
        # Delete the deferred response
        await ctx.interaction.delete_initial_response()
        
        # Send message to channel
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
        )


@register_action("fwa_verify_win", no_return=True)
@lightbulb.di.with_di
async def on_verify_win(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    ctx = kwargs.get("ctx")
    
    # Get all FWA clans
    fwa_clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
    
    if not fwa_clans:
        await ctx.respond("❌ No FWA clans found in the database.", ephemeral=True)
        return
    
    # Sort clans by name
    fwa_clans.sort(key=lambda x: x.get("name", ""))
    
    # Create container components for Verify Win
    container_components = [
        Text(content="## ✅ **Verify Win Links**"),
        Separator(divider=True),
        Text(content="Click any clan to verify their win status:"),
        Separator(divider=True),
    ]
    
    # Create button rows (5 buttons per row, max 5 rows = 25 clans)
    for i in range(0, min(len(fwa_clans), 25), 5):
        row = ActionRow()
        for j in range(5):
            if i + j < len(fwa_clans) and i + j < 25:
                clan_obj = Clan(data=fwa_clans[i + j])
                clan_tag = clan_obj.tag.lstrip("#")
                row.add_component(
                    LinkButton(
                        url=f"https://points.fwafarm.com/clan?tag={clan_tag}",
                        label=clan_obj.name[:80],  # Discord limit is 80 chars
                    )
                )
        if row.components:  # Only add row if it has buttons
            container_components.append(row)
    
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=container_components
        )
    ]
    
    await ctx.respond(components=components, ephemeral=True)


@register_action("fwa_war_weights", no_return=True)
@lightbulb.di.with_di
async def on_war_weights(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    ctx = kwargs.get("ctx")
    
    # Get all FWA clans
    fwa_clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
    
    if not fwa_clans:
        await ctx.respond("❌ No FWA clans found in the database.", ephemeral=True)
        return
    
    # Sort clans by name
    fwa_clans.sort(key=lambda x: x.get("name", ""))
    
    # Create container components for War Weights
    container_components = [
        Text(content="## ⚖️ **Enter War Weights Links**"),
        Separator(divider=True),
        Text(content="Click any clan to enter war weights:"),
        Separator(divider=True),
    ]
    
    # Create button rows (5 buttons per row, max 5 rows = 25 clans)
    for i in range(0, min(len(fwa_clans), 25), 5):
        row = ActionRow()
        for j in range(5):
            if i + j < len(fwa_clans) and i + j < 25:
                clan_obj = Clan(data=fwa_clans[i + j])
                clan_tag = clan_obj.tag.lstrip("#")
                row.add_component(
                    LinkButton(
                        url=f"https://fwastats.com/Clan/{clan_tag}/Weight",
                        label=clan_obj.name[:80],  # Discord limit is 80 chars
                    )
                )
        if row.components:  # Only add row if it has buttons
            container_components.append(row)
    
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=container_components
        )
    ]
    
    await ctx.respond(components=components, ephemeral=True)


loader.command(fwa)