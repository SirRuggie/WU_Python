"""Render the ticket-console overview attachment from live counts.

The reference image in ``docs/ticket-console/render_overview.py`` is kept
verbatim.  This module is the production form: it accepts data, returns PNG
bytes, and exposes an async wrapper so Pillow never blocks the gateway loop.
"""

from __future__ import annotations

import asyncio
import io
import math
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont


SCALE = 2
WIDTH = 1400
HEIGHT = 740

CANVAS = "#0b1018"
CARD = "#111822"
INK = "#f2f3f5"
MUTED = "#b5bac1"
FAINT = "#80848e"
APPROVED = "#4bce7a"
OPEN = "#4a90f5"
DENIED = "#f0555a"
BLACKLISTED = "#dd1c1d"
DENIED_BEFORE = "#ffcc00"
NOT_LOYAL = "#f17511"
GHOSTED = "#08c3fa"
NEUTRAL = "#80848e"

_ROOT = Path(__file__).resolve().parents[3]
_ASSETS = _ROOT / "assets" / "tickets"
_VENDORED_FONT_DIR = _ROOT / "assets" / "fonts" / "dejavu"
_SYSTEM_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    """All values needed by the fixed 1400x740 console chart."""

    statuses: Mapping[str, int]
    by_type: Mapping[str, Mapping[str, int]]
    flags: Mapping[str, int]
    updated_at: datetime | None = None


def _count(values: Mapping[str, int], key: str) -> int:
    try:
        return max(0, int(values.get(key, 0)))
    except (TypeError, ValueError):
        return 0


def _tint(hex_color: str, *, background: str = "#1a1c20", amount: float = 0.16) -> str:
    accent = hex_color.lstrip("#")
    base = background.lstrip("#")
    mixed = tuple(
        round(int(accent[index:index + 2], 16) * amount
              + int(base[index:index + 2], 16) * (1 - amount))
        for index in (0, 2, 4)
    )
    return "#%02x%02x%02x" % mixed


def _font(size: int, *, bold: bool = False, mono: bool = False):
    name = (
        "DejaVuSansMono.ttf" if mono
        else "DejaVuSans-Bold.ttf" if bold
        else "DejaVuSans.ttf"
    )
    vendored = _VENDORED_FONT_DIR / name
    if vendored.exists():
        return ImageFont.truetype(str(vendored), size * SCALE)
    system = _SYSTEM_FONT_DIR / name
    if system.exists():
        return ImageFont.truetype(str(system), size * SCALE)
    raise OSError(
        f"DejaVu font {name!r} not found in {_VENDORED_FONT_DIR} or {_SYSTEM_FONT_DIR}"
    )


def _age_copy(value: datetime | None) -> str:
    if not isinstance(value, datetime):
        return "updated just now"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return "updated just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"updated {minutes}m ago"
    hours = minutes // 60
    return f"updated {hours}h ago"


