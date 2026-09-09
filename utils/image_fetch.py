"""Fetching an image the bot was handed a URL for.

Two callers pull images from URLs a person typed: the clan dashboard's emoji
flow (`update_clan_info.process_emoji_upload`) and the FWA dashboard's
"update images from URL" modal, which used to hand the URL to Cloudinary and
let Cloudinary do the fetching. Cloudinary is gone (see
docs/media-hosting.md), so the bot fetches for itself, and both callers need
the same guards: a public-only host check (utils/url_safety.py), no
redirects, a timeout, and a byte cap.

Both functions are BLOCKING on purpose. Call them through
`asyncio.to_thread` so the download never runs on the event loop.
"""

from __future__ import annotations

import requests

from utils.url_safety import MAX_IMAGE_BYTES, is_safe_public_url


def download_image_blocking(url: str) -> bytes:
    """Fetch an image with a timeout, no redirects, and a byte cap.

    allow_redirects is off so a URL validated as public cannot bounce the bot
    to an internal host. Raises `requests.HTTPError` for a non-2xx status and
    `ValueError` when the body is larger than MAX_IMAGE_BYTES.
    """
    with requests.get(
        url,
        timeout=(5, 15),        # (connect seconds, read seconds)
        allow_redirects=False,
        stream=True,
    ) as resp:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            raise ValueError("Image is larger than the 10 MB limit.")
        chunks = []
        total = 0
        for chunk in resp.iter_content(8192):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ValueError("Image is larger than the 10 MB limit.")
            chunks.append(chunk)
        return b"".join(chunks)


def fetch_public_image(url: str) -> bytes:
    """`download_image_blocking` behind the public-URL check.

    Raises `ValueError` with a user-facing reason when the URL is not a
    direct, public image link, so callers can put the message straight into
    a Discord reply.
    """
    ok, reason = is_safe_public_url(url)
    if not ok:
        raise ValueError(reason)
    return download_image_blocking(url)
