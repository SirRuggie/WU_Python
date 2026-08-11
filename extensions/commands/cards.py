"""One-command Clash of Cards collection and family matching hub.

Members run ``/cards`` and start an account-bound private upload from its
dashboard. They can send the collection screenshots together in any order, or
use the manual editor as a fallback. No scan writes automatically: account
ownership, full card coverage, uncertainty, reservations, and inventory
revision are rechecked at explicit confirmation.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import coc
import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError

from extensions.commands.accounts import (
    LINK_FAILURE,
    STATUS_ERROR,
    STATUS_LOADED,
    STATUS_NOT_FOUND,
    AccountEntry,
    AccountsData,
    load_accounts,
)
from extensions.components import register_action
from utils.card_board import (
    CARD_ARTWORK_DIR,
    CATEGORY_ACCENTS,
    OWNED_SPARE_UNVERIFIED,
    SPARE_FLOOR,
    render_card_thumbnail,
    render_category_strip,
    render_inventory_card_board,
    render_trade_strip,
)
from utils.cards import (
    CARD_BY_ID,
    CARD_BY_NAME,
    CARDS,
    CATEGORIES,
    CATEGORY_BY_ID,
    CATEGORY_CARDS,
    DUPLICATE,
    MATCHABLE_FOR,
    MAX_COPIES,
    MISSING,
    OWNED,
    apply_category_selection,
    as_utc,
    category_summary,
    family_supply,
    find_matches,
    freshness_label,
    holders_for_card,
    inventory_summary,
    inventory_is_matchable,
    max_achievable_trades,
    normalize_cards,
    normalize_status,
    reciprocal_trade_error,
)
from utils.component_state import delete_state, get_state, insert_state, update_state
from utils import troop_emoji
from utils.emoji import emojis
from utils.constants import GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

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
    ThumbnailComponentBuilder as Thumbnail,
)


loader = lightbulb.Loader()
_log = logging.getLogger(__name__)

ACCOUNT_PAGE_SIZE = 25
MATCH_RESULT_LIMIT = 10
HOLDER_RESULT_LIMIT = 6
TRADE_VIEW_LIMIT = 5
MAX_OPEN_PROPOSALS_PER_ACCOUNT = 25
COMMITTED_TRADE_FETCH_LIMIT = 100
PROPOSAL_TRADE_FETCH_LIMIT = 250
REVIEW_TRADE_FETCH_LIMIT = 250
TRADE_COMPLETION_FOR = timedelta(minutes=10)
PROPOSAL_SLOT_HOLD_FOR = timedelta(minutes=10)
TRADE_REVIEW_FOR = timedelta(days=7)
TRADE_LEASE_COUNT = 4
CARD_SCAN_CAPTURE_COUNT = 5
CARD_SCAN_DRAFT_FOR = timedelta(minutes=20)
CARD_SCAN_MAX_IMAGE_BYTES = 10 * 1024 * 1024
CARD_SCAN_MAX_BATCH_BYTES = 50 * 1024 * 1024
CARD_SCAN_MAX_UPLOAD_ATTACHMENTS = 10
CARD_SCAN_MIN_CONFIDENCE = 0.75
CARD_SCAN_CONCURRENCY = 2
HIDDEN_BADGE_BATCH_SIZE = 25
COLLECTION_LINK = "https://link.clashofclans.com/en/?action=OpenCollection"
GLOBAL_CHAT_LINK = (
    "https://link.clashofclans.com/?action=OpenGlobalChat&"
    "chatId=P592bad3209a4408a9ba356469caaaa81"
)
FOOTER = "assets/Red_Footer.png"

def _parse_snowflake_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value < 2**64 else None


CARDS_GUILD_ID = _parse_snowflake_env("CARDS_GUILD_ID")
CARDS_CHANNEL_ID = _parse_snowflake_env("CARDS_CHANNEL_ID")

# The four category emoji uploaded to the bot. `CardCategory.emoji` keeps its
# plain unicode, which is still what select placeholders and the rendered board
# have to use: neither renders `<:name:id>` markup, they print it literally.
CATEGORY_EMOJI = {
    "elixir": emojis.card_elixir,
    "dark_elixir": emojis.card_dark_elixir,
    "builder_base": emojis.card_builder_base,
    "super_troop": emojis.card_super_troop,
}


def category_markup(category_id: str) -> str:
    """Inline emoji for a category, falling back to its unicode stand-in."""
    entry = CATEGORY_EMOJI.get(str(category_id))
    fallback = CATEGORY_BY_ID[category_id].emoji if category_id in CATEGORY_BY_ID else ""
    return str(entry) if entry is not None else fallback


def category_partial(category_id: str):
    """A CustomEmoji for a component's `emoji=` field, or UNDEFINED.

    `EmojiType.partial_emoji` raises on a malformed string, and one bad id here
    would take down every panel that names a category, so this degrades to no
    emoji the same way troop_emoji does.
    """
    entry = CATEGORY_EMOJI.get(str(category_id))
    if entry is None:
        return hikari.UNDEFINED
    try:
        return entry.partial_emoji
    except (ValueError, IndexError, TypeError):
        return hikari.UNDEFINED

# A member can keep two ephemeral panels open and submit both selects almost at
# once. Serialize writes per player tag so the missing-list update cannot race
# the duplicate-list update and replace it from a stale snapshot.
_inventory_locks: dict[str, asyncio.Lock] = {}
_card_scan_slots = asyncio.Semaphore(CARD_SCAN_CONCURRENCY)
_card_upload_locks: dict[int, asyncio.Lock] = {}


class ActiveCardTradeError(RuntimeError):
    """Raised when a collection edit touches a card reserved by a swap."""


class InventoryWriteConflict(RuntimeError):
    """Raised after repeated cross-process collection revision conflicts."""


class ScanDraftStaleError(RuntimeError):
    """Raised when a collection changed after its screenshot review opened."""


class InvalidCardTransitionError(RuntimeError):
    """Raised when a quick action no longer matches the card's saved state."""


QUICK_CARD_ACTIONS = {
    "found": {
        "label": "Found a missing card",
        "short_label": "Found card",
        "emoji": "✅",
        "from": MISSING,
        "to": OWNED,
        "result": "1 copy",
    },
    "spare": {
        "label": "Got a spare",
        "short_label": "Got spare",
        "emoji": "➕",
        "from": OWNED,
        "to": DUPLICATE,
        "result": "duplicate",
    },
    "used": {
        "label": "Used or traded a spare",
        "short_label": "Used spare",
        "emoji": "↘️",
        "from": DUPLICATE,
        "to": OWNED,
        "result": "1 copy",
    },
    "missing": {
        "label": "Mark a card missing",
        "short_label": "Mark missing",
        "emoji": "❌",
        "from": None,
        "to": MISSING,
        "result": "missing",
    },
}


def _inventory_lock(tag: str) -> asyncio.Lock:
    normalized = _normalize_tag(tag)
    lock = _inventory_locks.get(normalized)
    if lock is None:
        lock = asyncio.Lock()
        _inventory_locks[normalized] = lock
    return lock


def _card_upload_lock(discord_id: int) -> asyncio.Lock:
    user_id = int(discord_id)
    lock = _card_upload_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _card_upload_locks[user_id] = lock
    return lock


def _normalize_tag(value: object) -> str:
    tag = str(value or "").strip().upper()
    if tag and not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


def _guild_id(ctx) -> int | None:
    value = getattr(ctx, "guild_id", None)
    return int(value) if value is not None else None


def _configured_cards_guild_id() -> int | None:
    """Return the one Discord family allowed to own card inventory data."""
    return CARDS_GUILD_ID


def _configured_cards_channel_id() -> int | None:
    """Return the shared family trade-board channel, when configured."""
    return CARDS_CHANNEL_ID


def _guild_scope_error(ctx) -> str | None:
    configured = _configured_cards_guild_id()
    actual = _guild_id(ctx)
    if configured is None:
        return (
            "The Card Hub is not configured yet. An operator must set "
            "`CARDS_GUILD_ID` to the Warriors United Discord server ID."
        )
    if actual != configured:
        return (
            "Run `/cards` inside the configured Warriors United server so "
            "collections and trades stay inside the correct clan family."
        )
    return None


def _escape_markdown(value: object, *, limit: int = 100) -> str:
    raw = str(value or "Unknown")
    if len(raw) > limit:
        raw = f"{raw[:limit - 1]}…"
    escaped = raw.replace("\\", "\\\\")
    for char in ("`", "*", "_", "~", "|", ">", "[", "]", "(", ")"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped.replace("@", "@\u200b")


def _plain(value: object, *, limit: int = 90) -> str:
    text = str(value or "Unknown").replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _notice(title: str, description: str) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"# {title}"),
            Separator(divider=True),
            Text(content=description),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _stale_collection_notice() -> list[Container]:
    return _notice(
        "Confirm your collection first",
        "Trade search only uses collections confirmed within the last 72 hours. "
        "Return to the dashboard and choose **Everything still accurate**, or "
        "update the lists that changed.",
    )


