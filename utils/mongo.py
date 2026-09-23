import logging
import time

from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

_log = logging.getLogger(__name__)

# Retry at most hourly rather than on every /clan add. A transient startup
# outage must not disable the guard until restart, but repeated failures
# also must not flood the log.
_clan_tag_index_ready = False
_clan_tag_index_failed = False
_clan_tag_index_retry_at = 0.0
CLAN_TAG_INDEX_RETRY_SECONDS = 60 * 60


class MongoClient(AsyncMongoClient):
    def __init__(self, uri: str, **kwargs):
        super().__init__(host=uri, **kwargs)
        self.__settings = self.get_database("settings")
        self.button_store = self.__settings.get_collection("button_store")
        # Fixed-lifetime kwargs for Components V2 interactions. The TTL index is
        # owned by utils.component_state; durable tickets never enter here.
        self.component_state = self.__settings.get_collection("component_state")
        self.clans = self.__settings.get_collection("clan_data")
        #self.clan_recruitment = self.__settings.get_collection("clan_recruitment")
        self.fwa_data = self.__settings.get_collection("fwa_data")
        self.fwa_band_data = self.__settings.get_collection("fwa_band_data")
        self.ticket_setup = self.__settings.get_collection("ticket_setup")
        # Durable ticket records. Historically these lived in button_store next to
        # ephemeral component state; see extensions/commands/tickets/store.py.
        # NO TTL INDEX ON THIS COLLECTION - ticket history is permanent.
        # schema_version is this collection's own counter, owned by
        # extensions/commands/tickets/schema.py:SCHEMA_VERSION (currently 3).
        # It is unrelated to ticket_rollout/ticket_open_slots below, whose
        # schema_version is a separate, independently-versioned literal.
        self.tickets = self.__settings.get_collection("tickets")
        # Durable staff-authored applicant flags used by the ticket console.
        # No TTL: inactive records remain as an audit trail.
        self.ticket_flags = self.__settings.get_collection("ticket_flags")
        # Durable checkpoints for resumable source-channel -> thread cloning.
        # Source Discord content is never stored here; only progress and IDs.
        self.ticket_migrations = self.__settings.get_collection("ticket_migrations")
        # Durable plan/progress state for `/tickets migrate-all`, one document
        # per source guild (`_id="batch:<source_guild_id>"`). Permanent, no TTL:
        # it is the resumable checkpoint for which legacy channel is next.
        # Per-ticket side effects still live in ticket_migrations above.
        self.ticket_migration_batches = self.__settings.get_collection(
            "ticket_migration_batches"
        )
        # Short-lived idempotency leases for cross-system ticket creation.
        # Durable ticket history remains in tickets; handlers.py owns this TTL.
        self.ticket_creation_state = self.__settings.get_collection("ticket_creation_state")
        self.bot_config = self.__settings.get_collection("bot_config")
        # WU-owned Discord polls and named votes. Keep these separate from
        # Arcane's discord_polls rows: each bot can edit only messages it posted.
        # utils.poll_store adds a post-end TTL through the optional purge_at field.
        self.discord_polls = self.__settings.get_collection("wu_discord_polls")
        #self.reddit_monitor = self.__settings.get_collection("reddit_monitor")
        #self.reddit_notifications = self.__settings.get_collection("reddit_notifications")
        #self.clan_bidding = self.__settings.get_collection("clan_bidding")
        #self.new_recruits = self.__settings.get_collection("new_recruits")
        self.ticket_automation_state = self.__settings.get_collection("ticket_automation_state")
        # Shared, non-TTL durability for legacy/thread ticket coexistence.
        # ticket_rollout also holds the monotonic counters; neither collection
        # may ever receive a TTL index.
        # ROLLOUT_SCHEMA_VERSION (extensions/commands/ticket_runtime.py) versions
        # the rollout-state document only; the ticket_number_counters document
        # in the same collection carries its own literal schema_version: 1.
        self.ticket_rollout = self.__settings.get_collection("ticket_rollout")
        # schema_version: 1 is a plain literal here (extensions/commands/
        # ticket_runtime.py), not a named constant like tickets' SCHEMA_VERSION
        # or ticket_rollout's ROLLOUT_SCHEMA_VERSION above -- each of these
        # three ticket-adjacent collections versions its own documents
        # independently; the numbers are not comparable across collections.
        self.ticket_open_slots = self.__settings.get_collection("ticket_open_slots")
        self.recruit_onboarding = self.__settings.get_collection("recruit_onboarding")
        # Short-lived message challenges used during recruitment. This stays
        # separate from durable walkthrough records in recruit_onboarding so a
        # TTL index cannot remove role-cleanup history.
        self.recruit_challenges = self.__settings.get_collection("recruit_challenges")
        # Keep legacy snapshots available for the idempotent dashboard migration.
        self.lazy_cwl_snapshots = self.__settings.get_collection("lazy_cwl_snapshots")
        self.lazy_cwl_lists = self.__settings.get_collection("lazy_cwl_lists")
        # CWL reminder scheduling. cwl_reminder holds one singleton "schedule"
        # document (base time, followups, delivery_issues); cwl_pending_reminders
        # holds one row per outstanding job, keyed by job_id. Keep them separate:
        # extensions/tasks/cwl_reminder.py:restore_pending_reminders() does an
        # unfiltered find() over cwl_pending_reminders and would delete the
        # schedule document if the two ever shared a collection.
        self.cwl_reminder = self.__settings.get_collection("cwl_reminder")
        self.cwl_pending_reminders = self.__settings.get_collection("cwl_pending_reminders")
        self.fwa_points = self.__settings.get_collection("fwa_points")
        # Bounded discovery data for /todo. History/candidate rows and watches
        # both carry BSON-date TTL anchors; utils/clan_history.py owns indexes.
        self.player_clan_candidates = self.__settings.get_collection("player_clan_candidates")
        self.player_clan_watches = self.__settings.get_collection("player_clan_watches")
        self.clan_roster_snapshots = self.__settings.get_collection("clan_roster_snapshots")
        # Bounded DM /todo auto-refresh sessions. TTL index on expires_at is
        # created lazily by utils/todo_sessions.py.
        self.todo_sessions = self.__settings.get_collection("todo_sessions")
        # Durable, member-owned Clash of Cards inventories.  One document per
        # player tag; event cards are not exposed by Supercell's public API.
        self.card_inventories = self.__settings.get_collection("card_inventories")
        # Two-party card proposals and their expiring reservations. Completed
        # rows remain as a compact audit trail; no screenshots or tokens live here.
        self.card_trades = self.__settings.get_collection("card_trades")
        # Application emojis this bot uploaded and therefore owns. One row per
        # emoji, keyed "troop:<slug>". A row here is what authorizes replacing
        # an emoji, so emojis added by hand are never touched by the sync.
        self.emoji_registry = self.__settings.get_collection("emoji_registry")
        # Staff-maintained FWA opponent blacklist. Keyed by sanitized tag (no
        # '#'). See utils/fwa_blacklist.py and docs/fwa-blacklist.md.
        self.fwa_blacklist = self.__settings.get_collection("fwa_blacklist")
        # FWA sync panel storage (extensions/tasks/band_sync_ical.py,
        # extensions/tasks/band_sync_schema.py). Four collections replace the old
        # single fwa_sync_alerts mixed-kind collection; that legacy collection is
        # kept, read-once, for the startup config migration only - not declared here.
        # Owner: FWA sync task. Singleton config, permanent (no TTL), _id="config".
        self.fwa_sync_config = self.__settings.get_collection("fwa_sync_config")
        # Owner: FWA sync task. One row per BAND event, TTL(expire_at) 7 days after
        # start, _id="event:{uid}".
        self.fwa_sync_events = self.__settings.get_collection("fwa_sync_events")
        # Owner: FWA sync task. One row per user per event, TTL(expire_at) 7 days
        # after start, _id="{uid}|{user_id}".
        self.fwa_sync_responses = self.__settings.get_collection("fwa_sync_responses")
        # Owner: FWA sync task. One row per queued/sent DM, TTL(expire_at) 7 days
        # after start, _id="delivery:{uid}|{event_version}|{offset}|{user_id}".
        self.fwa_sync_deliveries = self.__settings.get_collection("fwa_sync_deliveries")


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
