"""Staff results for current signups, with explicitly requested historical records."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from aiohttp import web

from .providers import tag as normalize_tag
from utils.cwl_working_roster import working_accounts, account_token
from .participation_sync import settings_view, source_row

IDENTITY_FIELDS = (
    "user_id", "player_name", "town_hall", "pool",
    "assigned_clan_tag", "assigned_clan_name",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest(db, season_id: int):
    return db.execute(
        "SELECT id,version FROM roster_publications "
        "WHERE withdrawn_at IS NULL AND season_id=? ORDER BY version DESC LIMIT 1",
        (season_id,),
    ).fetchone()


def _published_account(db, publication_id: int, player_tag: str):
    return db.execute(
        "SELECT tag,user_id,player_name,town_hall,pool,"
        "assigned_clan_tag,assigned_clan_name FROM publication_accounts "
        "WHERE publication_id=? AND tag=?",
        (publication_id, player_tag),
    ).fetchone()


def _record(db, season_id: int, player_tag: str):
    return db.execute(
        "SELECT * FROM participation_records WHERE season_id=? AND tag=?",
        (season_id, player_tag),
    ).fetchone()


def _source(db, season_id: int, cycle: str | None, player_tag: str):
    return source_row(db, season_id, cycle, player_tag)


def _account_view(snapshot, saved=None, source=None, *, archived=False):
    identity = saved if saved is not None else snapshot
    in_latest = snapshot is not None
    roster_changed = bool(
        saved is not None and (
            snapshot is None or any(
                saved[field] != snapshot[field] for field in IDENTITY_FIELDS
            )
        )
    )
    attacks_override = bool(saved["attacks_override"]) if saved is not None else False
    stars_override = bool(saved["stars_override"]) if saved is not None else False
    source_attacks = source["attacks"] if source is not None else None
    source_stars = source["stars"] if source is not None else None
    attacks = saved["attacks"] if attacks_override else source_attacks
    stars = saved["stars"] if stars_override else source_stars
    source_status = source["status"] if source is not None else "never"
    source_checked = source["checked_at"] if source is not None else None
    if source_checked:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(source_checked)).total_seconds()
            if age > 30 * 60 and source_status in {"complete", "partial", "preparation", "no_data"}:
                source_status = "historical" if archived else "stale"
        except (TypeError, ValueError):
            source_status = "stale"
    staff_update = saved is not None and saved["updated_by"] != "sync"
    return {
        "tag": identity["tag"],
        # Exact Discord identity already linked to this saved signup.
        "user_id": identity["user_id"],
        "player_name": identity["player_name"],
        "town_hall": identity["town_hall"],
        "pool": identity["pool"],
        "assigned_clan_tag": identity["assigned_clan_tag"],
        "assigned_clan_name": identity["assigned_clan_name"],
        "attacks": attacks,
        "stars": stars,
        "notes": saved["notes"] if saved is not None else "",
        "revision": saved["revision"] if saved is not None else 0,
        "updated_by": saved["updated_by"] if staff_update else None,
        "updated_at": saved["updated_at"] if staff_update else None,
        "recorded_publication_version": (
            saved["recorded_publication_version"] if saved is not None else None
        ),
        "in_latest_publication": in_latest,
        "roster_changed": roster_changed,
        "source_attacks": source_attacks,
        "source_stars": source_stars,
        "source_status": source_status,
        "source_complete": bool(source["complete"]) if source is not None else False,
        "source_checked_at": source_checked,
        "source_warning": source["warning"] if source is not None else None,
        "attacks_override": attacks_override,
        "stars_override": stars_override,
        "attacks_origin": "manual" if attacks_override else "source" if source_attacks is not None else "unknown",
        "stars_origin": "manual" if stars_override else "source" if source_stars is not None else "unknown",
    }


def historical_account_view(snapshot, saved=None, source=None, *, archived=False):
    identity = saved if saved is not None else snapshot
    if source is not None and source['roster_token'] is not None and source['roster_token'] != account_token(identity):
        source = None
    return _account_view(snapshot, saved, source, archived=archived)


def current_account_view(snapshot, saved=None, source=None, *, archived=False):
    mismatch = saved is not None and account_token(saved) != account_token(snapshot)
    source_matches = source is not None and (
        source['roster_token'] == account_token(snapshot) or
        (source['roster_token'] is None and not mismatch and saved is not None)
    )
    row = _account_view(snapshot, saved, source if source_matches else None, archived=archived)
    row.update(snapshot)
    row['in_current_roster'] = True
    row['roster_token'] = account_token(snapshot)
    row['roster_changed'] = mismatch
    if mismatch:
        row.update(attacks=None, stars=None, attacks_origin='unknown', stars_origin='unknown')
        row['previous_results'] = {
            key: saved[key] for key in (
                'user_id', 'pool', 'assigned_clan_name', 'assigned_clan_tag',
                'attacks', 'stars',
            )
        }
    return row


def _validate(body, fail):
    required = {"publication_version", "revision", "attacks", "stars", "notes"}
    if not required <= set(body) or set(body) - required - {"source_checked_at", "roster_token"}:
        fail(400, "Expected publication_version, revision, attacks, stars, and notes")
    publication_version = body["publication_version"]
    revision = body["revision"]
    attacks = body["attacks"]
    stars = body["stars"]
    notes = body["notes"]
    checked = body.get("source_checked_at")
    if type(publication_version) is not int or publication_version < 0:
        fail(400, "Invalid publication version")
    if type(revision) is not int or revision < 0:
        fail(400, "Invalid participation revision")
    if attacks is not None and (type(attacks) is not int or not 0 <= attacks <= 7):
        fail(400, "Attacks must be 0–7 or null")
    if stars is not None and (type(stars) is not int or not 0 <= stars <= 21):
        fail(400, "Stars must be 0–21 or null")
    if attacks is not None and stars is not None and stars > attacks * 3:
        fail(400, "Stars cannot exceed three per recorded attack")
    if not isinstance(notes, str) or len(notes) > 2000:
        fail(400, "Notes must be text of at most 2000 characters")
    if checked is not None and not isinstance(checked, str):
        fail(400, "Invalid source timestamp")
    return publication_version, revision, attacks, stars, notes, checked


def _context(db, season_id: int, player_tag: str, publication_version: int, fail, roster_token=None, *, reconcile=False):
    season = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if season is None:
        fail(404, "Season not found")
    if season["status"] != "draft":
        fail(423, "Archived season is read-only")
    latest = _latest(db, season_id)
    snapshot = working_accounts(db, season_id).get(player_tag)
    if snapshot is None:
        fail(404, "This account is no longer signed up for this season")
    if roster_token is not None:
        if not isinstance(roster_token, str) or roster_token != account_token(snapshot):
            fail(409, "Signup or assignment changed; refresh before saving")
    else:
        published = _published_account(db, latest['id'], player_tag) if latest else None
        if latest is None or latest['version'] != publication_version or published is None or account_token(published) != account_token(snapshot):
            fail(409, "Roster changed; refresh before saving")
    saved = _record(db, season_id, player_tag)
    if saved is not None and account_token(saved) != account_token(snapshot) and not reconcile:
        fail(409, "Saved results belong to a previous assignment. Refresh Clash results and use synced results before editing.")
    settings = settings_view(db, season_id)
    source = _source(db, season_id, settings["cycle"], player_tag)
    return latest or {"version": 0}, snapshot, saved, source


def _audit(db, season_id, player_tag, actor, before, after, stamp):
    db.execute(
        "INSERT INTO participation_audit("
        "season_id,tag,actor_id,revision,before_json,after_json,created_at"
        ") VALUES (?,?,?,?,?,?,?)",
        (
            season_id, player_tag, actor, after["revision"],
            json.dumps(dict(before), sort_keys=True) if before is not None else None,
            json.dumps(dict(after), sort_keys=True), stamp,
        ),
    )


async def get_participation(request):
    from .app import _require, _season, _sid, _store

    _require(request, "editor")
    season_id = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, season_id)
        latest = _latest(db, season_id)
        settings = settings_view(db, season_id)
        history = request.query.get('source', 'current') == 'history'
        if request.query.get('source', 'current') not in {'current', 'history'}:
            raise web.HTTPBadRequest(text="Choose current results or history")
        current = working_accounts(db, season_id)
        saved = {
            row["tag"]: row for row in db.execute(
                "SELECT * FROM participation_records WHERE season_id=?",
                (season_id,),
            ).fetchall()
        }
        published_tags = {row[0] for row in db.execute("SELECT tag FROM publication_accounts WHERE publication_id=?", (latest["id"] if latest else None,))}
        accounts = [
            (historical_account_view if history else current_account_view)(
                current.get(player_tag), saved.get(player_tag),
                _source(db, season_id, settings["cycle"], player_tag),
                archived=season["status"] == "archived",
            )
            for player_tag in sorted(set(saved) if history else set(current))
        ]
        for account in accounts:
            account["in_latest_publication"] = account["tag"] in published_tags
    return web.json_response({
        "publication_version": latest["version"] if latest else 0,
        "roster_source": "history" if history else "current_signups",
        "historical_accounts_count": len(set(saved) - set(current)),
        "sync": settings,
        "accounts": accounts,
    })


async def patch_participation(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    publication_version, revision, attacks, stars, notes, checked = _validate(body, _fail)
    season_id = _sid(request)
    try:
        player_tag = normalize_tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid player tag")
    with _store(request).tx() as db:
        latest, snapshot, saved, source = _context(
            db, season_id, player_tag, publication_version, _fail, body.get("roster_token"),
        )
        if "source_checked_at" in body and checked != (source["checked_at"] if source else None):
            _fail(409, "Synced results changed; refresh before saving")
        current_revision = saved["revision"] if saved is not None else 0
        if revision != current_revision:
            _fail(409, "Participation changed; refresh before saving")
        current = current_account_view(snapshot, saved, source)
        attack_changed = attacks != current["attacks"]
        star_changed = stars != current["stars"]
        attack_override = attack_changed or bool(saved["attacks_override"]) if saved is not None else attack_changed
        star_override = star_changed or bool(saved["stars_override"]) if saved is not None else star_changed
        manual_attacks = attacks if attack_changed else saved["attacks"] if saved is not None else None
        manual_stars = stars if star_changed else saved["stars"] if saved is not None else None
        unchanged = saved is not None and (
            saved["attacks"], saved["stars"], saved["notes"],
            bool(saved["attacks_override"]), bool(saved["stars_override"])
        ) == (manual_attacks, manual_stars, notes, attack_override, star_override)
        if unchanged:
            account = current
        else:
            stamp = _now()
            before = saved
            if saved is None:
                db.execute(
                    "INSERT INTO participation_records("
                    "season_id,tag,recorded_publication_version,user_id,"
                    "player_name,town_hall,pool,assigned_clan_tag,assigned_clan_name,"
                    "attacks,stars,notes,revision,updated_by,updated_at,"
                    "attacks_override,stars_override"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        season_id, player_tag, latest["version"],
                        snapshot["user_id"], snapshot["player_name"],
                        snapshot["town_hall"], snapshot["pool"],
                        snapshot["assigned_clan_tag"], snapshot["assigned_clan_name"],
                        manual_attacks, manual_stars, notes, 1,
                        session["user_id"], stamp,
                        int(attack_override), int(star_override),
                    ),
                )
            else:
                result = db.execute(
                    "UPDATE participation_records SET attacks=?,stars=?,notes=?,"
                    "attacks_override=?,stars_override=?,revision=revision+1,"
                    "updated_by=?,updated_at=? "
                    "WHERE season_id=? AND tag=? AND revision=?",
                    (
                        manual_attacks, manual_stars, notes,
                        int(attack_override), int(star_override),
                        session["user_id"], stamp, season_id, player_tag, revision,
                    ),
                )
                if result.rowcount != 1:
                    _fail(409, "Participation changed; refresh before saving")
            saved = _record(db, season_id, player_tag)
            _audit(db, season_id, player_tag, session["user_id"], before, saved, stamp)
            account = current_account_view(snapshot, saved, source)
    return web.json_response({"account": account})


async def reset_to_source(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    required = {"publication_version", "revision", "source_checked_at"}
    if not required <= set(body) or set(body) - required - {"roster_token"}:
        _fail(400, "Expected publication_version, revision, and source_checked_at")
    publication_version = body["publication_version"]
    revision = body["revision"]
    checked = body["source_checked_at"]
    if type(publication_version) is not int or publication_version < 0:
        _fail(400, "Invalid publication version")
    if type(revision) is not int or revision < 0:
        _fail(400, "Invalid participation revision")
    if checked is not None and not isinstance(checked, str):
        _fail(400, "Invalid source timestamp")
    sid = _sid(request)
    try:
        player_tag = normalize_tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid player tag")
    with _store(request).tx() as db:
        latest, snapshot, saved, source = _context(
            db, sid, player_tag, publication_version, _fail, body.get("roster_token"), reconcile=True,
        )
        if checked != (source["checked_at"] if source else None):
            _fail(409, "Synced results changed; refresh before resetting")
        if source is None or source["roster_token"] != account_token(snapshot) or (source["attacks"] is None and source["stars"] is None):
            _fail(409, "No synced results are available to use")
        current_revision = saved["revision"] if saved is not None else 0
        if revision != current_revision:
            _fail(409, "Participation changed; refresh before resetting")
        if saved is None or not (saved["attacks_override"] or saved["stars_override"] or account_token(saved) != account_token(snapshot)):
            account = current_account_view(snapshot, saved, source)
        else:
            stamp = _now()
            before = saved
            result = db.execute(
                "UPDATE participation_records SET attacks=NULL,stars=NULL,"
                "attacks_override=0,stars_override=0,revision=revision+1,"
                "updated_by=?,updated_at=?,user_id=?,player_name=?,town_hall=?,pool=?,assigned_clan_tag=?,assigned_clan_name=? WHERE season_id=? AND tag=? AND revision=?",
                (session["user_id"], stamp, *(snapshot[key] for key in IDENTITY_FIELDS), sid, player_tag, revision),
            )
            if result.rowcount != 1:
                _fail(409, "Participation changed; refresh before resetting")
            saved = _record(db, sid, player_tag)
            _audit(db, sid, player_tag, session["user_id"], before, saved, stamp)
            account = current_account_view(snapshot, saved, source)
    return web.json_response({"account": account})


def routes():
    from .app import API

    return [
        web.get(API + "/seasons/{season_id}/participation", get_participation),
        web.patch(
            API + "/seasons/{season_id}/participation/{tag}",
            patch_participation,
        ),
        web.post(
            API + "/seasons/{season_id}/participation/{tag}/reset-to-source",
            reset_to_source,
        ),
    ]
