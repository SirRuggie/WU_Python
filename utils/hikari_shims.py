"""Startup shim closing the hikari 2.3.5 Components V2 double-fetch.

On hikari 2.3.5, ``ThumbnailComponentBuilder.build()`` and
``MediaGalleryItemBuilder.build()`` (in ``hikari.impl.special_endpoints``)
return ``(payload, (media_resource,))`` unconditionally -- even when the
media is an ``https://`` URL rather than a local file. The REST layer then
uploads every returned resource as a hidden attachment
(``RESTClientImpl._build_message_payload``), so on every send *and* every
edit the bot downloads the URL and re-uploads it to Discord, while Discord's
own media proxy fetches the same URL again for display. Classic embeds are
unaffected; only Components V2 (Thumbnail / MediaGalleryItem) hits this.

hikari 2.6.0 fixed this upstream (``RESTClientImpl._filter_web_resources``,
hikari issue/PR #2687: "Do not fetch WebResource attachments if they're part
of components/embeds"). We stay on hikari 2.3.5 for now because
hikari-lightbulb 3.0.3 pins ``hikari~=2.3.1`` (see
docs/hikari-lightbulb-versions.md), so this module mirrors that 2.6.0 fix at
the builder level until the coupled hikari/lightbulb upgrade happens.

``install_web_resource_skip()`` wraps both builders' ``build()`` methods so
the returned resources tuple drops any ``hikari.files.WebResource`` instance
(URL-backed media). Local files and in-memory ``hikari.files.Bytes`` are not
``WebResource`` instances, so they are left in the tuple and still upload
normally. The JSON payload is untouched either way -- the component still
points Discord at the original URL for display.

See docs/media-hosting.md section 3, option B, for the full writeup and the
verified before/after behaviour.

DELETE THIS MODULE (and tests/test_hikari_shims.py) when the bot moves to
hikari 2.6.0 -- see docs/hikari-lightbulb-versions.md.
"""

from __future__ import annotations

import functools

import hikari
from hikari import files
from hikari.impl import special_endpoints as se

_PATCHED_ATTR = "_wu_web_resource_skip_installed"


def _needs_shim(version: str) -> bool:
    """True when `version`'s leading numeric components are below 2.6.0.

    Only the first three dot-separated components are parsed (a trailing
    suffix such as "2.6.0rc1" is ignored on that last component); anything
    that fails to parse as an integer is treated as 0.
    """
    parts = version.split(".")[:3]
    parsed: list[int] = []
    for part in parts:
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        parsed.append(int(digits) if digits else 0)
    while len(parsed) < 3:
        parsed.append(0)
    return tuple(parsed) < (2, 6, 0)


def install_web_resource_skip() -> bool:
    """Patch the 2.3.5 builders to drop URL media from upload candidates.

    No-op (returns False) once hikari is 2.6.0 or newer, where the builders
    already do this upstream. Idempotent: calling this more than once only
    installs the wrapper once.

    Returns True if the shim is installed (including if it was already
    installed by an earlier call), False if it was skipped.
    """
    if not _needs_shim(hikari.__version__):
        return False

    if getattr(se.ThumbnailComponentBuilder.build, _PATCHED_ATTR, False):
        return True

    def _skip_web_resources(build):
        """hikari 2.3.5 uploads URL media as attachments; 2.6.0 does not (#2687)."""

        @functools.wraps(build)
        def wrapped(self):
            payload, resources = build(self)
            return payload, tuple(r for r in resources if not isinstance(r, files.WebResource))

        setattr(wrapped, _PATCHED_ATTR, True)
        return wrapped

    se.ThumbnailComponentBuilder.build = _skip_web_resources(se.ThumbnailComponentBuilder.build)
    se.MediaGalleryItemBuilder.build = _skip_web_resources(se.MediaGalleryItemBuilder.build)

    return True
