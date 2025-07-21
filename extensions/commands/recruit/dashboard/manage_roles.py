# extensions/commands/recruit/dashboard/manage_roles.py
"""
Handle the Add/Remove Needed Roles action from the recruit dashboard
"""

import lightbulb
import hikari
import asyncio

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT, GOLD_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SelectMenuBuilder as SelectMenu,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
)

# Define standard roles that should be managed for recruits
STANDARD_ROLES = {
    "family": {
        "name": "Family",
        "id": 1003749467863924806,
        "emoji": "👨‍👩‍👧‍👦",
        "description": "Part of the Warrior family"
    },
    "recruit": {
        "name": "New Recruit",
        "id": 779277305671319572,
        "emoji": "🆕",
        "description": "New member being onboarded"
    },
    "strike_accepted": {
        "name": "Strike System Accepted",
        "id": 1003797283348946944,
        "emoji": "✅",
        "description": "Has accepted the strike system rules"
    }
}

# Role to remove during quick setup
VISITOR_ROLE_ID = 1003796476750745751


@register_action("manage_roles")
@lightbulb.di.with_di
async def manage_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display role management interface"""

    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    
    # Get feedback messages from kwargs
    added_roles = kwargs.get("added_roles", [])
    removed_roles = kwargs.get("removed_roles", [])

    if not member:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ **Member Not Found**"),
                    Text(content="Could not find the member in this server."),
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
        ]

    # Get member's current roles
    member_role_ids = set(member.role_ids)

    # Build role lists for display
    current_roles = []
    available_roles = []

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id) if guild else None

        if role:
            if role_id in member_role_ids:
                current_roles.append(f"{role_info['emoji']} {role_info['name']}")
            else:
                available_roles.append(f"{role_info['emoji']} {role_info['name']}")

    # Build components list
    container_components = [
        Text(content=f"## 👤 **Manage Roles for {member.display_name}**"),
    ]
    
    # Add feedback messages if any
    if added_roles or removed_roles:
        feedback_parts = []
        if added_roles:
            feedback_parts.append(f"**✅ Added:** {', '.join(added_roles)}")
        if removed_roles:
            feedback_parts.append(f"**❌ Removed:** {', '.join(removed_roles)}")
        
        container_components.extend([
            Separator(divider=True),
            Text(content="\n".join(feedback_parts)),
        ])
    
    container_components.extend([
        Separator(divider=True),

        # Current roles display
        Text(content="### ✅ Current Roles:"),
        Text(content="\n".join(current_roles) if current_roles else "_No standard roles assigned_"),

        Separator(divider=True),

        # Available roles display
        Text(content="### 📋 Available Roles:"),
        Text(content="\n".join(available_roles) if available_roles else "_All standard roles assigned_"),

        Separator(divider=True),

        # Action buttons
        Text(content="**Choose an action:**"),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"add_roles:{action_id}",
                    label="Add Roles",
                    emoji="➕"
                ),
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"remove_roles:{action_id}",
                    label="Remove Roles",
                    emoji="➖",
                    is_disabled=len(member_role_ids) <= 1  # Only @everyone role
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"quick_setup:{action_id}",
                    label="Quick Setup",
                    emoji="⚡"
                ),
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

        Media(items=[MediaItem(media="assets/Blue_Footer.png")])
    ])
    
    # Build the interface
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=container_components
        )
    ]

    return components


@register_action("add_roles")
@lightbulb.di.with_di
async def add_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Show role addition interface with native role select menu"""

    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    return [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ➕ **Add Roles**"),
                Text(content="Select roles to add to the member:"),
                Text(content="-# You can search for roles by typing their name"),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.ROLE_SELECT_MENU,
                            custom_id=f"execute_add_roles:{action_id}",
                            placeholder="Select roles to add...",
                            min_values=1,
                            max_values=25,  # Discord's maximum
                        )
                    ]
                ),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"manage_roles:{action_id}",
                            label="Cancel",
                            emoji="❌"
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]


