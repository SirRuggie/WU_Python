# extensions/commands/tickets/close.py
"""
Ticket deny/approve functionality
"""

import hikari
import lightbulb
from datetime import datetime, timezone
import asyncio

from utils.mongo import MongoClient
from extensions.commands.tickets import loader, ticket
from extensions.components import register_action
from utils.constants import RED_ACCENT
import re

# Import discord_skills for monitor cleanup
from extensions.events.message.ticket_automation.handlers import discord_skills

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ModalActionRowBuilder as ModalActionRow,
    SectionComponentBuilder as Section,
    ThumbnailComponentBuilder as Thumbnail,
)


def get_channel_name_with_new_emoji(channel_name: str, new_emoji: str) -> str:
    """Replace the emoji prefix in a channel name with a new emoji"""
    # Known ticket emojis to look for
    ticket_emojis = ["🆕", "❌", "✅"]

    # Check if the channel name starts with any of the ticket emojis
    for emoji in ticket_emojis:
        if channel_name.startswith(emoji):
            # Replace the old emoji with the new one
            return new_emoji + channel_name[len(emoji):]

    # If no emoji found, just prepend the new emoji (this shouldn't happen for tickets)
    return new_emoji + channel_name


@ticket.register()
class Deny(
    lightbulb.SlashCommand,
    name="deny",
    description="Deny the ticket in current channel (Admin/Recruiter only)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Deny a ticket"""

        # Defer the response immediately to avoid timeout
        await ctx.defer(ephemeral=True)

        # Get config to check roles
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        main_role = config.get("main_recruiter_role")
        fwa_role = config.get("fwa_recruiter_role")

        # Check if user is a recruiter or admin
        user_roles = ctx.member.role_ids
        is_authorized = (
                (main_role and main_role in user_roles) or
                (fwa_role and fwa_role in user_roles) or
                ctx.member.permissions & hikari.Permissions.ADMINISTRATOR
        )

        if not is_authorized:
            await ctx.respond(
                "❌ You must be a recruiter or administrator to deny tickets!"
            )
            return

        # Deny ticket in current channel
        current_channel_id = ctx.channel_id

        # Find ticket for this channel
        ticket = await mongo.button_store.find_one({
            "type": "ticket",
            "channel_id": current_channel_id
        })

        if not ticket:
            await ctx.respond(
                "❌ This channel is not a ticket!"
            )
            return

        # Get user_id from ticket_automation_state
        user_id = None
        try:
            automation_doc = await mongo.ticket_automation_state.find_one({"_id": str(current_channel_id)})
            if automation_doc and automation_doc.get("user_id"):
                user_id = automation_doc["user_id"]
        except Exception:
            pass
        
        # If not found in automation state, try to get from ticket
        if not user_id:
            user_id = ticket.get("user_id")
        
        if not user_id:
            await ctx.respond(
                "❌ Could not find the user associated with this ticket!"
            )
            return

        # Store denial action data
        action_id = str(ctx.interaction.id)
        await mongo.button_store.insert_one({
            "_id": action_id,
            "type": "deny_action",
            "ticket_id": ticket["_id"],
            "channel_id": current_channel_id,
            "user_id": user_id,
            "denier_id": ctx.user.id,
            "denier_name": ctx.user.username
        })

        # Show denial options
        row = ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"deny_fwa_default:{action_id}",
                    label="FWA Default Deny"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"deny_main_default:{action_id}",
                    label="Main Default Deny"
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"deny_custom:{action_id}",
                    label="Custom Deny"
                )
            ]
        )
        
        await ctx.respond(
            "Select a denial option:",
            components=[row],
            ephemeral=True
        )


