# extensions/commands/recruit/dashboard/add_clan_roles.py
"""
Handle the Add Clan Roles action from the recruit dashboard.

This uses a single-message flow where the dashboard is edited to show the clan menu,
and then the clan menu can be edited back to show the dashboard.
"""

import lightbulb
import hikari
from typing import List, Optional

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT, GOLD_ACCENT
from utils.emoji import emojis
from utils.classes import Clan

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
)


# Helper function for error responses
def error_response(message: str, action_id: str) -> Container:
    """Create an error response container"""
    return Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ❌ **Error: {message}**"),
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        custom_id=f"back_to_dashboard:{action_id}",
                        label="Back to Dashboard",
                        emoji="↩️"
                    )
                ]
            ),
            Media(items=[MediaItem(media="assets/Red_Footer.png")])
        ]
    )


def build_clan_menu(
    member: hikari.Member,
    clans: List[Clan],
    action_id: str,
    accent_color: int = BLUE_ACCENT,
    success_message: Optional[str] = None,
    bot: hikari.GatewayBot = None
) -> List[Container]:
    """Build the clan selection menu with current state"""
    
    # Check which clan roles the member already has
    member_role_ids = set(member.role_ids)
    current_clan_roles = []
    available_clans = []
    
    for clan in clans:
        if clan.role_id and clan.role_id in member_role_ids:
            # Add emoji if clan has one, otherwise just show name
            if clan.partial_emoji:
                try:
                    # Test if emoji is valid by converting to string
                    str(clan.partial_emoji)
                    current_clan_roles.append(f"{clan.partial_emoji} {clan.name}")
                except Exception:
                    # If emoji is invalid, just show name
                    current_clan_roles.append(clan.name)
            else:
                # No emoji, just show name
                current_clan_roles.append(clan.name)
        elif clan.role_id:  # Only show clans with configured roles
            available_clans.append(clan)
    
    # Build select menu options
    options = []
    for i, clan in enumerate(available_clans):
        kwargs = {
            "label": clan.name,
            "value": f"{clan.tag}:{clan.role_id}",
            "description": f"{clan.tag}"
        }
        # Only add emoji if clan has one and it's valid
        if clan.partial_emoji:
            try:
                # Try to convert to string to test validity
                str(clan.partial_emoji)
                # Additional validation - check if emoji ID is valid
                if hasattr(clan.partial_emoji, 'id') and clan.partial_emoji.id:
                    # Try to validate the emoji more thoroughly
                    try:
                        # Check if the emoji has required attributes
                        if not hasattr(clan.partial_emoji, 'name') or not hasattr(clan.partial_emoji, 'id'):
                            raise ValueError("Emoji missing required attributes")
                        
                        # Simply add the emoji if validation passes
                        kwargs["emoji"] = clan.partial_emoji
                    except Exception as e:
                        # Silently skip adding emoji if it fails
                        pass
                else:
                    # Invalid emoji ID, skip it
                    pass
            except Exception as e:
                # Failed to validate emoji, skip it
                pass
                # Don't add emoji if it's invalid
        # If no emoji or invalid emoji, just create option without emoji
        try:
            options.append(SelectOption(**kwargs))
        except Exception as e:
            # Skip this clan if we can't create an option for it
            continue
    
    # Build component list
    component_list = [
        Text(content=f"## ⚔️ **Set Clan Roles for {member.display_name}**"),
        Separator(divider=True),
    ]
    
    # Add success message if provided
    if success_message:
        component_list.append(Text(content=success_message))
        component_list.append(Separator(divider=True))
    
    # Add current roles section
    component_list.extend([
        Text(content="### Current Clan Memberships:"),
        Text(content="\n".join(current_clan_roles) if current_clan_roles else "_No clan roles assigned_"),
        Separator(divider=True),
    ])
    
    # Build the common button row that we'll use in all cases
    button_row = ActionRow(
        components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"add_all_clans:{action_id}",
                label="Add ALL Clans",
                emoji="🌟",
                is_disabled=len(available_clans) == 0  # Disabled when no clans available to add
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"remove_all_clans:{action_id}",
                label="Remove All Clan Roles",
                emoji="🗑️",
                is_disabled=len(current_clan_roles) == 0  # Disabled when no roles to remove
            ),
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"back_to_dashboard:{action_id}",
                label="Back to Dashboard",
                emoji="↩️"
            )
        ]
    )
    
    if not options and not current_clan_roles:
        # No clans configured at all
        component_list.extend([
            Text(content="**❌ No clans are configured in the database.**"),
            button_row,
        ])
    elif not options:
        # Member already has all available clan roles
        component_list.extend([
            Text(content="**ℹ️ This member already has all available clan roles.**"),
            button_row,
        ])
    else:
        # Show selection interface
        component_list.extend([
            Text(content=(
                "**Instructions:**\n"
                "• Select clans to add from the dropdown\n"
                "• Existing clan roles will be kept\n"
                "• Use 'Remove All Clan Roles' to clear all clan assignments"
            )),
            Separator(divider=True),
            ActionRow(
                components=[
                    TextSelectMenu(
                        custom_id=f"execute_add_clans:{action_id}",
                        placeholder="Select clan(s) to add...",
                        min_values=1,
                        max_values=min(len(options), 25),  # Discord limit
                        options=options
                    )
                ]
            ),
            button_row,
        ])
    
    component_list.append(
        Media(items=[MediaItem(media=f"assets/{accent_color == GREEN_ACCENT and 'Green' or accent_color == RED_ACCENT and 'Red' or accent_color == GOLD_ACCENT and 'Gold' or 'Blue'}_Footer.png")])
    )
    
    return [Container(accent_color=accent_color, components=component_list)]


