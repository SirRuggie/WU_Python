"""
Family Links Command - Main server role and clan assignment interface
"""

import lightbulb
import hikari
from typing import List, Optional

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT, GOLDENROD_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
    LinkButtonBuilder as LinkButton,
)

loader = lightbulb.Loader()

# Town Hall configuration (same as in set_townhall.py)
TH_LEVELS = [
    {"level": 17, "emoji": emojis.TH17, "role_id": 1315835882435121152},
    {"level": 16, "emoji": emojis.TH16, "role_id": 1186343231303200848},
    {"level": 15, "emoji": emojis.TH15, "role_id": 1029879502484025474},
    {"level": 14, "emoji": emojis.TH14, "role_id": 1003796205630914630},
    {"level": 13, "emoji": emojis.TH13, "role_id": 1003796042317316166},
    {"level": 12, "emoji": emojis.TH12, "role_id": 1003796143630712943},
    {"level": 11, "emoji": emojis.TH11, "role_id": 1003796173993287690},
    {"level": 10, "emoji": emojis.TH10, "role_id": 1003796340578471977},
    {"level": 9, "emoji": emojis.TH9, "role_id": 1003795980052873276},
    {"level": 8, "emoji": emojis.TH8, "role_id": 1003796008121143436},
    {"level": 7, "emoji": emojis.TH7, "role_id": 1006456898616311808},
    {"level": 6, "emoji": emojis.TH6, "role_id": 1006457868037410887},
    {"level": 5, "emoji": emojis.TH5, "role_id": 1006458029597798420},
    {"level": 4, "emoji": emojis.TH4, "role_id": 1006458193418924062},
    {"level": 3, "emoji": emojis.TH3, "role_id": 1006458298842746890},
    {"level": 2, "emoji": emojis.TH2, "role_id": 1148951648484474951},
]

# Server roles configuration
SERVER_ROLES = [
    {
        "emoji": "⚔️",
        "label": "Base Builder",
        "description": "Discuss, design and test CoC Base designs",
        "role_id": 747868210161778779
    },
    {
        "emoji": "🤖",
        "label": "Bot Developer",
        "description": "Discuss Discord bot development.",
        "role_id": 728454164186660914
    },
    {
        "emoji": "📊",
        "label": "NASDAQ",
        "description": "Share and discuss different investment strategies.",
        "role_id": 767736693137997854
    },
    {
        "emoji": "🎨",
        "label": "Graphic Designer",
        "description": "Share, post and discuss graphic design ideas.",
        "role_id": 744293746962595971
    },
    {
        "emoji": "😴",
        "label": "LazyCWL Participant",
        "description": "Grab this role to see the LazyCWL sign-ups channel.",
        "role_id": 772313841090297886
    },
    {
        "emoji": "🎤",
        "label": "VC Participant",
        "description": "A ping for those that want to chat",
        "role_id": 1148955348598788166
    }
]


