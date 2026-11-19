import uuid
import hikari
import lightbulb
from hikari.impl import (
    MessageActionRowBuilder as ActionRow, ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text, MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem, LinkButtonBuilder as LinkButton,
)
from extensions.components import register_action
from extensions.commands.fwa import loader, fwa
from utils.component_state import insert_state
from utils.mongo import MongoClient
from utils.constants import WU_GOLD
from utils.town_hall_base_views import base_menu, base_choice


@fwa.register()
class Bases(lightbulb.SlashCommand, name="bases", description="Select and display an FWA base Town Hall level"):
    user = lightbulb.user("discord-user", "User to show this to")
    base_only = lightbulb.boolean("base-only", "Send only the base link button without description", default=False)

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        action_id = str(uuid.uuid4())
        menu = base_menu(f"fwa_bases_th_select:{action_id}")
        if menu is None:
            await ctx.respond("No base links are set.", ephemeral=True)
            return
        await insert_state(mongo, {"_id": action_id, "user_id": self.user.id, "base_only": self.base_only})
        await ctx.respond(components=[Container(accent_color=WU_GOLD, components=[
            Text(content="## Select FWA Base Town Hall Level"),
            Text(content="Select the Town Hall level of the recruit in the menu below."),
            ActionRow(components=[menu]),
            Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
        ])], ephemeral=True)


def base_components(base, *, base_only, user_mention, requester_mention):
    first = [Text(content=f"## {base['friendly_name']}")]
    if base['war_image']:
        first.append(Media(items=[MediaItem(media=base['war_image'])]))
    first.append(ActionRow(components=[LinkButton(url=base['link'], label="Open base link")]))
    components = [Container(accent_color=WU_GOLD, components=first)]
    if not base_only:
        info = base['instructions'] or "To continue, switch your active war base to the link above.\n\nThen send a screenshot like the example below."
        second = [Text(content=f"### TH{base['level']} FWA War Status and Base Layout"), Text(content=info)]
        if base['active_image']:
            second.append(Media(items=[MediaItem(media=base['active_image'])]))
        second.append(Text(content=f"-# Requested by {requester_mention}"))
        components = [Text(content=user_mention), *components, Container(accent_color=WU_GOLD, components=second)]
    return components


@register_action("fwa_bases_th_select", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def fwa_bases_th_select(user_id: int, base_only: bool, bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                             mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    ctx = kwargs['ctx']
    choice = ctx.interaction.values[0]
    base = base_choice(choice)
    if base is None:
        await ctx.respond(f"No base link is set for {choice}.", ephemeral=True)
        return
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)
    await bot.rest.create_message(
        components=base_components(base, base_only=base_only, user_mention=user.mention, requester_mention=ctx.member.mention),
        channel=ctx.channel_id, user_mentions=[user.id] if not base_only else [], role_mentions=True,
    )


loader.command(fwa)