@register_action("add_clan_roles", no_return=True)
@lightbulb.di.with_di
async def add_clan_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Display clan role selection interface"""
    
    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    if not member:
        # Member not found - refresh the dashboard to show current state
        from .dashboard import create_dashboard_page
        
        # Get stored data for dashboard parameters
        data = await mongo.button_store.find_one({"_id": action_id})
        if not data:
            # Can't refresh without data, just show error
            await ctx.interaction.edit_initial_response(
                components=[error_response("Session expired", action_id)]
            )
            return
        
        user = bot.cache.get_user(user_id)
        recruiter = guild.get_member(data.get("recruiter_id")) if guild else None
        
        dashboard_components = await create_dashboard_page(
            action_id=action_id,
            user=user,
            member=None,  # Pass None to show member left server
            recruiter=recruiter,
            bot=bot,
            mongo=mongo,
            guild_id=guild_id,
            channel_id=data.get("channel_id"),
            recruiter_id=data.get("recruiter_id")
        )
        
        await ctx.interaction.edit_initial_response(components=dashboard_components)
        return
    
    # Fetch all clans from database
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]
    
    components = build_clan_menu(member, clans, action_id, bot=bot)
    # Edit the existing dashboard message instead of creating a new one
    await ctx.interaction.edit_initial_response(components=components)


@register_action("execute_add_clans", no_return=True)
@lightbulb.di.with_di
async def execute_add_clans_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Execute clan role assignment"""
    
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return
    
    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Get all clans to check current roles
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]
    
    # Parse selected values
    selected_values = ctx.interaction.values
    selected_role_ids = set()
    clan_by_role = {}
    
    for value in selected_values:
        clan_tag, role_id = value.split(":")
        role_id = int(role_id)
        selected_role_ids.add(role_id)
        
        # Find the clan for this role
        for clan in clans:
            if clan.tag == clan_tag:
                clan_by_role[role_id] = clan
                break
    
    # Get all clan role IDs
    all_clan_role_ids = {clan.role_id for clan in clans if clan.role_id}
    
    # Get current roles, separating clan and non-clan roles
    current_roles = member.role_ids
    current_clan_role_ids = {role_id for role_id in current_roles if role_id in all_clan_role_ids}
    non_clan_roles = [role_id for role_id in current_roles if role_id not in all_clan_role_ids]
    
    # Calculate what needs to be added (we don't remove any existing clan roles)
    roles_to_add = selected_role_ids - current_clan_role_ids
    
    # Build the final role list: non-clan roles + existing clan roles + new clan roles
    # Important: Do NOT include @everyone role as it's managed automatically by Discord
    final_roles = [r for r in (non_clan_roles + list(current_clan_role_ids | selected_role_ids)) if r != ctx.interaction.guild_id]
    
    # Track changes for display
    added_roles = []
    
    for clan in clans:
        if clan.role_id in roles_to_add:
            # Only add emoji if clan has a valid one
            if clan.partial_emoji:
                try:
                    str(clan.partial_emoji)
                    added_roles.append(f"{clan.partial_emoji} {clan.name}")
                except Exception:
                    # If emoji is invalid, just show name
                    added_roles.append(clan.name)
            else:
                # No emoji, just show name
                added_roles.append(clan.name)
    
    # Batch update all roles at once
    if added_roles:
        try:
            await member.edit(roles=final_roles, reason="Clan roles added via dashboard")
        except Exception as e:
            # If batch fails, reset the list
            added_roles = []
    
    # Create success message without heading
    if not added_roles:
        success_text = "Selected clans were already assigned."
    else:
        success_text = f"**Added:** {', '.join(added_roles)}"
    
    # Refresh member data and update menu
    member = guild.get_member(user_id)
    components = build_clan_menu(member, clans, action_id, GREEN_ACCENT, success_text, bot)
    
    await ctx.interaction.edit_initial_response(components=components)