def _active_trade_notice(tag: str) -> list[Container]:
    tag = _normalize_tag(tag)
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# This category has reserved cards"),
            Text(content=(
                "An accepted swap is protecting one or more cards in this "
                "category. Finish or cancel that swap before editing this "
                "category; the rest of the account stays available."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_trades:{tag}",
                    label="My trades",
                    emoji="🤝",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}",
                    label="Dashboard",
                    emoji="⬅️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _inventory_retry_notice() -> list[Container]:
    return _notice(
        "Collection changed at the same time",
        "Another update won while this list was saving. Nothing unsafe was "
        "overwritten—reopen the category and try once more.",
    )


def _loaded_entries(data: AccountsData) -> list[AccountEntry]:
    return [
        entry
        for entry in data.entries
        if entry.status == STATUS_LOADED and entry.account is not None
    ]


def _parse_page(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _parse_target(value: str) -> tuple[str, str | None]:
    tag, separator, category_id = str(value or "").partition("|")
    category = category_id if separator and category_id in CATEGORY_BY_ID else None
    return _normalize_tag(tag), category


def _parse_editor_target(value: object) -> tuple[str, str | None]:
    tag, separator, card_id = str(value or "").partition("|")
    return (
        _normalize_tag(tag),
        card_id if separator and card_id in CARD_BY_ID else None,
    )


def _parse_card_step_target(value: object) -> tuple[str, str | None, int]:
    parts = str(value or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    card_id = parts[1] if len(parts) > 1 and parts[1] in CARD_BY_ID else None
    delta = 0
    if len(parts) > 2:
        try:
            delta = max(-1, min(1, int(parts[2])))
        except (TypeError, ValueError):
            delta = 0
    return tag, card_id, delta


def _parse_card_set_target(value: object) -> tuple[str, str | None, int | None]:
    parts = str(value or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    card_id = parts[1] if len(parts) > 1 and parts[1] in CARD_BY_ID else None
    target: int | None = None
    if len(parts) > 2:
        try:
            candidate = int(parts[2])
        except (TypeError, ValueError):
            candidate = -1
        if MISSING <= candidate <= MAX_COPIES:
            target = candidate
    return tag, card_id, target


def _parse_editor_category_target(value: object) -> tuple[str, str | None, int]:
    parts = str(value or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    category_id = parts[1] if len(parts) > 1 and parts[1] in CATEGORY_BY_ID else None
    try:
        page = max(0, int(parts[2])) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        page = 0
    return tag, category_id, page


def _card_search_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _card_name_matches(value: object, *, limit: int = 3) -> tuple[object, ...]:
    """Return an exact card or the strongest typo-tolerant suggestions."""
    query = str(value or "").strip()
    exact = CARD_BY_NAME.get(query.casefold()) or CARD_BY_ID.get(
        query.casefold().replace(" ", "_")
    )
    if exact is not None:
        return (exact,)
    key = _card_search_key(query)
    if not key:
        return ()
    scored = []
    for card in CARDS:
        candidate = _card_search_key(card.name)
        score = difflib.SequenceMatcher(None, key, candidate).ratio()
        if candidate.startswith(key) or key.startswith(candidate):
            score += 0.12
        if score >= 0.58:
            scored.append((score, -len(candidate), card.position, card))
    scored.sort(reverse=True, key=lambda item: item[:3])
    return tuple(item[3] for item in scored[:max(1, limit)])


def _parse_trade_request_target(value: str) -> tuple[str, str]:
    tag, separator, card_id = str(value or "").partition("|")
    return _normalize_tag(tag), card_id if separator else ""


def _parse_trade_option(value: object) -> tuple[str, str]:
    tag, separator, card_id = str(value or "").partition("|")
    return _normalize_tag(tag), card_id if separator else ""


def _parse_trade_page(value: object) -> tuple[str, int]:
    tag, separator, page = str(value or "").partition("|")
    return _normalize_tag(tag), _parse_page(page if separator else 0)


def _parse_holder_page(value: object) -> tuple[str, str, int]:
    parts = str(value or "").split("|", 2)
    if len(parts) != 3:
        return "", "", 0
    return _normalize_tag(parts[0]), parts[1], _parse_page(parts[2])


def _relative_timestamp(value: object) -> str:
    stamp = as_utc(value)
    return f"<t:{int(stamp.timestamp())}:R>" if stamp is not None else "never"


def _card_reservations(
    inventory: dict,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    raw = inventory.get("card_trade_reservations")
    if not isinstance(raw, dict):
        return {}
    checked_at = now or datetime.now(timezone.utc)
    active: dict[str, str] = {}
    for card_id, marker in raw.items():
        if card_id not in CARD_BY_ID:
            continue
        if isinstance(marker, dict):
            owner = str(marker.get("owner") or "")
            until = as_utc(marker.get("until"))
            if until is not None and until <= checked_at:
                continue
        else:
            # Version-one development rows stored the owner directly. Treat
            # them as indefinite so an upgrade cannot silently double-book.
            owner = str(marker or "")
        if owner:
            active[str(card_id)] = owner
    return active


def _inventory_has_active_trade(inventory: dict, *, now: datetime | None = None) -> bool:
    """Compatibility helper: whether any exact card is currently reserved."""
    del now
    return bool(_card_reservations(inventory))


def _category_has_reservations(inventory: dict, category_id: str) -> bool:
    reserved = _card_reservations(inventory)
    return any(card.id in reserved for card in CATEGORY_CARDS[category_id])


def _without_reserved_cards(inventory: dict) -> dict:
    """Return a matching snapshot with committed needs/supplies masked out."""
    reserved = _card_reservations(inventory)
    if not reserved:
        return inventory
    snapshot = dict(inventory)
    cards = normalize_cards(inventory.get("cards"))
    for card_id in reserved:
        cards[card_id] = OWNED
    snapshot["cards"] = cards
    return snapshot


PROGRESS_WIDTH = 12
PROGRESS_FULL = "█"
PROGRESS_EMPTY = "░"


def _category_progress(inventory: dict) -> str:
    """A per-category completion bar, one line each.

    Discord renders normal text in a proportional font, so padded plain text
    does not line up. An inline code span is monospaced and preserves runs of
    spaces, so putting the bar and the counts inside backticks gives a real
    column while the category emoji stays outside where it renders as art.
    This is ClashPerk's cell grammar, applied to progress instead of levels.
    """
    saved = normalize_cards(inventory.get("cards"))
    lines = []
    for category in CATEGORIES:
        cards_in = CATEGORY_CARDS[category.id]
        held = sum(1 for card in cards_in if saved.get(card.id, OWNED) >= OWNED)
        total = len(cards_in)
        filled = round(PROGRESS_WIDTH * held / total) if total else 0
        bar = PROGRESS_FULL * filled + PROGRESS_EMPTY * (PROGRESS_WIDTH - filled)
        tally = f"{held:>2}/{total:<2}"
        done = " ✓" if held == total else ""
        lines.append(f"{category_markup(category.id)} `{bar} {tally}`{done}")
    return "\n".join(lines)


def _card_rows(
    card_ids: tuple[str, ...] | list[str],
    *,
    limit: int = 6,
) -> str:
    """Cards as bullet rows, one per line, each led by its troop art.

    A comma-joined run mixing emoji and names is genuinely hard to read: the
    eye has no consistent left edge and the emoji break the rhythm of the
    commas. One card per bullet gives a column to scan down instead.

    Use this wherever a list stands on its own. `_card_names` still exists for
    the places a list has to sit inside a sentence.
    """
    known = [CARD_BY_ID[card_id] for card_id in card_ids if card_id in CARD_BY_ID]
    if not known:
        return "-# none"
    rows = []
    for card in known[:limit]:
        icon = troop_emoji.markup(card.id)
        lead = f"{icon} " if icon else ""
        rows.append(f"- {lead}{_escape_markdown(card.name)}")
    if len(known) > limit:
        rows.append(f"-# and {len(known) - limit} more")
    return "\n".join(rows)


def _card_names(card_ids: tuple[str, ...] | list[str], *, limit: int = 5) -> str:
    """A readable run of card names, each led by its troop art.

    This is the shared formatter behind the scan review, the trade offers and
    the holder lists, so the emoji arrive everywhere a card is named rather
    than only on the family board. `troop_emoji.markup` returns "" for a troop
    that has not been synced and never raises, so an un-synced set degrades to
    plain names.
    """
    known = [CARD_BY_ID[card_id] for card_id in card_ids if card_id in CARD_BY_ID]
    if not known:
        return "none"
    shown = []
    for card in known[:limit]:
        icon = troop_emoji.markup(card.id)
        shown.append(f"{icon} {card.name}" if icon else card.name)
    suffix = f" +{len(known) - limit} more" if len(known) > limit else ""
    return ", ".join(shown) + suffix


def _town_hall_emoji(level: object):
    """A town hall CustomEmoji for a component's `emoji=` field, or UNDEFINED.

    `EmojiType.partial_emoji` raises on a malformed id, and one bad id in the
    shared table would otherwise take the whole account picker down. An
    unknown or unconfigured town hall level falls back to no emoji, and the
    caller keeps the level in the label so nothing is lost.
    """
    try:
        obj = getattr(emojis, f"TH{int(level)}", None)
    except (TypeError, ValueError):
        return hikari.UNDEFINED
    if obj is None:
        return hikari.UNDEFINED
    try:
        return obj.partial_emoji
    except (ValueError, IndexError):
        return hikari.UNDEFINED


def _account_picker(data: AccountsData, page: int = 0) -> list[Container]:
    if data.problem == LINK_FAILURE:
        return _notice(
            "Couldn't reach the account link service",
            "I can't safely tell which Clash accounts belong to you right now. "
            "Nothing was changed—please try `/cards` again shortly.",
        )

    entries = _loaded_entries(data)
    if not entries:
        return _notice(
            "No usable linked accounts",
            "Link a Clash account with ClashKing's `/link` command using the "
            "in-game API token from **Settings → More Settings → API Token**, "
            "then run `/cards` again.",
        )

    pages = max(1, math.ceil(len(entries) / ACCOUNT_PAGE_SIZE))
    page = min(_parse_page(page), pages - 1)
    start = page * ACCOUNT_PAGE_SIZE
    window = entries[start:start + ACCOUNT_PAGE_SIZE]

    # A select, not a Section per account. Sections were tried and are worse
    # here: on mobile the accessory button wraps BELOW its text, so every
    # account costs about 200px, and this bot's owner has 37 linked accounts.
    # A select holds 25 in one tap and stays one line tall. Sections are right
    # for a handful of rows, which this is not.
    options = []
    for entry in window:
        town_hall = getattr(entry.account, "town_hall", None)
        emoji = _town_hall_emoji(town_hall)
        label = (
            entry.account.name
            if emoji is not hikari.UNDEFINED
            else f"{entry.account.name} · TH{town_hall}"
        )
        options.append(SelectOption(
            label=_plain(label),
            value=entry.tag,
            description=_plain(
                f"TH{town_hall} · {entry.account.clan_name or 'No clan'} · {entry.tag}",
                limit=100,
            ),
            emoji=emoji,
        ))

    body: list = [
        Text(content="# Your card collections"),
        Text(content=(
            f"-# {len(entries)} linked accounts · each keeps its own collection"
        )),
        Separator(divider=True),
        ActionRow(components=[
            TextSelectMenu(
                custom_id=f"cards_account_select:{page}",
                placeholder="Choose a Clash account...",
                max_values=1,
                options=options,
            )
        ]),
    ]
    if pages > 1:
        body.extend([
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_account_page:{page - 1}",
                    label="Previous",
                    is_disabled=page == 0,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_account_page:{page + 1}",
                    label="Next",
                    is_disabled=page >= pages - 1,
                ),
            ]),
            Text(content=(
                f"-# Accounts {start + 1}-{start + len(window)} "
                f"of {len(entries)}"
            )),
        ])
    return [Container(accent_color=GOLD_ACCENT, components=body)]


def _scan_field(value: object, *names: str, default=None):
    """Read one scanner field without coupling Card Hub to its dataclasses."""
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _scan_strings(value: object, *, limit: int = 30) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    try:
        iterator = iter(values)
    except TypeError:
        iterator = iter((value,))
    result: list[str] = []
    for item in iterator:
        text = str(item or "").replace("\n", " ").strip()
        if text and text not in result:
            result.append(text[:160])
        if len(result) >= limit:
            break
    return result


def _scan_card_id(value: object) -> str:
    card_id = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return card_id if card_id in CARD_BY_ID else ""


def _scan_card_state(value: object) -> int | None:
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        state = {
            "missing": MISSING,
            "owned": OWNED,
            "owned_once": OWNED,
            "duplicate": DUPLICATE,
            "spare": DUPLICATE,
        }.get(raw.strip().casefold().replace(" ", "_"))
        return state
    if isinstance(raw, bool):
        return None
    try:
        state = int(raw)
    except (TypeError, ValueError):
        return None
    return state if state in {MISSING, OWNED, DUPLICATE} else None


def _scan_confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence):
        return None
    return max(0.0, min(1.0, confidence))


def _ordered_card_ids(values) -> list[str]:
    wanted = set(values or ())
    return [card_id for card_id in CARD_BY_ID if card_id in wanted]


def _scan_id_set(value: object) -> tuple[set[str], bool]:
    if value is None:
        return set(), False
    values = (value,) if isinstance(value, str) else value
    try:
        items = list(values)
    except TypeError:
        items = [value]
    parsed = {_scan_card_id(item) for item in items}
    invalid = "" in parsed
    parsed.discard("")
    return parsed, invalid


def _normalize_collection_scan(result: object, *, capture_count: int) -> dict:
    """Convert the evolving batch-scanner result into a BSON-safe review draft.

    Expected scanner contract: ``scan_collection_screenshots(items,
    prior_draft=...)`` accepts one or more image byte payloads in any order and
    returns identity-bound card records plus missing logical page/row numbers.
    Every record supplies ``card_id``, ``state``, ``confidence``, and optional
    warnings. This adapter deliberately accepts a few equivalent field names;
    it never infers a card identity from input order.
    """
    raw_cards = _scan_field(
        result,
        "cards",
        "card_results",
        "card_scans",
        "slots",
        "card_states",
        default=(),
    )
    confidence_map = _scan_field(result, "confidences", "card_confidences", default={})
    warning_map = _scan_field(result, "card_warnings", "warnings_by_card", default={})
    states: dict[str, int] = {}
    confidences: dict[str, float] = {}
    card_warnings: dict[str, list[str]] = {}
    unknown: set[str] = set()
    duplicate_ids: set[str] = set()
    identity_bound = True
    capture_issues: list[dict] = []

    raw_captures = _scan_field(result, "captures", "capture_results", default=())
    try:
        capture_records = list(raw_captures or ())
    except TypeError:
        capture_records = []
    harmless_capture_codes = {
        "catalog_position_and_artwork_validated",
        "catalog_position_bound_by_batch_order",
        "duplicate_capture_ignored",
        "duplicate_page_ignored",
    }
    for fallback_index, capture in enumerate(capture_records, start=1):
        try:
            image_number = int(_scan_field(capture, "input_index", default=fallback_index))
        except (TypeError, ValueError):
            image_number = fallback_index
        image_number = max(1, image_number)
        try:
            assigned_page = int(_scan_field(
                capture,
                "assigned_page_number",
                "assigned_page",
                default=0,
            ))
        except (TypeError, ValueError):
            assigned_page = 0
        assigned_page = (
            assigned_page
            if 1 <= assigned_page <= CARD_SCAN_CAPTURE_COUNT
            else None
        )
        all_codes = _scan_strings(
            _scan_field(capture, "warnings", "issues", default=()), limit=12
        )
        codes = [
            code
            for code in all_codes
            if code not in harmless_capture_codes
        ]
        mismatch_ids, bad_mismatch_id = _scan_id_set(
            _scan_field(capture, "mismatched_card_ids", default=())
        )
        if bad_mismatch_id:
            identity_bound = False
        harmless_duplicate = bool(
            {"duplicate_capture_ignored", "duplicate_page_ignored"} & set(all_codes)
        )
        if (
            codes
            or mismatch_ids
            or (
                not bool(_scan_field(capture, "accepted", default=False))
                and not harmless_duplicate
            )
        ):
            capture_issues.append({
                "image": image_number,
                "assigned_page": assigned_page,
                "warnings": codes,
                "mismatched_card_ids": _ordered_card_ids(mismatch_ids),
            })

    if isinstance(raw_cards, dict):
        records = list(raw_cards.items())
    else:
        try:
            records = [(None, record) for record in raw_cards]
        except TypeError:
            records = []

    for mapping_id, record in records:
        record_id = _scan_field(record, "card_id", "id", "card", default=mapping_id)
        card_id = _scan_card_id(record_id)
        if not card_id:
            identity_bound = False
            continue
        if card_id in states or card_id in unknown:
            duplicate_ids.add(card_id)
            states.pop(card_id, None)
            confidences.pop(card_id, None)
            unknown.add(card_id)
            continue

        raw_state = _scan_field(record, "state", "status", "value", default=record)
        state = _scan_card_state(raw_state)
        raw_confidence = _scan_field(record, "confidence", "score", default=None)
        if raw_confidence is None and isinstance(confidence_map, dict):
            raw_confidence = confidence_map.get(card_id)
        confidence = _scan_confidence(raw_confidence)
        warnings = _scan_strings(
            _scan_field(record, "warnings", "warning", default=(
                warning_map.get(card_id, ()) if isinstance(warning_map, dict) else ()
            )),
            limit=8,
        )
        if warnings:
            card_warnings[card_id] = warnings
        if state is None or confidence is None or confidence < CARD_SCAN_MIN_CONFIDENCE:
            unknown.add(card_id)
            continue
        states[card_id] = state
        confidences[card_id] = round(confidence, 4)

    explicit_unknown = _scan_field(
        result, "unknown_card_ids", "unknown_ids", "ambiguous_card_ids", default=()
    )
    explicit_unseen = _scan_field(
        result, "unseen_card_ids", "uncovered_card_ids", default=()
    )
    duplicate_unverified = _scan_field(
        result,
        "duplicate_unverified_card_ids",
        "duplicate_badge_unverified_card_ids",
        default=(),
    )
    explicit_unknown_ids, bad_unknown_id = _scan_id_set(explicit_unknown)
    unseen, bad_unseen_id = _scan_id_set(explicit_unseen)
    unverified_duplicates, bad_unverified_id = _scan_id_set(duplicate_unverified)
    identity_bound = identity_bound and not (
        bad_unknown_id or bad_unseen_id or bad_unverified_id
    )
    unknown.update(explicit_unknown_ids)
    unknown.update(duplicate_ids)

    # Explicit identities are mandatory. Anything outside the returned set is
    # unseen even if a scanner accidentally labels global coverage complete.
    identified = set(states) | unknown
    unseen.update(set(CARD_BY_ID) - identified)
    for card_id in unknown | unseen:
        states.pop(card_id, None)
        confidences.pop(card_id, None)
    if any(states.get(card_id) != OWNED for card_id in unverified_duplicates):
        identity_bound = False

    global_warnings = _scan_strings(
        _scan_field(result, "warnings", "global_warnings", default=()),
        limit=20,
    )
    errors = _scan_strings(
        _scan_field(result, "errors", "error", "failure", default=()),
        limit=10,
    )
    coverage_value = _scan_field(
        result, "coverage_complete", "complete_coverage", "complete", default=None
    )
    computed_complete = (
        identity_bound
        and identified == set(CARD_BY_ID)
        and not unseen
    )
    coverage_complete = (
        computed_complete
        if coverage_value is None
        else bool(coverage_value) and computed_complete
    )

    raw_missing_pages = _scan_field(result, "missing_page_numbers", default=None)
    raw_missing_rows = _scan_field(result, "missing_global_rows", default=None)
    if raw_missing_pages is None:
        missing_pages = (
            [] if coverage_complete else list(range(1, CARD_SCAN_CAPTURE_COUNT + 1))
        )
    else:
        try:
            missing_pages = sorted({
                int(value)
                for value in (raw_missing_pages or ())
                if 1 <= int(value) <= CARD_SCAN_CAPTURE_COUNT
            })
        except (TypeError, ValueError):
            missing_pages = list(range(1, CARD_SCAN_CAPTURE_COUNT + 1))
    try:
        missing_rows = sorted({
            int(value)
            for value in (raw_missing_rows or ())
            if 1 <= int(value) <= CARD_SCAN_CAPTURE_COUNT * 2
        })
    except (TypeError, ValueError):
        missing_rows = []
    if raw_missing_rows is None or (missing_pages and not missing_rows):
        missing_rows = [
            row
            for page in missing_pages
            for row in (page * 2 - 1, page * 2)
        ]

    return {
        "version": 2,
        "capture_count": int(capture_count),
        "card_states": states,
        "card_confidences": confidences,
        "card_warnings": card_warnings,
        "unknown_card_ids": _ordered_card_ids(unknown),
        "unseen_card_ids": _ordered_card_ids(unseen),
        "duplicate_unverified_card_ids": _ordered_card_ids(unverified_duplicates),
        "capture_issues": capture_issues,
        "warnings": global_warnings,
        "errors": errors,
        "identity_bound": bool(identity_bound),
        "coverage_complete": bool(coverage_complete),
        "missing_page_numbers": missing_pages,
        "missing_global_rows": missing_rows,
        # Scanner output is always a review draft. This records the scanner's
        # own claim for diagnostics but never bypasses explicit confirmation.
        "scanner_persistence_safe": bool(_scan_field(result, "persistence_safe", default=False)),
    }


def _scan_collection_payloads(
    payloads: tuple[bytes, ...],
    *,
    prior_draft: dict | None = None,
) -> dict:
    """CPU-bound lazy adapter; callers must invoke this with asyncio.to_thread."""
    try:
        from utils import card_scan
    except Exception as exc:
        _log.exception("card screenshot scanner import failed")
        return _normalize_collection_scan(
            {"errors": [f"scanner_import_failed:{type(exc).__name__}"]},
            capture_count=len(payloads),
        )

    scanner = getattr(card_scan, "scan_collection_screenshots", None)
    if not callable(scanner):
        return _normalize_collection_scan(
            {"errors": ["batch_scanner_unavailable"]},
            capture_count=len(payloads),
        )
    try:
        scanner_prior = prior_draft
        if isinstance(prior_draft, dict) and isinstance(
            prior_draft.get("scan_checkpoint"), dict
        ):
            scanner_prior = prior_draft["scan_checkpoint"]
        result = scanner(payloads, prior_draft=scanner_prior)
        draft = _normalize_collection_scan(result, capture_count=len(payloads))
        checkpoint_builder = getattr(card_scan, "collection_scan_checkpoint", None)
        if callable(checkpoint_builder):
            checkpoint = checkpoint_builder(result)
            if isinstance(checkpoint, dict):
                draft["scan_checkpoint"] = checkpoint
        return draft
    except Exception as exc:
        _log.exception("card screenshot batch scan failed")
        return _normalize_collection_scan(
            {"errors": [f"scan_failed:{type(exc).__name__}"]},
            capture_count=len(payloads),
        )


def _scan_draft_confirmable(draft: object) -> bool:
    if not isinstance(draft, dict):
        return False
    states = draft.get("card_states")
    return (
        isinstance(states, dict)
        and set(states) == set(CARD_BY_ID)
        and all(_scan_card_state(state) is not None for state in states.values())
        and bool(draft.get("identity_bound"))
        and bool(draft.get("coverage_complete"))
        and not draft.get("unknown_card_ids")
        and not draft.get("unseen_card_ids")
        and not draft.get("errors")
    )


def _scan_draft_correctable(draft: object) -> bool:
    """Whether identities/coverage are safe and only card states need input."""
    if not isinstance(draft, dict):
        return False
    states = draft.get("card_states")
    unknown, invalid_unknown = _scan_id_set(draft.get("unknown_card_ids") or ())
    return (
        isinstance(states, dict)
        and not invalid_unknown
        and not (set(states) & unknown)
        and (set(states) | unknown) == set(CARD_BY_ID)
        and all(_scan_card_state(state) is not None for state in states.values())
        and bool(draft.get("identity_bound"))
        and bool(draft.get("coverage_complete"))
        and bool(draft.get("unknown_card_ids"))
        and not draft.get("unseen_card_ids")
        and not draft.get("errors")
    )


def _scan_loaded_account(data: AccountsData, account_tag: object):
    """Return the selected linked profile without blocking on unrelated tags."""
    if data.problem is not None:
        return None
    wanted = _normalize_tag(account_tag)
    return next(
        (
            entry.account
            for entry in data.entries
            if _normalize_tag(entry.tag) == wanted
            and entry.status == STATUS_LOADED
            and entry.account is not None
        ),
        None,
    )


def _scan_expiry_text(usable_until: object = None) -> str:
    stamp = as_utc(usable_until)
    if stamp is None:
        return "for 20 minutes after upload"
    unix = int(stamp.timestamp())
    return f"until <t:{unix}:t> (<t:{unix}:R>)"


def _scan_privacy_text() -> str:
    return (
        "Discord receives the attachments. The bot reads them only for this private "
        "scan and does not retain the raw image files."
    )


def _scan_upload_prompt(
    account,
    session_id: str,
    *,
    usable_until: object,
) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# 📸 Send Your Card Screenshots"),
            Text(content=(
                f"## {_escape_markdown(account.name)} · `{_normalize_tag(account.tag)}`\n"
                "Open the full **Clash of Cards** collection, then send all of its "
                "screenshots **together in your next DM**.\n\n"
                "- Select every screenshot at once; **any order is fine**.\n"
                "- Show two complete rows of six cards in each image.\n"
                "- Five clean screenshots normally cover all 60 cards.\n\n"
                "I will sort them automatically and tell you exactly which rows are "
                "still needed."
            )),
            Separator(divider=True),
            Text(content=(
                f"This upload stays linked to **{_escape_markdown(account.name)}** "
                f"and is open {_scan_expiry_text(usable_until)}.\n\n"
                f"{_scan_privacy_text()}"
            )),
            ActionRow(components=[
                LinkButton(
                    url=COLLECTION_LINK,
                    label="Open collection",
                    emoji="🎮",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_upload_cancel:{session_id}",
                    label="Cancel upload",
                    emoji="✖️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_upload_started(account, *, usable_until: object) -> list[Container]:
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content="# 📸 Private Upload Ready"),
            Text(content=(
                f"I sent **{_escape_markdown(account.name)}** a private upload DM. "
                "Open it, select every collection screenshot at once, and send. "
                f"Any order is fine. The upload closes {_scan_expiry_text(usable_until)}."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                    label="Back to dashboard",
                    emoji="⬅️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_dm_unavailable(account) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# I Couldn't Open the Private Upload"),
            Text(content=(
                "Allow direct messages from members of the family Discord server, "
                "then tap **Try scan again**. The Advanced editor still works "
                "without DMs."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_scan_start:{_normalize_tag(account.tag)}",
                    label="Try scan again",
                    emoji="📸",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_advanced:{_normalize_tag(account.tag)}",
                    label="Advanced editor",
                    emoji="⚙️",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                    label="Dashboard",
                    emoji="⬅️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_missing_page_numbers(draft: object) -> list[int]:
    if not isinstance(draft, dict):
        return list(range(1, CARD_SCAN_CAPTURE_COUNT + 1))
    values = draft.get("missing_page_numbers")
    if values is None:
        return [] if draft.get("coverage_complete") else list(
            range(1, CARD_SCAN_CAPTURE_COUNT + 1)
        )
    try:
        parsed = {int(value) for value in values}
    except (TypeError, ValueError):
        return list(range(1, CARD_SCAN_CAPTURE_COUNT + 1))
    return sorted(
        value for value in parsed if 1 <= value <= CARD_SCAN_CAPTURE_COUNT
    )


def _scan_missing_rows_text(draft: object) -> str:
    raw_rows = draft.get("missing_global_rows") if isinstance(draft, dict) else None
    try:
        rows = sorted({int(value) for value in (raw_rows or ()) if 1 <= int(value) <= 10})
    except (TypeError, ValueError):
        rows = []
    if not rows:
        rows = [
            row
            for page in _scan_missing_page_numbers(draft)
            for row in (page * 2 - 1, page * 2)
        ]
    ranges: list[tuple[int, int]] = []
    for row in rows:
        if ranges and row == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], row)
        else:
            ranges.append((row, row))
    catalog = list(CARD_BY_ID.values())
    labels: list[str] = []
    for start, end in ranges:
        first_index = max(0, (start - 1) * 6)
        last_index = min(len(catalog) - 1, end * 6 - 1)
        row_label = f"Row {start}" if start == end else f"Rows {start}–{end}"
        if first_index <= last_index:
            labels.append(
                f"- **{row_label}:** {catalog[first_index].name} → "
                f"{catalog[last_index].name}"
            )
        else:
            labels.append(f"- **{row_label}**")
    return "\n".join(labels) or "- The unreadable collection rows"


def _scan_upload_progress(
    account,
    session_id: str,
    draft: dict,
    *,
    usable_until: object,
    accepted_before: int = 0,
) -> list[Container]:
    missing_pages = _scan_missing_page_numbers(draft)
    accepted = CARD_SCAN_CAPTURE_COUNT - len(missing_pages)
    gained = max(0, accepted - max(0, int(accepted_before)))
    if accepted:
        result = (
            f"✅ I matched **{accepted} of {CARD_SCAN_CAPTURE_COUNT}** collection "
            f"sections" + (f" (**+{gained}** this time)." if gained else ".")
        )
    else:
        result = (
            "I couldn't match a complete two-row collection section in those images."
        )
    issue_lines = _scan_capture_issue_lines(draft)
    issue_text = ""
    if issue_lines:
        issue_text = "\n\n" + "\n".join(issue_lines[:3])
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# 📸 I Still Need More of the Collection"),
            Text(content=(
                f"## {_escape_markdown(account.name)} · `{_normalize_tag(account.tag)}`\n"
                f"{result}\n\n"
                f"**Still needed:**\n{_scan_missing_rows_text(draft)}\n\n"
                "Send only those missing screenshots in this DM. You do **not** "
                "need to resend sections already accepted, and the order does not "
                f"matter.{issue_text}"
            )),
            Separator(divider=True),
            Text(content=(
                f"Upload open {_scan_expiry_text(usable_until)}. "
                "Keep two full six-card rows visible in each screenshot."
            )),
            ActionRow(components=[
                LinkButton(
                    url=COLLECTION_LINK,
                    label="Open collection",
                    emoji="🎮",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_upload_cancel:{session_id}",
                    label="Cancel upload",
                    emoji="✖️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_upload_problem(
    account,
    session_id: str,
    title: str,
    detail: str,
    *,
    usable_until: object,
) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"# {title}"),
            Text(content=(
                f"**{_escape_markdown(account.name)}** · "
                f"`{_normalize_tag(account.tag)}`\n\n{detail}"
            )),
            Separator(divider=True),
            Text(content=f"Upload open {_scan_expiry_text(usable_until)}."),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_upload_cancel:{session_id}",
                    label="Cancel upload",
                    emoji="✖️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_capture_issue_lines(draft: object) -> list[str]:
    if not isinstance(draft, dict):
        return []
    raw_issues = draft.get("capture_issues") or ()
    try:
        issues = list(raw_issues)
    except TypeError:
        return []
    translations = {
        "capture_requires_two_rows": "could not find exactly two complete card rows",
        "duplicate_capture_ignored": "repeats an already accepted section",
        "duplicate_page_ignored": "repeats an already accepted section",
        "overlapping_capture_rows": "overlaps rows already shown on another page",
        "unexpected_extra_capture": "is an unexpected extra capture",
        "capture_sequence_mismatch": "shows the wrong rows or is out of order",
        "artwork_identity_mismatch": "has card artwork that does not match the expected positions",
        "invalid_image_bytes": "could not be decoded as an image",
        "empty_image": "was empty",
        "encoded_image_too_large": "was too large to scan safely",
        "unsupported_image_format": "uses an unsupported image format",
        "animated_image_not_supported": "must be a still image",
        "image_dimensions_too_small": "is too small to read",
        "image_dimensions_too_large": "is too large to scan safely",
        "image_decode_failed": "could not be decoded",
        "invalid_or_corrupt_image": "was invalid or corrupt",
        "no_card_rows_detected": "did not contain readable card rows",
        "no_valid_rows": "did not contain two readable card rows",
        "no_valid_six_column_rows": "did not contain two complete six-card rows",
        "no_card_sized_components": "did not contain readable card portraits",
        "insufficient_card_slots": "did not show all six cards in both rows",
        "no_new_collection_pages": "did not add a new collection section",
    }
    lines: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        try:
            image_number = max(1, int(issue.get("image", issue.get("page", 1))))
        except (TypeError, ValueError):
            image_number = 1
        try:
            assigned_page = int(issue.get("assigned_page") or 0)
        except (TypeError, ValueError):
            assigned_page = 0
        codes = _scan_strings(issue.get("warnings"), limit=12)
        reasons: list[str] = []
        for code in codes:
            reason = translations.get(code)
            if reason and reason not in reasons:
                reasons.append(reason)
        mismatches = _ordered_card_ids(issue.get("mismatched_card_ids") or ())
        if mismatches:
            names = _scan_card_names(mismatches)
            detail = f"expected card check failed for {names}"
            if detail not in reasons:
                reasons.append(detail)
        if not reasons:
            reasons.append("could not be validated as the expected two rows")
        assignment = (
            f" (collection rows {assigned_page * 2 - 1}–{assigned_page * 2})"
            if 1 <= assigned_page <= CARD_SCAN_CAPTURE_COUNT
            else ""
        )
        lines.append(
            f"**Image {image_number}{assignment}:** {'; '.join(reasons)}. Retake it."
        )
    return lines


def _scan_session_problem(ctx, user_id: object, guild_id: object) -> list[Container] | None:
    try:
        owns_session = int(user_id) == int(ctx.user.id)
        session_guild = int(guild_id)
        configured_guild = int(_configured_cards_guild_id() or 0)
        context_guild = _guild_id(ctx)
        correct_guild = (
            session_guild == configured_guild
            and (context_guild is None or int(context_guild) == session_guild)
        )
    except (TypeError, ValueError):
        owns_session = correct_guild = False
    if owns_session and correct_guild:
        return None
    return _notice(
        "This screenshot draft is private",
        "Only the member who started it can use it. Begin a new scan from your "
        "own `/cards` dashboard in the family server.",
    )


async def _discard_scan_state(mongo: MongoClient, draft_id: str) -> None:
    try:
        await delete_state(mongo, draft_id)
    except Exception:
        # A TTL still removes the draft. Most importantly, a successful
        # inventory write must never look failed only because cleanup hiccupped.
        _log.exception("card screenshot draft cleanup failed draft=%s", draft_id)


def _scan_accounts_problem(
    data: AccountsData,
    draft_id: str,
    *,
    has_draft: bool,
    usable_until: object = None,
    account_tag: object = None,
) -> list[Container]:
    if data.problem == LINK_FAILURE:
        reason = "The account link service could not be reached."
    elif not data.entries:
        reason = "No Clash accounts are linked to this Discord member."
    elif account_tag:
        reason = (
            f"The selected player profile `{_normalize_tag(account_tag)}` did not load."
        )
    else:
        failed = data.error_count + data.not_found_count
        reason = (
            f"{failed} of {data.linked_count} linked player profile"
            f"{'s did' if failed != 1 else ' did'} not load."
        )
    preserved = (
        f"Your scan draft is still usable {_scan_expiry_text(usable_until)}."
        if has_draft
        else "Discord received the attachments; the bot did not read or retain them."
    )
    privacy = _scan_privacy_text() if has_draft else "No raw image files were retained."
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# 📸 Account Check Needed"),
            Text(content=(
                f"{reason} The selected profile must load before its screenshot "
                f"draft can be shown or saved. {preserved}\n\n{privacy}"
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_scan_accounts_retry:{draft_id}",
                    label="Retry account check",
                    emoji="🔄",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_scan_retry_cancel:{draft_id}",
                    label="Cancel",
                    emoji="✖️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _scan_card_names(card_ids: object) -> str:
    """Scan-review card names, each led by its troop art."""
    ordered = _ordered_card_ids(card_ids)
    if not ordered:
        return "None"
    parts = []
    for card_id in ordered:
        card = CARD_BY_ID[card_id]
        icon = troop_emoji.markup(card.id)
        parts.append(f"{icon} {card.name}" if icon else card.name)
    return ", ".join(parts)


def _scan_review(
    account,
    inventory: dict,
    draft_id: str,
    draft: dict,
    *,
    usable_until: object = None,
    rendered_board=None,
) -> list[Container]:
    states = draft.get("card_states") if isinstance(draft, dict) else {}
    states = states if isinstance(states, dict) else {}
    missing = [card_id for card_id, state in states.items() if state == MISSING]
    unknown = _ordered_card_ids(draft.get("unknown_card_ids") or ())
    unseen = _ordered_card_ids(draft.get("unseen_card_ids") or ())
    errors = _scan_strings(draft.get("errors"), limit=5)
    unverified_duplicates = _ordered_card_ids(
        draft.get("duplicate_unverified_card_ids") or ()
    )
    reserved = bool(_card_reservations(inventory))
    confirmable = _scan_draft_confirmable(draft) and not reserved
    correctable = _scan_draft_correctable(draft)
    capture_issue_lines = _scan_capture_issue_lines(draft)

    collected = len(states) - len(missing)
    details = []
    if unknown:
        details.append(
            f"**Needs review ({len(unknown)})**\n{_card_rows(unknown)}"
        )
    if unseen:
        details.append(f"**Not visible:** {len(unseen)} card positions")
    if capture_issue_lines and unseen:
        # Only ask for another image when card positions were never seen. A
        # capture that merely produced an uncertain card is resolvable in place,
        # and telling a member to retake it right after they answered every card
        # by hand contradicted the Save button sitting next to it.
        details.append(
            "**Send these pages again:**\n" + "\n".join(capture_issue_lines)
        )

    if errors:
        status = "**This scan cannot be saved.** The scanner could not read it."
    elif reserved:
        status = "**Finish or cancel the accepted card trade before saving this scan.**"
    elif correctable and not reserved:
        status = "**Fix the uncertain card below before saving.**"
    elif not confirmable:
        status = "**This scan needs another screenshot before it can be saved.**"
    else:
        status = "**All 60 cards were read.**"

    body: list = [
        Text(content="# Scan complete"),
        Text(content=(
            f"**{_escape_markdown(account.name)}** · `{_normalize_tag(account.tag)}`\n"
            f"**{collected} collected** · {len(missing)} missing\n"
            + (
                f"{len(unverified_duplicates)} cards still need a duplicate check.\n"
                if unverified_duplicates else ""
            )
            + "-# Nothing has been saved. The bot does not retain the image files. "
            f"This review is usable {_scan_expiry_text(usable_until)}."
        )),
        Separator(divider=True),
        Text(content=status),
    ]
    if details:
        body.append(Text(content="\n".join(details)))
    if correctable:
        next_card_id = unknown[0]
        body.extend([
            Separator(divider=True),
            Text(content=(
                f"## Correct next: {CARD_BY_ID[next_card_id].name}\n"
                f"{len(unknown)} uncertain card{'s' if len(unknown) != 1 else ''} remaining"
            )),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_scan_fix_missing:{draft_id}",
                    label="Missing",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_scan_fix_owned:{draft_id}",
                    label="Have 1",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_scan_fix_duplicate:{draft_id}",
                    label="Duplicate",
                ),
            ]),
        ])
    save_buttons = [
        Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_scan_confirm:{draft_id}",
            label="Save collection",
            is_disabled=not confirmable,
        ),
    ]
    if not confirmable:
        save_buttons.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_advanced:{_normalize_tag(account.tag)}",
            label="Advanced manual editor",
        ))
        body.append(Text(content=(
            "The Advanced editor starts from your saved collection; this scan "
            "result will not be copied into it."
        )))
    body.extend([
        Separator(divider=True),
        ActionRow(components=[
            *save_buttons,
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_scan_cancel:{draft_id}",
                label="Cancel",
            ),
        ]),
    ])
    return [Container(components=body)]


async def _owned_account(
    coc_client: coc.Client,
    discord_id: int,
    tag: str,
    *,
    force: bool = False,
):
    wanted = _normalize_tag(tag)
    data = await load_accounts(coc_client, int(discord_id), force=force)
    for entry in _loaded_entries(data):
        if _normalize_tag(entry.tag) == wanted:
            return entry.account, data
    return None, data


async def _ensure_inventory(
    mongo: MongoClient,
    account,
    *,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    now = datetime.now(timezone.utc)
    identity = {
        "discord_id": int(discord_id),
        "player_name": account.name,
        "clan_tag": _normalize_tag(account.clan_tag) if account.clan_tag else None,
        "clan_name": account.clan_name,
        "last_seen_at": now,
    }
    # Never erase an established family scope merely because an old component
    # is clicked from a context without a guild id.
    if guild_id is not None:
        identity["guild_id"] = guild_id
    await mongo.card_inventories.update_one(
        {"_id": _normalize_tag(account.tag)},
        {
            "$set": identity,
            "$setOnInsert": {
                "cards": {},
                "complete_categories": [],
                "reviewed_lists": [],
                "inventory_revision": 0,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return await mongo.card_inventories.find_one({"_id": _normalize_tag(account.tag)}) or {}


async def _load_target(
    ctx,
    tag: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> tuple[object | None, dict | None, list[Container] | None]:
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return None, None, _notice("Open Card Hub in its family server", scope_error)
    account, _data = await _owned_account(coc_client, int(ctx.user.id), tag)
    if account is None:
        data = _data
        wanted = _normalize_tag(tag)
        if data.problem == LINK_FAILURE:
            return None, None, _notice(
                "Couldn't reach the account link service",
                "I could not re-check ownership, so nothing was shown or changed. "
                "This is a service problem, not an unlink—try again shortly.",
            )
        entry = next(
            (item for item in data.entries if _normalize_tag(item.tag) == wanted),
            None,
        )
        if entry is not None and entry.status == STATUS_ERROR:
            return None, None, _notice(
                "That player profile could not be loaded",
                "The account is still linked, but Clash did not return its profile "
                "this time. Nothing was changed—please try again shortly.",
            )
        if entry is not None and entry.status == STATUS_NOT_FOUND:
            return None, None, _notice(
                "That linked player tag was not found",
                "The tag is still in your link list but no current Clash profile "
                "was returned. Check the link, then re-run `/cards`.",
            )
        return None, None, _notice(
            "That account is no longer linked to you",
            "For safety, card collections can only be changed from the Discord "
            "account currently linked to that player tag. Re-run `/cards` to "
            "choose one of your current accounts.",
        )
    inventory = await _ensure_inventory(
        mongo,
        account,
        discord_id=int(ctx.user.id),
        guild_id=_guild_id(ctx),
    )
    return account, inventory, None


def _scan_unverified_ids(inventory: dict) -> list[str]:
    values = inventory.get("scan_duplicate_unverified_card_ids") or ()
    parsed, _invalid = _scan_id_set(values)
    return _ordered_card_ids(parsed)


def _card_board_media(
    values: dict,
    *,
    player_name: object,
    rendered_board=None,
) -> Media:
    board = rendered_board or render_inventory_card_board(
        values, player_name=str(player_name or "Player")
    )
    return Media(items=[MediaItem(
        media=hikari.Bytes(board.png_bytes, board.filename, "image/png"),
        description=board.alt_text,
    )])


def _confirmed_count_ids(inventory: dict) -> set[str]:
    raw = inventory.get("count_confirmed_card_ids") or ()
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(value) for value in raw if str(value) in CARD_BY_ID}


def _inventory_board_values(inventory: dict) -> dict:
    values: dict = normalize_cards(inventory.get("cards"))
    confirmed = _confirmed_count_ids(inventory)
    for card_id, state in list(values.items()):
        # Exactly two, and the member never said so: the scanner proved a spare
        # exists but not how many, so this reads "x2+" rather than "x2".
        if state == DUPLICATE and card_id not in confirmed:
            values[card_id] = SPARE_FLOOR
    for card_id in _scan_unverified_ids(inventory):
        values[card_id] = "owned_spare_unverified"
    return values


def _inventory_board_media(account, inventory: dict, *, rendered_board=None) -> Media:
    return _card_board_media(
        _inventory_board_values(inventory),
        player_name=account.name,
        rendered_board=rendered_board,
    )


def _scan_board_values(draft: dict) -> dict:
    values: dict = {card.id: "unknown" for card in CARDS}
    raw_states = draft.get("card_states") if isinstance(draft, dict) else {}
    if isinstance(raw_states, dict):
        for card_id, state in raw_states.items():
            if card_id in CARD_BY_ID:
                values[card_id] = state
    for field in ("unknown_card_ids", "unseen_card_ids"):
        for card_id in _ordered_card_ids(draft.get(field) or ()):
            values[card_id] = "unknown"
    for card_id in _ordered_card_ids(
        draft.get("duplicate_unverified_card_ids") or ()
    ):
        values[card_id] = "owned_spare_unverified"
    return values


async def _render_inventory_board_async(account, inventory: dict):
    return await asyncio.to_thread(
        render_inventory_card_board,
        _inventory_board_values(inventory),
        player_name=str(account.name or "Player"),
    )


def _dashboard(
    account,
    inventory: dict,
    *,
    account_count: int,
    rendered_board=None,
) -> list[Container]:
    tag = _normalize_tag(account.tag)
    complete = set(inventory.get("complete_categories") or ()) & set(CATEGORY_BY_ID)
    summary = inventory_summary(inventory.get("cards"), complete)
    all_complete = len(complete) == len(CATEGORIES)
    reserved_count = len(_card_reservations(inventory))
    unverified_duplicates = _scan_unverified_ids(inventory)
    stamp = inventory.get("confirmed_at") or inventory.get("updated_at")
    age = freshness_label(stamp)
    recorded = bool(normalize_cards(inventory.get("cards")))

    if summary.known:
        headline = (
            f"**{summary.collected} of {summary.known} collected** · "
            f"{summary.missing} missing · "
            f"{summary.duplicates} spare{'s' if summary.duplicates != 1 else ''}"
        )
    elif recorded:
        headline = "Review a category to make these cards tradeable"
    else:
        headline = "Nothing recorded yet"

    # The board is the landing screen. It renders unknown states too, so a
    # member who has entered nothing still sees the collection greyed out and
    # can read the goal before doing anything.
    body: list = [
        Text(content="# Clash of Cards"),
        _inventory_board_media(account, inventory, rendered_board=rendered_board),
        # One summary line, not four. The board image already draws a counted
        # pill per category, so the progress bars that used to sit here said
        # the same thing a second time, the headline a third, and the menu
        # labels a fourth. Repeating one fact in four visual languages is what
        # made the panel read as assembled rather than designed.
        Text(content=(
            f"**{_escape_markdown(account.name)}** · `{tag}` · "
            f"{headline} · updated {_relative_timestamp(stamp)}"
        )),
    ]

    notes = []
    if unverified_duplicates:
        notes.append(
            f"**{len(unverified_duplicates)} card"
            f"{'s need' if len(unverified_duplicates) != 1 else ' needs'} "
            "a duplicate check.** They read *Might be a spare* in the menus."
        )
    if reserved_count:
        notes.append(
            f"{reserved_count} card{'s are' if reserved_count != 1 else ' is'} "
            "reserved by accepted trades."
        )
    if notes:
        body.extend([
            Separator(divider=True),
            Text(content="\n".join(notes)),
        ])

    # Four menus, one per category, every card one interaction away. The label
    # and the controls that act on them sit either side of the menus, so Sort
    # is visibly attached to the thing it sorts rather than stranded under an
    # unrelated heading.
    sort = _inventory_sort(inventory)
    body.extend([
        Separator(divider=True),
        Text(content="**Your cards** · tap one to change how many you have"),
    ])
    body.extend(
        _category_select_row(account, inventory, category.id, sort)
        for category in CATEGORIES
    )

    scan_is_primary = not all_complete
    matchable = inventory_is_matchable(inventory)
    spare_total = sum(
        1 for value in normalize_cards(inventory.get("cards")).values()
        if value >= DUPLICATE
    )
    # Each destination is its own labelled row with its own button, rather than
    # a bar of buttons whose labels have to carry all the meaning. A row can
    # say what it is and what is waiting there, which a button cannot.
    destinations = [
        (
            "🔁", "Find trades",
            # Short blurbs on purpose. Matching cuts off at 72 hours, so the
            # unavailable case is staleness, not an unfinished collection.
            f"{summary.missing} needed" if matchable else "collection is stale",
            f"cards_matches:{tag}",
            hikari.ButtonStyle.PRIMARY if matchable else hikari.ButtonStyle.SECONDARY,
            matchable,
        ),
        (
            "📬", "My trades",
            "sent and received",
            f"cards_trades:{tag}",
            hikari.ButtonStyle.SECONDARY,
            True,
        ),
    ]
    # The controls that act on the menus above, immediately below them.
    collection_row: list = [
        Button(
            style=(
                hikari.ButtonStyle.PRIMARY
                if scan_is_primary
                else hikari.ButtonStyle.SECONDARY
            ),
            custom_id=f"cards_scan_start:{tag}",
            label="Scan screenshots",
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_sort:{tag}",
            label=CARD_SORT_LABELS[sort],
        ),
    ]
    if unverified_duplicates:
        # The note above already says these need checking. Until now the only
        # button that acted on it lived on a screen the board could not reach,
        # so the note was advice with nowhere to go.
        collection_row.append(Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_hidden:{tag}",
            label=f"Check spares ({len(unverified_duplicates)})",
        ))
    if not all_complete:
        collection_row.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_advanced:{tag}",
            label="Bulk edit",
        ))
    if complete and age != "fresh":
        collection_row.append(Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=f"cards_confirm:{tag}",
            label="Still accurate",
        ))
    if account_count > 1:
        collection_row.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id="cards_account_page:0",
            label="Switch account",
        ))
    # Wrap rather than slice. Discord takes five buttons to a row, and the
    # previous [:5] quietly dropped the sixth: a member with an unfinished
    # collection, a stale confirmation and several accounts lost a control
    # without anything saying so.
    for index in range(0, len(collection_row), 5):
        body.append(ActionRow(components=collection_row[index:index + 5]))

    body.append(Separator(divider=True))
    for icon, title, blurb, custom_id, style, enabled in destinations:
        # One short line, not a heading plus a subtext line plus a divider.
        # Discord's mobile client drops a Section accessory BELOW its text when
        # the text block is tall, so every extra line here is what made the
        # panel scroll. A single line keeps the button beside it far more often,
        # and costs a third of the height when it still wraps.
        body.append(Section(
            components=[Text(content=f"**{icon} {title}** · {blurb}")],
            accessory=Button(
                style=style,
                custom_id=custom_id,
                label="Open",
                is_disabled=not enabled,
            ),
        ))
    body.extend([
        Separator(divider=True),
    ])

    # Link buttons rather than three lines of trailing subtext. As buttons they
    # read as somewhere to go; as small print under everything else they read
    # as leftovers nobody placed on purpose.
    body.append(ActionRow(components=[
        LinkButton(url=COLLECTION_LINK, label="Open in game"),
        LinkButton(url=GLOBAL_CHAT_LINK, label="Global Card Chat"),
    ]))
    if age != "fresh":
        body.append(Text(content=(
            f"-# {age.title()} · confirm above to keep matching."
        )))
    return [Container(components=body)]


