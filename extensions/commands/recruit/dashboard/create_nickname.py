# extensions/commands/recruit/dashboard/create_nickname.py
"""
Handle the Create Server Nickname action from the recruit dashboard
"""

import lightbulb
import hikari
import re

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
    ModalActionRowBuilder as ModalActionRow,
)


@register_action("create_nickname", opens_modal=True)
async def create_nickname_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        **kwargs
):
    """Open modal for creating server nickname"""

    # Create modal inputs
    ign_input = ModalActionRow().add_text_input(
        "ign",
        "In-Game Name (IGN)",
        placeholder="Enter the recruit's in-game name",
        min_length=1,
        max_length=20,
        required=True
    )

    timezone_input = ModalActionRow().add_text_input(
        "timezone",
        "Time Zone",
        placeholder="e.g., EST, PST, GMT+5",
        min_length=2,
        max_length=10,
        required=True
    )

    country_input = ModalActionRow().add_text_input(
        "country",
        "Country Flag Emoji",
        placeholder="e.g., 🇺🇸 or US",
        min_length=1,
        max_length=10,
        required=True
    )

    await ctx.respond_with_modal(
        title="Create Server Nickname",
        custom_id=f"nickname_modal:{action_id}",
        components=[ign_input, timezone_input, country_input]
    )


@register_action("nickname_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def nickname_modal_handler(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Process the nickname creation modal submission"""

    # Helper to get modal values
    def get_val(custom_id: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == custom_id:
                    return comp.value
        return ""

    ign = get_val("ign")
    timezone = get_val("timezone").upper()
    country = get_val("country")

    # Process country flag - convert country code to flag emoji if needed
    if len(country) == 2 and country.isalpha():
        # Convert country code to flag emoji
        country = country.upper()
        country_flag = chr(ord(country[0]) + 127397) + chr(ord(country[1]) + 127397)
    else:
        # Assume it's already a flag emoji
        country_flag = country.strip()

    # Get the recruit data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        return await ctx.respond("❌ Session expired. Please run the dashboard command again.", ephemeral=True)

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    # Construct the new nickname
    new_nickname = f"{ign} | {timezone} {country_flag}"

    # Defer the response for processing
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    try:
        # Get the member and update their nickname
        guild = bot.cache.get_guild(guild_id)
        member = guild.get_member(user_id)

        if member:
            # Store old nickname before changing
            old_nickname = member.nickname if member.nickname else member.username

            # Check if member is server owner
            if member.id == guild.owner_id:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content="## ❌ **Cannot Modify Server Owner**"),
                            Text(content=(
                                "I cannot change the nickname of the server owner.\n"
                                "Server owners must change their own nicknames."
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
                            Media(items=[MediaItem(media="assets/Red_Footer.png")])
                        ]
                    )
                ]
                await ctx.interaction.edit_initial_response(components=components)
                return

            # Debug: Log the attempt
            print(f"[DEBUG] Attempting to change nickname for {member.username} (ID: {member.id}) to '{new_nickname}'")
            print(f"[DEBUG] Member is server owner: {member.id == guild.owner_id}")

            await member.edit(nickname=new_nickname, reason="Recruit dashboard nickname update")

            # Success response
            components = [
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content="## ✅ **Nickname Updated Successfully!**"),
                        Separator(divider=True),
                        Text(content=f"**Old Nickname:** {old_nickname}"),
                        Text(content=f"**New Nickname:** {new_nickname}"),
                        Separator(divider=True),
                        Text(content=(
                            f"• **IGN:** {ign}\n"
                            f"• **Time Zone:** {timezone}\n"
                            f"• **Country:** {country_flag}"
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
        else:
            # Error - member not found
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ **Error: Member Not Found**"),
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

    except hikari.ForbiddenError as e:
        # Log the actual error
        print(f"[ERROR] ForbiddenError when changing nickname: {e}")
        print(f"[ERROR] User ID: {user_id}, Guild ID: {guild_id}")

        # Bot lacks permissions - show a clear error message
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ **Permission Error**"),
                    Text(content=(
                        "I don't have permission to change this member's nickname.\n\n"
                        "**Possible reasons:**\n"
                        "• The member has a role higher than mine in the role hierarchy\n"
                        "• The member has Administrator permissions\n"
                        "• The member is the server owner\n"
                        "• I don't have the `Manage Nicknames` permission\n\n"
                        "**Solution:** Please ensure:\n"
                        "• My role is placed higher than the member's roles in Server Settings\n"
                        "• I have the `Manage Nicknames` permission"
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
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
    except Exception as e:
        # General error
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ **An Error Occurred**"),
                    Text(content=f"Error: {str(e)[:200]}"),
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

    # Send the response
    await ctx.interaction.edit_initial_response(components=components)