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
import re


def get_channel_name_with_new_emoji(channel_name: str, new_emoji: str) -> str:
    """Replace the emoji prefix in a channel name with a new emoji"""
    # Common ticket emojis to look for
    ticket_emojis = ["🆕", "❌", "✅"]
    
    # Check if the channel name starts with any of the ticket emojis
    for emoji in ticket_emojis:
        if channel_name.startswith(emoji):
            # Replace the old emoji with the new one
            return new_emoji + channel_name[len(emoji):]
    
    # If no emoji found, just prepend the new emoji
    return new_emoji + channel_name


@ticket.register()
class Deny(
    lightbulb.SlashCommand,
    name="deny",
    description="Deny a ticket (Admin/Recruiter only)"
):
    user = lightbulb.user(
        "user",
        "User whose ticket to deny (optional - denies current channel if not specified)",
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

        # Determine which ticket to deny
        if self.user:
            # Deny specific user's tickets
            user_id = self.user.id

            # Find all tickets for this user
            tickets_to_close = await mongo.button_store.find({
                "type": "ticket",
                "user_id": user_id
            }).to_list(length=None)

            if not tickets_to_close:
                await ctx.respond(
                    f"❌ No tickets found for <@{user_id}>"
                )
                return

            # Close all their tickets
            for ticket in tickets_to_close:
                await mongo.button_store.update_one(
                    {"_id": ticket["_id"]},
                    {
                        "$set": {
                            "status": "denied",
                            "denied_at": datetime.now(timezone.utc),
                            "denied_by": ctx.user.id
                        }
                    }
                )

                # Rename the channel to have ❌ prefix
                try:
                    channel = await bot.rest.fetch_channel(ticket["channel_id"])
                    new_name = get_channel_name_with_new_emoji(channel.name, "❌")

                    await bot.rest.edit_channel(
                        ticket["channel_id"],
                        name=new_name,
                        reason=f"Ticket denied by {ctx.user.username}"
                    )
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"[Tickets] Failed to rename channel {ticket.get('channel_id')}: {e}")

            await ctx.respond(
                f"✅ Denied {len(tickets_to_close)} ticket(s) for <@{user_id}>"
            )

        else:
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

            # Deny the ticket
            await mongo.button_store.update_one(
                {"_id": ticket["_id"]},
                {
                    "$set": {
                        "status": "denied",
                        "denied_at": datetime.now(timezone.utc),
                        "denied_by": ctx.user.id
                    }
                }
            )

            # Rename the channel to have ❌ prefix
            try:
                channel = await bot.rest.fetch_channel(current_channel_id)
                new_name = get_channel_name_with_new_emoji(channel.name, "❌")

                await bot.rest.edit_channel(
                    current_channel_id,
                    name=new_name,
                    reason=f"Ticket denied by {ctx.user.username}"
                )

                # Small delay to respect rate limits
                await asyncio.sleep(1)

                await ctx.respond(
                    "✅ Ticket denied! The channel has been marked as denied."
                )
            except Exception as e:
                await ctx.respond(
                    f"✅ Ticket denied in database, but failed to rename channel: {str(e)}"
                )


@ticket.register()
class Approve(
    lightbulb.SlashCommand,
    name="approve",
    description="Approve a denied ticket (Admin/Recruiter only)"
):
    user = lightbulb.user(
        "user",
        "User whose ticket to approve (optional - approves current channel if not specified)",
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

        if self.user:
            # Approve specific user's most recent denied ticket
            user_id = self.user.id

            # Find most recent ticket for this user
            ticket = await mongo.button_store.find_one({
                "type": "ticket",
                "user_id": user_id
            }, sort=[("_id", -1)])

            if not ticket:
                await ctx.respond(
                    f"❌ No tickets found for <@{user_id}>"
                )
                return

        else:
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

        # Rename the channel to have ✅ prefix
        try:
            channel = await bot.rest.fetch_channel(ticket["channel_id"])
            new_name = get_channel_name_with_new_emoji(channel.name, "✅")

            await bot.rest.edit_channel(
                ticket["channel_id"],
                name=new_name,
                reason=f"Ticket approved by {ctx.user.username}"
            )

            await ctx.respond(
                f"✅ Ticket approved for <@{ticket['user_id']}>!"
            )
        except Exception as e:
            await ctx.respond(
                f"✅ Ticket approved in database, but failed to rename channel: {str(e)}"
            )


# # Add this to clean up orphaned tickets on startup
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def cleanup_orphaned_tickets(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Check for tickets where the channel no longer exists and mark them as denied"""

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

            await asyncio.sleep(0.5)

            # If channel exists but starts with ❌, mark ticket as denied
            if channel.name.startswith("❌"):
                await mongo.button_store.update_one(
                    {"_id": ticket["_id"]},
                    {
                        "$set": {
                            "status": "denied",
                            "denied_at": datetime.now(timezone.utc),
                            "denied_reason": "channel_marked_denied"
                        }
                    }
                )
                closed_count += 1
            # If channel exists but starts with ✅, mark ticket as approved
            elif channel.name.startswith("✅"):
                await mongo.button_store.update_one(
                    {"_id": ticket["_id"]},
                    {
                        "$set": {
                            "status": "approved",
                            "approved_at": datetime.now(timezone.utc),
                            "approved_reason": "channel_marked_approved"
                        }
                    }
                )
                closed_count += 1

        except hikari.NotFoundError:
            # Channel doesn't exist, mark ticket as denied
            await mongo.button_store.update_one(
                {"_id": ticket["_id"]},
                {
                    "$set": {
                        "status": "denied",
                        "denied_at": datetime.now(timezone.utc),
                        "denied_reason": "channel_deleted"
                    }
                }
            )
            closed_count += 1
        except Exception:
            # Other errors, skip
            pass

    if closed_count > 0:
        print(f"[Tickets] Cleaned up {closed_count} orphaned tickets")