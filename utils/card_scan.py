"""Review-only Clash of Cards still-image classifier.

This module deliberately has no Discord or database imports.  Its batch entry
point reads collection screenshots in any order and recognizes them **one
six-card row at a time** against the frozen reference in
:mod:`utils.card_scan_reference`.

Identity is decided per row, never per page and never per card:

1. an adaptive frame detector recovers the visible six-card rows;
2. a resolution-normalized band sampler measures each card's width and centre
   from image structure alone, with run-to-centre assignment;
3. the six artwork hashes are scored against two coherent templates per catalog
   row, and the best and second-best catalog rows are ranked;
4. an independent per-slot frame category vetoes a contradicting row, and an
   unknown category fails closed;
5. a per-slot artwork guard rejects a slot a same-category rival explains
   better, so one wrong card cannot hide inside a healthy row average;
6. the frozen row gate accepts only ``top1 <= 48/6`` with a rival gap of at
   least ``276/6``.

A row that clears every step contributes six identity-bound card states.  A row
that fails any step contributes **nothing at all** — not even its five
apparently good cards — and its positions are reported as needing manual
review.  Zero wrong accepted row identities outranks recovering every row.

The output is never safe to persist without human review.  Missing portraits
can be recognized even when the fixed reward track covers the badge area.  A
clearly colored portrait there proves at least one copy, so it is returned as
owned while its possibly hidden duplicate badge is explicitly left unverified.

Only ordinary PNG, JPEG, and single-frame WebP still images are accepted.
Video decoding and arbitrary-scroll row merging are intentionally out of scope.
Scanning is CPU-bound; any async caller must run it outside the Discord event
loop.  This module intentionally provides no such integration.
"""

from __future__ import annotations

import io
import math
import statistics
import warnings
from collections.abc import Mapping
from collections import deque
from dataclasses import dataclass
from itertools import islice
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from utils import card_scan_reference as reference
from utils.cards import CARDS, CATEGORY_BY_ID


# The recognition stack is the qualified frozen package, but a scan result is
# still only a review draft: nothing in this module authorizes a write.
EXPERIMENTAL = True
PERSISTENCE_SAFE = False
SCANNER_VERSION = (
    f"{reference.FROZEN_SPEC_VERSION} "
    f"artifact:{reference.FROZEN_ARTIFACT_CHECKSUM[:16]}"
)

MISSING = "missing"
OWNED = "owned"
DUPLICATE = "duplicate"
UNKNOWN = "unknown"
CardState = Literal["missing", "owned", "duplicate", "unknown"]

SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_ENCODED_BYTES = 10 * 1024 * 1024
MAX_SOURCE_PIXELS = 24_000_000
MAX_SOURCE_EDGE = 8192
MIN_SOURCE_WIDTH = 720
MIN_SOURCE_HEIGHT = 300
MAX_SCAN_WIDTH = 1000
MAX_SCAN_HEIGHT = 2400
COLLECTION_CAPTURE_COUNT = 5
COLLECTION_ROWS = 10
COLLECTION_COLUMNS = 6
MAX_COLLECTION_INPUTS = 10
SCAN_CHECKPOINT_VERSION = 1

# Conservative thresholds checked against the supplied five-page live capture
# sequence.  Values between the missing and owned bands remain unknown.
FRAME_MIN_SATURATION = 110
FRAME_MIN_VALUE = 120
# A missing portrait is rendered fully desaturated and measures 0.00 on a clean
# capture, but JPEG residue on an already-grey subject lifts it: Cannon Cart, a
# grey mechanical cannon, measured 19.39 and fell into the old 12..25 gap, so a
# card that is obviously absent on screen came back "unknown".
#
# The floor moves to 25 and the owned threshold to 30. Widening the owned
# side as well was tried and is wrong: several genuinely owned cards have
# naturally muted art (Yeti, Golem, Headhunter, Thrower, Meteor Golem all
# measure 48..74), so raising it to 75 pushed five correct readings into the
# ambiguous band. The lowest owned reading observed is 48, which leaves ample
# room above 30: the sorted distribution across sixty live portraits is
# thirty-four zeros, then 19.4 (Cannon Cart, missing), then 33.6 upward,
# all owned. Nothing real falls in 25..30.
MISSING_MAX_SATURATION = 25.0
OWNED_MIN_SATURATION = 30.0
YELLOW_HUE_MIN = 24
YELLOW_HUE_MAX = 50
YELLOW_MIN_SATURATION = 120
YELLOW_MIN_VALUE = 150
BADGE_MIN_WIDTH_RATIO = 0.38
# Measured across five unobstructed badges (four x2 and one x4) from two
# accounts at 3120x1440: fill ran 0.484 to 0.529.  The former 0.50 floor sat
# inside that range and rejected a real badge at 0.484.  Width stays the
# discriminator that excludes the known fiery-art false signal at 0.321.
BADGE_MIN_FILL = 0.44

# Median frame hues in Pillow's 0..255 HSV representation, measured from the
# supplied live collection captures.  The tolerance intentionally leaves broad
# gaps between adjacent category colors while allowing ordinary recompression.
CATEGORY_FRAME_HUES = {
    "elixir": 211.0,
    "dark_elixir": 198.0,
    "builder_base": 145.0,
    "super_troop": 12.0,
}
# Row identity, per-slot guard, category veto, sampler, and brightness floor
# all come from the frozen package.  They are imported rather than restated so
# production cannot drift away from the evaluated numbers.
CARD_ASPECT = reference.CARD_ASPECT
ROW_GATE_TOP1_MAX = reference.ROW_GATE_TOP1_MAX
ROW_GATE_GAP_MIN = reference.ROW_GATE_GAP_MIN
NOMINAL_VALUE_P95 = reference.NOMINAL_VALUE_P95

# The only information retained from the development captures is one 128-bit
# grayscale perceptual hash per card portrait, held in
# `card_scan_reference.REFERENCE_BANK`.  Those values cannot reconstruct a
# screenshot, a badge, a collection, or an account identity.  The inner-art
# crop deliberately excludes the xN badge.
ARTWORK_HASH_SIZE = 32
ARTWORK_HASH_MAX_FREQUENCY = 10
ARTWORK_CROP_LEFT = -0.38
ARTWORK_CROP_TOP = 0.08
ARTWORK_CROP_RIGHT = 0.38
ARTWORK_CROP_BOTTOM = 0.66

_ARTWORK_PHASH_FREQUENCIES = (
    (1, 0), (0, 1), (0, 2), (1, 1), (2, 0), (3, 0), (2, 1), (1, 2),
    (0, 3), (0, 4), (1, 3), (2, 2), (3, 1), (4, 0), (5, 0), (4, 1),
    (3, 2), (2, 3), (1, 4), (0, 5), (0, 6), (1, 5), (2, 4), (3, 3),
    (4, 2), (5, 1), (6, 0), (7, 0), (6, 1), (5, 2), (4, 3), (3, 4),
    (2, 5), (1, 6), (0, 7), (0, 8), (1, 7), (2, 6), (3, 5), (4, 4),
    (5, 3), (6, 2), (7, 1), (8, 0), (9, 0), (8, 1), (7, 2), (6, 3),
    (5, 4), (4, 5), (3, 6), (2, 7), (1, 8), (0, 9), (0, 10), (1, 9),
    (2, 8), (3, 7), (4, 6), (5, 5), (6, 4), (7, 3), (8, 2), (9, 1),
)
_ARTWORK_COSINES = tuple(
    tuple(
        math.cos(
            math.pi * (2 * position + 1) * frequency
            / (2 * ARTWORK_HASH_SIZE)
        )
        for position in range(ARTWORK_HASH_SIZE)
    )
    for frequency in range(ARTWORK_HASH_MAX_FREQUENCY + 1)
)


@dataclass(frozen=True, slots=True)
class Bounds:
    """A half-open rectangle in normalized scan-image coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True, slots=True)
class SlotScan:
    column: int
    state: CardState
    confidence: float
    bounds: Bounds
    portrait_saturation: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RowScan:
    row: int
    slots: tuple[SlotScan, ...]
    layout_confidence: float
    bounds: Bounds


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Preview data only; it never contains category or card identities."""

    rows: tuple[RowScan, ...]
    source_size: tuple[int, int] | None
    scan_size: tuple[int, int] | None
    layout_confidence: float
    warnings: tuple[str, ...]
    experimental: bool = True
    persistence_safe: bool = False


@dataclass(frozen=True, slots=True)
class RowScanDecision:
    """What the frozen stack decided about one detected six-card row.

    ``proposed_row`` is the nearest catalog row the reference bank suggested.
    It is a proposal and nothing more: it is recorded for diagnostics even when
    the row was rejected, and it is **never** an identity.  ``catalog_row`` is
    the trusted identity and is set only on an accepted row.
    """

    input_index: int
    row_index: int
    accepted: bool
    outcome: str
    reason: str
    proposed_row: int | None = None
    catalog_row: int | None = None
    identity_top1: float | None = None
    identity_gap: float | None = None


@dataclass(frozen=True, slots=True)
class CollectionCaptureScan:
    """Disposition of one supplied screenshot in a collection batch."""

    input_index: int
    accepted: bool
    global_rows: tuple[int, ...]
    source_size: tuple[int, int] | None
    scan_size: tuple[int, int] | None
    warnings: tuple[str, ...]
    assigned_page_number: int | None = None
    mismatched_card_ids: tuple[str, ...] = ()
    conflicting_card_ids: tuple[str, ...] = ()
    rows_detected: int = 0
    rows_accepted: int = 0
    rows_manual: int = 0


