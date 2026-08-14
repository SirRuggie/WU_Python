"""Synthetic regression tests for the guided card-image scanner."""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType

import pytest
from PIL import Image, ImageDraw, ImageEnhance

from utils import card_scan
from utils import card_scan_reference
from utils.cards import CARDS


CANVAS_SIZE = (900, 520)
BACKGROUND = (211, 184, 139)
FRAME = (188, 45, 201)
INTERIOR = (58, 53, 65)
OWNED_PORTRAIT = (30, 160, 210)
MISSING_PORTRAIT = (112, 112, 112)
AMBIGUOUS_PORTRAIT = (120, 109, 120)
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
    frames: Sequence[Sequence[tuple[int, int, int]]] | None = None,
    size: tuple[int, int] = CANVAS_SIZE,
    image_format: str = "PNG",
    quality: int = 95,
) -> bytes:
    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    for row_index, states in enumerate(rows):
        y = row_y[row_index]
        for column, (x, state) in enumerate(zip(xs, states)):
            slot_frame = frames[row_index][column] if frames is not None else frame
            _draw_card(draw, x, y, state, frame=slot_frame)
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


def _safe_minimum_states(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    """Expected states for a capture whose badges are drawn unobstructed.

    This used to downgrade every duplicate to owned, because the scanner
    refused to read a badge at all. The detector is now calibrated against
    real captures, so a badge that clears the geometry tests is read as a
    spare and the expectation is the source row unchanged. Obstructed badges
    are still demoted, and that is asserted separately.
    """
    return [list(row) for row in rows]


REAL_CAPTURE_STATES = (
    (card_scan.OWNED, card_scan.MISSING, card_scan.OWNED,
     card_scan.OWNED, card_scan.OWNED, card_scan.OWNED),
    (card_scan.OWNED, card_scan.OWNED, card_scan.OWNED,
     card_scan.MISSING, card_scan.OWNED, card_scan.OWNED),
    (card_scan.MISSING, card_scan.OWNED, card_scan.OWNED,
     card_scan.OWNED, card_scan.OWNED, card_scan.MISSING),
    (card_scan.MISSING, card_scan.OWNED, card_scan.OWNED,
     card_scan.OWNED, card_scan.OWNED, card_scan.MISSING),
    (card_scan.OWNED, card_scan.OWNED, card_scan.OWNED,
     card_scan.MISSING, card_scan.MISSING, card_scan.MISSING),
    (card_scan.OWNED, card_scan.MISSING, card_scan.MISSING,
     card_scan.MISSING, card_scan.OWNED, card_scan.MISSING),
    (card_scan.MISSING, card_scan.OWNED, card_scan.MISSING,
     card_scan.OWNED, card_scan.MISSING, card_scan.MISSING),
    (card_scan.MISSING, card_scan.MISSING, card_scan.OWNED,
     card_scan.MISSING, card_scan.MISSING, card_scan.MISSING),
    (card_scan.MISSING, card_scan.MISSING, card_scan.OWNED,
     card_scan.MISSING, card_scan.OWNED, card_scan.MISSING),
    (card_scan.MISSING, card_scan.MISSING, card_scan.MISSING,
     card_scan.OWNED, card_scan.MISSING, card_scan.MISSING),
)


def _category_frame(category_id: str) -> tuple[int, int, int]:
    hue = round(card_scan.CATEGORY_FRAME_HUES[category_id])
    return Image.new("HSV", (1, 1), (hue, 200, 210)).convert("RGB").getpixel((0, 0))


def _collection_capture(
    capture_index: int,
    states: Sequence[str] | None = None,
    *,
    rows: Sequence[Sequence[str]] | None = None,
    overlay_rows: frozenset[int] | None = None,
    art_indices: Sequence[int] | None = None,
    toolbar: bool = False,
) -> bytes:
    """Synthetic geometry matching one ordered two-row collection capture."""
    if states is not None and rows is not None:
        raise ValueError("pass flat states or rows, not both")
    image = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    if rows is not None:
        row_states = rows
    elif states is not None:
        row_states = (states[:6], states[6:12])
    else:
        row_states = REAL_CAPTURE_STATES[
            capture_index * 2:capture_index * 2 + 2
        ]
    active_overlays = (
        frozenset({1}) if overlay_rows is None else overlay_rows
    )
    for local_row, states in enumerate(row_states):
        y = (70, 300)[local_row]
        for column, (x, state) in enumerate(zip(CARD_X, states)):
            card_index = capture_index * 12 + local_row * 6 + column
            _draw_card(
                draw,
                x,
                y,
                state,
                frame=_category_frame(CARDS[card_index].category),
            )
            marker = (
                art_indices[local_row * 6 + column]
                if art_indices is not None
                else card_index
            )
            # Real portraits contain broad, high-contrast shapes.  A seeded
            # tile field models that identity with enough spatial information
            # to exercise pHash+dHash under resize/JPEG.  State-specific color
            # pairs have similar luminance, while preserving the scanner's
            # saturation bands for missing/owned/ambiguous portraits.
            palette = {
                card_scan.MISSING: ((45, 45, 45), (205, 205, 205)),
                card_scan.OWNED: ((5, 65, 110), (115, 220, 250)),
                card_scan.DUPLICATE: ((5, 65, 110), (115, 220, 250)),
                card_scan.UNKNOWN: ((46, 40, 44), (212, 194, 206)),
            }[state]
            seed = ((marker + 1) * 0x9E3779B1) & 0xFFFFFFFF
            for tile_row in range(8):
                for tile_column in range(6):
                    seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF
                    color = palette[(seed >> 31) & 1]
                    left = x + 23 + tile_column * 8
                    top = y + 22 + tile_row * 8
                    draw.rectangle(
                        (left, top, left + 7, top + 7),
                        fill=color,
                    )
        if local_row in active_overlays:
            draw.rectangle(
                (0, y + CARD_HEIGHT + 1, CANVAS_SIZE[0], y + CARD_HEIGHT + 18),
                fill=(35, 31, 39),
            )

    # The live reward track covers every second-row xN area.  A phone toolbar
    # may then cover more of the already-obstructed footer without changing the
    # card-area fingerprint.
    if toolbar:
        draw.rectangle((120, 450, 780, 519), fill=(52, 53, 56))

    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    return encoded.getvalue()


def _install_synthetic_reference_bank(
    monkeypatch,
    payloads: Sequence[bytes],
) -> dict[int, tuple[tuple[int, ...], ...]]:
    """Bind synthetic art to the real frozen contract for focused batch tests.

    This is a test seam and nothing else.  Production has no runtime path that
    can add a reference; the only way a synthetic row reaches the bank is a
    monkeypatch, which is what
    `test_scanning_cannot_change_the_frozen_reference` exists to pin.
    """
    bank: dict[int, tuple[tuple[int, ...], ...]] = {}
    for capture_index, payload in enumerate(payloads):
        _result, rows = card_scan._register_capture(payload)
        assert len(rows) == 2
        for local_row, record in enumerate(rows):
            assert record.hashes is not None, record.reason
            # The frozen bank holds exactly two coherent templates per catalog
            # row and production refuses anything else, so the fixture has to
            # honour that shape. Minimum reduction makes a repeated template
            # score identically to a single one.
            bank[capture_index * 2 + local_row + 1] = (
                record.hashes, record.hashes,
            )
    assert sorted(bank) == list(range(1, 11))
    assert all(
        len(templates) == card_scan_reference.TEMPLATES_PER_ROW
        for templates in bank.values()
    )
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(bank)
    )
    return bank


