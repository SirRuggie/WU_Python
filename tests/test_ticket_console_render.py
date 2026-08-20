import asyncio
import io

from PIL import Image

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
