"""One-command Clash of Cards collection and family matching hub.

Members run ``/cards`` and start an account-bound private upload from its
dashboard. They can send the collection screenshots together in any order, or
use the manual editor as a fallback. No scan writes automatically: account
ownership, full card coverage, uncertainty, reservations, and inventory
revision are rechecked at explicit confirmation.
"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import logging
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

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
from extensions.commands.recruit.perms import guild_permissions
from extensions.components import register_action
from utils import bot_data
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
    TRADE_GEM_COST,
    MAX_COPIES,
    MISSING,
    OWNED,
    as_utc,
    category_summary,
    family_supply,
    find_matches,
    holders_for_card,
    inventory_summary,
    inventory_is_matchable,
    max_achievable_trades,
    normalize_cards,
    normalize_status,
    reciprocal_trade_error,
)
from utils import cards_config
from utils.component_state import delete_state, get_state, insert_state, update_state
from utils import troop_emoji
from utils.emoji import EmojiType, emojis
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
# Five, not six. Each holder costs four components (Section + Text +
# Button + Separator), and six put a full page at 38 of Discord's 40 -
# two away from the whole message being rejected, with no room for
# anything to be added later.
HOLDER_RESULT_LIMIT = 5
TRADE_VIEW_LIMIT = 5
PLAYER_LOOKUP_TEXT_LIMIT = 4_000
MAX_OPEN_PROPOSALS_PER_ACCOUNT = 25
# A want-ad reserves nothing, so the 25-slot proposal machinery would be the
# wrong bound for it - but every open request costs a public channel post, so
# it needs a much tighter cap.
MAX_OPEN_REQUESTS_PER_ACCOUNT = 3
OPEN_REQUEST_FOR = timedelta(hours=48)
# How long one member's claim may hold an open request's "claiming" fence
# before a sweeper returns it to open. Defined beside its siblings; the claim
# flow is what consumes it.
OPEN_REQUEST_CLAIM_FOR = timedelta(minutes=2)
COMMITTED_TRADE_FETCH_LIMIT = 100
PROPOSAL_TRADE_FETCH_LIMIT = 250
REVIEW_TRADE_FETCH_LIMIT = 250
TRADE_COMPLETION_FOR = timedelta(minutes=10)
PROPOSAL_SLOT_HOLD_FOR = timedelta(minutes=10)
TRADE_REVIEW_FOR = timedelta(days=7)
TRADE_LEASE_COUNT = 4
CARD_SCAN_CAPTURE_COUNT = 5
CARD_SCAN_DRAFT_FOR = timedelta(minutes=20)
CARD_BULK_SESSION_FOR = timedelta(hours=2)
CARD_BULK_WRITE_GRACE = timedelta(minutes=2)
CARD_SCAN_MAX_IMAGE_BYTES = 10 * 1024 * 1024
CARD_SCAN_MAX_BATCH_BYTES = 50 * 1024 * 1024
CARD_SCAN_MAX_UPLOAD_ATTACHMENTS = 10
CARD_SCAN_MIN_CONFIDENCE = 0.75
CARD_SCAN_CONCURRENCY = 2
HIDDEN_BADGE_BATCH_SIZE = 25
COLLECTION_LINK = "https://link.clashofclans.com/en/?action=OpenCollection"

# Owner-designated optional quick-trade clan for different-clan swaps.
NOAHS_ARK_TAG = "#8VPQCR2R"
NOAHS_ARK_LINK = (
    "https://link.clashofclans.com/en?action=OpenClanProfile&tag=8VPQCR2R"
)


def _clan_link(tag: object) -> str | None:
    """Deep link to a clan profile, or None when there is no tag."""
    clean = _normalize_tag(tag).lstrip("#")
    if not clean:
        return None
    return (
        "https://link.clashofclans.com/en/?action=OpenClanProfile"
        f"&tag={clean}"
    )
GLOBAL_CHAT_LINK = (
    "https://link.clashofclans.com/?action=OpenGlobalChat&"
    "chatId=P592bad3209a4408a9ba356469caaaa81"
)

# Kept as a module-level name because it was one, and a helper that moved to
# utils is still the same function. utils/cards_config.py owns the parsing now
# so the sticky task can resolve the same channel without importing this
# 14k-line module.
_parse_snowflake_env = cards_config.parse_snowflake_env

# Read once, into module globals, because that is what the tests patch:
# tests/test_cards.py sets `cards_command.CARDS_GUILD_ID` directly in ~20
# places. Calling cards_config on every access would quietly ignore all of
# them.
CARDS_GUILD_ID = cards_config.cards_guild_id()
CARDS_CHANNEL_ID = cards_config.cards_channel_id()

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


def _safe_partial(entry):
    """A CustomEmoji for a component's `emoji=` field, or UNDEFINED.

    `EmojiType.partial_emoji` raises on a malformed string, and one bad id here
    would take down every panel that uses it, so this degrades to no emoji the
    same way troop_emoji does.
    """
    if entry is None:
        return hikari.UNDEFINED
    try:
        return entry.partial_emoji
    except (ValueError, IndexError, TypeError, AttributeError):
        return hikari.UNDEFINED


def category_partial(category_id: str):
    return _safe_partial(CATEGORY_EMOJI.get(str(category_id)))


# Resolved once: these are fixed strings, so a failure here is a typo in the
# table above rather than anything that can change between renders.
REFRESH_EMOJI = _safe_partial(emojis.refresh)
RETURN_EMOJI = _safe_partial(emojis.return_arrow)
HOME_EMOJI = _safe_partial(emojis.home)
SEARCH_EMOJI = _safe_partial(emojis.magnifier)
CANCEL_EMOJI = _safe_partial(emojis.no)
TRADES_EMOJI = _safe_partial(emojis.inbox)
SWITCH_EMOJI = _safe_partial(emojis.switch)
SCAN_EMOJI = _safe_partial(emojis.scan)
UPDATE_EMOJI = _safe_partial(emojis.update_collection)
ADMIN_EMOJI = _safe_partial(emojis.admin_gear)
GIVE_EMOJI = _safe_partial(emojis.card_give)
SWAP_EMOJI = _safe_partial(emojis.card_swap)
HOT_EMOJI = _safe_partial(emojis.card_hot)
GEMS_EMOJI = _safe_partial(emojis.gems)


def _safe_markup(entry) -> str:
    """Emoji markup for a heading, or "" when the entry is unusable.

    Headings are plain text, so a malformed entry would print `<:name:123>`
    verbatim rather than failing loudly.
    """
    return "" if _safe_partial(entry) is hikari.UNDEFINED else str(entry)
NEXT_EMOJI = _safe_partial(emojis.next_page)
PREVIOUS_EMOJI = _safe_partial(emojis.previous_page)

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


class CandidateLookupUnavailable(RuntimeError):
    """The family-clan boundary could not be loaded, so searching must stop.

    Distinct from an empty result on purpose: "nobody has a spare" and "the
    search failed" need different player copy, and conflating them told
    players the family had nothing during a database blip.
    """


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
    """Return the shared family trade-board channel.

    Still typed optional, and every caller still guards for None. The env var
    now falls back to the sticky notice's channel so an unset variable no
    longer means "no trade board", but a test can patch the global to None and
    every path must survive that.
    """
    return CARDS_CHANNEL_ID


def _trade_guild_id(ctx) -> int | None:
    """Which family this interaction belongs to.

    The server you are actually in wins, so nothing is pinned to one hardcoded
    community. The configured id is only a fallback for a DM, which has no
    guild of its own - without it, every collection and trade would be
    invisible there.
    """
    return _guild_id(ctx) or _configured_cards_guild_id()


def _guild_scope_error(ctx) -> str | None:
    """Whether this interaction may act on a trade.

    Deliberately does NOT require the interaction to come from the family
    server. It used to, which meant a trade could only be answered from inside
    Warriors United - so a proposal that arrived by DM had to be answered
    somewhere else, and answering it in the DM was impossible.

    What actually protects a trade is the participant check every handler
    already performs: you must be its requester or its holder. That is the
    real gate, and it still applies. Guild membership never was: anybody in
    the server could see a trade id, and nobody outside it can guess one.
    """
    if _configured_cards_guild_id() is None:
        return (
            "The Card Hub is not configured yet. An operator must set "
            "`CARDS_GUILD_ID` to the Warriors United Discord server ID."
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


def _panel(accent: object, components: list) -> Container:
    """One Container, colored only when a semantic accent is passed.

    `accent_color` is typed UndefinedOr[Color], so "no accent" must omit the
    argument rather than pass None.
    """
    if accent is None:
        return Container(components=components)
    return Container(accent_color=accent, components=components)


def _notice(
    title: str,
    description: str,
    *,
    back_tag: str | None = None,
    accent: object = RED_ACCENT,
) -> list[Container]:
    """A message, and - when the caller knows the account - a way out of it.

    A notice replaces the whole panel, so without a control it is a dead end
    and the only escape is running /cards again.

    Color follows the accent canon: most notices refuse something, so red
    stays the default; a success passes GREEN_ACCENT and a routine
    acknowledgement passes None.
    """
    body: list = [
        Text(content=f"# {title}"),
        Separator(divider=True),
        Text(content=description),
    ]
    if back_tag:
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{_normalize_tag(back_tag)}",
                label="Back to collection",
                emoji=RETURN_EMOJI,
            ),
        ]))
    return [_panel(accent, body)]


def _stale_collection_notice() -> list[Container]:
    """Why matching is closed to you.

    Age stopped being the reason when the 72-hour window went; the only thing
    that turns matching off now is having trading switched off, so the message
    has to point at that instead or it sends people to confirm a collection
    that was never the problem.
    """
    return _notice(
        "Your trading is turned off",
        "Your cards are hidden from the family while trading is off, so there "
        "is nothing to search. Open `/cards` and turn trading back on.",
    )


def _search_unavailable_notice(tag: object = None) -> list[Container]:
    """The search failed. Says so, instead of claiming nobody has spares."""
    return _notice(
        "Search is not available right now",
        "Nothing was changed. Try again in a minute.",
        back_tag=_normalize_tag(tag) if tag else None,
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
                    emoji=TRADES_EMOJI,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}",
                    label="Collection",
                    emoji=RETURN_EMOJI,
                ),
            ]),
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


def _without_reserved_cards(inventory: dict) -> dict:
    """Return a safe matching snapshot with reservations masked out.

    The positive per-card trust ledger is canonical for modern documents.
    Project it here as a read-side compatibility boundary too: an untouched
    legacy Ready document may still carry durable hidden-badge uncertainty,
    and it must fail closed even before that owner next opens ``/cards`` and
    materializes the ledger.
    """
    trusted, ready_categories, reviewed_lists = _trust_projection(inventory)
    snapshot = dict(inventory)
    snapshot["complete_categories"] = ready_categories
    snapshot["reviewed_lists"] = reviewed_lists
    reserved = _card_reservations(inventory)
    cards = normalize_cards(inventory.get("cards"))
    # Some read-only trade summaries inspect counts directly instead of first
    # checking category readiness. Neutralize every value the trust ledger
    # cannot vouch for so a preserved partial-scan 0/2 cannot appear as false
    # demand or supply through those secondary views.
    for card_id in (set(CARD_BY_ID) - set(trusted)) | set(reserved):
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


def _parse_account_page(value: object) -> tuple[int, str | None]:
    """Split `page` or `page|tag`.

    The tag says which collection to go back to. Buttons on messages sent
    before it was threaded through carry the page alone, which parses to no
    tag - those panels simply render without a Back button rather than
    erroring at whoever clicks them.
    """
    page_part, _, tag = str(value or "").partition("|")
    return _parse_page(page_part), (_normalize_tag(tag) if tag else None)


def _account_picker(
    data: AccountsData, page: int = 0, *, back_tag: str | None = None
) -> list[Container]:
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
        # An account whose town hall never loaded used to read "THNone", in
        # both the name and the line under it. No level is better than a
        # wrong one, so the whole piece drops out.
        town_hall_text = f"TH{town_hall}" if town_hall else ""
        label = entry.account.name
        if emoji is hikari.UNDEFINED and town_hall_text:
            label = f"{entry.account.name} · {town_hall_text}"
        detail = " · ".join(part for part in (
            town_hall_text,
            entry.account.clan_name or "No clan",
            entry.tag,
        ) if part)
        options.append(SelectOption(
            label=_plain(label),
            value=entry.tag,
            description=_plain(detail, limit=100),
            emoji=emoji,
        ))

    # One small line, not two. "Accounts 1-25 of 37" already carries the total,
    # so a separate "37 accounts" line above it said the same number twice -
    # and this sits above the menu, so the reader knows which stretch of
    # accounts they are about to open before they open it.
    if pages > 1:
        summary_line = (
            # En dash, not a hyphen: it is a range, and 1–25 reads as one at a
            # glance where 1-25 can read as a subtraction.
            f"-# Accounts {start + 1}–{start + len(window)} of {len(entries)}"
            " · Each has its own collection."
        )
    else:
        summary_line = (
            f"-# {len(entries)} account{'s' if len(entries) != 1 else ''}"
            " · Each has its own collection."
        )

    body: list = [
        Text(content="# Your card collections"),
        # "linked" named the mechanic rather than the thing, and "keeps" is a
        # less common word than "has" for the same idea.
        Text(content=summary_line),
        Separator(divider=True),
        ActionRow(components=[
            TextSelectMenu(
                custom_id=f"cards_account_select:{page}",
                # No "Clash", because every account here is one, and no
                # trailing dots - Discord does not need them and they read as
                # an unfinished sentence.
                placeholder="Choose an account",
                max_values=1,
                options=options,
            )
        ]),
    ]
    # Directly under the menu they page, with nothing between.
    suffix = f"|{_normalize_tag(back_tag)}" if back_tag else ""
    if pages > 1:
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_account_page:{page - 1}{suffix}",
                label="Previous",
                emoji=PREVIOUS_EMOJI,
                is_disabled=page == 0,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_account_page:{page + 1}{suffix}",
                label="Next",
                emoji=NEXT_EMOJI,
                is_disabled=page >= pages - 1,
            ),
        ]))
    # This screen REPLACES the collection it was opened from - the dispatcher
    # edits the message in place, and the whole panel is ephemeral, so there is
    # nothing underneath to go back to and dismissing it loses everything.
    # Without this, opening the switcher and changing your mind meant running
    # /cards again.
    if back_tag:
        body.extend([
            Separator(divider=True),
            ActionRow(components=[Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{_normalize_tag(back_tag)}",
                label="Back to collection",
                emoji=RETURN_EMOJI,
            )]),
        ])
    # No accent, which is what the collection screen does. Gold across this
    # command has drifted into meaning "something wants your answer" - Ask for
    # help, Finish your swap, the gem asks, Trading paused, the DMs. Switching
    # account asks nothing; it is a step inside the collection flow, so it is
    # styled like the collection rather than like a request.
    return [Container(components=body)]


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


def _scan_row_numbers(value: object) -> list[int]:
    """Collection row numbers 1..10, deduplicated and ordered."""
    try:
        parsed = {int(item) for item in (value or ())}
    except (TypeError, ValueError):
        return []
    return sorted(row for row in parsed if 1 <= row <= CARD_SCAN_CAPTURE_COUNT * 2)


def _row_card_ids(rows) -> set[str]:
    """The six catalog card ids in each of these collection rows."""
    catalog = list(CARD_BY_ID)
    ids: set[str] = set()
    for row in rows:
        start = (int(row) - 1) * 6
        ids.update(catalog[start:start + 6])
    return ids


def _rows_missing_positions(rows, present: set[str]) -> list[int]:
    """Collection rows whose six catalog positions are not all represented.

    Row atomicity is the persistence side of the recognition rule. The scanner
    accepts or rejects a whole six-card row, so a row that reaches storage has
    to arrive whole: five of its six cards is not a smaller success, it is a
    different claim than the one the scanner made.
    """
    catalog = list(CARD_BY_ID)
    return [
        int(row)
        for row in rows
        if not set(catalog[(int(row) - 1) * 6:int(row) * 6]) <= present
    ]


def _scan_row_decisions(value: object) -> list[dict]:
    """Keep the scanner's per-row verdicts as BSON-safe evidence.

    This is diagnostic provenance, not player copy. It records the proposed
    row separately from the trusted identity, so a later investigation can see
    what the scanner nearly said without that proposal ever having counted as
    an identity.
    """
    try:
        records = list(value or ())
    except TypeError:
        return []
    decisions: list[dict] = []
    for record in records[:20]:
        outcome = str(_scan_field(record, "outcome", default="") or "")[:32]
        if not outcome:
            continue

        def number(name: str) -> int | None:
            raw = _scan_field(record, name, default=None)
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                return None
            return parsed

        def measure(name: str) -> float | None:
            raw = _scan_field(record, name, default=None)
            try:
                parsed = float(raw)
            except (TypeError, ValueError):
                return None
            return round(parsed, 4) if math.isfinite(parsed) else None

        decisions.append({
            "image": max(1, number("input_index") or 1),
            "row_index": max(0, number("row_index") or 0),
            "accepted": bool(_scan_field(record, "accepted", default=False)),
            "outcome": outcome,
            "reason": str(_scan_field(record, "reason", default="") or "")[:160],
            "proposed_row": number("proposed_row"),
            "catalog_row": number("catalog_row"),
            "identity_top1": measure("identity_top1"),
            "identity_gap": measure("identity_gap"),
        })
    return decisions


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
    # Codes that describe a normal outcome rather than a problem with the
    # image. A capture that produced trusted rows and also left one row for
    # manual checking is not a capture worth telling the member to retake:
    # the rows still to check are listed once, for the whole scan.
    harmless_capture_codes = {
        "catalog_position_and_artwork_validated",
        "catalog_position_bound_by_batch_order",
        "capture_rows_confirmed",
        "capture_rows_need_manual_review",
        "duplicate_capture_ignored",
        "duplicate_page_ignored",
        "repeat_rows_ignored",
        "repeat_rows_merged",
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
            {
                "duplicate_capture_ignored",
                "duplicate_page_ignored",
                "repeat_rows_ignored",
                "repeat_rows_merged",
            } & set(all_codes)
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
    # Make the three classifications a partition before anything reads them.
    #
    # A card that was never seen has no state, so the scanner reports it as
    # unknown as well; the two lists genuinely overlap on every partial scan.
    # Left overlapping, "unknown" would vouch for a position that was in fact
    # never observed, and an accepted row could look complete through a card
    # nothing ever looked at. Never seen is the stronger claim, so it wins, and
    # states / unknown / unseen become mutually exclusive.
    unknown -= unseen
    for card_id in unknown | unseen:
        states.pop(card_id, None)
        confidences.pop(card_id, None)
    identified = set(states) | unknown
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

    accepted_rows = [
        row
        for row in _scan_row_numbers(
            _scan_field(result, "accepted_global_rows", default=())
        )
        if row not in set(missing_rows)
    ]
    # Row atomicity, checked here rather than assumed. An accepted row means
    # six identified cards, so every one of its positions must have arrived as
    # exactly one of a trusted state or an explicit unknown - never absent,
    # never unseen, never both. A row claiming acceptance while one of its
    # positions was never seen is an inconsistent scanner result, and the safe
    # answer to that is to trust none of it.
    accepted_card_ids = _row_card_ids(accepted_rows)
    if (
        _rows_missing_positions(accepted_rows, set(states) | unknown)
        or accepted_card_ids & unseen
        or accepted_card_ids & (unknown & unseen)
    ):
        identity_bound = False
        coverage_complete = False
        accepted_rows = []
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
        # Row provenance. Only accepted rows contributed card states, so these
        # are the rows a human still has to answer for, and the evidence behind
        # each verdict is kept for debugging rather than for the player.
        "accepted_global_rows": accepted_rows,
        "manual_required_global_rows": missing_rows,
        "manual_required_card_ids": _ordered_card_ids(unknown | unseen),
        "row_decisions": _scan_row_decisions(
            _scan_field(result, "row_decisions", default=())
        ),
        "scanner_version": str(
            _scan_field(result, "scanner_version", default="") or ""
        )[:120],
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


def _scan_accepted_rows(draft: object) -> list[int]:
    if not isinstance(draft, dict):
        return []
    return _scan_row_numbers(draft.get("accepted_global_rows"))


def _scan_manual_required_ids(draft: object) -> list[str]:
    """Every card this scan could not answer for, ordered by catalog position.

    The union of what the scanner declared and what the draft's own accounting
    implies. Erring wide is the safe direction: this set decides which
    categories lose their readiness, so missing a card would leave an
    unreviewed category matchable.
    """
    if not isinstance(draft, dict):
        return []
    unknown, _invalid_unknown = _scan_id_set(draft.get("unknown_card_ids") or ())
    unseen, _invalid_unseen = _scan_id_set(draft.get("unseen_card_ids") or ())
    declared, _invalid_declared = _scan_id_set(
        draft.get("manual_required_card_ids") or ()
    )
    hidden_badges, _invalid_hidden = _scan_id_set(
        draft.get("duplicate_unverified_card_ids") or ()
    )
    return _ordered_card_ids(unknown | unseen | declared | hidden_badges)


def _scan_draft_partially_savable(draft: object) -> bool:
    """Whether some rows are safe to keep even though the scan is incomplete.

    The scanner accepts or rejects a whole six-card row, so this is strictly
    row-atomic in both directions:

    * every card offered here must come from an accepted row - five apparently
      good cards out of a rejected row are not evidence;
    * every accepted row must arrive whole - all six of its catalog positions
      present, each one **exactly one** of a valid state or an explicit
      unknown, which is the frozen model's way of saying "this row is that row,
      but I could not read this card's count".

    A position that is absent, unseen, both unknown and unseen, or carries a
    state while also being called unseen is a contradictory claim about a row
    the scanner said it recognized. None of the draft is trusted then: this
    does not lean on normalization having tidied the classifications up.
    """
    if not isinstance(draft, dict):
        return False
    states = draft.get("card_states")
    if not isinstance(states, dict) or not states:
        return False
    accepted_rows = _scan_accepted_rows(draft)
    if not accepted_rows:
        return False
    unknown, invalid_unknown = _scan_id_set(draft.get("unknown_card_ids") or ())
    unseen, invalid_unseen = _scan_id_set(draft.get("unseen_card_ids") or ())
    accepted_card_ids = _row_card_ids(accepted_rows)
    return (
        not invalid_unknown
        and not invalid_unseen
        and all(_scan_card_state(state) is not None for state in states.values())
        and set(states) <= accepted_card_ids
        # No card may be classified two ways at once.
        and not (unknown & unseen)
        and not (set(states) & (unknown | unseen))
        # No position of a recognized row may be unseen or missing.
        and not (accepted_card_ids & unseen)
        and not _rows_missing_positions(accepted_rows, set(states) | unknown)
        and (set(states) | unknown | unseen) == set(CARD_BY_ID)
        and bool(draft.get("identity_bound"))
        and not draft.get("errors")
    )


def _scan_ready_for_review(draft: object) -> bool:
    """Whether there is a result worth showing the member now.

    Either every collection section matched, or enough rows were confirmed for
    a partial save to be offered. Anything less means asking for the missing
    screenshots is still the more useful answer.
    """
    if not isinstance(draft, dict):
        return False
    if not _scan_missing_page_numbers(draft):
        return True
    return _scan_draft_partially_savable(draft)


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
    # Gold, not red: the bot is waiting on the player, nothing is wrong.
    return [Container(
        accent_color=GOLD_ACCENT,
        components=[
            Text(content=f"# {emojis.scan} Send your card screenshots"),
            Text(content=(
                f"**{_escape_markdown(account.name)}** · "
                f"`{_normalize_tag(account.tag)}`\n"
                "Open your collection in game. Screenshot every row of six "
                "cards.\n"
                "Send all screenshots here in one message.\n"
                "- Any order is fine. Overlap is fine.\n"
                "- Do not cut a row at the edge. Five screenshots normally "
                "cover all 60 cards."
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
                    emoji=CANCEL_EMOJI,
                ),
            ]),
            Text(content=(
                f"-# Open {_scan_expiry_text(usable_until)}. "
                "The bot reads the images once and does not keep them."
            )),
        ],
    )]


def _scan_upload_started(account, *, usable_until: object) -> list[Container]:
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content=f"# {emojis.scan} Private upload ready"),
            Text(content=(
                f"I sent **{_escape_markdown(account.name)}** a private "
                "upload DM. Open it and send your collection screenshots "
                "there.\n"
                f"-# The upload is open {_scan_expiry_text(usable_until)}."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                    label="Back to collection",
                    emoji=RETURN_EMOJI,
                ),
            ]),
        ],
    )]


def _scan_dm_unavailable(account) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="# I could not open a private upload"),
            Text(content=(
                "Allow direct messages from members of the family Discord server, "
                "then tap **Try scan again**. **Edit counts** still works "
                "without DMs."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_scan_start:{_normalize_tag(account.tag)}",
                    label="Try scan again",
                    emoji=SCAN_EMOJI,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_advanced:{_normalize_tag(account.tag)}",
                    label="Edit counts",
                    emoji="⚙️",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                    label="Collection",
                    emoji=RETURN_EMOJI,
                ),
            ]),
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
    # Recognition is per six-card row, so a single accepted row must not be
    # reported as "nothing matched" just because its partner row is missing.
    rows_accepted = None
    raw_missing_rows = (
        draft.get("missing_global_rows") if isinstance(draft, dict) else None
    )
    if raw_missing_rows is not None:
        try:
            rows_accepted = max(
                0, CARD_SCAN_CAPTURE_COUNT * 2 - len({
                    int(value) for value in raw_missing_rows
                })
            )
        except (TypeError, ValueError):
            rows_accepted = None
    if accepted:
        result = (
            f"✅ I matched **{accepted} of {CARD_SCAN_CAPTURE_COUNT}** collection "
            f"sections" + (f" (**+{gained}** this time)." if gained else ".")
        )
    elif rows_accepted:
        result = (
            f"✅ I matched **{rows_accepted}** six-card "
            f"{'row' if rows_accepted == 1 else 'rows'} so far."
        )
    else:
        result = (
            "I couldn't match a complete six-card row in those images."
        )
    issue_lines = _scan_capture_issue_lines(draft)
    issue_text = ""
    if issue_lines:
        issue_text = "\n\n" + "\n".join(issue_lines[:3])
    # Gold: the bot is waiting on more screenshots, nothing is wrong.
    return [Container(
        accent_color=GOLD_ACCENT,
        components=[
            Text(content=f"# {emojis.scan} More screenshots needed"),
            Text(content=(
                f"**{_escape_markdown(account.name)}** · "
                f"`{_normalize_tag(account.tag)}`\n"
                f"{result}\n\n"
                f"**Still needed:**\n{_scan_missing_rows_text(draft)}\n\n"
                "Send only the missing rows in this DM. Do not resend "
                f"accepted rows.{issue_text}"
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
                    emoji=CANCEL_EMOJI,
                ),
            ]),
            Text(content=(
                f"-# Open {_scan_expiry_text(usable_until)}."
            )),
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
                    emoji=CANCEL_EMOJI,
                ),
            ]),
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
        "capture_requires_two_rows": "could not find a complete card row",
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
        "no_valid_rows": "did not contain a readable card row",
        "no_valid_six_column_rows": "did not contain a complete six-card row",
        "no_card_sized_components": "did not contain readable card portraits",
        "insufficient_card_slots": "did not show all six cards in a row",
        "no_new_collection_pages": "did not add a new collection section",
        "no_new_collection_rows": "did not add a new card row",
        "no_confirmed_card_rows": "did not show a card row I could confirm",
        "conflicting_repeat_rows": "disagrees with a row I already read",
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
            reasons.append("could not be read as complete six-card rows")
        assignment = (
            f" (collection rows {assigned_page * 2 - 1}–{assigned_page * 2})"
            if 1 <= assigned_page <= CARD_SCAN_CAPTURE_COUNT
            else ""
        )
        lines.append(
            f"**Image {image_number}{assignment}:** {'; '.join(reasons)}. Retake it."
        )
    return lines


def _scan_guild_problem(ctx) -> list[Container] | None:
    """Refuse to start a scan outside the family that owns card collections.

    A scan session is only ever resolvable in the configured family. The DM
    listener looks the session up by that one guild id, and every button on the
    session rechecks it, so storing the guild the member happens to be standing
    in creates a session nothing can ever answer - and the collection would
    have been rescoped to that guild on the way in. Both fail closed here,
    before any inventory is touched.
    """
    configured = _configured_cards_guild_id()
    if configured is None:
        return _notice(
            "Open Card Hub in its family server",
            "The Card Hub is not configured yet. An operator must set "
            "`CARDS_GUILD_ID` to the family Discord server ID.",
        )
    here = _guild_id(ctx)
    if here is not None and int(here) != int(configured):
        return _notice(
            "Scanning only works in the family server",
            "Run `/cards` in the family server, then tap **Update collection** "
            "and **Scan screenshots**. Nothing was changed here.",
        )
    return None


def _scan_session_problem(ctx, user_id: object, guild_id: object) -> list[Container] | None:
    try:
        owns_session = int(user_id) == int(ctx.user.id)
        session_guild = int(guild_id)
        configured_guild = int(_configured_cards_guild_id() or 0)
        context_guild = _trade_guild_id(ctx)
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
        "own `/cards` collection in the family server.",
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
            Text(content=f"# {emojis.scan} Account check needed"),
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
                    emoji=REFRESH_EMOJI,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_scan_retry_cancel:{draft_id}",
                    label="Cancel",
                    emoji=CANCEL_EMOJI,
                ),
            ]),
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
    unseen = _ordered_card_ids(draft.get("unseen_card_ids") or ())
    errors = _scan_strings(draft.get("errors"), limit=5)
    manual_required = _scan_manual_required_ids(draft)
    reserved = bool(_card_reservations(inventory))
    confirmable = _scan_draft_confirmable(draft) and not reserved
    # Some rows were read safely and some were not. The safe ones are worth
    # keeping; the rest go to the manual editor rather than being guessed.
    partial = (
        not _scan_draft_confirmable(draft)
        and _scan_draft_partially_savable(draft)
        and not reserved
    )
    scan_read = len(set(states) - set(manual_required))
    finish_needed = bool(manual_required) and (partial or confirmable)
    capture_issue_lines = _scan_capture_issue_lines(draft)

    collected = len(states) - len(missing)
    details = []
    if manual_required and (partial or confirmable):
        # Name the unread rows once, then any single card inside a confirmed
        # row whose count the scanner could not read. Both need checking, and
        # the reader should not have to work out which is which.
        manual_rows = _scan_row_numbers(
            draft.get("manual_required_global_rows")
        )
        row_card_ids = _row_card_ids(manual_rows)
        loose = [
            card_id for card_id in manual_required
            if card_id not in row_card_ids
        ]
        lines = [
            f"**Still to check: {len(manual_required)} "
            f"card{'s' if len(manual_required) != 1 else ''}**",
        ]
        if manual_rows or _scan_missing_page_numbers(draft):
            lines.append(_scan_missing_rows_text(draft))
        if loose:
            named = _scan_card_names(loose[:6])
            extra = len(loose) - 6
            lines.append(
                f"- **Also:** {named}"
                + (f" and {extra} more" if extra > 0 else "")
            )
        details.append("\n".join(lines))
    if unseen and not partial:
        details.append(f"**Not visible:** {len(unseen)} card positions")
    if capture_issue_lines and unseen and not partial:
        # Only ask for another image when card positions were never seen. A
        # capture that merely produced an uncertain card is resolvable in place,
        # and telling a member to retake it right after they answered every card
        # by hand contradicted the Save button sitting next to it.
        details.append(
            "**Send these pages again:**\n" + "\n".join(capture_issue_lines)
        )

    # One state line: what happened, and that nothing is saved yet.
    if errors:
        state_line = "**This scan cannot be read.** Nothing is saved."
    elif reserved:
        state_line = (
            "**Finish or cancel your accepted trade first.** "
            "Nothing is saved yet."
        )
    elif partial or finish_needed:
        state_line = (
            f"**I read {scan_read} of 60 cards.** Nothing is saved yet.\n"
            f"**{len(manual_required)} still need a count.**"
        )
    elif not confirmable:
        state_line = (
            "**This scan needs another screenshot.** Nothing is saved yet."
        )
    else:
        state_line = (
            "**All 60 cards were read.** Nothing is saved yet.\n"
            f"**{collected} collected** · {len(missing)} missing"
        )

    body: list = [
        Text(content="# Scan complete"),
        Text(content=(
            f"**{_escape_markdown(account.name)}** · "
            f"`{_normalize_tag(account.tag)}`\n"
            + state_line
        )),
    ]
    if details:
        body.extend([
            Separator(divider=True),
            Text(content="\n".join(details)),
        ])
    if partial:
        save_buttons = [
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"cards_scan_save_partial:{draft_id}",
                label="Finish collection",
            ),
        ]
        body.append(Text(content=(
            f"**Finish collection** saves the {scan_read} cards I read, then "
            "opens the remaining cards for exact counts."
        )))
    elif finish_needed:
        save_buttons = [Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_scan_confirm:{draft_id}",
            label="Finish collection",
        )]
        body.append(Text(content=(
            f"**Finish collection** saves the {scan_read} cards I read, then "
            "opens the remaining cards for exact counts."
        )))
    else:
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
                label="Update collection",
            ))
            body.append(Text(content=(
                "-# **Update collection** edits your saved collection, "
                "not this scan."
            )))
    body.extend([
        Separator(divider=True),
        ActionRow(components=[
            *save_buttons,
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_scan_cancel:{draft_id}",
                label="Cancel",
                emoji=CANCEL_EMOJI,
            ),
        ]),
    ])
    quiet = []
    if partial or finish_needed:
        quiet.append(
            "-# Nothing was guessed. A category with unchecked cards is "
            "not ready to trade."
        )
        quiet.append(
            "-# You can send another screenshot here first if you want to try again."
        )
    quiet.append(f"-# This review is open {_scan_expiry_text(usable_until)}.")
    body.append(Text(content="\n".join(quiet)))
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
        "town_hall": getattr(account, "town_hall", 0) or 0,
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
    inventory = await mongo.card_inventories.find_one({
        "_id": _normalize_tag(account.tag)
    }) or {}
    return await _materialize_legacy_trust(mongo, inventory)


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
        guild_id=_trade_guild_id(ctx),
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


# Compatibility boundary for documents created before ``trusted_card_ids``.
# These are exactly the 60 cards shipped with the initial Cards catalog
# (2026-08-10, f4ca757). Keep this literal and versioned: deriving it from the
# live catalog would silently trust a future card merely because its category
# was historically Ready. A later catalog addition must start untrusted until
# the member confirms it through a trust-aware writer.
_LEGACY_READY_CARD_IDS_V1_BY_CATEGORY: dict[str, frozenset[str]] = {
    "elixir": frozenset({
        "barbarian", "archer", "giant", "goblin", "wall_breaker",
        "balloon", "wizard", "healer", "dragon", "pekka", "baby_dragon",
        "miner", "electro_dragon", "yeti", "dragon_rider",
        "electro_titan", "root_rider", "thrower", "meteor_golem",
    }),
    "dark_elixir": frozenset({
        "minion", "hog_rider", "valkyrie", "golem", "witch",
        "lava_hound", "bowler", "ice_golem", "headhunter",
        "apprentice_warden", "druid", "furnace", "rubble_witch",
    }),
    "builder_base": frozenset({
        "raged_barbarian", "sneaky_archer", "boxer_giant", "beta_minion",
        "bomber", "bb_baby_dragon", "cannon_cart", "night_witch",
        "drop_ship", "power_pekka", "hog_glider",
    }),
    "super_troop": frozenset({
        "super_barbarian", "super_archer", "super_giant", "sneaky_goblin",
        "super_wall_breaker", "rocket_balloon", "super_wizard",
        "super_dragon", "inferno_dragon", "super_miner", "super_yeti",
        "super_minion", "super_hog_rider", "super_valkyrie",
        "super_witch", "ice_hound", "super_bowler",
    }),
}


def _trusted_card_ids(inventory: dict) -> set[str]:
    """Return the collection values that are safe to use for trading.

    ``trusted_card_ids`` is the canonical positive ledger.  Its presence is
    also the schema marker: a card absent from a modern document is untrusted.

    Historical documents predate that ledger.  A legacy Ready category is
    retained as fully trusted, while an explicit exact-count marker is also
    durable proof that the member entered that one card by hand.  Nothing else
    is inferred for an incomplete legacy collection, so old partial scans fail
    closed instead of turning their preserved/default values into trade data.
    """
    if "trusted_card_ids" in inventory:
        raw = inventory.get("trusted_card_ids") or ()
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(value) for value in raw if str(value) in CARD_BY_ID}

    trusted = set(_confirmed_count_ids(inventory))
    for category_id in set(inventory.get("complete_categories") or ()):
        trusted.update(
            card_id
            for card_id in _LEGACY_READY_CARD_IDS_V1_BY_CATEGORY.get(
                str(category_id), ()
            )
            if card_id in CARD_BY_ID
        )
    # Older full scans marked every category Ready before their hidden-badge
    # review was finished. Those durable IDs are direct evidence that the
    # stored neutral value was only a conservative placeholder, so they are
    # the one exception to preserving a historical Ready category wholesale.
    trusted.difference_update(_scan_unverified_ids(inventory))
    return trusted


def _trust_projection(
    inventory: dict,
    *,
    add: object = (),
    remove: object = (),
) -> tuple[list[str], list[str], list[str]]:
    """Project canonical trust into the existing category readiness fields."""
    trusted = _trusted_card_ids(inventory)
    added, _invalid_added = _scan_id_set(add or ())
    removed, _invalid_removed = _scan_id_set(remove or ())
    trusted.update(added)
    trusted.difference_update(removed)
    ordered = _ordered_card_ids(trusted)
    ready = [
        category.id
        for category in CATEGORIES
        if all(card.id in trusted for card in CATEGORY_CARDS[category.id])
    ]
    reviewed = sorted(
        f"{category_id}:{mode}"
        for category_id in ready
        for mode in ("missing", "duplicates")
    )
    return ordered, ready, reviewed


def _untrusted_card_ids(inventory: dict) -> list[str]:
    trusted = _trusted_card_ids(inventory)
    return _ordered_card_ids(set(CARD_BY_ID) - trusted)


async def _materialize_legacy_trust(
    mongo: MongoClient,
    inventory: dict,
) -> dict:
    """Persist the safe legacy inference before UI and matching can diverge."""
    if not inventory or "trusted_card_ids" in inventory:
        return inventory
    tag = _normalize_tag(inventory.get("_id"))
    if not tag:
        return inventory
    for _attempt in range(2):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        if "trusted_card_ids" in latest:
            return latest
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(latest)
        # A brand-new or wholly ambiguous legacy collection already fails
        # closed without a migration write. Materialize only durable positive
        # evidence: historical Ready categories or exact member entries.
        if not trusted_ids:
            return latest
        revision = _inventory_revision_value(latest)
        revision_guard = (
            {"$or": [
                {"inventory_revision": {"$exists": False}},
                {"inventory_revision": 0},
            ]}
            if revision == 0
            else {"inventory_revision": revision}
        )
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "trusted_card_ids": {"$exists": False},
                **revision_guard,
            },
            {
                "$set": {
                    "trusted_card_ids": trusted_ids,
                    "complete_categories": ready_categories,
                    "reviewed_lists": reviewed_lists,
                },
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 0):
            return await mongo.card_inventories.find_one({"_id": tag}) or latest
    return await mongo.card_inventories.find_one({"_id": tag}) or inventory


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
    is_admin: bool | None = None,
) -> list[Container]:
    tag = _normalize_tag(account.tag)
    if is_admin is None:
        # Resolved here rather than passed in. You only ever see your own
        # board, so the inventory already names who is looking - and a dozen
        # handlers render this screen, which is why a threaded flag made the
        # button appear on some of them and vanish on others.
        is_admin = _is_cards_admin_id(inventory.get("discord_id"))
    _trusted, projected_ready, _reviewed = _trust_projection(inventory)
    complete = set(projected_ready)
    summary = inventory_summary(inventory.get("cards"), complete)
    all_complete = len(complete) == len(CATEGORIES)
    reserved_count = len(_card_reservations(inventory))
    unverified_duplicates = _scan_unverified_ids(inventory)
    untrusted = _untrusted_card_ids(inventory)
    # Informational only: when this collection last changed. There is no
    # freshness-confirmation control any more - every write refreshes the
    # stamp, and age never turns matching off.
    stamp = inventory.get("confirmed_at") or inventory.get("updated_at")
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
        # Two lines: who this is, then how it is going. As one run it was six
        # facts in a single sentence and nothing could be found at a glance.
        Text(content=(
            f"**{_escape_markdown(account.name)}** · `{tag}`\n"
            f"{headline} · updated {_relative_timestamp(stamp)}"
        )),
    ]
    if account_count > 1:
        # Directly under the name, because that is what it changes. It used to
        # sit in the row of collection controls, which act on the cards.
        body.append(ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_account_page:0|{tag}",
            label="Switch account",
            emoji=SWITCH_EMOJI,
        )]))

    notes = []
    if unverified_duplicates and untrusted:
        notes.append(
            f"**{len(untrusted)} card"
            f"{'s still need' if len(untrusted) != 1 else ' still needs'} "
            "a count.** Tap **Finish collection** below."
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

    # No category menus here any more, and no sort control with them. This
    # screen shows the collection and helps you trade; every way of CHANGING
    # the collection now lives behind one button, so there are not three
    # competing routes to the same edit.
    matchable = inventory_is_matchable(inventory)
    spare_total = sum(
        1 for value in normalize_cards(inventory.get("cards")).values()
        if value >= DUPLICATE
    )
    # A button label can carry the count, which is all the row above it was
    # ever saying. Two Section rows cost two lines each and wrap on mobile;
    # two buttons cost one line and say the same thing.
    destinations = [
        Button(
            style=(
                hikari.ButtonStyle.PRIMARY
                if matchable
                else hikari.ButtonStyle.SECONDARY
            ),
            custom_id=f"cards_matches:{tag}",
            # Matching no longer expires with age; the only thing that turns
            # this off is opting out, so the disabled label says so.
            label=(
                f"Find trades · {summary.missing} needed"
                if matchable
                else "Find trades · trading is off"
            ),
            emoji=SEARCH_EMOJI,
            is_disabled=not matchable,
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_trades:{tag}",
            label="My trades",
            emoji=TRADES_EMOJI,
        ),
    ]
    if unverified_duplicates and untrusted:
        body.append(ActionRow(components=[Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_hidden:{tag}",
            label=f"Finish collection ({len(untrusted)})",
        )]))
    body.append(Separator(divider=True))

    # One way in, not three. This used to be four category menus, a sort
    # control, Scan screenshots and Edit counts - four routes to the same job,
    # spread across the screen. Scanning still exists; it moved inside, where
    # it reads as the faster alternative to typing rather than a rival to it.
    body.append(ActionRow(components=[
        Button(
            style=(
                hikari.ButtonStyle.SECONDARY
                if all_complete
                else hikari.ButtonStyle.PRIMARY
            ),
            custom_id=f"cards_advanced:{tag}",
            label="Update collection",
            emoji=UPDATE_EMOJI,
        ),
    ]))

    body.append(Separator(divider=True))
    body.append(ActionRow(components=destinations))
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
    if is_admin:
        # Last, and on its own. It sat beside Find trades because that row had
        # room, which is not a reason - it is not part of trading and almost
        # nobody on the panel can even see it.
        body.append(ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_admin:{tag}",
            label="Admin",
            emoji=ADMIN_EMOJI,
        )]))
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








CATEGORY_HEADER_VALUE = "__category__"


def _category_header_option(category, detail: str) -> SelectOption:
    """A default-marked option, which is what a closed menu actually displays.

    A select's `placeholder` is sent as a bare string with no emoji field, so
    the uploaded category art cannot go there - it would print `<:Elixer:123>`
    verbatim. An option *does* carry an emoji, and Discord shows the default
    option in place of the placeholder, so marking one default is what puts the
    real art on the closed menu. Picking it is a no-op.
    """
    return SelectOption(
        label=f"{category.short_name} — {detail}"[:100],
        value=CATEGORY_HEADER_VALUE,
        emoji=category_partial(category.id),
        is_default=True,
    )


def _category_select_row(
    account,
    inventory: dict,
    category_id: str,
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
    for card in CATEGORY_CARDS[category_id]:
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
    detail = f"{summary.collected}/{summary.known}"
    if summary.collected == summary.known:
        detail += " complete"
    elif summary.missing:
        detail += f" · {summary.missing} missing"
    return ActionRow(components=[TextSelectMenu(
        custom_id=f"cards_pick:{tag}|{category_id}",
        # Only shown if the header option is ever cleared; the default option
        # below is what a closed menu actually draws.
        placeholder=f"{category.name} · {detail}"[:150],
        max_values=1,
        options=[_category_header_option(category, detail), *options],
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
            "in your collection."
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
        # One row, one meaning: minus, how many you have, plus. There used to
        # be six controls for this number - None, Have 1, Exactly 2, -1, +1 and
        # Type a number - and None and Have 1 turned green when they matched
        # your count, so they were the current-value display disguised as
        # buttons. That is why the count itself appeared nowhere as a number
        # and why two rows looked like rival ways to change the same thing.
        # The count is information, so it is text. It was briefly the middle
        # button, which read as a display anyway - so the modal behind it was
        # invisible, and tapping what looks like a readout did something
        # unexpected. Controls look like actions; facts look like facts.
        Text(content=(
            "**You have 2 or more**" if unconfirmed
            else f"**You have {state if isinstance(state, int) else 0}**"
        )),
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
            # Only for a spare the scanner proved exists without counting: the
            # answer is nearly always two, so it stays as a one-tap reply to
            # the "2 or more" prompt rather than a permanent fourth control.
            *(
                [Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_set:{tag}|{card.id}|{DUPLICATE}",
                    label="Set to 2",
                    is_disabled=reserved,
                )]
                if unconfirmed
                else []
            ),
        ]),
        Separator(divider=True),
        # Above the menu, not below it. Underneath, you had already scrolled
        # past the control before being told what it was for. It cannot be
        # said in the menu itself: a default-marked option is drawn in place
        # of the placeholder, so the placeholder is never seen.
        Text(content="**Pick another card to keep editing**"),
        # The menu stays mounted, so fixing several cards in one category is
        # pick, tap, pick, tap without returning to the collection between
        # them.
        _category_select_row(account, inventory, card.category),
        Separator(divider=True),
        # Navigation, on its own. It used to sit between "Have 1" and the
        # step buttons, inside the controls that change the number.
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{tag}",
                label="Back to collection",
                emoji=RETURN_EMOJI,
            ),
        ]),
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
            accent=GREEN_ACCENT,
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
        "Collection saved",
        f"**{_escape_markdown(account.name)}** is updated.{detail} Run `/cards` "
        "in the family server to open your collection.",
        accent=GREEN_ACCENT,
    )




def _quantity_selected(category_id: str, card_id: object) -> str | None:
    """Which card the shared controller is pointed at, or None for nothing.

    Returns None rather than falling back to the first card. The select menu
    draws a default-marked option IN PLACE OF its placeholder, so "nothing
    selected" is what lets the menu say "Choose a card to edit" - and picking
    the first card for the member would have put a real card's number under
    controls they had not aimed at anything.
    """
    definitions = CATEGORY_CARDS[category_id]
    chosen = str(card_id or "")
    return chosen if any(card.id == chosen for card in definitions) else None


def _bulk_editable_ids(category_id: str, inventory: dict) -> list[str]:
    """Canonical category cards that are not currently reserved for a trade."""
    reserved = set(_card_reservations(inventory))
    return [
        card.id for card in CATEGORY_CARDS[category_id]
        if card.id not in reserved
    ]


def _bulk_state_id(
    tag: object,
    category_id: str,
    *,
    scope: str = "category",
) -> str:
    """Opaque state key that retains only enough scope for expiry recovery."""
    clean_tag = _normalize_tag(tag).lstrip("#")
    token = secrets.token_urlsafe(8)
    prefix = "cards_finish" if scope == "scan_finish" else "cards_bulk"
    return f"{prefix}_{token}|{clean_tag}|{category_id}"


def _bulk_is_scan_finish_id(state_id: object) -> bool:
    return str(state_id or "").split("|", 1)[0].startswith("cards_finish_")


def _bulk_state_target(state_id: object) -> tuple[str, str | None]:
    """Recover the account/category encoded in an expired bulk state key."""
    parts = str(state_id or "").split("|")
    if len(parts) != 3 or not parts[0].startswith((
        "cards_bulk_", "cards_finish_"
    )):
        return "", None
    tag = _normalize_tag(parts[1]) if len(parts) > 1 else ""
    category_id = (
        parts[2] if len(parts) > 2 and parts[2] in CATEGORY_BY_ID else None
    )
    return tag, category_id


def _quantity_editor(
    account,
    inventory: dict,
    category_id: str,
    *,
    card_id: object = None,
    saved: str | None = None,
    bulk_state_id: str | None = None,
) -> list[Container]:
    """One category on one screen: every count listed, one set of controls.

    Three shapes were tried. Two whole-category select menus could only say
    missing, one or spare, so exact counts lived elsewhere and submitting one
    list while thinking about the other wiped data. Six cards a page with their
    own -1/+1 pairs made six mini-forms that filled a phone and still hid
    thirteen of the nineteen cards.

    Every category fits one Discord select - the largest is nineteen against a
    limit of twenty-five - so there is nothing to paginate. The whole category
    lists as ONE text component, and the big buttons exist once instead of
    once per card.
    """
    category = CATEGORY_BY_ID[category_id]
    tag = _normalize_tag(account.tag)
    definitions = CATEGORY_CARDS[category_id]
    card_id = _quantity_selected(category_id, card_id)
    card = CARD_BY_ID.get(card_id) if card_id else None
    saved_cards = normalize_cards(inventory.get("cards"))
    confirmed = _confirmed_count_ids(inventory)
    trusted = _trusted_card_ids(inventory)
    reservations = _card_reservations(inventory)
    category_reservations = {
        item.id for item in definitions if item.id in reservations
    }
    untrusted = [item.id for item in definitions if item.id not in trusted]
    complete = not untrusted
    summary = category_summary(saved_cards, category_id)
    editable_ids = _bulk_editable_ids(category_id, inventory)

    def count_for(item) -> str:
        """The number, and nothing else that can be avoided.

        Every card used to describe itself in words - "Missing", "Have 1",
        "3 copies · 2 to trade". Five phrasings for one fact, each needing
        translation in the reader's head, when the digit already says it.

        "2+" is the one token that stays. It is the scanner's floor, where a
        badge proved a spare exists but not how many, and a flat 2 would be
        inventing a number the bot does not have.
        """
        state = saved_cards.get(item.id, OWNED)
        if not isinstance(state, int) or isinstance(state, bool):
            state = OWNED
        unconfirmed = state == DUPLICATE and item.id not in confirmed
        return "2+" if unconfirmed else str(state)

    state = saved_cards.get(card_id, OWNED) if card_id else OWNED
    if not isinstance(state, int) or isinstance(state, bool):
        state = OWNED
    reserved = bool(card_id) and card_id in reservations

    # A category is tradeable only after every card has a trusted value.
    # ``complete_categories`` remains the matching gate, and every writer
    # projects it from this same per-card ledger in its atomic update.
    status = (
        "**Ready to trade.** Other players can see these spares."
        if complete
        else (
            f"**Not ready to trade yet.** {len(untrusted)} card"
            f"{'s' if len(untrusted) != 1 else ''} still need a count."
        )
    )

    # All nineteen quantities in a single component. Nineteen separate text
    # nodes would have been legal too, but this is one node and the whole
    # screen then costs about a third of Discord's 40-component ceiling.
    #
    # The count sits in an inline code span, which Discord draws as a small
    # shaded box. That is the separation the list needed: the troop art
    # anchors the left of every row and the boxed number anchors the right,
    # so the quantities can be scanned down the column without any alignment.
    # It replaced two attempts that both added a glyph instead of removing
    # one - markdown bullets printed a visible dot on all nineteen rows, and
    # an invisible spacer emoji only indented them.
    #
    # Markdown does render inside a TextDisplay, which is what makes this
    # work. It does NOT render in a select option's label, so the menu below
    # writes the same number as plain text rather than faking a box.
    listing = "\n".join(
        (
            f"{troop_emoji.markup(item.id)} "
            + (
                f"**{_escape_markdown(item.name)}**"
                if item.id == card_id
                else _escape_markdown(item.name)
            )
            + f" · `{count_for(item)}`"
            + (" · in a trade" if item.id in reservations else "")
            + (" · needs a count" if item.id in untrusted else "")
            # A second mark on the chosen row, at the far end of it. Bold alone
            # has to be compared against the eighteen rows around it to be
            # noticed; a mark that only ever appears once can be found without
            # comparing anything.
            + (f" {emojis.editing_pencil}" if item.id == card_id else "")
        ).strip()
        for item in definitions
    )

    bulk_controls: list = []
    if bulk_state_id and editable_ids:
        reserved_note = (
            f" {len(category_reservations)} reserved card"
            f"{'s' if len(category_reservations) != 1 else ''} remain listed and unchanged."
            if category_reservations else ""
        )
        bulk_controls = [
            Text(content=(
                "**Update several cards**\n"
                "-# Choose every changed card once. Each submitted group saves "
                "automatically."
                f"{reserved_note}"
            )),
            ActionRow(components=[TextSelectMenu(
                custom_id=f"cards_bulk_select:{bulk_state_id}",
                placeholder="Choose cards to update",
                min_values=1,
                max_values=len(editable_ids),
                options=[
                    SelectOption(
                        label=(
                            f"{CARD_BY_ID[item_id].name} - "
                            f"{count_for(CARD_BY_ID[item_id])}"
                        )[:100],
                        value=item_id,
                        emoji=troop_emoji.partial(item_id),
                    )
                    for item_id in editable_ids
                ],
            )]),
            ActionRow(components=[Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_edit_all:{bulk_state_id}",
                label=f"Edit all {len(editable_ids)} editable counts",
            )]),
            Separator(divider=True),
        ]
    elif bulk_state_id:
        bulk_controls = [
            Text(content=(
                "**Bulk edit exact counts**\n"
                "-# Every card in this category is reserved in a trade, so none "
                "can be changed right now."
            )),
            Separator(divider=True),
        ]

    body: list = [
        Text(content=(
            f"# Update collection · {category_markup(category.id)} "
            f"{category.name}"
            + (
                f"\n-# {_escape_markdown(account.name)} \u00b7 `{tag}`"
                if bulk_state_id else ""
            )
        )),
        # The category picker is the first control, because choosing which
        # category you are looking at comes before anything you do inside it.
        # It also replaced a whole screen: there used to be a router of four
        # category buttons in front of this one, which existed only to answer
        # the question this menu answers without a page change.
        ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_qcat:{tag}",
            placeholder="Choose a category",
            max_values=1,
            options=[
                SelectOption(
                    label=item.name,
                    value=item.id,
                    emoji=category_partial(item.id),
                )
                for item in CATEGORIES
            ],
        )]),
        Separator(divider=True),
        Text(content=(
            f"{status}\n"
            f"-# {summary.collected}/{summary.known} owned · "
            "Changes save automatically."
            + (f"\n-# {_escape_markdown(saved, limit=180)}" if saved else "")
        )),
        Separator(divider=True),
        Text(content=listing),
        Separator(divider=True),
        *bulk_controls,
        # Names the control below it and says what it is for, in the words the
        # reader needs. "Dropdown" is not one of them - it assumes the member
        # knows Discord's own vocabulary. It stays on screen after a card is
        # picked, because picking a different card is the next thing most
        # people do.
        # "how many you have", not "its number": the screen shows a count, and
        # a card also has a number in the game, so "number" could be read as
        # the wrong one. This is the same phrase the modal behind Set number
        # asks - "How many do you have?" - so the two agree.
        Text(content="**Choose a card below to change how many you have.**"),
        # The chosen card IS the menu. A default-marked option is drawn in
        # place of the placeholder, so the closed menu reads "Barbarian · 3"
        # once something is chosen and "Choose a card to edit" before that.
        # Every redraw re-sends the options, so the number on the menu moves
        # with the number in the list above - there is no second line to fall
        # out of step.
        ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_qpick:{tag}|{category_id}",
            placeholder="Choose a card to edit",
            max_values=1,
            options=[
                SelectOption(
                    label=f"{item.name} · {count_for(item)}"[:100],
                    value=item.id,
                    emoji=troop_emoji.partial(item.id),
                    is_default=item.id == card_id,
                )
                for item in definitions
            ],
        )]),
    ]

    # Not mounted at all until a card is chosen. These were drawn disabled so
    # the screen would not change shape, but rendered, three greyed-out
    # buttons under an empty menu read as something broken rather than
    # something waiting. There is nothing to act on yet, so there is nothing
    # to show.
    if card_id:
        # One controller for the whole category, not one per card. "Set
        # number" is spelled out rather than hidden behind tapping the count:
        # a control that looks like a readout is not a control anybody finds.
        selected_unconfirmed = state == DUPLICATE and card_id not in confirmed
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_qstep:{tag}|{card_id}|-1",
                label="-1",
                is_disabled=reserved or state <= MISSING,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_qnum:{tag}|{card_id}",
                label="Set number",
                is_disabled=reserved,
            ),
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"cards_qstep:{tag}|{card_id}|1",
                label="+1",
                is_disabled=reserved or state >= MAX_COPIES,
            ),
            # Only for a scanner "2+": the same one-tap answer the focused
            # card screen has, so confirming exactly 2 never needs the modal.
            *(
                [Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_qset:{tag}|{card_id}|{DUPLICATE}",
                    label="Set to 2",
                    is_disabled=reserved,
                )]
                if selected_unconfirmed
                else []
            ),
        ]))
    if reserved:
        body.append(Text(
            content="-# This card is in a trade and cannot change."
        ))

    # Below the manual controls, not beside them. Typing is the main way to do
    # this; scanning is the faster alternative, and putting it up top made two
    # unlike things compete. The warning is here because the scanner does miss
    # cards - said plainly, with what to do about it, rather than hedged.
    body.extend([
        Separator(divider=True),
        Text(content=(
            # "instead" is doing the whole job of this heading: it says this
            # is another way to do what the controls above do, not the next
            # thing to do after them. The old first sentence went with it -
            # the button underneath already says what tapping it does.
            "**Scan screenshots instead**\n"
            "-# Some cards may not be read. Check the result after scanning."
        )),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_scan_start:{tag}",
            label="Scan screenshots",
            emoji=SCAN_EMOJI,
        )]),
        Separator(divider=True),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{tag}",
            label="Back to collection",
            emoji=RETURN_EMOJI,
        )]),
    ])
    return [Container(
        accent_color=CATEGORY_ACCENTS[category_id],
        components=body,
    )]


async def _create_bulk_state(
    ctx,
    account,
    inventory: dict,
    *,
    mongo: MongoClient,
    category_id: str,
    scope: str = "category",
    selected_ids: list[str] | None = None,
) -> tuple[str | None, dict]:
    """Persist one owner-bound category or scanner-finish edit session."""
    if category_id not in CATEGORY_BY_ID or scope not in {
        "category", "scan_finish"
    }:
        raise ValueError("invalid card bulk scope")

    if scope == "scan_finish":
        requested = list(selected_ids or ())
        editable_ids = _ordered_card_ids(requested)
        if (
            not editable_ids
            or editable_ids != requested
            or set(editable_ids) & set(_card_reservations(inventory))
        ):
            raise ValueError("invalid scanner finish scope")
        selected = list(editable_ids)
        phase = "continue"
    else:
        editable_ids = _bulk_editable_ids(category_id, inventory)
        selected = []
        phase = "select"

    saved_cards = normalize_cards(inventory.get("cards"))
    confirmed = _confirmed_count_ids(inventory)
    trusted = _trusted_card_ids(inventory)
    count_snapshot = {}
    for item_id in editable_ids:
        value = saved_cards.get(item_id, OWNED)
        count_snapshot[item_id] = (
            value if isinstance(value, int) and not isinstance(value, bool)
            else OWNED
        )
    unconfirmed_ids = [
        item_id for item_id in editable_ids
        if (
            item_id in trusted
            and count_snapshot[item_id] == DUPLICATE
            and item_id not in confirmed
        )
    ]
    state_id = None
    state = {
        "type": "cards_bulk_edit",
        "scope": scope,
        "user_id": int(ctx.user.id),
        "guild_id": _trade_guild_id(ctx),
        "account_tag": _normalize_tag(account.tag),
        "account_name": str(account.name),
        "category_id": category_id,
        "editable_ids": editable_ids,
        "count_snapshot": count_snapshot,
        "unconfirmed_ids": unconfirmed_ids,
        "selected_ids": selected,
        "required_entry_ids": selected if scope == "scan_finish" else [],
        "next_index": 0,
        "expected_revision": _inventory_revision_value(inventory),
        "processed_count": 0,
        "written_count": 0,
        "phase": phase,
        "nonce": secrets.token_urlsafe(5),
    }
    for _attempt in range(2):
        candidate = _bulk_state_id(account.tag, category_id, scope=scope)
        try:
            await insert_state(
                mongo,
                {"_id": candidate, **state},
                ttl=CARD_BULK_SESSION_FOR,
            )
        except DuplicateKeyError:
            continue
        except Exception:
            _log.exception(
                "could not create card bulk state tag=%s category=%s",
                _normalize_tag(account.tag), category_id,
            )
            break
        state_id = candidate
        break
    return state_id, state


async def _quantity_editor_view(
    ctx,
    account,
    inventory: dict,
    category_id: str,
    *,
    mongo: MongoClient,
    card_id: object = None,
    saved: str | None = None,
) -> list[Container]:
    """Render a category with a restart-safe, owner-bound bulk edit session."""
    state_id, _state = await _create_bulk_state(
        ctx,
        account,
        inventory,
        mongo=mongo,
        category_id=category_id,
    )
    return _quantity_editor(
        account,
        inventory,
        category_id,
        card_id=card_id,
        saved=saved,
        bulk_state_id=state_id,
    )


async def _dashboard_view(
    account,
    inventory: dict,
    *,
    account_count: int,
    mongo: MongoClient | None = None,
    guild_id: int | None = None,
    skip_paused_gate: bool = False,
    skip_swap_gate: bool = False,
    is_admin: bool | None = None,
):
    """The board - unless this account owes somebody an answer.

    An agreed swap that nobody confirms holds both cards out of matching, and
    the member has no reason to go looking for it. Asking the moment they open
    `/cards` is the only place they are guaranteed to see it.
    """
    # A hidden account is asked whether it wants to come back before it is
    # shown a board it cannot trade from. `|paused` on the custom_id is how
    # "Not now" gets past this without turning trading back on.
    if inventory.get("trading_paused") and not skip_paused_gate:
        return _trading_paused_view(account)
    # "Not yet" on the swap prompt needs the same one-render pass the paused
    # gate has, or the prompt re-renders itself and the button is a trap. The
    # next `/cards` open asks again, which is what its copy promises.
    if not skip_swap_gate and mongo is not None and guild_id is not None:
        pending = await _swap_awaiting_confirmation(
            mongo, tag=account.tag, guild_id=guild_id
        )
        if pending is not None:
            trade, role = pending
            return _swap_confirm_view(trade, role=role)
    board = await _render_inventory_board_async(account, inventory)
    return _dashboard(
        account,
        inventory,
        account_count=account_count,
        rendered_board=board,
        is_admin=is_admin,
    )


async def _swap_awaiting_confirmation(
    mongo: MongoClient, *, tag: str, guild_id: int
) -> tuple[dict, str] | None:
    """The oldest agreed swap this account has not answered for, if any."""
    tag = _normalize_tag(tag)
    try:
        rows = await mongo.card_trades.find({
            "kind": "trade",
            "guild_id": int(guild_id),
            "status": {"$in": list(SWAP_LIVE_STATUSES)},
            "$or": [{"requester_tag": tag}, {"holder_tag": tag}],
        }).sort("accepted_at", 1).to_list(length=25)
    except Exception:
        _log.info("swap confirmation lookup failed tag=%s", tag)
        return None
    for trade in rows:
        role = _trade_role_for(trade, tag)
        if role and _awaiting_confirmation(trade, role=role):
            return trade, role
    return None


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
            else _notice(
                "Duplicate checks complete",
                "No cards still need review.",
                accent=GREEN_ACCENT,
            )
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
    require_requester_family: bool = False,
) -> list[dict]:
    if guild_id is None:
        return []
    now = datetime.now(timezone.utc)
    query: dict = {
        "confirmed_at": {"$gte": now - MATCHABLE_FOR},
        "guild_id": guild_id,
    }

    # Current family-clan membership is an additional safety boundary. When
    # the clan database is unavailable or empty the search refuses, and the
    # caller says the search failed - an empty list here would render as
    # "nobody has a spare", which is a different claim and a false one.
    try:
        family_tags = [
            _normalize_tag(tag)
            for tag in await mongo.clans.distinct("tag")
            if _normalize_tag(tag)
        ]
    except Exception:
        _log.exception("card matching could not load family clan tags")
        raise CandidateLookupUnavailable from None
    if not family_tags:
        _log.warning("card matching disabled because no family clan tags are configured")
        raise CandidateLookupUnavailable
    if (
        require_requester_family
        and _normalize_tag(requester.get("clan_tag")) not in set(family_tags)
    ):
        return []
    query["clan_tag"] = {"$in": family_tags}

    documents = await mongo.card_inventories.find(query).to_list(length=2_000)
    requester_tag = _normalize_tag(requester.get("_id"))
    return [
        _without_reserved_cards(document)
        for document in documents
        if _normalize_tag(document.get("_id")) != requester_tag
    ]


def _holder_line(match, ordinal: int, *, clan_emoji: dict | None = None) -> str:
    """One holder: their name, then everything else as one subtext line.

    The category and the give/get pair used to repeat under every holder,
    which is the same three lines said once per person. They are identical for
    everyone on this screen, so they moved to the top and each holder is now
    two lines instead of nine.
    """
    mention = (
        f"<@{match.holder_discord_id}>"
        if match.holder_discord_id
        else "Discord member"
    )
    clan = str(match.holder_clan_name or "").strip()
    badge = _clan_emoji_markup((clan_emoji or {}).get(
        _normalize_tag(match.holder_clan_tag)
    )) if clan else ""
    where = (
        f"{badge} {_escape_markdown(clan, limit=40)} • "
        f"`{_normalize_tag(match.holder_clan_tag)}`"
        if clan
        else "no clan"
    )
    standing = "**same clan**" if match.same_clan else "different clan"
    returns: list[str] = []
    wanted: list[str] = []
    categories: set[str] = set()
    for exchange in match.exchanges:
        returns.extend(exchange.returns)
        wanted.extend(exchange.wanted_returns)
        categories.add(exchange.category)
    if wanted:
        wants = "wants " + ", ".join(
            CARD_BY_ID[card_id].name for card_id in wanted[:3]
            if card_id in CARD_BY_ID
        )
    elif returns:
        # They already own everything you could give, which is fine: your card
        # becomes a duplicate for them. This used to read "wants nothing back",
        # which sounded like a decision they had made rather than a fact about
        # your own collection.
        wants = "your card becomes a spare for them"
    else:
        cost = max(
            (TRADE_GEM_COST.get(category, 0) for category in categories),
            default=0,
        )
        wants = (
            f"you have no spare to give — **costs you {cost} gems** {emojis.gems}"
            if cost else "you have no spare to give"
        )
    return (
        f"**{ordinal}. {_escape_markdown(match.holder_name, limit=40)}** "
        f"{mention}\n"
        f"-# {where} • {standing} • {wants} • "
        f"updated {_relative_timestamp(match.confirmed_at)}"
    )


def _match_line(match, ordinal: int) -> str:
    """One holder, in three labelled parts with a blank line between each.

    Everything used to run together: name, tag, category, both card lists and
    the clan footer, at one type size with no gaps. The lists are what a member
    reads, so they get headings and breathing room; the identifiers drop to
    subtext.
    """
    mention = (
        f"<@{match.holder_discord_id}>"
        if match.holder_discord_id
        else "Discord member"
    )
    location = _escape_markdown(match.holder_clan_name or "No clan", limit=50)
    same_clan = " • **same clan**" if match.same_clan else " • different clan"

    blocks = [
        f"**{ordinal}. {_escape_markdown(match.holder_name, limit=50)}**  "
        f"{mention}"
    ]
    for exchange in match.exchanges:
        category = CATEGORY_BY_ID[exchange.category]
        blocks.append(
            f"### {category_markup(category.id)} {category.short_name}\n"
            "**You get**\n"
            f"{_card_rows(exchange.offers)}"
        )
        if exchange.returns:
            blocks.append(
                "**You give back**\n" + _card_rows(exchange.returns)
            )
        else:
            blocks.append(
                "-# Nothing of yours matches. Ask if they will help anyway."
            )
    blocks.append(
        f"-# `{match.holder_tag}` • {location}{same_clan} • "
        f"updated {_relative_timestamp(match.confirmed_at)}"
    )
    return "\n\n".join(blocks)


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
            # Three different trades, and the difference is what it costs you.
            # `free` means you hold a same-category duplicate to hand over;
            # without one the event makes you pay gems instead. `mutual` is
            # the subset where they are also missing what you would give.
            free = bool(exchange.returns)
            mutual = bool(exchange.wanted_returns)
            for card_id in exchange.offers:
                entry = per_card.setdefault(
                    card_id,
                    {"givers": set(), "mutual": set(), "free": set()},
                )
                entry["givers"].add(match.holder_tag)
                if mutual:
                    entry["mutual"].add(match.holder_tag)
                if free:
                    entry["free"].add(match.holder_tag)
    return per_card


def _offer_rows(card_ids: list[str], per_card: dict) -> str:
    """Grouped bullets, one line per card, with who can supply it.

    The category name is a heading rather than a bold line, and the groups are
    separated by a blank line. Without both, four categories of bullets render
    as one undifferentiated wall at a single type size.
    """
    by_category: dict[str, list[str]] = {}
    for card_id in card_ids:
        by_category.setdefault(CARD_BY_ID[card_id].category, []).append(card_id)
    # A second heading level under the section heading read as a new section:
    # "## Even swaps" then "### Elixir" made the cards look like they belonged
    # to Elixir rather than to the swaps. A bold line is unmistakably inside
    # the section. With only one category there is nothing to separate, so the
    # label is dropped entirely.
    labelled = len(by_category) > 1
    blocks = []
    for category in CATEGORIES:
        rows = by_category.get(category.id)
        if not rows:
            continue
        lines = (
            [f"{category_markup(category.id)} **{category.short_name}**"]
            if labelled
            else []
        )
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
    # A blank line between groups; the bullets already sit tight within one.
    return "\n\n".join(blocks)


MATCH_LIST_PAGE = 12


def _match_list_view(
    account,
    *,
    title: str,
    blurb: str,
    rows: str,
    action: str,
    page: int,
    pages: int,
    accent: object,
    pickers: list | None = None,
) -> list[Container]:
    """One paginated list, shared by the favour and demand screens.

    Both are the same shape - a heading, grouped bullets and page controls -
    so they are one function. Sixty cards would not fit a single message and
    a family of any size can push either list past that.
    """
    tag = _normalize_tag(account.tag)
    body: list = [
        Text(content=title),
        Text(content=f"-# {blurb}"),
        Separator(divider=False),
    ]
    if pickers:
        body.extend(pickers)
    else:
        body.append(Text(content=rows or "-# Nothing here right now."))
    if pages > 1:
        body.extend([
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"{action}:{tag}|{page - 1}",
                    label="Previous",
                    emoji=PREVIOUS_EMOJI,
                    is_disabled=page <= 0,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"{action}:{tag}|{page}",
                    label=f"Page {page + 1}/{pages}",
                    is_disabled=True,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"{action}:{tag}|{page + 1}",
                    label="Next",
                    emoji=NEXT_EMOJI,
                    is_disabled=page >= pages - 1,
                ),
            ]),
        ])
    body.extend([
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_matches:{tag}",
                label="Back to Find trades",
                emoji=RETURN_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{tag}",
                label="Back to collection",
                emoji=HOME_EMOJI,
            ),
        ]),
    ])
    return [_panel(accent, body)]


def _favours_view(
    account, matches: list, *, page: int = 0, spares: int = 0
) -> list[Container]:
    """Cards in a category where you hold no duplicate at all.

    These cost YOU gems, not the holder. The event only lets a request be
    posted by somebody offering a duplicate, so when you have none the holder
    posts the offer and you answer it - and answering without a duplicate of
    what they asked for is exactly what the gems pay for.

    This screen previously said the sender paid, which is backwards, and
    quoted no figure at all.
    """
    per_card = _offers_by_card(matches)
    oneway = [c for c in CARDS if c.id in per_card and not per_card[c.id]["mutual"]]
    return _match_list_view(
        account,
        title=f"# {emojis.card_give} Ask for help",
        blurb=(
            "You have no spare in these categories, so there is nothing you "
            f"can hand over — **you pay gems instead** {emojis.gems}: "
            + " · ".join(
                f"{CATEGORY_BY_ID[category].short_name} **{cost}**"
                for category, cost in TRADE_GEM_COST.items()
                if category in CATEGORY_BY_ID
            )
            + ". The other player posts the trade in game and you answer it. "
            "Open the menu for the card you want, pick it, then ask whoever "
            "holds it."
        ),
        rows="",
        action="cards_favours",
        # One menu per category means every card fits, so there is no second
        # page to hide any of them behind.
        page=0,
        pages=1,
        accent=GOLD_ACCENT,
        pickers=_category_card_pickers(
            _normalize_tag(account.tag),
            [card.id for card in oneway],
            per_card,
        ),
    )


def _demand_view(
    account, inventory: dict, supply: dict | None, *, page: int = 0
) -> list[Container]:
    """Your spares that other people are missing."""
    mine = normalize_cards(inventory.get("cards"))
    wanted = [
        card for card in CARDS
        if mine.get(card.id, OWNED) >= DUPLICATE
        and supply and supply.get(card.id) and supply[card.id].demand
    ]
    pages = max(1, math.ceil(len(wanted) / MATCH_LIST_PAGE))
    page = min(max(0, page), pages - 1)
    window = wanted[page * MATCH_LIST_PAGE:(page + 1) * MATCH_LIST_PAGE]

    blocks = []
    for category in CATEGORIES:
        rows = [c for c in window if c.category == category.id]
        if not rows:
            continue
        lines = [f"### {category_markup(category.id)} {category.short_name}"]
        for card in rows:
            icon = troop_emoji.markup(card.id)
            lead = f"{icon} " if icon else ""
            demand = supply[card.id].demand
            lines.append(
                f"- {lead}**{_escape_markdown(card.name)}** — "
                f"{demand} need{'s' if demand == 1 else ''} it"
            )
        blocks.append("\n".join(lines))

    return _match_list_view(
        account,
        title=f"# {emojis.card_hot} Your spares others want",
        blurb="Other players need these. Good cards to offer.",
        rows="\n\n".join(blocks),
        action="cards_demand",
        page=page,
        pages=pages,
        # A list to read, not something waiting on the player: no accent.
        accent=None,
    )


def _card_pickers(
    tag: str, card_ids: list[str], per_card: dict, *, placeholder: str
) -> list:
    """Menus listing the cards themselves, not the categories they live in.

    One menu while the list fits Discord's 25-option cap, which it almost
    always does. Beyond that it splits by category, because that is the only
    grouping guaranteed to fit - but the labels stay card names either way, so
    a member never has to know which category a card belongs to.
    """
    def option(card_id: str) -> SelectOption:
        entry = per_card.get(card_id) or {}
        givers = len(entry.get("givers") or ())
        return SelectOption(
            label=CARD_BY_ID[card_id].name,
            value=card_id,
            description=(
                f"{givers} can give it"
                + (" · they want one of yours" if entry.get("mutual") else "")
            )[:100],
            emoji=troop_emoji.partial(card_id),
        )

    if len(card_ids) <= 25:
        return [ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_open_card:{tag}",
            placeholder=placeholder[:150],
            max_values=1,
            options=[option(card_id) for card_id in card_ids],
        )])]

    rows: list = []
    for category in CATEGORIES:
        in_category = [
            card_id for card_id in card_ids
            if CARD_BY_ID[card_id].category == category.id
        ]
        if not in_category:
            continue
        rows.append(ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_open_card:{tag}|{category.id}",
            placeholder=f"{placeholder} · {category.short_name}"[:150],
            max_values=1,
            options=[option(card_id) for card_id in in_category[:25]],
        )]))
    return rows


def _member_names(bot, discord_ids, *, guild_id: int | None) -> dict[int, str]:
    """Discord display names, from cache only.

    The member intent is on, so the cache already holds the family and this
    costs no API call. A miss simply leaves the name out and the caller falls
    back to the in-game name, which is why nothing here raises.
    """
    names: dict[int, str] = {}
    if bot is None or guild_id is None:
        return names
    for discord_id in discord_ids:
        if not discord_id or int(discord_id) in names:
            continue
        try:
            member = bot.cache.get_member(int(guild_id), int(discord_id))
        except Exception:
            continue
        if member is None:
            continue
        shown = str(
            getattr(member, "display_name", None)
            or getattr(member, "username", "")
        ).strip()
        if shown:
            names[int(discord_id)] = shown
    return names


def _browse_picker(
    tag: str,
    candidates: list[dict],
    *,
    names: dict[int, str],
    clan_tag: str | None,
) -> list:
    """Look a player up by name, rather than by guessing one of their cards.

    Every other route into this data starts from a card you are missing, which
    dead-ends the moment you are missing nothing anyone holds. This starts from
    the person, so it keeps working either way.

    Keyed on the Discord name because that is what people recognise in chat;
    the in-game name rides along for the accounts nobody knows by handle.
    """
    people: dict[str, list[dict]] = {}
    for document in candidates:
        if document.get("trading_paused"):
            continue        # they opted out; they should not be browsable
        discord_id = document.get("discord_id")
        key = f"d:{int(discord_id)}" if discord_id else f"t:{_normalize_tag(document.get('_id'))}"
        people.setdefault(key, []).append(document)

    def option(key: str, documents: list[dict]) -> SelectOption:
        # Spares are counted across every account they own, because the count
        # is only there to say whether the lookup is worth making. Counted the
        # same way the lookup lists them: Ready categories only.
        spares = 0
        for document in documents:
            ready = set(document.get("complete_categories") or ())
            counts = normalize_cards(document.get("cards"))
            spares += sum(
                1
                for card in CARDS
                if card.category in ready
                and counts.get(card.id, OWNED) >= DUPLICATE
            )
        discord_id = documents[0].get("discord_id")
        shown = names.get(int(discord_id)) if discord_id else None
        in_game = str(documents[0].get("player_name") or "").strip()
        label = shown or in_game or str(documents[0].get("_id") or "Unknown")
        if shown and in_game and in_game.lower() != shown.lower():
            label = f"{shown} · {in_game}"
        detail = f"{spares} spare{'s' if spares != 1 else ''}"
        if len(documents) > 1:
            detail += f" · {len(documents)} accounts"
        return SelectOption(
            label=label[:100], value=key, description=detail[:100],
        )

    def rank(item: tuple[str, list[dict]]) -> tuple[int, str]:
        # Clanmates first, so the 25 that survive the cap are the people you
        # can actually trade with today. Alphabetical inside that, because a
        # menu you are scanning for one name is easier to read sorted.
        _key, documents = item
        same_clan = bool(
            clan_tag
            and any(
                _normalize_tag(document.get("clan_tag")) == clan_tag
                for document in documents
            )
        )
        return (0 if same_clan else 1, option(_key, documents).label.lower())

    options = [option(key, docs) for key, docs in sorted(people.items(), key=rank)]
    if not options:
        return []
    return [ActionRow(components=[TextSelectMenu(
        custom_id=f"cards_browse:{tag}",
        placeholder="Look up a player by name",
        max_values=1,
        options=options[:25],
    )])]


def _player_spares_view(
    viewer_tag: str,
    viewer_inventory: dict,
    documents: list[dict],
    *,
    display_name: str,
    lookup_value: str | None = None,
    focused_tag: str | None = None,
) -> list[Container]:
    """Everything one player has spare, per account.

    Deliberately NOT merged across their accounts: you trade in game with one
    account, in one clan, so a merged list would tell you somebody has a card
    that is actually sitting on an alt you cannot reach.
    """
    mine = normalize_cards(viewer_inventory.get("cards"))
    title = f"# {emojis.magnifier} {_escape_markdown(display_name)}"
    rendered_accounts: list[tuple[dict, list, str]] = []
    total = 0
    for document in sorted(
        documents, key=lambda d: str(d.get("player_name") or "")
    ):
        spares = normalize_cards(document.get("cards"))
        # Only categories the holder marked Ready to trade are listed. A
        # half-reviewed category's counts are not supply any trade path would
        # accept, so showing them here invites asks that must be refused.
        ready = set(document.get("complete_categories") or ())
        held = [
            card for card in CARDS
            if card.category in ready
            and spares.get(card.id, OWNED) >= DUPLICATE
        ]
        total += len(held)
        clan = str(document.get("clan_name") or "").strip()
        heading = f"**{_escape_markdown(str(document.get('player_name') or 'Unknown'))}**"
        if clan:
            heading += f" · {_escape_markdown(clan)}"
        account_lines = [heading]
        if not held:
            account_lines.append("-# No spares on this account right now.")
            rendered_accounts.append((document, held, "\n".join(account_lines)))
            continue
        for category in CATEGORIES:
            in_category = [c for c in held if c.category == category.id]
            if not in_category:
                continue
            lines = []
            for card in in_category:
                # The whole reason to look somebody up is to spot the ones you
                # need, so they are marked rather than left to be cross-checked.
                needed = mine.get(card.id, OWNED) == MISSING
                lines.append(
                    f"- {_card_label(card)}"
                    + (" — **you need this**" if needed else "")
                )
            account_lines.append(
                f"{category_markup(category.id)} **{category.short_name}**\n"
                + "\n".join(lines)
            )
        rendered_accounts.append((document, held, "\n".join(account_lines)))

    nothing_spare = (
        "-# Nothing spare anywhere. Their collection is recorded, they "
        "just have no duplicates to give."
    )
    full_text_length = len(title) + sum(
        len(content) for _document, _held, content in rendered_accounts
    )
    if total == 0:
        full_text_length += len(nothing_spare)

    # Text Display's 4,000-character ceiling applies to the whole Components
    # V2 message, not to each Text component independently. Keep the familiar
    # all-account view when it fits. Rich multi-account owners use the same
    # cards_browse select to focus one complete account at a time, so no spare
    # is truncated and old d:/t: lookup values remain valid.
    selected_tag = _normalize_tag(focused_tag)
    focused_mode = bool(selected_tag) or full_text_length > PLAYER_LOOKUP_TEXT_LIMIT
    selected_account: tuple[dict, list, str] | None = None
    if focused_mode and rendered_accounts:
        if selected_tag:
            selected_account = next(
                (
                    rendered
                    for rendered in rendered_accounts
                    if _normalize_tag(rendered[0].get("_id")) == selected_tag
                ),
                None,
            )
            if selected_account is None:
                return _notice(
                    "Nothing to show",
                    "That linked account is no longer available. Open "
                    "**Find trades** again.",
                )
        else:
            selected_account = next(
                (
                    rendered
                    for rendered in rendered_accounts
                    if _normalize_tag(rendered[0].get("_id"))
                    == _normalize_tag(viewer_tag)
                ),
                rendered_accounts[0],
            )
        selected_tag = _normalize_tag(selected_account[0].get("_id"))

    body: list = [Text(content=title)]
    if focused_mode and selected_account is not None:
        account_count = len(rendered_accounts)
        note = (
            f"-# Showing 1 of {account_count} linked accounts. "
            "Choose another account below."
            if account_count > 1
            else ""
        )
        if note:
            body.append(Text(content=note))

        if account_count > 1:
            if not lookup_value:
                owner_id = selected_account[0].get("discord_id")
                try:
                    lookup_value = f"d:{int(owner_id)}" if owner_id else None
                except (TypeError, ValueError):
                    lookup_value = None
            if not lookup_value:
                return _notice(
                    "Player lookup is too large",
                    "Open **Find trades** again for a fresh player list.",
                )
            options = []
            for document, held, _content in rendered_accounts:
                tag = _normalize_tag(document.get("_id"))
                player = _plain(document.get("player_name"), limit=70)
                label = f"{player} · {tag}" if tag else player
                clan = _plain(document.get("clan_name"), limit=65)
                spare_count = len(held)
                detail = f"{spare_count} spare{'s' if spare_count != 1 else ''}"
                if clan and clan != "Unknown":
                    detail = f"{clan} · {detail}"
                options.append(SelectOption(
                    label=label[:100],
                    value=f"{lookup_value}|a:{tag}",
                    description=detail[:100],
                    is_default=tag == selected_tag,
                ))
            body.append(ActionRow(components=[TextSelectMenu(
                custom_id=f"cards_browse:{viewer_tag}",
                placeholder="Choose a linked account",
                max_values=1,
                options=options,
            )]))

        body.append(Separator(divider=True))
        account_content = selected_account[2]
        reserved_text = len(title) + len(note)
        if total == 0:
            reserved_text += len(nothing_spare)
        if len(account_content) + reserved_text > PLAYER_LOOKUP_TEXT_LIMIT:
            return _notice(
                "Player lookup is too large",
                "That account has more spare-card text than Discord can show "
                "safely. Nothing was changed.",
            )
        body.append(Text(content=account_content))
    else:
        if rendered_accounts:
            body.append(Separator(divider=True))
        body.extend(
            Text(content=content)
            for _document, _held, content in rendered_accounts
        )

    if total == 0:
        body.append(Text(content=nothing_spare))
    body.append(ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_matches:{viewer_tag}",
            label="Back to Find trades",
            emoji=RETURN_EMOJI,
        ),
    ]))
    return [Container(components=body)]


def _is_cards_admin_id(discord_id: object, *, bot=None) -> bool:
    """Whether one Discord user runs the family. Never raises."""
    guild_id = _configured_cards_guild_id()
    if guild_id is None or not discord_id:
        return False
    if bot is None:
        bot = bot_data.data.get("bot")
    if bot is None:
        return False
    try:
        member = bot.cache.get_member(guild_id, int(discord_id))
        guild = bot.cache.get_guild(guild_id)
    except Exception:
        return False
    return bool(
        guild_permissions(member, guild) & hikari.Permissions.ADMINISTRATOR
    )


def _is_cards_admin(ctx, *, bot=None) -> bool:
    """Whether whoever sent this interaction runs the family.

    Deliberately the SAME lookup that draws the button, not a second one based
    on the interaction's own member object. Two implementations disagreed: the
    button appeared and then the handler refused it. Whatever answer decides
    the button has to be the answer that decides access.

    It also means "admin of the family server", not "admin of whichever server
    you happened to click in", and it works identically from a DM.
    """
    return _is_cards_admin_id(getattr(ctx.user, "id", None), bot=bot)


async def _admin_stats(mongo: MongoClient, *, guild_id: int) -> dict:
    """The handful of numbers that answer "is anyone actually using this".

    Everything here is already stored, so it is retroactive: no counters were
    added and no data had to accumulate first.
    """
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    scope = {"guild_id": int(guild_id)}
    inventories = mongo.card_inventories
    trades = mongo.card_trades
    live = list(SWAP_LIVE_STATUSES) + ["pending"]

    async def people(extra: dict | None = None) -> set[int]:
        """Distinct humans, not inventory rows.

        One person can own several accounts, so counting documents counted a
        main and its alts as separate members - and listed somebody who uses
        this every day as having entered nothing, because one of their alts
        was empty.
        """
        try:
            found = await inventories.distinct(
                "discord_id", {**scope, **(extra or {})}
            )
        except Exception:
            _log.exception("cards admin count failed")
            return set()
        return {int(value) for value in found if value}

    opened = await people()
    entered = await people({"cards": {"$nin": [{}, None]}})
    stalled_ids = opened - entered

    stats = {
        "opened": len(opened),
        "entered": len(entered),
        "finished": len(await people(
            {"complete_categories": {"$size": len(CATEGORIES)}}
        )),
        "hidden": len(await people({"trading_paused": True})),
        "active": len(await people({"last_seen_at": {"$gte": week}})),
        "proposed": await trades.count_documents({**scope, "kind": "trade"}),
        "completed": await trades.count_documents(
            {**scope, "kind": "trade", "status": "completed"}
        ),
        "expired": await trades.count_documents(
            {**scope, "kind": "trade", "status": "expired"}
        ),
        "live": await trades.count_documents(
            {**scope, "kind": "trade", "status": {"$in": live}}
        ),
        "stalled_total": len(stalled_ids),
    }

    # The only actionable part of the screen: people with no cards on ANY of
    # their accounts. Bounded, because a long list is not more actionable.
    stats["stalled"] = []
    if stalled_ids:
        rows = await inventories.find(
            {**scope, "discord_id": {"$in": sorted(stalled_ids)[:ADMIN_NUDGE_LIMIT]}}
        ).sort("created_at", 1).to_list(length=ADMIN_NUDGE_LIMIT * 4)
        seen: set[int] = set()
        for row in rows:
            discord_id = int(row.get("discord_id") or 0)
            if discord_id and discord_id not in seen:
                seen.add(discord_id)
                stats["stalled"].append(row)
    return stats


ADMIN_NUDGE_LIMIT = 10


def _admin_view(
    stats: dict, *, names: dict[int, str], tag: str = ""
) -> list[Container]:
    """Six numbers and one list of names. Deliberately nothing else.

    Any figure that does not either say whether this is working or who to go
    talk to was left out - a longer screen would just be a data dump nobody
    acts on.
    """
    opened = stats["opened"]
    entered = stats["entered"]
    dropped = max(0, opened - entered)
    body: list = [
        Text(content=f"# {emojis.magnifier} Cards · admin"),
        Text(content=(
            f"**{entered} of {opened} people** who opened it entered cards."
            + (f"\n-# {dropped} entered nothing on any account." if dropped else "")
        )),
        Separator(divider=True),
        Text(content=(
            f"- **{stats['finished']}** finished all {len(CATEGORIES)} categories\n"
            f"- **{stats['active']}** used it in the last 7 days\n"
            f"- **{stats['hidden']}** hidden (turned trading off, or went quiet)"
        )),
        Separator(divider=True),
        Text(content=(
            f"**Trades** · {stats['proposed']} proposed · "
            f"{stats['completed']} completed · {stats['expired']} expired · "
            f"{stats['live']} live right now"
        )),
    ]

    stalled = stats.get("stalled") or []
    if stalled:
        total = int(stats.get("stalled_total") or len(stalled))
        # A mention already renders the name. Printing both put the same
        # person on screen twice, which is what made this list a wall.
        lines = [
            f"- <@{int(document['discord_id'])}>"
            if document.get("discord_id")
            else f"- {_escape_markdown(str(document.get('player_name') or document.get('_id')))}"
            for document in stalled
        ]
        more = (
            f"\n-# Showing {len(stalled)} of {total}."
            if total > len(stalled) else ""
        )
        body.extend([
            Separator(divider=True),
            Text(content=(
                "## Worth a nudge\n"
                "-# Opened `/cards`, entered nothing on any account.\n"
                + "\n".join(lines) + more
            )[:4000]),
        ])
    body.append(ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{_normalize_tag(tag)}",
            label="Back to collection",
            emoji=RETURN_EMOJI,
        ),
    ]))
    return [Container(components=body)]


def _category_card_pickers(tag: str, card_ids: list[str], per_card: dict) -> list:
    """One menu per category, which is what removes paging entirely.

    The biggest category holds 19 cards, so every category fits inside
    Discord's 25-option limit with room for its header. A single combined menu
    could not, which is why this screen used to page - and a Next button on a
    list of cards is a worse way to find one than four labelled menus.

    Each menu carries the category art on its closed state through the same
    default-option trick the board uses.
    """
    rows: list = []
    for category in CATEGORIES:
        in_category = [
            card_id for card_id in card_ids
            if CARD_BY_ID[card_id].category == category.id
        ]
        if not in_category:
            continue      # nothing to ask for here; an empty menu is noise
        options = []
        for card_id in in_category[:24]:
            entry = per_card.get(card_id) or {}
            givers = len(entry.get("givers") or ())
            options.append(SelectOption(
                label=CARD_BY_ID[card_id].name,
                value=card_id,
                description=(
                    f"{givers} can give it"
                    + (" · they want one of yours" if entry.get("mutual") else "")
                )[:100],
                emoji=troop_emoji.partial(card_id),
            ))
        detail = f"{len(options)} to ask for"
        rows.append(ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_open_card:{tag}|{category.id}",
            placeholder=f"{category.name} · {detail}"[:150],
            max_values=1,
            options=[_category_header_option(category, detail), *options],
        )]))
    return rows


def _matches_view(
    account,
    inventory: dict,
    matches: list,
    *,
    supply: dict | None = None,
    achievable: tuple[int, int] | None = None,
    reserved: int = 0,
    browse: list | None = None,
) -> list[Container]:
    tag = _normalize_tag(account.tag)
    per_card = _offers_by_card(matches)
    # A swap where both sides get something is the one worth doing first. The
    # rest are still real - somebody may hand a card over for a duplicate they
    # do not need - so they stay, one rank down rather than mixed in.
    # Split on cost, not on whether they happen to want your card. A swap
    # where they already own what you give is still free and still legal - it
    # just leaves them a duplicate. Only a category where you hold no spare at
    # all costs you gems, and that is the one worth separating.
    mutual_ids = [c for c in CARDS if c.id in per_card and per_card[c.id]["free"]]
    oneway_ids = [
        c for c in CARDS if c.id in per_card and not per_card[c.id]["free"]
    ]
    holders_total = len({match.holder_tag for match in matches})

    # The card menus only exist for even swaps. Saying "pick a card from the
    # menu below" when there are none sent people hunting for a menu that was
    # never drawn - and pointed them at whichever menu happened to be below.
    if mutual_ids:
        lead = "**Pick a card from the menu below.**"
    elif oneway_ids:
        lead = "**No even swaps right now.** Tap **Ask for help** below."
    else:
        lead = "**Nothing to trade for right now.**"
    summary_line = (
        f"{lead}\n"
        f"-# {holders_total} collection"
        f"{'s' if holders_total != 1 else ''} can supply something you need."
    )
    if reserved:
        # Cards held by an accepted trade are masked out of matching, which
        # makes an obvious swap silently disappear. Saying so is the whole
        # difference between "the bot is broken" and "that one is spoken for".
        summary_line += (
            f"\n-# {reserved} of your card{'s are' if reserved != 1 else ' is'} "
            "promised to an accepted trade, so they are hidden here until it "
            "finishes. See **My trades**."
        )
    body: list = [
        Text(content=f"# {emojis.magnifier} Find trades"),
        Text(content=summary_line),
    ]
    if mutual_ids:
        # The cards ARE the menu. Printing them as text above an unrelated
        # menu is what lost people: a member read "Electro Dragon" and then had
        # to work out for themselves that it lived behind a menu called
        # "Elixir". One thing to tap, and it lists what it acts on.
        body.extend([
            Separator(divider=True),
            Text(content=(
                f"## {emojis.balance_scale} Even swaps\n"
                "-# They have what you need and want one of your spares.\n"
                "-# Tap the menu, pick a card, then tap **Ask to swap**."
            )),
            *_card_pickers(
                tag, [c.id for c in mutual_ids], per_card,
                placeholder="Pick a card to swap for",
            ),
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
    if not per_card:
        body.extend([
            Separator(divider=True),
            Text(content=(
                "Nobody in the family has a spare of anything you are missing "
                "yet. This fills in as more people record their collections."
            )),
        ])

    if achievable and achievable[1] > 1:
        # Only worth saying when it changes what you would do: one spare
        # offered to five people is still one trade. Silent otherwise.
        body.append(Text(content=(
            f"-# You could complete up to **{achievable[1]}** of these."
        )))

    # The two secondary lists moved behind their own buttons. Printed inline
    # they tripled the height of the screen, and neither is what a member came
    # here to do: even swaps are the trades that actually complete.
    secondary: list = []
    if not per_card and _requestable_card_ids(inventory):
        # Nothing to trade for, but the member holds a spare in a finished
        # category where they are missing cards: a public want-ad in the
        # channel reaches the collections the matcher cannot see. Without a
        # spare the button would lead straight to a refusal, so it is not
        # drawn.
        secondary.append(Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_req_pick:{tag}",
            label="Post a request",
        ))
    if oneway_ids:
        secondary.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_favours:{tag}",
            label=f"Ask for help ({len(oneway_ids)})",
            emoji=GIVE_EMOJI,
        ))
    if wanted_from_me:
        secondary.append(Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_demand:{tag}",
            label=f"Spares others want ({len(wanted_from_me)})",
            emoji=HOT_EMOJI,
        ))
    if secondary:
        body.extend([Separator(divider=True), ActionRow(components=secondary)])

    if browse:
        # The one route in here that does not start from a card you are
        # missing. Everything above this line is empty for somebody whose
        # collection is complete; this still answers "what has Poppa got".
        body.extend([
            Separator(divider=True),
            Text(content=(
                f"## {emojis.inbox} Look up a player\n"
                "-# See everything one person has spare, by name."
            )),
            *browse,
        ])

    body.append(ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{tag}",
            label="Back to collection",
            emoji=RETURN_EMOJI,
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_trades:{tag}",
            label="My trades",
            emoji=TRADES_EMOJI,
        ),
    ]))
    # Green only when there is something to act on. An empty result is not a
    # warning, so it carries no accent.
    return [_panel(GREEN_ACCENT if per_card else None, body)]


async def _clan_emoji_map(mongo: MongoClient, holders: list) -> dict:
    """{clan tag: emoji markup} for the clans on screen, best effort.

    One query for the whole page. A failure is cosmetic - every clan just
    falls back to a shield - so it must never take the panel down.
    """
    tags = {
        _normalize_tag(match.holder_clan_tag)
        for match in holders
        if getattr(match, "holder_clan_tag", None)
    }
    if not tags:
        return {}
    try:
        rows = await mongo.clans.find(
            {"tag": {"$in": sorted(tags)}}, {"tag": 1, "emoji": 1}
        ).to_list(length=len(tags))
    except Exception:
        _log.info("holder clan emoji lookup failed")
        return {}
    return {
        _normalize_tag(row.get("tag")): str(row.get("emoji") or "")
        for row in rows
    }


def _holders_view(
    account,
    card_id: str,
    holders: list,
    *,
    page: int = 0,
    clan_emoji: dict | None = None,
    can_request: bool = False,
) -> list[Container]:
    card = CARD_BY_ID[card_id]
    category = CATEGORY_BY_ID[card.category]
    # Same clan first: those two can trade right now, everybody else has to
    # move an account before the cards can go anywhere. Stable within each
    # group, so the underlying match order still decides ties.
    holders = sorted(holders, key=lambda match: not match.same_clan)
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
            if holder_components:
                # A rule between people, so six holders read as six entries
                # rather than one continuous block of names and cards.
                holder_components.append(Separator(divider=True))
            line = Text(content=_holder_line(
                holder, index, clan_emoji=clan_emoji
            ))
            if tag in askable:
                holder_components.append(Section(
                    components=[line],
                    accessory=Button(
                        style=hikari.ButtonStyle.PRIMARY,
                        custom_id=(
                            f"cards_trade_holder:"
                            f"{_normalize_tag(account.tag)}|{card.id}|{tag}"
                        ),
                        label="Ask to swap",
                    ),
                ))
            elif holder.holder_discord_id is not None:
                # No spare to offer, so this cannot be a swap - but it can
                # still be an ask. The bot sends it so the whole approve and
                # deny flow stays here rather than turning into cold DMs.
                holder_components.append(Section(
                    components=[line],
                    accessory=Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=(
                            f"cards_gem_ask:{_normalize_tag(account.tag)}|"
                            f"{card.id}|{tag}"
                        ),
                        label="Ask for help",
                        emoji=GIVE_EMOJI,
                    ),
                ))
            else:
                holder_components.append(line)
    else:
        holder_components = [Text(content=(
            f"Nobody currently lists a duplicate **{card.name}**. "
            "Check again later as more family members finish setup."
        ))]
        if can_request:
            # The headline case for the public want-ad: the matcher found
            # nobody, but the matcher only sees recorded collections. A post
            # in the channel reaches everyone it cannot. Only offered when
            # the member holds a same-category spare - the game will not open
            # a trade without one to give back.
            holder_components.append(ActionRow(components=[Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=(
                    f"cards_req_new:{_normalize_tag(account.tag)}|{card.id}"
                ),
                label="Post a request",
            )]))
    # What you get is the same for everyone on this screen, so it is said
    # once at the top instead of once per holder.
    same_clan_total = sum(1 for match in holders if match.same_clan)
    components: list = [
        Text(content=f"# {category_markup(card.category)} Who has {card.name}?"),
        Text(content=(
            f"**You get:** {_card_label(card)}\n"
            f"-# {category.short_name} • searching for "
            f"**{_escape_markdown(account.name)}** • "
            f"`{_normalize_tag(account.tag)}`"
            + (
                f"\n-# {same_clan_total} of these are in your clan and can "
                "trade right away, listed first."
                if same_clan_total
                else ""
            )
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
    elif holders:
        # No Ask button on any of them, and until now the screen said nothing
        # about why - it just listed people and stopped. The event will not let
        # you post a request without a duplicate to offer, so the trade has to
        # start from their side and the instructions have to say so.
        cost = TRADE_GEM_COST.get(card.category, 0)
        # `can_request` is whether the member holds a same-category spare.
        # The old copy said "You have no spare" in both cases, which was a
        # lie whenever the member DOES hold one that no listed holder needs.
        why_not = (
            f"None of these players need your spare "
            f"**{category.short_name}** cards, so you "
            if can_request
            else f"You have no spare **{category.short_name}** card, so you "
        )
        components.extend([
            Separator(divider=True),
            Text(content=(
                f"## {emojis.card_give} What to do now\n"
                + why_not
                + "cannot start this trade. They start it for you.\n\n"
                # Names the button on this screen rather than telling anybody
                # to go and write a message. One verb, one button, the same
                # words as the label - which is what a reader translating in
                # their head needs.
                f"**1.** Tap **Ask for help** next to a player.\n"
                "**2.** They get a message and answer yes or no.\n"
                "**3.** If they say yes, they put the trade in the game.\n"
                f"**4.** You tap **Trade**, then **Use Gems** — **{cost} "
                f"gems** {emojis.gems}. You keep all your cards.\n\n"
                "-# You both need to be in the same clan to trade."
            )),
        ])
        if can_request:
            # The listed holders cannot be asked, but the matcher's blind
            # spots (paused, stale, unscanned collections) are exactly who a
            # public want-ad reaches. Same spare precondition as above.
            components.append(ActionRow(components=[Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=(
                    f"cards_req_new:{_normalize_tag(account.tag)}|{card.id}"
                ),
                label="Post a request",
            )]))
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
                    emoji=PREVIOUS_EMOJI,
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
                    emoji=NEXT_EMOJI,
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
                emoji=RETURN_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
                label="Back to collection",
                emoji=HOME_EMOJI,
            ),
        ]),
    ])
    # Nobody holding a spare is an empty result, not a warning.
    return [_panel(GREEN_ACCENT if holders else None, components)]


def _trade_offer_view(account, card_id: str, holder) -> list[Container]:
    wanted = CARD_BY_ID[card_id]
    category = CATEGORY_BY_ID[wanted.category]
    exchange = next(
        (item for item in holder.exchanges if item.category == wanted.category),
        None,
    )
    return_ids = exchange.returns if exchange is not None else ()
    givable = [return_id for return_id in return_ids if return_id in CARD_BY_ID]
    if not givable:
        return _notice(
            "That reciprocal match changed",
            "Refresh the holder list; this player no longer needs a compatible spare.",
        )

    tag = _normalize_tag(account.tag)
    holder_tag = _normalize_tag(holder.holder_tag)
    if len(givable) == 1:
        # Nothing to choose. A one-option menu still made the member open it,
        # read the only entry and pick it, to reach a conclusion the bot had
        # already worked out, so the offer sends straight from the button.
        only = CARD_BY_ID[givable[0]]
        icon = troop_emoji.markup(only.id)
        instruction = (
            f"You have one card they need: "
            f"{icon + ' ' if icon else ''}**{only.name}**.\n"
            "The bot rechecks both collections when they accept. This proposal "
            "does not reserve cards."
        )
        chooser = ActionRow(components=[Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=(
                f"cards_trade_request:{tag}|{wanted.id}"
                f"|{holder_tag}|{only.id}"
            ),
            label=f"Send offer · give {only.name}"[:80],
            emoji=troop_emoji.partial(only.id),
        )])
    else:
        instruction = (
            "Choose one duplicate to give. The bot rechecks both collections "
            "when the other player accepts. This proposal does not reserve cards."
        )
        chooser = ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_trade_request:{tag}|{wanted.id}",
            placeholder="Choose the duplicate you will give...",
            min_values=1,
            max_values=1,
            options=[
                SelectOption(
                    label=CARD_BY_ID[return_id].name,
                    value=f"{holder.holder_tag}|{return_id}",
                    description=_plain(
                        f"Give to {holder.holder_name}", limit=100
                    ),
                    # The troop's own art, so the menu reads as cards rather
                    # than a list of words, like every other card menu.
                    emoji=troop_emoji.partial(return_id),
                )
                for return_id in givable
            ],
        )])

    # Composing an offer is not a success yet: no accent.
    return [_panel(None, [
        Text(content=f"# 🤝 Swap for {wanted.name}"),
        Text(content=(
            f"**You receive:** {wanted.name}\n"
            f"**From:** {_escape_markdown(holder.holder_name, limit=60)} "
            f"· `{holder_tag}`\n\n"
            f"{instruction}"
        )),
        Separator(divider=True),
        chooser,
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_holder_page:{_normalize_tag(account.tag)}"
                    f"|{wanted.id}|0"
                ),
                label="Back to holders",
                emoji=RETURN_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_matches:{_normalize_tag(account.tag)}",
                label="All matches",
                emoji=SEARCH_EMOJI,
            ),
        ]),
    ])]


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
    """Untrust only the card values a legacy trade may have changed."""
    marker = f"card_trade_review_invalidations.{trade['_id']}"
    safe = 0
    for tag, affected_ids in _trade_inventory_cards(trade).items():
        handled = False
        async with _inventory_lock(tag):
            # Cross-process inventory writes can race cleanup. The revision
            # fence prevents a projection computed from an older document
            # from replacing newer trust; cleanup remains queued if retries
            # cannot obtain a current snapshot.
            for _attempt in range(3):
                current = await mongo.card_inventories.find_one({
                    "_id": tag,
                    "guild_id": int(trade["guild_id"]),
                })
                if current is None:
                    handled = True
                    break
                invalidations = current.get(
                    "card_trade_review_invalidations", {}
                )
                if not isinstance(invalidations, dict):
                    invalidations = {}
                if str(trade["_id"]) in invalidations:
                    handled = True
                    break

                trusted_ids, ready_categories, reviewed_lists = _trust_projection(
                    current, remove=affected_ids
                )
                invalidated_at = datetime.now(timezone.utc)
                revision = _inventory_revision_value(current)
                revision_guard = (
                    {"$or": [
                        {"inventory_revision": {"$exists": False}},
                        {"inventory_revision": 0},
                    ]}
                    if revision == 0
                    else {"inventory_revision": revision}
                )
                result = await mongo.card_inventories.update_one(
                    {
                        "_id": tag,
                        "guild_id": int(trade["guild_id"]),
                        marker: {"$exists": False},
                        **revision_guard,
                    },
                    {
                        "$set": {
                            "trusted_card_ids": trusted_ids,
                            "complete_categories": ready_categories,
                            "reviewed_lists": reviewed_lists,
                            marker: invalidated_at,
                            "updated_at": invalidated_at,
                            "update_source": "trade_needs_review",
                        },
                        "$pull": {
                            "count_confirmed_card_ids": {
                                "$in": list(affected_ids)
                            },
                        },
                        "$inc": {"inventory_revision": 1},
                    },
                )
                if getattr(result, "matched_count", 0):
                    handled = True
                    break
        if handled:
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
    chosen_card_id: str | None = None,
) -> tuple[str, str]:
    """Reserve exact cards on acceptance, never while merely proposed.

    `chosen_card_id` lets the accepter take a different one of the requester's
    spares. It is written INSIDE the pending -> reserving CAS below, which is
    the single-winner gate: only the accept that wins can change the card, and
    every fence and lease afterwards is derived from the updated document. A
    losing accept cannot repoint a card that is already reserved, and cleanup
    can never release a different card from the one it locked.
    """
    await _reconcile_trade_cleanups(
        mongo, guild_id=int(trade["guild_id"])
    )
    await _recover_stalled_reservations(
        mongo, now=now, guild_id=int(trade["guild_id"])
    )
    reservation_token = secrets.token_hex(8)
    reservation_until = now + TRADE_COMPLETION_FOR
    taken = str(chosen_card_id or trade["given_card_id"])
    if taken not in _trade_choice_ids(trade):
        return "changed", "unavailable"
    started = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": "pending"},
        {"$set": {
            "status": "reserving",
            "given_card_id": taken,
            "open_proposal_key": _open_proposal_key(
                dict(trade, given_card_id=taken)
            ),
            "reservation_token": reservation_token,
            "reservation_until": reservation_until,
            "accepted_at": now,
            "accepted_by": int(user_id),
            "updated_at": now,
            # Nothing starts the confirm clock until somebody confirms, so an
            # agreed swap both players abandon would hold their cards forever.
            # This is the only thing that can end that state.
            "backstop_at": now + SWAP_BACKSTOP_FOR,
        }},
    )
    if not getattr(started, "modified_count", 0):
        return "changed", str(trade.get("status") or "changed")
    trade = dict(trade)
    trade.update({
        "status": "reserving",
        # Every fence, lease and cleanup below reads this dict, so the chosen
        # card has to land here too or they would lock one card and release
        # another.
        "given_card_id": taken,
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
        await _answered_a_request(mongo, trade.get("holder_tag"))
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
    # The clan's own emoji, copied onto the trade so a notification never
    # depends on a query that could fail later. A missing row, a missing field
    # or unparseable markup all end up as "", which renders as a shield.
    clan_emoji: dict[str, str] = {}
    for clan_tag in {
        _normalize_tag(requester.get("clan_tag")),
        _normalize_tag(holder.get("clan_tag")),
    }:
        if not clan_tag:
            continue
        try:
            row = await mongo.clans.find_one({"tag": clan_tag}, {"emoji": 1})
        except Exception:
            _log.info("card trade clan emoji lookup failed clan=%s", clan_tag)
            continue
        clan_emoji[clan_tag] = str((row or {}).get("emoji") or "")

    trade = {
        "_id": secrets.token_hex(8),
        "kind": "trade",
        "status": "pending",
        "guild_id": int(guild_id),
        "category": CARD_BY_ID[wanted_card_id].category,
        "requester_clan_tag": requester.get("clan_tag"),
        "requester_clan_name": requester.get("clan_name"),
        "requester_clan_emoji": clan_emoji.get(
            _normalize_tag(requester.get("clan_tag")), ""
        ),
        # Copied onto the trade rather than looked up when a DM is built, so a
        # notification never depends on a second query that could fail.
        "requester_town_hall": requester.get("town_hall") or 0,
        "requester_tag": _normalize_tag(requester.get("_id")),
        "requester_name": str(requester.get("player_name") or "Unknown player"),
        "requester_discord_id": requester_discord_id,
        "holder_tag": _normalize_tag(holder.get("_id")),
        "holder_name": str(holder.get("player_name") or "Unknown player"),
        "holder_discord_id": holder_discord_id,
        "holder_clan_tag": holder.get("clan_tag"),
        "holder_clan_name": holder.get("clan_name"),
        "holder_clan_emoji": clan_emoji.get(
            _normalize_tag(holder.get("clan_tag")), ""
        ),
        "holder_town_hall": holder.get("town_hall") or 0,
        "wanted_card_id": wanted_card_id,
        "given_card_id": given_card_id,
        "compatible_card_ids": compatible_card_ids,
        "created_at": now,
        "updated_at": now,
        # Read by the deadline sweeper. Absolute, so a restart resumes and
        # a bot that was down processes everything overdue on the next pass.
        "accept_deadline_at": now + SWAP_ACCEPT_FOR,
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


def _open_request_offer_ids(inventory: dict, card) -> list[str]:
    """Every same-category card this member could give back: spares only.

    The game will not open a trade without a duplicate offered in return, so
    an empty list here refuses the whole open-request flow - that member's
    route is the gem **Ask for help** instead. Reserved cards are masked the
    same way `_create_trade_request` masks them, so a spare promised to an
    accepted trade cannot be promised to the channel too.
    """
    values = normalize_cards(_without_reserved_cards(inventory).get("cards"))
    return [
        item.id
        for item in CATEGORY_CARDS[card.category]
        if values.get(item.id, OWNED) >= DUPLICATE
    ]


def _requestable_card_ids(inventory: dict) -> list[str]:
    """The missing cards a want-ad may name for this member.

    Restricted to finished categories where they also hold a spare to give
    back - the two preconditions `_create_open_request` enforces - so the
    picker can never offer a card whose request would then be refused.
    """
    values = normalize_cards(_without_reserved_cards(inventory).get("cards"))
    complete = {str(v) for v in inventory.get("complete_categories") or ()}
    spare_categories = {
        CARD_BY_ID[card_id].category
        for card_id, count in values.items()
        if card_id in CARD_BY_ID and count >= DUPLICATE
    }
    return [
        card.id
        for card in CARDS
        if card.category in complete
        and card.category in spare_categories
        and values.get(card.id, OWNED) == MISSING
    ]


async def _create_open_request(
    mongo: MongoClient,
    *,
    requester_inventory: dict,
    wanted_card_id: str,
    guild_id: int,
) -> tuple[dict | None, str | None]:
    """Save one open request, or say exactly why not.

    Mirrors `_create_trade_request`'s contract: (document, None) on success,
    (None, member-facing error) on refusal. The sparse-unique
    `open_request_key` index is the one-open-request-per-card guard; every
    terminal transition must `$unset` it so the member can ask again later.
    """
    now = datetime.now(timezone.utc)
    card = CARD_BY_ID.get(str(wanted_card_id))
    if card is None:
        return None, "That card is not in the catalog."
    tag = _normalize_tag(requester_inventory.get("_id"))
    try:
        same_family = int(requester_inventory.get("guild_id")) == int(guild_id)
    except (TypeError, ValueError):
        same_family = False
    if not same_family:
        return None, "The collection must belong to this Discord family."
    if not inventory_is_matchable(requester_inventory):
        return None, (
            "Your collection needs a fresh update before anything goes on "
            "the family board. Open **Update collection** first."
        )
    category = CATEGORY_BY_ID[card.category]
    complete = {
        str(v) for v in requester_inventory.get("complete_categories") or ()
    }
    if card.category not in complete:
        return None, (
            f"Finish entering your **{category.short_name}** category first, "
            "then post the request."
        )
    values = normalize_cards(
        _without_reserved_cards(requester_inventory).get("cards")
    )
    if values.get(card.id, OWNED) != MISSING:
        return None, (
            f"You are not missing **{card.name}**, so there is nothing to "
            "request."
        )
    offer_ids = _open_request_offer_ids(requester_inventory, card)
    if not offer_ids:
        # The game's rule, not ours: no duplicate to give back means the trade
        # cannot start from this side at all (see the holders screen's "What
        # to do now"). The gem ask is the route built for exactly this case.
        return None, (
            f"You have no spare **{category.short_name}** card to give back, "
            "so the game will not let this trade start from your side. Use "
            "**Ask for help** next to a holder instead - they start the "
            "trade and you pay gems."
        )
    try:
        requester_discord_id = int(requester_inventory.get("discord_id"))
    except (TypeError, ValueError):
        return None, (
            "The collection must be linked to a current Discord member."
        )
    open_requests = await mongo.card_trades.find({
        "kind": "open_request",
        "guild_id": int(guild_id),
        "status": "open",
        "requester_tag": tag,
    }).to_list(length=MAX_OPEN_REQUESTS_PER_ACCOUNT)
    if len(open_requests) >= MAX_OPEN_REQUESTS_PER_ACCOUNT:
        return None, (
            f"`{tag}` already has {MAX_OPEN_REQUESTS_PER_ACCOUNT} open "
            "requests. Close one in **My trades** before posting another."
        )
    # The clan's own emoji, copied onto the request so a channel post never
    # depends on a query that could fail later - same policy as
    # `_create_trade_request`.
    clan_tag = _normalize_tag(requester_inventory.get("clan_tag"))
    clan_emoji = ""
    if clan_tag:
        try:
            row = await mongo.clans.find_one({"tag": clan_tag}, {"emoji": 1})
            clan_emoji = str((row or {}).get("emoji") or "")
        except Exception:
            _log.info(
                "open request clan emoji lookup failed clan=%s", clan_tag
            )
    request = {
        "_id": secrets.token_hex(8),
        "kind": "open_request",
        "status": "open",
        # The gem-ask staleness pattern: a button from a reused or stale post
        # carries an old generation and is refused instead of acted on.
        "generation": int(now.timestamp()),
        "guild_id": int(guild_id),
        "category": card.category,
        "wanted_card_id": card.id,
        "offer_card_ids": list(offer_ids),
        # Copied at creation like `_create_trade_request` does: a notification
        # must never depend on a later query that could fail.
        "requester_tag": tag,
        "requester_name": str(
            requester_inventory.get("player_name") or "Unknown player"
        ),
        "requester_discord_id": requester_discord_id,
        "requester_town_hall": requester_inventory.get("town_hall") or 0,
        "requester_clan_tag": requester_inventory.get("clan_tag"),
        "requester_clan_name": requester_inventory.get("clan_name"),
        "requester_clan_emoji": clan_emoji,
        "channel_id": None,
        "channel_message_id": None,
        # Claim fields, present from birth so the claim CAS and its sweeper
        # never have to reason about $exists.
        "claim_token": None,
        "claim_until": None,
        "claimed_by_discord_id": None,
        "claimed_by_tag": None,
        "claimed_at": None,
        "trade_id": None,
        "created_at": now,
        "updated_at": now,
        # Read by the deadline sweeper. Absolute, so a restart resumes.
        "expires_at": now + OPEN_REQUEST_FOR,
        # Sparse-unique: one open request per card per account per family.
        # Every terminal transition $unsets it.
        "open_request_key": f"{int(guild_id)}:{tag}:{card.id}",
    }
    try:
        await mongo.card_trades.insert_one(request)
    except DuplicateKeyError:
        return None, (
            f"You already have an open request for **{card.name}**. Close "
            "it in **My trades** first."
        )
    return request, None


async def _open_requests_for(
    mongo: MongoClient, *, tag: str, guild_id: int
) -> list[dict]:
    """The member's own open want-ads, newest first, for My trades.

    The expires_at guard matches the deadline sweeper's cutoff: between a
    request's deadline and the sweep pass that closes it, the document still
    says status:"open", and without the guard My trades would render it as
    open right up until the sweeper caught up.
    """
    return await mongo.card_trades.find({
        "kind": "open_request",
        "guild_id": int(guild_id),
        "status": "open",
        "expires_at": {"$gt": datetime.now(timezone.utc)},
        "requester_tag": _normalize_tag(tag),
    }).sort("created_at", -1).to_list(length=MAX_OPEN_REQUESTS_PER_ACCOUNT)


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


def _trade_proposal_controls(
    trade: dict, choices: list, *, preview: bool
) -> list:
    """Accept/decline for the proposal DM, so no server trip is needed.

    With more than one card on offer the accept is a menu, because choosing
    which card you want and agreeing to the swap are the same decision. One
    option needs no menu.
    """
    trade_id = str(trade["_id"])
    rows: list = []
    if len(choices) > 1:
        rows.append(ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_dm_accept:{trade_id}",
            placeholder="Accept — pick the card you want",
            min_values=1,
            max_values=1,
            is_disabled=preview,
            options=[
                SelectOption(
                    label=card.name,
                    value=card.id,
                    emoji=troop_emoji.partial(card.id),
                )
                for card in choices[:25]
            ],
        )]))
        rows.append(ActionRow(components=[Button(
            style=hikari.ButtonStyle.DANGER,
            custom_id=f"cards_dm_decline:{trade_id}",
            label="Decline",
            emoji=CANCEL_EMOJI,
            is_disabled=preview,
        )]))
        return rows
    rows.append(ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=f"cards_dm_accept:{trade_id}|{choices[0].id}",
            label=f"Accept · take {choices[0].name}"[:80],
            emoji=emojis.yes.partial_emoji,
            is_disabled=preview,
        ),
        Button(
            style=hikari.ButtonStyle.DANGER,
            custom_id=f"cards_dm_decline:{trade_id}",
            label="Decline",
            emoji=CANCEL_EMOJI,
            is_disabled=preview,
        ),
    ]))
    return rows


def _trade_dm_container(
    title: str,
    body: str,
    *,
    accent: int,
    attachment=None,
    footer: str | None = None,
    controls: list | None = None,
    extra: list | None = None,
) -> list[Container]:
    """One shape for every trade DM, so they read like the panels do.

    These used to be raw content strings, which Discord renders as an
    undifferentiated wall next to the Components V2 panels the same bot sends
    everywhere else.
    """
    components: list = [Text(content=f"## {title}"), Text(content=body)]
    if extra:
        components.append(Separator(divider=True))
        components.extend(extra)
    if attachment is not None:
        # In a V2 message an attachment is not displayed on its own; it has to
        # be mounted in a gallery or it silently does not appear.
        components.extend([Separator(divider=True), Media(items=[
            MediaItem(media=attachment),
        ])])
    if controls:
        components.append(Separator(divider=True))
        components.extend(controls)
    if footer:
        components.extend([Separator(divider=True), Text(content=f"-# {footer}")])
    return [Container(accent_color=accent, components=components)]


async def _send_trade_dm(
    bot: hikari.GatewayBot,
    discord_id: int,
    components: list,
    *,
    trade_id: str,
) -> bool:
    try:
        channel = await bot.rest.create_dm_channel(int(discord_id))
        await bot.rest.create_message(
            channel=channel,
            components=components,
            flags=hikari.MessageFlag.IS_COMPONENTS_V2,
        )
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


def _trade_choice_ids(trade: dict) -> list[str]:
    """Every card the accepter may take: the proposed one plus the spares.

    `compatible_card_ids` is the requester's consent - the set they agreed to
    part with when they proposed - so it bounds the choice. Whether each one is
    still actually held is re-checked against live inventories afterwards.
    """
    ids = [str(trade.get("given_card_id") or "")]
    for card_id in trade.get("compatible_card_ids") or ():
        if str(card_id) not in ids:
            ids.append(str(card_id))
    return [card_id for card_id in ids if card_id in CARD_BY_ID]


def _trade_offer_names(trade: dict) -> str:
    card_ids = list(trade.get("compatible_card_ids") or ())
    if trade.get("given_card_id") not in card_ids:
        card_ids.insert(0, str(trade.get("given_card_id") or ""))
    return _card_names(card_ids, limit=8)


def _trade_location_line(trade: dict, *, role: str | None = None) -> str:
    """Where both accounts are, named.

    The different-clans case used to say only "you are in different family
    clans", which is the one case where the names matter: somebody has to
    move, and they cannot decide who without knowing where the other one is.
    """
    requester = (
        trade.get("requester_clan_name"),
        _normalize_tag(trade.get("requester_clan_tag")),
    )
    holder = (
        trade.get("holder_clan_name"),
        _normalize_tag(trade.get("holder_clan_tag")),
    )
    if requester[1] and requester[1] == holder[1]:
        # The name first: a bare tag tells a member nothing about where that is.
        return "You are both in " + _clan_label(*requester)
    if role not in {"holder", "requester"}:
        # The channel post is read by everyone, so it names neither side "you".
        return f"{_clan_label(*requester)} and {_clan_label(*holder)}"
    mine, theirs = (
        (holder, requester) if role == "holder" else (requester, holder)
    )
    return (
        f"you are in {_clan_label(*mine)}, "
        f"they are in {_clan_label(*theirs)}"
    )


# One wording per status, shared by the V2 standing post and the legacy
# plain-content post so the two renderings can never disagree about what a
# status is called.
TRADE_STATUS_LABELS = {
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

# Statuses whose standing post collapses to the compact closed form: the
# audit line stays visible, but nothing on it is clickable any more.
TRADE_POST_TERMINAL_STATUSES = frozenset(
    {"completed", "declined", "cancelled", "expired"}
)


def _trade_status_label(status: str) -> str:
    return TRADE_STATUS_LABELS.get(
        status, status.replace("_", " ").title()
    )


def _trade_channel_content(trade: dict) -> str:
    status = str(trade.get("status") or "pending")
    labels = TRADE_STATUS_LABELS
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


# The most people one message may mention. A ping list is built from a query,
# and a query can return more rows than anyone expected; truncating in the
# transport means no policy mistake upstream can produce a twenty-mention post.
MAX_PING_PER_MESSAGE = 5


async def _channel_post(
    bot: hikari.GatewayBot,
    *,
    content: str | None = None,
    components: list | None = None,
    ping: object = (),
    attachment=None,
    reply_to: int | None = None,
    key: object = None,
) -> int | None:
    """Post to the family trade board. Returns the message id, or None.

    Every mention decision lives here and nowhere else. `mentions_everyone` and
    `role_mentions` are hardcoded off, and `user_mentions` is always an explicit
    list of ids - never True, never left undefined. That makes a stray
    `@everyone` in a player's name inert by construction rather than by every
    caller remembering, and it is why a body can name both players while
    pinging only the one who has to act.

    Never raises. A trade is saved before it is announced, so a delivery
    failure must not unwind the trade - the caller reports where it landed.
    """
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        return None
    try:
        channel = await bot.rest.fetch_channel(channel_id)
        if int(getattr(channel, "guild_id", 0) or 0) != int(
            _configured_cards_guild_id() or 0
        ):
            # A misconfigured environment must not spray family trade data into
            # an unrelated server. This check is the reason it cannot.
            _log.error(
                "card trade channel is outside configured guild channel=%s",
                channel_id,
            )
            return None
        outgoing: dict = {
            "channel": channel_id,
            "mentions_everyone": False,
            "role_mentions": False,
            "user_mentions": _mention_allowlist(ping),
        }
        if content is not None:
            outgoing["content"] = content
        if components is not None:
            # Components V2 is a creation-time flag. A message posted without
            # it can never be edited into one, so this has to be right here.
            outgoing["components"] = components
            outgoing["flags"] = hikari.MessageFlag.IS_COMPONENTS_V2
        if attachment is not None:
            outgoing["attachment"] = attachment
        if reply_to is not None:
            outgoing["reply"] = int(reply_to)
            # A reply that pings the author on top of the explicit allowlist
            # would double-notify, and worse, notify somebody the policy did
            # not choose.
            outgoing["mentions_reply"] = False
        message = await bot.rest.create_message(**outgoing)
        return int(message.id)
    except Exception as exc:
        _log.info(
            "card channel post failed key=%s error=%s", key, type(exc).__name__,
        )
        return None


def _mention_allowlist(ping: object) -> list[int]:
    """The ids this message is allowed to notify, bounded and de-duplicated.

    Returns a list, never True and never undefined: an empty list is a
    genuinely silent post, which is a thing the policy asks for.
    """
    allowed: list[int] = []
    for value in ping or ():
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id not in allowed:
            allowed.append(user_id)
    return allowed[:MAX_PING_PER_MESSAGE]


async def _channel_edit(
    bot: hikari.GatewayBot,
    *,
    channel_id: object,
    message_id: object,
    content: str | None = None,
    components: list | None = None,
    key: object = None,
) -> bool:
    """Refresh a standing post in place. Never raises, and never notifies.

    All three mention controls are off and there is no parameter to turn them
    on, because an edit does not notify anybody in the first place - Discord
    only fires a notification on create. Making that structural stops a future
    caller from passing a ping here and quietly getting silence.
    """
    if channel_id is None or message_id is None:
        return False
    try:
        outgoing: dict = {
            "channel": int(channel_id),
            "message": int(message_id),
            "mentions_everyone": False,
            "role_mentions": False,
            "user_mentions": False,
        }
        if content is not None:
            outgoing["content"] = content
        if components is not None:
            outgoing["components"] = components
        await bot.rest.edit_message(**outgoing)
        return True
    except Exception as exc:
        _log.info(
            "card channel edit failed key=%s error=%s", key, type(exc).__name__,
        )
        return False


async def _post_trade_channel(bot: hikari.GatewayBot, mongo: MongoClient, trade: dict) -> bool:
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        return False
    attachment = await asyncio.to_thread(_trade_strip_attachment, trade)
    message_id = await _channel_post(
        bot,
        # The standing post is Components V2 so it can carry live controls.
        # The strip rides inside the message's own gallery (mounted in
        # `_trade_post`), which is the only way a V2 message shows an image.
        components=_trade_post(trade, attachment_ref=attachment),
        ping=[trade["holder_discord_id"]],
        key=trade.get("_id"),
    )
    if message_id is None:
        return False
    trade["channel_id"] = int(channel_id)
    trade["channel_message_id"] = message_id
    # V2 is a creation-time property: a legacy plain-content post can never be
    # edited into components, so the branch in `_update_trade_channel` keys on
    # this marker rather than on age or status. Absent-tolerant by design.
    trade["channel_post_v2"] = True
    if attachment is not None:
        # `given_card_id` can change when the accepter takes a different
        # spare, so the uploaded strip's filename is remembered rather than
        # recomputed - an edit that referenced a filename the message does
        # not carry would be refused whole.
        trade["channel_post_image"] = getattr(attachment, "filename", None)
    try:
        await mongo.card_trades.update_one(
            {"_id": trade["_id"], "kind": "trade"},
            {"$set": {
                "channel_id": int(channel_id),
                "channel_message_id": message_id,
                "channel_post_v2": True,
                **(
                    {"channel_post_image": trade["channel_post_image"]}
                    if trade.get("channel_post_image")
                    else {}
                ),
            }},
        )
    except Exception as exc:
        # The post is already up and the ids are on the in-memory trade, so the
        # caller's feedback is still correct. Only later status edits are lost,
        # and they fall back to the configured channel id anyway.
        _log.info(
            "card trade channel id write failed trade=%s error=%s",
            trade.get("_id"), type(exc).__name__,
        )
    return True


def _standing_post_image_ref(trade: dict) -> str | None:
    """Whether an edited standing post carries the strip. It does not.

    The original theory: Discord keeps a message's attachments when an edit
    omits the attachments field, so a gallery could re-reference the retained
    file as `attachment://filename` without re-uploading. The first live
    acceptance (2026-08-16) killed it one layer earlier than predicted:
    hikari 2.3.5 resolves a string media value as a local file path, so the
    edit died client-side with `FileNotFoundError` for a path literally
    named "attachment://card-trade-....png" - the request never reached
    Discord at all. So edits drop the image: every edit moves the trade PAST
    the proposal stage, where the two players already know the cards and the
    words carry the state. The image lives on in the creation-time post
    history and in both DMs.
    """
    return None


async def _update_trade_channel(bot: hikari.GatewayBot, trade: dict) -> bool:
    if str(trade.get("kind") or "") == "gem_ask":
        # Kind-aware, and checked FIRST: everything below assumes a
        # trade-shaped document (wanted/given/requester_*), which a gem ask
        # does not have. An ask without a channel post (a legacy DM-only one
        # still in flight) has no message id, and `_channel_edit` refuses
        # that quietly.
        return await _channel_edit(
            bot,
            channel_id=trade.get("channel_id") or _configured_cards_channel_id(),
            message_id=trade.get("channel_message_id"),
            components=_gem_ask_post(trade),
            key=trade.get("_id"),
        )
    if not trade.get("channel_post_v2"):
        # Legacy path, kept verbatim: a message created with `content=` can
        # never be edited into Components V2 (IS_COMPONENTS_V2 is a
        # creation-time flag), so in-flight trades posted before the V2
        # standing post keep their plain-content refresh until they drain.
        return await _channel_edit(
            bot,
            channel_id=trade.get("channel_id") or _configured_cards_channel_id(),
            message_id=trade.get("channel_message_id"),
            content=_trade_channel_content(trade),
            key=trade.get("_id"),
        )
    return await _channel_edit(
        bot,
        channel_id=trade.get("channel_id") or _configured_cards_channel_id(),
        message_id=trade.get("channel_message_id"),
        components=_trade_post(
            trade, attachment_ref=_standing_post_image_ref(trade)
        ),
        key=trade.get("_id"),
    )


def _trade_post_controls(trade: dict) -> list:
    """The standing post's live controls - present only while pending.

    Every other status has nothing a channel reader may do to it: an
    accepted swap is managed from **My trades** by its two participants, and
    a closed one is history. One colon per custom_id; the trade id is the
    whole action id.
    """
    if str(trade.get("status") or "pending") != "pending":
        return []
    trade_id = str(trade.get("_id") or "")
    taken = CARD_BY_ID[trade["given_card_id"]].name
    return [ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=f"cards_pub_accept:{trade_id}",
            # The card, not the holder's name: this family's names are full
            # of decorated unicode, and the first live label truncated one to
            # "Accept · ŦH̶Ɇ". The DM button already says take-the-card, so
            # both surfaces now match, and the footer plus the handler's own
            # participant check keep wrong tappers out.
            label=f"Accept · take {taken}"[:80],
        ),
        Button(
            style=hikari.ButtonStyle.DANGER,
            custom_id=f"cards_pub_decline:{trade_id}",
            label="Decline",
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_pub_cancel:{trade_id}",
            label="Cancel · requester",
        ),
    ])]


def _trade_post_accent(status: str):
    """GOLD while an answer is owed, GREEN once agreed, RED when a human
    must intervene, and no accent at all once the trade is history."""
    if status in {"pending", "reserving"}:
        return GOLD_ACCENT
    if status in {"move_needed", "ready", "accepted", "completing"}:
        return GREEN_ACCENT
    if status == "needs_review":
        return RED_ACCENT
    return None


def _trade_post(trade: dict, *, attachment_ref=None) -> list[Container]:
    """The V2 standing post for one trade, read by the whole channel.

    `attachment_ref` mounts the trade strip: a fresh `hikari.Bytes` when the
    post is created, an `attachment://` string when an edit re-references the
    already-uploaded file, or None for no image. In a V2 message an
    attachment must be mounted in a gallery or it silently does not appear.
    """
    status = str(trade.get("status") or "pending")
    label = _trade_status_label(status)
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    requester = _escape_markdown(trade.get("requester_name"), limit=60)
    holder = _escape_markdown(trade.get("holder_name"), limit=60)
    requester_id = int(trade["requester_discord_id"])
    holder_id = int(trade["holder_discord_id"])
    if status in TRADE_POST_TERMINAL_STATUSES:
        # Compact closed form: the audit line survives, nothing is clickable,
        # and the image is dropped rather than re-referenced.
        return [_panel(None, [Text(content=(
            f"**{label}**\n"
            f"-# {requester} (`{trade['requester_tag']}`) offered **{given}** "
            f"for {holder}'s (`{trade['holder_tag']}`) **{wanted}**."
        ))])]
    if status == "needs_review":
        # Not a happy path and not a public conversation: the details of what
        # went wrong arrive by DM, so the post says only that the swap is on
        # hold and where the two players sort it out.
        return [_panel(_trade_post_accent(status), [
            Text(content=f"## {label}"),
            Text(content=(
                f"<@{requester_id}> and <@{holder_id}> — this swap needs a "
                "check. Please open `/cards` → **My trades** and check your "
                "cards."
            )),
        ])]
    if status not in {"pending", "reserving"}:
        # ACCEPTED. The proposal detail has done its job - both players know
        # the cards - so the post becomes the coordination point: who trades
        # with whom, and the next tap. Short sentences, because the family
        # reads this in a dozen languages, and mentions without pings (the
        # transport's edit path cannot notify anyone).
        same_clan = _normalize_tag(
            trade.get("requester_clan_tag")
        ) == _normalize_tag(trade.get("holder_clan_tag"))
        steps = (
            "**1.** Talk here and pick a time.\n"
            + (
                ""
                if same_clan
                else "**2.** One of you moves to the other clan.\n"
            )
            + f"**{2 if same_clan else 3}.** Trade in game.\n"
            + f"**{3 if same_clan else 4}.** Tap **I sent my card** in "
            "`/cards` → **My trades**."
        )
        return [_panel(_trade_post_accent(status), [
            Text(content=f"## {label}"),
            # Mention AND account name on each line. A mention shows the
            # Discord user, and one user can hold both sides of a swap with
            # two linked accounts - the first live acceptance rendered as the
            # same person giving both cards. The account name is what tells
            # the two lines apart.
            Text(content=(
                f"<@{requester_id}> — **{requester}** gives **{given}**\n"
                f"<@{holder_id}> — **{holder}** gives **{wanted}**"
            )),
            Separator(divider=True),
            Text(content=steps),
            Separator(divider=True),
            Text(content=f"-# 📍 {_trade_location_line(trade)}"),
        ])]
    # PENDING: the proposal itself. Blocks are kept short and separated -
    # the first live post rendered as one dense clump next to the airier DM,
    # and a wall of text is exactly what a channel skimmer skips.
    components: list = [
        Text(content=f"## {label}"),
        Text(content=(
            f"<@{holder_id}> — **{requester}** needs your duplicate "
            f"**{wanted}**."
        )),
        Separator(divider=True),
        Text(content=(
            f"**They give:** {given}\n"
            f"**You give:** {wanted}\n"
            f"-# You could also take: {_trade_offer_names(trade)}"
        )),
        Separator(divider=True),
        Text(content=(
            _player_line(
                "Asking", trade.get("requester_name"),
                trade.get("requester_tag"), trade.get("requester_town_hall"),
                trade.get("requester_clan_name"),
                trade.get("requester_clan_emoji"),
            )
            + "\n"
            + _player_line(
                "Holding", trade.get("holder_name"), trade.get("holder_tag"),
                trade.get("holder_town_hall"), trade.get("holder_clan_name"),
                trade.get("holder_clan_emoji"),
            )
            + f"\n-# 📍 {_trade_location_line(trade)}"
        )),
    ]
    if attachment_ref is not None:
        components.extend([Separator(divider=True), Media(items=[
            MediaItem(media=attachment_ref),
        ])])
    controls = _trade_post_controls(trade)
    if controls:
        components.append(Separator(divider=True))
        components.extend(controls)
    components.append(Text(content=(
        f"-# Only <@{holder_id}> can accept or decline; "
        f"<@{requester_id}> can cancel. Anyone in the trade can also use "
        "`/cards` → **My trades**."
    )))
    return [_panel(_trade_post_accent(status), components)]


def _accepted_channel_note(trade: dict) -> list[Container]:
    """The short acceptance reply under the standing post.

    Addressed to the requester - they are the one being pinged - and small on
    purpose: the standing post right above it carries the full detail.
    """
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    holder = _escape_markdown(trade.get("holder_name"), limit=40)
    return [_panel(GREEN_ACCENT, [Text(content=(
        f"✅ <@{int(trade['requester_discord_id'])}> — **{holder}** accepted. "
        f"You give **{given}**, you get **{wanted}**. "
        "Next steps in `/cards` → **My trades**."
    ))])]


def _claimed_channel_note(trade: dict) -> list[Container]:
    """The short claim reply under the reused want-ad post.

    `trade` is the CONVERTED kind:"trade" document (poster = requester,
    claimer = holder), so the requester mention here reaches the member who
    posted the want-ad. Small on purpose, like `_accepted_channel_note`: the
    standing post right above it - the want-ad's own message, just edited
    into `_trade_post` - carries the full detail. "has your {wanted}" rather
    than "accepted" is deliberate: the wording stays true even when the
    reservation could not land and the trade waits as a pending proposal.
    """
    wanted = CARD_BY_ID[trade["wanted_card_id"]].name
    given = CARD_BY_ID[trade["given_card_id"]].name
    holder = _escape_markdown(trade.get("holder_name"), limit=40)
    return [_panel(GREEN_ACCENT, [Text(content=(
        f"✅ <@{int(trade['requester_discord_id'])}> — **{holder}** has your "
        f"{wanted}. You give **{given}**, you get **{wanted}**. "
        "Next steps in `/cards` → **My trades**."
    ))])]


# One wording per status for the want-ad's standing post, mirroring
# TRADE_STATUS_LABELS so the two boards speak one language.
OPEN_REQUEST_STATUS_LABELS = {
    "open": "🃏 Card wanted",
    "claiming": "🟡 Being claimed",
    "claimed": "✅ Claimed",
    "cancelled": "⚪ Closed by the requester",
    "expired": "⌛ Expired",
}

# Statuses whose want-ad post collapses to the compact closed form: the audit
# line stays visible, nothing on it is clickable any more.
OPEN_REQUEST_TERMINAL_STATUSES = frozenset({"claimed", "cancelled", "expired"})


def _open_request_status_label(status: str) -> str:
    return OPEN_REQUEST_STATUS_LABELS.get(
        status, status.replace("_", " ").title()
    )


def _open_request_post(request: dict) -> list[Container]:
    """The V2 standing post for one open request, read by the whole channel.

    Small on purpose: one claim button while open, the compact closed form
    with zero interactive components once the request is over. The claim
    button's custom_id carries the generation, the gem-ask staleness pattern,
    so a stale panel refuses instead of acting.
    """
    status = str(request.get("status") or "open")
    label = _open_request_status_label(status)
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    card_name = card.name if card else "Unknown card"
    requester = _escape_markdown(request.get("requester_name"), limit=60)
    if status in OPEN_REQUEST_TERMINAL_STATUSES:
        return [_panel(None, [Text(content=(
            f"**{label}**\n"
            f"-# {requester} (`{request.get('requester_tag')}`) asked the "
            f"family for **{card_name}**."
        ))])]
    components: list = [
        Text(content=f"## {label}"),
        Text(content=(
            f"**{requester}** (`{request.get('requester_tag')}`) is missing "
            f"{_card_label(card) if card else f'**{card_name}**'}.\n"
            "**Can give back one of:** "
            f"{_card_names(request.get('offer_card_ids') or (), limit=8)}"
        )),
        Separator(divider=True),
        Text(content=(
            _player_line(
                "Asking", request.get("requester_name"),
                request.get("requester_tag"),
                request.get("requester_town_hall"),
                request.get("requester_clan_name"),
                request.get("requester_clan_emoji"),
            )
            + "\n⏳ Open until "
            + _relative_timestamp(request.get("expires_at"))
        )),
    ]
    if status == "open":
        components.extend([
            Separator(divider=True),
            ActionRow(components=[Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=(
                    f"cards_pub_claim:{request.get('_id')}|"
                    f"{int(request.get('generation') or 0)}"
                ),
                label="I have this card",
            )]),
        ])
    components.append(Text(content=(
        f"-# Have a spare **{card_name}**? Tap **I have this card** and you "
        f"get one of {requester}'s duplicates back. {requester} can close "
        "this in `/cards` → **My trades**."
    )))
    return [_panel(GOLD_ACCENT if status == "open" else None, components)]


async def _post_open_request_channel(
    bot: hikari.GatewayBot, mongo: MongoClient, request: dict
) -> bool:
    """Post the want-ad as its own V2 standing post. Pings nobody.

    Same shape as `_post_trade_channel`: the message ids land on both the
    in-memory document and the stored one, so the feedback string and every
    later edit know where the post lives.
    """
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        return False
    message_id = await _channel_post(
        bot,
        components=_open_request_post(request),
        # The policy row says a want-ad pings nobody; the empty allowlist is
        # what makes that structural rather than remembered.
        ping=(),
        key=request.get("_id"),
    )
    if message_id is None:
        return False
    request["channel_id"] = int(channel_id)
    request["channel_message_id"] = message_id
    request["channel_post_v2"] = True
    try:
        await mongo.card_trades.update_one(
            {"_id": request["_id"], "kind": "open_request"},
            {"$set": {
                "channel_id": int(channel_id),
                "channel_message_id": message_id,
                "channel_post_v2": True,
            }},
        )
    except Exception as exc:
        # The post is already up and the ids are on the in-memory document,
        # so the caller's feedback stays correct; only later edits are lost.
        _log.info(
            "open request channel id write failed request=%s error=%s",
            request.get("_id"), type(exc).__name__,
        )
    return True


# Statuses whose gem-ask post collapses to the compact closed form: the audit
# line stays visible, nothing on it is clickable any more.
GEM_ASK_TERMINAL_STATUSES = frozenset({"accepted", "declined"})


def _gem_ask_post(ask: dict) -> list[Container]:
    """The V2 standing post for one gem ask, read by the whole channel.

    Modeled on `_gem_ask_dm` - which stays byte-identical as the fallback
    payload - but channel-appropriate: the holder is addressed by mention,
    both players are named for everyone else reading, and the buttons carry
    the ask id + generation exactly like the DM pair so the same staleness
    guard applies. Small on purpose; an answered ask collapses to one line.
    """
    status = str(ask.get("status") or "pending")
    card = CARD_BY_ID[ask["card_id"]]
    category = CATEGORY_BY_ID[card.category]
    asker = _escape_markdown(ask.get("asker_name"), limit=60)
    holder = _escape_markdown(ask.get("holder_name"), limit=60)
    if status in GEM_ASK_TERMINAL_STATUSES:
        answer = "yes" if status == "accepted" else "no"
        return [_panel(None, [Text(content=(
            f"**💎 Gem ask answered — {answer}**\n"
            f"-# {asker} asked {holder} for **{card.name}**."
        ))])]
    holder_id = int(ask["holder_discord_id"])
    generation = int(ask.get("generation") or 0)
    return [_panel(GOLD_ACCENT, [
        Text(content=f"## 💎 Help wanted — {card.name}"),
        Text(content=(
            f"<@{holder_id}> — **{asker}** is missing {_card_label(card)} "
            f"and has no **{category.short_name}** spare to give back. "
            f"They pay **{ask.get('gem_cost')} gems** {emojis.gems} — you "
            "keep all your cards."
        )),
        Separator(divider=True),
        Text(content=(
            "**If you say yes**\n"
            "Post the trade in game.\n"
            f"Offer your {_card_label(card)}. Ask for any "
            f"**{category.short_name}** card."
        )),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                # The ask id itself contains colons; the dispatcher partitions
                # on the FIRST colon only, exactly as the cards_gem_yes DM
                # pair already relies on, so this routes fine.
                custom_id=f"cards_pub_gem_yes:{ask['_id']}|{generation}",
                label="Yes, I will post it",
                emoji=emojis.yes.partial_emoji,
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_pub_gem_no:{ask['_id']}|{generation}",
                label="No thanks", emoji=CANCEL_EMOJI,
            ),
        ]),
        Text(content=(
            f"-# Only <@{holder_id}> can answer. Nothing changes in anyone's "
            "collection until they trade in game."
        )),
    ])]


async def _post_gem_ask_channel(
    bot: hikari.GatewayBot, mongo: MongoClient, ask: dict
) -> bool:
    """Post the gem ask as its own V2 standing post, pinging the holder.

    Same shape as `_post_trade_channel`: the message ids land on both the
    in-memory document and the stored one, so the feedback string and the
    later answer edit know where the post lives.
    """
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        return False
    message_id = await _channel_post(
        bot,
        components=_gem_ask_post(ask),
        ping=[ask["holder_discord_id"]],
        key=ask.get("_id"),
    )
    if message_id is None:
        return False
    ask["channel_id"] = int(channel_id)
    ask["channel_message_id"] = message_id
    ask["channel_post_v2"] = True
    try:
        await mongo.card_trades.update_one(
            {"_id": ask["_id"], "kind": "gem_ask"},
            {"$set": {
                "channel_id": int(channel_id),
                "channel_message_id": message_id,
                "channel_post_v2": True,
            }},
        )
    except Exception as exc:
        # The post is already up and the ids are on the in-memory document,
        # so the caller's feedback stays correct; only later edits are lost.
        _log.info(
            "gem ask channel id write failed ask=%s error=%s",
            ask.get("_id"), type(exc).__name__,
        )
    return True


class _EventPolicy(NamedTuple):
    """What one lifecycle event is allowed to do to people's attention."""

    posts: bool          # a NEW channel message (the only thing that pings)
    pings: str | None    # "holder" | "requester" | None
    edits: bool          # refresh the standing post in place (never notifies)
    dm: str              # "never" | "fallback" | "always"


# THE delivery policy. Every trade event routes through `_deliver`, which
# consults this table and nothing else - call sites no longer decide who gets
# posted at, pinged, or DMed. Exactly two events may create a channel message,
# and `test_only_listed_events_may_post_and_ping` pins that set: widening it
# is a deliberate one-row change here, never an accident at a call site.
#
# The two posting events ship with dm="always" for the first live-verification
# window (both parties still get their familiar DM while the pings are
# confirmed to land). The planned end state is dm="fallback" - a DM only when
# the channel post fails - and flipping one table entry here is the whole
# rollback lever, no code path changes.
TRADE_DELIVERY: dict[str, _EventPolicy] = {
    "proposal_created": _EventPolicy(
        posts=True, pings="holder", edits=False, dm="always"
    ),
    "proposal_accepted": _EventPolicy(
        posts=True, pings="requester", edits=True, dm="always"
    ),
    # A want-ad IS its standing post and pings NOBODY - by construction it is
    # posted because the matcher found no holder, so there is nobody to aim
    # at. The sticky drives eyes to the channel instead. Never a DM: there is
    # no recipient.
    "open_request_posted": _EventPolicy(
        posts=True, pings=None, edits=False, dm="never"
    ),
    # A claimed want-ad reuses its own message as the resulting trade's
    # standing post (edits=True refreshes it into `_trade_post`); the short
    # reply-note underneath is the post that pings. The document delivered
    # for this event is the CONVERTED kind:"trade" doc, so pings="requester"
    # reaches the original poster. dm="always" for the same first
    # live-verification window as the other two pinging events - the planned
    # end state is dm="fallback", and flipping this one table entry is the
    # whole rollback lever, no code path changes.
    "open_request_claimed": _EventPolicy(
        posts=True, pings="requester", edits=True, dm="always"
    ),
    # The gem ask IS its standing post and pings the one holder being asked;
    # the DM is a silent fallback fired only when the channel post fails
    # (removing the old delete-on-DM-failure fragility: the DM stops being the
    # single point of delivery).
    "gem_ask_posted": _EventPolicy(
        posts=True, pings="holder", edits=False, dm="fallback"
    ),
    # The answer edits the ask's post to its terminal form silently and DMs
    # the asker the yes/no, exactly as informative as before. The plan table
    # sketched a pinging reply here, but the owner's later decision governs:
    # the ping budget is proposal + acceptance ONLY, and a gem answer is
    # neither - so no new pinging post for this event.
    "gem_ask_answered": _EventPolicy(
        posts=False, pings=None, edits=True, dm="always"
    ),
    "declined": _EventPolicy(posts=False, pings=None, edits=True, dm="never"),
    "cancelled": _EventPolicy(posts=False, pings=None, edits=True, dm="never"),
    "ready": _EventPolicy(posts=False, pings=None, edits=True, dm="never"),
    "card_arrived": _EventPolicy(
        posts=False, pings=None, edits=True, dm="never"
    ),
    "completed": _EventPolicy(posts=False, pings=None, edits=True, dm="never"),
    "expired": _EventPolicy(posts=False, pings=None, edits=True, dm="never"),
    # A public nag is worse than a DM: review keeps its private delivery.
    # (Check-in and auto-deduct notices are DM-only paths that live in
    # extensions/tasks/cards_deadlines.py and never route through here.)
    "needs_review": _EventPolicy(
        posts=False, pings=None, edits=True, dm="always"
    ),
}


@dataclasses.dataclass(frozen=True)
class _Delivery:
    """What actually happened, so feedback strings never have to guess."""

    channel_message_id: int | None = None
    pinged: tuple = ()
    dm_sent: tuple = ()
    dm_failed: tuple = ()


async def _default_dm_components(
    mongo, trade: dict, *, event: str
) -> dict[int, list]:
    """The DM each event sends when the caller supplies nothing bespoke."""
    if event == "proposal_created":
        attachment = await asyncio.to_thread(_trade_strip_attachment, trade)
        return {int(trade["holder_discord_id"]): _trade_proposal_dm(
            trade, attachment=attachment, controls=True
        )}
    if event in ("proposal_accepted", "open_request_claimed"):
        # One builder for both: a claimed want-ad IS an acceptance, and both
        # events aim the news at the trade's requester (for a claim, the
        # member who posted the want-ad). The claim path suppresses this DM
        # when the reservation stayed pending - "Trade accepted" would be
        # ahead of the truth there - by passing an empty recipients dict.
        fwa_relevant = await _trade_involves_fwa(mongo, trade)
        return {int(trade["requester_discord_id"]): _accepted_trade_dm(
            trade, fwa_relevant=fwa_relevant
        )}
    if event == "gem_ask_posted":
        # The fallback payload is the existing DM, unchanged: the channel
        # post is the primary surface, and this is what the holder gets only
        # when that post failed.
        return {int(trade["holder_discord_id"]): _gem_ask_dm(trade)}
    if event == "gem_ask_answered":
        if not trade.get("asker_discord_id"):
            return {}
        return {int(trade["asker_discord_id"]): _gem_answer_dm(trade)}
    return {}


async def _deliver(
    bot: hikari.GatewayBot,
    mongo,
    trade: dict,
    *,
    event: str,
    dm_components_by_recipient: dict[int, list] | None = None,
) -> _Delivery:
    """The one funnel between a trade event and anyone's attention.

    Consults TRADE_DELIVERY and performs, in order: the new channel post
    (the only step that can ping), the silent standing-post edit, then any
    DMs the policy asks for. Never raises for delivery reasons - every
    transport underneath already fails soft - so a caller may await it
    directly (sweepers do) or through `_deliver_soon` (interactive handlers).
    """
    policy = TRADE_DELIVERY[event]
    message_id = None
    pinged: tuple = ()
    ping_id = None
    if policy.pings:
        try:
            ping_id = int(trade.get(f"{policy.pings}_discord_id") or 0) or None
        except (TypeError, ValueError):
            ping_id = None
    if policy.posts:
        if event == "proposal_created":
            # The proposal IS the standing post; everything later refers back
            # to it.
            if await _post_trade_channel(bot, mongo, trade):
                message_id = trade.get("channel_message_id")
        elif event == "open_request_posted":
            # The want-ad is its own standing post, and its policy row pings
            # nobody - the ping_id above is already None.
            if await _post_open_request_channel(bot, mongo, trade):
                message_id = trade.get("channel_message_id")
        elif event == "gem_ask_posted":
            # The gem ask is its own standing post, pinging the one holder
            # being asked (the transport's allowlist carries the same id the
            # policy resolved above).
            if await _post_gem_ask_channel(bot, mongo, trade):
                message_id = trade.get("channel_message_id")
        elif event == "open_request_claimed":
            # The claim reply-note, threaded under the want-ad's message -
            # which the edits step below refreshes into the trade's own
            # standing post. `trade` is the converted kind:"trade" doc, so
            # the requester ping lands on the want-ad's poster.
            message_id = await _channel_post(
                bot,
                components=_claimed_channel_note(trade),
                ping=[ping_id] if ping_id is not None else [],
                reply_to=trade.get("channel_message_id"),
                key=f"{trade.get('_id')} {event}",
            )
        else:
            # A short follow-up, threaded under the standing post when one
            # exists so the channel reads as one conversation per trade.
            message_id = await _channel_post(
                bot,
                components=_accepted_channel_note(trade),
                ping=[ping_id] if ping_id is not None else [],
                reply_to=trade.get("channel_message_id"),
                key=f"{trade.get('_id')} {event}",
            )
        if message_id is not None and ping_id is not None:
            pinged = (ping_id,)
    if policy.edits:
        await _update_trade_channel(bot, trade)
    dm_sent: list[int] = []
    dm_failed: list[int] = []
    dm_wanted = policy.dm == "always" or (
        policy.dm == "fallback" and policy.posts and message_id is None
    )
    if policy.dm != "never" and dm_wanted:
        recipients = dm_components_by_recipient
        if recipients is None:
            recipients = await _default_dm_components(
                mongo, trade, event=event
            )
        for recipient_id, components in (recipients or {}).items():
            ok = await _send_trade_dm(
                bot, int(recipient_id), components,
                trade_id=str(trade.get("_id")),
            )
            (dm_sent if ok else dm_failed).append(int(recipient_id))
    return _Delivery(
        channel_message_id=(
            int(message_id) if message_id is not None else None
        ),
        pinged=pinged,
        dm_sent=tuple(dm_sent),
        dm_failed=tuple(dm_failed),
    )


# Keeps in-flight delivery tasks reachable: asyncio holds tasks weakly, so a
# fire-and-forget task with no other reference can be garbage-collected
# mid-delivery. done_callback removes each one the moment it finishes.
_DELIVERY_TASKS: set = set()


async def _deliver_soon(
    bot: hikari.GatewayBot,
    mongo,
    trade: dict,
    *,
    event: str,
    dm_components_by_recipient: dict[int, list] | None = None,
    on_complete=None,
    timeout: float = 3.0,
) -> _Delivery | None:
    """`_deliver` with a patience limit, for interactive handlers only.

    main.py sets max_rate_limit=120.0, so hikari can silently sleep minutes
    inside a rate-limited REST call. Awaiting delivery inline would turn that
    into a user-visible hang inside an interaction, so the handler waits up
    to 3 seconds and then answers anyway; `asyncio.wait` does not cancel, so
    a slow post still lands afterwards. Returns the _Delivery when it
    finished in time, else None ("still posting"). Background and sweeper
    callers await `_deliver` directly instead.

    `on_complete` is an async callback awaited with the finished _Delivery
    INSIDE the background task - so it runs even when the caller's 3-second
    patience ran out first. It exists for cleanup that must track the real
    outcome, not the caller's view of it: the gem ask's no-orphan deletion
    was silently skipped whenever the delivery outlived the window.
    """
    async def _run() -> _Delivery:
        delivery = await _deliver(
            bot, mongo, trade, event=event,
            dm_components_by_recipient=dm_components_by_recipient,
        )
        if on_complete is not None:
            try:
                await on_complete(delivery)
            except Exception:
                _log.exception(
                    "delivery on_complete failed doc=%s event=%s",
                    trade.get("_id"), event,
                )
        return delivery

    task = asyncio.create_task(_run())
    _DELIVERY_TASKS.add(task)
    task.add_done_callback(_DELIVERY_TASKS.discard)
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task not in done:
        return None
    try:
        return task.result()
    except Exception:
        _log.exception(
            "card delivery failed trade=%s event=%s", trade.get("_id"), event
        )
        return None


def _delivery_note(delivery: _Delivery | None, *, recipient_id) -> str:
    """One sentence about how the other player heard, built from what
    actually happened - never a guess."""
    try:
        rid = int(recipient_id)
    except (TypeError, ValueError):
        return ""
    if delivery is None:
        # Still in flight (the `_deliver_soon` timeout). Not a failure.
        return "I am telling them now."
    if rid in delivery.pinged:
        channel_id = _configured_cards_channel_id()
        note = (
            f"I pinged them in <#{channel_id}>."
            if channel_id
            else "I pinged them on the trade board."
        )
        if rid in delivery.dm_sent:
            note += " They also got a DM."
        return note
    if rid in delivery.dm_sent:
        return "I sent them a DM."
    return f"I could not reach <@{rid}>; please ping them."


def _trade_proposal_dm(
    trade: dict,
    *,
    attachment=None,
    controls: bool = False,
    preview: bool = False,
) -> list[Container]:
    """The proposal DM.

    `controls` adds accept/decline in the DM itself, handled by
    `cards_dm_accept` / `cards_dm_decline`. The preview command passes
    `preview=True` to render them disabled for reading.
    """
    wanted = CARD_BY_ID[trade["wanted_card_id"]]
    given = CARD_BY_ID[trade["given_card_id"]]
    # Everything of theirs this holder could take, the proposed card first.
    # Naming one card and then mentioning the others as an aside read as a
    # contradiction: it stated what you receive, then said to pick.
    choices = [given] + [
        CARD_BY_ID[card_id]
        for card_id in (trade.get("compatible_card_ids") or ())
        if card_id in CARD_BY_ID and card_id != given.id
    ]
    if len(choices) > 1:
        receive = "**You receive one of:**\n" + "\n".join(
            f"- {_card_label(card)}" for card in choices[:8]
        )
        if len(choices) > 8:
            receive += f"\n-# and {len(choices) - 8} more"
        chooser = " You pick which one when you accept."
    else:
        receive = f"**You receive:** {_card_label(given)}"
        chooser = ""
    same_clan = _normalize_tag(
        trade.get("requester_clan_tag")
    ) == _normalize_tag(trade.get("holder_clan_tag"))
    return _trade_dm_container(
        f"{emojis.inbox} New card proposal",
        (
            f"**You give:** {_card_label(wanted)}\n"
            f"{receive}"
        ),
        extra=[Text(content=(
            _player_line(
                "You", trade.get("holder_name"), trade.get("holder_tag"),
                trade.get("holder_town_hall"), trade.get("holder_clan_name"),
                trade.get("holder_clan_emoji"),
            )
            + "\n"
            + _player_line(
                "Them", trade.get("requester_name"),
                trade.get("requester_tag"), trade.get("requester_town_hall"),
                trade.get("requester_clan_name"),
                trade.get("requester_clan_emoji"),
            )
            + (
                ""
                if same_clan
                else "\n-# You are in different clans. One of you must move "
                "before trading."
            )
            + (
                # This proposal is card for card, so it does not mention gems.
                # The real gem path is the separate Ask for help flow, which
                # states payer and price before anything is sent.
                "\n-# Same-category trade: "
                f"{CATEGORY_BY_ID[wanted.category].short_name} for "
                f"{CATEGORY_BY_ID[wanted.category].short_name}."
            )
        ))],
        # A proposal is a question waiting on the reader, not a success.
        accent=GOLD_ACCENT,
        attachment=attachment,
        controls=(
            _trade_proposal_controls(trade, choices, preview=preview)
            if controls
            else None
        ),
        footer=(
            "Nothing is reserved until you accept."
            if controls
            else "Open /cards and tap **My trades** to accept or decline."
            f"{chooser} Nothing is reserved until you accept."
        ),
    )


async def _notify_trade_holder(bot: hikari.GatewayBot, trade: dict) -> bool:
    attachment = await asyncio.to_thread(_trade_strip_attachment, trade)
    return await _send_trade_dm(
        bot,
        int(trade["holder_discord_id"]),
        # Handlers exist now, so the DM carries its own accept/decline.
        _trade_proposal_dm(trade, attachment=attachment, controls=True),
        trade_id=str(trade["_id"]),
    )


FWA_WARNING_TEXT = (
    "⚠️ **FWA — Wait for war**\n"
    "Do not trade until war starts."
)

# The settled INLINE CALLOUT pattern (owner-chosen from the live markup
# comparison): a blockquote-wrapped small heading plus one short line.
# Discord draws the blockquote's vertical bar and the heading's weight, so
# the warning stands out inside an existing Container without a second box.
# Use this shape when information belongs inside a Container, a separate
# colored Container would be too heavy, and Markdown emphasis is enough.
FWA_WARNING_MARKUP = (
    "> ### ⚠️ FWA — Wait for war\n"
    "> Do not trade until war starts."
)


def _compact_callout(accent: object, text: str) -> Container:
    """The smallest colored structure a Discord message can carry.

    Verified 2026-08-14 against the Discord component reference and the
    pinned hikari builders: the accent bar exists only on a Container, and
    no smaller callout/alert component exists in messages - the callout
    boxes in Discord's own documentation are site styling, not message
    components. A compact callout is therefore exactly this: one accent,
    one Text Display, one or two short lines. No heading component, no
    separator, no footer, no buttons, no image.

    The reusable semantic palette: red warning, gold action required,
    blue information, green success. Emoji plus bold words must carry the
    meaning without the color. Reach for this only when a true colored
    accent is genuinely appropriate as its own message region; inside an
    existing Container, prefer the inline-callout Markdown pattern
    (`FWA_WARNING_MARKUP` is the reference example).
    """
    return Container(accent_color=accent, components=[Text(content=text)])


def _fwa_warning() -> Text:
    """The FWA warning as the settled inline callout for a Container."""
    return Text(content=FWA_WARNING_MARKUP)


def _noahs_ark_line() -> str:
    """Optional quick-trade help as one quiet line, never its own card."""
    return (
        f"-# ℹ️ Need a place to trade? [**Open Noahs Ark**]({NOAHS_ARK_LINK})"
        f" · `{NOAHS_ARK_TAG}`"
    )


def _accepted_trade_dm(
    trade: dict, *, fwa_relevant: bool = False
) -> list:
    """The requester's accepted-trade handoff.

    Self-contained on purpose: both accounts and tags, both cards, the
    partner's Discord identity, their clan with a link, and the next action.
    Users kept forgetting who they accepted with and had nothing to search
    for, so the message must stand alone days later.

    Final settled shape (owner-verified on live phone previews): one main
    Container holding short Text blocks with separators at the real section
    boundaries - cards, partner, next step - and the FWA warning, when
    relevant, as the inline blockquote-heading callout inside that same
    Container. Fully unboxed root text was rejected as looking unfinished;
    a separate FWA card was rejected as heavy; the inline markup treatment
    won the live comparison. Noahs Ark and the reader's own account stay
    quiet subtext.
    """
    wanted = _card_label(CARD_BY_ID[trade["wanted_card_id"]])
    given = _card_label(CARD_BY_ID[trade["given_card_id"]])
    status = str(trade.get("status") or "move_needed")
    move_needed = status == "move_needed"

    partner_lines = (
        f"**Trading with:** <@{int(trade['holder_discord_id'])}> · "
        f"{_escape_markdown(trade['holder_name'], limit=60)} · "
        f"`{trade['holder_tag']}`"
    )
    holder_clan_name = str(trade.get("holder_clan_name") or "").strip()
    holder_clan_link = _clan_link(trade.get("holder_clan_tag"))
    if holder_clan_name or holder_clan_link:
        clan_label = (
            _escape_markdown(holder_clan_name, limit=50)
            if holder_clan_name
            else "their clan"
        )
        partner_lines += (
            "\n**Their clan:** " + clan_label
            + (
                f" · [Open their clan]({holder_clan_link})"
                if holder_clan_link
                else ""
            )
        )

    # One action per line. The reader knows their own clan, and the partner
    # block above names the other one, so nothing is repeated here.
    if move_needed:
        next_lines = (
            "**Next**\n"
            "One of you moves to the other clan.\n"
            "Send the cards in game.\n"
            "Then tap **I sent my card** in /cards."
        )
    else:
        next_lines = (
            "**Next**\n"
            "Send the cards in game.\n"
            "Then tap **I sent my card** in /cards."
        )

    involved_clans = {
        _normalize_tag(trade.get("requester_clan_tag")),
        _normalize_tag(trade.get("holder_clan_tag")),
    }
    quiet_lines = []
    if move_needed and NOAHS_ARK_TAG not in involved_clans:
        quiet_lines.append(_noahs_ark_line())
    quiet_lines.append("-# Your card is reserved until you confirm.")
    quiet_lines.append(
        "-# Your account: "
        f"{_escape_markdown(trade['requester_name'], limit=60)} · "
        f"`{trade['requester_tag']}`"
    )

    body: list = [
        Text(content=f"## {emojis.yes} Trade accepted"),
        Text(content=(
            f"**You give:** {given}\n"
            f"**You receive:** {wanted}"
        )),
        Separator(divider=True),
        Text(content=partner_lines),
        Separator(divider=True),
        Text(content=next_lines),
    ]
    if fwa_relevant:
        body.extend([Separator(divider=True), _fwa_warning()])
    body.extend([
        Separator(divider=False),
        Text(content="\n".join(quiet_lines)),
    ])
    return [Container(accent_color=GREEN_ACCENT, components=body)]


# Sentinel: distinguishes "no _Delivery was computed" (the preview command
# still passes the legacy dm_sent flag) from a real timed-out delivery (None).
_NO_DELIVERY_INFO = object()


def _holder_accept_feedback(
    trade: dict,
    *,
    taken_card_id: str,
    status: str,
    dm_sent: bool = False,
    delivery: object = _NO_DELIVERY_INFO,
    fwa_relevant: bool,
    tag: str,
) -> list:
    """The holder's half of the handoff, in the same rhythm as the DM.

    No "Your account" line: this panel replaces the screen the holder just
    acted from, so context already binds the account. Same settled shape as
    the requester DM: one main Container of short blocks, with the FWA
    warning as the inline blockquote-heading callout when relevant.

    `delivery` (a `_Delivery`, or None while one is still in flight) drives
    the how-they-heard line; `dm_sent` remains for callers that predate the
    delivery funnel (the preview command).
    """
    gives = _card_label(CARD_BY_ID[trade["wanted_card_id"]])
    receives = _card_label(CARD_BY_ID[str(taken_card_id)])
    partner_lines = (
        f"**Trading with:** <@{int(trade['requester_discord_id'])}> · "
        f"{_escape_markdown(trade.get('requester_name'), limit=60)} · "
        f"`{trade['requester_tag']}`"
    )
    requester_clan = str(trade.get("requester_clan_name") or "").strip()
    if requester_clan:
        partner_lines += (
            f"\n**Their clan:** {_escape_markdown(requester_clan, limit=50)}"
        )
    if status == "move_needed":
        next_lines = (
            "**Next**\n"
            "One of you moves to the other clan.\n"
            "Send your card in game.\n"
            "Then tap **I sent my card** in **My trades**."
        )
    else:
        next_lines = (
            "**Next**\n"
            "Send your card in game.\n"
            "Then tap **I sent my card** in **My trades**."
        )
    if delivery is _NO_DELIVERY_INFO:
        heard = (
            "I sent them a DM."
            if dm_sent
            else f"I could not reach <@{int(trade['requester_discord_id'])}>. "
            "Please ping them."
        )
    else:
        heard = _delivery_note(
            delivery, recipient_id=trade["requester_discord_id"]
        )
    normalized = _normalize_tag(tag)
    body: list = [
        Text(content=f"# {emojis.yes} Trade accepted"),
        Text(content=(
            f"**You give:** {gives}\n"
            f"**You receive:** {receives}"
        )),
        Separator(divider=True),
        Text(content=partner_lines),
        Separator(divider=True),
        Text(content=next_lines),
    ]
    if fwa_relevant:
        body.extend([Separator(divider=True), _fwa_warning()])
    body.extend([
        Separator(divider=False),
        Text(content=(
            f"-# The exact cards are reserved. {heard}"
        )),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"cards_trades:{normalized}",
                label="My trades",
                emoji=TRADES_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{normalized}",
                label="Collection",
                emoji=RETURN_EMOJI,
            ),
        ]),
    ])
    return [Container(accent_color=GREEN_ACCENT, components=body)]


async def _trade_involves_fwa(mongo, trade: dict) -> bool:
    """Whether either side's clan is an FWA clan. Best-effort: never raises.

    Membership comes from the clans collection's type field, the same source
    every FWA command uses. Live war state is deliberately not consulted -
    it can fail (private log, maintenance) and would be stale by the time the
    cards move - so the DM carries the simple timing reminder instead.
    """
    if mongo is None:
        return False
    tags = [
        tag
        for tag in (
            _normalize_tag(trade.get("requester_clan_tag")),
            _normalize_tag(trade.get("holder_clan_tag")),
        )
        if tag
    ]
    if not tags:
        return False
    try:
        row = await mongo.clans.find_one(
            {"tag": {"$in": tags}, "type": "FWA"}, {"_id": 1}
        )
    except Exception:
        _log.exception("fwa lookup failed trade=%s", trade.get("_id"))
        return False
    return row is not None


async def _notify_trade_accepted(
    bot: hikari.GatewayBot, trade: dict, *, mongo=None
) -> bool:
    fwa_relevant = await _trade_involves_fwa(mongo, trade)
    return await _send_trade_dm(
        bot,
        int(trade["requester_discord_id"]),
        _accepted_trade_dm(trade, fwa_relevant=fwa_relevant),
        trade_id=str(trade["_id"]),
    )


def _reader_account_line(trade: dict, recipient_id: int) -> str:
    """`-# Account: …` for whichever side the recipient is, or "".

    A status DM used to name both players' accounts. The reader only ever
    needs their own - the detail already names the partner where it matters -
    so the pair of lines collapses to one quiet line.
    """
    try:
        rid = int(recipient_id)
    except (TypeError, ValueError):
        return ""
    for role in ("requester", "holder"):
        try:
            if int(trade.get(f"{role}_discord_id") or 0) != rid:
                continue
        except (TypeError, ValueError):
            continue
        name = _escape_markdown(trade.get(f"{role}_name"), limit=60)
        tag = _normalize_tag(trade.get(f"{role}_tag"))
        return f"-# Account: {name} · `{tag}`"
    return ""


def _status_dm(
    trade: dict,
    *,
    recipient_id: int,
    title: str,
    detail: str,
    accent: object = None,
) -> list:
    """One slim status DM: title, the swap, what happened, whose account.

    Terminal notices deliberately carry no accent, no separators and no
    navigation footer. Green marks a card arriving, gold an automatic change
    the reader may want to correct, red a swap that needs review.
    """
    wanted = CARD_BY_ID.get(str(trade.get("wanted_card_id")))
    given = CARD_BY_ID.get(str(trade.get("given_card_id")))
    swap = (
        f"{_card_label(given)} for {_card_label(wanted)}"
        if wanted is not None and given is not None
        else "the card swap"
    )
    components: list = [
        Text(content=f"## {title}"),
        Text(content=f"{swap}\n{detail}"),
    ]
    account_line = _reader_account_line(trade, recipient_id)
    if account_line:
        components.append(Text(content=account_line))
    return [_panel(accent, components)]


async def _notify_trade_status(
    bot: hikari.GatewayBot,
    trade: dict,
    *,
    recipient_id: int,
    title: str,
    detail: str,
    accent: object = None,
) -> bool:
    """Send one `_status_dm`. Kept exactly this shape: the deadline sweeper
    (extensions/tasks/cards_deadlines.py) calls it directly for its DM-only
    notices, which never route through the `_deliver` policy table."""
    return await _send_trade_dm(
        bot,
        int(recipient_id),
        _status_dm(
            trade, recipient_id=recipient_id, title=title, detail=detail,
            accent=accent,
        ),
        trade_id=str(trade["_id"]),
    )


def _dm_fallback_note(sent: bool, recipient_id: int) -> str:
    # Transport-neutral on purpose (the name stays for its many call sites):
    # depending on the event, "reach" may have meant a channel ping or a DM.
    return (
        ""
        if sent
        else f" I could not reach <@{int(recipient_id)}>; please ping them directly."
    )


def _notify_review_participants(
    trade: dict,
    detail: str,
) -> dict[int, list]:
    """The needs_review DM set: both participants, the same red notice.

    This used to send directly; it is now the dm-components builder for
    `_deliver(event="needs_review", dm_components_by_recipient=...)`, so the
    review DMs go through the same policy funnel as everything else.
    """
    recipients: dict[int, list] = {}
    for value in (
        trade.get("requester_discord_id"),
        trade.get("holder_discord_id"),
    ):
        try:
            recipient = int(value)
        except (TypeError, ValueError):
            continue
        recipients[recipient] = _status_dm(
            trade,
            recipient_id=recipient,
            title="Card swap needs review",
            detail=detail,
            accent=RED_ACCENT,
        )
    return recipients


async def _active_trades(
    mongo: MongoClient,
    *,
    tag: str,
    guild_id: int,
    bot: hikari.GatewayBot | None = None,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    normalized_tag = _normalize_tag(tag)
    participant = {
        "$or": [
            {"requester_tag": normalized_tag},
            {"holder_tag": normalized_tag},
        ],
    }
    unfinished_participant = {
        "$or": [
            {
                "requester_tag": normalized_tag,
                "requester_confirmed_at": {"$exists": False},
            },
            {
                "holder_tag": normalized_tag,
                "holder_confirmed_at": {"$exists": False},
            },
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
                await _deliver(
                    bot, mongo, trade, event="needs_review",
                    dm_components_by_recipient=_notify_review_participants(
                        trade,
                        "Completion expired before it could be confirmed. Recheck "
                        "and correct both affected categories.",
                    ),
                )

    committed = await mongo.card_trades.find({
        "kind": "trade",
        "guild_id": int(guild_id),
        "$and": [
            participant,
            {"$or": [
                {"status": "reserving"},
                {"$and": [
                    {"status": {"$in": list(SWAP_LIVE_STATUSES)}},
                    # A role confirmation is recorded only after that card's
                    # debit and receiver credit are acknowledged. The other
                    # account still sees the same live trade and can finish
                    # its own leg.
                    unfinished_participant,
                ]},
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


def _card_label(card) -> str:
    """A card's name with its troop art, matching every other card list."""
    icon = troop_emoji.markup(card.id)
    return f"{icon} **{card.name}**" if icon else f"**{card.name}**"


def _th_markup(level: object) -> str:
    """`<:TH18:...>` for a town hall level, or "" when there is no such emoji.

    Never raises. A missing or unconfigured level simply contributes nothing,
    because a DM that fails to send is worse than one without a picture.
    """
    try:
        entry = getattr(emojis, f"TH{int(level)}", None)
    except (TypeError, ValueError):
        return ""
    return str(entry) if entry is not None else ""


CLAN_FALLBACK_EMOJI = "🛡️"


def _clan_emoji_markup(value: object) -> str:
    """The clan's own emoji, or a plain shield.

    `clans.emoji` holds `<:name:id>` markup set by hand through the clan
    dashboard, so it can contain anything. Validated the way
    `utils.classes.Clan` validates it - by parsing rather than pattern
    matching - so this agrees with the rest of the bot about what is usable.

    Not the `logo`: that is a full-size Cloudinary image meant for a thumbnail,
    which is far too big to sit inside a line of text.
    """
    raw = str(value or "").strip()
    if not raw or raw.count(":") < 2:
        return CLAN_FALLBACK_EMOJI
    try:
        EmojiType(raw).partial_emoji
    except (IndexError, ValueError, TypeError, AttributeError):
        return CLAN_FALLBACK_EMOJI
    return raw


def _player_line(
    label: str, name: object, tag: object, town_hall: object,
    clan_name: object, clan_emoji: object = None,
) -> str:
    """One account on one line: who, where, and how big."""
    th = _th_markup(town_hall)
    head = f"**{label}:** {th + ' ' if th else ''}"
    head += f"{_escape_markdown(name, limit=40)} • `{_normalize_tag(tag)}`"
    clan = str(clan_name or "").strip()
    if clan:
        head += (
            f" • {_clan_emoji_markup(clan_emoji)} "
            f"{_escape_markdown(clan, limit=40)}"
        )
    return head


def _clan_label(name: object, tag: object) -> str:
    """`Name • #TAG`. A bare tag tells a member nothing about where that is."""
    clan_tag = _normalize_tag(tag)
    raw_name = str(name or "").strip()
    # `_escape_markdown` substitutes "Unknown" for an empty value, which would
    # render a nameless clan as "Unknown • #TAG". The tag alone is honest.
    if raw_name and clan_tag:
        return f"{_escape_markdown(raw_name, limit=50)} • `{clan_tag}`"
    return f"`{clan_tag}`" if clan_tag else "no clan"


def _trade_summary(trade: dict, *, role: str) -> str:
    wanted = CARD_BY_ID.get(str(trade.get("wanted_card_id")))
    given = CARD_BY_ID.get(str(trade.get("given_card_id")))
    if wanted is None or given is None:
        return "This request contains an unknown card and cannot be completed."
    if role == "requester":
        counterpart = trade.get("holder_name") or "Unknown player"
        counterpart_tag = trade.get("holder_tag") or "?"
        receive, offer = _card_label(wanted), _card_label(given)
    else:
        counterpart = trade.get("requester_name") or "Unknown player"
        counterpart_tag = trade.get("requester_tag") or "?"
        receive, offer = _card_label(given), _card_label(wanted)
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
    own_confirmed = bool(trade.get(f"{role}_confirmed_at"))
    other_role = "holder" if role == "requester" else "requester"
    other_confirmed = bool(trade.get(f"{other_role}_confirmed_at"))
    detail = ""
    if raw_status == "pending":
        detail = (
            f"\n-# Proposed {_relative_timestamp(trade.get('created_at'))}. "
            "Nothing is reserved until accepted."
        )
    elif raw_status == "move_needed":
        detail = (
            "\n-# Different family clans: "
            + _clan_label(
                trade.get("requester_clan_name"), trade.get("requester_clan_tag")
            )
            + " and "
            + _clan_label(
                trade.get("holder_clan_name"), trade.get("holder_clan_tag")
            )
            + (
                "."
                if own_confirmed
                else ". Exact cards are reserved."
            )
        )
    elif raw_status in {"ready", "accepted"}:
        if not own_confirmed:
            detail = (
                "\n-# Same family clan. Send your card in game, then tap "
                "**I sent my card**."
            )
    elif raw_status == "completing":
        detail = "\n-# Saving the tracked collection updates now."
    elif needs_review:
        detail = (
            f"\n-# Review visible until {_relative_timestamp(trade.get('review_expires_at'))}. "
            "Recheck both affected categories manually."
        )
    if raw_status in SWAP_LIVE_STATUSES and own_confirmed:
        detail += (
            "\n-# Both card sends are recorded. Refresh while the trade closes."
            if other_confirmed
            else (
                "\n-# You already marked your card sent. Waiting for "
                f"**{_escape_markdown(counterpart, limit=50)}** to confirm theirs."
            )
        )
    return (
        f"**{status} with {_escape_markdown(counterpart, limit=50)}** "
        f"· `{_normalize_tag(counterpart_tag)}`\n"
        f"**You give:** {offer}\n"
        f"**You receive:** {receive}\n"
        + detail
    )


def _open_request_summary(request: dict) -> str:
    """One compact My-trades row for the member's own want-ad."""
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    label = _card_label(card) if card else "**Unknown card**"
    return (
        f"**Open request on the family board**\n"
        f"**You asked for:** {label}\n"
        f"-# Posted {_relative_timestamp(request.get('created_at'))} · closes "
        f"{_relative_timestamp(request.get('expires_at'))}. Anyone with a "
        "spare can answer it from the channel post."
    )


def _trades_view(
    account,
    trades: list[dict],
    *,
    page: int = 0,
    open_requests: list[dict] | None = None,
) -> list[Container]:
    tag = _normalize_tag(account.tag)
    # Open requests ride in the same paged list as trades rather than in a
    # block of their own: a request row costs fewer components than a trade
    # row, so the page's worst case cannot grow past what the 5-trade page
    # already proved fits. They cap at MAX_OPEN_REQUESTS_PER_ACCOUNT anyway.
    requests = list(open_requests or ())[:MAX_OPEN_REQUESTS_PER_ACCOUNT]
    items: list[tuple[str, dict]] = [
        *(("request", request) for request in requests),
        *(("trade", trade) for trade in trades),
    ]
    pages = max(1, math.ceil(len(items) / TRADE_VIEW_LIMIT))
    page = min(max(0, page), pages - 1)
    start = page * TRADE_VIEW_LIMIT
    body: list = [
        Text(content=f"# {emojis.inbox} My Card Trades"),
        Text(content=f"**{_escape_markdown(account.name)}** · `{tag}`"),
        Separator(divider=True),
    ]
    shown = items[start:start + TRADE_VIEW_LIMIT]
    if not shown:
        body.append(Text(content="No open trades for this account."))
    for kind, trade in shown:
        if kind == "request":
            body.append(Text(content=_open_request_summary(trade)))
            body.append(ActionRow(components=[Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_req_close:{trade.get('_id')}",
                label="Close request",
                emoji=CANCEL_EMOJI,
            )]))
            body.append(Separator(divider=False))
            continue
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
                    emoji=CANCEL_EMOJI,
                ),
            ])
        elif status == "pending":
            buttons.append(Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_trade_cancel:{trade['_id']}",
                label="Cancel request",
                emoji=CANCEL_EMOJI,
            ))
        elif status in SWAP_LIVE_STATUSES:
            # One button, whatever the clans say. The clan check used to be the
            # ONLY control here while a swap was move_needed, so a member who
            # had already sent their card in game could not record it until a
            # scan agreed with them. Nothing about being in the same clan is
            # something the bot can verify at the moment the cards actually
            # move, so it no longer stands in the way.
            if _awaiting_confirmation(trade, role=role):
                buttons.append(Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"cards_swap_sent:{trade['_id']}|{role}",
                    label="I sent my card",
                    emoji=emojis.yes.partial_emoji,
                ))
            buttons.append(Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=f"cards_trade_cancel:{trade['_id']}",
                label="Cancel",
                emoji=CANCEL_EMOJI,
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
                emoji=PREVIOUS_EMOJI,
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
                emoji=NEXT_EMOJI,
                is_disabled=page >= pages - 1,
            ),
        ]))
    bottom_row: list = []
    if not trades:
        # An empty list's next step is starting a trade, so the route is a
        # button here rather than a sentence pointing somewhere else.
        bottom_row.append(Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"cards_matches:{tag}",
            label="Find trades",
            emoji=SEARCH_EMOJI,
        ))
    bottom_row.extend([
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{tag}",
            label="Collection",
            emoji=RETURN_EMOJI,
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_trades:{tag}",
            label="Refresh",
            emoji=REFRESH_EMOJI,
        ),
    ])
    body.append(ActionRow(components=bottom_row))
    # A routine list, not a warning: no accent.
    return [_panel(None, body)]


SWAP_ACCEPT_FOR = timedelta(hours=12)
# Seven days, not one. A player who has agreed a swap may not open the game
# for days, and taking their card away after 24 hours punishes that.
SWAP_CONFIRM_FOR = timedelta(days=7)
# Nothing starts the 24 hour clock until somebody confirms, so a trade both
# players abandon would hold their cards for ever. This is the only thing that
# can end that state.
SWAP_BACKSTOP_FOR = timedelta(days=7)

SWAP_LIVE_STATUSES = ("move_needed", "ready", "accepted")


class _SwapReceiverCreditError(RuntimeError):
    """The giver debit succeeded but the receiver credit is not trustworthy."""


class _SwapLegNeedsReview(RuntimeError):
    """A claimed one-sided transfer stopped in a durable review state."""

    def __init__(self, trade: dict):
        super().__init__("card swap leg needs review")
        self.trade = trade


def _swap_leg(trade: dict, *, role: str) -> tuple[str, str, str]:
    """(giver tag, receiver tag, card id) for one side of an agreed swap."""
    if role == "requester":
        return (
            _normalize_tag(trade["requester_tag"]),
            _normalize_tag(trade["holder_tag"]),
            str(trade["given_card_id"]),
        )
    return (
        _normalize_tag(trade["holder_tag"]),
        _normalize_tag(trade["requester_tag"]),
        str(trade["wanted_card_id"]),
    )


def _awaiting_confirmation(trade: dict, *, role: str) -> bool:
    """Whether this side still has to say what they did."""
    return (
        str(trade.get("status")) in SWAP_LIVE_STATUSES
        and not trade.get(f"{role}_confirmed_at")
    )


def _trade_role_for(trade: dict, tag: str) -> str | None:
    tag = _normalize_tag(tag)
    if _normalize_tag(trade.get("requester_tag")) == tag:
        return "requester"
    if _normalize_tag(trade.get("holder_tag")) == tag:
        return "holder"
    return None


async def _confirm_swap_leg(
    mongo: MongoClient, trade: dict, *, role: str, now: datetime
) -> tuple[bool, int]:
    """Move one card, because one player says they sent it.

    Deliberately one-sided: it never waits for the other player to agree.
    Waiting was the whole problem - a card sat reserved indefinitely because
    somebody went quiet - so each side's answer only ever moves the card that
    side promised, and the other card moves when they answer for themselves.

    Returns (did anything move, copies the giver has left).
    """
    giver, receiver, card_id = _swap_leg(trade, role=role)
    guild_id = int(trade["guild_id"])
    owner = _reservation_owner(trade)
    fence = [
        {f"card_trade_reservations.{card_id}": owner},
        {f"card_trade_reservations.{card_id}.owner": owner},
    ]

    given = await mongo.card_inventories.update_one(
        {
            "_id": giver,
            "guild_id": guild_id,
            "$or": fence,
            f"cards.{card_id}": {"$gte": DUPLICATE},
        },
        {
            "$set": {"updated_at": now, "update_source": "confirmed_trade"},
            # One copy, not the whole stack.
            "$inc": {f"cards.{card_id}": -1, "inventory_revision": 1},
            "$unset": {f"card_trade_reservations.{card_id}": ""},
        },
    )
    moved = bool(getattr(given, "modified_count", 0))

    if moved:
        try:
            credited = await mongo.card_inventories.update_one(
                {"_id": receiver, "guild_id": guild_id, "$or": fence},
                {
                    "$set": {
                        f"cards.{card_id}": OWNED,
                        "updated_at": now,
                        "update_source": "confirmed_trade",
                    },
                    "$inc": {"inventory_revision": 1},
                    "$unset": {f"card_trade_reservations.{card_id}": ""},
                },
            )
            if not getattr(credited, "modified_count", 0):
                # The giver's copy is already gone, so failing to credit the
                # receiver silently would lose the card. The fence can
                # legitimately be missing here (released by recovery); credit
                # anyway, but only while the receiver is still missing it.
                fallback = await mongo.card_inventories.update_one(
                    {
                        "_id": receiver,
                        "guild_id": guild_id,
                        f"cards.{card_id}": {"$lt": OWNED},
                    },
                    {
                        "$set": {
                            f"cards.{card_id}": OWNED,
                            "updated_at": now,
                            "update_source": "confirmed_trade",
                        },
                        "$inc": {"inventory_revision": 1},
                    },
                )
                if not getattr(fallback, "modified_count", 0):
                    receiver_document = await mongo.card_inventories.find_one({
                        "_id": receiver,
                        "guild_id": guild_id,
                    })
                    receiver_count = (
                        normalize_cards(receiver_document.get("cards")).get(
                            card_id, OWNED
                        )
                        if receiver_document is not None
                        else MISSING
                    )
                    if receiver_count < OWNED:
                        raise RuntimeError("receiver credit was not applied")
                await mongo.card_inventories.update_one(
                    {"_id": receiver},
                    {"$unset": {f"card_trade_reservations.{card_id}": ""}},
                )
        except Exception as exc:
            # The giver debit was acknowledged. A receiver exception may be a
            # before-commit failure or a lost acknowledgement after commit, so
            # never guess. The claimed saga records the receiver as unknown and
            # projects both affected inventories fail closed.
            raise _SwapReceiverCreditError(str(exc)) from exc

    remaining = 0
    document = await mongo.card_inventories.find_one({"_id": giver})
    if document:
        remaining = int(normalize_cards(document.get("cards")).get(card_id, 0))
    return moved, remaining


async def _record_swap_confirmation(
    mongo: MongoClient, trade: dict, *, role: str, now: datetime
) -> dict:
    """Stamp this side as done and close the trade once both sides are."""
    progress = _swap_leg_progress(trade)
    claimed = (
        trade.get("status") == "completing"
        and trade.get("completion_kind") == "swap_leg"
        and progress.get("attempt_nonce")
        and progress.get("role") == role
    )
    if claimed:
        # Reload after the claim. The other participant may have completed
        # their side immediately before this claim won the status CAS.
        latest = await mongo.card_trades.find_one({"_id": trade["_id"]}) or trade
        latest_progress = _swap_leg_progress(latest)
        if latest_progress.get("attempt_nonce") != progress.get("attempt_nonce"):
            if latest.get(f"{role}_confirmed_at"):
                return latest
            raise RuntimeError("swap leg claim changed before confirmation")
        other = "holder" if role == "requester" else "requester"
        finished = bool(latest.get(f"{other}_confirmed_at"))
        previous_status = str(
            latest_progress.get("previous_status") or "ready"
        )
        fields: dict[str, object] = {
            f"{role}_confirmed_at": now,
            "updated_at": now,
            "confirm_deadline_at": now + SWAP_CONFIRM_FOR,
            "status": "completed" if finished else previous_status,
        }
        if finished:
            fields.update({
                "completed_at": now,
                **_cleanup_fields(latest),
            })
        update = {
            "$set": fields,
            "$unset": {
                "open_proposal_key": "",
                "completion_kind": "",
                "completion_started_at": "",
                "expires_at": "",
                "swap_leg_progress": "",
            },
        }
        try:
            result = await mongo.card_trades.update_one(
                {
                    **_swap_leg_claim_query(latest, role=role),
                    f"{role}_confirmed_at": {"$exists": False},
                },
                update,
            )
        except Exception:
            result = None
        current = await mongo.card_trades.find_one({"_id": trade["_id"]})
        if getattr(result, "modified_count", 0) or (
            current and current.get(f"{role}_confirmed_at")
        ):
            updated = current or dict(latest)
            if current is None:
                updated.update(fields)
            if updated.get("status") == "completed":
                await _finish_trade_cleanup(
                    mongo, updated, owner=_reservation_owner(latest)
                )
            return updated

        review = await _mark_swap_leg_needs_review(
            mongo,
            latest,
            role=role,
            now=datetime.now(timezone.utc),
            phase="confirmation_record_unknown",
            failure_type="confirmation_record_failed",
            giver_debited=True,
            receiver_credit="acknowledged",
        )
        raise _SwapLegNeedsReview(review)

    # Compatibility path for old internal callers/tests that predate the
    # write-ahead one-sided claim. Production confirmations use the branch
    # above; keeping this path avoids changing old stored action semantics.
    other = "holder" if role == "requester" else "requester"
    fields: dict = {
        f"{role}_confirmed_at": now,
        "updated_at": now,
        # The other side now has a deadline. Until the first confirmation
        # there was nothing to count from.
        "confirm_deadline_at": now + SWAP_CONFIRM_FOR,
    }
    finished = bool(trade.get(f"{other}_confirmed_at"))
    if finished:
        fields.update({
            "status": "completed",
            "completed_at": now,
            **_cleanup_fields(trade),
        })
    await mongo.card_trades.update_one(
        {
            "_id": trade["_id"],
            f"{role}_confirmed_at": {"$exists": False},
            # A confirm racing a cancel must not stamp a closed trade. The
            # inventory move already happened either way; this only keeps the
            # trade document's final status honest.
            "status": {"$in": list(SWAP_LIVE_STATUSES)},
        },
        {"$set": fields, "$unset": {"open_proposal_key": ""}},
    )
    updated = dict(trade)
    updated.update(fields)
    if finished:
        await _finish_trade_cleanup(mongo, updated, owner=_reservation_owner(trade))
    return updated


# Two requests expiring back to back is what triggers the check-in. Two ever
# would nag somebody who trades happily for a month and misses one at each end,
# so the counter resets the moment they answer anything.
IGNORED_BEFORE_CHECKIN = 2
CHECKIN_ANSWER_FOR = timedelta(hours=24)


def _checkin_dm(tag: str, name: object) -> list[Container]:
    """Ask whether somebody is still trading, before hiding them.

    Nobody is removed for being idle any more, so this is the only path to
    being hidden - and it always asks first.
    """
    return _trade_dm_container(
        f"{emojis.magnifier} Are you still trading cards?",
        (
            f"Two trade requests for **{_escape_markdown(name, limit=40)}** "
            "were not answered.\n"
            "**Yes** — your cards stay visible.\n"
            "**No** — your cards are hidden. Nothing is deleted."
        ),
        accent=GOLD_ACCENT,
        controls=[ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"cards_trading_on:{_normalize_tag(tag)}",
                label="Yes, keep trading",
                emoji=emojis.yes.partial_emoji,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_trading_off:{_normalize_tag(tag)}",
                label="No, hide my cards",
                emoji=CANCEL_EMOJI,
            ),
        ])],
        footer=(
            "No answer in 24 hours hides your cards. You can turn them "
            "back on any time."
        ),
    )


def _trading_paused_view(account, *, just_changed: bool = False) -> list[Container]:
    """Shown when a hidden member opens /cards."""
    tag = _normalize_tag(account.tag)
    return [Container(
        accent_color=GOLD_ACCENT,
        components=[
            Text(content=f"## {emojis.magnifier} Trading is off for this account"),
            Text(content=(
                "Your cards are hidden. Nobody can send you requests.\n"
                "Nothing was deleted."
                if not just_changed
                else "Done. Your cards are hidden.\nNothing was deleted."
            )),
            Separator(divider=True),
            Text(content="**Do you want to start trading cards again?**"),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"cards_trading_on:{tag}",
                    label="Yes, start trading",
                    emoji=emojis.yes.partial_emoji,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}|paused",
                    label="Not now",
                ),
            ]),
        ],
    )]


def _swap_confirm_view(
    trade: dict, *, role: str, preview: bool = False
) -> list[Container]:
    """Ask the giver whether they actually sent their card.

    Only the giver is asked, and answering only ever moves the giver's own
    card. That is what stops a card sitting in limbo because the other player
    went quiet: nobody is waiting on anybody to agree with them.
    """
    given, received = _swap_legs(trade, role=role)
    other, other_tag = _swap_counterpart(trade, role=role)
    trade_id = str(trade["_id"])
    role_action_id = f"{trade_id}|{role}"
    return [Container(
        accent_color=GOLD_ACCENT,
        components=[
            Text(content=f"## {emojis.balance_scale} Finish your swap"),
            Text(content=(
                f"You agreed to send {_card_label(given)} to "
                f"**{_escape_markdown(other, limit=50)}** • `{other_tag}`.\n"
                f"You get {_card_label(received)} back."
            )),
            Separator(divider=True),
            Text(content="**Did you send your card in game?**"),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"cards_swap_sent:{role_action_id}",
                    label="Yes, I sent it",
                    emoji=emojis.yes.partial_emoji,
                    is_disabled=preview,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_swap_later:{role_action_id}",
                    label="Not yet",
                    is_disabled=preview,
                ),
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"cards_swap_no:{role_action_id}",
                    label="No",
                    emoji=CANCEL_EMOJI,
                    is_disabled=preview,
                ),
            ]),
            Text(content=(
                "-# **Yes** removes one copy of your card straight away. "
                "**Not yet** asks again next time you open `/cards`."
            )),
        ],
    )]


def _swap_cancel_check_view(
    trade: dict, *, role: str, preview: bool = False
) -> list[Container]:
    """After "No": is this swap dead, or just not done yet?"""
    given, _received = _swap_legs(trade, role=role)
    trade_id = str(trade["_id"])
    role_action_id = f"{trade_id}|{role}"
    other = "holder" if role == "requester" else "requester"
    # "Frees both cards" is only true while neither side has confirmed. Once
    # the other player sent theirs, that card already moved and stays.
    cancel_note = (
        "**Cancelled** closes the swap. The card they sent stays in your "
        "collection. Your card is not removed."
        if trade.get(f"{other}_confirmed_at")
        else "**Cancelled** closes the swap and frees both cards."
    )
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="## What happened with this swap?"),
            Text(content=(
                f"You have not sent {_card_label(given)} yet."
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"cards_swap_dead:{trade_id}",
                    label="It was cancelled",
                    emoji=CANCEL_EMOJI,
                    is_disabled=preview,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_swap_later:{role_action_id}",
                    label="Still going to do it",
                    is_disabled=preview,
                ),
            ]),
            Text(content=(
                f"-# {cancel_note} "
                "**Still going to do it** asks you again next time."
            )),
        ],
    )]


def _swap_sent_view(
    trade: dict,
    *,
    role: str,
    remaining: int,
    other_confirmed: bool,
    preview: bool = False,
) -> list[Container]:
    """What the giver sees straight after confirming."""
    given, received = _swap_legs(trade, role=role)
    other, _other_tag = _swap_counterpart(trade, role=role)
    tag = _normalize_tag(
        trade["requester_tag"] if role == "requester" else trade["holder_tag"]
    )
    waiting = (
        f"**{_escape_markdown(other, limit=50)}** has confirmed too, so "
        f"{_card_label(received)} is already in your collection."
        if other_confirmed
        else (
            f"Waiting for **{_escape_markdown(other, limit=50)}** to confirm "
            f"they sent {_card_label(received)}. If they do not confirm "
            "within 7 days it is added for you automatically."
        )
    )
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content=f"## {emojis.yes} Card sent"),
            Text(content=(
                f"Removed one {_card_label(given)}. You have "
                f"**{remaining}** left.\n\n{waiting}"
            )),
            Separator(divider=True),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_dashboard:{tag}",
                    label="Back to collection",
                    emoji=RETURN_EMOJI,
                    is_disabled=preview,
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_trades:{tag}",
                    label="My trades",
                    emoji=TRADES_EMOJI,
                    is_disabled=preview,
                ),
            ]),
        ],
    )]


def _swap_legs(trade: dict, *, role: str):
    """(what you send, what you get) for one side of a trade."""
    wanted = CARD_BY_ID[str(trade["wanted_card_id"])]
    given = CARD_BY_ID[str(trade["given_card_id"])]
    return (given, wanted) if role == "requester" else (wanted, given)


# Shared with the owner preview command, so what it sends is exactly what a
# member receives rather than a second copy of the wording that can drift.
SWAP_ARRIVED_TITLE = "Your card arrived"


def _swap_arrived_detail(name: object) -> str:
    return (
        f"{_escape_markdown(name, limit=50)} "
        "confirmed they sent it. It is in your collection now."
    )


def _swap_cancel_note(trade: dict, reader_role: str) -> str:
    """What already happened to the cards, from this reader's side."""
    reader_sent = bool(trade.get(f"{reader_role}_confirmed_at"))
    other_role = "holder" if reader_role == "requester" else "requester"
    other_sent = bool(trade.get(f"{other_role}_confirmed_at"))
    if reader_sent:
        return (
            "You already confirmed you sent your card, so one copy stays "
            "removed from your collection. The card you were waiting for "
            "was not added."
        )
    if other_sent:
        return (
            "The other player already sent their card. It stays in your "
            "collection. Your card was not removed."
        )
    return "No tracked inventory changed."


CANCELLED_DM_TITLE = "Card swap cancelled"


def _cancelled_dm_detail(trade: dict, *, reader_role: str, released: bool) -> str:
    # One fact per line, so the truth about what moved is easy to find.
    return (
        "The other player cancelled it.\n"
        f"{_swap_cancel_note(trade, reader_role)}\n"
        + (
            "The remaining exact-card reservations were released."
            if released
            else "Releasing the reserved cards is still finishing. "
            "Open Find trades in a moment."
        )
    )


def _swap_counterpart(trade: dict, *, role: str) -> tuple[str, str]:
    if role == "requester":
        return (
            str(trade.get("holder_name") or "the other player"),
            _normalize_tag(trade.get("holder_tag")),
        )
    return (
        str(trade.get("requester_name") or "the other player"),
        _normalize_tag(trade.get("requester_tag")),
    )


def _trade_feedback(
    title: str,
    description: str,
    tag: str,
    *,
    accent: object = GREEN_ACCENT,
) -> list[Container]:
    tag = _normalize_tag(tag)
    return [_panel(accent, [
        Text(content=f"# {title}"),
        Text(content=description),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"cards_trades:{tag}",
                label="My trades",
                emoji=TRADES_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_dashboard:{tag}",
                label="Collection",
                emoji=RETURN_EMOJI,
            ),
        ]),
    ])]


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
            "Open **My trades** from your own `/cards` collection.",
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
            await _deliver(
                bot, mongo, trade, event="needs_review",
                dm_components_by_recipient=_notify_review_participants(
                    trade,
                    "Completion expired before it could be confirmed. Recheck "
                    "and correct both affected categories.",
                ),
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
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            latest, add=[card_id]
        )

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
        "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "quick_card_update",
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
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
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            latest, add=[card_id]
        )

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
        "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "card_set",
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
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
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            latest, add=batch_ids
        )

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
        "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "hidden_badge_review",
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
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


async def _write_exact_card_batch(
    mongo: MongoClient,
    account,
    inventory: dict,
    batch_ids: list[str],
    values: dict[str, int],
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
    allowed_ids: list[str] | None = None,
) -> dict:
    """Save one exact-count modal atomically without touching other cards.

    ``batch_ids`` is the complete modal scope. ``values`` contains only fields
    that supplied an exact number; a scanner-derived ``2+`` may be left blank
    to preserve that uncertainty. Blank fields are still revision/reservation
    guarded, but they are never written or marked exact.
    """
    ordered = _ordered_card_ids(batch_ids)
    explicit = dict(values)
    allowed = _ordered_card_ids(allowed_ids or ()) if allowed_ids is not None else None
    if (
        not ordered
        or len(ordered) > 5
        or len(ordered) != len(batch_ids)
        or ordered != list(batch_ids)
        or not set(explicit) <= set(ordered)
        or (
            allowed is None
            and len({CARD_BY_ID[card_id].category for card_id in ordered}) != 1
        )
        or (
            allowed is not None
            and (
                allowed != list(allowed_ids or ())
                or not set(ordered) <= set(allowed)
            )
        )
    ):
        raise ValueError("invalid exact card batch")
    for card_id, target in explicit.items():
        if (
            not isinstance(target, int)
            or isinstance(target, bool)
            or not (MISSING <= target <= MAX_COPIES)
        ):
            raise ValueError(f"invalid exact count for {card_id}")

    tag = _normalize_tag(account.tag)
    async with _inventory_lock(tag):
        latest = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        if _inventory_revision_value(latest) != int(expected_revision):
            raise InventoryWriteConflict
        if set(ordered) & set(_card_reservations(latest)):
            raise ActiveCardTradeError

        # The only legal blank is an unchanged scanner floor. Recheck against
        # the latest document so a stale modal cannot preserve a certainty that
        # no longer exists or silently skip an exact card.
        latest_cards = normalize_cards(latest.get("cards"))
        latest_confirmed = _confirmed_count_ids(latest)
        for card_id in set(ordered) - set(explicit):
            if (
                latest_cards.get(card_id, OWNED) != DUPLICATE
                or card_id in latest_confirmed
            ):
                raise InventoryWriteConflict

        # An all-blank batch is a guarded no-op: advance the UI session without
        # manufacturing a revision, timestamp, or exact-count confirmation.
        if not explicit:
            return latest

        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            latest, add=list(explicit)
        )

        now = datetime.now(timezone.utc)
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
            "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": (
                _normalize_tag(account.clan_tag) if account.clan_tag else None
            ),
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "card_batch_set",
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
        }
        for card_id, target in explicit.items():
            identity[f"cards.{card_id}"] = int(target)
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
        reservation_guards = [
            {"$or": [
                {f"card_trade_reservations.{card_id}": {"$exists": False}},
                {
                    f"card_trade_reservations.{card_id}.until": {
                        "$lte": now,
                    },
                },
            ]}
            for card_id in ordered
        ]
        written_ids = list(explicit)
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [revision_guard, *reservation_guards],
            },
            {
                "$set": identity,
                "$pull": {
                    "scan_duplicate_unverified_card_ids": {"$in": written_ids},
                },
                "$addToSet": {
                    "count_confirmed_card_ids": {"$each": written_ids},
                },
                "$inc": {"inventory_revision": 1},
            },
        )
        if getattr(result, "matched_count", 1):
            return await mongo.card_inventories.find_one({"_id": tag}) or {}
        current = await mongo.card_inventories.find_one({"_id": tag}) or {}
        if set(ordered) & set(_card_reservations(current)):
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
        duplicate_unverified = _ordered_card_ids(
            draft.get("duplicate_unverified_card_ids") or ()
        )
        manual_required = set(_scan_manual_required_ids(draft))
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            {"trusted_card_ids": []},
            add=set(CARD_BY_ID) - manual_required,
        )
        identity = {
            "discord_id": int(discord_id),
            "player_name": account.name,
        "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": _normalize_tag(account.clan_tag) if account.clan_tag else None,
            "clan_name": account.clan_name,
            "cards": card_states,
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
            "scan_duplicate_unverified_card_ids": duplicate_unverified,
            # Every count here came from the scanner, and a scanner spare is a
            # floor. Keeping an older member-entered "exact" flag would print a
            # proven-at-least-two card as exactly two.
            "count_confirmed_card_ids": [],
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


async def _write_scan_partial(
    mongo: MongoClient,
    account,
    draft: dict,
    *,
    expected_revision: int,
    discord_id: int,
    guild_id: int | None,
) -> dict:
    """Merge only the rows the scanner confirmed into an unreserved inventory.

    This is the partial-success write and it is deliberately narrower than
    `_write_scan_draft`:

    * only whole accepted rows are written. A rejected row contributes nothing,
      and an accepted row that did not arrive with all six of its positions
      invalidates the save rather than persisting the part that did arrive;
    * a category that still holds a card needing manual review loses its
      readiness, so scanning can never leave an unchecked category matchable;
    * `confirmed_at` records this accepted collection update. Per-category
      trust, not the timestamp, remains the gate that prevents unchecked cards
      from matching;
    * every card it overwrites leaves `count_confirmed_card_ids`, because a
      scanner spare is a floor and only a member-entered number is exact.

    The revision compare-and-swap and the reservation guard are the same as the
    full write.
    """
    if not _scan_draft_partially_savable(draft):
        raise ValueError("screenshot draft has no confirmed rows to save")
    raw_states = draft.get("card_states") or {}
    accepted_rows = _scan_accepted_rows(draft)
    accepted_card_ids = _row_card_ids(accepted_rows)
    unknown, _invalid_unknown = _scan_id_set(draft.get("unknown_card_ids") or ())
    unseen, _invalid_unseen = _scan_id_set(draft.get("unseen_card_ids") or ())
    # Independent of the gate above: the write boundary decides for itself
    # which cards it is allowed to touch, and refuses a row that is not whole
    # or a card that is classified two ways at once. Nothing here trusts an
    # earlier layer to have already looked.
    if unknown & unseen:
        raise ValueError("screenshot draft calls a card both unknown and unseen")
    if set(raw_states) & (unknown | unseen):
        raise ValueError("screenshot draft contradicts its own card states")
    if accepted_card_ids & unseen:
        raise ValueError("screenshot draft has an unseen card in an accepted row")
    if _rows_missing_positions(accepted_rows, set(raw_states) | unknown):
        raise ValueError("screenshot draft has an incomplete accepted row")
    confirmed = {}
    for card_id in CARD_BY_ID:
        if card_id not in raw_states:
            continue
        if card_id not in accepted_card_ids:
            raise ValueError("screenshot draft state outside an accepted row")
        state = _scan_card_state(raw_states.get(card_id))
        if state is None:
            raise ValueError("screenshot draft contains an invalid card state")
        confirmed[card_id] = state
    if not confirmed:
        raise ValueError("screenshot draft has no confirmed rows to save")

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
        # A card this scan read definitely leaves the unverified list; a card
        # it read as an obstructed spare joins it. Cards it did not touch keep
        # whatever the collection already said about them.
        proven_spares = {
            card_id
            for card_id in _ordered_card_ids(
                draft.get("duplicate_unverified_card_ids") or ()
            )
            if card_id in confirmed
        }
        duplicate_unverified = _ordered_card_ids(
            (set(_scan_unverified_ids(latest)) - set(confirmed)) | proven_spares
        )
        # This scan is a collection-wide refresh. Values it read confidently
        # become trusted; every unknown, unseen or hidden-badge value becomes
        # untrusted even if an older collection happened to contain a number.
        # That durable complement is what the Finish collection queue uses.
        manual_required = set(_scan_manual_required_ids(draft))
        scanner_trusted = set(confirmed) - proven_spares
        trusted_ids, ready_categories, reviewed_lists = _trust_projection(
            latest,
            add=scanner_trusted,
            remove=manual_required,
        )
        identity = {
            "scan_duplicate_unverified_card_ids": duplicate_unverified,
            "trusted_card_ids": trusted_ids,
            "complete_categories": ready_categories,
            "reviewed_lists": reviewed_lists,
            "discord_id": int(discord_id),
            "player_name": account.name,
            "town_hall": getattr(account, "town_hall", 0) or 0,
            "clan_tag": _normalize_tag(account.clan_tag) if account.clan_tag else None,
            "clan_name": account.clan_name,
            "updated_at": now,
            "confirmed_at": now,
            "update_source": "confirmed_partial_screenshot_review",
        }
        for card_id, state in confirmed.items():
            identity[f"cards.{card_id}"] = state
        if guild_id is not None:
            identity["guild_id"] = guild_id
        pulls: dict[str, object] = {
            # A scanner spare is a floor, so a card it overwrites can no
            # longer claim a member-entered exact count.
            "count_confirmed_card_ids": {"$in": list(confirmed)},
        }
        result = await mongo.card_inventories.update_one(
            {
                "_id": tag,
                "$and": [revision_guard, *no_live_reservation],
            },
            {
                "$set": identity,
                "$pull": pulls,
                "$inc": {"inventory_revision": 1},
            },
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
                accent=GREEN_ACCENT,
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
                "I could not verify that account",
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
                "Attach the collection screenshots",
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
                "Too many images at once",
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
                "Send only screenshot images",
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
                "Those screenshots are too large",
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
                    "That upload has closed",
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
                        "I could not read those screenshots",
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
                    "I could not process those screenshots",
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
                    "That upload has closed",
                    "Nothing was saved. Start a new scan from `/cards` in the "
                    "family server.",
                ),
            )
            return

        # The scanner accepts rows one at a time, so a batch can end with some
        # rows proven and some not. Showing the review then is the point: the
        # member keeps the proven part and finishes the rest by hand, instead
        # of being told to resend screenshots that will fail the same way.
        reviewed = _scan_ready_for_review(draft)
        finished = reviewed and not missing_pages
        if reviewed:
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
        else:
            components = _scan_upload_progress(
                account,
                session_id,
                draft,
                usable_until=usable_until,
                accepted_before=accepted_before,
            )

        await _send_scan_dm_components(bot, int(event.channel_id), components)
        if reviewed:
            if finished:
                # Nothing more can arrive for this scan, so close the upload.
                # A partial scan keeps its session open, so a member who has
                # more screenshots can still send them into the same draft.
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
    channel_id = _configured_cards_channel_id()
    if channel_id is None:
        _log.warning(
            "Card Hub trade-board posting disabled: CARDS_CHANNEL_ID is not configured"
        )
    else:
        # Named rather than merely present, because the channel is now shared
        # with the sticky notice and a wrong one is the kind of mistake that is
        # only visible in the wrong channel.
        _log.info("Card Hub trade board and sticky notice: #%s", channel_id)
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
            [("kind", 1), ("guild_id", 1), ("status", 1), ("expires_at", 1)],
            name="idx_card_trades_open_requests",
        )
        await mongo.card_trades.create_index(
            "open_request_key",
            unique=True,
            sparse=True,
            name="uniq_open_card_request",
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
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
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
                guild_id=_trade_guild_id(ctx),
            )
            components = await _dashboard_view(
                account, inventory, account_count=1,
                mongo=mongo, guild_id=_trade_guild_id(ctx),
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
    page, back_tag = _parse_account_page(action_id)
    data = await load_accounts(coc_client, int(ctx.user.id))
    return _account_picker(data, page, back_tag=back_tag)


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
        guild_id=_trade_guild_id(ctx),
    )
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
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
    # Before _load_target, deliberately: loading the target ensures the
    # inventory, and ensuring it from the wrong server would rewrite that
    # collection's family scope before anything had authorised the scan.
    scope_problem = _scan_guild_problem(ctx)
    if scope_problem:
        return scope_problem

    account, inventory, problem = await _load_target(
        ctx,
        action_id,
        coc_client=coc_client,
        mongo=mongo,
    )
    if problem:
        return problem

    user_id = int(ctx.user.id)
    # The configured family, never the interaction's guild. This is the id the
    # DM listener searches and every session button rechecks.
    guild_id = int(_configured_cards_guild_id())
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
            "Upload already finished",
            "The screenshots already moved to review. Use the review's Save or "
            "Cancel button instead.",
            accent=None,
        )
    await _discard_scan_state(mongo, action_id)
    discord_id = int(ctx.user.id)
    lock = _card_upload_locks.get(discord_id)
    if lock is not None and not lock.locked():
        _card_upload_locks.pop(discord_id, None)
    return _notice(
        "Upload cancelled",
        "No collection was changed. The bot kept no image files.",
        accent=None,
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
    if _trade_guild_id(ctx) is None:
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
            "Screenshot review unavailable",
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
        "That account is no longer linked",
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
        "Screenshot import cancelled",
        "Nothing was saved. The bot kept no image files.",
        accent=None,
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
    revised["manual_required_card_ids"] = [
        item
        for item in _ordered_card_ids(
            revised.get("manual_required_card_ids") or ()
        )
        if item != card_id
    ]
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
    if _trade_guild_id(ctx) is None:
        return _notice(
            "Screenshot import cancelled",
            "Nothing was saved. Run `/cards` in the family server to return to "
            "your collection.",
            accent=None,
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
            account, inventory, account_count=len(_loaded_entries(data)),
            mongo=mongo, guild_id=_trade_guild_id(ctx),
        )
    data = await load_accounts(coc_client, int(ctx.user.id))
    return _account_picker(data)


async def _scan_finish_handoff(
    ctx,
    account,
    inventory: dict,
    *,
    mongo: MongoClient,
    read_count: int,
) -> list[Container] | None:
    """Open a preselected exact-count queue for durable untrusted values."""
    reservations = set(_card_reservations(inventory))
    remaining = [
        item_id for item_id in _untrusted_card_ids(inventory)
        if item_id not in reservations
    ]
    if not remaining:
        return None
    landing = CARD_BY_ID[remaining[0]].category
    try:
        state_id, state = await _create_bulk_state(
            ctx,
            account,
            inventory,
            mongo=mongo,
            category_id=landing,
            scope="scan_finish",
            selected_ids=remaining,
        )
    except ValueError:
        state_id = None
        state = {}
    if state_id:
        return _scan_finish_view(
            state_id,
            state,
            read_count=read_count,
        )
    return await _quantity_editor_view(
        ctx,
        account,
        inventory,
        landing,
        mongo=mongo,
        saved=(
            "The scan values were saved, but the Finish collection session "
            "could not be opened. Use Edit all counts; nothing saved was lost."
        ),
    )


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
            "Nothing was overwritten. Start a new scan, or edit the card in your "
            "collection.",
        )
    await _discard_scan_state(mongo, action_id)
    finish = await _scan_finish_handoff(
        ctx,
        account,
        updated,
        mongo=mongo,
        read_count=len(CARDS) - len(_scan_manual_required_ids(scan_draft)),
    )
    if finish is not None:
        return finish
    if _trade_guild_id(ctx) is None:
        return _scan_saved_notice(account)
    return await _dashboard_view(
        account, updated, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
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


async def _save_partial_scan_draft(
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
    """Keep the rows the scanner confirmed, then hand over the rest by hand.

    Throwing away six proven cards because another row failed costs the member
    work for nothing, and guessing the failed row costs them a wrong
    collection. This keeps the proven part and routes the rest into the manual
    editor that already exists.
    """
    problem = _scan_session_problem(ctx, user_id, guild_id)
    if problem:
        return problem
    if not account_tag:
        return _notice(
            "Choose an account first",
            "This draft is not attached to a collection. Run `/cards` again.",
        )
    account, inventory, _data, target_problem = await _load_scan_bound_account(
        ctx,
        action_id,
        _normalize_tag(account_tag),
        usable_until=usable_until,
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    if not _scan_draft_partially_savable(scan_draft) or base_revision is None:
        return await _scan_review_view(
            account, inventory, action_id, scan_draft, usable_until=usable_until,
        )
    if _inventory_has_active_trade(inventory):
        return await _scan_review_view(
            account, inventory, action_id, scan_draft, usable_until=usable_until,
        )
    try:
        updated = await _write_scan_partial(
            mongo,
            account,
            scan_draft,
            expected_revision=int(base_revision),
            discord_id=int(ctx.user.id),
            guild_id=int(guild_id),
        )
    except (TypeError, ValueError):
        return await _scan_review_view(
            account, inventory, action_id, scan_draft, usable_until=usable_until,
        )
    except ActiveCardTradeError:
        latest = await mongo.card_inventories.find_one({
            "_id": _normalize_tag(account.tag)
        }) or inventory
        return await _scan_review_view(
            account, latest, action_id, scan_draft, usable_until=usable_until,
        )
    except ScanDraftStaleError:
        return _notice(
            "Collection changed after this scan",
            "Nothing was overwritten. Start a new scan, or set the card in "
            "your collection.",
        )

    await _discard_scan_state(mongo, action_id)
    finish = await _scan_finish_handoff(
        ctx,
        account,
        updated,
        mongo=mongo,
        read_count=len(
            set(scan_draft.get("card_states") or ())
            - set(_scan_manual_required_ids(scan_draft))
        ),
    )
    if finish is not None:
        return finish
    if _trade_guild_id(ctx) is None:
        return _scan_saved_notice(account)
    return await _dashboard_view(
        account,
        updated,
        account_count=len(_loaded_entries(_data)),
        mongo=mongo,
        guild_id=_trade_guild_id(ctx),
    )


@register_action("cards_scan_save_partial", requires_state=True)
@lightbulb.di.with_di
async def cards_scan_save_partial(
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
    return await _save_partial_scan_draft(
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


# cards_sort was the board's order control, removed with the card menus it
# sorted. Its custom_id is the same shape as this one, so a board someone
# still has open redraws instead of answering "This panel is out of date".
@register_action("cards_dashboard", aliases=("cards_sort",))
@lightbulb.di.with_di
async def cards_dashboard(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, suffix = _parse_target(str(action_id or ""))
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
        # The paused screen's "Not now" carries `|paused` so it can show the
        # board once without turning trading back on. _parse_target drops the
        # suffix (it only returns category ids), so read it off the raw id.
        skip_paused_gate=str(action_id or "").endswith("|paused"),
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
    if values and values[0] == CATEGORY_HEADER_VALUE:
        # The header is only there to put the category art on the closed menu.
        # Tapping it is not an error, it just means nothing was chosen.
        return None
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
            guild_id=_trade_guild_id(ctx),
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
            guild_id=_trade_guild_id(ctx),
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
        return await _dashboard_view(account, inventory, account_count=1, mongo=mongo, guild_id=_trade_guild_id(ctx))
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
            guild_id=_trade_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return _notice(
            "Cards reserved",
            "Finish or cancel the accepted trade before changing these cards.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _dashboard_view(account, current, account_count=1, mongo=mongo, guild_id=_trade_guild_id(ctx))
    if _scan_unverified_ids(updated):
        return _hidden_badge_review(account, updated)
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, updated, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
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
    # The title is the card name alone. "How many <card> cards do you have?"
    # reads better but does not fit: a modal title caps at 45 characters and
    # Super Wall Breaker makes it 46, so the question mark would be silently
    # chopped off for the longest names. The card name is 18 at worst, and the
    # field below asks the question - in the same words as the screen you came
    # from, rather than introducing "hold" as a second verb for "have".
    await ctx.respond_with_modal(
        title=CARD_BY_ID[card_id].name[:45],
        custom_id=f"cards_count_submit:{tag}|{card_id}",
        components=[ModalActionRow().add_text_input(
            "copies",
            "How many do you have?",
            placeholder=f"0 to {MAX_COPIES}",
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
    # Same as cards_qnum_submit: update the panel the modal came from rather
    # than answering with a duplicate message.
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
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
            guild_id=_trade_guild_id(ctx),
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
            guild_id=_trade_guild_id(ctx),
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
    """Update collection. Opens straight into a category, not a menu of them.

    This used to render a router of four category buttons whose only job was
    to ask which category you wanted. The editor now carries that question as
    a menu at the top, so the router was a page-change that answered nothing.
    """
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    # Land on the first category that still cannot be traded, so setting up
    # for the first time starts where the work is. Once everything is ready
    # this is simply the first category.
    complete = set(inventory.get("complete_categories") or ())
    landing = next(
        (category.id for category in CATEGORIES if category.id not in complete),
        CATEGORIES[0].id,
    )
    return await _quantity_editor_view(
        ctx, account, inventory, landing, mongo=mongo
    )


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
    if _scan_unverified_ids(inventory):
        finish = await _scan_finish_handoff(
            ctx,
            account,
            inventory,
            mongo=mongo,
            read_count=len(CARDS) - len(_untrusted_card_ids(inventory)),
        )
        if finish is not None:
            return finish
    # Compatibility for an old posted cards_hidden button: once every value
    # is trusted it simply returns to the collection instead of reviving the
    # retired scanner-specific review path.
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account,
        inventory,
        account_count=len(_loaded_entries(data)),
        mongo=mongo,
        guild_id=_trade_guild_id(ctx),
        skip_paused_gate=str(action_id or "").endswith("|paused"),
    )


def _parse_quantity_target(value: object) -> tuple[str, str | None, str | None]:
    """Split `tag|category` and an optional trailing card id.

    Explicit split, not _parse_target: that helper only ever returns a second
    value when the second field is a category id, so it silently drops
    anything after it.

    The third field is tolerated rather than required. The paged version of
    this screen put a page number there, so buttons on messages sent before
    this change still parse - they just land on the category's first card
    instead of erroring at the member.
    """
    parts = str(value or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    category_id = (
        parts[1] if len(parts) > 1 and parts[1] in CATEGORY_BY_ID else None
    )
    card_id = parts[2] if len(parts) > 2 and parts[2] in CARD_BY_ID else None
    return tag, category_id, card_id


def _parse_quantity_card(value: object) -> tuple[str, str | None, int]:
    """Split `tag|card` and an optional step.

    Also tolerates the paged version's trailing page number, which is simply
    ignored - there are no pages any more.
    """
    parts = str(value or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    card_id = parts[1] if len(parts) > 1 and parts[1] in CARD_BY_ID else None
    delta = 0
    if len(parts) > 2:
        try:
            delta = int(parts[2])
        except (TypeError, ValueError):
            delta = 0
    return tag, card_id, delta


async def _quantity_screen(
    ctx,
    action_id: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
    card_id: object = None,
):
    """Shared open/refresh for the category screen."""
    tag, category_id, from_id = _parse_quantity_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    return await _quantity_editor_view(
        ctx,
        account,
        inventory,
        category_id,
        mongo=mongo,
        card_id=card_id or from_id,
    )


def _bulk_state_owned(ctx, state_id: str, state: dict) -> bool:
    """Whether this live session belongs to this user and family scope."""
    if state.get("type") != "cards_bulk_edit":
        return False
    tag, category_id = _bulk_state_target(state_id)
    try:
        owner_id = int(state.get("user_id"))
    except (TypeError, ValueError):
        return False
    scope = state.get("scope") or "category"
    return (
        owner_id == int(ctx.user.id)
        and state.get("guild_id") == _trade_guild_id(ctx)
        and _normalize_tag(state.get("account_tag")) == tag
        and state.get("category_id") == category_id
        and (
            (scope == "scan_finish" and _bulk_is_scan_finish_id(state_id))
            or (scope == "category" and not _bulk_is_scan_finish_id(state_id))
        )
    )


def _bulk_state_well_formed(state: dict) -> bool:
    category_id = state.get("category_id")
    if category_id not in CATEGORY_BY_ID:
        return False
    scope = state.get("scope") or "category"
    editable = list(state.get("editable_ids") or ())
    if scope == "scan_finish":
        canonical = _ordered_card_ids(editable)
    elif scope == "category":
        canonical = [
            item.id for item in CATEGORY_CARDS[category_id]
            if item.id in set(editable)
        ]
    else:
        return False
    counts = state.get("count_snapshot")
    selected = list(state.get("selected_ids") or ())
    canonical_selected = [
        item_id for item_id in editable if item_id in set(selected)
    ]
    unconfirmed = set(state.get("unconfirmed_ids") or ())
    required = list(state.get("required_entry_ids") or ())
    return (
        editable == canonical
        and bool(editable)
        and isinstance(counts, dict)
        and set(counts) == set(editable)
        and all(
            isinstance(counts[item_id], int)
            and not isinstance(counts[item_id], bool)
            and MISSING <= counts[item_id] <= MAX_COPIES
            for item_id in editable
        )
        and selected == canonical_selected
        and unconfirmed <= set(editable)
        and all(counts[item_id] == DUPLICATE for item_id in unconfirmed)
        and (
            (scope == "category" and not required)
            or (
                scope == "scan_finish"
                and selected == editable
                and required == selected
                and not (unconfirmed & set(required))
                and CARD_BY_ID[editable[0]].category == category_id
            )
        )
    )


async def _bulk_state_update(
    mongo: MongoClient,
    state_id: str,
    state: dict,
    *,
    guard: dict,
    values: dict,
    unset: tuple[str, ...] = (),
):
    """CAS a live state transition and slide its expiry in the same update."""
    now = datetime.now(timezone.utc)
    filt = {
        "_id": state_id,
        "type": "cards_bulk_edit",
        "user_id": int(state["user_id"]),
        "guild_id": state.get("guild_id"),
        "account_tag": _normalize_tag(state.get("account_tag")),
        "category_id": state.get("category_id"),
        "expires_at": {"$gt": now},
        **guard,
    }
    if "scope" in state:
        filt["scope"] = state.get("scope")
    update: dict = {"$set": {
        **values,
        "expires_at": now + CARD_BULK_SESSION_FOR,
    }}
    if unset:
        update["$unset"] = {name: "" for name in unset}
    return await update_state(mongo, filt, update)


def _bulk_matched(result) -> bool:
    return bool(getattr(result, "matched_count", 0))


def _bulk_selected(state: dict, values) -> list[str] | None:
    raw = [str(value) for value in (values or ())]
    if not raw or len(raw) != len(set(raw)):
        return None
    allowed = list(state.get("editable_ids") or ())
    selected_set = set(raw)
    selected = [item_id for item_id in allowed if item_id in selected_set]
    return selected if set(selected) == selected_set else None


def _bulk_exact_modal(state_id: str, state: dict) -> dict:
    """Build the current one-to-five-card modal from persisted state."""
    selected = list(state.get("selected_ids") or ())
    start = int(state.get("next_index") or 0)
    batch = selected[start:start + 5]
    total = len(selected)
    nonce = str(state.get("nonce") or "")
    counts = dict(state.get("count_snapshot") or {})
    uncertain = set(state.get("unconfirmed_ids") or ())
    required_entries = set(state.get("required_entry_ids") or ())
    inputs = []
    for offset, item_id in enumerate(batch):
        custom_id = f"q_{nonce}_{offset}"
        label = f"{start + offset + 1}. {CARD_BY_ID[item_id].name}"[:45]
        if item_id in required_entries:
            inputs.append(ModalActionRow().add_text_input(
                custom_id,
                label,
                placeholder=f"Enter {MISSING} to {MAX_COPIES}",
                min_length=1,
                max_length=2,
                required=True,
            ))
        elif item_id in uncertain:
            inputs.append(ModalActionRow().add_text_input(
                custom_id,
                label,
                placeholder="Current 2+ - leave blank to keep it",
                required=False,
                max_length=2,
            ))
        else:
            inputs.append(ModalActionRow().add_text_input(
                custom_id,
                label,
                value=str(counts[item_id]),
                placeholder=f"0 to {MAX_COPIES}",
                min_length=1,
                max_length=2,
                required=True,
            ))
    end = start + len(batch)
    category = CATEGORY_BY_ID[state["category_id"]]
    title = (
        f"Finish collection \u00b7 {start + 1}-{end} of {total}"
        if state.get("scope") == "scan_finish"
        else f"{category.name} \u00b7 {start + 1}-{end} of {total}"
    )
    return {
        "title": title[:45],
        "custom_id": f"cards_bulk_submit:{state_id}",
        "components": inputs,
    }


def _bulk_progress_view(
    state_id: str,
    state: dict,
    *,
    note: str | None = None,
    retry: bool = False,
) -> list[Container]:
    selected = list(state.get("selected_ids") or ())
    processed = int(state.get("processed_count") or 0)
    written = int(state.get("written_count") or 0)
    total = len(selected)
    remaining = max(0, total - int(state.get("next_index") or 0))
    last_batch = selected[max(0, processed - 5):processed]
    checked = "\n".join(
        f"\u2713 {_escape_markdown(CARD_BY_ID[item_id].name)}"
        for item_id in last_batch
    )
    detail = (
        f"## {processed} of {total} checked\n"
        + (f"{checked}\n\n" if checked else "")
        + f"**{remaining} remaining**\n"
        f"-# {written} exact count{'s' if written != 1 else ''} saved. "
        "Submitted batches are already saved."
    )
    if note:
        detail += f"\n\n{_escape_markdown(note, limit=300)}"
    scan_finish = state.get("scope") == "scan_finish"
    if scan_finish and processed == 0:
        detail = (
            f"**{total} card{'s' if total != 1 else ''} still need a count.**\n"
            "Enter a count for every card. Each submitted group saves "
            "automatically."
        )
        if note:
            detail += f"\n\n{_escape_markdown(note, limit=300)}"
    return [Container(
        accent_color=CATEGORY_ACCENTS[state["category_id"]],
        components=[
            Text(content=(
                (
                    "# Finish collection\n"
                    if scan_finish
                    else (
                        f"# Bulk edit \u00b7 "
                        f"{CATEGORY_BY_ID[state['category_id']].name}\n"
                    )
                )
                + f"-# {_escape_markdown(state.get('account_name'))} \u00b7 "
                f"`{_normalize_tag(state.get('account_tag'))}`"
            )),
            Text(content=detail),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_bulk_continue:{state_id}",
                    label=(
                        "Try again"
                        if retry
                        else "Enter counts" if scan_finish and processed == 0
                        else "Continue"
                    ),
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_bulk_finish:{state_id}",
                    label="Finish later" if scan_finish else "Finish here",
                ),
            ]),
            Text(content=(
                f"-# {'Finish later' if scan_finish else 'Finish here'} keeps "
                "every submitted batch and leaves the "
                "remaining cards unchanged."
            )),
        ],
    )]


def _scan_finish_view(
    state_id: str,
    state: dict,
    *,
    read_count: int,
) -> list[Container]:
    """Handoff from a saved scan into its preselected exact-count queue."""
    remaining = len(state.get("selected_ids") or ())
    return [Container(
        accent_color=GOLD_ACCENT,
        components=[
            Text(content="# Scan finished"),
            Text(content=(
                f"{_escape_markdown(state.get('account_name'))} \u00b7 "
                f"`{_normalize_tag(state.get('account_tag'))}`\n"
                f"**{max(0, int(read_count))} of {len(CARDS)} cards read.**\n"
                f"**{remaining} still need a count.**\n\n"
                "Finish these cards to complete your collection. Each "
                "submitted group saves automatically."
            )),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"cards_bulk_continue:{state_id}",
                    label="Enter counts",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id=f"cards_bulk_finish:{state_id}",
                    label="Finish later",
                ),
            ]),
        ],
    )]


def _bulk_modal_values(
    ctx, state: dict
) -> tuple[dict[str, int] | None, str | None]:
    selected = list(state.get("selected_ids") or ())
    start = int(state.get("next_index") or 0)
    batch = selected[start:start + 5]
    nonce = str(state.get("nonce") or "")
    expected_ids = [f"q_{nonce}_{offset}" for offset in range(len(batch))]
    supplied: list[tuple[str, str]] = []
    for row in getattr(ctx.interaction, "components", ()) or ():
        for component in row:
            supplied.append((
                str(getattr(component, "custom_id", "") or ""),
                str(getattr(component, "value", "") or "").strip(),
            ))
    supplied_ids = [custom_id for custom_id, _value in supplied]
    if (
        set(supplied_ids) != set(expected_ids)
        or len(supplied_ids) != len(set(supplied_ids))
    ):
        return None, "That form is no longer current. Nothing changed."

    uncertain = set(state.get("unconfirmed_ids") or ())
    supplied_by_id = dict(supplied)
    values: dict[str, int] = {}
    for offset, item_id in enumerate(batch):
        raw = supplied_by_id[expected_ids[offset]]
        if not raw and item_id in uncertain:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return {}, f"Enter a whole number from {MISSING} to {MAX_COPIES}. Nothing changed."
        if not (MISSING <= value <= MAX_COPIES):
            return {}, f"Enter a whole number from {MISSING} to {MAX_COPIES}. Nothing changed."
        values[item_id] = value
    return values, None


async def _bulk_defer_update(ctx) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
        await ctx.defer(ephemeral=True)


async def _bulk_recovery_view(
    ctx,
    state_id: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
    saved: str | None = None,
) -> list[Container]:
    tag, category_id = _bulk_state_target(state_id)
    if not tag or category_id is None:
        return _notice("Bulk editor unavailable", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return [
            *problem,
            *_notice(
                "Completed batches remain saved",
                "This session could not be refreshed right now. Re-run `/cards` "
                "when the account is available; saved counts remain in the collection.",
            ),
        ]
    if _bulk_is_scan_finish_id(state_id):
        reservations = set(_card_reservations(inventory))
        untrusted = _untrusted_card_ids(inventory)
        remaining = [
            item_id for item_id in untrusted
            if item_id not in reservations
        ]
        if remaining:
            landing = CARD_BY_ID[remaining[0]].category
            try:
                fresh_id, fresh_state = await _create_bulk_state(
                    ctx,
                    account,
                    inventory,
                    mongo=mongo,
                    category_id=landing,
                    scope="scan_finish",
                    selected_ids=remaining,
                )
            except ValueError:
                fresh_id = None
                fresh_state = {}
            if fresh_id:
                return _bulk_progress_view(
                    fresh_id,
                    fresh_state,
                    note=(
                        saved
                        or "This session expired. Completed groups remain saved; "
                        "continue with the cards that still need a count."
                    ),
                )
        blocked = [item_id for item_id in untrusted if item_id in reservations]
        recovery_note = saved
        if recovery_note is None:
            recovery_note = (
                "This session expired. Completed groups remain saved. "
                "Reserved cards can be finished after their trade ends."
                if blocked
                else (
                    "This session expired after all remaining counts were "
                    "saved. The collection below is current."
                )
            )
        return await _quantity_editor_view(
            ctx,
            account,
            inventory,
            category_id,
            mongo=mongo,
            saved=recovery_note,
        )
    return await _quantity_editor_view(
        ctx,
        account,
        inventory,
        category_id,
        mongo=mongo,
        saved=saved or (
            "This bulk session expired. Counts from completed batches are shown "
            "below. Select any remaining cards again."
        ),
    )


async def _bulk_discard_state(mongo: MongoClient, state_id: str) -> None:
    """Best-effort cleanup; inventory truth must still reach the player."""
    try:
        await delete_state(mongo, state_id)
    except Exception:
        _log.exception("could not discard card bulk state id=%s", state_id)


async def _bulk_writing_recovery_view(
    ctx,
    state_id: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> list[Container]:
    """Recover a state stranded while a process was saving a batch."""
    await _bulk_discard_state(mongo, state_id)
    return await _bulk_recovery_view(
        ctx,
        state_id,
        coc_client=coc_client,
        mongo=mongo,
        saved=(
            "Bulk editing was interrupted. Completed groups remain saved; "
            "continue with cards that still need a count."
        ),
    )


async def _bulk_ack_recovery(
    ctx,
    state_id: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> None:
    await _bulk_defer_update(ctx)
    view = await _bulk_recovery_view(
        ctx, state_id, coc_client=coc_client, mongo=mongo
    )
    await ctx.interaction.edit_initial_response(components=view)


async def _bulk_ack_writing_recovery(
    ctx,
    state_id: str,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> None:
    await _bulk_defer_update(ctx)
    view = await _bulk_writing_recovery_view(
        ctx, state_id, coc_client=coc_client, mongo=mongo
    )
    await ctx.interaction.edit_initial_response(components=view)


def _bulk_writing_stalled(state: dict) -> bool:
    started_at = as_utc(state.get("writing_started_at"))
    return (
        started_at is None
        or started_at <= datetime.now(timezone.utc) - CARD_BULK_WRITE_GRACE
    )


async def _bulk_respond_writing(
    ctx,
    state_id: str,
    state: dict,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> None:
    """Keep an active write intact; recover only after a restart-safe grace."""
    if _bulk_writing_stalled(state):
        await _bulk_ack_writing_recovery(
            ctx, state_id, coc_client=coc_client, mongo=mongo
        )
        return
    await ctx.respond(
        components=_notice(
            "This batch is still saving",
            "Try again shortly. Previously saved batches remain saved.",
        ),
        ephemeral=True,
    )


async def _bulk_open_current(
    ctx,
    state_id: str,
    state: dict,
    selected: list[str],
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
) -> None:
    nonce = secrets.token_urlsafe(5)
    result = await _bulk_state_update(
        mongo,
        state_id,
        state,
        guard={
            "phase": "select",
            "nonce": state.get("nonce"),
            "next_index": 0,
            "expected_revision": int(state.get("expected_revision") or 0),
        },
        values={
            "selected_ids": selected,
            "next_index": 0,
            "processed_count": 0,
            "written_count": 0,
            "nonce": nonce,
        },
    )
    if not _bulk_matched(result):
        fresh = await get_state(mongo, state_id, {"_id": 0})
        if fresh is None:
            await _bulk_ack_recovery(
                ctx, state_id, coc_client=coc_client, mongo=mongo
            )
        elif fresh.get("phase") == "writing":
            await _bulk_respond_writing(
                ctx,
                state_id,
                fresh,
                coc_client=coc_client,
                mongo=mongo,
            )
        else:
            await ctx.respond(
                components=_notice(
                    "A newer form is already open",
                    "Use the newest bulk-count form, or tap its button again if you dismissed it.",
                ),
                ephemeral=True,
            )
        return
    opened = {
        **state,
        "selected_ids": selected,
        "next_index": 0,
        "processed_count": 0,
        "written_count": 0,
        "nonce": nonce,
    }
    await ctx.respond_with_modal(**_bulk_exact_modal(state_id, opened))


@register_action("cards_bulk_select", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_bulk_select(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **state,
):
    if state.get("type") != "cards_bulk_edit":
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_owned(ctx, action_id, state):
        await ctx.respond(
            components=_notice(
                "This bulk editor belongs to another player",
                "Open your own collection with `/cards`.",
            ),
            ephemeral=True,
        )
        return
    if state.get("phase") == "writing":
        await _bulk_respond_writing(
            ctx, action_id, state, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_well_formed(state):
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    selected = _bulk_selected(
        state, getattr(ctx.interaction, "values", ()) or ()
    )
    if selected is None:
        await ctx.respond(
            components=_notice(
                "Choose at least one editable card",
                "Reserved cards stay visible in the list but cannot be selected.",
            ),
            ephemeral=True,
        )
        return
    await _bulk_open_current(
        ctx,
        action_id,
        state,
        selected,
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_bulk_edit_all", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_bulk_edit_all(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **state,
):
    if state.get("type") != "cards_bulk_edit":
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_owned(ctx, action_id, state):
        await ctx.respond(
            components=_notice(
                "This bulk editor belongs to another player",
                "Open your own collection with `/cards`.",
            ),
            ephemeral=True,
        )
        return
    if state.get("phase") == "writing":
        await _bulk_respond_writing(
            ctx, action_id, state, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_well_formed(state):
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    await _bulk_open_current(
        ctx,
        action_id,
        state,
        list(state["editable_ids"]),
        coc_client=coc_client,
        mongo=mongo,
    )


@register_action("cards_bulk_continue", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_bulk_continue(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **state,
):
    if state.get("type") != "cards_bulk_edit":
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_owned(ctx, action_id, state):
        await ctx.respond(
            components=_notice(
                "This bulk editor belongs to another player",
                "Open your own collection with `/cards`.",
            ),
            ephemeral=True,
        )
        return
    if state.get("phase") == "writing":
        await _bulk_respond_writing(
            ctx, action_id, state, coc_client=coc_client, mongo=mongo
        )
        return
    selected = list(state.get("selected_ids") or ())
    start = int(state.get("next_index") or 0)
    if (
        not _bulk_state_well_formed(state)
        or state.get("phase") != "continue"
        or not (0 <= start < len(selected))
    ):
        await ctx.respond(
            components=_notice(
                "This step is no longer current",
                "Use the newest bulk editor panel.",
            ),
            ephemeral=True,
        )
        return
    nonce = secrets.token_urlsafe(5)
    result = await _bulk_state_update(
        mongo,
        action_id,
        state,
        guard={
            "phase": "continue",
            "nonce": state.get("nonce"),
            "next_index": start,
            "expected_revision": int(state.get("expected_revision") or 0),
        },
        values={"nonce": nonce},
    )
    if not _bulk_matched(result):
        fresh = await get_state(mongo, action_id, {"_id": 0})
        if fresh is None:
            await _bulk_ack_recovery(
                ctx, action_id, coc_client=coc_client, mongo=mongo
            )
        elif fresh.get("phase") == "writing":
            await _bulk_respond_writing(
                ctx,
                action_id,
                fresh,
                coc_client=coc_client,
                mongo=mongo,
            )
        else:
            await ctx.respond(
                components=_notice(
                    "A newer form is already open",
                    "Use the newest form, or tap Continue again if you dismissed it.",
                ),
                ephemeral=True,
            )
        return
    opened = {**state, "nonce": nonce}
    await ctx.respond_with_modal(**_bulk_exact_modal(action_id, opened))


@register_action("cards_bulk_finish", no_return=True)
@lightbulb.di.with_di
async def cards_bulk_finish(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **state,
):
    if state.get("type") != "cards_bulk_edit":
        view = await _bulk_recovery_view(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        await ctx.interaction.edit_initial_response(components=view)
        return
    if not _bulk_state_owned(ctx, action_id, state):
        # The dispatcher already acknowledged this message update before the
        # state read. Fail closed without editing another player's panel.
        return
    if state.get("phase") == "writing":
        if _bulk_writing_stalled(state):
            view = await _bulk_writing_recovery_view(
                ctx, action_id, coc_client=coc_client, mongo=mongo
            )
            await ctx.interaction.edit_initial_response(components=view)
        return
    result = await _bulk_state_update(
        mongo,
        action_id,
        state,
        guard={
            "phase": "continue",
            "nonce": state.get("nonce"),
            "next_index": int(state.get("next_index") or 0),
            "expected_revision": int(state.get("expected_revision") or 0),
        },
        values={"phase": "closed"},
    )
    if not _bulk_matched(result):
        fresh = await get_state(mongo, action_id, {"_id": 0})
        if fresh is None:
            view = await _bulk_recovery_view(
                ctx, action_id, coc_client=coc_client, mongo=mongo
            )
            await ctx.interaction.edit_initial_response(components=view)
        elif fresh.get("phase") == "writing":
            if _bulk_writing_stalled(fresh):
                view = await _bulk_writing_recovery_view(
                    ctx, action_id, coc_client=coc_client, mongo=mongo
                )
                await ctx.interaction.edit_initial_response(components=view)
        return
    await _bulk_discard_state(mongo, action_id)
    tag = _normalize_tag(state.get("account_tag"))
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        view = [
            *problem,
            *_notice(
                "Submitted batches remain saved",
                "The remaining cards were not changed. Re-run `/cards` when the "
                "account is available to continue.",
            ),
        ]
    else:
        view = await _quantity_editor_view(
            ctx,
            account,
            inventory,
            state["category_id"],
            mongo=mongo,
            saved=(
                (
                    "Finished for now. Submitted groups remain saved; cards "
                    "still needing a count are not ready to trade."
                    if state.get("scope") == "scan_finish"
                    else (
                        f"Bulk editing finished. "
                        f"{int(state.get('written_count') or 0)} exact counts "
                        "were saved; remaining cards were unchanged."
                    )
                )
            ),
        )
    await ctx.interaction.edit_initial_response(components=view)


@register_action("cards_bulk_submit", is_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_bulk_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **state,
):
    if state.get("type") != "cards_bulk_edit":
        await _bulk_ack_recovery(
            ctx, action_id, coc_client=coc_client, mongo=mongo
        )
        return
    if not _bulk_state_owned(ctx, action_id, state):
        await ctx.respond(
            components=_notice(
                "This bulk editor belongs to another player",
                "Open your own collection with `/cards`.",
            ),
            ephemeral=True,
        )
        return
    if state.get("phase") == "writing":
        await _bulk_respond_writing(
            ctx, action_id, state, coc_client=coc_client, mongo=mongo
        )
        return
    selected = list(state.get("selected_ids") or ())
    start = int(state.get("next_index") or 0)
    phase = state.get("phase")
    if (
        not _bulk_state_well_formed(state)
        or phase not in {"select", "continue"}
        or not selected
        or not (0 <= start < len(selected))
    ):
        await ctx.respond(
            components=_notice(
                "This form is no longer current",
                "Use the newest bulk editor form. No count was changed by this form.",
            ),
            ephemeral=True,
        )
        return
    values, validation_problem = _bulk_modal_values(ctx, state)
    if values is None:
        await ctx.respond(
            components=_notice(
                "This form is no longer current",
                "Use the newest bulk editor form. No count was changed by this form.",
            ),
            ephemeral=True,
        )
        return
    await _bulk_defer_update(ctx)
    if validation_problem:
        nonce = secrets.token_urlsafe(5)
        result = await _bulk_state_update(
            mongo,
            action_id,
            state,
            guard={
                "phase": phase,
                "nonce": state.get("nonce"),
                "next_index": start,
                "expected_revision": int(state.get("expected_revision") or 0),
            },
            values={"phase": "continue", "nonce": nonce},
        )
        if _bulk_matched(result):
            retry = {**state, "phase": "continue", "nonce": nonce}
            await ctx.interaction.edit_initial_response(
                components=_bulk_progress_view(
                    action_id, retry, note=validation_problem, retry=True
                )
            )
        else:
            fresh = await get_state(mongo, action_id, {"_id": 0})
            if fresh is None:
                view = await _bulk_recovery_view(
                    ctx, action_id, coc_client=coc_client, mongo=mongo
                )
                await ctx.interaction.edit_initial_response(components=view)
        return

    expected_revision = int(state.get("expected_revision") or 0)
    claim = await _bulk_state_update(
        mongo,
        action_id,
        state,
        guard={
            "phase": phase,
            "nonce": state.get("nonce"),
            "next_index": start,
            "expected_revision": expected_revision,
        },
        values={
            "phase": "writing",
            "writing_started_at": datetime.now(timezone.utc),
        },
    )
    if not _bulk_matched(claim):
        fresh = await get_state(mongo, action_id, {"_id": 0})
        if fresh is None:
            view = await _bulk_recovery_view(
                ctx, action_id, coc_client=coc_client, mongo=mongo
            )
            await ctx.interaction.edit_initial_response(components=view)
        elif fresh.get("phase") == "writing":
            if _bulk_writing_stalled(fresh):
                view = await _bulk_writing_recovery_view(
                    ctx, action_id, coc_client=coc_client, mongo=mongo
                )
                await ctx.interaction.edit_initial_response(components=view)
        return

    tag = _normalize_tag(state.get("account_tag"))
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        await _bulk_discard_state(mongo, action_id)
        await ctx.interaction.edit_initial_response(components=[
            *problem,
            *_notice(
                "Earlier saved batches remain saved",
                "This group was not saved. Counts from earlier completed "
                "batches remain in the collection.",
            ),
        ])
        return
    batch = selected[start:start + 5]
    try:
        updated = await _write_exact_card_batch(
            mongo,
            account,
            inventory,
            batch,
            values,
            expected_revision=expected_revision,
            discord_id=int(ctx.user.id),
            guild_id=_trade_guild_id(ctx),
            allowed_ids=(
                list(state.get("required_entry_ids") or ())
                if state.get("scope") == "scan_finish"
                else None
            ),
        )
    except ActiveCardTradeError:
        await _bulk_discard_state(mongo, action_id)
        if state.get("scope") == "scan_finish":
            view = await _bulk_recovery_view(
                ctx,
                action_id,
                coc_client=coc_client,
                mongo=mongo,
                saved=(
                    "A card in this group entered a trade, so this group was "
                    "not changed. Earlier completed groups remain saved; "
                    "continue with cards that still need a count."
                ),
            )
        else:
            current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
            view = await _quantity_editor_view(
                ctx,
                account,
                current,
                state["category_id"],
                mongo=mongo,
                saved=(
                    "A card in this batch entered a trade, so this batch was not "
                    "changed. Any earlier submitted batches remain saved. Select "
                    "the remaining editable cards again."
                ),
            )
        await ctx.interaction.edit_initial_response(components=view)
        return
    except (InventoryWriteConflict, ValueError):
        await _bulk_discard_state(mongo, action_id)
        if state.get("scope") == "scan_finish":
            view = await _bulk_recovery_view(
                ctx,
                action_id,
                coc_client=coc_client,
                mongo=mongo,
                saved=(
                    "The collection changed, so this group was not changed. "
                    "Earlier completed groups remain saved; continue with "
                    "cards that still need a count."
                ),
            )
        else:
            current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
            view = await _quantity_editor_view(
                ctx,
                account,
                current,
                state["category_id"],
                mongo=mongo,
                saved=(
                    "The collection changed, so this batch was not changed. Any "
                    "earlier submitted batches remain saved. Select the remaining "
                    "cards again."
                ),
            )
        await ctx.interaction.edit_initial_response(components=view)
        return

    next_index = start + len(batch)
    written_count = int(state.get("written_count") or 0) + len(values)
    count_snapshot = dict(state.get("count_snapshot") or {})
    count_snapshot.update(values)
    unconfirmed_ids = [
        item_id for item_id in (state.get("unconfirmed_ids") or ())
        if item_id not in values
    ]
    next_revision = expected_revision + (1 if values else 0)
    if next_index >= len(selected):
        await _bulk_discard_state(mongo, action_id)
        landing_category = (
            CARD_BY_ID[batch[-1]].category
            if state.get("scope") == "scan_finish"
            else state["category_id"]
        )
        view = await _quantity_editor_view(
            ctx,
            account,
            updated,
            landing_category,
            mongo=mongo,
            saved=(
                f"Bulk edit complete. {written_count} exact count"
                f"{'s were' if written_count != 1 else ' was'} saved."
            ),
        )
        await ctx.interaction.edit_initial_response(components=view)
        return

    nonce = secrets.token_urlsafe(5)
    try:
        advanced = await _bulk_state_update(
            mongo,
            action_id,
            state,
            guard={
                "phase": "writing",
                "nonce": state.get("nonce"),
                "next_index": start,
                "expected_revision": expected_revision,
            },
            values={
                "phase": "continue",
                "nonce": nonce,
                "next_index": next_index,
                "processed_count": next_index,
                "written_count": written_count,
                "expected_revision": next_revision,
                "count_snapshot": count_snapshot,
                "unconfirmed_ids": unconfirmed_ids,
            },
            unset=("writing_started_at",),
        )
    except Exception:
        _log.exception(
            "card bulk batch saved but state could not advance id=%s",
            action_id,
        )
        advanced = None
    if not _bulk_matched(advanced):
        await _bulk_discard_state(mongo, action_id)
        if state.get("scope") == "scan_finish":
            view = await _bulk_recovery_view(
                ctx,
                action_id,
                coc_client=coc_client,
                mongo=mongo,
                saved=(
                    "This submitted group was saved. Continue with cards that "
                    "still need a count."
                ),
            )
        else:
            view = await _quantity_editor_view(
                ctx,
                account,
                updated,
                state["category_id"],
                mongo=mongo,
                saved=(
                    "This submitted batch was saved. Reopen bulk editing and select "
                    "the remaining cards again."
                ),
            )
        await ctx.interaction.edit_initial_response(components=view)
        return
    progressed = {
        **state,
        "phase": "continue",
        "nonce": nonce,
        "next_index": next_index,
        "processed_count": next_index,
        "written_count": written_count,
        "expected_revision": next_revision,
        "count_snapshot": count_snapshot,
        "unconfirmed_ids": unconfirmed_ids,
    }
    await ctx.interaction.edit_initial_response(
        components=_bulk_progress_view(action_id, progressed)
    )


# cards_qty and cards_qjump were the paged version's controls. They are kept as
# aliases rather than deleted so a panel someone still has open answers with
# the new screen instead of "This panel is out of date".
@register_action("cards_category", aliases=("cards_qty",))
@lightbulb.di.with_di
async def cards_category(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    # No category-wide reservation gate. Writes are per card, and
    # _write_card_state still refuses a reserved one, so a single held card no
    # longer locks the rest of its category.
    return await _quantity_screen(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )


@register_action("cards_qcat")
@lightbulb.di.with_di
async def cards_qcat(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Switch which category the screen is showing, without a page change."""
    tag = _normalize_tag(str(action_id or "").split("|")[0])
    chosen = next(iter(getattr(ctx.interaction, "values", ()) or ()), None)
    if chosen not in CATEGORY_BY_ID:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    return await _quantity_editor_view(
        ctx, account, inventory, chosen, mongo=mongo
    )


@register_action("cards_qpick", aliases=("cards_qjump",))
@lightbulb.di.with_di
async def cards_qpick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Point the shared controller at another card in the same category."""
    chosen = next(iter(getattr(ctx.interaction, "values", ()) or ()), None)
    return await _quantity_screen(
        ctx, action_id, coc_client=coc_client, mongo=mongo, card_id=chosen
    )


async def _quantity_write(
    ctx,
    tag: str,
    card_id: str,
    target: int,
    *,
    coc_client: coc.Client,
    mongo: MongoClient,
):
    """Write one card and redraw its category with that card still selected."""
    category_id = CARD_BY_ID[card_id].category
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
            guild_id=_trade_guild_id(ctx),
        )
    except ActiveCardTradeError:
        return await _quantity_editor_view(
            ctx, account, inventory, category_id, mongo=mongo, card_id=card_id,
            saved=f"{CARD_BY_ID[card_id].name} is in a trade and was not changed.",
        )
    except (InventoryWriteConflict, ValueError):
        current = await mongo.card_inventories.find_one({"_id": tag}) or inventory
        return await _quantity_editor_view(
            ctx, account, current, category_id, mongo=mongo, card_id=card_id,
            saved="The collection changed, so this screen was refreshed.",
        )
    return await _quantity_editor_view(
        ctx, account, updated, category_id, mongo=mongo, card_id=card_id,
        saved=_saved_count_line(CARD_BY_ID[card_id].name, target),
    )


@register_action("cards_qstep")
@lightbulb.di.with_di
async def cards_qstep(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, card_id, delta = _parse_quantity_card(action_id)
    if card_id is None:
        return _notice("Unknown card", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    current = normalize_cards(inventory.get("cards")).get(card_id, OWNED)
    if not isinstance(current, int) or isinstance(current, bool):
        current = OWNED
    return await _quantity_write(
        ctx, tag, card_id, current + delta,
        coc_client=coc_client, mongo=mongo,
    )


@register_action("cards_qset")
@lightbulb.di.with_di
async def cards_qset(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """One tap to answer the scanner's "2 or more" with exactly 2.

    An absolute write, so the member confirms the count without opening the
    Set number modal. Stays on the category screen like every other control
    there.
    """
    tag, card_id, target = _parse_card_set_target(action_id)
    if card_id is None or target is None:
        return _notice("Card unavailable", "Open `/cards` again.")
    return await _quantity_write(
        ctx, tag, card_id, int(target), coc_client=coc_client, mongo=mongo
    )


@register_action("cards_qnum", opens_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_qnum(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **_kwargs,
):
    """Type an exact count, rather than tapping +1 six times."""
    tag, card_id, _delta = _parse_quantity_card(action_id)
    if card_id is None:
        await ctx.respond(
            components=_notice("Card unavailable", "Open `/cards` again."),
            ephemeral=True,
        )
        return
    # The title is the card name alone. A modal title caps at 45 characters
    # and "How many <card> cards do you have?" overruns it for the longest
    # names, so the field below asks the question instead.
    await ctx.respond_with_modal(
        title=CARD_BY_ID[card_id].name[:45],
        custom_id=f"cards_qnum_submit:{tag}|{card_id}",
        components=[ModalActionRow().add_text_input(
            "copies",
            "How many do you have?",
            placeholder=f"0 to {MAX_COPIES}",
            required=True,
            max_length=2,
        )],
    )


@register_action("cards_qnum_submit", is_modal=True, no_return=True)
@lightbulb.di.with_di
async def cards_qnum_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    # ModalContext.defer can only DEFERRED_MESSAGE_CREATE, which answers the
    # modal with a brand-new message; in a DM that new panel piles up under
    # the old one forever. A modal opened from a component carries .message,
    # and hikari 2.4.1 allows DEFERRED_MESSAGE_UPDATE there, so the edit
    # below lands on the panel the modal came from instead.
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
        await ctx.defer(ephemeral=True)
    tag, card_id, _delta = _parse_quantity_card(action_id)
    if card_id is None:
        await ctx.interaction.edit_initial_response(
            components=_notice("Card unavailable", "Open `/cards` again.")
        )
        return
    try:
        target = int(str(_modal_text_value(ctx, "copies")).strip())
    except (TypeError, ValueError):
        account, inventory, problem = await _load_target(
            ctx, tag, coc_client=coc_client, mongo=mongo
        )
        view = problem or await _quantity_editor_view(
            ctx,
            account,
            inventory,
            CARD_BY_ID[card_id].category,
            mongo=mongo,
            card_id=card_id,
            saved="That was not a number, so nothing changed.",
        )
    else:
        view = await _quantity_write(
            ctx, tag, card_id, target, coc_client=coc_client, mongo=mongo
        )
    await ctx.interaction.edit_initial_response(components=view)


@register_action("cards_ready")
@lightbulb.di.with_di
async def cards_ready(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Safely refresh an old posted Ready button without granting trust."""
    tag, category_id, card_id = _parse_quantity_target(action_id)
    if category_id is None:
        return _notice("Unknown card category", "Re-run `/cards` to open a fresh panel.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    return await _quantity_editor_view(
        ctx,
        account,
        inventory,
        category_id,
        mongo=mongo,
        card_id=card_id,
        saved=(
            "Readiness is automatic. Enter a count for every card still marked "
            "as needing one."
        ),
    )


@register_action("cards_favours")
@lightbulb.di.with_di
async def cards_favours(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, page = _parse_trade_page(action_id)
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    try:
        candidates = await _candidate_inventories(
            mongo, inventory, guild_id=_trade_guild_id(ctx)
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    available = _without_reserved_cards(inventory)
    mine = normalize_cards(available.get("cards"))
    return _favours_view(
        account,
        find_matches(available, candidates),
        page=page,
        spares=sum(1 for value in mine.values() if value >= DUPLICATE),
    )


@register_action("cards_demand")
@lightbulb.di.with_di
async def cards_demand(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    tag, page = _parse_trade_page(action_id)
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    try:
        candidates = await _candidate_inventories(
            mongo, inventory, guild_id=_trade_guild_id(ctx)
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    return _demand_view(
        account,
        _without_reserved_cards(inventory),
        family_supply(candidates),
        page=page,
    )


def _gem_ask_confirm_view(account, card, holder_name: str, holder_tag: str):
    """Say the price before they commit, because gems are real money."""
    category = CATEGORY_BY_ID[card.category]
    cost = TRADE_GEM_COST.get(card.category, 0)
    return [Container(accent_color=GOLD_ACCENT, components=[
        Text(content=f"## {emojis.card_give} This will cost you {cost} gems"),
        Text(content=(
            f"You have no **{category.short_name}** spare to give back "
            f"for {_card_label(card)}."
        )),
        Separator(divider=True),
        Text(content=(
            f"**If {_escape_markdown(holder_name, limit=40)} agrees**\n"
            "They post the trade in game.\n"
            f"You tap Trade, then **Use Gems** — **{cost} gems** "
            f"{emojis.gems}."
        )),
        Separator(divider=False),
        Text(content=(
            "-# You keep every card you own. Nothing is reserved."
        )),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=(
                    f"cards_gem_send:{_normalize_tag(account.tag)}|"
                    f"{card.id}|{_normalize_tag(holder_tag)}"
                ),
                label=f"Yes, ask them ({cost} gems)",
                # A label is plain text, so the gem mark has to ride in the
                # emoji slot rather than as markup inside the words.
                emoji=GEMS_EMOJI,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_open_card:{_normalize_tag(account.tag)}",
                label="Cancel", emoji=CANCEL_EMOJI,
            ),
        ]),
    ])]


async def _gem_help_match(
    mongo: MongoClient,
    requester: dict,
    card_id: str,
    holder_tag: str,
    *,
    guild_id: int | None,
):
    """Revalidate one paid-help route through canonical matching snapshots.

    Gem-help buttons are long-lived Discord components.  Both clicks therefore
    rebuild normal matching eligibility instead of trusting the raw counts that
    were true when the holder list was rendered.  The matching boundary
    projects ``trusted_card_ids``, masks reservations, and confines candidates
    to the interaction's guild and the configured family clans.
    """
    if guild_id is None:
        return None
    candidates = await _candidate_inventories(
        mongo,
        requester,
        guild_id=int(guild_id),
        require_requester_family=True,
    )
    wanted_holder = _normalize_tag(holder_tag)
    for match in find_matches(_without_reserved_cards(requester), candidates):
        if _normalize_tag(match.holder_tag) != wanted_holder:
            continue
        exchange = next(
            (
                item
                for item in match.exchanges
                if card_id in item.offers and not item.returns
            ),
            None,
        )
        if exchange is not None and match.holder_discord_id is not None:
            return match
    return None


def _swap_leg_progress(trade: dict) -> dict:
    progress = trade.get("swap_leg_progress")
    return progress if isinstance(progress, dict) else {}


async def _claim_swap_leg(
    mongo: MongoClient,
    trade: dict,
    *,
    role: str,
    now: datetime,
) -> dict | None:
    """Fence one confirmation attempt before either inventory can change."""
    previous_status = str(trade.get("status") or "")
    if previous_status not in SWAP_LIVE_STATUSES:
        return None
    giver, receiver, card_id = _swap_leg(trade, role=role)
    nonce = secrets.token_hex(12)
    progress = {
        "attempt_nonce": nonce,
        "role": role,
        "card_id": card_id,
        "giver_tag": giver,
        "receiver_tag": receiver,
        "previous_status": previous_status,
        "phase": "inventory_update_started",
        "started_at": now,
    }
    query: dict[str, object] = {
        "_id": trade["_id"],
        "guild_id": int(trade["guild_id"]),
        "status": previous_status,
        f"{role}_confirmed_at": {"$exists": False},
    }
    if trade.get("reservation_token") is not None:
        query["reservation_token"] = trade.get("reservation_token")
    fields = {
        "status": "completing",
        "completion_kind": "swap_leg",
        "completion_started_at": now,
        "expires_at": now + TRADE_COMPLETION_FOR,
        "updated_at": now,
        "swap_leg_progress": progress,
    }
    try:
        result = await mongo.card_trades.update_one(query, {"$set": fields})
    except Exception:
        # An acknowledgement can be lost after Mongo committed the claim.
        # Continue only when our nonce is durably visible.
        current = await mongo.card_trades.find_one({"_id": trade["_id"]})
        if (
            current
            and current.get("status") == "completing"
            and _swap_leg_progress(current).get("attempt_nonce") == nonce
        ):
            return current
        raise
    if not getattr(result, "modified_count", 0):
        return None
    current = await mongo.card_trades.find_one({"_id": trade["_id"]})
    if current is not None:
        return current
    claimed = dict(trade)
    claimed.update(fields)
    return claimed


def _swap_leg_claim_query(trade: dict, *, role: str) -> dict[str, object]:
    progress = _swap_leg_progress(trade)
    return {
        "_id": trade["_id"],
        "status": "completing",
        "completion_kind": "swap_leg",
        "swap_leg_progress.attempt_nonce": progress.get("attempt_nonce"),
        "swap_leg_progress.role": role,
        "swap_leg_progress.card_id": progress.get("card_id"),
    }


async def _restore_swap_leg_claim(
    mongo: MongoClient,
    trade: dict,
    *,
    role: str,
    now: datetime,
) -> dict:
    """Release a no-spare interactive claim without recording confirmation."""
    progress = _swap_leg_progress(trade)
    previous_status = str(progress.get("previous_status") or "ready")
    result = await mongo.card_trades.update_one(
        _swap_leg_claim_query(trade, role=role),
        {
            "$set": {"status": previous_status, "updated_at": now},
            "$unset": {
                "completion_kind": "",
                "completion_started_at": "",
                "expires_at": "",
                "swap_leg_progress": "",
            },
        },
    )
    current = await mongo.card_trades.find_one({"_id": trade["_id"]})
    if getattr(result, "modified_count", 0):
        return current or dict(trade, status=previous_status)
    if current and current.get("status") == "needs_review":
        raise _SwapLegNeedsReview(current)
    if current and current.get(f"{role}_confirmed_at"):
        return current
    raise RuntimeError("swap leg claim could not be restored")


async def _mark_swap_leg_needs_review(
    mongo: MongoClient,
    trade: dict,
    *,
    role: str,
    now: datetime,
    phase: str,
    failure_type: str,
    giver_debited: bool | str,
    receiver_credit: str,
) -> dict:
    """Persist a partial/unknown leg, then invalidate trust before release."""
    progress = dict(_swap_leg_progress(trade))
    progress.update({
        "phase": phase,
        "giver_debited": giver_debited,
        "receiver_credit": receiver_credit,
        "failed_at": now,
        "failure_type": failure_type,
    })
    fields = {
        "status": "needs_review",
        "updated_at": now,
        "review_expires_at": now + TRADE_REVIEW_FOR,
        "failure": f"swap_leg_partial_failure:{failure_type}",
        "swap_leg_progress": progress,
        **_cleanup_fields(trade),
    }
    try:
        await mongo.card_trades.update_one(
            _swap_leg_claim_query(trade, role=role),
            {"$set": fields, "$unset": {"open_proposal_key": ""}},
        )
    except Exception:
        _log.exception(
            "swap leg review transition failed trade=%s role=%s",
            trade.get("_id"), role,
        )
    current = await mongo.card_trades.find_one({"_id": trade["_id"]})
    if current is None:
        current = dict(trade)
        current.update(fields)
    if current.get("status") == "needs_review":
        await _finish_trade_cleanup(
            mongo, current, owner=_reservation_owner(trade)
        )
        current = await mongo.card_trades.find_one({"_id": trade["_id"]}) or current
    return current


async def _run_swap_leg_confirmation(
    mongo: MongoClient,
    trade: dict,
    *,
    role: str,
    now: datetime,
    record_no_spare: bool,
) -> tuple[str, int, dict]:
    """Claim, apply, and audit one side without an untracked write window."""
    claimed = await _claim_swap_leg(mongo, trade, role=role, now=now)
    if claimed is None:
        current = await mongo.card_trades.find_one({"_id": trade["_id"]}) or trade
        return "changed", 0, current
    try:
        moved, remaining = await _confirm_swap_leg(
            mongo, claimed, role=role, now=now
        )
    except _SwapReceiverCreditError as exc:
        review = await _mark_swap_leg_needs_review(
            mongo,
            claimed,
            role=role,
            now=datetime.now(timezone.utc),
            phase="receiver_credit_unknown",
            failure_type=type(exc.__cause__ or exc).__name__,
            giver_debited=True,
            receiver_credit="unknown",
        )
        raise _SwapLegNeedsReview(review) from exc
    except Exception as exc:
        review = await _mark_swap_leg_needs_review(
            mongo,
            claimed,
            role=role,
            now=datetime.now(timezone.utc),
            phase="inventory_update_unknown",
            failure_type=type(exc).__name__,
            giver_debited="unknown",
            receiver_credit="not_started",
        )
        raise _SwapLegNeedsReview(review) from exc

    if not moved and not record_no_spare:
        try:
            restored = await _restore_swap_leg_claim(
                mongo, claimed, role=role, now=datetime.now(timezone.utc)
            )
        except _SwapLegNeedsReview:
            raise
        except Exception as exc:
            review = await _mark_swap_leg_needs_review(
                mongo,
                claimed,
                role=role,
                now=datetime.now(timezone.utc),
                phase="no_spare_restore_unknown",
                failure_type=type(exc).__name__,
                giver_debited=False,
                receiver_credit="not_started",
            )
            raise _SwapLegNeedsReview(review) from exc
        return "no_spare", remaining, restored

    updated = await _record_swap_confirmation(
        mongo, claimed, role=role, now=now
    )
    return ("moved" if moved else "no_spare_recorded"), remaining, updated


def _gem_ask_dm(ask: dict, *, preview: bool = False) -> list[Container]:
    """Asking somebody to post an offer. Deliberately not a trade record.

    No card is reserved and nothing moves in either collection, because the
    asker gives nothing up - they buy their side with gems. Modelling it as a
    trade would mean reserving a card that is never sent.
    """
    card = CARD_BY_ID[ask["card_id"]]
    category = CATEGORY_BY_ID[card.category]
    return _trade_dm_container(
        f"{emojis.card_give} Somebody needs your help",
        (
            f"**{_escape_markdown(ask.get('asker_name'), limit=40)}** is "
            f"missing {_card_label(card)}.\n"
            "You have a spare."
        ),
        extra=[
            Text(content=(
                f"They have no **{category.short_name}** spare to give "
                "back.\n"
                f"They pay **{ask.get('gem_cost')} gems** {emojis.gems} "
                "instead."
            )),
            Text(content=(
                "**If you say yes**\n"
                "Post the trade in game.\n"
                f"Offer your {_card_label(card)}. Ask for any "
                f"**{category.short_name}** card."
            )),
        ],
        accent=GOLD_ACCENT,
        controls=[ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=(
                    f"cards_gem_yes:{ask['_id']}|"
                    f"{int(ask.get('generation') or 0)}"
                ),
                label="Yes, I will post it",
                emoji=emojis.yes.partial_emoji,
                is_disabled=preview,
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                custom_id=(
                    f"cards_gem_no:{ask['_id']}|"
                    f"{int(ask.get('generation') or 0)}"
                ),
                label="No thanks", emoji=CANCEL_EMOJI,
                is_disabled=preview,
            ),
        ])],
        footer=(
            "Nothing changes in your collection until you trade in game."
        ),
    )


def _gem_answer_dm(ask: dict) -> list[Container]:
    """The asker's yes/no answer, one copy for every surface that sends it.

    Extracted verbatim from `_answer_gem_ask`'s old inline DM. The wording is
    derived from the ask's recorded status, so the DM and any future surface
    that shows the answer cannot drift apart.
    """
    agreed = str(ask.get("status") or "") == "accepted"
    card = CARD_BY_ID[ask["card_id"]]
    return _trade_dm_container(
        f"{emojis.yes} They said yes" if agreed
        else f"{emojis.no} They said no",
        (
            f"**{_escape_markdown(ask.get('holder_name'), limit=40)}** "
            f"will post the offer for {_card_label(card)} in game. "
            "Watch clan chat, tap **Trade**, then **Use Gems** — "
            f"**{ask.get('gem_cost')} gems** {emojis.gems}."
            if agreed else
            f"**{_escape_markdown(ask.get('holder_name'), limit=40)}** "
            f"cannot help with {_card_label(card)} right now. Open "
            "`/cards` and ask somebody else who holds it."
        ),
        accent=GREEN_ACCENT if agreed else RED_ACCENT,
    )


@register_action("cards_gem_ask")
@lightbulb.di.with_di
async def cards_gem_ask(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Confirm the gem cost before anything is sent."""
    # NOT _parse_target: that one only returns a second value when it is a
    # CATEGORY id, so "balloon|#TAG" came back as None and every Ask for help
    # answered "Out of date".
    parts = str(action_id or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    card = CARD_BY_ID.get(parts[1] if len(parts) > 1 else "")
    holder_tag = _normalize_tag(parts[2]) if len(parts) > 2 else ""
    if card is None or not holder_tag:
        return _notice("Out of date", "Open `/cards` again.", back_tag=tag)
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Not set up yet",
            "The Card Hub is not configured for this family yet.",
            back_tag=tag,
        )
    try:
        holder = await _gem_help_match(
            mongo, inventory, card.id, holder_tag, guild_id=guild_id
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    if holder is None:
        return _notice(
            "That help request is no longer available",
            "The missing card, spare, or family eligibility changed. Open "
            "**Find trades** again for the current options.",
            back_tag=tag,
        )
    return _gem_ask_confirm_view(
        account, card,
        holder.holder_name, holder.holder_tag,
    )


@register_action("cards_gem_send")
@lightbulb.di.with_di
async def cards_gem_send(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Send the ask. One per pair per card, so nobody can be spammed."""
    # NOT _parse_target: that one only returns a second value when it is a
    # CATEGORY id, so "balloon|#TAG" came back as None and every Ask for help
    # answered "Out of date".
    parts = str(action_id or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    card = CARD_BY_ID.get(parts[1] if len(parts) > 1 else "")
    holder_tag = _normalize_tag(parts[2]) if len(parts) > 2 else ""
    if card is None or not holder_tag:
        return _notice("Out of date", "Open `/cards` again.", back_tag=tag)
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Not set up yet",
            "The Card Hub is not configured for this family yet.",
            back_tag=tag,
        )
    try:
        holder = await _gem_help_match(
            mongo, inventory, card.id, holder_tag, guild_id=guild_id
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    if holder is None:
        return _notice(
            "That help request is no longer available",
            "Nothing was sent. The missing card, spare, or family eligibility "
            "changed. Open **Find trades** again for the current options.",
            back_tag=tag,
        )
    holder_discord_id = int(holder.holder_discord_id)
    holder_tag = _normalize_tag(holder.holder_tag)

    now = datetime.now(timezone.utc)
    ask = {
        "_id": f"gem:{_normalize_tag(account.tag)}:{holder_tag}:{card.id}",
        "kind": "gem_ask",         # the trade sweeper only looks at "trade"
        "guild_id": int(guild_id),
        "status": "pending",
        "card_id": card.id,
        "gem_cost": TRADE_GEM_COST.get(card.category, 0),
        "asker_tag": _normalize_tag(account.tag),
        "asker_name": account.name,
        "asker_discord_id": int(ctx.user.id),
        "holder_tag": holder_tag,
        "holder_name": holder.holder_name,
        "holder_discord_id": holder_discord_id,
        # Buttons carry this, so a DM from an earlier ask for the same card
        # cannot answer a later one.
        "generation": int(now.timestamp()),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await mongo.card_trades.insert_one(ask)
    except DuplicateKeyError:
        # One document per asker/holder/card. While it is pending, repeat
        # asks stay blocked; once it was answered, asking again takes the
        # document over as a fresh pending ask instead of blocking for ever.
        takeover = await mongo.card_trades.update_one(
            {"_id": ask["_id"], "kind": "gem_ask", "status": {"$ne": "pending"}},
            {
                "$set": {**{k: v for k, v in ask.items() if k != "_id"}},
                # The predecessor's channel post is settled history. Left in
                # place, its ids would ride along on this fresh ask - and if
                # the new post then failed, the eventual answer's edit would
                # rewrite the OLD terminal post, publicly flipping an
                # already-answered ask to a different answer.
                "$unset": {
                    "channel_id": "",
                    "channel_message_id": "",
                    "channel_post_v2": "",
                },
            },
        )
        if not getattr(takeover, "modified_count", 0):
            return _notice(
                "Already asked",
                f"You have already asked them for {card.name}. Give them a "
                "chance to answer before asking again.",
                back_tag=tag,
            )
    # Channel-first delivery: the ask posts publicly and pings the holder;
    # the old DM is only the fallback when that post fails (the policy row).
    async def _reap_if_undelivered(delivery: _Delivery) -> None:
        # No-orphan cleanup that tracks the REAL outcome. It runs inside the
        # delivery task, so a total failure that finishes after the 3-second
        # patience window below still deletes the ask - otherwise the doc
        # would sit pending forever, delivered nowhere, blocking every
        # repeat ask for this pair and card. Fenced on pending so a raced
        # answer can never be deleted.
        if (
            delivery.channel_message_id is None
            and holder_discord_id in delivery.dm_failed
        ):
            try:
                await mongo.card_trades.delete_one({
                    "_id": ask["_id"], "kind": "gem_ask", "status": "pending",
                })
            except Exception:
                _log.exception(
                    "undelivered gem ask cleanup failed ask=%s", ask["_id"]
                )

    delivery = await _deliver_soon(
        bot, mongo, ask, event="gem_ask_posted",
        on_complete=_reap_if_undelivered,
    )
    if (
        delivery is not None
        and delivery.channel_message_id is None
        and holder_discord_id in delivery.dm_failed
    ):
        # TOTAL failure within the window: neither the channel post nor the
        # fallback DM reached anyone. The reaper above already deleted the
        # ask (this delete is its idempotent twin for monkeypatched funnels);
        # keep the old no-orphan semantics and say so honestly. (The old
        # delete-on-DM-failure is gone: a DM failure alone no longer unwinds
        # an ask the channel already carries.)
        await mongo.card_trades.delete_one({"_id": ask["_id"]})
        return _notice(
            "Could not reach them",
            "The channel post and the fallback DM both failed, so nothing "
            "was asked. Ping them in the server, or try again later.",
            back_tag=tag,
        )
    holder_label = _escape_markdown(ask["holder_name"], limit=40)
    channel_id = _configured_cards_channel_id()
    if delivery is None:
        # Still in flight (the `_deliver_soon` timeout). The ask is saved and
        # the post still lands - not a failure, so no deletion and no alarm.
        asked_line = (
            f"I am posting the ask for **{holder_label}** in "
            f"<#{channel_id}> now."
        )
    elif delivery.channel_message_id is not None:
        asked_line = f"Posted in <#{channel_id}> and pinged **{holder_label}**."
    else:
        # The channel post failed but the fallback DM landed.
        asked_line = (
            f"I could not post in <#{channel_id}>, so I sent "
            f"**{holder_label}** a DM instead."
        )
    return [Container(accent_color=GREEN_ACCENT, components=[
        Text(content=f"## {emojis.yes} Asked"),
        Text(content=(
            f"**{holder_label}** has been asked for {_card_label(card)}. "
            f"{asked_line} I will DM you their answer.\n\n"
            "-# If they accept, watch clan chat: they post the offer and you "
            f"tap Trade, then **Use Gems** ({ask['gem_cost']})."
        )),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_dashboard:{_normalize_tag(account.tag)}",
            label="Back to collection", emoji=RETURN_EMOJI,
        )]),
    ])]


async def _answer_gem_ask(ctx, mongo, bot, action_id: str, *, agreed: bool):
    """Record the answer and tell the asker. No cards move either way."""
    ask_id, _, generation = str(action_id or "").partition("|")
    ask = await mongo.card_trades.find_one(
        {"_id": ask_id, "kind": "gem_ask"}
    )
    if ask is None:
        return _notice("Out of date", "That request is no longer open.")
    # Only the player who was asked can answer. The DM makes this the normal
    # case anyway, but the ask id is predictable, so it is checked, not
    # assumed - the same rule every trade handler applies.
    holder_id = ask.get("holder_discord_id")
    if not holder_id or int(holder_id) != int(ctx.user.id):
        return _notice(
            "That request is not yours",
            "Only the player who was asked can answer it.",
        )
    # A button from an earlier ask for the same card must not answer a newer
    # one. Old buttons without a generation still answer their own document.
    if generation and str(int(ask.get("generation") or 0)) != generation:
        return _notice("Out of date", "That request is no longer open.")
    # Compare-and-swap on pending: the first answer wins, and a stale or
    # double-clicked button cannot flip an answer that was already given.
    result = await mongo.card_trades.update_one(
        {"_id": ask["_id"], "kind": "gem_ask", "status": "pending"},
        {"$set": {
            "status": "accepted" if agreed else "declined",
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    if not getattr(result, "modified_count", 0):
        return _notice(
            "Already answered",
            "This request was already answered. Nothing changed.",
        )
    card = CARD_BY_ID[ask["card_id"]]
    category = CATEGORY_BY_ID[card.category]
    # The in-memory ask mirrors the CAS write above, so the delivery renders
    # the answered state: the standing post (when one exists) is silently
    # edited to its terminal form, and the asker gets the answer DM - exactly
    # as informative as before. No new channel post: the ping budget is
    # proposal + acceptance only, and a gem answer is neither.
    ask["status"] = "accepted" if agreed else "declined"
    delivery = await _deliver(bot, mongo, ask, event="gem_ask_answered")
    told = _delivery_note(delivery, recipient_id=ask.get("asker_discord_id"))
    if not agreed:
        return _notice(
            "Declined", f"Thanks for answering. {told}", accent=None
        )
    return [Container(accent_color=GREEN_ACCENT, components=[
        Text(content=f"## {emojis.yes} Thanks for helping"),
        Text(content=(
            f"Now post the offer in game: offer your {_card_label(card)} and "
            f"ask for any **{category.short_name}** card back. They pay the "
            f"gems.\n\n-# {told}\n"
            "-# You must be in the same clan for the trade itself."
        )),
    ])]


# cards_gem_yes / cards_gem_no stay registered FOREVER with their current
# semantics: fallback DMs already sent carry these ids, and editing the DM in
# place is right there - the same reasoning as cards_dm_accept. Aliasing onto
# the public pair is the wrong tool: the two need opposite no_return values
# and one Action cannot hold both. They route through the same rewired
# `_answer_gem_ask`, so an answer from an old DM also closes the public post.
@register_action("cards_gem_yes")
@lightbulb.di.with_di
async def cards_gem_yes(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _answer_gem_ask(ctx, mongo, bot, action_id, agreed=True)


@register_action("cards_gem_no")
@lightbulb.di.with_di
async def cards_gem_no(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _answer_gem_ask(ctx, mongo, bot, action_id, agreed=False)


@register_action("cards_admin")
@lightbulb.di.with_di
async def cards_admin(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Adoption numbers for whoever runs the family."""
    tag = _parse_target(str(action_id or ""))[0]
    # Re-checked here rather than trusted from the button: a custom_id is just
    # a string, and anyone who saw the panel could send this one back.
    if not _is_cards_admin(ctx, bot=bot):
        return _notice(
            "Admins only",
            "This panel is for server administrators.",
            back_tag=tag,
        )
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Not set up yet",
            "The Card Hub is not configured for this family yet.",
            back_tag=tag,
        )
    stats = await _admin_stats(mongo, guild_id=int(guild_id))
    return _admin_view(
        stats,
        names=_member_names(
            bot,
            [document.get("discord_id") for document in stats.get("stalled") or []],
            guild_id=int(guild_id),
        ),
        tag=tag,
    )


@register_action("cards_browse")
@lightbulb.di.with_di
async def cards_browse(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Everything one player has spare, looked up by their name."""
    values = list(getattr(ctx.interaction, "values", ()) or ())
    picked = str(values[0]) if values else ""
    lookup_value, separator, focus_value = picked.partition("|")
    focused_tag = None
    if separator:
        if "|" in focus_value or not focus_value.startswith("a:"):
            return _notice(
                "Unknown player", "Open `/cards` again for a fresh list."
            )
        focused_tag = _normalize_tag(focus_value[2:])
        if not focused_tag:
            return _notice(
                "Unknown player", "Open `/cards` again for a fresh list."
            )
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Not set up yet",
            "The Card Hub is not configured for this family yet.",
        )

    # The menu carries whichever key the inventory could be found by, so a
    # record written before discord_id existed is still reachable.
    query: dict = {"guild_id": int(guild_id), "trading_paused": {"$ne": True}}
    if lookup_value.startswith("d:"):
        try:
            discord_id = int(lookup_value[2:])
        except (TypeError, ValueError):
            return _notice(
                "Unknown player", "Open `/cards` again for a fresh list."
            )
        if discord_id <= 0:
            return _notice(
                "Unknown player", "Open `/cards` again for a fresh list."
            )
        query["discord_id"] = discord_id
    elif lookup_value.startswith("t:"):
        query["_id"] = _normalize_tag(lookup_value[2:])
    else:
        return _notice("Unknown player", "Open `/cards` again for a fresh list.")
    # The same family boundary matching applies. Without it an alt parked in a
    # clan outside the family would be listed, and nobody can trade with it.
    # Fail closed exactly like _candidate_inventories: a failed or empty clan
    # lookup refuses the search instead of quietly dropping the boundary.
    try:
        family_tags = [
            _normalize_tag(tag)
            for tag in await mongo.clans.distinct("tag")
            if _normalize_tag(tag)
        ]
    except Exception:
        _log.exception("player lookup could not load family clan tags")
        family_tags = []
    if not family_tags:
        return _notice(
            "Player lookup is not available right now",
            "Nothing was changed. Try again in a minute.",
            back_tag=_normalize_tag(account.tag),
        )
    query["clan_tag"] = {"$in": family_tags}
    documents = await mongo.card_inventories.find(query).to_list(length=25)
    if not documents:
        return _notice(
            "Nothing to show",
            "They have either turned trading off or removed their collection "
            "since this menu was drawn. Open **Find trades** again.",
        )

    safe_documents = [
        _without_reserved_cards(document) for document in documents
    ]
    if focused_tag and not any(
        _normalize_tag(document.get("_id")) == focused_tag
        for document in safe_documents
    ):
        return _notice(
            "Nothing to show",
            "That linked account is no longer available. Open **Find trades** "
            "again.",
        )

    discord_id = documents[0].get("discord_id")
    names = _member_names(bot, [discord_id], guild_id=guild_id)
    display = (
        names.get(int(discord_id)) if discord_id else None
    ) or str(documents[0].get("player_name") or "That player")
    return _player_spares_view(
        _normalize_tag(account.tag),
        _without_reserved_cards(inventory),
        # Reserved cards are masked here too: a card promised to an accepted
        # trade is not something a third player can ask for.
        safe_documents,
        display_name=display,
        lookup_value=lookup_value,
        focused_tag=focused_tag,
    )


@register_action("cards_matches")
@lightbulb.di.with_di
async def cards_matches(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    guild_id = _trade_guild_id(ctx)
    if guild_id is not None:
        # A cancel whose cleanup failed leaves the cards fenced, and a fenced
        # card is masked out of matching - so the swap silently vanishes on
        # exactly this screen. Draining the queue here means the screen where
        # the damage shows is also the screen that repairs it; before, only
        # My trades and a restart did.
        await _reconcile_trade_cleanups(mongo, guild_id=int(guild_id))
        await _recover_stalled_reservations(
            mongo, now=datetime.now(timezone.utc), guild_id=int(guild_id)
        )
        inventory = await mongo.card_inventories.find_one({
            "_id": _normalize_tag(account.tag), "guild_id": int(guild_id),
        }) or inventory
    try:
        candidates = await _candidate_inventories(
            mongo, inventory, guild_id=guild_id
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    available = _without_reserved_cards(inventory)
    matches = find_matches(available, candidates)
    return _matches_view(
        account,
        available,
        matches,
        browse=_browse_picker(
            _normalize_tag(account.tag),
            candidates,
            names=_member_names(
                bot,
                [document.get("discord_id") for document in candidates],
                guild_id=guild_id,
            ),
            clan_tag=_normalize_tag(inventory.get("clan_tag")),
        ),
        supply=family_supply(candidates),
        # Counted off the unmasked inventory: `available` has already had the
        # reserved cards rewritten, so it cannot report on them.
        reserved=len(_card_reservations(inventory)),
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
    if values and values[0] == CATEGORY_HEADER_VALUE:
        # Same header option that carries the category art; picking it is a
        # no-op rather than an error.
        return None
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
    try:
        candidates = await _candidate_inventories(
            mongo, inventory, guild_id=_trade_guild_id(ctx)
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    holders = holders_for_card(
        _without_reserved_cards(inventory), candidates, card_id
    )
    return _holders_view(
        account, card_id, holders,
        clan_emoji=await _clan_emoji_map(mongo, holders),
        can_request=bool(_open_request_offer_ids(inventory, card)),
    )


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
    try:
        candidates = await _candidate_inventories(
            mongo, inventory, guild_id=_trade_guild_id(ctx)
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    holders = holders_for_card(
        _without_reserved_cards(inventory), candidates, card_id
    )
    return _holders_view(
        account, card_id, holders, page=page,
        clan_emoji=await _clan_emoji_map(mongo, holders),
        can_request=bool(_open_request_offer_ids(inventory, card)),
    )


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
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Card Hub is not set up",
            "An operator must configure the family server before trades work.",
        )
    trades = await _active_trades(
        mongo, tag=account.tag, guild_id=guild_id, bot=bot
    )
    open_requests = await _open_requests_for(
        mongo, tag=account.tag, guild_id=guild_id
    )
    return _trades_view(
        account, trades, page=page, open_requests=open_requests
    )


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
    try:
        candidates = await _candidate_inventories(
            mongo, requester, guild_id=_trade_guild_id(ctx)
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
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
            "Go back and open the card search again, then choose another "
            "player.",
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
    parts = str(action_id or "").split("|")
    requester_tag, wanted_card_id = _parse_trade_request_target(
        "|".join(parts[:2])
    )
    values = list(getattr(ctx.interaction, "values", ()) or ())
    if values:
        holder_tag, given_card_id = _parse_trade_option(values[0])
    else:
        # When only one card qualifies there is nothing to choose, so the offer
        # sends straight from a button and the pair a select would have carried
        # rides in the custom_id instead. Same shape as the Ask button above.
        holder_tag = _normalize_tag(parts[2]) if len(parts) > 2 else ""
        given_card_id = parts[3] if len(parts) > 3 else ""
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
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Card Hub is not set up",
            "An operator must configure the family server before trades work.",
        )
    try:
        candidates = await _candidate_inventories(
            mongo, requester, guild_id=guild_id
        )
    except CandidateLookupUnavailable:
        return _search_unavailable_notice(account.tag)
    holder = next(
        (item for item in candidates if _normalize_tag(item.get("_id")) == holder_tag),
        None,
    )
    if holder is None:
        return _notice(
            "That match is no longer available",
            "Go back and open the holder list again.",
        )
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
    # One funnel decides who hears and how; the handler only reports back.
    # `_deliver_soon` because this is an interactive handler: a rate-limited
    # channel post must not hang the interaction.
    delivery = await _deliver_soon(bot, mongo, trade, event="proposal_created")
    # Lead with where it went. "Proposal posted" left people asking where,
    # because the delivery was the last clause of a sentence about reserving.
    holder_name = _escape_markdown(trade.get("holder_name"), limit=40)
    holder_id = int(trade["holder_discord_id"])
    channel_id = trade.get("channel_id") or _configured_cards_channel_id()
    board = f"<#{channel_id}>" if channel_id else "the trade channel"
    if delivery is not None and delivery.channel_message_id is not None:
        landed = f"Posted in {board} and pinged **{holder_name}**."
        if holder_id in delivery.dm_sent:
            landed += " They also got a DM copy."
    elif delivery is None:
        # Still posting (slow Discord); the task keeps running to completion.
        landed = (
            f"Posting it now in {board} — **{holder_name}** gets pinged "
            "there."
        )
    elif holder_id in delivery.dm_sent:
        landed = (
            f"The channel post failed, but **{holder_name}** got a DM with "
            "your offer. They can accept or decline right there."
        )
    else:
        landed = (
            f"I could not reach <@{holder_id}>. Ping them so they open "
            "`/cards` and check **My trades**."
        )
    return _trade_feedback(
        "Offer sent",
        f"{landed}\n\n"
        f"**You give:** {_card_label(given)}\n"
        f"**You get:** {_card_label(wanted)}\n\n"
        f"-# Nothing is reserved yet. Your {given.name} stays available to "
        "everyone else until they accept, so you can still trade it "
        "elsewhere.\n"
        "-# Changed your mind? Open **My trades** and cancel it.",
        account.tag,
    )


def _open_request_confirm_view(account, card, offer_ids: list[str]) -> list[Container]:
    """Consent before publication: what goes public, where, for how long."""
    tag = _normalize_tag(account.tag)
    channel_id = _configured_cards_channel_id()
    where = f"<#{channel_id}>" if channel_id else "the family trade channel"
    hours = int(OPEN_REQUEST_FOR.total_seconds() // 3600)
    return [Container(accent_color=GOLD_ACCENT, components=[
        Text(content=f"## 🃏 Post a request for {card.name}?"),
        Text(content=(
            f"**You get:** {_card_label(card)}\n"
            "**You give back one of:** "
            # The FULL give-back list: whoever answers picks from it, so the
            # member must see everything they are putting on the table.
            f"{_card_names(offer_ids, limit=max(len(offer_ids), 1))}\n"
            "-# Whoever answers picks which one they take."
        )),
        Separator(divider=True),
        Text(content=(
            f"This will be posted in {where} **for everyone to see**, with "
            "your player name, tag and clan on it. Nobody is pinged. It "
            f"closes on its own after **{hours} hours**, and you can close "
            "it any time in **My trades**."
        )),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"cards_req_post:{tag}|{card.id}",
                label="Post it",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_matches:{tag}",
                label="Cancel",
                emoji=CANCEL_EMOJI,
            ),
        ]),
    ])]


def _open_request_picker_view(account, card_ids: list[str]) -> list[Container]:
    """One menu per category of requestable cards, the four-menu shape.

    Same construction as `_category_card_pickers`: every category fits one
    25-option select, so there is no paging to build or maintain.
    """
    tag = _normalize_tag(account.tag)
    rows: list = []
    for category in CATEGORIES:
        in_category = [
            card_id for card_id in card_ids
            if CARD_BY_ID[card_id].category == category.id
        ]
        if not in_category:
            continue
        options = [
            SelectOption(
                label=CARD_BY_ID[card_id].name,
                value=card_id,
                description="you hold a spare to give back",
                emoji=troop_emoji.partial(card_id),
            )
            for card_id in in_category[:24]
        ]
        detail = f"{len(options)} to request"
        rows.append(ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_req_new:{tag}|{category.id}",
            placeholder=f"{category.name} · {detail}"[:150],
            max_values=1,
            options=[_category_header_option(category, detail), *options],
        )]))
    return [_panel(GOLD_ACCENT, [
        Text(content="# 🃏 Post a request"),
        Text(content=(
            "Pick the card you need. It goes on the family trade board as "
            "an open request anyone with a spare can answer.\n"
            "-# Only cards from finished categories where you hold a spare "
            "to give back are listed."
        )),
        Separator(divider=True),
        *rows,
        Separator(divider=True),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_matches:{tag}",
            label="Back to Find trades",
            emoji=RETURN_EMOJI,
        )]),
    ])]


@register_action("cards_req_pick")
@lightbulb.di.with_di
async def cards_req_pick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Choose which missing card to put on the family board."""
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    requestable = _requestable_card_ids(inventory)
    if not requestable:
        return _notice(
            "Nothing to request right now",
            "An open request needs a card you are missing in a finished "
            "category where you also hold a spare to give back. Use **Ask "
            "for help** from a card's holder list instead.",
            back_tag=_normalize_tag(account.tag),
        )
    return _open_request_picker_view(account, requestable)


@register_action("cards_req_new")
@lightbulb.di.with_di
async def cards_req_new(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """The confirm screen for one want-ad, before anything goes public.

    Reached two ways, like `cards_open_card`: a button carries
    `{tag}|{card_id}`, a picker select carries `{tag}|{category_id}` with the
    card riding in the interaction values.
    """
    parts = str(action_id or "").split("|")
    tag = _normalize_tag(parts[0] if parts else "")
    second = parts[1] if len(parts) > 1 else ""
    values = list(getattr(ctx.interaction, "values", ()) or ())
    if values and values[0] == CATEGORY_HEADER_VALUE:
        # The art-bearing header option; picking it is a no-op, not an error.
        return None
    if second in CARD_BY_ID:
        card_id = second
    else:
        card_id = str(values[0]) if values else ""
        picked = CARD_BY_ID.get(card_id)
        if picked is not None and second and picked.category != second:
            # A pick that does not belong to the menu it came from.
            return _notice(
                "Unknown card", "Open `/cards` again for a fresh list."
            )
    card = CARD_BY_ID.get(card_id)
    if not tag or card is None:
        return _notice("Unknown card", "Open `/cards` again for a fresh list.")
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    if not inventory_is_matchable(inventory):
        return _stale_collection_notice()
    offer_ids = _open_request_offer_ids(inventory, card)
    if not offer_ids:
        # The refusal names the working alternative: without a spare the game
        # only lets the trade start from the holder's side, which is the gem
        # Ask for help flow.
        return _notice(
            "No spare to give back",
            f"You have no spare "
            f"**{CATEGORY_BY_ID[card.category].short_name}** card, so the "
            "game will not let this trade start from your side. Use **Ask "
            "for help** next to a holder instead.",
            back_tag=_normalize_tag(account.tag),
        )
    return _open_request_confirm_view(account, card, offer_ids)


@register_action("cards_req_post")
@lightbulb.di.with_di
async def cards_req_post(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Create the open request and post the want-ad, after the confirm."""
    tag_part, _, card_id = str(action_id or "").partition("|")
    card = CARD_BY_ID.get(card_id)
    if not _normalize_tag(tag_part) or card is None:
        return _notice(
            "Unknown request", "Open `/cards` again and start over."
        )
    account, inventory, problem = await _load_target(
        ctx, tag_part, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    guild_id = _trade_guild_id(ctx)
    if guild_id is None:
        return _notice(
            "Card Hub is not set up",
            "An operator must configure the family server before trades work.",
        )
    request, error = await _create_open_request(
        mongo,
        requester_inventory=inventory,
        wanted_card_id=card.id,
        guild_id=guild_id,
    )
    if error:
        return _notice("Could not post this request", error)
    # One funnel decides delivery; `_deliver_soon` because this is an
    # interactive handler and a rate-limited post must not hang it.
    delivery = await _deliver_soon(
        bot, mongo, request, event="open_request_posted"
    )
    channel_id = request.get("channel_id") or _configured_cards_channel_id()
    board = f"<#{channel_id}>" if channel_id else "the trade channel"
    if delivery is not None and delivery.channel_message_id is not None:
        landed = (
            f"Posted in {board}. Nobody is pinged — anyone with a spare "
            f"**{card.name}** can tap **I have this card** there."
        )
    elif delivery is None:
        # Still posting (slow Discord); the task runs to completion.
        landed = f"Posting it now in {board}."
    else:
        landed = (
            "The channel post failed, but the request is saved — it still "
            "counts against your open requests and can be closed in "
            "**My trades**."
        )
    return _trade_feedback(
        "Request posted",
        f"{landed}\n\n"
        f"**You get:** {_card_label(card)}\n"
        "**You give back:** one of "
        f"{_card_names(request['offer_card_ids'], limit=8)}\n\n"
        "-# Nothing is reserved. It closes on its own in "
        f"**{int(OPEN_REQUEST_FOR.total_seconds() // 3600)} hours**, or any "
        "time from **My trades**.",
        account.tag,
    )


@register_action("cards_req_close")
@lightbulb.di.with_di
async def cards_req_close(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Close the member's own want-ad: owner-only, CAS on status:"open"."""
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    request = await mongo.card_trades.find_one({
        "_id": str(action_id or ""),
        "kind": "open_request",
        "guild_id": _trade_guild_id(ctx),
    })
    if not request:
        return _notice("Request not found", "Reopen **My trades**.")
    if int(ctx.user.id) != int(request.get("requester_discord_id") or -1):
        return _notice(
            "That request is not yours",
            "Only the member who posted a request can close it.",
        )
    now = datetime.now(timezone.utc)
    # CAS fenced on status:"open": a claim that lands first wins and this
    # close reports "already closed" instead of clobbering it. The claim
    # fields are deliberately left untouched.
    result = await mongo.card_trades.update_one(
        {"_id": request["_id"], "kind": "open_request", "status": "open"},
        {
            "$set": {
                "status": "cancelled",
                "cancelled_at": now,
                "cancelled_by": int(ctx.user.id),
                "updated_at": now,
            },
            "$unset": {"open_request_key": ""},
        },
    )
    if not getattr(result, "modified_count", 0):
        return _notice(
            "Request already closed",
            # "or being claimed": a claim in flight also holds the fence,
            # and it may yet roll back to open - so this cannot promise the
            # request is gone, only that this tap changed nothing.
            "It was already claimed, closed or expired - or somebody is "
            "accepting it right now. Reopen **My trades** for the latest "
            "state.",
        )
    request["status"] = "cancelled"
    # Flip the public post to its compact closed form. The `_deliver_soon`
    # patience pattern, because a rate-limited edit must not hang the
    # interaction; `asyncio.wait` does not cancel, so a slow edit still lands.
    task = asyncio.create_task(_channel_edit(
        bot,
        channel_id=request.get("channel_id") or _configured_cards_channel_id(),
        message_id=request.get("channel_message_id"),
        components=_open_request_post(request),
        key=request.get("_id"),
    ))
    _DELIVERY_TASKS.add(task)
    task.add_done_callback(_DELIVERY_TASKS.discard)
    await asyncio.wait({task}, timeout=3.0)
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    return _trade_feedback(
        "Request closed",
        f"Your open request for **{card.name if card else 'that card'}** is "
        "closed and nothing was traded. The channel post now shows it as "
        "closed.",
        request.get("requester_tag") or "",
        accent=None,
    )


async def _eligible_claim_accounts(
    ctx, request: dict, *, coc_client, mongo: MongoClient
) -> tuple[list[tuple[object, dict]], list[str]]:
    """Which of the clicker's linked accounts can fill this want-ad.

    Returns (eligible, reasons): eligible as (account, inventory) pairs, and
    one line per rejected account naming its best failure - no collection
    here, trading paused, needs an update, category unfinished, no spare.
    A bare "you can't" is what makes people think the bot is broken, so a
    refusal built from `reasons` always says why.
    """
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    category = CATEGORY_BY_ID.get(str(request.get("category")))
    data = await load_accounts(coc_client, int(ctx.user.id))
    if data.problem == LINK_FAILURE:
        return [], [
            "I could not check which Clash accounts are linked to you, so "
            "nothing was claimed. This is a service problem, not an unlink "
            "- try again shortly."
        ]
    eligible: list[tuple[object, dict]] = []
    reasons: list[str] = []
    for entry in _loaded_entries(data):
        tag = _normalize_tag(entry.tag)
        label = (
            f"**{_escape_markdown(entry.account.name, limit=40)}** (`{tag}`)"
        )
        try:
            inventory = await mongo.card_inventories.find_one({
                "_id": tag, "guild_id": int(request["guild_id"]),
            })
        except Exception:
            _log.exception("claim eligibility lookup failed tag=%s", tag)
            inventory = None
        if inventory is None:
            reasons.append(
                f"{label} has no card collection in this family yet - open "
                "`/cards` to set one up."
            )
            continue
        if inventory.get("trading_paused"):
            reasons.append(
                f"{label} has trading paused - turn it back on in `/cards`."
            )
            continue
        if not inventory_is_matchable(inventory):
            reasons.append(
                f"{label} needs a collection update first - open "
                "**Update collection** in `/cards`."
            )
            continue
        complete = {str(v) for v in inventory.get("complete_categories") or ()}
        if str(request.get("category")) not in complete:
            reasons.append(
                f"{label} has not finished entering the "
                f"**{category.short_name if category else 'card'}** "
                "category yet."
            )
            continue
        values = normalize_cards(
            _without_reserved_cards(inventory).get("cards")
        )
        if values.get(str(request.get("wanted_card_id")), OWNED) < DUPLICATE:
            reasons.append(
                f"{label} has no spare "
                f"**{card.name if card else 'copy of that card'}** to give."
            )
            continue
        eligible.append((entry.account, inventory))
    if not eligible and not reasons:
        reasons.append(
            "None of your Clash accounts are linked here. Link one with "
            "ClashKing's `/link` command, then open `/cards` to set up its "
            "collection."
        )
    return eligible, reasons


def _claim_account_picker(request: dict, eligible: list) -> list[Container]:
    """Which account claims: one Section per eligible account, each with its
    own SUCCESS button - the house rule that a row of things is Sections,
    not a select (docs/clash-of-cards.md, "Screen construction rules").

    This picker is an EPHEMERAL followup, and its buttons keep the frozen
    public pattern: cards_pub_claim_as is registered no_return=True too and
    answers with a fresh followup of its own - a component click on a
    followup is an ordinary interaction, and the dispatcher must never edit
    the public post on its behalf.
    """
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    card_name = card.name if card else "this card"
    request_id = str(request.get("_id") or "")
    generation = int(request.get("generation") or 0)
    rows: list = []
    # Eight Sections stay far under the 40-component ceiling. A member with
    # more eligible accounts than that can still claim - with the first
    # eight in the account list's own order.
    for account, _inventory in eligible[:8]:
        if rows:
            rows.append(Separator(divider=True))
        town_hall = getattr(account, "town_hall", None)
        detail = " · ".join(part for part in (
            f"TH{town_hall}" if town_hall else "",
            str(getattr(account, "clan_name", "") or ""),
        ) if part)
        first = (
            str(getattr(account, "name", "") or "").strip().split()
            or ["this one"]
        )[0]
        rows.append(Section(
            components=[Text(content=(
                f"**{_escape_markdown(account.name, limit=40)}** · "
                f"`{_normalize_tag(account.tag)}`"
                + (f"\n-# {_plain(detail)}" if detail else "")
            ))],
            accessory=Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=(
                    f"cards_pub_claim_as:{request_id}|{generation}|"
                    f"{_normalize_tag(account.tag)}"
                ),
                label=f"Claim · {first}"[:80],
            ),
        ))
    return [_panel(GOLD_ACCENT, [
        Text(content=f"## Which account claims {card_name}?"),
        Text(content=(
            "More than one of your accounts holds a spare "
            f"**{card_name}**. The one you pick gives that spare and takes "
            "one of the poster's duplicates back."
        )),
        Separator(divider=True),
        *rows,
    ])]


def _claim_take_picker(
    request: dict, takeable: list[str], *, tag: str
) -> list[Container]:
    """Which of the poster's spares the claimer takes back.

    A select, not Sections: a choice among known cards where the name is
    enough to choose by (the house select rule). The values are card ids;
    the custom_id carries request, generation and the claiming account so
    the handler re-runs the whole shared body with the answer. Like the
    account picker, this lives on an ephemeral followup and its handler
    (cards_pub_take) is no_return=True, answering with a fresh followup.
    """
    card = CARD_BY_ID.get(str(request.get("wanted_card_id")))
    poster = _escape_markdown(request.get("requester_name"), limit=40)
    return [_panel(GOLD_ACCENT, [
        Text(content="## Pick the card you take back"),
        Text(content=(
            f"You give your spare **{card.name if card else 'card'}** to "
            f"**{poster}** and take one of their duplicates. Every card "
            "listed is one you are missing."
        )),
        Separator(divider=True),
        ActionRow(components=[TextSelectMenu(
            custom_id=(
                f"cards_pub_take:{request.get('_id')}|"
                f"{int(request.get('generation') or 0)}|{_normalize_tag(tag)}"
            ),
            placeholder="Pick the card you take",
            min_values=1,
            max_values=1,
            options=[
                SelectOption(
                    label=CARD_BY_ID[card_id].name,
                    value=card_id,
                    emoji=troop_emoji.partial(card_id),
                )
                for card_id in takeable[:25]
            ],
        )]),
    ])]


async def _rollback_open_request_claim(
    mongo: MongoClient, request: dict, *, claim_token: str
) -> None:
    """Return a half-claimed want-ad to the board.

    Fenced on OUR claim_token, so only our own claim is ever undone - a
    claim the sweeper already recovered, or somebody else's newer one, does
    not match the filter. `open_request_key` was never unset during
    claiming, so the one-request-per-card guard survives the round trip
    untouched and the public post needs no edit: the want-ad simply stays
    up. If this write itself fails, the request sits in "claiming" with its
    claim_until deadline and the stale-claiming recovery sweeper returns it
    to "open" on that same fence.
    """
    now = datetime.now(timezone.utc)
    try:
        await mongo.card_trades.update_one(
            {
                "_id": request["_id"],
                "kind": "open_request",
                "status": "claiming",
                "claim_token": claim_token,
            },
            {
                "$set": {"status": "open", "updated_at": now},
                "$unset": {
                    "claim_token": "",
                    "claim_until": "",
                    "claimed_by_discord_id": "",
                    "claimed_by_tag": "",
                    "claimed_at": "",
                },
            },
        )
    except Exception:
        _log.exception(
            "open request claim rollback failed request=%s",
            request.get("_id"),
        )


async def _perform_open_request_claim(
    ctx,
    *,
    request_id: str,
    generation: str,
    claim_tag: str | None = None,
    taken_card_id: str | None = None,
    coc_client,
    mongo: MongoClient,
    bot,
) -> list[Container]:
    """The whole claim, shared by all three cards_pub_claim* adapters.

    The screens - the account picker and the take chooser - are resolved
    BEFORE the claiming CAS, so an open picker never holds the lock. The
    CAS is the single-winner gate; everything after it either finishes the
    claim or rolls it back on our own claim_token. Refusals here are plain
    return values: the adapters send them through `_public_reply`, so a
    wrong-member, stale or raced tap never alters the public post.
    """
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    request = await mongo.card_trades.find_one({
        "_id": str(request_id or ""),
        "kind": "open_request",
        "guild_id": _trade_guild_id(ctx),
    })
    if request is None:
        return _notice("Out of date", "That request is no longer open.")
    request_status = str(request.get("status") or "")
    if request_status in {"claiming", "claimed"}:
        return _notice(
            "Request already claimed",
            "Somebody got there first. Watch the board for the next one.",
        )
    if request_status != "open":
        return _notice("Out of date", "That request is no longer open.")
    # A button from a reused or stale post carries an old generation and is
    # refused instead of acted on - the gem-ask staleness pattern.
    if str(int(request.get("generation") or 0)) != str(generation or ""):
        return _notice("Out of date", "That request is no longer open.")
    if int(request.get("requester_discord_id") or -1) == int(ctx.user.id):
        return _notice(
            "That is your own request",
            "Close it in **My trades** if you no longer need the card.",
        )
    eligible, reasons = await _eligible_claim_accounts(
        ctx, request, coc_client=coc_client, mongo=mongo
    )
    if claim_tag:
        # A picker button carries the tag; re-verify it still belongs to the
        # clicker AND still qualifies - eligibility is recomputed above from
        # the clicker's own links, so a forged or stale tag simply misses.
        wanted_tag = _normalize_tag(claim_tag)
        chosen = next(
            (
                pair for pair in eligible
                if _normalize_tag(pair[1].get("_id")) == wanted_tag
            ),
            None,
        )
        if chosen is None:
            # The backticked form, so `#CL` can never match a `#CL2` line.
            named = [line for line in reasons if f"`{wanted_tag}`" in line]
            return _notice(
                "That account can no longer claim this",
                "\n".join(named) or (
                    "It is not one of your linked accounts any more, or it "
                    "stopped qualifying. Tap **I have this card** on the "
                    "request again."
                ),
            )
        _account, claimer = chosen
    elif not eligible:
        return _notice("You cannot fill this request", "\n".join(reasons))
    elif len(eligible) > 1:
        return _claim_account_picker(request, eligible)
    else:
        _account, claimer = eligible[0]
    claimer_tag = _normalize_tag(claimer.get("_id"))
    poster = await mongo.card_inventories.find_one({
        "_id": _normalize_tag(request["requester_tag"]),
        "guild_id": int(request["guild_id"]),
    })
    if poster is None:
        return _notice(
            "Poster collection unavailable",
            "Their collection could not be loaded, so nothing was claimed. "
            "Try again in a moment.",
        )
    # What the claimer may take: still consented to (it is on the ad), still
    # actually spare for the poster, and missing from the claimer's own
    # collection - offer_card_ids was computed at posting time and can be
    # stale by now.
    poster_values = normalize_cards(
        _without_reserved_cards(poster).get("cards")
    )
    claimer_values = normalize_cards(
        _without_reserved_cards(claimer).get("cards")
    )
    takeable = [
        str(card_id)
        for card_id in request.get("offer_card_ids") or ()
        if str(card_id) in CARD_BY_ID
        and poster_values.get(str(card_id), OWNED) >= DUPLICATE
        and claimer_values.get(str(card_id), OWNED) == MISSING
    ]
    if not takeable:
        return _notice(
            "Nothing to take back",
            "Their spares changed; nothing to take. The give-back list no "
            "longer holds a card that is both still spare for them and "
            "missing for you.",
        )
    if taken_card_id is not None:
        taken = str(taken_card_id)
        if taken not in takeable:
            return _notice(
                "That card is no longer available",
                "Their spares changed. Tap **I have this card** on the "
                "request again for the current list.",
            )
    elif len(takeable) > 1:
        return _claim_take_picker(request, takeable, tag=claimer_tag)
    else:
        taken = takeable[0]

    # FIRST-COME-FIRST-SERVED. The one CAS every concurrent claimer races:
    # fenced on (status:"open", generation) so exactly one tap can move the
    # request to "claiming" - and it runs only now, with every picker
    # resolved, so a picker screen never holds the lock. claim_until is
    # written here so the stale-"claiming" recovery sweeper can fence on it.
    now = datetime.now(timezone.utc)
    claim_token = secrets.token_hex(8)
    won = await mongo.card_trades.update_one(
        {
            "_id": request["_id"],
            "kind": "open_request",
            "status": "open",
            "generation": int(request.get("generation") or 0),
        },
        {"$set": {
            "status": "claiming",
            "claim_token": claim_token,
            "claim_until": now + OPEN_REQUEST_CLAIM_FOR,
            "claimed_by_discord_id": int(ctx.user.id),
            "claimed_by_tag": claimer_tag,
            "updated_at": now,
        }},
    )
    if not getattr(won, "modified_count", 0):
        return _notice(
            "Somebody else just took this one",
            "Two of you tapped at nearly the same time and they were first. "
            "Watch the board for the next request.",
        )
    live_clans = await _live_family_clans(
        mongo, coc_client, request["requester_tag"], claimer_tag
    )
    if live_clans is None:
        await _rollback_open_request_claim(
            mongo, request, claim_token=claim_token
        )
        return _notice(
            "Both accounts must be in family clans",
            "I could not verify both accounts inside the configured clan "
            "family, so nothing was claimed - the request stays open. Try "
            "again once you are back in a family clan.",
        )
    # Convert to an ordinary kind:"trade". The role mapping is fixed: the
    # poster is the requester (they want the card and give one back), the
    # claimer is the holder. Dict-copies with the LIVE clan tags, exactly
    # like cards_trade_request, so the trade records where both accounts
    # actually are.
    poster = dict(poster)
    claimer_doc = dict(claimer)
    poster["clan_tag"], claimer_doc["clan_tag"] = live_clans
    trade, error = await _create_trade_request(
        mongo,
        requester=poster,
        holder=claimer_doc,
        wanted_card_id=str(request["wanted_card_id"]),
        given_card_id=taken,
        guild_id=int(request["guild_id"]),
    )
    if trade is None:
        # Slots exhausted, a duplicate proposal, reciprocity now failing -
        # whatever it was, the claim is undone on our token and the want-ad
        # survives untouched. Nothing is lost.
        await _rollback_open_request_claim(
            mongo, request, claim_token=claim_token
        )
        return _notice(
            "Could not start this trade",
            error or "Please try again in a moment.",
        )
    # One tap means accepted: run the same fenced reservation the holder's
    # Accept runs. A non-accepted outcome is FINE - the trade stays pending
    # and degrades into an ordinary proposal the claimer can accept from
    # My trades once the conflict clears. Never roll the trade back.
    outcome, status = await _accept_trade_reservation(
        mongo,
        trade,
        user_id=int(ctx.user.id),
        live_clans=live_clans,
        now=now,
        chosen_card_id=taken,
    )
    finalized = await mongo.card_trades.update_one(
        {
            "_id": request["_id"],
            "kind": "open_request",
            "status": "claiming",
            "claim_token": claim_token,
        },
        {
            "$set": {
                "status": "claimed",
                "claimed_at": now,
                "trade_id": trade["_id"],
                "updated_at": now,
            },
            "$unset": {
                "open_request_key": "",
                "claim_token": "",
                "claim_until": "",
            },
        },
    )
    finalize_won = bool(getattr(finalized, "modified_count", 0))
    if not finalize_won:
        # The recovery sweeper reclaimed our stale "claiming" mid-flight.
        # The trade is real either way; only the want-ad bookkeeping moved,
        # and whoever holds the fence now owns it.
        _log.warning(
            "open request finalize lost its fence request=%s trade=%s",
            request.get("_id"), trade.get("_id"),
        )
    refreshed = await mongo.card_trades.find_one(
        {"_id": trade["_id"], "kind": "trade"}
    ) or dict(trade)
    if outcome == "accepted":
        refreshed["status"] = status
    # REUSE the want-ad's message as the trade's standing post: the policy
    # row's edit refreshes it into `_trade_post(trade)`, and the reply-note
    # underneath pings the poster. When the reservation stayed pending that
    # edit renders the pending post with its normal Accept/Decline controls
    # - correct: the claimer's own Accept retries the reservation. No
    # channel_post_image is set - the want-ad never uploaded a strip, so
    # there is nothing to re-reference.
    #
    # ONLY when the finalize kept its fence. A lost fence means the want-ad
    # is open again and its message still belongs to it: stamping the ids
    # anyway would make one channel message serve two live documents - the
    # reopened request's next claimer would reuse it again, and the 48-hour
    # expiry job would eventually paint "expired" over a live trade's post.
    # Without the reuse, the trade simply has no standing post yet; the
    # reply-note below still lands as an ordinary message.
    if finalize_won and request.get("channel_message_id"):
        post_ids = {
            "channel_id": int(
                request.get("channel_id")
                or _configured_cards_channel_id()
                or 0
            ) or None,
            "channel_message_id": int(request["channel_message_id"]),
            "channel_post_v2": True,
        }
        refreshed.update(post_ids)
        try:
            await mongo.card_trades.update_one(
                {"_id": trade["_id"], "kind": "trade"},
                {"$set": post_ids},
            )
        except Exception:
            _log.info(
                "claimed trade channel id write failed trade=%s",
                trade.get("_id"),
            )
    delivery = await _deliver_soon(
        bot, mongo, refreshed, event="open_request_claimed",
        # When the reservation did not land, the default DM would announce
        # an acceptance that has not happened yet; the reply-note (whose
        # wording fits both outcomes) and the edited standing post carry
        # the news instead. An empty dict means "no DM", None means "the
        # policy default".
        dm_components_by_recipient=None if outcome == "accepted" else {},
    )
    if outcome == "accepted":
        # The exact screen a holder gets after accepting, because that is
        # what the claimer just did.
        return _holder_accept_feedback(
            refreshed,
            taken_card_id=taken,
            status=status,
            delivery=delivery,
            fwa_relevant=await _trade_involves_fwa(mongo, refreshed),
            tag=claimer_tag,
        )
    blocked = {
        "conflict": (
            "one of these exact cards is already committed to another swap"
        ),
        "invalid": "one of the collections changed in the meantime",
    }.get(outcome, "the trade changed before the cards could be reserved")
    return _notice(
        "Claimed — saved as a proposal",
        f"You claimed it first, but {blocked}, so nothing is reserved yet. "
        "The proposal is saved for both of you: open `/cards` → "
        "**My trades** and tap **Accept** once it clears.",
        accent=GOLD_ACCENT,
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
    """Accept from My trades, taking the card the requester proposed."""
    return await _perform_trade_accept(
        ctx, action_id, chosen_card_id=None,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )


async def _perform_trade_accept(
    ctx,
    action_id: str,
    *,
    chosen_card_id: str | None,
    coc_client,
    mongo: MongoClient,
    bot,
):
    """Shared by the My trades button and the DM accept.

    One body, so the DM path cannot drift from the server path: the same
    participant check, the same live re-validation and the same fenced
    reservation run either way.
    """
    scope_error = _guild_scope_error(ctx)
    if scope_error:
        return _notice("Open Card Hub in its family server", scope_error)
    trade = await mongo.card_trades.find_one({
        "_id": action_id,
        "kind": "trade",
        "guild_id": _trade_guild_id(ctx),
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
    # A proposal with several valid return cards is a choice, and the plain
    # Accept button in My trades cannot carry one. When the DM never arrived
    # this was the only accept path, and it silently took the default card -
    # so instead of guessing, show the same pick-and-accept controls the DM
    # carries. Old Accept buttons land here too and get the chooser.
    if chosen_card_id is None and len(_trade_choice_ids(trade)) > 1:
        return _trade_proposal_dm(trade, controls=True)
    # The accepter may take any card the requester consented to give, but
    # only one they still actually hold - `compatible_card_ids` was computed
    # when the proposal was made and can be stale by now.
    taken = str(chosen_card_id or trade["given_card_id"])
    if taken not in _trade_choice_ids(trade):
        return _notice(
            "That card is not part of this swap",
            "Open the proposal again for the current list.",
        )
    error = reciprocal_trade_error(
        _without_reserved_cards(requester),
        _without_reserved_cards(holder),
        trade["wanted_card_id"],
        taken,
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
        chosen_card_id=taken,
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
    # One funnel: the short acceptance reply pinging the requester, the
    # silent standing-post refresh, and the requester's DM (dm="always"
    # during the live-verification window) all come from the policy table.
    delivery = await _deliver_soon(
        bot, mongo, accepted_trade, event="proposal_accepted"
    )
    return _holder_accept_feedback(
        accepted_trade,
        taken_card_id=taken,
        status=status,
        delivery=delivery,
        fwa_relevant=await _trade_involves_fwa(mongo, accepted_trade),
        tag=account.tag,
    )


async def _load_swap_for_confirm(ctx, action_id: str, *, mongo: MongoClient):
    """(trade, role) for a confirmation click, or (None, notice)."""
    trade_id, separator, role_suffix = str(action_id or "").partition("|")
    role_hint = (
        role_suffix
        if separator and role_suffix in {"requester", "holder"}
        else None
    )
    trade = await mongo.card_trades.find_one({
        "_id": trade_id,
        "kind": "trade",
        "guild_id": _trade_guild_id(ctx),
    })
    if not trade:
        return None, _notice("Swap not found", "Reopen **My trades**.")
    matching_roles = []
    for candidate in ("requester", "holder"):
        try:
            participant_id = int(trade.get(f"{candidate}_discord_id") or -1)
        except (TypeError, ValueError):
            continue
        if participant_id == int(ctx.user.id):
            matching_roles.append(candidate)
    if role_hint is not None:
        role = role_hint if role_hint in matching_roles else None
    elif len(matching_roles) == 1:
        # Compatibility for controls posted before the account role was added.
        role = matching_roles[0]
    elif len(matching_roles) > 1:
        # An old control cannot distinguish two linked accounts owned by the
        # same Discord user. Never guess and move the wrong inventory leg.
        return None, _notice(
            "Choose the account again",
            "This older control cannot tell which linked account sent the card. "
            "Reopen **My trades** from that account and use the current button.",
        )
    else:
        role = None
    if role is None:
        return None, _notice(
            "That swap is not yours", "Open **My trades** from your own collection."
        )
    if str(trade.get("status")) not in SWAP_LIVE_STATUSES:
        return None, _notice(
            "This swap is already closed", "Reopen **My trades** for its status."
        )
    return (trade, role), None


@register_action("cards_swap_sent")
@lightbulb.di.with_di
async def cards_swap_sent(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Yes, I sent my card. Moves only this side's card."""
    loaded, problem = await _load_swap_for_confirm(ctx, action_id, mongo=mongo)
    if problem:
        return problem
    trade, role = loaded
    # The trade stores who the participants were at acceptance. This is the
    # one action that mutates two inventories, so recheck against the live
    # links that the clicking user still owns this tag - the same recheck
    # cancel, decline, and accept already run. Fails closed on link outage.
    account, _inventory, target_problem = await _load_target(
        ctx,
        _normalize_tag(trade[f"{role}_tag"]),
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    now = datetime.now(timezone.utc)
    try:
        outcome, remaining, updated = await _run_swap_leg_confirmation(
            mongo,
            trade,
            role=role,
            now=now,
            record_no_spare=False,
        )
    except _SwapLegNeedsReview as exc:
        review = exc.trade
        detail = (
            "One collection update could not be confirmed. Both affected "
            "cards are hidden from matching until the counts are checked."
        )
        await _deliver_soon(
            bot, mongo, review, event="needs_review",
            dm_components_by_recipient=_notify_review_participants(
                review, detail
            ),
        )
        return _trade_feedback(
            "Trade needs review",
            detail,
            account.tag,
            accent=RED_ACCENT,
        )
    if outcome == "changed":
        return _notice(
            "This swap changed",
            "Reopen **My trades** and check its current status.",
        )
    if outcome == "no_spare":
        return _notice(
            "That card is no longer there",
            "Your collection no longer shows a spare of it. Open the card and "
            "set your real count, then try again.",
        )
    other = "holder" if role == "requester" else "requester"
    # Per the delivery table, a card arriving is a silent standing-post
    # refresh: no new post, no ping, and the arrival DM stopped.
    await _deliver_soon(bot, mongo, updated, event="card_arrived")
    return _swap_sent_view(
        updated, role=role, remaining=remaining,
        other_confirmed=bool(updated.get(f"{other}_confirmed_at")),
    )


@register_action("cards_swap_later")
@lightbulb.di.with_di
async def cards_swap_later(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Not yet. Nothing changes; it asks again next time."""
    loaded, problem = await _load_swap_for_confirm(ctx, action_id, mongo=mongo)
    if problem:
        return problem
    trade, role = loaded
    account, inventory, target_problem = await _load_target(
        ctx,
        _normalize_tag(trade[f"{role}_tag"]),
        coc_client=coc_client,
        mongo=mongo,
    )
    if target_problem:
        return target_problem
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
        # One render only. Without this the swap gate re-finds the same trade
        # and "Not yet" shows the question it was pressed to leave.
        skip_swap_gate=True,
    )


@register_action("cards_swap_no")
@lightbulb.di.with_di
async def cards_swap_no(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """No. Ask whether it is dead or simply not done yet."""
    loaded, problem = await _load_swap_for_confirm(ctx, action_id, mongo=mongo)
    if problem:
        return problem
    trade, role = loaded
    return _swap_cancel_check_view(trade, role=role)


@register_action("cards_swap_dead")
@lightbulb.di.with_di
async def cards_swap_dead(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Cancelled. Same path as cancelling from My trades."""
    return await cards_trade_cancel(
        ctx, str(action_id or "").partition("|")[0],
        coc_client=coc_client, mongo=mongo, bot=bot,
    )


async def _answered_a_request(mongo: MongoClient, tag: object) -> None:
    """Clear the ignored-request counter, because they just answered one.

    This is what makes the count CONSECUTIVE rather than lifetime. Without it,
    somebody who trades happily for a month and misses one request at each end
    would be asked whether they are still trading.
    """
    try:
        await mongo.card_inventories.update_one(
            {"_id": _normalize_tag(tag)},
            {"$set": {"ignored_requests": 0, "checkin_sent_at": None}},
        )
    except Exception:
        _log.info("ignored-request reset failed tag=%s", tag)


@register_action("cards_trading_on")
@lightbulb.di.with_di
async def cards_trading_on(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Make this account visible again. Works from the DM or from /cards."""
    account, inventory, problem = await _set_trading_paused(
        ctx, action_id, paused=False, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
    )


@register_action("cards_trading_off")
@lightbulb.di.with_di
async def cards_trading_off(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Hide this account from everyone else. Nothing is deleted."""
    account, _inventory, problem = await _set_trading_paused(
        ctx, action_id, paused=True, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    return _trading_paused_view(account, just_changed=True)


async def _set_trading_paused(
    ctx, action_id: str, *, paused: bool, coc_client, mongo: MongoClient
):
    """Flip the visibility flag and reset the ignored-request counter.

    The counter resets either way: saying yes proves they are responsive, and
    saying no means the count has done its job.
    """
    tag, _rest = _parse_target(str(action_id or ""))
    account, inventory, problem = await _load_target(
        ctx, tag, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return None, None, problem
    now = datetime.now(timezone.utc)
    try:
        await mongo.card_inventories.update_one(
            {"_id": _normalize_tag(account.tag)},
            {"$set": {
                "trading_paused": bool(paused),
                "trading_paused_at": now if paused else None,
                "ignored_requests": 0,
                "checkin_sent_at": None,
                "updated_at": now,
            }},
        )
    except Exception:
        _log.exception("trading visibility write failed tag=%s", account.tag)
        return None, None, _notice(
            "Could not save that", "Try again in a moment."
        )
    inventory = dict(inventory)
    inventory["trading_paused"] = bool(paused)
    return account, inventory, None


# cards_dm_accept / cards_dm_decline stay registered FOREVER, unchanged and
# with no_return=False, even though the public cards_pub_* actions below do
# the same job: DMs already sent carry these custom_ids, custom_ids never
# expire, and editing the DM in place is exactly right there. Aliasing onto
# the public names is the wrong tool - the DM pair needs the dispatcher's
# normal edit reply while the public pair needs no_return=True, and one
# Action cannot hold both flags. Do not "clean this up".
@register_action("cards_dm_accept")
@lightbulb.di.with_di
async def cards_dm_accept(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Accept straight from the proposal DM, choosing which card you take."""
    trade_id, _, suffix = str(action_id or "").partition("|")
    values = list(getattr(ctx.interaction, "values", ()) or ())
    chosen = str(values[0]) if values else suffix
    return await _perform_trade_accept(
        ctx, trade_id,
        chosen_card_id=chosen or None,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )


# See the comment above cards_dm_accept: this stays registered forever with
# no_return=False; cards_pub_decline is not a rename of it and cannot be.
@register_action("cards_dm_decline")
@lightbulb.di.with_di
async def cards_dm_decline(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Decline from the DM. Same path as declining in the server."""
    return await cards_trade_decline(
        ctx, str(action_id or "").partition("|")[0],
        coc_client=coc_client, mongo=mongo, bot=bot,
    )


async def _public_reply(ctx, components: list) -> None:
    """Answer a click on a PUBLIC channel post, privately.

    Every cards_pub_* handler replies through here and only here. The
    dispatcher's normal reply is an EDIT of the clicked message - on a public
    post that would replace the post with the clicker's private panel for the
    whole channel - so the public actions register with no_return=True and
    this followup is the sole reply channel. Same shape as cards_help
    (extensions/tasks/cards_sticky.py), the pattern that has run in
    production since the sticky shipped; the followup's own buttons keep
    working because a component click on it is an ordinary interaction that
    edits the followup (pinned by
    test_a_public_button_answers_privately_and_its_followup_stays_clickable).
    """
    try:
        await ctx.interaction.execute(
            components=components,
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.EPHEMERAL
            ),
        )
    except Exception as exc:
        _log.warning(
            "cards public reply failed user=%s error=%s",
            getattr(getattr(ctx, "user", None), "id", None),
            type(exc).__name__,
        )


# The public adapters are thin: the shared bodies already enforce that the
# clicker is a participant (`_load_trade_actor` / the cancel role check) and
# scope the lookup to the configured guild, so a wrong member's tap gets the
# existing ephemeral refusal notice - through _public_reply, never a public
# change. New names, deliberately without aliases: nothing ever pointed at
# them before.
@register_action("cards_pub_accept", no_return=True)
@lightbulb.di.with_di
async def cards_pub_accept(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Accept from the standing post. Multi-card proposals get the chooser."""
    result = await _perform_trade_accept(
        ctx, str(action_id or ""), chosen_card_id=None,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


@register_action("cards_pub_decline", no_return=True)
@lightbulb.di.with_di
async def cards_pub_decline(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Decline from the standing post, via the one shared decline body."""
    result = await cards_trade_decline(
        ctx, str(action_id or ""),
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


@register_action("cards_pub_cancel", no_return=True)
@lightbulb.di.with_di
async def cards_pub_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Cancel from the standing post, via the one shared cancel body."""
    result = await cards_trade_cancel(
        ctx, str(action_id or ""),
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


# The claim trio shares one body (_perform_open_request_claim); each adapter
# only parses its custom_id shape. All three reply ONLY through
# _public_reply: cards_pub_claim is clicked on the PUBLIC want-ad, and
# cards_pub_claim_as / cards_pub_take are clicked on the ephemeral followups
# it answers with - a component click on a followup is a fresh interaction,
# so each handler is also no_return=True and answers with a fresh followup
# of its own (test_component_action_names.py pins the flag on all three).
# Wrong-member, stale and raced taps therefore never alter the public post.
@register_action("cards_pub_claim", no_return=True)
@lightbulb.di.with_di
async def cards_pub_claim(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Entry from the want-ad's public button: {request_id}|{generation}."""
    request_id, _, generation = str(action_id or "").partition("|")
    result = await _perform_open_request_claim(
        ctx, request_id=request_id, generation=generation,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


@register_action("cards_pub_claim_as", no_return=True)
@lightbulb.di.with_di
async def cards_pub_claim_as(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Multi-account disambiguation: {request_id}|{generation}|{tag}."""
    parts = str(action_id or "").split("|")
    result = await _perform_open_request_claim(
        ctx,
        request_id=parts[0] if parts else "",
        generation=parts[1] if len(parts) > 1 else "",
        claim_tag=(parts[2] if len(parts) > 2 else "") or None,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


@register_action("cards_pub_take", no_return=True)
@lightbulb.di.with_di
async def cards_pub_take(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Which offered card the claimer takes.

    {request_id}|{generation}|{tag} with the card id in the select's values;
    a 4th pipe part is accepted as a button form for the single-option case.
    """
    parts = str(action_id or "").split("|")
    values = list(getattr(ctx.interaction, "values", ()) or ())
    taken = str(values[0]) if values else (
        parts[3] if len(parts) > 3 else ""
    )
    result = await _perform_open_request_claim(
        ctx,
        request_id=parts[0] if parts else "",
        generation=parts[1] if len(parts) > 1 else "",
        claim_tag=(parts[2] if len(parts) > 2 else "") or None,
        taken_card_id=taken or None,
        coc_client=coc_client, mongo=mongo, bot=bot,
    )
    await _public_reply(ctx, result)


# The gem-ask pair on the public post. Same shared body as the legacy DM pair
# (holder-only, generation and pending-CAS guards all live inside
# `_answer_gem_ask`), so a wrong member's tap gets the existing ephemeral
# refusal - through _public_reply, never a public change.
@register_action("cards_pub_gem_yes", no_return=True)
@lightbulb.di.with_di
async def cards_pub_gem_yes(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """Yes from the public gem-ask post: {ask_id}|{generation}."""
    result = await _answer_gem_ask(ctx, mongo, bot, action_id, agreed=True)
    await _public_reply(ctx, result)


@register_action("cards_pub_gem_no", no_return=True)
@lightbulb.di.with_di
async def cards_pub_gem_no(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
):
    """No from the public gem-ask post: {ask_id}|{generation}."""
    result = await _answer_gem_ask(ctx, mongo, bot, action_id, agreed=False)
    await _public_reply(ctx, result)


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
        "guild_id": _trade_guild_id(ctx),
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
    await _answered_a_request(mongo, trade.get("holder_tag"))
    trade["status"] = "declined"
    # Per the delivery table a decline is silent: the standing post updates
    # in place and nobody is pinged or DMed about it.
    await _deliver_soon(bot, mongo, trade, event="declined")
    return _trade_feedback(
        "Proposal declined",
        "The proposal is closed; no cards were reserved. "
        "The channel post now shows it as declined.",
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
        "guild_id": _trade_guild_id(ctx),
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
        return _notice("That trade action is not yours", "Open **My trades** from your own collection.")
    account, _inventory, problem = await _load_trade_actor(
        ctx, trade, role=role, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    now = datetime.now(timezone.utc)
    # A swap where one player already confirmed has already moved one card.
    # Cancelling is still allowed - it is how a dead half-swap gets closed -
    # but the copy below must not claim nothing changed when it did.
    one_leg_applied = bool(
        trade.get("requester_confirmed_at") or trade.get("holder_confirmed_at")
    )
    cancel_fields = {
        "status": "cancelled",
        "cancelled_at": now,
        "cancelled_by": user_id,
        "updated_at": now,
        **_cleanup_fields(trade),
    }
    if one_leg_applied:
        cancel_fields["cancelled_after_confirmation"] = True
    result = await mongo.card_trades.update_one(
        {"_id": trade["_id"], "status": {"$in": ["pending", "move_needed", "ready", "accepted"]}},
        {
            "$set": cancel_fields,
            "$unset": {"open_proposal_key": ""},
        },
    )
    if not getattr(result, "modified_count", 0):
        return _notice("Trade can no longer be cancelled", "Reopen **My trades**.")
    await _release_proposal_slots(mongo, trade)
    # This returns False and leaves the work queued when the release fails.
    # Claiming the cards are free when they are still fenced is what turns a
    # transient error into "I cancelled it and the swap never came back".
    released = await _finish_trade_cleanup(
        mongo, trade, owner=_reservation_owner(trade)
    )
    trade["status"] = "cancelled"
    # Per the delivery table a cancellation is silent: the standing post
    # updates in place and the cancelled-DM stopped.
    await _deliver_soon(bot, mongo, trade, event="cancelled")
    note = _swap_cancel_note(trade, role)
    return _trade_feedback(
        "Trade cancelled",
        (
            f"{note} The remaining exact-card reservations were "
            "released. The channel post now shows it as cancelled."
            if released
            else f"{note} Releasing the reserved cards is still "
            "finishing — open **Find trades** in a moment and it will "
            "complete. The channel post now shows it as cancelled."
        ),
        account.tag,
        accent=None,
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
        "guild_id": _trade_guild_id(ctx),
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
        return _notice("That trade action is not yours", "Open **My trades** from your own collection.")
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
            accent=RED_ACCENT,
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
            "The exact cards remain reserved. Move into the same family clan. "
            "After you send your card in game, open **My trades** and tap "
            "**I sent my card**.",
            account.tag,
            accent=GOLD_ACCENT,
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
            # needs_review keeps its DM (a public nag is worse); here only
            # the other player needs one - the actor is reading this panel.
            delivery = await _deliver_soon(
                bot, mongo, trade, event="needs_review",
                dm_components_by_recipient={other_id: _status_dm(
                    trade,
                    recipient_id=other_id,
                    title="Card swap needs review",
                    detail=(
                        "A reservation expired before completion. No automatic "
                        "inventory update was attempted."
                    ),
                    accent=RED_ACCENT,
                )},
            )
            return _notice(
                "Trade needs manual review",
                "A reservation expired; no automatic inventory update was attempted."
                # A None delivery is still in flight, which is not a failure,
                # so it earns no "could not reach" warning.
                + ("" if delivery is None else _dm_fallback_note(
                    other_id in delivery.dm_sent, other_id
                )),
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
        delivery = await _deliver_soon(
            bot, mongo, trade, event="needs_review",
            dm_components_by_recipient={other_id: _status_dm(
                trade, recipient_id=other_id,
                title="Card swap needs review", detail=detail,
                accent=RED_ACCENT,
            )},
        )
        return _trade_feedback(
            "Trade needs review",
            detail + ("" if delivery is None else _dm_fallback_note(
                other_id in delivery.dm_sent, other_id
            )),
            account.tag,
            accent=RED_ACCENT,
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
        delivery = await _deliver_soon(
            bot, mongo, trade, event="needs_review",
            dm_components_by_recipient={other_id: _status_dm(
                trade, recipient_id=other_id,
                title="Card swap needs review", detail=detail,
                accent=RED_ACCENT,
            )},
        )
        return _trade_feedback(
            "Trade needs review",
            detail + ("" if delivery is None else _dm_fallback_note(
                other_id in delivery.dm_sent, other_id
            )),
            account.tag,
            accent=RED_ACCENT,
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
        delivery = await _deliver_soon(
            bot, mongo, trade, event="needs_review",
            dm_components_by_recipient={other_id: _status_dm(
                trade, recipient_id=other_id,
                title="Card swap needs review", detail=review_detail,
                accent=RED_ACCENT,
            )},
        )
        return _trade_feedback(
            "Trade needs review",
            "Both collections changed, but the audit record could not be finalized. "
            "Review both collections before making another request."
            + ("" if delivery is None else _dm_fallback_note(
                other_id in delivery.dm_sent, other_id
            )),
            account.tag,
            accent=RED_ACCENT,
        )
    await _finish_trade_cleanup(
        mongo, trade, owner=_reservation_owner(trade)
    )
    trade["status"] = "completed"
    # Per the delivery table completion is silent: the standing post collapses
    # to its compact closed form and the completed-DM stopped.
    await _deliver_soon(bot, mongo, trade, event="completed")
    return _trade_feedback(
        "Trade completed",
        "Both inventories were updated conservatively: each missing card is now owned "
        "and each offered duplicate dropped by one copy. Mark another spare if you still have one.",
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
    """Legacy freshness button on old messages: redirect to the collection.

    "Still accurate" was removed from the UI because its stamp never affected
    matching (every write refreshes `confirmed_at`, and `MATCHABLE_FOR` is
    ten years). Old panels can still carry the button indefinitely, so it
    stays registered - it just opens the collection and writes nothing
    beyond the ordinary open-time activity stamp.
    """
    account, inventory, problem = await _load_target(
        ctx, action_id, coc_client=coc_client, mongo=mongo
    )
    if problem:
        return problem
    data = await load_accounts(coc_client, int(ctx.user.id))
    return await _dashboard_view(
        account, inventory, account_count=len(_loaded_entries(data)),
        mongo=mongo, guild_id=_trade_guild_id(ctx),
    )
