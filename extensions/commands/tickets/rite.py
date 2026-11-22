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
from utils.component_state import insert_state, get_state, update_state, utcnow
from utils.constants import WU_GOLD
from utils.mongo import MongoClient
from utils.recruit_error_reporting import edit_error, notify as notify_recruit_error


def path_panel(session_id="preview", sections=None, *, media=None, preview=False):
    def button(kind, label):
        return Row().add_interactive_button(
            hikari.ButtonStyle.SECONDARY, f"ticket_v2_rite_choose:{session_id}:{kind}",
            label=label, is_disabled=preview,
        )
    panel = [Container(accent_color=WU_GOLD, components=[
        Text(content="## <:warriors_united:1553249482836025425> **Warriors United – Your Rite of Passage Begins**"),
        Text(content=(
            '**“Warrior, your first steps within Warriors United are more than a simple entry… '
            'they mark the beginning of your Rite of Passage.”**\n\n'
            '**“The Apply Button has been replaced. There is no ‘apply’ for a warrior — '
            'only the path you take and the oath you are willing to take.”**'
        )),
        Separator(divider=True),
        Text(content=(
            "### <a:sword_fighting:1533860863147114769> **Rite of Passage to Main**\n"
            "**This path is for those who seek honor, unity, and the strength of the brotherhood.**\n"
            "It is the road toward becoming **Sworn** — a warrior recognized, trusted, and bound to the clan’s code.\n"
            "Select this path if you are ready to prove your worth and rise among your fellow warriors."
        )),
        button("main", "Rite of Passage to Main"),
        Separator(divider=True),
        Text(content=(
            "### <a:money_bag:1553248264042586142> **Rite of Passage to FWA**\n"
            "**This path leads into the fires of challenge and conflict.**\n"
            "It is for those who wish to test themselves in the crucible of battle, competition, or elite trials.\n"
            "Only the bold walk this road, and only the relentless endure it."
        )),
        button("fwa", "Rite of Passage to FWA"),
        Separator(divider=True),
        Text(content=(
            "## <a:orangeflame:1553250319134363732> **Your Choice Defines Your Destiny**\n"
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
    panel = [Container(accent_color=WU_GOLD, components=components)]
    return panel


def build_rite(sections=None, *, media=None, action_id="preview", preview=False):
    return path_panel(action_id, sections, media=media, preview=preview)


async def saved_path_panel(mongo, guild_id, session_id):
    from extensions.commands import content
    sections, media, _ = await content.template_for(mongo, content.DOCUMENTS["rite-of-passage"], guild_id)
    return path_panel(session_id, sections, media=media)


async def _new_path_session(ctx, mongo, source_id, kind):
    session_id = uuid.uuid4().hex
    await insert_state(mongo, {"_id":session_id,"type":kind,"owner_id":int(ctx.user.id),
        "guild_id":int(ctx.guild_id),"channel_id":int(ctx.channel_id),"source_message_id":int(source_id)},
        ttl=timedelta(minutes=30))
    return session_id


async def _owned_path_session(ctx, mongo, session_id, kind):
    state = await get_state(mongo, session_id)
    if (not state or state.get("type") != kind or state.get("owner_id") != int(ctx.user.id)
            or state.get("guild_id") != int(ctx.guild_id) or state.get("channel_id") != int(ctx.channel_id)):
        return None
    return state


def account_clan_panel(session_id):
    row = Row()
    for clan, label, emoji in (("main","Main clan","🏆"),("fwa","FWA clan","💎")):
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY,
            f"ticket_v2_account_choose:{session_id}:{clan}",label=label,emoji=emoji)
    row.add_interactive_button(hikari.ButtonStyle.SECONDARY,
        f"ticket_v2_account_choose:{session_id}:cancel",label="Cancel")
    return [Container(accent_color=WU_GOLD,components=[Text(content="## Add another account"),
        Text(content="Which clan will this account join?"),row])]


async def open_account_clans(ctx, mongo, source_id):
    # Called only after the common public-intake binding/readiness check.
    sid = await _new_path_session(ctx,mongo,source_id,"ticket_account_clans")
    await ctx.interaction.edit_initial_response(components=account_clan_panel(sid))


@register_action("ticket_v2_account_choose", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_account_clan(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                             bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    sid, _, clan = action_id.partition(":")
    state = await _owned_path_session(ctx,mongo,sid,"ticket_account_clans")
    if state is None or clan not in {"main","fwa","cancel"}:
        await ctx.respond("This clan choice expired. Select Add another account again.",ephemeral=True)
        return
    # A fixed-lifetime, owner-bound choice is consumed once before any ticket
    # action; the common account slot still guards races between different panels.
    claimed = await update_state(mongo,{"_id":sid,"type":"ticket_account_clans",
        "owner_id":int(ctx.user.id),"guild_id":int(ctx.guild_id),"channel_id":int(ctx.channel_id),
        "choice":{"$exists":False},"expires_at":{"$gt":utcnow()}},{"$set":{"choice":clan}})
    if not claimed.matched_count:
        await ctx.respond("This clan choice was already used. Select Add another account again to review your request.",ephemeral=True)
        return
    if clan == "cancel":
        await ctx.defer(ephemeral=True)
        await ctx.interaction.edit_initial_response(content="Request cancelled. No request was opened.",components=[])
        return
    await handlers.handle_create_ticket(ctx=ctx,action_id="public:account",bot=bot,mongo=mongo,
        _source_message_id=int(state["source_message_id"]),_account_clan=clan)


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
        await edit_error(ctx, content="This entry panel is not active. Please use the current ticket panel.")
        return
    session_id = await _new_path_session(ctx,mongo,source_id,"ticket_rite_paths")
    await ctx.interaction.edit_initial_response(components=await saved_path_panel(mongo, int(ctx.guild_id), session_id))


@register_action("ticket_v2_rite_choose", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_path(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                      bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    session_id, _, kind = action_id.partition(":")
    state = await _owned_path_session(ctx,mongo,session_id,"ticket_rite_paths")
    if state is None or kind not in {"main","fwa"}:
        await ctx.respond(await notify_recruit_error(ctx, "This path selection has expired. Open Earn Your Rite of Passage again."), ephemeral=True)
        return
    # Reuse all existing readiness, current binding, rollout, cooldown, and slot
    # checks. The private chooser's message ID is never an intake authority.
    await handlers.handle_create_ticket(
        ctx=ctx, action_id=f"public:{kind}", bot=bot, mongo=mongo,
        _source_message_id=int(state["source_message_id"]),
    )
