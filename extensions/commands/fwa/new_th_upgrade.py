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
class NewThUpgrade(lightbulb.SlashCommand, name="new-th-upgrade", description="Display Town Hall upgrade notes for FWA bases"):
    user = lightbulb.user("discord-user", "User to show this to")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        action_id = str(uuid.uuid4())
        menu = base_menu(f"fwa_new_th_upgrade_th_select:{action_id}")
        if menu is None:
            await ctx.respond("No base links are set.", ephemeral=True)
            return
        await insert_state(mongo, {"_id": action_id, "user_id": self.user.id})
        await ctx.respond(components=[Container(accent_color=WU_GOLD, components=[
            Text(content="## Select FWA Base Town Hall Level"),
            Text(content="Select the Town Hall level of the recruit in the menu below."),
            ActionRow(components=[menu]), Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
        ])], ephemeral=True)


def upgrade_components(base, *, user_mention, requester_mention):
    first = [Text(content=f"## {base['friendly_name']}")]
    if base['war_image']:
        first.append(Media(items=[MediaItem(media=base['war_image'])]))
    first.append(ActionRow(components=[LinkButton(url=base['link'], label="Open base link")]))
    notes = base['upgrade_notes'] or "There are no upgrade notes for this Town Hall level yet.\n\nCheck again later or ask leadership."
    second = [Text(content=f"### TH{base['level']} Upgrade Notes"), Text(content=notes)]
    if base['active_image']:
        second.append(Media(items=[MediaItem(media=base['active_image'])]))
    second.append(Text(content=f"-# Requested by {requester_mention}"))
    return [Text(content=user_mention), Container(accent_color=WU_GOLD, components=first), Container(accent_color=WU_GOLD, components=second)]


@register_action("fwa_new_th_upgrade_th_select", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def fwa_new_th_upgrade_th_select(user_id: int, bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                                      mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    ctx = kwargs['ctx']
    choice = ctx.interaction.values[0]
    base = base_choice(choice)
    if base is None:
        await ctx.respond(f"No base link is set for {choice}.", ephemeral=True)
        return
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)
    await bot.rest.create_message(
        components=upgrade_components(base, user_mention=user.mention, requester_mention=ctx.member.mention),
        channel=ctx.channel_id, user_mentions=[user.id], role_mentions=True,
    )


loader.command(fwa)
