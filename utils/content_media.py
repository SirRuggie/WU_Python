"""Pure content-gallery snapshots and stable Discord attachment identity.

Rendering, editor state, transport and persistence stay with their existing
owners. Hosted-image delivery transformations and upload state live elsewhere.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import hikari


def media_galleries(items):
    """Return galleries in their rendered order, including galleries in cards."""
    result = []
    for item in items:
        if getattr(item, "type", None) == hikari.ComponentType.MEDIA_GALLERY:
            result.append(item)
        result.extend(media_galleries(getattr(item, "components", ())))
    return result


def media_url(item):
    value = getattr(item, "media", None)
    url = getattr(value, "url", value)
    return str(url) if url is not None else ""


def canonical_media_url(value: str) -> str:
    """Ignore Discord's rotating attachment signatures, and nothing else."""
    parsed = urlparse(value)
    if (
        parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net"}
        and parsed.path.startswith("/attachments/")
    ):
        query = urlencode([
            (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in {"ex", "is", "hm"}
        ])
        return urlunparse(parsed._replace(query=query))
    return value


def discord_attachment_id(value: str) -> str | None:
    """The stable Discord attachment id behind a CDN or media-proxy URL."""
    parsed = urlparse(value)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net"}
        and len(parts) >= 4
        and parts[0] == "attachments"
        and parts[2].isdigit()
    ):
        return parts[2]
    return None


def media_snapshot(components):
    """The one image URL in each named gallery, in schema order."""
    values = []
    for gallery in media_galleries(components):
        items = getattr(gallery, "items", ())
        if len(items) != 1:
            raise ValueError("The content dashboard does not support the image layout of that post.")
        value = canonical_media_url(media_url(items[0]))
        if not value:
            raise ValueError("This post has an empty media slot.")
        values.append(value)
    return values
