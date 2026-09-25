"""Private FWA blacklist browser and role-gated editor inside /manage."""
from __future__ import annotations

import copy
import math
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import coc
import hikari
import lightbulb

from extensions.components import register_action
from extensions.commands.fwa.war_plans import FWA_WAR_PLANS_CONFIG
from utils.component_state import get_state, insert_state
from utils.constants import GOLDENROD_ACCENT, RED_ACCENT
from utils.fwa_blacklist import add_blacklisted, list_blacklisted, remove_blacklisted
from utils.fwa_points_parser import sanitize_tag
from utils.manage_ui import breadcrumb, button_emoji
from utils.mongo import MongoClient


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
PAGE_SIZE = 10
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
ROLE_ID = FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"]
_RAW_TAG = re.compile(r"#?[0-9A-Za-z]{3,15}\Z")
_STATE_FIELDS = (
    "kind", "user_id", "guild_id", "manage_token", "view", "page", "query",
    "selected_tag", "selected_added_at", "selected_name",
)


def _identity(ctx: Any) -> tuple[int | None, int | None]:
    user = getattr(getattr(ctx, "user", None), "id", None)
    guild = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return (int(user) if user is not None else None,
            int(guild) if guild is not None else None)


def _can_manage(ctx: Any) -> bool:
    member = getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)
    if member is None:
        return False
    role_ids = {int(role) for role in getattr(member, "role_ids", ())}
    if hasattr(member, "get_roles"):
        role_ids.update(int(role.id) for role in member.get_roles())
    return ROLE_ID in role_ids


def _safe(value: Any, limit: int = 100) -> str:
    return (str(value).replace("@", "＠").replace("`", "ˋ")
            .replace("<", "‹").replace(">", "›")
            .replace("\n", " ").replace("\r", " ")[:limit])


def _tag(raw: str) -> str | None:
    raw = raw.strip()
    return sanitize_tag(raw) if _RAW_TAG.fullmatch(raw) else None


def _date(value: Any) -> str:
    if not value:
        return "unknown"
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return _safe(value, 10)


def _buttons(*options: tuple[str, str, hikari.ButtonStyle, bool]) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, style, disabled in options:
        row.add_interactive_button(style, custom_id, label=label, emoji=button_emoji(label), is_disabled=disabled)
    return row


def _error(message: str, state: dict | None = None) -> list:
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("FWA", "Blacklist") + "\n## FWA Blacklist"),
        hikari.impl.TextDisplayComponentBuilder(content=_safe(message, 350)),
    ]
    if state is not None:
        rows.extend([
            _buttons((f"fwa_blacklist_refresh:{state['_id']}", "Refresh", hikari.ButtonStyle.SECONDARY, False)),
            hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
            _buttons(
                (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
                (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
            ),
        ])
    else:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="Run `/manage` to open a fresh private panel."))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


async def _state(ctx: Any, mongo: MongoClient, token: str, *, view: str | None = None) -> tuple[dict | None, str | None]:
    try:
        state = await get_state(mongo, token)
    except Exception:
        return None, "Blacklist controls are temporarily unavailable. Run `/manage` to retry."
    user, guild = _identity(ctx)
    if state is None or user is None or guild is None:
        return None, "This panel expired. Run `/manage` to open it again."
    if state.get("kind") != "fwa_blacklist":
        return None, "This is not a FWA Blacklist panel. Open Blacklist from `/manage`."
    if state.get("user_id") != user or state.get("guild_id") != guild:
        return None, "Open your own FWA Blacklist panel in this server."
    if view is not None and state.get("view") != view:
        return None, "This Blacklist panel is out of date. Use Refresh."
    return state, None


async def _new(mongo: MongoClient, **fields: Any) -> dict:
    state = {key: copy.deepcopy(value) for key, value in fields.items() if key in _STATE_FIELDS}
    state["_id"] = uuid.uuid4().hex
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _next(mongo: MongoClient, state: dict, **changes: Any) -> dict:
    values = {key: state[key] for key in _STATE_FIELDS if key in state}
    values.update(changes)
    return await _new(mongo, **values)


