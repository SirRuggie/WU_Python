from utils.clan_weights import source_weights, saved_sources, overlay_accounts
from utils.cwl_dashboard_state import DashboardDurabilityError
from .ticket_browser import routes as ticket_browser_routes
"""Aiohttp CWL foundation. Read-only bot directory; no bot gateway or Discord sends."""

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote, parse_qs

import aiohttp
from aiohttp import web
from .access_control import PERMISSIONS, scopes, request_scopes, OWNER_IDS, CWL_PERMISSIONS
from .access_settings import access_context
from .issues import diagnostics, routes as issue_routes
from .staff_tag_signups import routes as staff_tag_signup_routes
from .staff_signup_changes import routes as staff_signup_change_routes

from .providers import FixtureProviders, LiveProviders, ProviderUnavailable, tag
from .store import Store, signup_timestamps
from .canonical_host import canonical_host
from .placement_status import explain as explain_placement
from .clan_metadata import enrich as enrich_clan_metadata
from .exports import export_csv, export_preview
from .announcements import routes as announcement_routes
from .manage_bridge import routes as manage_bridge_routes
from .participation import routes as participation_routes
from .bonuses import routes as bonus_routes
from .bonus_raffle import routes as bonus_raffle_routes
from .participation_sync import routes as participation_sync_routes, lifecycle as participation_sync_lifecycle
from .todo import routes as todo_routes, lifecycle as todo_lifecycle
from .push import routes as push_routes, lifecycle as push_lifecycle


GUILD_ID = "644963518025826315"
PERMANENT_OWNER_ID = "505227988229554179"
SESSION_SECONDS = 30 * 24 * 60 * 60  # Persistent login; explicit logout revokes it immediately.
COOKIE = "cwl_session"
STATE_COOKIE = "cwl_oauth_state"
API = "/api/cwl"
DASHBOARD_ACCOUNTS_CACHE_SECONDS = 60
DASHBOARD_ACCOUNTS_CACHE_MAX_ENTRIES = 1024


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _discord_avatar_url(user):
    """Build a CDN URL only from validated Discord identity fields."""
    user_id = str(user["id"])
    avatar = user.get("avatar")
    if isinstance(avatar, str) and re.fullmatch(r"(?:a_)?[0-9a-fA-F]{32}", avatar):
        extension = "gif" if avatar.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{extension}"
    discriminator = str(user.get("discriminator") or "0")
    if discriminator.isdigit() and discriminator != "0":
        index = int(discriminator) % 5
    else:
        index = (int(user_id) >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


class HTTPLocked(web.HTTPClientError):
    status_code = 423


def _fail(status, message):
    kinds = {400: web.HTTPBadRequest, 401: web.HTTPUnauthorized,
             403: web.HTTPForbidden, 404: web.HTTPNotFound,
             409: web.HTTPConflict, 423: HTTPLocked,
             503: web.HTTPServiceUnavailable}
    raise kinds[status](text=message)


def _body_bool(body, key):
    value = body.get(key)
    if type(value) is not bool:
        _fail(400, f"{key} must be a boolean")
    return value


async def _json(request):
    try:
        body = await request.json()
    except Exception:
        _fail(400, "Invalid JSON")
    if not isinstance(body, dict):
        _fail(400, "Expected JSON object")
    return body


def _store(request):
    return request.app["store"]


def _session(request):
    raw = request.cookies.get(COOKIE, "")
    if not raw:
        _fail(401, "Sign in required")
    row = _store(request).one("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (_hash(raw), int(time.time())))
    if not row:
        _fail(401, "Session expired")
    return row


def _owner(session):
    return session["user_id"] in OWNER_IDS


def _editor(request, session):
    from .access_control import scopes
    return _owner(session) or bool(set(CWL_PERMISSIONS) & request_scopes(request, session["user_id"]))


def _require(request, level="member"):
    session = _session(request)
    if level == "owner" and not _owner(session):
        _fail(403, "Owner access required")
    if level == "editor" and not _editor(request, session):
        _fail(403, "Dashboard access required")
    if level == "editor" and not _owner(session) and (
        request.method not in ("GET", "HEAD", "OPTIONS")
        or request.match_info.handler.__name__ == "lookup_clan"
    ):
        from .cwl_permissions import mutation_permission
        required = mutation_permission(request)
        if required is None or required not in request_scopes(request, session['user_id']):
            _fail(403, "You do not have permission for this CWL action.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
        _fail(403, "Invalid CSRF token")
    return session


def _season(db, sid):
    row = db.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
    if row is None:
        _fail(404, "Season not found")
    return row


def _sid(request):
    try:
        sid = int(request.match_info["season_id"])
        session = _session(request)
        if not _editor(request, session) and _store(request).member_season()['season_id'] != sid:
            _fail(403, "This season is not available to members. Open Signups for the current season.")
        return sid
    except ValueError:
        _fail(404, "Season not found")


def _season_dict(row):
    result = dict(row)
    result["signup_open"] = bool(result["signup_open"])
    return result


def _revision(db, sid):
    row = db.execute("SELECT revision FROM roster_meta WHERE season_id=?", (sid,)).fetchone()
    return row["revision"] if row else 0


def _bump(db, sid):
    db.execute("INSERT INTO roster_meta(season_id,revision) VALUES (?,1) "
               "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1", (sid,))
    return _revision(db, sid)


def _check_revision(db, sid, supplied):
    if type(supplied) is not int or supplied != _revision(db, sid):
        _fail(409, "Roster changed; refresh before editing")


def _audit(db, sid, tag_value, actor_id, action, before, after):
    db.execute("INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json,after_json) "
               "VALUES (?,?,?,?,?,?)", (sid, tag_value, actor_id, action,
               json.dumps(before, sort_keys=True) if before is not None else None,
               json.dumps(after, sort_keys=True) if after is not None else None))


def _placement(row):
    return {"assigned_clan_tag": row["assigned_clan_tag"] if row else None,
            "kept": bool(row["kept"]) if row else False}


def _record_undo(db, sid, actor_id, label, revision, changes):
    changed = [change for change in changes if change["before"] != change["after"]]
    if not changed:
        return None
    cursor = db.execute(
        "INSERT INTO roster_undo(season_id,actor_id,label,revision,changes_json) VALUES (?,?,?,?,?)",
        (sid, actor_id, label, revision, json.dumps(changed, sort_keys=True)),
    )
    return cursor.lastrowid


def _current_undo(db, sid, actor_id):
    row = db.execute(
        "SELECT id,label,revision FROM roster_undo WHERE season_id=? AND actor_id=? "
        "AND revision=? AND consumed_at IS NULL ORDER BY id DESC LIMIT 1",
        (sid, actor_id, _revision(db, sid)),
    ).fetchone()
    return dict(row) if row else None


async def config(request):
    return web.json_response({"dev_fixture": bool(request.app["dev_fixture"])})


async def me(request):
    session = _require(request)
    from .visitors import record
    await record(request, session)
    return web.json_response({"authenticated": True, "access_warning": request.get("access_warning"), "user": {"id": session["user_id"], "username": session["username"], "display_name": session["display_name"] or session["username"], "avatar_url": session["avatar_url"]}, "is_owner": _owner(session), "can_edit": _editor(request, session), "dashboard_permissions": list(PERMISSIONS) if _owner(session) else sorted(request_scopes(request, session["user_id"])), "csrf_token": session["csrf"]})


RETURN_COOKIE = "wu_login_page"
CWL_PAGE_PATHS = {
    "manage-signups": "/cwl/signups",
    "roster": "/cwl/roster",
    "declaration": "/cwl/readiness",
    "reminders": "/cwl/reminders/signup",
    "cwl-returns": "/cwl/reminders/return",
    "publication": "/cwl/publish",
    "participation": "/cwl/results",
    "bonuses": "/cwl/bonuses",
    "exports": "/cwl/exports",
    "staff": "/cwl/settings",
}
MANAGEMENT_PAGE_PATHS = {
    "staff-overview": "/staff",
    "clan-management": "/clans",
    "strikes": "/strikes",
    "replacements": "/replacements",
    "members-settings": "/server/members",
    "member-activity": "/server/member-activity",
    "moderation": "/server/moderation",
    "applications-settings": "/server/applications",
    "fwa-settings": "/server/fwa",
    "connections-settings": "/settings/integrations",
    "text-commands": "/server/commands",
    "manage": "/server",
    "image-gallery": "/settings/image-gallery",
    "tickets": "/tickets",
    "access": "/settings/access",
    "issues": "/settings/issues",
}


def login_destination(query):
    view = query.get("view", "")
    if view == "manage-signups":
        params = {}
        season = str(query.get("season", ""))
        if re.fullmatch(r"[0-9]{1,18}", season):
            params["season"] = season
        return CWL_PAGE_PATHS["roster"] + ("?" + urlencode(params) if params else "")
    if view in ('strikes', 'replacements'):
        from .strike_activity_links import activity_query
        params = activity_query(query)
        return MANAGEMENT_PAGE_PATHS[view] + ('?' + urlencode(params) if params else '')
    if view in MANAGEMENT_PAGE_PATHS:
        return MANAGEMENT_PAGE_PATHS[view]
    if view in CWL_PAGE_PATHS:
        params = {}
        season = str(query.get("season", ""))
        if re.fullmatch(r"[0-9]{1,18}", season):
            params["season"] = season
        if view == "publication" and query.get("step") in {"review", "announce"}:
            params["step"] = query["step"]
        return CWL_PAGE_PATHS[view] + ("?" + urlencode(params) if params else "")
    if view == "my-signups":
        return "/my-signups"
    if view == "weight-trial":
        params = {key: str(query[key]).upper() for key in ('player', 'clan')
                  if re.fullmatch(r'#[A-Z0-9]{1,20}', str(query.get(key, '')), re.I)}
        return "/clan-weights" + ("?" + urlencode(params) if params else "")
    if view == "signups":
        view = "signup"
    if view not in {"home", "search", "wars", "events", "todo", "signup", "assignments"}:
        return ""
    return {'home':'/', 'todo':'/tasks'}.get(view, '/' + view)


def saved_login_destination(request):
    value = request.cookies.get(RETURN_COOKIE, "")
    if value in {'/', '/signup', '/assignments', '/tasks', '/wars', '/events', '/search', '/clan-weights', '/my-signups'}:
        return value
    if len(value) <= 2048:
        path, _, query = value.partition('?')
        strike_view = {'/strikes':'strikes', '/clans/strikes':'strikes',
                       '/replacements':'replacements', '/clans/replacements':'replacements'}.get(path)
        if strike_view:
            params = {key: values[0] for key, values in parse_qs(query).items()}
            params['view'] = strike_view
            return login_destination(params)
    if len(value) <= 150:
        path, _, query = value.partition("?")
        if path == '/clan-weights':
            params = {key: values[0] for key, values in parse_qs(query).items()}
            params['view'] = 'weight-trial'
            return login_destination(params)
        if path in MANAGEMENT_PAGE_PATHS.values():
            return path
        for view, destination in CWL_PAGE_PATHS.items():
            if path == destination:
                params = {key: values[0] for key, values in parse_qs(query).items()}
                params["view"] = view
                return login_destination(params)
    if not value.startswith("/?") or len(value) > 150:
        return ""
    return login_destination({key: values[0] for key, values in parse_qs(value[2:]).items()})


async def auth_start(request):
    cfg = request.app["oauth"]
    if not all(cfg.values()):
        _fail(503, "Discord OAuth is not configured")
    state = secrets.token_urlsafe(32)
    with _store(request).tx() as db:
        db.execute("DELETE FROM oauth_states WHERE expires_at<=?", (int(time.time()),))
        db.execute("INSERT INTO oauth_states VALUES (?,?)", (_hash(state), int(time.time()) + 300))
    params = {"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"], "response_type": "code", "scope": "identify guilds", "state": state, "prompt": "consent" if request.query.get("retry") == "1" else "none"}
    response = web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode(params, quote_via=quote))
    destination = login_destination(request.query)
    if destination:
        response.set_cookie(RETURN_COOKIE, destination, max_age=300, httponly=True, secure=request.app["secure_cookies"], samesite="Lax", path=API + "/auth")
    else:
        response.del_cookie(RETURN_COOKIE, path=API + "/auth")
    response.set_cookie(STATE_COOKIE, state, max_age=300, httponly=True, secure=request.app["secure_cookies"], samesite="Lax", path=API + "/auth")
    raise response


async def auth_callback(request):
    state = request.query.get("state", "")
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        _fail(403, "OAuth state mismatch")
    with _store(request).tx() as db:
        cursor = db.execute("DELETE FROM oauth_states WHERE state_hash=? AND expires_at>?", (_hash(state), int(time.time())))
        if cursor.rowcount != 1:
            _fail(403, "OAuth state expired or already used")
    if request.query.get("error"):
        _fail(401, "Discord authorization was not completed")
    cfg = request.app["oauth"]
    code = request.query.get("code", "")
    if not code or not all(cfg.values()):
        _fail(400, "OAuth callback incomplete")
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            data = {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"], "grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"]}
            async with client.post("https://discord.com/api/v10/oauth2/token", data=data) as response:
                if response.status != 200:
                    _fail(401, "Discord sign-in failed")
                token_data = await response.json()
            access = token_data.get("access_token")
            if not isinstance(access, str) or not access:
                _fail(401, "Discord sign-in failed")
            headers = {"Authorization": "Bearer " + access}
            async with client.get("https://discord.com/api/v10/users/@me", headers=headers) as response:
                if response.status != 200:
                    _fail(401, "Discord identity unavailable")
                user = await response.json()
            guilds = []
            after = None
            for _ in range(50):
                params = {"limit": "200"}
                if after:
                    params["after"] = after
                async with client.get("https://discord.com/api/v10/users/@me/guilds", headers=headers, params=params) as response:
                    if response.status != 200:
                        _fail(401, "Discord membership unavailable")
                    page = await response.json()
                if not isinstance(page, list):
                    _fail(401, "Discord membership unavailable")
                guilds.extend(page)
                if len(page) < 200:
                    break
                after = str(page[-1].get("id", ""))
                if not after.isdigit():
                    _fail(401, "Discord membership unavailable")
            else:
                _fail(503, "Discord guild list too large to verify")
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise web.HTTPServiceUnavailable(text="Discord unavailable") from exc
    if not isinstance(user, dict) or not str(user.get("id", "")).isdigit() or not isinstance(guilds, list):
        _fail(401, "Invalid Discord identity")
    guild = next((g for g in guilds if isinstance(g, dict) and str(g.get("id")) == GUILD_ID), None)
    if guild is None:
        _fail(403, "Warriors United membership required")
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    with _store(request).tx() as db:
        username = str(user.get("username") or user["id"])
        global_name = user.get("global_name")
        display_name = global_name.strip() if isinstance(global_name, str) and global_name.strip() else username
        db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at,display_name,avatar_url,is_bot) VALUES (?,?,?,?,?,?,?,?,?)",
                   (_hash(raw), str(user["id"]), username, int(guild.get("owner") is True), csrf,
                    int(time.time()) + SESSION_SECONDS, display_name, _discord_avatar_url(user), int(user.get("bot") is True)))
    response = web.HTTPFound(saved_login_destination(request) or request.app["after_login"])
    response.del_cookie(RETURN_COOKIE, path=API + "/auth")
    response.set_cookie(COOKIE, raw, max_age=SESSION_SECONDS, httponly=True, secure=request.app["secure_cookies"], samesite="Lax", path=API)
    response.del_cookie(STATE_COOKIE, path=API + "/auth")
    raise response


