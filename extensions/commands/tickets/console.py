"""Recruiter-only persistent ticket console and personal drill-down panels.

The shared hub never stores viewer state and no interaction edits it. Every
personal path responds ephemerally and mints its own fixed-lifetime state ID.
Hub refresh state is durable in ``ticket_setup/_id=ticket_console_hub`` so an
interrupted refresh is recovered at startup instead of being forgotten.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Iterable, Mapping, Sequence

import hikari
import lightbulb
from pymongo import ReturnDocument

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    LinkButtonBuilder as LinkButton,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    ModalActionRowBuilder as ModalActionRow,
    SectionComponentBuilder as Section,
    SelectOptionBuilder as SelectOption,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
    TextSelectMenuBuilder as TextSelectMenu,
)

from extensions.commands.fwa.chocolate_links import chocolate_url
from extensions.commands.tickets import (
    account_sync,
    flag_store,
    loader,
    perms,
    resolve,
    schema,
    store,
    thread_service,
    ticket,
)
from extensions.commands.tickets.console_render import OverviewCounts, render_overview
from extensions.components import register_action
from utils.component_state import get_state, insert_state, update_state
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler


_log = logging.getLogger(__name__)

HUB_STATE_ID = "ticket_console_hub"
HUB_ACTION_ID = "hub"
HUB_ATTACHMENT = "ticket_overview.png"
HUB_DEBOUNCE_SECONDS = 0.75
HUB_LEASE = timedelta(minutes=3)
HUB_RETRY_DELAYS = (0.0, 1.0, 4.0, 12.0)
HUB_RECONCILE_SECONDS = 60.0
CONTEXT_LEASE = timedelta(minutes=3)
CONTEXT_RECOVERY_LIMIT = 25
STAFF_CONTEXT_MARKER_PREFIX = "ticket-staff-context"
REQUIRED_HUB_BOT_PERMISSIONS = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.READ_MESSAGE_HISTORY
    | hikari.Permissions.ATTACH_FILES
)
REQUIRED_HUB_RECRUITER_PERMISSIONS = (
    hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)

MAX_OPEN_PICKER = 25
MAX_SEARCH_RESULTS = 10
MAX_HISTORY_RESULTS = 10
MAX_DETAIL_HISTORY = 5
SEARCH_PANEL_COMPONENT_MAX = 40
DISCORD_MESSAGE_TEXT_LIMIT = 4000

ACCENT_BLUE = 0x4A90F5
ACCENT_GREEN = 0x4BCE7A
ACCENT_RED = 0xF0555A
ACCENT_YELLOW = 0xFFCC00
ACCENT_GREY = 0x80848E

STATUS_META = {
    "open": ("New / open", "🆕", ACCENT_BLUE),
    "approved": ("Approved", "✅", ACCENT_GREEN),
    "denied": ("Denied", "❌", ACCENT_RED),
}
FLAG_META = {
    flag_store.FLAG_BLACKLISTED: ("Blacklisted", "⛔", True),
    flag_store.FLAG_DENIED_BEFORE: ("Previously denied", "⚠️", False),
    flag_store.FLAG_NOT_LOYAL: ("Not loyal to WU", "⚠️", False),
}
FLAG_SOURCES = flag_store.FLAG_SOURCES
MAX_FLAG_MANAGER_OPTIONS = 25

DISCORD_ID_RE = re.compile(r"^\d{17,20}$")
PLAYER_TAG_RE = re.compile(r"^#[A-Za-z0-9]{3,9}$")
USERNAME_RE = re.compile(r"^[\w .-]{2,32}$", re.UNICODE)

_refresh_tasks: dict[int, asyncio.Task] = {}
_startup_recovery: StartupReconciler | None = None


class ConsoleConfigurationError(RuntimeError):
    """The selected shared-console channel is unsafe or unusable."""


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    kind: str
    value: str
    error: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean(value, *, limit: int = 300) -> str:
    """Short, inert Discord markdown for user/database supplied values."""

    text = str(value or "").replace("\x00", "").strip()
    for character in ("\\", "`", "*", "_", "~", "|", ">"):
        text = text.replace(character, "\\" + character)
    return text[:limit] or "Unknown"


def _allocate_message_text(
    desired_lengths: Sequence[int],
    *,
    fixed_texts: Sequence[str] = (),
    minimum_lengths: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Allocate one Discord message's Text Display budget in priority order."""

    desired = tuple(max(0, int(length)) for length in desired_lengths)
    if minimum_lengths is None:
        minimum = (0,) * len(desired)
    else:
        if len(minimum_lengths) != len(desired):
            raise ValueError("message text minimums must match desired lengths")
        minimum = tuple(
            min(wanted, max(0, int(required)))
            for wanted, required in zip(desired, minimum_lengths)
        )

    fixed_length = sum(len(str(content)) for content in fixed_texts)
    mandatory_length = fixed_length + sum(minimum)
    if mandatory_length > DISCORD_MESSAGE_TEXT_LIMIT:
        raise ValueError("fixed ticket console copy exceeds Discord's text budget")

    budgets = list(minimum)
    remaining = DISCORD_MESSAGE_TEXT_LIMIT - mandatory_length
    for index, wanted in enumerate(desired):
        extra = min(wanted - budgets[index], remaining)
        budgets[index] += extra
        remaining -= extra
        if not remaining:
            break
    return tuple(budgets)


def _truncate_text(content: str, limit: int, *, suffix: str = "…") -> str:
    """Fit variable copy into an allocated Text Display slot."""

    content = str(content)
    limit = max(0, int(limit))
    if len(content) <= limit:
        return content
    if limit <= len(suffix):
        return suffix[:limit]
    return content[:limit - len(suffix)].rstrip() + suffix


def _timestamp(value, style: str = "R") -> str:
    if not isinstance(value, datetime):
        return "time unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"<t:{int(value.timestamp())}:{style}>"


def _status_meta(status) -> tuple[str, str, int]:
    key = str(status or "unknown").casefold()
    if key in STATUS_META:
        return STATUS_META[key]
    label = _clean(key.replace("_", " ").title(), limit=40)
    return (label, "❔", ACCENT_GREY)


def _ticket_type(ticket_doc: Mapping) -> str:
    value = str(ticket_doc.get("ticket_type") or "").casefold()
    return value if value in {"main", "fwa"} else "unknown"


def _ticket_number(ticket_doc: Mapping) -> str:
    value = ticket_doc.get("ticket_number")
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "?"


def _ticket_label(ticket_doc: Mapping, *, username: bool = False) -> str:
    kind = _ticket_type(ticket_doc)
    prefix = "FWA" if kind == "fwa" else "Main" if kind == "main" else "Ticket"
    label = f"{prefix} #{_ticket_number(ticket_doc)}"
    if username:
        label += f" · {_clean(ticket_doc.get('username'), limit=45)}"
    return label[:100]


def _ticket_id(ticket_doc: Mapping) -> str:
    return str(ticket_doc.get("_id") or "")


def _player_tags(ticket_doc: Mapping) -> tuple[str, ...]:
    snapshot = account_sync.snapshot_from_ticket(ticket_doc)
    if snapshot.observed_tags:
        return tuple(snapshot.observed_tags)
    raw = ticket_doc.get("player_tags") or ticket_doc.get("playerTags") or ()
    if isinstance(raw, str):
        raw = (raw,)
    if not raw:
        raw = (ticket_doc.get("player_tag") or ticket_doc.get("tag"),)
    tags: list[str] = []
    for value in raw:
        tag = str(value or "").strip().upper()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        if tag not in tags:
            tags.append(tag)
    return tuple(tags)


def _tag_omission_suffix(omitted: int) -> str:
    return f"… +{omitted} tag{'s' if omitted != 1 else ''} omitted"


def _bounded_tag_display(tags: Sequence[str], *, limit: int) -> str:
    """Format tags for Discord without changing the canonical tag sequence."""
    rendered = [f"`{_clean(tag, limit=15)}`" for tag in tags]
    complete = ", ".join(rendered)
    if len(complete) <= limit:
        return complete

    shown: list[str] = []
    for index, tag in enumerate(rendered):
        omitted = len(rendered) - index - 1
        suffix = f" {_tag_omission_suffix(omitted)}" if omitted else ""
        candidate = ", ".join((*shown, tag)) + suffix
        if len(candidate) > limit:
            break
        shown.append(tag)

    omitted = len(rendered) - len(shown)
    suffix = _tag_omission_suffix(omitted)
    result = ", ".join(shown)
    if result:
        result += " "
    return result + suffix


def _location_id(ticket_doc: Mapping, *, staff: bool = False) -> int:
    location = ticket_doc.get("location") or {}
    if staff:
        return _int(location.get("staff_space_id") or ticket_doc.get("thread_id"))
    return _int(location.get("id") or ticket_doc.get("channel_id"))


def ticket_jump_url(ticket_doc: Mapping, *, staff: bool = False) -> str | None:
    """A direct read-only Discord jump. It never unarchives a thread."""

    guild_id = _int(ticket_doc.get("guild_id"))
    location_id = _location_id(ticket_doc, staff=staff)
    if not guild_id or not location_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{location_id}"


def parse_search_query(raw: str | None) -> ParsedQuery:
    value = str(raw or "").strip()
    if not value:
        return ParsedQuery("all", "")
    if value.isdigit():
        if DISCORD_ID_RE.fullmatch(value):
            return ParsedQuery("discord_id", value)
        return ParsedQuery(
            "invalid",
            value,
            "That is not a Discord ID. A Discord ID has 17 to 20 numbers. "
            "Ticket numbers do not work here.",
        )
    if value.startswith("#"):
        if PLAYER_TAG_RE.fullmatch(value):
            return ParsedQuery("player_tag", value.upper())
        return ParsedQuery(
            "invalid",
            value,
            "That is not a player tag. A player tag is 3 to 9 letters and "
            "numbers after the #.",
        )
    if USERNAME_RE.fullmatch(value):
        return ParsedQuery("username", value)
    return ParsedQuery(
        "invalid",
        value,
        "Use a Discord ID, a player tag (start it with #), or a username. "
        "Enter only one of these values.",
    )


def _modal_value(ctx, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()) or ():
        for component in row:
            if getattr(component, "custom_id", None) == custom_id:
                return str(getattr(component, "value", "") or "").strip()
    return ""


async def _require_recruiter(ctx, mongo: MongoClient) -> bool:
    if await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return True
    await ctx.respond(
        "Only recruiters can use the ticket console.",
        ephemeral=True,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )
    return False


async def _execute_private_panel(ctx, components: Sequence) -> None:
    """Create a new ephemeral follow-up; never edit the clicked public hub."""

    await ctx.interaction.execute(
        components=list(components),
        flags=(hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL),
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


def _notice(title: str, body: str, *, accent: int = ACCENT_BLUE) -> list[Container]:
    heading = f"## {title}"
    body = str(body)
    (body_budget,) = _allocate_message_text(
        [len(body)],
        fixed_texts=[heading],
        minimum_lengths=[min(1, len(body))],
    )
    return [Container(
        accent_color=accent,
        components=[
            Text(content=heading),
            Text(content=_truncate_text(body, body_budget)),
        ],
    )]


def _open_picker_options(open_tickets: Sequence[Mapping]) -> list[SelectOption]:
    options: list[SelectOption] = []
    for ticket_doc in open_tickets[:MAX_OPEN_PICKER]:
        ticket_id = _ticket_id(ticket_doc)
        if not ticket_id or len(ticket_id) > 100:
            continue
        user_id = _int(ticket_doc.get("user_id"))
        description = f"Discord ID {user_id}" if user_id else "Applicant ID unavailable"
        options.append(SelectOption(
            label=_ticket_label(ticket_doc, username=True),
            value=ticket_id,
            description=description[:100],
            emoji="💎" if _ticket_type(ticket_doc) == "fwa" else "🏆",
        ))
    if options:
        return options
    return [SelectOption(
        label="No open tickets",
        value="no-open-tickets",
        description="There are no open tickets.",
    )]


def build_hub_components(open_tickets: Sequence[Mapping], png_bytes: bytes) -> list[Container]:
    """The only shared message shape: image, picker, and Find button."""

    attachment = hikari.Bytes(png_bytes, HUB_ATTACHMENT, "image/png")
    has_open = bool(open_tickets)
    return [Container(
        accent_color=ACCENT_BLUE,
        components=[
            Media(items=[MediaItem(
                media=attachment,
                description="Ticket totals by status and clan type, plus active staff flags.",
            )]),
            ActionRow(components=[TextSelectMenu(
                custom_id=f"ticket_console_pick:{HUB_ACTION_ID}",
                placeholder=(
                    "Choose an open ticket"
                    if has_open else "No open tickets"
                ),
                min_values=1,
                max_values=1,
                is_disabled=not has_open,
                options=_open_picker_options(open_tickets),
            )]),
            ActionRow(components=[Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"ticket_console_find:{HUB_ACTION_ID}",
                label="Find a ticket",
                emoji="🔍",
            )]),
        ],
    )]


def _coerce_counts(raw) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    if not isinstance(raw, Mapping):
        return {}, {"main": {}, "fwa": {}}
    statuses = raw.get("statuses") or raw.get("status") or {}
    by_type = raw.get("by_type") or raw.get("ticket_types") or {}
    if not isinstance(statuses, Mapping):
        statuses = {}
    if not isinstance(by_type, Mapping):
        by_type = {}
    return (
        {str(key): _int(value) for key, value in statuses.items()},
        {
            kind: {
                str(key): _int(value)
                for key, value in (by_type.get(kind) or {}).items()
            }
            for kind in ("main", "fwa")
        },
    )


async def _hub_payload(mongo: MongoClient) -> list[Container]:
    open_tickets, raw_counts, flag_counts = await asyncio.gather(
        store.list_open(mongo, limit=MAX_OPEN_PICKER),
        store.console_counts(mongo),
        flag_store.count_active(mongo),
    )
    statuses, by_type = _coerce_counts(raw_counts)
    png = await render_overview(OverviewCounts(
        statuses=statuses,
        by_type=by_type,
        flags=flag_counts if isinstance(flag_counts, Mapping) else {},
        updated_at=utcnow(),
    ))
    return build_hub_components(open_tickets, png)


async def _hub_state(mongo: MongoClient) -> dict:
    return await mongo.ticket_setup.find_one({"_id": HUB_STATE_ID}) or {}


async def _ensure_hub_state(mongo: MongoClient) -> None:
    await mongo.ticket_setup.update_one(
        {"_id": HUB_STATE_ID},
        {"$setOnInsert": {
            "kind": "ticket_console_hub",
            "desired_revision": 0,
            "applied_revision": -1,
            "created_at": utcnow(),
        }},
        upsert=True,
    )


async def _mark_hub_dirty(mongo: MongoClient, *, reason: str) -> int:
    await _ensure_hub_state(mongo)
    state = await mongo.ticket_setup.find_one_and_update(
        {"_id": HUB_STATE_ID},
        {
            "$inc": {"desired_revision": 1},
            "$set": {"refresh_requested_at": utcnow(), "refresh_reason": reason[:80]},
        },
        return_document=ReturnDocument.AFTER,
    )
    return _int((state or {}).get("desired_revision"))


async def _acquire_hub_lease(mongo: MongoClient, owner: str) -> dict | None:
    now = utcnow()
    return await mongo.ticket_setup.find_one_and_update(
        {
            "_id": HUB_STATE_ID,
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
                {"lease_owner": owner},
            ],
        },
        {"$set": {"lease_owner": owner, "lease_until": now + HUB_LEASE}},
        return_document=ReturnDocument.AFTER,
    )


