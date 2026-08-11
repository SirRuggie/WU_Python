"""Regression tests for the generated collection board."""

from __future__ import annotations

import io
import re
from hashlib import sha256

import pytest
from PIL import Image, ImageDraw

from utils import card_board
from utils.card_board import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    CARD_ARTWORK_DIR,
    GRID_LEFT,
    GRID_TOP,
    MAX_ARTWORK_EDGE,
    OWNED_SPARE_UNVERIFIED,
    TILE_GAP_Y,
    TILE_HEIGHT,
    TRADE_STRIP_HEIGHT,
    TRADE_STRIP_WIDTH,
    load_bundled_card_artwork,
    render_card_board,
    render_inventory_card_board,
    render_trade_strip,
)
from utils.cards import CARDS, DUPLICATE, MISSING, OWNED


def _artwork(color=(30, 150, 210)):
    return Image.new("RGB", (80, 80), color)


def test_board_renders_one_bounded_png_with_all_state_counts():
    values = {card.id: OWNED for card in CARDS}
    values[CARDS[0].id] = MISSING
    values[CARDS[1].id] = DUPLICATE
    values.pop(CARDS[2].id)

    result = render_card_board(
        values,
        {card.id: _artwork() for card in CARDS},
        player_name="Wolverine",
    )

    assert result.filename == "clash-cards-board.png"
    assert result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(result.png_bytes) < 8 * 1024 * 1024
    with Image.open(io.BytesIO(result.png_bytes)) as rendered:
        assert rendered.size == (BOARD_WIDTH, BOARD_HEIGHT)
        assert rendered.mode == "RGB"

    assert result.collected_count == 58
    assert result.missing_card_ids == (CARDS[0].id,)
    assert result.duplicate_card_ids == (CARDS[1].id,)
    assert not result.spare_unverified_card_ids
    assert result.unknown_card_ids == (CARDS[2].id,)
    assert result.alt_text.startswith(
        "Wolverine's Clash of Cards collection: 58 of 60 collected"
    )


def test_bundled_artwork_covers_the_catalog_without_mutating_files():
    artwork = load_bundled_card_artwork()

    assert set(artwork) == {card.id for card in CARDS}
    assert len(list(CARD_ARTWORK_DIR.glob("*.webp"))) == len(CARDS)
    assert all(image.mode == "RGBA" for image in artwork.values())
    assert all(image.width <= 306 and image.height <= 306 for image in artwork.values())


def test_bundled_artwork_matches_the_pinned_notice_checksums():
    notice = (CARD_ARTWORK_DIR / "NOTICE.md").read_text(encoding="utf-8")
    manifest = dict(re.findall(
        r"^\| `([^`]+)` \| `[^`]+` \| `([0-9a-f]{64})` \|$",
        notice,
        re.MULTILINE,
    ))

    assert set(manifest) == {card.id for card in CARDS}
    for card in CARDS:
        payload = (CARD_ARTWORK_DIR / f"{card.id}.webp").read_bytes()
        assert sha256(payload).hexdigest() == manifest[card.id]
    assert (CARD_ARTWORK_DIR / "LICENSE-GPL-3.0.txt").is_file()


def test_footer_starts_below_the_last_card_row():
    last_row_bottom = GRID_TOP + 9 * (TILE_HEIGHT + TILE_GAP_Y) + TILE_HEIGHT
    footer_top = BOARD_HEIGHT - 71

    assert last_row_bottom < footer_top


def test_inventory_board_cache_normalizes_mapping_order_and_unknown_keys():
    card_board._render_inventory_card_board_cached.cache_clear()
    first = render_inventory_card_board(
        {CARDS[0].id: MISSING, CARDS[1].id: DUPLICATE},
        player_name="Wolverine",
    )
    second = render_inventory_card_board(
        {"not_a_card": OWNED, CARDS[1].id: DUPLICATE, CARDS[0].id: MISSING},
        player_name="Wolverine",
    )

    assert first is second
    cache = card_board._render_inventory_card_board_cached.cache_info()
    assert cache.misses == 1
    assert cache.hits == 1
    assert cache.maxsize == 32


def test_absent_and_unrecognized_states_fail_closed_as_unknown():
    result = render_card_board(
        {
            CARDS[0].id: None,
            CARDS[1].id: "ambiguous",
            CARDS[2].id: object(),
        }
    )

    assert result.collected_count == 0
    assert len(result.unknown_card_ids) == len(CARDS)
    assert not result.missing_card_ids
    assert not result.duplicate_card_ids
    assert not result.spare_unverified_card_ids


