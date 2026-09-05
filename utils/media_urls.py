"""Delivery URLs for hosted images: sized for the slot, whatever host holds them.

Mongo stores the raw public URL of every uploaded image. Render sites never
put that raw URL in a component; they call `optimized(url, width=SLOT)`, and
this module decides what to hand Discord:

  * An R2 URL (under R2_PUBLIC_BASE_URL) becomes a Cloudflare Image
    Transformation - `<base>/cdn-cgi/image/width=256,fit=scale-down,format=auto/<key>`
    - when R2_IMAGE_TRANSFORMS is on. Transformations must be enabled for the
    zone in the Cloudflare dashboard (Images > Transformations) first; until
    then the raw URL is returned, which on R2 costs nothing but bytes.
  * A Cloudinary URL still gets Cloudinary's inline transformation, through
    utils/cloudinary_urls.py, until tools/migrate_media_to_r2.py has moved
    every row. That module and this branch go away together afterwards.
  * Everything else - None, a local `assets/` path, a Discord CDN icon, a
    Clash API badge, a pasted link - passes through untouched.

The three widths are the whole vocabulary, on purpose. Cloudflare bills
"unique transformations" (source + option set) per calendar month, 5,000 of
them free; three slots across a few hundred images is a rounding error, and
an arbitrary width per call would not be. Keep it three.

`fit=scale-down` never enlarges; `format=auto` serves WebP or AVIF to
clients that accept them and counts as one transformation either way.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from utils.cloudinary_urls import DETAIL, GALLERY, THUMBNAIL
from utils.cloudinary_urls import optimized as _cloudinary_optimized

__all__ = ["DETAIL", "GALLERY", "THUMBNAIL", "optimized",
           "public_base_url", "transforms_enabled"]

_ALLOWED_WIDTHS = (THUMBNAIL, GALLERY, DETAIL)
_TRANSFORM_PREFIX = "cdn-cgi/image/"
_TRUTHY = {"1", "true", "yes", "on"}


def public_base_url() -> str | None:
    """R2_PUBLIC_BASE_URL without a trailing slash, or None when unset."""
    raw = os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return raw or None


def transforms_enabled() -> bool:
    """R2_IMAGE_TRANSFORMS is on AND the base is a real zone.

    The managed `*.r2.dev` development URL is not a zone and cannot serve
    `/cdn-cgi/image/`, so the flag is ignored there rather than breaking
    every image the moment someone sets it.
    """
    base = public_base_url()
    if not base:
        return False
    if os.getenv("R2_IMAGE_TRANSFORMS", "").strip().lower() not in _TRUTHY:
        return False
    host = (urlparse(base).hostname or "").lower()
    return not host.endswith(".r2.dev")


def optimized(url: object, *, width: int | None = None) -> object:
    """`url` as it should be handed to Discord for a slot `width` px wide.

    See the module docstring for what happens to each kind of value. A width
    outside the three slots raises, on any input, because that mistake is a
    billing bug and should fail in tests rather than mint renditions.
    """
    if width is not None and width not in _ALLOWED_WIDTHS:
        raise ValueError(
            f"width must be one of {_ALLOWED_WIDTHS} (got {width}); "
            "each new width mints another billable rendition per asset"
        )
    if not isinstance(url, str):
        return url
    base = public_base_url()
    if base and url.startswith(base + "/"):
        return _cloudflare(url, base, width)
    return _cloudinary_optimized(url, width=width)


def _cloudflare(url: str, base: str, width: int | None) -> str:
    key = url[len(base) + 1:]
    if not key or key.startswith(_TRANSFORM_PREFIX):
        return url
    if not transforms_enabled():
        return url
    options = ["format=auto"]
    if width is not None:
        options = [f"width={width}", "fit=scale-down", "format=auto"]
    return f"{base}/{_TRANSFORM_PREFIX}{','.join(options)}/{key}"
