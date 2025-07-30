# extensions/commands/setup/recruit_strikesystem.py
"""
Warriors United Strike System command - displays clan rules and strike system information
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
STRIKE_SYSTEM_ROLE_ID = 1194706934926946459  # Strike system accepted role
FAMILY_PARTICULARS_CHANNEL_ID = 1194706935405084767  # Channel to direct users to


@setup.register()
class RecruitStrikeSystem(
    lightbulb.SlashCommand,
    name="recruit-strikesystem",
    description="Display Warriors United strike system and rules"
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
            "type": "recruit_strikesystem",
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
                        media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753908971/misc_images/WU_Strikes.gif"
                    )
                ]
            ),
            
            # Embed 1: Basic Rules
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 📜 **Warriors United Basic Rules** 📜"),
                    Separator(divider=True),
                    Text(content=(
                        "🛡️**WARRIORS UNITED**🛡️ is an adult community with good morals and ethics. A little banter and cutting up "
                        "is acceptable however, there are some things that just won't be tolerated...\n\n"
                        "**1.** No form of sexism, racism, religious discrimination, gender discrimination will be tolerated. "
                        "A permanent ban will be issued without a warning if this is seen anywhere on this server.\n\n"
                        "**2.** While cussing is allowed, do not cuss excessively or at someone. All such instances will be recorded. "
                        "A warning will be issued to you on each instance.\n\n"
                        "**3.** Don't post advertisements for free nitro. We don't check if they are actually legit and will ban "
                        "without a warning.\n\n"
                        "**4.** Respect other members and their privacy. If you DM someone repeatedly even after them telling you "
                        "not to do so, a warning will be issued against you.\n\n"
                        "**5.** While posting a message / image / gif / sticker, you should always follow discord ToS. "
                        "It can be found at https://discord.com/terms. Not following Discord ToS will lead to a one day mute, "
                        "and a second instance will lead to ban from the server.\n\n"
                        "On two warnings - A one day timeout will be issued to you.\n"
                        "On three warnings - A one week timeout will be issued to you.\n"
                        "On four warnings - A permanent ban from the server, along with a kick from the family in CoC will be issued."
                    )),
                ]
            ),
            
            # Embed 2: Strike System Overview
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ❌ **Warrior's United Strike System** ❌"),
                    Separator(divider=True),
                    Text(content=(
                        "Our Strike System is a penalty system in which strikes are given to members who violate the rules and "
                        "principles implemented within the Warrior's United Clan Family.\n\n"
                        "Violations have different set strikes that go along with them. It's not the amount violations you develop "
                        "but rather the amount of strikes. For example, missing both attacks in War is one violation that results "
                        "in two strikes. Members have a total of 4 strikes before disciplinary action is taken place. Once maximum "
                        "strikes are received, you will have 12hrs to open up a Ticket and discuss your situation. Failure to comply "
                        "will result in a kick from the Clan and a ban from any other Clan within the Family for a week. After one "
                        "week with no reply, your Clan Roles are stripped back to as if you just joined the Server.\n\n"
                        "All strikes are given per individual account, with the exception of civil behavior offenses. If multiple "
                        "strikes are broken within a single action, only the strike count of the more severe offense is counted; "
                        "both strikes are still noted.\n\n"
                        "Strike data is compiled and executed by the WU Strike Bot. Depending on the strike it will have a time "
                        "limit to reset. Generally speaking, it's a 60-day reset.\n\n"
                        "Below are charts of offenses and how much value each offense holds."
                    )),
                ]
            ),
            
            # Embed 3: Main Clan Strike System
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ❌ **MAIN CLAN STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    Text(content="Check below for the main clan strike system rules."),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753909119/misc_images/WU_Main_Strikes.jpg"
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 4: FWA Strike System
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ❌ **FWA STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    Text(content="Check below for fwa clan strike system rules."),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753909164/misc_images/WU_FWA_Strikes.jpg"
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 5: Terms and Conditions
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ❌ **Terms and conditions** ❌"),
                    Separator(divider=True),
                    Text(content=(
                        "• All offenses except those that reside in the Red Zone can have warnings issued before strikes are given. "
                        "Issuing warnings is up to the leadership team, and warnings will be logged.\n\n"
                        "• Strikes can be withdrawn by leadership majority.\n\n"
                        "• Leadership has the right to make changes and amendments to this system at any time in-between seasons.\n\n"
                        "• A kicked person may be reinvited to the Family after a unanimous vote by Leadership."
                    )),
                ]
            ),
            
            # Embed 6: Acknowledgment
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    Text(content=(
                        "To acknowledge you have read and agree to abide by the Warriors United Strike System, "
                        "react to the ✅ below and follow this link...\n\n"
                        "https://discord.com/channels/1194706934926946457/1194706935405084767/1270203767274344448\n\n"
                        "and head on over to check out our day-to-day family particulars\n"
                        "**Read through and follow the next prompt!**"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"strikesystem_acknowledge:{action_id}",
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


@register_action("strikesystem_acknowledge", no_return=True)
@lightbulb.di.with_di
async def on_strikesystem_acknowledge(
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
    if STRIKE_SYSTEM_ROLE_ID in member.role_ids:
        await ctx.respond(
            f"✅ You already have access! Please continue to <#{FAMILY_PARTICULARS_CHANNEL_ID}>",
            ephemeral=True
        )
        return
    
    # Add the role
    try:
        await bot.rest.add_role_to_member(
            guild=guild_id,
            user=user_id,
            role=STRIKE_SYSTEM_ROLE_ID
        )
        
        await ctx.respond(
            f"✅ Role assigned! Please continue to <#{FAMILY_PARTICULARS_CHANNEL_ID}> to check out our day-to-day family particulars.",
            ephemeral=True
        )
    except Exception as e:
        await ctx.respond(
            f"❌ Failed to assign role: {str(e)}",
            ephemeral=True
        )


loader.command(setup)