def _visible(entries: list[dict], state: dict) -> tuple[list[dict], int, int, int]:
    query = str(state.get("query") or "").strip().casefold().lstrip("#")
    matches = [
        entry for entry in entries
        if not query or query in str(entry.get("name") or "").casefold()
        or query in str(entry.get("_id") or "").casefold()
    ]
    pages = max(1, math.ceil(len(matches) / PAGE_SIZE))
    page = max(0, min(int(state.get("page", 0)), pages - 1))
    return matches[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], len(matches), page, pages


def _selected_on_page(showing: list[dict], state: dict) -> dict | None:
    tag = state.get("selected_tag")
    return next((entry for entry in showing if entry.get("_id") == tag
                 and entry.get("added_at") == state.get("selected_added_at")), None)


async def _panel(mongo: MongoClient, state: dict, *, editor: bool, notice: str | None = None) -> list:
    try:
        entries = await list_blacklisted(mongo)
        showing, match_count, page, pages = _visible(entries, state)
    except Exception:
        return _error("Could not load the blacklist. Use Refresh to retry.", state)
    selected = _selected_on_page(showing, state)
    query = str(state.get("query") or "").strip()
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("FWA", "Blacklist") + "\n## FWA Blacklist"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**{len(entries)} total** · **{match_count} matching** · Page {page + 1}/{pages}\n"
            f"Search: {_safe(query, 80) if query else 'All clans'} · "
            f"Access: {'FWA Clan Rep' if editor else 'View only'}"
        )),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {_safe(notice, 500)}"))
    if showing:
        lines = []
        for entry in showing:
            tag = _safe(entry.get("_id") or "?", 20)
            name = _safe(entry.get("name") or tag, 65)
            source = _safe(entry.get("source") or "unknown", 25)
            classification = _safe(entry.get("classification") or "", 30)
            detail = f" · {classification}" if classification else ""
            lines.append(f"• **{name}** (`#{tag}`){detail} · {source} · added {_date(entry.get('added_at'))}")
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="\n".join(lines)))
    else:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
            "No clans match this search." if query else "The FWA blacklist is empty."
        )))
    sid = state["_id"]
    rows.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
    rows.append(_buttons(
        (f"fwa_blacklist_page:{sid}|{page - 1}", "Previous", hikari.ButtonStyle.SECONDARY, page == 0),
        (f"fwa_blacklist_page:{sid}|{page + 1}", "Next page", hikari.ButtonStyle.SECONDARY, page >= pages - 1),
        (f"fwa_blacklist_refresh:{sid}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
    ))
    rows.append(_buttons(
        (f"fwa_blacklist_search:{sid}", "Search clans", hikari.ButtonStyle.SECONDARY, False),
        (f"fwa_blacklist_clear:{sid}", "Clear search", hikari.ButtonStyle.SECONDARY, not bool(query)),
        *((f"fwa_blacklist_add:{sid}", "Add clan", hikari.ButtonStyle.PRIMARY, False),) if editor else (),
    ))
    if editor and showing:
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(
            f"fwa_blacklist_select:{sid}", placeholder="Choose a clan on this page to remove",
            min_values=1, max_values=1,
        )
        for entry in showing:
            tag = str(entry.get("_id") or "")
            if _tag(tag) != tag:
                continue
            menu.add_option(f"{_safe(entry.get('name') or tag, 65)} (#{tag})", tag,
                            is_default=selected is not None and selected.get("_id") == tag)
        if menu.options:
            rows.append(menu_row)
            rows.append(_buttons(
                (f"fwa_blacklist_remove:{sid}", "Remove selected clan", hikari.ButtonStyle.DANGER, selected is None),
            ))
    rows.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
    rows.append(_buttons(
        (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
        (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
    ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


async def open_dashboard(ctx: Any, mongo: MongoClient, *, manage_token: str, deferred: bool = False) -> None:
    if not deferred and not getattr(ctx.interaction, "custom_id", None):
        await ctx.defer(ephemeral=True)
    user, guild = _identity(ctx)
    if user is None or guild is None:
        await ctx.interaction.edit_initial_response(
            components=_error("Open `/manage` inside a server."), **NO_MENTIONS,
        )
        return
    try:
        state = await _new(
            mongo, kind="fwa_blacklist", user_id=user, guild_id=guild, manage_token=manage_token,
            view="list", page=0, query="",
        )
    except Exception:
        await ctx.interaction.edit_initial_response(
            components=_error("Could not open the blacklist. Run `/manage` to retry."), **NO_MENTIONS,
        )
        return
    await ctx.interaction.edit_initial_response(
        components=await _panel(mongo, state, editor=_can_manage(ctx)), **NO_MENTIONS,
    )


@register_action("fwa_blacklist_refresh", preload_state=False)
@lightbulb.di.with_di
async def refresh(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    try:
        next_state = await _next(mongo, state, view="list", selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        return _error("Could not refresh this panel. Try again.", state)
    return await _panel(mongo, next_state, editor=_can_manage(ctx), notice="Blacklist refreshed.")


@register_action("fwa_blacklist_page", preload_state=False)
@lightbulb.di.with_di
async def page(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, sep, raw_page = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid, view="list")
    if problem:
        return _error(problem)
    try:
        page_number = int(raw_page) if sep else 0
        next_state = await _next(mongo, state, page=max(0, page_number), selected_tag=None, selected_added_at=None, selected_name=None)
    except (ValueError, OverflowError):
        return await _panel(mongo, state, editor=_can_manage(ctx), notice="Choose a valid page.")
    except Exception:
        return _error("Could not change pages. Use Refresh to retry.", state)
    return await _panel(mongo, next_state, editor=_can_manage(ctx))


@register_action("fwa_blacklist_clear", preload_state=False)
@lightbulb.di.with_di
async def clear(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        return _error(problem)
    try:
        next_state = await _next(mongo, state, page=0, query="", selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        return _error("Could not clear the search. Use Refresh to retry.", state)
    return await _panel(mongo, next_state, editor=_can_manage(ctx))


@register_action("fwa_blacklist_search", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def search(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    await ctx.respond_with_modal(
        title="Search FWA blacklist", custom_id=f"fwa_blacklist_search_submit:{action_id}",
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            "query", "Clan name or tag", required=True, min_length=1, max_length=80,
            value=str(state.get("query") or "") or hikari.UNDEFINED,
        )],
    )


def _modal_value(ctx: Any, key: str) -> str:
    return next((str(item.value or "")
                 for row in getattr(ctx.interaction, "components", ()) for item in row
                 if getattr(item, "custom_id", None) == key), "")


async def _ack_modal(ctx: Any) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)


async def _modal_edit(ctx: Any, panel: list) -> None:
    await ctx.interaction.edit_initial_response(components=panel, **NO_MENTIONS)


@register_action("fwa_blacklist_search_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def search_submit(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    query = _modal_value(ctx, "query").strip()
    if not 1 <= len(query) <= 80:
        await _modal_edit(ctx, await _panel(mongo, state, editor=_can_manage(ctx), notice="Enter a clan name or tag to search."))
        return
    try:
        next_state = await _next(mongo, state, page=0, query=query, selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        await _modal_edit(ctx, _error("Search is unavailable. Use Refresh to retry.", state))
        return
    await _modal_edit(ctx, await _panel(mongo, next_state, editor=_can_manage(ctx)))


@register_action("fwa_blacklist_add", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    if not _can_manage(ctx):
        await ctx.respond("The FWA Clan Rep role is required to add clans.", ephemeral=True)
        return
    await ctx.respond_with_modal(
        title="Add clan to FWA blacklist", custom_id=f"fwa_blacklist_add_submit:{action_id}",
        components=[
            hikari.impl.ModalActionRowBuilder().add_text_input(
                "tag", "Clan tag", placeholder="#ABC123", required=True,
                min_length=3, max_length=16,
            ),
            hikari.impl.ModalActionRowBuilder().add_text_input(
                "name", "Clan name (optional)", required=False, max_length=80,
            ),
        ],
    )


@register_action("fwa_blacklist_add_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add_submit(
    ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED, **_: Any,
) -> None:
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    if not _can_manage(ctx):
        await _modal_edit(ctx, _error("The FWA Clan Rep role is required to add clans.", state))
        return
    raw_tag = _modal_value(ctx, "tag").strip()
    tag = _tag(raw_tag)
    name = _modal_value(ctx, "name").strip()
    if tag is None:
        await _modal_edit(ctx, await _panel(mongo, state, editor=True, notice="Enter a plain clan tag of 3–15 letters or digits."))
        return
    if len(name) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        await _modal_edit(ctx, await _panel(mongo, state, editor=True, notice="Clan name must be at most 80 characters on one line."))
        return
    if not name:
        try:
            clan = await coc_client.get_clan(f"#{tag}")
            name = str(clan.name).strip()
        except Exception as exc:
            await _modal_edit(ctx, await _panel(mongo, state, editor=True,
                                                notice=f"Clan lookup failed ({type(exc).__name__}). Enter a name to add it."))
            return
        if not name or len(name) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name):
            await _modal_edit(ctx, await _panel(mongo, state, editor=True,
                                                notice="Clan lookup returned no usable name. Enter a name to add it."))
            return
    member = getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)
    author_name = getattr(member, "display_name", None) or getattr(ctx.user, "username", "Unknown")
    try:
        added = await add_blacklisted(mongo, tag, name, ctx.user.id, author_name, "manual")
    except Exception:
        await _modal_edit(ctx, _error("Could not save this clan. Use Refresh to retry.", state))
        return
    if added is None:
        await _modal_edit(ctx, await _panel(mongo, state, editor=True, notice="Invalid clan tag; nothing was saved."))
        return
    try:
        next_state = await _next(mongo, state, view="list", page=0, query="", selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        await _modal_edit(ctx, _error(f"Clan #{tag} was saved, but the panel could not refresh. Run `/manage` again."))
        return
    await _modal_edit(ctx, await _panel(mongo, next_state, editor=True, notice=f"Clan {name} (#{tag}) added to the blacklist."))


@register_action("fwa_blacklist_select", preload_state=False)
@lightbulb.di.with_di
async def select(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        return _error(problem)
    if not _can_manage(ctx):
        return _error("The FWA Clan Rep role is required to remove clans.", state)
    values = getattr(ctx.interaction, "values", ()) or ()
    try:
        entries = await list_blacklisted(mongo)
        showing, _, _, _ = _visible(entries, state)
    except Exception:
        return _error("Could not verify the selected clan. Use Refresh to retry.", state)
    tag = str(values[0]) if len(values) == 1 else ""
    entry = next((item for item in showing if item.get("_id") == tag and _tag(tag) == tag), None)
    if entry is None:
        return await _panel(mongo, state, editor=True, notice="Choose a clan shown on this page.")
    try:
        next_state = await _next(mongo, state, selected_tag=tag,
                                 selected_added_at=entry.get("added_at"),
                                 selected_name=entry.get("name") or tag)
    except Exception:
        return _error("Could not select that clan. Use Refresh to retry.", state)
    return await _panel(mongo, next_state, editor=True, notice=f"#{tag} selected. Choose Remove selected clan to review.")


@register_action("fwa_blacklist_remove", preload_state=False)
@lightbulb.di.with_di
async def remove(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="list")
    if problem:
        return _error(problem)
    if not _can_manage(ctx):
        return _error("The FWA Clan Rep role is required to remove clans.", state)
    try:
        entries = await list_blacklisted(mongo)
        showing, _, _, _ = _visible(entries, state)
    except Exception:
        return _error("Could not verify the selected clan. Use Refresh to retry.", state)
    entry = _selected_on_page(showing, state)
    if entry is None:
        return await _panel(mongo, state, editor=True, notice="Selection changed. Choose a clan on this page again.")
    try:
        review_state = await _next(
            mongo, state, view="confirm",
            selected_name=entry.get("name") or entry["_id"],
        )
    except Exception:
        return _error("Could not open confirmation. Use Refresh to retry.", state)
    return _confirm(review_state)


def _confirm(state: dict) -> list:
    tag = _safe(state.get("selected_tag") or "?", 20)
    name = _safe(state.get("selected_name") or tag, 80)
    return [hikari.impl.ContainerComponentBuilder(accent_color=RED_ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("FWA", "Blacklist", "Remove") + "\n## Remove clan?"),
        hikari.impl.TextDisplayComponentBuilder(content=f"Remove **{name}** (`#{tag}`) from the FWA blacklist?"),
        hikari.impl.TextDisplayComponentBuilder(content="This changes the shared list used by FWA war plans."),
        _buttons(
            (f"fwa_blacklist_confirm:{state['_id']}", "Yes, remove clan", hikari.ButtonStyle.DANGER, False),
            (f"fwa_blacklist_cancel:{state['_id']}", "No, keep clan", hikari.ButtonStyle.SECONDARY, False),
        ),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        _buttons(
            (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
            (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])]


@register_action("fwa_blacklist_cancel", preload_state=False)
@lightbulb.di.with_di
async def cancel(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="confirm")
    if problem:
        return _error(problem)
    try:
        next_state = await _next(mongo, state, view="list", selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        return _error("Could not return to the list. Use Refresh to retry.", state)
    return await _panel(mongo, next_state, editor=_can_manage(ctx), notice="Removal cancelled.")


@register_action("fwa_blacklist_confirm", preload_state=False)
@lightbulb.di.with_di
async def confirm(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="confirm")
    if problem:
        return _error(problem)
    if not _can_manage(ctx):
        return _error("The FWA Clan Rep role is required to remove clans.", state)
    tag = state.get("selected_tag")
    if not isinstance(tag, str) or _tag(tag) != tag:
        return _error("Selection expired. Use Refresh and choose a clan again.", state)
    try:
        entry = await mongo.fwa_blacklist.find_one({"_id": tag})
    except Exception:
        return _error("Could not verify this clan. Use Refresh to retry.", state)
    if entry is None:
        next_state = await _next(mongo, state, view="list", selected_tag=None, selected_added_at=None, selected_name=None)
        return await _panel(mongo, next_state, editor=True, notice=f"#{tag} is no longer on the blacklist.")
    if entry.get("added_at") != state.get("selected_added_at"):
        next_state = await _next(mongo, state, view="list", selected_tag=None, selected_added_at=None, selected_name=None)
        return await _panel(mongo, next_state, editor=True, notice="That clan entry changed. Select it again before removing.")
    try:
        removed = await remove_blacklisted(mongo, tag, expected_added_at=state.get("selected_added_at"))
    except Exception:
        return _error("Could not remove this clan. Use Refresh to retry.", state)
    try:
        next_state = await _next(mongo, state, view="list", selected_tag=None, selected_added_at=None, selected_name=None)
    except Exception:
        return _error("Removal finished, but the panel could not refresh. Run `/manage` again.")
    return await _panel(mongo, next_state, editor=True, notice=(
        f"#{tag} removed from the blacklist." if removed else "That entry changed or was removed. Select it again if you still want to remove it."
    ))
