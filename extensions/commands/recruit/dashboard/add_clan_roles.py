# extensions/commands/recruit/dashboard/add_clan_roles.py
"""
Handle the Add ALL Clan Roles to Recruit action from the recruit dashboard
"""

import lightbulb
import hikari

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


@register_action("add_clan_roles")
@lightbulb.di.with_di
async def add_clan_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display clan selection interface for adding clan roles"""

    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Fetch all clans from database
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]

    if not clans:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ **No Clans Found**"),
                    Text(content="No clans are configured in the database."),
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

    # Check which clan roles the member already has
    member_role_ids = set(member.role_ids)
    member_clans = []
    available_clans = []

    for clan in clans:
        if clan.role_id and clan.role_id in member_role_ids:
            member_clans.append(f"{clan.partial_emoji if clan.partial_emoji else '🏛️'} {clan.name}")
        else:
            available_clans.append(clan)

    # Build select menu options
    options = []
    for clan in available_clans:
        if clan.role_id:  # Only show clans with configured roles
            kwargs = {
                "label": clan.name,
                "value": f"{clan.tag}:{clan.role_id}",
                "description": f"Tag: {clan.tag}"
            }
            if clan.partial_emoji:
                kwargs["emoji"] = clan.partial_emoji
            options.append(SelectOption(**kwargs))

    if not options:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **All Clan Roles Assigned**"),
                    Text(content=(
                        f"This member already has all available clan roles:\n\n"
                        f"{chr(10).join(member_clans)}"
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
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## ⚔️ **Add Clan Roles to {member.display_name}**"),
                Separator(divider=True),

                # Current clan roles
                Text(content="### Current Clan Memberships:"),
                Text(content="\n".join(member_clans) if member_clans else "_No clan roles assigned_"),

                Separator(divider=True),

                # Instructions
                Text(content=(
                    "**Select clans to add:**\n"
                    "• You can select multiple clans at once\n"
                    "• This will add the main clan role\n"
                    "• Additional roles (leader, co-leader) must be added separately"
                )),

                # Select menu
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

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"add_all_clans:{action_id}",
                            label="Add ALL Clans",
                            emoji="🌟",
                            is_disabled=len(options) == 0
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


@register_action("execute_add_clans")
@lightbulb.di.with_di
async def execute_add_clans_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute adding selected clan roles"""

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
    added_clans = []
    failed_clans = []

    for value in selected_values:
        clan_tag, role_id = value.split(":")
        role_id = int(role_id)

        # Get clan info
        clan_data = await mongo.clans.find_one({"tag": clan_tag})
        if clan_data:
            clan = Clan(data=clan_data)
            role = guild.get_role(role_id)

            if role:
                try:
                    await member.add_role(role, reason="Clan role added via recruit dashboard")
                    added_clans.append(f"{clan.partial_emoji if clan.partial_emoji else '🏛️'} {clan.name}")
                except Exception:
                    failed_clans.append(f"{clan.name}")

    # Build response
    components = [
        Container(
            accent_color=GREEN_ACCENT if added_clans else RED_ACCENT,
            components=[
                Text(content="## ✅ **Clan Roles Updated!**" if added_clans else "## ❌ **Failed to Add Roles**"),
                Separator(divider=True),
            ]
        )
    ]

    if added_clans:
        components[0].components.extend([
            Text(content="**Successfully Added:**"),
            Text(content="\n".join(added_clans)),
        ])

    if failed_clans:
        components[0].components.extend([
            Separator(divider=True) if added_clans else Text(content=""),
            Text(content="**Failed to Add:**"),
            Text(content="\n".join(failed_clans)),
        ])

    components[0].components.extend([
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"add_clan_roles:{action_id}",
                    label="Manage Clan Roles",
                    emoji="⚔️"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"refresh_dashboard:{action_id}",
                    label="Back to Dashboard",
                    emoji="↩️"
                )
            ]
        ),
        Media(items=[MediaItem(media="assets/Green_Footer.png" if added_clans else "assets/Red_Footer.png")])
    ])

    return components


@register_action("add_all_clans")
@lightbulb.di.with_di
async def add_all_clans_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Add all available clan roles at once"""

    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None

    if not member:
        return [error_response("Member not found", action_id)]

    # Get all clans
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=d) for d in clan_data]

    member_role_ids = set(member.role_ids)
    added_clans = []
    failed_clans = []
    already_had = []

    for clan in clans:
        if not clan.role_id:
            continue

        if clan.role_id in member_role_ids:
            already_had.append(f"{clan.partial_emoji if clan.partial_emoji else '🏛️'} {clan.name}")
            continue

        role = guild.get_role(clan.role_id)
        if role:
            try:
                await member.add_role(role, reason="All clan roles added via recruit dashboard")
                added_clans.append(f"{clan.partial_emoji if clan.partial_emoji else '🏛️'} {clan.name}")
            except Exception:
                failed_clans.append(clan.name)

    # Build response
    if added_clans:
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## 🌟 **All Clan Roles Added!**"),
                    Separator(divider=True),
                    Text(content="**Successfully Added:**"),
                    Text(content="\n".join(added_clans)),
                ]
            )
        ]

        if already_had:
            components[0].components.extend([
                Separator(divider=True),
                Text(content="**Already Had:**"),
                Text(content="\n".join(already_had)),
            ])

        if failed_clans:
            components[0].components.extend([
                Separator(divider=True),
                Text(content="**Failed to Add:**"),
                Text(content="\n".join(failed_clans)),
            ])
    else:
        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **No New Roles Added**"),
                    Text(content="Member already has all available clan roles."),
                ]
            )
        ]

    components[0].components.extend([
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
        Media(items=[MediaItem(media="assets/Green_Footer.png" if added_clans else "assets/Gold_Footer.png")])
    ])

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