"""Synthetic feasibility tests for the experimental card-image scanner."""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw

from utils import card_scan


CANVAS_SIZE = (900, 520)
BACKGROUND = (211, 184, 139)
FRAME = (188, 45, 201)
INTERIOR = (58, 53, 65)
OWNED_PORTRAIT = (30, 160, 210)
MISSING_PORTRAIT = (112, 112, 112)
AMBIGUOUS_PORTRAIT = (120, 111, 120)
BADGE = (246, 202, 22)
CARD_WIDTH = 90
CARD_HEIGHT = 130
CARD_X = (65, 205, 345, 485, 625, 765)


def _draw_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    state: str,
    *,
    frame: tuple[int, int, int] = FRAME,
) -> None:
    draw.rectangle(
        (x, y, x + CARD_WIDTH, y + CARD_HEIGHT),
        fill=frame,
    )
    draw.rectangle(
        (x + 8, y + 8, x + CARD_WIDTH - 8, y + CARD_HEIGHT - 8),
        fill=INTERIOR,
    )
    portrait = {
        card_scan.MISSING: MISSING_PORTRAIT,
        card_scan.OWNED: OWNED_PORTRAIT,
        card_scan.DUPLICATE: OWNED_PORTRAIT,
        card_scan.UNKNOWN: AMBIGUOUS_PORTRAIT,
    }[state]
    draw.rectangle(
        (x + 23, y + 22, x + CARD_WIDTH - 23, y + 82),
        fill=portrait,
    )
    if state == card_scan.DUPLICATE:
        draw.rounded_rectangle(
            (x + 25, y + 93, x + CARD_WIDTH - 25, y + 116),
            radius=5,
            fill=BADGE,
        )


def _fixture(
    rows: Sequence[Sequence[str]],
    *,
    row_y: Sequence[int] = (70, 300),
    xs: Sequence[int] = CARD_X,
    overlay_rows: frozenset[int] = frozenset(),
    frame: tuple[int, int, int] = FRAME,
    size: tuple[int, int] = CANVAS_SIZE,
    image_format: str = "PNG",
    quality: int = 95,
) -> bytes:
    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    for row_index, states in enumerate(rows):
        y = row_y[row_index]
        for x, state in zip(xs, states):
            _draw_card(draw, x, y, state, frame=frame)
        if row_index in overlay_rows:
            draw.rectangle(
                (0, y + CARD_HEIGHT + 1, size[0], y + CARD_HEIGHT + 18),
                fill=(35, 31, 39),
            )

    encoded = io.BytesIO()
    save_options = {"format": image_format}
    if image_format == "JPEG":
        save_options.update(quality=quality, subsampling=2)
    image.save(encoded, **save_options)
    return encoded.getvalue()


def _states(result: card_scan.ScanResult) -> list[list[str]]:
    return [[slot.state for slot in row.slots] for row in result.rows]


def test_preview_flags_make_persistence_and_identity_limits_explicit():
    result = card_scan.scan_visible_rows(_fixture([[card_scan.OWNED] * 6]))

    assert card_scan.EXPERIMENTAL is True
    assert card_scan.PERSISTENCE_SAFE is False
    assert result.experimental is True
    assert result.persistence_safe is False
    assert "experimental_preview_only" in result.warnings
    assert "card_identity_not_inferred" in result.warnings


def test_classifies_missing_owned_duplicate_and_ambiguous_portraits():
    expected = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.UNKNOWN,
        card_scan.OWNED,
        card_scan.MISSING,
    ]
    result = card_scan.scan_visible_rows(_fixture([expected]))

    assert len(result.rows) == 1
    assert _states(result) == [expected]
    assert len(result.rows[0].slots) == 6
    assert result.rows[0].slots[3].warnings == (
        "ambiguous_portrait_saturation",
    )
    assert result.rows[0].layout_confidence >= 0.9


def test_finds_two_rows_in_top_to_bottom_and_left_to_right_order():
    expected = [
        [card_scan.OWNED, card_scan.MISSING, card_scan.OWNED,
         card_scan.DUPLICATE, card_scan.OWNED, card_scan.MISSING],
        [card_scan.DUPLICATE, card_scan.OWNED, card_scan.MISSING,
         card_scan.OWNED, card_scan.DUPLICATE, card_scan.OWNED],
    ]
    result = card_scan.scan_visible_rows(_fixture(expected))

    assert _states(result) == expected
    assert [row.row for row in result.rows] == [1, 2]
    assert all(
        [slot.column for slot in row.slots] == [1, 2, 3, 4, 5, 6]
        for row in result.rows
    )
    assert result.rows[0].bounds.top < result.rows[1].bounds.top


def test_complete_row_is_kept_while_partial_row_is_only_warned_about():
    complete = [card_scan.OWNED] * 6
    partial = [card_scan.MISSING] * 5

    result = card_scan.scan_visible_rows(_fixture([complete, partial]))

    assert _states(result) == [complete]
    assert "non_six_or_irregular_cluster_ignored" in result.warnings


def test_jpeg_recompression_keeps_high_separation_states_but_not_gray_zone():
    expected = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.DUPLICATE,
    ]
    result = card_scan.scan_visible_rows(
        _fixture([expected], image_format="JPEG", quality=70)
    )

    assert _states(result) == [expected]
    assert result.source_size == CANVAS_SIZE


