# BAND FWA sync-time monitor.
#
# Polls the three BAND iCal subscription feeds for FWA sync events and DMs a configured
# list of Discord users when a sync is scheduled, when it is approaching, and when its
# time changes. This exists because sync times are posted as BAND *calendar events*, not
# as text in the post body, so the existing post-text monitor in band_monitor.py cannot
# see the actual timestamp. Nothing here touches that monitor - it shares no state, no
# schedule and no collection with it.
#
# SHIPS DISABLED. The config doc is seeded with enabled=False on first run, only if the
# doc does not already exist. Turn it on from /manage → FWA → Sync & Reminders once the
# feeds check out.
#
# Feed URLs are CREDENTIALS - they grant unauthenticated read access to the calendar.
# They are read from the environment only, never committed, and never copied into Mongo.

import asyncio
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp
import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
from extensions.tasks import band_sync_panel as panel
from extensions.tasks import band_sync_schema as schema
from utils.band_ical_parser import (
    DISCOVERY_OFFSET,
    BandIcalParseError,
    detect_reschedule,
    discord_timestamp,
    drop_past,
    due_offsets,
    merge_feeds,
    normalize_start,
    parse_sync_events,
)

loader = lightbulb.Loader()

# ---- Config (all tunable here) ----
HTTP_TIMEOUT_SECONDS = 15
POLL_SECONDS_FLOOR = 300         # BAND publishes X-PUBLISHED-TTL:PT5M - never poll faster
DEFAULT_POLL_SECONDS = 300
DEFAULT_SUMMARY_FILTER = "sync"
DEFAULT_STALE_HOURS = 26         # no upcoming sync for this long -> shout about it
STALE_LOG_THROTTLE_SECONDS = 3600
DELIVERY_LEASE_SECONDS = 10 * 60
DELIVERY_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=3),
)
DELIVERY_MAX_FAILURES = 6
DELIVERY_MAX_AGE = timedelta(hours=24)
PERMANENT_DM_ERRORS = (
    hikari.BadRequestError,
    hikari.UnauthorizedError,
    hikari.ForbiddenError,
    hikari.NotFoundError,
)

# Order matters: the first feed carrying a UID decides which calendar name is shown.
FEED_ENV_VARS = {
    "Sync": "BAND_ICAL_SYNC1",
    "Sync2": "BAND_ICAL_SYNC2",
    "Sync3": "BAND_ICAL_SYNC3",
}

# Per-calendar accent colours, from the BAND calendar settings.
CALENDAR_COLORS = {
    "Sync": 0xFF703D,
    "Sync2": 0xF630A4,
    "Sync3": 0x7F51F9,
}
FALLBACK_COLOR = 0x5865F2

LEGACY_COLLECTION_NAME = "fwa_sync_alerts"  # pre-panel single collection; read-once, never written
CONFIG_ID = schema.CONFIG_ID

# ---- Module state ----
bot_instance = None
mongo_client = None
poller_task = None
startup_reconciler = None
_last_enabled_state = None       # for logging the flag only when it actually changes
_last_seen_upcoming_at = None
_last_stale_log_at = None


# ---- Collection access ----
def _legacy_alerts(mongo):
    """The pre-panel single collection, kept only as a one-time migration source.

    Everything else now reaches Mongo through the four declared attributes on
    MongoClient (fwa_sync_config/events/responses/deliveries, see utils/mongo.py). This
    ad hoc lookup is the one exception, and it is deliberately narrow: it is called only
    by _migrate_legacy_config() below, never written to, and never deleted.
    """
    return mongo.get_database("settings").get_collection(LEGACY_COLLECTION_NAME)