def _pseudo_hash(index: int) -> int:
    """A deterministic 128-bit stand-in for one card's artwork hash."""
    state = ((index + 1) * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    value = 0
    for _ in range(4):
        state = (
            state * 6364136223846793005 + 1442695040888963407
        ) & 0xFFFFFFFFFFFFFFFF
        value = (value << 32) | (state >> 32)
    return value


def _bit_flipped(value: int, count: int) -> int:
    for bit in range(count):
        value ^= 1 << bit
    return value


def _separated_bank(monkeypatch) -> dict[int, tuple[tuple[int, ...], ...]]:
    """Ten rows whose cards sit as far apart as real card artwork does.

    With a bank like this a single bit can be moved on purpose, so each frozen
    rejection reason can be reached one at a time instead of by luck.
    """
    bank = {}
    for row in range(1, 11):
        template = tuple(
            _pseudo_hash((row - 1) * 6 + slot) for slot in range(6)
        )
        # Two templates per row, as the frozen bank has.
        bank[row] = (template, template)
    every_card = [value for templates in bank.values() for value in templates[0]]
    closest_card = min(
        (left ^ right).bit_count()
        for index, left in enumerate(every_card)
        for right in every_card[index + 1:]
    )
    closest_row = min(
        sum(
            (left ^ right).bit_count()
            for left, right in zip(bank[first][0], bank[second][0])
        ) / 6
        for first in bank
        for second in bank
        if first < second
    )
    # The fixture has to leave room for the guard (rival at least ten bits
    # past the expected card) and for the frozen rival gap of 46.
    assert closest_card > 30, f"fixture cards are only {closest_card} apart"
    assert closest_row > 50, f"fixture rows are only {closest_row} apart"
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(bank)
    )
    return bank


def _dimmed(payload: bytes, factor: float) -> bytes:
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    encoded = io.BytesIO()
    ImageEnhance.Brightness(image).enhance(factor).save(encoded, format="PNG")
    return encoded.getvalue()


