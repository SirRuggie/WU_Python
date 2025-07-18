from logging import exception

import lightbulb
import hikari
import coc
import requests
import re
import asyncio

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectMenuBuilder as SelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    ThumbnailComponentBuilder as Thumbnail,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ModalActionRowBuilder as ModalActionRow,
    LinkButtonBuilder as LinkButton
)

from extensions.components import register_action
from io import BytesIO
from PIL import Image

from utils.constants import RED_ACCENT
from utils.classes import Clan
from utils.emoji import emojis
from utils.mongo import MongoClient
from extensions.commands.clan.dashboard import dashboard_page
from extensions.commands.clan.dashboard import update_clan_info_general

CLAN_MANAGEMENT_ROLE_ID = 1060318031575793694

IMG_RE = re.compile(r"^https?://\S+\.(?:png|jpe?g|gif|webp)$", re.IGNORECASE)


@register_action("update_clan_information", group="clan_database")
@lightbulb.di.with_di
async def update_clan_information(
        ctx: lightbulb.components.MenuContext,
        **kwargs
):
    # Check if user has the required role
    member = ctx.member
    if not member:
        await ctx.respond(
            "❌ Unable to verify permissions. Please try again.",
            ephemeral=True
        )
        return

    # Check if the user has the required role
    user_role_ids = [role.id for role in member.get_roles()]
    if CLAN_MANAGEMENT_ROLE_ID not in user_role_ids:
        # User doesn't have permission - show access denied message
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Access Denied"),
                    Separator(divider=True),
                    Text(content=(
                        "You do not have permission to access Clan Management.\n\n"
                        "This feature is restricted to users with the Clan Management role.\n"
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
        return await dashboard_page(ctx=ctx)

    # If we get here, user has permission - show your normal menu
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=(
                    "### Update Clan Information\n\n"
                    "Select an action below to manage clan information in our database.\n\n"
                )),

                Section(
                    components=[
                        Text(
                            content=(
                                f"{emojis.white_arrow_right}"
                                "**Add a Clan:** Add a new clan with all relevant information."
                            )
                        )
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        label="Add a Clan",
                        emoji=emojis.add.partial_emoji,
                        custom_id="add_clan_page:",
                    ),
                ),
                Section(
                    components=[
                        Text(
                            content=(
                                f"{emojis.white_arrow_right}"
                                "**Edit a Clan:** Modify details of an existing Clan"
                            )
                        )
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        label="Edit a Clan",
                        emoji=emojis.edit.partial_emoji,
                        custom_id="choose_clan_select:",
                    ),
                ),
                Section(
                    components=[
                        Text(
                            content=(
                                f"{emojis.white_arrow_right}"
                                "**Remove a Clan:** Delete a clan and all its associated information."
                            )
                        )
                    ],
                    accessory=Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        label="Remove a Clan",
                        emoji=emojis.remove.partial_emoji,
                        custom_id="remove_clan_select:",
                    ),
                ),
                Media(
                    items=[
                        MediaItem(media="assets/Red_Footer.png"),
                    ])
            ]
        )
    ]
    await ctx.respond(components=components, ephemeral=True)

    return await dashboard_page(ctx=ctx)


# ADD CLAN STUFF
@register_action("add_clan_page")
@lightbulb.di.with_di
async def add_clan_page(
        ctx: lightbulb.components.MenuContext,
        **kwargs
):
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=(
                    "### Add a New Clan\n\n"
                    "To add a new clan, you will need to be ready to supply all the core details of the new clan. These include:\n"
                    f"{emojis.white_arrow_right}Clan Name\n"
                    f"{emojis.white_arrow_right}Clan ID\n"
                    f"{emojis.white_arrow_right}Leadership (Leader ID & Role ID\n"
                    f"{emojis.white_arrow_right}Clan Role ID\n"
                    f"{emojis.white_arrow_right}Clan Type\n"
                    f"{emojis.white_arrow_right}Logo\n"
                    f"{emojis.white_arrow_right}TH Requirements\n"
                )),
                ActionRow(components=[
                    Button(style=hikari.ButtonStyle.SECONDARY, custom_id="add_clan:", label="Add the New Clan")
                ])
            ]
        )
    ]
    return components


