"""Read-only, fail-closed identity and Clash API adapters."""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import aiohttp
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from utils.mongo_routes import collection_for, load_routes
from utils.account_links import lookup_links, LinksUnavailable
from utils.clash_links import _lookup_shared_links
from utils.clashperk_links import lookup as _lookup_clashperk_links


TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,15}$")


def _clan_badge_url(clan):
    """Accept only Clash's HTTPS badge assets from the official asset host."""
    badges = clan.get("badgeUrls")
    if not isinstance(badges, dict):
        return None
    for size in ("medium", "small"):
        value = badges.get(size)
        if not isinstance(value, str):
            continue
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if (parsed.scheme == "https" and parsed.netloc == "api-assets.clashofclans.com"
                and parsed.path.startswith("/badges/") and not parsed.query and not parsed.fragment):
            return value
    return None


def tag(value):
    result = str(value or "").strip().upper().replace("O", "0")
    if result and not result.startswith("#"):
        result = "#" + result
    if not TAG_RE.fullmatch(result):
        raise ValueError("Invalid Clash tag")
    return result


def _coc_state(value):
    """Normalize Clash API camelCase and enum states for sync consumers."""
    if not isinstance(value, str):
        return value
    compact = re.sub(r"[^a-z]", "", value.casefold())
    known = {
        "preparation": "PREPARATION", "war": "WAR", "inwar": "WAR",
        "ended": "ENDED", "warended": "ENDED",
        "notinwar": "NOT_IN_WAR", "groupnotfound": "GROUP_NOT_FOUND",
        "clannotfound": "CLAN_NOT_FOUND", "accessdenied": "ACCESS_DENIED",
        "inmatchmaking": "IN_MATCHMAKING", "enterwar": "ENTER_WAR",
        "matched": "MATCHED",
    }
    return known.get(compact, value.upper())


class ProviderUnavailable(Exception):
    pass


FAMILY_TYPES = ("FWA", "Tactical", "Flexible Fun", "Competitive")
WEIGHTS_URL = "https://www.fwastats.com/Weights.json"
WEIGHTS_CACHE_SECONDS = 15 * 60
WEIGHTS_MAX_BYTES = 8 * 1024 * 1024


