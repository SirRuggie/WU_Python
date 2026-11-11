"""Discord profile links whose labels render as links in every client."""
from __future__ import annotations

import re
import unicodedata

# Discord shows backslash escapes inside masked-link labels as literal text,
# so Markdown characters become visually similar characters instead.
_LOOKALIKES = str.maketrans({
    "|": "│", "\\": "╲", "[": "［", "]": "］",
    "(": "（", ")": "）", "*": "∗", "_": "＿",
    "~": "～", "`": "′", "<": "‹", ">": "›",
})


def profile_label(value: object, limit: int = 64, fallback: str = "Discord profile") -> str:
    """Plain masked-link label: no escapes, emoji, mentions or live URLs."""
    # Discord parses emoji before masked links in some clients. Keep the
    # anchor text free of emoji, flags, joiners and variation selectors.
    label = "".join(c for c in str(value or "") if c.isprintable()
                    and unicodedata.category(c) != "So"
                    and not ("\U0001f3fb" <= c <= "\U0001f3ff")
                    and c not in "\ufe0e\ufe0f\u20e3")[:limit]
    label = label.translate(_LOOKALIKES).replace("@", "@\u200b")
    label = re.sub(r"(?i)\b(https?)://", "\\1\u200b://", label)
    return " ".join(label.split()) or fallback