def _is_spare_state(state: object) -> bool:
    """Whether a state is a tradeable spare, safely across ints and markers."""
    return (
        isinstance(state, int)
        and not isinstance(state, bool)
        and state >= DUPLICATE
    )


def _card_state_words(
    state: int | str,
    *,
    possible_spare: bool,
    unconfirmed: bool = False,
) -> str:
    if possible_spare:
        return "Might be a spare"
    if state == MISSING:
        return "Missing"
    if unconfirmed:
        # The scanner proved a spare exists but not how many.
        return "2 or more · tell me the exact number"
    if isinstance(state, int) and state >= DUPLICATE:
        return f"{state} copies · {state - 1} to trade"
    return "Have 1"


CARD_SORTS = ("game", "need", "have")
CARD_SORT_LABELS = {
    "game": "Game order",
    "need": "Missing first",
    "have": "Most copies first",
}


def _inventory_sort(inventory: dict) -> str:
    """Which order the member last chose for the card menus."""
    value = str(inventory.get("card_sort") or "game")
    return value if value in CARD_SORTS else "game"


def _next_sort(current: str) -> str:
    return CARD_SORTS[(CARD_SORTS.index(current) + 1) % len(CARD_SORTS)]


def _sorted_category_cards(inventory: dict, category_id: str, sort: str):
    """Category cards in the member's chosen order.

    Game order matches the rendered board, so a member reading the picture can
    find the same card in the menu. The other two put whatever they are about
    to act on at the top: missing cards to chase, or the biggest piles to trade
    away. Ties keep game order so the list never reshuffles between renders.
    """
    cards_in_category = CATEGORY_CARDS[category_id]
    if sort == "game":
        return cards_in_category
    saved = normalize_cards(inventory.get("cards"))
    reverse = sort == "have"
    return sorted(
        cards_in_category,
        key=lambda card: (
            -saved.get(card.id, OWNED) if reverse else saved.get(card.id, OWNED),
            card.position,
        ),
    )


def _category_select_row(
    account,
    inventory: dict,
    category_id: str,
    sort: str = "game",
) -> ActionRow:
    """One menu per category, so every card is one interaction from the board.

    Each category fits inside Discord's 25-option limit, which is what lets all
    sixty cards be reachable without pagination or a hidden category mode.
    """
    tag = _normalize_tag(account.tag)
    category = CATEGORY_BY_ID[category_id]
    summary = category_summary(inventory.get("cards"), category_id)
    saved = normalize_cards(inventory.get("cards"))
    possible = set(_scan_unverified_ids(inventory))
    confirmed = _confirmed_count_ids(inventory)
    options = []
    for card in _sorted_category_cards(inventory, category_id, sort):
        state = saved.get(card.id, OWNED)
        options.append(SelectOption(
            label=card.name,
            value=card.id,
            description=_card_state_words(
                state,
                possible_spare=card.id in possible,
                unconfirmed=(
                    state == DUPLICATE and card.id not in confirmed
                ),
            ),
            # The troop's own art, so the menu reads as cards rather than a
            # list of words. Falls back to no emoji when a troop has not been
            # synced; partial() returns UNDEFINED rather than raising.
            emoji=troop_emoji.partial(card.id),
        ))
    placeholder = f"{category.name} · {summary.collected}/{summary.known}"
    if summary.collected == summary.known:
        placeholder += " complete"
    elif summary.missing:
        placeholder += f" · {summary.missing} missing"
    return ActionRow(components=[TextSelectMenu(
        custom_id=f"cards_pick:{tag}|{category_id}",
        placeholder=placeholder[:150],
        max_values=1,
        options=options,
    )])


def _spare_counts_panel(account, inventory: dict) -> list[Container] | None:
    """After a scan, ask how many of each spare the member actually holds.

    The scanner can prove a spare exists but not how many, so every spare it
    finds is stored as the floor of two. This is the one moment a member has
    the game open next to Discord, which makes it the cheapest possible time to
    ask. Returns None when there is nothing to ask about, so the caller falls
    straight through to the dashboard.
    """
    tag = _normalize_tag(account.tag)
    saved = normalize_cards(inventory.get("cards"))
    confirmed = _confirmed_count_ids(inventory)
    spares = [
        card for card in CARDS
        if saved.get(card.id, OWNED) == DUPLICATE and card.id not in confirmed
    ]
    if not spares:
        return None

    shown = spares[:25]
    body: list = [
        Text(content="# How many spares?"),
        Text(content=(
            f"Your collection is saved. **{len(spares)} card"
            f"{'s' if len(spares) != 1 else ''}** came back as a spare, "
            "recorded as **2+** because a badge proves you have one to trade "
            "but not how many.\n"
            "Pick any card to set its real count, or skip this entirely - "
            "trading works fine on 2+."
        )),
        ActionRow(components=[TextSelectMenu(
            # cards_pick reads the chosen card id from the menu values and only
            # needs the tag from its custom_id.
            custom_id=f"cards_pick:{tag}|spares",
            placeholder="Set an exact count..."[:150],
            max_values=1,
            options=[
                SelectOption(
                    label=card.name,
                    value=card.id,
                    description=f"{CATEGORY_BY_ID[card.category].short_name} · 2+",
                )
                for card in shown
            ],
        )]),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_dashboard:{tag}",
            label="Skip, 2+ is fine",
        )]),
    ]
    if len(spares) > len(shown):
        body.append(Text(content=(
            f"-# {len(spares) - len(shown)} more are in the category menus "
            "on the board."
        )))
    return [Container(components=body)]


def _card_focus(
    account,
    inventory: dict,
    card_id: str,
    *,
    saved: str | None = None,
    rendered_tile: object = None,
    rendered_strip: object = None,
) -> list[Container]:
    """One card, its category at a legible size, and three state buttons."""
    card = CARD_BY_ID.get(card_id) or CARDS[0]
    tag = _normalize_tag(account.tag)
    category = CATEGORY_BY_ID[card.category]
    state = normalize_cards(inventory.get("cards")).get(card.id, OWNED)
    possible_spare = card.id in set(_scan_unverified_ids(inventory))
    reserved = card.id in _card_reservations(inventory)
    tile = rendered_tile or render_card_thumbnail(
        card.id,
        OWNED_SPARE_UNVERIFIED if possible_spare else state,
    )

    unconfirmed = (
        _is_spare_state(state)
        and state == DUPLICATE
        and card.id not in _confirmed_count_ids(inventory)
    )
    detail = _card_state_words(
        state, possible_spare=possible_spare, unconfirmed=unconfirmed
    )
    if reserved:
        detail = "Reserved by an accepted trade"

    body: list = [
        Text(content=f"## {_escape_markdown(card.name)}"),
    ]
    if rendered_strip is not None:
        # One category is scaled down far less than the sixty-card board, so
        # this is where the artwork is actually legible.
        body.append(Media(items=[MediaItem(
            media=hikari.Bytes(
                rendered_strip.png_bytes, rendered_strip.filename, "image/png"
            ),
            description=rendered_strip.alt_text,
        )]))
    body.extend([
        Section(
            components=[
                Text(content=(
                    f"**{category.name}**\n"
                    f"{detail}"
                    + (f"\n-# {_escape_markdown(saved, limit=180)}" if saved else "")
                )),
            ],
            accessory=Thumbnail(
                media=hikari.Bytes(tile.png_bytes, tile.filename, "image/png"),
                description=tile.alt_text,
            ),
        ),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.SUCCESS
                    if state == MISSING and not possible_spare
                    else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_set:{tag}|{card.id}|0",
                label="None",
                is_disabled=reserved,
            ),
            Button(
                style=(
                    hikari.ButtonStyle.SUCCESS
                    if state == OWNED and not possible_spare
                    else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_set:{tag}|{card.id}|1",
                label="Have 1",
                is_disabled=reserved,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{tag}",
                label="Back to board",
            ),
        ]),
        # "Spare, 2+" used to sit above. It was redundant with +1 and could not
        # express "exactly two", which is the common case: pressing it left the
        # badge reading 2+ forever.
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_step:{tag}|{card.id}|-1",
                label="-1",
                is_disabled=reserved or not isinstance(state, int) or state <= MISSING,
            ),
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"cards_step:{tag}|{card.id}|1",
                label="+1",
                is_disabled=reserved or (
                    isinstance(state, int) and state >= MAX_COPIES
                ),
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_count:{tag}|{card.id}",
                label="Type a number",
                is_disabled=reserved,
            ),
            # Only rendered for an unconfirmed scanned spare, where the count is
            # necessarily 2. Rendering it otherwise would repeat the custom_id
            # of the None or Have 1 button, and Discord rejects a message that
            # carries the same custom_id twice.
            *(
                [Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"cards_set:{tag}|{card.id}|{DUPLICATE}",
                    label="Exactly 2",
                    is_disabled=reserved,
                )]
                if unconfirmed
                else []
            ),
        ]),
        # The menu stays mounted, so fixing several cards in one category is
        # pick, tap, pick, tap without returning to the board between them.
        _category_select_row(
            account, inventory, card.category, _inventory_sort(inventory)
        ),
    ])
    return [Container(
        accent_color=CATEGORY_ACCENTS[card.category],
        components=body,
    )]


def _state_name(value: int) -> str:
    if value == MISSING:
        return "missing"
    if value == OWNED:
        return "1 copy"
    if isinstance(value, int) and value >= DUPLICATE:
        return f"{value} copies"
    return "unknown"


def _saved_count_line(card_name: str, count: int) -> str:
    """What the member is told after changing a card.

    Says what they hold and what that means for trading, in that order. The
    earlier phrasing, "Balloon is now a spare (2+)", named an internal state
    rather than answering the only question a member has: how many do I have,
    and can I give one away.
    """
    if count <= MISSING:
        return f"You have no {card_name}."
    if count == OWNED:
        return f"You have 1 {card_name}, none to spare."
    spare = count - 1
    return (
        f"You have {count} {card_name} · "
        f"{spare} spare {'copies' if spare != 1 else 'copy'} to trade."
    )


def _quick_transition_problem(inventory: dict, card_id: str, mode: str) -> str | None:
    action = QUICK_CARD_ACTIONS.get(mode)
    card = CARD_BY_ID.get(card_id)
    if action is None or card is None:
        return "That change is no longer available."
    current = normalize_cards(inventory.get("cards")).get(card_id, OWNED)
    desired = int(action["to"])
    required = action["from"]
    # A spare is any count at or above DUPLICATE, so both the "already there"
    # test and the precondition treat it as a threshold. Comparing for equality
    # rejected every member holding more than two.
    if required == DUPLICATE:
        if current < DUPLICATE:
            return (
                f"{card.name} is currently marked {_state_name(current)}, so "
                f"**{action['short_label']}** does not fit."
            )
        return None
    if desired == DUPLICATE and current >= DUPLICATE:
        return f"{card.name} is already marked {_state_name(current)}."
    if current == desired:
        return f"{card.name} is already marked {_state_name(desired)}."
    if required is not None and current != required:
        return (
            f"{card.name} is currently marked {_state_name(current)}, so "
            f"**{action['short_label']}** does not fit."
        )
    return None


def _hidden_badge_review(
    account,
    inventory: dict,
    *,
    session_id: str | None = None,
    rendered_board=None,
) -> list[Container]:
    pending = _scan_unverified_ids(inventory)
    if not pending:
        return _notice(
            "Possible spares checked",
            "The hidden duplicate-badge review is complete.",
        )
    tag = _normalize_tag(account.tag)
    batch = pending[:HIDDEN_BADGE_BATCH_SIZE]
    if len(batch) > 1:
        # Ask once for the whole batch instead of once per card. These are
        # cards whose badge sat under the reward track, which happens to a
        # whole row at a time, so a member was answering the same question six
        # or seven times in a row.
        return [Container(components=[
            Text(content="# Which of these do you have spares of?"),
            Text(content=(
                f"The reward bar covered the corner of **{len(batch)} cards**, "
                "so the scan could not read their spare badges.\n"
                "Tick every one you hold **2 or more** of. Anything you leave "
                "unticked is saved as a single copy."
            )),
            Separator(divider=True),
            ActionRow(components=[TextSelectMenu(
                custom_id=f"cards_hidden_pick:{tag}",
                placeholder="Choose every card you have a spare of...",
                min_values=0,
                max_values=len(batch),
                options=[
                    SelectOption(
                        label=CARD_BY_ID[card_id].name,
                        value=card_id,
                        description=CATEGORY_BY_ID[
                            CARD_BY_ID[card_id].category
                        ].short_name,
                        emoji=troop_emoji.partial(card_id),
                    )
                    for card_id in batch
                ],
            )]),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_hidden_none_of_these:{tag}",
                    label="None of them",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}",
                    label="Later",
                ),
            ]),
        ])]

    card = CARD_BY_ID[pending[0]]
    state_bound = session_id is not None
    no_id = (
        f"cards_scan_hidden_no:{session_id}"
        if state_bound
        else f"cards_editor_keep:{tag}|{card.id}"
    )
    yes_id = (
        f"cards_scan_hidden_yes:{session_id}"
        if state_bound
        else f"cards_editor_inc:{tag}|{card.id}"
    )
    missing_id = (
        f"cards_scan_hidden_missing:{session_id}"
        if state_bound
        else f"cards_editor_dec:{tag}|{card.id}"
    )
    return [Container(components=[
        Text(content=(
            f"# Check possible spare\n"
            f"**{len(pending)} remaining**"
        )),
        Section(
            components=[Text(content=(
                f"## {card.name}\n"
                "Does Clash show **×2 or more** for this card?"
            ))],
            accessory=Thumbnail(
                media=str(CARD_ARTWORK_DIR / f"{card.id}.webp"),
                description=f"{card.name} — possible spare check",
            ),
        ),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=missing_id,
                label="Missing — have 0",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=no_id,
                label="No — have 1",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=yes_id,
                label="Yes — spare",
            ),
        ]),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_scan_hidden_later:{session_id}"
                    if state_bound
                    else f"cards_dashboard:{tag}"
                ),
                label="Finish later",
            ),
        ]),
    ])]


def _scan_saved_notice(account, *, pending: int = 0) -> list[Container]:
    detail = f" {pending} possible spare{'s' if pending != 1 else ''} can be checked later." if pending else ""
    return _notice(
        "Collection Saved",
        f"**{_escape_markdown(account.name)}** is updated.{detail} Run `/cards` "
        "in the family server to open the dashboard.",
    )


def _update_overview(account, inventory: dict) -> list[Container]:
    complete = set(inventory.get("complete_categories") or ())
    reviewed = set(inventory.get("reviewed_lists") or ())
    unverified = set(_scan_unverified_ids(inventory))
    buttons = []
    for category in CATEGORIES:
        reserved = _category_has_reservations(inventory, category.id)
        if category.id in complete:
            summary = category_summary(inventory.get("cards"), category.id)
            label = (
                f"{category.short_name} reserved"
                if reserved
                else f"{category.short_name} {summary.collected}/{summary.known}"
            )
        elif any(step.startswith(f"{category.id}:") for step in reviewed):
            label = f"Continue {category.short_name}"
        else:
            label = f"Set up {category.short_name}"
        buttons.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_category:{_normalize_tag(account.tag)}|{category.id}",
            label=label,
            emoji=category_partial(category.id),
            is_disabled=reserved,
        ))

    intro = (
        f"**{_escape_markdown(account.name)}** · `{_normalize_tag(account.tag)}`\n\n"
        "Use this only for first-time manual setup or a full category rebuild. "
        "For normal changes, pick the card from a category menu on the board."
    )
    if unverified:
        intro += (
            f"\n\n📸 **{len(unverified)} possible spare"
            f"{'s' if len(unverified) != 1 else ''} still need review.** "
            "**Check spares** on the board handles them one at a time."
        )
    return [Container(
        components=[
            Text(content="# Advanced manual editor"),
            Text(content=intro),
            Separator(divider=True),
            ActionRow(components=buttons),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                    label="Back",
                ),
            ]),
        ],
    )]


def _category_editor(account, inventory: dict, category_id: str) -> list[Container]:
    category = CATEGORY_BY_ID[category_id]
    cards = normalize_cards(inventory.get("cards"))
    complete = category_id in set(inventory.get("complete_categories") or ())
    reviewed = set(inventory.get("reviewed_lists") or ())
    missing_reviewed = f"{category_id}:missing" in reviewed
    duplicates_reviewed = f"{category_id}:duplicates" in reviewed
    definitions = CATEGORY_CARDS[category_id]
    unverified_duplicates = [
        card.id
        for card in definitions
        if card.id in set(_scan_unverified_ids(inventory))
    ]

    missing_empty = not any(cards.get(card.id, OWNED) == MISSING for card in definitions)
    duplicates_empty = not any(cards.get(card.id, OWNED) >= DUPLICATE for card in definitions)
    missing_options = [
        SelectOption(
            label=card.name,
            value=card.id,
            is_default=cards.get(card.id, OWNED) == MISSING,
        )
        for card in definitions
    ]
    duplicate_options = [
        SelectOption(
            label=card.name,
            value=card.id,
            is_default=cards.get(card.id, OWNED) >= DUPLICATE,
        )
        for card in definitions
    ]
    summary = category_summary(cards, category_id) if complete else None
    if complete:
        setup_status = "✅ Both lists reviewed"
    elif missing_reviewed:
        setup_status = "✅ Missing saved · **review duplicates to finish**"
    elif duplicates_reviewed:
        setup_status = "✅ Duplicates saved · **review missing cards to finish**"
    else:
        setup_status = "Review both lists to finish this category"
    status = (
        f"{summary.collected}/{summary.known} owned · {summary.missing} missing · "
        f"{summary.duplicates} duplicate{'s' if summary.duplicates != 1 else ''}"
        if summary is not None
        else "Not set up yet"
    )

    body: list = [
        Text(content=f"# {category_markup(category.id)} {category.name}"),
        Text(content=(
            f"**{_escape_markdown(account.name)}** · `{_normalize_tag(account.tag)}`\n"
            f"{status}\n{setup_status}\n\n"
            "Select every card that applies in each list. Unselected cards are "
            "treated as **1 copy**. You can return here after a pack or trade "
            "and change only the affected list."
        )),
        Separator(divider=True),
        Text(content="## Missing cards"),
        ActionRow(components=[
            TextSelectMenu(
                custom_id=f"cards_set_missing:{_normalize_tag(account.tag)}|{category_id}",
                placeholder="Select all cards you do not have...",
                min_values=1,
                max_values=len(missing_options),
                options=missing_options,
            )
        ]),
        Text(content=(
            "## Cards with a duplicate"
            + (
                f"\n📸 Check the duplicate badges for: "
                f"**{_scan_card_names(unverified_duplicates)}**. They are currently "
                "saved as 1 copy; submit this duplicate list after checking."
                if unverified_duplicates
                else ""
            )
        )),
        ActionRow(components=[
            TextSelectMenu(
                custom_id=f"cards_set_duplicates:{_normalize_tag(account.tag)}|{category_id}",
                placeholder="Select all cards with at least one spare...",
                min_values=1,
                max_values=len(duplicate_options),
                options=duplicate_options,
            )
        ]),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.SUCCESS
                    if (complete or missing_reviewed) and missing_empty
                    else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_clear_missing:{_normalize_tag(account.tag)}|{category_id}",
                label="No missing cards",
                emoji="✅",
            ),
            Button(
                style=(
                    hikari.ButtonStyle.SUCCESS
                    if (complete or duplicates_reviewed) and duplicates_empty
                    else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_clear_duplicates:{_normalize_tag(account.tag)}|{category_id}",
                label="No duplicate cards",
                emoji="✅",
            ),
        ]),
        Separator(divider=True),
    ]
    action_buttons = [
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_advanced:{_normalize_tag(account.tag)}",
            label="All categories",
            emoji="⬅️",
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
            label="Done",
            emoji="✅",
        ),
    ]
    if not complete and not missing_reviewed and not duplicates_reviewed:
        action_buttons.insert(0, Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_baseline:{_normalize_tag(account.tag)}|{category_id}",
            label="No missing or spares",
            emoji="1️⃣",
        ))
    body.extend([
        ActionRow(components=action_buttons),
        Text(content="-# 2+ copies are stored simply as “duplicate”; exact counts are not required."),
        Media(items=[MediaItem(media=FOOTER)]),
    ])
    return [Container(accent_color=RED_ACCENT, components=body)]


async def _dashboard_view(account, inventory: dict, *, account_count: int):
    board = await _render_inventory_board_async(account, inventory)
    return _dashboard(
        account,
        inventory,
        account_count=account_count,
        rendered_board=board,
    )


async def _card_focus_view(
    account,
    inventory: dict,
    card_id: str,
    *,
    saved: str | None = None,
):
    possible_spare = card_id in set(_scan_unverified_ids(inventory))
    state = normalize_cards(inventory.get("cards")).get(card_id, OWNED)
    card = CARD_BY_ID.get(card_id) or CARDS[0]
    if possible_spare:
        tile_state: object = OWNED_SPARE_UNVERIFIED
    elif state == DUPLICATE and card_id not in _confirmed_count_ids(inventory):
        # Same "at least two" the board shows, so the tile and the strip beside
        # it never disagree.
        tile_state = SPARE_FLOOR
    else:
        tile_state = state
    tile = await asyncio.to_thread(
        render_card_thumbnail,
        card_id,
        tile_state,
    )
    strip = await asyncio.to_thread(
        render_category_strip,
        card.category,
        _inventory_board_values(inventory),
        highlight_card_id=card.id,
    )
    return _card_focus(
        account,
        inventory,
        card_id,
        saved=saved,
        rendered_tile=tile,
        rendered_strip=strip,
    )


async def _card_editor_view(
    account,
    inventory: dict,
    card_id: str,
    *,
    saved: str | None = None,
):
    """Every path that lands on one card lands on the focused card screen.

    This used to open the four-per-page category browser, which meant a scan
    correction or a duplicate check arrived inside a paginated grid with three
    controls per card. The focused screen shows the one card that is actually
    in question with three absolute state buttons.
    """
    return await _card_focus_view(account, inventory, card_id, saved=saved)


async def _scan_review_view(
    account,
    inventory: dict,
    draft_id: str,
    draft: dict,
    *,
    usable_until: object = None,
):
    return _scan_review(
        account,
        inventory,
        draft_id,
        draft,
        usable_until=usable_until,
    )


async def _hidden_badge_review_view(
    account,
    inventory: dict,
    *,
    session_id: str | None = None,
):
    if session_id is None:
        pending = _scan_unverified_ids(inventory)
        return (
            await _card_editor_view(account, inventory, pending[0])
            if pending
            else _notice("Duplicate checks complete", "No cards still need review.")
        )
    return _hidden_badge_review(
        account,
        inventory,
        session_id=session_id,
    )


async def _candidate_inventories(
    mongo: MongoClient,
    requester: dict,
    *,
    guild_id: int | None,
) -> list[dict]:
    if guild_id is None:
        return []
    now = datetime.now(timezone.utc)
    query: dict = {
        "confirmed_at": {"$gte": now - MATCHABLE_FOR},
        "guild_id": guild_id,
    }

    # Current family-clan membership is an additional safety boundary.  If the
    # clan database is temporarily unavailable/empty, guild scoping still keeps
    # results inside the Discord community using this panel.
    try:
        family_tags = [
            _normalize_tag(tag)
            for tag in await mongo.clans.distinct("tag")
            if _normalize_tag(tag)
        ]
    except Exception:
        _log.exception("card matching could not load family clan tags")
        return []
    if not family_tags:
        _log.warning("card matching disabled because no family clan tags are configured")
        return []
    query["clan_tag"] = {"$in": family_tags}

    documents = await mongo.card_inventories.find(query).to_list(length=2_000)
    requester_tag = _normalize_tag(requester.get("_id"))
    return [
        _without_reserved_cards(document)
        for document in documents
        if _normalize_tag(document.get("_id")) != requester_tag
    ]


