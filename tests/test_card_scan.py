"""Synthetic regression tests for the guided card-image scanner."""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw

from utils import card_scan
from utils.cards import CARDS


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
    return [
        [card_scan.OWNED if state == card_scan.DUPLICATE else state for state in row]
        for row in rows
    ]


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
                card_scan.UNKNOWN: ((46, 43, 45), (212, 203, 209)),
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


def _install_synthetic_artwork_anchors(monkeypatch, payloads: Sequence[bytes]) -> None:
    """Bind synthetic art to the real scanner contract for focused batch tests."""
    fingerprints: list[int] = []
    for payload in payloads:
        loaded = card_scan._load_still(payload)
        assert not isinstance(loaded, str)
        image, _source_size = loaded
        result = card_scan.scan_visible_rows(payload)
        assert len(result.rows) == 2
        fingerprints.extend(card_scan._artwork_hashes_for_rows(image, result.rows))
    assert len(fingerprints) == len(CARDS)
    monkeypatch.setattr(
        card_scan,
        "CARD_ARTWORK_HASHES",
        dict(zip((card.id for card in CARDS), fingerprints)),
    )
    # Six tiny bit bars are intentionally much less separated than live card
    # artwork.  Preserve unique-nearest checking without pretending this test
    # fixture has the live anchors' measured 12-bit runner-up margin.
    monkeypatch.setattr(card_scan, "ARTWORK_HASH_MIN_RUNNER_UP_GAP", 1)


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


def test_visible_badge_never_creates_unverified_duplicate_supply():
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
    assert result.rows[0].slots[2].warnings == (
        "visible_duplicate_badge_unverified",
        "duplicate_badge_unverified",
    )
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


def test_artwork_anchor_catalog_is_complete_private_and_separated():
    assert set(card_scan.CARD_ARTWORK_HASHES) == {card.id for card in CARDS}
    assert all(
        isinstance(anchor, int) and 0 <= anchor < (1 << 128)
        for anchor in card_scan.CARD_ARTWORK_HASHES.values()
    )
    same_category_distances = [
        (
            card_scan.CARD_ARTWORK_HASHES[left.id]
            ^ card_scan.CARD_ARTWORK_HASHES[right.id]
        ).bit_count()
        for left_index, left in enumerate(CARDS)
        for right in CARDS[left_index + 1:]
        if left.category == right.category
    ]
    assert min(same_category_distances) > card_scan.ARTWORK_HASH_MAX_DISTANCE


def test_artwork_identity_mismatch_names_the_page_and_cards(monkeypatch):
    canonical = [_collection_capture(index) for index in range(5)]
    _install_synthetic_artwork_anchors(monkeypatch, canonical)
    swapped_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    swapped_rows[0][0], swapped_rows[0][1] = (
        swapped_rows[0][1],
        swapped_rows[0][0],
    )
    swapped_art = (1, 0, *range(2, 12))
    payloads = [
        _collection_capture(0, rows=swapped_rows, art_indices=swapped_art),
        *canonical[1:],
    ]

    draft = card_scan.scan_collection_screenshots(payloads)

    first_page = draft.captures[0]
    assert first_page.input_index == 1
    assert first_page.accepted is False
    assert first_page.warnings == ("artwork_identity_mismatch",)
    assert set(first_page.mismatched_card_ids) >= {"barbarian", "archer"}
    assert "artwork_identity_mismatch" in draft.warnings
    assert "artwork_identity_mismatch" in draft.cards[0].warnings
    assert draft.complete is False