@ticket.register()
class Approve(
    lightbulb.SlashCommand,
    name="approve",
    description="Approve the ticket in current channel (Admin/Recruiter only)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Approve a ticket"""

        # Defer the response immediately to avoid timeout
        await ctx.defer(ephemeral=True)

        # Get config to check roles
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        main_role = config.get("main_recruiter_role")
        fwa_role = config.get("fwa_recruiter_role")

        # Check if user is a recruiter or admin
        user_roles = ctx.member.role_ids
        is_authorized = (
                (main_role and main_role in user_roles) or
                (fwa_role and fwa_role in user_roles) or
                ctx.member.permissions & hikari.Permissions.ADMINISTRATOR
        )

        if not is_authorized:
            await ctx.respond(
                "❌ You must be a recruiter or administrator to approve tickets!"
            )
            return

        # Approve ticket in current channel
        current_channel_id = ctx.channel_id

        # Find ticket for this channel
        ticket = await mongo.button_store.find_one({
            "type": "ticket",
            "channel_id": current_channel_id
        })

        if not ticket:
            await ctx.respond(
                "❌ This channel is not a ticket!"
            )
            return

        # Approve the ticket
        await mongo.button_store.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "status": "approved",
                    "approved_at": datetime.now(timezone.utc),
                    "approved_by": ctx.user.id
                }
            }
        )

        # Stop discord skills monitor if active
        try:
            await mongo.ticket_automation_state.update_one(
                {"_id": str(current_channel_id)},
                {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}}
            )
            await discord_skills.cleanup_monitor(current_channel_id)
        except Exception as e:
            print(f"[TicketApprove] Error stopping monitor: {e}")

        # Rename the channel to have ✅ prefix
        try:
            channel = await bot.rest.fetch_channel(ticket["channel_id"])
            new_name = get_channel_name_with_new_emoji(channel.name, "✅")

            await bot.rest.edit_channel(
                ticket["channel_id"],
                name=new_name,
                reason=f"Ticket approved by {ctx.user.username}"
            )

            # Small delay to respect rate limits (matching the deny command)
            await asyncio.sleep(1)

            # Get user_id from ticket_automation_state to send congratulations
            try:
                automation_doc = await mongo.ticket_automation_state.find_one({"_id": str(current_channel_id)})
                if automation_doc and automation_doc.get("user_id"):
                    user_id = automation_doc["user_id"]
                    
                    # Send congratulations message in the channel
                    await bot.rest.create_message(
                        channel=current_channel_id,
                        content=f"<@{user_id}> Congratulations on being accepted to Warriors United! Stand by for further instructions.",
                        user_mentions=[user_id]
                    )
                    print(f"[Tickets] Sent congratulations message to user {user_id}")
                else:
                    print(f"[Tickets] No automation doc found for channel {current_channel_id}, skipping congratulations message")
            except Exception as e:
                print(f"[Tickets] Failed to send congratulations message: {e}")

            await ctx.respond(
                f"✅ Ticket approved for <@{ticket['user_id']}>!"
            )
        except Exception as e:
            await ctx.respond(
                f"✅ Ticket approved in database, but failed to rename channel: {str(e)}"
            )


# # DISABLED - Orphaned ticket cleanup causing rate limit issues with hundreds of channels
# # This was checking all open tickets on startup, but with hundreds of channels it causes
# # excessive API calls and rate limit warnings. Tickets should be closed properly through commands.
# @loader.listener(hikari.StartedEvent)
# @lightbulb.di.with_di
# async def cleanup_orphaned_tickets(
#         event: hikari.StartedEvent,
#         mongo: MongoClient = lightbulb.di.INJECTED,
#         bot: hikari.GatewayBot = lightbulb.di.INJECTED,
# ) -> None:
#     """Check for tickets where the channel no longer exists and mark them as denied"""
#
#     # Wait a bit for bot to be fully ready
#     await asyncio.sleep(10)  # Increased from 5 to 10 seconds
#
#     print(f"[Tickets] Starting orphaned ticket cleanup...")
#
#     # Find all open tickets
#     open_tickets = await mongo.button_store.find({
#         "type": "ticket",
#         "status": "open"
#     }).to_list(length=None)
#
#     print(f"[Tickets] Found {len(open_tickets)} open tickets to check")
#
#     closed_count = 0
#     checked_count = 0
#
#     for i, ticket in enumerate(open_tickets):
#         # Add longer delay every 5 tickets to avoid rate limits
#         if i > 0 and i % 5 == 0:
#             print(f"[Tickets] Checked {i}/{len(open_tickets)} tickets, pausing 5s to avoid rate limits...")
#             await asyncio.sleep(5)
#         
#         checked_count += 1
#         
#         try:
#             # Try to fetch the channel
#             channel = await bot.rest.fetch_channel(ticket["channel_id"])
#
#             # Increase delay between checks from 0.5 to 2 seconds
#             await asyncio.sleep(2)
#
#             # If channel exists but starts with ❌, mark ticket as denied
#             if channel.name.startswith("❌"):
#                 await mongo.button_store.update_one(
#                     {"_id": ticket["_id"]},
#                     {
#                         "$set": {
#                             "status": "denied",
#                             "denied_at": datetime.now(timezone.utc),
#                             "denied_reason": "channel_marked_denied"
#                         }
#                     }
#                 )
#                 closed_count += 1
#             # If channel exists but starts with ✅, mark ticket as approved
#             elif channel.name.startswith("✅"):
#                 await mongo.button_store.update_one(
#                     {"_id": ticket["_id"]},
#                     {
#                         "$set": {
#                             "status": "approved",
#                             "approved_at": datetime.now(timezone.utc),
#                             "approved_reason": "channel_marked_approved"
#                         }
#                     }
#                 )
#                 closed_count += 1
#
#         except hikari.NotFoundError:
#             # Channel doesn't exist, mark ticket as denied
#             await mongo.button_store.update_one(
#                 {"_id": ticket["_id"]},
#                 {
#                     "$set": {
#                         "status": "denied",
#                         "denied_at": datetime.now(timezone.utc),
#                         "denied_reason": "channel_deleted"
#                     }
#                 }
#             )
#             closed_count += 1
#         except Exception:
#             # Other errors, skip
#             pass
#
#     print(f"[Tickets] Cleanup complete: checked {checked_count} tickets, cleaned up {closed_count} orphaned tickets")