async def logout(request):
    session = _require(request)
    from .manage_identity_cache import invalidate
    invalidate(request.app, session["user_id"])
    body = await request.json() if request.can_read_body else {}
    push_id = body.get("push_id") if isinstance(body, dict) else None
    with _store(request).tx() as db:
        if isinstance(push_id, str):
            db.execute("DELETE FROM push_subscriptions WHERE id=? AND user_id=?", (push_id, session["user_id"]))
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(request.cookies[COOKIE]),))
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE, path=API)
    return response


async def dev_login(request):
    host = request.headers.get("Host", "").split(":")[0].strip("[]")
    origin = request.headers.get("Origin")
    if (not request.app["dev_fixture"] or request.remote not in ("127.0.0.1", "::1")
            or host not in ("127.0.0.1", "localhost", "::1")
            or any(key.lower().startswith("x-forwarded-") or key.lower() == "forwarded" for key in request.headers)
            or (origin and origin not in (f"http://{request.host}", f"https://{request.host}"))):
        _fail(404, "Not found")
    identity = request.app["dev_identity"]
    raw, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    with _store(request).tx() as db:
        db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at,display_name,avatar_url,is_bot) VALUES (?,?,?,?,?,?,?,?,?)",
                   (_hash(raw), identity["id"], identity["username"], int(identity.get("guild_owner", False)),
                    csrf, int(time.time()) + SESSION_SECONDS, identity.get("display_name") or identity["username"],
                    identity.get("avatar_url") or _discord_avatar_url(identity), int(identity.get("bot") is True)))
    response = web.json_response({"ok": True})
    response.set_cookie(COOKIE, raw, max_age=SESSION_SECONDS, httponly=True, secure=False, samesite="Lax", path=API)
    return response


async def seasons(request):
    session = _require(request)
    selection = _store(request).member_season()
    rows = _store(request).rows("SELECT * FROM seasons ORDER BY id DESC")
    if not _editor(request, session):
        rows = [row for row in rows if row['id'] == selection['season_id']]
    from .member_timing import seasons_timing
    timing = await seasons_timing(request, [row['id'] for row in rows])
    return web.json_response({"seasons": [_season_dict(row) | dates for row, dates in zip(rows, timing)], "member_season": selection})


async def set_member_season(request):
    session = _require(request, 'editor')
    body = await _json(request)
    sid, revision = body.get('season_id'), body.get('revision')
    if set(body) != {'season_id', 'revision'} or type(revision) is not int or (sid is not None and (type(sid) is not int or not 0 < sid < 2**63)):
        _fail(400, 'Invalid member season selection')
    try:
        result = _store(request).set_member_season(sid, revision, session['user_id'])
    except ValueError as error:
        _fail(400, str(error))
    except RuntimeError as error:
        _fail(409, str(error))
    return web.json_response(result)


async def create_season(request):
    _require(request, "editor")
    body = await _json(request)
    label = str(body.get("label", "")).strip()
    if not 3 <= len(label) <= 80:
        _fail(400, "Season label must have 3–80 characters")
    opened = _body_bool(body, "signup_open")
    try:
        with _store(request).tx() as db:
            source = db.execute("SELECT MAX(season_id) FROM lineup").fetchone()[0]
            try:
                cursor = db.execute("INSERT INTO seasons(label,signup_open) VALUES (?,?)", (label, int(opened)))
            except sqlite3.IntegrityError:
                _fail(409, "Season already exists")
            row = _season(db, cursor.lastrowid)
            copied = 0
            if source is not None:
                copied = db.execute(
                    "INSERT INTO lineup(season_id,tag) SELECT ?,l.tag FROM lineup l "
                    "JOIN clans c ON c.tag=l.tag WHERE l.season_id=? AND c.archived=0",
                    (row['id'], source),
                ).rowcount
                db.execute(
                    "INSERT INTO lineup_rules(season_id,tag,pool,capacity,min_weight,max_weight) "
                    "SELECT ?,r.tag,r.pool,r.capacity,r.min_weight,r.max_weight FROM lineup_rules r "
                    "JOIN lineup l ON l.tag=r.tag AND l.season_id=? WHERE r.season_id=?",
                    (row['id'], row['id'], source),
                )
            if db.execute('SELECT COUNT(*) FROM seasons').fetchone()[0] == 1:
                db.execute('UPDATE member_season SET season_id=?,revision=revision+1 WHERE id=1 AND season_id IS NULL', (row['id'],))
    except sqlite3.Error as error:
        logging.getLogger("cwl.seasons").error(
            "Hosting clan copy failed (%s): %s", type(error).__name__, str(error)
        )
        return web.json_response({"error": "Couldn't copy hosting clans; nothing was created."}, status=500)
    return web.json_response({**_season_dict(row), "copied_clan_count": copied}, status=201)


async def update_season(request):
    session = _require(request, "editor")
    body = await _json(request)
    if not set(body) <= {"label", "signup_open", "status", "expected_signup_open"} or not body:
        _fail(400, "Invalid season update")
    if "expected_signup_open" in body and type(body["expected_signup_open"]) is not bool:
        _fail(400, "expected_signup_open must be a boolean")
    with _store(request).tx() as db:
        row = _season(db, _sid(request))
        if "expected_signup_open" in body and bool(row["signup_open"]) != body["expected_signup_open"]:
            _fail(409, "Signups were changed by someone else. Refresh and try again.")
        label = str(body.get("label", row["label"])).strip()
        if not 3 <= len(label) <= 80:
            _fail(400, "Invalid season label")
        opened = _body_bool(body, "signup_open") if "signup_open" in body else bool(row["signup_open"])
        status = body.get("status", row["status"])
        if status not in ("draft", "archived"):
            _fail(400, "Invalid status")
        try:
            db.execute("UPDATE seasons SET label=?,signup_open=?,status=? WHERE id=?", (label, int(opened), status, row["id"]))
        except sqlite3.IntegrityError:
            _fail(409, "Season already exists")
        result = _season(db, row["id"])
        if (label, opened, status) != (row["label"], bool(row["signup_open"]), row["status"]):
            _bump(db, row["id"])
            _audit(db, row["id"], None, session["user_id"], "season_update", _season_dict(row), _season_dict(result))
    return web.json_response(_season_dict(result))


async def clans(request):
    _require(request, "editor")
    rows = _store(request).rows("SELECT * FROM clans ORDER BY name")
    return web.json_response({"clans": await enrich_clan_metadata(request, [{**r, "archived": bool(r["archived"])} for r in rows])})