@register_action("add_clan", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def add_clan(
        ctx: lightbulb.components.MenuContext,
        **kwargs
):
    tag = ModalActionRow().add_text_input(
        "clantag",
        "Clan Tag",
        placeholder="Enter a Clan Tag",
        required=True
    )
    await ctx.respond_with_modal(
        title="Add Clan",
        custom_id=f"add_clan_modal:",
        components=[tag]
    )


@register_action("add_clan_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def add_clan_modal(
        ctx: lightbulb.components.ModalContext,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    def get_modal_item(ctx: lightbulb.components.ModalContext, custom_id: str):
        for row in ctx.interaction.components:
            for component in row:
                if component.custom_id == custom_id:
                    return component.value

    clan_tag = get_modal_item(ctx, "clantag")
    if not clan_tag:
        return await ctx.respond("⚠️ You must enter a clan tag!", ephemeral=True)

    clan = await coc_client.get_clan(tag=clan_tag)
    await mongo.clans.insert_one({
        "announcement_id": 0,
        "chat_channel_id": 0,
        "emoji": "",
        "tag": clan.tag,
        "leader_id": 0,
        "leader_role_id": 0,
        "leadership_channel_id": 0,
        "logo": "",
        "banner": "",
        "name": clan.name,
        "profile": "",
        "role_id": 0,
        "rules_channel_id": 0,
        "status": "",
        "th_attribute": "",
        "th_requirements": 0,
        "thread_id": 0,
        "thread_message_id": 0,
        "type": "",
        "points": 0.0,
        "recruit_count": 0
    })

    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    new_components = await clan_edit_menu(ctx, action_id=clan.tag, mongo=mongo, tag=clan.tag)
    await ctx.interaction.edit_initial_response(components=new_components)


# REMOVE CLAN STUFF
@register_action("remove_clan_select", ephemeral=True)
@lightbulb.di.with_di
async def remove_clan_select(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    clans = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=data) for data in clans]
    options = []

    for c in clans:
        # Create option with emoji if it exists, otherwise without
        if c.partial_emoji:
            # Use the partial_emoji property which properly parses the emoji format
            option = SelectOption(label=c.name, value=c.tag, description=c.tag, emoji=c.partial_emoji)
        else:
            option = SelectOption(label=c.name, value=c.tag, description=c.tag)
        options.append(option)

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="📋 **Select a clan**"),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"clan_remove_menu:",
                            placeholder="Select a clan…",
                            max_values=1,
                            options=options,
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]
    return components

@register_action("clan_remove_menu", ephemeral=True)
@lightbulb.di.with_di
async def clan_remove_menu(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = kwargs.get("tag") or ctx.interaction.values[0]

    raw = await mongo.clans.find_one({"tag": tag})
    db_clan = Clan(data=raw)

    components = [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ✏️ **Remove {db_clan.name} from Database** (`{db_clan.tag}`)"),
            Separator(divider=True, spacing=hikari.SpacingType.LARGE),

            # General Clan Info
            Text(content=f"Are you positive you want to delete **{db_clan.name}** from our system forever?"),
            Text(content="This is not reversible!"),

            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"remove_clan:confirm_{db_clan.tag}",
                        label="Yes, Delete Forever!",
                        emoji=emojis.confirm.partial_emoji,
                    ),
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"remove_clan:cancel_{db_clan.tag}",
                        label="Cancel Deletion",
                        emoji=emojis.cancel.partial_emoji,
                    ),
                ]
            ),

            # Clan Roles
            Media(items=[MediaItem(media="assets/Red_Footer.png")]),
        ],
    )]
    return components


@register_action("remove_clan", ephemeral=True)
@lightbulb.di.with_di
async def on_remove_clan_field(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,  # Add bot injection
        **kwargs
):
    # split into ["confirm" | "cancel"] and the tag
    verb, tag = action_id.split("_", 1)

    # 1) if they really confirmed, delete and show a ❌ message
    if verb == "confirm":
        raw = await mongo.clans.find_one({"tag": tag})
        db_clan = Clan(data=raw)

        # Delete the emoji from Discord if it exists
        if db_clan.emoji:
            # Parse emoji ID from mention format like <:emoji_name:123456789>
            match = re.search(r":(\d+)>$", db_clan.emoji)
            if match:
                emoji_id = int(match.group(1))
                application = await bot.rest.fetch_my_user()
                try:
                    await bot.rest.delete_application_emoji(
                        application=application.id,
                        emoji=emoji_id
                    )
                    print(f"[DEBUG] Deleted emoji {emoji_id} for clan {db_clan.name}")
                except hikari.NotFoundError:
                    print(f"[DEBUG] Emoji {emoji_id} not found, may have been already deleted")
                except Exception as e:
                    print(f"[ERROR] Failed to delete emoji {emoji_id}: {e}")

        # Delete clan from database
        await mongo.clans.delete_one({"tag": tag})

        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=f"Welp, `{db_clan.name}` has been deleted! <:SadTrash:1387846121094774854>\n"
                                 "Hopefully you didn't make an oopsie..."),
                    Text(content=f"✅ Associated emoji has been removed from the bot." if db_clan.emoji else ""),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]
    else:
        return await dashboard_page(ctx=ctx, mongo=mongo)