class LiveProviders:
    def __init__(self, coc_token=None, mongo_uri=None, routes=None):
        self.coc_token = os.getenv("COC_API_TOKEN", "").strip() if coc_token is None else coc_token.strip()
        self.mongo_uri = os.getenv("MONGODB_URI", "").strip() if mongo_uri is None else mongo_uri.strip()
        self.routes = routes if routes is not None else load_routes()
        self._weights_cache = None
        self._weights_cache_until = 0.0
        self.weights_checked_at = None
        self._weights_lock = asyncio.Lock()

    async def family_clans(self):
        """Read existing bot clan directory; never initialize its write-capable wrapper."""
        if not self.mongo_uri:
            raise ProviderUnavailable("Family-clan directory is not configured")
        client = AsyncMongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
        try:
            collection = collection_for(client, "clans", routes=self.routes)
            cursor = collection.find(
                {"type": {"$in": list(FAMILY_TYPES)}},
                {"_id": 0, "tag": 1, "name": 1, "type": 1},
                max_time_ms=5000,
            )
            docs = await cursor.to_list(length=201)
            if len(docs) >= 201:
                raise ProviderUnavailable("Family-clan directory exceeds supported size")
        except (PyMongoError, TimeoutError) as exc:
            raise ProviderUnavailable("Family-clan directory unavailable") from exc
        finally:
            await client.close()
        result = {}
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("type") not in FAMILY_TYPES:
                continue
            try:
                value = tag(doc.get("tag"))
            except ValueError:
                continue
            name = doc.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            result[value] = {"tag": value, "name": name.strip()}
        if not result:
            raise ProviderUnavailable("No eligible family clans found in bot directory")
        return {"source": "bot_mongo", "status": "ok", "checked_at": datetime.now(timezone.utc).isoformat(),
                "clans": sorted(result.values(), key=lambda clan: clan["name"].casefold())}

    async def weights(self, tags):
        """Read FWA Stats' public player weights once per 15-minute cache window."""
        wanted = {tag(value) for value in tags}
        if not wanted:
            return {}
        async with self._weights_lock:
            if self._weights_cache is None or time.monotonic() >= self._weights_cache_until:
                timeout = aiohttp.ClientTimeout(total=25)
                try:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(WEIGHTS_URL, headers={"Accept": "application/json"}) as response:
                            if response.status != 200 or response.content_type != "application/json":
                                raise ProviderUnavailable("FWA Stats weight feed unavailable")
                            raw = bytearray()
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                raw.extend(chunk)
                                if len(raw) > WEIGHTS_MAX_BYTES:
                                    raise ProviderUnavailable("FWA Stats weight feed exceeds size limit")
                    payload = json.loads(raw)
                except (aiohttp.ClientError, TimeoutError, UnicodeError, ValueError) as exc:
                    raise ProviderUnavailable("FWA Stats weight feed unavailable") from exc
                if not isinstance(payload, list) or not payload or len(payload) > 100_000:
                    raise ProviderUnavailable("Invalid FWA Stats weight feed")
                checked_at = datetime.now(timezone.utc).isoformat()
                index = {}
                for item in payload:
                    if not isinstance(item, dict):
                        raise ProviderUnavailable("Invalid FWA Stats weight feed")
                    try:
                        player_tag = tag(item.get("tag"))
                    except ValueError as exc:
                        raise ProviderUnavailable("Invalid FWA Stats player tag") from exc
                    weight = item.get("weight")
                    modified = item.get("lastModified")
                    if (type(weight) is not int or weight <= 0 or weight > 1_000_000_000
                            or not isinstance(modified, str) or not modified.endswith("Z")):
                        raise ProviderUnavailable("Invalid FWA Stats weight record")
                    try:
                        datetime.fromisoformat(modified.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise ProviderUnavailable("Invalid FWA Stats modification time") from exc
                    if player_tag in index:
                        raise ProviderUnavailable("Duplicate FWA Stats player tag")
                    index[player_tag] = {"weight": weight, "source_name": "FWA Stats",
                                         "source_modified_at": modified,
                                         "source_checked_at": checked_at}
                self._weights_cache = index
                self.weights_checked_at = checked_at
                self._weights_cache_until = time.monotonic() + WEIGHTS_CACHE_SECONDS
            return {player_tag: self._weights_cache[player_tag]
                    for player_tag in wanted if player_tag in self._weights_cache}

    async def _combined_links(self, **query):
        try:
            return await lookup_links(king=_lookup_shared_links, perk=_lookup_clashperk_links, **query)
        except LinksUnavailable as exc:
            raise ProviderUnavailable(str(exc)) from exc


    async def linked_owner(self, value):
        value = tag(value)
        owners = {uid for player, uid, _ in await self._combined_links(player_tags=[value]) if player == value}
        # Only auto-fill an unambiguous owner; staff can associate one manually.
        return next(iter(owners)) if len(owners) == 1 else None

    async def linked_tags(self, user_id):
        result = {}
        for value, uid, verified in await self._combined_links(discord_ids=[str(user_id)]):
            if uid == str(user_id):
                result[value] = result.get(value, False) or verified
        return result

    async def _coc(self, kind, value):
        if not self.coc_token:
            raise ProviderUnavailable("Clash API is not configured")
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"https://api.clashofclans.com/v1/{kind}/{quote(tag(value), safe='')}"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Authorization": f"Bearer {self.coc_token}"}) as response:
                    if response.status != 200:
                        raise ProviderUnavailable(f"Clash API returned {response.status}")
                    body = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise ProviderUnavailable("Clash API unavailable") from exc
        try:
            valid = isinstance(body, dict) and tag(body.get("tag")) == tag(value)
        except ValueError:
            valid = False
        if not valid:
            raise ProviderUnavailable("Invalid Clash API response")
        return body

    async def player(self, value):
        body = await self._coc("players", value)
        if not isinstance(body.get("name"), str) or not isinstance(body.get("townHallLevel"), int):
            raise ProviderUnavailable("Incomplete player data")
        clan = body.get("clan") or {}
        if not isinstance(clan, dict):
            raise ProviderUnavailable("Invalid player clan data")
        try:
            clan_tag = tag(clan["tag"]) if clan.get("tag") else None
        except ValueError as exc:
            raise ProviderUnavailable("Invalid player clan data") from exc
        return {"tag": tag(body["tag"]), "name": body["name"], "town_hall": body["townHallLevel"],
                "current_clan_tag": clan_tag,
                "current_clan_name": clan.get("name") if isinstance(clan.get("name"), str) else None,
                "current_clan_badge_url": _clan_badge_url(clan)}

    async def clan(self, value):
        body = await self._coc("clans", value)
        if not isinstance(body.get("name"), str):
            raise ProviderUnavailable("Incomplete clan data")
        return {"tag": tag(body["tag"]), "name": body["name"],
                "cwl_league": (body.get("warLeague") or {}).get("name") or "Unranked"}


    async def clan_roster(self, value):
        """Fetch and validate the current official clan member list."""
        clan_tag = tag(value)
        body = await self._coc("clans", clan_tag)
        raw = body.get("memberList")
        count = body.get("members")
        if (not isinstance(raw, list) or type(count) is not int or count != len(raw)
                or not 0 <= count <= 50 or not isinstance(body.get("name"), str)):
            raise ProviderUnavailable("Incomplete Clash clan roster")
        members = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ProviderUnavailable("Incomplete Clash clan roster member")
            try:
                player_tag = tag(item.get("tag"))
            except ValueError as exc:
                raise ProviderUnavailable("Invalid Clash clan roster member") from exc
            if player_tag in seen:
                raise ProviderUnavailable("Duplicate Clash clan roster member")
            seen.add(player_tag)
            th = item.get("townHallLevel")
            if th is not None and (type(th) is not int or not 0 < th < 100):
                raise ProviderUnavailable("Invalid Clash clan member Town Hall")
            members.append({"tag": player_tag, "name": item["name"], "town_hall": th})
        return {"tag": clan_tag, "name": body["name"], "members": members}

    async def _league_get(self, path):
        if not self.coc_token:
            raise ProviderUnavailable("Clash API is not configured")
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"https://api.clashofclans.com/v1{path}"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Authorization": f"Bearer {self.coc_token}"}) as response:
                    if response.status != 200:
                        error = ProviderUnavailable(f"Clash API returned {response.status}")
                        error.status_code = response.status
                        raise error
                    body = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise ProviderUnavailable("Clash API unavailable") from exc
        if not isinstance(body, dict):
            raise ProviderUnavailable("Invalid Clash API response")
        return body

    async def league_group(self, clan_tag):
        """Fetch a current league group, preserving API round order and #0 placeholders."""
        clan_tag = tag(clan_tag)
        body = await self._league_get(
            f"/clans/{quote(clan_tag, safe='')}/currentwar/leaguegroup"
        )
        state, season = _coc_state(body.get("state")), body.get("season")
        clans, rounds = body.get("clans"), body.get("rounds")
        if (not isinstance(state, str) or not state
                or (season is not None and not isinstance(season, str))
                or not isinstance(clans, list) or not isinstance(rounds, list)):
            raise ProviderUnavailable("Invalid Clash league-group response")
        result_clans = []
        for clan in clans:
            if not isinstance(clan, dict) or not isinstance(clan.get("name"), str):
                raise ProviderUnavailable("Invalid Clash league-group clan")
            try:
                clan_value = tag(clan.get("tag"))
            except ValueError as exc:
                raise ProviderUnavailable("Invalid Clash league-group clan tag") from exc
            members = clan.get("members", [])
            if not isinstance(members, list):
                raise ProviderUnavailable("Invalid Clash league-group members")
            result_members = []
            for member in members:
                if not isinstance(member, dict) or not isinstance(member.get("name"), str):
                    raise ProviderUnavailable("Invalid Clash league-group member")
                try:
                    member_tag = tag(member.get("tag"))
                except ValueError as exc:
                    raise ProviderUnavailable("Invalid Clash league-group member tag") from exc
                th = member.get("townHallLevel")
                if th is not None and type(th) is not int:
                    raise ProviderUnavailable("Invalid Clash league-group town hall")
                result_members.append({"tag": member_tag, "name": member["name"], "town_hall": th})
            result_clans.append({"tag": clan_value, "name": clan["name"], "members": result_members})
        result_rounds = []
        for round_data in rounds:
            if not isinstance(round_data, dict) or not isinstance(round_data.get("warTags"), list):
                raise ProviderUnavailable("Invalid Clash league-group rounds")
            war_tags = []
            for war_tag in round_data["warTags"]:
                if war_tag == "#0":
                    war_tags.append("#0")
                else:
                    try:
                        war_tags.append(tag(war_tag))
                    except ValueError as exc:
                        raise ProviderUnavailable("Invalid Clash league war tag") from exc
            result_rounds.append({"war_tags": war_tags})
        return {"tag": clan_tag, "season": season, "state": state,
                "clans": result_clans, "rounds": result_rounds,
                "checked_at": datetime.now(timezone.utc).isoformat()}

    async def league_war(self, war_tag):
        """Fetch CWL war sides; absent attack arrays remain unknown, not zero."""
        war_tag = tag(war_tag)
        body = await self._league_get(
            f"/clanwarleagues/wars/{quote(war_tag, safe='')}"
        )
        raw_state = body.get("state")
        if not isinstance(raw_state, str) or not raw_state:
            raise ProviderUnavailable("Invalid Clash league-war response")
        state = _coc_state(raw_state)
        season, team_size = body.get("season"), body.get("teamSize")
        if season is not None and not isinstance(season, str):
            raise ProviderUnavailable("Invalid Clash league-war season")
        if team_size is not None and type(team_size) is not int:
            raise ProviderUnavailable("Invalid Clash league-war team size")
        result = {"tag": war_tag, "state": state, "season": season,
                  "team_size": team_size,
                  "preparation_start_time": body.get("preparationStartTime"),
                  "start_time": body.get("startTime"), "end_time": body.get("endTime")}
        for side in ("clan", "opponent"):
            value = body.get(side)
            if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                raise ProviderUnavailable("Incomplete Clash league-war data")
            try:
                side_tag = tag(value.get("tag"))
            except ValueError as exc:
                raise ProviderUnavailable("Invalid Clash league-war clan tag") from exc
            members = value.get("members", [])
            if not isinstance(members, list):
                raise ProviderUnavailable("Invalid Clash league-war members")
            result_members = []
            for member in members:
                if not isinstance(member, dict) or not isinstance(member.get("name"), str):
                    raise ProviderUnavailable("Invalid Clash league-war member")
                try:
                    member_tag = tag(member.get("tag"))
                except ValueError as exc:
                    raise ProviderUnavailable("Invalid Clash league-war member tag") from exc
                attacks = member.get("attacks")
                if attacks is None and state in {"WAR", "ENDED"}:
                    # The API omits an empty optional attack list once battle
                    # is underway or ended; that means zero attacks. Before
                    # battle, absence means results are not ready yet.
                    attacks = []
                elif attacks is not None:
                    if not isinstance(attacks, list):
                        raise ProviderUnavailable("Invalid Clash league-war attacks")
                    normalized = []
                    for attack in attacks:
                        stars = attack.get("stars") if isinstance(attack, dict) else None
                        if type(stars) is not int or not 0 <= stars <= 3:
                            raise ProviderUnavailable("Invalid Clash league-war attack")
                        normalized.append({"stars": stars})
                    attacks = normalized
                opponent_attacks = member.get("opponentAttacks")
                if opponent_attacks is not None and (type(opponent_attacks) is not int or opponent_attacks < 0):
                    raise ProviderUnavailable("Invalid Clash league-war opponent attacks")
                th = member.get("townhallLevel")
                if th is not None and type(th) is not int:
                    raise ProviderUnavailable("Invalid Clash league-war town hall")
                result_members.append({"tag": member_tag, "name": member["name"],
                                       "town_hall": th, "attacks": attacks,
                                       "opponent_attacks": opponent_attacks})
            result[side] = {"tag": side_tag, "name": value["name"], "members": result_members}
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        return result


class FixtureProviders:
    """Clearly fictional local data, used only with explicit loopback dev mode."""

    def __init__(self, owner_id):
        self.owner_id = str(owner_id)
        self.players = {
            "#P2Y": {"tag": "#P2Y", "name": "Dev Scout", "town_hall": 16, "current_clan_tag": "#R2Y", "current_clan_name": "Fixture Family"},
            "#Q2Y": {"tag": "#Q2Y", "name": "Dev Guardian", "town_hall": 15, "current_clan_tag": "#R2Y", "current_clan_name": "Fixture Family"},
            "#G2Y": {"tag": "#G2Y", "name": "Dev Wanderer", "town_hall": 14, "current_clan_tag": "#J2Y", "current_clan_name": "Other Fixture Clan"},
        }

    async def weights(self, tags):
        fictional = {"#P2Y": 176000, "#Q2Y": 168000, "#G2Y": 159000}
        return {value: {"weight": fictional[value], "source_name": "fictional fixture",
                        "source_modified_at": "2026-10-14T00:00:00Z"}
                for value in tags if value in fictional}

    async def family_clans(self):
        return {"source": "fixture", "status": "ok", "checked_at": datetime.now(timezone.utc).isoformat(),
                "clans": [{"tag": "#R2Y", "name": "Fixture Family"}]}

    async def linked_owner(self, value):
        return self.owner_id if tag(value) in self.players else None

    async def linked_tags(self, user_id):
        return {value: True for value in self.players} if str(user_id) == self.owner_id else {}

    async def player(self, value):
        return self.players[tag(value)].copy()

    async def clan(self, value):
        value = tag(value)
        names = {"#R2Y": "Fixture Family", "#J2Y": "Other Fixture Clan", "#C2Y": "Fixture Hosting"}
        return {"tag": value, "name": names.get(value, "Fixture Clan")}

    async def clan_roster(self, value):
        clan_tag = tag(value)
        clan = await self.clan(clan_tag)
        return {**clan, "members": [{"tag": row["tag"], "name": row["name"],
                                     "town_hall": row.get("town_hall")}
                                     for row in self.players.values()
                                     if row.get("current_clan_tag") == clan_tag]}

    async def league_group(self, clan_tag):
        raise ProviderUnavailable("League data is unavailable in fixture mode")

    async def league_war(self, war_tag):
        raise ProviderUnavailable("League data is unavailable in fixture mode")
