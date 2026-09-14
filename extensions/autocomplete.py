from utils.mongo import MongoClient
import lightbulb
from utils.classes import Clan
from utils.constants import MAX_OPPONENT_NAME_LENGTH
from utils.fwa_points_parser import sanitize_tag
from extensions.tasks.fwa_points_monitor import _board_snapshot, current_opponent_name_for
import time

# Simple cache storage
_cache = {
    "clan_types": {"data": None, "timestamp": 0},
    "th_attribute": {"data": None, "timestamp": 0},
    "clans": {"data": None, "timestamp": 0},
    "fwa_clans": {"data": None, "timestamp": 0},
    "war_plan_opponents": {"data": None, "timestamp": 0},
}
CACHE_DURATION = 300  # 5 minutes
WAR_PLAN_OPPONENTS_CACHE_DURATION = 60  # seconds - points monitor scrapes are frequent

# Names the points monitor stores when it has no real opponent yet.
_PLACEHOLDER_OPPONENT_NAMES = {"", "unknown", "unknown opponent", "tbd", "n/a", "none"}


@lightbulb.di.with_di
async def clan_types(
        ctx: lightbulb.AutocompleteContext[str],
        mongo: MongoClient
) -> None:
    query = ctx.focused.value or ""

    # Check cache
    now = time.time()
    if _cache["clan_types"]["data"] is None or (now - _cache["clan_types"]["timestamp"]) > CACHE_DURATION:
        _cache["clan_types"]["data"] = (await mongo.clans.distinct("type")) + ["Demo", "Stuff"]
        _cache["clan_types"]["timestamp"] = now

    distinct = _cache["clan_types"]["data"]
    await ctx.respond([d for d in distinct if query.lower() in d.lower()])


@lightbulb.di.with_di
async def th_attribute(
        ctx: lightbulb.AutocompleteContext[str],
        mongo: MongoClient
) -> None:
    query = ctx.focused.value or ""

    # Check cache
    now = time.time()
    if _cache["th_attribute"]["data"] is None or (now - _cache["th_attribute"]["timestamp"]) > CACHE_DURATION:
        _cache["th_attribute"]["data"] = (await mongo.clans.distinct("th_attribute")) + ["Demo", "Stuff"]
        _cache["th_attribute"]["timestamp"] = now

    distinct = _cache["th_attribute"]["data"]
    await ctx.respond([d for d in distinct if query.lower() in d.lower()])


@lightbulb.di.with_di
async def clans(
        ctx: lightbulb.AutocompleteContext[str],
        mongo: MongoClient
) -> None:
    query = ctx.focused.value or ""

    # Check cache
    now = time.time()
    if _cache["clans"]["data"] is None or (now - _cache["clans"]["timestamp"]) > CACHE_DURATION:
        clans_data = await mongo.clans.find().to_list(length=None)
        _cache["clans"]["data"] = [Clan(data=data) for data in clans_data]
        _cache["clans"]["timestamp"] = now

    clans = _cache["clans"]["data"]
    await ctx.respond([f"{c.name} | {c.tag}" for c in clans if query.lower() in c.name.lower()])