def _assert_bson_safe(value) -> None:
    if isinstance(value, dict):
        assert all(isinstance(key, str) for key in value)
        for nested in value.values():
            _assert_bson_safe(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _assert_bson_safe(nested)
        return
    assert value is None or type(value) in (bool, int, float, str)


# Catalog rows 1 to 3 are entirely elixir, so an all-elixir observation is the
# honest category evidence for them.
ELIXIR_ROW = ("elixir",) * 6


def _reencode_collection_capture(
    payload: bytes,
    *,
    image_format: str = "PNG",
    width: int | None = None,
    quality: int = 95,
) -> bytes:
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    if width is not None:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    options = {"format": image_format}
    if image_format == "JPEG":
        options.update(quality=quality, subsampling=2)
    image.save(encoded, **options)
    return encoded.getvalue()


def test_preview_flags_make_persistence_and_identity_limits_explicit():
    result = card_scan.scan_visible_rows(_fixture([[card_scan.OWNED] * 6]))

    assert card_scan.EXPERIMENTAL is True
    assert card_scan.PERSISTENCE_SAFE is False
    assert result.experimental is True
    assert result.persistence_safe is False
    assert "experimental_preview_only" in result.warnings
    assert "card_identity_not_inferred" in result.warnings


def test_an_unobstructed_badge_is_read_as_a_spare():
    """Calibrated against real captures; see BADGE_MIN_FILL for the numbers."""
    source = [
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.DUPLICATE,
        card_scan.UNKNOWN,
        card_scan.OWNED,
        card_scan.MISSING,
    ]
    result = card_scan.scan_visible_rows(_fixture([source]))

    assert len(result.rows) == 1
    assert _states(result) == _safe_minimum_states([source])
    assert len(result.rows[0].slots) == 6
    assert result.rows[0].slots[2].state == card_scan.DUPLICATE
    assert result.rows[0].slots[2].warnings == ("duplicate_badge_read",)
    assert result.rows[0].slots[3].warnings == (
        "ambiguous_portrait_saturation",
    )
    assert result.rows[0].layout_confidence >= 0.9


def test_a_badge_narrower_than_the_width_floor_is_not_a_spare():
    """The width floor is what keeps fiery artwork from inventing supply."""
    assert card_scan.BADGE_MIN_WIDTH_RATIO > 0.321
    # Real badges measured 0.442 to 0.473 of the card width, so the floor sits
    # between the known false signal and the observed minimum.
    assert card_scan.BADGE_MIN_WIDTH_RATIO < 0.442
    # Real fills ran 0.484 to 0.529; the floor must sit below that range.
    assert card_scan.BADGE_MIN_FILL < 0.484


def test_finds_two_rows_in_top_to_bottom_and_left_to_right_order():
    expected = [
        [card_scan.OWNED, card_scan.MISSING, card_scan.OWNED,
         card_scan.DUPLICATE, card_scan.OWNED, card_scan.MISSING],
        [card_scan.DUPLICATE, card_scan.OWNED, card_scan.MISSING,
         card_scan.OWNED, card_scan.DUPLICATE, card_scan.OWNED],
    ]
    result = card_scan.scan_visible_rows(_fixture(expected))

    assert _states(result) == _safe_minimum_states(expected)
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

    assert _states(result) == _safe_minimum_states([expected])
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

    assert _states(result) == _safe_minimum_states([expected])


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

    assert _states(result) == _safe_minimum_states([expected])


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


def test_dark_overlay_keeps_owned_minimum_and_marks_duplicate_unverified():
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
        card_scan.OWNED,
        card_scan.OWNED,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.OWNED,
    ]]
    for index in (1, 2, 3, 5):
        assert result.rows[0].slots[index].warnings == (
            "badge_region_obstructed",
            "duplicate_badge_unverified",
        )


def test_bottom_crop_keeps_owned_minimum_and_marks_duplicate_unverified():
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
        card_scan.OWNED,
        card_scan.OWNED,
        card_scan.MISSING,
        card_scan.OWNED,
        card_scan.OWNED,
        card_scan.MISSING,
    ]]
    assert result.rows[0].slots[0].warnings == (
        "badge_region_clipped",
        "duplicate_badge_unverified",
    )


