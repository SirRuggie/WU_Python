from utils.mongo import MongoClient
import lightbulb
from utils.classes import Clan
import time

# Simple cache storage
_cache = {
    "clan_types": {"data": None, "timestamp": 0},
    "th_attribute": {"data": None, "timestamp": 0},
    "clans": {"data": None, "timestamp": 0},
    "fwa_clans": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 300  # 5 minutes


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
        # Display format: "Clan Name • #TAG"
        display = f"{clan['name']} • {clan['tag']}"
        # Value format: "Name|Tag|RoleID" (what the command receives)
        value = f"{clan['name']}|{clan['tag']}|{clan.get('role_id', '')}"
        choices.append((display, value))

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