# extensions/commands/setup/recruit_aboutus.py
"""
Warriors United About Us command - displays clan information and onboarding flow
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GOLDENROD_ACCENT

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

# Configuration
ABOUT_US_ROLE_ID = 1194706934926946458  # Role to assign when user acknowledges
STRIKE_SYSTEM_CHANNEL_ID = 1194706935405084766  # Channel to direct users to


@setup.register()
class RecruitAboutUs(
    lightbulb.SlashCommand,
    name="recruit-aboutus",
    description="Display Warriors United clan information and onboarding flow"
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
            "type": "recruit_aboutus",
            "user_id": ctx.user.id,
            "guild_id": ctx.guild_id,
            "channel_id": ctx.channel_id
        })
        
        # Create all embeds
        components = [
            # Image at the top
            Media(
                items=[
                    MediaItem(
                        media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753167826/misc_images/Warriors_United.gif"
                    )
                ]
            ),
            
            # Embed 1: Welcome and Overview
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## :shield: **Welcome to Warriors United!!** :shield:"),
                    Separator(divider=True),
                    Text(content=(
                        "We're an English-speaking Clan Family based in the USA but have Clasher's from all over the Globe. "
                        "We've developed system of game play that allows you to war no matter what the upgrade status of your base is.\n\n"
                        "**Note of mention** None of our clans are Family Friendly Clans. So if you know your account(s) will require "
                        "this; need to look elsewhere...👍🏼\n\n"
                        "Here's what we will provide:\n"
                        ":shield: 2 High Level Tactical Clans\n"
                        ":shield: 3 Flexible Fun War Clans\n"
                        ":shield: 5 Official FWA Clans for Farmers\n"
                        ":shield: CWL chances for everyone\n"
                        ":shield: An Experienced Base Building Team\n"
                        ":shield: Experienced Attack Trainers"
                    )),
                    Separator(divider=True),
                    Text(content="## ☠️ **High Level Tactical Clans** ☠️"),
                    Text(content=(
                        "**Funnies (#2Q9RLRCG)**\n"
                        "**WeAreBrother (#YQPYJCQ2)**\n\n"
                        "Our High Level Tactical Clans are TH13+ full maxed previous TH Level and always strive to obtain 3 ⭐'s in war. "
                        "Not to worry if you fail; they can't all be perfect; but we expect our members to follow the War Format set in place "
                        "and are committed to winning every war as part of an overall team effort.\n\n"
                        "Wars are always full strength, meaning no Heroes upgrading."
                    )),
                ]
            ),
            
            # Embed 2: Flexible Fun War Clans
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 🪖 **Flexible Fun War Clans** 🪖"),
                    Text(content=(
                        "**Warriors United (#2YRVY8YCP)**\n"
                        "**Noahs Ark (#8VPQCR2R)**\n"
                        "**Morning Woods! (#8VQP9VQ9)**\n\n"
                        "Our \"Flexible Fun\" Clans are relaxed Farm/War Clans that do 50v50 wars or highest amount possible. "
                        "You will be held accountable to make your first attack here but we won't hold you liable for performance. "
                        "No Heroes necessary!!\n\n"
                        "These clans are designed for lower level/more chill players. If your in a Tactical Clan and drop a Hero; "
                        "or more; upgrading and still want some war loot. Slide over to a Flexible Fun Clan and move back to Tactical "
                        "when upgrades are done.\n\n"
                        "Don't mistake these to be Camping Clans and not competitive. Like anyone we strive to win!!\n\n"
                        "No War Activity = No Clan Membership EzPz"
                    )),
                ]
            ),
            
            # Embed 3: FWA Clans
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 💰 **FWA Clans** 💰"),
                    Text(content=(
                        "**Clash of Thrones (#Q889GPL)**\n"
                        "**CoT Wildlings (#2YJVQUCYJ)**\n"
                        "**Four and Twenty (#8CV0GPPR)**\n"
                        "**The Horde (#2RRCJCI0)**\n"
                        "**PlaneClashers (#9UGQ0GL)**\n\n"
                        "FWA (Farm War Alliance) is an alliance of clans who have back to back organized wars for loot. "
                        "The war outcome is predetermined and simple War Plans are posted regarding the needed outcome. "
                        "Also a place with no Heroes necessary.\n\n"
                        "Minimum requirements: TH12 and above with war weight equal to or greater than 115 with all buildings "
                        "built for your current TH Level."
                    )),
                    Separator(divider=True),
                    Text(content="### **Disclaimer**"),
                    Text(content=(
                        "Each new recruit is viewed on a case by case scenario and more details on each Clan Category will be "
                        "provided in your interview. The above requirements are a benchmark and are subject to Leadership's discretion."
                    )),
                ]
            ),
            
            # Embed 4: Next Steps
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ⏩ **NEXT STEP**"),
                    Text(content=(
                        "Now react to the ✅ below and follow this link...\n\n"
                        "https://discord.com/channels/1194706934926946457/1194706935405084766/1270203766498394203\n\n"
                        "over to the WU Strike System Channel. Read through and follow the next prompt"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"aboutus_acknowledge:{action_id}",
                                label="I understand - Continue",
                                emoji="✅"
                            )
                        ]
                    )
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


@register_action("aboutus_acknowledge", no_return=True)
@lightbulb.di.with_di
async def on_aboutus_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle the acknowledge button click"""
    ctx = kwargs.get("ctx")
    
    # Get the stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("❌ This button has expired.", ephemeral=True)
        return
    
    guild_id = data.get("guild_id")
    user_id = ctx.user.id
    
    # Get the guild and member
    guild = bot.cache.get_guild(guild_id)
    if not guild:
        await ctx.respond("❌ Unable to find the server.", ephemeral=True)
        return
    
    member = guild.get_member(user_id)
    if not member:
        await ctx.respond("❌ Unable to find your member profile.", ephemeral=True)
        return
    
    # Check if user already has the role
    if ABOUT_US_ROLE_ID in member.role_ids:
        await ctx.respond(
            f"✅ You already have access! Please continue to <#{STRIKE_SYSTEM_CHANNEL_ID}>",
            ephemeral=True
        )
        return
    
    # Add the role
    try:
        await bot.rest.add_role_to_member(
            guild=guild_id,
            user=user_id,
            role=ABOUT_US_ROLE_ID
        )
        
        await ctx.respond(
            f"✅ Role assigned! Please continue to <#{STRIKE_SYSTEM_CHANNEL_ID}> to read about our strike system.",
            ephemeral=True
        )
    except Exception as e:
        await ctx.respond(
            f"❌ Failed to assign role: {str(e)}",
            ephemeral=True
        )


loader.command(setup)