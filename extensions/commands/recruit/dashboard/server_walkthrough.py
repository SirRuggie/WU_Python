# extensions/commands/recruit/dashboard/server_walkthrough.py
"""
Handle the Server walk thru action from the recruit dashboard
"""

import lightbulb
import hikari
import asyncio
from datetime import datetime, timezone

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    LinkButtonBuilder as LinkButton,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
)

# Walkthrough delay configuration (in seconds)
WALKTHROUGH_INITIAL_DELAY = 0  # Immediate initial message
WALKTHROUGH_ANNOUNCEMENT_DELAY = 30  # Wait before announcement channel
WALKTHROUGH_CHAT_DELAY = 30  # Wait before chat channel
WALKTHROUGH_HELP_DELAY = 30  # Wait before help me attack channel
WALKTHROUGH_LOUNGE_DELAY = 30  # Wait before lounge channel


@register_action("server_walkthrough")
@lightbulb.di.with_di
async def server_walkthrough_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display clan selection for server walkthrough"""

    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Get all clans from database
    clan_data = await mongo.clans.find().to_list(length=None)
    member_clans = []
    
    # Find which clans the member is in
    for clan_doc in clan_data:
        clan_role_id = clan_doc.get("role_id")
        if clan_role_id and clan_role_id in member.role_ids:
            member_clans.append(clan_doc)
    
    if not member_clans:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ⚠️ **No Clan Assigned**"),
                    Text(content="The member needs to be assigned to a clan before starting the walkthrough."),
                    Text(content="_Please use the 'Add Clan Roles' option first._"),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"refresh_dashboard:{action_id}",
                                label="Back to Dashboard",
                                emoji="↩️"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]
    
    # Build select menu options
    options = []
    for clan in member_clans:
        emoji = clan.get("emoji", "🏛️")
        # Parse emoji if it's a custom emoji format
        if emoji and emoji.count(":") >= 2:
            try:
                from utils.emoji import EmojiType
                partial_emoji = EmojiType(emoji).partial_emoji
                emoji = partial_emoji if partial_emoji else "🏛️"
            except:
                emoji = "🏛️"
        
        options.append(
            SelectOption(
                label=clan.get("name", "Unknown Clan"),
                value=clan.get("tag", ""),
                description=clan.get("tag", "#N/A"),
                emoji=emoji
            )
        )
    
    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content=f"## 🎯 **Server Walkthrough - Select Clan**"),
                Separator(divider=True),
                
                Text(content=(
                    f"**Member:** {member.display_name}\n"
                    f"**Assigned Clans:** {len(member_clans)}\n\n"
                    "Please select which clan this walkthrough is for:"
                )),
                
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"execute_server_walkthrough:{action_id}",
                            placeholder="Select a clan...",
                            min_values=1,
                            max_values=1,
                            options=options
                        )
                    ]
                ),
                
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"refresh_dashboard:{action_id}",
                            label="Back to Dashboard",
                            emoji="↩️"
                        )
                    ]
                ),
                
                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]

    return components


@register_action("execute_server_walkthrough")
@lightbulb.di.with_di
async def execute_server_walkthrough_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Process clan selection and send welcome message to new-warrior-launchpad"""
    
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]
    
    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    recruiter_id = data.get("recruiter_id")
    
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    recruiter = guild.get_member(recruiter_id) if guild else None
    
    if not member:
        return [error_response("Member not found", action_id)]
    
    # Get selected clan tag
    selected_clan_tag = ctx.interaction.values[0]
    
    # Fetch the clan data
    clan_doc = await mongo.clans.find_one({"tag": selected_clan_tag})
    if not clan_doc:
        return [error_response("Clan not found", action_id)]
    
    # Target channel for welcome message
    WELCOME_CHANNEL_ID = 1128966424082255872  # new-warrior-launchpad
    welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
    
    if not welcome_channel:
        return [error_response("Welcome channel not found", action_id)]
    
    # Get clan info
    clan_name = clan_doc.get("name", "Unknown Clan")
    clan_tag = clan_doc.get("tag", "")
    clan_role_id = clan_doc.get("role_id")
    clan_banner = clan_doc.get("banner")
    
    # Build clan link
    clan_link = f"https://link.clashofclans.com/en/?action=OpenClanProfile&tag={clan_tag.replace('#', '')}"
    
    # Get server logo dynamically
    guild_icon_url = guild.make_icon_url() if guild else None
    server_logo = str(guild_icon_url) if guild_icon_url else "https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836911/misc_images/WU_Logo.png"
    
    # Build welcome message components
    welcome_components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                # Section with server logo and member mention
                Section(
                    components=[
                        Text(content=f"{member.mention}"),
                    ],
                    accessory=Thumbnail(
                        media=server_logo
                    )
                ),
                
                # Large clan name
                Text(content=f"# {clan_name}"),
                Separator(divider=True),
                
                # Welcome message
                Text(content=(
                    f"## Welcome to the family!!! 🎉\n\n"
                    f"You've been assigned to **{clan_name}**\n\n"
                    f"You have been given the:\n"
                    f"• <@&{clan_role_id}> Clan Role\n"
                    f"• Family Role\n"
                    f"• All TH Roles that apply to you\n\n"
                    f"Now ping the __Recruiter__ that was helping you below and they will kick off a server walkthrough "
                    f"guiding you to important channels for your day to day dealings.\n\n"
                    f"The clan link for **{clan_name}** is here also, feel free to send a join request "
                    f"making sure you utilize one of the proper join codes already discussed."
                )),
                Separator(divider=True),
                
                # Clan banner image
                Media(
                    items=[
                        MediaItem(
                            media=clan_banner if clan_banner else "assets/Red_Footer.png"
                        )
                    ]
                ),
                Separator(divider=True),
                # Action buttons
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            custom_id=f"begin_walkthrough:{action_id}:{selected_clan_tag}",
                            label="Begin Walkthrough",
                            emoji="🚀"
                        ),
                        LinkButton(
                            url=clan_link,
                            label=f"Join {clan_name}",
                            emoji="🏰"
                        )
                    ]
                ),
            ]
        )
    ]
    
    try:
        # Send the welcome message to the channel
        await welcome_channel.send(
            components=welcome_components,
            user_mentions=[user_id]
        )
        
        # Update the dashboard to show success
        return [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ **Welcome Message Sent!**"),
                    Separator(divider=True),
                    Text(content=(
                        f"The welcome message has been posted in <#{WELCOME_CHANNEL_ID}>.\n\n"
                        f"**Member:** {member.display_name}\n"
                        f"**Clan:** {clan_name}\n"
                        f"**Recruiter:** {recruiter.display_name if recruiter else 'Unknown'}\n\n"
                        f"The member can now click 'Begin Walkthrough' to start the guided tour."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"refresh_dashboard:{action_id}",
                                label="Back to Dashboard",
                                emoji="↩️"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Green_Footer.png")])
                ]
            )
        ]
        
    except Exception as e:
        return [error_response(f"Failed to send welcome message: {str(e)[:100]}", action_id)]


