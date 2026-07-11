import asyncio
import time
from datetime import datetime, timezone

import aiohttp
import coc
import hikari
import lightbulb

from utils.mongo import MongoClient
from utils.fwa_points_parser import parse_clan_points, sanitize_tag, is_newer_war, FwaPointsParseError

loader = lightbulb.Loader()

# ---- Config (all tunable here) ----
DETECTOR_INTERVAL_SECONDS = 10 * 60   # how often we ask CoC "is there a new war?"
RETRY_INTERVAL_SECONDS = 2 * 60       # how often we re-check the points site while catching up
GIVE_UP_SECONDS = 45 * 60             # bounded catch-up deadline
MAX_CONSECUTIVE_FAILURES = 5          # stop early if the SITE is down (~10 min) vs merely stale
HTTP_TIMEOUT_SECONDS = 20
LOG_CHANNEL_ID = 947166650321494067
POINTS_URL = "https://points.fwafarm.com/clan?tag={tag}"

DEFAULT_ENABLED = False
DEFAULT_WATCH_LIST = [{"tag": "2PPCL2GYP", "name": "Edrag Rush"}]

# Cloudflare here rejects non-browser User-Agents (verified: honest UA -> 403,
# Chrome UA -> 200). We stay polite via event-only fetching and low frequency.
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


# ---- CoC side (source of truth for the hard gate) ----
async def get_current_war_info(our_tag):
    """Return (state, opponent_tag, war_key) or None (no war / private log / API error)."""
    try:
        war = await coc_client.get_clan_war(f"#{our_tag}")
    except coc.PrivateWarLog:
        print(f"[FWA Points] {our_tag}: war log is private, cannot verify opponent, skipping")
        return None
    except coc.NotFound:
        print(f"[FWA Points] {our_tag}: clan not found")
        return None
    except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as e:
        print(f"[FWA Points] {our_tag}: CoC unavailable ({type(e).__name__}), retry next cycle")
        return None
    except Exception as e:
        print(f"[FWA Points] {our_tag}: unexpected CoC error: {e}")
        return None

    state = getattr(war, "state", None)
    if state in (None, "notInWar"):
        return None
    opponent = getattr(war, "opponent", None)
    opp_tag = sanitize_tag(getattr(opponent, "tag", "") or "")
    if not opp_tag:
        return None
    prep = getattr(war, "preparation_start_time", None)
    war_key = f"{opp_tag}:{getattr(prep, 'raw_time', prep)}"
    return state, opp_tag, war_key


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
async def store_record(our_tag, name, parsed, coc_opponent_tag, war_key, attempt):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "clan_name": parsed["clan_name"] or name,
        "our_clan_tag": our_tag,
        "scraped_opponent_tag": parsed["opponent_tag"],
        "coc_opponent_tag": coc_opponent_tag,
        "opponent_name_scraped": parsed["opponent_name"],
        "war_number": parsed["war_number"],
        "sync_number": parsed["sync_number"],
        "point_balance": parsed["point_balance"],
        "active_fwa": parsed["active_fwa"],
        "last_war_state": parsed["last_war_state"],
        "raw_verdict": parsed["raw_verdict"],
        "coc_war_key": war_key,
        "scraped_at": now,
        "attempts": attempt,
        "status": "caught_up",
        "last_attempt_at": now,
        "last_attempt_status": "caught_up",
    }
    await mongo_client.fwa_points.update_one({"_id": our_tag}, {"$set": record}, upsert=True)


async def mark_attempt(our_tag, status):
    # Never touches the verdict block - only records that we tried.
    await mongo_client.fwa_points.update_one(
        {"_id": our_tag},
        {"$set": {"last_attempt_at": datetime.now(timezone.utc).isoformat(),
                  "last_attempt_status": status}},
        upsert=True,
    )


async def log_outcome(line):
    if not bot_instance:
        return
    try:
        await bot_instance.rest.create_message(channel=LOG_CHANNEL_ID, content=line)
    except Exception as e:
        print(f"[FWA Points] Failed to log outcome: {e}")


