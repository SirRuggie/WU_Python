"""Render Discord-friendly visual Clash of Cards collection artwork.

The full-board renderer is intentionally asset-source agnostic.  Callers can
pass validated, in-memory artwork, and it returns one composite PNG plus an
accessibility description.  The focused-thumbnail renderer uses the
checksum-pinned local artwork.  Neither path fetches, hotlinks, persists, or
learns artwork, and neither treats an absent inventory state as owned.

Supercell's fan-content policy permits non-commercial fan guide tools but
requires an unofficiality notice.  Collection state is primarily communicated
with frames and badges around the art; focused missing-card thumbnails also
apply a transient in-memory grayscale treatment and never overwrite the
checked-in source files.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

from utils.cards import (
    CARDS,
    CARD_BY_ID,
    CATEGORIES,
    CATEGORY_BY_ID,
    CATEGORY_CARDS,
    DUPLICATE,
    MISSING,
    OWNED,
)


UNKNOWN = "unknown"
OWNED_SPARE_UNVERIFIED = "owned_spare_unverified"
BoardState = int | str

BOARD_WIDTH = 1120
BOARD_HEIGHT = 1580
TRADE_STRIP_WIDTH = 1120
TRADE_STRIP_HEIGHT = 360
CARD_THUMBNAIL_SIZE = 256
BOARD_COLUMNS = 6
TILE_WIDTH = 150
TILE_HEIGHT = 112
TILE_GAP_X = 16
TILE_GAP_Y = 15
GRID_LEFT = 70
GRID_TOP = 218

MAX_ARTWORK_EDGE = 4096
MAX_ARTWORK_PIXELS = 4_000_000

BACKGROUND = (42, 35, 31)
PARCHMENT = (218, 191, 155)
PARCHMENT_DARK = (181, 147, 111)
TILE_INTERIOR = (73, 62, 57)
TEXT_DARK = (45, 38, 34)
TEXT_LIGHT = (252, 244, 222)
MISSING_FRAME = (130, 130, 130)
UNKNOWN_FRAME = (89, 82, 78)
DUPLICATE_BADGE = (250, 201, 38)
DUPLICATE_TEXT = (65, 48, 12)

# Single-source category accents for both Discord containers and rendered art.
# The integer form can be passed directly to Hikari; the RGB form is used by
# Pillow.  Keeping both derived from the same values prevents the UI pills and
# the card frames from drifting apart.
CATEGORY_ACCENTS: Mapping[str, int] = MappingProxyType({
    "elixir": 0xDB4EE1,
    "dark_elixir": 0x9424B5,
    "builder_base": 0x4D91E5,
    "super_troop": 0xF16F2F,
})
CATEGORY_COLORS: Mapping[str, tuple[int, int, int]] = MappingProxyType({
    category_id: (
        (accent >> 16) & 0xFF,
        (accent >> 8) & 0xFF,
        accent & 0xFF,
    )
    for category_id, accent in CATEGORY_ACCENTS.items()
})

DISCLAIMER = (
    "This material is unofficial and is not endorsed by Supercell. "
    "supercell.com/fan-content-policy"
)

CARD_ARTWORK_DIR = Path(__file__).resolve().parents[1] / "assets" / "cards"


@dataclass(frozen=True, slots=True)
class RenderedCardBoard:
    """A deterministic PNG and the text needed to make it accessible."""

    png_bytes: bytes
    filename: str
    alt_text: str
    collected_count: int
    missing_card_ids: tuple[str, ...]
    duplicate_card_ids: tuple[str, ...]
    spare_unverified_card_ids: tuple[str, ...]
    unknown_card_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RenderedTradeStrip:
    """A compact proposal image suitable for a public post or private DM."""

    png_bytes: bytes
    filename: str
    alt_text: str
    wanted_card_id: str
    offered_card_id: str
    other_offer_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RenderedCardThumbnail:
    """One immutable, accessible card tile for a Discord Thumbnail."""

    png_bytes: bytes
    filename: str
    alt_text: str


@lru_cache(maxsize=1)
def _bundled_artwork() -> Mapping[str, Image.Image]:
    """Load the checked-in, checksum-pinned canonical icon set once."""
    artwork: dict[str, Image.Image] = {}
    for card in CARDS:
        path = CARD_ARTWORK_DIR / f"{card.id}.webp"
        try:
            with Image.open(path) as image:
                if image.format != "WEBP":
                    continue
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_ARTWORK_EDGE
                    or height > MAX_ARTWORK_EDGE
                    or width * height > MAX_ARTWORK_PIXELS
                ):
                    continue
                image.load()
                artwork[card.id] = image.convert("RGBA")
        except (FileNotFoundError, OSError, ValueError):
            continue
    return MappingProxyType(artwork)


def load_bundled_card_artwork() -> dict[str, Image.Image]:
    """Return caller-owned copies of the bundled canonical card artwork."""
    return {card_id: image.copy() for card_id, image in _bundled_artwork().items()}


def _font(size: int):
    """Use Pillow's bundled font without a host-specific font dependency."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - bridge for older Pillow releases.
        return ImageFont.load_default()


