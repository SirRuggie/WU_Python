"""Experimental, review-only Clash of Cards still-image classifier.

This module deliberately has no Discord or database imports.  Its batch entry
point binds five ordered, two-row collection captures to the canonical 60-card
catalog.  The positional binding is intentionally narrow: arbitrary crops and
out-of-order screenshots fail closed instead of being guessed.

The output is never safe to persist without human review.  Missing portraits
can be recognized even when the fixed reward track covers the badge area.  A
clearly colored portrait there proves at least one copy, so it is returned as
owned while its possibly hidden duplicate badge is explicitly left unverified.

Only ordinary PNG, JPEG, and single-frame WebP still images are accepted.
Video decoding and arbitrary-scroll row merging are intentionally out of scope.
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
from itertools import islice
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from utils.cards import CARDS, CATEGORY_BY_ID


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
MIN_SOURCE_HEIGHT = 300
MAX_SCAN_WIDTH = 1000
MAX_SCAN_HEIGHT = 2400
COLLECTION_CAPTURE_COUNT = 5
COLLECTION_ROWS = 10
COLLECTION_COLUMNS = 6
MAX_COLLECTION_INPUTS = 6

# Conservative thresholds checked against the supplied five-page live capture
# sequence.  Values between the missing and owned bands remain unknown.
FRAME_MIN_SATURATION = 110
FRAME_MIN_VALUE = 120
MISSING_MAX_SATURATION = 12.0
OWNED_MIN_SATURATION = 25.0
YELLOW_HUE_MIN = 24
YELLOW_HUE_MAX = 50
YELLOW_MIN_SATURATION = 120
YELLOW_MIN_VALUE = 150
BADGE_MIN_WIDTH_RATIO = 0.38
BADGE_MIN_FILL = 0.50

# Median frame hues in Pillow's 0..255 HSV representation, measured from the
# supplied live collection captures.  The tolerance intentionally leaves broad
# gaps between adjacent category colors while allowing ordinary recompression.
CATEGORY_FRAME_HUES = {
    "elixir": 211.0,
    "dark_elixir": 198.0,
    "builder_base": 145.0,
    "super_troop": 12.0,
}
CATEGORY_FRAME_HUE_TOLERANCE = 8.0
CAPTURE_DUPLICATE_MAX_MEAN_DELTA = 0.5
ROW_OVERLAP_MAX_MEAN_DELTA = 1.0

# The only retained information derived from the supplied live screenshots is
# one 128-bit grayscale perceptual hash per portrait.  These values cannot
# reconstruct the screenshots, player state, badges, or account identity.  The
# inner-art crop deliberately excludes the xN badge; grid medians keep detector
# edge noise from moving a crop under ordinary resize or JPEG recompression.
ARTWORK_HASH_MAX_DISTANCE = 22
ARTWORK_HASH_MIN_RUNNER_UP_GAP = 12
ARTWORK_HASH_SIZE = 32
ARTWORK_HASH_MAX_FREQUENCY = 10
ARTWORK_CROP_LEFT = -0.38
ARTWORK_CROP_TOP = 0.08
ARTWORK_CROP_RIGHT = 0.38
ARTWORK_CROP_BOTTOM = 0.66
CARD_ARTWORK_HASHES = {
    "barbarian": 0xBC5387F24345685BBDBFAD71338C8E33,
    "archer": 0xDD83B808ABE021FF6A130B2A6B6A6C64,
    "giant": 0x9EDCC50CCD3C8F0CE7C86373B3BF393C,
    "goblin": 0x8E5577627241A68F30B7E362BE3E1792,
    "wall_breaker": 0xB425EBACE03B6C926479DBC6CBCD4FBA,
    "balloon": 0x447D81C658CFCA5B9AD1337353B3B7A3,
    "wizard": 0x1E447526F7855356F8E3253571CC9652,
    "healer": 0x88C31503FF889BEE6C45D69B39321259,
    "dragon": 0xD7AC4E914D9C2E5118293C1ACBF1A8A1,
    "pekka": 0xF2B8AFBE8A7C0C20393048DCDC4DAB09,
    "baby_dragon": 0xC0385EE772075C4F7A60C8C440734FCE,
    "miner": 0x1F8D49F579247113D0D9CAE134DC1C3C,
    "electro_dragon": 0xF8A2037F02D8F85EA28199942D233B8A,
    "yeti": 0xB933B87D4A21391ED32B2E846125AE8E,
    "dragon_rider": 0xC33CCA12CC1CD5B79848C8ECA9D1B261,
    "electro_titan": 0xF428AFD06E10F22F6948D8C48C8C83C3,
    "root_rider": 0x3E3F698A483E253C2D1F37FE4DDD4F0F,
    "thrower": 0x8CE1D1AC7325E2C7FCBCB83F367C37F1,
    "meteor_golem": 0x425ED3B355C53AC29961E6B4C91A3132,
    "minion": 0x1397EED8254DCE06D15C7CE6DEC8F968,
    "hog_rider": 0xB38582740B9399FE6386BCA9AC8E367B,
    "valkyrie": 0x99D72C1AE1C5463BA4A333715198EECC,
    "golem": 0x92A8549EA1CCF54FFEFE7E3F7B4B1D3E,
    "witch": 0x398E7C7ABD0C46543E1F1F3D1ECCCCEC,
    "lava_hound": 0xF6AFC07107D95C449C9C9D96360F0F0F,
    "bowler": 0x9DE17276271114F578B891A3B8F66278,
    "ice_golem": 0xE84C454D23ED6C7AC49283C5731A8B8B,
    "headhunter": 0xE9FC72247ABA0C2A3D1D1F0E44B6AEF3,
    "apprentice_warden": 0x318FF0136E670CF8323B7FF80232EE9C,
    "druid": 0xB84FCCF1742584F4CF7978E38B377FDC,
    "furnace": 0x412AF4D1F1C5761DE2EACCC4C3C3C0D6,
    "rubble_witch": 0x6E317AE2275C8C6C1E5E23436666EB09,
    "raged_barbarian": 0x9A43C73061AE5C7BFFDFEFFDD7DBDE73,
    "sneaky_archer": 0x8F802FC019FB7B4CE6F43C4CD4DCE8A9,
    "boxer_giant": 0xAC35005B165EF976DD9E8EE47447EBC8,
    "beta_minion": 0xA22CCE55B57E0B13327CEED6D78F4F5B,
    "bomber": 0x118C5B7E9F0C151F3C48DCCDAC5C5D79,
    "bb_baby_dragon": 0xC007FE0979F26CD472E8CC60634E94B4,
    "cannon_cart": 0x99D95899A1C5E6CC808C39797B697934,
    "night_witch": 0x278C1F85281BAF9D3D7E36DE48683D98,
    "drop_ship": 0x10EF709D51C7AF14B0F8BC751355369E,
    "power_pekka": 0xFE458B0A83227F69F0D9838D492E0F63,
    "hog_glider": 0x9487825107D9DEF663CE9CAC8C8E3A59,
    "super_barbarian": 0xB5443876272DBC366F4F0223726E6268,
    "super_archer": 0xC7890BDC9A05963FEC6CB889C9B07060,
    "super_giant": 0x909BAC99CD7C78916B79FCFABBA9ACCE,
    "sneaky_goblin": 0x1340ECBD4BE2C3E673F9E1636FE7B0F0,
    "super_wall_breaker": 0x3DA5D25B4846A976983D24040C6EA634,
    "rocket_balloon": 0x2ACFEC7C7882851E0F4F3F771B3B1D9C,
    "super_wizard": 0x73DAB0DA04128FFA999431321E3C383D,
    "super_dragon": 0x59A84419DC9B3CDDCCCE9494C0F1FCB2,
    "inferno_dragon": 0x1D0707DB76E84E4AC2D3459C5E7AB2FA,
    "super_miner": 0x9EC1FB5CA8C812E37232352DE82E3C68,
    "super_yeti": 0xAD293023D13E79F474369F2615C7C676,
    "super_minion": 0x52638C360E27ED5EC0C17322816BE3A1,
    "super_hog_rider": 0xFA82C9F949A6C296988DCD4F2D3D3087,
    "super_valkyrie": 0xCCD8ABB48AA7266AE673F19969742DED,
    "super_witch": 0x95C77AB41ECA232A696933384D7C7C79,
    "ice_hound": 0xF655B564E3350C8C1267F3F3323E87C3,
    "super_bowler": 0xA87551D2AF1165D5FEBFFF733BEB6737,
}

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
class CollectionCaptureScan:
    """Disposition of one supplied screenshot in a collection batch."""

    input_index: int
    accepted: bool
    global_rows: tuple[int, ...]
    source_size: tuple[int, int] | None
    scan_size: tuple[int, int] | None
    warnings: tuple[str, ...]
    mismatched_card_ids: tuple[str, ...] = ()


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

    ``coverage_complete`` means all 60 catalog positions were visibly bound to
    one of the five validated captures.  ``complete`` additionally requires no
    unknown state.  Neither flag authorizes an automatic database write.
    """

    cards: tuple[DraftCardScan, ...]
    categories: tuple[CategoryScanDraft, ...]
    captures: tuple[CollectionCaptureScan, ...]
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