async def _release_hub_lease(
    mongo: MongoClient,
    owner: str,
    *,
    applied_revision: int | None = None,
    error: Exception | None = None,
) -> None:
    update: dict = {"$unset": {"lease_owner": "", "lease_until": ""}}
    if applied_revision is not None:
        update.setdefault("$max", {})["applied_revision"] = int(applied_revision)
        update.setdefault("$set", {}).update({
            "refreshed_at": utcnow(),
            "refresh_error": None,
        })
    if error is not None:
        update.setdefault("$set", {}).update({
            "refresh_error": type(error).__name__,
            "refresh_failed_at": utcnow(),
        })
        update.setdefault("$inc", {})["refresh_failures"] = 1
    await mongo.ticket_setup.update_one(
        {"_id": HUB_STATE_ID, "lease_owner": owner},
        update,
    )


def _hub_action_ids(component) -> set[str]:
    result: set[str] = set()
    custom_id = str(getattr(component, "custom_id", "") or "")
    if custom_id:
        result.add(custom_id)
    for child in getattr(component, "components", ()) or ():
        result.update(_hub_action_ids(child))
    return result


async def _message_history(rest, channel_id: int) -> list:
    iterator = rest.fetch_messages(channel_id)
    collect = getattr(iterator, "collect", None)
    if callable(collect):
        return list(await collect(list))
    to_list = getattr(iterator, "to_list", None)
    if callable(to_list):
        return list(await to_list())
    return list(await iterator)


async def _find_orphaned_hub(bot: hikari.GatewayBot, channel_id: int):
    """Recover a hub whose Discord create committed before its Mongo checkpoint."""
    me = bot.get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable")
    required = {
        f"ticket_console_pick:{HUB_ACTION_ID}",
        f"ticket_console_find:{HUB_ACTION_ID}",
    }
    messages = await _message_history(bot.rest, channel_id)
    matches = []
    for message in messages:
        if _int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        action_ids: set[str] = set()
        for component in getattr(message, "components", ()) or ():
            action_ids.update(_hub_action_ids(component))
        if required <= action_ids:
            matches.append(message)
    return max(matches, key=lambda item: int(item.id), default=None)


async def _publish_hub(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    state: Mapping,
) -> int:
    channel_id = _int(state.get("channel_id"))
    if not channel_id:
        raise RuntimeError("ticket console channel is not configured")
    guild_id = _int(state.get("guild_id"))
    if not guild_id:
        raise ConsoleConfigurationError("ticket console server is not configured")
    await validate_console_channel(
        bot,
        mongo,
        guild_id=guild_id,
        channel_id=channel_id,
    )
    components = await _hub_payload(mongo)
    message_id = _int(state.get("message_id"))
    if message_id:
        try:
            await bot.rest.edit_message(
                channel=channel_id,
                message=message_id,
                components=components,
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )
            return message_id
        except hikari.NotFoundError:
            # The channel may still exist while the bot-owned hub message was
            # deleted. Creation below is the durable self-healing path.
            pass

    orphan = await _find_orphaned_hub(bot, channel_id)
    if orphan is not None:
        try:
            await bot.rest.edit_message(
                channel=channel_id,
                message=int(orphan.id),
                components=components,
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )
        except hikari.NotFoundError:
            orphan = None
        else:
            message_id = int(orphan.id)
            await mongo.ticket_setup.update_one(
                {"_id": HUB_STATE_ID},
                {"$set": {"message_id": message_id, "message_recovered_at": utcnow()}},
            )
            return message_id

    message = await bot.rest.create_message(
        channel=channel_id,
        components=components,
        flags=hikari.MessageFlag.IS_COMPONENTS_V2,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )
    message_id = int(message.id)
    await mongo.ticket_setup.update_one(
        {"_id": HUB_STATE_ID},
        {"$set": {"message_id": message_id, "message_created_at": utcnow()}},
    )
    return message_id


async def _drain_hub_refreshes(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    debounce: bool,
) -> bool:
    if debounce:
        await asyncio.sleep(HUB_DEBOUNCE_SECONDS)
    owner = uuid.uuid4().hex
    retry_index = 0
    while retry_index < len(HUB_RETRY_DELAYS):
        delay = HUB_RETRY_DELAYS[retry_index]
        if delay:
            await asyncio.sleep(delay)
        state = await _acquire_hub_lease(mongo, owner)
        if state is None:
            return False
        desired = _int(state.get("desired_revision"))
        applied = _int(state.get("applied_revision"))
        if desired <= applied:
            await _release_hub_lease(mongo, owner)
            return True
        if not _int(state.get("channel_id")):
            await _release_hub_lease(mongo, owner)
            return False
        try:
            await _publish_hub(bot, mongo, state)
        except asyncio.CancelledError:
            await _release_hub_lease(mongo, owner)
            raise
        except Exception as exc:  # durable dirty revision remains unapplied
            _log.exception(
                "ticket console refresh failed attempt=%s revision=%s",
                retry_index + 1,
                desired,
            )
            await _release_hub_lease(mongo, owner, error=exc)
            retry_index += 1
            continue

        await _release_hub_lease(mongo, owner, applied_revision=desired)
        retry_index = 0
        latest = await _hub_state(mongo)
        if _int(latest.get("desired_revision")) <= _int(latest.get("applied_revision")):
            return True
        # A ticket changed while Pillow/Discord were busy. Reacquire and draw
        # the newest snapshot instead of losing that refresh edge.
    return False


async def _hub_refresh_worker(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    debounce: bool,
) -> bool:
    """Keep reconciling durable dirty state after the fast retry window."""

    first = True
    while True:
        clean = await _drain_hub_refreshes(
            bot,
            mongo,
            debounce=debounce if first else False,
        )
        first = False
        if clean:
            return True
        state = await _hub_state(mongo)
        if (
            _int(state.get("desired_revision")) <= _int(state.get("applied_revision"))
            or not _int(state.get("channel_id"))
        ):
            return False
        # The quick retries are intentionally bounded. The worker remains alive
        # at a capped cadence so an extended Discord outage heals without a new
        # ticket event or process restart.
        await asyncio.sleep(HUB_RECONCILE_SECONDS)


def _schedule_hub_refresh(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    debounce: bool = True,
) -> asyncio.Task:
    key = id(mongo)
    current = _refresh_tasks.get(key)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(
        _hub_refresh_worker(bot, mongo, debounce=debounce),
        name="ticket-console-refresh",
    )
    _refresh_tasks[key] = task

    def done(finished: asyncio.Task) -> None:
        if _refresh_tasks.get(key) is finished:
            _refresh_tasks.pop(key, None)
        if not finished.cancelled():
            with contextlib.suppress(Exception):
                finished.result()

    task.add_done_callback(done)
    return task


async def stop_hub_refresh_workers() -> None:
    """Cancel, await, and forget every package-owned console refresh worker."""
    if _startup_recovery is not None:
        await _startup_recovery.stop()
    tasks = list(dict.fromkeys(_refresh_tasks.values()))
    _refresh_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def request_hub_refresh(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    reason: str = "ticket changed",
) -> int:
    """Durably request one coalesced refresh and return its revision."""

    revision = await _mark_hub_dirty(mongo, reason=reason)
    _schedule_hub_refresh(bot, mongo)
    return revision


async def request_hub_refresh_best_effort(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    reason: str = "ticket changed",
) -> bool:
    """Queue a durable redraw without changing a committed action's outcome."""

    try:
        await request_hub_refresh(bot, mongo, reason=reason)
    except Exception:
        _log.exception("could not queue ticket console refresh reason=%s", reason)
        return False
    return True


async def refresh_hub_now(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    reason: str = "manual setup",
) -> bool:
    """Request and wait; used only while establishing/recovering the hub."""

    await _mark_hub_dirty(mongo, reason=reason)
    existing = _refresh_tasks.get(id(mongo))
    if existing is not None and not existing.done():
        state = await _hub_state(mongo)
        return _int(state.get("desired_revision")) <= _int(state.get("applied_revision"))
    clean = await _drain_hub_refreshes(bot, mongo, debounce=False)
    if not clean:
        _schedule_hub_refresh(bot, mongo, debounce=False)
    return clean


def _permission_names(value: hikari.Permissions) -> str:
    return ", ".join(
        permission.name for permission in hikari.Permissions if permission & value
    ) or "unknown permissions"


def _role_permissions(role) -> hikari.Permissions:
    return hikari.Permissions(getattr(role, "permissions", 0))


def _member_can_view_private_hub(
    member,
    *,
    owner_id: int,
    recruiter_ids: set[int],
    roles_by_id: Mapping[int, object],
) -> bool:
    if _int(getattr(member, "id", 0)) == owner_id:
        return True
    role_ids = {_int(value) for value in getattr(member, "role_ids", ())}
    if role_ids & recruiter_ids:
        return True
    return any(
        _role_permissions(roles_by_id[role_id]) & hikari.Permissions.ADMINISTRATOR
        for role_id in role_ids
        if role_id in roles_by_id
    )


async def validate_console_channel(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    guild_id: int,
    channel_id: int,
) -> object:
    """Fail closed unless the hub is private and usable by bot/recruiters."""

    me = bot.get_me()
    if me is None:
        raise ConsoleConfigurationError("bot identity is unavailable")
    try:
        channel, guild, bot_member, roles = await asyncio.gather(
            bot.rest.fetch_channel(int(channel_id)),
            bot.rest.fetch_guild(int(guild_id)),
            bot.rest.fetch_member(int(guild_id), int(me.id)),
            bot.rest.fetch_roles(int(guild_id)),
        )
    except Exception as exc:
        raise ConsoleConfigurationError(
            "Discord channel permissions could not be inspected"
        ) from exc
    if getattr(channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
        raise ConsoleConfigurationError("console channel must be a guild text channel")
    if _int(getattr(channel, "guild_id", 0)) != int(guild_id):
        raise ConsoleConfigurationError("console channel is not in this server")

    owner_id = _int(getattr(guild, "owner_id", 0))
    bot_permissions = thread_service._effective_permissions(
        guild_id=int(guild_id),
        owner_id=owner_id,
        member=bot_member,
        roles=roles,
        channel=channel,
    )
    missing = REQUIRED_HUB_BOT_PERMISSIONS & ~bot_permissions
    if missing:
        raise ConsoleConfigurationError(
            "bot is missing " + _permission_names(missing)
        )

    # This panel contains applicant identities and staff flags. A channel that
    # @everyone can see is rejected even if the bot itself can post there.
    everyone_permissions = thread_service._effective_permissions(
        guild_id=int(guild_id),
        owner_id=owner_id,
        member=SimpleNamespace(id=0, role_ids=()),
        roles=roles,
        channel=channel,
    )
    if everyone_permissions & hikari.Permissions.VIEW_CHANNEL:
        raise ConsoleConfigurationError("console channel must deny View Channel to @everyone")

    recruiter_ids = {
        _int(value)
        for value in await perms.recruiter_role_ids(mongo)
        if _int(value)
    }
    if not recruiter_ids:
        raise ConsoleConfigurationError("configure at least one recruiter role first")
    roles_by_id = {
        _int(getattr(role, "id", 0)): role
        for role in roles
        if _int(getattr(role, "id", 0))
    }
    known_role_ids = set(roles_by_id)
    missing_roles = recruiter_ids - known_role_ids
    if missing_roles:
        raise ConsoleConfigurationError("a configured recruiter role no longer exists")
    for recruiter_id in recruiter_ids:
        role_permissions = thread_service._effective_permissions(
            guild_id=int(guild_id),
            owner_id=owner_id,
            member=SimpleNamespace(id=0, role_ids=(recruiter_id,)),
            roles=roles,
            channel=channel,
        )
        missing = REQUIRED_HUB_RECRUITER_PERMISSIONS & ~role_permissions
        if missing:
            raise ConsoleConfigurationError(
                "recruiter role is missing " + _permission_names(missing)
            )

    bot_role_ids = {_int(value) for value in getattr(bot_member, "role_ids", ())}
    for role_id, role in roles_by_id.items():
        if role_id == int(guild_id) or role_id in recruiter_ids:
            continue
        if _role_permissions(role) & hikari.Permissions.ADMINISTRATOR:
            continue
        if role_id in bot_role_ids and getattr(role, "is_managed", False):
            continue
        role_permissions = thread_service._effective_permissions(
            guild_id=int(guild_id),
            owner_id=owner_id,
            member=SimpleNamespace(id=0, role_ids=(role_id,)),
            roles=roles,
            channel=channel,
        )
        if role_permissions & hikari.Permissions.VIEW_CHANNEL:
            raise ConsoleConfigurationError(
                f"non-recruiter role {role_id} can view the console channel"
            )

    member_overwrite_ids: set[int] = set()
    for overwrite in thread_service._overwrite_values(
        getattr(channel, "permission_overwrites", ())
    ):
        overwrite_id = _int(getattr(overwrite, "id", 0))
        overwrite_type = getattr(overwrite, "type", None)
        is_member = overwrite_type == hikari.PermissionOverwriteType.MEMBER
        if overwrite_type is None:
            is_member = overwrite_id not in known_role_ids
        if (
            is_member
            and overwrite_id
            and overwrite_id != _int(getattr(bot_member, "id", 0))
            and hikari.Permissions(getattr(overwrite, "allow", 0))
            & hikari.Permissions.VIEW_CHANNEL
        ):
            member_overwrite_ids.add(overwrite_id)

    for member_id in sorted(member_overwrite_ids):
        if member_id == owner_id:
            continue
        try:
            member = await bot.rest.fetch_member(int(guild_id), member_id)
        except hikari.NotFoundError:
            continue
        except Exception as exc:
            raise ConsoleConfigurationError(
                "Discord member overwrites could not be inspected"
            ) from exc
        member_permissions = thread_service._effective_permissions(
            guild_id=int(guild_id),
            owner_id=owner_id,
            member=member,
            roles=roles,
            channel=channel,
        )
        if (
            member_permissions & hikari.Permissions.VIEW_CHANNEL
            and not _member_can_view_private_hub(
                member,
                owner_id=owner_id,
                recruiter_ids=recruiter_ids,
                roles_by_id=roles_by_id,
            )
        ):
            raise ConsoleConfigurationError(
                f"non-recruiter member {member_id} can view the console channel"
            )
    return channel


async def configure_hub_here(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    guild_id: int,
    channel_id: int,
) -> dict:
    """Set the location once, then repair/reuse the one durable message."""

    state = await _hub_state(mongo)
    existing_channel_id = _int(state.get("channel_id"))
    if existing_channel_id:
        try:
            await bot.rest.fetch_channel(existing_channel_id)
        except hikari.NotFoundError as exc:
            raise ConsoleConfigurationError(
                f"saved console channel ID {existing_channel_id} is missing; "
                "relocation is disabled, so the saved binding must be repaired first"
            ) from exc
        except hikari.ForbiddenError as exc:
            raise ConsoleConfigurationError(
                f"saved console channel ID {existing_channel_id} is inaccessible "
                "to the bot; restore access before retrying because relocation is disabled"
            ) from exc
        except Exception as exc:
            raise ConsoleConfigurationError(
                f"saved console channel ID {existing_channel_id} could not be "
                "inspected; retry later because relocation is disabled"
            ) from exc
        if existing_channel_id != int(channel_id):
            raise ConsoleConfigurationError(
                "one console is already configured in another channel"
            )

    await validate_console_channel(
        bot,
        mongo,
        guild_id=int(guild_id),
        channel_id=int(channel_id),
    )
    if not state:
        await _ensure_hub_state(mongo)
        state = await _hub_state(mongo)
        existing_channel_id = _int(state.get("channel_id"))
        if existing_channel_id and existing_channel_id != int(channel_id):
            raise ConsoleConfigurationError(
                "one console is already configured in another channel"
            )
    if not _int(state.get("channel_id")):
        await mongo.ticket_setup.update_one(
            {"_id": HUB_STATE_ID, "$or": [
                {"channel_id": {"$exists": False}},
                {"channel_id": None},
                {"channel_id": 0},
            ]},
            {"$set": {"guild_id": int(guild_id), "channel_id": int(channel_id)}},
        )
    elif not _int(state.get("guild_id")):
        await mongo.ticket_setup.update_one(
            {"_id": HUB_STATE_ID, "channel_id": int(channel_id)},
            {"$set": {"guild_id": int(guild_id)}},
        )
    await refresh_hub_now(bot, mongo, reason="console command")
    return await _hub_state(mongo)


async def _search_results(
    mongo: MongoClient,
    *,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
) -> list[dict]:
    return await store.search(
        mongo,
        query,
        statuses=tuple(statuses) or None,
        ticket_types=tuple(ticket_types) or None,
        limit=MAX_SEARCH_RESULTS,
    )


def _filter_selects(
    action_id: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
) -> list[ActionRow]:
    selected_statuses = set(statuses)
    selected_types = set(ticket_types)
    return [
        ActionRow(components=[TextSelectMenu(
            custom_id=f"ticket_console_status:{action_id}",
            placeholder="Any status",
            min_values=0,
            max_values=3,
            options=[SelectOption(
                label=label,
                value=value,
                emoji=emoji,
                is_default=value in selected_statuses,
            ) for value, (label, emoji, _accent) in STATUS_META.items()],
        )]),
        ActionRow(components=[TextSelectMenu(
            custom_id=f"ticket_console_type:{action_id}",
            placeholder="Any clan type",
            min_values=0,
            max_values=2,
            options=[
                SelectOption(
                    label="Main clan",
                    value="main",
                    emoji="🏆",
                    is_default="main" in selected_types,
                ),
                SelectOption(
                    label="FWA clan",
                    value="fwa",
                    emoji="💎",
                    is_default="fwa" in selected_types,
                ),
            ],
        )]),
    ]


def build_search_panel(
    action_id: str,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
    results: Sequence[Mapping],
    *,
    view_action_ids: Sequence[str] = (),
) -> list[Container]:
    summary = (
        f"Query: **{_clean(query, limit=80)}** · newest {MAX_SEARCH_RESULTS} matches"
        if query else f"All tickets · newest {MAX_SEARCH_RESULTS} matches"
    )
    heading = f"## Search results\n{summary}"
    footer = "-# Archived threads open in read-only mode and stay archived."
    rows: list = [
        Text(content=heading),
        *_filter_selects(action_id, statuses, ticket_types),
        Separator(divider=True),
    ]
    if not results:
        rows.append(Text(content="No tickets match those filters."))
    else:
        result_rows: list[tuple[str, object]] = []
        for index, ticket_doc in enumerate(results[:MAX_SEARCH_RESULTS]):
            status_label, status_emoji, _accent = _status_meta(ticket_doc.get("status"))
            tags = _player_tags(ticket_doc)
            identity = f" · `{_clean(tags[0], limit=15)}`" if tags else ""
            body = (
                f"**{_ticket_label(ticket_doc, username=True)}**\n"
                f"{status_emoji} {status_label} · opened "
                f"{_timestamp(ticket_doc.get('created_at'))}{identity}"
            )
            accessory = (
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"ticket_console_view:{view_action_ids[index]}",
                    label="View",
                )
                if index < len(view_action_ids) else
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"ticket_console_unavailable:{action_id}|{index}",
                    label="View unavailable",
                    is_disabled=True,
                )
            )
            result_rows.append((body, accessory))
        body_budgets = _allocate_message_text(
            [len(body) for body, _accessory in result_rows],
            fixed_texts=[heading, footer],
            minimum_lengths=[
                min(len(body), len(body.split("\n", 1)[0]) + 2)
                for body, _accessory in result_rows
            ],
        )
        for (body, accessory), body_budget in zip(result_rows, body_budgets):
            rows.append(Section(
                components=[Text(content=_truncate_text(body, body_budget))],
                accessory=accessory,
            ))
    rows.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id=f"ticket_console_search_again:{action_id}",
        label="New search",
        emoji="🔍",
    )]))
    rows.append(Text(content=footer))
    return [Container(accent_color=ACCENT_BLUE, components=rows)]


