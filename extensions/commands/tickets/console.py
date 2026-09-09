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

from extensions.commands import ticket_runtime
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
# A permanent failure (channel gone, privacy validation failing) must not
# keep hammering Discord at a fixed 60s/~77s cadence forever. Each
# unsuccessful reconcile cycle doubles the wait, starting at
# HUB_RECONCILE_SECONDS, up to this ceiling.
HUB_RECONCILE_MAX_SECONDS = 3600.0
# One Discord REST attempt can spend up to 120 seconds waiting on a rate-limit
# bucket plus the client's request timeout.  Keep each renewed ownership window
# comfortably beyond that single-attempt ceiling; Hikari retries stay disabled.
CONTEXT_LEASE = timedelta(minutes=5)
CONTEXT_RECOVERY_LIMIT = 25
# Internal bookkeeping key only -- never posted to Discord. The Applicant
# context panel is identified by its visible title text instead (see
# `_is_staff_context_component`); this prefix is kept only to recognise
# already-open tickets whose messages still carry the old marker line.
STAFF_CONTEXT_MARKER_PREFIX = "ticket-staff-context"
STAFF_CONTEXT_TITLE_PREFIX = "Applicant context"
# Internal bookkeeping key only -- never posted to Discord. Chocolate
# checklist messages are identified by their visible title text instead
# (see `_chocolate_title_page`); this prefix is kept only to recognise
# already-open tickets whose messages still carry the old marker line.
CHOCOLATE_MARKER_PREFIX = "ticket-chocolate"
CHOCOLATE_TITLE_PREFIX = "🍫 FWA Chocolate checklist"
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


class StaffContextLeaseLost(RuntimeError):
    """The staff-context worker no longer owns its durable write lease."""


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
# Tracks the last logged failure signature per mongo client (keyed by id),
# so a permanent failure logs one full traceback and then one line per
# retry instead of a fresh traceback every attempt.
_refresh_error_signatures: dict[int, str] = {}


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


_MARKDOWN_ESCAPE_CHARACTERS = ("\\", "`", "*", "_", "~", "|", ">", "[", "]", "(", ")", "#")


def _escape_markdown(text: str) -> str:
    """Escape every Discord markdown control character callers must keep inert."""

    for character in _MARKDOWN_ESCAPE_CHARACTERS:
        text = text.replace(character, "\\" + character)
    return text


def _clean(value, *, limit: int = 300) -> str:
    """Short, inert Discord markdown for user/database supplied values."""

    text = str(value or "").replace("\x00", "").strip()
    text = re.sub(r"[\r\n]+", " ", text)
    text = _escape_markdown(text)
    return text[:limit] or "Unknown"


def _clean_code_span(value, *, limit: int = 80) -> str:
    """Short, inert text for a value shown inside a Discord code span.

    Discord does not process markdown escapes inside a code span, so callers
    here must NOT run this through `_clean`/`_escape_markdown` — the leading
    backslash from an escaped hash or underscore would render literally
    (e.g. a player tag showing as a backslash followed by the tag instead
    of the tag itself). Strip backticks and newlines instead, so the value
    cannot break out of the span, then truncate.
    """

    text = str(value or "").replace("\x00", "").strip()
    text = re.sub(r"[\r\n]+", " ", text)
    text = text.replace("`", "")
    return text[:limit] or "Unknown"


def _mention(user_id, *, fallback: str = "someone") -> str:
    """A Discord mention for a person; never a stored name.

    Rendering the mention itself never pings -- every caller that sends this
    text is responsible for passing ``user_mentions=False`` on the send.
    """

    value = _int(user_id)
    return f"<@{value}>" if value else fallback


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


def _ticket_label(ticket_doc: Mapping, *, username: bool = False, markdown: bool = True) -> str:
    """A ticket's display label.

    ``markdown=False`` is for a Discord select-option label: those fields
    are plain text Discord never renders as markdown, so escaping would
    leak literal backslashes into it instead of keeping anything inert.
    Discord also cannot render a mention inside a select-option label, so
    that path falls back to the stored display name instead.
    Every other caller embeds this in real Text content and keeps the
    default, where a mention is used instead of the stored name.
    """
    kind = _ticket_type(ticket_doc)
    prefix = "FWA" if kind == "fwa" else "Main" if kind == "main" else "Ticket"
    label = f"{prefix} #{_ticket_number(ticket_doc)}"
    if username:
        if markdown:
            label += f" · {_mention(ticket_doc.get('user_id'))}"
        else:
            label += f" · {_clean_code_span(ticket_doc.get('username'), limit=45)}"
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


def _mentioned_tags(ticket_doc: Mapping) -> tuple[str, ...]:
    """Unverified `#TAG`-shaped tokens the applicant typed. Display/search only."""
    raw = ticket_doc.get("mentioned_tags") or ()
    if isinstance(raw, str):
        raw = (raw,)
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
    rendered = [f"`{_clean_code_span(tag, limit=15)}`" for tag in tags]
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


def _notice_with_row(
    title: str, body: str, *, accent: int = ACCENT_BLUE, row: ActionRow,
) -> list[Container]:
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
            row,
        ],
    )]


async def _already_decided_notice(
    mongo: MongoClient,
    current: Mapping,
    *,
    owner_id: int,
    guild_id: int,
) -> list[Container]:
    """The single conflict check that remains: someone else already decided this."""
    status = str(current.get("status") or "").casefold()
    if status == "approved":
        verb, who, when = (
            "approved",
            _mention(current.get("approved_by")),
            _timestamp(current.get("approved_at")),
        )
    else:
        verb, who, when = (
            "denied",
            _mention(current.get("denied_by")),
            _timestamp(current.get("denied_at")),
        )
    action_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": action_id,
        "type": "ticket_v2_console_view",
        "owner_id": int(owner_id),
        "guild_id": int(guild_id),
        "ticket_id": _ticket_id(current),
    })
    return _notice_with_row(
        f"Already {verb}",
        f"Already {verb} by {who} {when}.",
        accent=ACCENT_YELLOW,
        row=ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"ticket_v2_console_view:{action_id}",
            label="Open ticket",
        )]),
    )


def _confirm_panel(
    title: str,
    body: str,
    *,
    confirm_id: str,
    cancel_id: str,
    confirm_label: str = "Confirm",
    confirm_style: hikari.ButtonStyle = hikari.ButtonStyle.SUCCESS,
    accent: int = ACCENT_YELLOW,
) -> list[Container]:
    return _notice_with_row(
        title,
        body,
        accent=accent,
        row=ActionRow(components=[
            Button(style=confirm_style, custom_id=confirm_id, label=confirm_label),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=cancel_id,
                label="Cancel",
            ),
        ]),
    )


