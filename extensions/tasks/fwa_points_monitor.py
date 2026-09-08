# FWA points monitor.
#
# Was shipped DISABLED (DEFAULT_ENABLED = False) while the bot ran on Hetzner:
# points.fwafarm.com sits behind Cloudflare, which hard-blocks requests from
# datacenter IPs. Confirmed from the Hetzner box on 2026-07-11: curl returned
# HTTP 403 on all three attempts, and because curl has a completely different
# TLS fingerprint than aiohttp yet was blocked identically, the block was on
# the datacenter IP, not the client and not the request headers (the exact
# same headers returned HTTP 200 from a non-datacenter IP).
#
# Since 2026-09-08 the bot runs on Ruggie's Zone, a residential machine, and
# the site answers normally with these same headers - so DEFAULT_ENABLED is
# now True. The Mongo config doc still decides at runtime and is only seeded
# with the default on first boot, so an existing database that was seeded
# while this shipped disabled needs `/fwapoints enable` run once. Do not reach
# for a Cloudflare-bypass library: those defeat TLS/JS challenges, not
# IP-reputation blocks, so they would not have helped here anyway.

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import coc
import hikari
import lightbulb

from utils import coc_maintenance
from utils.mongo import MongoClient
from utils.fwa_points_parser import (
    parse_clan_points, parse_active_fwa, sanitize_tag, is_newer_war, FwaPointsParseError,
)
from utils.startup_reconciler import StartupReconciler

loader = lightbulb.Loader()

# ---- Config (all tunable here) ----
DETECTOR_INTERVAL_SECONDS = 10 * 60   # how often we ask CoC "is there a new war?"
RETRY_INTERVAL_SECONDS = 2 * 60       # how often we re-check the points site while catching up
GIVE_UP_SECONDS = 45 * 60             # bounded catch-up deadline
MAX_CONSECUTIVE_FAILURES = 5          # stop early if the SITE is down (~10 min) vs merely stale
FAILURE_COOLDOWN_SECONDS = GIVE_UP_SECONDS  # do not launch another retry burst for this same war immediately
HTTP_TIMEOUT_SECONDS = 20
LOG_CHANNEL_ID = 947166650321494067
POINTS_URL = "https://points.fwafarm.com/clan?tag={tag}"
STAGGER_STEP_SECONDS = 5        # spacing between clans launched in the same detector pass
STAGGER_JITTER_MAX_SECONDS = 5  # extra random slack added on top of the step

DEFAULT_ENABLED = True
# Extras only. The bulk of the watch list now comes from mongo.clans (every
# clan of type FWA) - see effective_watch_list(). This stays empty; a clan
# outside that set is added via /fwapoints watch-add.
DEFAULT_WATCH_LIST = []

# Cloudflare here rejects non-browser User-Agents (verified: honest UA -> 403,
# Chrome UA -> 200). We stay polite via event-only fetching, low frequency, and
# staggering each clan's catch-up start (see STAGGER_STEP_SECONDS) so a detector
# pass that launches several catch-ups does not fire them all in lockstep.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# ---- Module state ----
bot_instance = None
mongo_client = None
coc_client = None
detector_task = None
startup_reconciler = None
active_catchups = {}   # our_tag -> asyncio.Task


# ---- Config helpers ----
async def load_config():
    doc = await mongo_client.fwa_points.find_one({"_id": "config"})
    if not doc:
        return {"enabled": DEFAULT_ENABLED, "watch_list": list(DEFAULT_WATCH_LIST)}
    return {"enabled": doc.get("enabled", DEFAULT_ENABLED), "watch_list": doc.get("watch_list", [])}


async def feature_enabled():
    doc = await mongo_client.fwa_points.find_one({"_id": "config"}, {"enabled": 1})
    return bool(doc and doc.get("enabled"))