def _match_line(match, ordinal: int) -> str:
    mention = f"<@{match.holder_discord_id}>" if match.holder_discord_id else "Discord member"
    location = _escape_markdown(match.holder_clan_name or "No clan", limit=50)
    same_clan = " · **same clan**" if match.same_clan else ""
    exchange_lines: list[str] = []
    for exchange in match.exchanges:
        category = CATEGORY_BY_ID[exchange.category]
        block = [f"{category_markup(category.id)} **{category.short_name}**"]
        block.append("**They can give you**")
        block.append(_card_rows(exchange.offers))
        if exchange.returns:
            block.append("**You can give back**")
            block.append(_card_rows(exchange.returns))
        else:
            block.append("-# Nothing of yours matches. Ask if they will help anyway.")
        exchange_lines.append("\n".join(block))
    exchange = "\n".join(exchange_lines)
    icon = "🔁" if match.reciprocal else "🎁"
    return (
        f"{icon} **{ordinal}. {_escape_markdown(match.holder_name, limit=50)}** · "
        f"{mention} · `{match.holder_tag}`\n"
        f"{exchange}\n"
        f"{location}{same_clan} · confirmed {_relative_timestamp(match.confirmed_at)}"
    )


def _offers_by_card(matches: list) -> dict[str, dict]:
    """Invert holder-shaped matches into card-shaped ones.

    The old view printed one block per holder, so a hundred-member family
    produced a hundred blocks. A member is not choosing between people, they
    are choosing which missing card to chase, and there are at most sixty of
    those no matter how large the family grows.
    """
    per_card: dict[str, dict] = {}
    for match in matches:
        for exchange in match.exchanges:
            mutual = bool(exchange.returns)
            for card_id in exchange.offers:
                entry = per_card.setdefault(
                    card_id, {"givers": set(), "mutual": set()}
                )
                entry["givers"].add(match.holder_tag)
                if mutual:
                    entry["mutual"].add(match.holder_tag)
    return per_card


def _offer_rows(card_ids: list[str], per_card: dict) -> str:
    """Grouped bullets, one line per card, with who can supply it."""
    by_category: dict[str, list[str]] = {}
    for card_id in card_ids:
        by_category.setdefault(CARD_BY_ID[card_id].category, []).append(card_id)
    blocks = []
    for category in CATEGORIES:
        rows = by_category.get(category.id)
        if not rows:
            continue
        lines = [f"{category_markup(category.id)} **{category.short_name}**"]
        for card_id in rows:
            card = CARD_BY_ID[card_id]
            entry = per_card[card_id]
            icon = troop_emoji.markup(card.id)
            lead = f"{icon} " if icon else ""
            givers = len(entry["givers"])
            mutual = len(entry["mutual"])
            detail = f"{givers} can give it"
            if mutual:
                detail += f", {mutual} want yours"
            lines.append(f"- {lead}**{_escape_markdown(card.name)}** — {detail}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _matches_view(
    account,
    inventory: dict,
    matches: list,
    *,
    supply: dict | None = None,
    achievable: tuple[int, int] | None = None,
) -> list[Container]:
    tag = _normalize_tag(account.tag)
    per_card = _offers_by_card(matches)
    # A swap where both sides get something is the one worth doing first. The
    # rest are still real - somebody may hand a card over for a duplicate they
    # do not need - so they stay, one rank down rather than mixed in.
    mutual_ids = [c for c in CARDS if c.id in per_card and per_card[c.id]["mutual"]]
    oneway_ids = [
        c for c in CARDS if c.id in per_card and not per_card[c.id]["mutual"]
    ]
    holders_total = len({match.holder_tag for match in matches})

    body: list = [
        Text(content="# Find trades"),
        Text(content=(
            f"-# {holders_total} collection"
            f"{'s' if holders_total != 1 else ''} can supply something you need"
        )),
    ]
    if mutual_ids:
        body.extend([
            Separator(divider=True),
            Text(content=(
                "## 🤝 Even swaps\n"
                "-# They have what you need and want one of your spares.\n"
                + _offer_rows([c.id for c in mutual_ids], per_card)
            )),
        ])
    if oneway_ids:
        body.extend([
            Separator(divider=True),
            Text(content=(
                "## 🎁 They would be doing you a favour\n"
                "-# Nothing of yours matches, so they get nothing back.\n"
                + _offer_rows([c.id for c in oneway_ids], per_card)
            )),
        ])
    # What your own spares are worth. This is the one thing the old "Who has
    # what" panel said that this screen did not, so it moved here rather than
    # justifying a second destination that otherwise repeated this one.
    mine = normalize_cards(inventory.get("cards"))
    wanted_from_me = [
        card for card in CARDS
        if mine.get(card.id, OWNED) >= DUPLICATE
        and supply
        and supply.get(card.id)
        and supply[card.id].demand
    ]
    if wanted_from_me:
        lines = []
        for category in CATEGORIES:
            rows = [c for c in wanted_from_me if c.category == category.id]
            if not rows:
                continue
            lines.append(f"{category_markup(category.id)} **{category.short_name}**")
            for card in rows[:6]:
                icon = troop_emoji.markup(card.id)
                lead = f"{icon} " if icon else ""
                demand = supply[card.id].demand
                lines.append(
                    f"- {lead}**{_escape_markdown(card.name)}** — "
                    f"{demand} need{'s' if demand == 1 else ''} it"
                )
        body.extend([
            Separator(divider=True),
            Text(content=(
                "## 🎯 Your spares in demand\n"
                "-# Worth holding on to when you bargain.\n" + "\n".join(lines)
            )),
        ])

    if not per_card:
        body.extend([
            Separator(divider=True),
            Text(content=(
                "Nobody with a current collection has a spare of anything you "
                "are missing yet. Collections older than 72 hours are ignored "
                "on purpose, so this fills in as the family updates."
            )),
        ])

    # One menu per category rather than a single menu capped at 25. The old
    # single menu silently dropped every match past the twenty-fifth; no
    # category holds more than nineteen cards, so a per-category menu always
    # fits. This is also what retired the separate browse-by-category screen,
    # which listed cards nobody held and so mostly led to "nobody has this".
    for category in CATEGORIES:
        offered = [c for c in CATEGORY_CARDS[category.id] if c.id in per_card]
        if not offered:
            continue
        body.extend([
            Separator(divider=True),
            ActionRow(components=[TextSelectMenu(
                custom_id=f"cards_open_card:{tag}|{category.id}",
                # Unicode, not the uploaded category emoji: a select
                # placeholder is plain text and would print `<:Elixer:123>`
                # verbatim.
                placeholder=(
                    f"{category.emoji} {category.short_name} "
                    f"— see who has one ({len(offered)})"
                )[:150],
                max_values=1,
                options=[
                    SelectOption(
                        label=card.name,
                        value=card.id,
                        description=(
                            f"{len(per_card[card.id]['givers'])} can give it"
                            + (
                                " · even swap"
                                if per_card[card.id]["mutual"] else ""
                            )
                        )[:100],
                        emoji=troop_emoji.partial(card.id),
                    )
                    for card in offered
                ],
            )]),
        ])
    if achievable and achievable[0]:
        listed, doable = achievable
        # A menu is not a plan: one spare offered to five people is one trade.
        body.append(Text(content=(
            f"-# {listed} swap option{'s' if listed != 1 else ''} listed · "
            f"up to **{doable}** could complete at once"
        )))
    body.append(ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{tag}",
            label="Back to board",
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_trades:{tag}",
            label="My trades",
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_matches:{tag}",
            label="Refresh",
        ),
    ]))
    return [Container(
        accent_color=GREEN_ACCENT if per_card else RED_ACCENT,
        components=body,
    )]


def _holders_view(
    account,
    card_id: str,
    holders: list,
    *,
    page: int = 0,
) -> list[Container]:
    card = CARD_BY_ID[card_id]
    category = CATEGORY_BY_ID[card.category]
    pages = max(1, math.ceil(len(holders) / HOLDER_RESULT_LIMIT))
    page = min(max(0, page), pages - 1)
    start = page * HOLDER_RESULT_LIMIT
    holder_options: list[SelectOption] = []
    shown_holders = holders[start:start + HOLDER_RESULT_LIMIT]
    for holder in shown_holders:
        if holder.holder_discord_id is None:
            continue
        exchange = next(
            (item for item in holder.exchanges if item.category == card.category),
            None,
        )
        if exchange is None:
            continue
        if not exchange.returns:
            continue
        count = len(exchange.returns)
        holder_options.append(SelectOption(
            label=_plain(holder.holder_name, limit=100),
            value=_normalize_tag(holder.holder_tag),
            description=_plain(
                f"Needs {count} compatible card{'s' if count != 1 else ''} · "
                f"{'same clan' if holder.same_clan else 'family move needed'} · "
                f"{_normalize_tag(holder.holder_tag)}",
                limit=100,
            ),
        ))
    askable = {option.value for option in holder_options}
    if holders:
        # Each holder carries its own Ask button rather than being a line of
        # text above a select that repeats the same names. This removes a whole
        # step: read the row, press Ask, choose what to give.
        holder_components: list = []
        for index, holder in enumerate(shown_holders, start=start + 1):
            tag = _normalize_tag(holder.holder_tag)
            line = Text(content=_match_line(holder, index))
            if tag in askable:
                holder_components.append(Section(
                    components=[line],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        custom_id=(
                            f"cards_trade_holder:"
                            f"{_normalize_tag(account.tag)}|{card.id}|{tag}"
                        ),
                        label="Ask",
                    ),
                ))
            else:
                holder_components.append(line)
    else:
        holder_components = [Text(content=(
            f"Nobody with a fresh collection currently lists a duplicate **{card.name}**. "
            "Try Refresh later as more family members finish setup."
        ))]
    components: list = [
        Text(content=f"# {category_markup(card.category)} Who Has {card.name}?"),
        Text(content=(
            f"Searching for **{_escape_markdown(account.name)}** · "
            f"`{_normalize_tag(account.tag)}`"
        )),
        Separator(divider=True),
        *holder_components,
    ]
    if holder_options:
        # The select that used to sit here repeated the names already listed
        # above it. Each holder now carries its own Ask button instead.
        components.append(Text(content=(
            "-# Nothing is reserved until they accept. If you are in different "
            "clans, move only after acceptance."
        )))
    if pages > 1:
        components.extend([
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=(
                        f"cards_holder_page:{_normalize_tag(account.tag)}|"
                        f"{card.id}|{page - 1}"
                    ),
                    label="Previous holders",
                    is_disabled=page == 0,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=(
                        f"cards_holder_page:{_normalize_tag(account.tag)}|"
                        f"{card.id}|{page}"
                    ),
                    label=f"Page {page + 1}/{pages}",
                    is_disabled=True,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=(
                        f"cards_holder_page:{_normalize_tag(account.tag)}|"
                        f"{card.id}|{page + 1}"
                    ),
                    label="Next holders",
                    is_disabled=page >= pages - 1,
                ),
            ]),
        ])
    components.extend([
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_matches:{_normalize_tag(account.tag)}",
                label="Back to Find trades",
                emoji="⬅️",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                label="Back to board",
            ),
        ]),
        Media(items=[MediaItem(media=FOOTER)]),
    ])
    return [Container(
        accent_color=GREEN_ACCENT if holders else RED_ACCENT,
        components=components,
    )]


def _trade_offer_view(account, card_id: str, holder) -> list[Container]:
    wanted = CARD_BY_ID[card_id]
    category = CATEGORY_BY_ID[wanted.category]
    exchange = next(
        (item for item in holder.exchanges if item.category == wanted.category),
        None,
    )
    return_ids = exchange.returns if exchange is not None else ()
    options = [
        SelectOption(
            label=CARD_BY_ID[return_id].name,
            value=f"{holder.holder_tag}|{return_id}",
            description=_plain(f"Give to {holder.holder_name}", limit=100),
        )
        for return_id in return_ids
        if return_id in CARD_BY_ID
    ]
    if not options:
        return _notice(
            "That reciprocal match changed",
            "Refresh the holder list; this player no longer needs a compatible spare.",
        )
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content=f"# 🤝 Swap for {wanted.name}"),
            Text(content=(
                f"**You receive:** {wanted.name}\n"
                f"**From:** {_escape_markdown(holder.holder_name, limit=60)} "
                f"· `{_normalize_tag(holder.holder_tag)}`\n\n"
                "Choose one duplicate to give. The bot rechecks both collections "
                "when the other player accepts. This proposal does not reserve cards."
            )),
            Separator(divider=True),
            ActionRow(components=[
                TextSelectMenu(
                    custom_id=(
                        f"cards_trade_request:{_normalize_tag(account.tag)}|{wanted.id}"
                    ),
                    placeholder="Choose the duplicate you will give...",
                    min_values=1,
                    max_values=1,
                    options=options,
                )
            ]),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=(
                        f"cards_holder_page:{_normalize_tag(account.tag)}"
                        f"|{wanted.id}|0"
                    ),
                    label="Back to holders",
                    emoji="⬅️",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_matches:{_normalize_tag(account.tag)}",
                    label="All matches",
                    emoji="🔎",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


def _trade_lease_specs(trade: dict) -> tuple[tuple[str, str, str], ...]:
    """The four exact card legs protected after a proposal is accepted."""
    return (
        ("need", _normalize_tag(trade["requester_tag"]), trade["wanted_card_id"]),
        ("supply", _normalize_tag(trade["requester_tag"]), trade["given_card_id"]),
        ("need", _normalize_tag(trade["holder_tag"]), trade["given_card_id"]),
        ("supply", _normalize_tag(trade["holder_tag"]), trade["wanted_card_id"]),
    )


def _trade_inventory_cards(trade: dict) -> dict[str, tuple[str, str]]:
    cards = (str(trade["wanted_card_id"]), str(trade["given_card_id"]))
    return {
        _normalize_tag(trade["requester_tag"]): cards,
        _normalize_tag(trade["holder_tag"]): cards,
    }


def _open_proposal_key(trade: dict) -> str:
    return "|".join((
        _normalize_tag(trade["requester_tag"]),
        _normalize_tag(trade["holder_tag"]),
        str(trade["wanted_card_id"]),
        str(trade["given_card_id"]),
    ))


def _proposal_slot_id(guild_id: int, tag: str, slot: int) -> str:
    return (
        f"card-trade-proposal-slot|{int(guild_id)}|"
        f"{_normalize_tag(tag)}|{int(slot):02d}"
    )


async def _proposal_slot_reclaimable(
    mongo: MongoClient,
    slot: dict,
    *,
    now: datetime,
) -> bool:
    owner_trade_id = str(slot.get("trade_id") or "")
    if not owner_trade_id:
        return True
    owner_trade = await mongo.card_trades.find_one({
        "_id": owner_trade_id,
        "kind": "trade",
    })
    if owner_trade is None:
        expires_at = as_utc(slot.get("lease_expires_at"))
        return expires_at is None or expires_at <= now
    if owner_trade.get("status") in {"pending", "reserving"}:
        # Finish the tiny insert/finalize crash window while discovering slots.
        await mongo.card_trades.update_one(
            {"_id": slot["_id"], "kind": "proposal_slot", "trade_id": owner_trade_id},
            {"$unset": {"lease_expires_at": ""}},
        )
        return False
    return True


async def _acquire_account_proposal_slot(
    mongo: MongoClient,
    trade: dict,
    tag: str,
    *,
    now: datetime,
) -> str | None:
    tag = _normalize_tag(tag)
    existing = await mongo.card_trades.find({
        "kind": "proposal_slot",
        "guild_id": int(trade["guild_id"]),
        "player_tag": tag,
    }).to_list(length=MAX_OPEN_PROPOSALS_PER_ACCOUNT)
    occupied: set[str] = set()
    for slot in existing:
        if str(slot.get("trade_id")) == str(trade["_id"]):
            return str(slot["_id"])
        if await _proposal_slot_reclaimable(mongo, slot, now=now):
            await mongo.card_trades.delete_many({
                "_id": slot["_id"],
                "kind": "proposal_slot",
                "trade_id": slot.get("trade_id"),
            })
        else:
            occupied.add(str(slot["_id"]))

    for index in range(MAX_OPEN_PROPOSALS_PER_ACCOUNT):
        slot_id = _proposal_slot_id(int(trade["guild_id"]), tag, index)
        if slot_id in occupied:
            continue
        try:
            result = await mongo.card_trades.update_one(
                {
                    "_id": slot_id,
                    "$or": [
                        {"trade_id": str(trade["_id"])},
                        {"trade_id": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "kind": "proposal_slot",
                        "trade_id": str(trade["_id"]),
                        "guild_id": int(trade["guild_id"]),
                        "player_tag": tag,
                        "lease_expires_at": now + PROPOSAL_SLOT_HOLD_FOR,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            continue
        if getattr(result, "matched_count", 0) or getattr(
            result, "upserted_id", None
        ):
            return slot_id
    return None


async def _release_proposal_slots(mongo: MongoClient, trade: dict) -> bool:
    try:
        await mongo.card_trades.delete_many({
            "kind": "proposal_slot",
            "trade_id": str(trade["_id"]),
        })
    except Exception:
        _log.exception("card proposal slot release deferred trade=%s", trade.get("_id"))
        return False
    return True


async def _acquire_proposal_slots(
    mongo: MongoClient,
    trade: dict,
    *,
    now: datetime,
) -> tuple[str, str] | None:
    acquired: list[str] = []
    for tag in (trade["requester_tag"], trade["holder_tag"]):
        slot_id = await _acquire_account_proposal_slot(
            mongo, trade, str(tag), now=now
        )
        if slot_id is None:
            await _release_proposal_slots(mongo, trade)
            return None
        acquired.append(slot_id)
    return acquired[0], acquired[1]


async def _finalize_proposal_slots(mongo: MongoClient, trade: dict) -> bool:
    result = await mongo.card_trades.update_many(
        {
            "kind": "proposal_slot",
            "trade_id": str(trade["_id"]),
            "_id": {"$in": list(trade.get("proposal_slot_ids") or ())},
        },
        {"$unset": {"lease_expires_at": ""}},
    )
    return getattr(result, "matched_count", 0) == 2


async def _reconcile_proposal_slots(
    mongo: MongoClient,
    *,
    guild_id: int,
    now: datetime,
) -> int:
    unfinished = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "status": {"$in": ["pending", "reserving"]},
        "$or": [
            {"proposal_slots_finalized": {"$exists": False}},
            {"proposal_slots_finalized": False},
        ],
    }).to_list(length=500)
    reconciled = 0
    for trade in unfinished:
        slot_ids = await _acquire_proposal_slots(mongo, trade, now=now)
        if slot_ids is None:
            continue
        trade = dict(trade)
        trade["proposal_slot_ids"] = list(slot_ids)
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "kind": "trade",
                "status": {"$in": ["pending", "reserving"]},
            },
            {"$set": {"proposal_slot_ids": list(slot_ids)}},
        )
        if not await _finalize_proposal_slots(mongo, trade):
            continue
        result = await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "kind": "trade",
                "status": {"$in": ["pending", "reserving"]},
            },
            {"$set": {"proposal_slots_finalized": True}},
        )
        reconciled += int(bool(getattr(result, "matched_count", 0)))
    return reconciled


def _trade_lease_id(kind: str, tag: str, card_id: str) -> str:
    del kind
    return f"card-trade-lease|{_normalize_tag(tag)}|{card_id}"


def _reservation_owner(trade: dict) -> str:
    token = str(trade.get("reservation_token") or "")
    return f"{trade['_id']}:{token}" if token else str(trade["_id"])


async def _release_trade_leases(
    mongo: MongoClient,
    trade: dict,
    *,
    owner: str | None = None,
) -> None:
    # The acceptance-attempt token is cardinal: a stalled worker must never
    # release leases reacquired by a newer attempt for the same proposal.
    await mongo.card_trades.delete_many({
        "kind": "lease",
        "trade_id": str(trade["_id"]),
        "owner_token": owner or _reservation_owner(trade),
    })


async def _clear_trade_inventory_fences(
    mongo: MongoClient,
    trade: dict,
    *,
    owner: str | None = None,
) -> None:
    owner = owner or _reservation_owner(trade)
    for tag, card_ids in _trade_inventory_cards(trade).items():
        for card_id in card_ids:
            path = f"card_trade_reservations.{card_id}"
            await mongo.card_inventories.update_one(
                {
                    "_id": tag,
                    "$or": [{path: owner}, {f"{path}.owner": owner}],
                },
                {"$unset": {path: ""}},
            )


async def _release_trade_reservation(
    mongo: MongoClient,
    trade: dict,
    *,
    owner: str | None = None,
) -> None:
    owner = owner or _reservation_owner(trade)
    await _release_trade_leases(mongo, trade, owner=owner)
    await _clear_trade_inventory_fences(mongo, trade, owner=owner)


def _cleanup_fields(trade: dict) -> dict[str, object]:
    return {
        "cleanup_pending": True,
        "cleanup_owner_token": _reservation_owner(trade),
        "cleanup_requested_at": datetime.now(timezone.utc),
    }


async def _invalidate_trade_categories(
    mongo: MongoClient,
    trade: dict,
) -> bool:
    """Make uncertain trade legs unmatchable until both lists are reviewed."""
    category_id = str(
        trade.get("category")
        or CARD_BY_ID[str(trade["wanted_card_id"])].category
    )
    review_steps = [
        f"{category_id}:missing",
        f"{category_id}:duplicates",
    ]
    marker = f"card_trade_review_invalidations.{trade['_id']}"
    invalidated_at = datetime.now(timezone.utc)
    safe = 0
    for tag in {
        _normalize_tag(trade["requester_tag"]),
        _normalize_tag(trade["holder_tag"]),
    }:
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "guild_id": int(trade["guild_id"]),
                marker: {"$exists": False},
            },
            {
                "$pull": {
                    "complete_categories": category_id,
                    "reviewed_lists": {"$in": review_steps},
                },
                "$set": {
                    marker: invalidated_at,
                    "updated_at": invalidated_at,
                    "update_source": "trade_needs_review",
                },
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 0):
            safe += 1
            continue
        current = await mongo.card_inventories.find_one({
            "_id": tag,
            "guild_id": int(trade["guild_id"]),
        })
        invalidations = (
            current.get("card_trade_review_invalidations", {})
            if current else {}
        )
        if current is None or str(trade["_id"]) in invalidations:
            safe += 1
    return safe == 2


async def _finish_trade_cleanup(
    mongo: MongoClient,
    trade: dict,
    *,
    owner: str | None = None,
) -> bool:
    """Finish an already-durable cleanup request; leave it queued on error."""
    owner = owner or str(
        trade.get("cleanup_owner_token") or _reservation_owner(trade)
    )
    try:
        current = await mongo.card_trades.find_one({"_id": trade["_id"]})
        if current and current.get("status") == "needs_review":
            if not await _invalidate_trade_categories(mongo, current):
                return False
        await _release_trade_reservation(mongo, trade, owner=owner)
    except Exception:
        _log.exception(
            "card trade cleanup deferred trade=%s owner=%s",
            trade.get("_id"), owner,
        )
        return False
    await mongo.card_trades.update_one(
        {
            "_id": trade["_id"],
            "cleanup_pending": True,
            "cleanup_owner_token": owner,
        },
        {
            "$set": {"released_at": datetime.now(timezone.utc)},
            "$unset": {
                "cleanup_pending": "",
                "cleanup_owner_token": "",
                "cleanup_requested_at": "",
            },
        },
    )
    return True


async def _reconcile_trade_cleanups(
    mongo: MongoClient,
    *,
    guild_id: int,
) -> int:
    queued = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "cleanup_pending": True,
    }).to_list(length=500)
    cleaned = 0
    for trade in queued:
        if await _finish_trade_cleanup(mongo, trade):
            cleaned += 1
    return cleaned


async def _acquire_trade_inventory_fences(
    mongo: MongoClient,
    trade: dict,
) -> bool:
    """Mark only this swap's two cards on each inventory document."""
    fenced = 0
    owner = _reservation_owner(trade)
    checked_at = datetime.now(timezone.utc)
    reservation_until = as_utc(trade.get("reservation_until")) or checked_at
    for tag, card_ids in sorted(_trade_inventory_cards(trade).items()):
        guards = []
        updates = {}
        for card_id in card_ids:
            path = f"card_trade_reservations.{card_id}"
            guards.append({"$or": [
                {path: {"$exists": False}},
                {path: owner},
                {f"{path}.owner": owner},
                {f"{path}.until": {"$lte": checked_at}},
            ]})
            updates[path] = {
                "owner": owner,
                "until": reservation_until,
            }
        result = await mongo.card_inventories.update_one(
            {
                "_id": _normalize_tag(tag),
                "guild_id": int(trade["guild_id"]),
                "$and": guards,
            },
            {"$set": updates},
        )
        if getattr(result, "matched_count", 0):
            fenced += 1
    if fenced == 2:
        return True
    await _clear_trade_inventory_fences(mongo, trade)
    return False


async def _verify_trade_inventory_fences(
    mongo: MongoClient,
    trade: dict,
) -> bool:
    owner = _reservation_owner(trade)
    checked_at = datetime.now(timezone.utc)
    found = 0
    for tag, card_ids in _trade_inventory_cards(trade).items():
        query = {"_id": tag, "guild_id": int(trade["guild_id"])}
        for card_id in card_ids:
            path = f"card_trade_reservations.{card_id}"
            query["$and"] = query.get("$and", []) + [
                {"$or": [{path: owner}, {f"{path}.owner": owner}]},
                {"$or": [
                    {f"{path}.until": {"$exists": False}},
                    {f"{path}.until": {"$gt": checked_at}},
                ]},
            ]
        if await mongo.card_inventories.find_one(query):
            found += 1
    return found == 2


async def _acquire_trade_leases(
    mongo: MongoClient,
    trade: dict,
    *,
    now: datetime,
) -> bool:
    """Acquire the four card-leg mutexes; proposals themselves hold none."""
    acquired: list[str] = []
    try:
        for kind, tag, card_id in sorted(_trade_lease_specs(trade)):
            lease_id = _trade_lease_id(kind, tag, card_id)
            try:
                result = await mongo.card_trades.update_one(
                    {
                        "_id": lease_id,
                        "owner_token": _reservation_owner(trade),
                    },
                    {
                        "$set": {
                            "kind": "lease",
                            "trade_id": str(trade["_id"]),
                            "owner_token": _reservation_owner(trade),
                            "guild_id": trade["guild_id"],
                            "lease_kind": kind,
                            "player_tag": tag,
                            "card_id": card_id,
                            "lease_expires_at": trade.get("reservation_until"),
                        },
                        "$setOnInsert": {"created_at": now},
                    },
                    upsert=True,
                )
            except DuplicateKeyError:
                await _release_trade_leases(mongo, trade)
                return False
            if not (getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None)):
                await _release_trade_leases(mongo, trade)
                return False
            acquired.append(lease_id)
    except Exception:
        if acquired:
            await _release_trade_leases(mongo, trade)
        raise
    return True


async def _verify_trade_leases(
    mongo: MongoClient,
    trade: dict,
    *,
    now: datetime,
) -> bool:
    result = await mongo.card_trades.update_many(
        {
            "kind": "lease",
            "trade_id": str(trade["_id"]),
            "owner_token": _reservation_owner(trade),
            "$or": [
                {"lease_expires_at": {"$exists": False}},
                {"lease_expires_at": {"$gt": datetime.now(timezone.utc)}},
            ],
        },
        {"$set": {"checked_at": now}},
    )
    return getattr(result, "matched_count", 0) == TRADE_LEASE_COUNT


async def _finalize_trade_reservation(
    mongo: MongoClient,
    trade: dict,
) -> bool:
    """Turn temporary accepting resources into indefinite accepted ones."""
    checked_at = datetime.now(timezone.utc)
    current = await mongo.card_trades.find_one({
        "_id": trade["_id"],
        "status": "reserving",
        "reservation_token": trade.get("reservation_token"),
        "reservation_until": {"$gt": checked_at},
    })
    if current is None:
        return False
    owner = _reservation_owner(trade)
    finalized_markers = 0
    for tag, card_ids in _trade_inventory_cards(trade).items():
        for card_id in card_ids:
            path = f"card_trade_reservations.{card_id}"
            result = await mongo.card_inventories.update_one(
                {
                    "_id": tag,
                    f"{path}.owner": owner,
                    f"{path}.until": {"$gt": checked_at},
                },
                {"$unset": {f"{path}.until": ""}},
            )
            finalized_markers += int(bool(getattr(result, "matched_count", 0)))
    leases = await mongo.card_trades.update_many(
        {
            "kind": "lease",
            "trade_id": str(trade["_id"]),
            "owner_token": owner,
            "lease_expires_at": {"$gt": checked_at},
        },
        {"$unset": {"lease_expires_at": ""}},
    )
    return (
        finalized_markers == TRADE_LEASE_COUNT
        and getattr(leases, "matched_count", 0) == TRADE_LEASE_COUNT
    )


