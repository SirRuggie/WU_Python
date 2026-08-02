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
    for user_id in user_ids:
        try:
            user = await bot_instance.rest.fetch_user(user_id)
            channel = await bot_instance.rest.create_dm_channel(user.id)
            await bot_instance.rest.create_message(channel=channel, embed=embed)
            sent += 1
        except Exception as e:
            print(f"[FWA Sync ICS] DM to {user_id} failed ({type(e).__name__}: {e})")
    return sent


# ---- Dedupe state ----
def _claim_doc(event, offset, status):
    start = event["start"]
    return {
        "_id": f"{event['uid']}|{offset}",
        "uid": event["uid"],
        "offset": offset,
        "calendar": event["calendar"],
        "summary": event["summary"],
        "start_at": start,
        "status": status,
        "announced_at": datetime.now(timezone.utc),
        # TTL anchor: the doc dies 30 days after its own sync time.
        "expire_at": start + timedelta(days=DEDUPE_TTL_DAYS),
    }


async def claim(coll, event, offset, status):
    """Reserve (uid, offset) before sending. False means someone already has it."""
    try:
        await coll.insert_one(_claim_doc(event, offset, status))
        return True
    except DuplicateKeyError:
        return False


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
    """Announce a moved sync and re-anchor all state to the new time.

    Order is deliberate: state is rewritten BEFORE the DM goes out. If the DM fails we
    lose one change notification but the T-60m/T-10m alerts still fire correctly against
    the new time. The other order risks re-sending the change alert every poll forever.
    """
    old_start = normalize_start(existing.get("start_at"))
    await coll.delete_many({"uid": event["uid"]})
    await claim(coll, event, DISCOVERY_OFFSET, "sent")

    sent = await dm_all(config["dm_user_ids"], build_change_embed(event, old_start))
    print(f"[FWA Sync ICS] RESCHEDULE {event['calendar']} {event['uid']}: "
          f"{old_start} -> {event['start']} (DMed {sent})")
    if sent == 0:
        print("[FWA Sync ICS] WARNING: reschedule alert reached nobody")


async def process_event(coll, event, config, now):
    existing = await coll.find_one({"uid": event["uid"]})
    forced_first_seen = None

    if existing and detect_reschedule(existing.get("start_at"), event["start"]):
        await handle_reschedule(coll, event, existing, config)
        # State was just rebuilt against the new time; treat elapsed offsets as missed
        # rather than firing them behind the change alert.
        forced_first_seen = True

    claimed = set()
    async for doc in coll.find({"uid": event["uid"]}, {"offset": 1}):
        claimed.add(doc.get("offset"))

    to_send, to_retire = due_offsets(
        event["start"], now, claimed, config["offsets"],
        announce_on_discovery=config["announce_on_discovery"],
        first_seen=forced_first_seen,
    )

    for offset in to_retire:
        status = "seen" if offset == DISCOVERY_OFFSET else "skipped_late"
        if await claim(coll, event, offset, status):
            print(f"[FWA Sync ICS] {event['calendar']} {event['uid']}: "
                  f"offset {offset} recorded as {status} (window already passed)")

    for offset in to_send:
        if not await claim(coll, event, offset, "sent"):
            continue
        sent = await dm_all(config["dm_user_ids"], build_embed(event, offset))
        if sent == 0:
            # Nobody got it - drop the claim so the next poll retries rather than
            # silently swallowing the alert.
            await coll.delete_one({"_id": f"{event['uid']}|{offset}"})
            print(f"[FWA Sync ICS] WARNING: alert {offset} for {event['uid']} reached "
                  f"nobody; claim released, will retry next poll")
        else:
            print(f"[FWA Sync ICS] Sent {offset} alert for {event['calendar']} "
                  f"{event['start'].isoformat()} to {sent} user(s)")


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
        cursor = coll.find({"_id": {"$ne": CONFIG_ID}}).sort("announced_at", -1).limit(5)
        found = False
        async for doc in cursor:
            found = True
            lines.append(f"• `{doc.get('offset')}` {doc.get('status')} — "
                         f"{doc.get('calendar')} {discord_timestamp(doc.get('start_at'), 'f')}")
        if not found:
            lines.append("_(none yet)_")
        await ctx.respond("\n".join(lines), ephemeral=True)


@fwasync.register()
class Check(lightbulb.SlashCommand, name="check",
            description="Dry run: fetch all feeds and report what is upcoming. Sends no DMs."):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.respond("🔍 Fetching BAND iCal feeds...", ephemeral=True)
        config = await load_config(mongo)
        try:
            events, errors = await collect_events(config["summary_filter"])
        except Exception as e:
            await ctx.edit_last_response(f"❌ Fetch failed: `{type(e).__name__}: {e}`")
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
        await ctx.edit_last_response("\n".join(lines)[:1900])


@fwasync.register()
class Preview(lightbulb.SlashCommand, name="preview",
              description="DM yourself the alert embed for the next sync. Touches no dedupe state."):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.respond("📨 Building preview...", ephemeral=True)
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
            await ctx.edit_last_response(f"✅ Preview DMed to you ({note}). No dedupe state written.")
        else:
            await ctx.edit_last_response("❌ Could not DM you — your DMs are likely closed.")


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