async def effective_watch_list(config=None):
    """Every clan of type FWA, plus the config doc's watch_list as extras.

    Resolved fresh on every call (never cached alongside config) because clan
    membership in mongo.clans changes independently of any /fwapoints command.
    De-duplicated by tag; a clan-type entry wins over an extra with the same
    tag since it is the source of truth for FWA membership.
    """
    if config is None:
        config = await load_config()

    entries: dict[str, dict] = {}
    try:
        fwa_clans = await mongo_client.clans.find({"type": "FWA"}).to_list(length=None)
    except Exception as e:
        print(f"[FWA Points] Failed to load FWA clan list: {type(e).__name__}: {e}")
        fwa_clans = []
    for doc in fwa_clans:
        t = sanitize_tag(doc.get("tag", ""))
        if not t:
            continue
        entries[t] = {"tag": t, "name": doc.get("name") or t, "source": "clan_type"}

    for clan in config.get("watch_list", []):
        t = sanitize_tag(clan.get("tag", ""))
        if not t or t in entries:
            continue
        entries[t] = {"tag": t, "name": clan.get("name") or t, "source": "extra"}

    return list(entries.values())


# ---- CoC side (source of truth for the hard gate) ----
async def get_current_war_info(our_tag):
    """Return (state, opponent_tag, war_key, coc_war_end_time, coc_opponent_name) or None.

    None means no war / private log / API error. coc_war_end_time is an ISO
    string of the war's end_time (same Timestamp object war_key is built
    from), or None if that field is unreadable. coc_opponent_name is the
    opponent clan's name straight from the CoC API (war.opponent.name), used
    as a fallback header label when the points site scrape has none.
    """
    try:
        war = await coc_client.get_clan_war(f"#{our_tag}")
    except coc.PrivateWarLog:
        print(f"[FWA Points] {our_tag}: war log is private, cannot verify opponent, skipping")
        return None
    except coc.NotFound:
        print(f"[FWA Points] {our_tag}: clan not found")
        return None
    except coc.Maintenance:
        # This task runs on a timer whether or not anyone opens /todo, so it is
        # usually what NOTICES a break first - and what clears the flag first
        # once the API comes back. Behaviour is unchanged; only the reporting
        # is new. Must stay above the HTTPException clause, which it subclasses.
        coc_maintenance.note_maintenance()
        print(f"[FWA Points] {our_tag}: Clash in maintenance, retry next cycle")
        return None
    except (coc.GatewayError, coc.HTTPException) as e:
        print(f"[FWA Points] {our_tag}: CoC unavailable ({type(e).__name__}), retry next cycle")
        return None
    except Exception as e:
        print(f"[FWA Points] {our_tag}: unexpected CoC error: {e}")
        return None

    coc_maintenance.note_success()
    state = getattr(war, "state", None)
    if state in (None, "notInWar"):
        return None
    opponent = getattr(war, "opponent", None)
    opp_tag = sanitize_tag(getattr(opponent, "tag", "") or "")
    if not opp_tag:
        return None
    coc_opponent_name = getattr(opponent, "name", None)
    prep = getattr(war, "preparation_start_time", None)
    war_key = f"{opp_tag}:{getattr(prep, 'raw_time', prep)}"

    end = getattr(war, "end_time", None)
    end_dt = getattr(end, "time", None)
    coc_war_end_time = end_dt.isoformat() if end_dt is not None else None

    return state, opp_tag, war_key, coc_war_end_time, coc_opponent_name


# ---- Points site ----
async def fetch_points_html(our_tag):
    url = POINTS_URL.format(tag=our_tag)
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=BROWSER_HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"[FWA Points] {our_tag}: HTTP {resp.status} from points site")
                    return None
                return await resp.text()
    except asyncio.TimeoutError:
        print(f"[FWA Points] {our_tag}: points site timeout")
        return None
    except aiohttp.ClientError as e:
        print(f"[FWA Points] {our_tag}: points site error {type(e).__name__}: {e}")
        return None
    except Exception as e:
        print(f"[FWA Points] {our_tag}: unexpected fetch error: {e}")
        return None