async def _create_search_result_states(
    mongo: MongoClient,
    results: Sequence[Mapping],
    *,
    owner_id: int,
    guild_id: int,
) -> list[str]:
    action_ids = [uuid.uuid4().hex for _ in results[:MAX_SEARCH_RESULTS]]
    await asyncio.gather(*(
        insert_state(mongo, {
            "_id": result_action_id,
            "type": "ticket_console_search_result",
            "owner_id": int(owner_id),
            "guild_id": int(guild_id),
            "ticket_id": _ticket_id(ticket_doc),
        })
        for result_action_id, ticket_doc in zip(action_ids, results)
    ))
    return action_ids


async def _render_search_session(
    mongo: MongoClient,
    *,
    action_id: str,
    owner_id: int,
    guild_id: int,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
) -> list[Container]:
    results = await _search_results(
        mongo,
        query=query,
        statuses=statuses,
        ticket_types=ticket_types,
    )
    view_action_ids = await _create_search_result_states(
        mongo,
        results,
        owner_id=owner_id,
        guild_id=guild_id,
    )
    return build_search_panel(
        action_id,
        query,
        statuses,
        ticket_types,
        results,
        view_action_ids=view_action_ids,
    )


def _flag_kind(flag: Mapping) -> str:
    return str(flag.get("kind") or "").casefold()


def _active_flags(flags: Iterable[Mapping]) -> list[Mapping]:
    return [flag for flag in flags if flag.get("active", True)]


def _history_entry_content(prior: Mapping) -> str:
    label, emoji, _accent = _status_meta(prior.get("status"))
    reason = prior.get("denial_reason") or prior.get("reason")
    reason_copy = f" — {_clean(reason, limit=100)}" if reason else ""
    return (
        f"**{_ticket_label(prior)}** · {emoji} {label}{reason_copy}\n"
        f"Opened {_timestamp(prior.get('created_at'))}"
    )


def _history_sections(
    history: Sequence[Mapping],
    *,
    limit: int = MAX_DETAIL_HISTORY,
    content_limits: Sequence[int] | None = None,
) -> list:
    components: list = []
    for index, prior in enumerate(history[:limit]):
        body = _history_entry_content(prior)
        if content_limits is not None and index < len(content_limits):
            body = _truncate_text(body, content_limits[index])
        url = ticket_jump_url(prior)
        accessory = (
            LinkButton(label=f"Open {_ticket_label(prior)}"[:80], url=url)
            if url else
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"ticket_console_unavailable:history|{index}",
                label="Thread unavailable",
                is_disabled=True,
            )
        )
        components.append(Section(components=[Text(content=body)], accessory=accessory))
    return components


_INTAKE_LABELS = {
    "in_game_name": "In-game name",
    "player_name": "In-game name",
    "town_hall": "Town Hall",
    "townhall": "Town Hall",
    "age": "Age",
    "age_group": "Age",
    "timezone": "Timezone",
    "country": "Country",
    "multiple_accounts": "Multiple accounts",
    "other_accounts": "Other accounts",
    "all_player_tags": "All player tags",
    "looking_for": "What they want from a clan",
    "clan_goal": "What they want from a clan",
    "fwa_process": "FWA process",
    "war_process": "War process",
    "how_heard": "How they heard about WU",
}
_INTAKE_INTERNAL = {
    "discord_skills_monitor_active",
    "completed",
    "current_step",
    "message_id",
    "updated_at",
    "created_at",
}


def _intake_label(value) -> str:
    key = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return _INTAKE_LABELS.get(key, key.replace("_", " ").title())[:80]


def _intake_value(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Mapping):
        return None
    if isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip()
    return _clean(text, limit=350) if text else None


def _structured_intake(ticket_doc: Mapping) -> list[tuple[str, str]]:
    candidates: list = [
        ticket_doc.get("intake_snapshot"),
        ticket_doc.get("intake"),
        ticket_doc.get("questionnaire_snapshot"),
        ticket_doc.get("questionnaire"),
    ]
    step_data = ticket_doc.get("step_data")
    if isinstance(step_data, Mapping):
        candidates.append(step_data.get("questionnaire"))
    answers = ticket_doc.get("answers") or ()
    if isinstance(answers, Sequence) and not isinstance(answers, (str, bytes)):
        candidates.append([
            answer for answer in answers
            if isinstance(answer, Mapping)
            and (answer.get("question") or answer.get("prompt") or answer.get("label"))
        ])

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source in candidates:
        rows: Iterable
        if isinstance(source, Mapping):
            nested = source.get("answers")
            if isinstance(nested, Mapping):
                rows = nested.items()
            elif isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                rows = nested
            else:
                rows = source.items()
        elif isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
            rows = source
        else:
            continue
        for row in rows:
            if isinstance(row, Mapping):
                question = row.get("question") or row.get("prompt") or row.get("label")
                answer = (
                    row.get("answer")
                    if row.get("answer") is not None else
                    row.get("response")
                    if row.get("response") is not None else
                    row.get("value")
                    if row.get("value") is not None else
                    row.get("content")
                )
            else:
                try:
                    question, answer = row
                except (TypeError, ValueError):
                    continue
            key = str(question or "").strip().casefold().replace("-", "_").replace(" ", "_")
            if not key or key in _INTAKE_INTERNAL or key in seen:
                continue
            display = _intake_value(answer)
            if display is None:
                continue
            seen.add(key)
            result.append((_intake_label(question), display))
            if len(result) >= 8:
                return result
    return result


def _answer_transcript(ticket_doc: Mapping) -> list[str]:
    answers = ticket_doc.get("answers") or ()
    if not isinstance(answers, Sequence) or isinstance(answers, (str, bytes)):
        return []
    lines: list[str] = []
    for answer in answers[-6:]:
        if isinstance(answer, Mapping):
            content = answer.get("content") or answer.get("answer") or answer.get("response")
            when = _timestamp(answer.get("at"))
        else:
            content = answer
            when = "time unknown"
        value = _intake_value(content)
        if value:
            lines.append(f"- {when} · {value}")
    return lines


def _intake_content(ticket_doc: Mapping) -> str | None:
    structured = _structured_intake(ticket_doc)
    if structured:
        body = "\n".join(f"**{label}:** {value}" for label, value in structured)
        return f"### Captured intake\n{body}"
    transcript = _answer_transcript(ticket_doc)
    if transcript:
        return "### Captured answer transcript\n" + "\n".join(transcript)
    return None


def _intake_components(ticket_doc: Mapping, *, limit: int) -> list:
    content = _intake_content(ticket_doc)
    if content is None:
        return []
    return [
        Separator(divider=True),
        Text(content=_truncate_text(content, limit)),
    ]


def _flag_omission_suffix(omitted: int) -> str:
    return (
        f"\n\n-# {omitted} additional matching flag"
        f"{'s' if omitted != 1 else ''} not shown. Use `/ticket flags` for all details."
    )


def _flag_detail_content(
    flag_lines: Sequence[str],
    *,
    limit: int = DISCORD_MESSAGE_TEXT_LIMIT,
) -> str:
    content = "### Staff flags"
    for index, line in enumerate(flag_lines):
        addition = f"\n\n{line}"
        if len(content) + len(addition) <= limit:
            content += addition
            continue
        omitted = len(flag_lines) - index
        suffix = _flag_omission_suffix(omitted)
        return content[:limit - len(suffix)].rstrip() + suffix
    return content


def build_ticket_detail(
    ticket_doc: Mapping,
    *,
    action_id: str,
    flags: Sequence[Mapping],
    history: Sequence[Mapping],
) -> list[Container]:
    status = str(ticket_doc.get("status") or "unknown").casefold()
    status_label, status_emoji, accent = _status_meta(status)
    tags = _player_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id"))
    active_flags = _active_flags(flags)
    blacklisted = any(
        _flag_kind(flag) == flag_store.FLAG_BLACKLISTED for flag in active_flags
    )
    details_before_tags = [
        f"**Status:** {status_emoji} {status_label}",
        f"**Applicant:** {_clean(ticket_doc.get('username'), limit=80)}",
        f"**Discord ID:** `{user_id}`" if user_id else "**Discord ID:** unavailable",
    ]
    opened = (
        f"**Opened:** {_timestamp(ticket_doc.get('created_at'), 'F')} "
        f"({_timestamp(ticket_doc.get('created_at'))})"
    )
    title = f"## {status_emoji} {_ticket_label(ticket_doc, username=True)}"
    footer = "-# This panel is private to you. Ticket history is permanent."
    blacklist_warning = (
        "⛔ **Approve is blocked.** This applicant has an active blacklist flag. "
        "You can still deny the ticket."
        if status == "open" and blacklisted else None
    )
    history_heading = (
        "### Earlier tickets\nThis person has opened a ticket before."
        if history else None
    )
    history_copy = [
        _history_entry_content(prior)
        for prior in history[:MAX_DETAIL_HISTORY]
    ]

    flag_lines: list[str] = []
    for flag in active_flags:
        label, glyph, blocks = FLAG_META.get(
            _flag_kind(flag), ("Unknown flag", "⚠️", False)
        )
        reason = _clean(flag.get("reason"), limit=300)
        rule = " · blocks approve" if blocks else " · caution only"
        # IDs are shown in code spans specifically so staff can copy the exact
        # value into /ticket flag-remove. Escaping underscores changes that ID.
        flag_id = str(flag.get("_id") or "")[:80] or "Unknown"
        flag_lines.append(f"{glyph} **{label}**{rule} · `{flag_id}`\n{reason}")

    tag_prefix = "**Player tags:** "
    tag_copy = (
        _bounded_tag_display(tags, limit=DISCORD_MESSAGE_TEXT_LIMIT)
        if tags else None
    )
    intake_copy = _intake_content(ticket_doc)
    flag_copy = _flag_detail_content(flag_lines) if flag_lines else None

    fixed_tag_line = tag_prefix if tag_copy is not None else "**Player tags:** none recorded"
    fixed_texts = [title, footer, *history_copy]
    fixed_texts.append("\n".join((*details_before_tags, fixed_tag_line, opened)))
    if blacklist_warning:
        fixed_texts.append(blacklist_warning)
    if history_heading:
        fixed_texts.append(history_heading)

    variable_keys: list[str] = []
    desired_lengths: list[int] = []
    minimum_lengths: list[int] = []
    if flag_copy is not None:
        variable_keys.append("flags")
        desired_lengths.append(len(flag_copy))
        minimum_lengths.append(min(
            len(flag_copy),
            len("### Staff flags") + len(_flag_omission_suffix(len(flag_lines))),
        ))
    if intake_copy is not None:
        variable_keys.append("intake")
        desired_lengths.append(len(intake_copy))
        minimum_lengths.append(min(
            len(intake_copy),
            len(intake_copy.split("\n", 1)[0]) + 2,
        ))
    if tag_copy is not None:
        variable_keys.append("tags")
        desired_lengths.append(len(tag_copy))
        minimum_lengths.append(min(
            len(tag_copy),
            len(_tag_omission_suffix(len(tags))),
        ))

    allocations = dict(zip(
        variable_keys,
        _allocate_message_text(
            desired_lengths,
            fixed_texts=fixed_texts,
            minimum_lengths=minimum_lengths,
        ),
    ))
    tag_line = (
        tag_prefix + _bounded_tag_display(tags, limit=allocations["tags"])
        if tags else "**Player tags:** none recorded"
    )
    details = [*details_before_tags, tag_line, opened]
    components: list = [
        Text(content=title),
        Text(content="\n".join(details)),
        *_intake_components(ticket_doc, limit=allocations.get("intake", 0)),
    ]
    if flag_lines:
        components.extend([
            Separator(divider=True),
            Text(content=_flag_detail_content(
                flag_lines,
                limit=allocations["flags"],
            )),
        ])
    public_url = ticket_jump_url(ticket_doc)
    staff_url = ticket_jump_url(ticket_doc, staff=True)
    jump_buttons: list = []
    if public_url:
        jump_buttons.append(LinkButton(label="Open the thread", url=public_url))
    if staff_url:
        jump_buttons.append(LinkButton(label="Open staff thread", url=staff_url))
    if jump_buttons:
        components.append(ActionRow(components=jump_buttons))

    components.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id=f"ticket_console_manage_flags:{action_id}",
        label="Manage flags",
        emoji="🚩",
    )]))

    if status == "open":
        if blacklist_warning:
            components.append(Text(content=blacklist_warning))
        components.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"ticket_console_approve:{action_id}",
                label="Approve",
                is_disabled=blacklisted,
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"ticket_console_deny:{action_id}",
                label="Deny",
            ),
        ]))

    if history:
        components.extend([
            Separator(divider=True),
            Text(content=history_heading),
            *_history_sections(history),
        ])
    components.append(Text(content=footer))
    return [Container(accent_color=accent, components=components)]