async def lookup_clan(request):
    _require(request, "editor")
    try:
        value = tag(request.query.get("tag"))
    except ValueError:
        _fail(400, "Invalid clan tag")
    try:
        clan = await request.app["providers"].clan(value)
    except ProviderUnavailable as exc:
        if getattr(exc, "status_code", None) == 404:
            _fail(404, "Clan not found")
        raise
    return web.json_response({"tag": clan["tag"], "name": clan["name"]})


async def create_clan(request):
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) - {"tag", "pool"} or body.get("pool") not in (None, "main", "lazy"):
        _fail(400, "Choose Main or Lazy CWL")
    try:
        value = tag(body.get("tag"))
    except ValueError:
        _fail(400, "Invalid clan tag")
    clan = await request.app["providers"].clan(value)
    with _store(request).tx() as db:
        before_row = db.execute("SELECT * FROM clans WHERE tag=?", (clan["tag"],)).fetchone()
        before = dict(before_row) if before_row else None
        pool = body.get("pool", before["pool"] if before else None)
        db.execute("INSERT INTO clans(tag,name,archived,pool) VALUES (?,?,0,?) ON CONFLICT(tag) DO UPDATE SET name=excluded.name,archived=0,pool=excluded.pool", (clan["tag"], clan["name"], pool))
        after = {**clan, "archived": False, "pool": pool}
        if before != after:
            for season in db.execute("SELECT id FROM seasons"):
                _bump(db, season["id"])
                _audit(db, season["id"], clan["tag"], session["user_id"], "directory_add_or_restore", before, after)
    return web.json_response(after, status=201)


async def archive_clan(request):
    session = _require(request, "editor")
    body = await _json(request)
    if not body or set(body) - {"archived", "pool"}:
        _fail(400, "Expected archive status or CWL pool")
    if "pool" in body and body["pool"] not in ("main", "lazy"):
        _fail(400, "Choose Main or Lazy CWL")
    archived = _body_bool(body, "archived") if "archived" in body else None
    try:
        value = tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid clan tag")
    with _store(request).tx() as db:
        current = db.execute("SELECT * FROM clans WHERE tag=?", (value,)).fetchone()
        if current is None:
            _fail(404, "Clan not found")
        before = dict(current)
        after = {**before, "archived": bool(current["archived"]) if archived is None else archived,
                 "pool": body.get("pool", current["pool"])}
        db.execute("UPDATE clans SET archived=?,pool=? WHERE tag=?", (int(after["archived"]), after["pool"], value))
        if before != after:
            for row in db.execute("SELECT id FROM seasons"):
                _bump(db, row["id"])
                _audit(db, row["id"], value, session["user_id"], "directory_update", before, after)
    return web.json_response(after)


async def lineup(request):
    _require(request, "editor")
    sid = _sid(request)
    rows = _store(request).rows(
        "SELECT c.tag,c.name,c.archived FROM clans c WHERE c.archived=0 "
        "OR EXISTS (SELECT 1 FROM roster_entries e WHERE e.season_id=? AND e.assigned_clan_tag=c.tag) "
        "ORDER BY c.name,c.tag", (sid,))
    return web.json_response({"clans": await enrich_clan_metadata(request, [{**r, "archived": bool(r["archived"])} for r in rows])})


async def add_lineup(request):
    session = _require(request, "editor")
    body = await _json(request)
    try:
        value = tag(body.get("tag"))
    except ValueError:
        _fail(400, "Invalid clan tag")
    with _store(request).tx() as db:
        season = _season(db, _sid(request))
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        clan = db.execute("SELECT * FROM clans WHERE tag=?", (value,)).fetchone()
        if clan is None or clan["archived"]:
            _fail(409, "Add an active directory clan first")
        inserted = db.execute("INSERT OR IGNORE INTO lineup(season_id,tag) VALUES (?,?)", (season["id"], value))
        if inserted.rowcount:
            _bump(db, season["id"])
            _audit(db, season["id"], value, session["user_id"], "lineup_add", None,
                   {"tag": value, "name": clan["name"]})
    return web.json_response({"tag": value, "name": clan["name"]}, status=201)


async def remove_lineup(request):
    session = _require(request, "editor")
    try:
        value = tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid clan tag")
    with _store(request).tx() as db:
        sid = _sid(request)
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        assigned = db.execute("SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? AND assigned_clan_tag=?", (sid, value)).fetchone()["n"]
        if assigned:
            _fail(409, "Unassign or move roster accounts before removing this hosting clan")
        deleted = db.execute("DELETE FROM lineup WHERE season_id=? AND tag=?", (sid, value))
        if deleted.rowcount:
            _bump(db, sid)
            _audit(db, sid, value, session["user_id"], "lineup_remove", {"tag": value}, None)
    return web.json_response({"ok": True})


async def approved_clans(request):
    _require(request, "editor")
    result = await request.app["providers"].family_clans()
    await enrich_clan_metadata(request, result["clans"])
    return web.json_response(result)


async def family_clans_read_only(request):
    raise web.HTTPMethodNotAllowed(request.method, ["GET"])


from .access_settings import access, save as grant, roles as access_roles


async def _family_directory(request):
    """Unknown directory data must not be interpreted as a non-FWA clan."""
    try:
        family = await request.app["providers"].family_clans()
    except ProviderUnavailable:
        return None
    return {clan["tag"]: clan for clan in family["clans"]}


async def _family_tags(request):
    directory = await _family_directory(request)
    return None if directory is None else set(directory)


def _family_status(clan_tag, approved):
    if approved is None:
        return "unknown"
    return "approved" if clan_tag in approved else "outside"


def _check_signup_pool(pool, accounts):
    from utils.cwl_signup_policy import main_signup_error
    if pool == 'main':
        for account in accounts:
            problem = main_signup_error(account)
            if problem:
                _fail(*problem)


async def _accounts(request, user_id):
    from utils.cwl_member_service import accounts_for_member
    return await accounts_for_member(request.app["providers"], user_id)


async def linked_accounts(request):
    session = _require(request)
    if request.query.get("background") == "1":
        from .account_display import snapshot
        return web.json_response(await snapshot(request, session["user_id"]))
    return web.json_response({"accounts": await _accounts(request, session["user_id"]), "status": "ok", "link_url": None, "link_instruction": "Link your accounts with ClashKing or ClashPerk in Discord, then refresh."})


def _prune_dashboard_accounts(cache, now):
    for user_id, (expires_at, _) in list(cache.items()):
        if expires_at <= now:
            cache.pop(user_id, None)
    while len(cache) > DASHBOARD_ACCOUNTS_CACHE_MAX_ENTRIES:
        cache.pop(next(iter(cache)))


def _observe_dashboard_account_task(task):
    if not task.cancelled():
        task.exception()  # Consume failures when every HTTP waiter has disconnected.


async def _dashboard_account_snapshot(request, user_id):
    try:
        accounts = await _accounts(request, user_id)
        # Optional enrichment must not prevent members viewing their accounts.
        try:
            weights = await asyncio.wait_for(
                source_weights(_store(request), request.app["providers"], [account["tag"] for account in accounts]),
                timeout=5,
            ) if accounts else {}
        except (ProviderUnavailable, asyncio.TimeoutError):
            weights = {}
        for account in accounts:
            account["war_weight"] = weights.get(account["tag"], {}).get("weight")
        payload = {"accounts": accounts, "status": "ok", "link_url": None,
                   "link_instruction": "Link your accounts with ClashKing or ClashPerk in Discord, then refresh.",
                   "checked_at": datetime.now(timezone.utc).isoformat()}
        cache = request.app["dashboard_accounts_cache"]
        now = time.monotonic()
        cache[user_id] = (now + DASHBOARD_ACCOUNTS_CACHE_SECONDS, payload)
        _prune_dashboard_accounts(cache, now)
        return payload
    finally:
        request.app["dashboard_accounts_inflight"].pop(user_id, None)


async def dashboard_accounts(request):
    user_id = _require(request)["user_id"]
    if request.query.get("background") == "1":
        from .account_display import snapshot
        return web.json_response(await snapshot(request, user_id))
    cache = request.app["dashboard_accounts_cache"]
    _prune_dashboard_accounts(cache, time.monotonic())
    cached = cache.get(user_id)
    if cached is not None:
        return web.json_response(overlay_accounts(_store(request), cached[1]))
    inflight = request.app["dashboard_accounts_inflight"]
    task = inflight.get(user_id)
    if task is None:
        task = asyncio.create_task(_dashboard_account_snapshot(request, user_id))
        task.add_done_callback(_observe_dashboard_account_task)
        inflight[user_id] = task
    return web.json_response(overlay_accounts(_store(request), await asyncio.shield(task)))