def test_string_scan_states_and_numeric_inventory_states_match():
    result = render_card_board(
        {
            CARDS[0].id: "missing",
            CARDS[1].id: "owned",
            CARDS[2].id: "duplicate",
            CARDS[3].id: 0,
            CARDS[4].id: 1,
            CARDS[5].id: 8,
            CARDS[6].id: OWNED_SPARE_UNVERIFIED,
        }
    )

    assert result.missing_card_ids == (CARDS[0].id, CARDS[3].id)
    assert result.duplicate_card_ids == (CARDS[2].id, CARDS[5].id)
    assert result.spare_unverified_card_ids == (CARDS[6].id,)
    assert result.collected_count == 5
    assert len(result.unknown_card_ids) == len(CARDS) - 7


def test_spare_unverified_is_owned_colored_and_not_unknown():
    values = {card.id: OWNED for card in CARDS}
    values[CARDS[0].id] = OWNED_SPARE_UNVERIFIED

    result = render_card_board(values, player_name="Wolverine")

    assert result.collected_count == len(CARDS)
    assert result.spare_unverified_card_ids == (CARDS[0].id,)
    assert not result.unknown_card_ids
    assert not result.duplicate_card_ids
    assert "1 possible spares to check" in result.alt_text
    assert "Possible spares needing a check: Barbarian." in result.alt_text
    with Image.open(io.BytesIO(result.png_bytes)) as rendered:
        # The tile keeps its Elixir category frame instead of unknown gray.
        assert rendered.getpixel((GRID_LEFT + 4, GRID_TOP + 45)) == (211, 65, 218)
        # The top-right possible-spare badge is yellow.
        assert rendered.getpixel((GRID_LEFT + 122, GRID_TOP + 18)) == (250, 201, 38)


def test_artwork_is_not_mutated_and_invalid_artwork_falls_back():
    art = _artwork((10, 20, 30))
    original = art.tobytes()
    too_large = Image.new("RGB", (MAX_ARTWORK_EDGE + 1, 1), (1, 2, 3))

    result = render_card_board(
        {CARDS[0].id: OWNED, CARDS[1].id: OWNED},
        {CARDS[0].id: art, CARDS[1].id: too_large},
    )

    assert result.png_bytes
    assert art.size == (80, 80)
    assert art.mode == "RGB"
    assert art.tobytes() == original


def test_alt_text_is_bounded_for_discord_attachment_descriptions():
    result = render_card_board(
        {card.id: MISSING for card in CARDS},
        player_name="A" * 900,
    )

    assert len(result.alt_text) <= 1_000
    assert result.alt_text.endswith("...")


def test_rendered_copy_is_ascii_until_a_unicode_font_is_bundled():
    canvas = Image.new("RGB", (100, 40))
    with pytest.raises(ValueError, match="requires ASCII"):
        card_board._centered_text(
            ImageDraw.Draw(canvas),
            (0, 0, 100, 40),
            "Unicode bullet: •",
            font=card_board._font(12),
            fill=(255, 255, 255),
        )

    board = render_card_board({}, player_name="José 🔥")
    trade = render_trade_strip(
        "barbarian",
        "archer",
        requester_name="José 🔥",
        holder_name="Zoë",
    )
    assert board.png_bytes and trade.png_bytes
    assert "José 🔥" in board.alt_text
    assert "José 🔥" in trade.alt_text


def test_trade_strip_renders_wanted_offer_and_bounded_compatible_alternatives():
    result = render_trade_strip(
        "barbarian",
        "archer",
        ["giant", "goblin", "wizard", "dragon", "minion", "archer"],
        requester_name="Shaun",
        holder_name="Wolverine",
    )

    assert result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(result.png_bytes)) as rendered:
        assert rendered.size == (TRADE_STRIP_WIDTH, TRADE_STRIP_HEIGHT)
    assert result.other_offer_ids == ("giant", "goblin", "wizard")
    assert result.alt_text == (
        "Card trade: Shaun needs Barbarian from Wolverine and offers Archer. "
        "Other compatible offers: Giant, Goblin, Wizard."
    )


def test_trade_strip_rejects_cross_category_trade():
    try:
        render_trade_strip("barbarian", "minion")
    except ValueError as error:
        assert str(error) == "card trades must remain inside one category"
    else:  # pragma: no cover - explicit oracle if validation disappears.
        raise AssertionError("cross-category trade was accepted")


def test_trade_strip_alt_text_is_bounded():
    result = render_trade_strip(
        "barbarian",
        "archer",
        requester_name="A" * 1_500,
    )

    assert len(result.alt_text) <= 1_000
    assert result.alt_text.endswith("...")