# ---- Mongo writes ----
async def store_record(our_tag, name, parsed, coc_opponent_tag, war_key, attempt,
                        opponent_active_fwa=None, coc_war_end_time=None,
                        coc_opponent_name=None):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "clan_name": parsed["clan_name"] or name,
        "our_clan_tag": our_tag,
        "scraped_opponent_tag": parsed["opponent_tag"],
        "coc_opponent_tag": coc_opponent_tag,
        "coc_opponent_name": coc_opponent_name,
        "opponent_name_scraped": parsed["opponent_name"],
        "opponent_name": parsed["opponent_name"],
        "opponent_active_fwa": opponent_active_fwa,
        "war_number": parsed["war_number"],
        "sync_number": parsed["sync_number"],
        "point_balance": parsed["point_balance"],
        "active_fwa": parsed["active_fwa"],
        "last_war_state": parsed["last_war_state"],
        "raw_verdict": parsed["raw_verdict"],
        "predicted_winner_name": parsed.get("predicted_winner_name"),
        "our_outcome": parsed.get("our_outcome"),
        "coc_war_key": war_key,
        "coc_war_end_time": coc_war_end_time,
        "scraped_at": now,
        "attempts": attempt,
        "status": "caught_up",
        "last_attempt_at": now,
        "last_attempt_status": "caught_up",
        "last_attempt_war_key": war_key,
    }
    await mongo_client.fwa_points.update_one(
        {"_id": our_tag},
        {
            "$set": record,
            "$unset": {"retry_after": "", "last_attempt_error": ""},
        },
        upsert=True,
    )


async def mark_attempt(our_tag, status, war_key, error=None):
    # Never touches the verdict block - only records that we tried.
    now = datetime.now(timezone.utc)
    fields = {
        "status": status,
        "last_attempt_at": now.isoformat(),
        "last_attempt_status": status,
        "last_attempt_war_key": war_key,
        "retry_after": (now + timedelta(seconds=FAILURE_COOLDOWN_SECONDS)).isoformat(),
    }
    if error:
        fields["last_attempt_error"] = str(error)[:500]
    await mongo_client.fwa_points.update_one(
        {"_id": our_tag},
        {"$set": fields},
        upsert=True,
    )


def retry_is_deferred(record, war_key, now=None):
    """Whether a failed attempt for this exact war is still cooling down.

    The war key is deliberately part of the decision: a newly detected war must
    never inherit the previous war's failure cooldown.
    """
    if not record or record.get("last_attempt_war_key") != war_key:
        return False
    if record.get("last_attempt_status") not in {"failed", "gave_up", "error"}:
        return False

    retry_after = record.get("retry_after")
    if isinstance(retry_after, str):
        try:
            retry_after = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(retry_after, datetime):
        return False
    if retry_after.tzinfo is None:
        retry_after = retry_after.replace(tzinfo=timezone.utc)

    return retry_after > (now or datetime.now(timezone.utc))


def watch_list_replacement_pipeline(tag, name):
    """Build one atomic update that replaces any existing entry for ``tag``."""
    return [{
        "$set": {
            "watch_list": {
                "$concatArrays": [
                    {
                        "$filter": {
                            "input": {"$ifNull": ["$watch_list", []]},
                            "as": "clan",
                            "cond": {"$ne": ["$$clan.tag", tag]},
                        }
                    },
                    [{"tag": tag, "name": name}],
                ]
            }
        }
    }]


async def record_failed_catchup(our_tag, name, war_key, status, message):
    """Persist and announce a terminal catch-up failure without masking it."""
    try:
        await mark_attempt(our_tag, status, war_key, message)
    except Exception as e:
        print(f"[FWA Points] {name}: failed to persist {status} state: {type(e).__name__}: {e}")
    await log_outcome(f"{name}: {message}")


async def log_outcome(line):
    if not bot_instance:
        return
    try:
        await bot_instance.rest.create_message(channel=LOG_CHANNEL_ID, content=line)
    except Exception as e:
        print(f"[FWA Points] Failed to log outcome: {e}")


