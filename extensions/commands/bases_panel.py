"""A persistent channel panel: members select a Town Hall and see its base privately.

The panel stores nothing. Its select menu uses the fixed custom_id
``fwa_bases_panel:``, so the panel keeps working after restarts, and each
selection reads the current Town Hall registry snapshot.
"""
import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.fwa.bases import base_components
from extensions.components import register_action
from utils.constants import WU_GOLD
from utils.town_hall_base_views import base_choice, base_menu

loader = lightbulb.Loader()

PANEL_ACTION = "fwa_bases_panel"
STEPS = (
    "**How to get your base**\n"
    "1. Select your Town Hall in the menu below.\n"
    "2. Select **Open base link**. The base opens in Clash of Clans.\n"
    "3. Copy the base and set it as your war base."
)
TH16_NOTE = (
    "**TH16 and higher**\n"
    "**Non-merged**: Use this first. Use it when you are new to the Town Hall "
    "and your defenses are not merged.\n"
    "**Merged**: Use this after you merge your defenses."
)


def panel_components():
    """The public panel; the menu is disabled while no base links are set."""
    return [Container(accent_color=WU_GOLD, components=[
        Text(content="## FWA Bases"),
        Text(content=STEPS),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=TH16_NOTE),
        ActionRow(components=[base_menu(f"{PANEL_ACTION}:", empty=True)]),
        Text(content="-# Only you can see your base."),
        Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
    ])]


@loader.command
class BasesPanel(
    lightbulb.SlashCommand,
    name="bases-panel",
    description="Post the FWA base panel in this channel",
    default_member_permissions=hikari.Permissions.MANAGE_GUILD,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, bot: hikari.GatewayBot = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        await bot.rest.create_message(ctx.channel_id, components=panel_components())
        await ctx.respond("FWA base panel posted.", ephemeral=True)


@register_action(PANEL_ACTION, no_return=True, preload_state=False)
async def fwa_bases_panel(**kwargs):
    ctx = kwargs["ctx"]
    choice = ctx.interaction.values[0]
    base = base_choice(choice)
    if base is None:
        await ctx.respond("This base is no longer available.", ephemeral=True)
    else:
        await ctx.respond(components=base_components(
            base, base_only=True, user_mention="", requester_mention="",
        ), ephemeral=True)
    # Rebuild the panel: it clears the selection, so the same Town Hall can be
    # selected again, and it shows the current registry levels.
    await ctx.respond(components=panel_components(), edit=True)
