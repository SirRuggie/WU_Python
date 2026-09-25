# extensions/commands/clan/dashboard/fwa_data.py
"""
Modern FWA data management system for updating base links and images.
Provides a streamlined interface for managing FWA base configurations.
"""

import lightbulb
import hikari
import re
from typing import Dict, List, Optional, Tuple
import asyncio

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.manage_ui import breadcrumb, button_emoji
from utils.media_store import FWA_ACTIVE_BASE_NAME, FWA_WAR_BASE_NAME, MediaStore, fwa_base_folder
from utils.media_urls import DETAIL, optimized
from utils.constants import RED_ACCENT, GREEN_ACCENT, BLUE_ACCENT, GOLDENROD_ACCENT, FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
from utils.emoji import emojis
from extensions.commands.clan.dashboard.dashboard import dashboard_page
from extensions.commands.clan.dashboard.permissions import require_dashboard_role

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ModalActionRowBuilder as ModalActionRow,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
)

FWA_REP_ROLE_ID = 993015846442127420
def _management_token(ctx) -> str | None:
    interaction = getattr(ctx, "interaction", None)
    message = getattr(interaction, "message", None)
    for container in getattr(message, "components", ()):
        for row in getattr(container, "components", ()):
            for button in getattr(row, "components", ()):
                custom_id = getattr(button, "custom_id", "") or ""
                if custom_id.startswith(("manage_fwa:", "manage_home:")):
                    return custom_id.partition(":")[2]
    return None


def _return_to_th_id(ctx, th_level: str) -> str:
    token = _management_token(ctx)
    return f"fwa_th_select_return:{th_level}" + (f"|{token}" if token else "")


def _return_to_fwa_id(ctx) -> str:
    return f"fwa_back_to_main:{_management_token(ctx) or 'main'}"


def _home_button(ctx) -> list[Button]:
    token = _management_token(ctx)
    return [Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_fwa:{token}",
                   label="Back to FWA", emoji=button_emoji("Back to FWA")),
            Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_home:{token}",
                   label="Management Home", emoji=button_emoji("Management Home"))] if token else []


async def _require_fwa_representative(ctx) -> bool:
    """Recheck the existing FWA Representative role on persistent controls."""
    return await require_dashboard_role(ctx, FWA_REP_ROLE_ID, "FWA Representative")

# TH levels we support for FWA (ordered from highest to lowest)
FWA_TH_LEVELS = ["th18_new", "th18", "th17_new", "th17", "th16_new", "th16", "th15", "th14", "th13", "th12", "th11", "th10", "th9"]

def get_th_emoji(th_level: str):
    """Get the appropriate TH emoji object"""
    # Handle _new variants by removing the suffix
    clean_th_level = th_level.replace("_new", "")
    th_num = clean_th_level.upper().replace("TH", "")
    emoji_attr = f"TH{th_num}"
    if hasattr(emojis, emoji_attr):
        return getattr(emojis, emoji_attr)
    return None


def validate_clash_link(link: str) -> bool:
    """Validate if a link is a valid Clash of Clans link"""
    # Simple validation - just check if it's a clash of clans link
    return link.startswith("https://link.clashofclans.com/")


def validate_image_url(url: str) -> bool:
    """Validate if a URL is a valid image URL"""
    pattern = r'^https?://.*\.(?:png|jpe?g|gif|webp)'
    return bool(re.match(pattern, url, re.IGNORECASE))


async def get_fwa_data(mongo: MongoClient) -> Dict:
    """Get current FWA data from MongoDB"""
    fwa_data = await mongo.fwa_data.find_one({"_id": "fwa_config"})
    if not fwa_data:
        # Initialize empty FWA data if none exists
        fwa_data = {
            "_id": "fwa_config",
            "fwa_base_links": {},
            "base_information": {},
            "base_upgrade_notes": {},
            "war_base_images": {},
            "active_base_images": {}
        }
        await mongo.fwa_data.insert_one(fwa_data)
    else:
        # Migration: Move old base_descriptions to base_information
        if "base_descriptions" in fwa_data and "base_information" not in fwa_data:
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {"base_information": fwa_data["base_descriptions"]}}
            )
            fwa_data["base_information"] = fwa_data["base_descriptions"]

        # Ensure base_upgrade_notes exists
        if "base_upgrade_notes" not in fwa_data:
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {"base_upgrade_notes": {}}}
            )
            fwa_data["base_upgrade_notes"] = {}

    return fwa_data