@loader.command
class FamilyLinks(
    lightbulb.SlashCommand,
    name="family-links",
    description="Access the Family Clan Links panel to manage your roles and view clan information"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        await ctx.defer(ephemeral=True)
        
        # Generate unique action ID for this interaction
        action_id = str(ctx.interaction.id)
        
        # Store interaction data
        await mongo.button_store.update_one(
            {"_id": action_id},
            {"$set": {
                "_id": action_id,
                "user_id": ctx.user.id,
                "guild_id": ctx.guild_id,
                "channel_id": ctx.channel_id,
            }},
            upsert=True
        )
        
        # Get guild and member
        guild = bot.cache.get_guild(ctx.guild_id)
        member = guild.get_member(ctx.user.id) if guild else None
        
        if not member:
            await ctx.respond("❌ Could not find your member information.", ephemeral=True)
            return
        
        # Build the main panel
        components = await build_family_links_panel(guild, member, action_id, bot)
        
        # Send to channel instead of responding to the command
        channel = bot.cache.get_guild_channel(ctx.channel_id)
        if channel:
            await channel.send(components=components)
            await ctx.respond("✅ Family Links panel sent!", ephemeral=True)
        else:
            await ctx.respond("❌ Could not find the channel.", ephemeral=True)


async def build_family_links_panel(
    guild: hikari.Guild,
    member: hikari.Member,
    action_id: str,
    bot: hikari.GatewayBot
) -> List[Container]:
    """Build the main family links panel"""
    
    # Get server icon
    guild_icon_url = guild.make_icon_url() if guild else None
    server_logo = str(guild_icon_url) if guild_icon_url else "https://res.cloudinary.com/dxmtzuomk/image/upload/v1752836911/misc_images/WU_Logo.png"
    
    # Build TH dropdown options
    th_options = []
    for th_config in TH_LEVELS:
        th_options.append(
            SelectOption(
                emoji=th_config["emoji"].partial_emoji,
                label=f"TH{th_config['level']}",
                value=f"th{th_config['level']}:{th_config['role_id']}",
                description=f"Town Hall {th_config['level']}"
            )
        )
    
    # Build server role dropdown options
    server_role_options = []
    for role_config in SERVER_ROLES:
        server_role_options.append(
            SelectOption(
                emoji=role_config["emoji"],
                label=role_config["label"],
                value=f"server_role:{role_config['role_id']}",
                description=role_config["description"]
            )
        )
    
    # Build the container
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                # Header with server icon
                Section(
                    components=[
                        Text(content="# Family Clan Links:"),
                    ],
                    accessory=Thumbnail(
                        media=server_logo
                    )
                ),
                Separator(divider=True),
                
                # Town Hall Roles Section
                Text(content="## 🏰 Town Hall Roles"),
                Text(content="Select your current Town Hall Level **NOTE:** You are able to select multiple levels."),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"family_links_th:{action_id}",
                            placeholder="Select Town Hall level(s)...",
                            min_values=0,
                            max_values=len(th_options),
                            options=th_options
                        )
                    ]
                ),
                Separator(divider=True),
                
                # Server Roles Section
                Text(content="## ⚔️ Warriors United Server Roles"),
                Text(content="Please select the role that you would like to have. Click on Make a selection and select the role you would like accordingly. **NOTE:** You are able to add multiple roles."),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"family_links_server_roles:{action_id}",
                            placeholder="Select server role(s)...",
                            min_values=0,
                            max_values=len(server_role_options),
                            options=server_role_options
                        )
                    ]
                ),
                Separator(divider=True),
                
                # Warriors United Clans Section
                Text(content="## Warriors United Clans:"),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"family_links_war_clans:{action_id}",
                            label="War Clans",
                            emoji="⚔️"
                        ),
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            custom_id=f"family_links_fwa_clans:{action_id}",
                            label="FWA Clans",
                            emoji="🏳️"
                        ),
                        Button(
                            style=hikari.ButtonStyle.DANGER,
                            custom_id=f"family_links_cwl_clans:{action_id}",
                            label="CWL Clans",
                            emoji="🏆"
                        )
                    ]
                ),
                
                # Footer
                Media(
                    items=[
                        MediaItem(
                            media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753167826/misc_images/Warriors_United.gif"
                        )
                    ]
                )
            ]
        )
    ]
    
    return components


# Error response helper
def error_response(message: str, action_id: str) -> Container:
    """Create an error response container"""
    return Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ❌ **Error: {message}**"),
            Media(items=[MediaItem(media="assets/Red_Footer.png")])
        ]
    )