_TICKET_TYPE_LABEL = {"main": "Main", "fwa": "FWA"}


def _approve_confirm_panel(
    ticket_doc: Mapping, *, action_id: str, overturn: bool = False,
) -> list[Container]:
    label = _TICKET_TYPE_LABEL.get(_ticket_type(ticket_doc), "Unknown")
    applicant = _mention(ticket_doc.get("user_id"))
    confirm_id = (
        f"ticket_v2_console_overturn_approve_go:{action_id}"
        if overturn else f"ticket_v2_console_approve_go:{action_id}"
    )
    return _confirm_panel(
        "Confirm approval",
        f"Approve {applicant} for **{label}**?",
        confirm_id=confirm_id,
        cancel_id=f"ticket_v2_console_confirm_cancel:{action_id}",
        confirm_label="Approve",
        confirm_style=hikari.ButtonStyle.SUCCESS,
        accent=ACCENT_GREEN,
    )


def _overturn_step1_panel(ticket_doc: Mapping, *, action_id: str) -> list[Container]:
    """'Someone already decided this. Do the opposite anyway?' — step 1 of 2."""
    status = str(ticket_doc.get("status") or "").casefold()
    if status == "approved":
        who = _mention(ticket_doc.get("approved_by"))
        when = _timestamp(ticket_doc.get("approved_at"))
        verb, ask, style = "approved", "Deny anyway?", hikari.ButtonStyle.DANGER
        confirm_id = f"ticket_v2_overturn_deny_open:{action_id}"
    else:
        who = _mention(ticket_doc.get("denied_by"))
        when = _timestamp(ticket_doc.get("denied_at"))
        verb, ask, style = "denied", "Approve anyway?", hikari.ButtonStyle.SUCCESS
        confirm_id = f"ticket_v2_console_overturn_approve_confirm:{action_id}"
    return _confirm_panel(
        "Overturn this decision?",
        f"This person was {verb} by {who} {when}. {ask}",
        confirm_id=confirm_id,
        cancel_id=f"ticket_v2_console_confirm_cancel:{action_id}",
        confirm_label="Continue",
        confirm_style=style,
        accent=ACCENT_YELLOW,
    )