async def _dashboard_accounts_lifecycle(app):
    yield
    tasks = list(app["dashboard_accounts_inflight"].values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    app["dashboard_accounts_inflight"].clear()
    app["dashboard_accounts_cache"].clear()


async def signups(request):
    session = _require(request)
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        placed = {row["tag"] for row in db.execute(
            "SELECT tag FROM roster_entries WHERE season_id=? AND assigned_clan_tag IS NOT NULL", (sid,)
        ).fetchall()}
        staff_view = _editor(request, session) and request.query.get("all") == "1"
        revision = _revision(db, sid)
        assignments = {row["tag"]: dict(row) for row in db.execute("SELECT r.tag,r.assigned_clan_tag,c.name AS assigned_clan_name FROM roster_entries r LEFT JOIN clans c ON c.tag=r.assigned_clan_tag WHERE r.season_id=?", (sid,))} if staff_view else {}
        if staff_view:
            rows = db.execute("SELECT * FROM signups WHERE season_id=? ORDER BY user_id,tag", (sid,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM signups WHERE season_id=? AND user_id=? ORDER BY tag", (sid, session["user_id"])).fetchall()
    directory = await _family_directory(request)
    approved = None if directory is None else set(directory)
    result = []
    for row in rows:
        entry = dict(row)
        if staff_view:
            entry.update({key: assignments.get(entry["tag"], {}).get(key) for key in ("assigned_clan_tag", "assigned_clan_name")})
        entry["has_staff_placement"] = entry["tag"] in placed
        entry["prefer_crystal_1_or_lower"] = bool(entry["prefer_crystal_1_or_lower"])
        entry["family_clan_status"] = _family_status(entry["signup_clan_tag"], approved)
        origin_type = (directory or {}).get(entry["signup_clan_tag"], {}).get("type")
        entry["signup_clan_type"] = "FWA" if "FWA" in (entry.get("signup_clan_type"), origin_type) else entry.get("signup_clan_type") or origin_type
        entry["fwa_main_warning"] = entry["pool"] == "main" and entry["signup_clan_type"] == "FWA"
        result.append(entry)
    return web.json_response({"signups": result, **({"revision": revision} if staff_view else {})})


async def submit_signup(request):
    from utils.cwl_member_service import MemberError, submit

    session = _require(request)
    body = await _json(request)
    sid = _sid(request)
    try:
        result = await submit(
            _store(request), request.app["providers"], sid, session["user_id"],
            body.get("pool"), body.get("accounts"), verified_only=False,
            selected_only=not _editor(request, session)
        )
    except MemberError as exc:
        _fail(exc.status, str(exc))
    return web.json_response(result)


async def staff_signup_members(request):
    _require(request, "editor")
    from .manage_roles import searchable_members, member_option, search_text
    query = search_text(request.query.get("q", "").strip())
    if len(query) > 80:
        _fail(400, "Use a shorter member name")
    selected = request.query.get("id", "")
    signup_ids = None
    if "season_id" in request.query:
        try:
            sid = int(request.query["season_id"])
        except ValueError:
            _fail(400, "Invalid season")
        with _store(request).tx() as db:
            _season(db, sid)
            signup_ids = {str(row["user_id"]) for row in db.execute(
                "SELECT DISTINCT user_id FROM signups WHERE season_id=? AND user_id IS NOT NULL", (sid,)
            )}
    rows = await searchable_members(request)
    matches = [row for row in rows if not row.get("user", {}).get("bot") and
               (signup_ids is None or str(row["user"]["id"]) in signup_ids) and
               (not selected or str(row["user"]["id"]) == selected) and
               (not query or query in search_text(" ".join(str(value or "") for value in
                (row.get("nick"), row["user"].get("global_name"), row["user"].get("username"), row["user"]["id"]))))]
    options = [member_option(row) for row in (matches if signup_ids is not None else matches[:50])]
    for option in options:
        option["role_ids"] = []; option["role_names"] = []
    return web.json_response({"options": options, "next": None, "truncated": signup_ids is None and len(matches) > 50})


def signup_member_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,22}", value):
        _fail(400, "Select a member")
    return value


async def staff_signup_accounts(request):
    _require(request, "editor")
    uid = signup_member_id(request.query.get("user_id"))
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        signed = {row["tag"]: row["pool"] for row in db.execute("SELECT tag,pool FROM signups WHERE season_id=?", (sid,))}
    accounts = await _accounts(request, uid)
    return web.json_response({"accounts": [{**account, "signed_up_pool": signed.get(account["tag"])} for account in accounts]})


async def staff_add_signup(request):
    actor = _require(request, "editor")
    body = await _json(request)
    uid = signup_member_id(body.get("user_id"))
    pool = body.get("pool")
    choices = body.get("accounts")
    if pool not in ("main", "lazy") or not isinstance(choices, list) or not 1 <= len(choices) <= 100:
        _fail(400, "Choose Main or Lazy and at least one account")
    requested = {}
    for choice in choices:
        if not isinstance(choice, dict) or type(choice.get("prefer_crystal_1_or_lower")) is not bool:
            _fail(400, "Choose a league preference for each account")
        try:
            value = tag(choice.get("tag"))
        except ValueError:
            _fail(400, "Invalid player tag")
        if value in requested:
            _fail(400, "Account selected twice")
        requested[value] = choice["prefer_crystal_1_or_lower"] if pool == "lazy" else False
    sid = _sid(request)
    with _store(request).tx() as db:
        if _season(db, sid)["status"] != "draft":
            _fail(423, "Archived seasons cannot be changed")
    available = {account["tag"]: account for account in await _accounts(request, uid)}
    if not set(requested) <= set(available):
        _fail(409, "An account is no longer linked to this member. Reload their accounts.")
    _check_signup_pool(pool, [available[value] for value in requested])
    with _store(request).tx() as db:
        if _season(db, sid)["status"] != "draft":
            _fail(423, "Archived seasons cannot be changed")
        # Validate the whole batch under the write lock; never replace a signup.
        for value in requested:
            if db.execute("SELECT 1 FROM signups WHERE season_id=? AND tag=?", (sid, value)).fetchone():
                _fail(409, "An account is already signed up. Reload the list; use Roster builder to move it.")
        for value, preference in requested.items():
            account = available[value]
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall,signup_clan_tag,signup_clan_name) VALUES (?,?,?,?,?,?,?,?,?)",
                       (sid, value, uid, pool, int(preference), account["name"], account["town_hall"], account["current_clan_tag"], account["current_clan_name"]))
            if account.get("current_clan_type"):
                db.execute("UPDATE signups SET signup_clan_type=CASE WHEN signup_clan_type='FWA' OR ?='FWA' THEN 'FWA' ELSE COALESCE(signup_clan_type,?) END WHERE season_id=? AND tag=?", (account["current_clan_type"], account["current_clan_type"], sid, value))
            after = db.execute("SELECT * FROM signups WHERE season_id=? AND tag=?", (sid, value)).fetchone()
            _audit(db, sid, value, actor["user_id"], "staff_signup", None, dict(after))
        _bump(db, sid)
    return web.json_response({"ok": True, "count": len(requested)}, status=201)


async def staff_remove_signup(request):
    actor = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision"}:
        _fail(400, "Expected roster revision")
    sid = _sid(request)
    try:
        value = tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid player tag")
    with _store(request).tx() as db:
        if _season(db, sid)["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body["revision"])
        signup = db.execute("SELECT * FROM signups WHERE season_id=? AND tag=?", (sid, value)).fetchone()
        if signup is None:
            _fail(404, "Signup not found")
        entry = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, value)).fetchone()
        _audit(db, sid, value, actor["user_id"], "staff_remove_signup",
               {"signup": dict(signup), "roster": dict(entry) if entry else None}, None)
        db.execute("DELETE FROM signups WHERE season_id=? AND tag=?", (sid, value))
        _bump(db, sid)
    return web.json_response({"ok": True})


async def withdraw(request):
    from utils.cwl_member_service import MemberError, withdraw as member_withdraw

    session = _require(request)
    sid = _sid(request)
    try:
        result = member_withdraw(
            _store(request), sid, session["user_id"], request.match_info["tag"],
            selected_only=not _editor(request, session),
        )
    except MemberError as exc:
        _fail(exc.status, str(exc))
    return web.json_response({"ok": result["ok"]})


def _roster_rows(db, sid):
    rows = db.execute(
        "SELECT s.*,r.source_weight,r.source_status,r.source_name,r.source_checked_at,r.source_modified_at,"
        "r.manual_weight,r.assigned_clan_tag,r.kept FROM signups s "
        "LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag "
        "WHERE s.season_id=? ORDER BY s.tag", (sid,)
    ).fetchall()
    signed_up = signup_timestamps(db, sid)
    official = saved_sources(db, [row["tag"] for row in rows])
    result = []
    for raw in rows:
        row = dict(raw)
        row["signed_up_at"] = signed_up.get(row["tag"])
        if row["tag"] in official:
            source = official[row["tag"]]
            row.update(source_weight=source["weight"], source_name=source["source_name"],
                       source_modified_at=source["source_modified_at"], source_checked_at=source["source_checked_at"],
                       source_status="current" if source["weight"] is not None else "missing")
        row["prefer_crystal_1_or_lower"] = bool(row["prefer_crystal_1_or_lower"])
        row["source_status"] = row["source_status"] or "missing"
        row["kept"] = bool(row["kept"])
        saved_weight = db.execute("SELECT initial_weight FROM player_weights WHERE tag=?", (row["tag"],)).fetchone()
        row["initial_manual_weight"] = saved_weight["initial_weight"] if saved_weight else None
        row["weight_revision"] = official.get(row["tag"], {}).get("weight_revision", 0)
        row["weight_storages"] = official.get(row["tag"], {}).get("weight_storages")
        row["clan_weight_managed"] = row["tag"] in official
        for field in ('clan_weight_clan_tag', 'clan_weight_clan_name', 'clan_weight_saved_at'):
            row[field] = official.get(row['tag'], {}).get(field)
        row["effective_weight"] = (row["source_weight"] if row["clan_weight_managed"] else
                                   row["manual_weight"] if row["manual_weight"] is not None else row["source_weight"])
        result.append(row)
    return result


def _rule_rows(db, sid):
    rows = db.execute(
        "SELECT c.tag,c.name,c.archived,COALESCE(r.pool,c.pool) AS pool,r.capacity,r.min_weight,r.max_weight,"
        "(SELECT COUNT(*) FROM roster_entries e WHERE e.season_id=? "
        "AND e.assigned_clan_tag=c.tag) AS assigned_count "
        "FROM clans c LEFT JOIN lineup_rules r ON r.season_id=? AND r.tag=c.tag "
        "WHERE c.archived=0 OR EXISTS (SELECT 1 FROM roster_entries e "
        "WHERE e.season_id=? AND e.assigned_clan_tag=c.tag) "
        "ORDER BY c.name,c.tag", (sid, sid, sid)
    ).fetchall()
    result = []
    for raw in rows:
        row = dict(raw)
        row["archived"] = bool(row["archived"])
        row["effective_capacity"] = row["capacity"] if row["capacity"] is not None else 50
        result.append(row)
    return result


async def roster(request):
    session = _require(request, "editor")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        result = {"revision": _revision(db, sid), "accounts": _roster_rows(db, sid),
                  "clans": _rule_rows(db, sid),
                  "undo": _current_undo(db, sid, session["user_id"]) if season["status"] == "draft" else None}
        placements, blocked = _auto_plan(db, sid)
        reasons = {item["tag"]: item["reason"] for item in blocked}
        reasons.update({item["tag"]: "ready" for item in placements})
        for account in result["accounts"]:
            reason = reasons.get(account["tag"])
            account["auto_placement_reason"] = reason
            account["auto_placement_note"] = explain_placement(account, result["clans"], reason) if reason else None
    if request.query.get("background") == "1":
        from .roster_metadata import enrich as enrich_metadata
        family = await enrich_metadata(request, result)
    else:
        from .roster_locations import enrich as enrich_locations
        family, _, _ = await asyncio.gather(
            _family_tags(request), enrich_clan_metadata(request, result["clans"]),
            enrich_locations(request, result["accounts"]),
        )
    if request.query.get('background') == '1':
        import time
        cached_family = request.app.get('roster_family_snapshot')
        fwa_tags = (cached_family[2] if cached_family and len(cached_family) > 2
                    and cached_family[0] > time.monotonic() else None)
    else:
        from .clan_weight_trial import family as weight_family
        try:
            fwa_tags = {clan['tag'] for clan in await weight_family(request)}
        except ProviderUnavailable:
            fwa_tags = None
    for account in result['accounts']:
        known = account.get('current_clan_status') == 'current' and fwa_tags is not None
        account['current_fwa_clan_tag'] = (
            account.get('current_clan_tag') if known and account.get('current_clan_tag') in fwa_tags else None)
        account['current_fwa_status'] = 'current' if known else 'unavailable'
    hosting_tags = {clan["tag"] for clan in result["clans"] if not clan["archived"]}
    for account in result["accounts"]:
        # Unknown/stale locations or directory outages are not proof of an outside clan.
        account["outside_family_and_hosts"] = bool(
            account["current_clan_status"] == "current"
            and account["current_clan_tag"]
            and family is not None
            and account["current_clan_tag"] not in family
            and account["current_clan_tag"] not in hosting_tags
        )
    from .roster_owner_names import enrich as enrich_owner_names
    enrich_owner_names(request, result)
    return web.json_response(result)