# EDIT CLAN STUFF
@register_action("choose_clan_select", ephemeral=True)
@lightbulb.di.with_di
async def choose_clan_select(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    clans = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=data) for data in clans]
    options = []

    for c in clans:
        # Create option with emoji if it exists, otherwise without
        if c.partial_emoji:
            # Use the partial_emoji property which properly parses the emoji format
            option = SelectOption(label=c.name, value=c.tag, description=c.tag, emoji=c.partial_emoji)
        else:
            option = SelectOption(label=c.name, value=c.tag, description=c.tag)
        options.append(option)

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="📋 **Select a clan**"),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"clan_edit_menu:",
                            placeholder="Select a clan…",
                            max_values=1,
                            options=options,
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]
    return components


@register_action("clan_edit_menu", ephemeral=True)
@lightbulb.di.with_di
async def clan_edit_menu(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = kwargs.get("tag") or ctx.interaction.values[0]

    raw = await mongo.clans.find_one({"tag": tag})
    db_clan = Clan(data=raw)

    guild_id = ctx.interaction.guild_id
    channel_link = f"https://discord.com/channels/{guild_id}/"

    # Create a Section with Thumbnail if logo exists
    general_info_components = []

    # If we have a logo URL, create a section with thumbnail
    if db_clan.logo and db_clan.logo.startswith('http'):
        general_info_components.append(
            Section(
                components=[
                    Text(content="\n## __🛡️ General Info__"),
                    Text(
                        content=(
                            f"{emojis.white_arrow_right}**Clan Type:** {db_clan.type or '⚠️ Data Missing'}\n"
                            f"{emojis.white_arrow_right}**Clan Status:** {db_clan.status or '⚠️ Data Missing'}\n"
                            f"{emojis.white_arrow_right}**Logo:** {'✅ Uploaded' if db_clan.logo else '⚠️ Data Missing'}\n"
                            f"{emojis.white_arrow_right}**Emoji:** {db_clan.emoji or '⚠️ Data Missing'}\n"
                            f"{emojis.white_arrow_right}**TH Requirement:** {db_clan.th_requirements or '⚠️ Data Missing'}\n"
                            f"{emojis.white_arrow_right}**TH Attribute:** {db_clan.th_attribute or '⚠️ Data Missing'}"
                        )
                    ),
                ],
                accessory=Thumbnail(media=db_clan.logo)
            )
        )
    else:
        # No logo, just show text
        general_info_components.extend([
            Text(content="\n## __🛡️ General Info__"),
            Text(
                content=(
                    f"{emojis.white_arrow_right}**Clan Type:** {db_clan.type or '⚠️ Data Missing'}\n"
                    f"{emojis.white_arrow_right}**Clan Status:** {db_clan.status or '⚠️ Data Missing'}\n"
                    f"{emojis.white_arrow_right}**Logo:** {db_clan.logo or '⚠️ Data Missing'}\n"
                    f"{emojis.white_arrow_right}**Emoji:** {db_clan.emoji or '⚠️ Data Missing'}\n"
                    f"{emojis.white_arrow_right}**TH Requirement:** {db_clan.th_requirements or '⚠️ Data Missing'}\n"
                    f"{emojis.white_arrow_right}**TH Attribute:** {db_clan.th_attribute or '⚠️ Data Missing'}"
                )
            ),
        ])

    components = [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ✏️ **Editing {db_clan.name}** (`{db_clan.tag}`)"),
            Separator(divider=True, spacing=hikari.SpacingType.LARGE),
            *general_info_components,

            # Clan Roles
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            Text(content=(
                "\n## __👤 Roles__\n"
                f"**Leader:** {f'<@{db_clan.leader_id}>' if db_clan.leader_id else '⚠️ Data Missing'}\n"
                f"**Leader Role:** {f'<@&{db_clan.leader_role_id}>' if db_clan.leader_role_id else '⚠️ Data Missing'}\n"
                f"**Clan Role:** {f'<@&{db_clan.role_id}>' if db_clan.role_id else '⚠️ Data Missing'}"
            )),

            # Single action row for all role selections
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"edit_roles:{tag}",
                        label="Edit Roles",
                        emoji="👤"
                    )
                ]
            ),

            # Clan Channels
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            Text(content=(
                "\n## __💬 Channels__\n"
                f"**Chat:** {f'<#{db_clan.chat_channel_id}>' if db_clan.chat_channel_id else '⚠️ Data Missing'}\n"
                f"**Announcement:** {f'<#{db_clan.announcement_id}>' if db_clan.announcement_id else '⚠️ Data Missing'}\n"
                f"**Rules:** {f'<#{db_clan.rules_channel_id}>' if db_clan.rules_channel_id else '⚠️ Data Missing'}\n"
                f"**Leadership:** {f'<#{db_clan.leadership_channel_id}>' if db_clan.leadership_channel_id else '⚠️ Data Missing'}\n"
                f"**Thread:** {f'<#{db_clan.thread_id}>' if db_clan.thread_id else '⚠️ Data Missing'}"
            )),

            # Single action row for channel management
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"edit_channels:{tag}",
                        label="Edit Channels",
                        emoji="💬"
                    ),
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"edit_thread:thread_id_{db_clan.tag}",
                        label="Add/Update Thread",
                    )
                ]
            ),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"update_logo:{db_clan.tag}",
                        label="Update Logo",
                    ),
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"update_emoji:{db_clan.tag}",
                        label="Update Emoji",
                    ),
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"update_general_info:{db_clan.tag}",
                        label="Edit General Info",
                    ),
                ]
            ),
            Separator(divider=True, spacing=hikari.SpacingType.LARGE),

            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        custom_id="choose_clan_select:",
                        label="Edit Another Clan",
                        emoji="✏️"
                    )
                ]
            ),

            # Footer image
            Media(items=[MediaItem(media="assets/Red_Footer.png")]),
        ],
    )]
    return components

