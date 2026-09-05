"""Tests for the hikari 2.3.5 web-resource double-fetch shim.

The shim (utils/hikari_shims.py) patches process-global state on
hikari.impl.special_endpoints. It is installed once here, at module import
time, so every test below holds regardless of whether other test modules
installed it first (install_web_resource_skip() is idempotent) and
regardless of run order within this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hikari import files
from hikari.impl import special_endpoints as se
from PIL import Image

from utils.hikari_shims import _needs_shim, install_web_resource_skip

# Install once at import time so the patched builders are used by every test
# in this module, no matter the order pytest picks.
install_web_resource_skip()

URL = "https://wu-media.ruggie.zone/clans/X/logo.abc.png"


@pytest.fixture
def local_png(tmp_path: Path) -> Path:
    path = tmp_path / "tiny.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(path)
    return path


@pytest.mark.parametrize(
    "version, expected",
    [
        ("2.3.5", True),
        ("2.5.0", True),
        ("2.6.0", False),
        ("2.10.1", False),
        ("3.0.0", False),
    ],
)
def test_needs_shim_table(version: str, expected: bool) -> None:
    assert _needs_shim(version) is expected


def test_install_is_idempotent_and_reports_installed() -> None:
    # Already installed once at module import time; calling again must not
    # re-wrap, and must still report True (installed, whether by this call
    # or an earlier one).
    before = se.ThumbnailComponentBuilder.build
    assert install_web_resource_skip() is True
    assert install_web_resource_skip() is True
    assert se.ThumbnailComponentBuilder.build is before


def test_thumbnail_url_media_keeps_url_and_drops_resource() -> None:
    builder = se.ThumbnailComponentBuilder(media=URL)
    payload, resources = builder.build()

    assert payload["media"]["url"] == URL
    assert resources == ()


def test_media_gallery_local_file_still_uploads_only_local_resource(local_png: Path) -> None:
    gallery = se.MediaGalleryComponentBuilder(
        items=[
            se.MediaGalleryItemBuilder(media=URL),
            se.MediaGalleryItemBuilder(media=str(local_png)),
        ]
    )
    payload, resources = gallery.build()

    expected_local_resource = files.ensure_resource(str(local_png))
    assert list(resources) == [expected_local_resource]
    assert payload["items"][0]["media"]["url"] == URL


def test_section_with_thumbnail_url_and_gallery_local_file_yields_one_resource(local_png: Path) -> None:
    section = se.SectionComponentBuilder(
        accessory=se.ThumbnailComponentBuilder(media=URL),
        components=[
            se.MediaGalleryComponentBuilder(
                items=[se.MediaGalleryItemBuilder(media=str(local_png))]
            )
        ],
    )
    payload, resources = section.build()

    expected_local_resource = files.ensure_resource(str(local_png))
    assert list(resources) == [expected_local_resource]
