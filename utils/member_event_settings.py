"""Pure layered routing for member-event logs.

Legacy per-event destinations remain overrides. Reading an old row never
changes it; a successful revision-checked save writes schema version 2.
"""
from __future__ import annotations

import re
from copy import deepcopy

EVENT_CATEGORIES = {
    "join": "members", "leave": "members",
    "kick": "moderation", "ban": "moderation",
    "timeout_add": "moderation", "timeout_remove": "moderation",
    "member_update": "members",
    "link": "messages",
    "invite_create": "invites", "invite_delete": "invites", "invite_use": "invites",
    "unban": "moderation",
    "role_create": "roles", "role_update": "roles", "role_delete": "roles",
    "roles_added": "roles", "roles_removed": "roles",
    "message_delete": "messages", "message_edit": "messages", "message_bulk_delete": "messages",
    "channel_create": "channels", "channel_update": "channels", "channel_delete": "channels",
    "channel_permissions": "channels", "thread_delete": "channels", "thread_lock": "channels",
    "server_update": "server", "emoji": "server", "sticker": "server",
    "app": "server", "webhook": "server", "automod": "server",
}
CATEGORIES = ("members", "moderation", "roles", "messages", "channels", "server", "invites")
EVENT_TYPES = tuple(EVENT_CATEGORIES)
LEGACY_EVENT_TYPES = ("join", "leave", "kick", "ban")  # Events-only API clients.
SCHEMA_VERSION = 2
MAX_IGNORE_IDS = 100
MAX_IGNORED_BOTS = 50
MAX_INVITE_NAMES = 200
INVITE_CODE = re.compile(r"[A-Za-z0-9-]{2,32}\Z")


def empty_destination():
    return {"channel_id": None, "forum_tag_id": None}


def default_categories():
    return {category: {"mode": "main", **empty_destination()} for category in CATEGORIES}


def default_ignores():
    return {"channel_ids": [], "role_ids": []}


def normalize_settings(row: dict | None, legacy_defaults: dict) -> dict:
    """Return a new v2 value while preserving the old effective destinations."""
    source = row or legacy_defaults
    events = source.get("events", legacy_defaults["events"])
    ignores = source.get("ignores") or {}
    result = {
        "schema_version": SCHEMA_VERSION,
        "revision": source.get("revision", 0),
        "main": deepcopy(source.get("main", empty_destination())),
        "categories": {**default_categories(), **deepcopy(source.get("categories") or {})},
        "events": {kind: deepcopy(events.get(kind, legacy_defaults["events"][kind])) for kind in EVENT_TYPES},
        "ignores": {key: deepcopy(ignores.get(key, [])) for key in default_ignores()},
        "invite_names": deepcopy(source.get("invite_names") or {}),
        # None means never saved: the runtime default is this bot's own id.
        "ignored_bot_ids": (deepcopy(source["ignored_bot_ids"])
                            if isinstance(source.get("ignored_bot_ids"), list) else None),
    }
    return result


def resolve_ignored_bots(settings: dict, own_bot_id) -> list[str]:
    """Saved list as is; a row that never saved one ignores only this bot."""
    saved = settings.get("ignored_bot_ids")
    if isinstance(saved, list):
        return [str(item) for item in saved]
    return [str(own_bot_id)] if own_bot_id else []


def checked_ignored_bot_ids(value) -> list[str]:
    """Distinct snowflake strings, at most MAX_IGNORED_BOTS; raises ValueError."""
    if not isinstance(value, list) or len(value) > MAX_IGNORED_BOTS:
        raise ValueError(f"Select at most {MAX_IGNORED_BOTS} ignored bots.")
    for item in value:
        if not isinstance(item, str) or not item.isascii() or not item.isdigit() or not 17 <= len(item) <= 20:
            raise ValueError("Invalid ignored bot ID.")
    return list(dict.fromkeys(value))


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