@register_action("edit_clan", ephemeral=True)
@lightbulb.di.with_di
async def on_edit_clan_field(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    field, tag = action_id.rsplit("_", 1)
    raw_val = ctx.interaction.values[0]
    selected = int(raw_val) if raw_val.isdigit() else raw_val

    await mongo.clans.update_one({"tag": tag}, {"$set": {field: selected}})

    # Determine which menu to return to based on the field
    if field in ["leader_id", "leader_role_id", "role_id"]:
        # Return to roles menu
        return await edit_roles(
            ctx=ctx,
            action_id=tag,
            mongo=mongo
        )
    elif field in ["chat_channel_id", "announcement_id", "rules_channel_id", "leadership_channel_id"]:
        # Return to channels menu
        return await edit_channels(
            ctx=ctx,
            action_id=tag,
            mongo=mongo
        )
    else:
        # Default: return to main edit menu
        return await clan_edit_menu(
            ctx=ctx,
            mongo=mongo,
            tag=tag
        )



@register_action("edit_thread", ephemeral=True)
@lightbulb.di.with_di
async def on_edit_thread_field(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # e.g. "edit_thread:thread_id_LYUQG8CL"
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    field, tag = action_id.rsplit("_", 1)

    guild_id = ctx.interaction.guild_id
    PARENT_CH = 1133096989748363294

    raw = await mongo.clans.find_one({"tag": tag})

    active = await bot.rest.fetch_active_threads(guild_id)
    p_arch = await bot.rest.fetch_public_archived_threads(PARENT_CH)

    threads = [t for t in list(active) + list(p_arch) if t.parent_id == PARENT_CH and t.name == raw["name"]]

    if threads:
        thread = threads[0]
    else:
        # Create public thread
        thread = await bot.rest.create_thread(
            PARENT_CH,
            hikari.ChannelType.GUILD_PUBLIC_THREAD,
            raw["name"],
            auto_archive_duration=1440,
        )

        # Delete the "started a thread" message
        try:
            # Small delay to ensure the message is created
            await asyncio.sleep(0.5)

            # Fetch recent messages from parent channel
            messages = await bot.rest.fetch_messages(PARENT_CH).limit(5)

            # Find and delete the thread creation message
            for message in messages:
                # Thread creation messages have type 18
                if message.type == 18:  # THREAD_CREATED type
                    # Additional checks to ensure it's for our thread
                    # Thread creation messages typically mention the thread name
                    if raw["name"] in (message.content or ""):
                        await bot.rest.delete_message(PARENT_CH, message.id)
                        print(f"Deleted thread creation message for {raw['name']}")
                        break

                    # Alternative: Check if created around the same time
                    # (thread.created_at might not be available immediately, so use current time)
                    if hasattr(thread, 'created_at') and thread.created_at:
                        time_diff = abs((message.created_at - thread.created_at).total_seconds())
                        if time_diff < 2:  # Within 2 seconds
                            await bot.rest.delete_message(PARENT_CH, message.id)
                            print(f"Deleted thread creation message for {raw['name']}")
                            break

        except Exception as e:
            print(f"Error deleting thread creation message: {e}")
            # Continue even if deletion fails
            # Continue even if deletion fails

    await mongo.clans.update_one({"tag": tag}, {"$set": {"thread_id": thread.id}})

    # 5) Rebuild the edit menu
    return await clan_edit_menu(
        ctx=ctx,
        mongo=mongo,
        tag=tag
    )

@register_action("update_logo", ephemeral=True)
@lightbulb.di.with_di
async def update_logo_button(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # This is the clan tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # First, let's get the clan data so we can show the clan name
    # This makes the instructions more personalized and clear
    clan_data = await mongo.clans.find_one({"tag": tag})
    if not clan_data:
        # This shouldn't happen, but it's good to handle edge cases
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="❌ Clan not found in database."),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]
        return components

    clan_name = clan_data.get("name", "Unknown Clan")

    # Create a helpful instruction panel that explains both options
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=f"## 📸 Update Logo for {clan_name}"),
                Separator(divider=True),
                Text(content=(
                    "Choose how you'd like to provide your clan logo:\n\n"
                    "**🔗 Option 1: Image URL**\n"
                    "Perfect if your logo is already hosted online (Imgur, Discord, etc.)\n"
                    "• Quick and easy\n"
                    "• No file size limits\n"
                    "• Works with any image host\n\n"
                    "**📤 Option 2: Upload File**\n"
                    "Best if you have the logo saved on your device\n"
                    "• Drag and drop support\n"
                    "• Automatic cloud storage\n"
                    "• Max 8MB per file (Discord limit)\n"
                )),
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),

                # Action buttons for each option
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"logo_url_modal:{tag}",
                            label="Use Image URL",
                            emoji="🔗"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"logo_upload_guide:{tag}",
                            label="Upload File",
                            emoji="📤"
                        ),
                    ]
                ),

                # Cancel button to return to the edit menu
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"back_to_clan_edit:{tag}",
                            label="← Back to Edit Menu",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("logo_upload_guide", ephemeral=True)