async def arrival_check(request):
    _require(request, "editor")
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        latest = _latest_publication(db, sid)
        requested_source = request.query.get('source', 'draft')
        if requested_source not in ('draft', 'published'):
            _fail(400, 'Invalid roster source')
        published = latest is not None and requested_source == 'published'
        publication_outdated = _publication_changed(db, sid, latest)
        current_tags = {row['tag'] for row in db.execute('SELECT tag FROM signups WHERE season_id=?', (sid,))}
        published_tags = {row['tag'] for row in db.execute('SELECT tag FROM publication_accounts WHERE publication_id=?', (latest['id'],))} if latest else set()
        if published:
            accounts = [dict(row) for row in db.execute(
                'SELECT tag,user_id,player_name,town_hall,pool,assigned_clan_tag,assigned_clan_name FROM publication_accounts WHERE publication_id=?', (latest['id'],))]
        else:
            accounts = _roster_rows(db, sid)
            names = {row['tag']:row['name'] for row in db.execute('SELECT tag,name FROM clans')}
            for account in accounts: account['assigned_clan_name'] = names.get(account['assigned_clan_tag'])
        clan_pools = {row['tag']: row['pool'] for row in _rule_rows(db, sid)}
        for account in accounts:
            account['hosting_pool'] = clan_pools.get(account['assigned_clan_tag']) or account['pool']
    from .roster_locations import enrich, background_enrich
    updating = False
    if request.query.get('background') == '1':
        updating = await background_enrich(request, accounts, force=request.query.get('refresh') == '1')
    else:
        await enrich(request, accounts, force=request.query.get('refresh') == '1')
    family = await _family_tags(request)
    for account in accounts:
        current = account['current_clan_status'] == 'current'
        account['arrival_status'] = ('unassigned' if not account['assigned_clan_tag'] else
            'unknown' if not current else 'arrived' if account['current_clan_tag'] == account['assigned_clan_tag'] else 'missing')
        account['outside_family'] = current and family is not None and account['current_clan_tag'] not in family
    return web.json_response({'source':'published' if published else 'draft',
        'version':latest['version'] if published else None, 'accounts':accounts, 'updating':updating,
        'publication_available': latest is not None, 'publication_outdated': publication_outdated,
        'published_at': latest['published_at'] if latest else None,
        'removed_since_publication': len(published_tags - current_tags),
        'added_since_publication': len(current_tags - published_tags) if latest else 0})


async def update_lineup_rules(request):
    session = _require(request, "editor")
    body = await _json(request)
    allowed = {"revision", "pool", "capacity", "min_weight", "max_weight"}
    if not set(body) <= allowed or not (set(body) - {"revision"}):
        _fail(400, "Invalid hosting rule update")
    try:
        clan_tag = tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid clan tag")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body.get("revision"))
        clan = db.execute("SELECT archived FROM clans WHERE tag=?", (clan_tag,)).fetchone()
        if clan is None or clan["archived"]:
            _fail(404, "Active hosting clan not found")
        db.execute("INSERT OR IGNORE INTO lineup(season_id,tag) VALUES (?,?)", (sid, clan_tag))
        before_row = db.execute("SELECT pool,capacity,min_weight,max_weight FROM lineup_rules WHERE season_id=? AND tag=?", (sid, clan_tag)).fetchone()
        before = dict(before_row) if before_row else {"pool": None, "capacity": None, "min_weight": None, "max_weight": None}
        rule = {field: body.get(field, before[field]) for field in ("pool", "capacity", "min_weight", "max_weight")}
        if rule["pool"] not in (None, "main", "lazy"):
            _fail(400, "Invalid pool rule")
        if type(rule["capacity"]) is not int and rule["capacity"] is not None or rule["capacity"] not in (None, 15, 30):
            _fail(400, "Capacity must be 15 or 30")
        for field in ("min_weight", "max_weight"):
            value = rule[field]
            if value is not None and (type(value) is not int or value <= 0 or value > 1_000_000_000):
                _fail(400, "Invalid weight range")
        if rule["min_weight"] is not None and rule["max_weight"] is not None and rule["min_weight"] >= rule["max_weight"]:
            _fail(400, "Maximum weight must exceed minimum")
        db.execute("INSERT INTO lineup_rules(season_id,tag,pool,capacity,min_weight,max_weight) "
                   "VALUES (?,?,?,?,?,?) ON CONFLICT(season_id,tag) DO UPDATE SET "
                   "pool=excluded.pool,capacity=excluded.capacity,min_weight=excluded.min_weight,"
                   "max_weight=excluded.max_weight",
                   (sid, clan_tag, rule["pool"], rule["capacity"], rule["min_weight"], rule["max_weight"]))
        revision = _bump(db, sid)
        _audit(db, sid, clan_tag, session["user_id"], "hosting_rules", before, rule)
    return web.json_response({"revision": revision})


def _active_destination_capacity(db, sid, clan_tag):
    row = db.execute(
        "SELECT c.archived,r.capacity FROM clans c LEFT JOIN lineup_rules r "
        "ON r.season_id=? AND r.tag=c.tag WHERE c.tag=?", (sid, clan_tag)
    ).fetchone()
    if row is None or row["archived"]:
        _fail(409, "Hosting clan is archived or missing")
    return row["capacity"] if row["capacity"] is not None else 50


async def bulk_assign_roster(request):
    session = _require(request, "editor")
    body = await _json(request)
    if not {"revision", "tags", "assigned_clan_tag"} <= set(body) or not set(body) <= {"revision", "tags", "assigned_clan_tag", "include_locked"}:
        _fail(400, "Expected revision, tags, and assigned_clan_tag")
    supplied = body["tags"]
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 50:
        _fail(400, "Select 1 to 50 accounts")
    try:
        tags = [tag(value) for value in supplied]
    except ValueError:
        _fail(400, "Invalid player tag")
    if len(set(tags)) != len(tags):
        _fail(400, "Duplicate player tag")
    destination = body["assigned_clan_tag"]
    if destination is not None:
        try:
            destination = tag(destination)
        except ValueError:
            _fail(400, "Invalid hosting clan tag")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body["revision"])
        placeholders = ",".join("?" for _ in tags)
        rows = db.execute(
            f"SELECT tag FROM signups WHERE season_id=? AND tag IN ({placeholders})",
            (sid, *tags),
        ).fetchall()
        if len(rows) != len(tags):
            _fail(404, "One or more signed-up accounts were not found")
        if "include_locked" in body:
            if type(body["include_locked"]) is not bool:
                _fail(400, "Invalid lock option")
            if not body["include_locked"] and db.execute(
                f"SELECT 1 FROM roster_entries WHERE season_id=? AND kept=1 AND tag IN ({placeholders})",
                (sid, *tags),
            ).fetchone():
                _fail(409, "Locked placements changed; refresh and select again")
        if destination is not None:
            capacity = _active_destination_capacity(db, sid, destination)
            selected_already = db.execute(
                f"SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? "
                f"AND assigned_clan_tag=? AND tag IN ({placeholders})",
                (sid, destination, *tags),
            ).fetchone()["n"]
            current = db.execute(
                "SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? AND assigned_clan_tag=?",
                (sid, destination),
            ).fetchone()["n"]
            if current - selected_already + len(tags) > capacity:
                _fail(409, "Hosting clan is full")
            db.execute("INSERT OR IGNORE INTO lineup(season_id,tag) VALUES (?,?)", (sid, destination))
        changes = []
        for player_tag in tags:
            old = db.execute(
                "SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)
            ).fetchone()
            before = dict(old) if old else None
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,?) "
                "ON CONFLICT(season_id,tag) DO UPDATE SET "
                "assigned_clan_tag=excluded.assigned_clan_tag,kept=excluded.kept",
                (sid, player_tag, destination, int(destination is not None)),
            )
            after = dict(db.execute(
                "SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)
            ).fetchone())
            _audit(db, sid, player_tag, session["user_id"], "bulk_roster_assign", before, after)
            changes.append({"tag": player_tag, "before": _placement(before),
                            "after": _placement(after)})
        revision = _bump(db, sid)
        verb = "Assign" if destination is not None else "Unassign"
        _record_undo(db, sid, session["user_id"],
                     f"{verb} {len(tags)} account{'s' if len(tags) != 1 else ''}", revision, changes)
    return web.json_response({"revision": revision, "updated": len(tags)})


async def update_roster_account(request):
    session = _require(request, "editor")
    body = await _json(request)
    allowed = {"revision", "manual_weight", "weight_revision", "weight_storages", "assigned_clan_tag", "kept"}
    if not set(body) <= allowed or not (set(body) - {"revision"}):
        _fail(400, "Invalid roster update")
    if "manual_weight" in body:
        from .clan_weight_trial import authorize
        authorize(request)
        if type(body.get("weight_revision")) is not int or not 0 <= body["weight_revision"] < 2**63:
            _fail(400, "Expected weight revision")
    elif "weight_revision" in body or "weight_storages" in body:
        _fail(400, "Weight metadata requires a weight")
    try:
        player_tag = tag(request.match_info["tag"])
    except ValueError:
        _fail(400, "Invalid player tag")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body.get("revision"))
        if not db.execute("SELECT 1 FROM signups WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone():
            _fail(404, "Signed-up account not found")
        old = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone()
        before = dict(old) if old else None
        manual = old["manual_weight"] if old else None
        if manual is not None and (type(manual) is not int or manual <= 0 or manual > 1_000_000_000):
            _fail(400, "Invalid manual weight")
        assigned = body.get("assigned_clan_tag", old["assigned_clan_tag"] if old else None)
        if "assigned_clan_tag" in body and assigned is not None:
            try:
                assigned = tag(assigned)
            except ValueError:
                _fail(400, "Invalid hosting clan tag")
            capacity = _active_destination_capacity(db, sid, assigned)
            count = db.execute("SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? "
                               "AND assigned_clan_tag=? AND tag<>?", (sid, assigned, player_tag)).fetchone()["n"]
            if count >= capacity:
                _fail(409, "Hosting clan is full")
            db.execute("INSERT OR IGNORE INTO lineup(season_id,tag) VALUES (?,?)", (sid, assigned))
        kept = body.get("kept", True if "assigned_clan_tag" in body else bool(old["kept"]) if old else False)
        if type(kept) is not bool:
            _fail(400, "kept must be a boolean")
        db.execute("INSERT INTO roster_entries(season_id,tag,manual_weight,assigned_clan_tag,kept) "
                   "VALUES (?,?,?,?,?) ON CONFLICT(season_id,tag) DO UPDATE SET "
                   "manual_weight=excluded.manual_weight,assigned_clan_tag=excluded.assigned_clan_tag,kept=excluded.kept",
                   (sid, player_tag, manual, assigned, int(kept)))
        after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone())
        weight_changed = False
        if "manual_weight" in body:
            from utils.clan_weight_store import ClanWeightStore, WeightConflict
            change = {"weight": body["manual_weight"], "revision": body["weight_revision"]}
            if "weight_storages" in body:
                change["storages"] = body["weight_storages"]
            try:
                weight_changed = ClanWeightStore.save_roster(
                    db, sid, player_tag, change, session["user_id"],
                    session.get("display_name") or session.get("username"))
            except WeightConflict as exc:
                _fail(409, str(exc))
            except ValueError as exc:
                _fail(400, str(exc))
        revision = _revision(db, sid) if weight_changed else _bump(db, sid)
        _audit(db, sid, player_tag, session["user_id"], "manual_roster_edit", before, after)
        _record_undo(db, sid, session["user_id"], "Edit account placement", revision,
                     [{"tag": player_tag, "before": _placement(before),
                       "after": _placement(after)}])
    return web.json_response({"revision": revision})


