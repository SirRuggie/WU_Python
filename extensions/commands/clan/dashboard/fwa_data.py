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
from utils.cloudinary_client import CloudinaryClient
from utils.constants import RED_ACCENT, GREEN_ACCENT, BLUE_ACCENT, GOLD_ACCENT, FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
from utils.emoji import emojis
from extensions.commands.clan.dashboard.dashboard import dashboard_page

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

# TH levels we support for FWA
FWA_TH_LEVELS = ["th9", "th10", "th11", "th12", "th13", "th14", "th15", "th16", "th17"]

SERVER_FAMILY = "Warriors_United"

# Cloudinary folder structure
CLOUDINARY_WAR_BASE_FOLDER = f"FWA_Images/{SERVER_FAMILY}/war_bases"
CLOUDINARY_ACTIVE_BASE_FOLDER = f"FWA_Images/{SERVER_FAMILY}/active_bases"


# Helper function to generate public IDs
def get_fwa_public_id(th_level: str, base_type: str) -> str:
    """Generate consistent public ID for FWA images

    Args:
        th_level: e.g., "th15" or "TH15"
        base_type: "war" or "active"

    Returns:
        str: e.g., "TH15_WarBase" or "TH15_Active_WarBase"
    """
    th_num = th_level.upper().replace("TH", "")

    if base_type == "war":
        return f"TH{th_num}_WarBase"
    else:
        return f"TH{th_num}_Active_WarBase"


def get_th_emoji(th_level: str):
    """Get the appropriate TH emoji object"""
    th_num = th_level.upper().replace("TH", "")
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
            "base_descriptions": {},
            "war_base_images": {},
            "active_base_images": {}
        }
        await mongo.fwa_data.insert_one(fwa_data)
    return fwa_data


def format_th_status(th_level: str, base_link: Optional[str], war_image: Optional[str],
                     active_image: Optional[str]) -> str:
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

    return " ".join(statuses)


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
        return await dashboard_page(ctx=ctx, mongo=mongo)

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
                    Media(
                        items=[
                            MediaItem(media="assets/Red_Footer.png")
                        ]
                    ),
                ]
            )
        ]
        await ctx.respond(components=components, ephemeral=True)
        return await dashboard_page(ctx=ctx, mongo=mongo)

    # If we get here, user has permission - show the normal FWA management menu
    # Get current FWA data
    fwa_data = await get_fwa_data(mongo)
    base_links = fwa_data.get("fwa_base_links", {})
    descriptions = fwa_data.get("base_descriptions", {})

    # Load stored image URLs into memory if available
    war_images = fwa_data.get("war_base_images", {})
    active_images = fwa_data.get("active_base_images", {})

    # Update the constants with stored URLs
    if war_images:
        FWA_WAR_BASE.update(war_images)
    if active_images:
        FWA_ACTIVE_WAR_BASE.update(active_images)

    # Build overview of all TH levels
    overview_lines = []
    for th in FWA_TH_LEVELS:
        emoji_obj = get_th_emoji(th)
        emoji_str = str(emoji_obj) if emoji_obj else "🏛️"
        base_link = base_links.get(th)
        war_image = FWA_WAR_BASE.get(th)
        active_image = FWA_ACTIVE_WAR_BASE.get(th)

        status = format_th_status(th, base_link, war_image, active_image)
        th_num = th.upper().replace("TH", "")

        overview_lines.append(f"{emoji_str} **TH{th_num}** {status}")

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## 🏰 **FWA Data Management**"),
                Text(content="Manage base links and images for each Town Hall level"),
                Separator(divider=True),
                Text(content=(
                    "**Status Icons:**\n"
                    "🔗 = Base Link | 🖼️ = War Image | 🎯 = Active Image\n"
                    "❌ = Missing Data"
                )),
                Separator(divider=True),
                Text(content="### 📊 **Current Status**"),
                Text(content="\n".join(overview_lines)),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            label="Quick Edit",
                            emoji="✏️",
                            custom_id="fwa_quick_edit:main",
                        ),
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            label="Bulk Update",
                            emoji="📦",
                            custom_id="fwa_bulk_update:main",
                        ),
                    ]
                ),

                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ]
        )
    ]

    await ctx.respond(components=components, ephemeral=True)

    # Return to dashboard
    return await dashboard_page(ctx=ctx, mongo=mongo)


