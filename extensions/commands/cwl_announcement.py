# extensions/commands/cwl_announcement.py
"""
CWL announcement command for main and lazy channels
"""

import hikari
import lightbulb

from utils.mongo import MongoClient

loader = lightbulb.Loader()


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

        await ctx.respond(
            "This command is retired. Use `/manage section:CWL` to preview or send the saved roster announcement.",
            ephemeral=True,
        )