async def swap_roster(request):
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "left_tag", "right_tag"}:
        _fail(400, "Expected revision, left_tag, and right_tag")
    try:
        left_tag = tag(body["left_tag"])
        right_tag = tag(body["right_tag"])
    except ValueError:
        _fail(400, "Invalid player tag")
    if left_tag == right_tag:
        _fail(400, "Choose two different accounts")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body["revision"])
        rows = {}
        for player_tag in (left_tag, right_tag):
            if not db.execute("SELECT 1 FROM signups WHERE season_id=? AND tag=?",
                              (sid, player_tag)).fetchone():
                _fail(404, "Signed-up account not found")
            row = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?",
                             (sid, player_tag)).fetchone()
            if row is None or row["assigned_clan_tag"] is None:
                _fail(409, "Both accounts must be assigned")
            rows[player_tag] = dict(row)
        left_host = rows[left_tag]["assigned_clan_tag"]
        right_host = rows[right_tag]["assigned_clan_tag"]
        if left_host == right_host:
            _fail(409, "Accounts must be in different hosting clans")
        for host in (left_host, right_host):
            capacity = _active_destination_capacity(db, sid, host)
            occupancy = db.execute(
                "SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? AND assigned_clan_tag=?",
                (sid, host),
            ).fetchone()["n"]
            if occupancy > capacity:
                _fail(409, "Hosting clan exceeds capacity")
        changes = []
        for player_tag, target in ((left_tag, right_host), (right_tag, left_host)):
            before = rows[player_tag]
            db.execute("UPDATE roster_entries SET assigned_clan_tag=?,kept=1 "
                       "WHERE season_id=? AND tag=?", (target, sid, player_tag))
            after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?",
                                    (sid, player_tag)).fetchone())
            _audit(db, sid, player_tag, session["user_id"], "roster_swap", before, after)
            changes.append({"tag": player_tag, "before": _placement(before),
                            "after": _placement(after)})
        revision = _bump(db, sid)
        _record_undo(db, sid, session["user_id"], "Swap two accounts", revision, changes)
    return web.json_response({"revision": revision})


async def undo_roster(request):
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "undo_id"} or type(body["undo_id"]) is not int or body["undo_id"] < 1:
        _fail(400, "Expected revision and undo_id")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body["revision"])
        undo = db.execute(
            "SELECT * FROM roster_undo WHERE id=? AND season_id=? AND actor_id=?",
            (body["undo_id"], sid, session["user_id"]),
        ).fetchone()
        if undo is None:
            _fail(404, "Undo action not found")
        if undo["consumed_at"] is not None or undo["revision"] != _revision(db, sid):
            _fail(409, "Undo is no longer available")
        changes = json.loads(undo["changes_json"])
        if not isinstance(changes, list) or not changes:
            _fail(409, "Invalid undo record")
        current = {}
        occupancy_delta = {}
        restored_hosts = set()
        seen = set()
        for change in changes:
            player_tag = change["tag"]
            if player_tag in seen:
                _fail(409, "Invalid undo record")
            seen.add(player_tag)
            if not db.execute("SELECT 1 FROM signups WHERE season_id=? AND tag=?",
                              (sid, player_tag)).fetchone():
                _fail(409, "Roster account changed")
            row = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?",
                             (sid, player_tag)).fetchone()
            before = dict(row) if row else None
            if _placement(before) != change["after"]:
                _fail(409, "Roster placement changed")
            current[player_tag] = before
            old_host = change["after"]["assigned_clan_tag"]
            restored_host = change["before"]["assigned_clan_tag"]
            if old_host:
                occupancy_delta[old_host] = occupancy_delta.get(old_host, 0) - 1
            if restored_host:
                restored_hosts.add(restored_host)
                occupancy_delta[restored_host] = occupancy_delta.get(restored_host, 0) + 1
        for host in restored_hosts:
            capacity = _active_destination_capacity(db, sid, host)
            count = db.execute("SELECT COUNT(*) AS n FROM roster_entries WHERE season_id=? "
                               "AND assigned_clan_tag=?", (sid, host)).fetchone()["n"]
            if count + occupancy_delta[host] > capacity:
                _fail(409, "Undo would exceed hosting clan capacity")
        for change in changes:
            player_tag = change["tag"]
            restored = change["before"]
            before = current[player_tag]
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,?) "
                "ON CONFLICT(season_id,tag) DO UPDATE SET "
                "assigned_clan_tag=excluded.assigned_clan_tag,kept=excluded.kept",
                (sid, player_tag, restored["assigned_clan_tag"], int(restored["kept"])),
            )
            after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?",
                                    (sid, player_tag)).fetchone())
            _audit(db, sid, player_tag, session["user_id"], "roster_undo_account", before, after)
        db.execute("UPDATE roster_undo SET consumed_at=CURRENT_TIMESTAMP WHERE id=?", (undo["id"],))
        revision = _bump(db, sid)
        _audit(db, sid, None, session["user_id"], "roster_undo", {"undo_id": undo["id"]},
               {"revision": revision})
    return web.json_response({"revision": revision})


def _auto_plan(db, sid, pool=None):
    accounts = _roster_rows(db, sid)
    clans = _rule_rows(db, sid)
    counts = {clan["tag"]: clan["assigned_count"] for clan in clans}
    totals = {clan["tag"]: 0 for clan in clans}
    for account in accounts:
        if account["assigned_clan_tag"] in totals and account["effective_weight"] is not None:
            totals[account["assigned_clan_tag"]] += account["effective_weight"]
    candidates = sorted((a for a in accounts if a["assigned_clan_tag"] is None and (pool is None or a["pool"] == pool)),
                        key=lambda a: (-(a["effective_weight"] or 0), a["tag"]))
    placements = []
    unassigned = []
    for account in candidates:
        if account["kept"]:
            unassigned.append({"tag": account["tag"], "reason": "kept"})
            continue
        weight = account["effective_weight"]
        if account["manual_weight"] is None and account["source_status"] == "unavailable":
            unassigned.append({"tag": account["tag"], "reason": "source_unavailable"})
            continue
        if weight is None:
            unassigned.append({"tag": account["tag"], "reason": "missing_weight"})
            continue
        eligible = []
        for clan in clans:
            if clan["archived"] or clan["pool"] != account["pool"] or clan["capacity"] not in (15, 30):
                continue
            if clan["min_weight"] is not None and weight < clan["min_weight"]:
                continue
            if clan["max_weight"] is not None and weight > clan["max_weight"]:
                continue
            eligible.append(clan)
        if not eligible:
            unassigned.append({"tag": account["tag"], "reason": "no_eligible_rule"})
            continue
        available = [clan for clan in eligible if counts[clan["tag"]] < clan["capacity"]]
        if not available:
            unassigned.append({"tag": account["tag"], "reason": "full"})
            continue
        chosen = min(available, key=lambda clan: (counts[clan["tag"]], totals[clan["tag"]], clan["tag"]))
        counts[chosen["tag"]] += 1
        totals[chosen["tag"]] += weight
        placements.append({"tag": account["tag"], "assigned_clan_tag": chosen["tag"]})
    return placements, unassigned


def _requested_plan(db, sid, body, pool):
    if body.get("mode") != "balance":
        if body.get("mode") is not None:
            _fail(400, "Invalid placement mode")
        return _auto_plan(db, sid, pool)
    from utils.cwl_balance import balance_accounts
    def tags_field(field):
        values = body.get(field)
        if not isinstance(values, list) or not 1 <= len(values) <= 50:
            _fail(400, "Choose 1 to 50 accounts or clans")
        try:
            result = [tag(value) for value in values]
        except (ValueError, TypeError):
            _fail(400, "Invalid tag")
        if len(set(result)) != len(result):
            _fail(400, "Duplicate tag")
        return result
    selected, destinations = tags_field("tags"), tags_field("clan_tags")
    if type(body.get("include_locked", False)) is not bool:
        _fail(400, "Invalid lock option")
    accounts, clans = _roster_rows(db, sid), _rule_rows(db, sid)
    if not set(selected) <= {a['tag'] for a in accounts}:
        _fail(409, "Selected accounts changed; refresh the roster")
    if not set(destinations) <= {c['tag'] for c in clans if not c['archived']}:
        _fail(409, "Selected hosting clans changed; refresh the roster")
    return balance_accounts(accounts, clans, selected, destinations, body.get("include_locked", False))


async def auto_preview(request):
    _require(request, "editor")
    body = await _json(request)
    pool = body.get("pool")
    if pool not in (None, "main", "lazy"):
        _fail(400, "Choose Main or Lazy CWL")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body.get("revision"))
        placements, unassigned = _requested_plan(db, sid, body, pool)
        revision = _revision(db, sid)
    return web.json_response({"revision": revision, "placements": placements, "unassigned": unassigned})


async def auto_apply(request):
    session = _require(request, "editor")
    body = await _json(request)
    submitted = body.get("placements")
    if not isinstance(submitted, list):
        _fail(400, "Preview placements are required")
    pool = body.get("pool")
    if pool not in (None, "main", "lazy"):
        _fail(400, "Choose Main or Lazy CWL")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body.get("revision"))
        placements, _ = _requested_plan(db, sid, body, pool)
        if submitted != placements:
            _fail(409, "Preview changed; refresh before applying")
        changes = []
        for placement in placements:
            player_tag = placement["tag"]
            clan_tag = placement["assigned_clan_tag"]
            old = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone()
            before = dict(old) if old else None
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,0) "
                       "ON CONFLICT(season_id,tag) DO UPDATE SET assigned_clan_tag=excluded.assigned_clan_tag",
                       (sid, player_tag, clan_tag))
            after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone())
            _audit(db, sid, player_tag, session["user_id"], "balance_place" if body.get("mode") == "balance" else "auto_place", before, after)
            changes.append({"tag": player_tag, "before": _placement(before),
                            "after": _placement(after)})
        revision = _bump(db, sid) if placements else _revision(db, sid)
        if placements:
            _record_undo(db, sid, session["user_id"], "Balance selected accounts" if body.get("mode") == "balance" else "Auto-place accounts", revision, changes)
    return web.json_response({"revision": revision, "applied": len(placements)})