def test_single_frame_lossless_webp_is_accepted_as_a_still():
    expected = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.DUPLICATE,
    ]
    result = card_scan.scan_visible_rows(
        _fixture([expected], image_format="WEBP")
    )

    assert _states(result) == [expected]


def test_older_pillow_pixel_iterator_fallback(monkeypatch):
    monkeypatch.setattr(Image.Image, "get_flattened_data", None)
    expected = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.DUPLICATE,
    ]

    result = card_scan.scan_visible_rows(_fixture([expected]))

    assert _states(result) == [expected]


def test_five_columns_are_rejected_instead_of_partially_mapped():
    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 5], xs=CARD_X[:5])
    )

    assert result.rows == ()
    assert result.layout_confidence == 0.0
    assert "no_valid_six_column_rows" in result.warnings
    assert "non_six_or_irregular_cluster_ignored" in result.warnings


def test_irregular_spacing_is_rejected_instead_of_guessing_columns():
    irregular_x = (65, 205, 345, 485, 650, 765)
    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 6], xs=irregular_x)
    )

    assert result.rows == ()
    assert "no_valid_six_column_rows" in result.warnings


def test_seventh_card_sized_component_invalidates_the_cluster():
    seven_x = (5, 130, 255, 380, 505, 630, 755)
    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 7], xs=seven_x)
    )

    assert result.rows == ()
    assert "no_valid_six_column_rows" in result.warnings


def test_dark_overlay_below_cards_makes_badge_dependent_states_unknown():
    source = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.DUPLICATE,
    ]
    result = card_scan.scan_visible_rows(
        _fixture([source], overlay_rows=frozenset({0}))
    )

    assert _states(result) == [[
        card_scan.MISSING,
        card_scan.UNKNOWN,
        card_scan.UNKNOWN,
        card_scan.UNKNOWN,
        card_scan.MISSING,
        card_scan.UNKNOWN,
    ]]
    for index in (1, 2, 3, 5):
        assert result.rows[0].slots[index].warnings == (
            "badge_region_obstructed",
        )


def test_bottom_crop_never_assumes_an_owned_card_has_no_hidden_badge():
    source = [
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.MISSING,
    ]
    result = card_scan.scan_visible_rows(
        _fixture([source], row_y=(310,), size=(900, 450))
    )

    assert _states(result) == [[
        card_scan.UNKNOWN,
        card_scan.UNKNOWN,
        card_scan.MISSING,
        card_scan.UNKNOWN,
        card_scan.UNKNOWN,
        card_scan.MISSING,
    ]]
    assert result.rows[0].slots[0].warnings == ("badge_region_clipped",)


def test_yellow_frame_is_not_mistaken_for_a_duplicate_badge():
    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 6], frame=(230, 178, 20))
    )

    assert card_scan.DUPLICATE not in _states(result)[0]
    assert all(slot.state == card_scan.UNKNOWN for slot in result.rows[0].slots)
    assert all(
        "ambiguous_badge_signal" in slot.warnings
        for slot in result.rows[0].slots
    )


def test_blank_saturated_art_does_not_form_a_valid_row():
    image = Image.new("RGB", CANVAS_SIZE, (20, 160, 210))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")

    result = card_scan.scan_visible_rows(encoded.getvalue())

    assert result.rows == ()
    assert "no_card_sized_components" in result.warnings


def test_bad_inputs_return_warnings_without_raising():
    cases = (
        (None, "invalid_image_bytes"),
        (b"", "empty_image"),
        (b"not an image", "invalid_or_corrupt_image"),
        (b"x" * (card_scan.MAX_ENCODED_BYTES + 1),
         "encoded_image_too_large"),
    )

    for payload, warning in cases:
        result = card_scan.scan_visible_rows(payload)
        assert result.rows == ()
        assert warning in result.warnings


def test_source_pixel_limit_is_checked_before_classification(monkeypatch):
    monkeypatch.setattr(card_scan, "MAX_SOURCE_PIXELS", 400_000)

    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 6])
    )

    assert result.rows == ()
    assert "image_dimensions_too_large" in result.warnings


def test_unsupported_animation_and_tiny_images_fail_closed():
    tiny = Image.new("RGB", (200, 200), BACKGROUND)
    tiny_bytes = io.BytesIO()
    tiny.save(tiny_bytes, format="PNG")

    frame_a = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    frame_b = Image.new("RGB", CANVAS_SIZE, FRAME)
    gif_bytes = io.BytesIO()
    frame_a.save(
        gif_bytes,
        format="GIF",
        save_all=True,
        append_images=[frame_b],
        duration=50,
        loop=0,
    )

    tiny_result = card_scan.scan_visible_rows(tiny_bytes.getvalue())
    gif_result = card_scan.scan_visible_rows(gif_bytes.getvalue())

    assert "image_dimensions_too_small" in tiny_result.warnings
    assert "unsupported_image_format" in gif_result.warnings
    assert tiny_result.rows == gif_result.rows == ()


def test_scan_is_deterministic_for_the_same_bytes():
    payload = _fixture([[
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.UNKNOWN,
        card_scan.OWNED,
        card_scan.MISSING,
    ]])

    assert card_scan.scan_visible_rows(payload) == card_scan.scan_visible_rows(
        payload
    )
