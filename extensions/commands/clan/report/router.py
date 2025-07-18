# commands/clan/report/router.py

"""Central routing and dispatch for report types"""

import hikari
import lightbulb

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.constants import GOLD_ACCENT
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# ╔══════════════════════════════════════════════════════════════╗
# ║                  Create Home Dashboard Utility               ║
# ╚══════════════════════════════════════════════════════════════╝

async def create_home_dashboard(member: hikari.Member) -> list:
    """Create the main report dashboard"""
    components = [
        Container(
            accent_color=GOLD_ACCENT,
            components=[
                Text(content="## 📊 Report Clan Points"),
                Text(content="Select the type of recruitment activity to report:"),

                Separator(divider=True),

                # Main report types
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            label="Discord Post",
                            emoji="💬",
                            custom_id=f"report_type:discord_post_{member.id}"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            label="DM Recruitment",
                            emoji="📩",
                            custom_id=f"report_type:dm_recruit_{member.id}"
                        )
                    ]
                ),

                # Additional features row
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Member Left",
                            emoji="👋",
                            custom_id=f"report_type:member_left_{member.id}"
                            # REMOVED is_disabled=True - button is now active!
                        ),
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            label="Recruitment Help",
                            emoji="📢",
                            custom_id=f"report_type:recruitment_help_{member.id}"
                        )
                    ]
                ),

                # Help section
                Separator(divider=True),
                Text(content=(
                    "**📌 Quick Guide:**\n"
                    "• **Discord Post** - You recruited via a public Discord message\n"
                    "• **DM Recruitment** - You recruited someone through DMs\n"
                    "• **Member Left** - Process refunds for members who left early\n"
                    "• **Recruitment Help** - Post what members your clan is looking for"
                )),

                Media(items=[MediaItem(media="assets/Gold_Footer.png")])
            ]
        )
    ]
    return components

# ╔══════════════════════════════════════════════════════════════╗
# ║                  Report Type Selection Handler               ║
# ╚══════════════════════════════════════════════════════════════╝

@register_action("report_type", no_return=True)
@lightbulb.di.with_di
async def report_type_selected(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Route to appropriate report type handler"""
    parts = action_id.split("_")
    report_type = "_".join(parts[:-1])  # Everything except user ID
    user_id = parts[-1]

    # Check if user is authorized
    if str(ctx.user.id) != user_id:
        await ctx.respond("❌ This button is not for you!", ephemeral=True)
        return

    # Dispatch to appropriate handler based on report type
    if report_type == "discord_post":
        from .discord_post import show_discord_post_flow
        await show_discord_post_flow(ctx, user_id, mongo)
    elif report_type == "dm_recruit":
        from .dm_recruitment import show_dm_recruitment_flow
        await show_dm_recruitment_flow(ctx, user_id, mongo)
    elif report_type == "member_left":
        from .member_left import show_member_left_flow
        # Call the handler directly with proper context
        await show_member_left_flow(ctx, action_id, mongo)
    elif report_type == "recruitment_help":
        from .recruitment_help import recruitment_help_select
        await recruitment_help_select(ctx, user_id, mongo)

# ╔══════════════════════════════════════════════════════════════╗
# ║                      Cancel Handler                          ║
# ╚══════════════════════════════════════════════════════════════╝

@register_action("cancel_report", no_return=True)
async def cancel_report(ctx: lightbulb.components.MenuContext, action_id: str, **kwargs):
    """Universal cancel handler - returns to main dashboard"""
    user_id = action_id

    # Clean up any sessions (each module should handle its own cleanup)
    # This is just a fallback to return to dashboard

    components = await create_home_dashboard(ctx.member)
    await ctx.respond(components=components, edit=True)

# ╔══════════════════════════════════════════════════════════════╗
# ║                   Report Another Handler                     ║
# ╚══════════════════════════════════════════════════════════════╝

@register_action("report_another", no_return=True)
async def report_another(ctx: lightbulb.components.MenuContext, action_id: str, **kwargs):
    """Handle 'Submit Another' button - returns to main dashboard"""
    components = await create_home_dashboard(ctx.member)
    await ctx.respond(components=components, edit=True)