async def _verify_trade_reservation(
    mongo: MongoClient,
    trade: dict,
    *,
    now: datetime,
) -> bool:
    if not await _verify_trade_inventory_fences(mongo, trade):
        return False
    return await _verify_trade_leases(
        mongo, trade, now=now
    )


async def _recover_stalled_reservations(
    mongo: MongoClient,
    *,
    now: datetime,
    guild_id: int,
) -> int:
    """Release crashed acceptance attempts using their unique fencing token."""
    stalled = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "status": "reserving",
        "reservation_until": {"$lte": now},
    }).to_list(length=200)
    recovered = 0
    for stale in stalled:
        result = await mongo.card_trades.update_one(
            {
                "_id": stale["_id"],
                "status": "reserving",
                "reservation_token": stale.get("reservation_token"),
                "reservation_until": {"$lte": now},
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": now,
                    "last_error": "acceptance_recovered",
                    **_cleanup_fields(stale),
                },
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        if getattr(result, "modified_count", 0):
            await _finish_trade_cleanup(
                mongo, stale, owner=_reservation_owner(stale)
            )
            recovered += 1
    return recovered


async def _accept_trade_reservation(
    mongo: MongoClient,
    trade: dict,
    *,
    user_id: int,
    live_clans: tuple[str, str],
    now: datetime,
) -> tuple[str, str]:
    """Reserve exact cards on acceptance, never while merely proposed."""
    await _reconcile_trade_cleanups(
        mongo, guild_id=int(trade["guild_id"])
    )
    await _recover_stalled_reservations(
        mongo, now=now, guild_id=int(trade["guild_id"])
    )
    reservation_token = secrets.token_hex(8)
    reservation_until = now + TRADE_COMPLETION_FOR
    started = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": "pending"},
        {"$set": {
            "status": "reserving",
            "reservation_token": reservation_token,
            "reservation_until": reservation_until,
            "accepted_at": now,
            "accepted_by": int(user_id),
            "updated_at": now,
        }},
    )
    if not getattr(started, "modified_count", 0):
        return "changed", str(trade.get("status") or "changed")
    trade = dict(trade)
    trade.update({
        "status": "reserving",
        "reservation_token": reservation_token,
        "reservation_until": reservation_until,
    })

    requester, holder = await asyncio.gather(
        mongo.card_inventories.find_one({
            "_id": _normalize_tag(trade["requester_tag"]),
            "guild_id": int(trade["guild_id"]),
        }),
        mongo.card_inventories.find_one({
            "_id": _normalize_tag(trade["holder_tag"]),
            "guild_id": int(trade["guild_id"]),
        }),
    )
    error = (
        "One collection is unavailable."
        if requester is None or holder is None
        else reciprocal_trade_error(
            _without_reserved_cards(requester),
            _without_reserved_cards(holder),
            trade["wanted_card_id"],
            trade["given_card_id"],
            now=now,
        )
    )
    if error:
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": reservation_token,
            },
            {
                "$set": {"status": "pending", "updated_at": now, "last_error": error},
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        return "invalid", "pending"

    if not await _acquire_trade_leases(mongo, trade, now=now):
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": reservation_token,
            },
            {
                "$set": {"status": "pending", "updated_at": now, "last_error": "card_reserved"},
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        return "conflict", "pending"
    if not await _acquire_trade_inventory_fences(mongo, trade):
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": reservation_token,
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": now,
                    "last_error": "card_reserved",
                    **_cleanup_fields(trade),
                },
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        return "conflict", "pending"

    fenced_requester, fenced_holder = await asyncio.gather(
        mongo.card_inventories.find_one({
            "_id": _normalize_tag(trade["requester_tag"]),
            "guild_id": int(trade["guild_id"]),
        }),
        mongo.card_inventories.find_one({
            "_id": _normalize_tag(trade["holder_tag"]),
            "guild_id": int(trade["guild_id"]),
        }),
    )
    fenced_error = (
        "One collection is unavailable."
        if fenced_requester is None or fenced_holder is None
        else reciprocal_trade_error(
            fenced_requester,
            fenced_holder,
            trade["wanted_card_id"],
            trade["given_card_id"],
            now=now,
        )
    )
    if fenced_error or not await _verify_trade_reservation(mongo, trade, now=now):
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": reservation_token,
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": now,
                    "last_error": fenced_error or "reservation_lost",
                    **_cleanup_fields(trade),
                },
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        return "conflict" if not fenced_error else "invalid", "pending"
    if not await _finalize_trade_reservation(mongo, trade):
        await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": reservation_token,
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": now,
                    "last_error": "reservation_finalize_failed",
                    **_cleanup_fields(trade),
                },
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        return "conflict", "pending"

    requester_clan, holder_clan = live_clans
    status = "ready" if requester_clan == holder_clan else "move_needed"
    result = await mongo.card_trades.update_one(
        {
            "_id": trade["_id"],
            "status": "reserving",
            "reservation_token": reservation_token,
        },
        {"$set": {
            "status": status,
            "requester_clan_tag": requester_clan,
            "holder_clan_tag": holder_clan,
            "clan_tag": requester_clan if status == "ready" else None,
            "ready_at": now if status == "ready" else None,
            "updated_at": now,
        }, "$unset": {"reservation_until": ""}},
    )
    if getattr(result, "modified_count", 0):
        await _release_proposal_slots(mongo, trade)
        return "accepted", status
    current = await mongo.card_trades.find_one({"_id": trade["_id"]})
    owner = _reservation_owner(trade)
    if (
        current
        and current.get("status")
        in {"move_needed", "ready", "accepted", "completing"}
        and _reservation_owner(current) == owner
    ):
        await _release_proposal_slots(mongo, current)
        return "changed", str(current["status"])
    if (
        current
        and current.get("cleanup_pending")
        and current.get("cleanup_owner_token") != owner
    ):
        await _finish_trade_cleanup(mongo, current)
        current = await mongo.card_trades.find_one({"_id": trade["_id"]})
    if current:
        cleanup_query: dict[str, object] = {
            "_id": trade["_id"],
            "status": current.get("status"),
        }
        if current.get("reservation_token") is not None:
            cleanup_query["reservation_token"] = current["reservation_token"]
        queued = await mongo.card_trades.update_one(
            cleanup_query,
            {"$set": _cleanup_fields(trade)},
        )
        if getattr(queued, "modified_count", 0):
            await _finish_trade_cleanup(mongo, trade, owner=owner)
    else:
        # A deleted audit row cannot carry a retry flag. The exact old owner
        # still makes this best-effort release safe against any newer attempt.
        await _release_trade_reservation(mongo, trade, owner=owner)
    return "changed", str(current.get("status") if current else "changed")


async def _create_trade_request(
    mongo: MongoClient,
    *,
    requester: dict,
    holder: dict,
    wanted_card_id: str,
    given_card_id: str,
    guild_id: int,
) -> tuple[dict | None, str | None]:
    now = datetime.now(timezone.utc)
    try:
        same_family = (
            int(requester.get("guild_id")) == int(guild_id)
            and int(holder.get("guild_id")) == int(guild_id)
        )
    except (TypeError, ValueError):
        same_family = False
    if not same_family:
        return None, "Both collections must belong to this Discord family."
    if _normalize_tag(requester.get("_id")) == _normalize_tag(holder.get("_id")):
        return None, "Choose a different player's collection for this swap."
    error = reciprocal_trade_error(
        _without_reserved_cards(requester),
        _without_reserved_cards(holder),
        wanted_card_id,
        given_card_id,
        now=now,
    )
    if error:
        return None, error

    holder_discord_id = holder.get("discord_id")
    requester_discord_id = requester.get("discord_id")
    try:
        holder_discord_id = int(holder_discord_id)
        requester_discord_id = int(requester_discord_id)
    except (TypeError, ValueError):
        return None, "Both collections must be linked to current Discord members."

    requester_cards = normalize_cards(_without_reserved_cards(requester).get("cards"))
    holder_cards = normalize_cards(_without_reserved_cards(holder).get("cards"))
    compatible_card_ids = [
        card.id
        for card in CATEGORY_CARDS[CARD_BY_ID[wanted_card_id].category]
        if requester_cards.get(card.id, OWNED) >= DUPLICATE
        and holder_cards.get(card.id, OWNED) == MISSING
    ]
    trade = {
        "_id": secrets.token_hex(8),
        "kind": "trade",
        "status": "pending",
        "guild_id": int(guild_id),
        "category": CARD_BY_ID[wanted_card_id].category,
        "requester_clan_tag": requester.get("clan_tag"),
        "requester_clan_name": requester.get("clan_name"),
        "requester_tag": _normalize_tag(requester.get("_id")),
        "requester_name": str(requester.get("player_name") or "Unknown player"),
        "requester_discord_id": requester_discord_id,
        "holder_tag": _normalize_tag(holder.get("_id")),
        "holder_name": str(holder.get("player_name") or "Unknown player"),
        "holder_discord_id": holder_discord_id,
        "holder_clan_tag": holder.get("clan_tag"),
        "holder_clan_name": holder.get("clan_name"),
        "wanted_card_id": wanted_card_id,
        "given_card_id": given_card_id,
        "compatible_card_ids": compatible_card_ids,
        "created_at": now,
        "updated_at": now,
    }
    trade["open_proposal_key"] = _open_proposal_key(trade)
    duplicate = await mongo.card_trades.find_one({
        "kind": "trade",
        "guild_id": int(guild_id),
        "status": "pending",
        "requester_tag": trade["requester_tag"],
        "holder_tag": trade["holder_tag"],
        "wanted_card_id": wanted_card_id,
        "given_card_id": given_card_id,
    })
    if duplicate:
        return None, "That exact proposal is already open in My trades."
    for participant_tag in (trade["requester_tag"], trade["holder_tag"]):
        open_proposals = await mongo.card_trades.find({
            "kind": "trade",
            "guild_id": int(guild_id),
            "status": {"$in": ["pending", "reserving"]},
            "$or": [
                {"requester_tag": participant_tag},
                {"holder_tag": participant_tag},
            ],
        }).to_list(length=MAX_OPEN_PROPOSALS_PER_ACCOUNT)
        if len(open_proposals) >= MAX_OPEN_PROPOSALS_PER_ACCOUNT:
            return None, (
                f"`{participant_tag}` already has "
                f"{MAX_OPEN_PROPOSALS_PER_ACCOUNT} open proposals. Close one "
                "in My trades before posting another."
            )
    proposal_slots = await _acquire_proposal_slots(mongo, trade, now=now)
    if proposal_slots is None:
        return None, (
            "One account already has the maximum number of open proposals. "
            "Close one in My trades before posting another."
        )
    trade["proposal_slot_ids"] = list(proposal_slots)
    trade["proposal_slots_finalized"] = False
    try:
        await mongo.card_trades.insert_one(trade)
    except DuplicateKeyError:
        await _release_proposal_slots(mongo, trade)
        return None, "That exact proposal is already open in My trades."
    except Exception:
        await _release_proposal_slots(mongo, trade)
        raise
    if not await _finalize_proposal_slots(mongo, trade):
        await mongo.card_trades.delete_many({
            "_id": trade["_id"],
            "kind": "trade",
            "status": "pending",
        })
        await _release_proposal_slots(mongo, trade)
        return None, "The proposal could not be saved safely. Please try again."
    await mongo.card_trades.update_one(
        {"_id": trade["_id"], "kind": "trade", "status": "pending"},
        {"$set": {"proposal_slots_finalized": True}},
    )
    trade["proposal_slots_finalized"] = True
    return trade, None


async def _live_clan_tag(coc_client: coc.Client, tag: str) -> str | None:
    try:
        player = await coc_client.get_player(_normalize_tag(tag))
    except Exception:
        _log.exception("card trade could not refresh player clan tag=%s", tag)
        return None
    clan = getattr(player, "clan", None)
    return _normalize_tag(getattr(clan, "tag", None)) if clan else None


async def _live_family_clans(
    mongo: MongoClient,
    coc_client: coc.Client,
    left_tag: str,
    right_tag: str,
) -> tuple[str, str] | None:
    """Return both live clan tags only when both are configured family clans."""
    left_clan, right_clan = await asyncio.gather(
        _live_clan_tag(coc_client, left_tag),
        _live_clan_tag(coc_client, right_tag),
    )
    if not left_clan or not right_clan:
        return None
    try:
        family_tags = {
            _normalize_tag(tag)
            for tag in await mongo.clans.distinct("tag")
            if _normalize_tag(tag)
        }
    except Exception:
        _log.exception("card trade could not verify family clan membership")
        return None
    if left_clan not in family_tags or right_clan not in family_tags:
        return None
    return left_clan, right_clan


async def _send_trade_dm(
    bot: hikari.GatewayBot,
    discord_id: int,
    content: str,
    *,
    trade_id: str,
    attachment=None,
) -> bool:
    try:
        channel = await bot.rest.create_dm_channel(int(discord_id))
        message = {"channel": channel, "content": content}
        if attachment is not None:
            message["attachment"] = attachment
        await bot.rest.create_message(**message)
        return True
    except Exception as exc:
        _log.info(
            "card trade DM failed trade=%s user=%s error=%s",
            trade_id, discord_id, type(exc).__name__,
        )
        return False


def _trade_strip_attachment(trade: dict):
    """Build the proposal image without making delivery depend on rendering."""
    try:
        compatible = [
            str(card_id)
            for card_id in (trade.get("compatible_card_ids") or ())
            if str(card_id) != str(trade.get("given_card_id") or "")
        ]
        strip = render_trade_strip(
            str(trade.get("wanted_card_id") or ""),
            str(trade.get("given_card_id") or ""),
            compatible,
            requester_name=str(trade.get("requester_name") or "A family member"),
            holder_name=str(trade.get("holder_name") or "the holder"),
        )
        return hikari.Bytes(strip.png_bytes, strip.filename, "image/png")
    except Exception:
        _log.exception("card trade visual render failed trade=%s", trade.get("_id"))
        return None


def _trade_offer_names(trade: dict) -> str:
    card_ids = list(trade.get("compatible_card_ids") or ())
    if trade.get("given_card_id") not in card_ids:
        card_ids.insert(0, str(trade.get("given_card_id") or ""))
    return _card_names(card_ids, limit=8)


def _trade_location_line(trade: dict) -> str:
    requester_clan = _normalize_tag(trade.get("requester_clan_tag"))
    holder_clan = _normalize_tag(trade.get("holder_clan_tag"))
    if requester_clan and requester_clan == holder_clan:
        return f"You are currently together in `{requester_clan}`."
    return "You are currently in different family clans."


def _trade_channel_content(trade: dict) -> str:
    status = str(trade.get("status") or "pending")
    labels = {
        "pending": "🃏 New card proposal",
        "reserving": "🟡 Proposal being accepted",
        "move_needed": "🟡 Accepted — family move needed",
        "ready": "🟢 Ready in the same clan",
        "accepted": "🟢 Ready in the same clan",
        "completing": "🟡 Saving completion",
        "completed": "✅ Completed",
        "declined": "⚪ Declined",
        "cancelled": "⚪ Cancelled",
        "needs_review": "⚠️ Needs review",
        "expired": "⌛ Closed",
    }
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    requester = _escape_markdown(trade.get("requester_name"), limit=60)
    holder = _escape_markdown(trade.get("holder_name"), limit=60)
    requester_id = int(trade["requester_discord_id"])
    holder_id = int(trade["holder_discord_id"])
    return (
        f"**{labels.get(status, status.replace('_', ' ').title())}**\n"
        f"<@{holder_id}> — **{requester} needs your duplicate {wanted}.**\n"
        f"**Proposed:** {requester} (`{trade['requester_tag']}`) gives **{given}** "
        f"to {holder} (`{trade['holder_tag']}`) for **{wanted}**.\n"
        f"<@{requester_id}> has **{_trade_offer_names(trade)}** duplicates that you need.\n"
        f"📍 {_trade_location_line(trade)}\n"
        + (
            "Use `/cards` → **My trades** to manage this proposal."
            if status in {"pending", "reserving", "move_needed", "ready", "accepted", "completing", "needs_review"}
            else "This proposal is closed."
        )
    )


async def _post_trade_channel(bot: hikari.GatewayBot, mongo: MongoClient, trade: dict) -> bool:
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        return False
    try:
        channel = await bot.rest.fetch_channel(channel_id)
        if int(getattr(channel, "guild_id", 0) or 0) != int(
            _configured_cards_guild_id() or 0
        ):
            _log.error(
                "card trade channel is outside configured guild channel=%s",
                channel_id,
            )
            return False
        outgoing = {
            "channel": channel_id,
            "content": _trade_channel_content(trade),
            "mentions_everyone": False,
            "role_mentions": False,
            "user_mentions": [int(trade["holder_discord_id"])],
        }
        attachment = await asyncio.to_thread(_trade_strip_attachment, trade)
        if attachment is not None:
            outgoing["attachment"] = attachment
        message = await bot.rest.create_message(**outgoing)
        trade["channel_id"] = int(channel_id)
        trade["channel_message_id"] = int(message.id)
        await mongo.card_trades.update_one(
            {"_id": trade["_id"], "kind": "trade"},
            {"$set": {
                "channel_id": int(channel_id),
                "channel_message_id": int(message.id),
            }},
        )
        return True
    except Exception as exc:
        _log.info(
            "card trade channel post failed trade=%s error=%s",
            trade.get("_id"), type(exc).__name__,
        )
        return False


async def _update_trade_channel(bot: hikari.GatewayBot, trade: dict) -> bool:
    channel_id = trade.get("channel_id") or _configured_cards_channel_id()
    message_id = trade.get("channel_message_id")
    if channel_id is None or message_id is None:
        return False
    try:
        await bot.rest.edit_message(
            channel=int(channel_id),
            message=int(message_id),
            content=_trade_channel_content(trade),
            mentions_everyone=False,
            role_mentions=False,
            user_mentions=False,
        )
        return True
    except Exception as exc:
        _log.info(
            "card trade channel update failed trade=%s error=%s",
            trade.get("_id"), type(exc).__name__,
        )
        return False


async def _notify_trade_holder(bot: hikari.GatewayBot, trade: dict) -> bool:
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    requester = _escape_markdown(trade.get("requester_name"), limit=60)
    holder = _escape_markdown(trade.get("holder_name"), limit=60)
    attachment = await asyncio.to_thread(_trade_strip_attachment, trade)
    return await _send_trade_dm(
        bot,
        int(trade["holder_discord_id"]),
        (
            "🃏 **New Clash of Cards proposal**\n"
            f"**{requester} needs your duplicate {wanted}.**\n"
            f"For **{holder}** (`{trade['holder_tag']}`): you give **{wanted}** "
            f"and receive **{given}**.\n"
            f"{requester} has **{_trade_offer_names(trade)}** duplicates that you need.\n"
            f"{_trade_location_line(trade)}\n"
            "Run `/cards` in the Warriors United server and open **My trades** "
            "to accept or decline. Nothing is reserved until you accept."
        ),
        trade_id=str(trade["_id"]),
        attachment=attachment,
    )


async def _notify_trade_accepted(bot: hikari.GatewayBot, trade: dict) -> bool:
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    status = str(trade.get("status") or "move_needed")
    next_step = (
        "You are in different family clans. Move one account manually within "
        "the family, then use `/cards` → **My trades** → **Check clans**."
        if status == "move_needed"
        else "You are now in the same clan and can coordinate the two in-game requests."
    )
    return await _send_trade_dm(
        bot,
        int(trade["requester_discord_id"]),
        (
            "✅ **Your Clash of Cards swap was accepted**\n"
            f"For **{_plain(trade['requester_name'])}** "
            f"(`{trade['requester_tag']}`): "
            f"**{_plain(trade['holder_name'])}** (`{trade['holder_tag']}`) accepted "
            f"your **{given}** for **{wanted}** swap.\n"
            f"The exact cards are reserved; there is no short completion timer. {next_step}"
        ),
        trade_id=str(trade["_id"]),
    )


async def _notify_trade_status(
    bot: hikari.GatewayBot,
    trade: dict,
    *,
    recipient_id: int,
    title: str,
    detail: str,
) -> bool:
    wanted = CARD_BY_ID.get(str(trade.get("wanted_card_id")))
    given = CARD_BY_ID.get(str(trade.get("given_card_id")))
    swap = (
        f"**{given.name}** for **{wanted.name}**"
        if wanted is not None and given is not None
        else "the card swap"
    )
    accounts = (
        f"**{_plain(trade.get('requester_name'))}** "
        f"(`{trade.get('requester_tag')}`) ↔ "
        f"**{_plain(trade.get('holder_name'))}** "
        f"(`{trade.get('holder_tag')}`)"
    )
    return await _send_trade_dm(
        bot,
        int(recipient_id),
        (
            f"🃏 **{title}**\n"
            f"{accounts}\n"
            f"Status changed for {swap}. {detail}\n"
            "Run `/cards` in the Warriors United server for the current "
            "collection and trade status."
        ),
        trade_id=str(trade["_id"]),
    )


def _dm_fallback_note(sent: bool, recipient_id: int) -> str:
    return (
        ""
        if sent
        else f" I could not DM <@{int(recipient_id)}>; please ping them directly."
    )


async def _notify_review_participants(
    bot: hikari.GatewayBot,
    trade: dict,
    detail: str,
) -> None:
    recipients: set[int] = set()
    for value in (
        trade.get("requester_discord_id"),
        trade.get("holder_discord_id"),
    ):
        try:
            recipients.add(int(value))
        except (TypeError, ValueError):
            continue
    await asyncio.gather(*(
        _notify_trade_status(
            bot,
            trade,
            recipient_id=recipient,
            title="Card swap needs review",
            detail=detail,
        )
        for recipient in recipients
    ))


async def _active_trades(
    mongo: MongoClient,
    *,
    tag: str,
    guild_id: int,
    bot: hikari.GatewayBot | None = None,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    participant = {
        "$or": [
            {"requester_tag": _normalize_tag(tag)},
            {"holder_tag": _normalize_tag(tag)},
        ],
    }
    await _reconcile_trade_cleanups(mongo, guild_id=int(guild_id))
    await _recover_stalled_reservations(
        mongo, now=now, guild_id=int(guild_id)
    )
    expired = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "status": "completing",
        "expires_at": {"$lte": now},
        **participant,
    }).to_list(length=COMMITTED_TRADE_FETCH_LIMIT)
    for trade in expired:
        result = await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "completing",
                "expires_at": {"$lte": now},
            },
            {
                "$set": {
                    "status": "needs_review",
                    "updated_at": now,
                    "failure": "completion_expired",
                    "review_expires_at": now + TRADE_REVIEW_FOR,
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        if getattr(result, "modified_count", 0):
            await _finish_trade_cleanup(
                mongo, trade, owner=_reservation_owner(trade)
            )
            if bot is not None:
                trade["status"] = "needs_review"
                await asyncio.gather(
                    _notify_review_participants(
                        bot,
                        trade,
                        "Completion expired before it could be confirmed. Recheck "
                        "and correct both affected categories.",
                    ),
                    _update_trade_channel(bot, trade),
                )

    committed = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "$and": [
            participant,
            {"$or": [
                {"status": {"$in": [
                    "reserving", "move_needed", "ready", "accepted"
                ]}},
                {"status": "completing", "expires_at": {"$gt": now}},
            ]},
        ],
    }).sort("updated_at", -1).to_list(length=COMMITTED_TRADE_FETCH_LIMIT)
    proposals = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "$and": [
            participant,
            {"status": "pending"},
        ],
    }).sort("updated_at", -1).to_list(length=PROPOSAL_TRADE_FETCH_LIMIT)
    reviews = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "$and": [
            participant,
            {
                "status": "needs_review",
                "review_expires_at": {"$gt": now},
            },
        ],
    }).sort("updated_at", -1).to_list(length=REVIEW_TRADE_FETCH_LIMIT)
    # Committed agreements always appear before unreserved proposals and old
    # review records. Even a burst beyond the advisory proposal cap therefore
    # cannot hide a move/check/cancel/complete button.
    return [*committed, *proposals, *reviews]


def _trade_summary(trade: dict, *, role: str) -> str:
    wanted = CARD_BY_ID.get(str(trade.get("wanted_card_id")))
    given = CARD_BY_ID.get(str(trade.get("given_card_id")))
    if wanted is None or given is None:
        return "This request contains an unknown card and cannot be completed."
    if role == "requester":
        counterpart = trade.get("holder_name") or "Unknown player"
        counterpart_tag = trade.get("holder_tag") or "?"
        receive, offer = wanted.name, given.name
    else:
        counterpart = trade.get("requester_name") or "Unknown player"
        counterpart_tag = trade.get("requester_tag") or "?"
        receive, offer = given.name, wanted.name
    raw_status = str(trade.get("status") or "unknown")
    status = {
        "pending": "Proposal",
        "reserving": "Accepting proposal",
        "move_needed": "Accepted · move needed",
        "ready": "Ready in game",
        "accepted": "Ready in game",
        "completing": "Saving completion",
        "needs_review": "Needs review",
    }.get(raw_status, raw_status.replace("_", " ").title())
    needs_review = trade.get("status") == "needs_review"
    detail = ""
    if raw_status == "pending":
        detail = (
            f"\n-# Proposed {_relative_timestamp(trade.get('created_at'))}. "
            "Nothing is reserved until accepted."
        )
    elif raw_status == "move_needed":
        detail = (
            f"\n-# Different family clans: `{_normalize_tag(trade.get('requester_clan_tag'))}` "
            f"and `{_normalize_tag(trade.get('holder_clan_tag'))}`. Exact cards are reserved."
        )
    elif raw_status in {"ready", "accepted"}:
        detail = "\n-# Same family clan. Finish both in-game requests, then mark complete."
    elif raw_status == "completing":
        detail = "\n-# Saving the tracked collection updates now."
    elif needs_review:
        detail = (
            f"\n-# Review visible until {_relative_timestamp(trade.get('review_expires_at'))}. "
            "Recheck both affected categories manually."
        )
    return (
        f"**{status} with {_escape_markdown(counterpart, limit=50)}** "
        f"· `{_normalize_tag(counterpart_tag)}`\n"
        f"**You give:** {offer} · **You receive:** {receive}\n"
        + detail
    )


def _trades_view(account, trades: list[dict], *, page: int = 0) -> list[Container]:
    tag = _normalize_tag(account.tag)
    pages = max(1, math.ceil(len(trades) / TRADE_VIEW_LIMIT))
    page = min(max(0, page), pages - 1)
    start = page * TRADE_VIEW_LIMIT
    body: list = [
        Text(content="# 🤝 My Card Trades"),
        Text(content=f"**{_escape_markdown(account.name)}** · `{tag}`"),
        Separator(divider=True),
    ]
    shown = trades[start:start + TRADE_VIEW_LIMIT]
    if not shown:
        body.append(Text(content=(
            "No open proposals or accepted swaps for this account. Find a "
            "specific missing card to propose a family-wide swap."
        )))
    for trade in shown:
        role = "requester" if _normalize_tag(trade.get("requester_tag")) == tag else "holder"
        status = trade.get("status")
        body.append(Text(content=_trade_summary(trade, role=role)))
        buttons: list[Button] = []
        if status == "pending" and role == "holder":
            buttons.extend([
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"cards_trade_accept:{trade['_id']}",
                    label="Accept",
                    emoji="✅",
                ),
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"cards_trade_decline:{trade['_id']}",
                    label="Decline",
                    emoji="✖️",
                ),
            ])
        elif status == "pending":
            buttons.append(Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_trade_cancel:{trade['_id']}",
                label="Cancel request",
                emoji="✖️",
            ))
        elif status == "move_needed":
            buttons.append(Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"cards_trade_ready:{trade['_id']}",
                label="Check clans",
                emoji="🏠",
            ))
            buttons.append(Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_trade_cancel:{trade['_id']}",
                label="Cancel swap",
                emoji="✖️",
            ))
        elif status in {"ready", "accepted"}:
            buttons.append(Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"cards_trade_complete:{trade['_id']}",
                label="Trade completed",
                emoji="✅",
            ))
            buttons.append(Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_trade_cancel:{trade['_id']}",
                label="Cancel",
                emoji="✖️",
            ))
        elif status in {"reserving", "completing"}:
            buttons.append(Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trade_complete:{trade['_id']}",
                label=(
                    "Accepting proposal..."
                    if status == "reserving"
                    else "Saving completion..."
                ),
                emoji="⏳",
                is_disabled=True,
            ))
        if buttons:
            body.append(ActionRow(components=buttons))
        body.append(Separator(divider=False))
    if pages > 1:
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trades:{tag}|{page - 1}",
                label="Previous",
                is_disabled=page == 0,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trades:{tag}|{page}",
                label=f"Page {page + 1}/{pages}",
                is_disabled=True,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trades:{tag}|{page + 1}",
                label="Next",
                is_disabled=page >= pages - 1,
            ),
        ]))
    body.extend([
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{tag}",
                label="Dashboard",
                emoji="⬅️",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trades:{tag}",
                label="Refresh",
                emoji="🔄",
            ),
        ]),
        Media(items=[MediaItem(media=FOOTER)]),
    ])
    return [Container(accent_color=RED_ACCENT, components=body)]


