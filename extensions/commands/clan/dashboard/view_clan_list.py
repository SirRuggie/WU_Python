import lightbulb


from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.constants import RED_ACCENT
from extensions.components import register_action
from utils.mongo import MongoClient
from utils.classes import Clan
from extensions.commands.clan.dashboard.dashboard import dashboard_page

@register_action("view_clan_list", group="clan_database")
@lightbulb.di.with_di
async def view_clan_list(
        ctx: lightbulb.components.MenuContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    clan_data = await mongo.clans.find().to_list(length=None)
    clans = [Clan(data=data) for data in clan_data]

    clan_list = ""
    for clan in clans:
        clan_list += f"{clan.name} ({clan.tag})\n"

    # View Clan List message here
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=(
                    "### Current Clan List\n\n"
                    f"{clan_list}"
                )),
                Media(
                    items=[
                        MediaItem(media="assets/Red_Footer.png"),
                    ])
            ]
        )
    ]
    await ctx.respond(components=components, ephemeral=True)

    return (await dashboard_page(ctx=ctx))