# ---- Catch-up task (the only thing that touches the points site) ----
async def run_catchup(clan_entry, coc_opponent_tag, war_key, coc_war_end_time=None,
                       stagger_seconds=0, coc_opponent_name=None):
    """`stagger_seconds` is slept before the first fetch, so several clans
    detected in the same pass do not all hit the points site in the same
    instant and retry in lockstep. The caller (detector_loop) computes it as
    ``index * STAGGER_STEP_SECONDS + random.uniform(0, STAGGER_JITTER_MAX_SECONDS)``
    for this clan's position among the catch-ups launched this pass. The
    sleep lives here rather than in detector_loop so it delays this clan's own
    fetches without blocking the detector from starting other clans' tasks.
    Defaults to 0 so tests (and a lone catch-up) see no delay.
    """
    our_tag = sanitize_tag(clan_entry.get("tag", ""))
    name = clan_entry.get("name", our_tag)
    try:
        if stagger_seconds > 0:
            await asyncio.sleep(stagger_seconds)
        prev_record = await mongo_client.fwa_points.find_one(
            {"_id": our_tag}, {"war_number": 1, "raw_verdict": 1}
        )
        deadline = time.monotonic() + GIVE_UP_SECONDS
        attempt = 0
        consecutive_failures = 0
        last_error = None
        while True:
            if not await feature_enabled():
                print(f"[FWA Points] {name}: disabled mid-catch-up, stopping")
                return
            attempt += 1
            html = await fetch_points_html(our_tag)
            if html is None:
                consecutive_failures += 1
                last_error = "timeout/HTTP error"
            else:
                try:
                    parsed = parse_clan_points(html, our_tag)
                except FwaPointsParseError as e:
                    consecutive_failures += 1
                    last_error = f"parse failed ({e})"
                else:
                    if parsed["opponent_tag"] != coc_opponent_tag:
                        # Page still shows the previous war (different opponent) -> wait.
                        consecutive_failures = 0
                    elif parsed.get("war_number") is None:
                        # Right opponent but the war number is unreadable, so we cannot
                        # confirm which war this is. Never write an unverifiable record;
                        # treat it as a failure and keep retrying.
                        consecutive_failures += 1
                        last_error = "war number unreadable"
                    elif is_newer_war(prev_record, parsed):
                        # HARD GATE: right opponent AND a war newer than what we stored.
                        # The war-number check stops a stale same-opponent page from
                        # writing a previous war's verdict.
                        consecutive_failures = 0
                        opponent_active_fwa = None
                        opp_html = await fetch_points_html(coc_opponent_tag)
                        if opp_html is not None:
                            try:
                                opponent_active_fwa = parse_active_fwa(opp_html)
                            except Exception as e:
                                print(f"[FWA Points] {name}: opponent Active FWA parse failed: "
                                      f"{type(e).__name__}: {e}")
                        else:
                            print(f"[FWA Points] {name}: could not fetch opponent page for "
                                  f"Active FWA status, storing as unknown")
                        await store_record(
                            our_tag, name, parsed, coc_opponent_tag, war_key, attempt,
                            opponent_active_fwa=opponent_active_fwa,
                            coc_war_end_time=coc_war_end_time,
                            coc_opponent_name=coc_opponent_name,
                        )
                        cname = parsed["clan_name"] or name
                        verdict = parsed["raw_verdict"] or ""
                        short = verdict[len(cname):].strip() if verdict.startswith(cname) else verdict
                        await log_outcome(
                            f"{name}: {short} - war #{parsed['war_number']}, sync #{parsed['sync_number']}"
                        )
                        return
                    else:
                        # Same opponent but the page still shows a war we already have
                        # (or older) -> keep waiting for it to advance.
                        consecutive_failures = 0

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                await record_failed_catchup(
                    our_tag, name, war_key, "failed",
                    f"scrape failed ({last_error}), keeping last known",
                )
                return
            if time.monotonic() >= deadline:
                await record_failed_catchup(
                    our_tag, name, war_key, "gave_up",
                    f"no new data after {GIVE_UP_SECONDS // 60} min, gave up",
                )
                return
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        print(f"[FWA Points] {name}: catch-up cancelled")
        raise
    except Exception as e:
        detail = f"unexpected catch-up error ({type(e).__name__}: {e})"
        print(f"[FWA Points] {name}: {detail}")
        await record_failed_catchup(our_tag, name, war_key, "error", detail)
    finally:
        active_catchups.pop(our_tag, None)


