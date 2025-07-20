# extensions/commands/recruit/dashboard/set_townhall.py
"""
Handle the Set Townhall Role(s) action from the recruit dashboard
"""

import lightbulb
import hikari

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


@register_action("set_townhall")
@lightbulb.di.with_di
async def set_townhall_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display townhall role selection interface"""

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

    # Check current TH roles
    member_role_ids = set(member.role_ids)
    current_th_roles = []

    for th_config in TH_LEVELS:
        if th_config["role_id"] in member_role_ids:
            current_th_roles.append(f"{th_config['emoji'].mention} TH{th_config['level']}")

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

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## 🏰 **Set Townhall Roles for {member.display_name}**"),
                Separator(divider=True),

                # Current TH roles
                Text(content="### Current Townhall Roles:"),
                Text(content="\n".join(current_th_roles) if current_th_roles else "_No townhall roles assigned_"),

                Separator(divider=True),

                # Instructions
                Text(content=(
                    "**Instructions:**\n"
                    "• Select one or more townhall levels from the dropdown\n"
                    "• This will remove any existing TH roles and add the selected ones\n"
                    "• Members can have multiple TH roles if they have multiple accounts"
                )),

                Separator(divider=True),

                # Select menu
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


@register_action("execute_set_th")
@lightbulb.di.with_di
async def execute_set_th_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute townhall role assignment"""

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

    # Parse selected values
    selected_values = ctx.interaction.values
    selected_roles = []

    for value in selected_values:
        th_level, role_id = value.split(":")
        role_id = int(role_id)
        selected_roles.append((th_level, role_id))

    # Remove all existing TH roles first
    removed_roles = []
    for th_config in TH_LEVELS:
        role_id = th_config["role_id"]
        if role_id in member.role_ids:
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.remove_role(role, reason="Townhall role update via dashboard")
                    removed_roles.append(f"{th_config['emoji'].mention} TH{th_config['level']}")
                except Exception:
                    pass

    # Add selected roles
    added_roles = []
    failed_roles = []

    for th_level, role_id in selected_roles:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_role(role, reason="Townhall role update via dashboard")
                # Find the emoji for this TH level
                th_num = int(th_level.replace("th", ""))
                emoji = next((th["emoji"] for th in TH_LEVELS if th["level"] == th_num), None)
                if emoji:
                    added_roles.append(f"{emoji.mention} TH{th_num}")
                else:
                    added_roles.append(f"TH{th_num}")
            except Exception:
                failed_roles.append(f"TH{th_level}")

    # Build response
    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ✅ **Townhall Roles Updated!**"),
                Separator(divider=True),
            ]
        )
    ]

    if removed_roles:
        components[0].components.extend([
            Text(content="**Removed Roles:**"),
            Text(content="\n".join(removed_roles)),
            Separator(divider=True),
        ])

    if added_roles:
        components[0].components.extend([
            Text(content="**Added Roles:**"),
            Text(content="\n".join(added_roles)),
        ])

    if failed_roles:
        components[0].components.extend([
            Separator(divider=True),
            Text(content="**Failed to Add:**"),
            Text(content="\n".join(failed_roles)),
        ])

    components[0].components.extend([
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"set_townhall:{action_id}",
                    label="Manage TH Roles",
                    emoji="🏰"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"refresh_dashboard:{action_id}",
                    label="Back to Dashboard",
                    emoji="↩️"
                )
            ]
        ),
        Media(items=[MediaItem(media="assets/Green_Footer.png")])
    ])

    return components


@register_action("remove_all_th")
@lightbulb.di.with_di
async def remove_all_th_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Remove all townhall roles from member"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Remove all TH roles
    removed_roles = []

    for th_config in TH_LEVELS:
        role_id = th_config["role_id"]
        if role_id in member.role_ids:
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.remove_role(role, reason="Remove all TH roles via dashboard")
                    removed_roles.append(f"{th_config['emoji'].mention} TH{th_config['level']}")
                except Exception:
                    pass

    if removed_roles:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## 🗑️ **All Townhall Roles Removed**"),
                    Separator(divider=True),
                    Text(content="**Removed Roles:**"),
                    Text(content="\n".join(removed_roles)),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                custom_id=f"set_townhall:{action_id}",
                                label="Set TH Roles",
                                emoji="🏰"
                            ),
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
    else:
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## ℹ️ **No Townhall Roles Found**"),
                    Text(content="This member doesn't have any townhall roles to remove."),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                custom_id=f"set_townhall:{action_id}",
                                label="Back to TH Management",
                                emoji="↩️"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")])
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