@register_action("fwa_quick_edit", ephemeral=True)
@lightbulb.di.with_di
async def fwa_quick_edit(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Quick edit selector for individual TH levels"""

    # Build options for each TH level
    options = []
    fwa_data = await get_fwa_data(mongo)
    base_links = fwa_data.get("fwa_base_links", {})

    for th in FWA_TH_LEVELS:
        emoji_obj = get_th_emoji(th)
        th_num = th.upper().replace("TH", "")

        # Check what data exists
        has_link = "✅" if base_links.get(th) else "❌"
        has_war = "✅" if FWA_WAR_BASE.get(th) else "❌"
        has_active = "✅" if FWA_ACTIVE_WAR_BASE.get(th) else "❌"

        description = f"Link {has_link} | War {has_war} | Active {has_active}"

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
            accent_color=GOLD_ACCENT,
            components=[
                Text(content="## ✏️ **Quick Edit - Select Town Hall**"),
                Text(content="Choose a Town Hall level to update its FWA data"),

                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id="fwa_th_select:main",
                            placeholder="Select a Town Hall...",
                            max_values=1,
                            options=options,
                        )
                    ]
                ),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji="◀️",
                            custom_id="back_to_fwa_main:main",
                        ),
                    ]
                ),

                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("fwa_th_select", ephemeral=True)
@lightbulb.di.with_di
async def fwa_th_select(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        cloudinary: CloudinaryClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Display detailed edit view for selected TH"""

    th_level = ctx.interaction.values[0]
    th_num = th_level.upper().replace("TH", "")
    emoji_obj = get_th_emoji(th_level)
    emoji_str = str(emoji_obj) if emoji_obj else "🏛️"

    # Get current data
    fwa_data = await get_fwa_data(mongo)
    base_link = fwa_data.get("fwa_base_links", {}).get(th_level, "")
    description = fwa_data.get("base_descriptions", {}).get(th_level, "")
    war_image = FWA_WAR_BASE.get(th_level, "")
    active_image = FWA_ACTIVE_WAR_BASE.get(th_level, "")

    # Build components
    component_list = [
        Text(content=f"## {emoji_str} **Editing TH{th_num} FWA Data**"),
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

    # Description Section
    component_list.extend([
        Text(content="### 📝 **Base Description**"),
        Text(content=f"_{description if description else 'No description set'}_"),
        Separator(divider=True),
    ])

    # Action Buttons
    component_list.extend([
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update Link",
                    emoji="🔗",
                    custom_id=f"fwa_update_link:{th_level}",
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update Images",
                    emoji="🖼️",
                    custom_id=f"fwa_update_images:{th_level}",
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    label="Update All",
                    emoji="📝",
                    custom_id=f"fwa_update_all:{th_level}",
                ),
            ]
        ),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    label="Back",
                    emoji="◀️",
                    custom_id="fwa_quick_edit:main",
                ),
            ]
        ),
    ])

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=component_list
        )
    ]

    return components