@lightbulb.di.with_di
async def logo_upload_guide(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # This is the clan tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # Get clan data for personalized instructions
    clan_data = await mongo.clans.find_one({"tag": tag})
    clan_name = clan_data.get("name", "Unknown Clan")

    # Create the instruction guide with copyable command
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## 📤 Upload Files Instructions"),
                Separator(divider=True),

                # Step-by-step instructions
                Text(content=(
                    f"To upload images for **{clan_name}**, follow these steps:\n\n"
                    "**Step 1:** Copy this command:\n"
                    f"```/clan upload-images clan:{clan_name} | {tag}```\n\n"
                    "**Step 2:** Paste it in any channel where you can use bot commands\n\n"
                    "**Step 3:** Attach your images:\n"
                    "• Click the ➕ button when typing the command\n"
                    "• Select your logo and/or banner files\n"
                    "• You can upload both at once or separately\n\n"
                    "**File Requirements:**\n"
                    "• Formats: PNG, JPG, GIF, or WEBP\n"
                    "• Maximum size: 8MB per file\n"
                    "• Logo: First attachment\n"
                    "• Banner: Second attachment (if uploading both)\n"
                )),

                # Visual separator
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),

                # Helpful tip
                Text(content=(
                    "💡 **Pro Tip:** You can also type `/clan upload-images` and "
                    "select the clan from the dropdown menu that appears!"
                )),

                # Navigation buttons
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"update_logo:{tag}",
                            label="← Back to Options",
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"back_to_clan_edit:{tag}",
                            label="← Back to Edit Menu",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("logo_url_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def logo_url_modal_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    # When a button with custom_id="logo_url_modal:TAG" is clicked,
    # the system splits it into command_name="logo_url_modal" and action_id="TAG"

    tag = action_id  # The clan tag passed from the button

    # Create the modal with input fields for URLs
    logo_input = ModalActionRow().add_text_input(
        "logo_url",
        "Logo Image URL",
        placeholder="https://example.com/logo.png",
        required=True,  # Making it required since it's specifically for logo
    )

    # Important: Use respond_with_modal for button interactions that open modals
    await ctx.respond_with_modal(
        title=f"Update Logo via URL",
        custom_id=f"update_logo_modal:{tag}",  # This will trigger update_logo_modal handler
        components=[logo_input],
    )


@register_action("update_logo_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def update_logo_modal(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # Helper function to extract values from modal components
    def get_val(cid: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == cid:
                    return comp.value
        return ""

    new_logo_url = get_val("logo_url")

    # Basic validation - ensure URL was provided
    if not new_logo_url:
        return await ctx.respond(
            "❌ Please provide a logo URL.",
            ephemeral=True
        )

    # Validate URL format
    if not IMG_RE.match(new_logo_url):
        return await ctx.respond(
            "⚠️ Logo URL must be a direct link to a .png/.jpg/.gif/.webp image.",
            ephemeral=True
        )

    # Create a deferred response first
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    try:
        # Update the database with new URL
        await mongo.clans.update_one(
            {"tag": tag},
            {"$set": {"logo": new_logo_url}}
        )

        # Return to the clan edit menu
        new_components = await clan_edit_menu(ctx, action_id=tag, mongo=mongo, tag=tag)
        await ctx.interaction.edit_initial_response(components=new_components)

    except Exception as e:
        # Create error components that maintain the interface style
        error_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Update Failed"),
                    Separator(divider=True),
                    Text(content=f"**Error:** {str(e)[:200]}"),
                    Text(content=(
                        "\n**Please check:**\n"
                        "• The URL is valid and accessible\n"
                        "• The image format is supported (PNG, JPG, GIF, WEBP)\n"
                        "• The URL is a direct link to the image\n"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"update_logo:{tag}",
                                label="← Try Again",
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"back_to_clan_edit:{tag}",
                                label="← Back to Edit Menu",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=error_components)


@register_action("back_to_clan_edit", ephemeral=True)
@lightbulb.di.with_di
async def back_to_clan_edit(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # the tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    # Call clan_edit_menu to rebuild the menu
    components = await clan_edit_menu(
        ctx,
        mongo=mongo,
        tag=action_id,
    )

    # Return the components
    return components


@register_action("edit_roles", ephemeral=True)
@lightbulb.di.with_di
async def edit_roles(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # clan tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id
    raw = await mongo.clans.find_one({"tag": tag})
    db_clan = Clan(data=raw)

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=f"## 👤 **Edit Roles - {db_clan.name}**"),
                Separator(divider=True),

                Text(content=(
                    f"**Current Leader:** {f'<@{db_clan.leader_id}>' if db_clan.leader_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            min_values=1,
                            type=hikari.ComponentType.USER_SELECT_MENU,
                            custom_id=f"edit_clan:leader_id_{tag}",
                            placeholder="Select the leader...",
                        ),
                    ]
                ),

                Text(content=(
                    f"**Current Leader Role:** {f'<@&{db_clan.leader_role_id}>' if db_clan.leader_role_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.ROLE_SELECT_MENU,
                            custom_id=f"edit_clan:leader_role_id_{tag}",
                            placeholder="Select the leader role...",
                        ),
                    ]
                ),

                Text(content=(
                    f"**Current Clan Role:** {f'<@&{db_clan.role_id}>' if db_clan.role_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.ROLE_SELECT_MENU,
                            custom_id=f"edit_clan:role_id_{tag}",
                            placeholder="Select the clan role...",
                        ),
                    ]
                ),

                Separator(divider=True),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"back_to_clan_edit:{tag}",
                            label="← Back to Edit Menu",
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]
    return components


@register_action("edit_channels", ephemeral=True)
@lightbulb.di.with_di
async def edit_channels(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # clan tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id
    raw = await mongo.clans.find_one({"tag": tag})
    db_clan = Clan(data=raw)

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=f"## 💬 **Edit Channels - {db_clan.name}**"),
                Separator(divider=True),

                Text(content=(
                    f"**Chat Channel:** {f'<#{db_clan.chat_channel_id}>' if db_clan.chat_channel_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.CHANNEL_SELECT_MENU,
                            custom_id=f"edit_clan:chat_channel_id_{tag}",
                            placeholder="Select chat channel...",
                        ),
                    ]
                ),

                Text(content=(
                    f"**Announcement Channel:** {f'<#{db_clan.announcement_id}>' if db_clan.announcement_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.CHANNEL_SELECT_MENU,
                            custom_id=f"edit_clan:announcement_id_{tag}",
                            placeholder="Select announcement channel...",
                        ),
                    ]
                ),

                Text(content=(
                    f"**Rules Channel:** {f'<#{db_clan.rules_channel_id}>' if db_clan.rules_channel_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.CHANNEL_SELECT_MENU,
                            custom_id=f"edit_clan:rules_channel_id_{tag}",
                            placeholder="Select rules channel...",
                        ),
                    ]
                ),

                Text(content=(
                    f"**Leadership Channel:** {f'<#{db_clan.leadership_channel_id}>' if db_clan.leadership_channel_id else '⚠️ Not Set'}"
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.CHANNEL_SELECT_MENU,
                            custom_id=f"edit_clan:leadership_channel_id_{tag}",
                            placeholder="Select leadership channel...",
                        ),
                    ]
                ),

                Separator(divider=True),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"back_to_clan_edit:{tag}",
                            label="← Back to Edit Menu",
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]
    return components


