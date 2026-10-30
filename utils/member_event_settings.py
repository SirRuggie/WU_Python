"""Pure layered routing for member-event logs.

Legacy per-event destinations remain overrides. Reading an old row never
changes it; a successful revision-checked save writes schema version 2.
"""
from __future__ import annotations

from copy import deepcopy

EVENT_CATEGORIES = {"join": "members", "leave": "members", "kick": "moderation", "ban": "moderation"}
CATEGORIES = ("members", "moderation")
EVENT_TYPES = tuple(EVENT_CATEGORIES)
SCHEMA_VERSION = 2


def empty_destination():
    return {"channel_id": None, "forum_tag_id": None}


def default_categories():
    return {category: {"mode": "main", **empty_destination()} for category in CATEGORIES}


def normalize_settings(row: dict | None, legacy_defaults: dict) -> dict:
    """Return a new v2 value while preserving the old effective destinations."""
    source = row or legacy_defaults
    events = source.get("events", legacy_defaults["events"])
    result = {
        "schema_version": SCHEMA_VERSION,
        "revision": source.get("revision", 0),
        "main": deepcopy(source.get("main", empty_destination())),
        "categories": deepcopy(source.get("categories", default_categories())),
        "events": {kind: deepcopy(events.get(kind, legacy_defaults["events"][kind])) for kind in EVENT_TYPES},
        "ignores": deepcopy(source.get("ignores", {})),
    }
    return result


def effective_event(settings: dict, kind: str) -> dict:
    """Resolve enabled state and destination, with category Off taking priority."""
    if kind not in EVENT_CATEGORIES:
        raise ValueError("Unsupported member event")
    event = settings["events"][kind]
    if "categories" not in settings:  # Original callers and persisted rows.
        return {"enabled": bool(event["enabled"]),
                "channel_id": event.get("channel_id"),
                "forum_tag_id": event.get("forum_tag_id")}
    category = settings["categories"][EVENT_CATEGORIES[kind]]
    if category["mode"] == "off":
        return {"enabled": False, **empty_destination()}
    destination = (event if event.get("channel_id") else
                   category if category["mode"] == "own" else settings["main"])
    return {
        "enabled": bool(event["enabled"]),
        "channel_id": destination.get("channel_id"),
        "forum_tag_id": destination.get("forum_tag_id"),
    }