async def execute_walkthrough_sequence(member: hikari.Member, guild: hikari.Guild, clan_doc: dict, bot: hikari.GatewayBot):
    """Execute the timed walkthrough sequence, pinging the member in various channels"""
    
    # Helper function to send a placeholder message
    async def send_placeholder_message(channel_id: int, message_text: str = "Placeholder"):
        channel = guild.get_channel(channel_id)
        if channel:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content=f"{member.mention}"),
                        Separator(divider=True),
                        Text(content=message_text),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            try:
                await channel.send(components=components, user_mentions=[member.id])
            except Exception as e:
                print(f"Failed to send walkthrough message to channel {channel_id}: {e}")
    
    # Get clan channels
    clan_announcement_id = clan_doc.get("announcement_id") if clan_doc else None
    clan_chat_id = clan_doc.get("chat_channel_id") if clan_doc else None
    
    # Fixed channel IDs
    HELP_ME_ATTACK_CHANNEL = 1005916813378465832
    LOUNGE_CHANNEL = 671836698371424256
    
    try:
        # Initial delay (should be 0 for immediate)
        if WALKTHROUGH_INITIAL_DELAY > 0:
            await asyncio.sleep(WALKTHROUGH_INITIAL_DELAY)
        
        # Clan announcement channel
        if clan_announcement_id:
            await asyncio.sleep(WALKTHROUGH_ANNOUNCEMENT_DELAY)
            await send_placeholder_message(clan_announcement_id, "**📢 Clan Announcements**\nWar announcements and special instructions will be made here in this channel.")
        
        # Clan chat channel - Custom message with troop request instructions
        if clan_chat_id:
            await asyncio.sleep(WALKTHROUGH_CHAT_DELAY)
            channel = guild.get_channel(clan_chat_id)
            if channel:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content=f"{member.mention}"),
                            Separator(divider=True),
                            Text(content="## 🎯 **How to request troops!**"),
                            Text(content=(
                                "If you need troops for War or any other urgent reason, come here and use this "
                                "slash command format with 🧙 Clash Commander Bot...\n\n"
                                "`/announce donate`\n"
                                "or\n"
                                "`/announce supertroop`\n\n"
                                "Then simply enter the message you'd like to send to the donor as well as the troop name.\n\n"
                                "It pings the person(s) in the clan who can provide Max Level for requested troops...👍🏻\n\n"
                                "If you're wanting a Friendly Challenge(FC) and no one of your level is online in-game, "
                                "this is where you would send for a FC. It doesn't always get them to come in game but "
                                "it's your best bet to get their attention...💪🏼\n\n"
                                "Simply ping the TH Level Role in your Clan's Chat Channel and all players with that "
                                "Level in your Clan will be announced."
                            )),
                            Media(items=[MediaItem(media="assets/Red_Footer.png")])
                        ]
                    )
                ]
                try:
                    await channel.send(components=components, user_mentions=[member.id])
                except Exception as e:
                    print(f"Failed to send walkthrough message to channel {clan_chat_id}: {e}")
        
        # Help me attack this base channel - Custom message with attack help instructions
        await asyncio.sleep(WALKTHROUGH_HELP_DELAY)
        channel = guild.get_channel(HELP_ME_ATTACK_CHANNEL)
        if channel:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content=f"{member.mention}"),
                        Separator(divider=True),
                        Text(content="## ⚔️ **Help me attack this base!**"),
                        Text(content=(
                            "Having doubts or concerns on a base you're going to attack? You have a few choices...\n\n"
                            "**1)** Take a screenshot of the Base you wish to get info on. \n"
                            "Use Find This Base <:FTB:1397098130792775781> `/scan` and add the pic into the command.\n\n"
                            "**2)** Bring a screenshot here and ping the\n"
                            "<@&1006460305464905808>\n"
                            "Role for one-on-one help.\n\n"
                            "**3)** Bring a screenshot here and ping the Town Hall Role equal to the Base you're attacking.\n\n"
                            "For those joining FWA, the above will be helpful in Mismatch Wars and Blacklisted Wars."
                        )),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            try:
                await channel.send(components=components, user_mentions=[member.id])
            except Exception as e:
                print(f"Failed to send walkthrough message to channel {HELP_ME_ATTACK_CHANNEL}: {e}")
        
        # Lounge channel - Custom welcome messages
        await asyncio.sleep(WALKTHROUGH_LOUNGE_DELAY)
        channel = guild.get_channel(LOUNGE_CHANNEL)
        if channel:
            # First message - Welcome to the Team
            components1 = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content=f"{member.mention}"),
                        Separator(divider=True),
                        Text(content="## 🎉 **Welcome to the Team!**"),
                        Text(content=(
                            "This is your Lounge... All of our Clans chill and converse here. Feel free to post "
                            "anything you'd like here but we ask to keep your War related stuff in your Clan's War Channels.\n\n"
                            "You may have noticed we changed your nickname to match your CoC name. Makes it easier "
                            "for everyone to know who they're talking to.\n\n"
                            "As we're an International Family, we've added your Timezone acronym at the tail end of "
                            "your nickname. It helps us know where everyone is in the World.\n\n"
                            "Welcome to Warriors United!! Feel free to ask questions regarding anything about the "
                            "operation. Pinging our Leaders is acceptable. We're here to help...🫡"
                        )),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            
            # Second message - Noob welcome
            components2 = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content=f"{member.mention}"),
                        Separator(divider=True),
                        Text(content="## 😈 **Welcome to Warriors United \"noob\"**"),
                        Text(content="We have a special way of welcoming noobs into the Fam...."),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            
            try:
                # Send first message
                await channel.send(components=components1, user_mentions=[member.id])
                # Send second message immediately after
                await channel.send(components=components2, user_mentions=[member.id])
            except Exception as e:
                print(f"Failed to send walkthrough messages to lounge channel {LOUNGE_CHANNEL}: {e}")
        
    except Exception as e:
        print(f"Error during walkthrough sequence: {e}")