def test_yellow_frame_is_not_mistaken_for_a_duplicate_badge():
    result = card_scan.scan_visible_rows(
        _fixture([[card_scan.OWNED] * 6], frame=(230, 178, 20))
    )

    # The guarantee that matters: a yellow frame must never invent trade
    # supply. It still cannot.
    assert card_scan.DUPLICATE not in _states(result)[0]
    # The portrait is clearly coloured, so ownership is not in doubt; only the
    # spare question is. Throwing the whole card away for an unreadable blob
    # made obviously-owned cards come back as "no idea".
    assert all(slot.state == card_scan.OWNED for slot in result.rows[0].slots)
    assert all(
        "ambiguous_badge_signal" in slot.warnings
        and "duplicate_badge_unverified" in slot.warnings
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


def test_landscape_capture_at_documented_minimum_width_is_not_size_rejected():
    image = Image.new("RGB", (720, 332), BACKGROUND)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")

    loaded = card_scan._load_still(encoded.getvalue())

    assert not isinstance(loaded, str)
    normalized, source_size = loaded
    assert source_size == (720, 332)
    assert normalized.size == (720, 332)


def test_high_iou_inner_art_component_is_pruned_without_merging_neighbors():
    frame = card_scan.Bounds(10, 10, 90, 110)
    jpeg_shifted_inner_art = card_scan.Bounds(15, 14, 91, 109)
    neighboring_frame = card_scan.Bounds(120, 10, 200, 110)

    result = card_scan._prune_nested_components([
        jpeg_shifted_inner_art,
        neighboring_frame,
        frame,
    ])

    assert set(result) == {frame, neighboring_frame}


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


def test_invalid_collection_capture_set_fails_closed_with_every_card_unseen():
    draft = card_scan.scan_collection_screenshots(
        tuple(f"invalid-image-{index}".encode() for index in range(5))
    )

    assert draft.complete is False
    assert draft.coverage_complete is False
    assert draft.recognized_count == 0
    assert len(draft.unknown_card_ids) == 60
    assert len(draft.unseen_card_ids) == 60
    assert all(card.state == card_scan.UNKNOWN for card in draft.cards)
    assert all(not capture.accepted for capture in draft.captures)
    assert "incomplete_capture_set" in draft.warnings


# --- the frozen reference and its boundary ---------------------------------


def test_frozen_reference_matches_the_sealed_development_artifact():
    """Production must recognize with the numbers the holdout was run on."""
    artifact_path = (
        Path(__file__).resolve().parents[1]
        / "tools" / "scan_frozen_artifact.json"
    )
    if not artifact_path.exists():
        pytest.skip("the frozen development artifact is not in this checkout")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact["checksum"] == card_scan_reference.FROZEN_ARTIFACT_CHECKSUM
    assert artifact["spec_version"] == card_scan_reference.FROZEN_SPEC_VERSION
    assert float(artifact["aspect"]) == card_scan_reference.CARD_ASPECT
    assert artifact["gate"] == {"top1_max_sixths": 48, "gap_min_sixths": 276}
    assert artifact["slot_guard"] == {
        "support_max": card_scan_reference.SLOT_SUPPORT_MAX,
        "gross": card_scan_reference.SLOT_GROSS,
        "gap_margin": card_scan_reference.SLOT_GAP_MARGIN,
    }
    assert artifact["category"]["centres"] == dict(card_scan.CATEGORY_FRAME_HUES)
    assert artifact["upstream"]["nominal_p95"] == card_scan.NOMINAL_VALUE_P95
    for row, templates in artifact["bank"].items():
        assert card_scan_reference.REFERENCE_BANK[int(row)] == tuple(
            tuple(int(value, 16) for value in template["hashes"])
            for template in templates
        )
    # The manifest is the artifact's catalog, slot for slot and in order.
    assert card_scan_reference.FROZEN_CATALOG == tuple(
        (card["id"], card["category"]) for card in artifact["catalog"]
    )
    # Exactly two coherent templates per catalog row, and nothing but hashes.
    assert sorted(card_scan_reference.REFERENCE_BANK) == list(range(1, 11))
    assert all(
        len(templates) == card_scan_reference.TEMPLATES_PER_ROW
        for templates in artifact["bank"].values()
    )
    assert all(
        len(templates) == card_scan_reference.TEMPLATES_PER_ROW
        and all(len(t) == 6 for t in templates)
        for templates in card_scan_reference.REFERENCE_BANK.values()
    )


def test_the_retired_row_gate_cannot_be_used():
    """The candidate 37/6 + 313/6 gate is retired, not merely unused."""
    assert card_scan_reference.ROW_GATE_TOP1_MAX_SIXTHS == 48
    assert card_scan_reference.ROW_GATE_GAP_MIN_SIXTHS == 276
    assert card_scan.ROW_GATE_TOP1_MAX == 48 / 6
    assert card_scan.ROW_GATE_GAP_MIN == 276 / 6

    for module in (card_scan, card_scan_reference):
        constants = {
            name: getattr(module, name)
            for name in dir(module)
            if name.isupper()
        }
        assert 37 / 6 not in constants.values(), module.__name__
        assert 313 / 6 not in constants.values(), module.__name__
        # The historical experiment tools keep the retired values under
        # RETIRED_ names. Production must not reach them at all.
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "scan_identity_gate" not in source
        assert "scan_slot_guard" not in source


def test_scanning_cannot_change_the_frozen_reference(monkeypatch):
    """No production input can enter the reference or calibration state."""
    shipped = {
        row: tuple(templates)
        for row, templates in card_scan_reference.REFERENCE_BANK.items()
    }
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    card_scan.scan_collection_screenshots(payloads)
    monkeypatch.undo()

    assert {
        row: tuple(templates)
        for row, templates in card_scan_reference.REFERENCE_BANK.items()
    } == shipped
    assert isinstance(card_scan_reference.REFERENCE_BANK, MappingProxyType)
    with pytest.raises(TypeError):
        card_scan_reference.REFERENCE_BANK[1] = ()

    # The reference module offers two functions and both are read-only: one
    # projects a catalog into a manifest, one reports problems. There is no
    # add, fit, learn, or recalibrate.
    owned_callables = {
        name
        for name in dir(card_scan_reference)
        if not name.startswith("_")
        and callable(getattr(card_scan_reference, name))
        and getattr(getattr(card_scan_reference, name), "__module__", "")
        == card_scan_reference.__name__
    }
    assert owned_callables == {"catalog_manifest", "reference_problems"}


def test_a_frozen_reference_that_no_longer_describes_this_code_refuses(
    monkeypatch,
):
    monkeypatch.setattr(card_scan, "FRAME_MIN_VALUE", 99)

    draft = card_scan.scan_collection_screenshots([_collection_capture(0)])

    assert draft.errors == ("frozen_reference_upstream_value_drifted",)
    assert draft.accepted_global_rows == ()
    assert len(draft.unseen_card_ids) == 60
    assert draft.complete is False


# --- the frozen decision order, one rejection reason at a time --------------


def test_a_row_that_clears_every_gate_is_accepted(monkeypatch):
    bank = _separated_bank(monkeypatch)

    outcome, reason, proposed, top1, gap = card_scan._decide_row_identity(
        bank[2][0], ELIXIR_ROW
    )

    assert (outcome, reason, proposed, top1) == ("accepted", "", 2, 0)
    assert gap >= card_scan_reference.ROW_GATE_GAP_MIN


def test_a_contradicting_frame_category_rejects_the_whole_row(monkeypatch):
    bank = _separated_bank(monkeypatch)
    categories = list(ELIXIR_ROW)
    categories[2] = "dark_elixir"

    outcome, reason, proposed, top1, _gap = card_scan._decide_row_identity(
        bank[2][0], tuple(categories)
    )

    assert outcome == "category"
    assert "card 3" in reason
    # The proposal is recorded for diagnostics and is not an identity.
    assert (proposed, top1) == (2, 0)


def test_an_unknown_frame_category_fails_the_row_closed(monkeypatch):
    """Category unknown cannot support a slot, however good the artwork is."""
    bank = _separated_bank(monkeypatch)
    categories = list(ELIXIR_ROW)
    categories[4] = None

    outcome, reason, _proposed, top1, gap = card_scan._decide_row_identity(
        bank[2][0], tuple(categories)
    )

    assert outcome == "unresolved"
    assert "card" in reason and "5" in reason
    assert top1 == 0 and gap >= card_scan_reference.ROW_GATE_GAP_MIN


def test_one_wrong_card_cannot_hide_inside_a_healthy_row_average(monkeypatch):
    """The blind spot the per-slot guard exists to close.

    A wrong card 35 bits away averages to 5.83 over six cards, which clears
    the frozen ceiling of 8.00 while leaving the rival gap wide. The row-level
    numbers alone would accept it; the per-slot guard does not.
    """
    bank = dict(_separated_bank(monkeypatch))
    intruder = _bit_flipped(bank[2][0][3], 35)
    bank[1] = (bank[1][0][:3] + (intruder,) + bank[1][0][4:],)
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(bank)
    )
    observed = bank[2][0][:3] + (intruder,) + bank[2][0][4:]

    outcome, reason, proposed, top1, gap = card_scan._decide_row_identity(
        observed, ELIXIR_ROW
    )

    assert top1 <= card_scan_reference.ROW_GATE_TOP1_MAX
    assert gap >= card_scan_reference.ROW_GATE_GAP_MIN
    assert outcome == "slot"
    assert "card 4" in reason
    assert proposed == 2


