"""Private administrator controls for the running FWA points monitor."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import math
import re
from typing import Any
import uuid

import hikari
import lightbulb

from extensions.components import register_action
from extensions.tasks import fwa_points_monitor as monitor
from utils.component_state import get_state, insert_state
from utils.constants import GOLD_ACCENT
from utils.fwa_points_parser import sanitize_tag
from utils.mongo import MongoClient


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
PAGE_SIZE = 8
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
_RAW_TAG = re.compile(r"#?[0-9A-Za-z]{3,15}\Z")


def _identity(ctx: Any) -> tuple[int | None, int | None]:
    user = getattr(getattr(ctx, "user", None), "id", None)
    guild = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return (int(user) if user is not None else None,
            int(guild) if guild is not None else None)


def _admin(ctx: Any) -> bool:
    member = getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    return bool(permissions & hikari.Permissions.ADMINISTRATOR)


def _safe(value: Any, limit: int = 80) -> str:
    return (str(value).replace("@", "＠").replace("`", "ˋ")
            .replace("<", "‹").replace(">", "›")
            .replace("\n", " ").replace("\r", " ")[:limit])


def _error(message: str, state: dict | None = None) -> list:
    rows = [hikari.impl.TextDisplayComponentBuilder(content=f"## FWA Points Monitor\n{message}")]
    if state is not None:
        rows.append(_buttons(
            (f"fwa_points_refresh:{state['_id']}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
            (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
        ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=rows)]


async def _state(ctx: Any, mongo: MongoClient, token: str) -> tuple[dict | None, str | None]:
    state = await get_state(mongo, token)
    user, guild = _identity(ctx)
    if (state is None or user is None or guild is None
            or state.get("user_id") != user or state.get("guild_id") != guild):
        return None, "Open your own FWA Points Monitor from `/manage`."
    if not _admin(ctx):
        return None, "Administrator permission is required."
    return state, None


async def _new(mongo: MongoClient, **fields: Any) -> dict:
    state = {**fields, "_id": uuid.uuid4().hex}
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _next(mongo: MongoClient, state: dict, **changes: Any) -> dict:
    return await _new(mongo, **{**state, **changes})


def _buttons(*options: tuple[str, str, hikari.ButtonStyle, bool]) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, style, disabled in options:
        row.add_interactive_button(style, custom_id, label=label, is_disabled=disabled)
    return row


def _monitor_status() -> tuple[str, str, int]:
    running = bool(monitor.detector_task and not monitor.detector_task.done())
    recovery = (monitor.startup_reconciler.status_text()
                if monitor.startup_reconciler is not None else "Stopped")
    retries = sum(not task.done() for task in monitor.active_catchups.values())
    return ("Running" if running else "Not running", recovery, retries)


async def _snapshot(mongo: MongoClient) -> tuple[dict, list[dict]]:
    config = await monitor.load_config(mongo)
    watch = await monitor.effective_watch_list(config, mongo, strict=True)
    return config, watch


async def _panel(mongo: MongoClient, state: dict, notice: str | None = None) -> list:
    try:
        config, watch = await _snapshot(mongo)
    except Exception:
        return _error("Could not refresh monitor status. Try Refresh when clan data recovers.", state)
    pages = max(1, math.ceil(len(watch) / PAGE_SIZE))
    page = max(0, min(int(state.get("page", 0)), pages - 1))
    showing = watch[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    detector, recovery, retries = _monitor_status()
    selected = state.get("selected_extra")
    extra_options = [entry for entry in showing if entry["source"] == "extra"]
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content="## FWA Points Monitor"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**Monitor:** {'Enabled' if config['enabled'] else 'Disabled'} · "
            f"**Detector:** {detector} · **Active retries:** {retries}\n"
            f"**Startup recovery:** {_safe(recovery, 180)}"
        )),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"### Effective watch list · {len(watch)} clans · Page {page + 1}/{pages}\n"
            "FWA clans are automatic; extras can be removed below."
        )),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {_safe(notice, 700)}"))
    for entry in showing:
        tag = entry["tag"]
        record = await mongo.fwa_points.find_one({"_id": tag})
        if record and record.get("raw_verdict"):
            verdict = _safe(record["raw_verdict"], 90)
            last = f"{verdict} · War #{record.get('war_number', '?')} · {_safe(record.get('scraped_at', '?'), 50)}"
        else:
            last = "No verdict yet"
        source = "Automatic FWA" if entry["source"] == "clan_type" else "Extra"
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
            f"**{_safe(entry['name'], 55)}** (`{tag}`) · {source}\n-# {last}"
        )))
    if not showing:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="No clans are watched yet."))
    rows.append(_buttons(
        (f"fwa_points_page:{state['_id']}|{page - 1}", "Previous", hikari.ButtonStyle.SECONDARY, page == 0),
        (f"fwa_points_page:{state['_id']}|{page + 1}", "Next", hikari.ButtonStyle.SECONDARY, page >= pages - 1),
        (f"fwa_points_refresh:{state['_id']}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
    ))
    rows.append(_buttons(
        (f"fwa_points_toggle:{state['_id']}|on", "Enable", hikari.ButtonStyle.SECONDARY, bool(config["enabled"])),
        (f"fwa_points_toggle:{state['_id']}|off", "Disable", hikari.ButtonStyle.SECONDARY, not bool(config["enabled"])),
        (f"fwa_points_add:{state['_id']}", "Add extra clan", hikari.ButtonStyle.SECONDARY, False),
    ))
    if extra_options:
        menu_row = hikari.impl.MessageActionRowBuilder()
        select = menu_row.add_text_menu(
            f"fwa_points_select_extra:{state['_id']}", placeholder="Choose an extra clan to remove",
            min_values=1, max_values=1,
        )
        for entry in extra_options:
            select.add_option(f"{_safe(entry['name'], 65)} ({entry['tag']})", entry["tag"],
                              is_default=entry["tag"] == selected)
        rows.append(menu_row)
        rows.append(_buttons((f"fwa_points_remove:{state['_id']}", "Remove selected extra",
                              hikari.ButtonStyle.DANGER,
                              not any(entry["tag"] == selected for entry in extra_options))))
    rows.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
    rows.append(_buttons(
        (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
        (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
    ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=rows)]


async def open_dashboard(ctx: Any, mongo: MongoClient, *, manage_token: str,
                         deferred: bool = False) -> None:
    if not deferred:
        await ctx.defer(ephemeral=True)
    user, guild = _identity(ctx)
    if user is None or guild is None or not _admin(ctx):
        await ctx.interaction.edit_initial_response(
            components=_error("Administrator permission is required."), **NO_MENTIONS,
        )
        return
    state = await _new(mongo, user_id=user, guild_id=guild, manage_token=manage_token, page=0)
    await ctx.interaction.edit_initial_response(components=await _panel(mongo, state), **NO_MENTIONS)


@register_action("fwa_points_refresh", preload_state=False)
@lightbulb.di.with_di
async def refresh(ctx: Any, action_id: str,
                  mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    return await _panel(mongo, await _next(mongo, state), "Status refreshed.")


@register_action("fwa_points_page", preload_state=False)
@lightbulb.di.with_di
async def page(ctx: Any, action_id: str,
               mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, sep, number = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid)
    if problem:
        return _error(problem)
    try:
        target = int(number) if sep else 0
    except ValueError:
        target = 0
    return await _panel(mongo, await _next(mongo, state, page=max(0, target), selected_extra=None))


@register_action("fwa_points_toggle", preload_state=False)
@lightbulb.di.with_di
async def toggle(ctx: Any, action_id: str,
                 mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, sep, choice = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid)
    if problem:
        return _error(problem)
    if not sep or choice not in {"on", "off"}:
        return await _panel(mongo, state, "Choose Enable or Disable.")
    cancelled = await monitor.set_monitor_enabled(mongo, choice == "on")
    notice = ("Monitor enabled. Checks resume on the next detector pass (within 10 minutes)." if choice == "on" else
              f"Monitor disabled; stopped {cancelled} active retry task(s).")
    return await _panel(mongo, await _next(mongo, state), notice)


@register_action("fwa_points_add", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add(ctx: Any, action_id: str,
              mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    await ctx.respond_with_modal(
        title="Add extra FWA points clan",
        custom_id=f"fwa_points_add_submit:{action_id}",
        components=[
            hikari.impl.ModalActionRowBuilder().add_text_input(
                "tag", "Clan tag", placeholder="#ABC123", required=True,
                min_length=3, max_length=16,
            ),
            hikari.impl.ModalActionRowBuilder().add_text_input(
                "name", "Display name", required=True, min_length=1, max_length=80,
            ),
        ],
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


@register_action("fwa_points_add_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add_submit(ctx: Any, action_id: str,
                     mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        await ctx.interaction.edit_initial_response(components=_error(problem), **NO_MENTIONS)
        return
    raw_tag = _modal_value(ctx, "tag").strip()
    name = _modal_value(ctx, "name").strip()
    tag = sanitize_tag(raw_tag)
    if not _RAW_TAG.fullmatch(raw_tag) or not tag or not 1 <= len(name) <= 80:
        response = await _panel(mongo, state, "Enter a plain clan tag and a name of 1–80 characters.")
    elif any(char in name for char in "@<>`\n\r"):
        response = await _panel(mongo, state, "The display name cannot contain mentions or markup.")
    else:
        try:
            _, watch = await _snapshot(mongo)
        except Exception:
            await ctx.interaction.edit_initial_response(
                components=_error("Watch list unavailable; no extra was added."), **NO_MENTIONS,
            )
            return
        if any(entry["tag"] == tag and entry["source"] == "clan_type" for entry in watch):
            response = await _panel(mongo, state, "That FWA clan is watched automatically; no extra is needed.")
        else:
            await mongo.fwa_points.update_one(
                {"_id": "config"}, monitor.watch_list_replacement_pipeline(tag, name), upsert=True,
            )
            response = await _panel(mongo, await _next(mongo, state), f"Extra clan {name} (`{tag}`) saved.")
    await ctx.interaction.edit_initial_response(components=response, **NO_MENTIONS)


@register_action("fwa_points_select_extra", preload_state=False)
@lightbulb.di.with_di
async def select_extra(ctx: Any, action_id: str,
                       mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    values = getattr(ctx.interaction, "values", ()) or ()
    if len(values) != 1:
        return await _panel(mongo, state, "Choose one extra clan.")
    tag = str(values[0])
    try:
        _, watch = await _snapshot(mongo)
    except Exception:
        return _error("Watch list unavailable; no extra was selected.")
    if not any(entry["tag"] == tag and entry["source"] == "extra" for entry in watch):
        return await _panel(mongo, state, "Automatic FWA clans cannot be removed here.")
    selected = await _next(mongo, state, selected_extra=tag)
    return await _panel(mongo, selected, f"Extra clan `{tag}` selected. Choose Remove to confirm.")


@register_action("fwa_points_remove", preload_state=False)
@lightbulb.di.with_di
async def remove(ctx: Any, action_id: str,
                 mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    tag = state.get("selected_extra")
    try:
        _, watch = await _snapshot(mongo)
    except Exception:
        return _error("Watch list unavailable; no extra was removed.")
    if not tag or not any(entry["tag"] == tag and entry["source"] == "extra" for entry in watch):
        return await _panel(mongo, state, "Choose an extra clan; automatic FWA clans cannot be removed.")
    await mongo.fwa_points.update_one(
        {"_id": "config"}, {"$pull": {"watch_list": {"tag": tag}}},
    )
    task = monitor.active_catchups.get(tag)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return await _panel(mongo, await _next(mongo, state, selected_extra=None),
                        f"Extra clan `{tag}` removed.")