@lru_cache(maxsize=5)
def thumbnail_asset(filename: str) -> bytes:
    """Return a small cached PNG for a native console thumbnail."""
    with Image.open(_ASSETS / filename) as source:
        image = source.convert("RGBA")
        image.thumbnail((160, 160), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


def render_overview_sync(counts: OverviewCounts) -> bytes:
    """Render one complete PNG. Safe to call in a worker thread."""

    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), CANVAS)
    draw = ImageDraw.Draw(image)

    def rounded(xy, radius, *, fill=None, outline=None, width=1):
        draw.rounded_rectangle(
            [coordinate * SCALE for coordinate in xy],
            radius=radius * SCALE,
            fill=fill,
            outline=outline,
            width=width * SCALE,
        )

    def text(x, y, value, font, fill, *, anchor="la"):
        draw.text((x * SCALE, y * SCALE), value, font=font, fill=fill, anchor=anchor)

    def line(points, fill, width):
        draw.line(
            [(x * SCALE, y * SCALE) for x, y in points],
            fill=fill,
            width=width * SCALE,
            joint="curve",
        )

    def paste_icon(filename: str, center_x: int, center_y: int, size: int):
        path = _ASSETS / filename
        with Image.open(path) as source:
            icon = source.convert("RGBA")
            bounds = icon.getbbox()
            if bounds:
                icon = icon.crop(bounds)
            icon = icon.resize((size * SCALE, size * SCALE), Image.Resampling.LANCZOS)
            image.paste(
                icon,
                (int((center_x - size / 2) * SCALE), int((center_y - size / 2) * SCALE)),
                icon,
            )

    def icon_check(cx, cy, color):
        line([(cx - 8, cy + 1), (cx - 2, cy + 7), (cx + 9, cy - 8)], color, 3)

    def icon_plus(cx, cy, color):
        line([(cx - 8, cy), (cx + 8, cy)], color, 3)
        line([(cx, cy - 8), (cx, cy + 8)], color, 3)

    def icon_x(cx, cy, color):
        line([(cx - 7, cy - 7), (cx + 7, cy + 7)], color, 3)
        line([(cx - 7, cy + 7), (cx + 7, cy - 7)], color, 3)

    def icon_refresh(cx, cy, radius, color):
        draw.arc(
            [
                (cx - radius) * SCALE,
                (cy - radius) * SCALE,
                (cx + radius) * SCALE,
                (cy + radius) * SCALE,
            ],
            25,
            320,
            fill=color,
            width=2 * SCALE,
        )
        angle = math.radians(25)
        tip_x = cx + radius * math.cos(angle)
        tip_y = cy + radius * math.sin(angle)
        line(
            [(tip_x - 5, tip_y - 2), (tip_x, tip_y + 4), (tip_x + 5, tip_y - 3)],
            color,
            2,
        )

    def icon_bars(x, baseline, color):
        for index, height in enumerate((11, 18, 26)):
            left = x + index * 10
            rounded((left, baseline - height, left + 7, baseline), 2, fill=color)

    left, right = 36, 1364
    statuses = {
        "approved": _count(counts.statuses, "approved"),
        "open": _count(counts.statuses, "open"),
        "denied": _count(counts.statuses, "denied"),
    }
    type_counts = {
        kind: {
            status: _count(counts.by_type.get(kind, {}), status)
            for status in ("approved", "open", "denied")
        }
        for kind in ("main", "fwa")
    }
    total = sum(_count(counts.statuses, key) for key in counts.statuses)
    main_total = sum(type_counts["main"].values())
    fwa_total = sum(type_counts["fwa"].values())

    icon_bars(left, 58, APPROVED)
    text(left + 40, 26, "Ticket Console — overview", _font(27, bold=True), INK)
    text(
        left + 40,
        64,
        f"{total} tickets · Main {main_total} · FWA {fwa_total}",
        _font(16),
        MUTED,
    )
    icon_refresh(right - 10, 46, 10, FAINT)
    text(right - 28, 46, _age_copy(counts.updated_at), _font(14), MUTED, anchor="rm")

    tile_top, tile_height = 108, 128
    tile_width = (right - left - 2 * 16) // 3
    tiles = (
        ("APPROVED", statuses["approved"], APPROVED, icon_check),
        ("NEW / OPEN", statuses["open"], OPEN, icon_plus),
        ("DENIED", statuses["denied"], DENIED, icon_x),
    )
    for index, (label, number, color, icon) in enumerate(tiles):
        x = left + index * (tile_width + 16)
        rounded(
            (x, tile_top, x + tile_width, tile_top + tile_height),
            12,
            fill=_tint(color),
            outline=color,
        )
        draw.ellipse(
            [
                (x + tile_width - 46) * SCALE,
                (tile_top + 18) * SCALE,
                (x + tile_width - 18) * SCALE,
                (tile_top + 46) * SCALE,
            ],
            outline=color,
            width=2 * SCALE,
        )
        icon(x + tile_width - 32, tile_top + 32, color)
        text(x + 24, tile_top + 20, str(number), _font(46, bold=True), color)
        text(x + 24, tile_top + 88, label, _font(15, bold=True), INK)

    type_top = tile_top + tile_height + 24
    header_y, first_row_top, row_height = type_top + 16, type_top + 56, 96
    type_height = row_height * 2 + 60
    rounded((left, type_top, right, type_top + type_height), 12, fill=CARD)
    text(left + 24, header_y, "BY CLAN TYPE", _font(14, bold=True), FAINT)
    rows = (
        ("Main clan", "clan_main.png", type_counts["main"]),
        ("FWA clan", "clan_fwa.png", type_counts["fwa"]),
    )
    bar_x, bar_width = left + 96, 1080
    shared_maximum = max(1, main_total, fwa_total)
    for index, (name, filename, values) in enumerate(rows):
        row_top = first_row_top + index * row_height
        paste_icon(filename, left + 52, row_top + 24, 68)
        text(bar_x, row_top, name, _font(19, bold=True), INK)
        segments = (
            (APPROVED, values["approved"], "approved"),
            (OPEN, values["open"], "new/open"),
            (DENIED, values["denied"], "denied"),
        )
        description = " · ".join(f"{value} {label}" for _, value, label in segments)
        text(bar_x, row_top + 27, description, _font(13), MUTED)
        total_for_type = sum(values.values())
        y = row_top + 54
        x = bar_x
        for color, number, _ in segments:
            if number <= 0:
                continue
            segment_width = max(2, int(bar_width * number / shared_maximum) - 2)
            rounded((x, y, x + segment_width, y + 10), 5, fill=color)
            x += segment_width + 2
        text(x + 10, y - 3, f"{total_for_type} total", _font(14, bold=True), INK)

    flags_top = type_top + type_height + 20
    pill_height, flags_height = 58, 126
    rounded((left, flags_top, right, flags_top + flags_height), 12, fill=CARD)
    text(left + 24, flags_top + 16, "FLAGS", _font(14, bold=True), FAINT)
    flag_rows = (
        ("BLACKLISTED", _count(counts.flags, "blacklisted"), BLACKLISTED, "flag_blacklisted.png"),
        ("DENIED BEFORE", _count(counts.flags, "denied_before"), DENIED_BEFORE, "flag_denied_before.png"),
        ("NOT LOYAL TO WU", _count(counts.flags, "not_loyal"), NOT_LOYAL, "flag_not_loyal.png"),
    )
    pill_width = (right - 24 - (left + 24) - 2 * 16) // 3
    pill_top = flags_top + 46
    for index, (label, number, color, filename) in enumerate(flag_rows):
        x = left + 24 + index * (pill_width + 16)
        rounded(
            (x, pill_top, x + pill_width, pill_top + pill_height),
            10,
            fill=_tint(color, amount=0.18),
            outline=color,
        )
        paste_icon(filename, x + 30, pill_top + 29, 40)
        text(x + 62, pill_top + 18, label, _font(14, bold=True), INK)
        text(x + pill_width - 14, pill_top + 18, str(number), _font(16, bold=True), color, anchor="ra")

    text(
        left,
        flags_top + flags_height + 22,
        "drawn by WU Wizard · attached to the message · redrawn when a ticket changes",
        _font(13, mono=True),
        FAINT,
    )

    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def render_overview(counts: OverviewCounts) -> bytes:
    """Render without occupying the Discord gateway event loop."""

    return await asyncio.to_thread(render_overview_sync, counts)