# TH Role Selection Handler
@register_action("family_links_th", no_return=True)
@lightbulb.di.with_di
async def family_links_th_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle Town Hall role selection"""
    
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return
    
    guild_id = data.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(ctx.user.id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Parse selected values
    selected_values = ctx.interaction.values
    selected_role_ids = set()
    
    for value in selected_values:
        if value.startswith("th"):
            _, role_id = value.split(":")
            selected_role_ids.add(int(role_id))
    
    # Get current TH roles
    current_th_role_ids = set()
    for th_config in TH_LEVELS:
        if th_config["role_id"] in member.role_ids:
            current_th_role_ids.add(th_config["role_id"])
    
    # Calculate what needs to be removed and added
    roles_to_remove = current_th_role_ids - selected_role_ids
    roles_to_add = selected_role_ids - current_th_role_ids
    
    # Get all current roles and prepare the new role list
    current_roles = list(member.role_ids)
    
    # Remove TH roles that need to be removed
    for role_id in roles_to_remove:
        if role_id in current_roles:
            current_roles.remove(role_id)
    
    # Add TH roles that need to be added
    for role_id in roles_to_add:
        if role_id not in current_roles:
            current_roles.append(role_id)
    
    # Batch update all roles at once
    try:
        await member.edit(roles=current_roles, reason="TH role update via family links")
        
        # Build success message showing what changed
        added_names = []
        removed_names = []
        
        for th_config in TH_LEVELS:
            if th_config["role_id"] in roles_to_add:
                added_names.append(f"{th_config['emoji']} TH{th_config['level']}")
            elif th_config["role_id"] in roles_to_remove:
                removed_names.append(f"{th_config['emoji']} TH{th_config['level']}")
        
        message_parts = ["✅ **Town Hall roles updated!**"]
        if added_names:
            message_parts.append(f"**Added:** {', '.join(added_names)}")
        if removed_names:
            message_parts.append(f"**Removed:** {', '.join(removed_names)}")
        if not added_names and not removed_names:
            message_parts = ["✅ No changes made - selected roles were already assigned."]
        
        await ctx.respond("\n".join(message_parts), ephemeral=True)
        
    except Exception as e:
        await ctx.respond(f"❌ Failed to update roles: {str(e)}", ephemeral=True)


# Server Role Selection Handler
@register_action("family_links_server_roles", no_return=True)
@lightbulb.di.with_di
async def family_links_server_roles_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle server role selection"""
    
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return
    
    guild_id = data.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(ctx.user.id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Parse selected values
    selected_values = ctx.interaction.values
    selected_role_ids = set()
    
    for value in selected_values:
        if value.startswith("server_role:"):
            _, role_id = value.split(":")
            selected_role_ids.add(int(role_id))
    
    # Get current server roles
    current_server_role_ids = set()
    for role_config in SERVER_ROLES:
        if role_config["role_id"] in member.role_ids:
            current_server_role_ids.add(role_config["role_id"])
    
    # Calculate what needs to be removed and added
    roles_to_remove = current_server_role_ids - selected_role_ids
    roles_to_add = selected_role_ids - current_server_role_ids
    
    # Get all current roles and prepare the new role list
    current_roles = list(member.role_ids)
    
    # Remove server roles that need to be removed
    for role_id in roles_to_remove:
        if role_id in current_roles:
            current_roles.remove(role_id)
    
    # Add server roles that need to be added
    for role_id in roles_to_add:
        if role_id not in current_roles:
            current_roles.append(role_id)
    
    # Batch update all roles at once
    try:
        await member.edit(roles=current_roles, reason="Server role update via family links")
        
        # Build success message showing what changed
        added_names = []
        removed_names = []
        
        for role_config in SERVER_ROLES:
            if role_config["role_id"] in roles_to_add:
                added_names.append(f"{role_config['emoji']} {role_config['label']}")
            elif role_config["role_id"] in roles_to_remove:
                removed_names.append(f"{role_config['emoji']} {role_config['label']}")
        
        message_parts = ["✅ **Server roles updated!**"]
        if added_names:
            message_parts.append(f"**Added:** {', '.join(added_names)}")
        if removed_names:
            message_parts.append(f"**Removed:** {', '.join(removed_names)}")
        if not added_names and not removed_names:
            message_parts = ["✅ No changes made - selected roles were already assigned."]
        
        await ctx.respond("\n".join(message_parts), ephemeral=True)
        
    except Exception as e:
        await ctx.respond(f"❌ Failed to update roles: {str(e)}", ephemeral=True)


# War Clans Button Handler
@register_action("family_links_war_clans", no_return=True)
@lightbulb.di.with_di
async def family_links_war_clans_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Display War clans (Tactical and Flexible Fun)"""
    
    # Fetch clans by type
    tactical_clans = await mongo.clans.find({"type": "Tactical"}).to_list(length=None)
    flexible_fun_clans = await mongo.clans.find({"type": "Flexible Fun"}).to_list(length=None)
    
    # Build options
    options = []
    
    # Add Tactical clans first
    for clan in tactical_clans:
        emoji_str = clan.get("emoji", "⚔️")
        # Parse custom emoji if needed
        if emoji_str and emoji_str.count(":") >= 2:
            try:
                from utils.emoji import EmojiType
                partial_emoji = EmojiType(emoji_str).partial_emoji
                emoji = partial_emoji
            except:
                emoji = "⚔️"
        else:
            emoji = emoji_str or "⚔️"
        
        options.append(
            SelectOption(
                emoji=emoji,
                label=clan.get("name", "Unknown Clan"),
                value=clan.get("tag", ""),
                description=f"Tactical - {clan.get('tag', '#N/A')}"
            )
        )
    
    # Add Flexible Fun clans
    for clan in flexible_fun_clans:
        emoji_str = clan.get("emoji", "🎮")
        # Parse custom emoji if needed
        if emoji_str and emoji_str.count(":") >= 2:
            try:
                from utils.emoji import EmojiType
                partial_emoji = EmojiType(emoji_str).partial_emoji
                emoji = partial_emoji
            except:
                emoji = "🎮"
        else:
            emoji = emoji_str or "🎮"
        
        options.append(
            SelectOption(
                emoji=emoji,
                label=clan.get("name", "Unknown Clan"),
                value=clan.get("tag", ""),
                description=f"Flexible Fun - {clan.get('tag', '#N/A')}"
            )
        )
    
    if not options:
        await ctx.respond("No War clans found in the database.", ephemeral=True)
        return
    
    # Build component
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ⚔️ **War Clans**"),
                Text(content="**Tactical** clans focus on competitive war strategies\n**Flexible Fun** clans balance competition with enjoyment"),
                Separator(divider=True),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"view_clan_info:{action_id}",
                            placeholder="Select a clan to view details...",
                            min_values=1,
                            max_values=1,
                            options=options[:25]  # Discord limit
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]
    
    await ctx.respond(components=components, ephemeral=True)


# FWA Clans Button Handler
@register_action("family_links_fwa_clans", no_return=True)
@lightbulb.di.with_di
async def family_links_fwa_clans_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Display FWA clans"""
    
    # Fetch FWA clans
    fwa_clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
    
    # Build options
    options = []
    
    for clan in fwa_clans:
        emoji_str = clan.get("emoji", "🏳️")
        # Parse custom emoji if needed
        if emoji_str and emoji_str.count(":") >= 2:
            try:
                from utils.emoji import EmojiType
                partial_emoji = EmojiType(emoji_str).partial_emoji
                emoji = partial_emoji
            except:
                emoji = "🏳️"
        else:
            emoji = emoji_str or "🏳️"
        
        options.append(
            SelectOption(
                emoji=emoji,
                label=clan.get("name", "Unknown Clan"),
                value=clan.get("tag", "")
            )
        )
    
    if not options:
        await ctx.respond("No FWA clans found in the database.", ephemeral=True)
        return
    
    # Build component
    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## 🏳️ **FWA Clans**"),
                Text(content="Farm War Alliance clans focus on loot farming through organized wars"),
                Separator(divider=True),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"view_clan_info:{action_id}",
                            placeholder="Select a clan to view details...",
                            min_values=1,
                            max_values=1,
                            options=options[:25]  # Discord limit
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]
    
    await ctx.respond(components=components, ephemeral=True)