async def build_fwa_management_screen(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient,
        manage_token: str | None = None,
) -> List[Container]:
    """Build the FWA management screen components

    Returns:
        List of Container components for the FWA management screen
    """
    # Keep managed navigation available after TH edits and modal submissions.
    manage_token = manage_token or _management_token(ctx)
    # Get current FWA data
    fwa_data = await get_fwa_data(mongo)
    base_links = fwa_data.get("fwa_base_links", {})
    base_information = fwa_data.get("base_information", {})
    base_upgrade_notes = fwa_data.get("base_upgrade_notes", {})

    # Load stored image URLs into memory if available
    war_images = fwa_data.get("war_base_images", {})
    active_images = fwa_data.get("active_base_images", {})

    # Mongo keeps the raw URLs; the in-memory dicts hold delivery-optimized ones, as main.py seeds them at startup.
    if war_images:
        FWA_WAR_BASE.update({th: optimized(u, width=DETAIL) for th, u in war_images.items()})
    if active_images:
        FWA_ACTIVE_WAR_BASE.update({th: optimized(u, width=DETAIL) for th, u in active_images.items()})

    # Build overview of all TH levels
    overview_lines = []
    for th in FWA_TH_LEVELS:
        emoji_obj = get_th_emoji(th)
        emoji_str = str(emoji_obj) if emoji_obj else "🏛️"
        base_link = base_links.get(th)
        war_image = FWA_WAR_BASE.get(th)
        active_image = FWA_ACTIVE_WAR_BASE.get(th)
        base_info = base_information.get(th)
        upgrade_notes = base_upgrade_notes.get(th)

        status = format_th_status(th, base_link, war_image, active_image, base_info, upgrade_notes)
        th_num = th.upper().replace("TH", "")

        overview_lines.append(f"{emoji_str} **TH{th_num}** {status}")

    # Build dropdown options for TH selection
    options = []
    for th in FWA_TH_LEVELS:
        emoji_obj = get_th_emoji(th)
        th_num = th.upper().replace("TH", "")

        # Check what data exists
        has_link = "✅" if base_links.get(th) else "❌"
        has_war = "✅" if FWA_WAR_BASE.get(th) else "❌"
        has_active = "✅" if FWA_ACTIVE_WAR_BASE.get(th) else "❌"
        has_info = "✅" if base_information.get(th) else "❌"
        has_notes = "✅" if base_upgrade_notes.get(th) else "❌"

        description = f"Link {has_link} | War {has_war} | Active {has_active} | Info {has_info} | Notes {has_notes}"

        option_kwargs = {
            "label": f"Town Hall {th_num}",
            "value": th,
            "description": description
        }

        # Only add emoji if it has partial_emoji attribute
        if emoji_obj and hasattr(emoji_obj, 'partial_emoji'):
            option_kwargs["emoji"] = emoji_obj.partial_emoji

        options.append(SelectOption(**option_kwargs))

    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=breadcrumb("FWA", "Bases & Guidance") + "\n## FWA Bases & Guidance"),
                Text(content="Manage base links and images for each Town Hall level"),
                Separator(divider=True),
                Text(content=(
                    "**Status Icons:**\n"
                    "🔗 = Base Link | 🖼️ = War Image | 🎯 = Active Image\n"
                    "📝 = Base Information | 📋 = Upgrade Notes | ❌ = Missing Data"
                )),
                Separator(divider=True),
                Text(content="### 📊 **Current Status**"),
                Text(content="\n".join(overview_lines)),
                Separator(divider=True),
                Text(content="### 🔧 **Select Town Hall to Edit**"),

                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"fwa_th_select:{manage_token or 'main'}",
                            placeholder="Select a Town Hall to edit...",
                            max_values=1,
                            options=options,
                        )
                    ]
                ),

                Separator(divider=True),
            ]
        )
    ]

    if manage_token:
        components[0].add_component(ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"manage_fwa:{manage_token}",
            label="Back to FWA", emoji=button_emoji("Back to FWA"),
        ), Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_home:{manage_token}",
                  label="Management Home", emoji=button_emoji("Management Home"))]))
    return components


