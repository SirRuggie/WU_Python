"""Explicit production collection routes shared by the bot and maintenance tools.

MONGODB_ROUTES is a JSON object of alias -> {database, collection} overrides.
Absent aliases retain their existing namespace. Invalid configuration fails
before the client connects; an empty destination is never a reason to fall back.
Sandbox/test database routing is intentionally independent.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from types import MappingProxyType

from pymongo.write_concern import WriteConcern

ROUTES_ENV = "MONGODB_ROUTES"
LAZYCWL_WRITE_CONCERN = WriteConcern(w="majority", wtimeout=10000)
RESERVED_DATABASES = frozenset({
    "admin", "local", "config", "database", "test",
    "ticket_testing", "wubot_test",
    "warriors_united_sandbox", "warriors_united_test",
})


@dataclass(frozen=True)
class Namespace:
    database: str
    collection: str


DEFAULT_ROUTES = MappingProxyType({
    'button_store': Namespace("settings", 'button_store'),
    'component_state': Namespace("settings", 'component_state'),
    'clans': Namespace("settings", 'clan_data'),
    'fwa_data': Namespace("settings", 'fwa_data'),
    'fwa_band_data': Namespace("settings", 'fwa_band_data'),
    'ticket_setup': Namespace("settings", 'ticket_setup'),
    'tickets': Namespace("settings", 'tickets'),
    'ticket_flags': Namespace("settings", 'ticket_flags'),
    'ticket_migrations': Namespace("settings", 'ticket_migrations'),
    'ticket_migration_batches': Namespace("settings", 'ticket_migration_batches'),
    'ticket_creation_state': Namespace("settings", 'ticket_creation_state'),
    'cwl_dashboard_state': Namespace("settings", 'cwl_dashboard_state'),
    'bot_config': Namespace("settings", 'bot_config'),
    'discord_polls': Namespace("settings", 'wu_discord_polls'),
    'ticket_automation_state': Namespace("settings", 'ticket_automation_state'),
    'ticket_rollout': Namespace("settings", 'ticket_rollout'),
    'ticket_open_slots': Namespace("settings", 'ticket_open_slots'),
    'recruit_onboarding': Namespace("settings", 'recruit_onboarding'),
    'recruit_challenges': Namespace("settings", 'recruit_challenges'),
    'lazy_cwl_snapshots': Namespace("settings", 'lazy_cwl_snapshots'),
    'lazy_cwl_lists': Namespace("settings", 'lazy_cwl_lists'),
    'cwl_reminder': Namespace("settings", 'cwl_reminder'),
    'cwl_pending_reminders': Namespace("settings", 'cwl_pending_reminders'),
    'fwa_points': Namespace("settings", 'fwa_points'),
    'player_clan_candidates': Namespace("settings", 'player_clan_candidates'),
    'player_clan_watches': Namespace("settings", 'player_clan_watches'),
    'clan_roster_snapshots': Namespace("settings", 'clan_roster_snapshots'),
    'todo_sessions': Namespace("settings", 'todo_sessions'),
    'card_inventories': Namespace("settings", 'card_inventories'),
    'card_trades': Namespace("settings", 'card_trades'),
    'emoji_registry': Namespace("settings", 'emoji_registry'),
    'fwa_blacklist': Namespace("settings", 'fwa_blacklist'),
    'fwa_sync_config': Namespace("settings", 'fwa_sync_config'),
    'fwa_sync_events': Namespace("settings", 'fwa_sync_events'),
    'fwa_sync_responses': Namespace("settings", 'fwa_sync_responses'),
    'fwa_sync_deliveries': Namespace("settings", 'fwa_sync_deliveries'),
    'legacy_fwa_sync_alerts': Namespace("settings", 'fwa_sync_alerts'),
    'ticket_thread_rename_runs': Namespace("settings", 'ticket_thread_rename_runs'),
    'strike_records': Namespace("settings", 'strike_records'),
    'strike_settings': Namespace("settings", 'strike_settings'),
    'strike_leaves': Namespace("settings", 'strike_leaves'),
    'strike_leave_history': Namespace("settings", 'strike_leave_history'),
    'strike_profiles': Namespace("settings", 'strike_profiles'),
    'strike_imports': Namespace("settings", 'strike_imports'),
    'strike_tracking': Namespace("settings", 'strike_tracking'),
    'member_events': Namespace("settings", 'member_events'),
    'member_event_test_audit': Namespace("settings", 'member_event_test_audit'),
})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("MONGODB_ROUTES contains a duplicate key")
        result[key] = value
    return result


def load_routes(overrides=None):
    """Return a frozen complete mapping, validating even aliases not yet used."""
    if overrides is None:
        raw = os.getenv(ROUTES_ENV, "")
        try:
            overrides = json.loads(raw, object_pairs_hook=_unique_object) if raw.strip() else {}
        except (ValueError, TypeError):
            raise ValueError("MONGODB_ROUTES must be a JSON object with unique keys") from None
    if not isinstance(overrides, dict):
        raise ValueError("MONGODB_ROUTES must be an object")
    routes = dict(DEFAULT_ROUTES)
    for alias, entry in overrides.items():
        if alias not in routes:
            raise ValueError("MONGODB_ROUTES contains an unknown collection alias")
        if not isinstance(entry, dict) or set(entry) != {"database", "collection"}:
            raise ValueError("Each Mongo route must specify database and collection")
        database, collection = entry["database"], entry["collection"]
        # Deliberately narrower than MongoDB's full grammar. These routes use
        # portable lowercase names and fit the Atlas Free namespace limits.
        if not isinstance(database, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,37}", database):
            raise ValueError("Invalid production database name")
        if database in RESERVED_DATABASES or database.endswith(("_test", "_testing", "_sandbox")):
            raise ValueError("Production routing cannot target a system, historical, or test database")
        if not isinstance(collection, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", collection):
            raise ValueError("Invalid production collection name")
        if len(database + "." + collection) > 95:
            raise ValueError("Production namespace exceeds the configured 95-byte limit")
        routes[alias] = Namespace(database, collection)
    if len(set(routes.values())) != len(routes):
        raise ValueError("Production collection routes must have unique destinations")
    return MappingProxyType(routes)


def collection_for(client, alias, *, routes=None, **options):
    """Resolve one stable alias on a synchronous or asynchronous PyMongo client."""
    if routes is None:
        # Bypass PyMongo dynamic database lookup for this private Python field.
        try:
            routes = object.__getattribute__(client, "_wu_collection_routes")
        except AttributeError:
            routes = load_routes()
    namespace = routes[alias]  # Unknown aliases must never create ad hoc collections.
    if alias == "lazy_cwl_lists":
        options.setdefault("write_concern", LAZYCWL_WRITE_CONCERN)
    return client.get_database(namespace.database).get_collection(namespace.collection, **options)


class RoutedCollections:
    """Narrow alias facade for tools; deliberately not a MongoDB Database."""

    def __init__(self, client, *, overrides=None):
        self._client = client
        self._routes = load_routes(overrides)

    def __getitem__(self, alias):
        return collection_for(self._client, alias, routes=self._routes)

    def __getattr__(self, alias):
        if alias.startswith("_") or alias not in self._routes:
            raise AttributeError(alias)
        return self[alias]
