# extensions/commands/tickets/setup.py
"""
Ticket system setup command - posts the ticket creation embed
"""

import hikari
import lightbulb
from typing import List

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
)

from utils.constants import RED_ACCENT, GOLDENROD_ACCENT
from utils.mongo import MongoClient
from extensions.commands import ticket_runtime
from extensions.commands.tickets_legacy import loader, ticket
from extensions.commands.tickets_legacy import perms


def create_ticket_embed() -> List[Container]:
    """Create the Warriors United Clan Entry embed"""
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## Warriors United Clan Entry"),
                Separator(divider=True),
                Text(content=(
                    "Now that you've read what we're all about, don't hesitate to create "
                    "an entry ticket from one of the categories below.\n\n"
                    "Once you have created one, please wait patiently for on of our "
                    "Recruiters to respond.\n\n"
                    "We want you to have the best experience possible here! within "
                    "the Warriors United Family!"
                )),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                # Buttons row
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="create_ticket:main",
                            label="Main Clan Interest",
                            emoji="🏆",  # Trophy emoji
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="create_ticket:fwa",
                            label="FWA Clan Interest",
                            emoji="💎",  # Diamond emoji
                        ),
                    ]
                ),
            ]
        )
    ]

    return components


@ticket.register()
class Setup(
    lightbulb.SlashCommand,
    name="setup",
    description="Set up the ticket system embed (Admin only)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """Send the ticket creation embed"""

        # Defer the response immediately to avoid timeout
        await ctx.defer(ephemeral=True)

        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!"
            )
            return
        if not await perms.is_legacy_control_guild(mongo, ctx.guild_id):
            await ctx.respond(
                "❌ Legacy ticket setup is bound to its configured guild. Nothing was posted."
            )
            return

        try:
            rollout = await ticket_runtime.get_rollout(mongo)
        except Exception:
            await ctx.respond(
                "❌ Could not verify the ticket rollout phase. Nothing was posted."
            )
            return
        if rollout.valid and rollout.phase in {
            ticket_runtime.PHASE_THREAD_DEFAULT,
            ticket_runtime.PHASE_THREAD_ONLY,
        }:
            await ctx.respond(
                "❌ Legacy intake is retired in the current rollout phase. Nothing was posted."
            )
            return

        message = None
        panel_active = False
        try:
            # Send the embed to the channel (not as a reply)
            message = await bot.rest.create_message(
                channel=ctx.channel_id,
                components=create_ticket_embed()
            )

            if rollout.valid:
                if not rollout.thread_intake or not rollout.pilot_intake:
                    raise RuntimeError(
                        "ticket rollout intake configuration is incomplete"
                    )
                await ticket_runtime.configure_rollout(
                    mongo,
                    expected_revision=rollout.revision,
                    actor_id=int(ctx.user.id),
                    legacy_intake={
                        "guild_id": int(ctx.guild_id),
                        "channel_id": int(ctx.channel_id),
                        "message_id": int(message.id),
                    },
                    thread_intake={
                        "guild_id": int(ctx.guild_id),
                        "channel_id": int(ctx.channel_id),
                        "message_id": int(message.id),
                    },
                    pilot={
                        "intake": {
                            "guild_id": rollout.pilot_intake.guild_id,
                            "channel_id": rollout.pilot_intake.channel_id,
                            "message_id": rollout.pilot_intake.message_id,
                        },
                        "user_ids": rollout.pilot_user_ids,
                        "role_ids": rollout.pilot_role_ids,
                        "ticket_types": rollout.pilot_ticket_types,
                    },
                )

            panel_active = True

            # Send success feedback
            await ctx.respond(
                "✅ Ticket system embed has been posted!"
            )

        except Exception as e:
            if message is not None and not panel_active:
                try:
                    await bot.rest.delete_message(ctx.channel_id, message.id)
                except Exception as cleanup_error:
                    print(
                        "[Tickets:Legacy] inactive_intake_cleanup_failed "
                        f"message={message.id} error={type(cleanup_error).__name__}"
                    )
            # Send error
            await ctx.respond(
                f"❌ Failed to post ticket embed: {str(e)}"
            )