# ---- Catch-up task (the only thing that touches the points site) ----
async def run_catchup(clan_entry, coc_opponent_tag, war_key):
    our_tag = sanitize_tag(clan_entry.get("tag", ""))
    name = clan_entry.get("name", our_tag)
    prev_record = await mongo_client.fwa_points.find_one(
        {"_id": our_tag}, {"war_number": 1, "raw_verdict": 1}
    )
    deadline = time.monotonic() + GIVE_UP_SECONDS
    attempt = 0
    consecutive_failures = 0
    last_error = None
    try:
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
                        await store_record(our_tag, name, parsed, coc_opponent_tag, war_key, attempt)
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
                await mark_attempt(our_tag, "failed")
                await log_outcome(f"{name}: scrape failed ({last_error}), keeping last known")
                return
            if time.monotonic() >= deadline:
                await mark_attempt(our_tag, "gave_up")
                await log_outcome(f"{name}: no new data after {GIVE_UP_SECONDS // 60} min, gave up")
                return
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        print(f"[FWA Points] {name}: catch-up cancelled")
        raise
    finally:
        active_catchups.pop(our_tag, None)


# ---- Detector loop (CoC only, cheap) ----
async def detector_loop():
    print("[FWA Points] Detector loop started")
    while True:
        try:
            config = await load_config()
            if config["enabled"]:
                for clan in config["watch_list"]:
                    our_tag = sanitize_tag(clan.get("tag", ""))
                    if not our_tag:
                        continue
                    existing = active_catchups.get(our_tag)
                    if existing and not existing.done():
                        continue
                    info = await get_current_war_info(our_tag)
                    if info is None:
                        continue
                    _state, coc_opp, war_key = info
                    rec = await mongo_client.fwa_points.find_one({"_id": our_tag})
                    if rec and rec.get("status") == "caught_up" and rec.get("coc_war_key") == war_key:
                        continue   # already have this exact war's verdict
                    task = asyncio.create_task(run_catchup(clan, coc_opp, war_key))
                    active_catchups[our_tag] = task
        except Exception as e:
            print(f"[FWA Points] Detector loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(DETECTOR_INTERVAL_SECONDS)


# ---- Lifecycle ----
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(event: hikari.StartedEvent,
                         mongo: MongoClient = lightbulb.di.INJECTED,
                         coc_api: coc.Client = lightbulb.di.INJECTED) -> None:
    global bot_instance, mongo_client, coc_client, detector_task
    bot_instance = event.app
    mongo_client = mongo
    coc_client = coc_api
    if not await mongo.fwa_points.find_one({"_id": "config"}):
        await mongo.fwa_points.update_one(
            {"_id": "config"},
            {"$setOnInsert": {"enabled": DEFAULT_ENABLED, "watch_list": list(DEFAULT_WATCH_LIST)}},
            upsert=True,
        )
        print("[FWA Points] Seeded config")
    detector_task = asyncio.create_task(detector_loop())
    print("[FWA Points] Task started")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    global detector_task
    if detector_task and not detector_task.done():
        detector_task.cancel()
    for t in list(active_catchups.values()):
        if not t.done():
            t.cancel()
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
        await mongo.fwa_points.update_one({"_id": "config"}, {"$pull": {"watch_list": {"tag": t}}}, upsert=True)
        await mongo.fwa_points.update_one({"_id": "config"},
                                          {"$push": {"watch_list": {"tag": t, "name": self.name}}}, upsert=True)
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
        config = await load_config()
        active = sum(1 for t in active_catchups.values() if not t.done())
        lines = [f"**Enabled:** {'yes' if config['enabled'] else 'no'}",
                 f"**Active retries:** {active}", "**Watch list:**"]
        if not config["watch_list"]:
            lines.append("_(empty)_")
        for clan in config["watch_list"]:
            t = sanitize_tag(clan.get("tag", ""))
            rec = await mongo.fwa_points.find_one({"_id": t})
            if rec and rec.get("raw_verdict"):
                lines.append(f"• {clan.get('name')} (`{t}`): {rec['raw_verdict']} "
                             f"(war #{rec.get('war_number')}, scraped {rec.get('scraped_at', '?')})")
            else:
                lines.append(f"• {clan.get('name')} (`{t}`): no data yet")
        await ctx.respond("\n".join(lines), ephemeral=True)