@register_action("fwa_update_link", no_return=True, is_modal=True)
async def fwa_update_link(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
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

    desc_input = ModalActionRow().add_text_input(
        "description",
        "Base Description (Optional)",
        placeholder="Enter any special notes about this base layout",
        required=False,
        max_length=200,
        style=hikari.TextInputStyle.PARAGRAPH
    )

    await ctx.respond_with_modal(
        title=f"Update TH{th_num} Base Link",
        custom_id=f"fwa_link_submit:{th_level}",
        components=[link_input, desc_input]
    )


@register_action("fwa_link_submit", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def fwa_link_submit(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
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
    description = get_value("description").strip()

    # Validate the link
    if not validate_clash_link(base_link):
        await ctx.respond(
            "❌ Invalid base link! Please use a valid Clash of Clans layout link.",
            ephemeral=True
        )
        return

    # Update in database
    await mongo.fwa_data.update_one(
        {"_id": "fwa_config"},
        {
            "$set": {
                f"fwa_base_links.{th_level}": base_link,
                f"base_descriptions.{th_level}": description
            }
        },
        upsert=True
    )

    # Success response
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.MESSAGE_UPDATE,
        components=[
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content=f"## ✅ TH{th_num} Base Link Updated!"),
                    Text(content=f"```\n{base_link}\n```"),
                    Separator(divider=True),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                label=f"Back to TH{th_num} Edit",
                                custom_id=f"fwa_th_select_return:{th_level}",
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Back to Main Menu",
                                custom_id="fwa_quick_edit:main",
                            )
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
            accent_color=GOLD_ACCENT,
            components=[
                Text(content=f"## 🖼️ **Update TH{th_num} Images**"),
                Text(content="Choose how to update the base images:"),
                Separator(divider=True),

                Section(
                    components=[
                        Text(content=(
                            "**Option 1: Image URLs**\n"
                            "Provide direct links to images already hosted online"
                        ))
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        label="Use URLs",
                        emoji="🔗",
                        custom_id=f"fwa_image_urls:{th_level}",
                    )
                ),

                Section(
                    components=[
                        Text(content=(
                            "**Option 2: Upload Command**\n"
                            "Use `/fwa upload-images` to upload files directly"
                        ))
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        label="Instructions",
                        emoji="📤",
                        custom_id=f"fwa_upload_guide:{th_level}",
                    )
                ),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji="◀️",
                            custom_id=f"fwa_th_select_return:{th_level}",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("fwa_image_urls", no_return=True, is_modal=True)
async def fwa_image_urls(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
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
        cloudinary: CloudinaryClient = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
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
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## ⏳ Uploading Images..."),
                    Text(content="Please wait while we upload your images to Cloudinary...")
                ]
            )
        ]
    )

    try:
        updates = []

        # Upload war base image
        if war_url:
            war_public_id = get_fwa_public_id(th_level, "war")

            result = await cloudinary.upload_image_from_url(
                war_url,
                folder=CLOUDINARY_WAR_BASE_FOLDER,
                public_id=war_public_id
            )
            war_cloudinary_url = result["secure_url"]

            # Update the constant in memory (for this session)
            FWA_WAR_BASE[th_level] = war_cloudinary_url

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"war_base_images.{th_level}": war_cloudinary_url}},
                upsert=True
            )

            updates.append(f"✅ War base image uploaded")

        # Upload active base image
        if active_url:
            active_public_id = get_fwa_public_id(th_level, "active")

            result = await cloudinary.upload_image_from_url(
                active_url,
                folder=CLOUDINARY_ACTIVE_BASE_FOLDER,
                public_id=active_public_id
            )
            active_cloudinary_url = result["secure_url"]

            # Update the constant in memory (for this session)
            FWA_ACTIVE_WAR_BASE[th_level] = active_cloudinary_url

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"active_base_images.{th_level}": active_cloudinary_url}},
                upsert=True
            )

            updates.append(f"✅ Active base image uploaded")

        # Success response
        await ctx.interaction.edit_initial_response(
            components=[
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content=f"## ✅ TH{th_num} Images Updated!"),
                        Text(content="\n".join(updates)),
                        Separator(divider=True),
                        Text(content="*Images have been uploaded successfully!*"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.PRIMARY,
                                    label=f"Back to TH{th_num} Edit",
                                    custom_id=f"fwa_th_select_return:{th_level}",
                                ),
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    label="Back to Main Menu",
                                    custom_id="fwa_quick_edit:main",
                                )
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
                                    label="Back",
                                    custom_id=f"fwa_th_select_return:{th_level}",
                                )
                            ]
                        )
                    ]
                )
            ]
        )

