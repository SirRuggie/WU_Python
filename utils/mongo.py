import logging
import time

from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from utils.mongo_routes import LAZYCWL_WRITE_CONCERN, collection_for, load_routes

_log = logging.getLogger(__name__)

# Retry at most hourly rather than on every /clan add. A transient startup
# outage must not disable the guard until restart, but repeated failures
# also must not flood the log.
_clan_tag_index_ready = False
_clan_tag_index_failed = False
_clan_tag_index_retry_at = 0.0
CLAN_TAG_INDEX_RETRY_SECONDS = 60 * 60


class MongoClient(AsyncMongoClient):
    def __init__(self, uri: str, *, route_overrides=None, **kwargs):
        routes = load_routes(route_overrides)
        super().__init__(host=uri, **kwargs)
        self._wu_collection_routes = routes
        self.button_store = collection_for(self, "button_store", routes=routes)
        # Fixed-lifetime kwargs for Components V2 interactions. The TTL index is
        # owned by utils.component_state; durable tickets never enter here.
        self.component_state = collection_for(self, "component_state", routes=routes)
        self.clans = collection_for(self, "clans", routes=routes)
        # Active strikes expire after60days; backup-gated history retention is90days.
        self.strike_records = collection_for(self, "strike_records", routes=routes)
        self.strike_settings = collection_for(self, "strike_settings", routes=routes)
        self.strike_leaves = collection_for(self, "strike_leaves", routes=routes)
        self.strike_leave_history = collection_for(self, "strike_leave_history", routes=routes)
        self.strike_profiles = collection_for(self, "strike_profiles", routes=routes)
        self.strike_imports = collection_for(self, "strike_imports", routes=routes)
        self.player_activity = collection_for(self, "player_activity", routes=routes)
        self.member_profiles = collection_for(self, "member_profiles", routes=routes)
        self.strike_tracking = collection_for(self, "strike_tracking", routes=routes)
        self.strike_war_snapshots = collection_for(self, "strike_war_snapshots", routes=routes)
        # Permanent identity and avatar snapshots plus delivery receipts. No TTL.
        self.member_events = collection_for(self, "member_events", routes=routes)
        # Test-send rate claims and audit live apart from real member history.
        self.member_event_test_audit = collection_for(self, "member_event_test_audit", routes=routes)
        self.fwa_data = collection_for(self, "fwa_data", routes=routes)
        self.fwa_band_data = collection_for(self, "fwa_band_data", routes=routes)
        self.ticket_setup = collection_for(self, "ticket_setup", routes=routes)
        # Owner: utils.ticket_staff_content, schema version 1. Permanent guild/type
        # configuration, _id="<guild_id>:<main|fwa>"; no ticket data or session TTL.
        self.ticket_staff_templates = self.ticket_setup.database.get_collection("ticket_staff_templates")
        # Warrior owner: extensions/warrior/schema.py. Follow the configured
        # production database; do not mix new setup records with legacy recruit
        # onboarding or ticket configuration. All four are permanent (no TTL).
        # Settings: warrior_settings:<guild>; runs: warrior:<guild>:<user>;
        # history: run key + run token; audit: warrior_audit:<guild>:<user>,
        # retaining the latest 100 events per member.
        warrior_db = self.ticket_setup.database
        self.warrior_settings = warrior_db.get_collection("warrior_settings")
        self.warrior_walkthroughs = warrior_db.get_collection("warrior_walkthroughs")
        self.warrior_history = warrior_db.get_collection("warrior_history")
        self.warrior_audit = warrior_db.get_collection("warrior_audit")
        # Durable ticket records. Historically these lived in button_store next to
        # ephemeral component state; see extensions/commands/tickets/store.py.
        # NO TTL INDEX ON THIS COLLECTION - ticket history is permanent.
        # schema_version is this collection's own counter, owned by
        # extensions/commands/tickets/schema.py:SCHEMA_VERSION (currently 3).
        # It is unrelated to ticket_rollout/ticket_open_slots below, whose
        # schema_version is a separate, independently-versioned literal.
        self.tickets = collection_for(self, "tickets", routes=routes)
        # Durable staff-authored applicant flags used by the ticket console.
        # No TTL: inactive records remain as an audit trail.
        self.ticket_flags = collection_for(self, "ticket_flags", routes=routes)
        # Durable checkpoints for resumable source-channel -> thread cloning.
        # Source Discord content is never stored here; only progress and IDs.
        self.ticket_migrations = collection_for(self, "ticket_migrations", routes=routes)
        # Durable plan/progress state for `/tickets migrate-all`, one document
        # per source guild (`_id="batch:<source_guild_id>"`). Permanent, no TTL:
        # it is the resumable checkpoint for which legacy channel is next.
        # Per-ticket side effects still live in ticket_migrations above.
        self.ticket_migration_batches = collection_for(
            self, "ticket_migration_batches", routes=routes
        )
        # Short-lived idempotency leases for cross-system ticket creation.
        # Durable ticket history remains in tickets; handlers.py owns this TTL.
        self.ticket_creation_state = collection_for(self, "ticket_creation_state", routes=routes)
        self.cwl_dashboard_state = collection_for(self, "cwl_dashboard_state", routes=routes)
        self.bot_config = collection_for(self, "bot_config", routes=routes)
        # WU-owned Discord polls and named votes. Keep these separate from
        # Arcane's discord_polls rows: each bot can edit only messages it posted.
        # utils.poll_store adds a post-end TTL through the optional purge_at field.
        self.discord_polls = collection_for(self, "discord_polls", routes=routes)
        self.ticket_automation_state = collection_for(self, "ticket_automation_state", routes=routes)
        # Shared, non-TTL durability for legacy/thread ticket coexistence.
        # ticket_rollout also holds the monotonic counters; neither collection
        # may ever receive a TTL index.
        # ROLLOUT_SCHEMA_VERSION (extensions/commands/ticket_runtime.py) versions
        # the rollout-state document only; the ticket_number_counters document
        # in the same collection carries its own literal schema_version: 1.
        self.ticket_rollout = collection_for(self, "ticket_rollout", routes=routes)
        # schema_version: 1 is a plain literal here (extensions/commands/
        # ticket_runtime.py), not a named constant like tickets' SCHEMA_VERSION
        # or ticket_rollout's ROLLOUT_SCHEMA_VERSION above -- each of these
        # three ticket-adjacent collections versions its own documents
        # independently; the numbers are not comparable across collections.
        self.ticket_open_slots = collection_for(self, "ticket_open_slots", routes=routes)
        self.recruit_onboarding = collection_for(self, "recruit_onboarding", routes=routes)
        # Short-lived message challenges used during recruitment. This stays
        # separate from durable walkthrough records in recruit_onboarding so a
        # TTL index cannot remove role-cleanup history.
        self.recruit_challenges = collection_for(self, "recruit_challenges", routes=routes)
        # Keep legacy snapshots available for the idempotent dashboard migration.
        self.lazy_cwl_snapshots = collection_for(self, "lazy_cwl_snapshots", routes=routes)
        self.lazy_cwl_lists = collection_for(
            self, "lazy_cwl_lists", routes=routes, write_concern=LAZYCWL_WRITE_CONCERN
        )
        # CWL reminder scheduling. cwl_reminder holds one singleton "schedule"
        # document (base time, followups, delivery_issues); cwl_pending_reminders
        # holds one row per outstanding job, keyed by job_id. Keep them separate:
        # extensions/tasks/cwl_reminder.py:restore_pending_reminders() does an
        # unfiltered find() over cwl_pending_reminders and would delete the
        # schedule document if the two ever shared a collection.
        self.cwl_reminder = collection_for(self, "cwl_reminder", routes=routes)
        self.cwl_pending_reminders = collection_for(self, "cwl_pending_reminders", routes=routes)
        self.fwa_war_plans = collection_for(self, "fwa_war_plans", routes=routes)
        self.fwa_points = collection_for(self, "fwa_points", routes=routes)
        # Bounded discovery data for /todo. History/candidate rows and watches
        # both carry BSON-date TTL anchors; utils/clan_history.py owns indexes.
        self.player_clan_candidates = collection_for(self, "player_clan_candidates", routes=routes)
        self.player_clan_watches = collection_for(self, "player_clan_watches", routes=routes)
        self.clan_roster_snapshots = collection_for(self, "clan_roster_snapshots", routes=routes)
        # Bounded DM /todo auto-refresh sessions. TTL index on expires_at is
        # created lazily by utils/todo_sessions.py.
        self.todo_sessions = collection_for(self, "todo_sessions", routes=routes)
        # Durable, member-owned Clash of Cards inventories.  One document per
        # player tag; event cards are not exposed by Supercell's public API.
        self.card_inventories = collection_for(self, "card_inventories", routes=routes)
        # Two-party card proposals and their expiring reservations. Completed
        # rows remain as a compact audit trail; no screenshots or tokens live here.
        self.card_trades = collection_for(self, "card_trades", routes=routes)
        # Application emojis this bot uploaded and therefore owns. One row per
        # emoji, keyed "troop:<slug>". A row here is what authorizes replacing
        # an emoji, so emojis added by hand are never touched by the sync.
        self.emoji_registry = collection_for(self, "emoji_registry", routes=routes)
        # Staff-maintained FWA opponent blacklist. Keyed by sanitized tag (no
        # '#'). See utils/fwa_blacklist.py and docs/fwa-blacklist.md.
        self.fwa_blacklist = collection_for(self, "fwa_blacklist", routes=routes)
        # FWA sync panel storage (extensions/tasks/band_sync_ical.py,
        # extensions/tasks/band_sync_schema.py). Four collections replace the old
        # single fwa_sync_alerts mixed-kind collection; that legacy collection is
        # kept as an explicit legacy source for the startup config migration.
        # Owner: FWA sync task. Singleton config, permanent (no TTL), _id="config".
        self.fwa_sync_config = collection_for(self, "fwa_sync_config", routes=routes)
        # Owner: FWA sync task. One row per BAND event, TTL(expire_at) 7 days after
        # start, _id="event:{uid}".
        self.fwa_sync_events = collection_for(self, "fwa_sync_events", routes=routes)
        # Owner: FWA sync task. One row per user per event, TTL(expire_at) 7 days
        # after start, _id="{uid}|{user_id}".
        self.fwa_sync_responses = collection_for(self, "fwa_sync_responses", routes=routes)
        # Owner: FWA sync task. One row per queued/sent DM, TTL(expire_at) 7 days
        # after start, _id="delivery:{uid}|{event_version}|{offset}|{user_id}".
        self.fwa_sync_deliveries = collection_for(self, "fwa_sync_deliveries", routes=routes)

        # Compatibility and maintenance-tool state are also explicitly routed.
        self.legacy_fwa_sync_alerts = collection_for(self, "legacy_fwa_sync_alerts", routes=routes)
        self.ticket_thread_rename_runs = collection_for(self, "ticket_thread_rename_runs", routes=routes)


