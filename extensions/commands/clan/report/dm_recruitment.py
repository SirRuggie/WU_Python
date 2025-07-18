# commands/clan/report/dm_recruitment.py

"""DM recruitment reporting functionality with event-based image handling"""

import hikari
import lightbulb
import asyncio
from datetime import datetime
from typing import Dict

loader = lightbulb.Loader()

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ModalActionRowBuilder as ModalActionRow,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
    LinkButtonBuilder as LinkButton
)

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.classes import Clan
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, MAGENTA_ACCENT, RED_ACCENT

from .helpers import (
    get_clan_options,
    create_progress_header,
    validate_discord_id,
    create_submission_data,
    get_clan_by_tag,
    APPROVAL_CHANNEL,
    RECRUITMENT_PING
)

# Temporary storage for DM recruitment data
dm_recruitment_data: Dict[str, dict] = {}

# Image collection sessions - exported for event listener
image_collection_sessions: Dict[str, dict] = {}


# ╔══════════════════════════════════════════════════════════╗
# ║          Show DM Recruitment Flow (Step 1)               ║
# ╚══════════════════════════════════════════════════════════╝

@lightbulb.di.with_di
async def show_dm_recruitment_flow(
        ctx: lightbulb.components.MenuContext,
        user_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED
):
    """Show the DM recruitment reporting flow - Step 1: Clan Selection"""
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=create_progress_header(1, 3, ["Select Clan", "Enter Details", "Review"])),
                Separator(),

                Text(content="## 🏰 Select Your Clan"),
                Text(content="Which clan recruited the new member?"),

                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"dm_select_clan:{user_id}",
                            placeholder="Choose a clan...",
                            options=await get_clan_options(mongo)
                        )
                    ]
                ),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Cancel",
                            emoji="❌",
                            custom_id=f"cancel_report:{user_id}"
                        )
                    ]
                ),

                Text(content="-# Select the clan where you recruited a member via DM"),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        )
    ]

    await ctx.respond(components=components, edit=True)