def _open_picker_options(open_tickets: Sequence[Mapping]) -> list[SelectOption]:
    options: list[SelectOption] = []
    for ticket_doc in open_tickets[:MAX_OPEN_PICKER]:
        ticket_id = _ticket_id(ticket_doc)
        if not ticket_id or len(ticket_id) > 100:
            continue
        user_id = _int(ticket_doc.get("user_id"))
        description = f"Discord ID {user_id}" if user_id else "Applicant ID unavailable"
        options.append(SelectOption(
            label=_ticket_label(ticket_doc, username=True, markdown=False),
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


def _hub_picker_placeholder(has_open: bool, shown: int, total_open: int | None) -> str:
    if not has_open:
        return "No open tickets"
    if total_open is not None and total_open > shown:
        return (
            f"Choose a ticket ({shown} of {total_open} shown, oldest first; "
            "use Find for the rest)"
        )
    return "Choose an open ticket"


def build_hub_components(
    open_tickets: Sequence[Mapping],
    png_bytes: bytes,
    *,
    total_open: int | None = None,
) -> list[Container]:
    """The only shared message shape: image, picker, and Find button.

    ``open_tickets`` is oldest-first (the longest-waiting applicant at the
    top) so that when more than ``MAX_OPEN_PICKER`` tickets are open, the
    ones that fall off the picker are the newest, not the ones a recruiter
    is most overdue to look at. ``total_open`` (the true open count, which
    may exceed ``len(open_tickets)``) drives the placeholder hint so a
    recruiter knows the picker is not showing everything.
    """

    attachment = hikari.Bytes(png_bytes, HUB_ATTACHMENT, "image/png")
    has_open = bool(open_tickets)
    shown = min(len(open_tickets), MAX_OPEN_PICKER)
    return [Container(
        accent_color=ACCENT_BLUE,
        components=[
            Media(items=[MediaItem(
                media=attachment,
                description="Ticket totals by status and clan type, plus active staff flags.",
            )]),
            ActionRow(components=[TextSelectMenu(
                custom_id=f"ticket_v2_console_pick:{HUB_ACTION_ID}",
                placeholder=_hub_picker_placeholder(has_open, shown, total_open),
                min_values=1,
                max_values=1,
                is_disabled=not has_open,
                options=_open_picker_options(open_tickets),
            )]),
            ActionRow(components=[Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"ticket_v2_console_find:{HUB_ACTION_ID}",
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
    return build_hub_components(
        open_tickets, png, total_open=statuses.get("open", len(open_tickets))
    )


async def _chart_signature(mongo: MongoClient) -> str:
    """A stable fingerprint of the hub chart's own inputs: console_counts
    plus flag counts.

    The open-ticket picker's *set membership* is deliberately not part of
    this -- two different open-ticket sets can have identical totals. That
    case is covered separately by ``force_pending``, which every ticket
    create/decide/flag change sets regardless of whether this signature
    happens to net out unchanged.
    """
    raw_counts, flag_counts = await asyncio.gather(
        store.console_counts(mongo), flag_store.count_active(mongo),
    )
    statuses, by_type = _coerce_counts(raw_counts)
    flags = flag_counts if isinstance(flag_counts, Mapping) else {}
    return json.dumps(
        {"statuses": statuses, "by_type": by_type, "flags": flags},
        sort_keys=True, separators=(",", ":"),
    )


async def _hub_state(mongo: MongoClient) -> dict:
    return await mongo.ticket_setup.find_one({"_id": HUB_STATE_ID}) or {}


async def refresh_status(mongo: MongoClient) -> str | None:
    """The shared console's current unresolved publish error, if any.

    ``None`` once a refresh has since succeeded -- ``_release_hub_lease``
    clears ``refresh_error`` on every successful publish. Callers such as
    ``/tickets rollout-status`` use this to surface a permanent
    console-config failure that would otherwise only show up as repeated
    log lines.

    A missing ``channel_id`` reports ``"not configured"`` ahead of any
    ``refresh_error`` -- the refresh worker gives up (and clears
    ``refresh_error``/``refresh_failures``) the moment the console channel
    is unset, so an unconfigured console must never keep echoing whatever
    error was last recorded before it was cleared.
    """
    state = await _hub_state(mongo)
    if not _int(state.get("channel_id")):
        return "not configured"
    error = state.get("refresh_error")
    return str(error) if error else None


async def _ensure_hub_state(mongo: MongoClient) -> None:
    await mongo.ticket_setup.update_one(
        {"_id": HUB_STATE_ID},
        {"$setOnInsert": {
            "kind": "ticket_console_hub",
            "desired_revision": 0,
            "applied_revision": -1,
            "force_pending": True,
            "created_at": utcnow(),
        }},
        upsert=True,
    )


async def _mark_hub_dirty(mongo: MongoClient, *, reason: str, force: bool = True) -> int:
    """Bump the durable dirty revision. ``force=True`` (the default) means a
    create/decide/flag-style change: the next publish must fully redraw even
    if the chart signature happens to look unchanged (open-ticket set
    membership can change without moving any total). ``force=False`` never
    clears an already-pending force from an earlier call in the same
    debounce window -- only a publish that actually redraws does that.
    """
    await _ensure_hub_state(mongo)
    update: dict = {
        "$inc": {"desired_revision": 1},
        "$set": {"refresh_requested_at": utcnow(), "refresh_reason": reason[:80]},
    }
    if force:
        update["$set"]["force_pending"] = True
    state = await mongo.ticket_setup.find_one_and_update(
        {"_id": HUB_STATE_ID},
        update,
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
    clear_error: bool = False,
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
            "refresh_error": f"{type(error).__name__}: {error}"[:300],
            "refresh_failed_at": utcnow(),
        })
        update.setdefault("$inc", {})["refresh_failures"] = 1
    if clear_error:
        # The worker gave up because the console is unconfigured, not
        # because a publish failed -- a stale `refresh_error` from an
        # earlier failure must not keep surfacing once the config that
        # caused it is gone. `refresh_status` reports "not configured"
        # for a missing channel_id regardless, but clear the counters too
        # so a later misconfiguration starts its failure count fresh.
        update.setdefault("$set", {}).update({
            "refresh_error": None,
            "refresh_failures": 0,
        })
    await mongo.ticket_setup.update_one(
        {"_id": HUB_STATE_ID, "lease_owner": owner},
        update,
    )


def _log_refresh_failure(mongo: MongoClient, exc: Exception, *, attempt: int) -> None:
    """Log a full traceback the first time an error is seen, then one line
    per retry after that.

    Without this, a permanent failure (channel gone, privacy validation)
    logs a fresh traceback on every one of the four quick retries, every
    reconcile cycle, forever -- pure noise once the cause is known.
    """
    key = id(mongo)
    signature = f"{type(exc).__name__}: {exc}"[:300]
    if _refresh_error_signatures.get(key) != signature:
        _refresh_error_signatures[key] = signature
        _log.exception(
            "ticket console refresh failed attempt=%s: %s", attempt, signature
        )
    else:
        _log.warning(
            "ticket console refresh failed again attempt=%s: %s", attempt, signature
        )


def _hub_action_ids(component) -> set[str]:
    result: set[str] = set()
    custom_id = str(getattr(component, "custom_id", "") or "")
    if custom_id:
        result.add(custom_id)
    for child in getattr(component, "components", ()) or ():
        result.update(_hub_action_ids(child))
    return result


_STAFF_CONTEXT_SCAN_LIMIT = 100
# The hub is always one of the bot's own most recent messages in the console
# channel -- crawling the channel's entire history to find it does not scale
# as unrelated chatter accumulates there over the channel's lifetime.
_ORPHANED_HUB_SCAN_LIMIT = 200


async def _message_history(rest, channel_id: int, *, limit: int | None = None) -> list:
    iterator = rest.fetch_messages(channel_id)
    if limit:
        bound = getattr(iterator, "limit", None)
        if callable(bound):
            iterator = bound(limit)
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
        f"ticket_v2_console_pick:{HUB_ACTION_ID}",
        f"ticket_v2_console_find:{HUB_ACTION_ID}",
    }
    messages = await _message_history(
        bot.rest, channel_id, limit=_ORPHANED_HUB_SCAN_LIMIT
    )
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

    message_id = _int(state.get("message_id"))
    # The revision read at entry -- a ticket change that lands mid-publish
    # bumps desired_revision (and re-raises force_pending via
    # _mark_hub_dirty) past this value, and the settle write below must not
    # clobber that.
    entry_revision = _int(state.get("desired_revision"))
    # Missing force_pending (a state row predating this field, or a caller
    # that never went through _mark_hub_dirty) means "unknown baseline" and
    # must default to a full redraw, not a skip.
    signature: str | None = None
    if message_id and not state.get("force_pending", True):
        signature = await _chart_signature(mongo)
        if signature == state.get("chart_signature"):
            # Every applicant message dirties the hub, but the chart and
            # open-ticket picker only ever change on a create/decide/flag
            # event -- those always set force_pending, so an unchanged
            # signature here means there is nothing new to draw. Skip the
            # Pillow render and Discord PNG re-upload.
            return message_id
    # Always store the signature of what is actually drawn (the forced path
    # used to leave it unwritten), so a later non-forced publish compares
    # against the right baseline instead of stale or missing data.
    if signature is None:
        signature = await _chart_signature(mongo)
    settle_fields: dict = {"force_pending": False, "chart_signature": signature}

    async def _settle() -> None:
        # Conditioned on the revision read at entry: if a ticket change
        # landed mid-publish and bumped desired_revision (re-raising
        # force_pending), that force must survive this settle so the next
        # drain redraws instead of silently clearing the flag on data this
        # publish never saw. Shared by the edit, orphan and create paths.
        await mongo.ticket_setup.update_one(
            {"_id": HUB_STATE_ID, "desired_revision": entry_revision},
            {"$set": settle_fields},
        )

    components = await _hub_payload(mongo)
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
            await _settle()
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
            # The message binding must never be conditional (a lost write
            # would orphan the message and duplicate the hub); only the
            # settle is revision-guarded.
            await mongo.ticket_setup.update_one(
                {"_id": HUB_STATE_ID},
                {"$set": {
                    "message_id": message_id,
                    "message_recovered_at": utcnow(),
                }},
            )
            await _settle()
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
        {"$set": {
            "message_id": message_id,
            "message_created_at": utcnow(),
        }},
    )
    await _settle()
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
            await _release_hub_lease(mongo, owner, clear_error=True)
            return False
        try:
            await _publish_hub(bot, mongo, state)
        except asyncio.CancelledError:
            await _release_hub_lease(mongo, owner)
            raise
        except Exception as exc:  # durable dirty revision remains unapplied
            _log_refresh_failure(mongo, exc, attempt=retry_index + 1)
            await _release_hub_lease(mongo, owner, error=exc)
            retry_index += 1
            continue

        _refresh_error_signatures.pop(id(mongo), None)
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
    backoff = HUB_RECONCILE_SECONDS
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
        # at a geometrically growing cadence -- starting at
        # HUB_RECONCILE_SECONDS, doubling each unsuccessful cycle, capped at
        # HUB_RECONCILE_MAX_SECONDS -- so a transient Discord outage still
        # heals promptly while a permanent config failure stops hammering
        # Discord every ~77s forever.
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, HUB_RECONCILE_MAX_SECONDS)


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
        _refresh_error_signatures.pop(key, None)
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
    force: bool = True,
) -> int:
    """Durably request one coalesced refresh and return its revision."""

    revision = await _mark_hub_dirty(mongo, reason=reason, force=force)
    _schedule_hub_refresh(bot, mongo)
    return revision


async def request_hub_refresh_best_effort(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    reason: str = "ticket changed",
    force: bool = True,
) -> bool:
    """Queue a durable redraw without changing a committed action's outcome."""

    try:
        await request_hub_refresh(bot, mongo, reason=reason, force=force)
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


async def _search_total(
    mongo: MongoClient,
    *,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
) -> int:
    return await store.search_count(
        mongo,
        query,
        statuses=tuple(statuses) or None,
        ticket_types=tuple(ticket_types) or None,
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
            custom_id=f"ticket_v2_console_status:{action_id}",
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
            custom_id=f"ticket_v2_console_type:{action_id}",
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


def _search_count_phrase(shown: int, total: int | None) -> str:
    """The actual number rendered, not a fixed claim of ``MAX_SEARCH_RESULTS``.

    ``total`` unknown or no larger than what is shown just states the exact
    count ("3 matches"); a truncated result set says how much more there is
    ("newest 10 of 27 matches").
    """
    if total is not None and total > shown:
        return f"newest {shown} of {total} matches"
    return f"{shown} match" if shown == 1 else f"{shown} matches"


def build_search_panel(
    action_id: str,
    query: str,
    statuses: Sequence[str],
    ticket_types: Sequence[str],
    results: Sequence[Mapping],
    *,
    view_action_ids: Sequence[str] = (),
    total: int | None = None,
) -> list[Container]:
    count_phrase = _search_count_phrase(min(len(results), MAX_SEARCH_RESULTS), total)
    summary = (
        f"Query: **{_clean(query, limit=80)}** · {count_phrase}"
        if query else f"All tickets · {count_phrase}"
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
            identity = f" · `{_clean_code_span(tags[0], limit=15)}`" if tags else ""
            body = (
                f"**{_ticket_label(ticket_doc, username=True)}**\n"
                f"{status_emoji} {status_label} · opened "
                f"{_timestamp(ticket_doc.get('created_at'))}{identity}"
            )
            accessory = (
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"ticket_v2_console_view:{view_action_ids[index]}",
                    label="View",
                )
                if index < len(view_action_ids) else
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"ticket_v2_console_unavailable:{action_id}|{index}",
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
        custom_id=f"ticket_v2_console_search_again:{action_id}",
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
            "type": "ticket_v2_console_search_result",
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
    results, total = await asyncio.gather(
        _search_results(
            mongo, query=query, statuses=statuses, ticket_types=ticket_types,
        ),
        _search_total(
            mongo, query=query, statuses=statuses, ticket_types=ticket_types,
        ),
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
        total=total,
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
                custom_id=f"ticket_v2_console_unavailable:history|{index}",
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
    if not text:
        return None
    # Applicant-typed tags render uppercased (O -> 0) in every intake view,
    # structured or transcript; storage is untouched.
    return _clean(schema.normalize_tag_tokens_for_display(text), limit=350)


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
        f"{'s' if omitted != 1 else ''} not shown. Use `/tickets flags` for all details."
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
    mentioned = _mentioned_tags(ticket_doc)
    user_id = _int(ticket_doc.get("user_id"))
    active_flags = _active_flags(flags)
    blacklisted = any(
        _flag_kind(flag) == flag_store.FLAG_BLACKLISTED for flag in active_flags
    )
    details_before_tags = [
        f"**Status:** {status_emoji} {status_label}",
        f"**Applicant:** {_mention(user_id)}",
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
    conflict_flag_ids = [
        str(flag_id) for flag_id in (
            (ticket_doc.get("linked_accounts") or {}).get("flag_conflict") or {}
        ).get("flag_ids") or []
        if str(flag_id)
    ]
    flag_conflict_notice = (
        "🟡 **Two flags overlap for this applicant:** "
        + ", ".join(f"`{flag_id}`" for flag_id in conflict_flag_ids)
        + ". Merge or remove one in Manage flags."
        if conflict_flag_ids else None
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
        # value into /tickets flag-remove. _clean_code_span truncates but
        # never escapes, since escaping underscores would change that ID.
        flag_id = _clean_code_span(flag.get("_id"), limit=80)
        flag_lines.append(f"{glyph} **{label}**{rule} · `{flag_id}`\n{reason}")

    tag_prefix = "**Player tags:** "
    tag_copy = (
        _bounded_tag_display(tags, limit=DISCORD_MESSAGE_TEXT_LIMIT)
        if tags else None
    )
    mentioned_prefix = "**Mentioned tags:** "
    mentioned_copy = (
        _bounded_tag_display(mentioned, limit=DISCORD_MESSAGE_TEXT_LIMIT)
        if mentioned else None
    )
    intake_copy = _intake_content(ticket_doc)
    flag_copy = _flag_detail_content(flag_lines) if flag_lines else None

    fixed_tag_line = tag_prefix if tag_copy is not None else "**Player tags:** none recorded"
    fixed_detail_lines = [*details_before_tags, fixed_tag_line]
    if mentioned_copy is not None:
        fixed_detail_lines.append(mentioned_prefix)
    fixed_detail_lines.append(opened)
    fixed_texts = [title, footer, *history_copy]
    fixed_texts.append("\n".join(fixed_detail_lines))
    if blacklist_warning:
        fixed_texts.append(blacklist_warning)
    if flag_conflict_notice:
        fixed_texts.append(flag_conflict_notice)
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
    if mentioned_copy is not None:
        variable_keys.append("mentioned")
        desired_lengths.append(len(mentioned_copy))
        minimum_lengths.append(min(
            len(mentioned_copy),
            len(_tag_omission_suffix(len(mentioned))),
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
    details = [*details_before_tags, tag_line]
    if mentioned_copy is not None:
        details.append(
            mentioned_prefix
            + _bounded_tag_display(mentioned, limit=allocations["mentioned"])
        )
    details.append(opened)
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
    candidate_missing = ticket_runtime.thread_missing_has_role(ticket_doc, "candidate")
    staff_missing = ticket_runtime.thread_missing_has_role(ticket_doc, "staff")
    jump_buttons: list = []
    if candidate_missing:
        jump_buttons.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"ticket_v2_console_unavailable:thread|{_ticket_id(ticket_doc)}|candidate",
            label="Thread removed",
            is_disabled=True,
        ))
    elif public_url:
        jump_buttons.append(LinkButton(label="Open the thread", url=public_url))
    if staff_missing:
        jump_buttons.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"ticket_v2_console_unavailable:thread|{_ticket_id(ticket_doc)}|staff",
            label="Thread removed",
            is_disabled=True,
        ))
    elif staff_url:
        jump_buttons.append(LinkButton(label="Open staff thread", url=staff_url))
    if jump_buttons:
        components.append(ActionRow(components=jump_buttons))

    components.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id=f"ticket_v2_console_manage_flags:{action_id}",
        label="Manage flags",
        emoji="🚩",
    )]))

    if flag_conflict_notice:
        components.append(Text(content=flag_conflict_notice))

    if status == "open":
        if blacklist_warning:
            components.append(Text(content=blacklist_warning))
        components.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"ticket_v2_console_approve:{action_id}",
                label="Approve",
                is_disabled=blacklisted,
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"ticket_v2_console_deny:{action_id}",
                label="Deny",
            ),
        ]))
    elif status in schema.TERMINAL_STATUSES:
        # Nothing is ever closed for good: any recruiter can overturn a
        # decided ticket the other way, and every overturn is logged.
        components.append(ActionRow(components=[Button(
            style=(
                hikari.ButtonStyle.DANGER
                if status == "approved"
                else hikari.ButtonStyle.SUCCESS
            ),
            custom_id=f"ticket_v2_console_overturn:{action_id}",
            label="Deny" if status == "approved" else "Approve",
        )]))

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
        "type": "ticket_v2_console_detail",
        "owner_id": int(owner_id),
        "guild_id": int(guild_id),
        "ticket_id": _ticket_id(ticket_doc),
        "expected_status": str(ticket_doc.get("status") or "open"),
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
                custom_id=f"ticket_v2_flag_set:{action_id}|{kind}",
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
            custom_id=f"ticket_v2_flag_remove:{action_id}",
            placeholder="Remove an active flag…",
            min_values=1,
            max_values=1,
            options=[SelectOption(
                label=(
                    f"{FLAG_META.get(_flag_kind(flag), ('Unknown flag', '⚠️', False))[1]} "
                    f"{FLAG_META.get(_flag_kind(flag), ('Unknown flag', '⚠️', False))[0]}"
                )[:100],
                value=str(index),
                description=_clean_code_span(flag.get("reason"), limit=100),
            ) for index, flag in enumerate(removable)],
        )]))
    components.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.PRIMARY,
        custom_id=f"ticket_v2_flag_back:{action_id}",
        label="Back to ticket details",
        emoji="⬅️",
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
        "type": "ticket_v2_console_flag_manager",
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
    label = _escape_markdown(label)
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
        marker = _chocolate_marker(ticket_id, 1)
        return [(marker, [Container(
            accent_color=ACCENT_YELLOW,
            components=[
                Text(content=f"## {CHOCOLATE_TITLE_PREFIX}"),
                Text(content=state_copy),
                Text(content=disclaimer),
            ],
        )])]

    panels: list[tuple[str, list[Container]]] = []
    total = len(accounts)
    for start in range(0, total, 20):
        group = accounts[start:start + 20]
        end = start + len(group)
        marker = _chocolate_marker(ticket_id, start // 20 + 1)
        lines = []
        for tag, name in group:
            label_name = _chocolate_link_label(name)
            lines.append(f"- [{label_name} · `{tag}`]({chocolate_url(tag)})")
        title = f"## {CHOCOLATE_TITLE_PREFIX} · {start + 1}–{end} of {total}"
        body = "\n".join(lines)
        # The visible title carries the page identity now, not a hidden
        # marker line, so the full aggregate limit is available here.
        message_budget = DISCORD_MESSAGE_TEXT_LIMIT
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
    heading = f"## {STAFF_CONTEXT_TITLE_PREFIX}"
    account_copy = _staff_account_summary(ticket_doc) if has_account_snapshot else None
    account_state = account_sync.snapshot_from_ticket(ticket_doc).state
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


def _is_staff_context_component(component) -> bool:
    """True if this component tree is the Applicant context panel.

    Identified by its visible title text, the same structural approach as
    the FWA Chocolate checklist (see `_chocolate_title_page`).
    """

    content = str(getattr(component, "content", "") or "").strip()
    if content.startswith(f"## {STAFF_CONTEXT_TITLE_PREFIX}"):
        return True
    return any(
        _is_staff_context_component(child)
        for child in getattr(component, "components", ()) or ()
    )


async def _find_staff_context_message(
    bot: hikari.GatewayBot,
    staff_id: int,
    marker: str,
):
    """Find the newest Applicant context panel message in this ticket's staff thread.

    The panel is identified structurally: authored by the bot, in this
    ticket's own staff thread (one ticket per thread), titled as the
    Applicant context panel -- no bookkeeping text is posted to Discord for
    it. A message from before this change that still carries the old
    ``-# ticket-staff-context:...`` marker line is still recognised.

    Deliberately unbounded, unlike the FWA Chocolate checklist finder: a
    staff thread can accumulate arbitrary conversation after the panel is
    posted, and this message must still be recoverable after a checkpoint
    loss no matter how much later activity has pushed it back (see
    ``test_staff_context_reuses_committed_message_after_checkpoint_loss``,
    which pushes it behind 150 newer messages).
    """

    get_me = getattr(bot, "get_me", None)
    if not callable(get_me):
        return None
    me = get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable")
    matches = []
    history = await _message_history(bot.rest, staff_id)
    for message in history:
        if _int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        components = getattr(message, "components", ()) or ()
        matched = any(
            _component_contains_marker(component, marker)
            for component in components
        ) or any(
            _is_staff_context_component(component)
            for component in components
        )
        if matched:
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


def _chocolate_marker(ticket_id: str, page: int) -> str:
    """Internal bookkeeping key only -- never posted to Discord."""

    return f"{CHOCOLATE_MARKER_PREFIX}:{ticket_id}:{page}"


_CHOCOLATE_RANGE_RE = re.compile(r"·\s*(\d+)–\d+\s*of\s*\d+\s*$")


def _chocolate_title_page(component) -> int | None:
    """Resolve a checklist container's page number from its visible title.

    A retired page's title carries no range and is never matched here --
    once retired, a page is no longer tracked or re-managed.
    """

    content = str(getattr(component, "content", "") or "").strip()
    if content.startswith(f"## {CHOCOLATE_TITLE_PREFIX}"):
        if content.endswith("page retired"):
            return None
        match = _CHOCOLATE_RANGE_RE.search(content)
        if match:
            return (int(match.group(1)) - 1) // 20 + 1
        # Only the bare no-accounts title is page 1; any other unparsed
        # range must not be misclaimed as page 1.
        return 1 if content == f"## {CHOCOLATE_TITLE_PREFIX}" else None
    for child in getattr(component, "components", ()) or ():
        page = _chocolate_title_page(child)
        if page is not None:
            return page
    return None


async def _find_chocolate_messages(
    bot: hikari.GatewayBot,
    staff_id: int,
    ticket_id: str,
) -> dict[str, object]:
    """Find the newest bot-authored FWA Chocolate checklist message per page.

    Pages are identified structurally: the ticket's own staff thread (one
    ticket per thread), authored by the bot, titled as a checklist page --
    no bookkeeping text is posted to Discord for this. A message from
    before this change that still carries the old ``-# ticket-chocolate:...``
    marker line is still recognised, so already-open tickets keep working.
    """

    get_me = getattr(bot, "get_me", None)
    if not callable(get_me):
        return {}
    me = get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable")
    legacy_prefix = f"{CHOCOLATE_MARKER_PREFIX}:{ticket_id}:"
    matches: dict[str, object] = {}
    history = await _message_history(
        bot.rest, staff_id, limit=_STAFF_CONTEXT_SCAN_LIMIT
    )
    for message in history:
        if _int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        components = getattr(message, "components", ()) or ()
        page: int | None = None
        for component in components:
            for legacy_marker in _component_markers_with_prefix(
                component, legacy_prefix
            ):
                try:
                    page = int(legacy_marker.rsplit(":", 1)[-1])
                except ValueError:
                    continue
        if page is None:
            for component in components:
                page = _chocolate_title_page(component)
                if page is not None:
                    break
        if page is None:
            continue
        marker = _chocolate_marker(ticket_id, page)
        prior = matches.get(marker)
        if prior is None or _int(getattr(message, "id", 0)) > _int(
            getattr(prior, "id", 0)
        ):
            matches[marker] = message
    return matches


async def _find_chocolate_message(
    bot: hikari.GatewayBot,
    staff_id: int,
    ticket_id: str,
    page: int,
):
    found = await _find_chocolate_messages(bot, staff_id, ticket_id)
    return found.get(_chocolate_marker(ticket_id, page))


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
        (marker, _context_fingerprint(components))
        for marker, components in source
    ]
    stored_ids = [_int(value) for value in state.get("chocolate_message_ids") or ()]
    stored_fingerprints = [
        str(value) for value in state.get("chocolate_fingerprints") or ()
    ]
    if len(stored_ids) != len(expected) or len(stored_fingerprints) != len(expected):
        return False
    recovered = await _find_chocolate_messages(bot, staff_id, ticket_id)
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


