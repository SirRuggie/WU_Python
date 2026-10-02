"""Administrator editor for the FWA calculator; layout settings are guild-specific."""
from datetime import timedelta
import uuid
import hikari
import lightbulb
from extensions.components import register_action
from utils import war_weight as store
from utils.component_state import insert_state, get_state
from utils.mongo import MongoClient
from utils.constants import GOLDENROD_ACCENT

loader = lightbulb.Loader()
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)


def admin(ctx):
    member = getattr(ctx.interaction, "member", None)
    return bool(getattr(member, "permissions", 0) & hikari.Permissions.ADMINISTRATOR)


async def session(ctx, mongo, token):
    state = await get_state(mongo, token)
    if not admin(ctx) or not state or state.get("type") != "war_weight_editor" or state.get("user_id") != int(ctx.user.id) or state.get("guild_id") != ctx.interaction.guild_id:
        raise ValueError("Open your own War Weight panel in /manage with Administrator permission.")
    return state


def button(row, action, label):
    return row.add_interactive_button(hikari.ButtonStyle.SECONDARY, action, label=label)


async def panel(mongo, state, notice=""):
    config = await store.load(mongo, state["guild_id"])
    # Every rendered panel gets a fixed config revision: stale modals cannot overwrite newer edits.
    state = {**state, "_id": uuid.uuid4().hex, "revision": config["revision"]}
    await insert_state(mongo, state, ttl=timedelta(minutes=30))
    sid = state["_id"]
    entries = store.ranges(config)
    children = [hikari.impl.TextDisplayComponentBuilder(content="## War Weight\nManage → FWA → War Weight"),
        hikari.impl.TextDisplayComponentBuilder(content=f"Reference list: **TH{config['minimum_th']}–TH{max(entries)}**\nCalculations still use all configured ranges. Enter total weights, not single-storage values.")]
    if notice:
        children.append(hikari.impl.TextDisplayComponentBuilder(content=notice))
    children += [hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content="\n".join(
            f"**TH{th}** · {data['min']:,}–{data['max']:,} · Emoji: {data.get('emoji') or f'Automatic (TH_{th})'}"
            for th, data in sorted(entries.items(), reverse=True)))]
    row = hikari.impl.MessageActionRowBuilder()
    menu = row.add_text_menu(f"weight_edit:{sid}", placeholder="Edit a Town Hall")
    for th in sorted(entries, reverse=True):
        menu.add_option(f"Town Hall {th}", str(th))
    children.append(row)
    row = hikari.impl.MessageActionRowBuilder()
    menu = row.add_text_menu(f"weight_minimum:{sid}", placeholder="Lowest Town Hall to show")
    for th in sorted(entries, reverse=True):
        menu.add_option(f"TH{th} and above", str(th))
    children.append(row)
    row = hikari.impl.MessageActionRowBuilder()
    button(row, f"weight_add:{sid}", "Add Town Hall")
    button(row, f"weight_refresh:{sid}", "Refresh")
    children += [row, hikari.impl.SeparatorComponentBuilder(divider=True),
        button(hikari.impl.MessageActionRowBuilder(), f"manage_fwa:{state['manage_token']}", "Return to FWA"),
        hikari.impl.TextDisplayComponentBuilder(content="-# Emoji: automatic name lookup, custom emoji name, or pasted custom emoji. Changes apply to new calculator results.")]
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=children)]


async def open_dashboard(ctx, mongo, *, manage_token, deferred=False):
    if not admin(ctx):
        await ctx.respond("Administrator permission is required.", ephemeral=True)
        return
    if not deferred:
        await ctx.defer(ephemeral=True)
    state = dict(type="war_weight_editor", user_id=int(ctx.user.id), guild_id=int(ctx.interaction.guild_id), manage_token=manage_token)
    await ctx.interaction.edit_initial_response(components=await panel(mongo, state), **NO_MENTIONS)


@register_action("weight_refresh", preload_state=False)
@lightbulb.di.with_di
async def refresh(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    try:
        return await panel(mongo, await session(ctx, mongo, action_id))
    except ValueError as exc:
        return [hikari.impl.TextDisplayComponentBuilder(content=str(exc))]


@register_action("weight_minimum", preload_state=False)
@lightbulb.di.with_di
async def minimum(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    try:
        state = await session(ctx, mongo, action_id)
        config = await store.load(mongo, state["guild_id"])
        if state["revision"] != config["revision"]:
            return await panel(mongo, state, "Settings changed. Please select the minimum again.")
        config["minimum_th"] = int(ctx.interaction.values[0])
        await store.save(mongo, state["guild_id"], config, ctx.user.id)
        return await panel(mongo, state, "Lowest displayed Town Hall saved.")
    except ValueError as exc:
        return [hikari.impl.TextDisplayComponentBuilder(content=str(exc))]


async def show_modal(ctx, action_id, mongo, *, add=False):
    try:
        state = await session(ctx, mongo, action_id)
        config = await store.load(mongo, state["guild_id"])
        if state["revision"] != config["revision"]:
            raise ValueError("Settings changed. Refresh before editing.")
        th = None if add else int(ctx.interaction.values[0])
        entry = config["ranges"].get(str(th), {})
        modal_state = {**state, "_id": uuid.uuid4().hex, "editing_th": th, "adding": add}
        await insert_state(mongo, modal_state, ttl=timedelta(minutes=30))
        fields = [("th", "Town Hall level", str(th or "")), ("low", "Minimum total war weight", str(entry.get("min", ""))),
                  ("high", "Maximum total war weight", str(entry.get("max", ""))), ("emoji", "Emoji name or custom emoji (blank = auto)", entry.get("emoji", ""))]
        await ctx.respond_with_modal(title="Add Town Hall" if add else f"Edit TH{th}", custom_id=f"weight_save:{modal_state['_id']}",
            components=[hikari.impl.ModalActionRowBuilder().add_text_input(key, label, value=value or hikari.UNDEFINED,
                required=key != "emoji", max_length=80 if key == "emoji" else 9) for key, label, value in fields])
    except ValueError as exc:
        await ctx.respond(str(exc), ephemeral=True)


@register_action("weight_add", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await show_modal(ctx, action_id, mongo, add=True)


@register_action("weight_edit", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await show_modal(ctx, action_id, mongo)


@register_action("weight_save", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def save(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    state = None
    try:
        state = await session(ctx, mongo, action_id)
        values = {item.custom_id: item.value or "" for row in ctx.interaction.components for item in row}
        try:
            th, low, high = (int(values[key].replace(",", "").strip()) for key in ("th", "low", "high"))
        except ValueError:
            raise ValueError("Enter whole numbers for Town Hall and weights (for example 181000).") from None
        config = await store.load(mongo, state["guild_id"])
        if config["revision"] != state["revision"]:
            raise ValueError("Settings changed. Refresh and try again.")
        if state["adding"] and str(th) in config["ranges"]:
            raise ValueError("That Town Hall already exists. Choose Edit instead.")
        if not state["adding"] and th != state["editing_th"]:
            raise ValueError("Use Add Town Hall for a new level. Keep this entry's level unchanged.")
        config = store.edit_entry(config, th, low, high, values["emoji"])
        await store.save(mongo, state["guild_id"], config, ctx.user.id)
        notice = f"TH{th} saved."
    except ValueError as exc:
        notice = str(exc)
    components = await panel(mongo, state, notice) if state else [hikari.impl.TextDisplayComponentBuilder(content=notice)]
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)