def _state(value: object) -> int | str:
    if isinstance(value, str):
        normalized = value.casefold().strip()
        if normalized == "missing":
            return MISSING
        if normalized == "owned":
            return OWNED
        if normalized == "duplicate":
            return DUPLICATE
        if normalized in {
            OWNED_SPARE_UNVERIFIED,
            "owned_unverified",
            "spare_unknown",
            "possible-spare",
            "possible_spare",
            "possible spare",
        }:
            return OWNED_SPARE_UNVERIFIED
        return UNKNOWN
    if isinstance(value, bool):
        return OWNED if value else MISSING
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return UNKNOWN
    if numeric <= MISSING:
        return MISSING
    if numeric >= DUPLICATE:
        return DUPLICATE
    return OWNED


def _bound_alt_text(text: str) -> str:
    if len(text) <= 1_000:
        return text
    return f"{text[:996].rstrip(' ,.;')}..."[:1_000]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    max_size: int,
    min_size: int,
):
    for size in range(max_size, min_size - 1, -1):
        font = _font(size)
        if _text_width(draw, text, font) <= max_width:
            return text, font

    font = _font(min_size)
    lower = 0
    upper = len(text)
    while lower < upper:
        midpoint = (lower + upper + 1) // 2
        if _text_width(draw, f"{text[:midpoint]}...", font) <= max_width:
            lower = midpoint
        else:
            upper = midpoint - 1
    shortened = text[:lower]
    return (f"{shortened}..." if shortened else "..."), font


def _centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    font,
    fill: tuple[int, int, int],
) -> None:
    if not text.isascii():
        raise ValueError("visual board copy requires ASCII or a bundled font")
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        (
            left + (right - left - width) / 2,
            top + (bottom - top - height) / 2 - bounds[1],
        ),
        text,
        font=font,
        fill=fill,
    )


def _artwork_thumbnail(artwork: object, size: tuple[int, int]) -> Image.Image | None:
    if not isinstance(artwork, Image.Image):
        return None
    width, height = artwork.size
    if (
        width < 1
        or height < 1
        or width > MAX_ARTWORK_EDGE
        or height > MAX_ARTWORK_EDGE
        or width * height > MAX_ARTWORK_PIXELS
    ):
        return None
    thumbnail = artwork.convert("RGBA")
    thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
    return thumbnail