async def refresh_weights(request):
    session = _require(request, "editor")
    body = await _json(request)
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        _check_revision(db, sid, body.get("revision"))
        tags = [row["tag"] for row in db.execute("SELECT tag FROM signups WHERE season_id=?", (sid,))]
    try:
        found = await source_weights(_store(request), request.app["providers"], tags)
    except ProviderUnavailable:
        with _store(request).tx() as db:
            _check_revision(db, sid, body.get("revision"))
            for player_tag in tags:
                old = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone()
                before = dict(old) if old else None
                db.execute("INSERT INTO roster_entries(season_id,tag,source_status) "
                           "VALUES (?,?,'unavailable') ON CONFLICT(season_id,tag) DO UPDATE SET "
                           "source_status='unavailable'", (sid, player_tag))
                after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone())
                _audit(db, sid, player_tag, session["user_id"], "weight_refresh_failed", before, after)
            if tags:
                _bump(db, sid)
        _fail(503, "FWA weight source unavailable; previous values retained")
    if not isinstance(found, dict) or not set(found) <= set(tags):
        _fail(503, "Invalid FWA weight response")
    for item in found.values():
        if not isinstance(item, dict) or type(item.get("weight")) is not int or item["weight"] <= 0 or item["weight"] > 1_000_000_000 or not isinstance(item.get("source_name"), str) or (item.get("source_modified_at") is not None and not isinstance(item.get("source_modified_at"), str)):
            _fail(503, "Invalid FWA weight response")
    checked_at = getattr(request.app["providers"], "weights_checked_at", None) or datetime.now(timezone.utc).isoformat()
    with _store(request).tx() as db:
        _check_revision(db, sid, body.get("revision"))
        for player_tag in tags:
            item = found.get(player_tag)
            old = db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone()
            before = dict(old) if old else None
            status = "current" if item else "missing"
            weight = item["weight"] if item else None
            source_name = item["source_name"] if item else None
            source_modified_at = item.get("source_modified_at") if item else None
            item_checked_at = item.get("source_checked_at", checked_at) if item else checked_at
            db.execute("INSERT INTO roster_entries(season_id,tag,source_weight,source_status,source_name,source_checked_at,source_modified_at) "
                       "VALUES (?,?,?,?,?,?,?) ON CONFLICT(season_id,tag) DO UPDATE SET "
                       "source_weight=excluded.source_weight,source_status=excluded.source_status,"
                       "source_name=excluded.source_name,source_checked_at=excluded.source_checked_at,"
                       "source_modified_at=excluded.source_modified_at",
                       (sid, player_tag, weight, status, source_name, item_checked_at, source_modified_at))
            after = dict(db.execute("SELECT * FROM roster_entries WHERE season_id=? AND tag=?", (sid, player_tag)).fetchone())
            _audit(db, sid, player_tag, session["user_id"], "weight_refresh", before, after)
        revision = _bump(db, sid) if tags else _revision(db, sid)
    return web.json_response({"revision": revision, "refreshed": len(found), "missing": len(tags)-len(found)})


def _publication_meta(row):
    if row is None:
        return None
    return {key: row[key] for key in (
        "version", "revision", "published_at", "published_by",
        "joining_instructions", "assigned_count", "unassigned_count",
    )}


def _latest_publication(db, sid):
    return db.execute(
        "SELECT * FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1",
        (sid,),
    ).fetchone()


def _publication_changed(db, sid, latest):
    """Compare saved roster content; season administration is not a roster edit."""
    if latest is None:
        return False
    if _revision(db, sid) == latest["revision"] + 1:
        return False
    fields = (
        "tag", "user_id", "player_name", "town_hall", "pool",
        "prefer_crystal_1_or_lower", "signup_clan_tag", "signup_clan_name",
        "assigned_clan_tag", "assigned_clan_name", "source_weight", "source_status",
        "source_name", "source_checked_at", "source_modified_at", "manual_weight",
        "effective_weight", "kept",
    )
    names = {row["tag"]: row["name"] for row in db.execute("SELECT tag,name FROM clans")}
    current = {}
    for row in _roster_rows(db, sid):
        row["assigned_clan_name"] = names.get(row["assigned_clan_tag"])
        current[row["tag"]] = tuple(row.get(field) for field in fields)
    published = {
        row["tag"]: tuple(row[field] for field in fields)
        for row in db.execute("SELECT * FROM publication_accounts WHERE publication_id=?", (latest["id"],))
    }
    return current != published


async def publication_preview(request):
    _require(request, "editor")
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        accounts = _roster_rows(db, sid)
        clans = _rule_rows(db, sid)
        assigned = sum(account["assigned_clan_tag"] is not None for account in accounts)
        latest = _latest_publication(db, sid)
        last_publication = db.execute(
            "SELECT version,published_at,withdrawn_at,joining_instructions FROM roster_publications "
            "WHERE season_id=? ORDER BY version DESC LIMIT 1", (sid,),
        ).fetchone()
        next_version = db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM roster_publications WHERE season_id=?", (sid,),
        ).fetchone()[0]
        revision = _revision(db, sid)
        result = {
            "last_publication": dict(last_publication) if last_publication is not None else None,
            "next_version": next_version,
            "draft_revision": revision,
            "draft_changed": _publication_changed(db, sid, latest),
            "preview": {
                "accounts": accounts,
                "clans": clans,
                "assigned_count": assigned,
                "unassigned_count": len(accounts) - assigned,
            },
            "published": _publication_meta(latest),
        }
    return web.json_response(result)


async def publish_roster(request):
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "acknowledge_unassigned", "joining_instructions"}:
        _fail(400, "Expected revision, acknowledge_unassigned, and joining_instructions")
    revision = body["revision"]
    if type(revision) is not int or revision < 0:
        _fail(400, "Invalid roster revision")
    acknowledged = _body_bool(body, "acknowledge_unassigned")
    instructions = body["joining_instructions"]
    if not isinstance(instructions, str) or len(instructions) > 2000:
        _fail(400, "Joining instructions must be at most 2000 characters")
    sid = _sid(request)
    with _store(request).tx() as db:
        season = _season(db, sid)
        if season["status"] != "draft":
            _fail(423, "Season is archived")
        latest = _latest_publication(db, sid)
        if latest and latest["revision"] == revision and latest["joining_instructions"] == instructions:
            return web.json_response({"published": _publication_meta(latest)})
        _check_revision(db, sid, revision)
        accounts = _roster_rows(db, sid)
        if not accounts:
            _fail(409, "No signed-up accounts to publish")
        clans = _rule_rows(db, sid)
        assigned = sum(account["assigned_clan_tag"] is not None for account in accounts)
        unassigned = len(accounts) - assigned
        if unassigned and not acknowledged:
            _fail(409, "Unassigned accounts require explicit acknowledgement")
        clan_names = {clan["tag"]: clan["name"] for clan in clans}
        version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM roster_publications WHERE season_id=?", (sid,)).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute(
            "INSERT INTO roster_publications(season_id,version,revision,published_by,published_at,"
            "joining_instructions,assigned_count,unassigned_count,clans_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, version, revision, session["user_id"], now, instructions,
             assigned, unassigned, json.dumps(clans, sort_keys=True)),
        )
        publication_id = cursor.lastrowid
        for account in accounts:
            db.execute(
                "INSERT INTO publication_accounts(publication_id,tag,user_id,player_name,town_hall,pool,"
                "prefer_crystal_1_or_lower,signup_clan_tag,signup_clan_name,assigned_clan_tag,"
                "assigned_clan_name,source_weight,source_status,source_name,source_checked_at,"
                "source_modified_at,manual_weight,effective_weight,kept) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (publication_id, account["tag"], account["user_id"], account["player_name"],
                 account["town_hall"], account["pool"], int(account["prefer_crystal_1_or_lower"]),
                 account["signup_clan_tag"], account["signup_clan_name"],
                 account["assigned_clan_tag"], clan_names.get(account["assigned_clan_tag"]),
                 account["source_weight"], account["source_status"], account["source_name"],
                 account["source_checked_at"], account["source_modified_at"],
                 account["manual_weight"], account["effective_weight"], int(account["kept"])),
            )
        published = _publication_meta(_latest_publication(db, sid))
        _audit(db, sid, None, session["user_id"], "roster_publish",
               _publication_meta(latest), published)
        _bump(db, sid)
    return web.json_response({"published": published}, status=201)


async def withdraw_publication(request):
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"revision", "version"} or any(
        type(body[key]) is not int or body[key] < 0 for key in ("revision", "version")
    ):
        _fail(400, "Expected roster revision and publication version")
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        _check_revision(db, sid, body["revision"])
        latest = _latest_publication(db, sid)
        if latest is None or latest["version"] != body["version"]:
            _fail(409, "Publication changed; refresh before withdrawing")
        # Withdraw all visible versions so an older publication cannot reappear.
        db.execute("UPDATE roster_publications SET withdrawn_at=? "
                   "WHERE season_id=? AND withdrawn_at IS NULL",
                   (datetime.now(timezone.utc).isoformat(), sid))
        _audit(db, sid, None, session["user_id"], "roster_unpublish", _publication_meta(latest), None)
        revision = _bump(db, sid)
    return web.json_response({"published": None, "revision": revision})


async def my_assignments(request):
    from utils.cwl_member_service import MemberError, assignment_view

    session = _require(request)
    sid = _sid(request)
    try:
        result = assignment_view(
            _store(request), session["user_id"], sid,
            selected_only=not _editor(request, session),
        )
    except MemberError as exc:
        _fail(exc.status, str(exc))
    return web.json_response(result)


@web.middleware
async def auth_diagnostics(request, handler):
    if request.path not in {API + "/auth/discord", API + "/auth/callback", API + "/auth/me"}:
        return await handler(request)
    logger = logging.getLogger("cwl.auth")
    stage = request.path.rsplit("/", 1)[-1]
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        # Only application-owned error messages: never URL queries, codes, cookies or tokens.
        outcome = "redirect" if isinstance(exc, web.HTTPRedirection) else exc.text
        logger.info("auth stage=%s status=%s outcome=%s", stage, exc.status, outcome)
        raise
    except Exception as exc:
        logger.error("auth stage=%s exception_type=%s", stage, type(exc).__name__)
        raise
    logger.info("auth stage=%s status=%s", stage, response.status)
    return response


