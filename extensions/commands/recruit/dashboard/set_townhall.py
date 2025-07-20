"""
Handle the Set Townhall Role(s) action from the recruit dashboard.

This uses a single-message flow where the dashboard is edited to show the TH menu,
and then the TH menu can be edited back to show the dashboard.
"""

import lightbulb
import hikari
from typing import List, Optional, Tuple

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT
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

# Town Hall configuration
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


def build_th_menu(
    member: hikari.Member,
    action_id: str,
    accent_color: int = BLUE_ACCENT,
    success_message: Optional[str] = None
) -> List[Container]:
    """Build the TH selection menu with current state"""

    # Check current TH roles
    member_role_ids = set(member.role_ids)
    current_th_roles = []

    for th_config in TH_LEVELS:
        if th_config["role_id"] in member_role_ids:
            current_th_roles.append(f"{th_config['emoji']} TH{th_config['level']}")

    # Build select menu options
    options = []
    for th_config in TH_LEVELS:
        options.append(
            SelectOption(
                emoji=th_config["emoji"].partial_emoji,
                label=f"TH{th_config['level']}",
                value=f"th{th_config['level']}:{th_config['role_id']}",
                description=f"Town Hall {th_config['level']}"
            )
        )

    # Build component list
    component_list = [
        Text(content=f"## 🏰 **Set Townhall Roles for {member.display_name}**"),
        Separator(divider=True),
    ]

    # Add success message if provided
    if success_message:
        component_list.extend([
            Text(content=success_message),
            Separator(divider=True),
        ])

    # Add current roles section
    component_list.extend([
        Text(content="### Current Townhall Roles:"),
        Text(content="\n".join(current_th_roles) if current_th_roles else "_No townhall roles assigned_"),
        Separator(divider=True),
        Text(content=(
            "**Instructions:**\n"
            "• Select one or more townhall levels from the dropdown\n"
            "• This will remove any existing TH roles and add the selected ones\n"
            "• Members can have multiple TH roles if they have multiple accounts"
        )),
        Separator(divider=True),
    ])

    # Add interactive elements
    component_list.extend([
        ActionRow(
            components=[
                TextSelectMenu(
                    custom_id=f"execute_set_th:{action_id}",
                    placeholder="Select townhall level(s)...",
                    min_values=1,
                    max_values=len(options),
                    options=options
                )
            ]
        ),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"remove_all_th:{action_id}",
                    label="Remove All TH Roles",
                    emoji="🗑️",
                    is_disabled=len(current_th_roles) == 0
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"back_to_dashboard:{action_id}",
                    label="Back to Dashboard",
                    emoji="↩️"
                )
            ]
        ),
        Media(items=[MediaItem(media=f"assets/{accent_color == GREEN_ACCENT and 'Green' or accent_color == RED_ACCENT and 'Red' or 'Blue'}_Footer.png")])
    ])

    return [Container(accent_color=accent_color, components=component_list)]


@register_action("set_townhall", no_return=True)
@lightbulb.di.with_di
async def set_townhall_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Display townhall role selection interface"""

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

    components = build_th_menu(member, action_id)
    # Edit the existing dashboard message instead of creating a new one
    await ctx.interaction.edit_initial_response(components=components)


@register_action("execute_set_th", no_return=True)
@lightbulb.di.with_di
async def execute_set_th_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Execute townhall role assignment"""

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

    # Parse selected values
    selected_values = ctx.interaction.values
    selected_role_ids = set()

    for value in selected_values:
        th_level, role_id = value.split(":")
        selected_role_ids.add(int(role_id))

    # Get current TH roles
    current_th_role_ids = set()
    for th_config in TH_LEVELS:
        if th_config["role_id"] in member.role_ids:
            current_th_role_ids.add(th_config["role_id"])

    # Calculate what needs to be removed and added
    roles_to_remove = current_th_role_ids - selected_role_ids
    roles_to_add = selected_role_ids - current_th_role_ids

    # Remove roles that are no longer selected
    removed_roles = []
    for th_config in TH_LEVELS:
        role_id = th_config["role_id"]
        if role_id in roles_to_remove:
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.remove_role(role, reason="Townhall role update via dashboard")
                    removed_roles.append(f"{th_config['emoji']} TH{th_config['level']}")
                except Exception:
                    pass

    # Add newly selected roles
    added_roles = []
    failed_roles = []

    for th_config in TH_LEVELS:
        role_id = th_config["role_id"]
        if role_id in roles_to_add:
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.add_role(role, reason="Townhall role update via dashboard")
                    added_roles.append(f"{th_config['emoji']} TH{th_config['level']}")
                except Exception:
                    failed_roles.append(f"{th_config['emoji']} TH{th_config['level']}")

    # Create success message
    success_text = "### ✅ Townhall Roles Updated!"
    if removed_roles:
        success_text += f"\n**Removed:** {', '.join(removed_roles)}"
    if added_roles:
        success_text += f"\n**Added:** {', '.join(added_roles)}"
    if failed_roles:
        success_text += f"\n**Failed:** {', '.join(failed_roles)}"
    if not removed_roles and not added_roles:
        success_text = "### ✅ No Changes Made\nThe selected roles were already assigned."

    # Refresh member data and update menu
    member = guild.get_member(user_id)
    components = build_th_menu(member, action_id, GREEN_ACCENT, success_text)

    await ctx.interaction.edit_initial_response(components=components)


@register_action("remove_all_th", no_return=True)
@lightbulb.di.with_di
async def remove_all_th_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Remove all townhall roles from member"""

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

    # Remove all TH roles
    removed_roles = []

    for th_config in TH_LEVELS:
        role_id = th_config["role_id"]
        if role_id in member.role_ids:
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.remove_role(role, reason="Remove all TH roles via dashboard")
                    removed_roles.append(f"{th_config['emoji']} TH{th_config['level']}")
                except Exception:
                    pass

    # Create success message
    success_text = f"### ✅ All Townhall Roles Removed!"
    if removed_roles:
        success_text += f"\n**Removed:** {', '.join(removed_roles)}"

    # Refresh member and update menu
    member = guild.get_member(user_id)
    components = build_th_menu(member, action_id, GREEN_ACCENT, success_text)

    await ctx.interaction.edit_initial_response(components=components)


@register_action("back_to_dashboard", no_return=True)
@lightbulb.di.with_di
async def back_to_dashboard_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to the recruit dashboard"""

    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("Session expired", ephemeral=True)
        return

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    # Create a fresh dashboard
    from .dashboard import create_dashboard_page

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    user = bot.cache.get_user(user_id)
    recruiter = guild.get_member(data.get("recruiter_id")) if guild else None

    dashboard_components = await create_dashboard_page(
        action_id=action_id,
        user=user,
        member=member,
        recruiter=recruiter,
        bot=bot,
        mongo=mongo,
        guild_id=guild_id,
        channel_id=data.get("channel_id"),
        recruiter_id=data.get("recruiter_id")
    )

    # Update the message with the dashboard
    await ctx.interaction.edit_initial_response(components=dashboard_components)