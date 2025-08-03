# extensions/commands/cwl_announcement.py
"""
CWL announcement command for main and lazy channels
"""

import hikari
import lightbulb

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    LinkButtonBuilder as LinkButton,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.constants import GOLDENROD_ACCENT

loader = lightbulb.Loader()

# Configuration - Easy to change for different channels
MAIN_CWL_CHANNEL = 1072714594625257502
LAZY_CWL_CHANNEL = 865726525990633472
ROLE_TO_PING = 1080521665584308286

# Google Sheet URLs
MAIN_SHEET_URL = "https://docs.google.com/spreadsheets/d/1GcNVWyx5HjoDm5AbQAOT0_pwyf95KRl_f4lQ0Up3ZBM/edit?usp=sharing"
LAZY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1GxIuathFuro-xdYM9rVcF2Sob9lyFgDsT7TekkkuK-E/edit#gid=512888016"

# GIF URL from Tenor (more reliable than imgur)
CWL_GIF_URL = "https://c.tenor.com/aXIInybKvOwAAAAd/tenor.gif"


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
        bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        if self.type == "main":
            # Create Main CWL announcement
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content="<:league_medal:949137422933962753> CWL Time <:league_medal:949137422933962753>"),
                        Text(content=(
                            "Below are the CWL Rosters. Once your attacks are complete, make your way to your assigned Clan.\n\n"
                            "The Clan Links are on the Spreadsheet. You can also find them in <#1114047624216068136>\n\n"
                            "Direct all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
                        )),
                        Media(items=[MediaItem(media=CWL_GIF_URL)]),
                        Separator(divider=True),
                        ActionRow(
                            components=[
                                LinkButton(
                                    url=MAIN_SHEET_URL,
                                    label="CWL Rosters",
                                    emoji="📋"
                                )
                            ]
                        ),
                    ]
                )
            ]

            # Send to main channel
            try:
                await bot.rest.create_message(
                    channel=MAIN_CWL_CHANNEL,
                    components=components,
                    role_mentions=[ROLE_TO_PING]
                )
                await ctx.respond(
                    f"✅ Main CWL announcement sent to <#{MAIN_CWL_CHANNEL}>",
                    ephemeral=True
                )
            except Exception as e:
                await ctx.respond(
                    f"❌ Failed to send announcement: {str(e)}",
                    ephemeral=True
                )

        else:  # lazy
            # Create Lazy CWL announcement
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content="<:league_medal:949137422933962753> Lazy CWL Time <:league_medal:949137422933962753>"),
                        Text(content=(
                            "Below are the Lazy CWL Rosters. If you cannot view the Roster or do not understand it, "
                            "please ping <@&769130325460254740> in <#872692009066958879> and we'll get it sorted.\n\n"
                            "As soon as both your attacks are complete in the current war make your way to your assigned Clan. "
                            "__The sooner the better.__\n\n"
                            "There are several Bots in the server that can provide war information. To many to list here. "
                            "Feel free to play around in <#1128848663872028743>. War and CWL are good keywords for looking."
                        )),
                        Media(items=[MediaItem(media=CWL_GIF_URL)]),
                        Separator(divider=True),
                        ActionRow(
                            components=[
                                LinkButton(
                                    url=LAZY_SHEET_URL,
                                    label="Lazy CWL Rosters",
                                    emoji="😴"
                                ),
                                LinkButton(
                                    url="https://docs.google.com/document/d/137zYF4CHwW-hqwZXzDVmQWONkao1X-XckjGs5Myg-h0/edit",
                                    label="LazyCWL Guide",
                                    emoji="📖"
                                )
                            ]
                        ),
                    ]
                )
            ]

            # Send to lazy channel
            try:
                await bot.rest.create_message(
                    channel=LAZY_CWL_CHANNEL,
                    components=components,
                    role_mentions=[ROLE_TO_PING]
                )
                await ctx.respond(
                    f"✅ Lazy CWL announcement sent to <#{LAZY_CWL_CHANNEL}>",
                    ephemeral=True
                )
            except Exception as e:
                await ctx.respond(
                    f"❌ Failed to send announcement: {str(e)}",
                    ephemeral=True
                )