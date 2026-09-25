
import lightbulb
import hikari

from extensions.commands.clan import loader, clan

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectMenuBuilder as SelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    ThumbnailComponentBuilder as Thumbnail,
    ModalActionRowBuilder as ModalActionRow
)

from utils.constants import GOLDENROD_ACCENT
from utils.emoji import emojis
from utils.mongo import MongoClient

# Main Clan Dashboard Management
@lightbulb.di.with_di
async def dashboard_page(
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        ctx: lightbulb.Context = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    clan_count = await mongo.clans.count_documents({})
    guild = bot.cache.get_guild(ctx.guild_id)
    icon_url = guild.make_icon_url(size=256) if guild else None
    heading = Text(content=(
        "### Clan Management Dashboard\n"
        "Welcome to Warrior's United Clan Management Dashboard\n\n"
        f"{emojis.white_arrow_right}**Clans in System:** `{clan_count}`\n"
    ))
    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Section(accessory=Thumbnail(media=icon_url), components=[heading])
                if icon_url else heading,
                Separator(divider=True, spacing=hikari.SpacingType.SMALL),
                Text(content=(
                    "Use the dropdown menu below to:\n"
                    f"{emojis.white_arrow_right}View clan details\n"
                    f"{emojis.white_arrow_right}Update Clan Information\n"
                    f"{emojis.white_arrow_right}Update FWA Data\n"
                )),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            max_values=1,
                            custom_id=f"clan_database:",
                            placeholder="Make a Selection...",
                            options=[
                                SelectOption(
                                    emoji=emojis.view.partial_emoji,
                                    label="View Clan List",
                                    description="View all clans & their IDs",
                                    value="view_clan_list"),
                                SelectOption(
                                    emoji=emojis.edit.partial_emoji,
                                    label="Update Clan Information",
                                    description="Edit or Manage Clan Details",
                                    value="update_clan_information"),
                                SelectOption(
                                    emoji=1387882523358527608,
                                    label="Manage FWA Data",
                                    description="Update FWA Links & Images",
                                    value="manage_fwa_data"),
                            ]),
                    ]),
                Separator(divider=True),
            ]
        )
    ]
    return components


class DashboardCommand(
    lightbulb.SlashCommand,
    name="dashboard",
    description="Open the Clan Management Dashboard",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)  # Hide the command response

        # Get the components
        comps = await dashboard_page(bot=bot, ctx=ctx, mongo=mongo)

        # Send to channel as standalone message (not a reply)
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=comps
        )

        # Delete the ephemeral "thinking" message
        await ctx.interaction.delete_initial_response()