async def _ticket_detail_panel(
    mongo: MongoClient,
    ticket_doc: Mapping,
    *,
    owner_id: int,
    guild_id: int,
) -> list[Container]:
    action_id = uuid.uuid4().hex
    tags = _player_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id")) or None
    flags, history = await asyncio.gather(
        flag_store.list_for_identity(mongo, discord_ids=user_id, player_tags=tags),
        store.history_for(
            mongo,
            user_id=user_id,
            player_tags=tags,
            exclude_id=_ticket_id(ticket_doc),
            limit=MAX_DETAIL_HISTORY,
        ),
    )
    await insert_state(mongo, {
        "_id": action_id,
        "type": "ticket_console_detail",
        "owner_id": int(owner_id),
        "guild_id": int(guild_id),
        "ticket_id": _ticket_id(ticket_doc),
        "expected_status": str(ticket_doc.get("status") or "open"),
        "expected_rev": max(0, _int(ticket_doc.get("rev"))),
    })
    return build_ticket_detail(
        ticket_doc,
        action_id=action_id,
        flags=flags,
        history=history,
    )


def _flag_manager_content(
    flags: Sequence[Mapping],
    *,
    limit: int = DISCORD_MESSAGE_TEXT_LIMIT,
) -> str:
    content = "### Active staff flags"
    if not flags:
        return content + "\nNo active flags match this applicant."
    for index, flag in enumerate(flags):
        label, glyph, blocks = FLAG_META.get(
            _flag_kind(flag), ("Unknown flag", "⚠️", False)
        )
        rule = "blocks approve" if blocks else "caution only"
        flag_id = str(flag.get("_id") or "")[:80] or "Unknown"
        source = _clean(flag.get("source"), limit=180)
        reason = _clean(flag.get("reason"), limit=500)
        addition = (
            f"\n\n{glyph} **{label}** · {rule}\n"
            f"`{flag_id}`\n**Source:** {source}\n**Reason:** {reason}"
        )
        if len(content) + len(addition) <= limit:
            content += addition
            continue
        omitted = len(flags) - index
        suffix = (
            f"\n\n-# {omitted} additional active flag"
            f"{'s' if omitted != 1 else ''} not shown."
        )
        return content[:limit - len(suffix)].rstrip() + suffix
    return content


def _flag_manager_kind_snapshot(flags: Sequence[Mapping]) -> dict[str, list[dict]]:
    snapshot = {kind: [] for kind in FLAG_META}
    for flag in flags:
        kind = _flag_kind(flag)
        flag_id = str(flag.get("_id") or "")
        if kind in snapshot and flag_id:
            snapshot[kind].append({
                "flag_id": flag_id,
                "rev": max(0, _int(flag.get("rev"))),
            })
    return snapshot


def build_flag_manager(
    ticket_doc: Mapping,
    *,
    action_id: str,
    flags: Sequence[Mapping],
) -> list[Container]:
    """Build one owner-bound flag editor without placing identity in controls."""

    active_flags = _active_flags(flags)
    tags = _player_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id"))
    title = f"## 🚩 Manage flags · {_ticket_label(ticket_doc, username=True)}"
    identity_prefix = (
        f"**Discord ID:** `{user_id}`\n**Stored player tags ({len(tags)}):** "
        if user_id else
        f"**Discord ID:** unavailable\n**Stored player tags ({len(tags)}):** "
    )
    footer = (
        "-# Changes bind the latest stored Discord ID and every recorded player tag. "
        "Names are display-only."
    )
    guidance = (
        "Choose a flag type to add it or update its reason. "
        "To remove a flag, choose it below and record why."
    )
    tag_copy = _bounded_tag_display(tags, limit=DISCORD_MESSAGE_TEXT_LIMIT) if tags else "none"
    flag_copy = _flag_manager_content(active_flags)
    tag_budget, flag_budget = _allocate_message_text(
        [len(tag_copy), len(flag_copy)],
        fixed_texts=[title, identity_prefix, guidance, footer],
        minimum_lengths=[
            min(len(tag_copy), len(_tag_omission_suffix(len(tags)))) if tags else len(tag_copy),
            min(len(flag_copy), len("### Active staff flags\nNo active flags match this applicant.")),
        ],
    )
    identity = identity_prefix + (
        _bounded_tag_display(tags, limit=tag_budget) if tags else "none"
    )
    has_identity = bool(user_id or tags)
    components: list = [
        Text(content=title),
        Text(content=identity),
        Text(content=guidance),
        Separator(divider=True),
        Text(content=_flag_manager_content(active_flags, limit=flag_budget)),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.DANGER
                    if kind == flag_store.FLAG_BLACKLISTED else
                    hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"ticket_flag_set:{action_id}|{kind}",
                label=label,
                emoji=glyph,
                is_disabled=not has_identity,
            )
            for kind, (label, glyph, _blocks) in FLAG_META.items()
        ]),
    ]
    removable = active_flags[:MAX_FLAG_MANAGER_OPTIONS]
    if removable:
        components.append(ActionRow(components=[TextSelectMenu(
            custom_id=f"ticket_flag_remove:{action_id}",
            placeholder="Remove an active flag…",
            min_values=1,
            max_values=1,
            options=[SelectOption(
                label=(
                    f"{FLAG_META.get(_flag_kind(flag), ('Unknown flag', '⚠️', False))[1]} "
                    f"{FLAG_META.get(_flag_kind(flag), ('Unknown flag', '⚠️', False))[0]}"
                )[:100],
                value=str(index),
                description=_clean(flag.get("reason"), limit=100),
            ) for index, flag in enumerate(removable)],
        )]))
    components.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.PRIMARY,
        custom_id=f"ticket_flag_back:{action_id}",
        label="Back to ticket details",
        emoji="←️",
    )]))
    components.append(Text(content=footer))
    return [Container(accent_color=ACCENT_RED if any(
        _flag_kind(flag) == flag_store.FLAG_BLACKLISTED for flag in active_flags
    ) else ACCENT_BLUE, components=components)]


async def _flag_manager_panel(
    mongo: MongoClient,
    ticket_doc: Mapping,
    *,
    owner_id: int,
    guild_id: int,
) -> list[Container]:
    tags = _player_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id")) or None
    flags = await flag_store.list_for_identity(
        mongo,
        discord_ids=user_id,
        player_tags=tags,
    )
    active_flags = _active_flags(flags)
    action_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": action_id,
        "type": "ticket_console_flag_manager",
        "owner_id": int(owner_id),
        "guild_id": int(guild_id),
        "ticket_id": _ticket_id(ticket_doc),
        "flag_kinds": _flag_manager_kind_snapshot(active_flags),
        "flag_slots": [{
            "flag_id": str(flag.get("_id") or ""),
            "rev": max(0, _int(flag.get("rev"))),
        } for flag in active_flags[:MAX_FLAG_MANAGER_OPTIONS]],
    })
    return build_flag_manager(
        ticket_doc,
        action_id=action_id,
        flags=active_flags,
    )


def _staff_account_summary(ticket_doc: Mapping) -> str:
    """Render the durable linked-account snapshot without triggering a lookup."""

    snapshot = account_sync.snapshot_from_ticket(ticket_doc)
    if snapshot.state == account_sync.STATE_PENDING:
        return (
            "### 🔄 Linked Clash accounts\n"
            "The opening account check is pending. No zero-account conclusion has "
            "been recorded; an automatic retry is required."
        )
    if snapshot.state == account_sync.STATE_FAILED:
        retained = len(snapshot.observed_tags)
        retained_copy = (
            f" **{retained} previously recorded account"
            f"{'s remain' if retained != 1 else ' remains'} attached to this ticket.**"
            if retained else ""
        )
        return (
            "### ⚠️ Linked Clash accounts\n"
            "The latest account lookup failed, so the current linked count is "
            f"unknown.{retained_copy} Retry before making the final decision."
        )
    if snapshot.state == account_sync.STATE_EMPTY:
        retained = len(snapshot.observed_tags)
        retained_copy = (
            f" {retained} previously recorded account"
            f"{'s are' if retained != 1 else ' is'} retained for identity history."
            if retained else ""
        )
        return (
            "### 🔗 Linking required\n"
            "No Clash accounts are currently linked to this Discord ID."
            f"{retained_copy} Complete linking privately if needed; the final "
            "decision rechecks automatically."
        )
    current = len(snapshot.current_tags)
    observed = len(snapshot.observed_tags)
    noun = "account" if current == 1 else "accounts"
    observed_copy = (
        f" · **{observed} permanently recorded**"
        if observed != current else ""
    )
    return (
        "### ✅ Linked Clash accounts\n"
        f"**{current} currently linked {noun}**{observed_copy}. The final decision "
        "rechecks the complete list automatically."
    )


def _chocolate_accounts(ticket_doc: Mapping) -> tuple[tuple[str, str | None], ...]:
    """Return only the current linked snapshot, sorted for stable grouping."""

    snapshot = account_sync.snapshot_from_ticket(ticket_doc)
    current = {account.tag: account.name for account in snapshot.current_accounts}
    return tuple((tag, current.get(tag)) for tag in sorted(snapshot.current_tags))


def _chocolate_link_label(name: object) -> str:
    """Keep a linked-account name inert inside Chocolate Markdown links."""

    label = " ".join(str(name or "").replace("\x00", "").split())[:80]
    label = label.replace("@", "@\u200b")
    for character in ("\\", "`", "*", "_", "~", "|", ">", "[", "]", "(", ")"):
        label = label.replace(character, "\\" + character)
    return label or "Player"


def build_staff_chocolate_checklist(
    ticket_doc: Mapping,
) -> list[tuple[str, list[Container]]]:
    """Build staff-only FWA Chocolate links in deterministic 20-account groups."""

    if _ticket_type(ticket_doc) != "fwa" or not isinstance(
        ticket_doc.get("linked_accounts"), Mapping
    ):
        return []
    ticket_id = _ticket_id(ticket_doc)
    snapshot = account_sync.snapshot_from_ticket(ticket_doc)
    accounts = _chocolate_accounts(ticket_doc)
    state_copy = {
        account_sync.STATE_PENDING: (
            "The linked-account check is pending. No blacklist result was inferred."
        ),
        account_sync.STATE_FAILED: (
            "The latest linked-account refresh failed. The last confirmed current "
            "snapshot remains below and the lookup must be retried."
        ),
        account_sync.STATE_EMPTY: (
            "No accounts are currently linked. Complete linking privately if needed."
        ),
        account_sync.STATE_READY: (
            "Open each link to review the account on FWA Chocolate."
        ),
    }[snapshot.state]
    disclaimer = (
        "-# These are review links only. No Chocolate blacklist verdict was checked "
        "automatically; record a verified concern through Manage Flags."
    )
    if not accounts:
        marker = f"ticket-chocolate:{ticket_id}:1"
        return [(marker, [Container(
            accent_color=ACCENT_YELLOW,
            components=[
                Text(content="## 🍫 FWA Chocolate checklist"),
                Text(content=state_copy),
                Text(content=disclaimer),
            ],
        )])]

    panels: list[tuple[str, list[Container]]] = []
    total = len(accounts)
    for start in range(0, total, 20):
        group = accounts[start:start + 20]
        end = start + len(group)
        marker = f"ticket-chocolate:{ticket_id}:{start // 20 + 1}"
        lines = []
        for tag, name in group:
            label_name = _chocolate_link_label(name)
            lines.append(f"- [{label_name} · `{tag}`]({chocolate_url(tag)})")
        title = f"## 🍫 FWA Chocolate checklist · {start + 1}–{end} of {total}"
        body = "\n".join(lines)
        # Delivery appends this durable marker. Reserve its text budget here so
        # every Components V2 message stays within Discord's 4,000-character
        # aggregate Text Display limit.
        marker_budget = len(f"-# {marker}")
        message_budget = DISCORD_MESSAGE_TEXT_LIMIT - marker_budget
        # Keep each group independently safe even with maximum Clash names.
        if sum(map(len, (title, state_copy, body, disclaimer))) > message_budget:
            body = "\n".join(
                f"- [`{tag}`]({chocolate_url(tag)})"
                for tag, _name in group
            )
        panels.append((marker, [Container(
            accent_color=ACCENT_YELLOW,
            components=[
                Text(content=title),
                *([Text(content=state_copy)] if start == 0 else []),
                Text(content=body),
                Text(content=disclaimer),
            ],
        )]))
    return panels


def build_history_panel(user_id: int, history: Sequence[Mapping]) -> list[Container]:
    heading = "## Ticket history"
    summary = f"Discord ID `{int(user_id)}` · newest {MAX_HISTORY_RESULTS} tickets"
    footer = "-# Archived threads open in read-only mode and stay archived."
    components: list = [
        Text(content=heading),
        Text(content=summary),
        Separator(divider=True),
    ]
    if history:
        history_copy = [
            _history_entry_content(prior)
            for prior in history[:MAX_HISTORY_RESULTS]
        ]
        history_budgets = _allocate_message_text(
            [len(content) for content in history_copy],
            fixed_texts=[heading, summary, footer],
            minimum_lengths=[
                min(len(content), len(content.split("\n", 1)[0]) + 2)
                for content in history_copy
            ],
        )
        components.extend(_history_sections(
            history,
            limit=MAX_HISTORY_RESULTS,
            content_limits=history_budgets,
        ))
    else:
        components.append(Text(content="No ticket history was found for this person."))
    components.append(Text(content=footer))
    return [Container(accent_color=ACCENT_BLUE, components=components)]