@register_action("update_emoji", ephemeral=True)
@lightbulb.di.with_di
async def update_emoji_button(
        ctx: lightbulb.components.MenuContext,
        action_id: str,  # this is your clan tag
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # Get clan data to show current emoji status
    clan_data = await mongo.clans.find_one({"tag": tag})
    if not clan_data:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="❌ Clan not found in database."),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]
        return components

    clan_name = clan_data.get("name", "Unknown Clan")
    current_emoji = clan_data.get("emoji", "")

    # Create instruction panel for emoji upload
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=f"## 😊 Update Emoji for {clan_name}"),
                Separator(divider=True),
                Text(content=(
                    f"**Current Emoji:** {current_emoji if current_emoji else '⚠️ No emoji set'}\n\n"
                    "Choose how you'd like to provide your clan emoji:\n\n"
                    "**🔗 Option 1: Image URL**\n"
                    "• Provide a direct link to an emoji image\n"
                    "• Will be automatically resized to 128x128\n"
                    "• Uploaded to Discord as a bot emoji\n\n"
                    "**☁️ Option 2: From Cloudinary**\n"
                    "• Automatically fetch from your clan's Cloudinary folder\n"
                    "• Uses your clan logo as the emoji\n"
                    "• One-click solution\n"
                )),
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),

                # Action buttons
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"emoji_url_modal:{tag}",
                            label="Use Image URL",
                            emoji="🔗"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"emoji_from_cloudinary:{tag}",
                            label="Use Cloudinary Logo",
                            emoji="☁️"
                        ),
                    ]
                ),

                # Back button
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"back_to_clan_edit:{tag}",
                            label="← Back to Edit Menu",
                        )
                    ]
                ),

                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]

    return components