def test_artwork_anchors_survive_jpeg_and_resize_without_changing_identity(
    monkeypatch,
):
    canonical = [_collection_capture(index) for index in range(5)]
    _install_synthetic_artwork_anchors(monkeypatch, canonical)
    variants = (
        [
            _reencode_collection_capture(
                payload,
                image_format="JPEG",
                quality=95,
            )
            for payload in canonical
        ],
        [
            _reencode_collection_capture(
                payload,
                image_format="JPEG",
                quality=85,
            )
            for payload in canonical
        ],
        [
            _reencode_collection_capture(payload, width=1080)
            for payload in canonical
        ],
        [
            _reencode_collection_capture(payload, width=800)
            for payload in canonical
        ],
    )

    for payloads in variants:
        draft = card_scan.scan_collection_screenshots(payloads)
        assert draft.complete is True
        assert draft.unseen_card_ids == ()
        assert all(capture.accepted for capture in draft.captures)
        assert all(
            capture.warnings == ("catalog_position_and_artwork_validated",)
            for capture in draft.captures
        )


def test_ordered_batch_maps_all_cards_and_discloses_toolbar_hidden_duplicates(
    monkeypatch,
):
    patterns = (
        [card_scan.OWNED] * 12,
        [card_scan.MISSING] * 6 + [card_scan.OWNED] * 6,
        [card_scan.MISSING, card_scan.OWNED] * 6,
        [card_scan.OWNED] * 6 + [card_scan.MISSING] * 6,
        [card_scan.MISSING] * 12,
    )
    payloads = tuple(
        _collection_capture(
            position,
            pattern,
            overlay_rows=frozenset({0}) if position == 0 else frozenset(),
        )
        for position, pattern in enumerate(patterns)
    )
    _install_synthetic_artwork_anchors(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.coverage_complete is True
    assert draft.complete is True
    assert len(draft.cards) == 60
    assert all(capture.accepted for capture in draft.captures)
    assert tuple(card.card_id for card in draft.cards) == tuple(
        card.id for card in card_scan.CARDS
    )
    assert draft.duplicate_count == 0
    assert draft.duplicate_unverified_card_ids == tuple(
        card.id for card in card_scan.CARDS[:6]
    )
    assert all(
        draft.cards[index].state == card_scan.OWNED
        and "duplicate_badge_unverified" in draft.cards[index].warnings
        for index in range(6)
    )


def test_batch_maps_five_live_order_captures_and_ignores_toolbar_copy(monkeypatch):
    clean = [_collection_capture(index) for index in range(5)]
    payloads = [clean[0], _collection_capture(0, toolbar=True), *clean[1:]]
    _install_synthetic_artwork_anchors(monkeypatch, clean)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert [capture.accepted for capture in draft.captures] == [
        True, False, True, True, True, True
    ]
    assert draft.captures[1].warnings == ("duplicate_capture_ignored",)
    assert [capture.global_rows for capture in draft.captures if capture.accepted] == [
        (1, 2), (3, 4), (5, 6), (7, 8), (9, 10)
    ]
    assert len(draft.cards) == 60
    assert [card.card_id for card in draft.cards] == [card.id for card in CARDS]
    assert draft.cards[0].card_name == "Barbarian"
    assert draft.cards[-1].card_name == "Super Bowler"
    assert draft.cards[12].source_index == 3

    assert draft.recognized_count == 60
    assert draft.missing_count == 31
    assert draft.owned_count == 29
    assert draft.duplicate_count == 0
    assert draft.unknown_count == 0
    assert draft.unknown_card_ids == ()
    assert draft.unseen_card_ids == ()
    assert len(draft.duplicate_unverified_card_ids) == 13
    assert draft.coverage_complete is True
    assert draft.complete is True
    assert draft.persistence_safe is False
    assert "capture_sequence_validated" in draft.warnings
    assert "human_confirmation_required" in draft.warnings
    assert "hidden_duplicates_require_review" in draft.warnings
    assert all(category.complete for category in draft.categories)


def test_batch_downgrades_visible_and_hidden_duplicate_badges_to_owned(monkeypatch):
    first_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    first_rows[0][0] = card_scan.DUPLICATE
    first_rows[1][0] = card_scan.DUPLICATE
    payloads = [
        _collection_capture(0, rows=first_rows),
        *(_collection_capture(index) for index in range(1, 5)),
    ]
    _install_synthetic_artwork_anchors(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.cards[0].state == card_scan.OWNED
    assert "visible_duplicate_badge_unverified" in draft.cards[0].warnings
    assert draft.cards[6].state == card_scan.OWNED
    assert "duplicate_badge_unverified" in draft.cards[6].warnings
    assert draft.duplicate_count == 0
    assert draft.owned_count == 29


def test_batch_rejects_out_of_order_capture_without_shifting_catalog_ids(monkeypatch):
    canonical = [_collection_capture(index) for index in range(5)]
    _install_synthetic_artwork_anchors(monkeypatch, canonical)
    payloads = [
        canonical[0],
        canonical[2],
        canonical[1],
        canonical[3],
        canonical[4],
    ]

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.captures[1].accepted is False
    assert draft.captures[1].warnings == ("capture_sequence_mismatch",)
    assert draft.coverage_complete is False
    assert draft.complete is False
    assert draft.recognized_count == 36
    assert len(draft.unseen_card_ids) == 24
    assert "incomplete_capture_set" in draft.warnings


def test_batch_rejects_one_row_scroll_overlap_without_shifting_later_pages(
    monkeypatch,
):
    overlap_rows = (
        REAL_CAPTURE_STATES[1],
        REAL_CAPTURE_STATES[3],
    )
    overlap_art = (*range(6, 12), *range(18, 24))
    canonical = [_collection_capture(index) for index in range(5)]
    _install_synthetic_artwork_anchors(monkeypatch, canonical)
    payloads = [
        canonical[0],
        _collection_capture(1, rows=overlap_rows, art_indices=overlap_art),
        *canonical[2:],
    ]

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.captures[1].accepted is False
    assert draft.captures[1].warnings == ("overlapping_capture_rows",)
    assert draft.coverage_complete is False
    assert draft.complete is False
    assert draft.recognized_count == 48
    assert tuple(draft.unseen_card_ids) == tuple(
        card.id for card in CARDS[12:24]
    )
    assert "overlapping_capture_rows" in draft.warnings
    assert [
        capture.global_rows for capture in draft.captures if capture.accepted
    ] == [(1, 2), (5, 6), (7, 8), (9, 10)]


def test_unreadable_page_does_not_shift_later_catalog_positions(monkeypatch):
    canonical = [_collection_capture(index) for index in range(5)]
    _install_synthetic_artwork_anchors(monkeypatch, canonical)
    payloads = [canonical[0], b"not-an-image", *canonical[2:]]

    draft = card_scan.scan_collection_screenshots(payloads)

    assert [capture.accepted for capture in draft.captures] == [
        True, False, True, True, True
    ]
    assert "capture_requires_two_rows" in draft.captures[1].warnings
    assert draft.recognized_count == 48
    assert tuple(draft.unseen_card_ids) == tuple(
        card.id for card in CARDS[12:24]
    )
    assert [
        capture.global_rows for capture in draft.captures if capture.accepted
    ] == [(1, 2), (5, 6), (7, 8), (9, 10)]


def test_batch_keeps_ambiguous_portrait_unknown_for_explicit_review(monkeypatch):
    first_rows = [list(row) for row in REAL_CAPTURE_STATES[:2]]
    first_rows[0][0] = card_scan.UNKNOWN
    payloads = [
        _collection_capture(0, rows=first_rows),
        *(_collection_capture(index) for index in range(1, 5)),
    ]
    _install_synthetic_artwork_anchors(monkeypatch, payloads)

    draft = card_scan.scan_collection_screenshots(payloads)

    assert draft.coverage_complete is True
    assert draft.complete is False
    assert draft.recognized_count == 59
    assert draft.unknown_count == 1
    assert draft.unknown_card_ids == ("barbarian",)
    assert draft.unseen_card_ids == ()
    assert draft.categories[0].complete is False
    assert "unknown_states_require_review" in draft.warnings