def format_th_status(th_level: str, base_link: Optional[str], war_image: Optional[str],
                     active_image: Optional[str], base_info: Optional[str],
                     upgrade_notes: Optional[str]) -> str:
    """Format the status of a TH level for display"""
    statuses = []

    if base_link:
        statuses.append("🔗")
    else:
        statuses.append("❌")

    if war_image:
        statuses.append("🖼️")
    else:
        statuses.append("❌")

    if active_image:
        statuses.append("🎯")
    else:
        statuses.append("❌")

    if base_info:
        statuses.append("📝")
    else:
        statuses.append("❌")

    if upgrade_notes:
        statuses.append("📋")
    else:
        statuses.append("❌")

    return " ".join(statuses)


def build_th_edit_components(th_level: str, base_link: str, base_info: str,
                             upgrade_notes: str, war_image: str, active_image: str,
                             manage_token: str | None = None) -> List[Container]:
    """Build the TH edit screen components

    Args:
        th_level: The TH level (e.g., "th15")
        base_link: The base link URL
        base_info: Base information description
        upgrade_notes: Upgrade notes description
        war_image: War base image URL
        active_image: Active base image URL

    Returns:
        List of Container components for the TH edit screen
    """
    th_num = th_level.upper().replace("TH", "")
    emoji_obj = get_th_emoji(th_level)
    emoji_str = str(emoji_obj) if emoji_obj else "🏛️"

    # Build components
    component_list = [
        Text(content=breadcrumb("FWA", "Bases & Guidance", f"TH{th_num}") + f"\n## {emoji_str} **Editing TH{th_num} FWA Data**"),
        Separator(divider=True),
    ]

    # Base Link Section
    component_list.extend([
        Text(content="### 🔗 **Base Link**"),
        Text(content=f"```\n{base_link if base_link else 'No link set'}\n```"),
    ])

    # War Base Image Section
    if war_image:
        component_list.extend([
            Text(content="### 🖼️ **Current War Base**"),
            Media(items=[MediaItem(media=war_image)]),
        ])
    else:
        component_list.append(Text(content="### 🖼️ **War Base** - ❌ Not Set"))

    # Active Base Image Section
    if active_image:
        component_list.extend([
            Text(content="### 🎯 **Current Active Base**"),
            Media(items=[MediaItem(media=active_image)]),
        ])
    else:
        component_list.append(Text(content="### 🎯 **Active Base** - ❌ Not Set"))

    # Description Sections
    component_list.extend([
        Text(content="### 📝 **Base Information**"),
        Text(content=f"{base_info if base_info else 'Not set'}"),
        Separator(divider=True),
        Text(content="### 📋 **Upgrade Notes (What's New)**"),
        Text(content=f"{upgrade_notes if upgrade_notes else 'Not set'}"),
        Separator(divider=True),
    ])

    # Action Buttons
    component_list.extend([
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update Link",
                    emoji=button_emoji("Update Link"),
                    custom_id=f"fwa_update_link:{th_level}",
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update Images",
                    emoji=button_emoji("Update Images"),
                    custom_id=f"fwa_update_images:{th_level}",
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update Descriptions",
                    emoji=button_emoji("Update Descriptions"),
                    custom_id=f"fwa_update_descriptions:{th_level}",
                ),
            ]
        ),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    label="Back to Bases & Guidance",
                    emoji=button_emoji("Back to Bases & Guidance"),
                    custom_id=f"fwa_back_to_main:{manage_token or 'main'}",
                ),
            ]
        ),
    ])

    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=component_list
        )
    ]

    if manage_token:
        components[0].add_component(ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"manage_fwa:{manage_token}",
            label="Back to FWA", emoji=button_emoji("Back to FWA"),
        ), Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_home:{manage_token}",
                  label="Management Home", emoji=button_emoji("Management Home"))]))
    return components


