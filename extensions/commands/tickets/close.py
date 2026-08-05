# extensions/commands/tickets/close.py
"""
Ticket deny/approve functionality
"""

import hikari
import lightbulb
from datetime import datetime, timezone
import asyncio

from utils.mongo import MongoClient
from utils.component_state import delete_state, get_state, insert_state
from extensions.commands.tickets import loader, ticket
from extensions.commands.tickets import resolve, store
from extensions.components import register_action
from utils.constants import RED_ACCENT
import re

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ModalActionRowBuilder as ModalActionRow,
)


def _status_write_warning(result, doc_id) -> str:
    """Return a recruiter-facing warning when a status update matched nothing.

    Mongo reports success on a zero-match update_one, so a write against a missing
    document silently no-ops while the channel rename further down still runs. That
    divergence is how live channels ended up carrying a ✅/❌ emoji with their ticket
    document still reading "open". The rename is deliberately still performed - the
    emoji is the signal recruiters actually read - but the mismatch is surfaced
    instead of being reported as success.
    """
    if getattr(result, "matched_count", 0):
        return ""
    return (
        f"\n\n⚠️ **Status was not recorded** — no ticket document matched `{doc_id}`. "
        f"The channel was still renamed; please report this to an admin."
    )


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
        ticket = await store.find_one(mongo, {
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
        await insert_state(mongo, {
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
        ticket = await store.find_one(mongo, {
            "type": "ticket",
            "channel_id": current_channel_id
        })

        if not ticket:
            await ctx.respond(
                "❌ This channel is not a ticket!"
            )
            return

        # Conditional: only transitions a ticket that is still open. See
        # store.transition - side effects run ONLY on a won outcome.
        result = await store.transition(
            mongo,
            ticket["_id"],
            to_status="approved",
            actor_id=ctx.user.id,
            actor_name=ctx.user.username,
            extra={"approved_at": store.utcnow(), "approved_by": ctx.user.id},
        )

        if result.outcome == store.LOST:
            content, rows = await resolve.offer_override(
                ctx, mongo,
                kind=resolve.KIND_APPROVE,
                current=result.doc,
                ticket_id=ticket["_id"],
                channel_id=ticket["channel_id"],
                user_id=ticket.get("user_id"),
            )
            await ctx.respond(content, components=rows)
            return

        # A missing document is a data error, not a race, and is handled exactly
        # as before: the channel is still marked, because the emoji is the signal
        # recruiters actually read, and the mismatch is surfaced instead.
        status_warning = "" if result.won else _status_write_warning(None, ticket["_id"])

        await resolve.apply_approval(
            bot, mongo, channel_id=ticket["channel_id"], actor_name=ctx.user.username
        )
        await ctx.respond(
            f"✅ Ticket approved for <@{ticket['user_id']}>!{status_warning}"
            f"{resolve.claim_note(result.doc, ctx.user.id)}"
        )
        return


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
@register_action("deny_fwa_default", no_return=True, requires_state=True)
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
    data = await get_state(mongo, action_id)
    if not data:
        await ctx.respond("❌ Session expired", ephemeral=True)
        return
    
    # Status FIRST, applicant message second. The message used to be sent before
    # this write, so two recruiters denying the same ticket in the same second
    # both succeeded and the applicant received two denials.
    result = await store.transition(
        mongo,
        data['ticket_id'],
        to_status="denied",
        actor_id=data['denier_id'],
        actor_name=data['denier_name'],
        extra={
            "denied_at": store.utcnow(),
            "denied_by": data['denier_id'],
            "denial_type": "fwa_default",
        },
    )

    if result.outcome == store.LOST:
        content, rows = await resolve.offer_override(
            ctx, mongo,
            kind=resolve.KIND_DENY_FWA,
            current=result.doc,
            ticket_id=data['ticket_id'],
            channel_id=data['channel_id'],
            user_id=data['user_id'],
        )
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(content=content, components=rows)
        return

    status_warning = "" if result.won else _status_write_warning(None, data['ticket_id'])

    await resolve.apply_denial(
        bot, mongo,
        kind=resolve.KIND_DENY_FWA,
        channel_id=data['channel_id'],
        user_id=data['user_id'],
        actor_name=data['denier_name'],
    )
    await delete_state(mongo, action_id)

    await ctx.interaction.edit_initial_response(
        content=f"✅ FWA default denial sent!{status_warning}"
                f"{resolve.claim_note(result.doc, ctx.user.id)}",
        component=None
    )


@register_action("deny_main_default", no_return=True, requires_state=True)
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
    data = await get_state(mongo, action_id)
    if not data:
        await ctx.respond("❌ Session expired", ephemeral=True)
        return
    
    # Status FIRST, applicant message second - see deny_fwa_default_handler.
    result = await store.transition(
        mongo,
        data['ticket_id'],
        to_status="denied",
        actor_id=data['denier_id'],
        actor_name=data['denier_name'],
        extra={
            "denied_at": store.utcnow(),
            "denied_by": data['denier_id'],
            "denial_type": "main_default",
        },
    )

    if result.outcome == store.LOST:
        content, rows = await resolve.offer_override(
            ctx, mongo,
            kind=resolve.KIND_DENY_MAIN,
            current=result.doc,
            ticket_id=data['ticket_id'],
            channel_id=data['channel_id'],
            user_id=data['user_id'],
        )
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(content=content, components=rows)
        return

    status_warning = "" if result.won else _status_write_warning(None, data['ticket_id'])

    await resolve.apply_denial(
        bot, mongo,
        kind=resolve.KIND_DENY_MAIN,
        channel_id=data['channel_id'],
        user_id=data['user_id'],
        actor_name=data['denier_name'],
    )
    await delete_state(mongo, action_id)

    await ctx.interaction.edit_initial_response(
        content=f"✅ Main default denial sent!{status_warning}"
                f"{resolve.claim_note(result.doc, ctx.user.id)}",
        component=None
    )


@register_action("deny_custom", no_return=True, opens_modal=True, requires_state=True)
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


@register_action("process_custom_denial", no_return=True, is_modal=True, requires_state=True)
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
    data = await get_state(mongo, action_id)
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
    
    # Status FIRST, applicant message second - see deny_fwa_default_handler.
    result = await store.transition(
        mongo,
        data['ticket_id'],
        to_status="denied",
        actor_id=data['denier_id'],
        actor_name=data['denier_name'],
        extra={
            "denied_at": store.utcnow(),
            "denied_by": data['denier_id'],
            "denial_type": "custom",
            "denial_reason": reason,
        },
    )

    if result.outcome == store.LOST:
        content, rows = await resolve.offer_override(
            ctx, mongo,
            kind=resolve.KIND_DENY_CUSTOM,
            current=result.doc,
            ticket_id=data['ticket_id'],
            channel_id=data['channel_id'],
            user_id=data['user_id'],
            reason=reason,
        )
        await delete_state(mongo, action_id)
        await ctx.respond(content, components=rows, ephemeral=True)
        return

    status_warning = "" if result.won else _status_write_warning(None, data['ticket_id'])

    await resolve.apply_denial(
        bot, mongo,
        kind=resolve.KIND_DENY_CUSTOM,
        channel_id=data['channel_id'],
        user_id=data['user_id'],
        actor_name=data['denier_name'],
        reason=reason,
    )
    await delete_state(mongo, action_id)

    await ctx.respond(
        f"✅ Custom denial sent!{status_warning}"
        f"{resolve.claim_note(result.doc, ctx.user.id)}",
        ephemeral=True
    )
