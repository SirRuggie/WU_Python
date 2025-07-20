# extensions/commands/recruit/dashboard/manage_roles.py
"""
Handle the Add/Remove Needed Roles action from the recruit dashboard
"""

import lightbulb
import hikari

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
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
)

# Define standard roles that should be managed for recruits
STANDARD_ROLES = {
    "member": {
        "name": "Kings Alliance",
        "id": 901627019190657024,  # You'll need to update with actual role IDs
        "emoji": "👑",
        "description": "Main alliance membership role"
    },
    "recruit": {
        "name": "New Recruit",
        "id": 901627019190657025,  # Update with actual ID
        "emoji": "🆕",
        "description": "Temporary role for new members"
    },
    "notifications": {
        "name": "Clan Notifications",
        "id": 901627019190657026,  # Update with actual ID
        "emoji": "🔔",
        "description": "Receive clan announcements"
    },
    "war": {
        "name": "War Participant",
        "id": 901627019190657027,  # Update with actual ID
        "emoji": "⚔️",
        "description": "Participates in clan wars"
    }
}


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

    # Build role options for the select menu
    options = []
    current_roles = []
    available_roles = []

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id) if guild else None

        if role:
            option = SelectOption(
                label=role_info["name"],
                value=f"{role_key}:{role_id}",
                description=role_info["description"],
                emoji=role_info["emoji"]
            )

            if role_id in member_role_ids:
                current_roles.append(f"{role_info['emoji']} {role_info['name']}")
            else:
                available_roles.append(f"{role_info['emoji']} {role_info['name']}")

            options.append(option)

    # Build the interface
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## 👤 **Manage Roles for {member.display_name}**"),
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
                            emoji="➕",
                            is_disabled=len(available_roles) == 0
                        ),
                        Button(
                            style=hikari.ButtonStyle.DANGER,
                            custom_id=f"remove_roles:{action_id}",
                            label="Remove Roles",
                            emoji="➖",
                            is_disabled=len(current_roles) == 0
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
            ]
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
    """Show role addition interface"""

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

    # Build available roles for selection
    member_role_ids = set(member.role_ids)
    options = []

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        if role_id not in member_role_ids:
            role = guild.get_role(role_id)
            if role:
                options.append(
                    SelectOption(
                        label=role_info["name"],
                        value=f"{role_key}:{role_id}",
                        description=role_info["description"],
                        emoji=role_info["emoji"]
                    )
                )

    if not options:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **All Roles Assigned**"),
                    Text(content="This member already has all standard roles."),
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

    return [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ➕ **Add Roles**"),
                Text(content="Select roles to add to the member:"),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"execute_add_roles:{action_id}",
                            placeholder="Select roles to add...",
                            min_values=1,
                            max_values=len(options),
                            options=options
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
    """Show role removal interface"""

    # Similar to add_roles but for removing
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Build current roles for selection
    member_role_ids = set(member.role_ids)
    options = []

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        if role_id in member_role_ids:
            role = guild.get_role(role_id)
            if role:
                options.append(
                    SelectOption(
                        label=role_info["name"],
                        value=f"{role_key}:{role_id}",
                        description=role_info["description"],
                        emoji=role_info["emoji"]
                    )
                )

    if not options:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **No Roles to Remove**"),
                    Text(content="This member doesn't have any standard roles."),
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

    return [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ➖ **Remove Roles**"),
                Text(content="Select roles to remove from the member:"),
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
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]


@register_action("quick_setup")
@lightbulb.di.with_di
async def quick_setup_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Quick setup - adds all standard recruit roles at once"""

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

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id)

        if role and role_id not in member.role_ids:
            try:
                await member.add_role(role, reason="Recruit dashboard quick setup")
                added_roles.append(f"{role_info['emoji']} {role_info['name']}")
            except Exception:
                failed_roles.append(f"{role_info['emoji']} {role_info['name']}")

    # Build response
    if added_roles:
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ **Quick Setup Complete!**"),
                    Separator(divider=True),
                    Text(content="**Added Roles:**"),
                    Text(content="\n".join(added_roles)),
                ]
            )
        ]

        if failed_roles:
            components[0].components.extend([
                Separator(divider=True),
                Text(content="**Failed to Add:**"),
                Text(content="\n".join(failed_roles))
            ])

        components[0].components.extend([
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
            Media(items=[MediaItem(media="assets/Green_Footer.png")])
        ])
    else:
        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **No Changes Made**"),
                    Text(content="Member already has all standard roles."),
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

    return components


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