def _trade_feedback(title: str, description: str, tag: str) -> list[Container]:
    tag = _normalize_tag(tag)
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content=f"# {title}"),
            Text(content=description),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_trades:{tag}",
                    label="My trades",
                    emoji="🤝",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}",
                    label="Dashboard",
                    emoji="⬅️",
                ),
            ]),
            Media(items=[MediaItem(media=FOOTER)]),
        ],
    )]


async def _load_trade_actor(
    ctx,
    trade: dict,
    *,
    role: str,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    expected_id = trade.get(f"{role}_discord_id")
    if expected_id is None or int(expected_id) != int(ctx.user.id):
        return None, None, _notice(
            "That trade action is not yours",
            "Open **My trades** from your own `/cards` dashboard.",
        )
    return await _load_target(
        ctx,
        trade.get(f"{role}_tag"),
        coc_client=coc_client,
        mongo=mongo,
    )


async def _expire_trade_if_needed(
    mongo: MongoClient,
    trade: dict,
    *,
    bot: hikari.GatewayBot | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    if trade.get("status") == "reserving":
        reservation_until = as_utc(trade.get("reservation_until"))
        if reservation_until is None or reservation_until > now:
            return trade
        result = await mongo.card_trades.update_one(
            {
                "_id": trade["_id"],
                "status": "reserving",
                "reservation_token": trade.get("reservation_token"),
                "reservation_until": {"$lte": now},
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": now,
                    "last_error": "acceptance_recovered",
                    **_cleanup_fields(trade),
                },
                "$unset": {"reservation_token": "", "reservation_until": ""},
            },
        )
        if getattr(result, "modified_count", 0):
            await _finish_trade_cleanup(
                mongo, trade, owner=_reservation_owner(trade)
            )
        return await mongo.card_trades.find_one({"_id": trade["_id"]}) or trade

    expires_at = as_utc(trade.get("expires_at"))
    if trade.get("status") != "completing" or (
        expires_at is not None and expires_at > now
    ):
        return trade
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": trade["status"], "expires_at": {"$lte": now}},
        {
            "$set": {
                "status": "needs_review",
                "updated_at": now,
                "failure": "completion_expired",
                "review_expires_at": now + TRADE_REVIEW_FOR,
                **_cleanup_fields(trade),
            },
            "$unset": {"open_proposal_key": ""},
        },
    )
    if getattr(result, "modified_count", 0):
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        if bot is not None:
            trade["status"] = "needs_review"
            await asyncio.gather(
                _notify_review_participants(
                    bot,
                    trade,
                    "Completion expired before it could be confirmed. Recheck "
                    "and correct both affected categories.",
                ),
                _update_trade_channel(bot, trade),
            )
    return await mongo.card_trades.find_one({"_id": trade["_id"]}) or trade


async def _apply_trade_inventory_updates(
    mongo: MongoClient,
    trade: dict,
    *,
    now: datetime,
) -> dict[str, bool]:
    """Reload both parties, then conditionally apply each reserved card pair."""
    requester_tag = _normalize_tag(trade["requester_tag"])
    holder_tag = _normalize_tag(trade["holder_tag"])
    owner = _reservation_owner(trade)
    guild_id = int(trade["guild_id"])
    locks = [_inventory_lock(tag) for tag in sorted({requester_tag, holder_tag})]
    for lock in locks:
        await lock.acquire()
    try:
        requester = await mongo.card_inventories.find_one({"_id": requester_tag}) or {}
        holder = await mongo.card_inventories.find_one({"_id": holder_tag}) or {}
        requester_cards = normalize_cards(requester.get("cards"))
        holder_cards = normalize_cards(holder.get("cards"))
        requester_reservations = _card_reservations(requester)
        holder_reservations = _card_reservations(holder)
        requester_fenced = (
            requester.get("guild_id") == guild_id
            and requester_reservations.get(trade["wanted_card_id"]) == owner
            and requester_reservations.get(trade["given_card_id"]) == owner
        )
        holder_fenced = (
            holder.get("guild_id") == guild_id
            and holder_reservations.get(trade["wanted_card_id"]) == owner
            and holder_reservations.get(trade["given_card_id"]) == owner
        )
        # `>=`, not `==`. Copy counts are stored exactly, so a member holding
        # four of the card they are giving away is still a valid giver. An
        # equality test here silently failed completion for precisely the
        # members with the most to trade.
        requester_expected = (
            requester_fenced
            and requester_cards.get(trade["wanted_card_id"], OWNED) == MISSING
            and requester_cards.get(trade["given_card_id"], OWNED) >= DUPLICATE
        )
        holder_expected = (
            holder_fenced
            and holder_cards.get(trade["wanted_card_id"], OWNED) >= DUPLICATE
            and holder_cards.get(trade["given_card_id"], OWNED) == MISSING
        )

        if not (requester_expected and holder_expected):
            return {
                "requester": False,
                "holder": False,
                "requester_prevalidated": requester_expected,
                "holder_prevalidated": holder_expected,
            }

        requester_updated = False
        requester_result = await mongo.card_inventories.update_one(
                {
                    "_id": requester_tag,
                    "guild_id": guild_id,
                    "$and": [
                        {"$or": [
                            {f"card_trade_reservations.{trade['wanted_card_id']}": owner},
                            {f"card_trade_reservations.{trade['wanted_card_id']}.owner": owner},
                        ]},
                        {"$or": [
                            {f"card_trade_reservations.{trade['given_card_id']}": owner},
                            {f"card_trade_reservations.{trade['given_card_id']}.owner": owner},
                        ]},
                    ],
                    f"cards.{trade['wanted_card_id']}": MISSING,
                    f"cards.{trade['given_card_id']}": {"$gte": DUPLICATE},
                },
                {"$set": {
                    f"cards.{trade['wanted_card_id']}": OWNED,
                    "updated_at": now,
                    "update_source": "confirmed_trade",
                }, "$inc": {
                    # Give away one copy, not every spare copy. Setting this to
                    # OWNED would drop a member holding five down to one.
                    f"cards.{trade['given_card_id']}": -1,
                    "inventory_revision": 1,
                }},
        )
        requester_updated = bool(getattr(requester_result, "modified_count", 0))

        holder_updated = False
        holder_result = await mongo.card_inventories.update_one(
                {
                    "_id": holder_tag,
                    "guild_id": guild_id,
                    "$and": [
                        {"$or": [
                            {f"card_trade_reservations.{trade['wanted_card_id']}": owner},
                            {f"card_trade_reservations.{trade['wanted_card_id']}.owner": owner},
                        ]},
                        {"$or": [
                            {f"card_trade_reservations.{trade['given_card_id']}": owner},
                            {f"card_trade_reservations.{trade['given_card_id']}.owner": owner},
                        ]},
                    ],
                    f"cards.{trade['wanted_card_id']}": {"$gte": DUPLICATE},
                    f"cards.{trade['given_card_id']}": MISSING,
                },
                {"$set": {
                    f"cards.{trade['given_card_id']}": OWNED,
                    "updated_at": now,
                    "update_source": "confirmed_trade",
                }, "$inc": {
                    f"cards.{trade['wanted_card_id']}": -1,
                    "inventory_revision": 1,
                }},
        )
        holder_updated = bool(getattr(holder_result, "modified_count", 0))
        return {
            "requester": requester_updated,
            "holder": holder_updated,
            "requester_prevalidated": requester_expected,
            "holder_prevalidated": holder_expected,
        }
    finally:
        for lock in reversed(locks):
            lock.release()


async def _write_one_card(
    mongo: MongoClient,
    account,
    inventory: dict,
    card_id: str,
    mode: str,
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    """Apply one confirmed transition with revision and exact-card guards."""
    card = CARD_BY_ID.get(card_id)
    action = QUICK_CARD_ACTIONS.get(mode)
    if card is None or action is None:
        raise ValueError("unknown quick card update")
    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        if _inventory_revision_value(latest) != int(expected_revision):
            raise InventoryWriteConflict
        if card_id in _card_reservations(latest):
            raise ActiveCardTradeError
        problem = _quick_transition_problem(latest, card_id, mode)
        if problem:
            raise InvalidCardTransitionError(problem)

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "quick_card_update",
            # "Used a spare" means one copy left, not all of them. The action
            # table's flat target of OWNED was written when two was the ceiling;
            # with real counts it would drop a member holding five down to one.
            f"cards.{card_id}": (
                max(OWNED, normalize_status(
                    normalize_cards(latest.get("cards")).get(card_id, OWNED)
                ) - 1)
                if mode == "used"
                else int(action["to"])
            ),
        }
        if guild_id is not None:
            identity["guild_id"] = guild_id
        revision_guard = (
            {"$or": [
                {"inventory_revision": {"$exists": False}},
                {"inventory_revision": 0},
            ]}
            if expected_revision == 0
            else {"inventory_revision": int(expected_revision)}
        )
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [
                    revision_guard,
                    {"$or": [
                        {f"card_trade_reservations.{card_id}": {"$exists": False}},
                        {
                            f"card_trade_reservations.{card_id}.until": {
                                "$lte": now,
                            },
                        },
                    ]},
                ],
            },
            {
                "$set": identity,
                "$pull": {"scan_duplicate_unverified_card_ids": card_id},
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 1):
            return await mongo.card_inventories.find_one({"_id": tag}) or {}
        current = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if card_id in _card_reservations(current):
            raise ActiveCardTradeError
        raise InventoryWriteConflict


async def _write_card_state(
    mongo: MongoClient,
    account,
    inventory: dict,
    card_id: str,
    target: int,
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    """Set one card to an absolute state, with the same guards as a step.

    Absolute set replaces the increment/decrement/keep family. Setting a card
    to a state it already holds is a no-op rather than an error, so a stale
    control cannot double-apply and there are no unreachable transitions: the
    old table had no edge from missing straight to spare.
    """
    card = CARD_BY_ID.get(card_id)
    if card is None or not (MISSING <= int(target) <= MAX_COPIES):
        raise ValueError("unknown card state update")
    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        if _inventory_revision_value(latest) != int(expected_revision):
            raise InventoryWriteConflict
        if card_id in _card_reservations(latest):
            raise ActiveCardTradeError

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "card_set",
            f"cards.{card_id}": int(target),
        }
        if guild_id is not None:
            identity["guild_id"] = guild_id
        revision_guard = (
            {"$or": [
                {"inventory_revision": {"$exists": False}},
                {"inventory_revision": 0},
            ]}
            if expected_revision == 0
            else {"inventory_revision": int(expected_revision)}
        )
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [
                    revision_guard,
                    {"$or": [
                        {f"card_trade_reservations.{card_id}": {"$exists": False}},
                        {
                            f"card_trade_reservations.{card_id}.until": {
                                "$lte": now,
                            },
                        },
                    ]},
                ],
            },
            {
                "$set": identity,
                "$pull": {"scan_duplicate_unverified_card_ids": card_id},
                # A number the member entered is exact. The scanner's spares are
                # a floor, so only member writes land here, and only cards in
                # this list drop the "+" from their badge.
                "$addToSet": {"count_confirmed_card_ids": card_id},
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 1):
            return await mongo.card_inventories.find_one({"_id": tag}) or {}
        current = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if card_id in _card_reservations(current):
            raise ActiveCardTradeError
        raise InventoryWriteConflict


async def _write_hidden_badge_batch(
    mongo: MongoClient,
    account,
    inventory: dict,
    batch: list[str],
    selected: list[str],
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    """Resolve one global hidden-badge batch without touching other cards."""
    pending = set(_scan_unverified_ids(inventory))
    batch_ids = _ordered_card_ids(batch)
    selected_ids = set(selected)
    if (
        not batch_ids
        or len(batch_ids) > HIDDEN_BADGE_BATCH_SIZE
        or not set(batch_ids) <= pending
        or not selected_ids <= set(batch_ids)
    ):
        raise ValueError("invalid hidden badge batch")

    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        if _inventory_revision_value(latest) != int(expected_revision):
            raise InventoryWriteConflict
        if not set(batch_ids) <= set(_scan_unverified_ids(latest)):
            raise InventoryWriteConflict
        if set(batch_ids) & set(_card_reservations(latest)):
            raise ActiveCardTradeError

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "hidden_badge_review",
        }
        if guild_id is not None:
            identity["guild_id"] = guild_id
        card_updates = {
            f"cards.{card_id}": (
                DUPLICATE if card_id in selected_ids else OWNED
            )
            for card_id in batch_ids
        }
        revision_guard = (
            {"$or": [
                {"inventory_revision": {"$exists": False}},
                {"inventory_revision": 0},
            ]}
            if expected_revision == 0
            else {"inventory_revision": int(expected_revision)}
        )
        reservation_guards = [
            {"$or": [
                {f"card_trade_reservations.{card_id}": {"$exists": False}},
                {
                    f"card_trade_reservations.{card_id}.until": {
                        "$lte": now,
                    },
                },
            ]}
            for card_id in batch_ids
        ]
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [revision_guard, *reservation_guards],
            },
            {
                "$set": identity | card_updates,
                "$pull": {
                    "scan_duplicate_unverified_card_ids": {"$in": batch_ids},
                },
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 1):
            return await mongo.card_inventories.find_one({"_id": tag}) or {}
        current = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if set(batch_ids) & set(_card_reservations(current)):
            raise ActiveCardTradeError
        raise InventoryWriteConflict


async def _write_category(
    mongo: MongoClient,
    account,
    inventory: dict,
    category_id: str,
    selected: list[str],
    *,
    mode: str,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        for _attempt in range(5):
            latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
            if _category_has_reservations(latest, category_id):
                raise ActiveCardTradeError
            updated_cards = apply_category_selection(
                latest.get("cards"),
                category_id,
                selected,
                mode=mode,
            )
            now = datetime.now(timezone.utc)
            existing_steps = set(latest.get("reviewed_lists") or ())
            if mode == "baseline":
                new_steps = {
                    f"{category_id}:missing",
                    f"{category_id}:duplicates",
                }
            else:
                new_steps = {f"{category_id}:{mode}"}
            reviewed_after = existing_steps | new_steps
            category_complete = {
                f"{category_id}:missing",
                f"{category_id}:duplicates",
            } <= reviewed_after
            card_updates = {
                f"cards.{card.id}": updated_cards[card.id]
                for card in CATEGORY_CARDS[category_id]
            }
            identity_updates = {
                "discord_id": int(discord_id),
                "player_name": account.name,
                "clan_tag": (
                    _normalize_tag(account.clan_tag) if account.clan_tag else None
                ),
                "clan_name": account.clan_name,
                "updated_at": now,
                "confirmed_at": now,
                "update_source": "quick_select",
            }
            if guild_id is not None:
                identity_updates["guild_id"] = guild_id
            add_to_set: dict = {
                "reviewed_lists": {"$each": sorted(new_steps)},
            }
            if category_complete:
                add_to_set["complete_categories"] = category_id
            try:
                revision = max(0, int(latest.get("inventory_revision", 0)))
            except (TypeError, ValueError):
                revision = 0
            revision_guard: dict
            if revision == 0:
                revision_guard = {"$or": [
                    {"inventory_revision": {"$exists": False}},
                    {"inventory_revision": 0},
                ]}
            else:
                revision_guard = {"inventory_revision": revision}
            update_document: dict = {
                "$set": card_updates | identity_updates,
                "$addToSet": add_to_set,
                "$inc": {"inventory_revision": 1},
            }
            if mode in {"duplicates", "baseline"}:
                update_document["$pull"] = {
                    "scan_duplicate_unverified_card_ids": {
                        "$in": [card.id for card in CATEGORY_CARDS[category_id]],
                    },
                }
            result = await mongo.card_inventories.update_one(
                {
                    "_id": tag,
                    "$and": [
                        *(
                            {"$or": [
                                {
                                    f"card_trade_reservations.{card.id}": {
                                        "$exists": False,
                                    },
                                },
                                {
                                    f"card_trade_reservations.{card.id}.until": {
                                        "$lte": now,
                                    },
                                },
                            ]}
                            for card in CATEGORY_CARDS[category_id]
                        ),
                        revision_guard,
                    ],
                },
                update_document,
            )
            if getattr(result, "matched_count", 1):
                return await mongo.card_inventories.find_one({"_id": tag}) or {}
            current = await mongo.card_inventories.find_one({"_id": tag}) or {}
            if _category_has_reservations(current, category_id):
                raise ActiveCardTradeError
        raise InventoryWriteConflict


def _inventory_revision_value(inventory: dict) -> int:
    try:
        return max(0, int(inventory.get("inventory_revision", 0)))
    except (TypeError, ValueError):
        return 0


async def _write_scan_draft(
    mongo: MongoClient,
    account,
    draft: dict,
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    """Atomically replace one unreserved inventory after explicit review."""
    if not _scan_draft_confirmable(draft):
        raise ValueError("screenshot draft is incomplete")
    raw_states = draft.get("card_states") or {}
    card_states = {
        card_id: _scan_card_state(raw_states.get(card_id))
        for card_id in CARD_BY_ID
    }
    if any(state is None for state in card_states.values()):
        raise ValueError("screenshot draft contains an invalid card state")

    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if _inventory_revision_value(latest) != int(expected_revision):
            raise ScanDraftStaleError
        if _inventory_has_active_trade(latest):
            raise ActiveCardTradeError

        now = datetime.now(timezone.utc)
        revision_guard: dict
        if expected_revision == 0:
            revision_guard = {"$or": [
                {"inventory_revision": {"$exists": False}},
                {"inventory_revision": 0},
            ]}
        else:
            revision_guard = {"inventory_revision": int(expected_revision)}
        no_live_reservation = [
            {"$or": [
                {f"card_trade_reservations.{card_id}": {"$exists": False}},
                {f"card_trade_reservations.{card_id}.until": {"$lte": now}},
            ]}
            for card_id in CARD_BY_ID
        ]
        reviewed_lists = sorted(
            f"{category.id}:{mode}"
            for category in CATEGORIES
            for mode in ("missing", "duplicates")
        )
        duplicate_unverified = _ordered_card_ids(
            draft.get("duplicate_unverified_card_ids") or ()
        )
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
            "clan_tag": _normalize_tag(account.clan_tag) if account.clan_tag else None,
            "clan_name": account.clan_name,
            "cards": card_states,
            "complete_categories": [category.id for category in CATEGORIES],
            "reviewed_lists": reviewed_lists,
            "scan_duplicate_unverified_card_ids": duplicate_unverified,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "confirmed_screenshot_review",
        }
        if guild_id is not None:
            identity["guild_id"] = guild_id
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [revision_guard, *no_live_reservation],
            },
            {"$set": identity, "$inc": {"inventory_revision": 1}},
        )
        if getattr(result, "matched_count", 1):
            return await mongo.card_inventories.find_one({"_id": tag}) or {}

        current = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if _inventory_has_active_trade(current):
            raise ActiveCardTradeError
        raise ScanDraftStaleError


def _is_scan_image_attachment(attachment: object) -> bool:
    media_type = str(getattr(attachment, "media_type", "") or "")
    media_type = media_type.partition(";")[0].strip().casefold()
    if media_type:
        return media_type in {"image/jpeg", "image/png", "image/webp"}
    filename = str(getattr(attachment, "filename", "") or "").casefold()
    return filename.endswith((".jpg", ".jpeg", ".png", ".webp"))


async def _find_card_upload_state(
    mongo: MongoClient,
    discord_id: int,
) -> dict | None:
    """Find the member's one live account-bound upload session."""
    return await mongo.component_state.find_one(
        {
            "type": "cards_scan_upload",
            "user_id": int(discord_id),
            "guild_id": int(_configured_cards_guild_id() or 0),
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        sort=[("created_at", -1)],
    )


async def _send_scan_dm_components(
    bot: hikari.GatewayBot,
    channel_id: int,
    components: list[Container],
):
    return await bot.rest.create_message(
        channel=int(channel_id),
        components=components,
        flags=hikari.MessageFlag.IS_COMPONENTS_V2,
    )


async def _mark_scan_prompt_received(
    bot: hikari.GatewayBot,
    state: dict,
    account,
) -> None:
    channel_id = state.get("upload_prompt_channel_id")
    message_id = state.get("upload_prompt_message_id")
    if channel_id is None or message_id is None:
        return
    try:
        await bot.rest.edit_message(
            channel=int(channel_id),
            message=int(message_id),
            components=_notice(
                "Screenshots received",
                f"The private review for **{_escape_markdown(account.name)}** is below.",
            ),
        )
    except Exception:
        _log.info(
            "card upload prompt edit failed user=%s",
            state.get("user_id"),
        )


async def _handle_card_scan_dm_upload(
    event: hikari.DMMessageCreateEvent,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
    bot: hikari.GatewayBot,
) -> None:
    if not event.is_human:
        return
    user_id = int(event.author_id)
    state = await _find_card_upload_state(mongo, user_id)
    if state is None:
        return
    session_id = str(state.get("_id") or "")
    account_tag = _normalize_tag(state.get("account_tag"))
    usable_until = state.get("usable_until")

    data = await load_accounts(coc_client, user_id, force=True)
    account = _scan_loaded_account(data, account_tag)
    if account is None:
        await _send_scan_dm_components(
            bot,
            int(event.channel_id),
            _notice(
                "I Couldn't Verify That Account",
                "I did not read or retain the attachments. The linked-account "
                "check must succeed before a screenshot can change a collection. "
                "Try sending the screenshots again shortly.",
            ),
        )
        return

    attachments = tuple(getattr(event.message, "attachments", ()) or ())
    images = tuple(
        attachment
        for attachment in attachments
        if _is_scan_image_attachment(attachment)
    )
    if not images:
        await _send_scan_dm_components(
            bot,
            int(event.channel_id),
            _scan_upload_problem(
                account,
                session_id,
                "Attach the Collection Screenshots",
                "Use Discord's **+** button, select every screenshot together, "
                "then send them in this DM. PNG, JPEG, and still WebP images work.",
                usable_until=usable_until,
            ),
        )
        return
    if len(images) > CARD_SCAN_MAX_UPLOAD_ATTACHMENTS:
        await _send_scan_dm_components(
            bot,
            int(event.channel_id),
            _scan_upload_problem(
                account,
                session_id,
                "Too Many Images at Once",
                f"Send at most {CARD_SCAN_MAX_UPLOAD_ATTACHMENTS} screenshots in one "
                "message. Five clean images normally cover the collection.",
                usable_until=usable_until,
            ),
        )
        return
    if len(images) != len(attachments):
        await _send_scan_dm_components(
            bot,
            int(event.channel_id),
            _scan_upload_problem(
                account,
                session_id,
                "Send Only Screenshot Images",
                f"I found {len(images)} supported image"
                f"{'s' if len(images) != 1 else ''} and "
                f"{len(attachments) - len(images)} other file"
                f"{'s' if len(attachments) - len(images) != 1 else ''}. "
                "Remove the other files and send the screenshots again.",
                usable_until=usable_until,
            ),
        )
        return
    oversized = [
        attachment
        for attachment in images
        if int(getattr(attachment, "size", 0) or 0) > CARD_SCAN_MAX_IMAGE_BYTES
    ]
    total_size = sum(int(getattr(item, "size", 0) or 0) for item in images)
    if oversized or total_size > CARD_SCAN_MAX_BATCH_BYTES:
        await _send_scan_dm_components(
            bot,
            int(event.channel_id),
            _scan_upload_problem(
                account,
                session_id,
                "Those Screenshots Are Too Large",
                "Each image must be 10 MB or smaller and the complete message must "
                "be 50 MB or smaller. Discord received the files, but the bot did "
                "not read or retain them.",
                usable_until=usable_until,
            ),
        )
        return

    lock = _card_upload_lock(user_id)
    finished = False
    async with lock:
        # The session may have been canceled or replaced while account profiles
        # loaded. Re-read its exact id before downloading private attachments.
        latest = await get_state(mongo, session_id)
        if (
            not isinstance(latest, dict)
            or latest.get("type") != "cards_scan_upload"
            or int(latest.get("user_id", 0) or 0) != user_id
            or _normalize_tag(latest.get("account_tag")) != account_tag
        ):
            await _send_scan_dm_components(
                bot,
                int(event.channel_id),
                _notice(
                    "That Upload Has Closed",
                    "No attachment was read. Start a new scan from `/cards` in the "
                    "family server.",
                ),
            )
            return
        state = latest
        usable_until = state.get("usable_until")
        prior_draft = (
            state.get("scan_draft")
            if isinstance(state.get("scan_draft"), dict)
            else None
        )
        accepted_before = (
            CARD_SCAN_CAPTURE_COUNT - len(_scan_missing_page_numbers(prior_draft))
            if prior_draft is not None
            else 0
        )

        payloads: list[bytes] = []
        async with _card_scan_slots:
            try:
                payloads = list(await asyncio.gather(
                    *(attachment.read() for attachment in images)
                ))
            except Exception:
                _log.exception("card DM screenshot download failed user=%s", user_id)
                await _send_scan_dm_components(
                    bot,
                    int(event.channel_id),
                    _scan_upload_problem(
                        account,
                        session_id,
                        "I Couldn't Read Those Screenshots",
                        "Nothing was saved. Send the images again in one message.",
                        usable_until=usable_until,
                    ),
                )
                return
            try:
                draft = await asyncio.to_thread(
                    _scan_collection_payloads,
                    tuple(payloads),
                    prior_draft=prior_draft,
                )
            finally:
                for index in range(len(payloads)):
                    payloads[index] = b""
                payloads.clear()

        if _scan_strings(draft.get("errors"), limit=1):
            preserved = (
                "Your previously matched pages are still saved. "
                if prior_draft is not None
                else ""
            )
            await _send_scan_dm_components(
                bot,
                int(event.channel_id),
                _scan_upload_problem(
                    account,
                    session_id,
                    "I Couldn't Process Those Screenshots",
                    f"{preserved}Send this same set again; no collection was changed.",
                    usable_until=usable_until,
                ),
            )
            return

        missing_pages = _scan_missing_page_numbers(draft)
        update = {
            "scan_draft": draft,
            "last_upload_at": datetime.now(timezone.utc),
        }
        result = await update_state(
            mongo,
            {
                "_id": session_id,
                "type": "cards_scan_upload",
                "user_id": user_id,
                "guild_id": int(state.get("guild_id", 0) or 0),
                "account_tag": account_tag,
            },
            {"$set": update},
        )
        if not getattr(result, "matched_count", 1):
            await _send_scan_dm_components(
                bot,
                int(event.channel_id),
                _notice(
                    "That Upload Has Closed",
                    "Nothing was saved. Start a new scan from `/cards` in the "
                    "family server.",
                ),
            )
            return

        if missing_pages:
            components = _scan_upload_progress(
                account,
                session_id,
                draft,
                usable_until=usable_until,
                accepted_before=accepted_before,
            )
        else:
            inventory = await _ensure_inventory(
                mongo,
                account,
                discord_id=user_id,
                guild_id=int(state.get("guild_id", 0) or 0),
            )
            components = await _scan_review_view(
                account,
                inventory,
                session_id,
                draft,
                usable_until=usable_until,
            )
            finished = True

        await _send_scan_dm_components(bot, int(event.channel_id), components)
        if finished:
            await update_state(
                mongo,
                {
                    "_id": session_id,
                    "type": "cards_scan_upload",
                    "user_id": user_id,
                },
                {"$set": {"type": "cards_scan_draft"}},
            )
            await _mark_scan_prompt_received(bot, state, account)

    if finished and _card_upload_locks.get(user_id) is lock:
        _card_upload_locks.pop(user_id, None)


@loader.listener(hikari.DMMessageCreateEvent)
@lightbulb.di.with_di
async def cards_scan_dm_upload(
    event: hikari.DMMessageCreateEvent,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Consume screenshots only while the member has a live upload session."""
    await _handle_card_scan_dm_upload(
        event,
        coc_client=coc_client,
        mongo=mongo,
        bot=bot,
    )


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def prepare_card_inventory_storage(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Install only the indexes used by the 500-player matching queries."""
    if _configured_cards_guild_id() is None:
        _log.critical(
            "Card Hub disabled: CARDS_GUILD_ID must be a valid Discord server ID"
        )
    if _configured_cards_channel_id() is None:
        _log.warning(
            "Card Hub trade-board posting disabled: CARDS_CHANNEL_ID is not configured"
        )
    try:
        await mongo.component_state.create_index(
            [("type", 1), ("user_id", 1), ("created_at", -1)],
            name="idx_component_card_upload_user",
        )
        await mongo.card_inventories.create_index(
            [("guild_id", 1), ("confirmed_at", -1)],
            name="idx_card_inventories_guild_confirmed",
        )
        await mongo.card_inventories.create_index(
            "discord_id",
            name="idx_card_inventories_discord",
        )
        await mongo.card_trades.create_index(
            "lease_expires_at",
            expireAfterSeconds=0,
            name="ttl_card_trade_leases",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("guild_id", 1), ("requester_tag", 1),
             ("status", 1), ("updated_at", -1)],
            name="idx_card_trades_requester",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("guild_id", 1), ("holder_tag", 1),
             ("status", 1), ("updated_at", -1)],
            name="idx_card_trades_holder",
        )
        await mongo.card_trades.create_index(
            "open_proposal_key",
            unique=True,
            sparse=True,
            name="uniq_open_card_proposal",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("status", 1), ("reservation_until", 1)],
            name="idx_card_trades_reserving",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("status", 1), ("expires_at", 1)],
            name="idx_card_trades_completing",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("trade_id", 1), ("owner_token", 1)],
            name="idx_card_trade_lease_owner",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("guild_id", 1), ("player_tag", 1)],
            name="idx_card_proposal_slots",
        )
        await mongo.card_trades.create_index(
            [("kind", 1), ("guild_id", 1), ("cleanup_pending", 1)],
            name="idx_card_trade_cleanup",
        )
    except Exception:
        # A temporary/no-index-permission Mongo problem must not stop the rest
        # of the bot. At family scale a collection scan still remains bounded.
        _log.exception("card inventory indexes unavailable")
    guild_id = _configured_cards_guild_id()
    if guild_id is not None:
        try:
            now = datetime.now(timezone.utc)
            await _reconcile_proposal_slots(
                mongo, guild_id=guild_id, now=now
            )
            await _reconcile_trade_cleanups(mongo, guild_id=guild_id)
            await _recover_stalled_reservations(
                mongo, now=now, guild_id=guild_id
            )
        except Exception:
            _log.exception("card trade reservation recovery unavailable")