def _artwork_hashes_for_rows(
    image: Image.Image,
    rows: tuple[RowScan, ...],
) -> tuple[int, ...]:
    """Hash stable inner-art crops in visual row/column order."""
    fingerprints: list[int] = []
    card_width = statistics.median(
        slot.bounds.width for row in rows for slot in row.slots
    )
    column_centers = tuple(
        statistics.median(row.slots[column].bounds.center_x for row in rows)
        for column in range(COLLECTION_COLUMNS)
    )
    for row in rows:
        row_top = statistics.median(slot.bounds.top for slot in row.slots)
        row_height = statistics.median(slot.bounds.height for slot in row.slots)
        for center_x in column_centers:
            crop = image.crop((
                round(center_x + card_width * ARTWORK_CROP_LEFT),
                round(row_top + row_height * ARTWORK_CROP_TOP),
                round(center_x + card_width * ARTWORK_CROP_RIGHT),
                round(row_top + row_height * ARTWORK_CROP_BOTTOM),
            ))
            fingerprints.append(_artwork_perceptual_hash(crop))
    return tuple(fingerprints)


def _artwork_identity_mismatches(
    image: Image.Image,
    result: ScanResult,
    capture_position: int,
) -> tuple[str, ...]:
    """Return expected card ids whose portrait does not prove that identity."""
    catalog_ids = {card.id for card in CARDS}
    start = capture_position * COLLECTION_COLUMNS * 2
    expected = CARDS[start:start + COLLECTION_COLUMNS * 2]
    if set(CARD_ARTWORK_HASHES) != catalog_ids:
        # Adding, removing, or renaming a catalog entry without new live artwork
        # anchors is a deliberate global kill-switch, not a best-effort scan.
        return tuple(card.id for card in expected)

    observed = _artwork_hashes_for_rows(image, result.rows)
    category_by_card_id = {card.id: card.category for card in CARDS}
    mismatched: list[str] = []
    for card, fingerprint in zip(expected, observed):
        expected_distance = (
            fingerprint ^ CARD_ARTWORK_HASHES[card.id]
        ).bit_count()
        competitor_distances = [
            (fingerprint ^ anchor).bit_count()
            for other_id, anchor in CARD_ARTWORK_HASHES.items()
            if other_id != card.id
            and category_by_card_id[other_id] == card.category
        ]
        nearest_competitor = min(competitor_distances, default=math.inf)
        if (
            expected_distance > ARTWORK_HASH_MAX_DISTANCE
            or nearest_competitor - expected_distance
            < ARTWORK_HASH_MIN_RUNNER_UP_GAP
        ):
            mismatched.append(card.id)
    return tuple(mismatched)


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
    reward_track_covers_badge = (
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
        # The supplied live calibration set contains no unobstructed positive
        # xN badge.  Until one exists, a yellow badge-shaped signal proves only
        # the colored portrait (one copy); it must never create trade supply.
        return SlotScan(
            column=column,
            state=OWNED,
            confidence=min(confidence, 0.85),
            bounds=box,
            portrait_saturation=portrait_saturation,
            warnings=(
                "visible_duplicate_badge_unverified",
                "duplicate_badge_unverified",
            ),
        )
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


def _frame_hue(image: Image.Image, box: Bounds) -> float | None:
    """Return the median saturated hue around a detected category frame."""
    crop = image.crop((box.left, box.top, box.right, box.bottom)).convert("HSV")
    width, height = crop.size
    inset = max(3, round(min(width, height) * 0.08))
    hues: list[int] = []
    for y in range(height):
        for x in range(width):
            if not (
                x < inset
                or x >= width - inset
                or y < inset
                or y >= height - inset
            ):
                continue
            hue, saturation, value = crop.getpixel((x, y))
            if saturation >= FRAME_MIN_SATURATION and value >= FRAME_MIN_VALUE:
                hues.append(hue)
    return float(statistics.median(hues)) if hues else None


def _hue_distance(left: float, right: float) -> float:
    difference = abs(left - right)
    return min(difference, 256.0 - difference)


def _capture_matches_catalog_position(
    image: Image.Image,
    result: ScanResult,
    capture_position: int,
) -> bool:
    start = capture_position * COLLECTION_COLUMNS * 2
    slots = tuple(slot for row in result.rows for slot in row.slots)
    expected = CARDS[start:start + len(slots)]
    if len(slots) != COLLECTION_COLUMNS * 2 or len(expected) != len(slots):
        return False

    for slot, card in zip(slots, expected):
        hue = _frame_hue(image, slot.bounds)
        target = CATEGORY_FRAME_HUES.get(card.category)
        if (
            hue is None
            or target is None
            or _hue_distance(hue, target) > CATEGORY_FRAME_HUE_TOLERANCE
        ):
            return False
    return True


def _capture_fingerprint(image: Image.Image, result: ScanResult) -> bytes:
    """Return a small visual signature of card art, excluding phone toolbars."""
    bounds = Bounds(
        min(row.bounds.left for row in result.rows),
        min(row.bounds.top for row in result.rows),
        max(row.bounds.right for row in result.rows),
        max(row.bounds.bottom for row in result.rows),
    )
    crop = image.crop(
        (bounds.left, bounds.top, bounds.right, bounds.bottom)
    ).convert("L")
    return crop.resize((192, 96), Image.Resampling.BILINEAR).tobytes()


def _row_fingerprint(image: Image.Image, row: RowScan) -> bytes:
    bounds = row.bounds
    crop = image.crop(
        (bounds.left, bounds.top, bounds.right, bounds.bottom)
    ).convert("L")
    return crop.resize((192, 48), Image.Resampling.BILINEAR).tobytes()


def _fingerprint_delta(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        return math.inf
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _fingerprints_match(left: bytes, right: bytes) -> bool:
    return _fingerprint_delta(left, right) <= CAPTURE_DUPLICATE_MAX_MEAN_DELTA


def _empty_draft_card(
    card,
    catalog_index: int,
    *,
    artwork_mismatch: bool = False,
) -> DraftCardScan:
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
        warnings=(
            "unseen_card",
            *(("artwork_identity_mismatch",) if artwork_mismatch else ()),
        ),
    )


def scan_collection_screenshots(image_items: object) -> CollectionScanDraft:
    """Build a conservative 60-card review draft from ordered screenshots.

    The supported capture contract is deliberately small: five distinct still
    images, in top-to-bottom order, each containing exactly two complete rows.
    One additional near-duplicate image may be supplied and is ignored (this
    covers the observed phone-toolbar copy).  Category-frame colors and a
    privacy-safe expected portrait hash validate every accepted position before
    identities are assigned.

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

    captures: list[CollectionCaptureScan] = []
    accepted: list[tuple[int, int, Image.Image, ScanResult]] = []
    fingerprints: list[bytes] = []
    row_fingerprints: list[bytes] = []
    duplicate_ignored = False
    overlap_ignored = False
    artwork_mismatch_ids: set[str] = set()
    too_many = len(payloads) > MAX_COLLECTION_INPUTS
    next_capture_position = 0

    for input_index, payload in enumerate(payloads[:MAX_COLLECTION_INPUTS], start=1):
        result = scan_visible_rows(payload)
        loaded = _load_still(payload)
        if isinstance(loaded, str) or len(result.rows) != 2:
            # An unreadable intended page still owns its position.  Otherwise
            # every later valid page would shift backward and produce a cascade
            # of misleading sequence errors (or, worse, wrong identities).
            next_capture_position += 1
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=tuple(dict.fromkeys((*result.warnings, "capture_requires_two_rows"))),
            ))
            continue

        image, _source_size = loaded
        fingerprint = _capture_fingerprint(image, result)
        if any(
            _fingerprints_match(fingerprint, prior)
            for prior in fingerprints
        ):
            duplicate_ignored = True
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=("duplicate_capture_ignored",),
            ))
            continue

        capture_position = next_capture_position
        next_capture_position += 1

        candidate_row_fingerprints = [
            _row_fingerprint(image, row) for row in result.rows
        ]
        if any(
            _fingerprint_delta(candidate, prior)
            <= ROW_OVERLAP_MAX_MEAN_DELTA
            for candidate in candidate_row_fingerprints
            for prior in row_fingerprints
        ):
            overlap_ignored = True
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=("overlapping_capture_rows",),
            ))
            continue

        if capture_position >= COLLECTION_CAPTURE_COUNT:
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=("unexpected_extra_capture",),
            ))
            continue
        if not _capture_matches_catalog_position(
            image, result, capture_position
        ):
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=("capture_sequence_mismatch",),
            ))
            continue

        mismatched_card_ids = _artwork_identity_mismatches(
            image, result, capture_position
        )
        if mismatched_card_ids:
            artwork_mismatch_ids.update(mismatched_card_ids)
            captures.append(CollectionCaptureScan(
                input_index=input_index,
                accepted=False,
                global_rows=(),
                source_size=result.source_size,
                scan_size=result.scan_size,
                warnings=("artwork_identity_mismatch",),
                mismatched_card_ids=mismatched_card_ids,
            ))
            continue

        global_rows = (
            capture_position * 2 + 1,
            capture_position * 2 + 2,
        )
        captures.append(CollectionCaptureScan(
            input_index=input_index,
            accepted=True,
            global_rows=global_rows,
            source_size=result.source_size,
            scan_size=result.scan_size,
            warnings=("catalog_position_and_artwork_validated",),
        ))
        accepted.append((capture_position, input_index, image, result))
        fingerprints.append(fingerprint)
        row_fingerprints.extend(candidate_row_fingerprints)

    mapped: dict[int, DraftCardScan] = {}
    for capture_position, source_index, _image, result in accepted:
        for local_row, row in enumerate(result.rows):
            global_row = capture_position * 2 + local_row + 1
            for slot in row.slots:
                catalog_index = (
                    (global_row - 1) * COLLECTION_COLUMNS + slot.column
                )
                card = CARDS[catalog_index - 1]
                mapped[catalog_index] = DraftCardScan(
                    card_id=card.id,
                    card_name=card.name,
                    category_id=card.category,
                    catalog_index=catalog_index,
                    global_row=global_row,
                    column=slot.column,
                    state=slot.state,
                    confidence=slot.confidence,
                    source_index=source_index,
                    warnings=slot.warnings,
                )

    cards = tuple(
        mapped.get(index) or _empty_draft_card(
            card,
            index,
            artwork_mismatch=card.id in artwork_mismatch_ids,
        )
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

    warnings_found = [
        "experimental_review_draft",
        "human_confirmation_required",
    ]
    if too_many:
        warnings_found.append("too_many_collection_inputs")
    if duplicate_ignored:
        warnings_found.append("duplicate_capture_ignored")
    if overlap_ignored:
        warnings_found.append("overlapping_capture_rows")
    if artwork_mismatch_ids:
        warnings_found.append("artwork_identity_mismatch")
    accepted_positions = {position for position, *_rest in accepted}
    if accepted_positions != set(range(COLLECTION_CAPTURE_COUNT)):
        warnings_found.append("incomplete_capture_set")
    else:
        warnings_found.append("capture_sequence_validated")
    if unknown_card_ids:
        warnings_found.append("unknown_states_require_review")
    if duplicate_unverified_card_ids:
        warnings_found.append("hidden_duplicates_require_review")

    coverage_complete = not unseen_card_ids
    return CollectionScanDraft(
        cards=cards,
        categories=tuple(categories),
        captures=tuple(captures),
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
    )
