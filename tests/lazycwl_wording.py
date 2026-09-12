# tests/lazycwl_wording.py
"""Shared wording rule for LazyCWL render-facing text (design-01-main.md §2).

One copy, imported by both tests/test_lazycwl_dashboard.py's banned-word
scan and tests/test_lazy_cwl_aliases.py's notice-string check, so the rule
cannot drift between the two (refuter-14 NOTED)."""

BANNED_WORDS = {
    "snapshot", "ping", "sync", "fwa", "cwl", "th",
    "cadence", "interval", "roster", "reset",
}
# "Lazy CWL" is the one allowed title exception.
ALLOWED_CWL_STRINGS = {"Lazy CWL", "## Lazy CWL"}
