"""Advisory ticket claiming.

Discord cannot enforce ownership of a thread or a channel per-user in any way a
bot can use, so this records and signals intent - it does not stop a second
recruiter acting. Tickets.bot documents the same limitation and disables claiming
entirely in thread mode; making it advisory is the honest version.

The value is in the signal, so a claim is posted into the ticket itself as well
as recorded in Mongo. A claim nobody can see is a claim nobody respects.
"""

import hikari
import lightbulb

from extensions.commands.tickets import loader, ticket
from extensions.commands.tickets import perms, store
from utils.mongo import MongoClient


def _discord_ts(value, style: str = "R") -> str:
    """<t:unix:R>. Renders in the reader's own timezone, and keeps ageing on a
    message the bot never touches again."""
    try:
        return f"<t:{int(value.timestamp())}:{style}>"
    except (AttributeError, TypeError, ValueError):
        return "some time ago"


async def _current_ticket(mongo: MongoClient, channel_id):
    """The open-or-not ticket document for the channel the command was run in.

    Inside a thread ctx.channel_id IS the thread id, so this resolves for both
    the channel era and the thread era with no change.
    """
    return await store.find_one(mongo, {"type": "ticket", "channel_id": channel_id})


@ticket.register()
class Claim(
    lightbulb.SlashCommand,
    name="claim",
    description="Take ownership of this ticket so other recruiters can see you have it",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        if not await perms.is_recruiter(ctx.member, mongo):
            await ctx.respond("Only recruiters can claim tickets.")
            return

        doc = await _current_ticket(mongo, ctx.channel_id)
        if doc is None:
            await ctx.respond("This isn't a ticket channel.")
            return

        result = await store.claim(mongo, doc["_id"], ctx.user.id, ctx.user.username)

        if result.won:
            await ctx.respond("You've got this one. I've said so in the ticket.")
            try:
                await bot.rest.create_message(
                    ctx.channel_id,
                    content=f"🙋 {ctx.user.mention} picked this one up.",
                    user_mentions=False,
                )
            except Exception as exc:
                print(f"[Tickets] claim marker failed for {doc['_id']}: {exc}")
            return

        if result.outcome == store.MISSING:
            await ctx.respond(
                f"I can't find the ticket record for this channel (`{doc['_id']}`). "
                f"Worth flagging to an admin."
            )
            return

        # LOST - either someone already has it, or it is no longer open.
        current = result.doc or {}
        holder = current.get("claimed_by")
        if holder and holder != ctx.user.id:
            await ctx.respond(
                f"{current.get('claimed_by_name') or f'<@{holder}>'} already has this one, "
                f"picked up {_discord_ts(current.get('claimed_at'))}."
            )
        elif holder == ctx.user.id:
            await ctx.respond("You already have this one.")
        else:
            await ctx.respond(
                f"This ticket is already **{current.get('status', 'resolved')}**, "
                f"so there's nothing to pick up."
            )


@ticket.register()
class Release(
    lightbulb.SlashCommand,
    name="release",
    description="Give up your claim on this ticket",
):
    force = lightbulb.boolean(
        "force",
        "Release someone else's claim (Admin only).",
        default=False,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        if not await perms.is_recruiter(ctx.member, mongo):
            await ctx.respond("Only recruiters can release tickets.")
            return

        forcing = bool(self.force)
        if forcing and not (ctx.member.permissions & hikari.Permissions.ADMINISTRATOR):
            await ctx.respond("Releasing someone else's claim is Administrator-only.")
            return

        doc = await _current_ticket(mongo, ctx.channel_id)
        if doc is None:
            await ctx.respond("This isn't a ticket channel.")
            return

        result = await store.release(
            mongo, doc["_id"], ctx.user.id, ctx.user.username, force=forcing
        )

        if result.won:
            await ctx.respond("Released. It's back in the pile.")
            try:
                await bot.rest.create_message(
                    ctx.channel_id,
                    content=f"🔓 {ctx.user.mention} let this one go — it's unclaimed again.",
                    user_mentions=False,
                )
            except Exception as exc:
                print(f"[Tickets] release marker failed for {doc['_id']}: {exc}")
            return

        if result.outcome == store.MISSING:
            await ctx.respond(f"I can't find the ticket record for this channel (`{doc['_id']}`).")
            return

        current = result.doc or {}
        holder = current.get("claimed_by")
        if not holder:
            await ctx.respond("Nobody has this one, so there's nothing to release.")
        else:
            await ctx.respond(
                f"{current.get('claimed_by_name') or f'<@{holder}>'} has this one, not you. "
                f"An admin can release it with `force: true`."
            )