@loader.command
class Cards(
    lightbulb.SlashCommand,
    name="cards",
    description="Update your Clash card collection and find family trades",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        scope_error = _guild_scope_error(ctx)
        if scope_error:
            await ctx.respond(scope_error, ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        data = await load_accounts(coc_client, int(ctx.user.id), force=True)
        entries = _loaded_entries(data)
        if len(entries) != 1:
            components = _account_picker(data)
        else:
            account = entries[0].account
            inventory = await _ensure_inventory(
                mongo,
                account,
                discord_id=int(ctx.user.id),
                guild_id=_guild_id(ctx),
            )
            components = await _dashboard_view(
                account, inventory, account_count=1
            )
        await ctx.interaction.edit_initial_response(components=components)


@register_action("cards_account_page")
@lightbulb.di.with_di
async def cards_account_page(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    data = await load_accounts(coc_client, int(ctx.user.id))
    return _account_picker(data, _parse_page(action_id))


@register_action("cards_account_select")
@lightbulb.di.with_di
async def cards_account_select(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Open the collection for the account chosen from the picker."""
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    values = list(getattr(ctx.interaction, "values", ()) or ())
    account, data = await _owned_account(
        coc_client, int(ctx.user.id), _normalize_tag(values[0] if values else "")
    )
    if account is None:
        return _account_picker(data)
    inventory = await _ensure_inventory(
        mongo,
        account,
        discord_id=int(ctx.user.id),
        guild_id=_guild_id(ctx),
    )
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data))
    )


@register_action("cards_scan_start")
@lightbulb.di.with_di
async def cards_scan_start(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx,
        action_id,
        coc_client=coc_client,
        mongo=mongo,
    )
    if problem:
        return problem

    user_id = int(ctx.user.id)
    guild_id = int(_guild_id(ctx) or 0)
    session_id = f"cards_upload_{secrets.token_urlsafe(12)}"
    usable_until = datetime.now(timezone.utc) + CARD_SCAN_DRAFT_FOR
    document = {
        "_id": session_id,
        "type": "cards_scan_upload",
        "user_id": user_id,
        "guild_id": guild_id,
        "account_tag": _normalize_tag(account.tag),
        "base_revision": _inventory_revision_value(inventory),
        "usable_until": usable_until,
    }
    lock = _card_upload_lock(user_id)
    async with lock:
        try:
            # Serialize replacement with DM processing so rapid double-clicks
            # cannot leave two current sessions for one member.
            await mongo.component_state.delete_many({
                "type": "cards_scan_upload",
                "user_id": user_id,
            })
            await insert_state(mongo, document, ttl=CARD_SCAN_DRAFT_FOR)
            channel = await bot.rest.create_dm_channel(user_id)
            prompt = await _send_scan_dm_components(
                bot,
                int(channel.id),
                _scan_upload_prompt(
                    account,
                    session_id,
                    usable_until=usable_until,
                ),
            )
        except Exception as exc:
            _log.info(
                "card private upload unavailable user=%s error=%s",
                user_id,
                type(exc).__name__,
            )
            await _discard_scan_state(mongo, session_id)
            return _scan_dm_unavailable(account)

        try:
            await update_state(
                mongo,
                {
                    "_id": session_id,
                    "type": "cards_scan_upload",
                    "user_id": user_id,
                },
                {"$set": {
                    "upload_prompt_channel_id": int(channel.id),
                    "upload_prompt_message_id": int(prompt.id),
                }},
            )
        except Exception:
            # The session itself is already durable and usable. Failing to
            # remember the prompt id only leaves its Cancel button visible.
            _log.exception("card upload prompt id storage failed user=%s", user_id)
    return _scan_upload_started(account, usable_until=usable_until)


@register_action("cards_upload_cancel", requires_state=True)
@lightbulb.di.with_di
async def cards_upload_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    type: object = None,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    if type != "cards_scan_upload":
        return _notice(
            "Upload Already Finished",
            "The screenshots already moved to review. Use the review's Save or "
            "Cancel button instead.",
        )
    await _discard_scan_state(mongo, action_id)
    discord_id = int(ctx.user.id)
    lock = _card_upload_locks.get(discord_id)
    if lock is not None and not lock.locked():
        _card_upload_locks.pop(discord_id, None)
    return _notice(
        "Upload Canceled",
        "No collection was changed, and the bot retained no raw screenshot files.",
    )


async def _load_scan_bound_account(
    ctx,
    action_id: str,
    account_tag: object,
    *,
    usable_until: object,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    """Reload and verify the selected linked profile before draft access."""
    data = await load_accounts(coc_client, int(ctx.user.id), force=True)
    account = _scan_loaded_account(data, account_tag)
    if account is None:
        return None, None, data, _scan_accounts_problem(
            data,
            action_id,
            has_draft=True,
            usable_until=usable_until,
            account_tag=account_tag,
        )
    if _guild_id(ctx) is None:
        inventory = await _ensure_inventory(
            mongo,
            account,
            discord_id=int(ctx.user.id),
            guild_id=_configured_cards_guild_id(),
        )
        return account, inventory, data, None
    account, inventory, problem = await _load_target(
        ctx,
        _normalize_tag(account_tag),
        coc_client=coc_client,
        mongo=mongo,
    )
    return account, inventory, data, problem


@register_action("cards_scan_accounts_retry", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_accounts_retry(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    scan_draft: object = None,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    data = await load_accounts(coc_client, int(ctx.user.id), force=True)
    has_draft = isinstance(scan_draft, dict)
    account = _scan_loaded_account(data, account_tag)
    if account is None:
        return _scan_accounts_problem(
            data,
            action_id,
            has_draft=has_draft,
            usable_until=usable_until,
            account_tag=account_tag,
        )
    if not has_draft:
        return _notice(
            "Screenshot Review Unavailable",
            "Start a new scan from `/cards` in the family server.",
        )
    if account is not None:
        inventory = await _ensure_inventory(
            mongo,
            account,
            discord_id=int(ctx.user.id),
            guild_id=int(guild_id),
        )
        return await _scan_review_view(
            account,
            inventory,
            action_id,
            scan_draft,
            usable_until=usable_until,
        )
    return _notice(
        "That Account Is No Longer Linked",
        "Nothing was shown or changed. Start a new scan from `/cards` in the "
        "family server.",
    )


@register_action("cards_scan_retry_cancel", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_retry_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    await _discard_scan_state(mongo, action_id)
    return _notice(
        "Screenshot import canceled",
        "The bot did not retain the raw image files and no scan result was saved.",
    )


async def _scan_fix_unknown(
    ctx,
    action_id: str,
    *,
    chosen_state: int,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object,
    usable_until: object,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    if not _scan_draft_correctable(scan_draft):
        return _notice(
            "This scan needs new screenshots",
            "Only fully identified cards can be corrected here. Nothing was saved.",
        )
    unknown = _ordered_card_ids(scan_draft.get("unknown_card_ids") or ())
    if not unknown:
        return _notice("No uncertain card remains", "Return to the review and save when ready.")
    card_id = unknown[0]
    revised = dict(scan_draft)
    states = dict(revised.get("card_states") or {})
    confidences = dict(revised.get("card_confidences") or {})
    warnings = dict(revised.get("card_warnings") or {})
    states[card_id] = chosen_state
    confidences[card_id] = 1.0
    warnings[card_id] = ["member_corrected"]
    revised["card_states"] = states
    revised["card_confidences"] = confidences
    revised["card_warnings"] = warnings
    revised["unknown_card_ids"] = [item for item in unknown if item != card_id]
    revised["duplicate_unverified_card_ids"] = [
        item
        for item in _ordered_card_ids(
            revised.get("duplicate_unverified_card_ids") or ()
        )
        if item != card_id
    ]
    result = await update_state(
        mongo,
        {
            "_id": action_id,
            "type": "cards_scan_draft",
            "user_id": int(ctx.user.id),
            "guild_id": int(guild_id),
            "scan_draft.unknown_card_ids": unknown,
        },
        {"$set": {"scan_draft": revised}},
    )
    latest = await get_state(mongo, action_id)
    if latest is None:
        return _notice(
            "Screenshot draft expired",
            "Nothing was saved. Start a new scan from `/cards` in the family server.",
        )
    latest_draft = latest.get("scan_draft")
    if not isinstance(latest_draft, dict):
        return _notice("Screenshot draft unavailable", "Nothing was saved.")
    # A concurrent click may win the compare-and-set. Always show the database
    # winner instead of overwriting it with this interaction's stale draft.
    del result
    account, inventory, _data, target_problem = await _load_scan_bound_account(
        ctx,
        action_id,
        account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    return await _scan_review_view(
        account,
        inventory,
        action_id,
        latest_draft,
        usable_until=usable_until,
    )


@register_action("cards_scan_fix_missing", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_fix_missing(
    ctx,
    action_id: str,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_fix_unknown(
        ctx,
        action_id,
        chosen_state=MISSING,
        scan_draft=scan_draft,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_fix_owned", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_fix_owned(
    ctx,
    action_id: str,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_fix_unknown(
        ctx,
        action_id,
        chosen_state=OWNED,
        scan_draft=scan_draft,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_fix_duplicate", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_fix_duplicate(
    ctx,
    action_id: str,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_fix_unknown(
        ctx,
        action_id,
        chosen_state=DUPLICATE,
        scan_draft=scan_draft,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_cancel", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    await _discard_scan_state(mongo, action_id)
    if _guild_id(ctx) is None:
        return _notice(
            "Screenshot Import Canceled",
            "Nothing was saved. Run `/cards` in the family server to return to "
            "your collection dashboard.",
        )
    if account_tag:
        account, inventory, target_problem = await _load_target(
            ctx,
            _normalize_tag(account_tag),
            coc_client=coc_client,
            mongo=mongo,
        )
        if target_problem:
            return target_problem
        data = await load_accounts(coc_client, int(ctx.user.id))
        return await _dashboard_view(
            account, inventory, account_count=len(_loaded_entries(data))
        )
    data = await load_accounts(coc_client, int(ctx.user.id))
    return _account_picker(data)


async def _confirm_scan_draft(
    ctx,
    action_id: str,
    *,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object,
    base_revision: object,
    usable_until: object,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    if not account_tag:
        return _notice(
            "Choose an account first",
            "This draft is not attached to a collection. Re-run `/cards` with all five pages.",
        )
    account, inventory, data, target_problem = await _load_scan_bound_account(
        ctx,
        action_id,
        _normalize_tag(account_tag),
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    if not _scan_draft_confirmable(scan_draft) or base_revision is None:
        return await _scan_review_view(
            account,
            inventory,
            action_id,
            scan_draft,
            usable_until=usable_until,
        )
    if _inventory_has_active_trade(inventory):
        return await _scan_review_view(
            account,
            inventory,
            action_id,
            scan_draft,
            usable_until=usable_until,
        )
    try:
        updated = await _write_scan_draft(
            mongo,
            account,
            scan_draft,
            expected_revision=int(base_revision),
            discord_id=int(ctx.user.id),
            guild_id=int(guild_id),
        )
    except (TypeError, ValueError):
        return await _scan_review_view(
            account,
            inventory,
            action_id,
            scan_draft,
            usable_until=usable_until,
        )
    except ActiveCardTradeError:
        latest = await mongo.card_inventories.find_one({
            "_id": _normalize_tag(account.tag)
        }) or inventory
        return await _scan_review_view(
            account,
            latest,
            action_id,
            scan_draft,
            usable_until=usable_until,
        )
    except ScanDraftStaleError:
        return _notice(
            "Collection changed after this scan",
            "Nothing was overwritten. Start a new scan, or edit the card from the "
            "board.",
        )
    pending = _scan_unverified_ids(updated)
    if pending:
        try:
            await update_state(
                mongo,
                {
                    "_id": action_id,
                    "user_id": int(ctx.user.id),
                    "guild_id": int(guild_id),
                },
                {"$set": {
                    "type": "cards_hidden_badge_review",
                    "base_revision": _inventory_revision_value(updated),
                }},
            )
        except Exception:
            _log.exception("hidden badge session handoff failed draft=%s", action_id)
            await _discard_scan_state(mongo, action_id)
            return _scan_saved_notice(account, pending=len(pending))
        return await _hidden_badge_review_view(
            account, updated, session_id=action_id
        )

    await _discard_scan_state(mongo, action_id)
    if _guild_id(ctx) is None:
        return _scan_saved_notice(account)
    spare_prompt = _spare_counts_panel(account, updated)
    if spare_prompt is not None:
        return spare_prompt
    return await _dashboard_view(
        account, updated, account_count=len(_loaded_entries(data))
    )


@register_action("cards_scan_confirm", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_confirm(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    scan_draft: dict,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    base_revision: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _confirm_scan_draft(
        ctx,
        action_id,
        scan_draft=scan_draft,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        base_revision=base_revision,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


async def _scan_hidden_badge_update(
    ctx,
    action_id: str,
    *,
    selected: list[str],
    single_result: bool | None = None,
    single_missing: bool = False,
    user_id: object,
    guild_id: object,
    account_tag: object,
    usable_until: object,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    if not account_tag:
        return _notice("Review expired", "Open `/cards` and check possible spares.")
    account, inventory, _data, target_problem = await _load_scan_bound_account(
        ctx,
        action_id,
        account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    pending = _scan_unverified_ids(inventory)
    batch = (
        pending[:1]
        if single_result is not None or single_missing
        else pending[:HIDDEN_BADGE_BATCH_SIZE]
    )
    if not batch:
        await _discard_scan_state(mongo, action_id)
        return _scan_saved_notice(account)
    try:
        if single_missing:
            updated = await _write_one_card(
                mongo,
                account,
                inventory,
                batch[0],
                "missing",
                expected_revision=_inventory_revision_value(inventory),
                discord_id=int(ctx.user.id),
                guild_id=int(guild_id),
            )
        else:
            updated = await _write_hidden_badge_batch(
                mongo,
                account,
                inventory,
                batch,
                batch if single_result is True else selected,
                expected_revision=_inventory_revision_value(inventory),
                discord_id=int(ctx.user.id),
                guild_id=int(guild_id),
            )
    except ActiveCardTradeError:
        return _notice(
            "A card is reserved",
            "Finish or cancel its accepted swap, then check possible spares from `/cards`.",
        )
    except (InventoryWriteConflict, InvalidCardTransitionError, ValueError):
        return _notice(
            "Collection changed",
            "Nothing was overwritten. Open `/cards` to see the current collection.",
        )
    if _scan_unverified_ids(updated):
        return await _hidden_badge_review_view(
            account, updated, session_id=action_id
        )
    await _discard_scan_state(mongo, action_id)
    return _scan_saved_notice(account)


@register_action("cards_scan_hidden_no", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_hidden_no(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_hidden_badge_update(
        ctx,
        action_id,
        selected=[],
        single_result=False,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_hidden_yes", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_hidden_yes(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_hidden_badge_update(
        ctx,
        action_id,
        selected=[],
        single_result=True,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_hidden_missing", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_hidden_missing(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _scan_hidden_badge_update(
        ctx,
        action_id,
        selected=[],
        single_missing=True,
        user_id=user_id,
        guild_id=guild_id,
        account_tag=account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_scan_hidden_later", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_hidden_later(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    user_id: object,
    guild_id: object,
    account_tag: object = None,
    usable_until: object = None,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    account, inventory, _data, target_problem = await _load_scan_bound_account(
        ctx,
        action_id,
        account_tag,
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    await _discard_scan_state(mongo, action_id)
    return _scan_saved_notice(account, pending=len(_scan_unverified_ids(inventory)))


@register_action("cards_dashboard")
@lightbulb.di.with_di
async def cards_dashboard(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data))
    )


@register_action("cards_pick")
@lightbulb.di.with_di
async def cards_pick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Open one card from a category menu."""
    tag, _category_id, _page = _parse_editor_category_target(action_id)
    values = list(getattr(ctx.interaction, "values", ()) or ())
    card_id = values[0] if values and values[0] in CARD_BY_ID else None
    if card_id is None:
        return _notice("Card unavailable", "Open `/cards` again.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    return await _card_focus_view(account, inventory, card_id)


@register_action("cards_set")
@lightbulb.di.with_di
async def cards_set(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Set one card to an absolute state."""
    tag, card_id, target = _parse_card_set_target(action_id)
    if card_id is None or target is None:
        return _notice("Card unavailable", "Open `/cards` again.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    try:
        updated = await _write_card_state(
            mongo,
            account,
            inventory,
            card_id,
            target,
            expected_revision=_inventory_revision_value(inventory),
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return await _card_focus_view(
            account,
            inventory,
            card_id,
            saved="This card is reserved and was not changed.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _card_focus_view(
            account,
            current,
            card_id,
            saved="The collection changed, so this view was refreshed.",
        )
    return await _card_focus_view(
        account,
        updated,
        card_id,
        saved=_saved_count_line(CARD_BY_ID[card_id].name, target),
    )


async def _apply_card_count(
    ctx,
    tag: str,
    card_id: str,
    target: int,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
    note: str | None = None,
):
    """Shared tail for every absolute or relative count write."""
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    target = max(MISSING, min(int(target), MAX_COPIES))
    try:
        updated = await _write_card_state(
            mongo,
            account,
            inventory,
            card_id,
            target,
            expected_revision=_inventory_revision_value(inventory),
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return await _card_focus_view(
            account, inventory, card_id,
            saved="This card is reserved and was not changed.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _card_focus_view(
            account, current, card_id,
            saved="The collection changed, so this view was refreshed.",
        )
    return await _card_focus_view(
        account,
        updated,
        card_id,
        saved=note or _saved_count_line(CARD_BY_ID[card_id].name, target),
    )


async def _resolve_hidden_batch(
    ctx,
    tag: str,
    spares: list[str],
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    """Write one whole hidden-badge batch: ticked are spares, rest are singles."""
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    batch = _scan_unverified_ids(inventory)[:HIDDEN_BADGE_BATCH_SIZE]
    if not batch:
        return await _dashboard_view(account, inventory, account_count=1)
    chosen = [card_id for card_id in batch if card_id in set(spares)]
    try:
        updated = await _write_hidden_badge_batch(
            mongo,
            account,
            inventory,
            batch,
            chosen,
            expected_revision=_inventory_revision_value(inventory),
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return _notice(
            "Cards reserved",
            "Finish or cancel the accepted trade before changing these cards.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _dashboard_view(account, current, account_count=1)
    if _scan_unverified_ids(updated):
        return _hidden_badge_review(account, updated)
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, updated, account_count=len(_loaded_entries(data))
    )


@register_action("cards_hidden_pick")
@lightbulb.di.with_di
async def cards_hidden_pick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    values = [
        str(value) for value in (getattr(ctx.interaction, "values", ()) or ())
        if str(value) in CARD_BY_ID
    ]
    return await _resolve_hidden_batch(
        ctx, _normalize_tag(action_id), values,
        coc_client=coc_client, mongo=mongo,
    )


@register_action("cards_hidden_none_of_these")
@lightbulb.di.with_di
async def cards_hidden_none_of_these(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _resolve_hidden_batch(
        ctx, _normalize_tag(action_id), [],
        coc_client=coc_client, mongo=mongo,
    )


@register_action("cards_sort")
@lightbulb.di.with_di
async def cards_sort(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Cycle the card menus between game order, missing first and most copies."""
    tag = _normalize_tag(action_id)
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    chosen = _next_sort(_inventory_sort(inventory))
    await mongo.card_inventories.update_one(
        {"_id": tag}, {"$set": {"card_sort": chosen}}, upsert=True
    )
    inventory = dict(inventory, card_sort=chosen)
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data))
    )


@register_action("cards_step")
@lightbulb.di.with_di
async def cards_step(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Nudge one card's copy count up or down by one."""
    tag, card_id, delta = _parse_card_step_target(action_id)
    if card_id is None or delta == 0:
        return _notice("Card unavailable", "Open `/cards` again.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    current = normalize_cards(inventory.get("cards")).get(card_id, OWNED)
    return await _apply_card_count(
        ctx,
        tag,
        card_id,
        current + delta,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_count", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_count(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
):
    tag, card_id, _target = _parse_card_set_target(f"{action_id}|0")
    if card_id is None:
        await ctx.respond(
            components=_notice("Card unavailable", "Open `/cards` again."),
            ephemeral=True,
        )
        return
    await ctx.respond_with_modal(
        title=f"How many {CARD_BY_ID[card_id].name}?"[:45],
        custom_id=f"cards_count_submit:{tag}|{card_id}",
        components=[ModalActionRow().add_text_input(
            "copies",
            "Copies you hold",
            placeholder="0 to 99",
            required=True,
            max_length=2,
        )],
    )


@register_action("cards_count_submit", is_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_count_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    await ctx.defer(ephemeral=True)
    tag, card_id, _target = _parse_card_set_target(f"{action_id}|0")
    if card_id is None:
        view = _notice("Card unavailable", "Open `/cards` again.")
        await ctx.interaction.edit_initial_response(components=view)
        return
    raw = _modal_text_value(ctx, "copies")
    try:
        target = int(str(raw).strip())
    except (TypeError, ValueError):
        account, inventory, problem = await _load_target(
            ctx, tag, coc_client=coc_client, mongo=mongo
        )
        view = problem or await _card_focus_view(
            account, inventory, card_id,
            saved="That was not a number, so nothing changed.",
        )
    else:
        view = await _apply_card_count(
            ctx, tag, card_id, target, coc_client=coc_client, mongo=mongo
        )
    await ctx.interaction.edit_initial_response(components=view)


async def _card_editor_step(
    ctx,
    action_id: str,
    *,
    direction: int,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    tag, card_id = _parse_editor_target(action_id)
    if card_id is None or direction not in {-1, 1}:
        return _notice("Card unavailable", "Open `/cards` again.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    state = normalize_cards(inventory.get("cards")).get(card_id, OWNED)
    was_possible_spare = card_id in set(_scan_unverified_ids(inventory))
    mode = (
        ("used" if state >= DUPLICATE else "missing" if state == OWNED else None)
        if direction < 0
        else ("found" if state == MISSING else "spare" if state == OWNED else None)
    )
    if mode is None:
        return await _card_editor_view(account, inventory, card_id)
    try:
        updated = await _write_one_card(
            mongo,
            account,
            inventory,
            card_id,
            mode,
            expected_revision=_inventory_revision_value(inventory),
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return await _card_editor_view(
            account,
            inventory,
            card_id,
            saved="This card is reserved and was not changed.",
        )
    except (InventoryWriteConflict, InvalidCardTransitionError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _card_editor_view(
            account,
            current,
            card_id,
            saved="The collection changed, so this view was refreshed.",
        )
    pending = _scan_unverified_ids(updated)
    next_card_id = pending[0] if was_possible_spare and pending else card_id
    return await _card_editor_view(
        account,
        updated,
        next_card_id,
        saved=f"{CARD_BY_ID[card_id].name} is {_state_name(int(QUICK_CARD_ACTIONS[mode]['to']))}.",
    )


@register_action("cards_editor_dec")
@lightbulb.di.with_di
async def cards_editor_dec(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _card_editor_step(
        ctx,
        action_id,
        direction=-1,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_editor_inc")
@lightbulb.di.with_di
async def cards_editor_inc(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _card_editor_step(
        ctx,
        action_id,
        direction=1,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_editor_keep")
@lightbulb.di.with_di
async def cards_editor_keep(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, card_id = _parse_editor_target(action_id)
    if card_id is None:
        return _notice("Card unavailable", "Open `/cards` again.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    try:
        updated = await _write_hidden_badge_batch(
            mongo,
            account,
            inventory,
            [card_id],
            [],
            expected_revision=_inventory_revision_value(inventory),
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return await _card_editor_view(
            account, inventory, card_id,
            saved="This card is reserved and was not changed.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _card_editor_view(
            account, current, card_id,
            saved="The collection changed, so this view was refreshed.",
        )
    pending = _scan_unverified_ids(updated)
    return await _card_editor_view(
        account,
        updated,
        pending[0] if pending else card_id,
        saved=f"{CARD_BY_ID[card_id].name} stays at 1 copy.",
    )


@register_action("cards_advanced")
@lightbulb.di.with_di
async def cards_advanced(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    return problem or _update_overview(account, inventory)


def _modal_text_value(ctx, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()) or ():
        for component in row:
            if getattr(component, "custom_id", None) == custom_id:
                return str(getattr(component, "value", "") or "").strip()
    return ""


@register_action("cards_hidden")
@lightbulb.di.with_di
async def cards_hidden(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not _scan_unverified_ids(inventory):
        # Nothing left to check, so show the result rather than a menu about it.
        data = await load_accounts(coc_client, int(ctx.user.id))
        return await _dashboard_view(
            account, inventory, account_count=len(_loaded_entries(data))
        )
    return await _hidden_badge_review_view(account, inventory)


@register_action("cards_category")
@lightbulb.di.with_di
async def cards_category(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, category_id = _parse_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if _category_has_reservations(inventory, category_id):
        return _active_trade_notice(account.tag)
    return _category_editor(account, inventory, category_id)


async def _selection_update(
    ctx,
    action_id: str,
    *,
    mode: str,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    tag, category_id = _parse_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if _category_has_reservations(inventory, category_id):
        return _active_trade_notice(account.tag)
    selected = list(getattr(ctx.interaction, "values", ()) or ())
    try:
        inventory = await _write_category(
            mongo,
            account,
            inventory,
            category_id,
            selected,
            mode=mode,
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return _active_trade_notice(account.tag)
    except InventoryWriteConflict:
        return _inventory_retry_notice()
    return _category_editor(account, inventory, category_id)


async def _clear_category_list(
    ctx,
    action_id: str,
    *,
    mode: str,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    tag, category_id = _parse_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if _category_has_reservations(inventory, category_id):
        return _active_trade_notice(account.tag)
    try:
        inventory = await _write_category(
            mongo,
            account,
            inventory,
            category_id,
            [],
            mode=mode,
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return _active_trade_notice(account.tag)
    except InventoryWriteConflict:
        return _inventory_retry_notice()
    return _category_editor(account, inventory, category_id)


@register_action("cards_set_missing")
@lightbulb.di.with_di
async def cards_set_missing(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _selection_update(
        ctx,
        action_id,
        mode="missing",
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_set_duplicates")
@lightbulb.di.with_di
async def cards_set_duplicates(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _selection_update(
        ctx,
        action_id,
        mode="duplicates",
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_clear_missing")
@lightbulb.di.with_di
async def cards_clear_missing(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _clear_category_list(
        ctx,
        action_id,
        mode="missing",
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_clear_duplicates")
@lightbulb.di.with_di
async def cards_clear_duplicates(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _clear_category_list(
        ctx,
        action_id,
        mode="duplicates",
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_baseline")
@lightbulb.di.with_di
async def cards_baseline(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, category_id = _parse_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if _category_has_reservations(inventory, category_id):
        return _active_trade_notice(account.tag)
    reviewed = set(inventory.get("reviewed_lists") or ())
    missing_reviewed = f"{category_id}:missing" in reviewed
    duplicates_reviewed = f"{category_id}:duplicates" in reviewed
    if missing_reviewed and not duplicates_reviewed:
        mode = "duplicates"
    elif duplicates_reviewed and not missing_reviewed:
        mode = "missing"
    else:
        mode = "baseline"
    try:
        inventory = await _write_category(
            mongo,
            account,
            inventory,
            category_id,
            [],
            mode=mode,
            discord_id=int(ctx.user.id),
            guild_id=_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return _active_trade_notice(account.tag)
    except InventoryWriteConflict:
        return _inventory_retry_notice()
    return _category_editor(account, inventory, category_id)


@register_action("cards_matches")
@lightbulb.di.with_di
async def cards_matches(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    candidates = await _candidate_inventories(
        mongo, inventory, guild_id=_guild_id(ctx)
    )
    available = _without_reserved_cards(inventory)
    matches = find_matches(available, candidates)
    return _matches_view(
        account,
        available,
        matches,
        supply=family_supply(candidates),
        achievable=_achievable_from_matches(
            matches, _normalize_tag(account.tag)
        ),
    )


def _achievable_from_matches(matches, requester_tag: str) -> tuple[int, int]:
    """Count listed swap options and how many could complete together."""
    pairs = []
    for match in matches:
        for exchange in match.exchanges:
            for offered in exchange.offers:
                for returned in exchange.returns:
                    pairs.append((
                        (match.holder_tag, offered),
                        (requester_tag, returned),
                    ))
    return len(pairs), max_achievable_trades(pairs)


@register_action("cards_open_card")
@lightbulb.di.with_di
async def cards_open_card(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Show who holds one card, from the card-shaped Find trades list."""
    # Find trades draws one menu per category, so the category rides along in
    # the custom_id: four menus in one message need four distinct ids, and it
    # doubles as a check that the pick belongs to the menu it came from.
    tag, category_id = _parse_target(action_id)
    values = list(getattr(ctx.interaction, "values", ()) or ())
    card_id = str(values[0]) if values else ""
    card = CARD_BY_ID.get(card_id)
    if card is None or (category_id is not None and card.category != category_id):
        return _notice("Unknown card", "Open `/cards` again for a fresh list.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    candidates = await _candidate_inventories(
        mongo, inventory, guild_id=_guild_id(ctx)
    )
    holders = holders_for_card(
        _without_reserved_cards(inventory), candidates, card_id
    )
    return _holders_view(account, card_id, holders)


@register_action("cards_holder_page")
@lightbulb.di.with_di
async def cards_holder_page(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, card_id, page = _parse_holder_page(action_id)
    card = CARD_BY_ID.get(card_id)
    if not tag or card is None:
        return _notice("Unknown holder page", "Open a fresh card search.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    candidates = await _candidate_inventories(
        mongo, inventory, guild_id=_guild_id(ctx)
    )
    holders = holders_for_card(
        _without_reserved_cards(inventory), candidates, card_id
    )
    return _holders_view(account, card_id, holders, page=page)


@register_action("cards_trades")
@lightbulb.di.with_di
async def cards_trades(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, page = _parse_trade_page(action_id)
    account, _inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    guild_id = _guild_id(ctx)
    if guild_id is None:
        return _notice("Open trades in the server", "Run `/cards` in Warriors United.")
    trades = await _active_trades(
        mongo, tag=account.tag, guild_id=guild_id, bot=bot
    )
    return _trades_view(account, trades, page=page)


@register_action("cards_trade_holder")
@lightbulb.di.with_di
async def cards_trade_holder(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    parts = str(action_id or "").split("|")
    requester_tag, wanted_card_id = _parse_trade_request_target(
        "|".join(parts[:2])
    )
    wanted = CARD_BY_ID.get(wanted_card_id)
    # The Ask button carries the holder in its custom_id. Interaction values
    # remain a fallback for any panel still open from the old select.
    values = list(getattr(ctx.interaction, "values", ()) or ())
    holder_tag = _normalize_tag(
        parts[2] if len(parts) > 2 else (values[0] if values else "")
    )
    if wanted is None or not holder_tag:
        return _notice("Unknown swap", "Open a fresh specific-card result and try again.")
    account, requester, problem = await _load_target(
        ctx, requester_tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(requester):
        return _stale_collection_notice()
    candidates = await _candidate_inventories(
        mongo, requester, guild_id=_guild_id(ctx)
    )
    holders = holders_for_card(
        _without_reserved_cards(requester), candidates, wanted_card_id
    )
    holder = next(
        (
            item for item in holders
            if _normalize_tag(item.holder_tag) == holder_tag
        ),
        None,
    )
    if holder is None:
        return _notice(
            "That holder is no longer available",
            "Refresh the specific-card results and choose another player.",
        )
    return _trade_offer_view(account, wanted_card_id, holder)


@register_action("cards_trade_request")
@lightbulb.di.with_di
async def cards_trade_request(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    requester_tag, wanted_card_id = _parse_trade_request_target(action_id)
    values = list(getattr(ctx.interaction, "values", ()) or ())
    holder_tag, given_card_id = _parse_trade_option(values[0] if values else "")
    wanted = CARD_BY_ID.get(wanted_card_id)
    given = CARD_BY_ID.get(given_card_id)
    if wanted is None or given is None or wanted.category != given.category:
        return _notice("Invalid swap", "Open a fresh specific-card result and try again.")
    account, requester, problem = await _load_target(
        ctx, requester_tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(requester):
        return _stale_collection_notice()
    guild_id = _guild_id(ctx)
    if guild_id is None:
        return _notice("Open trades in the server", "Run `/cards` in Warriors United.")
    candidates = await _candidate_inventories(mongo, requester, guild_id=guild_id)
    holder = next(
        (item for item in candidates if _normalize_tag(item.get("_id")) == holder_tag),
        None,
    )
    if holder is None:
        return _notice("That match is no longer available", "Refresh the holder list and try again.")
    error = reciprocal_trade_error(
        _without_reserved_cards(requester), holder, wanted_card_id, given_card_id
    )
    if error:
        return _notice("That swap is no longer available", error)
    live_clans = await _live_family_clans(
        mongo, coc_client, requester_tag, holder_tag
    )
    if live_clans is None:
        return _notice(
            "Both accounts must be in family clans",
            "I could not verify both accounts inside the configured clan family, so no proposal was posted.",
        )
    requester = dict(requester)
    holder = dict(holder)
    requester["clan_tag"], holder["clan_tag"] = live_clans
    trade, error = await _create_trade_request(
        mongo,
        requester=requester,
        holder=holder,
        wanted_card_id=wanted_card_id,
        given_card_id=given_card_id,
        guild_id=guild_id,
    )
    if error:
        return _notice("Could not post this proposal", error)
    channel_sent, dm_sent = await asyncio.gather(
        _post_trade_channel(bot, mongo, trade),
        _notify_trade_holder(bot, trade),
    )
    delivery: list[str] = []
    delivery.append("posted it in the trade channel" if channel_sent else "could not post in the configured trade channel")
    delivery.append("sent the holder a DM" if dm_sent else f"could not DM <@{trade['holder_discord_id']}>")
    return _trade_feedback(
        "Proposal posted",
        f"You proposed **{given.name}** for **{wanted.name}**; nothing is reserved "
        f"until they accept. I {' and '.join(delivery)}.",
        account.tag,
    )


@register_action("cards_trade_accept")
@lightbulb.di.with_di
async def cards_trade_accept(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _guild_id(ctx),
    })
    if not trade:
        return _notice("Trade proposal not found", "Reopen **My trades**.")
    trade = await _expire_trade_if_needed(mongo, trade, bot=bot)
    if trade.get("status") != "pending":
        return _notice("Trade request is no longer pending", "Reopen **My trades** for its status.")
    account, holder, problem = await _load_trade_actor(
        ctx, trade, role="holder", coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    requester = await mongo.card_inventories.find_one({
        "_id": _normalize_tag(trade["requester_tag"]),
        "guild_id": int(trade["guild_id"]),
    })
    if not requester:
        return _notice("Requester collection unavailable", "Decline this request and ask them to refresh.")
    error = reciprocal_trade_error(
        _without_reserved_cards(requester),
        _without_reserved_cards(holder),
        trade["wanted_card_id"],
        trade["given_card_id"],
    )
    if error:
        return _notice("Trade can no longer be accepted", error)
    live_clans = await _live_family_clans(
        mongo, coc_client, trade["requester_tag"], trade["holder_tag"]
    )
    if live_clans is None:
        return _notice(
            "Both accounts must be in family clans",
            "I could not verify both accounts inside the configured clan family. Try again after they are back in family clans.",
        )
    now = datetime.now(timezone.utc)
    outcome, status = await _accept_trade_reservation(
        mongo,
        trade,
        user_id=int(ctx.user.id),
        live_clans=live_clans,
        now=now,
    )
    if outcome == "conflict":
        return _notice(
            "One of these exact cards is already committed",
            "No account-wide lock was added. Finish or cancel the conflicting swap, or accept a proposal using different cards.",
        )
    if outcome == "invalid":
        return _notice(
            "The collections changed",
            "Nothing was reserved. Refresh the proposal after both players update their cards.",
        )
    if outcome != "accepted":
        return _notice("Trade changed before acceptance", "Reopen **My trades** and check its status.")
    accepted_trade = await mongo.card_trades.find_one({"_id": trade["_id"]}) or dict(trade)
    accepted_trade["status"] = status
    dm_sent, _channel_updated = await asyncio.gather(
        _notify_trade_accepted(bot, accepted_trade),
        _update_trade_channel(bot, accepted_trade),
    )
    delivery = (
        "I notified the requester by DM."
        if dm_sent
        else f"I could not DM <@{trade['requester_discord_id']}>; please ping them."
    )
    return _trade_feedback(
        "Swap accepted",
        (
            "The exact cards are reserved. You are in different family clans; move one account manually, then click **Check clans**. "
            if status == "move_needed"
            else "The exact cards are reserved and both accounts are in the same family clan. Complete both in-game requests, then mark the swap complete. "
        ) + f"{delivery}",
        account.tag,
    )


@register_action("cards_trade_ready")
@lightbulb.di.with_di
async def cards_trade_ready(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _guild_id(ctx),
    })
    if not trade:
        return _notice("Trade not found", "Reopen **My trades**.")
    user_id = int(ctx.user.id)
    if user_id == int(trade.get("requester_discord_id", -1)):
        role = "requester"
    elif user_id == int(trade.get("holder_discord_id", -1)):
        role = "holder"
    else:
        return _notice("That trade action is not yours", "Open **My trades** from your own dashboard.")
    account, _inventory, problem = await _load_trade_actor(
        ctx, trade, role=role, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if trade.get("status") != "move_needed":
        return _notice("This swap is not waiting on a move", "Reopen **My trades** for its current status.")
    live_clans = await _live_family_clans(
        mongo, coc_client, trade["requester_tag"], trade["holder_tag"]
    )
    if live_clans is None:
        return _trade_feedback(
            "Both accounts must stay in family clans",
            "I could not verify both accounts in the configured family. The card reservations remain until you retry or cancel.",
            account.tag,
        )
    now = datetime.now(timezone.utc)
    if not await _verify_trade_reservation(mongo, trade, now=now):
        review = await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "move_needed"},
            {
                "$set": {
                    "status": "needs_review",
                    "failure": "reservation_lost",
                    "review_expires_at": now + TRADE_REVIEW_FOR,
                    "updated_at": now,
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        if not getattr(review, "modified_count", 0):
            return _trade_feedback(
                "Swap changed while clans were checked",
                "Reopen **My trades** for its current status.",
                account.tag,
            )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        trade["status"] = "needs_review"
        other_id = (
            int(trade["holder_discord_id"])
            if role == "requester"
            else int(trade["requester_discord_id"])
        )
        await asyncio.gather(
            _notify_trade_status(
                bot,
                trade,
                recipient_id=other_id,
                title="Card swap needs review",
                detail="An exact-card reservation is missing. Recheck both collections.",
            ),
            _update_trade_channel(bot, trade),
        )
        return _notice(
            "Swap needs review",
            "An exact-card reservation is missing. Recheck both collections before making another proposal.",
        )
    requester_clan, holder_clan = live_clans
    if requester_clan != holder_clan:
        await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "move_needed"},
            {"$set": {
                "requester_clan_tag": requester_clan,
                "holder_clan_tag": holder_clan,
                "updated_at": now,
            }},
        )
        return _trade_feedback(
            "Still in different clans",
            f"The accounts are currently in `{requester_clan}` and `{holder_clan}`. The exact cards remain reserved; check again after the move.",
            account.tag,
        )
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": "move_needed"},
        {"$set": {
            "status": "ready",
            "requester_clan_tag": requester_clan,
            "holder_clan_tag": holder_clan,
            "clan_tag": requester_clan,
            "ready_at": now,
            "updated_at": now,
        }},
    )
    if not getattr(result, "modified_count", 0):
        return _notice("Trade changed while checking clans", "Reopen **My trades**.")
    trade.update({
        "status": "ready",
        "requester_clan_tag": requester_clan,
        "holder_clan_tag": holder_clan,
        "clan_tag": requester_clan,
    })
    other_id = (
        int(trade["holder_discord_id"])
        if role == "requester"
        else int(trade["requester_discord_id"])
    )
    dm_sent, _channel_updated = await asyncio.gather(
        _notify_trade_status(
            bot,
            trade,
            recipient_id=other_id,
            title="Card swap is ready",
            detail="Both accounts are now in the same family clan. Coordinate both in-game requests.",
        ),
        _update_trade_channel(bot, trade),
    )
    return _trade_feedback(
        "Ready in the same clan",
        "Coordinate both in-game requests. Mark **Trade completed** only after both finish."
        + _dm_fallback_note(dm_sent, other_id),
        account.tag,
    )


@register_action("cards_trade_decline")
@lightbulb.di.with_di
async def cards_trade_decline(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _guild_id(ctx),
    })
    if not trade:
        return _notice("Trade request not found", "Reopen **My trades**.")
    trade = await _expire_trade_if_needed(mongo, trade, bot=bot)
    account, _inventory, problem = await _load_trade_actor(
        ctx, trade, role="holder", coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    now = datetime.now(timezone.utc)
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": "pending"},
        {
            "$set": {"status": "declined", "declined_at": now, "updated_at": now},
            "$unset": {"open_proposal_key": ""},
        },
    )
    if not getattr(result, "modified_count", 0):
        return _notice("Trade is no longer pending", "Reopen **My trades**.")
    await _release_proposal_slots(mongo, trade)
    trade["status"] = "declined"
    dm_sent, _channel_updated = await asyncio.gather(
        _notify_trade_status(
            bot,
            trade,
            recipient_id=int(trade["requester_discord_id"]),
            title="Card proposal declined",
            detail="The holder declined it. No cards had been reserved.",
        ),
        _update_trade_channel(bot, trade),
    )
    delivery = (
        "The requester was notified by DM."
        if dm_sent
        else f"I could not DM <@{trade['requester_discord_id']}>; please ping them."
    )
    return _trade_feedback(
        "Proposal declined",
        f"The proposal is closed; no cards were reserved. {delivery}",
        account.tag,
    )


@register_action("cards_trade_cancel")
@lightbulb.di.with_di
async def cards_trade_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _guild_id(ctx),
    })
    if not trade:
        return _notice("Trade request not found", "Reopen **My trades**.")
    trade = await _expire_trade_if_needed(mongo, trade, bot=bot)
    user_id = int(ctx.user.id)
    if user_id == int(trade.get("requester_discord_id", -1)):
        role = "requester"
    elif user_id == int(trade.get("holder_discord_id", -1)):
        role = "holder"
    else:
        return _notice("That trade action is not yours", "Open **My trades** from your own dashboard.")
    account, _inventory, problem = await _load_trade_actor(
        ctx, trade, role=role, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    now = datetime.now(timezone.utc)
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": {"$in": ["pending", "move_needed", "ready", "accepted"]}},
        {
            "$set": {
                "status": "cancelled",
                "cancelled_at": now,
                "cancelled_by": user_id,
                "updated_at": now,
                **_cleanup_fields(trade),
            },
            "$unset": {"open_proposal_key": ""},
        },
    )
    if not getattr(result, "modified_count", 0):
        return _notice("Trade can no longer be cancelled", "Reopen **My trades**.")
    await _release_proposal_slots(mongo, trade)
    await _finish_trade_cleanup(
        mongo, trade, owner=_reservation_owner(trade)
    )
    trade["status"] = "cancelled"
    other_id = (
        int(trade["holder_discord_id"])
        if role == "requester"
        else int(trade["requester_discord_id"])
    )
    dm_sent, _channel_updated = await asyncio.gather(
        _notify_trade_status(
            bot,
            trade,
            recipient_id=other_id,
            title="Card swap cancelled",
            detail="The other player cancelled it and exact-card reservations were released.",
        ),
        _update_trade_channel(bot, trade),
    )
    delivery = (
        "The other player was notified by DM."
        if dm_sent
        else f"I could not DM <@{other_id}>; please ping them."
    )
    return _trade_feedback(
        "Trade cancelled",
        f"No tracked inventory changed; exact-card reservations were released. {delivery}",
        account.tag,
    )


@register_action("cards_trade_complete")
@lightbulb.di.with_di
async def cards_trade_complete(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _guild_id(ctx),
    })
    if not trade:
        return _notice("Trade request not found", "Reopen **My trades**.")
    trade = await _expire_trade_if_needed(mongo, trade, bot=bot)
    user_id = int(ctx.user.id)
    if user_id == int(trade.get("requester_discord_id", -1)):
        role = "requester"
    elif user_id == int(trade.get("holder_discord_id", -1)):
        role = "holder"
    else:
        return _notice("That trade action is not yours", "Open **My trades** from your own dashboard.")
    account, _inventory, problem = await _load_trade_actor(
        ctx, trade, role=role, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    other_id = (
        int(trade["holder_discord_id"])
        if role == "requester"
        else int(trade["requester_discord_id"])
    )
    now = datetime.now(timezone.utc)
    if trade.get("status") not in {"ready", "accepted"}:
        return _notice("Trade is not ready to complete", "It must be accepted and both accounts must be in the same family clan.")
    live_clans = await _live_family_clans(
        mongo, coc_client, trade["requester_tag"], trade["holder_tag"]
    )
    if live_clans is None:
        return _trade_feedback(
            "Could not verify both family clans",
            "The exact cards remain reserved. Retry when both accounts are inside configured family clans, or cancel the swap.",
            account.tag,
        )
    if live_clans[0] != live_clans[1]:
        demoted = await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": {"$in": ["ready", "accepted"]}},
            {"$set": {
                "status": "move_needed",
                "requester_clan_tag": live_clans[0],
                "holder_clan_tag": live_clans[1],
                "updated_at": now,
            }},
        )
        if getattr(demoted, "modified_count", 0):
            trade.update({
                "status": "move_needed",
                "requester_clan_tag": live_clans[0],
                "holder_clan_tag": live_clans[1],
            })
            await _update_trade_channel(bot, trade)
        return _trade_feedback(
            "The accounts moved apart",
            "The exact cards remain reserved. Move into the same family clan, then use **Check clans**.",
            account.tag,
        )
    completing_until = now + TRADE_COMPLETION_FOR
    if not await _verify_trade_reservation(mongo, trade, now=now):
        review = await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": {"$in": ["ready", "accepted"]}},
            {
                "$set": {
                    "status": "needs_review",
                    "updated_at": now,
                    "review_expires_at": now + TRADE_REVIEW_FOR,
                    "failure": "lease_lost",
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        if getattr(review, "modified_count", 0):
            await _finish_trade_cleanup(
                mongo, trade, owner=_reservation_owner(trade)
            )
            trade["status"] = "needs_review"
            await _update_trade_channel(bot, trade)
            dm_sent = await _notify_trade_status(
                bot,
                trade,
                recipient_id=other_id,
                title="Card swap needs review",
                detail=(
                    "A reservation expired before completion. No automatic "
                    "inventory update was attempted."
                ),
            )
            return _notice(
                "Trade needs manual review",
                "A reservation expired; no automatic inventory update was attempted."
                + _dm_fallback_note(dm_sent, other_id),
            )
        return _notice(
            "Trade changed while completion started",
            "Reopen **My trades** and check its current status.",
        )
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": {"$in": ["ready", "accepted"]}},
        {"$set": {
            "status": "completing",
            "completion_started_at": now,
            "completion_started_by": user_id,
            "updated_at": now,
            "expires_at": completing_until,
        }},
    )
    if not getattr(result, "modified_count", 0):
        return _notice(
            "Completion is already being saved",
            "Wait a moment, then reopen **My trades**. Do not click completion twice.",
        )
    trade = await mongo.card_trades.find_one({"_id": trade["_id"]}) or trade

    try:
        updates = await _apply_trade_inventory_updates(mongo, trade, now=now)
    except Exception as exc:
        _log.exception(
            "card trade inventory completion failed trade=%s", trade["_id"]
        )
        await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "completing"},
            {
                "$set": {
                    "status": "needs_review",
                    "updated_at": datetime.now(timezone.utc),
                    "review_expires_at": datetime.now(timezone.utc) + TRADE_REVIEW_FOR,
                    "failure": f"inventory_update_exception:{type(exc).__name__}",
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        detail = (
            "An unexpected storage error interrupted completion. Recheck and "
            "correct both affected categories before another swap."
        )
        trade["status"] = "needs_review"
        dm_sent, _channel_updated = await asyncio.gather(
            _notify_trade_status(
                bot,
                trade,
                recipient_id=other_id,
                title="Card swap needs review",
                detail=detail,
            ),
            _update_trade_channel(bot, trade),
        )
        return _trade_feedback(
            "Trade needs review",
            detail + _dm_fallback_note(dm_sent, other_id),
            account.tag,
        )
    prevalidated = updates["requester_prevalidated"] and updates["holder_prevalidated"]
    both_updated = updates["requester"] and updates["holder"]
    if not prevalidated or not both_updated:
        await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "completing"},
            {
                "$set": {
                    "status": "needs_review",
                    "updated_at": now,
                    "review_expires_at": now + TRADE_REVIEW_FOR,
                    "inventory_updates": updates,
                    "failure": "inventory_state_changed",
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        detail = (
            "One inventory changed while completion was saving. Review both card "
            "collections manually before making another request."
            if updates["requester"] or updates["holder"]
            else "Neither inventory was changed because at least one collection no longer matched the accepted swap."
        )
        trade["status"] = "needs_review"
        dm_sent, _channel_updated = await asyncio.gather(
            _notify_trade_status(
                bot,
                trade,
                recipient_id=other_id,
                title="Card swap needs review",
                detail=detail,
            ),
            _update_trade_channel(bot, trade),
        )
        return _trade_feedback(
            "Trade needs review",
            detail + _dm_fallback_note(dm_sent, other_id),
            account.tag,
        )

    finalize_error: Exception | None = None
    try:
        completed = await mongo.card_trades.update_one(
            {"_id": trade["_id"], "status": "completing"},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": now,
                    "completed_by": user_id,
                    "updated_at": now,
                    "inventory_updates": updates,
                    **_cleanup_fields(trade),
                },
                "$unset": {"open_proposal_key": ""},
            },
        )
    except Exception as exc:
        finalize_error = exc
        completed = None
        _log.exception("card trade audit finalization failed trade=%s", trade["_id"])
    if not getattr(completed, "modified_count", 0):
        review_now = datetime.now(timezone.utc)
        try:
            await mongo.card_trades.update_one(
                {"_id": trade["_id"], "status": "completing"},
                {
                    "$set": {
                        "status": "needs_review",
                        "updated_at": review_now,
                        "review_expires_at": review_now + TRADE_REVIEW_FOR,
                        "inventory_updates": updates,
                        "failure": (
                            f"audit_finalize_exception:{type(finalize_error).__name__}"
                            if finalize_error is not None
                            else "audit_finalize_failed"
                        ),
                        **_cleanup_fields(trade),
                    },
                    "$unset": {"open_proposal_key": ""},
                },
            )
        except Exception:
            _log.exception(
                "card trade review fallback could not persist trade=%s", trade["_id"]
            )
        await _finish_trade_cleanup(
            mongo, trade, owner=_reservation_owner(trade)
        )
        review_detail = (
            "Both collection writes ran, but the audit record could not "
            "be finalized. Recheck both collections before another swap."
        )
        trade["status"] = "needs_review"
        dm_sent, _channel_updated = await asyncio.gather(
            _notify_trade_status(
                bot,
                trade,
                recipient_id=other_id,
                title="Card swap needs review",
                detail=review_detail,
            ),
            _update_trade_channel(bot, trade),
        )
        return _trade_feedback(
            "Trade needs review",
            "Both collections changed, but the audit record could not be finalized. "
            "Review both collections before making another request."
            + _dm_fallback_note(dm_sent, other_id),
            account.tag,
        )
    await _finish_trade_cleanup(
        mongo, trade, owner=_reservation_owner(trade)
    )
    trade["status"] = "completed"
    dm_sent, _channel_updated = await asyncio.gather(
        _notify_trade_status(
            bot,
            trade,
            recipient_id=other_id,
            title="Card swap completed",
            detail="Both tracked collections were updated conservatively.",
        ),
        _update_trade_channel(bot, trade),
    )
    return _trade_feedback(
        "Trade completed",
        "Both inventories were updated conservatively: each missing card is now owned "
        "and each offered duplicate dropped by one copy. Mark another spare if you still have one."
        + _dm_fallback_note(dm_sent, other_id),
        account.tag,
    )


@register_action("cards_confirm")
@lightbulb.di.with_di
async def cards_confirm(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if inventory.get("complete_categories"):
        now = datetime.now(timezone.utc)
        await mongo.card_inventories.update_one(
            {"_id": _normalize_tag(account.tag)},
            {"$set": {"confirmed_at": now, "last_seen_at": now}},
        )
        inventory = await mongo.card_inventories.find_one(
            {"_id": _normalize_tag(account.tag)}
        ) or inventory
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data))
    )