# ---- Config ----
def _seed_from_env():
    """Initial config values, read from env ONCE to seed the Mongo doc on first run.

    After seeding, Mongo is authoritative and these are ignored - editing .env will not
    change a running bot. Use /manage → FWA → Sync & Reminders.
    """
    offsets = []
    for chunk in os.getenv("SYNC_DM_OFFSETS", "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            offsets.append(int(chunk))

    return schema.new_config_doc(
        # Always seeded off. Check the feeds in Sync & Reminders, then select Enable.
        enabled=False,
        offsets=offsets or list(schema.DEFAULT_OFFSETS),
        announce_on_discovery=os.getenv("SYNC_DM_ANNOUNCE_ON_DISCOVERY", "true").lower() == "true",
        summary_filter=os.getenv("SYNC_DM_SUMMARY_FILTER", DEFAULT_SUMMARY_FILTER),
        poll_seconds=DEFAULT_POLL_SECONDS,
        stale_hours=DEFAULT_STALE_HOURS,
    )


async def load_config(mongo):
    doc = await mongo.fwa_sync_config.find_one({"_id": CONFIG_ID})
    config = schema.normalize_config(doc) if doc else schema.normalize_config(_seed_from_env())
    # Floor enforced on read, so a bad Mongo edit cannot make us hammer BAND.
    config["poll_seconds"] = max(POLL_SECONDS_FLOOR, int(config.get("poll_seconds", DEFAULT_POLL_SECONDS)))
    config["stale_hours"] = int(config.get("stale_hours", DEFAULT_STALE_HOURS))
    return config


def feed_urls():
    """{label: url} for feeds that actually have a value set.

    Read lazily so a missing env var can never stop the bot booting. BAND hands out
    webcal:// URLs; HTTP clients need https://.
    """
    urls = {}
    for label, var in FEED_ENV_VARS.items():
        raw = (os.getenv(var) or "").strip()
        if not raw:
            continue
        if raw.startswith("webcal://"):
            raw = "https://" + raw[len("webcal://"):]
        urls[label] = raw
    return urls


# ---- Feed fetching ----
async def fetch_feed(session, label, url):
    """Return the raw feed body, or None. One dead feed must not kill the run."""
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                # 404/410 is plausible here: the UID references an upstream calendar that
                # can move independently of our band, so the token can stop resolving.
                print(f"[FWA Sync ICS] {label}: HTTP {resp.status} from feed")
                return None
            return await resp.read()
    except asyncio.TimeoutError:
        print(f"[FWA Sync ICS] {label}: feed timeout after {HTTP_TIMEOUT_SECONDS}s")
        return None
    except aiohttp.ClientError as e:
        print(f"[FWA Sync ICS] {label}: feed error {type(e).__name__}: {e}")
        return None
    except Exception as e:
        print(f"[FWA Sync ICS] {label}: unexpected fetch error {type(e).__name__}: {e}")
        return None


async def collect_events(summary_filter):
    """Fetch every configured feed and return (merged_future_events, errors)."""
    urls = feed_urls()
    if not urls:
        return [], ["no feed URLs configured (BAND_ICAL_SYNC1/2/3 unset)"]

    errors = []
    per_feed = []
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for label, url in urls.items():
            body = await fetch_feed(session, label, url)
            if body is None:
                errors.append(f"{label}: fetch failed")
                continue
            try:
                per_feed.append(parse_sync_events(body, label, summary_filter))
            except BandIcalParseError as e:
                errors.append(str(e))
                print(f"[FWA Sync ICS] {e}")

    merged = drop_past(merge_feeds(*per_feed), datetime.now(timezone.utc))
    return merged, errors


# ---- Embeds ----
def _base_embed(event, color):
    # normalize_start(): event["start"] may come back naive from a Mongo round trip
    # (band_sync_panel._start_of has the same requirement, refuter-03 must-fix 2) -
    # Embed(timestamp=...) raises HikariWarning on a naive datetime.
    start = normalize_start(event["start"])
    embed = hikari.Embed(
        description=event["summary"] or "FWA Sync",
        color=color,
        timestamp=start,
    )
    embed.add_field(
        name="Sync Time",
        value=f"{discord_timestamp(start, 'F')}\n{discord_timestamp(start, 'R')}",
        inline=False,
    )
    embed.set_footer(text=f"BAND calendar: {event['calendar']}")
    return embed


def build_embed(event, offset_label):
    """The alert embed. Plain hikari.Embed - no components, no buttons, by design."""
    color = CALENDAR_COLORS.get(event["calendar"], FALLBACK_COLOR)
    if offset_label == DISCOVERY_OFFSET:
        title = "🗓️ New FWA Sync Scheduled"
        lead = "A new sync has been posted. Get your FWA wars ready to spin."
    else:
        title = f"⚔️ FWA Sync in ~{offset_label} minutes"
        lead = "**Spin the FWA wars.** Sync is coming up."

    embed = _base_embed(event, color)
    embed.title = title
    embed.description = f"{lead}\n\n**{event['summary'] or 'FWA Sync'}**"
    if event.get("end"):
        embed.add_field(name="Window Ends", value=discord_timestamp(event["end"], "t"), inline=True)
    return embed


# ---- DM delivery ----
async def dm_all(user_ids, embed):
    """DM every recipient. Returns how many succeeded.

    A user with DMs closed is logged and skipped - never allowed to block delivery to
    the others or to raise out of the poll.
    """
    if not bot_instance:
        print("[FWA Sync ICS] No bot instance; cannot DM")
        return 0
    if not user_ids:
        print("[FWA Sync ICS] No DM recipients configured; alert not delivered")
        return 0

    sent = 0
    for user_id in ordered_user_ids(user_ids):
        if await dm_one(user_id, embed):
            sent += 1
    return sent


def ordered_user_ids(user_ids):
    """Return valid recipient IDs once each, preserving configured order."""
    seen = set()
    result = []
    for raw_id in user_ids or ():
        try:
            user_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user_id)
    return result