@register_action("manage_fwa_data", group="clan_database")
@lightbulb.di.with_di
async def manage_fwa_data(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Main FWA data management dashboard"""

    # Check if user has the required role
    member = ctx.member
    if not member:
        await ctx.respond(
            "❌ Unable to verify permissions. Please try again.",
            ephemeral=True
        )
        return

    # Check if the user has the FWA Rep role
    user_role_ids = [role.id for role in member.get_roles()]
    if FWA_REP_ROLE_ID not in user_role_ids:
        # User doesn't have permission - show access denied message
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Access Denied"),
                    Separator(divider=True),
                    Text(content=(
                        "You do not have permission to access FWA Data Management.\n\n"
                        "This feature is restricted to users with the FWA Rep role.\n"
                        "If you believe you should have access, please contact an administrator."
                    )),
                    Separator(divider=True),
                ]
            )
        ]
        await ctx.respond(components=components, ephemeral=True)
        return await dashboard_page(ctx=ctx, mongo=mongo)

    # If we get here, user has permission - build and show the FWA management screen
    components = await build_fwa_management_screen(ctx, mongo)

    await ctx.respond(components=components, ephemeral=True)

    return await dashboard_page(ctx=ctx, mongo=mongo)


@register_action("fwa_back_to_main", ephemeral=True)
@lightbulb.di.with_di
async def fwa_back_to_main(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to FWA management main screen from TH edit or other sub-screens"""
    token = kwargs.get("action_id")
    return await build_fwa_management_screen(ctx, mongo, manage_token=token if token and token != "main" else _management_token(ctx))


@register_action("fwa_th_select", ephemeral=True)
@lightbulb.di.with_di
async def fwa_th_select(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        media: MediaStore = lightbulb.di.INJECTED,
        **kwargs
):
    """Display detailed edit view for selected TH"""

    th_level = ctx.interaction.values[0]

    # Get current data
    fwa_data = await get_fwa_data(mongo)
    base_link = fwa_data.get("fwa_base_links", {}).get(th_level, "")
    base_info = fwa_data.get("base_information", {}).get(th_level, "")
    upgrade_notes = fwa_data.get("base_upgrade_notes", {}).get(th_level, "")
    war_image = FWA_WAR_BASE.get(th_level, "")
    active_image = FWA_ACTIVE_WAR_BASE.get(th_level, "")

    # Build and return the TH edit screen
    token = kwargs.get("manage_token") or kwargs.get("action_id")
    token = token if token and token != "main" else _management_token(ctx)
    return build_th_edit_components(th_level, base_link, base_info, upgrade_notes, war_image, active_image,
                                    manage_token=token)


@register_action("fwa_update_link", no_return=True, opens_modal=True)
async def fwa_update_link(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Modal for updating base link"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    link_input = ModalActionRow().add_text_input(
        "base_link",
        f"TH{th_num} Base Link",
        placeholder="https://link.clashofclans.com/?action=OpenLayout&id=...",
        required=True,
        max_length=500
    )

    await ctx.respond_with_modal(
        title=f"Update TH{th_num} Base Link",
        custom_id=f"fwa_link_submit:{th_level}",
        components=[link_input]
    )


@register_action("fwa_link_submit", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def fwa_link_submit(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Process base link update"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    def get_value(custom_id: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == custom_id:
                    return comp.value
        return ""

    base_link = get_value("base_link").strip()

    # Validate the link
    if not validate_clash_link(base_link):
        await ctx.respond(
            "❌ Invalid base link! Please use a valid Clash of Clans layout link.",
            ephemeral=True
        )
        return

    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)

    # Update in database
    await mongo.fwa_data.update_one(
        {"_id": "fwa_config"},
        {"$set": {f"fwa_base_links.{th_level}": base_link}},
        upsert=True
    )

    # Success response
    await ctx.interaction.edit_initial_response(
        components=[
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## ✅ TH{th_num} Base Link Updated!"),
                    Text(content=f"```\n{base_link}\n```"),
                    Separator(divider=True),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                label=f"Back to TH{th_num} Edit", emoji=button_emoji(f"Back to TH{th_num} Edit"),
                                custom_id=_return_to_th_id(ctx, th_level),
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Back to Bases & Guidance", emoji=button_emoji("Back to Bases & Guidance"),
                                custom_id=_return_to_fwa_id(ctx),
                            ),
                            *_home_button(ctx),
                        ]
                    )
                ]
            )
        ]
    )