async def build_staff_identity_context(
    mongo: MongoClient,
    ticket_doc: Mapping,
) -> list[Container] | None:
    """Build the automatic staff identity, account, flag, and history panel."""

    tags = _player_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id")) or None
    flags, history = await asyncio.gather(
        flag_store.list_for_identity(mongo, discord_ids=user_id, player_tags=tags),
        store.history_for(
            mongo,
            user_id=user_id,
            player_tags=tags,
            exclude_id=_ticket_id(ticket_doc),
            limit=MAX_DETAIL_HISTORY,
        ),
    )
    flags = _active_flags(flags)[:8]
    has_account_snapshot = isinstance(ticket_doc.get("linked_accounts"), Mapping)
    if not flags and not history and not has_account_snapshot:
        return None
    blacklisted = any(
        _flag_kind(flag) == flag_store.FLAG_BLACKLISTED for flag in flags
    )
    heading = "## Applicant context"
    account_copy = _staff_account_summary(ticket_doc) if has_account_snapshot else None
    account_state = account_sync.snapshot_from_ticket(ticket_doc).state
    marker_copy = f"-# {_staff_context_marker(_ticket_id(ticket_doc))}"
    history_heading = (
        "### This person has opened a ticket before.\n"
        "Open the earlier thread and read it before you answer here."
        if history else None
    )
    history_copy = [
        _history_entry_content(prior)
        for prior in history[:MAX_DETAIL_HISTORY]
    ]
    flag_copy: list[tuple[str, str]] = []
    for flag in flags:
        label, glyph, blocks = FLAG_META.get(
            _flag_kind(flag), ("Unknown flag", "⚠️", False)
        )
        action = "Approve is blocked." if blocks else "This is a caution only."
        flag_copy.append((
            f"{glyph} **Matching flag — {label}**\n{action}\n**Why:** ",
            _clean(flag.get("reason"), limit=500),
        ))

    fixed_texts = [
        heading,
        *([account_copy] if account_copy else []),
        marker_copy,
        *history_copy,
        *(prefix for prefix, _reason in flag_copy),
    ]
    if history_heading:
        fixed_texts.append(history_heading)
    reason_budgets = _allocate_message_text(
        [len(reason) for _prefix, reason in flag_copy],
        fixed_texts=fixed_texts,
        minimum_lengths=[1] * len(flag_copy),
    )

    components: list = [
        Text(content=heading),
        *([Text(content=account_copy)] if account_copy else []),
    ]
    for (prefix, reason), reason_budget in zip(flag_copy, reason_budgets):
        components.append(Text(content=(
            prefix + _truncate_text(reason, reason_budget)
        )))
    if history:
        components.extend([
            Separator(divider=True),
            Text(content=history_heading),
            *_history_sections(history),
        ])
    return [Container(
        accent_color=(
            ACCENT_RED
            if blacklisted else
            ACCENT_YELLOW
            if flags or history or (
                has_account_snapshot and account_state != account_sync.STATE_READY
            ) else
            ACCENT_BLUE
        ),
        components=components,
    )]


def _context_fingerprint(components: Sequence) -> str:
    payloads: list = []
    for component in components:
        built = component.build()
        payloads.append(built[0] if isinstance(built, tuple) else built)
    encoded = json.dumps(payloads, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _staff_context_marker(ticket_id: str) -> str:
    return f"{STAFF_CONTEXT_MARKER_PREFIX}:{ticket_id}"


def _component_contains_marker(component, marker: str) -> bool:
    content = str(getattr(component, "content", "") or "").strip()
    if content in {marker, f"-# {marker}"}:
        return True
    return any(
        _component_contains_marker(child, marker)
        for child in getattr(component, "components", ()) or ()
    )


async def _find_staff_context_message(
    bot: hikari.GatewayBot,
    staff_id: int,
    marker: str,
):
    get_me = getattr(bot, "get_me", None)
    if not callable(get_me):
        return None
    me = get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable")
    matches = []
    for message in await _message_history(bot.rest, staff_id):
        if _int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        if any(
            _component_contains_marker(component, marker)
            for component in getattr(message, "components", ()) or ()
        ):
            matches.append(message)
    return max(matches, key=lambda item: int(item.id), default=None)


def _component_markers_with_prefix(component, prefix: str) -> set[str]:
    """Collect staff-context markers stored in a component tree."""

    content = str(getattr(component, "content", "") or "").strip()
    marker = content.removeprefix("-# ").strip()
    result = {marker} if marker.startswith(prefix) else set()
    for child in getattr(component, "components", ()) or ():
        result.update(_component_markers_with_prefix(child, prefix))
    return result


async def _find_staff_context_messages_with_prefix(
    bot: hikari.GatewayBot,
    staff_id: int,
    prefix: str,
) -> dict[str, object]:
    """Find the newest bot-authored message for each durable marker prefix."""

    get_me = getattr(bot, "get_me", None)
    if not callable(get_me):
        return {}
    me = get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable")
    matches: dict[str, object] = {}
    for message in await _message_history(bot.rest, staff_id):
        if _int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        for component in getattr(message, "components", ()) or ():
            for marker in _component_markers_with_prefix(component, prefix):
                prior = matches.get(marker)
                if prior is None or _int(getattr(message, "id", 0)) > _int(
                    getattr(prior, "id", 0)
                ):
                    matches[marker] = message
    return matches


async def staff_chocolate_context_is_current(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket_doc: Mapping,
) -> bool:
    """Verify the latest FWA checklist is durably checkpointed and visible."""

    if _ticket_type(ticket_doc) != "fwa":
        return True
    ticket_id = _ticket_id(ticket_doc)
    staff_id = _location_id(ticket_doc, staff=True)
    if not ticket_id or not staff_id:
        return False
    source = build_staff_chocolate_checklist(ticket_doc)
    if not source:
        return False
    state = await mongo.ticket_automation_state.find_one({
        "_id": f"ticket_staff_context:{ticket_id}",
        "kind": "ticket_staff_context",
    }) or {}
    delivered_at = state.get("delivered_at")
    requested_at = state.get("refresh_requested_at")
    if (
        state.get("delivery_state") != "delivered"
        or state.get("lease_owner")
        or not isinstance(delivered_at, datetime)
        or not isinstance(requested_at, datetime)
        or delivered_at < requested_at
    ):
        return False
    expected = [
        (
            marker,
            _context_fingerprint([
                *components,
                Text(content=f"-# {marker}"),
            ]),
        )
        for marker, components in source
    ]
    stored_ids = [_int(value) for value in state.get("chocolate_message_ids") or ()]
    stored_fingerprints = [
        str(value) for value in state.get("chocolate_fingerprints") or ()
    ]
    if len(stored_ids) != len(expected) or len(stored_fingerprints) != len(expected):
        return False
    recovered = await _find_staff_context_messages_with_prefix(
        bot,
        staff_id,
        f"ticket-chocolate:{ticket_id}:",
    )
    return all(
        stored_ids[index]
        and stored_fingerprints[index] == fingerprint
        and _int(getattr(recovered.get(marker), "id", 0)) == stored_ids[index]
        for index, (marker, fingerprint) in enumerate(expected)
    )


async def _finish_staff_context_lease(
    mongo: MongoClient,
    state_id: str,
    owner: str,
    *,
    refresh_generation: int,
    message_id: int | None = None,
    fingerprint: str | None = None,
    chocolate_message_ids: Sequence[int] | None = None,
    chocolate_fingerprints: Sequence[str] | None = None,
    error: Exception | None = None,
    pending: bool = False,
) -> bool:
    now = utcnow()
    update: dict = {
        "$unset": {"lease_owner": "", "lease_until": ""},
        "$set": {"checked_at": now, "updated_at": now},
    }
    if message_id is not None:
        update["$set"].update({
            "delivery_state": "delivered",
            "message_id": int(message_id),
            "fingerprint": str(fingerprint or ""),
            "delivered_at": now,
            "delivery_error": None,
        })
        if chocolate_message_ids is not None:
            update["$set"].update({
                "chocolate_message_ids": [int(value) for value in chocolate_message_ids],
                "chocolate_fingerprints": [
                    str(value) for value in (chocolate_fingerprints or ())
                ],
            })
        update["$unset"]["delivery_failed_at"] = ""
    elif error is not None:
        update["$set"].update({
            "delivery_state": "failed",
            "delivery_error": type(error).__name__,
            "delivery_failed_at": now,
        })
    elif pending:
        update["$set"]["delivery_state"] = "pending"
    else:
        update["$set"].update({
            "delivery_state": "not_needed",
            "delivery_error": None,
        })
        update["$unset"]["delivery_failed_at"] = ""
    generation_filter: int | dict = int(refresh_generation)
    if not refresh_generation:
        generation_filter = {"$in": [0, None]}
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": state_id,
            "kind": "ticket_staff_context",
            "lease_owner": owner,
            "refresh_generation": generation_filter,
        },
        update,
    )
    return bool(getattr(result, "matched_count", 0))


@contextlib.asynccontextmanager
async def _staff_context_write_window(
    rest,
    ticket_doc: Mapping,
    staff_id: int,
    *,
    reopen_terminal_thread: bool,
    expected_owner_id: int | None,
):
    """Temporarily reopen one terminal staff thread only when a write is needed."""
    if (
        not reopen_terminal_thread
        or str(ticket_doc.get("status") or "") not in {"approved", "denied"}
    ):
        yield
        return

    thread = await _validated_terminal_staff_thread(
        rest,
        ticket_doc,
        staff_id,
        expected_owner_id=expected_owner_id,
    )
    was_archived = bool(getattr(thread, "is_archived", False))
    was_locked = bool(getattr(thread, "is_locked", False))
    delivery_error: BaseException | None = None
    try:
        if was_archived:
            await rest.edit_channel(
                staff_id,
                archived=False,
                reason="Retrying committed ticket staff context",
            )
        if was_locked:
            await rest.edit_channel(
                staff_id,
                locked=False,
                reason="Retrying committed ticket staff context",
            )
        yield
    except BaseException as exc:
        delivery_error = exc
        raise
    finally:
        try:
            await rest.edit_channel(
                staff_id,
                locked=True,
                archived=True,
                reason="Restoring resolved ticket staff thread",
            )
        except Exception:
            if delivery_error is None:
                raise
            _log.exception(
                "terminal staff context restoration also failed staff=%s",
                staff_id,
            )


async def _validated_terminal_staff_thread(
    rest,
    ticket_doc: Mapping,
    staff_id: int,
    *,
    expected_owner_id: int | None,
):
    thread = await rest.fetch_channel(staff_id)
    location = ticket_doc.get("location") or {}
    expected_name = thread_service.thread_names(
        str(ticket_doc.get("ticket_type") or ""),
        _int(ticket_doc.get("ticket_number")),
        str(ticket_doc.get("username") or ""),
    )[1]
    if not expected_owner_id:
        raise RuntimeError("staff context recovery bot identity is unavailable")
    thread_service._validate_recovered_thread(
        thread,
        guild_id=_int(location.get("guild_id") or ticket_doc.get("guild_id")),
        parent_id=_int(location.get("staff_parent_id")),
        name=expected_name,
        private=False,
        expected_owner_id=expected_owner_id,
    )
    return thread


async def _converge_terminal_staff_thread(
    rest,
    ticket_doc: Mapping,
    staff_id: int,
    *,
    expected_owner_id: int | None,
) -> None:
    if str(ticket_doc.get("status") or "") not in {"approved", "denied"}:
        return
    thread = await _validated_terminal_staff_thread(
        rest,
        ticket_doc,
        staff_id,
        expected_owner_id=expected_owner_id,
    )
    if not (
        bool(getattr(thread, "is_archived", False))
        and bool(getattr(thread, "is_locked", False))
    ):
        await rest.edit_channel(
            staff_id,
            locked=True,
            archived=True,
            reason="Restoring resolved ticket staff thread",
        )


async def queue_staff_identity_context(
    mongo: MongoClient,
    ticket_doc: Mapping,
    *,
    open_only_refresh: bool = False,
) -> str | None:
    """Durably queue one bound ticket context before best-effort delivery."""

    ticket_id = _ticket_id(ticket_doc)
    staff_id = _location_id(ticket_doc, staff=True)
    if not ticket_id or not staff_id:
        return None
    state_id = f"ticket_staff_context:{ticket_id}"
    now = utcnow()
    await mongo.ticket_automation_state.update_one(
        {"_id": state_id, "kind": "ticket_staff_context"},
        {
            "$setOnInsert": {
                "kind": "ticket_staff_context",
                "created_at": now,
            },
            "$set": {
                "ticket_id": ticket_id,
                "staff_space_id": staff_id,
                "delivery_state": "pending",
                "open_only_refresh": bool(open_only_refresh),
                "refresh_requested_at": now,
                "updated_at": now,
            },
            "$inc": {"refresh_generation": 1},
        },
        upsert=True,
    )
    return state_id


async def _upsert_marked_staff_message(
    bot: hikari.GatewayBot,
    *,
    staff_id: int,
    marker: str,
    components: Sequence,
    message_id: int,
) -> int:
    """Edit one durable marked message, recovering its ID before recreating it."""

    if message_id:
        try:
            await bot.rest.edit_message(
                channel=staff_id,
                message=message_id,
                components=components,
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )
            return message_id
        except hikari.NotFoundError:
            message_id = 0
            recovered = await _find_staff_context_message(bot, staff_id, marker)
            message_id = _int(getattr(recovered, "id", 0))
            if message_id:
                await bot.rest.edit_message(
                    channel=staff_id,
                    message=message_id,
                    components=components,
                    user_mentions=False,
                    role_mentions=False,
                    mentions_everyone=False,
                )
                return message_id
    message = await bot.rest.create_message(
        channel=staff_id,
        components=components,
        flags=hikari.MessageFlag.IS_COMPONENTS_V2,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )
    return int(message.id)