def _paste_artwork(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_id: str,
    card_name: str,
    artwork_by_card_id: Mapping[str, object],
    box: tuple[int, int, int, int],
    *,
    desaturate: bool = False,
) -> None:
    left, top, right, bottom = box
    thumbnail = _artwork_thumbnail(
        artwork_by_card_id.get(card_id),
        (right - left, bottom - top),
    )
    if thumbnail is None:
        initials = "".join(part[0] for part in card_name.split()[:2]).upper()
        _centered_text(
            draw,
            box,
            initials or "?",
            font=_font(28),
            fill=(205, 193, 178),
        )
        return

    if desaturate:
        # Transient, in memory only.  The bundled asset is never written to.
        if thumbnail.mode == "RGBA":
            alpha = thumbnail.getchannel("A")
            thumbnail = thumbnail.convert("L").convert("RGBA")
            thumbnail.putalpha(alpha)
        else:
            thumbnail = thumbnail.convert("L").convert("RGBA")

    x = left + (right - left - thumbnail.width) // 2
    y = top + (bottom - top - thumbnail.height) // 2
    canvas.paste(thumbnail, (x, y), thumbnail)


def _thumbnail_state(value: object) -> int | str:
    """Normalize one of the four states supported by a focused card tile."""
    state = _state(value)
    if state not in {MISSING, OWNED, DUPLICATE, OWNED_SPARE_UNVERIFIED}:
        raise ValueError(
            "card state must be missing, owned, duplicate, or possible-spare"
        )
    return state


def _thumbnail_state_slug(state: int | str) -> str:
    if state == MISSING:
        return "missing"
    if state == DUPLICATE:
        return "duplicate"
    if state == OWNED_SPARE_UNVERIFIED:
        return "possible-spare"
    return "owned"


def _thumbnail_alt_text(card, state: int | str) -> str:
    category_name = CATEGORY_BY_ID[card.category].name
    if state == MISSING:
        detail = "missing. Grayscale card art with an X marker."
    elif state == DUPLICATE:
        detail = "duplicate available (x2 or more)."
    elif state == OWNED_SPARE_UNVERIFIED:
        detail = "owned; possible spare needs checking (question-mark badge)."
    else:
        detail = "owned (one copy)."
    return f"{card.name}, {category_name}: {detail}"


@lru_cache(maxsize=len(CARDS) * 4)
def _render_card_thumbnail_cached(
    card_id: str,
    state: int | str,
) -> RenderedCardThumbnail:
    """Render one canonical card/state pair from the checked-in artwork."""
    card = CARD_BY_ID[card_id]
    accent = CATEGORY_COLORS[card.category]
    missing = state == MISSING

    canvas = Image.new(
        "RGB",
        (CARD_THUMBNAIL_SIZE, CARD_THUMBNAIL_SIZE),
        (30, 27, 26),
    )
    draw = ImageDraw.Draw(canvas)
    # A compact version of the in-game tile: category frame, dark inset, art.
    draw.rounded_rectangle(
        (8, 10, CARD_THUMBNAIL_SIZE - 8, CARD_THUMBNAIL_SIZE - 6),
        radius=23,
        fill=(24, 22, 21),
    )
    draw.rounded_rectangle(
        (7, 7, CARD_THUMBNAIL_SIZE - 9, CARD_THUMBNAIL_SIZE - 11),
        radius=22,
        fill=accent,
        outline=(38, 32, 30),
        width=4,
    )
    interior = (67, 67, 67) if missing else TILE_INTERIOR
    art_box = (19, 19, CARD_THUMBNAIL_SIZE - 21, CARD_THUMBNAIL_SIZE - 23)
    draw.rounded_rectangle(
        art_box,
        radius=15,
        fill=interior,
        outline=(210, 210, 210) if missing else (235, 219, 198),
        width=2,
    )

    artwork = _artwork_thumbnail(
        _bundled_artwork().get(card.id),
        (art_box[2] - art_box[0] - 8, art_box[3] - art_box[1] - 8),
    )
    if artwork is None:
        initials = "".join(part[0] for part in card.name.split()[:2]).upper()
        _centered_text(
            draw,
            art_box,
            initials or "?",
            font=_font(48),
            fill=(215, 215, 215) if missing else TEXT_LIGHT,
        )
    else:
        if missing:
            alpha = artwork.getchannel("A")
            artwork = artwork.convert("L").convert("RGBA")
            artwork.putalpha(alpha)
        x = art_box[0] + (art_box[2] - art_box[0] - artwork.width) // 2
        y = art_box[1] + (art_box[3] - art_box[1] - artwork.height) // 2
        canvas.paste(artwork, (x, y), artwork)

    if state == DUPLICATE:
        badge = (163, 14, 244, 60)
        draw.rounded_rectangle(
            badge,
            radius=13,
            fill=DUPLICATE_BADGE,
            outline=(112, 77, 15),
            width=3,
        )
        _centered_text(
            draw,
            badge,
            "x2+",
            font=_font(24),
            fill=DUPLICATE_TEXT,
        )
    elif state == OWNED_SPARE_UNVERIFIED:
        badge = (188, 13, 244, 69)
        draw.ellipse(
            badge,
            fill=DUPLICATE_BADGE,
            outline=(112, 77, 15),
            width=3,
        )
        _centered_text(
            draw,
            badge,
            "?",
            font=_font(30),
            fill=DUPLICATE_TEXT,
        )
    elif missing:
        # The two-layer X remains legible after Discord scales the tile down.
        diagonals = (
            (43, 43, CARD_THUMBNAIL_SIZE - 43, CARD_THUMBNAIL_SIZE - 47),
            (CARD_THUMBNAIL_SIZE - 43, 43, 43, CARD_THUMBNAIL_SIZE - 47),
        )
        for diagonal in diagonals:
            draw.line(diagonal, fill=(45, 45, 45), width=22)
        for diagonal in diagonals:
            draw.line(diagonal, fill=(235, 235, 235), width=9)

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    slug = _thumbnail_state_slug(state)
    return RenderedCardThumbnail(
        png_bytes=output.getvalue(),
        filename=f"clash-card-{card.id}-{slug}.png",
        alt_text=_thumbnail_alt_text(card, state),
    )