@register_action("fwa_update_images", ephemeral=True)
@lightbulb.di.with_di
async def fwa_update_images(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Show options for updating images"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=f"## 🖼️ **Update TH{th_num} Images**"),
                Text(content="Choose how to update the base images:"),
                Separator(divider=True),

                Text(content=(
                    "Upload a war or active base image. Submitting saves the "
                    "replacement immediately and shows a preview.\n"
                    "PNG, JPG, GIF or WEBP; maximum 10 MB per image."
                )),
                ActionRow(components=[
                    Button(style=hikari.ButtonStyle.PRIMARY,
                           custom_id=f"fwa_image_upload:war:{th_level}",
                           label="Upload War Base"),
                    Button(style=hikari.ButtonStyle.PRIMARY,
                           custom_id=f"fwa_image_upload:active:{th_level}",
                           label="Upload Active Base"),
                    Button(style=hikari.ButtonStyle.SECONDARY,
                           custom_id=f"fwa_image_urls:{th_level}",
                           label="Use Image URLs"),
                ]),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji=button_emoji("Back"),
                            custom_id=_return_to_th_id(ctx, th_level),
                        ),
                        *_home_button(ctx),
                    ]
                ),

                Separator(divider=True),
            ]
        )
    ]

    return components


@register_action("fwa_image_urls", no_return=True, opens_modal=True)
async def fwa_image_urls(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Modal for updating image URLs"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    war_input = ModalActionRow().add_text_input(
        "war_image",
        f"TH{th_num} War Base Image URL",
        placeholder="https://example.com/war_base.png",
        required=False,
        max_length=500
    )

    active_input = ModalActionRow().add_text_input(
        "active_image",
        f"TH{th_num} Active Base Image URL",
        placeholder="https://example.com/active_base.png",
        required=False,
        max_length=500
    )

    await ctx.respond_with_modal(
        title=f"Update TH{th_num} Images",
        custom_id=f"fwa_images_submit:{th_level}",
        components=[war_input, active_input]
    )


@register_action("fwa_images_submit", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def fwa_images_submit(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        media: MediaStore = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Process image URL updates"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    def get_value(custom_id: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == custom_id:
                    return comp.value
        return ""

    war_url = get_value("war_image").strip()
    active_url = get_value("active_image").strip()

    if not war_url and not active_url:
        await ctx.respond(
            "❌ Please provide at least one image URL!",
            ephemeral=True
        )
        return

    # Validate URLs
    if war_url and not validate_image_url(war_url):
        await ctx.respond(
            "❌ Invalid war base image URL!",
            ephemeral=True
        )
        return

    if active_url and not validate_image_url(active_url):
        await ctx.respond(
            "❌ Invalid active base image URL!",
            ephemeral=True
        )
        return

    # Initial response
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.MESSAGE_UPDATE,
        components=[
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ⏳ Uploading Images..."),
                    Text(content="Please wait while we fetch and store your images...")
                ]
            )
        ]
    )

    try:
        updates = []

        # Upload war base image
        if war_url:
            war_stored_url = await media.upload_from_url(
                war_url,
                folder=fwa_base_folder(th_level),
                name=FWA_WAR_BASE_NAME
            )

            # Update the constant in memory (for this session),
            # delivery-optimized; Mongo below keeps the raw URL
            FWA_WAR_BASE[th_level] = optimized(war_stored_url, width=DETAIL)

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"war_base_images.{th_level}": war_stored_url}},
                upsert=True
            )

            updates.append(f"✅ War base image uploaded")

        # Upload active base image
        if active_url:
            active_stored_url = await media.upload_from_url(
                active_url,
                folder=fwa_base_folder(th_level),
                name=FWA_ACTIVE_BASE_NAME
            )

            # Update the constant in memory (for this session),
            # delivery-optimized; Mongo below keeps the raw URL
            FWA_ACTIVE_WAR_BASE[th_level] = optimized(active_stored_url, width=DETAIL)

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"active_base_images.{th_level}": active_stored_url}},
                upsert=True
            )

            updates.append(f"✅ Active base image uploaded")

        # Success response
        await ctx.interaction.edit_initial_response(
            components=[
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"## ✅ TH{th_num} Images Updated!"),
                        Text(content="\n".join(updates)),
                        Separator(divider=True),
                        Text(content="*Images have been uploaded successfully!*"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.PRIMARY,
                                    label=f"Back to TH{th_num} Edit", emoji=button_emoji(f"Back to TH{th_num} Edit"),
                                    custom_id=_return_to_th_id(ctx, th_level),
                                ),
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    label="Back to Bases & Guidance", emoji=button_emoji("Back to Bases & Guidance"),
                                    custom_id=_return_to_fwa_id(ctx),
                                ),
                                *_home_button(ctx),
                            ]
                        )
                    ]
                )
            ]
        )

    except Exception as e:
        await ctx.interaction.edit_initial_response(
            components=[
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ Upload Failed"),
                        Text(content=f"Error: {str(e)[:200]}"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    label="Back", emoji=button_emoji("Back"),
                                    custom_id=_return_to_th_id(ctx, th_level),
                                )
                            ]
                        )
                    ]
                )
            ]
        )

