# extensions/commands/cwl_announcement.py
"""
CWL announcement command for main and lazy channels
"""

import hikari
import lightbulb

from extensions.tasks import cwl_reminder as cwl_runtime
from utils import cwl_campaign
from utils.mongo import MongoClient

loader = lightbulb.Loader()


@loader.command()
class CWLAnnouncement(
    lightbulb.SlashCommand,
    name="cwl-announcement",
    description="Send CWL announcement to main or lazy channels"
):
    type = lightbulb.string(
        "type",
        "Type of announcement to send",
        choices=[
            lightbulb.Choice("Main CWL", "main"),
            lightbulb.Choice("Lazy CWL", "lazy")
        ]
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self, 
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        guild_id = int(ctx.interaction.guild_id)
        configured = await cwl_campaign.load_campaign(mongo, guild_id)
        destination = configured["campaign"]["messages"]["roster"]["variants"][self.type]["destination_channel_id"]
        if cwl_runtime.mongo_client is not mongo or cwl_runtime.bot_instance is None:
            await ctx.respond(
                "❌ The CWL delivery scheduler is still starting. Try again in a moment.",
                ephemeral=True,
            )
            return
        delivered = await cwl_runtime.send_campaign_message(
            guild_id, configured["cycle"], "roster", [self.type],
        )
        if delivered:
            await ctx.respond(
                f"✅ {self.type.title()} CWL announcement sent to <#{destination}>",
                ephemeral=True,
            )
        else:
            await ctx.respond(
                "⚠️ The announcement was not sent. Check the CWL dashboard history for a delivery error or existing send.",
                ephemeral=True,
            )