# ---- Detector loop (CoC only, cheap) ----
async def detector_loop():
    print("[FWA Points] Detector loop started")
    while True:
        try:
            config = await load_config()
            if config["enabled"]:
                # Resolved fresh every tick: mongo.clans membership can change
                # without anyone touching /fwapoints.
                launched = 0  # position among catch-ups actually started this pass, for staggering
                for clan in await effective_watch_list(config):
                    our_tag = sanitize_tag(clan.get("tag", ""))
                    if not our_tag:
                        continue
                    existing = active_catchups.get(our_tag)
                    if existing and not existing.done():
                        continue
                    info = await get_current_war_info(our_tag)
                    if info is None:
                        continue
                    _state, coc_opp, war_key, coc_war_end_time, coc_opponent_name = info
                    rec = await mongo_client.fwa_points.find_one({"_id": our_tag})
                    if rec and rec.get("status") == "caught_up" and rec.get("coc_war_key") == war_key:
                        continue   # already have this exact war's verdict
                    if retry_is_deferred(rec, war_key):
                        continue   # same failed war is cooling down; a new war key bypasses this
                    stagger_seconds = (
                        launched * STAGGER_STEP_SECONDS
                        + random.uniform(0, STAGGER_JITTER_MAX_SECONDS)
                    )
                    task = asyncio.create_task(
                        run_catchup(clan, coc_opp, war_key, coc_war_end_time,
                                    stagger_seconds=stagger_seconds,
                                    coc_opponent_name=coc_opponent_name),
                        name=f"fwa-points-catchup:{our_tag}",
                    )
                    active_catchups[our_tag] = task
                    launched += 1
        except Exception as e:
            print(f"[FWA Points] Detector loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(DETECTOR_INTERVAL_SECONDS)


# ---- Lifecycle ----
async def _reconcile_points_startup() -> None:
    """Seed configuration and start exactly one protected detector loop."""
    global detector_task

    if not await mongo_client.fwa_points.find_one({"_id": "config"}):
        await mongo_client.fwa_points.update_one(
            {"_id": "config"},
            {"$setOnInsert": {"enabled": DEFAULT_ENABLED, "watch_list": list(DEFAULT_WATCH_LIST)}},
            upsert=True,
        )
        print("[FWA Points] Seeded config")
    if detector_task and not detector_task.done():
        return
    detector_task = asyncio.create_task(
        detector_loop(), name="fwa-points-detector"
    )
    print("[FWA Points] Task started")


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(event: hikari.StartedEvent,
                         mongo: MongoClient = lightbulb.di.INJECTED,
                         coc_api: coc.Client = lightbulb.di.INJECTED) -> None:
    global bot_instance, mongo_client, coc_client, startup_reconciler
    bot_instance = event.app
    mongo_client = mongo
    coc_client = coc_api

    if startup_reconciler is None:
        startup_reconciler = StartupReconciler(
            "fwa_points",
            _reconcile_points_startup,
        )
    startup_reconciler.start()


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global detector_task, startup_reconciler
    tasks = []
    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None
    if detector_task and not detector_task.done():
        detector_task.cancel()
        tasks.append(detector_task)
    for t in list(active_catchups.values()):
        if not t.done():
            t.cancel()
            tasks.append(t)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    detector_task = None
    active_catchups.clear()
    print("[FWA Points] Tasks cancelled")


# ---- Admin controls (ADMINISTRATOR only) ----
fwapoints = lightbulb.Group("fwapoints", "Admin controls for the FWA points monitor",
                            default_member_permissions=hikari.Permissions.ADMINISTRATOR)
loader.command(fwapoints)


@fwapoints.register()
class Enable(lightbulb.SlashCommand, name="enable", description="Turn the FWA points monitor ON"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await mongo.fwa_points.update_one({"_id": "config"}, {"$set": {"enabled": True}}, upsert=True)
        await ctx.respond("✅ FWA points monitor **enabled**.", ephemeral=True)


@fwapoints.register()
class Disable(lightbulb.SlashCommand, name="disable",
              description="Turn the FWA points monitor OFF (stops in-progress retries)"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await mongo.fwa_points.update_one({"_id": "config"}, {"$set": {"enabled": False}}, upsert=True)
        cancelled = 0
        for t in list(active_catchups.values()):
            if not t.done():
                t.cancel()
                cancelled += 1
        await ctx.respond(f"🛑 FWA points monitor **disabled**. Stopped {cancelled} in-progress retr"
                          f"{'y' if cancelled == 1 else 'ies'}.", ephemeral=True)


@fwapoints.register()
class WatchAdd(lightbulb.SlashCommand, name="watch-add", description="Add a clan to the watch list"):
    tag = lightbulb.string("tag", "Clan tag (with or without #)")
    name = lightbulb.string("name", "Display name used in logs")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        t = sanitize_tag(self.tag)
        if not t:
            await ctx.respond("❌ Invalid tag.", ephemeral=True)
            return
        # One aggregation-pipeline update avoids the brief missing/duplicate
        # state produced by the old $pull followed by $push pair.
        await mongo.fwa_points.update_one(
            {"_id": "config"},
            watch_list_replacement_pipeline(t, self.name),
            upsert=True,
        )
        await ctx.respond(f"✅ Added **{self.name}** (`{t}`) to the watch list.", ephemeral=True)


@fwapoints.register()
class WatchRemove(lightbulb.SlashCommand, name="watch-remove", description="Remove a clan from the watch list"):
    tag = lightbulb.string("tag", "Clan tag to remove")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        t = sanitize_tag(self.tag)
        await mongo.fwa_points.update_one({"_id": "config"}, {"$pull": {"watch_list": {"tag": t}}})
        task = active_catchups.get(t)
        if task and not task.done():
            task.cancel()
        await ctx.respond(f"✅ Removed `{t}` from the watch list.", ephemeral=True)


@fwapoints.register()
class Status(lightbulb.SlashCommand, name="status", description="Show monitor status and last records"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        try:
            config = await load_config()
        except Exception as exc:
            detector_state = "running" if detector_task and not detector_task.done() else "not running"
            recovery_state = (
                startup_reconciler.status_text()
                if startup_reconciler is not None
                else "stopped"
            )
            await ctx.respond(
                "**FWA Points Status**\n"
                f"**Detector:** {detector_state}\n"
                f"**Startup recovery:** {recovery_state}\n"
                f"**MongoDB:** unavailable ({type(exc).__name__})",
                ephemeral=True,
            )
            return
        active = sum(1 for t in active_catchups.values() if not t.done())
        detector_running = bool(detector_task and not detector_task.done())
        recovery_status = (
            startup_reconciler.status_text()
            if startup_reconciler is not None
            else "⏹️ Stopped"
        )
        watch_list = await effective_watch_list(config)
        lines = [f"**Enabled:** {'yes' if config['enabled'] else 'no'}",
                 f"**Detector:** {'✅ Running' if detector_running else '❌ Not running'}",
                 f"**Startup recovery:** {recovery_status}",
                 f"**Active retries:** {active}", "**Watch list (effective):**"]
        if not watch_list:
            lines.append("_(empty)_")
        for clan in watch_list:
            t = sanitize_tag(clan.get("tag", ""))
            source_tag = "FWA clan" if clan.get("source") == "clan_type" else "extra"
            rec = await mongo.fwa_points.find_one({"_id": t})
            if rec and rec.get("raw_verdict"):
                lines.append(f"• {clan.get('name')} (`{t}`) [{source_tag}]: {rec['raw_verdict']} "
                             f"(war #{rec.get('war_number')}, scraped {rec.get('scraped_at', '?')})")
            else:
                lines.append(f"• {clan.get('name')} (`{t}`) [{source_tag}]: no data yet")
        await ctx.respond("\n".join(lines), ephemeral=True)