@dataclass(frozen=True, slots=True)
class DraftCardScan:
    """One identity-bound card state that must still be reviewed by a human."""

    card_id: str
    card_name: str
    category_id: str
    catalog_index: int
    global_row: int
    column: int
    state: CardState
    confidence: float
    source_index: int | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CategoryScanDraft:
    """Review summary for one fixed catalog category."""

    category_id: str
    category_name: str
    cards: tuple[DraftCardScan, ...]
    recognized_count: int
    unknown_card_ids: tuple[str, ...]
    unseen_card_ids: tuple[str, ...]
    duplicate_unverified_card_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class CollectionScanDraft:
    """Identity-bound preview; ``persistence_safe`` is intentionally false.

    ``coverage_complete`` means all ten catalog rows were accepted by the
    frozen row gate.  ``complete`` additionally requires no unknown state.
    Neither flag authorizes an automatic database write.

    ``manual_required_global_rows`` and ``manual_required_card_ids`` are the
    positions the scanner refused to guess.  They are the manual fallback's
    input, and they are the reason a rejected row costs the player a few taps
    instead of a wrong collection.
    """

    cards: tuple[DraftCardScan, ...]
    categories: tuple[CategoryScanDraft, ...]
    captures: tuple[CollectionCaptureScan, ...]
    accepted_page_numbers: tuple[int, ...]
    missing_page_numbers: tuple[int, ...]
    missing_global_rows: tuple[int, ...]
    recognized_count: int
    missing_count: int
    owned_count: int
    duplicate_count: int
    unknown_count: int
    unknown_card_ids: tuple[str, ...]
    unseen_card_ids: tuple[str, ...]
    duplicate_unverified_card_ids: tuple[str, ...]
    coverage_complete: bool
    complete: bool
    warnings: tuple[str, ...]
    accepted_global_rows: tuple[int, ...] = ()
    manual_required_global_rows: tuple[int, ...] = ()
    manual_required_card_ids: tuple[str, ...] = ()
    row_decisions: tuple[RowScanDecision, ...] = ()
    # Non-empty only when the scan could not be performed at all, for example
    # because the frozen reference no longer describes this code.  An error
    # makes the draft unsavable rather than partly trusted.
    errors: tuple[str, ...] = ()
    scanner_version: str = SCANNER_VERSION
    experimental: bool = True
    persistence_safe: bool = False


def _result_failure(
    code: str,
    *,
    source_size: tuple[int, int] | None = None,
    scan_size: tuple[int, int] | None = None,
    prior: tuple[str, ...] = (),
) -> ScanResult:
    return ScanResult(
        rows=(),
        source_size=source_size,
        scan_size=scan_size,
        layout_confidence=0.0,
        warnings=(*prior, code),
    )


def _load_still(image_bytes: object) -> tuple[Image.Image, tuple[int, int]] | str:
    """Return the normalized scan image and the original source size."""
    loaded = _load_still_pair(image_bytes)
    if isinstance(loaded, str):
        return loaded
    scan, _source, source_size = loaded
    return scan, source_size


