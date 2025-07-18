# commands/clan/report/__init__.py
"""Main entry point for clan points reporting system"""
import lightbulb
from extensions.commands.clan import loader, clan
from .router import create_home_dashboard

@clan.register()
class RecruitPoints(
    lightbulb.SlashCommand,
    name="recruit-points",
    description="Report recruitment activities for clan points",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Initialize the reporting dashboard"""
        await ctx.respond(
            components=await create_home_dashboard(ctx.member),
            ephemeral=True
        )

# Import helpers first as other modules depend on it
from . import helpers

# Import all report modules to register their actions
from . import discord_post
from . import dm_recruitment
from . import member_left
from . import approval
from . import router
from . import recruitment_help  # New import

# Register the clan group with the loader
loader.command(clan)