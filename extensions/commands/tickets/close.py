# extensions/commands/tickets/close.py
"""
Ticket deny/approve functionality
"""

import hikari
import lightbulb

from utils.mongo import MongoClient
from utils.component_state import delete_state, get_state, insert_state
from extensions.commands.tickets import ticket
from extensions.commands.tickets import perms, resolve, store
from extensions.components import register_action

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ModalActionRowBuilder as ModalActionRow,
)


async def _validate_denial_actor(ctx, mongo: MongoClient, data: dict) -> bool:
    """Fail closed unless the initiating recruiter is still acting."""
    if int(data.get("denier_id") or 0) != int(ctx.user.id):
        await ctx.respond("This denial session belongs to another recruiter.", ephemeral=True)
        return False
    if not await perms.is_recruiter(ctx.member, mongo):
        await ctx.respond("You are no longer authorized to deny tickets.", ephemeral=True)
        return False
    return True


@ticket.register()
class Deny(
    lightbulb.SlashCommand,
    name="deny",
    description="Deny the ticket in this channel (Admin/Recruiter only)"
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

        if not await perms.is_recruiter(ctx.member, mongo):
            await ctx.respond(
                "❌ Only recruiters and administrators can deny tickets."
            )
            return

        # Deny ticket in current channel
        current_channel_id = ctx.channel_id

        # Find ticket for this channel
        ticket = await store.find_by_location(mongo, current_channel_id)

        if not ticket:
            await ctx.respond(
                "❌ No ticket is linked to this channel."
            )
            return

        user_id = ticket.get("user_id")
        if not user_id:
            await ctx.respond(
                "❌ This ticket has no applicant Discord ID. Nothing was changed."
            )
            return

        # Store denial action data
        action_id = str(ctx.interaction.id)
        await insert_state(mongo, {
            "_id": action_id,
            "type": "deny_action",
            "ticket_id": ticket["_id"],
            "guild_id": int(ctx.guild_id or 0),
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
                    label="Use FWA default"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"deny_main_default:{action_id}",
                    label="Use Main default"
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"deny_custom:{action_id}",
                    label="Write custom reason"
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
    description="Approve the ticket in this channel (Admin/Recruiter only)"
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

        if not await perms.is_recruiter(ctx.member, mongo):
            await ctx.respond(
                "❌ Only recruiters and administrators can approve tickets."
            )
            return

        # Approve ticket in current channel
        current_channel_id = ctx.channel_id

        # Find ticket for this channel
        ticket = await store.find_by_location(mongo, current_channel_id)

        if not ticket:
            await ctx.respond(
                "❌ No ticket is linked to this channel."
            )
            return

        result = await resolve.approve_ticket(
            bot,
            mongo,
            ticket_id=ticket["_id"],
            member=ctx.member,
            actor_name=ctx.user.username,
        )

        if result.outcome == store.LOST:
            if (result.doc or {}).get("status") == "open":
                await ctx.respond(
                    "The ticket changed before approval finished. Run `/ticket approve` again."
                )
                return
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

        if result.outcome == store.MISSING:
            await ctx.respond("❌ The ticket record is missing. Nothing was changed.")
            return
        if result.outcome == store.BLOCKED:
            if result.blocker:
                await ctx.respond("⛔ Approval blocked: this applicant is blacklisted.")
            else:
                reason = result.reason or "Applicant identity is being updated; try again."
                await ctx.respond(f"⏳ Approval not completed: {reason}")
            return
        if result.outcome == store.UNAUTHORIZED:
            await ctx.respond("❌ You are no longer authorized to approve tickets.")
            return
        if result.outcome == store.EFFECT_FAILED:
            await ctx.respond(f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}")
            return
        await ctx.respond(
            f"✅ Ticket approved for <@{ticket['user_id']}>!"
        )
        return


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
    if not await _validate_denial_actor(ctx, mongo, data):
        return
    
    result = await resolve.deny_ticket(
        bot,
        mongo,
        ticket_id=data['ticket_id'],
        member=ctx.member,
        actor_name=ctx.user.username,
        kind=resolve.KIND_DENY_FWA,
    )

    if result.outcome == store.LOST:
        if (result.doc or {}).get("status") == "open":
            await delete_state(mongo, action_id)
            await ctx.interaction.edit_initial_response(
                content=(
                    "The ticket changed before denial finished. Run `/ticket deny` again."
                ),
                components=[],
            )
            return
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
    if result.outcome in {store.MISSING, store.UNAUTHORIZED}:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content="❌ Nothing changed: the ticket is missing or you are no longer authorized.",
            components=[],
        )
        return
    if result.outcome == store.EFFECT_FAILED:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}",
            components=[],
        )
        return
    await delete_state(mongo, action_id)

    await ctx.interaction.edit_initial_response(
        content="✅ Ticket denied with the FWA default message.",
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
    if not await _validate_denial_actor(ctx, mongo, data):
        return
    
    result = await resolve.deny_ticket(
        bot,
        mongo,
        ticket_id=data['ticket_id'],
        member=ctx.member,
        actor_name=ctx.user.username,
        kind=resolve.KIND_DENY_MAIN,
    )

    if result.outcome == store.LOST:
        if (result.doc or {}).get("status") == "open":
            await delete_state(mongo, action_id)
            await ctx.interaction.edit_initial_response(
                content=(
                    "The ticket changed before denial finished. Run `/ticket deny` again."
                ),
                components=[],
            )
            return
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
    if result.outcome in {store.MISSING, store.UNAUTHORIZED}:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content="❌ Nothing changed: the ticket is missing or you are no longer authorized.",
            components=[],
        )
        return
    if result.outcome == store.EFFECT_FAILED:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}",
            components=[],
        )
        return
    await delete_state(mongo, action_id)

    await ctx.interaction.edit_initial_response(
        content="✅ Ticket denied with the Main default message.",
        component=None
    )