@dataclass(frozen=True)
class _DmResult:
    sent: bool
    permanent: bool = False
    error_type: str = ""
    detail: str = ""


def _error_detail(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


async def _try_dm(user_id, embed) -> _DmResult:
    """Deliver one DM while preserving whether a failure is retryable."""
    if not bot_instance:
        return _DmResult(False, error_type="BotUnavailable",
                         detail="bot instance unavailable")
    try:
        user = await bot_instance.rest.fetch_user(user_id)
        channel = await bot_instance.rest.create_dm_channel(user.id)
        await bot_instance.rest.create_message(channel=channel, embed=embed)
        return _DmResult(True)
    except Exception as e:
        return _DmResult(
            False,
            permanent=isinstance(e, PERMANENT_DM_ERRORS),
            error_type=type(e).__name__,
            detail=_error_detail(e),
        )


async def dm_one(user_id, embed):
    """Deliver one DM and report success without raising into the poller."""
    result = await _try_dm(user_id, embed)
    if not result.sent:
        print(f"[FWA Sync ICS] DM to {user_id} failed "
              f"({result.error_type}: {result.detail})")
    return result.sent


# ---- Durable event and delivery state ----
def _event_state_id(uid):
    return f"event:{uid}"


def _event_version(event):
    return schema.event_version(event)


def _delivery_id(event, offset, user_id):
    return schema.delivery_id(event, offset, user_id)


def _event_state_doc(event, closed_offsets=None):
    return schema.new_event_doc(event, closed_offsets=closed_offsets,
                                now=datetime.now(timezone.utc))


def _delivery_doc(event, offset, user_id, delivery_type="reminder", old_start=None):
    return schema.new_delivery_doc(event, offset, user_id, delivery_type, old_start,
                                   now=datetime.now(timezone.utc))


async def get_or_create_event_state(coll, event):
    """Return (state, first_seen). coll is mongo.fwa_sync_events.

    The old pre-lease-schema migration this used to do (_legacy_state) translated claim
    documents that lived in the SAME collection as event_state rows. That collection was
    fwa_sync_alerts, which this function no longer reads at all - fwa_sync_events starts
    empty, so there is nothing to translate here. See DECISIONS.md D005.
    """
    state_id = _event_state_id(event["uid"])
    state = await coll.find_one({"_id": state_id})
    if state:
        return schema.normalize_event(state), False

    state = _event_state_doc(event)
    try:
        await coll.insert_one(state)
        return state, True
    except DuplicateKeyError:
        return schema.normalize_event(await coll.find_one({"_id": state_id})), False


async def enqueue_deliveries(coll, event, offset, user_ids, delivery_type="reminder",
                             old_start=None):
    """Create the durable recipient work items before closing an offset. coll is
    mongo.fwa_sync_deliveries."""
    for user_id in ordered_user_ids(user_ids):
        try:
            await coll.insert_one(
                _delivery_doc(event, offset, user_id, delivery_type, old_start)
            )
        except DuplicateKeyError:
            pass


def _offset_key(offset):
    """A numeric offset label ("60") is stored as int in a response's reminders list;
    "new" and "change:..." labels never appear there. This is the one place the two
    representations are reconciled."""
    text = str(offset)
    return int(text) if text.lstrip("-").isdigit() else offset


async def _responses_for_uid(mongo, uid, status=None):
    query = {"uid": uid}
    if status:
        # A set/tuple means "any of these" (D007: reminders for Yes OR Maybe).
        query["status"] = {"$in": sorted(status)} if isinstance(status, (set, tuple, frozenset)) else status
    projection = {"user_id": 1, "status": 1, "reminders": 1, "event_version": 1,
                  "dm_channel_id": 1, "dm_message_id": 1}
    results = []
    async for doc in mongo.fwa_sync_responses.find(query, projection).limit(500):
        results.append(schema.normalize_response(doc))
    return results


async def claim_delivery(coll, delivery, now=None):
    """Lease due queued/failed work or reclaim a crashed pending worker."""
    now = now or datetime.now(timezone.utc)
    result = await coll.update_one(
        {
            "_id": delivery["_id"],
            "$or": [
                {"status": "queued"},
                {"status": "failed", "next_attempt_at": {"$exists": False}},
                {"status": "failed", "next_attempt_at": {"$lte": now}},
                {"status": "pending", "lease_until": {"$lte": now}},
            ],
        },
        {"$set": {
            "status": "pending",
            "claimed_at": now,
            "lease_until": now + timedelta(seconds=DELIVERY_LEASE_SECONDS),
        }},
    )
    return bool(result.modified_count)


def _retry_delay(failure_count: int) -> timedelta:
    index = min(max(failure_count - 1, 0), len(DELIVERY_RETRY_DELAYS) - 1)
    return DELIVERY_RETRY_DELAYS[index]


def _event_from_delivery(delivery):
    return {
        "uid": delivery["uid"],
        "calendar": delivery["calendar"],
        "summary": delivery.get("summary") or "",
        "start": normalize_start(delivery.get("start_at")),
        "end": normalize_start(delivery.get("end_at")),
    }


_DELIVERY_PROJECTION = {f: 1 for f in (
    "uid", "event_version", "offset", "recipient_id", "delivery_type", "calendar",
    "summary", "start_at", "end_at", "old_start_at", "status", "failure_count",
    "first_failed_at", "lease_until",
)}


async def deliver_outstanding(mongo, event, now=None):
    """Attempt only unsent recipients for the current version of an event.

    A recipient with an fwa_sync_responses row (opted in through the panel) gets the
    full interactive DM via band_sync_panel.send_dm, which also replaces their
    previous DM for this event (D001 in DECISIONS.md). Eligibility is checked
    again before delivery: old fixed-recipient work and withdrawn reminders
    are abandoned without sending a message.
    """
    coll = mongo.fwa_sync_deliveries
    now = normalize_start(now) or datetime.now(timezone.utc)
    query = {
        "uid": event["uid"],
        "event_version": _event_version(event),
        "status": {"$in": ["queued", "failed", "pending"]},
    }
    config = None
    async for delivery in coll.find(query, _DELIVERY_PROJECTION).limit(200):
        if not await claim_delivery(coll, delivery, now):
            continue

        delivery_event = _event_from_delivery(delivery)
        user_id = delivery["recipient_id"]
        response = await mongo.fwa_sync_responses.find_one(
            {"_id": schema.response_id(event["uid"], user_id)},
            {"user_id": 1, "status": 1, "reminders": 1, "dm_channel_id": 1, "dm_message_id": 1},
        )
        eligible = (
            response is not None
            and response.get("status") in schema.REMINDER_STATUSES
            and _offset_key(delivery["offset"]) in (response.get("reminders") or ())
        )
        if eligible:
            if config is None:
                config = await load_config(mongo)
            response = schema.normalize_response(response)
            # Discovery is also stored with delivery_type="reminder". Only numeric
            # offsets are scheduled countdown DMs; discovery keeps its current UI.
            render_type = delivery.get("delivery_type")
            if render_type == "reminder" and str(delivery["offset"]).isdigit():
                render_type = "timed_reminder"
            panel_result = await panel.send_dm(
                mongo, bot_instance, delivery_event, response,
                panel.band_url(delivery_event, config),
                render_type,
            )
            result = _DmResult(panel_result.sent, panel_result.permanent,
                               panel_result.error_type, panel_result.detail)
        else:
            # Retired fixed-recipient broadcasts must never send a plain embed.
            # A queued row without a live opt-in response is terminally ineligible.
            await coll.update_one(
                {"_id": delivery["_id"], "status": "pending"},
                {"$set": {"status": "abandoned", "terminal_reason": "opt_in_removed",
                          "status_updated_at": now, "abandoned_at": now},
                 "$unset": {"lease_until": "", "next_attempt_at": ""}},
            )
            continue

        if result.sent:
            await coll.update_one(
                {"_id": delivery["_id"], "status": "pending"},
                {
                    "$set": {
                        "status": "sent",
                        "announced_at": now,
                        "status_updated_at": now,
                    },
                    "$unset": {
                        "lease_until": "",
                        "next_attempt_at": "",
                        "last_error_type": "",
                        "last_error_detail": "",
                    },
                },
            )
            print(f"[FWA Sync ICS] Sent {delivery['offset']} alert for "
                  f"{event['calendar']} {event['start'].isoformat()} to {user_id}")
        else:
            failure_count = int(delivery.get("failure_count") or 0) + 1
            first_failed_at = normalize_start(delivery.get("first_failed_at")) or now
            age_exhausted = now - first_failed_at >= DELIVERY_MAX_AGE
            terminal_reason = None
            if result.permanent:
                terminal_reason = "permanent_discord_error"
            elif failure_count >= DELIVERY_MAX_FAILURES:
                terminal_reason = "failure_limit"
            elif age_exhausted:
                terminal_reason = "age_limit"

            failure_fields = {
                "failure_count": failure_count,
                "first_failed_at": first_failed_at,
                "last_failed_at": now,
                "status_updated_at": now,
                "last_error_type": result.error_type,
                "last_error_detail": result.detail,
            }
            if terminal_reason:
                failure_fields.update({
                    "status": "abandoned",
                    "terminal_reason": terminal_reason,
                    "abandoned_at": now,
                })
                update = {
                    "$set": failure_fields,
                    "$unset": {"lease_until": "", "next_attempt_at": ""},
                }
            else:
                delay = _retry_delay(failure_count)
                failure_fields.update({
                    "status": "failed",
                    "next_attempt_at": now + delay,
                })
                update = {
                    "$set": failure_fields,
                    "$unset": {"lease_until": ""},
                }
            await coll.update_one(
                {"_id": delivery["_id"], "status": "pending"},
                update,
            )
            if terminal_reason:
                print(f"[FWA Sync ICS] ALERT delivery_abandoned uid={event['uid']} "
                      f"offset={delivery['offset']} recipient={user_id} "
                      f"failures={failure_count} reason={terminal_reason} "
                      f"error={result.error_type} detail={result.detail}")
            else:
                print(f"[FWA Sync ICS] delivery_retry_scheduled uid={event['uid']} "
                      f"offset={delivery['offset']} recipient={user_id} "
                      f"failures={failure_count} retry_at="
                      f"{failure_fields['next_attempt_at'].isoformat()} "
                      f"error={result.error_type} detail={result.detail}")


async def _ensure_one_index(factory, label):
    """One try per index, so one bad index never skips the rest (rule 4)."""
    try:
        await factory()
    except Exception as e:
        print(f"[FWA Sync ICS] WARNING: could not create {label} index "
              f"({type(e).__name__}: {e}). Non-fatal; that self-prune/lookup is lost.")


async def ensure_indexes(mongo):
    """Create the named, idempotent indexes for the four fwa_sync_* collections. Loud on
    failure, never fatal - dedupe rides on the unique _id and works without any of these;
    only the TTL self-prune and the (uid) lookups are lost.
    """
    await _ensure_one_index(
        lambda: mongo.fwa_sync_events.create_index(
            "expire_at", expireAfterSeconds=0, name="ttl_fwa_sync_events_expire_at"),
        "fwa_sync_events TTL",
    )
    await _ensure_one_index(
        lambda: mongo.fwa_sync_responses.create_index(
            "expire_at", expireAfterSeconds=0, name="ttl_fwa_sync_responses_expire_at"),
        "fwa_sync_responses TTL",
    )
    await _ensure_one_index(
        lambda: mongo.fwa_sync_deliveries.create_index(
            "expire_at", expireAfterSeconds=0, name="ttl_fwa_sync_deliveries_expire_at"),
        "fwa_sync_deliveries TTL",
    )
    await _ensure_one_index(
        lambda: mongo.fwa_sync_deliveries.create_index(
            [("uid", 1), ("status", 1)], name="idx_fwa_sync_deliveries_uid_status"),
        "fwa_sync_deliveries (uid, status)",
    )
    await _ensure_one_index(
        lambda: mongo.fwa_sync_responses.create_index(
            "uid", name="idx_fwa_sync_responses_uid"),
        "fwa_sync_responses (uid)",
    )


async def _migrate_legacy_config(mongo):
    """One-time copy from the old fwa_sync_alerts config doc, if one still exists.

    Returns True if a fwa_sync_config doc now exists because of this call (so the caller
    does not also seed from env). The old collection is never deleted or written to.
    """
    legacy = await _legacy_alerts(mongo).find_one({"_id": CONFIG_ID}, {
        "enabled": 1, "offsets": 1, "announce_on_discovery": 1,
    })
    if not legacy:
        return False
    doc = schema.new_config_doc(
        enabled=bool(legacy.get("enabled", False)),
        offsets=list(legacy.get("offsets") or schema.DEFAULT_OFFSETS),
        announce_on_discovery=bool(legacy.get("announce_on_discovery", True)),
    )
    try:
        await mongo.fwa_sync_config.insert_one(doc)
    except DuplicateKeyError:
        return True  # lost the race with another seed/migration; a config doc exists
    print("[FWA Sync ICS] Migrated legacy config from fwa_sync_alerts (opt-in reminders only)")
    return True


# ---- The poll ----
async def handle_reschedule(mongo, event, existing):
    """A BAND time change is handled like a new sync (DECISIONS.md D009): the uid stays
    the same, but every response and delivery for it is wiped, any DM still tracked on
    a response is deleted, and the panel is dropped so process_event posts a fresh one
    with the role ping. No change-alert DM is ever sent.

    Write ordering is crash-safe: responses/deliveries (and their DMs) are cleared
    BEFORE start_at/event_version move. delete_many is idempotent, so a crash before
    the state update just repeats the same clearing on the next poll (detect_reschedule
    still finds the move, since start_at has not changed yet) instead of leaving stale
    answers pinned against the new time.
    """
    old_start = normalize_start(existing.get("start_at"))
    uid = event["uid"]

    async for response in mongo.fwa_sync_responses.find(
        {"uid": uid}, {"dm_channel_id": 1, "dm_message_id": 1}
    ).limit(500):
        channel_id = response.get("dm_channel_id")
        message_id = response.get("dm_message_id")
        if channel_id and message_id and bot_instance:
            try:
                await bot_instance.rest.delete_message(channel_id, message_id)
            except hikari.NotFoundError:
                pass  # already gone - not an error
            except Exception as e:
                print(f"[FWA Sync ICS] reschedule: could not delete DM uid={uid} "
                      f"channel={channel_id} message={message_id}: {type(e).__name__}: {e}")

    await mongo.fwa_sync_responses.delete_many({"uid": uid})
    await mongo.fwa_sync_deliveries.delete_many({"uid": uid})

    coll = mongo.fwa_sync_events
    await coll.update_one(
        {"_id": _event_state_id(uid)},
        {"$set": {
            "calendar": event["calendar"],
            "summary": event["summary"],
            "start_at": event["start"],
            "event_version": _event_version(event),
            # Like a new sync: "new" stays closed (no second discovery alert), the
            # panel is dropped so process_event's "post when unset" branch below posts
            # a fresh one, and every numeric offset re-arms against the new start_at.
            "closed_offsets": [DISCOVERY_OFFSET],
            "scheduled_offsets": [],
            "panel_message_id": None,
            "panel_version": None,
            "updated_at": datetime.now(timezone.utc),
            "expire_at": event["start"] + timedelta(days=schema.EVENT_TTL_DAYS),
        }},
    )
    print(f"[FWA Sync ICS] RESCHEDULE {event['calendar']} {uid}: "
          f"{old_start} -> {event['start']} (responses/deliveries cleared, panel reposts)")
    return True


async def process_event(mongo, event, config, now):
    events_coll = mongo.fwa_sync_events
    deliveries_coll = mongo.fwa_sync_deliveries
    existing, first_seen = await get_or_create_event_state(events_coll, event)
    forced_first_seen = None

    if existing and detect_reschedule(existing.get("start_at"), event["start"]):
        await handle_reschedule(mongo, event, existing)
        # State was just rebuilt against the new time (D009: handled like a new sync);
        # treat elapsed offsets as missed rather than firing them immediately.
        forced_first_seen = True
        existing = await events_coll.find_one({"_id": _event_state_id(event["uid"])})

    if not existing.get("panel_message_id"):
        # Retries every poll until a panel channel is configured or the post
        # succeeds - cheap (one query) and self-healing after a transient failure.
        await panel.post_or_replace_panel(mongo, bot_instance, schema.normalize_event(existing))
        refreshed = await events_coll.find_one({"_id": _event_state_id(event["uid"])})
        if refreshed:
            existing = refreshed
    elif existing.get("panel_version") != existing.get("event_version"):
        # The panel already exists but was last rendered against an older
        # event_version - a reschedule's new start_at, or a previous refresh that
        # raised or was interrupted by a restart before this field could be updated.
        # Comparing the two stored fields (rather than relying on detect_reschedule
        # firing again) means a failed or interrupted refresh simply retries on the
        # next poll instead of leaving the panel on the old time forever
        # (refuter-06 must-fix; D003/D013: current_panel is untouched, this is the
        # same message).
        normalized = schema.normalize_event(existing)
        all_responses = await panel.load_responses(mongo, event["uid"])
        await panel.refresh_panel_message(
            mongo, bot_instance, normalized, all_responses,
            panel.band_url(normalized, config),
        )
        refreshed = await events_coll.find_one({"_id": _event_state_id(event["uid"])})
        if refreshed:
            existing = refreshed

    claimed = set(existing.get("closed_offsets") or ())
    responses = await _responses_for_uid(mongo, event["uid"], status=schema.REMINDER_STATUSES)
    # Honor every supported member choice even when an older server config
    # omitted it (notably "at sync time", added after the original broadcast).
    offsets = set(config["offsets"])
    offsets.update(
        offset for response in responses for offset in response.get("reminders", ())
        if offset in schema.DEFAULT_OFFSETS
    )

    to_send, to_retire = due_offsets(
        event["start"], now, claimed, offsets,
        announce_on_discovery=config["announce_on_discovery"],
        first_seen=forced_first_seen if forced_first_seen is not None else first_seen,
    )

    # Work items must exist before the event-level offset closes. That ordering makes
    # the operation crash-safe: duplicate inserts are harmless, absent work is not.
    # Recipients are exclusively members who opted in and chose this reminder.
    # See band_sync_schema.recipients_for_offset.
    recipients_by_offset = {
        offset: schema.recipients_for_offset(config, responses, _offset_key(offset))
        for offset in to_send
    }
    deliverable = [offset for offset in to_send if recipients_by_offset[offset]]
    starved = [offset for offset in to_send if not recipients_by_offset[offset]]
    # "new" (discovery) is a one-shot announcement, not a per-user reminder: with nobody
    # to tell it is retired silently so it does not log the same warning every poll
    # forever. Numeric offsets stay open on zero recipients so a late opt-in still gets
    # a later reminder - only "new" is retired here.
    starved_new = [offset for offset in starved if offset == DISCOVERY_OFFSET]
    starved_numeric = [offset for offset in starved if offset != DISCOVERY_OFFSET]
    if starved_numeric:
        print(f"[FWA Sync ICS] WARNING: alert(s) {starved_numeric} for {event['uid']} have no "
              "recipients; offsets left open so they can retry")
    for offset in deliverable:
        await enqueue_deliveries(deliveries_coll, event, offset, recipients_by_offset[offset])

    closed = list(dict.fromkeys([*deliverable, *to_retire, *starved_new]))
    update = {"$set": {"updated_at": datetime.now(timezone.utc)}}
    if closed:
        update["$addToSet"] = {"closed_offsets": {"$each": closed}}
    if deliverable:
        update.setdefault("$addToSet", {})["scheduled_offsets"] = {"$each": deliverable}
    await events_coll.update_one({"_id": _event_state_id(event["uid"])}, update)

    for offset in to_retire:
        status = "seen" if offset == DISCOVERY_OFFSET else "skipped_late"
        print(f"[FWA Sync ICS] {event['calendar']} {event['uid']}: "
              f"offset {offset} recorded as {status} (window already passed)")

    await deliver_outstanding(mongo, event, now)


def _check_staleness(events, stale_hours):
    """Shout if no upcoming sync has been visible for too long.

    A missed sync window is worse than a noisy log, so silence here is never assumed to
    be good news.
    """
    global _last_seen_upcoming_at, _last_stale_log_at
    now = datetime.now(timezone.utc)
    if events:
        _last_seen_upcoming_at = now
        return
    if _last_seen_upcoming_at is None:
        _last_seen_upcoming_at = now
        return
    idle = now - _last_seen_upcoming_at
    if idle < timedelta(hours=stale_hours):
        return
    if _last_stale_log_at and (now - _last_stale_log_at) < timedelta(seconds=STALE_LOG_THROTTLE_SECONDS):
        return
    _last_stale_log_at = now
    print(f"[FWA Sync ICS] WARNING: no upcoming sync event seen for "
          f"{idle.total_seconds() / 3600:.1f}h across all feeds. Feed tokens may have "
          f"expired or the calendar may have moved.")


async def poll_once(mongo):
    """One full cycle. Returns the interval to sleep before the next one."""
    global _last_enabled_state

    config = await load_config(mongo)
    interval = config["poll_seconds"]

    if config["enabled"] != _last_enabled_state:
        print(f"[FWA Sync ICS] Feature {'ENABLED' if config['enabled'] else 'DISABLED'}")
        _last_enabled_state = config["enabled"]
    if not config["enabled"]:
        return interval

    events, errors = await collect_events(config["summary_filter"])
    configured_feeds = len(feed_urls())
    if errors and (configured_feeds == 0 or len(errors) >= configured_feeds):
        print(f"[FWA Sync ICS] WARNING: no feed produced usable data this cycle: {errors}")
    elif errors:
        print(f"[FWA Sync ICS] Partial feed failure (others still read): {errors}")

    _check_staleness(events, config["stale_hours"])

    now = datetime.now(timezone.utc)
    for event in events:
        try:
            await process_event(mongo, event, config, now)
        except Exception as e:
            # One bad event must not stop the others.
            print(f"[FWA Sync ICS] Error processing {event.get('uid')}: {type(e).__name__}: {e}")

    try:
        await purge_finished_events(mongo, now)
    except Exception as e:
        # Purge failing must never stop the next poll; TTL is the backstop anyway.
        print(f"[FWA Sync ICS] Purge error: {type(e).__name__}: {e}")

    try:
        await sweep_dm_deletions(mongo, now)
    except Exception as e:
        # Same isolation as purge above: the in-process timer is the fast path anyway.
        print(f"[FWA Sync ICS] DM sweep error: {type(e).__name__}: {e}")
    return interval


async def sweep_dm_deletions(mongo, now):
    """Restart backstop for DECISIONS.md D006: delete any DM whose dm_delete_at has
    passed. band_sync_panel._schedule_dm_delete's in-process timer is the fast path for
    this; a bot restart drops every pending asyncio task with it, so this poll-cycle
    sweep is what actually guarantees the 10-minute TTL when the process was down.
    """
    projection = {"dm_channel_id": 1, "dm_message_id": 1, "dm_delete_at": 1}
    query = {"dm_message_id": {"$exists": True}, "dm_delete_at": {"$lte": now}}
    async for response in mongo.fwa_sync_responses.find(query, projection).limit(200):
        channel_id = response.get("dm_channel_id")
        message_id = response.get("dm_message_id")
        if channel_id and message_id and bot_instance:
            try:
                await bot_instance.rest.delete_message(channel_id, message_id)
            except hikari.NotFoundError:
                pass  # already gone - not an error
            except Exception as e:
                # Transient failure: leave the tracking fields so this response is
                # picked up again on the next poll instead of being orphaned
                # (refuter-03 noted).
                print(f"[FWA Sync ICS] dm sweep: could not delete DM id={response['_id']} "
                      f"channel={channel_id} message={message_id}: {type(e).__name__}: {e}")
                continue
        # Status and reminders stay - only the DM tracking fields go.
        await mongo.fwa_sync_responses.update_one(
            {"_id": response["_id"]},
            {"$unset": {"dm_channel_id": "", "dm_message_id": "", "dm_delete_at": ""}},
        )


async def purge_finished_events(mongo, now):
    """Delete per-event data once the sync is over. Panel message is NOT deleted here
    (D003 in DECISIONS.md) - only the poller's next discovery replaces it.
    """
    async for event in mongo.fwa_sync_events.find({}, {"uid": 1, "start_at": 1}).limit(200):
        start = normalize_start(event.get("start_at"))
        if start is None or start + timedelta(hours=1) >= now:
            continue
        uid = event["uid"]

        async for response in mongo.fwa_sync_responses.find(
            {"uid": uid}, {"dm_channel_id": 1, "dm_message_id": 1}
        ).limit(500):
            channel_id = response.get("dm_channel_id")
            message_id = response.get("dm_message_id")
            if not (channel_id and message_id and bot_instance):
                continue
            try:
                await bot_instance.rest.delete_message(channel_id, message_id)
            except hikari.NotFoundError:
                pass  # already gone - not an error
            except Exception as e:
                print(f"[FWA Sync ICS] purge: could not delete DM uid={uid} "
                      f"channel={channel_id} message={message_id}: {type(e).__name__}: {e}")

        await mongo.fwa_sync_responses.delete_many({"uid": uid})
        await mongo.fwa_sync_deliveries.delete_many({"uid": uid})
        await mongo.fwa_sync_events.delete_one({"_id": event["_id"]})
        print(f"[FWA Sync ICS] purge: removed per-event data for uid={uid}")


async def poller_loop(mongo):
    print("[FWA Sync ICS] Poller started")
    while True:
        interval = DEFAULT_POLL_SECONDS
        try:
            # Total failure isolation: nothing in here may propagate and nothing may
            # affect band_monitor.py, which runs its own independent task.
            interval = await poll_once(mongo)
        except Exception as e:
            print(f"[FWA Sync ICS] Poll error: {type(e).__name__}: {e}")
            print(traceback.format_exc())
        await asyncio.sleep(max(POLL_SECONDS_FLOOR, interval))


# ---- Lifecycle ----
async def _reconcile_ical_startup() -> None:
    """Ensure durable setup exists, then start exactly one protected poller."""
    global poller_task

    await ensure_indexes(mongo_client)

    existing_config = await mongo_client.fwa_sync_config.find_one({"_id": CONFIG_ID}, {"_id": 1})
    if not existing_config:
        migrated = await _migrate_legacy_config(mongo_client)
        if not migrated:
            await mongo_client.fwa_sync_config.update_one(
                {"_id": CONFIG_ID}, {"$setOnInsert": _seed_from_env()}, upsert=True
            )
            print("[FWA Sync ICS] Seeded config (disabled; enable in Sync & Reminders)")

    configured = ", ".join(feed_urls().keys()) or "NONE"
    print(f"[FWA Sync ICS] Feeds configured: {configured}")

    if poller_task and not poller_task.done():
        return
    poller_task = asyncio.create_task(
        poller_loop(mongo_client), name="fwa-sync-ical"
    )


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global bot_instance, mongo_client, startup_reconciler
    bot_instance = event.app
    mongo_client = mongo

    if startup_reconciler is None:
        startup_reconciler = StartupReconciler(
            "fwa_sync_ical",
            _reconcile_ical_startup,
        )
    startup_reconciler.start()


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global poller_task, startup_reconciler
    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None
    if poller_task and not poller_task.done():
        poller_task.cancel()
        await asyncio.gather(poller_task, return_exceptions=True)
    poller_task = None
    # panel.py owns the DM auto-delete timers (D006) but has no loader/listener of its
    # own to catch StoppingEvent - cancel them here so shutdown never leaves a bare
    # sleeping task behind.
    await panel.cancel_dm_delete_tasks()
    print("[FWA Sync ICS] Poller cancelled")
