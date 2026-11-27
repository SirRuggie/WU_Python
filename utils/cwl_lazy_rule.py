"""The shared Lazy CWL participation thresholds and public wording."""

from __future__ import annotations

LAZY_MIN_ATTACKS = 4
LAZY_ALT_ATTACKS = 3
LAZY_ALT_STARS = 8
RULE_SHORT = "4+ attacks, or 3 attacks and 8+ stars"
RULE_SENTENCE = "Do 4 or more attacks, OR do 3 attacks and get 8 or more stars."


def lazy_qualifies(attacks: int, stars: int) -> bool:
    return attacks >= LAZY_MIN_ATTACKS or (
        attacks >= LAZY_ALT_ATTACKS and stars >= LAZY_ALT_STARS
    )