@register_action("begin_walkthrough", no_return=True)
@lightbulb.di.with_di
async def begin_walkthrough_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle the Begin Walkthrough button from the welcome message"""
    
    # Check if the user has the recruitment team role
    RECRUITMENT_TEAM_ROLE_ID = 1003797104088592444
    guild = bot.cache.get_guild(ctx.interaction.guild_id)
    clicking_member = guild.get_member(ctx.user.id) if guild else None
    
    if not clicking_member or RECRUITMENT_TEAM_ROLE_ID not in clicking_member.role_ids:
        await ctx.respond(
            "❌ Only members of the Recruitment Team can start the walkthrough.",
            ephemeral=True
        )
        return
    
    # Parse the custom_id to get the original action_id and clan tag
    # Format: begin_walkthrough:action_id:clan_tag
    parts = ctx.interaction.custom_id.split(":")
    if len(parts) >= 3:
        original_action_id = parts[1]
        clan_tag = parts[2]
    else:
        await ctx.respond("Invalid walkthrough data", ephemeral=True)
        return
    
    # Get the original dashboard data
    data = await mongo.button_store.find_one({"_id": original_action_id})
    if not data:
        # If no data, just use the person who clicked
        user_id = ctx.user.id
        guild_id = ctx.interaction.guild_id
    else:
        user_id = data.get("user_id")
        guild_id = data.get("guild_id")
    
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Get clan info
    clan_doc = await mongo.clans.find_one({"tag": clan_tag})
    
    # Send the initial walkthrough message
    try:
        initial_message = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=f"{member.mention}"),
                    Separator(divider=True),
                    Text(content="## 🚀 **Walkthrough Started!**"),
                    Text(content=(
                        "Good deal!!!! Our Bot is going to walk you thru the Server, "
                        "pinging you in the important channels for your clan. "
                        "Feel free to explore the rest of the server on your own.\n\n"
                        "For those joining multiple clans, all clans have the same channel set up. "
                        "This walk thru paints a good picture for the other clan(s) you are joining as well."
                    )),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
        
        # Send as a new message in the channel
        channel = guild.get_channel(ctx.interaction.channel_id)
        if channel:
            await channel.send(components=initial_message, user_mentions=[user_id])
    except Exception as e:
        print(f"Failed to send initial walkthrough message: {e}")
    
    # Store walkthrough start timestamp in recruit_onboarding collection
    walkthrough_data = {
        "_id": f"walkthrough_{user_id}_{guild_id}",
        "user_id": user_id,
        "guild_id": guild_id,
        "walkthrough_started_at": datetime.now(timezone.utc),
        "new_recruit_role_removed": False,
        "clan_tag": clan_tag
    }
    
    # Use upsert to handle multiple walkthroughs for the same user
    await mongo.recruit_onboarding.update_one(
        {"_id": f"walkthrough_{user_id}_{guild_id}"},
        {"$set": walkthrough_data},
        upsert=True
    )
    
    # Start the walkthrough sequence in the background
    asyncio.create_task(execute_walkthrough_sequence(member, guild, clan_doc, bot))
    
    # Just acknowledge the interaction without editing
    #await ctx.respond("Walkthrough started!", ephemeral=True)





# Helper function for error responses
def error_response(message: str, action_id: str) -> Container:
    return Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ❌ **Error: {message}**"),
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"refresh_dashboard:{action_id}",
                        label="Back to Dashboard",
                        emoji="↩️"
                    )
                ]
            ),
            Media(items=[MediaItem(media="assets/Red_Footer.png")])
        ]
    )