# Denial action handlers
@register_action("deny_fwa_default", no_return=True)
@lightbulb.di.with_di
async def deny_fwa_default_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle FWA default denial"""
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("❌ Session expired", ephemeral=True)
        return
    
    # Build denial message
    denial_components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{data['user_id']}>, we regret to inform you that currently your application has been denied.\n\n"
                            f"## **Reason:**\n"
                            f"I am sorry but unfortunately, you do not meet the criteria for Warriors United. Here's a resource link to other FWA Clans that may have a spot for you.\n\n"
                            f"https://band.us/@reqfwa\n\n"
                            f"Good luck!"
                        ))
                    ],
                    accessory=Thumbnail(media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753271403/misc_images/Denied.png")
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]
    
    # Send denial message
    await bot.rest.create_message(
        channel=data['channel_id'],
        components=denial_components,
        user_mentions=[int(data['user_id'])]
    )
    
    # Update ticket status
    await mongo.button_store.update_one(
        {"_id": data['ticket_id']},
        {
            "$set": {
                "status": "denied",
                "denied_at": datetime.now(timezone.utc),
                "denied_by": data['denier_id'],
                "denial_type": "fwa_default"
            }
        }
    )

    # Stop discord skills monitor if active
    try:
        await mongo.ticket_automation_state.update_one(
            {"_id": str(data['channel_id'])},
            {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}}
        )
        await discord_skills.cleanup_monitor(data['channel_id'])
    except Exception as e:
        print(f"[TicketDeny] Error stopping monitor: {e}")

    # Rename channel
    try:
        channel = await bot.rest.fetch_channel(data['channel_id'])
        new_name = get_channel_name_with_new_emoji(channel.name, "❌")
        await bot.rest.edit_channel(
            data['channel_id'],
            name=new_name,
            reason=f"Ticket denied by {data['denier_name']}"
        )
    except Exception:
        pass
    
    # Clean up action data
    await mongo.button_store.delete_one({"_id": action_id})
    
    await ctx.interaction.edit_initial_response(
        content="✅ FWA default denial sent!",
        component=None
    )


@register_action("deny_main_default", no_return=True)
@lightbulb.di.with_di
async def deny_main_default_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Handle Main default denial"""
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("❌ Session expired", ephemeral=True)
        return
    
    # Build denial message
    denial_components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{data['user_id']}>, we regret to inform you that currently your application has been denied.\n\n"
                            f"## **Reason:**\n"
                            f"I am sorry but unfortunately, you do not meet the criteria for Warriors United. Here's a resource link to other Clans that may have a spot for you.\n\n"
                            f"https://discord.com/invite/clashofclans\n\n"
                            f"Good luck!"
                        ))
                    ],
                    accessory=Thumbnail(media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753271403/misc_images/Denied.png")
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]
    
    # Send denial message
    await bot.rest.create_message(
        channel=data['channel_id'],
        components=denial_components,
        user_mentions=[int(data['user_id'])]
    )
    
    # Update ticket status
    await mongo.button_store.update_one(
        {"_id": data['ticket_id']},
        {
            "$set": {
                "status": "denied",
                "denied_at": datetime.now(timezone.utc),
                "denied_by": data['denier_id'],
                "denial_type": "main_default"
            }
        }
    )

    # Stop discord skills monitor if active
    try:
        await mongo.ticket_automation_state.update_one(
            {"_id": str(data['channel_id'])},
            {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}}
        )
        await discord_skills.cleanup_monitor(data['channel_id'])
    except Exception as e:
        print(f"[TicketDeny] Error stopping monitor: {e}")

    # Rename channel
    try:
        channel = await bot.rest.fetch_channel(data['channel_id'])
        new_name = get_channel_name_with_new_emoji(channel.name, "❌")
        await bot.rest.edit_channel(
            data['channel_id'],
            name=new_name,
            reason=f"Ticket denied by {data['denier_name']}"
        )
    except Exception:
        pass
    
    # Clean up action data
    await mongo.button_store.delete_one({"_id": action_id})
    
    await ctx.interaction.edit_initial_response(
        content="✅ Main default denial sent!",
        component=None
    )


