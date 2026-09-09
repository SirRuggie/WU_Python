"""The URL rewrite that ended the August 2026 bandwidth blowout.

These tests pin the two properties the fix depends on: a plain Cloudinary
delivery URL gains exactly one f_auto,q_auto(,w_,c_limit) segment, and
every other value a render site might hold passes through untouched.
"""

import pytest

from utils.cloudinary_urls import DETAIL, GALLERY, THUMBNAIL, optimized

CLOUDINARY = (
    "https://res.cloudinary.com/dxmtzuomk/image/upload/"
    "v1753167826/clan_logos/Warriors_United/Arcane_Angels.png"
)


def test_inserts_transformation_with_width():
    assert optimized(CLOUDINARY, width=THUMBNAIL) == (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "f_auto,q_auto,w_256,c_limit/"
        "v1753167826/clan_logos/Warriors_United/Arcane_Angels.png"
    )


def test_inserts_format_and_quality_only_without_width():
    assert optimized(CLOUDINARY) == (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "f_auto,q_auto/"
        "v1753167826/clan_logos/Warriors_United/Arcane_Angels.png"
    )


def test_idempotent_on_already_transformed_url():
    once = optimized(CLOUDINARY, width=GALLERY)
    assert optimized(once, width=GALLERY) == once


@pytest.mark.parametrize("passthrough", [
    None,
    "",
    "assets/branding/WU_Logo.png",
    "https://cdn.discordapp.com/icons/123/abc.png",
    "https://api-assets.clashofclans.com/badges/512/xyz.png",
    # Versionless Cloudinary URL (hand-pasted by an admin): shape unknown,
    # so it is left alone rather than guessed at.
    "https://res.cloudinary.com/dxmtzuomk/image/upload/clan_logos/X.png",
    12345,
])
def test_non_delivery_values_pass_through(passthrough):
    assert optimized(passthrough, width=THUMBNAIL) == passthrough


def test_unknown_width_is_refused():
    # Arbitrary widths would mint unbounded billable renditions per asset.
    with pytest.raises(ValueError):
        optimized(CLOUDINARY, width=999)


def test_detail_width_for_base_layouts():
    assert "w_1600,c_limit" in optimized(CLOUDINARY, width=DETAIL)
