"""Regression tests for the generated collection board."""

from __future__ import annotations

import io
import math
import re
from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest
from PIL import Image, ImageDraw

from utils import card_board
from utils.card_board import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    CARD_ARTWORK_DIR,
    CARD_THUMBNAIL_SIZE,
    CATEGORY_ACCENTS,
    CATEGORY_COLORS,
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
    render_card_thumbnail,
    render_inventory_card_board,
    render_trade_strip,
)
from utils.cards import CARDS, CATEGORY_CARDS, DUPLICATE, MISSING, OWNED


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


def test_category_rgb_frames_and_discord_accents_share_one_exact_palette():
    assert dict(CATEGORY_ACCENTS) == {
        "elixir": 0xDB4EE1,
        "dark_elixir": 0x9424B5,
        "builder_base": 0x4D91E5,
        "super_troop": 0xF16F2F,
    }
    assert dict(CATEGORY_COLORS) == {
        category_id: (
            (accent >> 16) & 0xFF,
            (accent >> 8) & 0xFF,
            accent & 0xFF,
        )
        for category_id, accent in CATEGORY_ACCENTS.items()
    }


@pytest.mark.parametrize(
    ("card_id", "state", "state_slug", "alt_fragment"),
    (
        ("barbarian", "owned", "owned", "owned (one copy)"),
        ("minion", "missing", "missing", "Grayscale card art with an X"),
        ("raged_barbarian", "duplicate", "duplicate", "x2 or more"),
        (
            "super_barbarian",
            "possible-spare",
            "possible-spare",
            "possible spare needs checking",
        ),
    ),
)
def test_card_thumbnail_renders_each_state_as_an_accessible_bounded_png(
    card_id,
    state,
    state_slug,
    alt_fragment,
):
    result = render_card_thumbnail(card_id, state)

    assert result.filename == f"clash-card-{card_id}-{state_slug}.png"
    assert result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(result.png_bytes) < 512 * 1024
    assert alt_fragment in result.alt_text
    assert len(result.alt_text) <= 1_000
    with Image.open(io.BytesIO(result.png_bytes)) as rendered:
        assert rendered.size == (CARD_THUMBNAIL_SIZE, CARD_THUMBNAIL_SIZE)
        assert rendered.mode == "RGB"
        # The focused tile and Discord category container use the same accent.
        assert rendered.getpixel((13, CARD_THUMBNAIL_SIZE // 2)) == (
            CATEGORY_COLORS[CARDS_BY_TEST_ID[card_id]]
        )


CARDS_BY_TEST_ID = {
    "barbarian": "elixir",
    "minion": "dark_elixir",
    "raged_barbarian": "builder_base",
    "super_barbarian": "super_troop",
}


def test_missing_thumbnail_is_grayscale_inside_its_category_frame():
    owned = render_card_thumbnail("barbarian", OWNED)
    missing = render_card_thumbnail("barbarian", MISSING)

    with Image.open(io.BytesIO(owned.png_bytes)) as rendered:
        owned_pixels = rendered.crop((26, 26, 230, 226)).get_flattened_data()
        assert any(red != green or green != blue for red, green, blue in owned_pixels)
    with Image.open(io.BytesIO(missing.png_bytes)) as rendered:
        missing_pixels = rendered.crop((26, 26, 230, 226)).get_flattened_data()
        assert all(red == green == blue for red, green, blue in missing_pixels)
        assert rendered.getpixel((13, CARD_THUMBNAIL_SIZE // 2)) == (
            CATEGORY_COLORS["elixir"]
        )


def test_card_thumbnail_badges_are_distinct_and_cache_is_canonical():
    card_id = "barbarian"
    duplicate = render_card_thumbnail(card_id, DUPLICATE)
    duplicate_alias = render_card_thumbnail(card_id.upper(), "duplicate")
    possible = render_card_thumbnail(card_id, OWNED_SPARE_UNVERIFIED)
    possible_alias = render_card_thumbnail(card_id, "possible spare")

    assert duplicate is duplicate_alias
    assert possible is possible_alias
    assert duplicate.png_bytes != possible.png_bytes
    with Image.open(io.BytesIO(duplicate.png_bytes)) as rendered:
        assert rendered.getpixel((172, 23)) == card_board.DUPLICATE_BADGE
    with Image.open(io.BytesIO(possible.png_bytes)) as rendered:
        assert rendered.getpixel((216, 20)) == card_board.DUPLICATE_BADGE


def test_card_thumbnail_result_is_immutable_and_rejects_unknown_inputs():
    result = render_card_thumbnail("barbarian", OWNED)

    with pytest.raises(FrozenInstanceError):
        result.filename = "changed.png"
    with pytest.raises(ValueError, match="card id must be in the catalog"):
        render_card_thumbnail("not-a-card", OWNED)
    with pytest.raises(ValueError, match="card state must be"):
        render_card_thumbnail("barbarian", "unknown")


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
    rows = math.ceil(len(CARDS) / card_board.BOARD_COLUMNS)
    last_row_bottom = (
        GRID_TOP + (rows - 1) * (TILE_HEIGHT + TILE_GAP_Y) + TILE_HEIGHT
    )
    footer_top = BOARD_HEIGHT - 71

    assert last_row_bottom < footer_top


def test_the_board_is_landscape_so_discord_does_not_height_cap_it():
    """Discord caps an embedded image near 310px tall and gives it ~490 wide.

    A portrait board is scaled by height and renders about 219 wide, wasting
    the width. This pins the shape rather than the exact pixel numbers.
    """
    assert BOARD_WIDTH > BOARD_HEIGHT
    assert card_board.BOARD_COLUMNS * card_board.BOARD_ROWS == len(CARDS)
    displayed = min(490 / BOARD_WIDTH, 310 / BOARD_HEIGHT)
    tile_on_screen = card_board.TILE_WIDTH * displayed
    # The previous 6x10 portrait board landed at about 36px per tile.
    assert tile_on_screen > 40


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
        assert rendered.getpixel((GRID_LEFT + 4, GRID_TOP + 45)) == (
            CATEGORY_COLORS["elixir"]
        )
        # The possible-spare badge sits on the tile's bottom edge, where the
        # game puts its own xN badge.
        badge_row = GRID_TOP + TILE_HEIGHT - 8
        assert any(
            rendered.getpixel((x, badge_row)) == (250, 201, 38)
            for x in range(GRID_LEFT + 55, GRID_LEFT + 95)
        )


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


def test_category_strip_renders_one_category_larger_than_the_board():
    values = {card.id: OWNED for card in CARDS}
    strip = card_board.render_category_strip("elixir", values)

    with Image.open(io.BytesIO(strip.png_bytes)) as rendered:
        strip_size = rendered.size
    board = render_card_board(values, player_name="Wolverine")
    with Image.open(io.BytesIO(board.png_bytes)) as rendered:
        board_size = rendered.size

    # Both are scaled into the same media box, so the strip's larger tiles come
    # from it being scaled down less, not from a bigger source tile.
    strip_scale = min(490 / strip_size[0], 310 / strip_size[1])
    board_scale = min(490 / board_size[0], 310 / board_size[1])
    assert strip_scale > board_scale * 1.5

    assert strip.filename == "clash-cards-elixir.png"
    assert strip.collected_count == len(CATEGORY_CARDS["elixir"])
    assert not strip.missing_card_ids


def test_category_strip_states_cover_only_that_category():
    values = {card.id: OWNED for card in CARDS}
    values[CATEGORY_CARDS["elixir"][0].id] = MISSING
    values[CATEGORY_CARDS["dark_elixir"][0].id] = MISSING

    strip = card_board.render_category_strip("elixir", values)

    assert strip.missing_card_ids == (CATEGORY_CARDS["elixir"][0].id,)
    assert strip.collected_count == len(CATEGORY_CARDS["elixir"]) - 1


def test_category_strip_rejects_an_unknown_category():
    with pytest.raises(ValueError):
        card_board.render_category_strip("nope", {})


def test_category_strip_highlight_does_not_change_the_accounting():
    values = {card.id: DUPLICATE for card in CARDS}
    plain = card_board.render_category_strip("super_troop", values)
    ringed = card_board.render_category_strip(
        "super_troop", values, highlight_card_id=CATEGORY_CARDS["super_troop"][0].id
    )

    assert plain.duplicate_card_ids == ringed.duplicate_card_ids
    assert plain.collected_count == ringed.collected_count
    assert plain.png_bytes != ringed.png_bytes
