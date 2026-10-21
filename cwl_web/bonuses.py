"""Staff bonus review decisions; never awards bonuses in Clash of Clans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from aiohttp import web

from .participation import _account_view, _latest
from .participation_sync import settings_view, source_row
from utils.cwl_working_roster import working_accounts

POLICY_KEYS = {"min_attacks", "min_stars", "cooldown_months"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _require_draft(db, season_id, fail):
    row = db.execute("SELECT status FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        fail(404, "Season not found")
    if row["status"] != "draft":
        fail(423, "Archived season is read-only")


def _meta(db, season_id):
    row = db.execute("SELECT * FROM bonus_reviews WHERE season_id=?", (season_id,)).fetchone()
    policy = {key: row[key] if row else None for key in POLICY_KEYS}
    return row["revision"] if row else 0, policy


def _ensure_meta(db, season_id):
    db.execute("INSERT OR IGNORE INTO bonus_reviews(season_id) VALUES (?)", (season_id,))


def _audit(db, season_id, actor, action, before, after):
    db.execute(
        "INSERT INTO bonus_audit(season_id,actor_id,action,before_json,after_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (season_id, actor, action, json.dumps(before, sort_keys=True) if before is not None else None,
         json.dumps(after, sort_keys=True), _now()),
    )


def _bump(db, season_id, actor):
    _ensure_meta(db, season_id)
    db.execute(
        "UPDATE bonus_reviews SET revision=revision+1,updated_by=?,updated_at=? WHERE season_id=?",
        (actor, _now(), season_id),
    )


def _months_between(earlier, later):
    return (int(later[:4]) - int(earlier[:4])) * 12 + int(later[5:7]) - int(earlier[5:7])


def _history_row(row):
    return {
        "id": row["id"], "tag": row["tag"], "player_name": row["player_name"],
        "pool": row["pool"], "clan_tag": row["clan_tag"], "clan_name": row["clan_name"],
        "cycle": row["cycle"], "publication_version": row["publication_version"],
        "attacks": row["attacks"], "stars": row["stars"], "reason": row["reason"],
        "warnings": json.loads(row["warnings_json"]),
        "confirmed_by": row["confirmed_by"], "confirmed_at": row["confirmed_at"],
        "voided_by": row["voided_by"], "voided_at": row["voided_at"],
        "void_reason": row["void_reason"],
        "record_type": "dashboard_selection_not_game_award",
    }


def _view(db, season_id, *, current_roster=False):
    season = db.execute("SELECT status FROM seasons WHERE id=?", (season_id,)).fetchone()
    if season is None:
        return None
    latest = _latest(db, season_id)
    sync = settings_view(db, season_id)
    cycle = sync["cycle"]
    revision, policy = _meta(db, season_id)
    current = {}
    if latest:
        current = {row["tag"]: row for row in db.execute(
            "SELECT tag,user_id,player_name,town_hall,pool,assigned_clan_tag,assigned_clan_name "
            "FROM publication_accounts WHERE publication_id=?", (latest["id"],),
        ).fetchall()}
    published_tags = set(current)
    if current_roster:
        current = working_accounts(db, season_id)
    saved = {row["tag"]: row for row in db.execute(
        "SELECT * FROM participation_records WHERE season_id=?", (season_id,),
    ).fetchall()}
    selections = {row["tag"]: row["reason"] for row in db.execute(
        "SELECT tag,reason FROM bonus_draft_selections WHERE season_id=?", (season_id,),
    ).fetchall()}
    slots = {row["clan_tag"]: row["slots"] for row in db.execute(
        "SELECT clan_tag,slots FROM bonus_clan_slots WHERE season_id=?", (season_id,),
    ).fetchall()}
    history_rows = db.execute(
        "SELECT * FROM bonus_confirmations WHERE season_id=? ORDER BY id DESC", (season_id,),
    ).fetchall()
    active_cycle = {}
    cycle_confirmed = []
    if cycle:
        cycle_confirmed = [dict(row) for row in db.execute(
            "SELECT id,tag,clan_tag,season_id FROM bonus_confirmations "
            "WHERE cycle=? AND voided_at IS NULL ORDER BY id",
            (cycle,),
        ).fetchall()]
        active_cycle = {row["tag"]: row["season_id"] for row in cycle_confirmed}
    active_other_cycles = [row["cycle"] for row in db.execute(
        "SELECT DISTINCT cycle FROM bonus_confirmations WHERE season_id=? "
        "AND voided_at IS NULL AND cycle<>? ORDER BY cycle",
        (season_id, cycle or ""),
    ).fetchall()]
    accounts = []
    clan_names = {}
    configured = all(policy[key] is not None for key in POLICY_KEYS)
    for player_tag in sorted(set(current) if current_roster else set(current) | set(saved)):
        account = _account_view(
            current.get(player_tag), saved.get(player_tag),
            source_row(db, season_id, cycle, player_tag),
            archived=season["status"] == "archived",
        )
        if current_roster:
            # Always display current signup identity; mismatched saved results stay
            # flagged and cannot qualify until reconciled with the actual clan.
            account.update(current[player_tag])
        clan_tag = account["assigned_clan_tag"]
        if clan_tag:
            clan_names[clan_tag] = account["assigned_clan_name"] or clan_tag
        previous = None
        if cycle:
            previous = db.execute(
                "SELECT cycle,confirmed_at,season_id,clan_tag FROM bonus_confirmations "
                "WHERE tag=? AND cycle<? AND voided_at IS NULL "
                "ORDER BY cycle DESC,id DESC LIMIT 1", (player_tag, cycle),
            ).fetchone()
        prior = dict(previous) if previous else None
        recommended = None
        reason = "Set all bonus rules to enable recommendations"
        if configured:
            recommended = True
            reason = "Meets configured dashboard rules"
            if account["attacks"] is None or account["stars"] is None:
                recommended, reason = False, "Participation results are unknown"
            elif account["attacks"] < policy["min_attacks"] or account["stars"] < policy["min_stars"]:
                recommended, reason = False, "Below configured participation threshold"
            elif prior and _months_between(prior["cycle"], cycle) < policy["cooldown_months"]:
                recommended, reason = False, "Within configured dashboard bonus cooldown"
        if not clan_tag:
            recommended, reason = False, "No recorded hosting clan"
        if player_tag in active_cycle:
            recommended, reason = False, "Already confirmed for this CWL month"
        accounts.append({
            **account, "selected": player_tag in selections,
            "reason": selections.get(player_tag, ""), "recommended": recommended,
            "eligibility_reason": reason, "last_confirmed_bonus": prior,
            "already_confirmed_this_cycle": player_tag in active_cycle,
        })
    clans = [
        {"tag": tag, "name": name, "slots": slots.get(tag)}
        for tag, name in sorted(clan_names.items(), key=lambda item: (item[1].lower(), item[0]))
    ]
    return {
        "cycle": cycle, "cycle_source": sync["cycle_source"], "sync": sync,
        "season_status": season["status"],
        "publication_version": latest["version"] if latest else (0 if current_roster else None),
        "roster_source": "current_signups" if current_roster else "published_and_saved",
        "historical_accounts_count": len((set(saved) | published_tags) - set(current)) if current_roster else 0,
        "revision": revision, "policy": policy, "clans": clans,
        "accounts": accounts, "history": [_history_row(row) for row in history_rows],
        "cycle_confirmed": cycle_confirmed,
        "active_other_cycles": active_other_cycles,
        "history_scope": "dashboard_confirmations_only",
        "award_status": "Selections are dashboard decisions, not in-game awards",
    }


def _fingerprint(view):
    # Full snapshot makes participation refresh, policy, roster, prior-history,
    # or draft edits invalidate an already reviewed preview.
    return _json_hash(view)


def _preview(db, season_id):
    view = _view(db, season_id)
    if view is None:
        return None
    selected = [row for row in view["accounts"] if row["selected"]]
    warnings = []
    blocks = []
    if view["season_status"] != "draft":
        blocks.append("Archived season is read-only")
    if not view["cycle"]:
        blocks.append("Select an explicit CWL month before confirming selections")
    if not view["publication_version"]:
        blocks.append("Publish a roster before confirming selections")
    if not selected:
        blocks.append("Select at least one account")
    if view["active_other_cycles"]:
        months = ", ".join(view["active_other_cycles"])
        blocks.append(
            f"This season already has confirmed selections for {months}. "
            "Restore that month or create a new season"
        )
    capacities = []
    for clan in view["clans"]:
        count = sum(row["assigned_clan_tag"] == clan["tag"] for row in selected)
        confirmed = sum(
            row["clan_tag"] == clan["tag"]
            for row in view["cycle_confirmed"]
        )
        capacities.append({
            "clan_tag": clan["tag"], "clan_name": clan["name"],
            "slots": clan["slots"], "selected_count": count,
            "confirmed_count": confirmed,
        })
        if count and clan["slots"] is None:
            blocks.append(f"Set bonus slots for {clan['name']}")
        elif count and count + confirmed > clan["slots"]:
            blocks.append(f"Bonus selections exceed slots for {clan['name']}")
    for account in selected:
        if account["already_confirmed_this_cycle"]:
            blocks.append(f"{account['player_name']} is already confirmed for this CWL month")
        if not account["assigned_clan_tag"]:
            blocks.append(f"{account['player_name']} has no recorded hosting clan")
        needs_reason = account["recommended"] is not True or not account["source_complete"] or account["source_status"] != "complete"
        if needs_reason:
            warnings.append(
                f"{account['tag']} {account['player_name']}: {account['eligibility_reason']}; "
                f"source {account['source_status']} / {'complete' if account['source_complete'] else 'incomplete'}"
            )
            if not account["reason"].strip():
                blocks.append(f"Add a reason for {account['player_name']}")
    return {
        "revision": view["revision"], "fingerprint": _fingerprint(view),
        "selected": selected, "warnings": warnings, "capacity": capacities,
        "blocking_reasons": blocks, "can_confirm": not blocks,
        "award_status": view["award_status"],
    }


def _validate_revision(body, fail):
    value = body.get("revision")
    if type(value) is not int or value < 0:
        fail(400, "Invalid bonus revision")
    return value


def _cas(db, season_id, expected, fail):
    actual, _ = _meta(db, season_id)
    if actual != expected:
        fail(409, "Bonus review changed; refresh before saving")


async def get_bonuses(request):
    from .app import _fail, _require, _sid, _store

    _require(request, "editor")
    with _store(request).tx() as db:
        result = _view(db, _sid(request))
        if result is None:
            _fail(404, "Season not found")
    return web.json_response(result)


async def get_preview(request):
    from .app import _fail, _require, _sid, _store

    _require(request, "editor")
    with _store(request).tx() as db:
        result = _preview(db, _sid(request))
        if result is None:
            _fail(404, "Season not found")
    return web.json_response(result)


async def patch_settings(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "policy", "clans"}:
        _fail(400, "Expected revision, policy, and clans")
    revision = _validate_revision(body, _fail)
    policy, clans = body["policy"], body["clans"]
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS or not isinstance(clans, list):
        _fail(400, "Invalid bonus settings")
    for key, maximum in (("min_attacks", 7), ("min_stars", 21), ("cooldown_months", 24)):
        value = policy[key]
        if value is not None and (type(value) is not int or not 0 <= value <= maximum):
            _fail(400, f"Invalid {key}")
    supplied = {}
    for clan in clans:
        if not isinstance(clan, dict) or set(clan) != {"tag", "slots"}:
            _fail(400, "Invalid clan bonus slots")
        tag, slots = clan["tag"], clan["slots"]
        if not isinstance(tag, str) or tag in supplied or (slots is not None and (type(slots) is not int or not 0 <= slots <= 50)):
            _fail(400, "Invalid clan bonus slots")
        supplied[tag] = slots
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, revision, _fail)
        current = _view(db, sid)
        expected = {clan["tag"] for clan in current["clans"]}
        if set(supplied) != expected:
            _fail(409, "Published hosting clans changed; refresh bonus settings")
        before = {"policy": current["policy"], "clans": current["clans"]}
        _ensure_meta(db, sid)
        db.execute(
            "UPDATE bonus_reviews SET min_attacks=?,min_stars=?,cooldown_months=? WHERE season_id=?",
            (policy["min_attacks"], policy["min_stars"], policy["cooldown_months"], sid),
        )
        db.execute("DELETE FROM bonus_clan_slots WHERE season_id=?", (sid,))
        db.executemany(
            "INSERT INTO bonus_clan_slots(season_id,clan_tag,slots) VALUES (?,?,?)",
            [(sid, tag, slots) for tag, slots in supplied.items()],
        )
        _bump(db, sid, session["user_id"])
        result = _view(db, sid)
        _audit(db, sid, session["user_id"], "settings", before, {"policy": result["policy"], "clans": result["clans"]})
    return web.json_response(result)


async def patch_draft(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "selections"} or not isinstance(body["selections"], list):
        _fail(400, "Expected revision and selections")
    revision = _validate_revision(body, _fail)
    selections = {}
    for entry in body["selections"]:
        if not isinstance(entry, dict) or set(entry) != {"tag", "reason"}:
            _fail(400, "Invalid bonus selection")
        tag, reason = entry["tag"], entry["reason"]
        if not isinstance(tag, str) or tag in selections or not isinstance(reason, str) or len(reason) > 500:
            _fail(400, "Invalid bonus selection")
        selections[tag] = reason.strip()
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, revision, _fail)
        current = _view(db, sid)
        accounts = {row["tag"]: row for row in current["accounts"]}
        if any(tag not in accounts or not accounts[tag]["assigned_clan_tag"] for tag in selections):
            _fail(400, "Selections must have a recorded hosting clan")
        before = {row["tag"]: row["reason"] for row in current["accounts"] if row["selected"]}
        db.execute("DELETE FROM bonus_draft_selections WHERE season_id=?", (sid,))
        db.executemany(
            "INSERT INTO bonus_draft_selections(season_id,tag,reason) VALUES (?,?,?)",
            [(sid, tag, reason) for tag, reason in selections.items()],
        )
        _bump(db, sid, session["user_id"])
        result = _view(db, sid)
        _audit(db, sid, session["user_id"], "draft", before, selections)
    return web.json_response(result)


async def confirm(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "fingerprint", "acknowledge_warnings"}:
        _fail(400, "Expected revision, fingerprint, and acknowledge_warnings")
    revision = _validate_revision(body, _fail)
    fingerprint, acknowledged = body["fingerprint"], body["acknowledge_warnings"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or type(acknowledged) is not bool:
        _fail(400, "Invalid bonus confirmation")
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        actual, _ = _meta(db, sid)
        if actual == revision + 1:
            prior = db.execute(
                "SELECT id FROM bonus_batches WHERE season_id=? AND base_revision=? AND fingerprint=?",
                (sid, revision, fingerprint),
            ).fetchone()
            if prior:
                return web.json_response(_view(db, sid))
        _cas(db, sid, revision, _fail)
        preview = _preview(db, sid)
        if preview["fingerprint"] != fingerprint:
            _fail(409, "Bonus preview changed; review it again before confirming")
        if not preview["can_confirm"]:
            _fail(409, "; ".join(preview["blocking_reasons"]))
        if preview["warnings"] and not acknowledged:
            _fail(409, "Review and acknowledge bonus warnings before confirming")
        view = _view(db, sid)
        stamp = _now()
        cursor = db.execute(
            "INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                sid, view["cycle"], revision, fingerprint,
                json.dumps({
                    "cycle": view["cycle"], "publication_version": view["publication_version"],
                    "policy": view["policy"], "capacity": preview["capacity"],
                    "selected": preview["selected"], "warnings": preview["warnings"],
                    "history_scope": view["history_scope"],
                }, sort_keys=True),
                session["user_id"], stamp,
            ),
        )
        batch_id = cursor.lastrowid
        for account in preview["selected"]:
            row_warnings = [warning for warning in preview["warnings"] if warning.startswith(account["tag"] + " ")]
            db.execute(
                "INSERT INTO bonus_confirmations("
                "batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,"
                "attacks,stars,reason,warnings_json,confirmed_by,confirmed_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch_id, sid, view["cycle"],
                    account["recorded_publication_version"] or view["publication_version"],
                    account["tag"], account["player_name"], account["pool"],
                    account["assigned_clan_tag"], account["assigned_clan_name"],
                    account["attacks"], account["stars"], account["reason"],
                    json.dumps(row_warnings), session["user_id"], stamp,
                ),
            )
        db.execute("DELETE FROM bonus_draft_selections WHERE season_id=?", (sid,))
        _bump(db, sid, session["user_id"])
        result = _view(db, sid)
        _audit(db, sid, session["user_id"], "confirm", None, {"batch_id": batch_id, "tags": sorted(row["tag"] for row in preview["selected"])})
    return web.json_response(result)


async def void_confirmation(request):
    from .app import _fail, _json, _require, _sid, _store

    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "reason"}:
        _fail(400, "Expected revision and reason")
    revision = _validate_revision(body, _fail)
    reason = body["reason"]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        _fail(400, "A void reason of at most 500 characters is required")
    try:
        history_id = int(request.match_info["id"])
    except ValueError:
        _fail(400, "Invalid confirmation id")
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, revision, _fail)
        row = db.execute(
            "SELECT * FROM bonus_confirmations WHERE id=? AND season_id=?", (history_id, sid),
        ).fetchone()
        if row is None:
            _fail(404, "Bonus confirmation not found")
        if row["voided_at"] is not None:
            _fail(409, "Bonus confirmation was already voided")
        stamp = _now()
        db.execute(
            "UPDATE bonus_confirmations SET voided_by=?,voided_at=?,void_reason=? WHERE id=?",
            (session["user_id"], stamp, reason.strip(), history_id),
        )
        _bump(db, sid, session["user_id"])
        result = _view(db, sid)
        _audit(db, sid, session["user_id"], "void", {"id": history_id, "tag": row["tag"]}, {"id": history_id, "reason": reason.strip()})
    return web.json_response(result)


def routes():
    from .app import API

    base = API + "/seasons/{season_id}/bonuses"
    return [
        web.get(base, get_bonuses),
        web.get(base + "/preview", get_preview),
        web.patch(base + "/settings", patch_settings),
        web.patch(base + "/draft", patch_draft),
        web.post(base + "/confirm", confirm),
        web.post(base + "/{id}/void", void_confirmation),
    ]