def render_card_thumbnail(
    card_id: str,
    state: BoardState,
) -> RenderedCardThumbnail:
    """Return a cached focused card tile for a Discord section thumbnail.

    Only catalog ids and the four user-facing collection states are accepted.
    The returned frozen dataclass contains immutable bytes and no mutable
    Pillow object, so callers can safely share cached results across views.
    """
    normalized_id = str(card_id).casefold().strip()
    if normalized_id not in CARD_BY_ID:
        raise ValueError("card id must be in the catalog")
    return _render_card_thumbnail_cached(
        normalized_id,
        _thumbnail_state(state),
    )


def _draw_check(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    *,
    fill: tuple[int, int, int] = (74, 222, 96),
    width: int = 4,
) -> None:
    """Draw a completion check as a stroke.

    Pillow's bundled font renders no check glyph, and the ASCII-only rule in
    docs/clash-of-cards-visuals.md forbids substituting one. A short polyline
    needs no font and no licence.
    """
    draw.line(
        (
            center_x - 9, center_y,
            center_x - 3, center_y + 7,
            center_x + 10, center_y - 8,
        ),
        fill=fill,
        width=width,
        joint="curve",
    )


def _draw_category_tabs(
    draw: ImageDraw.ImageDraw,
    states: Mapping[str, int | str],
) -> None:
    tab_left = 54
    tab_top = 118
    tab_gap = 12
    tab_width = (BOARD_WIDTH - tab_left * 2 - tab_gap * 3) // 4
    for index, category in enumerate(CATEGORIES):
        left = tab_left + index * (tab_width + tab_gap)
        right = left + tab_width
        color = CATEGORY_COLORS[category.id]
        draw.rounded_rectangle(
            (left, tab_top, right, tab_top + 72),
            radius=14,
            fill=color,
            outline=(255, 221, 160),
            width=3,
        )
        category_states = [states[card.id] for card in CATEGORY_CARDS[category.id]]
        collected = sum(
            state in {OWNED, DUPLICATE, OWNED_SPARE_UNVERIFIED}
            for state in category_states
        )
        complete = collected == len(category_states)
        label, label_font = _fit_text(
            draw,
            category.name,
            tab_width - 16,
            max_size=18,
            min_size=12,
        )
        _centered_text(
            draw,
            (left + 6, tab_top + 7, right - 6, tab_top + 37),
            label,
            font=label_font,
            fill=TEXT_LIGHT,
        )
        count_right = right - 6 - (30 if complete else 0)
        _centered_text(
            draw,
            (left + 6, tab_top + 36, count_right, tab_top + 67),
            f"{collected}/{len(category_states)}",
            font=_font(22),
            fill=TEXT_LIGHT,
        )
        if complete:
            # Pillow's bundled font has no check glyph, so draw the stroke.
            _draw_check(draw, count_right + 6, tab_top + 51)


