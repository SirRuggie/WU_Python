import lightbulb
import hikari
from datetime import datetime

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton,
    MessageActionRowBuilder as ActionRow,
)

from utils.constants import BLUE_ACCENT

loader = lightbulb.Loader()

# Constants
ALLOWED_ROLE_ID = 1060318031575793694
LOG_CHANNEL_ID = 1350318721771634699


@loader.command
class Say(
    lightbulb.SlashCommand,
    name="say",
    description="Send a message as the bot",
):
    message = lightbulb.string(
        "message",
        "Message to send",
        min_length=1,
        max_length=2000
    )

    @lightbulb.invoke
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Check if user has the required role
        member = ctx.member
        if ALLOWED_ROLE_ID not in member.role_ids:
            await ctx.respond(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        # Get necessary IDs
        guild_id = ctx.guild_id
        channel_id = ctx.channel_id

        # Send the message
        sent_message = await bot.rest.create_message(
            channel=channel_id,
            content=self.message,
            user_mentions=True,
            role_mentions=True
        )

        # Create message link
        message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{sent_message.id}"

        # Create log entry with components
        log_components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## 📝 **Say Command Used**"),
                    Separator(divider=True),
                    Text(content=(
                        f"**User:** {member.mention} (`{member.username}`)\n"
                        f"**Channel:** <#{channel_id}>\n"
                        f"**Time:** <t:{int(datetime.now().timestamp())}:F>\n\n"
                        f"**Message:**\n```\n{self.message}\n```"
                    )),
                    ActionRow(
                        components=[
                            LinkButton(
                                label="Jump to Message",
                                url=message_link
                            ),
                            LinkButton(
                                label="Go to Channel",
                                url=f"https://discord.com/channels/{guild_id}/{channel_id}"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Blue_Footer.png")])
                ]
            )
        ]

        # Send log to logging channel
        await bot.rest.create_message(
            channel=LOG_CHANNEL_ID,
            components=log_components
        )

        # Confirm to user
        await ctx.respond(
            "✅ Message sent",
            ephemeral=True
        )


loader.command(Say)