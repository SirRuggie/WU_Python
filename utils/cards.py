"""Pure Clash of Cards catalog, inventory, and matching rules.

The public Clash API does not expose the August 2026 event collection.  The
Discord command therefore stores a deliberately small state per card:

    0 = missing, 1 = owned once, 2 = at least one tradable duplicate

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
DUPLICATE = 2

FRESH_FOR = timedelta(hours=24)
AGING_FOR = timedelta(hours=48)
MATCHABLE_FOR = timedelta(hours=72)


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
    returns: tuple[str, ...]


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
    """Return one of the three supported inventory states."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return OWNED
    if numeric <= MISSING:
        return MISSING
    if numeric >= DUPLICATE:
        return DUPLICATE
    return OWNED


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
            elif current == DUPLICATE or card.id not in result:
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
        return "Your collection must be confirmed within the last 72 hours."
    if not inventory_is_matchable(holder, now=now, max_age=max_age):
        return "The holder's collection is no longer current."

    requester_cards = normalize_cards(requester.get("cards"))
    holder_cards = normalize_cards(holder.get("cards"))
    if requester_cards.get(wanted.id, OWNED) != MISSING:
        return "You no longer list the requested card as missing."
    if requester_cards.get(given.id, OWNED) < DUPLICATE:
        return "You no longer list the offered card as a duplicate."
    if holder_cards.get(wanted.id, OWNED) < DUPLICATE:
        return "The holder no longer lists the requested card as a duplicate."
    if holder_cards.get(given.id, OWNED) != MISSING:
        return "The holder no longer lists your offered card as missing."
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
                and candidate_cards.get(card.id, OWNED) == MISSING
            ]
            exchanges.append(CategoryExchange(
                category=category_id,
                offers=tuple(category_offers),
                returns=tuple(category_returns),
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

        returns = tuple(
            other.id
            for other in CATEGORY_CARDS[card.category]
            if requester_cards.get(other.id, OWNED) >= DUPLICATE
            and candidate_cards.get(other.id, OWNED) == MISSING
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