def _draw_card_tile(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    index: int,
    card,
    state: int | str,
    artwork_by_card_id: Mapping[str, object],
) -> None:
    row, column = divmod(index, BOARD_COLUMNS)
    left = GRID_LEFT + column * (TILE_WIDTH + TILE_GAP_X)
    top = GRID_TOP + row * (TILE_HEIGHT + TILE_GAP_Y)
    right = left + TILE_WIDTH
    bottom = top + TILE_HEIGHT

    if state == MISSING:
        frame = MISSING_FRAME
    elif state == UNKNOWN:
        frame = UNKNOWN_FRAME
    else:
        frame = CATEGORY_COLORS[card.category]

    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=12,
        fill=frame,
        outline=(58, 44, 37),
        width=3,
    )
    # No per-tile caption.  At the size Discord renders this on a phone the
    # name is an illegible smudge, and the artwork is what identifies a card.
    # The freed height goes to the art box, which the game also fills entirely.
    art_box = (left + 6, top + 6, right - 6, bottom - 6)
    draw.rounded_rectangle(art_box, radius=8, fill=TILE_INTERIOR)
    _paste_artwork(
        canvas,
        draw,
        card.id,
        card.name,
        artwork_by_card_id,
        art_box,
        desaturate=state in {MISSING, UNKNOWN},
    )

    center_x = (left + right) // 2
    if state == DUPLICATE:
        badge = (center_x - 27, bottom - 21, center_x + 27, bottom + 5)
        draw.rounded_rectangle(
            badge,
            radius=10,
            fill=DUPLICATE_BADGE,
            outline=(112, 77, 15),
            width=2,
        )
        _centered_text(
            draw,
            badge,
            "x2+",
            font=_font(15),
            fill=DUPLICATE_TEXT,
        )
    elif state == OWNED_SPARE_UNVERIFIED:
        badge = (center_x - 15, bottom - 23, center_x + 15, bottom + 7)
        draw.ellipse(
            badge,
            fill=DUPLICATE_BADGE,
            outline=(112, 77, 15),
            width=2,
        )
        _centered_text(
            draw,
            badge,
            "?",
            font=_font(18),
            fill=DUPLICATE_TEXT,
        )
    elif state == MISSING:
        marker = (left + 5, top + 5, left + 34, top + 34)
        draw.ellipse(marker, fill=(70, 70, 70), outline=(230, 230, 230), width=2)
        _centered_text(
            draw,
            marker,
            "X",
            font=_font(19),
            fill=(245, 245, 245),
        )
    elif state == UNKNOWN:
        marker = (left + 5, top + 5, left + 34, top + 34)
        draw.ellipse(marker, fill=(55, 50, 48), outline=(230, 193, 82), width=2)
        _centered_text(
            draw,
            marker,
            "!",
            font=_font(19),
            fill=(255, 226, 130),
        )