@register_action("deny_custom", no_return=True, opens_modal=True)
@lightbulb.di.with_di
async def deny_custom_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    """Open modal for custom denial reason"""
    # Create modal for denial reason
    reason_input = ModalActionRow().add_text_input(
        "denial_reason",
        "Denial Reason",
        placeholder="Please provide a clear reason for the denial",
        required=True,
        style=hikari.TextInputStyle.PARAGRAPH,
        min_length=5,
        max_length=1000
    )
    
    await ctx.interaction.create_modal_response(
        title="Custom Denial Reason",
        custom_id=f"process_custom_denial:{action_id}",
        components=[reason_input]
    )


@register_action("process_custom_denial", no_return=True, is_modal=True)
@lightbulb.di.with_di
async def process_custom_denial_handler(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Process custom denial modal"""
    # Get stored data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.respond("❌ Session expired", ephemeral=True)
        return
    
    # Get denial reason from modal
    reason = ""
    for row in ctx.interaction.components:
        for comp in row:
            if comp.custom_id == "denial_reason":
                reason = comp.value.strip()
                break
    
    # Build denial message
    denial_components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{data['user_id']}>, we regret to inform you that currently your application has been denied.\n\n"
                            f"## **Reason:**\n{reason}"
                        ))
                    ],
                    accessory=Thumbnail(media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753271403/misc_images/Denied.png")
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")])
            ]
        )
    ]
    
    # Send denial message
    await bot.rest.create_message(
        channel=data['channel_id'],
        components=denial_components,
        user_mentions=[int(data['user_id'])]
    )
    
    # Update ticket status
    await mongo.button_store.update_one(
        {"_id": data['ticket_id']},
        {
            "$set": {
                "status": "denied",
                "denied_at": datetime.now(timezone.utc),
                "denied_by": data['denier_id'],
                "denial_type": "custom",
                "denial_reason": reason
            }
        }
    )

    # Stop discord skills monitor if active
    try:
        await mongo.ticket_automation_state.update_one(
            {"_id": str(data['channel_id'])},
            {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}}
        )
        await discord_skills.cleanup_monitor(data['channel_id'])
    except Exception as e:
        print(f"[TicketDeny] Error stopping monitor: {e}")

    # Rename channel
    try:
        channel = await bot.rest.fetch_channel(data['channel_id'])
        new_name = get_channel_name_with_new_emoji(channel.name, "❌")
        await bot.rest.edit_channel(
            data['channel_id'],
            name=new_name,
            reason=f"Ticket denied by {data['denier_name']}"
        )
    except Exception:
        pass
    
    # Clean up action data
    await mongo.button_store.delete_one({"_id": action_id})
    
    await ctx.respond(
        "✅ Custom denial sent!",
        ephemeral=True
    )