"""Shared navigation vocabulary for management Components V2 screens."""
from __future__ import annotations

import hikari

ICONS = {
    "yes": 1397096942907166831,
    "no": 1397096986506825778,
    "back": 1536796427198668911,
    "home": 1536924506147524730,
    "next": 1536793616004022403,
    "previous": 1536793616863862784,
    "search": 1536797595089899540,
    "refresh": 1536798918858514502,
    "settings": 1537238367857676310,
    "edit": 1537264251603779764,
}


def button_emoji(label: str):
    """Keep labels readable; add an icon only for recognized action meanings."""
    text = label.strip().casefold()
    kind = None
    if text in {"yes", "confirm", "accept"} or text.startswith(("confirm ", "yes, ", "accept ")):
        kind = "yes"
    elif text in {"no", "deny", "cancel"} or text.startswith(("cancel ", "deny ", "no, ")):
        kind = "no"
    elif text == "management home":
        kind = "home"
    elif text == "back" or text.startswith("back to "):
        kind = "back"
    elif text == "previous" or text.startswith("previous "):
        kind = "previous"
    elif text == "next" or text.startswith(("next page", "next clans")):
        kind = "next"
    elif text == "refresh" or text.startswith("refresh "):
        kind = "refresh"
    elif text.startswith(("search", "find ")):
        kind = "search"
    elif text in {"settings", "advanced", "advanced settings", "admin settings", "more options"}:
        kind = "settings"
    elif text.startswith(("edit ", "update link", "update images", "update descriptions")) or text in {"edit", "keep editing"}:
        kind = "edit"
    return hikari.Snowflake(ICONS[kind]) if kind else hikari.UNDEFINED


def breadcrumb(*parts: str) -> str:
    return "-# " + " › ".join(("Management", *parts))
