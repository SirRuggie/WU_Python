# extensions/commands/tickets/close.py
"""
Ticket closing functionality
"""

import hikari
import lightbulb
from datetime import datetime, timezone
import asyncio

from utils.mongo import MongoClient
from extensions.commands.tickets import loader, tickets


@tickets.register()
class Close(
    lightbulb.SlashCommand,
    name="close",
    description="Close a ticket (Admin/Recruiter only)"
):
    user = lightbulb.user(
        "user",
        "User whose ticket to close (optional - closes current channel if not specified)",
        default=None
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Close a ticket"""

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
                "❌ You must be a recruiter or administrator to close tickets!",
                ephemeral=True
            )
            return

        # Determine which ticket to close
        if self.user:
            # Close specific user's tickets
            user_id = self.user.id

            # Find all open tickets for this user
            tickets_to_close = await mongo.button_store.find({
                "type": "ticket",
                "user_id": user_id,
                "status": "open"
            }).to_list(length=None)

            if not tickets_to_close:
                await ctx.respond(
                    f"❌ No open tickets found for <@{user_id}>",
                    ephemeral=True
                )
                return

            # Close all their tickets
            for ticket in tickets_to_close:
                await mongo.button_store.update_one(
                    {"_id": ticket["_id"]},
                    {
                        "$set": {
                            "status": "closed",
                            "closed_at": datetime.now(timezone.utc),
                            "closed_by": ctx.user.id
                        }
                    }
                )

                # Rename the channel from ✅ to ❌
                try:
                    ticket_type = ticket.get("ticket_type", "main")
                    ticket_number = ticket.get("ticket_number", 0)
                    username = ticket.get("username", "unknown")
                    new_name = f"❌{ticket_type}-{ticket_number}-{username}"

                    await bot.rest.edit_channel(
                        ticket["channel_id"],
                        name=new_name,
                        reason=f"Ticket closed by {ctx.user.username}"
                    )
                except Exception as e:
                    print(f"[Tickets] Failed to rename channel {ticket.get('channel_id')}: {e}")

            await ctx.respond(
                f"✅ Closed {len(tickets_to_close)} ticket(s) for <@{user_id}>",
                ephemeral=True
            )

        else:
            # Close ticket in current channel
            current_channel_id = ctx.channel_id

            # Find ticket for this channel
            ticket = await mongo.button_store.find_one({
                "type": "ticket",
                "channel_id": current_channel_id,
                "status": "open"
            })

            if not ticket:
                await ctx.respond(
                    "❌ This channel is not an open ticket!",
                    ephemeral=True
                )
                return

            # Close the ticket
            await mongo.button_store.update_one(
                {"_id": ticket["_id"]},
                {
                    "$set": {
                        "status": "closed",
                        "closed_at": datetime.now(timezone.utc),
                        "closed_by": ctx.user.id
                    }
                }
            )

            # Rename the channel from ✅ to ❌
            try:
                ticket_type = ticket.get("ticket_type", "main")
                ticket_number = ticket.get("ticket_number", 0)
                username = ticket.get("username", "unknown")
                new_name = f"❌{ticket_type}-{ticket_number}-{username}"

                await bot.rest.edit_channel(
                    current_channel_id,
                    name=new_name,
                    reason=f"Ticket closed by {ctx.user.username}"
                )

                await ctx.respond(
                    "✅ Ticket closed! The channel has been marked as closed.",
                    ephemeral=False
                )
            except Exception as e:
                await ctx.respond(
                    f"✅ Ticket closed in database, but failed to rename channel: {str(e)}",
                    ephemeral=True
                )


@tickets.register()
class Reopen(
    lightbulb.SlashCommand,
    name="reopen",
    description="Reopen a closed ticket (Admin/Recruiter only)"
):
    user = lightbulb.user(
        "user",
        "User whose ticket to reopen (optional - reopens current channel if not specified)",
        default=None
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Reopen a ticket"""

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
                "❌ You must be a recruiter or administrator to reopen tickets!",
                ephemeral=True
            )
            return

        if self.user:
            # Reopen specific user's most recent closed ticket
            user_id = self.user.id

            # Find most recent closed ticket for this user
            ticket = await mongo.button_store.find_one({
                "type": "ticket",
                "user_id": user_id,
                "status": "closed"
            }, sort=[("closed_at", -1)])

            if not ticket:
                await ctx.respond(
                    f"❌ No closed tickets found for <@{user_id}>",
                    ephemeral=True
                )
                return

        else:
            # Reopen ticket in current channel
            current_channel_id = ctx.channel_id

            # Find ticket for this channel
            ticket = await mongo.button_store.find_one({
                "type": "ticket",
                "channel_id": current_channel_id,
                "status": "closed"
            })

            if not ticket:
                await ctx.respond(
                    "❌ This channel is not a closed ticket!",
                    ephemeral=True
                )
                return

        # Reopen the ticket
        await mongo.button_store.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "status": "open",
                    "reopened_at": datetime.now(timezone.utc),
                    "reopened_by": ctx.user.id
                }
            }
        )

        # Rename the channel from ❌ to ✅
        try:
            ticket_type = ticket.get("ticket_type", "main")
            ticket_number = ticket.get("ticket_number", 0)
            username = ticket.get("username", "unknown")
            new_name = f"✅{ticket_type}-{ticket_number}-{username}"

            await bot.rest.edit_channel(
                ticket["channel_id"],
                name=new_name,
                reason=f"Ticket reopened by {ctx.user.username}"
            )

            await ctx.respond(
                f"✅ Ticket reopened for <@{ticket['user_id']}>!",
                ephemeral=False
            )
        except Exception as e:
            await ctx.respond(
                f"✅ Ticket reopened in database, but failed to rename channel: {str(e)}",
                ephemeral=True
            )


# Add this to clean up orphaned tickets on startup
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def cleanup_orphaned_tickets(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Check for tickets where the channel no longer exists and mark them as closed"""

    # Wait a bit for bot to be fully ready
    await asyncio.sleep(5)

    # Find all open tickets
    open_tickets = await mongo.button_store.find({
        "type": "ticket",
        "status": "open"
    }).to_list(length=None)

    closed_count = 0

    for ticket in open_tickets:
        try:
            # Try to fetch the channel
            channel = await bot.rest.fetch_channel(ticket["channel_id"])

            # If channel exists but starts with ❌, mark ticket as closed
            if channel.name.startswith("❌"):
                await mongo.button_store.update_one(
                    {"_id": ticket["_id"]},
                    {
                        "$set": {
                            "status": "closed",
                            "closed_at": datetime.now(timezone.utc),
                            "closed_reason": "channel_marked_closed"
                        }
                    }
                )
                closed_count += 1

        except hikari.NotFoundError:
            # Channel doesn't exist, mark ticket as closed
            await mongo.button_store.update_one(
                {"_id": ticket["_id"]},
                {
                    "$set": {
                        "status": "closed",
                        "closed_at": datetime.now(timezone.utc),
                        "closed_reason": "channel_deleted"
                    }
                }
            )
            closed_count += 1
        except Exception:
            # Other errors, skip
            pass

    if closed_count > 0:
        print(f"[Tickets] Cleaned up {closed_count} orphaned tickets")