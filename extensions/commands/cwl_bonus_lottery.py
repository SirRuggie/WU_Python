"""Compatibility entry point for the reviewed dashboard bonus workflow."""
import lightbulb
from utils.dashboard_urls import DASHBOARD_ORIGIN

loader = lightbulb.Loader()


@loader.command()
class LazyBonusLottery(lightbulb.SlashCommand, name="lazycwl-bonuses",
                       description="Open staff-reviewed CWL bonus draws in the dashboard"):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        if not ctx.member or 1430950420926300200 not in ctx.member.role_ids:
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        await ctx.respond(
            "Choose Lazy CWL in **Bonus winners** to review attacks, draw equal-chance winners, "
            "and approve them before posting an announcement.\n"
            f"{DASHBOARD_ORIGIN}/?view=bonuses\n"
            "Sign in with your staff account. If Home opens after sign-in, go to CWL → Results & bonuses → Bonus medals.",
            ephemeral=True,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