@register_action("emoji_url_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def emoji_url_modal_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs
):
    tag = action_id

    emoji_input = ModalActionRow().add_text_input(
        "emoji_url",
        "Emoji Image URL",
        placeholder="https://example.com/emoji.png",
        required=True,
    )

    await ctx.respond_with_modal(
        title=f"Update Emoji via URL",
        custom_id=f"update_emoji_modal:{tag}",
        components=[emoji_input],
    )


@register_action("emoji_from_cloudinary", ephemeral=True, no_return=True)
@lightbulb.di.with_di
async def emoji_from_cloudinary(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # Get clan data
    raw = await mongo.clans.find_one({"tag": tag})
    if not raw:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="❌ Clan not found!"),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]

    db_clan = Clan(data=raw)

    # Check if clan has a logo URL
    if not db_clan.logo:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=(
                        "❌ **No Logo Found**\n\n"
                        "This clan doesn't have a logo uploaded yet.\n"
                        "Please upload a logo first using the 'Update Logo' button."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"update_emoji:{tag}",
                                label="← Back",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]

    # Process the emoji using the logo URL
    await process_emoji_upload(
        ctx=ctx,
        tag=tag,
        emoji_url=db_clan.logo,
        db_clan=db_clan,
        mongo=mongo,
        bot=bot
    )