@lightbulb.di.with_di
async def fwa_clans(
        ctx: lightbulb.AutocompleteContext[str],
        mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Autocomplete for FWA clans only"""
    query = ctx.focused.value or ""

    # Check cache
    now = time.time()
    if _cache["fwa_clans"]["data"] is None or (now - _cache["fwa_clans"]["timestamp"]) > CACHE_DURATION:
        _cache["fwa_clans"]["data"] = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
        _cache["fwa_clans"]["timestamp"] = now

    clans = _cache["fwa_clans"]["data"]

    # Filter clans based on query
    filtered_clans = []
    for clan in clans:
        if query.lower() in clan['name'].lower() or query.lower() in clan['tag'].lower():
            filtered_clans.append(clan)

    # Create list of tuples for clean display
    choices = []
    for clan in filtered_clans[:25]:
        # Display format: Just the clan name for simplicity
        display = clan['name']
        # Value format: "Name|Tag|RoleID" (what the command receives)
        value = f"{clan['name']}|{clan['tag']}|{clan.get('role_id', '')}"
        choices.append((display, value))

    await ctx.respond(choices)


def _opponent_name_for_record(rec: dict) -> str | None:
    """Current opponent name for one fwa_points record, or None if unusable.

    Uses fwa_points_monitor.current_opponent_name_for - the same rule the
    war board (build_points_board) renders from - so a war that is merely
    noted but not yet caught up doesn't surface the previous war's name.
    """
    name = current_opponent_name_for(rec)
    if not name:
        return None
    name = name.strip()
    if not name or name.casefold() in _PLACEHOLDER_OPPONENT_NAMES:
        return None
    return name


def build_opponent_choices(
        watch: list,
        records: dict,
        *,
        query: str = "",
        chosen_clan_tag: str | None = None,
) -> list[tuple[str, str]]:
    """Build (display, value) choices for /fwa war-plans' `opponent` option.

    `watch`/`records` are exactly what fwa_points_monitor._board_snapshot()
    returns - the same source the war board renders from. Pure and sync so
    it is testable without mongo or an interaction. Values are the raw
    opponent name (no markdown escaping/stripping) so they equal the CoC
    name war_plans compares against via sanitize_opponent_name.
    """
    query = (query or "").casefold()
    chosen_clan_tag = sanitize_tag(chosen_clan_tag) if chosen_clan_tag else None

    entries = []  # (opponent_name, our_clan_name, tag)
    for clan in watch:
        tag = sanitize_tag(clan.get("tag", ""))
        rec = records.get(tag)
        if not rec:
            continue
        name = _opponent_name_for_record(rec)
        if not name:
            continue
        entries.append((name, clan.get("name") or tag, tag))

    if chosen_clan_tag:
        # Stable sort: chosen clan's opponent(s) first, everything else keeps order.
        entries.sort(key=lambda e: e[2] != chosen_clan_tag)

    seen = set()
    choices = []
    for name, our_clan_name, tag in entries:
        key = name.casefold()
        if key in seen:
            continue
        if query and query not in key:
            continue
        seen.add(key)
        display = f"{name} — vs {our_clan_name}" if tag == chosen_clan_tag else name
        choices.append((display[:100], name[:MAX_OPPONENT_NAME_LENGTH]))
        if len(choices) >= 25:
            break
    return choices


def _chosen_clan_tag_from_option(raw_value: str | None) -> str | None:
    """Pull the clan tag out of the `clan` option's value, if set.

    Handles both the desktop "Name|#TAG|role_id" autocomplete value and the
    plain "Name" text mobile clients can submit - same formats war_plans.py's
    invoke() already parses.
    """
    if not raw_value:
        return None
    parts = raw_value.split("|")
    if len(parts) >= 2:
        return sanitize_tag(parts[1])
    return None


async def war_plan_opponents(
        ctx: lightbulb.AutocompleteContext[str],
) -> None:
    """Autocomplete for /fwa war-plans' `opponent` option from the FWA points
    monitor's current-opponent records, so reps don't have to type or copy
    the name off the war board."""
    query = ctx.focused.value or ""

    now = time.time()
    cache = _cache["war_plan_opponents"]
    if cache["data"] is None or (now - cache["timestamp"]) > WAR_PLAN_OPPONENTS_CACHE_DURATION:
        try:
            _, watch, records = await _board_snapshot()
            cache["data"] = (watch, records)
            cache["timestamp"] = now
        except Exception as e:
            print(f"[Autocomplete] war_plan_opponents: failed to load points monitor data: {type(e).__name__}: {e}")
            if cache["data"] is None:
                await ctx.respond([])
                return
            # Refresh failed but a previous snapshot exists - serve it stale
            # rather than going empty.

    watch, records = cache["data"]

    clan_option = ctx.get_option("clan")
    chosen_clan_tag = _chosen_clan_tag_from_option(clan_option.value if clan_option else None)

    try:
        choices = build_opponent_choices(watch, records, query=query, chosen_clan_tag=chosen_clan_tag)
    except Exception as e:
        print(f"[Autocomplete] war_plan_opponents: failed to build choices: {type(e).__name__}: {e}")
        choices = []

    await ctx.respond(choices)


# Simple preload function to call on bot startup
async def preload_autocomplete_cache(mongo: MongoClient):
    """Call this once when your bot starts to preload all caches"""
    print("[Autocomplete] Preloading caches...")

    # Preload each cache
    _cache["clan_types"]["data"] = (await mongo.clans.distinct("type")) + ["Demo", "Stuff"]
    _cache["clan_types"]["timestamp"] = time.time()

    _cache["th_attribute"]["data"] = (await mongo.clans.distinct("th_attribute")) + ["Demo", "Stuff"]
    _cache["th_attribute"]["timestamp"] = time.time()

    clans_data = await mongo.clans.find().to_list(length=None)
    _cache["clans"]["data"] = [Clan(data=data) for data in clans_data]
    _cache["clans"]["timestamp"] = time.time()

    _cache["fwa_clans"]["data"] = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
    _cache["fwa_clans"]["timestamp"] = time.time()

    print(f"[Autocomplete] Loaded {len(_cache['clans']['data'])} clans, {len(_cache['fwa_clans']['data'])} FWA clans")