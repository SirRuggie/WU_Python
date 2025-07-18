import uuid
import hikari
import lightbulb
import coc

from extensions.commands.clan   import loader, clan
from extensions.components      import register_action
from utils.mongo                import MongoClient
from utils.classes              import Clan
from utils.constants            import RED_ACCENT
from utils.emoji                import emojis

from hikari.impl import (
    MessageActionRowBuilder         as ActionRow,
    TextSelectMenuBuilder           as TextSelectMenu,
    SelectOptionBuilder             as SelectOption,
    ContainerComponentBuilder       as Container,
    SectionComponentBuilder         as Section,
    TextDisplayComponentBuilder     as Text,
    SeparatorComponentBuilder       as Separator,
    MediaGalleryComponentBuilder    as Media,
    MediaGalleryItemBuilder         as MediaItem,
    ThumbnailComponentBuilder       as Thumbnail,
    LinkButtonBuilder               as LinkButton,
)


@clan.register()
class ListCommand(
    lightbulb.SlashCommand,
    name="list",
    description="Pick a clan to view or manage",
):
    # 1) define a user‐select option here:
    user = lightbulb.user(
        "discord-user",
        "Which user to show this for",
    )

    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        clan_data = await mongo.clans.find().to_list(length=None)
        clans     = [Clan(data=d) for d in clan_data]

        options = []
        for c in clans:
            kwargs = {"label": c.name, "value": c.tag, "description": c.tag}
            if getattr(c, "partial_emoji", None):
                kwargs["emoji"] = c.partial_emoji
            options.append(SelectOption(**kwargs))

        action_id = str(uuid.uuid4())

        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=(
                        "## **Pick Your Clan**\n"
                        "Use the dropdown below to select your clan.\n"
                        "If your clan isn’t listed, notify Ruggie."
                    )),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                # 2) include the selected user's ID
                                custom_id=f"clan_select_menu:{action_id}_{self.user.id}",
                                placeholder="Select a clan",
                                max_values=1,
                                options=options,
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                ],
            )
        ]
        await ctx.respond(components=components, ephemeral=True)


@register_action("clan_select_menu", no_return=True)
@lightbulb.di.with_di
async def on_clan_chosen(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_client: coc.Client  = lightbulb.di.INJECTED,
    mongo: MongoClient      = lightbulb.di.INJECTED,
    **kwargs
):
    ctx: lightbulb.components.MenuContext = kwargs["ctx"]
    _, user_id = action_id.rsplit("_", 1)
    user = await bot.rest.fetch_member(ctx.guild_id, int(user_id))

    tag = ctx.interaction.values[0]
    raw = await mongo.clans.find_one({"tag": tag})
    if not raw:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[Text(content="⚠️ I couldn’t find that clan in our database.")]
            )
        ]
    db_clan = Clan(data=raw)

    api_clan = None
    try:
        api_clan = await coc_client.get_clan(tag=tag)
    except coc.NotFound:
        pass

    if api_clan and api_clan.capital_districts:
        peak = max(d.hall_level for d in api_clan.capital_districts)
    else:
        peak = 0

    lines = [
        f"{emojis.red_arrow_right}**Name:** {db_clan.name} (`{db_clan.tag}`)",
        f"{emojis.red_arrow_right}**Level:** {api_clan.level}" if api_clan else "• **Level:** —",
        f"{emojis.red_arrow_right}**CWL Rank:** {api_clan.war_league.name if api_clan else '—'}",
        f"{emojis.red_arrow_right}**Type:** {db_clan.type or '—'}",
        f"{emojis.red_arrow_right}**Capital Peak:** Level {peak}",
    ]
    content = (
        f"Hey {user.mention},\n"
        f"I’d like to introduce you to **{db_clan.name}**, led by "
        f"<@{db_clan.leader_id}> and <@&{db_clan.leader_role_id}>."
    )
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content=f"Hey {user.mention},"),
                Text(content=(
                    f"I’d like to introduce you to **{db_clan.name}**, led by "
                    f"<@{db_clan.leader_id}> and <@&{db_clan.leader_role_id}>."
                )),
                Separator(divider=True),
                Text(content="## **Important Information Below**"),
                Text(content=(
                    "You’re free to move temporarily within our Family. "
                    "If you want to switch clans permanently, please discuss it with leadership to ensure a good fit.\n\n"
                    "If you’re unhappy with the clan given, let us know—we can explore other options."
                )),
                Separator(divider=True),
                Text(content=(
                    f"From now on, **{db_clan.name}** is your new home. "
                    "Use the code `Arcane` to access any clan within our Family. "
                    "It will become your friend during CWL... *make sense?*"
                )),
            ],
        ),
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[Text(content="\n".join(lines))],
                    accessory=Thumbnail(media=api_clan.badge.large if api_clan else db_clan.logo),
                ),
                Media(items=[MediaItem(media=db_clan.banner)]),
                ActionRow(
                    components=[
                        LinkButton(
                            label="Open In-Game",
                            url=api_clan.share_link if api_clan else ""
                        )
                    ]
                ),
                Separator(divider=True),
                Text(content=f"-# Requested by {ctx.member.mention}"),
            ],
        ),
    ]

    await ctx.interaction.delete_initial_response()

    await bot.rest.create_message(
        channel=ctx.channel_id,
        components=components,
        user_mentions = [user.id, db_clan.leader_id],
        role_mentions = True,
    )

loader.command(clan)
