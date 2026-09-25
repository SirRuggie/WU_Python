"""Private FWA sync and reminder controls inside /manage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
from typing import Any
from urllib.parse import urlparse
import uuid

import hikari
import lightbulb

from extensions.components import register_action
from extensions.tasks import band_sync_ical as sync
from utils.band_ical_parser import DISCOVERY_OFFSET, discord_timestamp
from utils.component_state import get_state, insert_state
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
from utils.manage_ui import breadcrumb, button_emoji


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
CHANNEL_TYPES = (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS)


def _identity(ctx: Any) -> tuple[int | None, int | None]:
    user = getattr(getattr(ctx, "user", None), "id", None)
    guild = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return (int(user) if user is not None else None,
            int(guild) if guild is not None else None)


def _admin(ctx: Any) -> bool:
    member = getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)
    return bool(getattr(member, "permissions", hikari.Permissions.NONE)
                & hikari.Permissions.ADMINISTRATOR)


def _safe(value: Any, limit: int = 130) -> str:
    return (str(value).replace("@", "＠").replace("`", "ˋ")
            .replace("<", "‹").replace(">", "›")
            .replace("\n", " ").replace("\r", " ")[:limit])


def _buttons(*items: tuple[str, str, hikari.ButtonStyle, bool]) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, style, disabled in items:
        row.add_interactive_button(style, custom_id, label=label, emoji=button_emoji(label), is_disabled=disabled)
    return row


def _error(message: str, state: dict | None = None) -> list:
    rows = [hikari.impl.TextDisplayComponentBuilder(content=f"## FWA Sync & Reminders\n{message}")]
    if state is not None:
        rows.append(_buttons(
            (f"fwa_sync_refresh:{state['_id']}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
            (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
        ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


async def _state(ctx: Any, mongo: MongoClient, token: str) -> tuple[dict | None, str | None]:
    state = await get_state(mongo, token)
    user, guild = _identity(ctx)
    if (state is None or user is None or guild is None
            or state.get("user_id") != user or state.get("guild_id") != guild):
        return None, "Open your own FWA Sync & Reminders panel from `/manage`."
    if not _admin(ctx):
        return None, "Administrator permission is required."
    return state, None


async def _new(mongo: MongoClient, **fields: Any) -> dict:
    state = {**fields, "_id": uuid.uuid4().hex}
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _next(mongo: MongoClient, state: dict) -> dict:
    return await _new(mongo, **state)


async def _recent_rows(mongo: MongoClient) -> list[str]:
    rows = []
    cursor = mongo.fwa_sync_deliveries.find(
        {}, {"calendar": 1, "offset": 1, "status": 1, "terminal_reason": 1,
             "failure_count": 1, "start_at": 1},
    ).sort("status_updated_at", -1).limit(30)
    seen = set()
    async for doc in cursor:
        key = (doc.get("calendar"), doc.get("start_at"), doc.get("offset"), doc.get("status"))
        if key in seen:
            continue
        seen.add(key)
        status = _safe(doc.get("status") or "unknown", 35)
        reason = _safe(doc.get("terminal_reason") or "", 85)
        detail = f" · {reason}" if reason else ""
        offset = doc.get("offset")
        rows.append(f"• {_safe(doc.get('calendar') or '?', 30)} · {_safe(offset if offset is not None else '?', 25)} · {status}{detail}")
        if len(rows) >= 5:
            break
    return rows


async def _recent_failures(mongo: MongoClient) -> list[str]:
    rows = []
    cursor = mongo.fwa_sync_deliveries.find(
        {"status": "abandoned"},
        {"calendar": 1, "offset": 1, "terminal_reason": 1, "failure_count": 1},
    ).sort("abandoned_at", -1).limit(3)
    async for doc in cursor:
        offset = doc.get("offset")
        rows.append(
            f"• {_safe(doc.get('calendar') or '?', 30)} · "
            f"{_safe(offset if offset is not None else '?', 25)} · "
            f"{_safe(doc.get('terminal_reason') or 'Delivery abandoned', 90)} "
            f"({int(doc.get('failure_count') or 0)} failed attempt(s))"
        )
    return rows


async def _panel(mongo: MongoClient, state: dict, notice: str | None = None) -> list:
    try:
        config = await sync.load_config(mongo)
        recent = await _recent_rows(mongo)
        failures = await _recent_failures(mongo)
    except Exception:
        return _error("Status is unavailable. Refresh when the database recovers.", state)
    poller = "Running" if sync.poller_task and not sync.poller_task.done() else "Not running"
    recovery = (sync.startup_reconciler.status_text()
                if sync.startup_reconciler is not None else "Stopped")
    feeds = ", ".join(sync.feed_urls().keys()) or "None configured"
    channel_id = config.get("panel_channel_id")
    channel_label = f"<#{int(channel_id)}>" if channel_id else "Not configured"
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("FWA", "Sync & Reminders") + "\n## FWA Sync & Reminders"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**Reminders:** {'Enabled' if config['enabled'] else 'Disabled'} · "
            f"**Poller:** {poller} · **Startup recovery:** {_safe(recovery, 110)}\n"
            f"**Feeds configured:** {_safe(feeds, 80)}"
        )),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**Panel channel:** {channel_label}\n"
            "**Member reminder choices:** 1 hour before · 10 minutes before · At sync time\n"
            f"**BAND fallback link:** {_safe(config['band_url'], 180)}"
        )),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {_safe(notice, 350)}"))
    rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
        "### Recent delivery status\n" + ("\n".join(recent) if recent else "No deliveries yet.")
    )))
    rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
        "### Recent failures\n" + ("\n".join(failures) if failures else "None recorded.")
    )))
    sid = state["_id"]
    rows.extend([
        _buttons(
            (f"fwa_sync_toggle:{sid}|on", "Enable", hikari.ButtonStyle.SECONDARY, bool(config["enabled"])),
            (f"fwa_sync_toggle:{sid}|off", "Disable", hikari.ButtonStyle.SECONDARY, not bool(config["enabled"])),
            (f"fwa_sync_refresh:{sid}", "Refresh", hikari.ButtonStyle.SECONDARY, False),
        ),
        _buttons(
            (f"fwa_sync_check:{sid}", "Check feeds (no DM)", hikari.ButtonStyle.SECONDARY, False),
            (f"fwa_sync_test:{sid}", "Send me test DM", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])
    channel_row = hikari.impl.MessageActionRowBuilder()
    channel_row.add_channel_menu(
        f"fwa_sync_channel:{sid}", channel_types=CHANNEL_TYPES,
        placeholder="Choose sync panel channel", min_values=1, max_values=1,
    )
    rows.append(channel_row)
    rows.append(_buttons(
        (f"fwa_sync_url:{sid}", "Set BAND fallback link", hikari.ButtonStyle.SECONDARY, False),
    ))
    rows.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
    rows.append(_buttons(
        (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
        (f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
    ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


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
    state = await _new(mongo, user_id=user, guild_id=guild, manage_token=manage_token)
    await ctx.interaction.edit_initial_response(components=await _panel(mongo, state), **NO_MENTIONS)


@register_action("fwa_sync_refresh", preload_state=False)
@lightbulb.di.with_di
async def refresh(ctx: Any, action_id: str,
                  mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    return _error(problem) if problem else await _panel(mongo, await _next(mongo, state), "Status refreshed.")


@register_action("fwa_sync_toggle", preload_state=False)
@lightbulb.di.with_di
async def toggle(ctx: Any, action_id: str,
                 mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    sid, sep, choice = action_id.partition("|")
    state, problem = await _state(ctx, mongo, sid)
    if problem:
        return _error(problem)
    if not sep or choice not in {"on", "off"}:
        return await _panel(mongo, state, "Choose Enable or Disable.")
    await mongo.fwa_sync_config.update_one(
        {"_id": sync.CONFIG_ID}, {"$set": {"enabled": choice == "on"}}, upsert=True,
    )
    return await _panel(mongo, await _next(mongo, state),
                        "Reminders enabled; takes effect within one poll (up to 5 minutes)."
                        if choice == "on" else
                        "Reminders disabled; takes effect within one poll (up to 5 minutes).")


def _check_panel(state: dict, events: list[dict], errors: list[str]) -> list:
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("FWA", "Sync & Reminders", "Feed Check") + "\n## FWA feed check"),
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"**{len(events)} upcoming sync(s)** · Dry run only; No DMs sent."
        )),
    ]
    if errors:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
            "### Feed errors\n" + "\n".join(f"• {_safe(error, 150)}" for error in errors[:5])
        )))
    rows.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
    if events:
        for event in events[:10]:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
                f"• **{_safe(event['calendar'], 30)}** · "
                f"{discord_timestamp(event['start'], 'F')} "
                f"({discord_timestamp(event['start'], 'R')})\n"
                f"  {_safe(event['summary'], 130)}"
            )))
    else:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=(
            "Nothing upcoming. This can be normal on a quiet day; check the feeds if it persists."
        )))
    rows.append(_buttons(
        (f"fwa_sync_refresh:{state['_id']}", "Back to Sync & Reminders", hikari.ButtonStyle.SECONDARY, False),
        (f"manage_fwa:{state['manage_token']}", "Back to FWA", hikari.ButtonStyle.SECONDARY, False),
    ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


@register_action("fwa_sync_check", preload_state=False)
@lightbulb.di.with_di
async def check(ctx: Any, action_id: str,
                mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    config = await sync.load_config(mongo)
    try:
        events, errors = await sync.collect_events(config["summary_filter"])
    except Exception as exc:
        return await _panel(mongo, state, f"Feed check failed: {type(exc).__name__}.")
    return _check_panel(await _next(mongo, state), events, errors)



@register_action("fwa_sync_test", preload_state=False)
@lightbulb.di.with_di
async def test_dm(ctx: Any, action_id: str,
                  mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    config = await sync.load_config(mongo)
    try:
        events, _errors = await sync.collect_events(config["summary_filter"])
    except Exception as exc:
        return await _panel(mongo, state, f"Could not prepare test DM: {type(exc).__name__}.")
    if events:
        event, source = events[0], "next sync"
    else:
        event = {
            "uid": "preview", "start": datetime.now(timezone.utc) + timedelta(minutes=61),
            "end": datetime.now(timezone.utc) + timedelta(minutes=101),
            "summary": "PREVIEW — Tie Breaker High Sync", "calendar": "Sync3",
        }
        source = "sample sync; no upcoming event found"
    offset = str(config["offsets"][0]) if config["offsets"] else DISCOVERY_OFFSET
    sent = await sync.dm_all([state["user_id"]], sync.build_embed(event, offset))
    return await _panel(mongo, await _next(mongo, state),
                        f"Test DM sent to you ({source}); no reminder state saved."
                        if sent else "Could not DM you. Check your DM settings.")


@register_action("fwa_sync_channel", preload_state=False)
@lightbulb.di.with_di
async def channel(ctx: Any, action_id: str,
                  mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        return _error(problem)
    values = getattr(ctx.interaction, "values", ()) or ()
    if len(values) != 1:
        return await _panel(mongo, state, "Choose one text or announcement channel.")
    try:
        channel_id = int(values[0])
        target = await ctx.interaction.app.rest.fetch_channel(channel_id)
    except (TypeError, ValueError, hikari.NotFoundError, hikari.ForbiddenError, hikari.HTTPError):
        return await _panel(mongo, state, "Could not find that channel.")
    if (getattr(target, "guild_id", None) != state["guild_id"]
            or getattr(target, "type", None) not in CHANNEL_TYPES):
        return await _panel(mongo, state, "Choose a text or announcement channel in this server.")
    from extensions.commands.content import destination_permissions
    try:
        permissions = await destination_permissions(ctx.interaction.app, state["guild_id"], target)
    except (ValueError, hikari.ForbiddenError, hikari.HTTPError):
        return await _panel(mongo, state, "I could not verify permissions in that channel.")
    needed = (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
              | hikari.Permissions.EMBED_LINKS)
    if permissions & needed != needed:
        return await _panel(mongo, state, "I need View Channel, Send Messages, and Embed Links there.")
    await mongo.fwa_sync_config.update_one(
        {"_id": sync.CONFIG_ID}, {"$set": {"panel_channel_id": channel_id}}, upsert=True,
    )
    return await _panel(mongo, await _next(mongo, state), "Sync panel channel saved.")


def _modal_value(ctx: Any, key: str) -> str:
    return next((str(item.value or "")
                 for row in getattr(ctx.interaction, "components", ()) for item in row
                 if getattr(item, "custom_id", None) == key), "")


async def _ack_modal(ctx: Any) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)


@register_action("fwa_sync_url", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def url_modal(ctx: Any, action_id: str,
                    mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    config = await sync.load_config(mongo)
    await ctx.respond_with_modal(
        title="BAND fallback link", custom_id=f"fwa_sync_url_submit:{action_id}",
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            "url", "Public http(s) link", value=config["band_url"], required=True,
            min_length=10, max_length=2048,
        )],
    )


def _valid_public_url(value: str) -> bool:
    if len(value) > 2048:
        return False
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username
                or parsed.password or parsed.port not in (None, 80, 443)):
            return False
        if "." not in host or host.lower() == "localhost" or host.lower().endswith((".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        return address is None or address.is_global
    except ValueError:
        return False


@register_action("fwa_sync_url_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def url_submit(ctx: Any, action_id: str,
                     mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id)
    if problem:
        await ctx.interaction.edit_initial_response(components=_error(problem), **NO_MENTIONS)
        return
    value = _modal_value(ctx, "url").strip()
    if not _valid_public_url(value):
        response = await _panel(mongo, state, "Enter a public http:// or https:// URL.")
    else:
        await mongo.fwa_sync_config.update_one(
            {"_id": sync.CONFIG_ID}, {"$set": {"band_url": value}}, upsert=True,
        )
        response = await _panel(mongo, await _next(mongo, state), "BAND fallback link saved.")
    await ctx.interaction.edit_initial_response(components=response, **NO_MENTIONS)