def _draw_trade_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    card,
    artwork_by_card_id: Mapping[str, object],
    box: tuple[int, int, int, int],
    label: str,
) -> None:
    left, top, right, bottom = box
    color = CATEGORY_COLORS[card.category]
    draw.rounded_rectangle(
        box,
        radius=14,
        fill=color,
        outline=(255, 221, 160),
        width=3,
    )
    _centered_text(
        draw,
        (left + 5, top + 4, right - 5, top + 29),
        label,
        font=_font(13),
        fill=TEXT_LIGHT,
    )
    art_box = (left + 8, top + 31, right - 8, bottom - 42)
    draw.rounded_rectangle(art_box, radius=8, fill=TILE_INTERIOR)
    _paste_artwork(
        canvas,
        draw,
        card.id,
        card.name,
        artwork_by_card_id,
        art_box,
    )
    name, name_font = _fit_text(
        draw,
        card.name,
        right - left - 14,
        max_size=15,
        min_size=10,
    )
    _centered_text(
        draw,
        (left + 5, bottom - 38, right - 5, bottom - 5),
        name,
        font=name_font,
        fill=TEXT_LIGHT,
    )


def _draw_exchange_arrows(draw: ImageDraw.ImageDraw) -> None:
    color = (103, 75, 53)
    draw.line((267, 168, 383, 168), fill=color, width=8)
    draw.polygon(((383, 168), (364, 153), (364, 183)), fill=color)
    draw.line((383, 205, 267, 205), fill=color, width=8)
    draw.polygon(((267, 205), (286, 190), (286, 220)), fill=color)