def test_a_row_over_the_frozen_distance_ceiling_is_rejected(monkeypatch):
    bank = _separated_bank(monkeypatch)
    observed = tuple(_bit_flipped(value, 9) for value in bank[2][0])

    outcome, reason, proposed, top1, gap = card_scan._decide_row_identity(
        observed, ELIXIR_ROW
    )

    assert (proposed, top1) == (2, 9.0)
    assert top1 > card_scan_reference.ROW_GATE_TOP1_MAX
    assert gap >= card_scan_reference.ROW_GATE_GAP_MIN
    assert outcome == "distance"
    assert "8.00" in reason


def test_a_row_without_the_frozen_rival_gap_is_rejected(monkeypatch):
    """Catalog row 9 is super troop, so a near twin there changes no slot.

    Rivals are drawn from the expected card's own category, so this isolates
    the row-level separation term from the per-slot guard.
    """
    bank = dict(_separated_bank(monkeypatch))
    bank[9] = (tuple(_bit_flipped(value, 2) for value in bank[2][0]),)
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(bank)
    )

    outcome, reason, proposed, top1, gap = card_scan._decide_row_identity(
        bank[2][0], ELIXIR_ROW
    )

    assert (proposed, top1) == (2, 0)
    assert gap < card_scan_reference.ROW_GATE_GAP_MIN
    assert outcome == "separation"
    assert "46.00" in reason


def test_ranking_breaks_a_tie_on_catalog_row_rather_than_dictionary_order(
    monkeypatch,
):
    bank = dict(_separated_bank(monkeypatch))
    bank[7] = (bank[2][0],)
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(bank)
    )

    _outcome, _reason, proposed, top1, gap = card_scan._decide_row_identity(
        bank[2][0], ELIXIR_ROW
    )

    assert (proposed, top1, gap) == (2, 0, 0)


# --- whole captures through the row scanner --------------------------------