async def ensure_clan_tag_index(mongo: "MongoClient") -> bool:
    """Create the unique index on clans.tag once per process, retrying hourly
    after failure; never fatal.

    Without this index, a repeat `/clan add` for the same tag inserts a
    second document instead of updating the existing one (rules 7, 9 in
    docs/mongodb-refactor.md). If duplicate tags already exist, index
    creation fails with DuplicateKeyError -- that is logged at ERROR and the
    bot keeps running with the index absent; see
    tools/find_duplicate_clans.py to locate and resolve the duplicates.
    """
    global _clan_tag_index_ready, _clan_tag_index_failed, _clan_tag_index_retry_at
    if _clan_tag_index_ready:
        return True
    if _clan_tag_index_failed and time.monotonic() < _clan_tag_index_retry_at:
        return False
    try:
        await mongo.clans.create_index("tag", unique=True, name="uniq_clan_tag")
        _clan_tag_index_ready = True
        _clan_tag_index_failed = False
        return True
    except DuplicateKeyError:
        _clan_tag_index_failed = True
        _clan_tag_index_retry_at = time.monotonic() + CLAN_TAG_INDEX_RETRY_SECONDS
        _log.error("duplicate clan tags exist; run tools/find_duplicate_clans.py")
        return False
    except Exception as exc:  # noqa: BLE001 - index setup must not take the bot down
        _clan_tag_index_failed = True
        _clan_tag_index_retry_at = time.monotonic() + CLAN_TAG_INDEX_RETRY_SECONDS
        _log.error(
            "clans.tag unique index unavailable: %s: %s", type(exc).__name__, exc
        )
        return False
