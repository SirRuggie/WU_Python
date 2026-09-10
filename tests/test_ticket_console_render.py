import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image, ImageColor

from extensions.commands.tickets import console_render


def _counts(**overrides):
    values = {
        "statuses": {"open": 8, "approved": 4, "denied": 12},
        "by_type": {
            "main": {"open": 2, "approved": 1, "denied": 3},
            "fwa": {"open": 6, "approved": 3, "denied": 9},
        },
        "flags": {"blacklisted": 2, "denied_before": 5, "not_loyal": 1},
    }
    values.update(overrides)
    return console_render.OverviewCounts(**values)


def test_overview_renders_the_contract_size_for_live_and_empty_data():
    for counts in (
        _counts(),
        _counts(statuses={}, by_type={}, flags={}),
    ):
        payload = console_render.render_overview_sync(counts)
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(io.BytesIO(payload)) as image:
            assert image.size == (1400, 740)
            assert image.mode == "RGB"


def test_overview_tolerates_unknown_and_bad_counts():
    payload = console_render.render_overview_sync(_counts(
        statuses={"open": "bad", "legacy_unknown": 7},
        by_type={"main": {"open": -9}, "other": {"denied": 100}},
        flags={"blacklisted": None},
    ))
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (1400, 740)


def test_async_renderer_moves_pillow_off_the_event_loop(monkeypatch):
    calls = []

    async def to_thread(function, *args):
        calls.append((function, args))
        return b"png"

    monkeypatch.setattr(console_render.asyncio, "to_thread", to_thread)
    result = asyncio.run(console_render.render_overview(_counts()))

    assert result == b"png"
    assert calls == [(console_render.render_overview_sync, (_counts(),))]


def test_status_strip_renders_mobile_friendly_contract_and_five_digit_counts():
    counts = _counts(statuses={"approved": 99_999, "open": 12_345, "denied": 54_321})

    payload = console_render.render_status_strip_sync(counts)

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(payload)) as image:
        # The strip keeps SCALE=2 pixels for crisp Discord downscaling while
        # preserving the intended 720x250 logical aspect ratio.
        assert image.size == (720 * console_render.SCALE, 250 * console_render.SCALE)
        assert image.mode == "RGB"

    # At the renderer's five-digit size the widest value retains breathing
    # room inside a 218px card instead of clipping at either edge.
    font = console_render._font(50, bold=True)
    left, _top, right, _bottom = font.getbbox("99999")
    assert (right - left) / console_render.SCALE < 200


def test_async_status_strip_moves_pillow_off_the_event_loop(monkeypatch):
    calls = []

    async def to_thread(function, *args):
        calls.append((function, args))
        return b"strip"

    counts = _counts()
    monkeypatch.setattr(console_render.asyncio, "to_thread", to_thread)

    assert asyncio.run(console_render.render_status_strip(counts)) == b"strip"
    assert calls == [(console_render.render_status_strip_sync, (counts,))]


def test_clan_status_bar_has_shared_scale_colored_segments_and_neutral_zero_state():
    payload = console_render.render_clan_status_bar_sync(
        {"approved": 40, "open": 20, "denied": 10, "closed": 30}, maximum=100,
    )
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (720 * console_render.SCALE, 48 * console_render.SCALE)
        y = 24 * console_render.SCALE
        assert image.getpixel((10 * console_render.SCALE, y)) == ImageColor.getrgb(console_render.APPROVED)
        assert image.getpixel((300 * console_render.SCALE, y)) == ImageColor.getrgb(console_render.OPEN)
        assert image.getpixel((450 * console_render.SCALE, y)) == ImageColor.getrgb(console_render.DENIED)
        assert image.getpixel((530 * console_render.SCALE, y)) == ImageColor.getrgb(console_render.NEUTRAL)

    # A clan with half the shared maximum occupies half the common track;
    # it is not normalized to a misleading 100%-wide bar.
    smaller = console_render.render_clan_status_bar_sync(
        {"approved": 20, "open": 10, "denied": 5, "closed": 15}, maximum=100,
    )
    with Image.open(io.BytesIO(smaller)) as image:
        y = 24 * console_render.SCALE
        assert image.getpixel((350 * console_render.SCALE, y)) == ImageColor.getrgb(
            console_render.NEUTRAL
        )
        assert image.getpixel((400 * console_render.SCALE, y)) == ImageColor.getrgb(
            console_render.CANVAS
        )

    empty = console_render.render_clan_status_bar_sync({}, maximum=100)
    with Image.open(io.BytesIO(empty)) as image:
        assert image.getpixel((360 * console_render.SCALE, 24 * console_render.SCALE)) == ImageColor.getrgb(console_render.NEUTRAL)


def test_async_clan_status_bar_moves_pillow_off_the_event_loop(monkeypatch):
    calls = []

    async def to_thread(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return b"bar"

    monkeypatch.setattr(console_render.asyncio, "to_thread", to_thread)

    assert asyncio.run(console_render.render_clan_status_bar({"approved": 1}, maximum=4)) == b"bar"
    assert calls == [(
        console_render.render_clan_status_bar_sync,
        ({"approved": 1},),
        {"maximum": 4},
    )]


def test_console_thumbnail_assets_are_bounded_png_bytes_and_cached():
    console_render.thumbnail_asset.cache_clear()

    first = console_render.thumbnail_asset("clan_main.png")
    second = console_render.thumbnail_asset("clan_main.png")

    assert first is second
    with Image.open(io.BytesIO(first)) as image:
        assert image.format == "PNG"
        assert image.width <= 160
        assert image.height <= 160


def test_overview_renders_from_vendored_fonts_without_the_system_directory(monkeypatch):
    monkeypatch.setattr(console_render, "_SYSTEM_FONT_DIR", Path("/nonexistent/dejavu"))
    assert console_render._VENDORED_FONT_DIR.is_dir()

    payload = console_render.render_overview_sync(_counts())

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (1400, 740)


def test_missing_font_raises_a_clear_error_naming_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(console_render, "_VENDORED_FONT_DIR", tmp_path)
    monkeypatch.setattr(console_render, "_SYSTEM_FONT_DIR", tmp_path / "also-missing")

    with pytest.raises(OSError, match="DejaVuSans.ttf"):
        console_render._font(16)
