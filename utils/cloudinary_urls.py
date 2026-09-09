"""Delivery-side optimization for Cloudinary URLs.

LEGACY. Uploads moved to Cloudflare R2 in September 2026 (utils/media_store.py);
utils/media_urls.py routes only URLs still on res.cloudinary.com here. Once
tools/migrate_media_to_r2.py has moved every Mongo row, delete this module,
its tests and the Cloudinary branch of media_urls together.

Every image this bot stores on Cloudinary is uploaded as a full-size
original, and until September 2026 it was also DELIVERED full-size: a
multi-megabyte clan logo squeezed into an 80px thumbnail slot cost the
full megabytes every time Discord's media proxy re-fetched it. That is
what emptied the Cloudinary bandwidth budget (116 GB in August 2026 -
the free plan is ~25 GB).

`optimized()` rewrites a delivery URL to insert an inline transformation
(`f_auto,q_auto` plus an optional width cap) so Cloudinary serves a
rendition sized for the slot it renders in. Originals in Cloudinary and
the URLs stored in Mongo stay untouched - the rewrite happens at render
time, so it also covers URLs uploaded years ago.

Cost note: a transformation is billed once per unique rendition (a
fraction of a credit across the whole account), then cached on
Cloudinary's CDN; bandwidth drops by 90%+ per fetch. Do not "improve"
this by adding per-call variety (timestamps, jitter, many widths): every
distinct transformation string mints a new billable rendition.
"""

_UPLOAD_MARKER = "/image/upload/"

# The only widths render sites may ask for, one per slot shape. A bounded
# set keeps the number of billable renditions per asset at three, forever.
THUMBNAIL = 256   # Section/Thumbnail accessories (~80px slot, retina headroom)
GALLERY = 1024    # MediaGallery items inside containers
DETAIL = 1600     # images people zoom into (FWA base layouts)

_ALLOWED_WIDTHS = (THUMBNAIL, GALLERY, DETAIL)


def optimized(url: object, *, width: int | None = None) -> object:
    """`url` rewritten to deliver an f_auto,q_auto rendition, capped at `width`.

    Anything that is not a plain Cloudinary upload-delivery URL - None, a
    Discord CDN guild icon, a Clash API badge, a local asset path, or a
    Cloudinary URL that already carries a transformation - passes through
    unchanged, so call sites can wrap whatever value they hold.
    """
    if not isinstance(url, str):
        return url
    if "res.cloudinary.com" not in url or _UPLOAD_MARKER not in url:
        return url
    head, tail = url.split(_UPLOAD_MARKER, 1)
    first_segment = tail.split("/", 1)[0]
    # Upload-delivery paths start with a v<timestamp> version (every
    # secure_url Cloudinary returns does). Anything else in that position
    # is a transformation someone already chose - leave it alone.
    if not _is_version_segment(first_segment):
        return url
    parts = ["f_auto", "q_auto"]
    if width is not None:
        if width not in _ALLOWED_WIDTHS:
            raise ValueError(
                f"width must be one of {_ALLOWED_WIDTHS} (got {width}); "
                "each new width mints another billable rendition per asset"
            )
        parts.append(f"w_{width}")
        parts.append("c_limit")
    return f"{head}{_UPLOAD_MARKER}{','.join(parts)}/{tail}"


def _is_version_segment(segment: str) -> bool:
    return len(segment) > 1 and segment[0] == "v" and segment[1:].isdigit()
