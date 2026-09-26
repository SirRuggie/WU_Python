"""Private path selection bound to the currently authorized public intake post."""
from datetime import timedelta
import uuid

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator, MessageActionRowBuilder as Row,
    MediaGalleryComponentBuilder as Media, MediaGalleryItemBuilder as MediaItem,
)
from extensions.components import register_action
from extensions.commands import ticket_runtime
from extensions.commands.tickets import handlers
from utils.component_state import insert_state, get_state
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient


def path_panel(session_id="preview", sections=None, *, media=None, preview=False):
    def button(kind, label, emoji):
        return Row().add_interactive_button(
            hikari.ButtonStyle.PRIMARY, f"ticket_v2_rite_choose:{session_id}:{kind}",
            label=label, emoji=emoji, is_disabled=preview,
        )
    panel = [Container(accent_color=GOLDENROD_ACCENT, components=[
        Text(content="## ⚔️ **Warriors United – Your Rite of Passage Begins**"),
        Text(content=(
            '**“Warrior, your first steps within Warriors United are more than a simple entry… '
            'they mark the beginning of your Rite of Passage.”**\n\n'
            '**“The Apply Button has been replaced. There is no ‘apply’ for a warrior — '
            'only the path you choose and the oath you are willing to take.”**'
        )),
        Separator(divider=True),
        Text(content=(
            "### 🔱 **Rite of Passage to Main**\n"
            "**This path is for those who seek honor, unity, and the strength of the brotherhood.**\n"
            "It is the road toward becoming **Sworn** — a warrior recognized, trusted, and bound to the clan’s code.\n"
            "Choose this path if you are ready to prove your worth and rise among your fellow warriors."
        )),
        button("main", "Rite of Passage to Main", "🔱"),
        Separator(divider=True),
        Text(content=(
            "### 🩸 **Rite of Passage to FWA**\n"
            "**This path leads into the fires of challenge and conflict.**\n"
            "It is for those who wish to test themselves in the crucible of battle, competition, or elite trials.\n"
            "Only the bold walk this road, and only the relentless endure it."
        )),
        button("fwa", "Rite of Passage to FWA", "🩸"),
        Separator(divider=True),
        Text(content=(
            "## 🛡️ **Your Choice Defines Your Destiny**\n"
            "**“Every warrior begins as the Unproven.\n"
            "Your Rite of Passage determines whether you rise… or fall.”**"
        )),
        Media(items=[MediaItem(media="assets/tickets/static/Rite_of_Passage.jpg")]),
    ])]
    components = list(panel[0].components)
    if sections is not None:
        values = iter(sections)
        for index, component in enumerate(components):
            if component.type == hikari.ComponentType.TEXT_DISPLAY:
                components[index] = Text(content=next(values))
    if media and media.get("guide"):
        components[-1] = Media(items=[MediaItem(media=media["guide"])])
    panel = [Container(accent_color=GOLDENROD_ACCENT, components=components)]
    return panel


def build_rite(sections=None, *, media=None, action_id="preview", preview=False):
    return path_panel(action_id, sections, media=media, preview=preview)


async def saved_path_panel(mongo, guild_id, session_id):
    from extensions.commands import content
    sections, media, _ = await content.template_for(mongo, content.DOCUMENTS["rite-of-passage"], guild_id)
    return path_panel(session_id, sections, media=media)


@register_action("ticket_v2_rite_open", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_paths(ctx, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.defer(ephemeral=True)
    source_id = int(ctx.interaction.message.id)
    route = await ticket_runtime.route_public_intake(
        mongo, requested_route=ticket_runtime.ROUTE_THREAD,
        guild_id=int(ctx.guild_id), channel_id=int(ctx.channel_id), message_id=source_id,
        user_id=int(ctx.user.id), member_role_ids=tuple(getattr(ctx.member, "role_ids", ()) or ()),
        ticket_type="main",
    )
    if not route.allowed or route.route != ticket_runtime.ROUTE_THREAD:
        await ctx.interaction.edit_initial_response(content="This entry panel is not active. Please use the current ticket panel.")
        return
    session_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": session_id, "type": "ticket_rite_paths", "owner_id": int(ctx.user.id),
        "guild_id": int(ctx.guild_id), "channel_id": int(ctx.channel_id), "source_message_id": source_id,
    }, ttl=timedelta(minutes=30))
    await ctx.interaction.edit_initial_response(components=await saved_path_panel(mongo, int(ctx.guild_id), session_id))


@register_action("ticket_v2_rite_choose", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_path(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                      bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    session_id, _, kind = action_id.partition(":")
    state = await get_state(mongo, session_id)
    if (not state or state.get("type") != "ticket_rite_paths" or kind not in {"main", "fwa"}
        or state.get("owner_id") != int(ctx.user.id) or state.get("guild_id") != int(ctx.guild_id)
        or state.get("channel_id") != int(ctx.channel_id)):
        await ctx.respond("This path selection has expired. Open Earn Your Rite of Passage again.", ephemeral=True)
        return
    # Reuse all existing readiness, current binding, rollout, cooldown, and slot
    # checks. The private chooser's message ID is never an intake authority.
    await handlers.handle_create_ticket(
        ctx=ctx, action_id=f"public:{kind}", bot=bot, mongo=mongo,
        _source_message_id=int(state["source_message_id"]),
    )
