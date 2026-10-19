"""Bounded, read-only Clash CWL results synchronization for staff participation."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from aiohttp import web

from .providers import ProviderUnavailable, tag as normalize_tag

INTERVAL_SECONDS = 15 * 60
MAX_CLANS = 20
MAX_WARS = MAX_CLANS * 28
_CYCLE = re.compile(r"20\d\d-(?:0[1-9]|1[0-2])\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def settings_view(db, season_id: int) -> dict:
    row = db.execute(
        "SELECT * FROM participation_sync_settings WHERE season_id=?",
        (season_id,),
    ).fetchone()
    binding = db.execute(
        "SELECT cycle FROM manage_campaign_bindings WHERE season_id=?",
        (season_id,),
    ).fetchone()
    cycle = row["cycle"] if row else (binding["cycle"] if binding else None)
    status = row["status"] if row else "never"
    warning = row["warning"] if row else None
    season = db.execute("SELECT status FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row and row["last_success_at"] and status in {"complete", "partial", "preparation"}:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["last_success_at"])).total_seconds()
            if age > 30 * 60:
                if season and season["status"] == "archived":
                    status = "historical"
                    warning = "Archived CWL results are retained historical evidence"
                else:
                    status = "stale"
                    warning = "Last successful Clash refresh is over 30 minutes old"
        except ValueError:
            status = "stale"
            warning = "Clash refresh timestamp is invalid"
    return {
        "cycle": cycle,
        "cycle_source": "settings" if row else "manage_binding" if binding else "none",
        "enabled": bool(row["enabled"]) if row else False,
        "status": status,
        "warning": warning,
        "last_checked_at": row["last_checked_at"] if row else None,
        "last_success_at": row["last_success_at"] if row else None,
    }


def source_row(db, season_id: int, cycle: str | None, player_tag: str):
    if not cycle:
        return None
    return db.execute(
        "SELECT * FROM participation_source_results "
        "WHERE season_id=? AND cycle=? AND tag=?",
        (season_id, cycle, player_tag),
    ).fetchone()


def _participants(db, season_id: int, publication_id: int) -> dict:
    current = {
        row["tag"]: row for row in db.execute(
            "SELECT tag,user_id,player_name,town_hall,pool,"
            "assigned_clan_tag,assigned_clan_name FROM publication_accounts "
            "WHERE publication_id=?",
            (publication_id,),
        ).fetchall()
    }
    saved = {
        row["tag"]: row for row in db.execute(
            "SELECT * FROM participation_records WHERE season_id=?",
            (season_id,),
        ).fetchall()
    }
    return {tag: saved.get(tag) or current.get(tag) for tag in set(current) | set(saved)}


def _valid_group(group: dict, cycle: str, clan_tag: str) -> tuple[list[list[str]], list[str]]:
    if not isinstance(group, dict) or group.get("season") != cycle:
        raise ValueError("CWL group season does not match configured month")
    rounds = group.get("rounds")
    if not isinstance(rounds, list) or len(rounds) > 7:
        raise ValueError("CWL group rounds are unavailable")
    result = []
    for round_row in rounds:
        values = round_row.get("war_tags") if isinstance(round_row, dict) else None
        if not isinstance(values, list):
            raise ValueError("CWL round war tags are unavailable")
        tags = []
        for raw in values:
            if raw == "#0":
                continue
            tags.append(normalize_tag(raw))
        result.append(list(dict.fromkeys(tags)))
    clans = group.get("clans")
    if not isinstance(clans, list):
        raise ValueError("CWL group clan roster is unavailable")
    matching = [clan for clan in clans if isinstance(clan, dict) and clan.get("tag") == clan_tag]
    if len(matching) != 1 or not isinstance(matching[0].get("members"), list):
        raise ValueError("CWL hosting clan is missing from its league group")
    members = [normalize_tag(member["tag"]) for member in matching[0]["members"]]
    return result, list(dict.fromkeys(members))


def _war_state(raw) -> str | None:
    value = str(raw or "").upper().replace("_", "")
    return {
        "PREPARATION": "PREPARATION",
        "WAR": "WAR",
        "INWAR": "WAR",
        "ENDED": "ENDED",
        "WARENDED": "ENDED",
    }.get(value)


def _side_observation(war: dict, clan_tag: str) -> dict | None:
    state = _war_state(war.get("state"))
    if state is None:
        return None
    side = None
    for key in ("clan", "opponent"):
        candidate = war.get(key)
        if isinstance(candidate, dict) and candidate.get("tag") == clan_tag:
            side = candidate
            break
    if side is None or not isinstance(side.get("members"), list):
        return None
    members = {}
    for member in side["members"]:
        try:
            player_tag = normalize_tag(member["tag"])
        except (KeyError, ValueError, TypeError):
            continue
        attacks = member.get("attacks")
        if attacks is None:
            members[player_tag] = {"attacks": None, "stars": None}
            continue
        if not isinstance(attacks, list) or len(attacks) > 1:
            continue
        stars = []
        for attack in attacks:
            value = attack.get("stars") if isinstance(attack, dict) else None
            if type(value) is not int or not 0 <= value <= 3:
                stars = []
                break
            stars.append(value)
        if len(stars) != len(attacks):
            members[player_tag] = {"attacks": None, "stars": None}
        else:
            members[player_tag] = {
                "attacks": len(attacks),
                "stars": sum(stars),
            }
    return {"state": state, "ended": state == "ENDED", "members": members}


async def _fetch_groups(providers, clans: list[str], cycle: str):
    semaphore = asyncio.Semaphore(3)

    async def one(clan_tag):
        async with semaphore:
            try:
                group = await asyncio.wait_for(providers.league_group(clan_tag), timeout=10)
                return clan_tag, (*_valid_group(group, cycle, clan_tag), str(group.get("state") or "").upper()), None
            except (ProviderUnavailable, ValueError, KeyError, TypeError, TimeoutError) as exc:
                return clan_tag, None, "season_mismatch" if isinstance(exc, ValueError) and "season" in str(exc) else "unavailable"

    return await asyncio.gather(*(one(tag) for tag in clans))


async def _fetch_wars(providers, tags: list[str]):
    semaphore = asyncio.Semaphore(3)

    async def one(war_tag):
        async with semaphore:
            try:
                war = await asyncio.wait_for(providers.league_war(war_tag), timeout=10)
                if not isinstance(war, dict):
                    raise ValueError("War unavailable")
                return war_tag, war, None
            except (ProviderUnavailable, ValueError, KeyError, TypeError, TimeoutError):
                return war_tag, None, "unavailable"

    tasks = [asyncio.create_task(one(tag)) for tag in tags]
    results = []
    try:
        for completed in asyncio.as_completed(tasks, timeout=180):
            try:
                results.append(await completed)
            except TimeoutError:
                break
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    fetched = {tag for tag, _, _ in results}
    results.extend((tag, None, "timeout") for tag in tags if tag not in fetched)
    return results


def _group_rows(db, season_id: int, cycle: str):
    rows = db.execute(
        "SELECT * FROM participation_group_observations WHERE season_id=? AND cycle=?",
        (season_id, cycle),
    ).fetchall()
    return {row["clan_tag"]: row for row in rows}


def _war_rows(db, season_id: int, cycle: str):
    rows = db.execute(
        "SELECT * FROM participation_war_observations WHERE season_id=? AND cycle=?",
        (season_id, cycle),
    ).fetchall()
    return {(row["war_tag"], row["clan_tag"]): row for row in rows}


def _aggregate_for_account(
    identity, group, wars: dict, fresh_groups: set[str], fresh_wars: set[str],
    prior, cycle: str,
):
    clan = identity["assigned_clan_tag"]
    if not clan:
        return None, None, "unassigned", False, None, "No published hosting clan"
    if group is None:
        if prior:
            return prior["attacks"], prior["stars"], "stale", False, prior["checked_at"], "League group unavailable; previous result retained"
        return None, None, "unavailable", False, None, "League group unavailable"
    rounds = json.loads(group["war_tags_json"])
    group_members = set(json.loads(group["members_json"])) if group["members_json"] else set()
    registered = identity["tag"] in group_members
    if not rounds:
        return None, None, "preparation", False, group["observed_at"], "CWL rounds have not been announced"
    attacks_total = stars_total = 0
    member_seen = False
    known_rounds = 0
    all_ended = True
    stale = clan not in fresh_groups
    missing = False
    preparing = False
    member_missing = False
    checked = None
    seen_wars = set()
    for round_tags in rounds:
        matches = [
            wars[(war_tag, clan)] for war_tag in round_tags
            if (war_tag, clan) in wars
        ]
        if len(matches) != 1:
            all_ended = False
            missing = True
            continue
        war = matches[0]
        if war["war_tag"] in seen_wars:
            all_ended = False
            missing = True
            continue
        seen_wars.add(war["war_tag"])
        checked = max(checked, war["observed_at"]) if checked else war["observed_at"]
        if (war["war_tag"], clan) not in fresh_wars:
            stale = True
        if not war["ended"]:
            all_ended = False
        state = war["state"]
        if state == "PREPARATION":
            preparing = True
            continue
        members = json.loads(war["attacks_json"])
        member = members.get(identity["tag"])
        if member and member.get("attacks") is not None and member.get("stars") is not None:
            member_seen = True
            known_rounds += 1
            attacks_total += member["attacks"]
            stars_total += member["stars"]
        elif member is None and registered:
            # The league group confirms registration. Absence from this war's
            # 15-person side is a bench/rotation, so the observed round is zero.
            known_rounds += 1
        else:
            member_missing = True
    if checked is None:
        checked = group["observed_at"]
    if not known_rounds:
        attacks = stars = None
    elif attacks_total > 7 or stars_total > 21 or stars_total > attacks_total * 3:
        attacks, stars = None, None
        missing = True
    else:
        attacks, stars = attacks_total, stars_total
    complete = (
        all_ended and not missing and not member_missing and bool(rounds)
        and registered
        and str(group["state"]).upper().replace("_", "") == "ENDED"
    )
    if stale:
        status, warning = "stale", "Cached CWL observations used; results are not freshly verified"
    elif complete:
        status, warning = "complete", None
    elif preparing and not member_seen:
        status, warning = "preparation", "CWL wars have not all started"
    else:
        status, warning = "partial", "CWL wars are in progress or unavailable"
    if not registered and not member_seen:
        status, warning = "no_data", "Player is not in the league-group roster or observed war rosters"
    elif not registered and not stale:
        status, warning = "partial", "Player was observed in a war but not the league-group roster"
    return attacks, stars, status, complete, checked, warning


async def sync_season(app, season_id: int, *, force: bool = False) -> dict:
    """Fetch outside SQLite transactions; commit only to the same draft snapshot."""
    from .app import _fail

    locks = app["participation_sync_locks"]
    lock = locks.setdefault(season_id, asyncio.Lock())
    async with lock:
        store = app["store"]
        with store.tx() as db:
            season = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
            if season is None:
                _fail(404, "Season not found")
            if season["status"] != "draft":
                _fail(423, "Archived season is read-only")
            settings = settings_view(db, season_id)
            if not settings["cycle"]:
                _fail(409, "Select a CWL month before syncing")
            if not force and not settings["enabled"]:
                return {"sync": settings, "updated_accounts": 0}
            latest = db.execute(
                "SELECT id,version FROM roster_publications "
                "WHERE season_id=? ORDER BY version DESC LIMIT 1",
                (season_id,),
            ).fetchone()
            if latest is None:
                _fail(409, "Publish a roster before syncing results")
            identities = _participants(db, season_id, latest["id"])
            clans = sorted({
                row["assigned_clan_tag"] for row in identities.values()
                if row["assigned_clan_tag"]
            })
            cycle = settings["cycle"]
            publication_version = latest["version"]
        if len(clans) > MAX_CLANS:
            _fail(400, "Too many hosting clans for one sync")
        group_fetches = await _fetch_groups(app["providers"], clans, cycle)
        fresh_groups = set()
        groups_to_write = []
        failures = []
        for clan_tag, result, error in group_fetches:
            if result is None:
                failures.append(error or "unavailable")
                continue
            rounds, members, state = result
            groups_to_write.append((clan_tag, state, rounds, members))
            fresh_groups.add(clan_tag)
        with store.tx() as db:
            cached_groups = _group_rows(db, season_id, cycle)
            cached_fetches = {
                row["war_tag"]: row for row in db.execute(
                    "SELECT * FROM participation_war_fetches "
                    "WHERE season_id=? AND cycle=?",
                    (season_id, cycle),
                ).fetchall()
            }
        all_tags = set()
        for clan_tag in clans:
            fresh = next((row for row in groups_to_write if row[0] == clan_tag), None)
            if fresh:
                rounds = fresh[2]
            elif clan_tag in cached_groups:
                rounds = json.loads(cached_groups[clan_tag]["war_tags_json"])
            else:
                rounds = []
            for round_tags in rounds:
                all_tags.update(round_tags)
        if len(all_tags) > MAX_WARS:
            _fail(400, "Too many CWL wars for one sync")
        to_fetch = []
        for war_tag in sorted(all_tags):
            cached = cached_fetches.get(war_tag)
            scanned = set(json.loads(cached["scanned_clans_json"])) if cached else set()
            if cached and cached["ended"] and set(clans) <= scanned:
                continue
            to_fetch.append(war_tag)
        war_fetches = await _fetch_wars(app["providers"], to_fetch)
        fresh_wars = set()
        wars_to_write = []
        for war_tag, war, error in war_fetches:
            if war is None:
                failures.append(error or "unavailable")
                continue
            for clan_tag in clans:
                side = _side_observation(war, clan_tag)
                if side is not None:
                    wars_to_write.append((war_tag, clan_tag, side))
        stamp = now()
        with store.tx() as db:
            season = db.execute("SELECT status FROM seasons WHERE id=?", (season_id,)).fetchone()
            latest = db.execute(
                "SELECT version FROM roster_publications "
                "WHERE season_id=? ORDER BY version DESC LIMIT 1",
                (season_id,),
            ).fetchone()
            current = settings_view(db, season_id)
            if (
                season is None or season["status"] != "draft"
                or latest is None or latest["version"] != publication_version
                or current["cycle"] != cycle
                or current["enabled"] != settings["enabled"]
            ):
                _fail(409, "Season, publication, or sync month changed during refresh")
            for clan_tag, state, rounds, members in groups_to_write:
                db.execute(
                    "INSERT INTO participation_group_observations("
                    "season_id,cycle,clan_tag,season,state,war_tags_json,members_json,observed_at"
                    ") VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(season_id,cycle,clan_tag) DO UPDATE SET "
                    "season=excluded.season,state=excluded.state,"
                    "war_tags_json=excluded.war_tags_json,"
                    "members_json=excluded.members_json,observed_at=excluded.observed_at",
                    (season_id, cycle, clan_tag, cycle, state, json.dumps(rounds), json.dumps(members), stamp),
                )
            for war_tag, war, error in war_fetches:
                if war is None:
                    continue
                db.execute(
                    "INSERT INTO participation_war_fetches("
                    "season_id,cycle,war_tag,ended,scanned_clans_json,observed_at"
                    ") VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(season_id,cycle,war_tag) DO UPDATE SET "
                    "ended=excluded.ended,scanned_clans_json=excluded.scanned_clans_json,"
                    "observed_at=excluded.observed_at",
                    (
                        season_id, cycle, war_tag,
                        int(
                            _war_state(war.get("state")) == "ENDED"
                            and all(
                                isinstance(war.get(key), dict)
                                and isinstance(war[key].get("members"), list)
                                and bool(war[key]["members"])
                                and isinstance(war[key].get("tag"), str)
                                for key in ("clan", "opponent")
                            )
                        ),
                        json.dumps(clans), stamp,
                    ),
                )
            for war_tag, clan_tag, side in wars_to_write:
                old = db.execute(
                    "SELECT ended FROM participation_war_observations "
                    "WHERE season_id=? AND cycle=? AND war_tag=? AND clan_tag=?",
                    (season_id, cycle, war_tag, clan_tag),
                ).fetchone()
                if old and old["ended"] and not side["ended"]:
                    failures.append("war_state_regression")
                    continue
                fresh_wars.add((war_tag, clan_tag))
                db.execute(
                    "INSERT INTO participation_war_observations("
                    "season_id,cycle,war_tag,clan_tag,state,ended,attacks_json,observed_at"
                    ") VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(season_id,cycle,war_tag,clan_tag) DO UPDATE SET "
                    "state=excluded.state,ended=excluded.ended,"
                    "attacks_json=excluded.attacks_json,observed_at=excluded.observed_at",
                    (
                        season_id, cycle, war_tag, clan_tag, side["state"],
                        int(side["ended"]), json.dumps(side["members"], sort_keys=True), stamp,
                    ),
                )
            group_rows = _group_rows(db, season_id, cycle)
            war_rows = _war_rows(db, season_id, cycle)
            updated = 0
            statuses = set()
            for player_tag, identity in identities.items():
                prior = db.execute(
                    "SELECT * FROM participation_source_results "
                    "WHERE season_id=? AND cycle=? AND tag=?",
                    (season_id, cycle, player_tag),
                ).fetchone()
                values = _aggregate_for_account(
                    identity, group_rows.get(identity["assigned_clan_tag"]),
                    war_rows, fresh_groups, fresh_wars, prior, cycle,
                )
                attacks, stars, status, complete, checked_at, warning = values
                statuses.add(status)
                if attacks is not None or stars is not None:
                    existing_identity = db.execute(
                        "SELECT 1 FROM participation_records WHERE season_id=? AND tag=?",
                        (season_id, player_tag),
                    ).fetchone()
                    if existing_identity is None:
                        db.execute(
                            "INSERT INTO participation_records("
                            "season_id,tag,recorded_publication_version,user_id,"
                            "player_name,town_hall,pool,assigned_clan_tag,assigned_clan_name,"
                            "attacks,stars,notes,revision,updated_by,updated_at,"
                            "attacks_override,stars_override"
                            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                season_id, player_tag, publication_version,
                                identity["user_id"], identity["player_name"],
                                identity["town_hall"], identity["pool"],
                                identity["assigned_clan_tag"], identity["assigned_clan_name"],
                                None, None, "", 0, "sync", stamp, 0, 0,
                            ),
                        )
                if prior is None or (
                    prior["attacks"], prior["stars"], prior["status"],
                    prior["complete"], prior["checked_at"], prior["warning"]
                ) != (attacks, stars, status, int(complete), checked_at, warning):
                    updated += 1
                db.execute(
                    "INSERT INTO participation_source_results("
                    "season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning"
                    ") VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(season_id,cycle,tag) DO UPDATE SET "
                    "attacks=excluded.attacks,stars=excluded.stars,status=excluded.status,"
                    "complete=excluded.complete,checked_at=excluded.checked_at,"
                    "warning=excluded.warning",
                    (season_id, cycle, player_tag, attacks, stars, status, int(complete), checked_at, warning),
                )
            if not clans:
                overall = "unassigned"
                warning = "No published hosting clans to query"
            elif "season_mismatch" in failures:
                overall = "season_mismatch"
                warning = "Clash CWL month differs from the selected month"
            elif failures or "stale" in statuses:
                overall = "stale" if group_rows else "unavailable"
                warning = "Some Clash CWL data could not be refreshed; cached results are marked stale"
            elif statuses == {"complete"}:
                overall, warning = "complete", None
            elif "partial" in statuses or "no_data" in statuses:
                overall, warning = "partial", "CWL observations are incomplete"
            else:
                overall, warning = "preparation", "CWL wars have not all started"
            db.execute(
                "INSERT INTO participation_sync_settings("
                "season_id,cycle,enabled,status,warning,last_checked_at,last_success_at,"
                "updated_by,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(season_id) DO UPDATE SET "
                "status=excluded.status,warning=excluded.warning,"
                "last_checked_at=excluded.last_checked_at,"
                "last_success_at=COALESCE(excluded.last_success_at,participation_sync_settings.last_success_at)",
                (
                    season_id, cycle, int(current["enabled"]), overall, warning,
                    stamp, stamp if not failures and clans and (fresh_wars or not all_tags) else None,
                    "sync", stamp,
                ),
            )
            result = settings_view(db, season_id)
        return {"sync": result, "updated_accounts": updated}


async def sync_settings(request):
    from .app import _fail, _json, _require, _season, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"cycle", "enabled"}:
        _fail(400, "Expected cycle and enabled")
    cycle = body["cycle"]
    enabled = body["enabled"]
    if not isinstance(cycle, str) or not _CYCLE.fullmatch(cycle):
        _fail(400, "Cycle must be YYYY-MM")
    if type(enabled) is not bool:
        _fail(400, "Enabled must be a boolean")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Archived season is read-only")
        prior = settings_view(db, sid)
        stamp = now()
        changed_cycle = prior["cycle"] != cycle
        db.execute(
            "INSERT INTO participation_sync_settings("
            "season_id,cycle,enabled,status,warning,last_checked_at,last_success_at,"
            "updated_by,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(season_id) DO UPDATE SET "
            "cycle=excluded.cycle,enabled=excluded.enabled,"
            "status=CASE WHEN cycle<>excluded.cycle THEN 'never' ELSE status END,"
            "warning=CASE WHEN cycle<>excluded.cycle THEN NULL ELSE warning END,"
            "last_checked_at=CASE WHEN cycle<>excluded.cycle THEN NULL ELSE last_checked_at END,"
            "last_success_at=CASE WHEN cycle<>excluded.cycle THEN NULL ELSE last_success_at END,"
            "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (
                sid, cycle, int(enabled),
                "never" if changed_cycle else prior["status"],
                None if changed_cycle else prior["warning"],
                None if changed_cycle else prior["last_checked_at"],
                None if changed_cycle else prior["last_success_at"],
                session["user_id"], stamp,
            ),
        )
        result = settings_view(db, sid)
    return web.json_response({"sync": result})


async def force_sync(request):
    from .app import _require, _sid

    _require(request, "editor")
    result = await sync_season(request.app, _sid(request), force=True)
    return web.json_response(result)


async def _worker(app):
    try:
        while True:
            await asyncio.sleep(INTERVAL_SECONDS)
            with app["store"].tx() as db:
                season_ids = [
                    row["season_id"] for row in db.execute(
                        "SELECT s.season_id FROM participation_sync_settings s "
                        "JOIN seasons x ON x.id=s.season_id "
                        "WHERE s.enabled=1 AND x.status='draft'"
                    ).fetchall()
                ]
            for season_id in season_ids:
                try:
                    await sync_season(app, season_id)
                except Exception:
                    # One season or provider outage must not stop later cycles.
                    continue
    except asyncio.CancelledError:
        raise


async def lifecycle(app):
    task = asyncio.create_task(_worker(app), name="cwl-participation-sync")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def routes():
    from .app import API

    return [
        web.post(API + "/seasons/{season_id}/participation/sync-settings", sync_settings),
        web.post(API + "/seasons/{season_id}/participation/sync", force_sync),
    ]
