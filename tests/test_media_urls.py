"""Delivery URL rewriting across both hosts, driven by the R2_* environment.

The R2 rules: an R2 URL becomes a Cloudflare transformation only when the
flag is on AND the base is a real zone; Cloudinary rows still get their
inline transformation until the migration script has moved them; everything
else passes through. And the width vocabulary stays at three, on any input.
"""

import pytest

from utils.media_urls import DETAIL, GALLERY, THUMBNAIL, optimized, transforms_enabled

BASE = "https://img.example.com"
KEY = "clan_logos/Warriors_United/Arcane_Angels.0123456789.png"
R2 = f"{BASE}/{KEY}"
CLOUDINARY = (
    "https://res.cloudinary.com/dxmtzuomk/image/upload/"
    "v1753167826/clan_logos/Warriors_United/Arcane_Angels.png"
)


@pytest.fixture
def r2_transforms(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", BASE + "/")   # trailing slash tolerated
    monkeypatch.setenv("R2_IMAGE_TRANSFORMS", "true")


def test_r2_url_becomes_cloudflare_transformation(r2_transforms):
    assert optimized(R2, width=THUMBNAIL) == (
        f"{BASE}/cdn-cgi/image/width=256,fit=scale-down,format=auto/{KEY}"
    )


def test_r2_url_without_width_only_picks_format(r2_transforms):
    assert optimized(R2) == f"{BASE}/cdn-cgi/image/format=auto/{KEY}"


def test_idempotent_on_already_transformed_url(r2_transforms):
    once = optimized(R2, width=GALLERY)
    assert optimized(once, width=GALLERY) == once


def test_all_three_widths_are_distinct_renditions(r2_transforms):
    urls = {optimized(R2, width=w) for w in (THUMBNAIL, GALLERY, DETAIL)}
    assert len(urls) == 3
    assert any("width=1600" in u for u in urls)


def test_flag_off_returns_the_raw_r2_url(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", BASE)
    monkeypatch.delenv("R2_IMAGE_TRANSFORMS", raising=False)
    assert optimized(R2, width=THUMBNAIL) == R2
    assert transforms_enabled() is False


def test_flag_is_ignored_on_the_r2_dev_development_url(monkeypatch):
    base = "https://pub-0123456789abcdef.r2.dev"
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", base)
    monkeypatch.setenv("R2_IMAGE_TRANSFORMS", "1")
    url = f"{base}/{KEY}"
    assert optimized(url, width=THUMBNAIL) == url
    assert transforms_enabled() is False


def test_no_base_configured_means_no_r2_rewrite(monkeypatch):
    monkeypatch.delenv("R2_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("R2_IMAGE_TRANSFORMS", "true")
    assert optimized(R2, width=THUMBNAIL) == R2


def test_cloudinary_rows_still_get_their_inline_transformation(r2_transforms):
    assert optimized(CLOUDINARY, width=THUMBNAIL) == (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "f_auto,q_auto,w_256,c_limit/"
        "v1753167826/clan_logos/Warriors_United/Arcane_Angels.png"
    )


@pytest.mark.parametrize("passthrough", [
    None,
    "",
    "assets/branding/WU_Logo.png",
    "https://cdn.discordapp.com/icons/123/abc.png",
    "https://api-assets.clashofclans.com/badges/512/xyz.png",
    "https://img.example.com.evil.test/clan_logos/x.png",   # base is a prefix of the host
    "https://other.example.com/clan_logos/x.png",
    12345,
])
def test_everything_else_passes_through(r2_transforms, passthrough):
    assert optimized(passthrough, width=THUMBNAIL) == passthrough


@pytest.mark.parametrize("value", [R2, CLOUDINARY, None, "assets/branding/WU_Logo.png"])
def test_unknown_width_is_refused_for_any_input(r2_transforms, value):
    # An arbitrary width would mint unbounded billable renditions per asset.
    with pytest.raises(ValueError):
        optimized(value, width=999)