@register_action("fwa_update_descriptions", no_return=True, opens_modal=True)
@lightbulb.di.with_di
async def fwa_update_descriptions(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Modal for updating base descriptions"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    # Fetch existing data from MongoDB
    fwa_data = await get_fwa_data(mongo)
    existing_base_info = fwa_data.get("base_information", {}).get(th_level, "")
    existing_upgrade_notes = fwa_data.get("base_upgrade_notes", {}).get(th_level, "")

    info_input = ModalActionRow().add_text_input(
        "base_information",
        "Base Information",
        placeholder="General information about this base layout",
        required=False,
        max_length=4000,
        style=hikari.TextInputStyle.PARAGRAPH,
        value=existing_base_info
    )

    notes_input = ModalActionRow().add_text_input(
        "upgrade_notes",
        "Upgrade Notes (What's New)",
        placeholder="What changed from previous TH (new buildings, defense levels, etc.)",
        required=False,
        max_length=4000,
        style=hikari.TextInputStyle.PARAGRAPH,
        value=existing_upgrade_notes
    )

    await ctx.respond_with_modal(
        title=f"Update TH{th_num} Descriptions",
        custom_id=f"fwa_descriptions_submit:{th_level}",
        components=[info_input, notes_input]
    )


@register_action("fwa_th_select_return", ephemeral=True)
@lightbulb.di.with_di
async def fwa_th_select_return(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        media: MediaStore = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to TH edit view"""
    # Manually set the interaction values to simulate selection
    th_level, _, token = action_id.partition("|")
    ctx.interaction.values = [th_level]

    # Call fwa_th_select and get its components
    return await fwa_th_select(ctx=ctx, mongo=mongo, media=media,
                               manage_token=token or _management_token(ctx), **kwargs)


@register_action("fwa_descriptions_submit", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def fwa_descriptions_submit(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    if not await _require_fwa_representative(ctx):
        return
    """Process description updates"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    def get_value(custom_id: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == custom_id:
                    return comp.value
        return ""

    base_info = get_value("base_information").strip()
    upgrade_notes = get_value("upgrade_notes").strip()

    # Check if at least one field is provided
    if not base_info and not upgrade_notes:
        await ctx.respond(
            "❌ Please provide at least one description!",
            ephemeral=True
        )
        return

    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)

    # Update in database
    update_fields = {}
    if base_info:
        update_fields[f"base_information.{th_level}"] = base_info
    if upgrade_notes:
        update_fields[f"base_upgrade_notes.{th_level}"] = upgrade_notes

    await mongo.fwa_data.update_one(
        {"_id": "fwa_config"},
        {"$set": update_fields},
        upsert=True
    )

    # Initial response - show loading screen immediately
    await ctx.interaction.edit_initial_response(
        components=[
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ⏳ Updating Descriptions..."),
                    Text(content="Please wait while we update the descriptions...")
                ]
            )
        ]
    )

    # Fetch UPDATED data from database
    fwa_data = await get_fwa_data(mongo)
    base_link = fwa_data.get("fwa_base_links", {}).get(th_level, "")
    updated_base_info = fwa_data.get("base_information", {}).get(th_level, "")
    updated_upgrade_notes = fwa_data.get("base_upgrade_notes", {}).get(th_level, "")
    war_image = FWA_WAR_BASE.get(th_level, "")
    active_image = FWA_ACTIVE_WAR_BASE.get(th_level, "")

    # Build TH edit screen with updated descriptions
    components = build_th_edit_components(
        th_level, base_link, updated_base_info, updated_upgrade_notes, war_image, active_image,
        manage_token=_management_token(ctx),
    )

    # Edit the response to show the updated TH edit screen
    await ctx.interaction.edit_initial_response(components=components)


@register_action("fwa_upload_guide", ephemeral=True)
@lightbulb.di.with_di
async def fwa_upload_guide(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # th_level
        **kwargs
):
    """Old persistent buttons now open the native FWA image controls."""
    return await fwa_update_images(ctx=ctx, action_id=action_id)
