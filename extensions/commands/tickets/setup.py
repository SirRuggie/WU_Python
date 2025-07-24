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
from extensions.commands.tickets import loader, ticket


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

        try:
            # Send the embed to the channel (not as a reply)
            await bot.rest.create_message(
                channel=ctx.channel_id,
                components=create_ticket_embed()
            )

            # Send success feedback
            await ctx.respond(
                "✅ Ticket system embed has been posted!"
            )

        except Exception as e:
            # Send error
            await ctx.respond(
                f"❌ Failed to post ticket embed: {str(e)}"
            )