async def _renew_staff_context_lease(
    mongo: MongoClient,
    state_id: str,
    owner: str,
) -> None:
    """Renew one exact owner token immediately before a Discord write."""

    now = utcnow()
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": state_id,
            "kind": "ticket_staff_context",
            "lease_owner": owner,
            "lease_until": {"$gt": now},
        },
        {
            "$set": {
                "lease_until": now + CONTEXT_LEASE,
                "updated_at": now,
            },
        },
    )
    if not getattr(result, "matched_count", 0):
        raise StaffContextLeaseLost(
            f"staff context lease lost state={state_id}"
        )


@contextlib.asynccontextmanager
async def _staff_context_write_window(
    rest,
    ticket_doc: Mapping,
    staff_id: int,
    *,
    reopen_terminal_thread: bool,
    expected_owner_id: int | None,
    renew_lease,
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
    if was_archived:
        await renew_lease()
        await rest.edit_channel(
            staff_id,
            archived=False,
            reason="Retrying committed ticket staff context",
        )
    if was_locked:
        await renew_lease()
        await rest.edit_channel(
            staff_id,
            locked=False,
            reason="Retrying committed ticket staff context",
        )
    yield


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
    renew_lease,
    finder=None,
) -> int:
    """Edit one durable marked message, recovering its ID before recreating it.

    ``finder`` overrides how a lost message ID is recovered; it defaults to
    scanning for the durable marker line. FWA Chocolate checklist pages pass
    a structural, title-based finder instead since they post no marker line.
    """

    async def _default_finder():
        return await _find_staff_context_message(bot, staff_id, marker)

    locate = finder or _default_finder

    if message_id:
        try:
            await renew_lease()
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
            recovered = await locate()
            message_id = _int(getattr(recovered, "id", 0))
            if message_id:
                await renew_lease()
                await bot.rest.edit_message(
                    channel=staff_id,
                    message=message_id,
                    components=components,
                    user_mentions=False,
                    role_mentions=False,
                    mentions_everyone=False,
                )
                return message_id
    await renew_lease()
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
    ticket_id: str,
    marker: str,
    message_id: int,
    renew_lease,
) -> None:
    """Remove stale current-account links without deleting the audit message."""

    if not message_id:
        return
    page_text = marker.rsplit(":", 1)[-1]
    components = [
        Container(
            accent_color=ACCENT_GREY,
            components=[
                Text(content=f"## {CHOCOLATE_TITLE_PREFIX} · page retired"),
                Text(content=(
                    "Accounts formerly shown on this page are no longer in the "
                    "current linked-account snapshot. Their tags remain in durable "
                    "ticket identity history for search and flags."
                )),
            ],
        ),
    ]
    try:
        await renew_lease()
        await bot.rest.edit_message(
            channel=staff_id,
            message=message_id,
            components=components,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
    except hikari.NotFoundError:
        recovered = None
        if page_text.isdigit():
            recovered = await _find_chocolate_message(
                bot, staff_id, ticket_id, int(page_text)
            )
        recovered_id = _int(getattr(recovered, "id", 0))
        if recovered_id:
            await renew_lease()
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

    async def renew_lease() -> None:
        await _renew_staff_context_lease(mongo, state_id, owner)

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
            finished = await _finish_staff_context_lease(
                mongo,
                state_id,
                owner,
                refresh_generation=refresh_generation,
            )
            if not finished:
                raise StaffContextLeaseLost(
                    f"staff context lease lost state={state_id}"
                )
            return None
        if components is None:
            components = _notice(
                "Applicant context updated",
                "This applicant has no active staff flags or earlier tickets.",
                accent=ACCENT_GREEN,
            )
        fingerprint = _context_fingerprint(components)

        prepared_chocolate: list[tuple[str, list, str]] = [
            (
                chocolate_marker,
                chocolate_components,
                _context_fingerprint(chocolate_components),
            )
            for chocolate_marker, chocolate_components in chocolate_source
        ]
        stored_chocolate_ids = state.get("chocolate_message_ids") or ()
        stored_chocolate_fingerprints = state.get("chocolate_fingerprints") or ()
        chocolate_prefix = f"{CHOCOLATE_MARKER_PREFIX}:{ticket_id}:"
        chocolate_checkpoint_complete = (
            len(stored_chocolate_ids) >= len(prepared_chocolate)
            and all(
                _int(value)
                for value in stored_chocolate_ids[:len(prepared_chocolate)]
            )
        )
        recovered_chocolate = (
            {}
            if chocolate_checkpoint_complete
            else await _find_chocolate_messages(bot, staff_id, ticket_id)
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
            and (
                chocolate_checkpoint_complete
                or _int(getattr(
                    recovered_chocolate.get(panel_marker), "id", 0
                )) == chocolate_ids[index]
            )
            for index, (panel_marker, _panel, panel_fingerprint) in enumerate(
                prepared_chocolate
            )
        )
        if context_current and chocolate_current:
            finished = await _finish_staff_context_lease(
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
            if not finished:
                raise StaffContextLeaseLost(
                    f"staff context lease lost state={state_id}"
                )
            return existing_message_id

        async with _staff_context_write_window(
            bot.rest,
            ticket_doc,
            staff_id,
            reopen_terminal_thread=reopen_terminal_thread,
            expected_owner_id=expected_owner_id,
            renew_lease=renew_lease,
        ):
            message_id = existing_message_id
            if not context_current:
                message_id = await _upsert_marked_staff_message(
                    bot,
                    staff_id=staff_id,
                    marker=marker,
                    components=components,
                    message_id=message_id,
                    renew_lease=renew_lease,
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
                    and (
                        chocolate_checkpoint_complete
                        or _int(getattr(
                            recovered_chocolate.get(chocolate_marker), "id", 0
                        )) == chocolate_ids[index]
                    )
                )
                if panel_current:
                    continue
                chocolate_ids[index] = await _upsert_marked_staff_message(
                    bot,
                    staff_id=staff_id,
                    marker=chocolate_marker,
                    components=chocolate_components,
                    message_id=chocolate_ids[index],
                    renew_lease=renew_lease,
                    finder=lambda page=index + 1: _find_chocolate_message(
                        bot, staff_id, ticket_id, page
                    ),
                )
            for stale_marker, stale_message_id in stale_chocolate_messages.items():
                await _retire_chocolate_message(
                    bot,
                    staff_id=staff_id,
                    ticket_id=ticket_id,
                    marker=stale_marker,
                    message_id=stale_message_id,
                    renew_lease=renew_lease,
                )
        finished = await _finish_staff_context_lease(
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
        if not finished:
            raise StaffContextLeaseLost(
                f"staff context lease lost state={state_id}"
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
    except StaffContextLeaseLost:
        _log.info("staff ticket context lease lost ticket=%s", ticket_id)
        return None
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
        "type": "ticket_v2_console_search",
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
    submit_action: str = "ticket_v2_console_find_submit",
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


@register_action("ticket_v2_console_pick", no_return=True)
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
    "ticket_v2_console_find", opens_modal=True, no_return=True, preload_state=False,
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
        submit_action="ticket_v2_console_find_root_submit",
    )


@register_action(
    "ticket_v2_console_search_again", opens_modal=True, no_return=True,
    preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_search_again(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    await _open_find_modal(ctx, action_id)


@register_action("ticket_v2_console_view", requires_state=True)
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
    if not envelope or envelope.get("type") != "ticket_v2_console_flag_manager":
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
        or data.get("type") != "ticket_v2_console_flag_manager"
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


@register_action("ticket_v2_console_manage_flags", requires_state=True)
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


@register_action("ticket_v2_flag_back", requires_state=True)
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
    "ticket_v2_flag_set", opens_modal=True, no_return=True, preload_state=False,
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
        custom_id=f"ticket_v2_flag_set_submit:{manager_id}|{kind}",
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
    "ticket_v2_flag_remove", opens_modal=True, no_return=True, preload_state=False,
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
        custom_id=f"ticket_v2_flag_remove_submit:{action_id}|{slot}",
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
    "ticket_v2_flag_set_submit", is_modal=True, no_return=True, preload_state=False,
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
    "ticket_v2_flag_remove_submit", is_modal=True, no_return=True,
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
    "ticket_v2_console_find_submit", is_modal=True, no_return=True, preload_state=False,
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
    if not data or data.get("type") != "ticket_v2_console_search":
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
    "ticket_v2_console_find_root_submit",
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
        # The dispatcher already deferred this interaction as a message edit
        # (see extensions/components.py); returning None here unconditionally
        # edits the panel to no components at all, blanking a search panel
        # that still legitimately belongs to this owner. Re-render it
        # unchanged instead of losing it out from under them.
        return await _render_search_session(
            mongo,
            action_id=action_id,
            owner_id=owner_id,
            guild_id=guild_id,
            query=query,
            statuses=statuses,
            ticket_types=ticket_types,
        )
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


@register_action("ticket_v2_console_status", requires_state=True)
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


@register_action("ticket_v2_console_type", requires_state=True)
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


async def _transition_result_panel(
    result, *, verb: str, mongo: MongoClient, owner_id: int, guild_id: int,
) -> list[Container]:
    if result.outcome == store.WON:
        return _notice(
            f"Ticket {verb}",
            "The decision was saved. The applicant is being notified. The "
            "permanent thread remains available from the console.",
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
                "Approval not completed" if verb == "approved" else "Not completed",
                reason,
                accent=ACCENT_YELLOW,
            )
        flag_id = _clean_code_span(blocker.get("_id"), limit=80)
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
    return await _already_decided_notice(
        mongo, current, owner_id=owner_id, guild_id=guild_id,
    )


async def _owner_only_notice(ctx, owner_id: int) -> list[Container] | None:
    if int(ctx.user.id) != int(owner_id):
        return _notice(
            "Private panel",
            "Open your own ticket panel from the shared console.",
            accent=ACCENT_RED,
        )
    return None


async def _show_in_progress(ctx, title: str) -> None:
    """Best-effort loading card so the confirm buttons don't look dead.

    The dispatcher's own `defer(edit=True)` (DEFERRED_MESSAGE_UPDATE) and a
    handler's own manual defer both acknowledge silently with no loading
    state, so without this the confirm buttons stay live for as long as the
    decision takes to commit -- inviting a second click that loses the
    status CAS and renders "Already approved/denied", read as a failure.
    Best-effort: a missing or dead interaction (several tests build a bare
    ctx with no `.interaction`; a live token can also die mid-click) must
    never stop the real decision from proceeding.
    """
    try:
        await ctx.interaction.edit_initial_response(
            components=_notice(
                title,
                "Saving the decision and updating the ticket. This can take "
                "a few seconds.",
                accent=ACCENT_YELLOW,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
    except Exception:
        _log.exception("failed to show in-progress notice %r", title)


@register_action("ticket_v2_console_approve", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_approve(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Approve is one click plus a confirm, never a silent single click."""
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is no longer available.",
            accent=ACCENT_RED,
        )
    return _approve_confirm_panel(ticket_doc, action_id=action_id)


@register_action("ticket_v2_console_approve_go", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_approve_go(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    expected_status: str = "open",
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    await _show_in_progress(ctx, "Approving…")
    try:
        result = await resolve.approve_ticket(
            bot,
            mongo,
            ticket_id=ticket_id,
            member=ctx.member,
            actor_name=ctx.user.username,
            expected_status=expected_status,
        )
    except Exception:
        _log.exception("ticket approval failed ticket=%s", ticket_id)
        return _notice(
            "Decision not saved",
            "Something went wrong before the decision was saved. Open the "
            "ticket again and retry.",
            accent=ACCENT_RED,
        )
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket approved")
    return await _transition_result_panel(
        result, verb="approved", mongo=mongo, owner_id=owner_id, guild_id=guild_id,
    )


@register_action("ticket_v2_console_confirm_cancel", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_confirm_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is no longer available.",
            accent=ACCENT_RED,
        )
    return await _ticket_detail_panel(
        mongo, ticket_doc, owner_id=owner_id, guild_id=guild_id,
    )


@register_action("ticket_v2_console_overturn", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_overturn(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return _notice(
            "Recruiter access required",
            "Only recruiters can use the ticket console.",
            accent=ACCENT_RED,
        )
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None or ticket_doc.get("status") not in schema.TERMINAL_STATUSES:
        return _notice(
            "Ticket changed",
            "This ticket is no longer decided. Open it again from the console.",
            accent=ACCENT_YELLOW,
        )
    return _overturn_step1_panel(ticket_doc, action_id=action_id)


@register_action("ticket_v2_console_overturn_approve_confirm", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_overturn_approve_confirm(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    ticket_doc = await store.find_one(mongo, {"_id": ticket_id, "type": "ticket"})
    if ticket_doc is None:
        return _notice(
            "Ticket not found",
            "The ticket record is no longer available.",
            accent=ACCENT_RED,
        )
    return _approve_confirm_panel(ticket_doc, action_id=action_id, overturn=True)


@register_action("ticket_v2_console_overturn_approve_go", requires_state=True)
@lightbulb.di.with_di
async def ticket_console_overturn_approve_go(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    owner_id: int,
    guild_id: int,
    ticket_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    if (denied := await _owner_only_notice(ctx, owner_id)) is not None:
        return denied
    await _show_in_progress(ctx, "Approving…")
    try:
        result = await resolve.overturn_ticket(
            bot,
            mongo,
            ticket_id=ticket_id,
            member=ctx.member,
            actor_name=ctx.user.username,
            to_status="approved",
        )
    except Exception:
        _log.exception("ticket overturn failed ticket=%s", ticket_id)
        return _notice(
            "Decision not saved",
            "Something went wrong before the decision was saved. Open the "
            "ticket again and retry.",
            accent=ACCENT_RED,
        )
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket overturned")
    return await _transition_result_panel(
        result, verb="approved", mongo=mongo, owner_id=owner_id, guild_id=guild_id,
    )


@register_action(
    "ticket_v2_overturn_deny_open", opens_modal=True, no_return=True,
    preload_state=False,
)
@lightbulb.di.with_di
async def ticket_overturn_deny_open(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    # Matches ticket_console_deny: no state read here, since the reason
    # modal's own submit handler owns every check (owner, guild, recruiter).
    await ctx.respond_with_modal(
        title="Deny ticket",
        custom_id=f"ticket_v2_overturn_deny_submit:{action_id}",
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
    "ticket_v2_overturn_deny_submit", is_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def ticket_overturn_deny_submit(
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
    if not envelope or envelope.get("type") != "ticket_v2_console_detail":
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
        or data.get("type") != "ticket_v2_console_detail"
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
    await _show_in_progress(ctx, "Denying…")
    ticket_id = str(data.get("ticket_id") or "")
    try:
        result = await resolve.overturn_ticket(
            bot,
            mongo,
            ticket_id=ticket_id,
            member=ctx.member,
            actor_name=ctx.user.username,
            to_status="denied",
            reason=reason,
        )
    except Exception:
        _log.exception("ticket overturn failed ticket=%s", ticket_id)
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Decision not saved",
                "Something went wrong before the decision was saved. Open "
                "the ticket again and retry.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket overturned")
    components = await _transition_result_panel(
        result, verb="denied", mongo=mongo, owner_id=owner_id, guild_id=guild_id,
    )
    await ctx.interaction.edit_initial_response(
        components=components,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@register_action(
    "ticket_v2_console_deny", opens_modal=True, no_return=True,
    preload_state=False,
)
@lightbulb.di.with_di
async def ticket_console_deny(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
) -> None:
    await ctx.respond_with_modal(
        title="Deny ticket",
        custom_id=f"ticket_v2_console_deny_submit:{action_id}",
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
    "ticket_v2_console_deny_submit", is_modal=True, no_return=True, preload_state=False,
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
    if not envelope or envelope.get("type") != "ticket_v2_console_detail":
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
        or data.get("type") != "ticket_v2_console_detail"
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
    await _show_in_progress(ctx, "Denying…")
    ticket_id = str(data.get("ticket_id") or "")
    try:
        result = await resolve.deny_ticket(
            bot,
            mongo,
            ticket_id=ticket_id,
            member=ctx.member,
            actor_name=ctx.user.username,
            kind=resolve.KIND_DENY_CUSTOM,
            reason=reason,
            expected_status=str(data.get("expected_status") or "open"),
        )
    except Exception:
        _log.exception("ticket denial failed ticket=%s", ticket_id)
        await ctx.interaction.edit_initial_response(
            components=_notice(
                "Decision not saved",
                "Something went wrong before the decision was saved. Open "
                "the ticket again and retry.",
                accent=ACCENT_RED,
            ),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
        return
    if result.outcome in {store.WON, store.EFFECT_FAILED}:
        await request_hub_refresh_best_effort(bot, mongo, reason="ticket denied")
    components = await _transition_result_panel(
        result, verb="denied", mongo=mongo, owner_id=owner_id, guild_id=guild_id,
    )
    await ctx.interaction.edit_initial_response(
        components=components,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


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
                submit_action="ticket_v2_console_find_root_submit",
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