async def _retire_chocolate_message(
    bot: hikari.GatewayBot,
    *,
    staff_id: int,
    marker: str,
    message_id: int,
) -> None:
    """Remove stale current-account links without deleting the audit message."""

    if not message_id:
        return
    retired_marker = marker.replace(
        "ticket-chocolate:", "ticket-chocolate-retired:", 1
    )
    components = [
        Container(
            accent_color=ACCENT_GREY,
            components=[
                Text(content="## 🍫 FWA Chocolate checklist · page retired"),
                Text(content=(
                    "Accounts formerly shown on this page are no longer in the "
                    "current linked-account snapshot. Their tags remain in durable "
                    "ticket identity history for search and flags."
                )),
            ],
        ),
        Text(content=f"-# {retired_marker}"),
    ]
    try:
        await bot.rest.edit_message(
            channel=staff_id,
            message=message_id,
            components=components,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
    except hikari.NotFoundError:
        recovered = await _find_staff_context_message(bot, staff_id, marker)
        recovered_id = _int(getattr(recovered, "id", 0))
        if recovered_id:
            await bot.rest.edit_message(
                channel=staff_id,
                message=recovered_id,
                components=components,
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )


async def deliver_staff_identity_context(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    ticket_doc: Mapping,
    *,
    reopen_terminal_thread: bool = False,
    open_only_refresh: bool = False,
) -> int | None:
    """Create or update durable staff context and FWA Chocolate panels.

    Safe to call after creation and again after every candidate activity. A
    later account or player tag updates the existing messages rather than
    posting duplicates.
    """

    ticket_id = _ticket_id(ticket_doc)
    if open_only_refresh and ticket_id:
        current = await mongo.tickets.find_one({
            "_id": ticket_id,
            **store.RUNTIME_FILTER,
            "status": "open",
        })
        if current is None:
            return None
        ticket_doc = current
    staff_id = _location_id(ticket_doc, staff=True)
    if not ticket_id or not staff_id:
        return None
    state_id = await queue_staff_identity_context(
        mongo,
        ticket_doc,
        open_only_refresh=open_only_refresh,
    )
    if state_id is None:
        return None
    now = utcnow()
    owner = uuid.uuid4().hex
    state = await mongo.ticket_automation_state.find_one_and_update(
        {
            "_id": state_id,
            "kind": "ticket_staff_context",
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
                {"lease_owner": owner},
            ],
        },
        {
            "$set": {
                "delivery_state": "pending",
                "open_only_refresh": bool(open_only_refresh),
                "ticket_id": ticket_id,
                "staff_space_id": staff_id,
                "lease_owner": owner,
                "lease_until": now + CONTEXT_LEASE,
                "updated_at": now,
            },
            "$inc": {"delivery_attempts": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if state is None:
        current = await mongo.ticket_automation_state.find_one({
            "_id": state_id,
            "kind": "ticket_staff_context",
        }) or {}
        return _int(current.get("message_id")) or None
    refresh_generation = max(0, _int(state.get("refresh_generation")))
    expected_owner_id = None
    if (
        reopen_terminal_thread
        and str(ticket_doc.get("status") or "") in {"approved", "denied"}
    ):
        get_me = getattr(bot, "get_me", None)
        me = get_me() if callable(get_me) else None
        expected_owner_id = _int(getattr(me, "id", 0)) or None

    try:
        components = await build_staff_identity_context(mongo, ticket_doc)
        existing_message_id = _int(state.get("message_id"))
        marker = _staff_context_marker(ticket_id)
        if not existing_message_id:
            recovered = await _find_staff_context_message(bot, staff_id, marker)
            existing_message_id = _int(getattr(recovered, "id", 0))
        chocolate_source = build_staff_chocolate_checklist(ticket_doc)
        if components is None and not existing_message_id and not chocolate_source:
            if reopen_terminal_thread:
                await _converge_terminal_staff_thread(
                    bot.rest,
                    ticket_doc,
                    staff_id,
                    expected_owner_id=expected_owner_id,
                )
            await _finish_staff_context_lease(
                mongo,
                state_id,
                owner,
                refresh_generation=refresh_generation,
            )
            return None
        if components is None:
            components = _notice(
                "Applicant context updated",
                "This applicant has no active staff flags or earlier tickets.",
                accent=ACCENT_GREEN,
            )
        components = [*components, Text(content=f"-# {marker}")]
        fingerprint = _context_fingerprint(components)

        prepared_chocolate: list[tuple[str, list, str]] = []
        for chocolate_marker, chocolate_components in chocolate_source:
            marked = [
                *chocolate_components,
                Text(content=f"-# {chocolate_marker}"),
            ]
            prepared_chocolate.append((
                chocolate_marker,
                marked,
                _context_fingerprint(marked),
            ))
        stored_chocolate_ids = state.get("chocolate_message_ids") or ()
        stored_chocolate_fingerprints = state.get("chocolate_fingerprints") or ()
        chocolate_prefix = f"ticket-chocolate:{ticket_id}:"
        recovered_chocolate = (
            await _find_staff_context_messages_with_prefix(
                bot, staff_id, chocolate_prefix
            )
            if chocolate_source or stored_chocolate_ids
            else {}
        )
        stale_chocolate_messages: dict[str, int] = {
            f"{chocolate_prefix}{index + 1}": _int(value)
            for index, value in enumerate(stored_chocolate_ids)
            if index >= len(prepared_chocolate) and _int(value)
        }
        for recovered_marker, recovered_message in recovered_chocolate.items():
            try:
                page = int(recovered_marker.rsplit(":", 1)[-1])
            except ValueError:
                continue
            if page > len(prepared_chocolate):
                stale_chocolate_messages[recovered_marker] = _int(
                    getattr(recovered_message, "id", 0)
                )
        chocolate_ids = [
            _int(stored_chocolate_ids[index])
            if index < len(stored_chocolate_ids) else 0
            for index in range(len(prepared_chocolate))
        ]
        for index, (chocolate_marker, _panel, _fingerprint) in enumerate(
            prepared_chocolate
        ):
            if chocolate_ids[index]:
                continue
            recovered = recovered_chocolate.get(chocolate_marker)
            chocolate_ids[index] = _int(getattr(recovered, "id", 0))

        context_current = (
            existing_message_id
            and fingerprint == str(state.get("fingerprint") or "")
        )
        chocolate_current = not stale_chocolate_messages and all(
            chocolate_ids[index]
            and index < len(stored_chocolate_fingerprints)
            and panel_fingerprint == str(stored_chocolate_fingerprints[index])
            and _int(getattr(
                recovered_chocolate.get(panel_marker), "id", 0
            )) == chocolate_ids[index]
            for index, (panel_marker, _panel, panel_fingerprint) in enumerate(
                prepared_chocolate
            )
        )
        if context_current and chocolate_current:
            if reopen_terminal_thread:
                await _converge_terminal_staff_thread(
                    bot.rest,
                    ticket_doc,
                    staff_id,
                    expected_owner_id=expected_owner_id,
                )
            await _finish_staff_context_lease(
                mongo,
                state_id,
                owner,
                refresh_generation=refresh_generation,
                message_id=existing_message_id,
                fingerprint=fingerprint,
                chocolate_message_ids=chocolate_ids,
                chocolate_fingerprints=[
                    panel_fingerprint
                    for _panel_marker, _panel, panel_fingerprint in prepared_chocolate
                ],
            )
            return existing_message_id

        async with _staff_context_write_window(
            bot.rest,
            ticket_doc,
            staff_id,
            reopen_terminal_thread=reopen_terminal_thread,
            expected_owner_id=expected_owner_id,
        ):
            message_id = existing_message_id
            if not context_current:
                message_id = await _upsert_marked_staff_message(
                    bot,
                    staff_id=staff_id,
                    marker=marker,
                    components=components,
                    message_id=message_id,
                )
            for index, (
                chocolate_marker,
                chocolate_components,
                chocolate_fingerprint,
            ) in enumerate(prepared_chocolate):
                panel_current = (
                    chocolate_ids[index]
                    and index < len(stored_chocolate_fingerprints)
                    and chocolate_fingerprint
                    == str(stored_chocolate_fingerprints[index])
                    and _int(getattr(
                        recovered_chocolate.get(chocolate_marker), "id", 0
                    )) == chocolate_ids[index]
                )
                if panel_current:
                    continue
                chocolate_ids[index] = await _upsert_marked_staff_message(
                    bot,
                    staff_id=staff_id,
                    marker=chocolate_marker,
                    components=chocolate_components,
                    message_id=chocolate_ids[index],
                )
            for stale_marker, stale_message_id in stale_chocolate_messages.items():
                await _retire_chocolate_message(
                    bot,
                    staff_id=staff_id,
                    marker=stale_marker,
                    message_id=stale_message_id,
                )
        await _finish_staff_context_lease(
            mongo,
            state_id,
            owner,
            refresh_generation=refresh_generation,
            message_id=message_id,
            fingerprint=fingerprint,
            chocolate_message_ids=chocolate_ids,
            chocolate_fingerprints=[
                panel_fingerprint
                for _panel_marker, _panel, panel_fingerprint in prepared_chocolate
            ],
        )
        return message_id
    except asyncio.CancelledError:
        await _finish_staff_context_lease(
            mongo,
            state_id,
            owner,
            refresh_generation=refresh_generation,
            pending=True,
        )
        raise
    except Exception as exc:
        _log.exception("staff ticket context delivery failed ticket=%s", ticket_id)
        with contextlib.suppress(Exception):
            await _finish_staff_context_lease(
                mongo,
                state_id,
                owner,
                refresh_generation=refresh_generation,
                error=exc,
            )
        return None


async def ensure_staff_context_indexes(mongo: MongoClient) -> None:
    """Index only durable staff-context work that can require recovery."""
    await mongo.ticket_automation_state.create_index(
        [
            ("kind", 1),
            ("delivery_state", 1),
            ("lease_until", 1),
            ("updated_at", 1),
        ],
        name="ticket_staff_context_recovery",
        partialFilterExpression={"kind": "ticket_staff_context"},
    )


def _pending_staff_context_filter(now: datetime) -> dict:
    return {
        "kind": "ticket_staff_context",
        "$and": [
            {"$or": [
                {"delivery_state": {"$in": ["pending", "failed"]}},
                {"lease_until": {"$lte": now}},
                {
                    "delivery_state": {"$exists": False},
                    "delivery_error": {"$exists": True, "$nin": [None, ""]},
                },
                {
                    "delivery_state": {"$exists": False},
                    "checked_at": {"$exists": False},
                },
            ]},
            {"$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
            ]},
        ],
    }


async def _mark_staff_context_ticket_missing(
    mongo: MongoClient,
    state_id: str,
    *,
    now: datetime,
    state: str = "ticket_missing",
    error: str = "TicketNotFound",
) -> bool:
    result = await mongo.ticket_automation_state.update_one(
        {"_id": state_id, **_pending_staff_context_filter(now)},
        {
            "$set": {
                "delivery_state": state,
                "delivery_error": error,
                "delivery_failed_at": now,
                "checked_at": now,
                "updated_at": now,
            },
            "$unset": {"lease_owner": "", "lease_until": ""},
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def _mark_open_only_context_terminal(
    mongo: MongoClient,
    state_id: str,
    *,
    now: datetime,
) -> bool:
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": state_id,
            "open_only_refresh": True,
            **_pending_staff_context_filter(now),
        },
        {
            "$set": {
                "delivery_state": "not_needed",
                "delivery_error": None,
                "checked_at": now,
                "updated_at": now,
            },
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                "delivery_failed_at": "",
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def recover_pending_staff_identity_contexts(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    limit: int = CONTEXT_RECOVERY_LIMIT,
) -> dict[str, int]:
    """Retry only explicit pending/failed staff-context deliveries."""
    await ensure_staff_context_indexes(mongo)
    amount = max(1, min(int(limit), 100))
    now = utcnow()
    cursor = mongo.ticket_automation_state.find(_pending_staff_context_filter(now))
    pending = await cursor.sort(
        [("updated_at", 1), ("created_at", 1)]
    ).limit(amount).to_list(length=amount)
    counts = {"processed": 0, "completed": 0, "failed": 0}
    for state in pending:
        counts["processed"] += 1
        state_id = str(state.get("_id") or "")
        ticket_id = str(state.get("ticket_id") or "")
        if state_id != f"ticket_staff_context:{ticket_id}" or not ticket_id:
            ticket_doc = None
        else:
            ticket_doc = await mongo.tickets.find_one({
                "_id": ticket_id,
                **store.RUNTIME_FILTER,
            })
        if ticket_doc is None:
            marked = await _mark_staff_context_ticket_missing(
                mongo, state_id, now=utcnow()
            )
            if marked:
                _log.error("staff context recovery ticket missing state=%s", state_id)
            counts["failed"] += 1
            continue

        canonical_staff_id = _location_id(ticket_doc, staff=True)
        if not canonical_staff_id or _int(state.get("staff_space_id")) != canonical_staff_id:
            await _mark_staff_context_ticket_missing(
                mongo,
                state_id,
                now=utcnow(),
                state="binding_invalid",
                error="StaffBindingMismatch",
            )
            counts["failed"] += 1
            continue

        if state.get("open_only_refresh") and ticket_doc.get("status") != "open":
            if await _mark_open_only_context_terminal(
                mongo, state_id, now=utcnow()
            ):
                counts["completed"] += 1
            else:
                counts["failed"] += 1
            continue

        await deliver_staff_identity_context(
            bot,
            mongo,
            ticket_doc,
            reopen_terminal_thread=True,
            open_only_refresh=bool(state.get("open_only_refresh")),
        )
        current = await mongo.ticket_automation_state.find_one({
            "_id": state_id,
            "kind": "ticket_staff_context",
        }) or {}
        if current.get("delivery_state") in {"delivered", "not_needed"}:
            counts["completed"] += 1
        else:
            counts["failed"] += 1
    return counts


async def recover_open_staff_identity_contexts(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    after_ticket_id: str | None = None,
    limit: int = CONTEXT_RECOVERY_LIMIT,
) -> dict[str, int | str | bool | None]:
    """Check one bounded startup batch of canonical open-ticket contexts.

    The caller retains ``after_ticket_id`` across startup-reconciler passes.
    The cursor advances only after this invocation acquires the ticket's
    context lease and records a fresh terminal delivery checkpoint. Replaying
    a batch after cancellation is safe because context delivery is idempotent.
    """

    await ensure_staff_context_indexes(mongo)
    amount = max(1, min(int(limit), 100))
    query: dict = {**store.RUNTIME_FILTER, "status": "open"}
    if after_ticket_id:
        query["_id"] = {"$gt": str(after_ticket_id)}
    cursor = mongo.tickets.find(query)
    tickets = await cursor.sort("_id", 1).limit(amount).to_list(length=amount)
    counts: dict[str, int | str | bool | None] = {
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "after_ticket_id": after_ticket_id,
        "exhausted": False,
    }

    for ticket_doc in tickets:
        ticket_id = _ticket_id(ticket_doc)
        counts["processed"] = int(counts["processed"]) + 1
        if not ticket_id or (after_ticket_id and ticket_id <= after_ticket_id):
            counts["failed"] = int(counts["failed"]) + 1
            _log.error("open staff context sweep received an invalid cursor row")
            break

        state_id = f"ticket_staff_context:{ticket_id}"
        before = await mongo.ticket_automation_state.find_one({
            "_id": state_id,
            "kind": "ticket_staff_context",
        }) or {}
        previous_attempts = max(0, _int(before.get("delivery_attempts")))
        try:
            await deliver_staff_identity_context(
                bot,
                mongo,
                ticket_doc,
                open_only_refresh=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            counts["failed"] = int(counts["failed"]) + 1
            _log.exception("open staff context sweep failed ticket=%s", ticket_id)
            break

        current_ticket = await mongo.tickets.find_one({
            "_id": ticket_id,
            **store.RUNTIME_FILTER,
        })
        if current_ticket is None or current_ticket.get("status") != "open":
            # It stopped being eligible after the bounded query. Do not write
            # to a terminal/deleted ticket, and do not strand the sweep here.
            counts["completed"] = int(counts["completed"]) + 1
            counts["after_ticket_id"] = ticket_id
            after_ticket_id = ticket_id
            continue

        state = await mongo.ticket_automation_state.find_one({
            "_id": state_id,
            "kind": "ticket_staff_context",
        }) or {}
        completed = (
            state.get("ticket_id") == ticket_id
            and _int(state.get("staff_space_id"))
            == _location_id(current_ticket, staff=True)
            and state.get("delivery_state") in {"delivered", "not_needed"}
            and max(0, _int(state.get("delivery_attempts"))) > previous_attempts
            and not state.get("lease_owner")
            and not state.get("lease_until")
        )
        if not completed:
            counts["failed"] = int(counts["failed"]) + 1
            _log.error(
                "open staff context sweep lacks a fresh checkpoint ticket=%s",
                ticket_id,
            )
            break

        counts["completed"] = int(counts["completed"]) + 1
        counts["after_ticket_id"] = ticket_id
        after_ticket_id = ticket_id

    counts["exhausted"] = (
        not counts["failed"]
        and int(counts["processed"]) == len(tickets)
        and len(tickets) < amount
    )
    return counts


async def _queue_open_staff_context_refreshes(
    mongo: MongoClient,
    *,
    discord_ids: Iterable,
    player_tags: Iterable[str],
) -> list[dict]:
    ids = sorted({_int(value) for value in discord_ids if _int(value)})
    tags = schema.player_tags(player_tags)
    clauses: list[dict] = []
    if ids:
        mixed_ids = [item for value in ids for item in (value, str(value))]
        clauses.append({"user_id": {"$in": mixed_ids}})
    if tags:
        clauses.extend([
            {"player_tags": {"$in": tags}},
            {"player_tag": {"$in": tags}},
            {"tag": {"$in": tags}},
        ])
    if not clauses:
        return []

    cursor = mongo.tickets.find({
        **store.RUNTIME_FILTER,
        "status": "open",
        "$or": clauses,
    })
    tickets = await cursor.sort("_id", 1).to_list(length=None)
    for ticket_doc in tickets:
        ticket_id = _ticket_id(ticket_doc)
        staff_id = _location_id(ticket_doc, staff=True)
        if not ticket_id or not staff_id:
            continue
        await queue_staff_identity_context(
            mongo,
            ticket_doc,
            open_only_refresh=True,
        )
    return [
        ticket_doc
        for ticket_doc in tickets
        if _ticket_id(ticket_doc) and _location_id(ticket_doc, staff=True)
    ]


async def refresh_open_staff_contexts_for_flag_best_effort(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    flag_doc: Mapping,
) -> bool:
    """Queue then immediately attempt every exact matching open-ticket panel."""
    def values(field: str, legacy_field: str) -> tuple:
        result: list = []
        for raw in (flag_doc.get(field), flag_doc.get(legacy_field)):
            if raw is None:
                continue
            result.extend(raw if isinstance(raw, (list, tuple, set)) else (raw,))
        return tuple(result)

    try:
        tickets = await _queue_open_staff_context_refreshes(
            mongo,
            discord_ids=values("discord_ids", "discordIds"),
            player_tags=values("player_tags", "playerTags"),
        )
        for ticket_doc in tickets:
            current = await mongo.tickets.find_one({
                "_id": ticket_doc["_id"],
                **store.RUNTIME_FILTER,
                "status": "open",
            })
            if current is None:
                await _mark_open_only_context_terminal(
                    mongo,
                    f"ticket_staff_context:{ticket_doc['_id']}",
                    now=utcnow(),
                )
                continue
            await deliver_staff_identity_context(
                bot,
                mongo,
                current,
                open_only_refresh=True,
            )
        return True
    except Exception:
        _log.exception(
            "could not queue open ticket staff-context refresh flag=%s",
            flag_doc.get("_id"),
        )
        return False


async def _create_search_state(
    mongo: MongoClient,
    *,
    owner_id: int,
    guild_id: int,
    query: str = "",
) -> str:
    action_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": action_id,
        "type": "ticket_console_search",
        "owner_id": int(owner_id),
        "guild_id": int(guild_id),
        "query": query,
        "statuses": [],
        "ticket_types": [],
    })
    return action_id


async def _open_find_modal(
    ctx,
    action_id: str,
    *,
    submit_action: str = "ticket_console_find_submit",
) -> None:
    await ctx.respond_with_modal(
        title="Find a ticket",
        custom_id=f"{submit_action}:{action_id}",
        components=[ModalActionRow().add_text_input(
            "query",
            "Discord ID, player tag, or username",
            placeholder="Leave blank to show all tickets",
            required=False,
            max_length=32,
        )],
    )


@register_action("ticket_console_pick", no_return=True)
@lightbulb.di.with_di
async def ticket_console_pick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        await _execute_private_panel(
            ctx,
            _notice(
                "Recruiter access required",
                "Only recruiters can use the ticket console.",
                accent=ACCENT_RED,
            ),
        )
        return
    values = tuple(getattr(ctx.interaction, "values", ()) or ())
    ticket_id = str(values[0]) if values else ""
    if ticket_id == "no-open-tickets" or not ticket_id:
        await _execute_private_panel(
            ctx,
            _notice("No open tickets", "There are no open tickets."),
        )
        return
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None or str(ticket_doc.get("status")) != "open":
        await _execute_private_panel(
            ctx,
            _notice(
                "Ticket changed",
                "That ticket is no longer open. The shared console will refresh automatically.",
            ),
        )
        return
    components = await _ticket_detail_panel(
        mongo,
        ticket_doc,
        owner_id=int(ctx.user.id),
        guild_id=_int(getattr(ctx, "guild_id", 0)),
    )
    await _execute_private_panel(ctx, components)


@register_action(
    "ticket_console_find", opens_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_find(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    await _open_find_modal(
        ctx,
        str(_int(getattr(ctx, "guild_id", 0))),
        submit_action="ticket_console_find_root_submit",
    )


@register_action(
    "ticket_console_search_again", opens_modal=True, no_return=True,
    requires_state=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_search_again(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    await _open_find_modal(ctx, action_id)


@register_action("ticket_console_view", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_view(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if int(ctx.user.id) != int(owner_id):
        return _notice(
            "Private panel",
            "Run your own search to open this ticket.",
            accent=ACCENT_RED,
        )
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return _notice(
            "Recruiter access required",
            "Only recruiters can use the ticket console.",
            accent=ACCENT_RED,
        )
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is no longer available.",
            accent=ACCENT_RED,
        )
    return await _ticket_detail_panel(
        mongo,
        ticket_doc,
        owner_id=owner_id,
        guild_id=guild_id,
    )


async def _latest_flag_ticket(
    mongo: MongoClient,
    *,
    ticket_id: str,
    guild_id: int,
) -> dict | None:
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None or _int(ticket_doc.get("guild_id")) != int(guild_id):
        return None
    return ticket_doc


def _flag_action_parts(action_id: str) -> tuple[str, str]:
    manager_id, separator, operand = str(action_id or "").partition("|")
    if not separator:
        return manager_id, ""
    return manager_id, operand


async def _authorized_flag_manager_state(
    ctx,
    mongo: MongoClient,
    manager_id: str,
) -> tuple[dict | None, list[Container] | None]:
    envelope = await get_state(mongo, manager_id, {
        "type": 1,
        "owner_id": 1,
        "guild_id": 1,
    })
    if not envelope or envelope.get("type") != "ticket_console_flag_manager":
        return None, _notice(
            "Flag panel expired",
            "Open the ticket and choose **Manage flags** again.",
            accent=ACCENT_RED,
        )
    owner_id = _int(envelope.get("owner_id"))
    if _int(getattr(ctx.user, "id", 0)) != owner_id:
        return None, _notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        )
    guild_id = _int(envelope.get("guild_id"))
    if not guild_id or _int(getattr(ctx, "guild_id", 0)) != guild_id:
        return None, _notice(
            "Flag panel expired",
            "Open the ticket again from this server's console.",
            accent=ACCENT_RED,
        )
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return None, _notice(
            "Recruiter access required",
            "Only recruiters can manage applicant flags.",
            accent=ACCENT_RED,
        )
    data = await get_state(mongo, manager_id)
    if (
        not data
        or data.get("type") != "ticket_console_flag_manager"
        or _int(data.get("owner_id")) != owner_id
        or _int(data.get("guild_id")) != guild_id
    ):
        return None, _notice(
            "Flag panel expired",
            "Open the ticket and choose **Manage flags** again.",
            accent=ACCENT_RED,
        )
    return data, None


async def _ack_flag_modal(ctx) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
        await ctx.defer(ephemeral=True)


async def _edit_flag_modal(ctx, components: Sequence) -> None:
    await ctx.interaction.edit_initial_response(
        components=list(components),
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


async def _refresh_after_flag_mutation(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    flag_doc: Mapping,
) -> None:
    await refresh_open_staff_contexts_for_flag_best_effort(bot, mongo, flag_doc)
    await request_hub_refresh_best_effort(bot, mongo, reason="flag changed")


@register_action("ticket_console_manage_flags", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_manage_flags(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if _int(ctx.user.id) != _int(owner_id):
        return _notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        )
    if not guild_id or _int(getattr(ctx, "guild_id", 0)) != _int(guild_id):
        return _notice(
            "Ticket panel expired",
            "Open the ticket again from this server's console.",
            accent=ACCENT_RED,
        )
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return _notice(
            "Recruiter access required",
            "Only recruiters can manage applicant flags.",
            accent=ACCENT_RED,
        )
    ticket_doc = await _latest_flag_ticket(
        mongo,
        ticket_id=str(ticket_id or ""),
        guild_id=_int(guild_id),
    )
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is unavailable in this server. Nothing was changed.",
            accent=ACCENT_RED,
        )
    return await _flag_manager_panel(
        mongo,
        ticket_doc,
        owner_id=_int(owner_id),
        guild_id=_int(guild_id),
    )


@register_action("ticket_flag_back", requires_state=True)
@lightbulb.di.with_di
async def ticket_flag_back(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if _int(ctx.user.id) != _int(owner_id):
        return _notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        )
    if not guild_id or _int(getattr(ctx, "guild_id", 0)) != _int(guild_id):
        return _notice(
            "Flag panel expired",
            "Open the ticket again from this server's console.",
            accent=ACCENT_RED,
        )
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return _notice(
            "Recruiter access required",
            "Only recruiters can use the ticket console.",
            accent=ACCENT_RED,
        )
    ticket_doc = await _latest_flag_ticket(
        mongo,
        ticket_id=str(ticket_id or ""),
        guild_id=_int(guild_id),
    )
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is unavailable in this server.",
            accent=ACCENT_RED,
        )
    return await _ticket_detail_panel(
        mongo,
        ticket_doc,
        owner_id=_int(owner_id),
        guild_id=_int(guild_id),
    )


@register_action(
    "ticket_flag_set", opens_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_flag_set(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    manager_id, kind = _flag_action_parts(action_id)
    label = FLAG_META.get(kind, ("Applicant flag", "🚩", False))[0]
    await ctx.respond_with_modal(
        title=f"Add or update {label}"[:45],
        custom_id=f"ticket_flag_set_submit:{manager_id}|{kind}",
        components=[ModalActionRow().add_text_input(
            "reason",
            "Why this flag applies",
            placeholder="Record the staff-verifiable reason",
            required=True,
            style=hikari.TextInputStyle.PARAGRAPH,
            min_length=2,
            max_length=500,
        )],
    )


@register_action(
    "ticket_flag_remove", opens_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_flag_remove(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    values = tuple(getattr(ctx.interaction, "values", ()) or ())
    slot = str(values[0]) if values else ""
    await ctx.respond_with_modal(
        title="Remove applicant flag",
        custom_id=f"ticket_flag_remove_submit:{action_id}|{slot}",
        components=[ModalActionRow().add_text_input(
            "reason",
            "Why this flag no longer applies",
            placeholder="This reason is kept in the permanent audit history",
            required=True,
            style=hikari.TextInputStyle.PARAGRAPH,
            min_length=2,
            max_length=500,
        )],
    )


@register_action(
    "ticket_flag_set_submit", is_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_flag_set_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    await _ack_flag_modal(ctx)
    manager_id, kind = _flag_action_parts(action_id)
    if kind not in FLAG_META:
        await _edit_flag_modal(ctx, _notice(
            "Flag not saved",
            "That flag control is invalid. Open **Manage flags** again.",
            accent=ACCENT_RED,
        ))
        return
    data, error = await _authorized_flag_manager_state(ctx, mongo, manager_id)
    if error is not None or data is None:
        await _edit_flag_modal(ctx, error or _notice(
            "Flag panel expired", "Open **Manage flags** again.", accent=ACCENT_RED,
        ))
        return
    ticket_doc = await _latest_flag_ticket(
        mongo,
        ticket_id=str(data.get("ticket_id") or ""),
        guild_id=_int(data.get("guild_id")),
    )
    if ticket_doc is None:
        await _edit_flag_modal(ctx, _notice(
            "Flag not saved",
            "The ticket record is unavailable in this server. Nothing was changed.",
            accent=ACCENT_RED,
        ))
        return
    reason = _modal_value(ctx, "reason")
    if len(reason) < 2:
        await _edit_flag_modal(ctx, _notice(
            "Flag not saved",
            "Write a reason with at least 2 characters.",
            accent=ACCENT_RED,
        ))
        return
    kind_rows = (data.get("flag_kinds") or {}).get(kind)
    if not isinstance(kind_rows, list) or len(kind_rows) > 1:
        await _edit_flag_modal(ctx, _notice(
            "Flag panel changed",
            "The matching flags changed. Open **Manage flags** again before saving.",
            accent=ACCENT_YELLOW,
        ))
        return
    expected = kind_rows[0] if kind_rows else {}
    user_id = _int(ticket_doc.get("user_id")) or None
    tags = _player_tags(ticket_doc)
    if user_id is None and not tags:
        await _edit_flag_modal(ctx, _notice(
            "Flag not saved",
            "This ticket has no durable Discord ID or player tag.",
            accent=ACCENT_RED,
        ))
        return
    try:
        result = await flag_store.set_flag_if_current_authorized(
            mongo,
            member=ctx.member,
            actor_name=ctx.user.username,
            kind=kind,
            discord_ids=user_id,
            player_tags=tags,
            source=FLAG_SOURCES[kind],
            reason=reason,
            expected_flag_id=str(expected.get("flag_id") or "") or None,
            expected_rev=(
                max(0, _int(expected.get("rev"))) if expected else None
            ),
        )
    except (ValueError, flag_store.FlagConflictError) as exc:
        await _edit_flag_modal(ctx, _notice(
            "Flag not saved", str(exc), accent=ACCENT_RED,
        ))
        return
    if result.outcome == store.UNAUTHORIZED:
        await _edit_flag_modal(ctx, _notice(
            "Recruiter access required",
            "Your recruiter permission changed before this action finished.",
            accent=ACCENT_RED,
        ))
        return
    if not result.won:
        await _edit_flag_modal(ctx, _notice(
            "Flag panel changed",
            result.reason or "The flag changed before this action finished.",
            accent=ACCENT_YELLOW,
        ))
        return
    await _refresh_after_flag_mutation(bot, mongo, result.doc or {})
    await _edit_flag_modal(ctx, await _flag_manager_panel(
        mongo,
        ticket_doc,
        owner_id=_int(data.get("owner_id")),
        guild_id=_int(data.get("guild_id")),
    ))


@register_action(
    "ticket_flag_remove_submit", is_modal=True, no_return=True,
    preload_state=False,
)
@lightbulb.di.with_di
async def ticket_flag_remove_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    await _ack_flag_modal(ctx)
    manager_id, raw_slot = _flag_action_parts(action_id)
    data, error = await _authorized_flag_manager_state(ctx, mongo, manager_id)
    if error is not None or data is None:
        await _edit_flag_modal(ctx, error or _notice(
            "Flag panel expired", "Open **Manage flags** again.", accent=ACCENT_RED,
        ))
        return
    try:
        slot = int(raw_slot)
        selected = (data.get("flag_slots") or [])[slot]
        if slot < 0 or not isinstance(selected, Mapping):
            raise IndexError()
        flag_id = str(selected.get("flag_id") or "")
        expected_rev = max(0, _int(selected.get("rev")))
        if not flag_id:
            raise IndexError()
    except (TypeError, ValueError, IndexError):
        await _edit_flag_modal(ctx, _notice(
            "Flag not removed",
            "That flag selection is invalid. Open **Manage flags** again.",
            accent=ACCENT_RED,
        ))
        return
    ticket_doc = await _latest_flag_ticket(
        mongo,
        ticket_id=str(data.get("ticket_id") or ""),
        guild_id=_int(data.get("guild_id")),
    )
    if ticket_doc is None:
        await _edit_flag_modal(ctx, _notice(
            "Flag not removed",
            "The ticket record is unavailable in this server. Nothing was changed.",
            accent=ACCENT_RED,
        ))
        return
    reason = _modal_value(ctx, "reason")
    if len(reason) < 2:
        await _edit_flag_modal(ctx, _notice(
            "Flag not removed",
            "Write a removal reason with at least 2 characters.",
            accent=ACCENT_RED,
        ))
        return
    matching = await flag_store.list_for_identity(
        mongo,
        discord_ids=_int(ticket_doc.get("user_id")) or None,
        player_tags=_player_tags(ticket_doc),
    )
    if flag_id not in {str(flag.get("_id") or "") for flag in matching}:
        await _edit_flag_modal(ctx, _notice(
            "Flag panel changed",
            "That flag no longer matches this ticket. Open **Manage flags** again.",
            accent=ACCENT_YELLOW,
        ))
        return
    try:
        result = await flag_store.deactivate_flag_authorized(
            mongo,
            flag_id,
            member=ctx.member,
            actor_name=ctx.user.username,
            reason=reason,
            expected_rev=expected_rev,
        )
    except flag_store.FlagConflictError as exc:
        await _edit_flag_modal(ctx, _notice(
            "Flag not removed", str(exc), accent=ACCENT_RED,
        ))
        return
    if result.outcome == store.UNAUTHORIZED:
        await _edit_flag_modal(ctx, _notice(
            "Recruiter access required",
            "Your recruiter permission changed before this action finished.",
            accent=ACCENT_RED,
        ))
        return
    if result.outcome in {store.MISSING, store.LOST}:
        await _edit_flag_modal(ctx, _notice(
            "Flag panel changed",
            result.reason or "That flag changed before this action finished.",
            accent=ACCENT_YELLOW,
        ))
        return
    if not result.won:
        await _edit_flag_modal(ctx, _notice(
            "Flag not removed",
            result.reason or "The flag could not be removed.",
            accent=ACCENT_RED,
        ))
        return
    await _refresh_after_flag_mutation(bot, mongo, result.doc or {})
    await _edit_flag_modal(ctx, await _flag_manager_panel(
        mongo,
        ticket_doc,
        owner_id=_int(data.get("owner_id")),
        guild_id=_int(data.get("guild_id")),
    ))


@register_action(
    "ticket_console_find_submit", is_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_find_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    # Modal submissions have their own three-second acknowledgement window.
    # The dispatcher is explicitly told not to preload state for this action,
    # so this is the first await in the complete dispatch path.
    await ctx.defer(ephemeral=True)
    data = await get_state(mongo, action_id, {
        "type": 1,
        "owner_id": 1,
        "guild_id": 1,
    })
    if not data or data.get("type") != "ticket_console_search":
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Search expired",
                "Use **Find a ticket** on the console to search again.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    owner_id = _int(data.get("owner_id"))
    guild_id = _int(data.get("guild_id"))
    if int(ctx.user.id) != owner_id:
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Private panel",
                "This search panel belongs to someone else.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    if not guild_id or _int(getattr(ctx, "guild_id", 0)) != guild_id:
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Search expired",
                "Use **Find a ticket** on the console to search again.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    parsed = parse_search_query(_modal_value(ctx, "query"))
    if parsed.error:
        await ctx.interaction.edit_initial_response(
            components=_notice("Search not run", parsed.error, accent=ACCENT_RED),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Recruiter access required",
                "Only recruiters can use the ticket console.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    next_action_id = await _create_search_state(
        mongo,
        owner_id=owner_id,
        guild_id=guild_id,
        query=parsed.value,
    )
    components = await _render_search_session(
        mongo,
        action_id=next_action_id,
        owner_id=owner_id,
        guild_id=guild_id,
        query=parsed.value,
        statuses=(),
        ticket_types=(),
    )
    await ctx.interaction.edit_initial_response(
        components=components,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@register_action(
    "ticket_console_find_root_submit",
    is_modal=True,
    no_return=True,
    preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_find_root_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    """Acknowledge a root search before creating its owner-bound state."""
    await ctx.defer(ephemeral=True)
    guild_id = _int(getattr(ctx, "guild_id", 0))
    if not guild_id or guild_id != _int(action_id):
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Search expired",
                "Use **Find a ticket** on the console to search again.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    parsed = parse_search_query(_modal_value(ctx, "query"))
    if parsed.error:
        await ctx.interaction.edit_initial_response(
            components=_notice("Search not run", parsed.error, accent=ACCENT_RED),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Recruiter access required",
                "Only recruiters can use the ticket console.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    owner_id = int(ctx.user.id)
    search_id = await _create_search_state(
        mongo,
        owner_id=owner_id,
        guild_id=guild_id,
        query=parsed.value,
    )
    components = await _render_search_session(
        mongo,
        action_id=search_id,
        owner_id=owner_id,
        guild_id=guild_id,
        query=parsed.value,
        statuses=(),
        ticket_types=(),
    )
    await ctx.interaction.edit_initial_response(
        components=components,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


async def _filter_action(
    ctx,
    mongo: MongoClient,
    *,
    action_id: str,
    owner_id: int,
    guild_id: int,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
    field: str,
    allowed: set[str],
) -> list[Container] | None:
    if int(ctx.user.id) != int(owner_id):
        await ctx.respond("This search panel belongs to someone else.", ephemeral=True)
        return None
    if not await _require_recruiter(ctx, mongo):
        return None
    selected = [
        str(value) for value in (getattr(ctx.interaction, "values", ()) or ())
        if str(value) in allowed
    ]
    await update_state(mongo, action_id, {"$set": {field: selected}})
    next_statuses = selected if field == "statuses" else list(statuses)
    next_types = selected if field == "ticket_types" else list(ticket_types)
    return await _render_search_session(
        mongo,
        action_id=action_id,
        owner_id=owner_id,
        guild_id=guild_id,
        query=query,
        statuses=next_statuses,
        ticket_types=next_types,
    )


@register_action("ticket_console_status", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_status(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    query: str = "",
    statuses: Sequence[str] = (),
    ticket_types: Sequence[str] = (),
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _filter_action(
        ctx,
        mongo,
        action_id=action_id,
        owner_id=owner_id,
        guild_id=guild_id,
        query=query,
        statuses=statuses,
        ticket_types=ticket_types,
        field="statuses",
        allowed=set(STATUS_META),
    )


@register_action("ticket_console_type", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_type(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    query: str = "",
    statuses: Sequence[str] = (),
    ticket_types: Sequence[str] = (),
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _filter_action(
        ctx,
        mongo,
        action_id=action_id,
        owner_id=owner_id,
        guild_id=guild_id,
        query=query,
        statuses=statuses,
        ticket_types=ticket_types,
        field="ticket_types",
        allowed={"main", "fwa"},
    )


def _transition_result_panel(result, *, verb: str) -> list[Container]:
    if result.outcome == store.WON:
        return _notice(
            f"Ticket {verb}",
            "The decision was saved. The permanent thread remains available from the console.",
            accent=ACCENT_GREEN if verb == "approved" else ACCENT_RED,
        )
    if result.outcome == store.EFFECT_FAILED:
        return _notice(
            "Decision recorded; updates retrying",
            resolve.RESOLUTION_EFFECT_RETRY_MESSAGE,
            accent=ACCENT_YELLOW,
        )
    if result.outcome == store.BLOCKED:
        blocker = result.blocker or {}
        if not blocker:
            reason = str(result.reason or "Applicant identity is being updated; try again.")
            if "try again" not in reason.casefold():
                reason += " Try again."
            return _notice(
                "Approval not completed",
                reason,
                accent=ACCENT_YELLOW,
            )
        flag_id = _clean(blocker.get("_id"), limit=80)
        return _notice(
            "Approval blocked",
            f"This applicant has an active blacklist flag (`{flag_id}`). You can still deny.",
            accent=ACCENT_RED,
        )
    if result.outcome == store.UNAUTHORIZED:
        return _notice(
            "Recruiter access required",
            "Your recruiter permission changed before this action finished.",
            accent=ACCENT_RED,
        )
    if result.outcome == store.MISSING:
        return _notice(
            "Ticket not found",
            "The ticket record is no longer available. Nothing was changed.",
            accent=ACCENT_RED,
        )
    current = result.doc or {}
    label, emoji, _accent = _status_meta(current.get("status"))
    return _notice(
        "Ticket changed",
        f"Another recruiter changed this ticket first. It is now {emoji} **{label}**.",
        accent=ACCENT_YELLOW,
    )


@register_action("ticket_console_approve", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_approve(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    ticket_id: str,
    expected_status: str = "open",
    expected_rev: int | None = None,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    if int(ctx.user.id) != int(owner_id):
        return _notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        )
    result = await resolve.approve_ticket(
        bot,
        mongo,
        ticket_id=ticket_id,
        member=ctx.member,
        actor_name=ctx.user.username,
        expected_status=expected_status,
        expected_rev=expected_rev,
    )
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket approved")
    return _transition_result_panel(result, verb="approved")


@register_action(
    "ticket_console_deny", opens_modal=True, no_return=True,
    requires_state=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_deny(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    await ctx.respond_with_modal(
        title="Deny ticket",
        custom_id=f"ticket_console_deny_submit:{action_id}",
        components=[ModalActionRow().add_text_input(
            "reason",
            "Reason shown to the applicant",
            placeholder="Use short, clear language",
            required=True,
            style=hikari.TextInputStyle.PARAGRAPH,
            min_length=5,
            max_length=1000,
        )],
    )


@register_action(
    "ticket_console_deny_submit", is_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_deny_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    edits_origin = getattr(ctx.interaction, "message", None) is not None
    if edits_origin:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
        await ctx.defer(ephemeral=True)
    envelope = await get_state(mongo, action_id, {
        "type": 1,
        "owner_id": 1,
        "guild_id": 1,
    })
    if not envelope or envelope.get("type") != "ticket_console_detail":
        await ctx.interaction.edit_initial_response(components=_notice(
            "Ticket panel expired",
            "Open the ticket again from the console.",
            accent=ACCENT_RED,
        ))
        return
    owner_id = _int(envelope.get("owner_id"))
    if int(ctx.user.id) != owner_id:
        await ctx.interaction.edit_initial_response(components=_notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        ))
        return
    guild_id = _int(envelope.get("guild_id"))
    if not guild_id or _int(getattr(ctx, "guild_id", 0)) != guild_id:
        await ctx.interaction.edit_initial_response(components=_notice(
            "Ticket panel expired",
            "Open the ticket again from the console.",
            accent=ACCENT_RED,
        ))
        return
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        await ctx.interaction.edit_initial_response(components=_notice(
            "Recruiter access required",
            "Only recruiters can use the ticket console.",
            accent=ACCENT_RED,
        ))
        return
    data = await get_state(mongo, action_id)
    if (
        not data
        or data.get("type") != "ticket_console_detail"
        or _int(data.get("owner_id")) != owner_id
        or _int(data.get("guild_id")) != guild_id
    ):
        await ctx.interaction.edit_initial_response(components=_notice(
            "Ticket panel expired",
            "Open the ticket again from the console.",
            accent=ACCENT_RED,
        ))
        return
    reason = _modal_value(ctx, "reason")
    if len(reason) < 5:
        await ctx.interaction.edit_initial_response(components=_notice(
            "Ticket not denied",
            "Write a clear reason with at least 5 characters.",
            accent=ACCENT_RED,
        ))
        return
    result = await resolve.deny_ticket(
        bot,
        mongo,
        ticket_id=str(data.get("ticket_id") or ""),
        member=ctx.member,
        actor_name=ctx.user.username,
        kind=resolve.KIND_DENY_CUSTOM,
        reason=reason,
        expected_status=str(data.get("expected_status") or "open"),
        expected_rev=data.get("expected_rev"),
    )
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket denied")
    components = _transition_result_panel(result, verb="denied")
    await ctx.interaction.edit_initial_response(components=components)


@ticket.register()
class ConsoleCommand(
    lightbulb.SlashCommand,
    name="console",
    description="Configure, inspect, or repair the shared ticket console (Admin only)",
):
    channel = lightbulb.channel(
        "channel",
        "Private recruiter text channel; omit to inspect the current setup",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await perms.is_target_admin(ctx.member, mongo):
            await ctx.respond(
                "Administrator permission is required in the configured ticket guild.",
                ephemeral=True,
            )
            return
        if not ctx.guild_id:
            await ctx.respond("Run this command in the configured recruiter server.", ephemeral=True)
            return
        existing = await _hub_state(mongo)
        selected_channel_id = _int(getattr(self.channel, "id", 0))
        channel_id = (
            selected_channel_id
            or _int(existing.get("channel_id"))
            or _int(ctx.channel_id)
        )
        try:
            state = await configure_hub_here(
                bot,
                mongo,
                guild_id=int(ctx.guild_id),
                channel_id=channel_id,
            )
        except ConsoleConfigurationError as exc:
            await ctx.respond(f"Nothing was saved: {exc}.", ephemeral=True)
            return
        channel_id = _int(state.get("channel_id"))
        message_id = _int(state.get("message_id"))
        if not channel_id or not message_id:
            await ctx.respond(
                "The console could not be posted. Check the bot log and channel permissions.",
                ephemeral=True,
            )
            return
        url = f"https://discord.com/channels/{_int(state.get('guild_id'))}/{channel_id}/{message_id}"
        await ctx.respond(
            f"Ticket console ready: {url}",
            ephemeral=True,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )


@ticket.register()
class FindCommand(
    lightbulb.SlashCommand,
    name="find",
    description="Find tickets by Discord ID, player tag, or username",
):
    query = lightbulb.string(
        "query",
        "Discord ID, #player tag, or username; leave blank to use the form",
        default=None,
        max_length=32,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        parsed = parse_search_query(self.query)
        if parsed.error:
            await ctx.respond(
                components=_notice("Search not run", parsed.error, accent=ACCENT_RED),
                ephemeral=True,
            )
            return
        # A root modal is stateless until its independently acknowledged submit.
        if self.query is None:
            await _open_find_modal(
                ctx,
                str(_int(ctx.guild_id)),
                submit_action="ticket_console_find_root_submit",
            )
            return
        await ctx.defer(ephemeral=True)
        if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
            await ctx.interaction.edit_initial_response(
                content="Only recruiters can use the ticket console.",
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )
            return
        action_id = await _create_search_state(
            mongo,
            owner_id=int(ctx.user.id),
            guild_id=_int(ctx.guild_id),
            query=parsed.value,
        )
        components = await _render_search_session(
            mongo,
            action_id=action_id,
            owner_id=int(ctx.user.id),
            guild_id=_int(ctx.guild_id),
            query=parsed.value,
            statuses=(),
            ticket_types=(),
        )
        await ctx.interaction.edit_initial_response(
            components=components,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )


@ticket.register()
class HistoryCommand(
    lightbulb.SlashCommand,
    name="history",
    description="Open permanent ticket history for one Discord member",
):
    member = lightbulb.user("member", "Member whose ticket history you need")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
            await ctx.interaction.edit_initial_response(
                content="Only recruiters can use the ticket console.",
                user_mentions=False,
                role_mentions=False,
                mentions_everyone=False,
            )
            return
        user_id = int(self.member.id)
        history = await store.history_for(
            mongo,
            user_id=user_id,
            limit=MAX_HISTORY_RESULTS,
        )
        await ctx.interaction.edit_initial_response(
            components=build_history_panel(user_id, history),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )


async def _recover_ticket_console_once(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> None:
    """Recover dirty state and schedule bot-owned hub convergence once."""
    state = await _hub_state(mongo)
    if not _int(state.get("channel_id")):
        return
    await _mark_hub_dirty(mongo, reason="startup recovery")
    _schedule_hub_refresh(bot, mongo)


def start_ticket_console_recovery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> StartupReconciler:
    """Start one self-healing console startup recovery task."""
    global _startup_recovery
    if _startup_recovery is None:
        _startup_recovery = StartupReconciler(
            "ticket-console",
            lambda: _recover_ticket_console_once(bot, mongo),
        )
    _startup_recovery.start()
    return _startup_recovery


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def recover_ticket_console(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Start retrying recovery of the bot-owned shared console hub."""
    start_ticket_console_recovery(bot, mongo)
