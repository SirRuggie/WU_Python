# BAND FWA sync-time monitor.
#
# Polls the three BAND iCal subscription feeds for FWA sync events and DMs a configured
# list of Discord users when a sync is scheduled, when it is approaching, and when its
# time changes. This exists because sync times are posted as BAND *calendar events*, not
# as text in the post body, so the existing post-text monitor in band_monitor.py cannot
# see the actual timestamp. Nothing here touches that monitor - it shares no state, no
# schedule and no collection with it.
#
# SHIPS DISABLED. The config doc is seeded with enabled=False on first run regardless of
# the SYNC_DM_ENABLED seed value being true, only if the doc does not already exist.
# Turn it on from Discord with /fwasync enable once the feeds check out.
#
# Feed URLs are CREDENTIALS - they grant unauthenticated read access to the calendar.
# They are read from the environment only, never committed, and never copied into Mongo.

import asyncio
import os
import traceback
from datetime import datetime, timedelta, timezone

import aiohttp
import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient
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
DEFAULT_OFFSETS = [60, 10]
DEFAULT_SUMMARY_FILTER = "sync"
DEFAULT_STALE_HOURS = 26         # no upcoming sync for this long -> shout about it
STALE_LOG_THROTTLE_SECONDS = 3600
DEDUPE_TTL_DAYS = 30
DELIVERY_LEASE_SECONDS = 10 * 60

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
CHANGE_COLOR = 0xE67E22

COLLECTION_NAME = "fwa_sync_alerts"
CONFIG_ID = "config"

# ---- Module state ----
bot_instance = None
mongo_client = None
poller_task = None
_last_enabled_state = None       # for logging the flag only when it actually changes
_last_seen_upcoming_at = None
_last_stale_log_at = None


# ---- Collection access ----
def _alerts(mongo):
    """The dedupe/config collection.

    Reached through the injected client rather than declared on MongoClient, which is
    how every other collection in this codebase is exposed (see utils/mongo.py). That is
    deliberate: this feature was added without modifying utils/mongo.py at all. If you
    are tidying up later, moving this to a declared attribute is safe - just keep the
    collection name identical or the dedupe state is orphaned.
    """
    return mongo.get_database("settings").get_collection(COLLECTION_NAME)