@web.middleware
async def errors(request, handler):
    try:
        response = await handler(request)
    except DashboardDurabilityError as exc:
        response = web.json_response({"error": str(exc)}, status=503)
    except ProviderUnavailable as exc:
        response = web.json_response({"error": str(exc)}, status=503)
        if getattr(exc, "read_retries_exhausted", False) or getattr(exc, "read_retry_blocked", False):
            response.headers["X-Read-Retries-Exhausted"] = "1"
    except web.HTTPException as exc:
        if exc.status >= 500:
            # Preserve only the underlying class, never provider text or credentials.
            cause = exc.__cause__ or exc
            request["dashboard_error_type"] = type(cause).__name__
        if isinstance(exc, web.HTTPRedirection):
            if request.path.startswith(API):
                exc.headers["Cache-Control"] = "no-store"
                exc.headers["X-Content-Type-Options"] = "nosniff"
            raise
        if request.path == API + "/auth/callback" and "text/html" in request.headers.get("Accept", ""):
            destination = saved_login_destination(request)
            separator = "&" if "?" in destination else "?"
            response = web.HTTPFound((destination or "/") + separator + "signin_error=discord")
            response.del_cookie(RETURN_COOKIE, path=API + "/auth")
            response.del_cookie(STATE_COOKIE, path=API + "/auth")
        else:
            response = web.json_response({"error": exc.text or exc.reason}, status=exc.status)
    if request.path.startswith(API):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def create_app(*, db_path=None, durability=None, providers=None, oauth=None, secure_cookies=True, after_login="/", dev_fixture=False, dev_identity=None, static_dir=None, live_access=False):
    """Build an app. Dev fixture requires explicit opt-in and loopback serving."""
    if db_path is None:
        db_path = os.getenv("CWL_WEB_DB_PATH", "")
    if not db_path:
        raise ValueError("CWL_WEB_DB_PATH is required for the dashboard working copy")
    if dev_fixture and dev_identity is None:
        dev_identity = {"id": PERMANENT_OWNER_ID, "username": "Development owner", "guild_owner": False}
    app = web.Application(middlewares=[diagnostics, errors, canonical_host, access_context, auth_diagnostics], client_max_size=32 * 1024)
    from .server_management import mongo_lifecycle
    app.cleanup_ctx.append(mongo_lifecycle)
    from .roster_sequence_jobs import lifecycle as roster_sequence_lifecycle
    app.cleanup_ctx.append(roster_sequence_lifecycle)
    app["store"] = Store(db_path, durability=durability)
    app["live_access"] = live_access
    if dev_fixture and providers is None:
        providers = FixtureProviders(dev_identity["id"])
        with app["store"].tx() as db:
            db.execute("INSERT OR IGNORE INTO seasons(label,signup_open) VALUES ('Development season',1)")
    app["providers"] = providers or LiveProviders()
    app["oauth"] = oauth or {"client_id": os.getenv("CWL_DISCORD_CLIENT_ID", ""), "client_secret": os.getenv("CWL_DISCORD_CLIENT_SECRET", ""), "redirect_uri": os.getenv("CWL_DISCORD_REDIRECT_URI", "")}
    app["secure_cookies"] = secure_cookies
    app["after_login"] = after_login
    app["dev_fixture"] = dev_fixture
    app["dev_identity"] = dev_identity
    app["member_timing_cache"] = {}
    app["member_timing_state"] = {"task": None}
    app["participation_sync_locks"] = {}
    app["dashboard_accounts_cache"] = {}
    app["dashboard_accounts_inflight"] = {}
    app["todo_cache"] = {}
    app["todo_inflight"] = {}
    app["todo_client"] = None
    app["todo_client_lock"] = asyncio.Lock()
    from .durability import lifecycle as durability_lifecycle
    app.cleanup_ctx.append(durability_lifecycle)
    from .member_timing import lifecycle as member_timing_lifecycle
    app.cleanup_ctx.append(member_timing_lifecycle)
    app.cleanup_ctx.append(participation_sync_lifecycle)
    app.cleanup_ctx.append(_dashboard_accounts_lifecycle)
    from .roster_owner_names import lifecycle as owner_nicknames_lifecycle
    app.cleanup_ctx.append(owner_nicknames_lifecycle)
    from .roster_profile_zones import lifecycle as profile_zones_lifecycle
    app.cleanup_ctx.append(profile_zones_lifecycle)
    from .account_display import lifecycle as account_display_lifecycle
    app.cleanup_ctx.append(account_display_lifecycle)
    app.cleanup_ctx.append(todo_lifecycle)
    from .clan_activity import setup as setup_clan_activity
    setup_clan_activity(app)
    from .visitors import setup as setup_visitors
    setup_visitors(app)
    from .war_detail import setup as setup_war_detail
    setup_war_detail(app)
    app.cleanup_ctx.append(push_lifecycle)
    from .roster_locations import lifecycle as location_lifecycle
    app.cleanup_ctx.append(location_lifecycle)
    from .clan_metadata import lifecycle as clan_metadata_lifecycle
    from .roster_metadata import lifecycle as roster_metadata_lifecycle
    app.cleanup_ctx.append(clan_metadata_lifecycle)
    app.cleanup_ctx.append(roster_metadata_lifecycle)
    from .player_weights import lifecycle as player_weights_lifecycle
    app.cleanup_ctx.append(player_weights_lifecycle)
    from .strikes import strike_jobs_lifecycle
    app.cleanup_ctx.append(strike_jobs_lifecycle)
    from .clan_weight_trial import routes as weight_trial_routes
    from utils.clan_weight_store import ClanWeightStore
    app["clan_weight_trial"] = ClanWeightStore(app["store"].path, transaction_factory=app["store"].tx)
    from .clan_weights import lineup_lifecycle
    app.cleanup_ctx.append(lineup_lifecycle)
    from .signup_activity import routes as signup_activity_routes
    from .discord_member import routes as discord_member_routes
    routes = [*discord_member_routes, *staff_signup_change_routes, *weight_trial_routes, *ticket_browser_routes, *staff_tag_signup_routes, *signup_activity_routes,
        web.get(API + "/config", config), web.get(API + "/auth/me", me), web.get(API + "/auth/discord", auth_start), web.get(API + "/auth/callback", auth_callback), web.post(API + "/auth/logout", logout), web.post(API + "/dev/login", dev_login),
        web.put(API + "/member-season", set_member_season), web.get(API + "/seasons", seasons), web.post(API + "/seasons", create_season), web.patch(API + "/seasons/{season_id}", update_season),
        web.get(API + "/clans", clans), web.get(API + "/clans/lookup", lookup_clan), web.post(API + "/clans", create_clan), web.patch(API + "/clans/{tag}", archive_clan),
        web.get(API + "/seasons/{season_id}/lineup", lineup), web.post(API + "/seasons/{season_id}/lineup", add_lineup), web.delete(API + "/seasons/{season_id}/lineup/{tag}", remove_lineup),
        web.patch(API + "/seasons/{season_id}/lineup/{tag}/rules", update_lineup_rules),
        web.get(API + "/seasons/{season_id}/roster", roster),
        web.patch(API + "/seasons/{season_id}/roster/assignments", bulk_assign_roster),
        web.post(API + "/seasons/{season_id}/roster/swap", swap_roster),
        web.post(API + "/seasons/{season_id}/roster/undo", undo_roster),
        web.patch(API + "/seasons/{season_id}/roster/{tag}", update_roster_account),
        web.post(API + "/seasons/{season_id}/roster/auto-preview", auto_preview),
        web.post(API + "/seasons/{season_id}/roster/auto-apply", auto_apply),
        web.post(API + "/seasons/{season_id}/roster/refresh-weights", refresh_weights),
        web.get(API + "/seasons/{season_id}/arrival-check", arrival_check),
        web.get(API + "/seasons/{season_id}/publication", publication_preview),
        web.get(API + "/seasons/{season_id}/export.csv", export_csv),
        web.get(API + "/seasons/{season_id}/export-preview", export_preview),
        web.post(API + "/seasons/{season_id}/publication", publish_roster),
        web.post(API + "/seasons/{season_id}/publication/withdraw", withdraw_publication),
        web.get(API + "/seasons/{season_id}/my-assignments", my_assignments),
        web.get(API + "/approved-clans", approved_clans), web.delete(API + "/approved-clans/{tag}", family_clans_read_only),
        web.get(API + "/access", access), web.post(API + "/access", grant), web.get(API + "/access/roles", access_roles),
        web.get(API + "/staff-signup-members", staff_signup_members), web.get(API + "/seasons/{season_id}/staff-signups/accounts", staff_signup_accounts), web.post(API + "/seasons/{season_id}/staff-signups", staff_add_signup), web.delete(API + "/seasons/{season_id}/staff-signups/{tag}", staff_remove_signup), web.get(API + "/linked-accounts", linked_accounts), web.get(API + "/dashboard/accounts", dashboard_accounts), web.get(API + "/seasons/{season_id}/signups", signups), web.post(API + "/seasons/{season_id}/signups", submit_signup), web.delete(API + "/seasons/{season_id}/signups/{tag}", withdraw),
    ]
    routes.extend(announcement_routes())
    routes.extend(manage_bridge_routes())
    from .roster_images import routes as roster_image_routes
    routes.extend(roster_image_routes())
    from .roster_image_posts import routes as roster_image_post_routes
    routes.extend(roster_image_post_routes())
    routes.extend(participation_routes())
    routes.extend(participation_sync_routes())
    routes.extend(bonus_routes())
    routes.extend(bonus_raffle_routes())
    routes.extend(todo_routes())
    from .strikes import routes as strike_routes
    routes.extend(strike_routes)
    routes.extend(push_routes())
    from . import war_reminders, staff_overview, clan_history, clan_usage, manage_clans, server_management, manage_roles, manage_tickets, manage_returns, manage_operations, manage_content, manage_return_bulk, manage_return_channels, text_commands, change_history, member_events, owner_prank
    app.cleanup_ctx.append(owner_prank.lifecycle)
    from .clan_artwork_cleanup import lifecycle as clan_artwork_cleanup_lifecycle
    app.cleanup_ctx.append(clan_artwork_cleanup_lifecycle)
    for module in (war_reminders, staff_overview, clan_history, clan_usage, manage_clans, server_management, manage_roles, manage_tickets, manage_returns, manage_operations, manage_return_bulk, manage_return_channels, text_commands, change_history, member_events, owner_prank):
        routes.extend(module.routes)
    manage_content.routes(app)
    routes.extend(issue_routes)
    app.add_routes(routes)
    if static_dir is not None:
        from pathlib import Path
        root = Path(static_dir).resolve()
        index = root / "index.html"
        if not index.is_file():
            raise ValueError("Frontend build index.html is missing")
        if (root / "assets").is_dir():
            app.router.add_static("/assets", root / "assets")
        if (root / "icons").is_dir():
            app.router.add_static("/icons", root / "icons")
        async def push_asset(request):
            name = request.match_info["asset"]
            response = web.FileResponse(root / name)
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Content-Type"] = "application/javascript" if name == "sw.js" else "application/manifest+json"
            if name == "sw.js":
                response.headers["Service-Worker-Allowed"] = "/"
            return response
        app.router.add_get("/{asset:sw\\.js|manifest\\.webmanifest}", push_asset)
        async def index_page(request):
            response = web.FileResponse(index)
            response.headers["Cache-Control"] = "no-store, max-age=0"
            return response
        app.router.add_get("/", index_page)
        app.router.add_get("/index.html", index_page)
        for path in ('signup', 'assignments', 'tasks', 'wars', 'events', 'search', 'clan-weights', 'weight', 'weights', 'weight-trial', 'my-signups', *(path.lstrip('/') for path in CWL_PAGE_PATHS.values()), *(path.lstrip('/') for path in MANAGEMENT_PAGE_PATHS.values())):
            app.router.add_get('/' + path, index_page)
            app.router.add_get('/' + path + '/', index_page)
        for page in ("reminders", "history", "strikes", "replacements"):
            app.router.add_get("/clans/" + page, index_page)
            app.router.add_get("/clans/" + page + "/", index_page)

        async def family_clan_page(request):
            import re
            if not re.fullmatch(r"#[A-Za-z0-9]{3,15}", request.match_info["clan_tag"]):
                raise web.HTTPNotFound()
            if request.match_info.get("section", "details") not in (
                "details", "roles", "channels", "artwork", "war-reminders"
            ):
                raise web.HTTPNotFound()
            return await index_page(request)

        for suffix in ("", "/"):
            app.router.add_get("/clans/{clan_tag}" + suffix, family_clan_page)
            app.router.add_get("/clans/{clan_tag}/{section}" + suffix, family_clan_page)
    return app