def test_a_confirmed_row_binds_its_six_cards_and_nothing_else(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots([payloads[0]])

    assert draft.accepted_global_rows == (1, 2)
    assert draft.manual_required_global_rows == (3, 4, 5, 6, 7, 8, 9, 10)
    assert [decision.outcome for decision in draft.row_decisions] == [
        "accepted", "accepted",
    ]
    assert [decision.catalog_row for decision in draft.row_decisions] == [1, 2]
    assert draft.recognized_count == 12
    assert [card.card_id for card in draft.cards[:12]] == [
        card.id for card in CARDS[:12]
    ]
    assert all(card.source_index == 1 for card in draft.cards[:12])
    assert all(card.source_index is None for card in draft.cards[12:])
    assert draft.captures[0].rows_detected == 2
    assert draft.captures[0].rows_accepted == 2
    assert draft.captures[0].rows_manual == 0
    assert draft.captures[0].warnings == ("capture_rows_confirmed",)
    assert draft.complete is False
    assert draft.persistence_safe is False


def test_a_rejected_row_contributes_no_cards_at_all(monkeypatch):
    """Row atomicity: five good cards out of a bad row are not evidence."""
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    tampered = _collection_capture(
        0, art_indices=(0, 1, 30, 3, 4, 5, *range(6, 12))
    )

    draft = card_scan.scan_collection_screenshots([tampered])

    first, second = draft.row_decisions
    assert first.accepted is False
    assert first.outcome in {"slot", "category", "unresolved", "distance"}
    assert first.catalog_row is None
    assert first.proposed_row == 1
    assert second.accepted is True and second.catalog_row == 2

    assert draft.accepted_global_rows == (2,)
    assert 1 in draft.manual_required_global_rows
    assert all(card.source_index is None for card in draft.cards[:6])
    assert tuple(draft.unseen_card_ids[:6]) == tuple(
        card.id for card in CARDS[:6]
    )
    assert all(
        card.id in draft.manual_required_card_ids for card in CARDS[:6]
    )
    assert draft.captures[0].rows_accepted == 1
    assert draft.captures[0].rows_manual == 1
    assert "rows_need_manual_review" in draft.warnings


def test_mixed_captures_keep_the_confirmed_rows_and_flag_the_rest(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    tampered = _collection_capture(
        0, art_indices=(0, 1, 30, 3, 4, 5, *range(6, 12))
    )

    draft = card_scan.scan_collection_screenshots([tampered, payloads[1]])

    assert draft.accepted_global_rows == (2, 3, 4)
    assert draft.manual_required_global_rows == (1, 5, 6, 7, 8, 9, 10)
    assert draft.recognized_count == 18
    assert draft.coverage_complete is False
    assert draft.complete is False
    assert draft.captures[1].accepted is True
    assert len(draft.manual_required_card_ids) == 42


def test_every_row_confirmed_produces_a_complete_draft(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.accepted_global_rows == tuple(range(1, 11))
    assert draft.manual_required_global_rows == ()
    assert draft.manual_required_card_ids == ()
    assert draft.coverage_complete is True
    assert draft.complete is True
    assert draft.accepted_page_numbers == (1, 2, 3, 4, 5)
    assert draft.missing_page_numbers == ()
    assert draft.missing_global_rows == ()
    assert [card.card_id for card in draft.cards] == [
        card.id for card in CARDS
    ]
    assert "collection_rows_validated" in draft.warnings
    assert "human_confirmation_required" in draft.warnings
    assert card_scan.PERSISTENCE_SAFE is False


def test_upload_order_is_never_an_identity_signal(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    shuffled = [payloads[3], payloads[0], payloads[4], payloads[2], payloads[1]]

    draft = card_scan.scan_collection_screenshots(shuffled)

    assert draft.complete is True
    assert [
        tuple(capture.global_rows) for capture in draft.captures
    ] == [(7, 8), (1, 2), (9, 10), (5, 6), (3, 4)]
    assert draft.cards[0].source_index == 2
    assert draft.cards[36].source_index == 1


def test_a_scrolled_capture_of_two_far_apart_rows_is_read_correctly(
    monkeypatch,
):
    """Row identity makes a scroll overlap an ordinary, correct reading."""
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    scrolled = _collection_capture(
        1,
        rows=(REAL_CAPTURE_STATES[1], REAL_CAPTURE_STATES[3]),
        art_indices=(*range(6, 12), *range(18, 24)),
    )

    draft = card_scan.scan_collection_screenshots([scrolled])

    assert draft.accepted_global_rows == (2, 4)
    assert draft.cards[6].source_index == 1
    assert draft.cards[18].source_index == 1
    assert all(card.source_index is None for card in draft.cards[12:18])


def test_an_unreadable_image_does_not_shift_any_catalog_position(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots([
        b"not-an-image", payloads[4], payloads[0], payloads[2], payloads[3],
    ])

    assert [capture.accepted for capture in draft.captures] == [
        False, True, True, True, True,
    ]
    assert draft.captures[0].warnings == ("invalid_or_corrupt_image",)
    assert draft.accepted_global_rows == (1, 2, 5, 6, 7, 8, 9, 10)
    assert draft.manual_required_global_rows == (3, 4)
    assert draft.missing_page_numbers == (2,)
    assert tuple(draft.unseen_card_ids) == tuple(
        card.id for card in CARDS[12:24]
    )


def test_a_repeated_row_resolves_unknowns_but_fails_a_contradiction_closed(
    monkeypatch,
):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    unknown_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    unknown_rows[0][0] = card_scan.UNKNOWN
    resolved = card_scan.scan_collection_screenshots((
        _collection_capture(0, rows=unknown_rows), payloads[0],
    ))

    assert resolved.cards[0].state == card_scan.OWNED
    assert resolved.captures[1].warnings == ("repeat_rows_merged",)
    assert resolved.captures[1].global_rows == (1, 2)
    assert "repeat_rows_merged" in resolved.warnings

    conflicting_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    conflicting_rows[0][0] = card_scan.MISSING
    conflicted = card_scan.scan_collection_screenshots((
        payloads[0], _collection_capture(0, rows=conflicting_rows),
    ))

    assert conflicted.cards[0].state == card_scan.UNKNOWN
    assert "conflicting_duplicate_capture_state" in conflicted.cards[0].warnings
    assert conflicted.captures[1].warnings == ("conflicting_repeat_rows",)
    assert conflicted.captures[1].conflicting_card_ids == ("barbarian",)
    assert conflicted.complete is False


def test_an_ambiguous_portrait_stays_unknown_inside_a_confirmed_row(
    monkeypatch,
):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    first_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    first_rows[0][0] = card_scan.UNKNOWN

    draft = card_scan.scan_collection_screenshots([
        _collection_capture(0, rows=first_rows), *payloads[1:],
    ])

    # Identity confidence and ownership confidence are separate: the row is
    # confirmed, one portrait inside it is not.
    assert draft.accepted_global_rows == tuple(range(1, 11))
    assert draft.coverage_complete is True
    assert draft.complete is False
    assert draft.unknown_card_ids == ("barbarian",)
    assert draft.recognized_count == 59
    assert draft.categories[0].complete is False
    assert "unknown_states_require_review" in draft.warnings


def test_the_reward_bar_row_is_read_and_its_badges_left_unverified(
    monkeypatch,
):
    """Item 9 and item 12 together: a clipped badge lowers the claim, not the
    row. A visible badge is a spare; an obstructed one is one proven copy."""
    first_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    first_rows[0][0] = card_scan.DUPLICATE
    first_rows[1][0] = card_scan.DUPLICATE
    payloads = [
        _collection_capture(0, rows=first_rows),
        *(_collection_capture(index) for index in range(1, 5)),
    ]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.accepted_global_rows == tuple(range(1, 11))
    assert draft.cards[0].state == card_scan.DUPLICATE
    assert "duplicate_badge_read" in draft.cards[0].warnings
    # Row 2 sits under the reward track, so its badge cannot be read.
    assert draft.cards[6].state == card_scan.OWNED
    assert "duplicate_badge_unverified" in draft.cards[6].warnings
    assert "barbarian" not in draft.duplicate_unverified_card_ids
    assert "wizard" in draft.duplicate_unverified_card_ids
    assert "hidden_duplicates_require_review" in draft.warnings


def test_a_dim_capture_keeps_its_rows_and_the_floor_is_inert_when_bright():
    """Item 10: the frame floor scales with the capture's own bright end."""
    assert card_scan._adaptive_value_floor([250] * 100) == card_scan.FRAME_MIN_VALUE
    assert card_scan._adaptive_value_floor([]) == card_scan.FRAME_MIN_VALUE
    assert card_scan._adaptive_value_floor([150] * 100) < card_scan.FRAME_MIN_VALUE

    dim = _dimmed(_collection_capture(0), 0.55)
    assert len(card_scan.scan_visible_rows(dim).rows) == 2

    fixed_floor = card_scan._adaptive_value_floor
    try:
        card_scan._adaptive_value_floor = lambda _values: card_scan.FRAME_MIN_VALUE
        assert card_scan.scan_visible_rows(dim).rows == ()
    finally:
        card_scan._adaptive_value_floor = fixed_floor


def test_a_dim_capture_still_reaches_the_right_identity(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(
        [_dimmed(payload, 0.7) for payload in payloads]
    )

    assert draft.accepted_global_rows == tuple(range(1, 11))
    assert all(
        decision.catalog_row == decision.row_index + 1 + 2 * (decision.input_index - 1)
        for decision in draft.row_decisions
    )


def test_resize_and_recompression_never_produce_a_wrong_identity(monkeypatch):
    """Recall may fall on a transformed capture; identity may not be wrong."""
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    variants = {
        "jpeg 95": [
            _reencode_collection_capture(p, image_format="JPEG", quality=95)
            for p in payloads
        ],
        "jpeg 85": [
            _reencode_collection_capture(p, image_format="JPEG", quality=85)
            for p in payloads
        ],
        "width 1080": [
            _reencode_collection_capture(p, width=1080) for p in payloads
        ],
        "width 800": [
            _reencode_collection_capture(p, width=800) for p in payloads
        ],
    }

    for label, transformed in variants.items():
        draft = card_scan.scan_collection_screenshots(transformed)
        for decision in draft.row_decisions:
            if not decision.accepted:
                continue
            expected = 2 * (decision.input_index - 1) + decision.row_index + 1
            assert decision.catalog_row == expected, label
        assert draft.accepted_global_rows, label


def test_a_horizontally_squeezed_capture_is_never_accepted_as_a_wrong_row(
    monkeypatch,
):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    squeezed = []
    for payload in payloads:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
        narrowed = image.resize(
            (round(image.width * 0.9), image.height), Image.Resampling.LANCZOS
        )
        encoded = io.BytesIO()
        narrowed.save(encoded, format="PNG")
        squeezed.append(encoded.getvalue())

    draft = card_scan.scan_collection_screenshots(squeezed)

    for decision in draft.row_decisions:
        if decision.accepted:
            expected = 2 * (decision.input_index - 1) + decision.row_index + 1
            assert decision.catalog_row == expected


def test_the_same_bytes_always_produce_the_same_decisions(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    first = card_scan.scan_collection_screenshots(payloads)
    again = card_scan.scan_collection_screenshots(payloads)
    reversed_order = card_scan.scan_collection_screenshots(payloads[::-1])

    assert first.row_decisions == again.row_decisions
    assert first.cards == again.cards
    # Order changes which image proved a row, never which row was proved.
    assert {
        (decision.catalog_row, decision.outcome)
        for decision in reversed_order.row_decisions
    } == {
        (decision.catalog_row, decision.outcome)
        for decision in first.row_decisions
    }
    assert reversed_order.accepted_global_rows == first.accepted_global_rows


def test_the_scan_records_which_reference_decided_it(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads[:1])

    assert card_scan_reference.FROZEN_SPEC_VERSION in draft.scanner_version
    assert (
        card_scan_reference.FROZEN_ARTIFACT_CHECKSUM[:16]
        in draft.scanner_version
    )


# --- checkpoints ------------------------------------------------------------


def test_partial_rows_resume_from_a_bson_checkpoint_without_raw_images(
    monkeypatch,
):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)

    first = card_scan.scan_collection_screenshots((payloads[4], payloads[1]))
    checkpoint = card_scan.collection_scan_checkpoint(first)

    assert first.accepted_global_rows == (3, 4, 9, 10)
    assert checkpoint["accepted_global_rows"] == [3, 4, 9, 10]
    assert checkpoint["missing_global_rows"] == [1, 2, 5, 6, 7, 8]
    assert checkpoint["missing_page_numbers"] == [1, 3, 4]
    assert checkpoint["version"] == card_scan.SCAN_CHECKPOINT_VERSION
    _assert_bson_safe(checkpoint)

    resumed = card_scan.scan_collection_screenshots(
        (payloads[3], payloads[0], payloads[2]),
        prior_draft=checkpoint,
    )

    assert resumed.coverage_complete is True
    assert resumed.complete is True
    assert resumed.accepted_global_rows == tuple(range(1, 11))
    assert resumed.cards[12].source_index == 0
    assert resumed.cards[0].source_index == 2
    assert "prior_scan_checkpoint_merged" in resumed.warnings


def test_a_checkpoint_holding_half_a_row_is_rejected_atomically(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    first = card_scan.scan_collection_screenshots((payloads[0],))
    checkpoint = card_scan.collection_scan_checkpoint(first)

    stranded = CARDS[3].id
    checkpoint["card_states"].pop(stranded, None)
    checkpoint["card_confidences"].pop(stranded, None)
    checkpoint["unseen_card_ids"] = [
        *checkpoint["unseen_card_ids"], stranded,
    ]

    resumed = card_scan.scan_collection_screenshots(
        (payloads[2],), prior_draft=checkpoint
    )

    assert "invalid_prior_scan_checkpoint" in resumed.warnings
    assert resumed.accepted_global_rows == (5, 6)


def test_a_normalized_v2_checkpoint_is_accepted_for_a_partial_resume(
    monkeypatch,
):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    first = card_scan.scan_collection_screenshots((payloads[0], payloads[2]))
    checkpoint = card_scan.collection_scan_checkpoint(first)
    checkpoint["version"] = 2
    checkpoint["card_states"] = {
        card_id: {
            card_scan.MISSING: 0,
            card_scan.OWNED: 1,
            card_scan.DUPLICATE: 2,
        }[state]
        for card_id, state in checkpoint["card_states"].items()
    }
    checkpoint["unknown_card_ids"] = [
        *checkpoint["unknown_card_ids"], *checkpoint["unseen_card_ids"],
    ]

    resumed = card_scan.scan_collection_screenshots(
        (payloads[4], payloads[1], payloads[3]),
        prior_draft=checkpoint,
    )

    assert resumed.complete is True
    assert resumed.accepted_global_rows == tuple(range(1, 11))


def test_an_invalid_prior_checkpoint_is_ignored_atomically(monkeypatch):
    payloads = [_collection_capture(index) for index in range(5)]
    _install_synthetic_reference_bank(monkeypatch, payloads)
    first = card_scan.scan_collection_screenshots((payloads[0], payloads[1]))
    checkpoint = card_scan.collection_scan_checkpoint(first)
    checkpoint["identity_bound"] = False

    resumed = card_scan.scan_collection_screenshots(
        (payloads[3],), prior_draft=checkpoint
    )

    assert resumed.accepted_global_rows == (7, 8)
    assert resumed.recognized_count == 12
    assert "invalid_prior_scan_checkpoint" in resumed.warnings


# --- the frozen catalog manifest -------------------------------------------


class _CatalogEntry:
    """The only two catalog fields the frozen manifest is defined over."""

    def __init__(self, card_id: str, category: str):
        self.id = card_id
        self.category = category


def _live_catalog():
    return [
        _CatalogEntry(card_id, category)
        for card_id, category in card_scan_reference.FROZEN_CATALOG
    ]


def _manifest_problems(catalog=None):
    return card_scan_reference.reference_problems(
        catalog=_live_catalog() if catalog is None else catalog,
        frame_min_saturation=card_scan_reference.EXPECTED_FRAME_MIN_SATURATION,
        frame_min_value=card_scan_reference.EXPECTED_FRAME_MIN_VALUE,
        category_frame_hues=dict(
            card_scan_reference.EXPECTED_CATEGORY_FRAME_HUES
        ),
    )


def test_the_frozen_manifest_pins_every_catalog_slot():
    assert len(card_scan_reference.FROZEN_CATALOG) == 60
    assert card_scan_reference.FROZEN_CATALOG == tuple(
        (card.id, card.category) for card in CARDS
    )
    assert _manifest_problems() == ()


def test_a_reordered_catalog_of_the_same_size_is_refused():
    """A reference hash means the artwork at slot N. Reorder and it lies."""
    catalog = _live_catalog()
    catalog[0], catalog[1] = catalog[1], catalog[0]

    assert _manifest_problems(catalog) == ("catalog_manifest_drifted",)


def test_a_recategorised_card_is_refused():
    catalog = _live_catalog()
    catalog[0] = _CatalogEntry(catalog[0].id, "dark_elixir")

    assert _manifest_problems(catalog) == ("catalog_manifest_drifted",)


def test_a_renamed_or_resized_catalog_is_refused():
    renamed = _live_catalog()
    renamed[7] = _CatalogEntry("some_new_card", renamed[7].category)
    assert _manifest_problems(renamed) == ("catalog_manifest_drifted",)

    assert _manifest_problems(_live_catalog()[:59]) == (
        "catalog_manifest_drifted",
    )
    assert _manifest_problems(
        [*_live_catalog(), _CatalogEntry("extra", "elixir")]
    ) == ("catalog_manifest_drifted",)


def test_exactly_two_templates_per_catalog_row_are_required(monkeypatch):
    assert card_scan_reference.TEMPLATES_PER_ROW == 2
    assert _manifest_problems() == ()

    complete = dict(card_scan_reference.REFERENCE_BANK)

    missing = dict(complete)
    missing[3] = (complete[3][0],)
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(missing)
    )
    assert _manifest_problems() == ("reference_template_count_changed",)

    extra = dict(complete)
    extra[3] = (*complete[3], complete[3][0])
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(extra)
    )
    assert _manifest_problems() == ("reference_template_count_changed",)

    dropped = dict(complete)
    dropped.pop(10)
    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(dropped)
    )
    assert _manifest_problems() == ("reference_rows_incomplete",)

    monkeypatch.setattr(
        card_scan_reference, "REFERENCE_BANK", MappingProxyType(complete)
    )
    assert _manifest_problems() == ()


def test_a_drifted_catalog_makes_the_scanner_refuse_to_answer(monkeypatch):
    reordered = (CARDS[1], CARDS[0], *CARDS[2:])
    monkeypatch.setattr(card_scan, "CARDS", reordered)

    draft = card_scan.scan_collection_screenshots([_collection_capture(0)])

    assert draft.errors == ("frozen_reference_catalog_manifest_drifted",)
    assert draft.accepted_global_rows == ()
    assert draft.row_decisions == ()
    assert len(draft.unseen_card_ids) == 60
    assert draft.complete is False
