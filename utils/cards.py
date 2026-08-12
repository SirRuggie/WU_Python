"""Pure Clash of Cards catalog, inventory, and matching rules.

The public Clash API does not expose the August 2026 event collection.  The
Discord command therefore stores a deliberately small state per card:

    0 = missing, 1 = one copy, 2+ = that many copies, all but one tradable

Exact duplicate counts are unnecessary for discovery and would make members do
more work.  A completed trade can turn ``2`` into ``1``; the member can mark it
as a duplicate again if another spare remains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping


MISSING = 0
OWNED = 1
# DUPLICATE is the threshold at which a card becomes tradeable, not a ceiling.
# A card never gives away its last copy, so two is the floor for a spare and
# the stored value may be any count at or above it.
DUPLICATE = 2
MAX_COPIES = 99

FRESH_FOR = timedelta(hours=24)
AGING_FOR = timedelta(hours=48)
# Kept only so an existing collection with no confirmation timestamp at all
# is still recognised as never-scanned. A collection does NOT expire with age:
# this event runs for weeks, and dropping somebody for being idle removed
# people whose cards were perfectly accurate, without ever telling them.
# Visibility is now driven by whether they answer requests - see
# `trading_paused` and the check-in flow in extensions/commands/cards.py.
# Gems the responder pays when they hold no duplicate of the requested card.
# Only a same-category trade exists at all - elixir for elixir, dark for dark,
# builder for builder, super for super - so the cost keys on that category.
# Source: Clash of Clans wiki, Clash of Cards, "Clan Chat Trades".
TRADE_GEM_COST = {
    "elixir": 50,
    "dark_elixir": 70,
    "builder_base": 90,
    "super_troop": 110,
}

MATCHABLE_FOR = timedelta(days=3650)


@dataclass(frozen=True, slots=True)
class CardCategory:
    id: str
    name: str
    short_name: str
    emoji: str


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    name: str
    category: str
    position: int


@dataclass(frozen=True, slots=True)
class InventorySummary:
    collected: int
    missing: int
    duplicates: int
    known: int
    complete_categories: int


@dataclass(frozen=True, slots=True)
class CategoryExchange:
    category: str
    offers: tuple[str, ...]
    # Every same-category duplicate the requester could hand over. The event
    # does NOT require the holder to be missing it - a second copy is simply a
    # duplicate for them, which the Trader accepts. Treating "they need it" as
    # a requirement hid most legal trades.
    returns: tuple[str, ...]
    # The subset the holder is actually missing. Not a rule, just the better
    # trade, so it still sorts first.
    wanted_returns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CardMatch:
    holder_tag: str
    holder_name: str
    holder_discord_id: int | None
    holder_clan_tag: str | None
    holder_clan_name: str | None
    exchanges: tuple[CategoryExchange, ...]
    same_clan: bool
    confirmed_at: datetime

    @property
    def reciprocal(self) -> bool:
        """A genuine two-way trade: they are missing what you would give.

        Keys on wanted_returns rather than returns. Since any same-category
        duplicate became a legal offer, `returns` is non-empty for almost
        everybody, so sorting on it would rank every holder identically and
        the best trades would stop floating to the top.
        """
        return any(exchange.wanted_returns for exchange in self.exchanges)

    @property
    def free(self) -> bool:
        """You hold a same-category duplicate, so this costs you no gems."""
        return any(exchange.returns for exchange in self.exchanges)

    @property
    def offers(self) -> tuple[str, ...]:
        return tuple(
            card_id
            for exchange in self.exchanges
            for card_id in exchange.offers
        )

    @property
    def returns(self) -> tuple[str, ...]:
        return tuple(
            card_id
            for exchange in self.exchanges
            for card_id in exchange.returns
        )

    @property
    def wanted_returns(self) -> tuple[str, ...]:
        return tuple(
            card_id
            for exchange in self.exchanges
            for card_id in exchange.wanted_returns
        )


# The emoji here is the plain-unicode stand-in, used where Discord will not
# render `<:name:id>` markup - select placeholders print it verbatim. Anything
# that renders as message text uses the uploaded category emoji instead, via
# `category_markup` / `category_partial` in the cards command.
CATEGORIES: tuple[CardCategory, ...] = (
    CardCategory("elixir", "Elixir Cards", "Elixir", "💧"),
    CardCategory("dark_elixir", "Dark Elixir Cards", "Dark Elixir", "🌑"),
    CardCategory("builder_base", "Builder Base Cards", "Builder Base", "🔨"),
    CardCategory("super_troop", "Super Troop Cards", "Super Troops", "⚡"),
)

CATEGORY_BY_ID = {category.id: category for category in CATEGORIES}

_CARD_NAMES: dict[str, tuple[str, ...]] = {
    "elixir": (
        "Barbarian",
        "Archer",
        "Giant",
        "Goblin",
        "Wall Breaker",
        "Balloon",
        "Wizard",
        "Healer",
        "Dragon",
        "PEKKA",
        "Baby Dragon",
        "Miner",
        "Electro Dragon",
        "Yeti",
        "Dragon Rider",
        "Electro Titan",
        "Root Rider",
        "Thrower",
        "Meteor Golem",
    ),
    "dark_elixir": (
        "Minion",
        "Hog Rider",
        "Valkyrie",
        "Golem",
        "Witch",
        "Lava Hound",
        "Bowler",
        "Ice Golem",
        "Headhunter",
        "Apprentice Warden",
        "Druid",
        "Furnace",
        "Rubble Witch",
    ),
    "builder_base": (
        "Raged Barbarian",
        "Sneaky Archer",
        "Boxer Giant",
        "Beta Minion",
        "Bomber",
        "BB Baby Dragon",
        "Cannon Cart",
        "Night Witch",
        "Drop Ship",
        "Power PEKKA",
        "Hog Glider",
    ),
    "super_troop": (
        "Super Barbarian",
        "Super Archer",
        "Super Giant",
        "Sneaky Goblin",
        "Super Wall Breaker",
        "Rocket Balloon",
        "Super Wizard",
        "Super Dragon",
        "Inferno Dragon",
        "Super Miner",
        "Super Yeti",
        "Super Minion",
        "Super Hog Rider",
        "Super Valkyrie",
        "Super Witch",
        "Ice Hound",
        "Super Bowler",
    ),
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


CARDS: tuple[Card, ...] = tuple(
    Card(_slug(name), name, category_id, position)
    for category_id, names in _CARD_NAMES.items()
    for position, name in enumerate(names, start=1)
)

CARD_BY_ID = {card.id: card for card in CARDS}
CARD_BY_NAME = {card.name.casefold(): card for card in CARDS}
CATEGORY_CARDS = {
    category.id: tuple(card for card in CARDS if card.category == category.id)
    for category in CATEGORIES
}


def normalize_status(value: object) -> int:
    """Return a stored copy count.

    ``0`` is missing and ``1`` is a single copy, exactly as before. Anything at
    or above ``DUPLICATE`` is a spare, and the exact number is now kept rather
    than clamped to two, so a member holding four can say so.

    Every rule in this module tests ``>= DUPLICATE`` rather than ``== DUPLICATE``
    so that holding more than two is never mistaken for holding none. Documents
    written before this change store at most ``2`` and stay valid without a
    migration; they simply mean "at least one spare", which is what they always
    meant.
    """
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return OWNED
    if numeric <= MISSING:
        return MISSING
    return min(numeric, MAX_COPIES)


def normalize_cards(values: Mapping[str, object] | None) -> dict[str, int]:
    """Drop unknown ids and clamp known card states."""
    values = values or {}
    return {
        card_id: normalize_status(status)
        for card_id, status in values.items()
        if card_id in CARD_BY_ID
    }


def apply_category_selection(
    existing: Mapping[str, object] | None,
    category_id: str,
    selected: Iterable[str] = (),
    *,
    mode: str,
) -> dict[str, int]:
    """Apply one complete missing/duplicate selection for a category.

    Unknown cards in the selected category default to one copy.  This is the
    low-effort setup rule: members only select exceptions.  A missing update
    preserves existing duplicates; a duplicate update preserves existing
    missing cards.  Selecting the same card in the other list later makes the
    most recent interaction authoritative.
    """
    if category_id not in CATEGORY_BY_ID:
        raise ValueError(f"unknown card category: {category_id}")
    if mode not in {"missing", "duplicates", "baseline"}:
        raise ValueError(f"unknown category update mode: {mode}")

    result = normalize_cards(existing)
    valid_ids = {card.id for card in CATEGORY_CARDS[category_id]}
    chosen = set(selected) & valid_ids

    for card in CATEGORY_CARDS[category_id]:
        current = result.get(card.id, OWNED)
        if mode == "baseline":
            result[card.id] = OWNED
        elif mode == "missing":
            if card.id in chosen:
                result[card.id] = MISSING
            elif current == MISSING or card.id not in result:
                result[card.id] = OWNED
        else:
            if card.id in chosen:
                result[card.id] = DUPLICATE
            elif current >= DUPLICATE or card.id not in result:
                result[card.id] = OWNED
    return result


def inventory_summary(
    values: Mapping[str, object] | None,
    complete_categories: Iterable[str] = (),
) -> InventorySummary:
    cards = normalize_cards(values)
    complete = set(complete_categories) & set(CATEGORY_BY_ID)
    known_ids = {
        card.id
        for category_id in complete
        for card in CATEGORY_CARDS[category_id]
    }
    states = [cards.get(card_id, OWNED) for card_id in known_ids]
    return InventorySummary(
        collected=sum(state >= OWNED for state in states),
        missing=sum(state == MISSING for state in states),
        duplicates=sum(state >= DUPLICATE for state in states),
        known=len(known_ids),
        complete_categories=len(complete),
    )


def category_summary(
    values: Mapping[str, object] | None,
    category_id: str,
) -> InventorySummary:
    if category_id not in CATEGORY_BY_ID:
        raise ValueError(f"unknown card category: {category_id}")
    cards = normalize_cards(values)
    states = [cards.get(card.id, OWNED) for card in CATEGORY_CARDS[category_id]]
    return InventorySummary(
        collected=sum(state >= OWNED for state in states),
        missing=sum(state == MISSING for state in states),
        duplicates=sum(state >= DUPLICATE for state in states),
        known=len(states),
        complete_categories=1,
    )


def as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def freshness_label(value: object, *, now: datetime | None = None) -> str:
    stamp = as_utc(value)
    if stamp is None:
        return "stale"
    now = as_utc(now) or datetime.now(timezone.utc)
    age = max(timedelta(), now - stamp)
    if age <= FRESH_FOR:
        return "fresh"
    if age <= AGING_FOR:
        return "aging"
    return "stale"


def _document_timestamp(document: Mapping[str, object]) -> datetime | None:
    return as_utc(document.get("confirmed_at") or document.get("updated_at"))


def _matchable(
    document: Mapping[str, object],
    *,
    now: datetime,
    max_age: timedelta,
) -> datetime | None:
    """When this collection was confirmed, or None if it cannot be matched.

    Two ways to be unmatchable: never scanned at all, or the member turned
    trading off. Age alone is no longer one of them.
    """
    if document.get("trading_paused"):
        return None
    confirmed_at = _document_timestamp(document)
    if confirmed_at is None or now - confirmed_at > max_age:
        return None
    return confirmed_at


def inventory_is_matchable(
    document: Mapping[str, object],
    *,
    now: datetime | None = None,
    max_age: timedelta = MATCHABLE_FOR,
) -> bool:
    """Whether a collection is recent enough to participate in matching."""
    now = as_utc(now) or datetime.now(timezone.utc)
    return _matchable(document, now=now, max_age=max_age) is not None


def reciprocal_trade_error(
    requester: Mapping[str, object],
    holder: Mapping[str, object],
    wanted_card_id: str,
    given_card_id: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = MATCHABLE_FOR,
) -> str | None:
    """Validate the four inventory legs of one same-category reciprocal swap.

    This deliberately validates collection snapshots only. Discovery and
    proposals may cross family clans; callers must verify live family-clan
    membership before acceptance and same-clan membership before completion.
    """
    wanted = CARD_BY_ID.get(wanted_card_id)
    given = CARD_BY_ID.get(given_card_id)
    if wanted is None or given is None or wanted.id == given.id:
        return "Choose two different known cards."
    if wanted.category != given.category:
        return "Both cards must belong to the same category."

    requester_complete = set(requester.get("complete_categories") or ())
    holder_complete = set(holder.get("complete_categories") or ())
    if wanted.category not in requester_complete or wanted.category not in holder_complete:
        return "Both players must finish this category before requesting a swap."

    now = as_utc(now) or datetime.now(timezone.utc)
    if not inventory_is_matchable(requester, now=now, max_age=max_age):
        return "Your trading is turned off. Turn it back on in /cards."
    if not inventory_is_matchable(holder, now=now, max_age=max_age):
        return "That player has turned trading off."

    requester_cards = normalize_cards(requester.get("cards"))
    holder_cards = normalize_cards(holder.get("cards"))
    if requester_cards.get(wanted.id, OWNED) != MISSING:
        return "You no longer list the requested card as missing."
    if requester_cards.get(given.id, OWNED) < DUPLICATE:
        return "You no longer list the offered card as a duplicate."
    if holder_cards.get(wanted.id, OWNED) < DUPLICATE:
        return "The holder no longer lists the requested card as a duplicate."
    # No check that the holder is MISSING the offered card. The event lets any
    # same-category duplicate be offered; if they already own it they simply
    # gain a duplicate, which the Trader takes. Requiring it hid most trades.
    return None


def find_matches(
    requester: Mapping[str, object],
    candidates: Iterable[Mapping[str, object]],
    *,
    now: datetime | None = None,
    max_age: timedelta = MATCHABLE_FOR,
) -> list[CardMatch]:
    """Find holders for every configured card the requester is missing.

    A reciprocal return is only listed when it belongs to the same category as
    at least one offered card.  Same-category exchanges are the legal no-gem
    path in the event.  Direct helpers are retained even when no reciprocal
    return exists.
    """
    now = as_utc(now) or datetime.now(timezone.utc)
    if not inventory_is_matchable(requester, now=now, max_age=max_age):
        return []
    requester_tag = str(requester.get("_id") or requester.get("tag") or "")
    requester_cards = normalize_cards(requester.get("cards"))
    requester_complete = set(requester.get("complete_categories") or ())
    requester_clan = requester.get("clan_tag")

    results: list[CardMatch] = []
    for candidate in candidates:
        candidate_tag = str(candidate.get("_id") or candidate.get("tag") or "")
        if not candidate_tag or candidate_tag == requester_tag:
            continue
        confirmed_at = _matchable(candidate, now=now, max_age=max_age)
        if confirmed_at is None:
            continue

        candidate_cards = normalize_cards(candidate.get("cards"))
        candidate_complete = set(candidate.get("complete_categories") or ())
        common_categories = requester_complete & candidate_complete & set(CATEGORY_BY_ID)
        exchanges: list[CategoryExchange] = []

        for category_id in CATEGORY_BY_ID:
            if category_id not in common_categories:
                continue
            category_offers = [
                card.id
                for card in CATEGORY_CARDS[category_id]
                if requester_cards.get(card.id, OWNED) == MISSING
                and candidate_cards.get(card.id, OWNED) >= DUPLICATE
            ]
            if not category_offers:
                continue
            category_returns = [
                card.id
                for card in CATEGORY_CARDS[category_id]
                if requester_cards.get(card.id, OWNED) >= DUPLICATE
            ]
            exchanges.append(CategoryExchange(
                category=category_id,
                offers=tuple(category_offers),
                returns=tuple(category_returns),
                wanted_returns=tuple(
                    card_id for card_id in category_returns
                    if candidate_cards.get(card_id, OWNED) == MISSING
                ),
            ))

        if not exchanges:
            continue

        discord_id = candidate.get("discord_id")
        try:
            holder_discord_id = int(discord_id) if discord_id is not None else None
        except (TypeError, ValueError):
            holder_discord_id = None

        results.append(CardMatch(
            holder_tag=candidate_tag,
            holder_name=str(candidate.get("player_name") or "Unknown player"),
            holder_discord_id=holder_discord_id,
            holder_clan_tag=(str(candidate["clan_tag"]) if candidate.get("clan_tag") else None),
            holder_clan_name=(str(candidate["clan_name"]) if candidate.get("clan_name") else None),
            exchanges=tuple(exchanges),
            same_clan=bool(requester_clan and requester_clan == candidate.get("clan_tag")),
            confirmed_at=confirmed_at,
        ))

    results.sort(key=lambda match: (
        not match.same_clan,
        not match.reciprocal,
        -match.confirmed_at.timestamp(),
        match.holder_name.casefold(),
        match.holder_tag,
    ))
    return results


@dataclass(frozen=True, slots=True)
class CardSupply:
    """How one card sits across the family."""

    card_id: str
    holders: tuple[str, ...]
    seekers: tuple[str, ...]
    reporting: int

    @property
    def spare_count(self) -> int:
        return len(self.holders)

    @property
    def demand(self) -> int:
        return len(self.seekers)


def family_supply(
    candidates: Iterable[Mapping[str, object]],
    *,
    now: datetime | None = None,
    max_age: timedelta = MATCHABLE_FOR,
) -> dict[str, CardSupply]:
    """Who holds a spare of each card, and who still needs it.

    This is a projection of the same documents matching already loads, so a
    family view costs no extra query.  Only categories a collection has
    actually reviewed count, for either side: an untouched category means the
    member has not told us anything, and counting it as demand would invent a
    want out of missing data.
    """
    now = as_utc(now) or datetime.now(timezone.utc)
    holders: dict[str, list[str]] = {card.id: [] for card in CARDS}
    seekers: dict[str, list[str]] = {card.id: [] for card in CARDS}
    reporting = 0

    for candidate in candidates:
        tag = str(candidate.get("_id") or candidate.get("tag") or "")
        if not tag or _matchable(candidate, now=now, max_age=max_age) is None:
            continue
        complete = set(candidate.get("complete_categories") or ()) & set(CATEGORY_BY_ID)
        if not complete:
            continue
        reporting += 1
        values = normalize_cards(candidate.get("cards"))
        for category_id in complete:
            for card in CATEGORY_CARDS[category_id]:
                state = values.get(card.id, OWNED)
                if state >= DUPLICATE:
                    holders[card.id].append(tag)
                elif state == MISSING:
                    seekers[card.id].append(tag)

    return {
        card.id: CardSupply(
            card_id=card.id,
            holders=tuple(sorted(holders[card.id])),
            seekers=tuple(sorted(seekers[card.id])),
            reporting=reporting,
        )
        for card in CARDS
    }


def max_achievable_trades(
    trades: Iterable[tuple[tuple[str, str], tuple[str, str]]],
) -> int:
    """How many of these swaps could all complete together.

    A raw count of legal swaps overstates what the family can actually do,
    because completing one spends a spare: a member offering their single
    extra Barbarian to three partners is one trade, not three.

    Each swap is given as the two ``(tag, card_id)`` spares it would consume.
    This is a resource-constrained matching whose exact solution is a
    blossom-style search; that is disproportionate machinery for a hint line,
    so this is a most-constrained-first greedy.  ``tests/test_cards.py`` checks
    it against brute force on small inputs, including a case built to hit the
    known worst case, so the gap is measured rather than assumed away.
    """
    pending = [
        (left, right)
        for left, right in trades
        if left != right
    ]
    used: set[tuple[str, str]] = set()
    taken = 0

    while pending:
        contention: dict[tuple[str, str], int] = {}
        for left, right in pending:
            contention[left] = contention.get(left, 0) + 1
            contention[right] = contention.get(right, 0) + 1
        # Fewest competing claims first, then a stable key so the answer does
        # not depend on input order.
        left, right = min(
            pending,
            key=lambda pair: (
                contention[pair[0]] + contention[pair[1]],
                pair[0],
                pair[1],
            ),
        )
        used.add(left)
        used.add(right)
        taken += 1
        pending = [
            pair
            for pair in pending
            if pair[0] not in used and pair[1] not in used
        ]

    return taken


def holders_for_card(
    requester: Mapping[str, object],
    candidates: Iterable[Mapping[str, object]],
    card_id: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = MATCHABLE_FOR,
) -> list[CardMatch]:
    """Return duplicate holders for one card, with legal reciprocal options."""
    card = CARD_BY_ID.get(card_id)
    if card is None:
        return []

    now = as_utc(now) or datetime.now(timezone.utc)
    if not inventory_is_matchable(requester, now=now, max_age=max_age):
        return []
    requester_tag = str(requester.get("_id") or requester.get("tag") or "")
    requester_cards = normalize_cards(requester.get("cards"))
    requester_complete = set(requester.get("complete_categories") or ())
    requester_clan = requester.get("clan_tag")
    if card.category not in requester_complete:
        return []

    results: list[CardMatch] = []
    for candidate in candidates:
        candidate_tag = str(candidate.get("_id") or candidate.get("tag") or "")
        if not candidate_tag or candidate_tag == requester_tag:
            continue
        confirmed_at = _matchable(candidate, now=now, max_age=max_age)
        if confirmed_at is None:
            continue

        candidate_complete = set(candidate.get("complete_categories") or ())
        candidate_cards = normalize_cards(candidate.get("cards"))
        if (
            card.category not in candidate_complete
            or candidate_cards.get(card_id, OWNED) < DUPLICATE
        ):
            continue

        # Same rule as find_matches: any same-category duplicate is a legal
        # offer. Requiring the holder to be MISSING it meant a spare Barbarian
        # counted for nobody, because everybody has a Barbarian - so a player
        # with a real card to trade was told they had none and must pay gems.
        returns = tuple(
            other.id
            for other in CATEGORY_CARDS[card.category]
            if requester_cards.get(other.id, OWNED) >= DUPLICATE
        )
        wanted_returns = tuple(
            other_id for other_id in returns
            if candidate_cards.get(other_id, OWNED) == MISSING
        )
        discord_id = candidate.get("discord_id")
        try:
            holder_discord_id = int(discord_id) if discord_id is not None else None
        except (TypeError, ValueError):
            holder_discord_id = None

        results.append(CardMatch(
            holder_tag=candidate_tag,
            holder_name=str(candidate.get("player_name") or "Unknown player"),
            holder_discord_id=holder_discord_id,
            holder_clan_tag=(str(candidate["clan_tag"]) if candidate.get("clan_tag") else None),
            holder_clan_name=(str(candidate["clan_name"]) if candidate.get("clan_name") else None),
            exchanges=(CategoryExchange(
                category=card.category,
                offers=(card_id,),
                returns=returns,
                wanted_returns=wanted_returns,
            ),),
            same_clan=bool(requester_clan and requester_clan == candidate.get("clan_tag")),
            confirmed_at=confirmed_at,
        ))

    results.sort(key=lambda match: (
        not match.same_clan,
        not match.reciprocal,
        -match.confirmed_at.timestamp(),
        match.holder_name.casefold(),
        match.holder_tag,
    ))
    return results