@register_action(
    "deny_custom", no_return=True, opens_modal=True,
    requires_state=True, preload_state=False,
)
@lightbulb.di.with_di
async def deny_custom_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
):
    """Open modal for custom denial reason"""
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


@register_action(
    "process_custom_denial", no_return=True, is_modal=True, preload_state=False,
)
@lightbulb.di.with_di
async def process_custom_denial_handler(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    """Process custom denial modal"""
    # Modal submissions have their own three-second response deadline. This
    # action deliberately does not ask the dispatcher to load state first.
    await ctx.defer(ephemeral=True)
    # Get stored data
    envelope = await get_state(mongo, action_id, {
        "type": 1,
        "denier_id": 1,
        "guild_id": 1,
    })
    if not envelope or envelope.get("type") != "deny_action":
        await ctx.interaction.edit_initial_response(content="❌ Session expired")
        return
    denier_id = int(envelope.get("denier_id") or 0)
    if denier_id != int(ctx.user.id):
        await ctx.interaction.edit_initial_response(
            content="This denial session belongs to another recruiter."
        )
        return
    guild_id = int(envelope.get("guild_id") or 0)
    if not guild_id or int(getattr(ctx, "guild_id", 0) or 0) != guild_id:
        await ctx.interaction.edit_initial_response(content="❌ Session expired")
        return
    if not await perms.is_recruiter(ctx.member, mongo):
        await ctx.interaction.edit_initial_response(
            content="You are no longer authorized to deny tickets."
        )
        return
    data = await get_state(mongo, action_id)
    if (
        not data
        or data.get("type") != "deny_action"
        or int(data.get("denier_id") or 0) != denier_id
        or int(data.get("guild_id") or 0) != guild_id
    ):
        await ctx.interaction.edit_initial_response(content="❌ Session expired")
        return
    
    # Get denial reason from modal
    reason = ""
    for row in ctx.interaction.components:
        for comp in row:
            if comp.custom_id == "denial_reason":
                reason = comp.value.strip()
                break
    
    result = await resolve.deny_ticket(
        bot,
        mongo,
        ticket_id=data['ticket_id'],
        member=ctx.member,
        actor_name=ctx.user.username,
        kind=resolve.KIND_DENY_CUSTOM,
        reason=reason,
    )

    if result.outcome == store.LOST:
        if (result.doc or {}).get("status") == "open":
            await delete_state(mongo, action_id)
            await ctx.interaction.edit_initial_response(
                content=(
                    "The ticket changed before denial finished. Run `/ticket deny` again."
                )
            )
            return
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
        await ctx.interaction.edit_initial_response(content=content, components=rows)
        return
    if result.outcome in {store.MISSING, store.UNAUTHORIZED, store.BLOCKED}:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=(
                result.reason
                or "❌ Nothing changed: the ticket is missing or unauthorized."
            ),
        )
        return
    if result.outcome == store.EFFECT_FAILED:
        await delete_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(
            content=f"⚠️ {resolve.RESOLUTION_EFFECT_RETRY_MESSAGE}",
        )
        return
    await delete_state(mongo, action_id)

    await ctx.interaction.edit_initial_response(content="✅ Ticket denied with the custom message.")