def render_trade_strip(
    wanted_card_id: str,
    offered_card_id: str,
    other_offer_ids: tuple[str, ...] | list[str] = (),
    *,
    requester_name: str | None = None,
    holder_name: str | None = None,
    artwork_by_card_id: Mapping[str, object] | None = None,
) -> RenderedTradeStrip:
    """Render one same-category proposal with up to three alternatives."""
    wanted = CARD_BY_ID.get(str(wanted_card_id))
    offered = CARD_BY_ID.get(str(offered_card_id))
    if wanted is None or offered is None:
        raise ValueError("wanted and offered cards must be in the catalog")
    if wanted.category != offered.category:
        raise ValueError("card trades must remain inside one category")

    compatible: list[str] = []
    seen = {wanted.id, offered.id}
    for card_id in other_offer_ids:
        card = CARD_BY_ID.get(str(card_id))
        if (
            card is None
            or card.id in seen
            or card.category != wanted.category
        ):
            continue
        compatible.append(card.id)
        seen.add(card.id)
        if len(compatible) == 3:
            break

    artwork = (
        _bundled_artwork()
        if artwork_by_card_id is None
        else artwork_by_card_id
    )
    canvas = Image.new(
        "RGB",
        (TRADE_STRIP_WIDTH, TRADE_STRIP_HEIGHT),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (18, 16, TRADE_STRIP_WIDTH - 18, TRADE_STRIP_HEIGHT - 16),
        radius=20,
        fill=PARCHMENT,
        outline=(93, 66, 46),
        width=5,
    )
    draw.rounded_rectangle(
        (31, 28, TRADE_STRIP_WIDTH - 31, 80),
        radius=12,
        fill=(60, 53, 49),
    )
    requester = requester_name or "A family member"
    holder = holder_name or "the holder"
    display_requester = str(requester).encode("ascii", "replace").decode("ascii")
    display_holder = str(holder).encode("ascii", "replace").decode("ascii")
    heading = f"{display_requester} needs {wanted.name} from {display_holder}"
    heading, heading_font = _fit_text(
        draw,
        heading,
        TRADE_STRIP_WIDTH - 100,
        max_size=25,
        min_size=15,
    )
    _centered_text(
        draw,
        (45, 35, TRADE_STRIP_WIDTH - 45, 73),
        heading,
        font=heading_font,
        fill=TEXT_LIGHT,
    )

    _draw_trade_card(
        canvas,
        draw,
        card=wanted,
        artwork_by_card_id=artwork,
        box=(52, 96, 242, 286),
        label="WANTED",
    )
    _draw_exchange_arrows(draw)

    offer_ids = (offered.id, *compatible)
    offer_lefts = (414, 584, 754, 924)
    for index, card_id in enumerate(offer_ids):
        _draw_trade_card(
            canvas,
            draw,
            card=CARD_BY_ID[card_id],
            artwork_by_card_id=artwork,
            box=(offer_lefts[index], 96, offer_lefts[index] + 146, 286),
            label="OFFERS" if index == 0 else "ALSO WORKS",
        )

    footer_top = 310
    draw.line(
        (35, footer_top, TRADE_STRIP_WIDTH - 35, footer_top),
        fill=PARCHMENT_DARK,
        width=2,
    )
    _centered_text(
        draw,
        (45, footer_top + 5, TRADE_STRIP_WIDTH - 45, TRADE_STRIP_HEIGHT - 21),
        DISCLAIMER,
        font=_font(12),
        fill=TEXT_DARK,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    other_names = [CARD_BY_ID[card_id].name for card_id in compatible]
    alt = (
        f"Card trade: {requester} needs {wanted.name} from {holder} and offers "
        f"{offered.name}."
    )
    if other_names:
        alt += f" Other compatible offers: {', '.join(other_names)}."
    return RenderedTradeStrip(
        png_bytes=output.getvalue(),
        filename=f"card-trade-{wanted.id}-{offered.id}.png",
        alt_text=_bound_alt_text(alt),
        wanted_card_id=wanted.id,
        offered_card_id=offered.id,
        other_offer_ids=tuple(compatible),
    )


def _alt_text(
    *,
    player_name: str | None,
    collected: int,
    missing_names: list[str],
    duplicate_names: list[str],
    spare_unverified_names: list[str],
    unknown_names: list[str],
) -> str:
    owner = f"{player_name}'s " if player_name else ""
    parts = [
        f"{owner}Clash of Cards collection: {collected} of {len(CARDS)} collected; "
        f"{len(duplicate_names)} confirmed spares; "
        f"{len(spare_unverified_names)} possible spares to check; "
        f"{len(unknown_names)} ownership states not verified."
    ]
    if missing_names:
        parts.append(f"Missing: {', '.join(missing_names)}.")
    if duplicate_names:
        parts.append(f"Spares: {', '.join(duplicate_names)}.")
    if spare_unverified_names:
        parts.append(
            "Possible spares needing a check: "
            f"{', '.join(spare_unverified_names)}."
        )
    if unknown_names:
        parts.append(f"Not verified: {', '.join(unknown_names)}.")
    text = " ".join(parts)
    return _bound_alt_text(text)


def render_card_board(
    values: Mapping[str, BoardState] | None,
    artwork_by_card_id: Mapping[str, object] | None = None,
    *,
    player_name: str | None = None,
) -> RenderedCardBoard:
    """Return one visual board for all 60 cards.

    Missing keys and unrecognized values remain ``unknown``.  Artwork is
    optional, never changes the accounting, and is never written anywhere
    except into the returned composite PNG.
    """
    supplied = values or {}
    artwork = (
        _bundled_artwork()
        if artwork_by_card_id is None
        else artwork_by_card_id
    )
    states = {card.id: _state(supplied.get(card.id)) for card in CARDS}

    missing = [card for card in CARDS if states[card.id] == MISSING]
    duplicates = [card for card in CARDS if states[card.id] == DUPLICATE]
    spare_unverified = [
        card
        for card in CARDS
        if states[card.id] == OWNED_SPARE_UNVERIFIED
    ]
    unknown = [card for card in CARDS if states[card.id] == UNKNOWN]
    collected = sum(
        states[card.id] in {OWNED, DUPLICATE, OWNED_SPARE_UNVERIFIED}
        for card in CARDS
    )

    canvas = Image.new("RGB", (BOARD_WIDTH, BOARD_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (28, 22, BOARD_WIDTH - 28, BOARD_HEIGHT - 24),
        radius=22,
        fill=PARCHMENT,
        outline=(93, 66, 46),
        width=6,
    )
    draw.rounded_rectangle(
        (42, 35, BOARD_WIDTH - 42, 102),
        radius=14,
        fill=(60, 53, 49),
    )
    title = "Clash of Cards"
    if player_name:
        display_name = str(player_name).encode("ascii", "replace").decode("ascii")
        title = f"{display_name} - {title}"
    title, title_font = _fit_text(
        draw,
        title,
        BOARD_WIDTH - 120,
        max_size=32,
        min_size=18,
    )
    _centered_text(
        draw,
        (58, 39, BOARD_WIDTH - 58, 73),
        title,
        font=title_font,
        fill=TEXT_LIGHT,
    )
    # Only the clauses that apply.  The old line always printed all five, so a
    # finished collection still read "0 possible spares | 0 unknown".
    subtitle = [f"{collected}/{len(CARDS)} collected"]
    if missing:
        subtitle.append(f"{len(missing)} missing")
    if duplicates:
        subtitle.append(f"x2+ {len(duplicates)} spares")
    if spare_unverified:
        subtitle.append(f"? {len(spare_unverified)} to check")
    if unknown:
        subtitle.append(f"! {len(unknown)} unknown")
    _centered_text(
        draw,
        (58, 72, BOARD_WIDTH - 58, 98),
        "  |  ".join(subtitle),
        font=_font(16),
        fill=(226, 211, 188),
    )

    _draw_category_tabs(draw, states)
    for index, card in enumerate(CARDS):
        _draw_card_tile(
            canvas,
            draw,
            index=index,
            card=card,
            state=states[card.id],
            artwork_by_card_id=artwork,
        )

    footer_top = BOARD_HEIGHT - 71
    draw.line(
        (48, footer_top, BOARD_WIDTH - 48, footer_top),
        fill=PARCHMENT_DARK,
        width=2,
    )
    _centered_text(
        draw,
        (58, footer_top + 8, BOARD_WIDTH - 58, BOARD_HEIGHT - 31),
        DISCLAIMER,
        font=_font(13),
        fill=TEXT_DARK,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return RenderedCardBoard(
        png_bytes=output.getvalue(),
        filename="clash-cards-board.png",
        alt_text=_alt_text(
            player_name=player_name,
            collected=collected,
            missing_names=[card.name for card in missing],
            duplicate_names=[card.name for card in duplicates],
            spare_unverified_names=[card.name for card in spare_unverified],
            unknown_names=[card.name for card in unknown],
        ),
        collected_count=collected,
        missing_card_ids=tuple(card.id for card in missing),
        duplicate_card_ids=tuple(card.id for card in duplicates),
        spare_unverified_card_ids=tuple(card.id for card in spare_unverified),
        unknown_card_ids=tuple(card.id for card in unknown),
    )


@lru_cache(maxsize=32)
def _render_inventory_card_board_cached(
    states: tuple[int | str, ...],
    player_name: str | None,
) -> RenderedCardBoard:
    values = {card.id: state for card, state in zip(CARDS, states)}
    return render_card_board(
        values,
        _bundled_artwork(),
        player_name=player_name,
    )


def render_inventory_card_board(
    values: Mapping[str, BoardState] | None,
    *,
    player_name: str | None = None,
) -> RenderedCardBoard:
    """Render the common bundled-art dashboard path with a bounded PNG cache.

    The cache key contains only the canonical 60 normalized states and display
    name; irrelevant mapping keys and insertion order cannot fragment it.
    Thirty-two full boards are retained, bounding the typical cache payload to
    roughly 25 MiB with the current artwork and PNG output.
    """
    supplied = values or {}
    states = tuple(_state(supplied.get(card.id)) for card in CARDS)
    normalized_name = None if player_name is None else str(player_name)
    return _render_inventory_card_board_cached(states, normalized_name)