@register_action("remove_roles")
@lightbulb.di.with_di
async def remove_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Show role removal interface with paginated role list"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    page = kwargs.get("page", 0)  # Get current page from kwargs

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Build list of removable roles
    removable_roles = []
    member_roles = sorted(
        [guild.get_role(role_id) for role_id in member.role_ids if guild.get_role(role_id)],
        key=lambda r: r.position,
        reverse=True
    )
    
    for role in member_roles:
        # Skip @everyone role and managed roles (bot roles)
        if role.id == guild_id or role.is_managed:
            continue
        removable_roles.append(role)

    if not removable_roles:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **No Roles to Remove**"),
                    Text(content="This member doesn't have any removable roles."),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"manage_roles:{action_id}",
                                label="Back to Role Management",
                                emoji="↩️"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]

    # Pagination logic
    roles_per_page = 25
    total_pages = (len(removable_roles) + roles_per_page - 1) // roles_per_page
    page = max(0, min(page, total_pages - 1))  # Ensure page is within bounds
    
    start_idx = page * roles_per_page
    end_idx = start_idx + roles_per_page
    page_roles = removable_roles[start_idx:end_idx]
    
    # Build options for the current page
    options = []
    for role in page_roles:
        options.append(
            SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=f"Position: {role.position}",
                emoji="🏷️"
            )
        )

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ➖ **Remove Roles**"),
                Text(content="Select roles to remove from the member:"),
                Text(content=f"-# Page {page + 1} of {total_pages} • Showing {len(page_roles)} of {len(removable_roles)} roles"),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"execute_remove_roles:{action_id}",
                            placeholder="Select roles to remove...",
                            min_values=1,
                            max_values=len(options),
                            options=options
                        )
                    ]
                ),
            ]
        )
    ]
    
    # Add navigation buttons if there are multiple pages
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"remove_roles_page:{action_id}:{page-1}",
                label="Previous",
                emoji="◀️"
            )
        )
    
    nav_buttons.append(
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"manage_roles:{action_id}",
            label="Cancel",
            emoji="❌"
        )
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"remove_roles_page:{action_id}:{page+1}",
                label="Next",
                emoji="▶️"
            )
        )
    
    components[0].components.extend([
        ActionRow(components=nav_buttons),
        Media(items=[MediaItem(media="assets/Red_Footer.png")])
    ])

    return components


@register_action("quick_setup")
@lightbulb.di.with_di
async def quick_setup_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Quick setup - adds standard recruit roles and removes visitor role"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Add all standard roles
    added_roles = []
    failed_roles = []
    removed_roles = []

    # Add standard roles
    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id)

        if role and role_id not in member.role_ids:
            try:
                await member.add_role(role, reason="Recruit dashboard quick setup")
                added_roles.append(role_info['name'])
            except Exception:
                failed_roles.append(role_info['name'])
    
    # Remove visitor role if they have it
    visitor_role = guild.get_role(VISITOR_ROLE_ID)
    if visitor_role and VISITOR_ROLE_ID in member.role_ids:
        try:
            await member.remove_role(visitor_role, reason="Recruit dashboard quick setup - removing visitor role")
            removed_roles.append(visitor_role.name)
        except Exception:
            failed_roles.append(f"Failed to remove: {visitor_role.name}")
    
    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)

    # Refresh the manage roles view to show updated roles
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        added_roles=added_roles,
        removed_roles=removed_roles
    )


@register_action("execute_add_roles")
@lightbulb.di.with_di
async def execute_add_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute the role addition and refresh the manage roles view"""
    
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Get selected role IDs from the interaction
    selected_values = ctx.interaction.values
    added_roles = []

    for role_id in selected_values:
        # Role select menu provides role IDs as integers already
        role = guild.get_role(role_id)
        
        if role and role_id not in member.role_ids:
            try:
                await member.add_role(role, reason=f"Added via recruit dashboard by {ctx.user.username}")
                added_roles.append(role.name)
            except Exception:
                pass  # Silently handle errors

    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)
    
    # Refresh the manage roles view
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        added_roles=added_roles
    )


@register_action("execute_remove_roles")
@lightbulb.di.with_di
async def execute_remove_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute the role removal and refresh the manage roles view"""
    
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Get selected role IDs from the interaction
    selected_values = ctx.interaction.values
    removed_roles = []

    for role_id_str in selected_values:
        # TextSelectMenu provides role IDs as strings
        role_id = int(role_id_str)
        role = guild.get_role(role_id)
        
        if role and role_id in member.role_ids:
            try:
                await member.remove_role(role, reason=f"Removed via recruit dashboard by {ctx.user.username}")
                removed_roles.append(role.name)
            except Exception:
                pass  # Silently handle errors

    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)
    
    # Refresh the manage roles view
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        removed_roles=removed_roles
    )


@register_action("remove_roles_page")
@lightbulb.di.with_di
async def remove_roles_page_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Handle pagination for remove roles"""
    
    # Extract the page number from the custom_id
    # Format: remove_roles_page:action_id:page_number
    parts = ctx.interaction.custom_id.split(":")
    page = int(parts[2])
    
    # Get the stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]
    
    # Call remove_roles_handler with the page parameter
    return await remove_roles_handler(
        ctx=ctx,
        action_id=action_id,
        mongo=mongo,
        bot=bot,
        page=page,
        **data
    )


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