@register_action("add_all_clans", no_return=True)
@lightbulb.di.with_di
async def add_all_clans_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Add all available clan roles at once"""
    
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return
    
    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Get all clans
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]
    
    # Get all clan role IDs
    all_clan_role_ids = {clan.role_id for clan in clans if clan.role_id}
    
    # Get current roles
    current_roles = member.role_ids
    current_role_set = set(current_roles)
    
    # Track what will be added
    added_clans = []
    already_had = []
    
    # Determine which clan roles to add
    roles_to_add = []
    for clan in clans:
        if not clan.role_id:
            continue
        
        if clan.role_id in current_role_set:
            # Only add emoji if clan has a valid one
            if clan.partial_emoji:
                try:
                    str(clan.partial_emoji)
                    already_had.append(f"{clan.partial_emoji} {clan.name}")
                except Exception:
                    already_had.append(clan.name)
            else:
                already_had.append(clan.name)
        else:
            roles_to_add.append(clan.role_id)
            # Only add emoji if clan has a valid one
            if clan.partial_emoji:
                try:
                    str(clan.partial_emoji)
                    added_clans.append(f"{clan.partial_emoji} {clan.name}")
                except Exception:
                    added_clans.append(clan.name)
            else:
                added_clans.append(clan.name)
    
    # Build final role list: current roles + new clan roles (excluding @everyone)
    final_roles = [r for r in (list(current_roles) + roles_to_add) if r != ctx.interaction.guild_id]
    
    # Batch update all roles at once
    if roles_to_add:
        try:
            await member.edit(roles=final_roles, reason="All clan roles added via recruit dashboard")
        except Exception:
            # If batch fails, clear the added list
            added_clans = []
    
    # Create success message without heading
    if added_clans:
        success_parts = [f"**Added:** {', '.join(added_clans)}"]
        if already_had:
            success_parts.append(f"**Already Had:** {', '.join(already_had)}")
        success_text = "\n".join(success_parts)
    else:
        success_text = "Member already has all available clan roles."
    
    # Refresh member and update menu
    member = guild.get_member(user_id)
    accent = GREEN_ACCENT if added_clans else GOLD_ACCENT
    components = build_clan_menu(member, clans, action_id, accent, success_text, bot)
    
    await ctx.interaction.edit_initial_response(components=components)


@register_action("remove_all_clans", no_return=True)
@lightbulb.di.with_di
async def remove_all_clans_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Remove all clan roles from member"""
    
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return
    
    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    if not member:
        await ctx.respond("Member not found", ephemeral=True)
        return
    
    # Get all clans
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]
    
    # Get all clan role IDs from the database
    clan_role_ids = {clan.role_id for clan in clans if clan.role_id}
    
    # Calculate which roles to keep (all non-clan roles, excluding @everyone)
    current_roles = member.role_ids
    roles_to_keep = [role_id for role_id in current_roles if role_id not in clan_role_ids and role_id != ctx.interaction.guild_id]
    
    # Track which clan roles were actually removed
    removed_roles = []
    for clan in clans:
        if clan.role_id and clan.role_id in current_roles:
            # Only add emoji if clan has a valid one
            if clan.partial_emoji:
                try:
                    str(clan.partial_emoji)
                    removed_roles.append(f"{clan.partial_emoji} {clan.name}")
                except Exception:
                    # If emoji is invalid, just show name
                    removed_roles.append(clan.name)
            else:
                # No emoji, just show name
                removed_roles.append(clan.name)
    
    # Batch update all roles at once
    if removed_roles:
        try:
            await member.edit(roles=roles_to_keep, reason="Remove all clan roles via dashboard")
        except Exception:
            # If batch fails, we won't show any as removed
            removed_roles = []
    
    # Create success message without the heading
    if removed_roles:
        success_text = f"**Removed:** {', '.join(removed_roles)}"
    else:
        success_text = "No clan roles to remove."
    
    # Refresh member and update menu
    member = guild.get_member(user_id)
    components = build_clan_menu(member, clans, action_id, GREEN_ACCENT, success_text, bot)
    
    await ctx.interaction.edit_initial_response(components=components)