# CWL Clans Button Handler
@register_action("family_links_cwl_clans", no_return=True)
@lightbulb.di.with_di
async def family_links_cwl_clans_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Display CWL clans"""
    
    # Fetch CWL clans
    cwl_clans = await mongo.clans.find({"type": "CWL"}).to_list(length=None)
    
    # Build options
    options = []
    
    for clan in cwl_clans:
        emoji_str = clan.get("emoji", "🏆")
        # Parse custom emoji if needed
        if emoji_str and emoji_str.count(":") >= 2:
            try:
                from utils.emoji import EmojiType
                partial_emoji = EmojiType(emoji_str).partial_emoji
                emoji = partial_emoji
            except:
                emoji = "🏆"
        else:
            emoji = emoji_str or "🏆"
        
        options.append(
            SelectOption(
                emoji=emoji,
                label=clan.get("name", "Unknown Clan"),
                value=clan.get("tag", "")
            )
        )
    
    if not options:
        await ctx.respond("No CWL clans found in the database.", ephemeral=True)
        return
    
    # Build component
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content="## 🏆 **CWL Clans**"),
                Text(content="Clan War League focused clans competing for league medals and rewards"),
                Separator(divider=True),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"view_clan_info:{action_id}",
                            placeholder="Select a clan to view details...",
                            min_values=1,
                            max_values=1,
                            options=options[:25]  # Discord limit
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]
    
    await ctx.respond(components=components, ephemeral=True)


# View Clan Info Handler
@register_action("view_clan_info", no_return=True)
@lightbulb.di.with_di
async def view_clan_info_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Display detailed clan information when selected from dropdown"""
    
    # Get selected clan tag
    selected_clan_tag = ctx.interaction.values[0]
    
    # Fetch clan data from MongoDB
    clan_doc = await mongo.clans.find_one({"tag": selected_clan_tag})
    if not clan_doc:
        await ctx.respond("❌ Clan not found in database.", ephemeral=True)
        return
    
    # Build clan link
    clan_link = f"https://link.clashofclans.com/en/?action=OpenClanProfile&tag={selected_clan_tag.replace('#', '')}"
    
    # Get clan details
    clan_name = clan_doc.get("name", "Unknown Clan")
    clan_logo = clan_doc.get("logo")  # Logo URL is stored in the 'logo' field
    
    # Build the clan info embed
    components = []
    
    if clan_logo and clan_logo.startswith('http'):
        # If clan has a logo, show it with the info
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"# {clan_name}"),
                    Media(items=[MediaItem(media=clan_logo)]),
                    ActionRow(
                        components=[
                            LinkButton(
                                url=clan_link,
                                label=f"Join {clan_name}",
                                emoji="🏰"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]
    else:
        # No logo, just show the clan name
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"# {clan_name}"),
                    ActionRow(
                        components=[
                            LinkButton(
                                url=clan_link,
                                label=f"Join {clan_name}",
                                emoji="🏰"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]
    
    await ctx.respond(components=components, ephemeral=True)