async def process_emoji_upload(
        ctx: lightbulb.components.MenuContext | lightbulb.components.ModalContext,
        tag: str,
        emoji_url: str,
        db_clan: Clan,
        mongo: MongoClient,
        bot: hikari.GatewayBot
):
    """Common function to process emoji uploads from any source"""

    # Create loading message
    loading_components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ⏳ Processing Emoji..."),
                Text(content="Downloading and resizing image..."),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ]
        )
    ]

    # Update or respond based on context type
    if isinstance(ctx, lightbulb.components.ModalContext):
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            components=loading_components
        )
    else:
        await ctx.respond(components=loading_components, edit=True)

    try:
        # Clean clan name for emoji name (remove spaces, special chars)
        clan_name = re.sub(r'[^a-zA-Z0-9]', '', db_clan.name)
        if not clan_name:
            clan_name = f"clan_{tag.replace('#', '')}"

        application = await bot.rest.fetch_my_user()

        # Check for any existing emoji with the same NAME (not just same clan)
        print(f"[DEBUG] Checking for existing emojis with name: {clan_name}")
        try:
            existing_emojis = await bot.rest.fetch_application_emojis(application.id)
            for emoji in existing_emojis:
                if emoji.name.lower() == clan_name.lower():
                    print(f"[DEBUG] Found duplicate emoji name '{emoji.name}' (ID: {emoji.id}), deleting...")
                    try:
                        await bot.rest.delete_application_emoji(
                            application=application.id,
                            emoji=emoji.id
                        )
                        print(f"[DEBUG] Deleted duplicate emoji {emoji.id}")
                    except Exception as e:
                        print(f"[ERROR] Failed to delete duplicate emoji {emoji.id}: {e}")
        except Exception as e:
            print(f"[ERROR] Failed to fetch existing emojis: {e}")

        # Also delete old emoji for this specific clan if it exists
        old_mention = db_clan.emoji or ""
        match = re.search(r':(\d+)>$', old_mention)
        if match:
            old_id = int(match.group(1))
            # Only try to delete if it's different from any we already deleted
            try:
                await bot.rest.delete_application_emoji(
                    application=application.id,
                    emoji=old_id
                )
                print(f"[DEBUG] Deleted old clan emoji {old_id}")
            except hikari.NotFoundError:
                print(f"[DEBUG] Old emoji {old_id} not found (may have been already deleted)")
            except Exception as e:
                print(f"[DEBUG] Could not delete old emoji {old_id}: {e}")

        # Download and resize image
        def resize_and_compress_image(image_content, max_size=(128, 128), max_kb=256):
            image = Image.open(BytesIO(image_content))

            # Convert to RGBA if necessary
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            # Resize with high quality
            image.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Save as PNG with optimization
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)

            # If still too large, reduce quality
            if buffer.tell() / 1024 > max_kb:
                buffer = BytesIO()
                image.save(buffer, format="PNG", optimize=True, quality=85)

            return buffer.getvalue()

        # Download the image
        resp = requests.get(emoji_url)
        resp.raise_for_status()
        img_data = resize_and_compress_image(resp.content)

        # Upload to Discord
        new_emoji = await bot.rest.create_application_emoji(
            application=application.id,
            name=clan_name,
            image=img_data
        )
        print(f"[DEBUG] Created new emoji '{new_emoji.name}' (ID: {new_emoji.id})")

        # Update database
        await mongo.clans.update_one(
            {"tag": tag},
            {"$set": {"emoji": new_emoji.mention}}
        )

        # Success message
        success_components = [
            Container(
                accent_color=0x00FF00,  # Green
                components=[
                    Text(content="## ✅ Emoji Updated Successfully!"),
                    Separator(divider=True),
                    Text(content=(
                        f"**Clan:** {db_clan.name}\n"
                        f"**New Emoji:** {new_emoji.mention}\n"
                        f"**Emoji Name:** `:{clan_name}:`\n"
                        f"**Emoji ID:** `{new_emoji.id}`"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"back_to_clan_edit:{tag}",
                                label="← Back to Edit Menu",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=success_components)

    except Exception as e:
        error_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Emoji Upload Failed"),
                    Separator(divider=True),
                    Text(content=f"**Error:** {str(e)[:200]}"),
                    Text(content=(
                        "\n**Common Issues:**\n"
                        "• Image URL is invalid or inaccessible\n"
                        "• Image format not supported\n"
                        "• Discord API rate limit\n"
                        "• Bot doesn't have permission to create emojis\n"
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"update_emoji:{tag}",
                                label="← Try Again",
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"back_to_clan_edit:{tag}",
                                label="← Back to Edit Menu",
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=error_components)


@register_action("update_emoji_modal", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def update_emoji_modal(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    tag = action_id

    # Get modal input
    def get_val(cid: str) -> str:
        for row in ctx.interaction.components:
            for comp in row:
                if comp.custom_id == cid:
                    return comp.value
        return ""

    new_emoji_url = get_val("emoji_url")

    if not new_emoji_url:
        return await ctx.respond(
            "❌ Please provide an emoji URL.",
            ephemeral=True
        )

    # Get clan data
    raw = await mongo.clans.find_one({"tag": tag})
    if not raw:
        return await ctx.respond("❌ Clan not found!", ephemeral=True)

    db_clan = Clan(data=raw)

    # Process the emoji upload
    await process_emoji_upload(
        ctx=ctx,
        tag=tag,
        emoji_url=new_emoji_url,
        db_clan=db_clan,
        mongo=mongo,
        bot=bot
    )