import lightbulb
import hikari

from extensions.commands.fwa import loader, fwa
from extensions.commands.fwa.chocolate_links import (
    chocolate_url,
    is_valid_tag,
    normalize_tag,
)
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton,
    SectionComponentBuilder as Section,
    MessageActionRowBuilder as ActionRow,
)


@fwa.register()
class ChocolateCommand(
    lightbulb.SlashCommand,
    name="chocolate",
    description="Look up player or clan on FWA chocolate site",
):
    player_tag = lightbulb.string(
        "player-tag",
        "Player tag to look up",
        default=None,
        min_length=3,
        max_length=20
    )

    clan_tag = lightbulb.string(
        "clan-tag",
        "Clan tag to look up",
        default=None,
        min_length=3,
        max_length=20
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, bot: hikari.GatewayBot = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)

        # Check that exactly one option was provided
        if (self.player_tag and self.clan_tag) or (not self.player_tag and not self.clan_tag):
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ **Invalid Usage**"),
                        Text(content=(
                            "Please provide **either** a player tag **or** a clan tag, not both.\n\n"
                            "**Examples:**\n"
                            "• `/fwa chocolate player-tag:#Y2Q8R0GQ`\n"
                            "• `/fwa chocolate clan-tag:#9LLUR8`"
                        )),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            await bot.rest.create_message(
                channel=ctx.channel_id,
                components=components
            )
            await ctx.interaction.delete_initial_response()
            return

        # Determine which tag was provided
        if self.player_tag:
            tag = self.player_tag
            tag_type = "player"
            emoji = "👤"
            type_text = "Player"
        else:
            tag = self.clan_tag
            tag_type = "clan"
            emoji = "🏛️"
            type_text = "Clan"

        # Normalize the tag
        normalized_tag = normalize_tag(tag)

        # Validate tag format
        if not is_valid_tag(tag):
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ **Invalid Tag Format**"),
                        Text(content=(
                            f"The tag `{tag}` appears to be invalid.\n\n"
                            "Please check that you've entered a valid Clash of Clans tag."
                        )),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            await bot.rest.create_message(
                channel=ctx.channel_id,
                components=components
            )
            await ctx.interaction.delete_initial_response()
            return

        # Build the URL
        url = chocolate_url(normalized_tag, tag_type=tag_type)

        # Build type-specific information text
        if tag_type == "player":
            type_info = (
                "• Player's FWA participation history\n"
                "• Current clan status\n"
                "• War performance metrics\n"
                "• Blacklist status (if any)"
            )
        else:
            type_info = (
                "• Clan's FWA membership status\n"
                "• War sync information\n"
                "• Member compliance\n"
                "• Clan statistics"
            )

        # Build response components
        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## 🍫 **FWA Chocolate Lookup**"),
                    Separator(divider=True),
                    Text(content=(
                        f"{emoji} **{type_text} Tag:** `#{normalized_tag}`\n"
                        f"🔗 **FWA Status:** Click below to check\n\n"
                        f"This will open the FWA Chocolate site to show:\n"
                    )),
                    Text(content=type_info),
                    ActionRow(
                        components=[
                            LinkButton(
                                label=f"Open {type_text} on FWA Chocolate",
                                url=url
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                    Separator(divider=True),
                    Text(content=f"-# Requested by <@{ctx.member.id}>"),
                ]
            )
        ]

        # Send message to channel
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components
        )

        # Delete the ephemeral "thinking" message
        await ctx.interaction.delete_initial_response()


loader.command(fwa)