def render_status_strip_sync(counts: OverviewCounts) -> bytes:
    """Render only the three high-value status totals for a narrow media card."""
    width, height = 720, 250
    image = Image.new("RGB", (width * SCALE, height * SCALE), CANVAS)
    draw = ImageDraw.Draw(image)
    values = (
        ("APPROVED", _count(counts.statuses, "approved"), APPROVED),
        ("OPEN", _count(counts.statuses, "open"), OPEN),
        ("DENIED", _count(counts.statuses, "denied"), DENIED),
    )
    gap, left, card_width = 14, 18, 218
    for index, (label, number, color) in enumerate(values):
        x = left + index * (card_width + gap)
        draw.rounded_rectangle(
            (x * SCALE, 20 * SCALE, (x + card_width) * SCALE, 230 * SCALE),
            radius=16 * SCALE, fill=_tint(color), outline=color, width=2 * SCALE,
        )
        number_size = 72 if len(str(number)) <= 3 else 60 if len(str(number)) == 4 else 50
        draw.text(((x + card_width // 2) * SCALE, 102 * SCALE), str(number),
                  font=_font(number_size, bold=True), fill=color, anchor="mm")
        draw.text(((x + card_width // 2) * SCALE, 176 * SCALE), label,
                  font=_font(28, bold=True), fill=INK, anchor="mm")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def render_status_strip(counts: OverviewCounts) -> bytes:
    return await asyncio.to_thread(render_status_strip_sync, counts)


def render_clan_status_bar_sync(
    values: Mapping[str, int], *, maximum: int | None = None,
) -> bytes:
    """Render a compact, text-free status distribution for one clan section."""
    width, height, inset = 720, 48, 4
    image = Image.new("RGB", (width * SCALE, height * SCALE), CANVAS)
    draw = ImageDraw.Draw(image)
    categories = (
        (APPROVED, _count(values, "approved")),
        (OPEN, _count(values, "open")),
        (DENIED, _count(values, "denied")),
        (NEUTRAL, _count(values, "closed")),
    )
    total = sum(value for _, value in categories)
    scale_total = max(total, int(maximum or 0), 1)
    bounds = (inset * SCALE, inset * SCALE, (width - inset) * SCALE, (height - inset) * SCALE)
    radius = (height // 2) * SCALE
    if total <= 0:
        draw.rounded_rectangle(bounds, radius=radius, fill=NEUTRAL)
    else:
        left = inset
        usable = round((width - inset * 2) * total / scale_total)
        for index, (color, value) in enumerate(categories):
            if value <= 0:
                continue
            # The last present segment absorbs rounding, keeping the bar flush.
            remaining = sum(number for _, number in categories[index + 1:])
            right = inset + usable if remaining == 0 else left + round(usable * value / total)
            draw.rectangle(
                (left * SCALE, inset * SCALE, right * SCALE, (height - inset) * SCALE),
                fill=color,
            )
            left = right
        # Reapply the silhouette as a mask so only the outer ends are rounded.
        mask = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle(
            (
                inset * SCALE,
                inset * SCALE,
                (inset + usable) * SCALE,
                (height - inset) * SCALE,
            ),
            radius=min(radius, usable * SCALE // 2),
            fill=255,
        )
        clipped = Image.new("RGB", image.size, CANVAS)
        clipped.paste(image, mask=mask)
        image = clipped
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def render_clan_status_bar(
    values: Mapping[str, int], *, maximum: int | None = None,
) -> bytes:
    """Render a clan bar without occupying the Discord gateway event loop."""
    return await asyncio.to_thread(render_clan_status_bar_sync, values, maximum=maximum)


def render_flag_row_sync(*, label: str, count: int, color: str, filename: str) -> bytes:
    """Render one slim, full-width flag row for the Components V2 hub.

    Discord keeps media-gallery images at their intrinsic wide aspect ratio.
    A dedicated row therefore preserves the supplied flag artwork at a useful
    mobile size without the forced tall footprint of a Section thumbnail.
    """
    width, height = 1200, 132
    image = Image.new("RGB", (width * SCALE, height * SCALE), CANVAS)
    draw = ImageDraw.Draw(image)
    inset = 8
    draw.rounded_rectangle(
        (inset * SCALE, inset * SCALE, (width - inset) * SCALE, (height - inset) * SCALE),
        radius=18 * SCALE,
        fill=_tint(color, amount=0.16),
        outline=color,
        width=2 * SCALE,
    )
    with Image.open(_ASSETS / filename) as source:
        icon = source.convert("RGBA")
        bounds = icon.getbbox()
        if bounds:
            icon = icon.crop(bounds)
        icon.thumbnail((88 * SCALE, 88 * SCALE), Image.Resampling.LANCZOS)
        left = 28 * SCALE
        top = (height * SCALE - icon.height) // 2
        image.paste(icon, (left, top), icon)
    draw.text((146 * SCALE, (height // 2) * SCALE), label,
              font=_font(52, bold=True), fill=INK, anchor="lm")
    draw.text(((width - 44) * SCALE, (height // 2) * SCALE), str(max(0, int(count))),
              font=_font(60, bold=True), fill=color, anchor="rm")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def render_flag_row(**kwargs) -> bytes:
    """Render a flag row without occupying the Discord gateway event loop."""
    return await asyncio.to_thread(render_flag_row_sync, **kwargs)