@register_action("fwa_update_all", no_return=True, is_modal=True)
async def fwa_update_all(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    """Modal for updating all data at once"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    link_input = ModalActionRow().add_text_input(
        "base_link",
        f"TH{th_num} Base Link",
        placeholder="https://link.clashofclans.com/?action=OpenLayout&id=...",
        required=True,
        max_length=500
    )

    war_input = ModalActionRow().add_text_input(
        "war_image",
        "War Base Image URL (Optional)",
        placeholder="https://example.com/war_base.png",
        required=False,
        max_length=500
    )

    active_input = ModalActionRow().add_text_input(
        "active_image",
        "Active Base Image URL (Optional)",
        placeholder="https://example.com/active_base.png",
        required=False,
        max_length=500
    )

    desc_input = ModalActionRow().add_text_input(
        "description",
        "Base Description (Optional)",
        placeholder="Special notes about this base",
        required=False,
        max_length=200,
        style=hikari.TextInputStyle.PARAGRAPH
    )

    await ctx.respond_with_modal(
        title=f"Update TH{th_num} - All Data",
        custom_id=f"fwa_all_submit:{th_level}",
        components=[link_input, war_input, active_input, desc_input]
    )


@register_action("fwa_th_select_return", ephemeral=True)
@lightbulb.di.with_di
async def fwa_th_select_return(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        cloudinary: CloudinaryClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to TH edit view"""
    # Manually set the interaction values to simulate selection
    ctx.interaction.values = [action_id]

    # Call fwa_th_select and get its components
    return await fwa_th_select(ctx=ctx, mongo=mongo, cloudinary=cloudinary, **kwargs)


@register_action("back_to_fwa_main", ephemeral=True)
@lightbulb.di.with_di
async def back_to_fwa_main(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Return to main FWA management view"""
    # Get current FWA data
    fwa_data = await get_fwa_data(mongo)
    base_links = fwa_data.get("fwa_base_links", {})
    descriptions = fwa_data.get("base_descriptions", {})

    # Build overview of all TH levels
    overview_lines = []
    for th in FWA_TH_LEVELS:
        emoji_obj = get_th_emoji(th)
        emoji_str = str(emoji_obj) if emoji_obj else "🏛️"
        base_link = base_links.get(th)
        war_image = FWA_WAR_BASE.get(th)
        active_image = FWA_ACTIVE_WAR_BASE.get(th)

        status = format_th_status(th, base_link, war_image, active_image)
        th_num = th.upper().replace("TH", "")

        overview_lines.append(f"{emoji_str} **TH{th_num}** {status}")

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## 🏰 **FWA Data Management**"),
                Text(content="Manage base links and images for each Town Hall level"),
                Separator(divider=True),
                Text(content=(
                    "**Status Icons:**\n"
                    "🔗 = Base Link | 🖼️ = War Image | 🎯 = Active Image\n"
                    "❌ = Missing Data"
                )),
                Separator(divider=True),
                Text(content="### 📊 **Current Status**"),
                Text(content="\n".join(overview_lines)),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            label="Quick Edit",
                            emoji="✏️",
                            custom_id="fwa_quick_edit:main",
                        ),
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            label="Bulk Update",
                            emoji="📦",
                            custom_id="fwa_bulk_update:main",
                        ),
                    ]
                ),

                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ]
        )
    ]

    return components


# Additional handler for bulk updates
@register_action("fwa_bulk_update", ephemeral=True)
@lightbulb.di.with_di
async def fwa_bulk_update(
        ctx: lightbulb.components.MenuContext,
        **kwargs
):
    """Show bulk update options"""

    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content="## 📦 **Bulk Update Options**"),
                Text(content="Choose a bulk update action:"),
                Separator(divider=True),

                Section(
                    components=[
                        Text(content=(
                            "**Import from JSON**\n"
                            "Upload a JSON file with base links and descriptions"
                        ))
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        label="Import JSON",
                        emoji="📄",
                        custom_id="fwa_import_json:main",
                    )
                ),

                Section(
                    components=[
                        Text(content=(
                            "**Export Current Data**\n"
                            "Download current FWA configuration as JSON"
                        ))
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        label="Export JSON",
                        emoji="💾",
                        custom_id="fwa_export_json:main",
                    )
                ),

                Section(
                    components=[
                        Text(content=(
                            "**Clear All Data**\n"
                            "⚠️ Remove all FWA base data (requires confirmation)"
                        ))
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.DANGER,
                        label="Clear All",
                        emoji="🗑️",
                        custom_id="fwa_clear_all:main",
                    )
                ),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji="◀️",
                            custom_id="back_to_fwa_main:main",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("fwa_all_submit", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def fwa_all_submit(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        cloudinary: CloudinaryClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Process all data update at once"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    def get_value(custom_id: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == custom_id:
                    return comp.value
        return ""

    base_link = get_value("base_link").strip()
    war_url = get_value("war_image").strip()
    active_url = get_value("active_image").strip()
    description = get_value("description").strip()

    # Validate base link
    if not validate_clash_link(base_link):
        await ctx.respond(
            "❌ Invalid base link! Please use a valid Clash of Clans layout link.",
            ephemeral=True
        )
        return

    # Validate image URLs if provided
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
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## ⏳ Updating FWA Data..."),
                    Text(content="Please wait while we process your updates...")
                ]
            )
        ]
    )

    try:
        updates = []

        # Update base link
        await mongo.fwa_data.update_one(
            {"_id": "fwa_config"},
            {
                "$set": {
                    f"fwa_base_links.{th_level}": base_link,
                    f"base_descriptions.{th_level}": description
                }
            },
            upsert=True
        )
        updates.append("✅ Base link updated")

        # Upload images if provided
        if war_url:
            war_public_id = get_fwa_public_id(th_level, "war")

            result = await cloudinary.upload_image_from_url(
                war_url,
                folder=CLOUDINARY_WAR_BASE_FOLDER,
                public_id=war_public_id
            )

            # Update in memory
            FWA_WAR_BASE[th_level] = result["secure_url"]

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"war_base_images.{th_level}": result["secure_url"]}},
                upsert=True
            )

            updates.append("✅ War base image uploaded")

        if active_url:
            active_public_id = get_fwa_public_id(th_level, "active")

            result = await cloudinary.upload_image_from_url(
                active_url,
                folder=CLOUDINARY_ACTIVE_BASE_FOLDER,
                public_id=active_public_id
            )

            # Update in memory
            FWA_ACTIVE_WAR_BASE[th_level] = result["secure_url"]

            # Update in database
            await mongo.fwa_data.update_one(
                {"_id": "fwa_config"},
                {"$set": {f"active_base_images.{th_level}": result["secure_url"]}},
                upsert=True
            )

            updates.append("✅ Active base image uploaded")

            # Success response - MOVED OUTSIDE THE IF BLOCK
        await ctx.interaction.edit_initial_response(
            components=[
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content=f"## ✅ TH{th_num} Fully Updated!"),
                        Text(content="\n".join(updates)),
                        Separator(divider=True),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.PRIMARY,
                                    label=f"Back to TH{th_num} Edit",
                                    custom_id=f"fwa_th_select_return:{th_level}",
                                ),
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    label="Back to Main Menu",
                                    custom_id="fwa_quick_edit:main",
                                )
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
                        Text(content="## ❌ Update Failed"),
                        Text(content=f"Error: {str(e)[:200]}"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    label="Back",
                                    custom_id=f"fwa_th_select_return:{th_level}",
                                )
                            ]
                        )
                    ]
                )
            ]
        )


@register_action("fwa_upload_guide", ephemeral=True)
@lightbulb.di.with_di
async def fwa_upload_guide(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # th_level
        **kwargs
):
    """Show upload instructions"""
    th_level = action_id
    th_num = th_level.upper().replace("TH", "")

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## 📤 **Upload Images for TH{th_num}**"),
                Separator(divider=True),

                Text(content=(
                    "**To upload images using the command:**\n\n"
                    "1. Copy this command:\n"
                    f"```/fwa upload-images town-hall:Town Hall {th_num[2:]}```\n\n"
                    "2. Paste it in any channel\n\n"
                    "3. Attach your images:\n"
                    "   • Click the ➕ button\n"
                    "   • Select war base image\n"
                    "   • Select active base image\n\n"
                    "4. Press Enter to upload\n\n"
                    "**File Requirements:**\n"
                    "• Formats: PNG, JPG, GIF, or WEBP\n"
                    "• Maximum size: 8MB per file"
                )),

                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji="◀️",
                            custom_id=f"fwa_update_images:{th_level}",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ]
        )
    ]

    return components


# Placeholder handlers for unimplemented features
@register_action("fwa_import_json", ephemeral=True)
async def fwa_import_json(ctx: lightbulb.components.MenuContext, **kwargs):
    """Import JSON handler - to be implemented"""
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## 📄 Import JSON"),
                Text(content="This feature is not yet implemented."),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back",
                            emoji="◀️",
                            custom_id="fwa_bulk_update:main",
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ]
        )
    ]
    return components


@register_action("fwa_export_json", ephemeral=True)
@lightbulb.di.with_di
async def fwa_export_json(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Export current FWA data as JSON"""

    fwa_data = await get_fwa_data(mongo)
    base_links = fwa_data.get("fwa_base_links", {})
    descriptions = fwa_data.get("base_descriptions", {})
    war_images = fwa_data.get("war_base_images", {})
    active_images = fwa_data.get("active_base_images", {})

    # Build export data
    export_data = {
        "fwa_base_links": base_links,
        "base_descriptions": descriptions,
        "war_base_images": war_images,
        "active_base_images": active_images
    }

    # Format as JSON string
    import json
    json_str = json.dumps(export_data, indent=2)

    # Discord has a 2000 character limit for messages
    if len(json_str) > 1900:
        # Too long, provide instructions to copy from database
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## 💾 Export JSON"),
                    Text(content=(
                        "The FWA data is too large to display here.\n\n"
                        "To export your data:\n"
                        "1. Use a MongoDB client to connect to your database\n"
                        "2. Export the `fwa_data` collection\n"
                        "3. Look for the document with `_id: 'fwa_config'`"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Back",
                                emoji="◀️",
                                custom_id="fwa_bulk_update:main",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                ]
            )
        ]
    else:
        # If it fits, show it
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## 💾 Export JSON"),
                    Text(content="```json\n" + json_str + "\n```"),
                    Text(content="_Copy the JSON above to save your FWA configuration_"),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Back",
                                emoji="◀️",
                                custom_id="fwa_bulk_update:main",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                ]
            )
        ]

    return components


