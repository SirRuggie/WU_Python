"""Experimental, preview-only Clash of Cards still-image classifier.

This module deliberately has no Discord, database, or inventory-model imports.
It only tests whether Pillow can conservatively find complete six-card rows and
classify visible tiles.  The output is not safe to persist: card identities and
categories cannot be inferred from the collection artwork alone, and every
ambiguous layout or state fails closed.

Only ordinary PNG, JPEG, and single-frame WebP still images are accepted.
Video decoding and multi-image row merging are intentionally out of scope.
Scanning is CPU-bound; any future async preview caller must run it outside the
Discord event loop.  This module intentionally provides no such integration.
"""

from __future__ import annotations

import io
import math
import statistics
import warnings
from collections import deque
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError


EXPERIMENTAL = True
PERSISTENCE_SAFE = False

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
MIN_SOURCE_HEIGHT = 400
MAX_SCAN_WIDTH = 1000
MAX_SCAN_HEIGHT = 2400

# Conservative thresholds calibrated only against the two publicly available
# top-of-Elixir screenshots.  Values between the bands remain unknown.
FRAME_MIN_SATURATION = 110
FRAME_MIN_VALUE = 120
MISSING_MAX_SATURATION = 12.0
OWNED_MIN_SATURATION = 25.0
YELLOW_HUE_MIN = 24
YELLOW_HUE_MAX = 50
YELLOW_MIN_SATURATION = 120
YELLOW_MIN_VALUE = 150


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

    image.thumbnail(
        (MAX_SCAN_WIDTH, MAX_SCAN_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    return image, source_size


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


def _saturated_components(image: Image.Image) -> list[Bounds]:
    width, height = image.size
    hsv = image.convert("HSV")
    mask = bytearray(width * height)
    for index, (_hue, saturation, value) in enumerate(_pixel_data(hsv)):
        if saturation >= FRAME_MIN_SATURATION and value >= FRAME_MIN_VALUE:
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
    return components


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
        and 0.55 <= aspect <= 0.95
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
            0.30 <= width_ratio <= 0.72
            and 0.10 <= height_ratio <= 0.30
            and center_offset <= 0.14
            and 0.70 <= vertical_center <= 1.05
            and fill >= 0.35
        ):
            return True, False

    crop_area = max(
        (badge_bounds[2] - badge_bounds[0])
        * (badge_bounds[3] - badge_bounds[1]),
        1,
    )
    return False, unresolved_pixels / crop_area >= 0.08


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
            state=UNKNOWN,
            confidence=0.0,
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("badge_region_clipped",),
        )

    badge_bounds = _relative_box(box, 0.10, 0.68, 0.90, 1.14)
    external_bounds = _relative_box(box, 0.20, 1.0, 0.80, 1.12)
    external_value = _mean_hsv_channel(
        image, external_bounds, channel=2
    )
    if provisional != MISSING and external_value < 70.0:
        return SlotScan(
            column=column,
            state=UNKNOWN,
            confidence=0.0,
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("badge_region_obstructed",),
        )

    has_badge, unresolved_yellow = _has_badge_shape(
        image, box, badge_bounds
    )
    if provisional == MISSING:
        if has_badge or unresolved_yellow:
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
        state = DUPLICATE
        confidence = min(confidence, 0.94)
    elif unresolved_yellow:
        return SlotScan(
            column=column,
            state=UNKNOWN,
            confidence=0.0,
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=("ambiguous_badge_signal",),
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


def scan_visible_rows(image_bytes: object) -> ScanResult:
    """Conservatively classify complete visible six-card rows in one still.

    The function never raises for bad user input and never assigns card names,
    category names, or collection positions.  Callers must treat every result
    as a preview requiring human review; ``PERSISTENCE_SAFE`` is permanently
    false for this experimental implementation.
    """
    base_warnings = (
        "experimental_preview_only",
        "card_identity_not_inferred",
    )
    loaded = _load_still(image_bytes)
    if isinstance(loaded, str):
        return _result_failure(loaded, prior=base_warnings)
    image, source_size = loaded

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