def _load_still_pair(
    image_bytes: object,
) -> tuple[Image.Image, Image.Image, tuple[int, int]] | str:
    """Return (scan image, full-resolution source, source size) or a code.

    Geometry and card states are read from the normalized scan image, while the
    band sampler and the artwork crops read the full-resolution source, because
    a band one to three per cent of a card wide has too few pixels once the
    capture has been shrunk to 1000 px.  Both come from one decode.
    """
    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        return "invalid_image_bytes"
    if not image_bytes:
        return "empty_image"
    if len(image_bytes) > MAX_ENCODED_BYTES:
        return "encoded_image_too_large"

    encoded = bytes(image_bytes)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(encoded)) as probe:
                image_format = (probe.format or "").upper()
                source_size = probe.size
                if image_format not in SUPPORTED_FORMATS:
                    return "unsupported_image_format"
                if getattr(probe, "n_frames", 1) != 1:
                    return "animated_image_not_supported"

                width, height = source_size
                if width < MIN_SOURCE_WIDTH or height < MIN_SOURCE_HEIGHT:
                    return "image_dimensions_too_small"
                if (
                    width > MAX_SOURCE_EDGE
                    or height > MAX_SOURCE_EDGE
                    or width * height > MAX_SOURCE_PIXELS
                ):
                    return "image_dimensions_too_large"
                probe.verify()

            with Image.open(io.BytesIO(encoded)) as decoded:
                decoded.load()
                image = ImageOps.exif_transpose(decoded).convert("RGB")
    except Image.DecompressionBombError:
        return "image_dimensions_too_large"
    except Image.DecompressionBombWarning:
        return "image_dimensions_too_large"
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return "invalid_or_corrupt_image"

    scan = image.copy()
    scan.thumbnail(
        (MAX_SCAN_WIDTH, MAX_SCAN_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    return scan, image, source_size


def _pixel_data(image: Image.Image):
    """Iterate pixels across both current and older supported Pillow releases."""
    flattened = getattr(image, "get_flattened_data", None)
    if callable(flattened):
        return flattened()
    with warnings.catch_warnings():
        # Pillow 12 deprecates getdata(), but older unpinned releases do not
        # provide its replacement.  Keep the warning confined to this bridge.
        warnings.simplefilter("ignore", DeprecationWarning)
        return image.getdata()


def _artwork_perceptual_hash(image: Image.Image) -> int:
    """Return combined grayscale pHash+dHash without retaining portrait pixels."""
    grayscale = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    resized = grayscale.resize(
        (ARTWORK_HASH_SIZE, ARTWORK_HASH_SIZE),
        Image.Resampling.LANCZOS,
    )
    pixels = list(_pixel_data(resized))

    # A separable low-frequency DCT is materially cheaper than evaluating every
    # two-dimensional coefficient independently.  The DC coefficient is later
    # excluded, making the hash insensitive to uniform brightness changes such
    # as the game's missing-card grayscale treatment.
    horizontal = [
        [
            sum(
                pixels[row * ARTWORK_HASH_SIZE + column]
                * _ARTWORK_COSINES[frequency][column]
                for column in range(ARTWORK_HASH_SIZE)
            )
            for frequency in range(ARTWORK_HASH_MAX_FREQUENCY + 1)
        ]
        for row in range(ARTWORK_HASH_SIZE)
    ]
    coefficients = [
        sum(
            horizontal[row][horizontal_frequency]
            * _ARTWORK_COSINES[vertical_frequency][row]
            for row in range(ARTWORK_HASH_SIZE)
        )
        for vertical_frequency, horizontal_frequency
        in _ARTWORK_PHASH_FREQUENCIES
    ]
    median = statistics.median(coefficients)
    fingerprint = 0
    for coefficient in coefficients:
        fingerprint = (fingerprint << 1) | int(coefficient > median)

    difference_image = grayscale.resize((9, 8), Image.Resampling.LANCZOS)
    difference_pixels = list(_pixel_data(difference_image))
    for row in range(8):
        for column in range(8):
            left = difference_pixels[row * 9 + column]
            right = difference_pixels[row * 9 + column + 1]
            fingerprint = (fingerprint << 1) | int(right > left)
    return fingerprint


def _bounds_area(bounds: Bounds) -> int:
    return max(bounds.width, 0) * max(bounds.height, 0)


def _intersection_over_union(left: Bounds, right: Bounds) -> float:
    overlap_width = max(0, min(left.right, right.right) - max(left.left, right.left))
    overlap_height = max(0, min(left.bottom, right.bottom) - max(left.top, right.top))
    intersection = overlap_width * overlap_height
    union = _bounds_area(left) + _bounds_area(right) - intersection
    return intersection / union if union else 0.0


def _prune_nested_components(components: list[Bounds]) -> list[Bounds]:
    """Keep the largest frame when recompression splits frame and inner art."""
    kept: list[Bounds] = []
    for candidate in sorted(components, key=_bounds_area, reverse=True):
        candidate_area = _bounds_area(candidate)
        if any(
            (
                outer.left <= candidate.left
                and outer.top <= candidate.top
                and outer.right >= candidate.right
                and outer.bottom >= candidate.bottom
                and candidate_area <= _bounds_area(outer) * 0.85
            )
            # JPEG85 can move one inner-art edge one pixel outside its frame.
            # Those two boxes still have IoU >0.86; adjacent cards have zero.
            or _intersection_over_union(candidate, outer) >= 0.80
            for outer in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _adaptive_value_floor(values: list[int]) -> int:
    """Scale the frame value floor by how bright this capture actually is.

    Pillow's brightness transform scales HSV value linearly and leaves
    saturation, a ratio, almost still, so on a dim capture only the absolute
    value floor moves - and an absolute floor of 120 then erodes real frames
    below the component fill floor.  The frame-to-bright-end value ratio is
    brightness invariant (0.127-0.141 measured across native, brightness
    0.7-0.9, JPEG 70/30/15, and resize 0.5-1.5) while the image's own bright
    end tracks brightness faithfully, so the capture can be asked how bright it
    is instead of being assumed.

    ``min()`` is what makes this safe: on any capture as bright as the
    development set the floor is exactly the unchanged FRAME_MIN_VALUE, so the
    rule is inert on every image that already worked.  Only a measurably dim
    capture relaxes the floor, and only by the factor its own pixels report.
    """
    if not values:
        return FRAME_MIN_VALUE
    bright_end = sorted(values)[int(len(values) * 0.95)]
    return min(
        FRAME_MIN_VALUE,
        round(FRAME_MIN_VALUE * bright_end / NOMINAL_VALUE_P95),
    )


def _saturated_components(image: Image.Image) -> list[Bounds]:
    width, height = image.size
    hsv = image.convert("HSV")
    pixels = list(_pixel_data(hsv))
    floor = _adaptive_value_floor([value for _hue, _saturation, value in pixels])
    mask = bytearray(width * height)
    for index, (_hue, saturation, value) in enumerate(pixels):
        if saturation >= FRAME_MIN_SATURATION and value >= floor:
            mask[index] = 1

    components: list[Bounds] = []
    for seed in range(len(mask)):
        if not mask[seed]:
            continue
        mask[seed] = 0
        queue: deque[int] = deque((seed,))
        count = 0
        min_x = max_x = seed % width
        min_y = max_y = seed // width

        while queue:
            index = queue.popleft()
            y, x = divmod(index, width)
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            if x and mask[index - 1]:
                mask[index - 1] = 0
                queue.append(index - 1)
            if x + 1 < width and mask[index + 1]:
                mask[index + 1] = 0
                queue.append(index + 1)
            if y and mask[index - width]:
                mask[index - width] = 0
                queue.append(index - width)
            if y + 1 < height and mask[index + width]:
                mask[index + width] = 0
                queue.append(index + width)

        box = Bounds(min_x, min_y, max_x + 1, max_y + 1)
        if _is_card_sized_component(box, count, image.size):
            components.append(box)

    # Saturated artwork can itself form a card-sized island inside the real
    # category frame (the live Barbarian, Furnace, and Boxer Giant portraits do
    # this).  Keeping both turns an otherwise valid row into seven or eight
    # columns.  High-overlap non-maximum suppression also covers a one-pixel
    # JPEG edge escape without merging neighboring cards.
    return _prune_nested_components(components)


def _is_card_sized_component(
    box: Bounds,
    saturated_pixels: int,
    image_size: tuple[int, int],
) -> bool:
    image_width, _image_height = image_size
    width_fraction = box.width / image_width
    aspect = box.width / max(box.height, 1)
    fill = saturated_pixels / max(box.width * box.height, 1)
    return (
        0.06 <= width_fraction <= 0.14
        # The fixed reward track clips the bottom of the second visible row in
        # the live UI, making a valid frame almost square.
        and 0.55 <= aspect <= 1.05
        and fill >= 0.035
        and saturated_pixels >= 80
    )


def _coefficient_of_variation(values: list[float]) -> float:
    average = statistics.fmean(values)
    if average <= 0:
        return math.inf
    return statistics.pstdev(values) / average


def _cluster_components_by_row(boxes: list[Bounds]) -> list[list[Bounds]]:
    clusters: list[list[Bounds]] = []
    for box in sorted(boxes, key=lambda candidate: candidate.center_y):
        if not clusters:
            clusters.append([box])
            continue
        current = clusters[-1]
        center = statistics.fmean(item.center_y for item in current)
        typical_height = statistics.median(item.height for item in current)
        if abs(box.center_y - center) <= max(4.0, typical_height * 0.22):
            current.append(box)
        else:
            clusters.append([box])
    return clusters


def _validate_six_column_row(
    boxes: list[Bounds], image_width: int
) -> tuple[tuple[Bounds, ...], float] | None:
    if len(boxes) != 6:
        return None
    ordered = tuple(sorted(boxes, key=lambda box: box.center_x))
    widths = [float(box.width) for box in ordered]
    heights = [float(box.height) for box in ordered]
    centers = [box.center_x for box in ordered]
    spacings = [right - left for left, right in zip(centers, centers[1:])]

    width_cv = _coefficient_of_variation(widths)
    height_cv = _coefficient_of_variation(heights)
    spacing_cv = _coefficient_of_variation(spacings)
    mean_height = statistics.fmean(heights)
    alignment = (
        max(box.center_y for box in ordered)
        - min(box.center_y for box in ordered)
    ) / mean_height
    mean_width = statistics.fmean(widths)
    mean_spacing = statistics.fmean(spacings)
    span_fraction = (centers[-1] - centers[0]) / image_width

    if (
        width_cv > 0.08
        or height_cv > 0.08
        or spacing_cv > 0.08
        or alignment > 0.08
        or not 0.95 * mean_width <= mean_spacing <= 2.5 * mean_width
        or not 0.35 <= span_fraction <= 0.90
    ):
        return None

    worst_variation = max(width_cv, height_cv, spacing_cv, alignment)
    confidence = round(max(0.65, 1.0 - 4.0 * worst_variation), 3)
    return ordered, confidence


def _mean_hsv_channel(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    channel: int,
) -> float:
    crop = image.crop(bounds).convert("HSV")
    values = [pixel[channel] for pixel in _pixel_data(crop)]
    return statistics.fmean(values) if values else 0.0


def _relative_box(
    box: Bounds,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> tuple[int, int, int, int]:
    return (
        round(box.left + box.width * left),
        round(box.top + box.height * top),
        round(box.left + box.width * right),
        round(box.top + box.height * bottom),
    )


def _yellow_components(
    image: Image.Image,
    crop_bounds: tuple[int, int, int, int],
) -> list[tuple[Bounds, int]]:
    crop = image.crop(crop_bounds).convert("HSV")
    width, height = crop.size
    mask = bytearray(width * height)
    for index, (hue, saturation, value) in enumerate(_pixel_data(crop)):
        if (
            YELLOW_HUE_MIN <= hue <= YELLOW_HUE_MAX
            and saturation >= YELLOW_MIN_SATURATION
            and value >= YELLOW_MIN_VALUE
        ):
            mask[index] = 1

    components: list[tuple[Bounds, int]] = []
    for seed in range(len(mask)):
        if not mask[seed]:
            continue
        mask[seed] = 0
        queue: deque[int] = deque((seed,))
        count = 0
        min_x = max_x = seed % width
        min_y = max_y = seed // width
        while queue:
            index = queue.popleft()
            y, x = divmod(index, width)
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            if x and mask[index - 1]:
                mask[index - 1] = 0
                queue.append(index - 1)
            if x + 1 < width and mask[index + 1]:
                mask[index + 1] = 0
                queue.append(index + 1)
            if y and mask[index - width]:
                mask[index - width] = 0
                queue.append(index - width)
            if y + 1 < height and mask[index + width]:
                mask[index + width] = 0
                queue.append(index + width)
        components.append((Bounds(min_x, min_y, max_x + 1, max_y + 1), count))
    return components


def _has_badge_shape(
    image: Image.Image,
    box: Bounds,
    badge_bounds: tuple[int, int, int, int],
) -> tuple[bool, bool]:
    """Return (badge found, unresolved yellow signal)."""
    crop_left, crop_top, _crop_right, _crop_bottom = badge_bounds
    unresolved_pixels = 0
    for component, count in _yellow_components(image, badge_bounds):
        unresolved_pixels += count
        absolute = Bounds(
            crop_left + component.left,
            crop_top + component.top,
            crop_left + component.right,
            crop_top + component.bottom,
        )
        width_ratio = absolute.width / box.width
        height_ratio = absolute.height / box.height
        center_offset = abs(absolute.center_x - box.center_x) / box.width
        vertical_center = (absolute.center_y - box.top) / box.height
        fill = count / max(absolute.width * absolute.height, 1)
        if (
            # The public x2 calibration badge spans 0.457..0.462 card widths;
            # the known fiery-art false signal spans only 0.321.  This width
            # floor is the safer discriminator, while the lower fill permits
            # the dark ``x2`` glyph (observed fills 0.542..0.578).  A match is
            # still only an unverified-owned reminder, never duplicate supply.
            BADGE_MIN_WIDTH_RATIO <= width_ratio <= 0.72
            and 0.10 <= height_ratio <= 0.30
            and center_offset <= 0.14
            and 0.70 <= vertical_center <= 1.05
            # Live fiery artwork can make a centered yellow island with the
            # same rough dimensions as a badge.  A real rounded badge is much
            # more rectangular, even with the dark ``xN`` glyph cut out.
            and fill >= BADGE_MIN_FILL
        ):
            return True, False

    crop_area = max(
        (badge_bounds[2] - badge_bounds[0])
        * (badge_bounds[3] - badge_bounds[1]),
        1,
    )
    return False, unresolved_pixels / crop_area >= 0.12


def _classify_slot(image: Image.Image, box: Bounds, column: int) -> SlotScan:
    portrait_bounds = _relative_box(box, 0.24, 0.16, 0.76, 0.66)
    portrait_saturation = round(
        _mean_hsv_channel(image, portrait_bounds, channel=1), 2
    )

    if portrait_saturation <= MISSING_MAX_SATURATION:
        provisional: CardState = MISSING
        confidence = 0.97
    elif portrait_saturation >= OWNED_MIN_SATURATION:
        provisional = OWNED
        confidence = min(0.97, 0.78 + (portrait_saturation - 25.0) / 200.0)
    else:
        return SlotScan(
            column=column,
            state=UNKNOWN,
            confidence=0.0,
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("ambiguous_portrait_saturation",),
        )

    badge_bottom = math.ceil(box.bottom + box.height * 0.14)
    if badge_bottom > image.height:
        if provisional == MISSING:
            return SlotScan(
                column, provisional, confidence, box, portrait_saturation
            )
        return SlotScan(
            column=column,
            state=OWNED,
            confidence=min(confidence, 0.85),
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("badge_region_clipped", "duplicate_badge_unverified"),
        )

    badge_bounds = _relative_box(box, 0.10, 0.68, 0.90, 1.14)
    external_bounds = _relative_box(box, 0.20, 1.0, 0.80, 1.12)
    external_value = _mean_hsv_channel(
        image, external_bounds, channel=2
    )
    external_saturation = _mean_hsv_channel(
        image, external_bounds, channel=1
    )
    # The reward track only ever sits along the bottom of the screen, below the
    # grid. Without this guard the colour test also matched the grid's own pale
    # tan gutter, which is identically low-saturation and bright, so cards in
    # the upper row were reported as having an unreadable badge and the member
    # was asked "do you have more?" about cards with visibly no badge at all.
    #
    # Measured on live captures: the upper row's badge region ends around 0.56
    # of frame height and the lower row's around 0.81, so 0.70 sits in the gap.
    # This is a fraction rather than a fixed row index on purpose, because a
    # member may crop the track away entirely. A crop that removes the track
    # also removes the obstruction, so declining to flag it is correct; the
    # residual risk is a capture cropped so tightly that the track lands above
    # 0.70, which would read a hidden badge as no badge. That direction only
    # under-reports a spare, which a member can add back, rather than inventing
    # trade supply that does not exist.
    badge_near_screen_bottom = badge_bounds[3] >= image.height * 0.70
    reward_track_covers_badge = badge_near_screen_bottom and (
        (external_saturation < 55.0 and external_value > 165.0)
        # One calibrated capture catches the reward track at its darker upper
        # bevel; it is less bright but still distinctly less saturated than the
        # unobstructed category gutter above it.
        or (
            external_saturation < 90.0
            and 125.0 < external_value < 165.0
        )
    )
    if provisional != MISSING and (
        external_value < 70.0 or reward_track_covers_badge
    ):
        return SlotScan(
            column=column,
            state=OWNED,
            confidence=min(confidence, 0.85),
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("badge_region_obstructed", "duplicate_badge_unverified"),
        )

    has_badge, unresolved_yellow = _has_badge_shape(
        image, box, badge_bounds
    )
    if provisional == MISSING:
        if has_badge:
            # The badge wins. A duplicate badge is only ever drawn on a card
            # the player owns, so its presence is stronger evidence than a low
            # saturation reading. Intrinsically grey artwork reads as low
            # saturation even when owned: Cannon Cart, a grey mechanical
            # cannon, measured 19.5 while carrying a visible x2, and calling
            # that a conflict made an obviously owned spare unknown.
            return SlotScan(
                column=column,
                state=DUPLICATE,
                confidence=min(confidence, 0.85),
                bounds=box,
                portrait_saturation=portrait_saturation,
                warnings=("duplicate_badge_read", "grey_portrait_with_badge"),
            )
        if unresolved_yellow:
            return SlotScan(
                column=column,
                state=UNKNOWN,
                confidence=0.0,
                bounds=box,
                portrait_saturation=portrait_saturation,
                warnings=("portrait_badge_conflict",),
            )
        state = MISSING
    elif has_badge:
        # A live calibration set now exists: five unobstructed badges (four x2
        # and one x4) across two accounts, with no false positive in twenty
        # four slots.  Their geometry clusters tightly - width 0.442..0.473,
        # height 0.138..0.152, centre offset under 0.015, vertical centre
        # 0.959..0.987 - and the width floor keeps the known fiery-art signal
        # at 0.321 out.  A badge that clears all five tests is therefore read
        # as a spare rather than demoted to one copy.
        #
        # The exact count is deliberately not read.  The catalog stores only
        # missing/owned/spare, so x2 and x4 are the same fact, and reading the
        # glyph would be a harder problem for no gain.
        #
        # This still authorizes nothing on its own: the scan produces a draft
        # that the member confirms before anything is written.  What changed is
        # the default, so a correct read no longer costs a question per card.
        return SlotScan(
            column=column,
            state=DUPLICATE,
            confidence=min(confidence, 0.9),
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("duplicate_badge_read",),
        )
    elif unresolved_yellow:
        # A clearly coloured portrait already proves ownership. An unreadable
        # yellow blob in the badge area can only leave the SPARE question open,
        # so the card is owned with its badge unverified rather than unknown.
        # Discarding the confident half of the reading is what made Rocket
        # Balloon, at saturation 84, come back as "no idea".
        return SlotScan(
            column=column,
            state=OWNED,
            confidence=min(confidence, 0.85),
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("ambiguous_badge_signal", "duplicate_badge_unverified"),
        )
    else:
        state = OWNED

    return SlotScan(
        column=column,
        state=state,
        confidence=round(confidence, 3),
        bounds=box,
        portrait_saturation=portrait_saturation,
    )


_BASE_SCAN_WARNINGS = (
    "experimental_preview_only",
    "card_identity_not_inferred",
)


def scan_visible_rows(image_bytes: object) -> ScanResult:
    """Conservatively classify complete visible six-card rows in one still.

    The function never raises for bad user input and never assigns card names,
    category names, or collection positions.  Callers must treat every result
    as a preview requiring human review; ``PERSISTENCE_SAFE`` is permanently
    false, and identity is decided separately by the frozen row stack.
    """
    loaded = _load_still(image_bytes)
    if isinstance(loaded, str):
        return _result_failure(loaded, prior=_BASE_SCAN_WARNINGS)
    image, source_size = loaded
    return _scan_rows(image, source_size)


def _scan_rows(
    image: Image.Image,
    source_size: tuple[int, int],
) -> ScanResult:
    """Detect and classify rows in an already validated scan image."""
    base_warnings = _BASE_SCAN_WARNINGS
    candidates = _saturated_components(image)
    if not candidates:
        return _result_failure(
            "no_card_sized_components",
            source_size=source_size,
            scan_size=image.size,
            prior=base_warnings,
        )

    rows: list[RowScan] = []
    warnings_found = list(base_warnings)
    rejected_cluster = False
    for cluster in _cluster_components_by_row(candidates):
        validated = _validate_six_column_row(cluster, image.width)
        if validated is None:
            rejected_cluster = True
            continue
        ordered, layout_confidence = validated
        slots = tuple(
            _classify_slot(image, box, column)
            for column, box in enumerate(ordered, start=1)
        )
        row_bounds = Bounds(
            min(box.left for box in ordered),
            min(box.top for box in ordered),
            max(box.right for box in ordered),
            max(box.bottom for box in ordered),
        )
        rows.append(RowScan(
            row=len(rows) + 1,
            slots=slots,
            layout_confidence=layout_confidence,
            bounds=row_bounds,
        ))

    if rejected_cluster:
        warnings_found.append("non_six_or_irregular_cluster_ignored")
    if not rows:
        return _result_failure(
            "no_valid_six_column_rows",
            source_size=source_size,
            scan_size=image.size,
            prior=tuple(warnings_found),
        )

    rows.sort(key=lambda row: row.bounds.top)
    rows = [
        RowScan(index, row.slots, row.layout_confidence, row.bounds)
        for index, row in enumerate(rows, start=1)
    ]
    return ScanResult(
        rows=tuple(rows),
        source_size=source_size,
        scan_size=image.size,
        layout_confidence=min(row.layout_confidence for row in rows),
        warnings=tuple(warnings_found),
    )


def _hue_distance(left: float, right: float) -> float:
    """Circular hue distance: a super troop frame at 254 is 14 from centre 12."""
    difference = abs(left - right)
    return min(difference, 256.0 - difference)


# --- the frozen row identity stack -----------------------------------------
#
# Everything from here to `_decide_row_identity` is the frozen development
# package, transcribed into production unchanged.  Every constant lives in
# `card_scan_reference`; none of them may be retuned here.  Geometry is chosen
# from image structure and never sees an identity score.


def _percentile(values, share: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def _row_geometry(
    result: ScanResult,
) -> tuple[float, tuple[float, ...], list[tuple[float, float]]]:
    """Shared card width, column centres, and each row's (top, height).

    Medians across every detected row, so one noisy frame edge cannot move a
    crop.  All three are in scan-image coordinates.
    """
    width = statistics.median(
        slot.bounds.width for row in result.rows for slot in row.slots
    )
    columns = tuple(
        statistics.median(
            row.slots[column].bounds.center_x for row in result.rows
        )
        for column in range(COLLECTION_COLUMNS)
    )
    rows = [
        (
            statistics.median(slot.bounds.top for slot in row.slots),
            statistics.median(slot.bounds.height for slot in row.slots),
        )
        for row in result.rows
    ]
    return width, columns, rows


def _band_sample_offsets(expected_width: float) -> list[int]:
    """The five logical band positions, in source pixels below the top edge.

    Positions are a fraction of measured card width, so the logical pattern is
    identical at every resolution and a bigger capture cannot spend its extra
    pixel rows as extra evidence.  Two positions may land on the same pixel row
    on a small capture; they still count as two logical samples.
    """
    span = reference.BAND_BOTTOM - reference.BAND_TOP
    return [
        max(1, round(expected_width * (
            reference.BAND_TOP + span * index / (reference.BAND_SAMPLES - 1)
        )))
        for index in range(reference.BAND_SAMPLES)
    ]


def _saturation_line(hsv: Image.Image, y: int, x_from: int, x_to: int):
    """One scanline's saturation channel, read in a single pass."""
    if not (0 <= y < hsv.size[1]):
        return None
    x_from = max(0, x_from)
    x_to = min(hsv.size[0], x_to)
    if x_to - x_from < 2:
        return None
    return hsv.crop((x_from, y, x_to, y + 1)).tobytes()[1::3], x_from


def _frame_runs(
    hsv: Image.Image,
    y: int,
    x_from: int,
    x_to: int,
    expected_width: float,
) -> list[tuple[int, int]] | None:
    """Contiguous saturated stretches, thresholded against this line only."""
    line = _saturation_line(hsv, y, x_from, x_to)
    if line is None:
        return None
    saturations, start_x = line
    if len(saturations) < expected_width:
        return None
    high = _percentile(saturations, 0.9)
    low = _percentile(saturations, 0.1)
    if high - low < reference.BAND_MIN_CONTRAST:
        # No frame-to-gap contrast on this line, so it says nothing at all.
        return None
    threshold = (high + low) / 2
    runs: list[tuple[int, int]] = []
    start = None
    for offset, saturation in enumerate(saturations):
        if saturation >= threshold:
            if start is None:
                start = offset
        elif start is not None:
            runs.append((start_x + start, start_x + offset - 1))
            start = None
    if start is not None:
        runs.append((start_x + start, start_x + len(saturations) - 1))
    return [
        run for run in runs
        if run[1] - run[0] >= expected_width * reference.BAND_MIN_RUN_SHARE
    ]


def _assign_runs(
    runs: list[tuple[int, int]],
    centres: list[float],
    pitch: float,
) -> dict[int, tuple[int, float]] | None:
    """One frame run per expected card centre, or an explicit refusal.

    Six runs appearing somewhere on the line is not evidence that six cards
    were measured.  Each expected centre must fall inside exactly one run, and
    no run may swallow two centres - which is what a weld between neighbouring
    cards looks like, and it rejects the whole line.
    """
    owner: dict[tuple[int, int], list[int]] = {}
    for centre_index, centre in enumerate(centres):
        for run in runs:
            if run[0] <= centre <= run[1]:
                owner.setdefault(run, []).append(centre_index)
                break
    if any(len(claimants) > 1 for claimants in owner.values()):
        return None

    assigned: dict[int, tuple[int, float]] = {}
    for run, claimants in owner.items():
        width = run[1] - run[0] + 1
        share = width / pitch
        if not (
            reference.RUN_MIN_OF_PITCH <= share <= reference.RUN_MAX_OF_PITCH
        ):
            # Pathological width: drop this measurement rather than trust it.
            continue
        assigned[claimants[0]] = (width, (run[0] + run[1]) / 2)
    return assigned or None


def _find_source_top(
    hsv: Image.Image,
    x0: int,
    x1: int,
    start: float,
    reach: int,
) -> int | None:
    """First scanline where the six frames are lit, at source resolution.

    This deliberately keeps the fixed saturation/value predicate rather than
    the brightness-relative floor.  It is the frozen sampler's known limit: on
    an extremely dim capture it fails to find the edge, which costs recall and
    fails closed.  Changing it would change a frozen recognition decision.
    """
    image_width, image_height = hsv.size
    x0 = max(0, min(image_width - 1, x0))
    x1 = max(x0 + 1, min(image_width, x1))
    step = max(1, (x1 - x0) // 24)
    for offset in range(reach):
        y = int(start + offset)
        if not (0 <= y < image_height):
            return None
        pixels = [hsv.getpixel((x, y)) for x in range(x0, x1, step)]
        lit = sum(
            1 for _hue, saturation, value in pixels
            if saturation >= FRAME_MIN_SATURATION and value >= FRAME_MIN_VALUE
        )
        if lit >= len(pixels) * 0.6:
            return y
    return None


def _slot_frame_category(hues: list[int], lines: int) -> str | None:
    """Observe one slot's category, or answer unknown.

    The classifier is a veto and never chooses a card, so a confident mistake
    would reject a legitimate row.  It answers only when the nearest category
    is close enough AND clearly ahead of the runner-up; the documented
    elixir/dark-elixir tolerance overlap therefore answers unknown by
    construction rather than by preference.
    """
    if lines < reference.CATEGORY_MIN_LINES or not hues:
        return None
    distances = {
        name: statistics.median(_hue_distance(hue, centre) for hue in hues)
        for name, centre in CATEGORY_FRAME_HUES.items()
    }
    ordered = sorted(distances.items(), key=lambda item: item[1])
    (nearest_name, nearest), (_runner_name, runner_up) = ordered[0], ordered[1]
    if nearest > reference.CATEGORY_TOLERANCE:
        return None
    if runner_up - nearest < reference.CATEGORY_MARGIN:
        return None
    return nearest_name


def _measure_row_band(
    hsv: Image.Image,
    source_top: int,
    columns: tuple[float, ...],
    scan_width: float,
    scale: float,
) -> tuple[dict | None, str]:
    """Six card widths, centres, and frame categories from one band.

    Each card is built only from the band lines that actually reached it.  The
    hue pixels come from the same assigned runs, so the category measurement
    inherits the sampler's resolution independence for free.
    """
    expected = scan_width * scale
    centres = [centre * scale for centre in columns]
    pitch = statistics.median(
        centres[index + 1] - centres[index]
        for index in range(COLLECTION_COLUMNS - 1)
    )
    x_from = int((columns[0] - scan_width) * scale)
    x_to = int((columns[-1] + scan_width) * scale)

    per_card_width: list[list[int]] = [[] for _ in range(COLLECTION_COLUMNS)]
    per_card_centre: list[list[float]] = [[] for _ in range(COLLECTION_COLUMNS)]
    per_card_hues: list[list[int]] = [[] for _ in range(COLLECTION_COLUMNS)]
    for offset in _band_sample_offsets(expected):
        y = source_top + offset
        runs = _frame_runs(hsv, y, x_from, x_to, expected)
        if not runs:
            continue
        assigned = _assign_runs(runs, centres, pitch)
        if assigned is None:
            continue
        for index, (width, centre) in assigned.items():
            per_card_width[index].append(width)
            per_card_centre[index].append(centre)
            left = max(0, int(centre - (width - 1) / 2))
            right = min(hsv.size[0] - 1, int(centre + (width - 1) / 2))
            per_card_hues[index].extend(
                hsv.getpixel((x, y))[0] for x in range(left, right + 1)
            )

    support = [len(values) for values in per_card_width]
    if min(support) < reference.MIN_LINES_PER_CARD:
        thin = [
            index + 1 for index, count in enumerate(support)
            if count < reference.MIN_LINES_PER_CARD
        ]
        return None, (
            f"cards {thin} measured on {support} of "
            f"{reference.BAND_SAMPLES} band lines"
        )

    widths = [statistics.median(values) for values in per_card_width]
    card_centres = [statistics.median(values) for values in per_card_centre]
    median_width = statistics.median(widths)
    ordered = sorted(widths)
    five = min(
        (ordered[:5], ordered[1:]),
        key=lambda group: group[-1] - group[0],
    )
    measured_pitch = statistics.median(
        card_centres[index + 1] - card_centres[index]
        for index in range(COLLECTION_COLUMNS - 1)
    )
    return {
        "widths": widths,
        "centres": card_centres,
        "median_width": median_width,
        "all_spread": (max(widths) - min(widths)) / median_width,
        "five_spread": (five[-1] - five[0]) / median_width,
        "width_over_pitch": median_width / measured_pitch,
        # One pixel over the card width: the finest distinction this capture
        # can draw, and therefore the slack a frozen spread limit owes it.
        "quantum": reference.SPREAD_QUANT_PIXELS / median_width,
        "categories": tuple(
            _slot_frame_category(per_card_hues[index], support[index])
            for index in range(COLLECTION_COLUMNS)
        ),
    }, ""


def _geometry_breach(evidence: dict) -> str:
    """Width evidence that does not describe six equal cards in a row."""
    quantum = evidence["quantum"]
    if evidence["five_spread"] > reference.FIVE_SPREAD_MAX + quantum:
        return f"five-card width spread {evidence['five_spread']:.4f}"
    if evidence["all_spread"] > reference.ALL_SPREAD_MAX + quantum:
        return f"six-card width spread {evidence['all_spread']:.4f}"
    if not (
        reference.PITCH_MIN
        <= evidence["width_over_pitch"]
        <= reference.PITCH_MAX
    ):
        return f"width over pitch {evidence['width_over_pitch']:.4f}"
    return ""


def _reference_row_scores(hashes: tuple[int, ...]) -> dict[int, float]:
    """Mean bit distance from this row to each catalog row's nearest template."""
    return {
        row: min(
            statistics.mean(
                (observed ^ template_hash).bit_count()
                for observed, template_hash in zip(hashes, template)
            )
            for template in templates
        )
        for row, templates in reference.REFERENCE_BANK.items()
    }


def _reference_card_distance(slot_hash: int, catalog_index: int) -> int | None:
    """Bit distance from one slot to one catalog card's nearest template."""
    row = catalog_index // COLLECTION_COLUMNS + 1
    slot = catalog_index % COLLECTION_COLUMNS
    templates = reference.REFERENCE_BANK.get(row)
    if not templates:
        return None
    return min(
        (slot_hash ^ template[slot]).bit_count() for template in templates
    )


def _slot_artwork_verdict(slot_hash: int, expected_index: int) -> str:
    """Judge one slot against same-category rivals only.

    Rivals are drawn from the expected card's own category rather than filtered
    by the observed one.  If the category filtered the candidate set instead, a
    wrong cross-category match could be forced back into the target's category
    and thereby rescued.
    """
    expected = _reference_card_distance(slot_hash, expected_index)
    if expected is None:
        return "ambiguous"
    category = CARDS[expected_index].category
    rival = None
    for index, card in enumerate(CARDS):
        if index == expected_index or card.category != category:
            continue
        distance = _reference_card_distance(slot_hash, index)
        if distance is not None and (rival is None or distance < rival):
            rival = distance
    if rival is None:
        return "ambiguous"
    if rival + reference.SLOT_GAP_MARGIN <= expected \
            or expected >= reference.SLOT_GROSS:
        return "contradicted"
    if expected <= reference.SLOT_SUPPORT_MAX \
            and expected + reference.SLOT_GAP_MARGIN <= rival:
        return "supported"
    return "ambiguous"


def _decide_row_identity(
    hashes: tuple[int, ...],
    categories: tuple[str | None, ...],
) -> tuple[str, str, int, float, float]:
    """Run the frozen decision order over one registered row.

    Returns ``(outcome, reason, proposed row, top1, gap)``.  ``accepted`` is
    the only outcome that yields an identity; every other one leaves the row's
    six positions to the manual editor.
    """
    scores = _reference_row_scores(hashes)
    # Ranking is by (score, catalog row), so a tie breaks on row number rather
    # than dictionary order.  Scores reduce to one per catalog row before
    # ranking, so the runner-up is structurally a different catalog row.
    ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    (proposed_row, top1), (_runner_up_row, top2) = ordered[0], ordered[1]
    gap = top2 - top1

    supported: list[bool] = []
    for slot in range(COLLECTION_COLUMNS):
        expected_index = (proposed_row - 1) * COLLECTION_COLUMNS + slot
        observed = categories[slot]
        if observed is not None and observed != CARDS[expected_index].category:
            return (
                "category",
                f"card {slot + 1} has a {observed} frame",
                proposed_row, top1, gap,
            )
        verdict = _slot_artwork_verdict(hashes[slot], expected_index)
        if verdict == "contradicted":
            return (
                "slot",
                f"card {slot + 1} artwork contradicts the row",
                proposed_row, top1, gap,
            )
        # Category agreement is necessary and never sufficient: an unknown
        # category cannot support a slot, so the row fails closed.
        supported.append(verdict == "supported" and observed is not None)

    if not all(supported):
        unsupported = [
            index + 1 for index, ok in enumerate(supported) if not ok
        ]
        return (
            "unresolved",
            f"cards {unsupported} are not clearly supported",
            proposed_row, top1, gap,
        )
    if top1 > ROW_GATE_TOP1_MAX:
        return (
            "distance",
            f"row distance {top1:.2f} over {ROW_GATE_TOP1_MAX:.2f}",
            proposed_row, top1, gap,
        )
    if gap < ROW_GATE_GAP_MIN:
        return (
            "separation",
            f"rival gap {gap:.2f} under {ROW_GATE_GAP_MIN:.2f}",
            proposed_row, top1, gap,
        )
    return "accepted", "", proposed_row, top1, gap


@dataclass(frozen=True, slots=True)
class _RegisteredRow:
    """One detected row, measured and hashed, before identity is decided."""

    row_index: int
    slots: tuple[SlotScan, ...]
    hashes: tuple[int, ...] | None
    categories: tuple[str | None, ...]
    reason: str


def _register_capture(
    payload: object,
) -> tuple[ScanResult, tuple[_RegisteredRow, ...]]:
    """Detect every visible row, then measure and hash each one."""
    loaded = _load_still_pair(payload)
    if isinstance(loaded, str):
        return _result_failure(loaded, prior=_BASE_SCAN_WARNINGS), ()
    scan, source, source_size = loaded
    result = _scan_rows(scan, source_size)
    if not result.rows:
        return result, ()

    scan_width, columns, row_bounds = _row_geometry(result)
    scale = source.size[0] / scan.size[0]
    hsv = source.convert("HSV")
    reach = int(scale * 4) + 4
    x0 = round((columns[0] + scan_width * ARTWORK_CROP_LEFT) * scale)
    x1 = round((columns[-1] + scan_width * ARTWORK_CROP_RIGHT) * scale)

    unmeasured = (None,) * COLLECTION_COLUMNS
    registered: list[_RegisteredRow] = []
    for index, row in enumerate(result.rows):
        top, _height = row_bounds[index]
        source_top = _find_source_top(
            hsv, x0, x1, top * scale - scale * 2, reach
        )
        if source_top is None:
            registered.append(_RegisteredRow(
                index, row.slots, None, unmeasured, "top edge not found",
            ))
            continue
        evidence, failure = _measure_row_band(
            hsv, source_top, columns, scan_width, scale
        )
        if evidence is None:
            registered.append(
                _RegisteredRow(index, row.slots, None, unmeasured, failure)
            )
            continue
        breach = _geometry_breach(evidence)
        if breach:
            registered.append(
                _RegisteredRow(index, row.slots, None, unmeasured, breach)
            )
            continue
        width = evidence["median_width"]
        card_height = width * CARD_ASPECT
        registered.append(_RegisteredRow(
            row_index=index,
            slots=row.slots,
            hashes=tuple(
                _artwork_perceptual_hash(source.crop((
                    round(centre + width * ARTWORK_CROP_LEFT),
                    round(source_top + card_height * ARTWORK_CROP_TOP),
                    round(centre + width * ARTWORK_CROP_RIGHT),
                    round(source_top + card_height * ARTWORK_CROP_BOTTOM),
                )))
                for centre in evidence["centres"]
            ),
            categories=evidence["categories"],
            reason="",
        ))
    return result, tuple(registered)


def _empty_draft_card(card, catalog_index: int) -> DraftCardScan:
    """A catalog position no accepted row covered, so a human must supply it."""
    return DraftCardScan(
        card_id=card.id,
        card_name=card.name,
        category_id=card.category,
        catalog_index=catalog_index,
        global_row=(catalog_index - 1) // COLLECTION_COLUMNS + 1,
        column=(catalog_index - 1) % COLLECTION_COLUMNS + 1,
        state=UNKNOWN,
        confidence=0.0,
        source_index=None,
        warnings=("unseen_card", "manual_review_required"),
    )


def _checkpoint_card_state(value: object) -> CardState | None:
    if value in (MISSING, OWNED, DUPLICATE, UNKNOWN):
        return value  # type: ignore[return-value]
    if type(value) is int:
        return {
            0: MISSING,
            1: OWNED,
            2: DUPLICATE,
        }.get(value)
    return None


def _checkpoint_id_set(value: object) -> set[str] | None:
    if value is None:
        return set()
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return None
    if not all(isinstance(item, str) for item in values):
        return None
    ids = set(values)
    if not ids <= {card.id for card in CARDS}:
        return None
    return ids


def _checkpoint_warnings(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return None
    if not all(isinstance(item, str) for item in values):
        return None
    return tuple(dict.fromkeys(values))


def _rows_are_atomic(mapped: Mapping[int, DraftCardScan]) -> bool:
    """A checkpoint may retain whole accepted rows, never identity fragments.

    Row atomicity is the persistence side of the recognition rule: a row is
    accepted as six cards or not at all, so five apparently good cards from a
    rejected row must never survive into a later batch as trusted evidence.
    """
    for row in range(COLLECTION_ROWS):
        start = row * COLLECTION_COLUMNS + 1
        count = sum(
            index in mapped
            for index in range(start, start + COLLECTION_COLUMNS)
        )
        if count not in (0, COLLECTION_COLUMNS):
            return False
    return True


def _validated_prior_cards(
    prior_draft: object,
) -> tuple[dict[int, DraftCardScan], bool]:
    """Return identity-bound prior cards or reject the checkpoint atomically."""
    if prior_draft is None:
        return {}, True

    if isinstance(prior_draft, CollectionScanDraft):
        if len(prior_draft.cards) != len(CARDS):
            return {}, False
        mapped: dict[int, DraftCardScan] = {}
        for catalog_index, (card, record) in enumerate(
            zip(CARDS, prior_draft.cards),
            start=1,
        ):
            if (
                record.card_id != card.id
                or record.card_name != card.name
                or record.category_id != card.category
                or record.catalog_index != catalog_index
                or record.global_row != (catalog_index - 1) // COLLECTION_COLUMNS + 1
                or record.column != (catalog_index - 1) % COLLECTION_COLUMNS + 1
                or record.state not in (MISSING, OWNED, DUPLICATE, UNKNOWN)
                or isinstance(record.confidence, bool)
                or not isinstance(record.confidence, (int, float))
                or not math.isfinite(record.confidence)
                or not 0.0 <= record.confidence <= 1.0
                or not all(isinstance(item, str) for item in record.warnings)
                or (
                    record.source_index is not None
                    and (
                        type(record.source_index) is not int
                        or record.source_index < 0
                    )
                )
                or (
                    record.source_index is None
                    and (record.state != UNKNOWN or record.confidence != 0.0)
                )
            ):
                return {}, False
            if record.source_index is not None:
                mapped[catalog_index] = DraftCardScan(
                    card_id=record.card_id,
                    card_name=record.card_name,
                    category_id=record.category_id,
                    catalog_index=record.catalog_index,
                    global_row=record.global_row,
                    column=record.column,
                    state=record.state,
                    confidence=float(record.confidence),
                    source_index=0,
                    warnings=tuple(record.warnings),
                )
        return (mapped, True) if _rows_are_atomic(mapped) else ({}, False)

    if not isinstance(prior_draft, Mapping):
        return {}, False
    if prior_draft.get("identity_bound") is not True:
        return {}, False
    if prior_draft.get("errors"):
        return {}, False
    if prior_draft.get("version") not in (SCAN_CHECKPOINT_VERSION, 2):
        return {}, False

    raw_states = prior_draft.get("card_states")
    raw_confidences = prior_draft.get("card_confidences")
    raw_warnings = prior_draft.get("card_warnings", {})
    if not isinstance(raw_states, Mapping):
        return {}, False
    if not isinstance(raw_confidences, Mapping):
        return {}, False
    if not isinstance(raw_warnings, Mapping):
        return {}, False

    unknown_ids = _checkpoint_id_set(prior_draft.get("unknown_card_ids"))
    unseen_ids = _checkpoint_id_set(prior_draft.get("unseen_card_ids"))
    unverified_ids = _checkpoint_id_set(
        prior_draft.get("duplicate_unverified_card_ids")
    )
    if unknown_ids is None or unseen_ids is None or unverified_ids is None:
        return {}, False

    catalog_ids = {card.id for card in CARDS}
    state_ids = set(raw_states)
    confidence_ids = set(raw_confidences)
    warning_ids = set(raw_warnings)
    if (
        not all(isinstance(card_id, str) for card_id in state_ids)
        or not all(isinstance(card_id, str) for card_id in confidence_ids)
        or not all(isinstance(card_id, str) for card_id in warning_ids)
        or not state_ids <= catalog_ids
        or confidence_ids != state_ids
        or not warning_ids <= catalog_ids
        or state_ids & unknown_ids
        or state_ids & unseen_ids
        or not unverified_ids <= state_ids
        or state_ids | unknown_ids | unseen_ids != catalog_ids
    ):
        return {}, False

    seen_unknown_ids = unknown_ids - unseen_ids
    cards_by_id = {card.id: (index, card) for index, card in enumerate(CARDS, 1)}
    mapped = {}
    for card_id in state_ids | seen_unknown_ids:
        catalog_index, card = cards_by_id[card_id]
        if card_id in seen_unknown_ids:
            state: CardState = UNKNOWN
            confidence = 0.0
        else:
            parsed_state = _checkpoint_card_state(raw_states[card_id])
            raw_confidence = raw_confidences.get(card_id)
            if (
                parsed_state is None
                or parsed_state == UNKNOWN
                or isinstance(raw_confidence, bool)
                or not isinstance(raw_confidence, (int, float))
                or not math.isfinite(raw_confidence)
                or not 0.0 <= raw_confidence <= 1.0
            ):
                return {}, False
            state = parsed_state
            confidence = float(raw_confidence)

        warnings_found = _checkpoint_warnings(raw_warnings.get(card_id))
        if warnings_found is None:
            return {}, False
        if card_id in unverified_ids:
            if state != OWNED:
                return {}, False
            warnings_found = tuple(dict.fromkeys((
                *warnings_found,
                "duplicate_badge_unverified",
            )))
        mapped[catalog_index] = DraftCardScan(
            card_id=card.id,
            card_name=card.name,
            category_id=card.category,
            catalog_index=catalog_index,
            global_row=(catalog_index - 1) // COLLECTION_COLUMNS + 1,
            column=(catalog_index - 1) % COLLECTION_COLUMNS + 1,
            state=state,
            confidence=confidence,
            source_index=0,
            warnings=warnings_found,
        )

    return (mapped, True) if _rows_are_atomic(mapped) else ({}, False)


def collection_scan_checkpoint(draft: CollectionScanDraft) -> dict[str, object]:
    """Return a BSON-safe parsed-state checkpoint for a later upload batch."""
    if not isinstance(draft, CollectionScanDraft):
        raise TypeError("draft must be a CollectionScanDraft")

    mapped, valid = _validated_prior_cards(draft)
    if not valid:
        raise ValueError("draft is not an identity-bound collection scan")
    seen = tuple(mapped[index] for index in sorted(mapped))
    accepted_rows = _accepted_rows_in(mapped)
    missing_global_rows = [
        row for row in range(1, COLLECTION_ROWS + 1) if row not in accepted_rows
    ]
    accepted_page_numbers = _pages_fully_covered(accepted_rows)
    missing_page_numbers = [
        page for page in range(1, COLLECTION_CAPTURE_COUNT + 1)
        if page not in accepted_page_numbers
    ]
    unseen_card_ids = [
        card.id
        for catalog_index, card in enumerate(CARDS, start=1)
        if catalog_index not in mapped
    ]
    return {
        "version": SCAN_CHECKPOINT_VERSION,
        "card_states": {
            card.card_id: card.state
            for card in seen
            if card.state != UNKNOWN
        },
        "card_confidences": {
            card.card_id: float(card.confidence)
            for card in seen
            if card.state != UNKNOWN
        },
        "card_warnings": {
            card.card_id: list(card.warnings)
            for card in seen
            if card.warnings
        },
        "unknown_card_ids": [
            card.card_id for card in seen if card.state == UNKNOWN
        ],
        "unseen_card_ids": unseen_card_ids,
        "duplicate_unverified_card_ids": [
            card.card_id
            for card in seen
            if "duplicate_badge_unverified" in card.warnings
        ],
        "accepted_global_rows": list(accepted_rows),
        "accepted_page_numbers": accepted_page_numbers,
        "missing_page_numbers": missing_page_numbers,
        "missing_global_rows": missing_global_rows,
        "identity_bound": True,
        "coverage_complete": not unseen_card_ids,
        "errors": [],
    }


def _accepted_rows_in(mapped: Mapping[int, DraftCardScan]) -> tuple[int, ...]:
    """Catalog rows whose six positions are all present."""
    return tuple(
        row
        for row in range(1, COLLECTION_ROWS + 1)
        if all(
            index in mapped
            for index in range(
                (row - 1) * COLLECTION_COLUMNS + 1,
                row * COLLECTION_COLUMNS + 1,
            )
        )
    )


def _pages_fully_covered(accepted_rows) -> list[int]:
    """Screen pages whose two catalog rows were both accepted."""
    rows = set(accepted_rows)
    return [
        page
        for page in range(1, COLLECTION_CAPTURE_COUNT + 1)
        if {page * 2 - 1, page * 2} <= rows
    ]


def _row_cards(
    catalog_row: int,
    source_index: int,
    slots: tuple[SlotScan, ...],
) -> dict[int, DraftCardScan]:
    """Bind one accepted row's six slots to their catalog positions."""
    mapped: dict[int, DraftCardScan] = {}
    for slot in slots:
        catalog_index = (catalog_row - 1) * COLLECTION_COLUMNS + slot.column
        card = CARDS[catalog_index - 1]
        mapped[catalog_index] = DraftCardScan(
            card_id=card.id,
            card_name=card.name,
            category_id=card.category,
            catalog_index=catalog_index,
            global_row=catalog_row,
            column=slot.column,
            state=slot.state,
            confidence=slot.confidence,
            source_index=source_index,
            warnings=slot.warnings,
        )
    return mapped


def _merge_repeat_cards(
    mapped: dict[int, DraftCardScan],
    incoming: Mapping[int, DraftCardScan],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Improve unknowns, but downgrade contradictory known states to unknown."""
    resolved: list[str] = []
    conflicts: list[str] = []
    for catalog_index, candidate in incoming.items():
        previous = mapped[catalog_index]
        if previous.state == candidate.state:
            continue
        if (
            previous.state == UNKNOWN
            and "conflicting_duplicate_capture_state" not in previous.warnings
            and candidate.state != UNKNOWN
        ):
            mapped[catalog_index] = candidate
            resolved.append(candidate.card_id)
            continue
        if candidate.state == UNKNOWN:
            continue

        conflicts.append(candidate.card_id)
        mapped[catalog_index] = DraftCardScan(
            card_id=previous.card_id,
            card_name=previous.card_name,
            category_id=previous.category_id,
            catalog_index=previous.catalog_index,
            global_row=previous.global_row,
            column=previous.column,
            state=UNKNOWN,
            confidence=0.0,
            source_index=previous.source_index,
            warnings=tuple(dict.fromkeys((
                *previous.warnings,
                *candidate.warnings,
                "conflicting_duplicate_capture_state",
            ))),
        )
    return tuple(resolved), tuple(conflicts)


def _capture_failure_code(result: ScanResult) -> str:
    """The one code explaining why a capture produced no usable row."""
    for code in reversed(result.warnings):
        if code not in _BASE_SCAN_WARNINGS:
            return code
    return "no_valid_six_column_rows"


def _fail_closed_draft(
    payload_count: int,
    errors: tuple[str, ...],
) -> CollectionScanDraft:
    """Every position unseen, with the reason recorded and nothing guessed."""
    cards = tuple(
        _empty_draft_card(card, index)
        for index, card in enumerate(CARDS, start=1)
    )
    categories = tuple(
        CategoryScanDraft(
            category_id=category.id,
            category_name=category.name,
            cards=tuple(
                card for card in cards if card.category_id == category.id
            ),
            recognized_count=0,
            unknown_card_ids=tuple(
                card.card_id for card in cards
                if card.category_id == category.id
            ),
            unseen_card_ids=tuple(
                card.card_id for card in cards
                if card.category_id == category.id
            ),
            duplicate_unverified_card_ids=(),
            complete=False,
        )
        for category in CATEGORY_BY_ID.values()
    )
    every_card = tuple(card.card_id for card in cards)
    every_row = tuple(range(1, COLLECTION_ROWS + 1))
    return CollectionScanDraft(
        cards=cards,
        categories=categories,
        captures=tuple(
            CollectionCaptureScan(
                input_index=index,
                accepted=False,
                global_rows=(),
                source_size=None,
                scan_size=None,
                warnings=errors,
            )
            for index in range(1, payload_count + 1)
        ),
        accepted_page_numbers=(),
        missing_page_numbers=tuple(range(1, COLLECTION_CAPTURE_COUNT + 1)),
        missing_global_rows=every_row,
        recognized_count=0,
        missing_count=0,
        owned_count=0,
        duplicate_count=0,
        unknown_count=len(every_card),
        unknown_card_ids=every_card,
        unseen_card_ids=every_card,
        duplicate_unverified_card_ids=(),
        coverage_complete=False,
        complete=False,
        warnings=(
            "experimental_review_draft",
            "human_confirmation_required",
            "manual_review_required",
        ),
        accepted_global_rows=(),
        manual_required_global_rows=every_row,
        manual_required_card_ids=every_card,
        row_decisions=(),
        errors=errors,
    )


def scan_collection_screenshots(
    image_items: object,
    *,
    prior_draft: object = None,
) -> CollectionScanDraft:
    """Build a conservative 60-card review draft from any-order screenshots.

    Up to ten still images may be supplied in any order.  Every complete
    six-card row found in them is recognized on its own against the frozen
    reference: a row that clears the category veto, the per-slot artwork guard
    and the frozen row gate contributes its six identity-bound card states, and
    a row that fails any of them contributes nothing and is reported as needing
    manual review.  Upload order is never an identity signal, and a repeated
    row is simply recognized again.

    ``prior_draft`` may be an earlier :class:`CollectionScanDraft`, the BSON-safe
    mapping returned by :func:`collection_scan_checkpoint`, or the normalized
    version-2 mapping used by the Discord adapter.  Only complete accepted rows
    are accumulated; invalid checkpoints are rejected atomically.  This lets a
    caller discard raw image bytes between follow-up upload messages.

    Clearly colored cards with an obstructed badge are recorded as ``owned`` --
    the minimum quantity proven by the portrait -- and listed in
    ``duplicate_unverified_card_ids``.  This avoids inventing trade supply while
    still reducing review to the potentially hidden duplicates.  The returned
    draft always requires explicit human confirmation.
    """
    if isinstance(image_items, (bytes, bytearray, memoryview)):
        payloads = (image_items,)
    else:
        try:
            payloads = tuple(islice(
                iter(image_items),  # type: ignore[arg-type]
                MAX_COLLECTION_INPUTS + 1,
            ))
        except TypeError:
            payloads = ()

    # The sealed evaluator verified its artifact before answering any query.
    # Production cannot re-read that file, so it checks the same relationships
    # against the live catalog and detector constants, and refuses outright if
    # the frozen reference no longer describes this code.
    reference_problems = reference.reference_problems(
        catalog=CARDS,
        frame_min_saturation=FRAME_MIN_SATURATION,
        frame_min_value=FRAME_MIN_VALUE,
        category_frame_hues=CATEGORY_FRAME_HUES,
    )
    if reference_problems:
        return _fail_closed_draft(
            min(len(payloads), MAX_COLLECTION_INPUTS),
            tuple(f"frozen_reference_{code}" for code in reference_problems),
        )

    mapped, prior_valid = _validated_prior_cards(prior_draft)
    had_prior = prior_draft is not None
    captures: list[CollectionCaptureScan] = []
    row_decisions: list[RowScanDecision] = []
    too_many = len(payloads) > MAX_COLLECTION_INPUTS
    rows_added = False
    repeat_ignored = False
    repeat_merged = False
    repeat_conflict = False
    manual_rows_seen = False

    for input_index, payload in enumerate(
        payloads[:MAX_COLLECTION_INPUTS], start=1
    ):
        result, registered = _register_capture(payload)
        if not registered:
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=(_capture_failure_code(result),),
            ))
            continue

        accepted_rows: list[int] = []
        conflicting_card_ids: list[str] = []
        capture_codes: list[str] = []
        repeats: list[str] = []
        manual_rows = 0
        for record in registered:
            if record.hashes is None:
                decision = RowScanDecision(
                    input_index=input_index,
                    row_index=record.row_index,
                    accepted=False,
                    outcome="geometry",
                    reason=record.reason,
                )
            else:
                outcome, reason, proposed_row, top1, gap = _decide_row_identity(
                    record.hashes, record.categories
                )
                accepted = outcome == "accepted"
                decision = RowScanDecision(
                    input_index=input_index,
                    row_index=record.row_index,
                    accepted=accepted,
                    outcome=outcome,
                    reason=reason,
                    proposed_row=proposed_row,
                    catalog_row=proposed_row if accepted else None,
                    identity_top1=round(float(top1), 4),
                    identity_gap=round(float(gap), 4),
                )
            row_decisions.append(decision)
            if not decision.accepted or decision.catalog_row is None:
                # Row atomicity: a rejected row contributes nothing, not even
                # the five cards inside it that happen to look right.
                manual_rows += 1
                continue

            accepted_rows.append(decision.catalog_row)
            incoming = _row_cards(
                decision.catalog_row, input_index, record.slots
            )
            if decision.catalog_row in _accepted_rows_in(mapped):
                resolved_ids, conflicts = _merge_repeat_cards(mapped, incoming)
                conflicting_card_ids.extend(conflicts)
                repeat_conflict = repeat_conflict or bool(conflicts)
                repeat_merged = repeat_merged or bool(resolved_ids)
                repeat_ignored = repeat_ignored or not (
                    conflicts or resolved_ids
                )
                repeats.append(
                    "conflicting_repeat_rows" if conflicts
                    else "repeat_rows_merged" if resolved_ids
                    else "repeat_rows_ignored"
                )
                continue
            mapped.update(incoming)
            rows_added = True

        # One summary code per image, worst first: a member reads "this image
        # disagreed with an earlier one", not a list of per-row bookkeeping.
        for code in ("conflicting_repeat_rows", "repeat_rows_merged",
                     "repeat_rows_ignored"):
            if code in repeats:
                capture_codes.append(code)
                break
        if manual_rows:
            manual_rows_seen = True
            capture_codes.append(
                "capture_rows_need_manual_review" if accepted_rows
                else "no_confirmed_card_rows"
            )
        elif accepted_rows and not capture_codes:
            capture_codes.append("capture_rows_confirmed")
        captures.append(CollectionCaptureScan(
            input_index=input_index,
            accepted=bool(accepted_rows),
            global_rows=tuple(sorted(set(accepted_rows))),
            source_size=result.source_size,
            scan_size=result.scan_size,
            warnings=tuple(dict.fromkeys(capture_codes)),
            conflicting_card_ids=tuple(dict.fromkeys(conflicting_card_ids)),
            rows_detected=len(registered),
            rows_accepted=len(accepted_rows),
            rows_manual=manual_rows,
        ))

    cards = tuple(
        mapped.get(index) or _empty_draft_card(card, index)
        for index, card in enumerate(CARDS, start=1)
    )
    unknown_card_ids = tuple(
        card.card_id for card in cards if card.state == UNKNOWN
    )
    unseen_card_ids = tuple(
        card.card_id for card in cards if card.source_index is None
    )
    duplicate_unverified_card_ids = tuple(
        card.card_id
        for card in cards
        if "duplicate_badge_unverified" in card.warnings
    )
    manual_required_card_ids = tuple(
        card.card_id
        for card in cards
        if card.state == UNKNOWN or card.source_index is None
    )

    categories: list[CategoryScanDraft] = []
    for category in CATEGORY_BY_ID.values():
        category_cards = tuple(
            card for card in cards if card.category_id == category.id
        )
        category_unknown = tuple(
            card.card_id for card in category_cards if card.state == UNKNOWN
        )
        category_unseen = tuple(
            card.card_id for card in category_cards if card.source_index is None
        )
        category_unverified = tuple(
            card.card_id
            for card in category_cards
            if "duplicate_badge_unverified" in card.warnings
        )
        categories.append(CategoryScanDraft(
            category_id=category.id,
            category_name=category.name,
            cards=category_cards,
            recognized_count=len(category_cards) - len(category_unknown),
            unknown_card_ids=category_unknown,
            unseen_card_ids=category_unseen,
            duplicate_unverified_card_ids=category_unverified,
            complete=not category_unknown,
        ))

    accepted_global_rows = _accepted_rows_in(mapped)
    manual_required_global_rows = tuple(
        row for row in range(1, COLLECTION_ROWS + 1)
        if row not in accepted_global_rows
    )
    accepted_page_numbers = tuple(_pages_fully_covered(accepted_global_rows))
    missing_page_numbers = tuple(
        page for page in range(1, COLLECTION_CAPTURE_COUNT + 1)
        if page not in accepted_page_numbers
    )

    warnings_found = [
        "experimental_review_draft",
        "human_confirmation_required",
    ]
    if had_prior and prior_valid:
        warnings_found.append("prior_scan_checkpoint_merged")
    if had_prior and not prior_valid:
        warnings_found.append("invalid_prior_scan_checkpoint")
    if too_many:
        warnings_found.append("too_many_collection_inputs")
    if repeat_ignored:
        warnings_found.append("repeat_rows_ignored")
    if repeat_merged:
        warnings_found.append("repeat_rows_merged")
    if repeat_conflict:
        warnings_found.append("conflicting_repeat_rows")
    if manual_rows_seen:
        warnings_found.append("rows_need_manual_review")
    if manual_required_global_rows:
        warnings_found.append("incomplete_capture_set")
    else:
        warnings_found.append("collection_rows_validated")
    if payloads and not rows_added:
        warnings_found.append("no_new_collection_rows")
    if unknown_card_ids:
        warnings_found.append("unknown_states_require_review")
    if duplicate_unverified_card_ids:
        warnings_found.append("hidden_duplicates_require_review")
    if manual_required_card_ids:
        warnings_found.append("manual_review_required")

    coverage_complete = not unseen_card_ids
    return CollectionScanDraft(
        cards=cards,
        categories=tuple(categories),
        captures=tuple(captures),
        accepted_page_numbers=accepted_page_numbers,
        missing_page_numbers=missing_page_numbers,
        missing_global_rows=manual_required_global_rows,
        recognized_count=len(cards) - len(unknown_card_ids),
        missing_count=sum(card.state == MISSING for card in cards),
        owned_count=sum(card.state == OWNED for card in cards),
        duplicate_count=sum(card.state == DUPLICATE for card in cards),
        unknown_count=len(unknown_card_ids),
        unknown_card_ids=unknown_card_ids,
        unseen_card_ids=unseen_card_ids,
        duplicate_unverified_card_ids=duplicate_unverified_card_ids,
        coverage_complete=coverage_complete,
        complete=coverage_complete and not unknown_card_ids,
        warnings=tuple(warnings_found),
        accepted_global_rows=accepted_global_rows,
        manual_required_global_rows=manual_required_global_rows,
        manual_required_card_ids=manual_required_card_ids,
        row_decisions=tuple(row_decisions),
    )