# ---- Config ----
def _seed_from_env():
    """Initial config values, read from env ONCE to seed the Mongo doc on first run.

    After seeding, Mongo is authoritative and these are ignored - editing .env will not
    change a running bot. Use /fwasync enable|disable|set-recipients|set-offsets.
    """
    raw_ids = os.getenv("SYNC_DM_USER_IDS", "")
    user_ids = []
    for chunk in raw_ids.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            user_ids.append(int(chunk))

    offsets = []
    for chunk in os.getenv("SYNC_DM_OFFSETS", "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            offsets.append(int(chunk))

    return {
        # Always seeded off. Confirm the feeds with /fwasync check, then /fwasync enable.
        "enabled": False,
        "dm_user_ids": user_ids,
        "offsets": offsets or list(DEFAULT_OFFSETS),
        "announce_on_discovery": os.getenv("SYNC_DM_ANNOUNCE_ON_DISCOVERY", "true").lower() == "true",
        "summary_filter": os.getenv("SYNC_DM_SUMMARY_FILTER", DEFAULT_SUMMARY_FILTER),
        "poll_seconds": DEFAULT_POLL_SECONDS,
        "stale_hours": DEFAULT_STALE_HOURS,
    }


async def load_config(mongo):
    doc = await _alerts(mongo).find_one({"_id": CONFIG_ID})
    defaults = _seed_from_env()
    if not doc:
        return defaults
    return {
        "enabled": bool(doc.get("enabled", False)),
        "dm_user_ids": list(doc.get("dm_user_ids") or []),
        "offsets": list(doc.get("offsets") or DEFAULT_OFFSETS),
        "announce_on_discovery": bool(doc.get("announce_on_discovery", True)),
        "summary_filter": doc.get("summary_filter", DEFAULT_SUMMARY_FILTER),
        # Floor enforced on read, so a bad Mongo edit cannot make us hammer BAND.
        "poll_seconds": max(POLL_SECONDS_FLOOR, int(doc.get("poll_seconds", DEFAULT_POLL_SECONDS))),
        "stale_hours": int(doc.get("stale_hours", DEFAULT_STALE_HOURS)),
    }


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
    embed = hikari.Embed(
        description=event["summary"] or "FWA Sync",
        color=color,
        timestamp=event["start"],
    )
    embed.add_field(
        name="Sync Time",
        value=f"{discord_timestamp(event['start'], 'F')}\n{discord_timestamp(event['start'], 'R')}",
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


def build_change_embed(event, old_start):
    embed = _base_embed(event, CHANGE_COLOR)
    embed.title = "⏰ FWA Sync Time CHANGED"
    embed.description = (
        f"The sync has moved. Re-check your war timing.\n\n**{event['summary'] or 'FWA Sync'}**"
    )
    embed.add_field(name="Was", value=discord_timestamp(old_start, "F"), inline=False)
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


async def dm_one(user_id, embed):
    """Deliver one DM and report success without raising into the poller."""
    if not bot_instance:
        print("[FWA Sync ICS] No bot instance; cannot DM")
        return False
    try:
        user = await bot_instance.rest.fetch_user(user_id)
        channel = await bot_instance.rest.create_dm_channel(user.id)
        await bot_instance.rest.create_message(channel=channel, embed=embed)
        return True
    except Exception as e:
        print(f"[FWA Sync ICS] DM to {user_id} failed ({type(e).__name__}: {e})")
        return False


# ---- Durable event and delivery state ----
def _event_state_id(uid):
    return f"event:{uid}"


def _event_version(event):
    return str(int(normalize_start(event["start"]).timestamp()))


def _delivery_id(event, offset, user_id):
    return f"delivery:{event['uid']}|{_event_version(event)}|{offset}|{user_id}"


def _event_state_doc(event, closed_offsets=None):
    return {
        "_id": _event_state_id(event["uid"]),
        "kind": "event_state",
        "uid": event["uid"],
        "calendar": event["calendar"],
        "summary": event["summary"],
        "start_at": event["start"],
        "event_version": _event_version(event),
        "closed_offsets": list(closed_offsets or ()),
        "scheduled_offsets": [],
        "updated_at": datetime.now(timezone.utc),
        "expire_at": event["start"] + timedelta(days=DEDUPE_TTL_DAYS),
    }


def _delivery_doc(event, offset, user_id, delivery_type="alert", old_start=None):
    now = datetime.now(timezone.utc)
    return {
        "_id": _delivery_id(event, offset, user_id),
        "kind": "delivery",
        "uid": event["uid"],
        "event_version": _event_version(event),
        "offset": offset,
        "recipient_id": user_id,
        "delivery_type": delivery_type,
        "calendar": event["calendar"],
        "summary": event["summary"],
        "start_at": event["start"],
        "end_at": event.get("end"),
        "old_start_at": old_start,
        "status": "queued",
        "queued_at": now,
        "expire_at": event["start"] + timedelta(days=DEDUPE_TTL_DAYS),
    }


async def _legacy_state(coll, event):
    """Translate the old global claim documents without replaying their alerts."""
    legacy = []
    async for doc in coll.find({"uid": event["uid"], "kind": {"$exists": False}}):
        legacy.append(doc)
    if not legacy:
        return None

    first = legacy[0]
    state_event = dict(event)
    state_event["start"] = normalize_start(first.get("start_at")) or event["start"]
    closed = [doc.get("offset") for doc in legacy if doc.get("offset") is not None]
    return _event_state_doc(state_event, closed)


async def get_or_create_event_state(coll, event):
    """Return (state, first_seen), preserving claims from the pre-lease schema."""
    state_id = _event_state_id(event["uid"])
    state = await coll.find_one({"_id": state_id})
    if state:
        return state, False

    state = await _legacy_state(coll, event)
    first_seen = state is None
    state = state or _event_state_doc(event)
    try:
        await coll.insert_one(state)
        return state, first_seen
    except DuplicateKeyError:
        return await coll.find_one({"_id": state_id}), False


async def enqueue_deliveries(coll, event, offset, user_ids, delivery_type="alert",
                             old_start=None):
    """Create the durable recipient work items before closing an offset."""
    for user_id in ordered_user_ids(user_ids):
        try:
            await coll.insert_one(
                _delivery_doc(event, offset, user_id, delivery_type, old_start)
            )
        except DuplicateKeyError:
            pass


async def claim_delivery(coll, delivery, now=None):
    """Lease queued/failed work or reclaim a pending item after a crashed worker."""
    now = now or datetime.now(timezone.utc)
    result = await coll.update_one(
        {
            "_id": delivery["_id"],
            "$or": [
                {"status": {"$in": ["queued", "failed"]}},
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


def _event_from_delivery(delivery):
    return {
        "uid": delivery["uid"],
        "calendar": delivery["calendar"],
        "summary": delivery.get("summary") or "",
        "start": normalize_start(delivery.get("start_at")),
        "end": normalize_start(delivery.get("end_at")),
    }


async def deliver_outstanding(coll, event):
    """Attempt only unsent recipients for the current version of an event."""
    query = {
        "kind": "delivery",
        "uid": event["uid"],
        "event_version": _event_version(event),
        "status": {"$ne": "sent"},
    }
    async for delivery in coll.find(query):
        if not await claim_delivery(coll, delivery):
            continue

        delivery_event = _event_from_delivery(delivery)
        if delivery.get("delivery_type") == "change":
            embed = build_change_embed(
                delivery_event, normalize_start(delivery.get("old_start_at"))
            )
        else:
            embed = build_embed(delivery_event, delivery["offset"])

        user_id = delivery["recipient_id"]
        if await dm_one(user_id, embed):
            await coll.update_one(
                {"_id": delivery["_id"], "status": "pending"},
                {"$set": {
                    "status": "sent",
                    "announced_at": datetime.now(timezone.utc),
                    "lease_until": None,
                }},
            )
            print(f"[FWA Sync ICS] Sent {delivery['offset']} alert for "
                  f"{event['calendar']} {event['start'].isoformat()} to {user_id}")
        else:
            await coll.update_one(
                {"_id": delivery["_id"], "status": "pending"},
                {"$set": {
                    "status": "failed",
                    "last_failed_at": datetime.now(timezone.utc),
                    "lease_until": None,
                }},
            )
            print(f"[FWA Sync ICS] WARNING: alert {delivery['offset']} for "
                  f"{event['uid']} did not reach {user_id}; will retry next poll")


async def ensure_indexes(mongo):
    """Create the TTL index. Loud on failure, but never fatal.

    Dedupe rides on the unique _id and works with or without this; only the 30-day
    auto-prune is lost. This is the first index this codebase creates, so a permissions
    gap on the remote Mongo would show up here first.
    """
    try:
        await _alerts(mongo).create_index("expire_at", expireAfterSeconds=0, name="ttl_expire_at")
    except Exception as e:
        print(f"[FWA Sync ICS] WARNING: could not create TTL index ({type(e).__name__}: {e}). "
              f"Dedupe still works; {COLLECTION_NAME} will NOT self-prune.")


# ---- The poll ----
async def handle_reschedule(coll, event, existing, config):
    """Durably queue a moved-sync alert, then re-anchor timing to the new event.

    Returns False when no recipients exist. In that case the old event state is left
    intact so the reschedule is detected and retried on the next poll.
    """
    old_start = normalize_start(existing.get("start_at"))
    change_offset = f"change:{_event_version(event)}"
    recipients = ordered_user_ids(config["dm_user_ids"])
    if not recipients:
        print(f"[FWA Sync ICS] WARNING: reschedule {event['uid']} has no recipients; "
              "event state left unchanged so it can retry")
        return False

    # Queue first. A crash before the state update repeats this insert harmlessly;
    # updating first could lose the change alert permanently.
    await enqueue_deliveries(
        coll, event, change_offset, recipients, "change", old_start
    )
    await coll.update_one(
        {"_id": _event_state_id(event["uid"])},
        {"$set": {
            "calendar": event["calendar"],
            "summary": event["summary"],
            "start_at": event["start"],
            "event_version": _event_version(event),
            # The change alert replaces a second discovery alert. Numeric offsets
            # already elapsed against the new time are retired below.
            "closed_offsets": [DISCOVERY_OFFSET],
            "scheduled_offsets": [change_offset],
            "updated_at": datetime.now(timezone.utc),
            "expire_at": event["start"] + timedelta(days=DEDUPE_TTL_DAYS),
        }},
    )
    print(f"[FWA Sync ICS] RESCHEDULE queued {event['calendar']} {event['uid']}: "
          f"{old_start} -> {event['start']}")
    return True


async def process_event(coll, event, config, now):
    existing, first_seen = await get_or_create_event_state(coll, event)
    forced_first_seen = None

    if existing and detect_reschedule(existing.get("start_at"), event["start"]):
        if not await handle_reschedule(coll, event, existing, config):
            return
        # State was just rebuilt against the new time; treat elapsed offsets as missed
        # rather than firing them behind the change alert.
        forced_first_seen = True
        existing = await coll.find_one({"_id": _event_state_id(event["uid"])})

    claimed = set(existing.get("closed_offsets") or ())

    to_send, to_retire = due_offsets(
        event["start"], now, claimed, config["offsets"],
        announce_on_discovery=config["announce_on_discovery"],
        first_seen=forced_first_seen if forced_first_seen is not None else first_seen,
    )

    # Work items must exist before the event-level offset closes. That ordering makes
    # the operation crash-safe: duplicate inserts are harmless, absent work is not.
    recipients = ordered_user_ids(config["dm_user_ids"])
    deliverable = to_send if recipients else []
    if to_send and not recipients:
        print(f"[FWA Sync ICS] WARNING: alert(s) {to_send} for {event['uid']} have no "
              "recipients; offsets left open so they can retry")
    for offset in deliverable:
        await enqueue_deliveries(coll, event, offset, recipients)

    closed = list(dict.fromkeys([*deliverable, *to_retire]))
    update = {"$set": {"updated_at": datetime.now(timezone.utc)}}
    if closed:
        update["$addToSet"] = {"closed_offsets": {"$each": closed}}
    if deliverable:
        update.setdefault("$addToSet", {})["scheduled_offsets"] = {"$each": deliverable}
    await coll.update_one({"_id": _event_state_id(event["uid"])}, update)

    for offset in to_retire:
        status = "seen" if offset == DISCOVERY_OFFSET else "skipped_late"
        print(f"[FWA Sync ICS] {event['calendar']} {event['uid']}: "
              f"offset {offset} recorded as {status} (window already passed)")

    await deliver_outstanding(coll, event)


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

    coll = _alerts(mongo)
    now = datetime.now(timezone.utc)
    for event in events:
        try:
            await process_event(coll, event, config, now)
        except Exception as e:
            # One bad event must not stop the others.
            print(f"[FWA Sync ICS] Error processing {event.get('uid')}: {type(e).__name__}: {e}")
    return interval


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
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global bot_instance, mongo_client, poller_task
    bot_instance = event.app
    mongo_client = mongo

    await ensure_indexes(mongo)

    if not await _alerts(mongo).find_one({"_id": CONFIG_ID}):
        await _alerts(mongo).update_one(
            {"_id": CONFIG_ID}, {"$setOnInsert": _seed_from_env()}, upsert=True
        )
        print("[FWA Sync ICS] Seeded config (disabled; enable with /fwasync enable)")

    configured = ", ".join(feed_urls().keys()) or "NONE"
    print(f"[FWA Sync ICS] Feeds configured: {configured}")

    poller_task = asyncio.create_task(poller_loop(mongo))


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global poller_task
    if poller_task and not poller_task.done():
        poller_task.cancel()
    print("[FWA Sync ICS] Poller cancelled")


# ---- Admin controls (ADMINISTRATOR only) ----
fwasync = lightbulb.Group("fwasync", "Admin controls for the BAND FWA sync DM alerts",
                          default_member_permissions=hikari.Permissions.ADMINISTRATOR)
loader.command(fwasync)


@fwasync.register()
class Enable(lightbulb.SlashCommand, name="enable", description="Turn the FWA sync DM alerts ON"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _alerts(mongo).update_one({"_id": CONFIG_ID}, {"$set": {"enabled": True}}, upsert=True)
        await ctx.respond("✅ FWA sync DM alerts **enabled**. Takes effect within one poll "
                          "(≤5 min).", ephemeral=True)


@fwasync.register()
class Disable(lightbulb.SlashCommand, name="disable", description="Turn the FWA sync DM alerts OFF"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await _alerts(mongo).update_one({"_id": CONFIG_ID}, {"$set": {"enabled": False}}, upsert=True)
        await ctx.respond("🛑 FWA sync DM alerts **disabled**. Takes effect within one poll "
                          "(≤5 min). No restart needed.", ephemeral=True)


@fwasync.register()
class Status(lightbulb.SlashCommand, name="status", description="Show config and recent alert state"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        # Mongo is remote; two round trips can outrun the 3s deadline on a slow link.
        await ctx.defer(ephemeral=True)
        config = await load_config(mongo)
        coll = _alerts(mongo)
        recipients = ", ".join(f"<@{u}>" for u in config["dm_user_ids"]) or "_none configured_"
        lines = [
            f"**Enabled:** {'yes' if config['enabled'] else 'no'}",
            f"**Feeds set:** {', '.join(feed_urls().keys()) or '_none_'}",
            f"**Recipients:** {recipients}",
            f"**Offsets:** {', '.join(str(o) for o in config['offsets'])} min"
            f"{' + on discovery' if config['announce_on_discovery'] else ''}",
            f"**Poll:** every {config['poll_seconds']}s",
            f"**Summary filter:** `{config['summary_filter']}`",
            "**Recent alerts:**",
        ]
        cursor = coll.find({
            "_id": {"$ne": CONFIG_ID},
            "kind": {"$ne": "event_state"},
        }).sort("announced_at", -1).limit(50)
        found = False
        shown = set()
        async for doc in cursor:
            # Delivery state is per recipient, but the command has always presented
            # alert occurrences. Collapse recipient rows to preserve that UX.
            alert_key = (
                doc.get("uid"), doc.get("event_version"), doc.get("offset")
            )
            if alert_key in shown:
                continue
            shown.add(alert_key)
            found = True
            lines.append(f"• `{doc.get('offset')}` {doc.get('status')} — "
                         f"{doc.get('calendar')} {discord_timestamp(doc.get('start_at'), 'f')}")
            if len(shown) >= 5:
                break
        if not found:
            lines.append("_(none yet)_")
        await ctx.respond("\n".join(lines))


@fwasync.register()
class Check(lightbulb.SlashCommand, name="check",
            description="Dry run: fetch all feeds and report what is upcoming. Sends no DMs."):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        # defer + respond, not respond + edit: fetching three feeds can take up to 45s,
        # well past Discord's 3s initial-response deadline.
        await ctx.defer(ephemeral=True)
        config = await load_config(mongo)
        try:
            events, errors = await collect_events(config["summary_filter"])
        except Exception as e:
            await ctx.respond(f"❌ Fetch failed: `{type(e).__name__}: {e}`")
            return

        lines = [f"**Feeds set:** {', '.join(feed_urls().keys()) or '_none_'}"]
        if errors:
            lines.append("**Errors:**")
            lines.extend(f"• ⚠️ {e}" for e in errors)
        lines.append(f"**Upcoming syncs:** {len(events)}")
        for event in events[:10]:
            lines.append(
                f"• **{event['calendar']}** — {discord_timestamp(event['start'], 'F')} "
                f"({discord_timestamp(event['start'], 'R')})\n"
                f"  {event['summary'][:120]}"
            )
        if not events:
            lines.append("_(nothing upcoming - normal on a quiet day, but check the feeds "
                         "if this persists)_")
        await ctx.respond("\n".join(lines)[:1900])


@fwasync.register()
class Preview(lightbulb.SlashCommand, name="preview",
              description="DM yourself the alert embed for the next sync. Touches no dedupe state."):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        config = await load_config(mongo)
        events, _errors = await collect_events(config["summary_filter"])

        if events:
            event = events[0]
            note = "real next sync"
        else:
            event = {
                "uid": "preview",
                "start": datetime.now(timezone.utc) + timedelta(minutes=61),
                "end": datetime.now(timezone.utc) + timedelta(minutes=101),
                "summary": "⚀⚀ PREVIEW — Tie Breaker High Sync ➡️ Closest to Z wins",
                "calendar": "Sync3",
            }
            note = "synthetic (no upcoming sync in the feeds)"

        offset = str(config["offsets"][0]) if config["offsets"] else DISCOVERY_OFFSET
        sent = await dm_all([ctx.user.id], build_embed(event, offset))
        if sent:
            await ctx.respond(f"✅ Preview DMed to you ({note}). No dedupe state written.")
        else:
            await ctx.respond("❌ Could not DM you — your DMs are likely closed.")


@fwasync.register()
class SetRecipients(lightbulb.SlashCommand, name="set-recipients",
                    description="Replace the DM recipient list (comma-separated user IDs)"):
    user_ids = lightbulb.string("user_ids", "Comma-separated Discord user IDs")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        parsed = []
        for chunk in self.user_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                parsed.append(int(chunk))
        parsed = ordered_user_ids(parsed)
        if not parsed:
            await ctx.respond("❌ No valid user IDs found.", ephemeral=True)
            return
        await _alerts(mongo).update_one({"_id": CONFIG_ID}, {"$set": {"dm_user_ids": parsed}}, upsert=True)
        await ctx.respond("✅ Recipients set to " + ", ".join(f"<@{u}>" for u in parsed), ephemeral=True)


@fwasync.register()
class SetOffsets(lightbulb.SlashCommand, name="set-offsets",
                 description="Replace the alert offsets, in minutes before the sync"):
    minutes = lightbulb.string("minutes", "Comma-separated minutes, e.g. 60,10")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        parsed = sorted({int(c.strip()) for c in self.minutes.replace(";", ",").split(",")
                         if c.strip().isdigit() and int(c.strip()) > 0}, reverse=True)
        if not parsed:
            await ctx.respond("❌ No valid positive offsets found.", ephemeral=True)
            return
        await _alerts(mongo).update_one({"_id": CONFIG_ID}, {"$set": {"offsets": parsed}}, upsert=True)
        await ctx.respond(f"✅ Offsets set to {', '.join(str(p) for p in parsed)} minutes. "
                          f"Applies to events not yet alerted.", ephemeral=True)