@register_action("fwa_clear_all", ephemeral=True)
async def fwa_clear_all(ctx: lightbulb.components.MenuContext, **kwargs):
    """Clear all data confirmation"""
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## 🗑️ **Clear All FWA Data?**"),
                Text(content=(
                    "⚠️ **WARNING** ⚠️\n\n"
                    "This will permanently delete:\n"
                    "• All base links\n"
                    "• All base descriptions\n"
                    "• All stored configurations\n\n"
                    "This action cannot be undone!"
                )),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.DANGER,
                            label="Yes, Delete Everything",
                            emoji="🗑️",
                            custom_id="fwa_clear_confirm:main",
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Cancel",
                            emoji="❌",
                            custom_id="fwa_bulk_update:main",
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]
    return components


@register_action("fwa_clear_confirm", ephemeral=True)
@lightbulb.di.with_di
async def fwa_clear_confirm(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Actually clear all FWA data"""

    # Delete all FWA data
    await mongo.fwa_data.delete_many({})

    # Reinitialize empty data
    await get_fwa_data(mongo)

    components = [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ✅ **FWA Data Cleared**"),
                Text(content=(
                    "All FWA base links and descriptions have been removed.\n\n"
                    "The system has been reset to default state."
                )),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Back to Menu",
                            custom_id="back_to_fwa_main:main",
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Green_Footer.png")]),
            ]
        )
    ]
    return components