# Handler to restart DM recruitment flow
@register_action("show_dm_recruitment")
@lightbulb.di.with_di
async def restart_dm_recruitment(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Restart the DM recruitment flow"""
    user_id = action_id
    return await show_dm_recruitment_flow(ctx, user_id, mongo)


# ╔══════════════════════════════════════════════════════════╗
# ║           DM Recruitment Clan Selection (Step 2)          ║
# ╚══════════════════════════════════════════════════════════╝

@register_action("dm_select_clan", no_return=True, opens_modal=True)
@lightbulb.di.with_di
async def dm_select_clan(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle clan selection for DM recruitment"""
    user_id = action_id
    selected_clan = ctx.interaction.values[0]

    # Create modal for recruitment details
    discord_id_input = ModalActionRow().add_text_input(
        "discord_id",
        "Discord User ID of Recruited Member",
        placeholder="e.g., 123456789012345678",
        required=True,
        min_length=17,
        max_length=19
    )

    context_input = ModalActionRow().add_text_input(
        "context",
        "How/Where did you recruit them?",
        placeholder="Describe where you found them and the context\n(e.g., 'From Reddit COC subreddit')",
        required=True,
        style=hikari.TextInputStyle.PARAGRAPH,
        max_length=200
    )

    await ctx.respond_with_modal(
        title="DM Recruitment Details",
        custom_id=f"dm_submit_details:{selected_clan}_{user_id}",
        components=[discord_id_input, context_input]
    )


# ╔══════════════════════════════════════════════════════════╗
# ║         DM Recruitment Details Submission (Step 3)       ║
# ╚══════════════════════════════════════════════════════════╝

@register_action("dm_submit_details", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def dm_submit_details(
        ctx: lightbulb.components.ModalContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Process DM recruitment details and prompt for screenshot"""
    print(f"[DEBUG] dm_submit_details called with action_id: {action_id}")

    parts = action_id.split("_")
    clan_tag = parts[0]
    user_id = parts[1]

    discord_id = ""
    context = ""

    for row in ctx.interaction.components:
        for comp in row:
            if comp.custom_id == "discord_id":
                discord_id = comp.value.strip()
            elif comp.custom_id == "context":
                context = comp.value.strip()

    # Always use DEFERRED_MESSAGE_UPDATE for consistent response handling
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    # Handle validation errors by updating the message with error info
    if not validate_discord_id(discord_id):
        error_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Invalid Discord ID"),
                    Text(content="Please enter a valid 17-19 digit Discord user ID."),
                    Separator(),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                label="Try Again",
                                emoji="🔄",
                                custom_id=f"show_dm_recruitment:{user_id}"
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Cancel",
                                emoji="❌",
                                custom_id=f"cancel_report:{user_id}"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=error_components)
        return

    clan = await get_clan_by_tag(mongo, clan_tag)
    if not clan:
        error_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Clan Not Found"),
                    Text(content="The selected clan could not be found. Please try again."),
                    Separator(),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.PRIMARY,
                                label="Start Over",
                                emoji="🔄",
                                custom_id=f"show_dm_recruitment:{user_id}"
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                label="Cancel",
                                emoji="❌",
                                custom_id=f"cancel_report:{user_id}"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=error_components)
        return

    # Create session for image collection
    session_key = f"{clan_tag}_{user_id}_{int(datetime.now().timestamp())}"

    # Show image upload prompt components
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=create_progress_header(2.5, 3, ["Select Clan", "Enter Details", "Review"])),
                Separator(),

                Text(content="## 📸 **Show Your Proof of Recruitment!**"),
                Text(content=(
                    "**What to do:**\n"
                    "1. Take a screenshot of your DM where you talked to the recruit.\n"
                    "2. Send the screenshot in this chat as your **next message**.\n"
                    "3. That's it! The bot will see it and handle the rest."
                )),
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),
                Text(content=(
                    "⏳ **You have 2 minutes!**\n"
                    "🧼 Don't worry, the bot will clean up your message after."
                )),
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Cancel",
                            emoji="❌",
                            custom_id=f"cancel_report:{user_id}"
                        )
                    ]
                ),

                Text(content="-# The bot is now waiting for your screenshot upload"),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            ]
        )
    ]

    # Update the original message with upload instructions
    await ctx.interaction.edit_initial_response(components=components)

    # Store session data with the message ID of the UPDATED message
    image_collection_sessions[session_key] = {
        "discord_id": discord_id,
        "context": context,
        "channel_id": ctx.channel_id,
        "user_id": int(user_id),
        "clan": clan,
        "timestamp": datetime.now(),
        "upload_prompt_message_id": ctx.interaction.message.id  # This is the same message we just updated
    }

    print(f"[DEBUG] Stored message ID: {ctx.interaction.message.id}")

    # Also store in MongoDB for persistence
    await mongo.button_store.insert_one({
        "_id": f"dm_upload_{session_key}",
        "message_id": ctx.interaction.message.id,
        "channel_id": ctx.channel_id,
        "session_key": session_key
    })


# ╔══════════════════════════════════════════════════════════╗
# ║              Review Screen Functions                     ║
# ╚══════════════════════════════════════════════════════════╝

async def show_dm_review(ctx: lightbulb.components.MenuContext, session_key: str, user_id: str, mongo: MongoClient):
    """Show review screen from button context"""
    parts = session_key.split("_")
    clan_tag = parts[0]

    clan = await get_clan_by_tag(mongo, clan_tag)
    data = dm_recruitment_data[session_key]

    review_components = create_review_components(clan, data, session_key, user_id)

    # Use DEFERRED_MESSAGE_UPDATE for button interactions
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    await ctx.interaction.edit_initial_response(components=review_components)


async def show_dm_review_in_channel(bot: hikari.GatewayBot, session_key: str, user_id: str, channel_id: int,
                                    mongo: MongoClient):
    """Update the upload prompt message with review screen"""
    parts = session_key.split("_")
    clan_tag = parts[0]

    clan = await get_clan_by_tag(mongo, clan_tag)
    data = dm_recruitment_data[session_key]

    review_components = create_review_components(clan, data, session_key, user_id)

    # Get the upload prompt message ID from session
    session_data = image_collection_sessions.get(session_key, {})
    upload_message_id = session_data.get("upload_prompt_message_id")

    if not upload_message_id:
        # Try to get from MongoDB as backup
        stored_data = await mongo.button_store.find_one({"_id": f"dm_upload_{session_key}"})
        if stored_data:
            upload_message_id = stored_data.get("message_id")

    if upload_message_id:
        try:
            # Edit the upload prompt message with the review form
            # This is NOT using DEFERRED_MESSAGE_UPDATE because it's from an event, not an interaction
            await bot.rest.edit_message(
                channel=channel_id,
                message=upload_message_id,
                components=review_components
            )
            print(f"[SUCCESS] Updated upload prompt message {upload_message_id} with review form")

            # Clean up MongoDB storage
            await mongo.button_store.delete_one({"_id": f"dm_upload_{session_key}"})

            # Start auto-cleanup timer (5 minutes)
            async def auto_cleanup():
                await asyncio.sleep(300)  # 5 minutes
                # Check if the session still exists (hasn't been submitted)
                if session_key in dm_recruitment_data:
                    try:
                        await bot.rest.delete_message(
                            channel=channel_id,
                            message=upload_message_id
                        )
                        # Clean up data
                        del dm_recruitment_data[session_key]
                        print(f"[AUTO-CLEANUP] Deleted review message after 5 minutes: {upload_message_id}")
                    except:
                        pass  # Message already deleted or other error

            # Start the cleanup task
            asyncio.create_task(auto_cleanup())

        except Exception as e:
            print(f"[ERROR] Failed to edit message {upload_message_id}: {e}")
            # Fallback: create new message
            new_msg = await bot.rest.create_message(
                channel=channel_id,
                components=review_components
            )

            # Start auto-cleanup timer for the new message
            async def auto_cleanup_new():
                await asyncio.sleep(300)  # 5 minutes
                if session_key in dm_recruitment_data:
                    try:
                        await bot.rest.delete_message(
                            channel=channel_id,
                            message=new_msg.id
                        )
                        del dm_recruitment_data[session_key]
                        print(f"[AUTO-CLEANUP] Deleted review message after 5 minutes: {new_msg.id}")
                    except:
                        pass

            asyncio.create_task(auto_cleanup_new())
    else:
        print(f"[WARNING] No upload message ID found, creating new message")
        new_msg = await bot.rest.create_message(
            channel=channel_id,
            components=review_components
        )

        # Start auto-cleanup timer
        async def auto_cleanup_fallback():
            await asyncio.sleep(300)  # 5 minutes
            if session_key in dm_recruitment_data:
                try:
                    await bot.rest.delete_message(
                        channel=channel_id,
                        message=new_msg.id
                    )
                    del dm_recruitment_data[session_key]
                    print(f"[AUTO-CLEANUP] Deleted review message after 5 minutes: {new_msg.id}")
                except:
                    pass

        asyncio.create_task(auto_cleanup_fallback())


# ╔══════════════════════════════════════════════════════════╗
# ║            Cancel Review Handler                         ║
# ╚══════════════════════════════════════════════════════════╝

@register_action("dm_cancel_review", no_return=True)
@lightbulb.di.with_di
async def dm_cancel_review(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Cancel the review and delete the message"""
    parts = action_id.split("_")
    session_key = "_".join(parts[:-1])  # Reconstruct session key
    user_id = parts[-1]

    # Clean up data
    if session_key in dm_recruitment_data:
        del dm_recruitment_data[session_key]

    try:
        # Delete the message
        await bot.rest.delete_message(
            channel=ctx.channel_id,
            message=ctx.interaction.message.id
        )
        print(f"[CANCEL] User {user_id} cancelled DM recruitment review")
    except Exception as e:
        print(f"[ERROR] Failed to delete message on cancel: {e}")
        # If deletion fails, at least update it to show cancelled
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
        cancelled_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Submission Cancelled"),
                    Text(content="This DM recruitment submission has been cancelled."),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=cancelled_components)


def create_review_components(clan: Clan, data: dict, session_key: str, user_id: str) -> list:
    """Create review screen components"""
    review_components = [
        Text(content=create_progress_header(3, 3, ["Select Clan", "Enter Details", "Review"])),
        Separator(),

        Text(content="## 📋 Review Your Submission"),

        Section(
            components=[
                Text(content=(
                    f"**Clan:** {clan.emoji if clan.emoji else ''} {clan.name}\n"
                    f"**Type:** DM Recruitment\n"
                    f"**Points to Award:** 1"
                ))
            ],
            accessory=Thumbnail(
                media=clan.logo if clan.logo else "https://cdn-icons-png.flaticon.com/512/845/845665.png"
            )
        ),

        Separator(),

        Text(content=(
            f"**📋 Recruitment Details:**\n"
            f"**Recruited User:** <@{data['discord_id']}>\n"
            f"**Context:** {data['context']}"
        )),
    ]

    # Add screenshot if available
    if data.get('screenshot_url'):
        review_components.extend([
            Separator(),
            Text(content="**📸 Screenshot:**"),
            Media(items=[MediaItem(media=data['screenshot_url'])])
        ])
    else:
        review_components.append(
            Text(content="-# No screenshot provided")
        )

    # Add action buttons - only Submit and Cancel
    review_components.extend([
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    label="Submit for Approval",
                    emoji="✅",
                    custom_id=f"dm_confirm_submit:{session_key}"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    label="Cancel",
                    emoji="❌",
                    custom_id=f"dm_cancel_review:{session_key}_{user_id}"
                )
            ]
        ),

        Text(content="-# Your submission will be reviewed by leadership"),
        Text(content="-# This message will auto-delete in 5 minutes if not submitted"),
        Media(items=[MediaItem(media="assets/Green_Footer.png")])
    ])

    # Return wrapped in container
    return [
        Container(
            accent_color=GREEN_ACCENT,
            components=review_components
        )
    ]


