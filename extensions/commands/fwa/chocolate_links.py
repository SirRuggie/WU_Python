"""Shared FWA Chocolate link helpers.

Keep URL construction in one place so the manual command and automated ticket
checklist cannot drift apart.
"""

from __future__ import annotations

import re


_TAG_RE = re.compile(r"^[A-Z0-9]{2,15}$")


def normalize_tag(tag: str) -> str:
    """Return a Clash tag without leading hashes or internal whitespace, in uppercase.

    Leniently accepts what `main`'s `/fwa chocolate` accepts: doubled `#`
    (``##ABC123``) and internal spaces (``# ABC 123``), not just a single
    clean leading hash.
    """

    normalized = str(tag).strip().lstrip("#")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.upper()


def is_valid_tag(tag: str) -> bool:
    """Apply the same deliberately small validation used by the slash command."""

    return bool(_TAG_RE.fullmatch(normalize_tag(tag)))


def chocolate_url(tag: str, *, tag_type: str = "player") -> str:
    """Build a direct FWA Chocolate URL for a player or clan tag."""

    normalized = normalize_tag(tag)
    if not is_valid_tag(normalized):
        raise ValueError("Chocolate tags must contain 2 to 15 letters or numbers")
    page = "member.php" if tag_type == "player" else "clan.php"
    return f"https://cc.fwafarm.com/cc_n/{page}?tag={normalized}"
