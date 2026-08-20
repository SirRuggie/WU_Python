"""Render the ticket-console overview attachment from live counts.

The reference image in ``docs/ticket-console/render_overview.py`` is kept
verbatim.  This module is the production form: it accepts data, returns PNG
bytes, and exposes an async wrapper so Pillow never blocks the gateway loop.
"""

from __future__ import annotations

import asyncio
import io
import math
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

_ROOT = Path(__file__).resolve().parents[3]
_ASSETS = _ROOT / "assets" / "tickets"
_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


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
    path = _FONT_DIR / name
    try:
        return ImageFont.truetype(str(path), size * SCALE)
    except OSError:
        # Pillow normally ships DejaVu under this family name even when the
        # Linux package path differs.  Let this second lookup be the portable
        # fallback instead of silently changing the chart to bitmap text.
        return ImageFont.truetype(name, size * SCALE)


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
