# extensions/commands/setup/recruit_familyparticulars.py
"""
Warriors United Family Particulars command - displays clan rules, war information, and CWL details
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
CLAN_RULES_READ_ROLE_ID = 1194706934926946460  # Clan Rules Read role
APPLY_HERE_CHANNEL_ID = 1194706935405084768  # Apply Here channel


@setup.register()
class RecruitFamilyParticulars(
    lightbulb.SlashCommand,
    name="recruit-familyparticulars",
    description="Display Warriors United family particulars and war rules"
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
            "type": "recruit_familyparticulars",
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
                        media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753909843/misc_images/WU_FamilyParticulars.gif"
                    )
                ]
            ),
            
            # Embed 1: Family Particulars
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Family Particulars**"),
                    Separator(divider=True),
                    Text(content="### **GOLDEN RULE**\n"),
                    Text(content=(
                        "The main rule for any Group or Gathering is \"To treat and speak to others as you would expect to be "
                        "treated or spoken to.\" We understand that not every day is a good day. Just don't bring your bad day in here."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **FRIENDLY CHALLENGES**\n"),
                    Text(content=(
                        "Everytime you come into the game, put up a Friendly Challenge. No matter what Town Hall Level you are. "
                        "This gives anyone and everyone a chance to practice."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **CLAN GAMES**\n"),
                    Text(content=(
                        "Simple and easy achievement here...each member has to achieve at least 1000 point minimum as a goal for "
                        "Clan Games. Builder Base challenges will get you there in no time. Giving you a math figure, if 40 participate "
                        "and achieve 1,250 points that will equal out to the needed 50,000."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),
            
            # Embed 2: Family War Rules
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Family War Rules**"),
                    Separator(divider=True),
                    Text(content="### 🛡 **WAR ELIGIBILITY**\n"),
                    Text(content=(
                        "To be included in war you must have a GREEN ✅ 🛡️ (opt-in) as your War Status. FWA/No Stress is explained below\n\n"
                        "If for any personal reason, you cannot participate in war or you have Heroes upgrading in a Clan that requires "
                        "Heroes in War; RED ❌ 🛡️ (opt-out) should be your War Status.\n\n"
                        "Failure to communicate or change your war availability in any of the above scenarios will result in a strike "
                        "within the WU_Strike System.\n\n"
                        "If you are in one of our FWA Clans or one of our No Stress Clans, it's 50v50 Wars so no matter what your "
                        "base is upgrading you should be ✅ with your War Status."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **PREP DAY**\n"),
                    Text(content=(
                        "Everyone is expected to help fill Defensive CC. You are responsible for filling the member below you with "
                        "the Troops they desire. No need to let one person fill all when it can be a joint effort."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **BATTLE DAY**\n"),
                    Text(content=(
                        "Our Clan War General will provide a scripted War Plan detailing your war assignment. Don't always assume "
                        "you will be attacking your Mirror/Equal. Wait for the War Plan before attacking. If one is not provided "
                        "in a timely fashion ping your Clan's War General Role and ask. Don't just go rogue. 24hrs is plenty of "
                        "time to plan and attack. Always attack for stars, not for loot or hero status. (Unless given specific "
                        "direction by the War General)"
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),
            
            # Embed 3: Clan War League
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Clan War League**"),
                    Separator(divider=True),
                    Text(content=(
                        "CWL is our pinnacle team event. Your clan is expecting and counting on you to ensure the entire team has "
                        "the best shot at success. We split up into different clans for this event. Three factors determine the "
                        "League you'll be placed:\n"
                        "1) War activity\n"
                        "2) War performance\n"
                        "3) Account strength.\n\n"
                        "Participation is not mandatory but the completion of a simple Google \"CWL Form\" before the given deadline "
                        "is mandatory for participation. No exceptions to the deadline. The data compiled from this form allows Clan "
                        "Leaders and War General's to produce Clan Rosters. We have several Clans in the Family so everyone can have "
                        "a shot at some medals. If you have multiple accounts, only three are allotted to be in one Clan Roster.\n\n"
                        "No form, No Play...pretty simple."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **Principles for every CWL Battle**\n"),
                    Text(content=(
                        "--Be available to attack and make sure you request offensive CC Troops.\n\n"
                        "--Have you heroes ready for battle.\n\n"
                        "--Have your defensive CC Troop Request laid out plainly. (e.g. Ice Golem/ Dragon or IG/Drag)\n\n"
                        "--Donate Defensive CC Troops to the player below you and/or at least one or more of your teammates, "
                        "making sure they are Max Troops.\n\n"
                        "--Make a plan of attack. You have 24hrs for one attack.\n\n"
                        "Make use of our Attack Trainer's in the \"Help-Me-Attack-This-Base\" Channels."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753909969/misc_images/warriors_united_.gif"
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 4: Acknowledgment
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    Text(content=(
                        "Reacting to the ✅ below is an acknowledgment of our Family Particulars. It will grant access to the "
                        f"<#{APPLY_HERE_CHANNEL_ID}> channel, where you will be able to create an Entry Ticket.\n\n"
                        "You will have two entry ticket choices...**ONLY CHOOSE ONE!!**"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"familyparticulars_acknowledge:{action_id}",
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


@register_action("familyparticulars_acknowledge", no_return=True)
@lightbulb.di.with_di
async def on_familyparticulars_acknowledge(
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
    if CLAN_RULES_READ_ROLE_ID in member.role_ids:
        await ctx.respond(
            f"✅ You already have access! Please continue to <#{APPLY_HERE_CHANNEL_ID}>",
            ephemeral=True
        )
        return
    
    # Add the role
    try:
        await bot.rest.add_role_to_member(
            guild=guild_id,
            user=user_id,
            role=CLAN_RULES_READ_ROLE_ID
        )
        
        await ctx.respond(
            f"✅ Role assigned! Please continue to <#{APPLY_HERE_CHANNEL_ID}> where you will be able to create an Entry Ticket.",
            ephemeral=True
        )
    except Exception as e:
        await ctx.respond(
            f"❌ Failed to assign role: {str(e)}",
            ephemeral=True
        )


loader.command(setup)