# ╔══════════════════════════════════════════════════════════╗
# ║            Confirm Submission Handler                    ║
# ╚══════════════════════════════════════════════════════════╝

@register_action("dm_confirm_submit", no_return=True)
@lightbulb.di.with_di
async def dm_confirm_submission(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Finalize DM recruitment submission and send to approval"""
    session_key = action_id

    if session_key not in dm_recruitment_data:
        await ctx.respond("❌ Error: Session expired. Please start over.", ephemeral=True)
        return

    data = dm_recruitment_data[session_key]
    parts = session_key.split("_")
    clan_tag = parts[0]
    user_id = parts[1]

    clan = await get_clan_by_tag(mongo, clan_tag)
    if not clan:
        await ctx.respond("❌ Error: Clan not found!", ephemeral=True)
        return

    try:
        approval_data = await create_submission_data(
            submission_type="DM Recruitment",
            clan=clan,
            user=ctx.user,
            discord_id=data['discord_id'],
            context=data['context'],
            screenshot_url=data.get('screenshot_url')
        )

        approval_components_list = [
            Text(content=f"<@&{RECRUITMENT_PING}>"),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            Text(content="## 🔔 Clan Points Submission"),

            Section(
                components=[
                    Text(content=(
                        f"**Submitted by:** {approval_data['user_mention']}\n"
                        f"**Clan:** {approval_data['clan_name']}\n"
                        f"**Type:** DM Recruitment\n"
                        f"**Time:** <t:{approval_data['timestamp']}:R>"
                    ))
                ],
                accessory=Thumbnail(media=approval_data['clan_logo'])
            ),

            Separator(),

            Text(content=(
                f"**📋 Recruitment Details:**\n"
                f"**Recruited User:** <@{data['discord_id']}>\n"
                f"**Context:** {data['context']}"
            )),
        ]

        if data.get('screenshot_url'):
            approval_components_list.extend([
                Separator(),
                Text(content="**📸 Screenshot Evidence:**"),
                Media(items=[MediaItem(media=data['screenshot_url'])])
            ])

        approval_components_list.extend([
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SUCCESS,
                        label="Approve",
                        emoji="✅",
                        custom_id=f"approve_points:dm_recruit_{clan_tag}_{user_id}"
                    ),
                    Button(
                        style=hikari.ButtonStyle.DANGER,
                        label="Deny",
                        emoji="❌",
                        custom_id=f"deny_points:dm_recruit_{clan_tag}_{user_id}"
                    )
                ]
            ),
            Media(items=[MediaItem(media="assets/Purple_Footer.png")])
        ])

        approval_components = [
            Container(
                accent_color=MAGENTA_ACCENT,
                components=approval_components_list
            )
        ]

        # Send to approval channel
        await bot.rest.create_message(
            channel=APPROVAL_CHANNEL,
            components=approval_components,
            role_mentions=True
        )

        # Clean up data
        del dm_recruitment_data[session_key]

        # Delete the review message (the one with the Submit button)
        await bot.rest.delete_message(
            channel=ctx.channel_id,
            message=ctx.interaction.message.id
        )

        success_components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Submission Sent!"),
                    Text(content=(
                        f"Your DM recruitment submission for **{clan.name}** has been sent for approval.\n\n"
                        "You'll receive a DM once it's been reviewed by leadership."
                    )),
                    Media(items=[MediaItem(media="assets/Green_Footer.png")])
                ]
            )
        ]

        # Manually respond with ephemeral message
        await ctx.respond(components=success_components, ephemeral=True)

    except Exception as e:
        import traceback
        print(f"[ERROR] Failed to submit for approval: {e}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")

        # Respond with ephemeral error message (don't reference approval_components)
        await ctx.respond(
            f"❌ Error submitting for approval: {str(e)[:200]}\n\nPlease try again or contact an administrator.",
            ephemeral=True
        )


# ╔══════════════════════════════════════════════════════════╗
# ║            Cancel Review Handler                         ║
# ╚══════════════════════════════════════════════════════════╝

@register_action("dm_cancel_review", no_return=True)
@lightbulb.di.with_di
async def dm_cancel_review(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
):
    """Cancel the review and delete the message"""
    parts = action_id.split("_")
    session_key = "_".join(parts[:-1])  # Reconstruct session key
    user_id = parts[-1]

    # Clean up data
    if session_key in dm_recruitment_data:
        del dm_recruitment_data[session_key]

    try:
        # Delete the message
        await bot.rest.delete_message(
            channel=ctx.channel_id,
            message=ctx.interaction.message.id
        )
        print(f"[CANCEL] User {user_id} cancelled DM recruitment review")
    except Exception as e:
        print(f"[ERROR] Failed to delete message on cancel: {e}")
        # If deletion fails, at least update it to show cancelled
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
        cancelled_components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Submission Cancelled"),
                    Text(content="This DM recruitment submission has been cancelled."),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=cancelled_components)