"""Explicit, durable Discord announcements for published CWL rosters.

This module does not send on publication or app startup. A staff POST reserves one
version/pool/channel delivery before contacting Discord; uncertain attempts are
never blindly retried, even after Discord's short nonce window expires.
"""

import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp import web
from extensions.cwl_discord_transport import (
    DiscordTransport, AnnouncementUnavailable, AnnouncementRejected,
    AnnouncementUncertain, _snowflake, _channel,
)


GUILD_ID = "644963518025826315"
API = "/api/cwl"
POOLS = ("main", "lazy")
CHANNEL_TYPES = (0, 5)  # Guild text and guild announcement.
DISCORD_API = "https://discord.com/api/v10"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pool(request):
    pool = request.match_info["pool"]
    if pool not in POOLS:
        raise web.HTTPNotFound(text="Unknown CWL pool")
    return pool


def _public_url(request):
    raw = os.getenv("CWL_WEB_PUBLIC_URL", "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise AnnouncementUnavailable("Invalid CWL_WEB_PUBLIC_URL") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(char.isspace() for char in raw)):
        # Explicit loopback fixture may use HTTP for local browser verification.
        if not (request.app.get("dev_fixture") and parsed.scheme == "http"
                and parsed.hostname in ("localhost", "127.0.0.1")
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and not any(char.isspace() for char in raw)):
            raise AnnouncementUnavailable("CWL_WEB_PUBLIC_URL must be an HTTPS site URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/", "", ""))


def _nonce(sid, version, pool, channel_id):
    key = f"cwl:{sid}:{version}:{pool}:{channel_id}".encode()
    return hashlib.blake2s(key, digest_size=12).hexdigest()


def _content(season_label, publication, pool, counts, site_url):
    label = re.sub(r"[@\r\n]", "", season_label).strip()
    heading = "Main" if pool == "main" else "Lazy"
    return (
        f"{heading} CWL roster published for {label} (version {publication['version']}).\n"
        f"{counts['assigned_count']} assigned account(s); "
        f"{counts['unassigned_count']} awaiting placement.\n"
        f"View your own assignment in My assignments: {site_url}"
    )


def _counts(db, publication_id, pool):
    row = db.execute(
        "SELECT COUNT(*) AS account_count, "
        "SUM(CASE WHEN assigned_clan_tag IS NOT NULL THEN 1 ELSE 0 END) AS assigned_count "
        "FROM publication_accounts WHERE publication_id=? AND pool=?",
        (publication_id, pool),
    ).fetchone()
    assigned = row["assigned_count"] or 0
    return {"account_count": row["account_count"], "assigned_count": assigned,
            "unassigned_count": row["account_count"] - assigned}


def _delivery(row):
    if row is None:
        return None
    return {key: row[key] for key in (
        "status", "pool", "publication_version", "channel_id", "message_id",
        "requested_at", "sent_at", "failure", "attempts",
    )}


def _transport(request):
    return request.app.get("announcement_transport") or DiscordTransport()


async def list_channels(request):
    from .app import _require, _fail
    _require(request, "editor")
    try:
        channels = await _transport(request).list_channels()
    except (AnnouncementUnavailable, AnnouncementRejected):
        _fail(503, "Discord channels are unavailable")
    return web.json_response({"channels": channels})


async def list_roles(request):
    from .app import _require, _fail
    _require(request, "editor")
    try:
        roles = await _transport(request).list_roles()
    except (AnnouncementUnavailable, AnnouncementRejected):
        _fail(503, "Discord roles are unavailable")
    return web.json_response({"roles": roles})


async def announcement_status(request):
    from .app import _require, _sid, _store, _season
    _require(request, "editor")
    sid = _sid(request)
    try:
        site_url = _public_url(request)
        preview_error = None
    except AnnouncementUnavailable as exc:
        site_url = None
        preview_error = str(exc)
    with _store(request).tx() as db:
        season = _season(db, sid)
        latest = db.execute(
            "SELECT * FROM roster_publications WHERE season_id=? ORDER BY version DESC LIMIT 1",
            (sid,),
        ).fetchone()
        pools = {}
        for pool in POOLS:
            setting = db.execute(
                "SELECT * FROM announcement_channels WHERE season_id=? AND pool=?", (sid, pool)
            ).fetchone()
            delivery = None
            preview = None
            if latest:
                if setting:
                    delivery = db.execute(
                        "SELECT * FROM announcement_deliveries WHERE season_id=? "
                        "AND publication_version=? AND pool=? AND channel_id=?",
                        (sid, latest["version"], pool, setting["channel_id"]),
                    ).fetchone()
                counts = _counts(db, latest["id"], pool)
                if site_url:
                    preview = {"content": _content(season["label"], latest, pool, counts, site_url),
                               **counts}
            pools[pool] = {
                "channel_id": setting["channel_id"] if setting else None,
                "channel_name": setting["channel_name"] if setting else None,
                "preview": preview,
                "delivery": _delivery(delivery),
            }
    return web.json_response({
        "latest_publication": {"version": latest["version"],
                               "published_at": latest["published_at"]} if latest else None,
        "pools": pools,
        "preview_error": preview_error,
    })


async def set_channel(request):
    if os.getenv('CWL_WEB_MANAGE_BRIDGE') == '1':
        raise web.HTTPConflict(text='Use the shared Manage announcement controls; the separate sender is retired')
    from .app import _require, _json, _sid, _store, _season, _fail, _audit
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"channel_id"}:
        _fail(400, "Expected channel_id")
    pool = _pool(request)
    channel_id = body["channel_id"]
    channel = None
    if channel_id is not None:
        try:
            channel_id = _snowflake(channel_id)
        except ValueError:
            _fail(400, "Invalid Discord channel ID")
        try:
            channel = await _transport(request).get_channel(channel_id)
        except AnnouncementRejected:
            _fail(400, "Channel must be in this guild and support announcements")
        except AnnouncementUnavailable:
            _fail(503, "Discord channel lookup unavailable")
        if channel["id"] != channel_id:
            _fail(503, "Discord channel response did not match")
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        other = "lazy" if pool == "main" else "main"
        if channel_id and db.execute(
            "SELECT 1 FROM announcement_channels WHERE season_id=? AND pool=? AND channel_id=?",
            (sid, other, channel_id),
        ).fetchone():
            _fail(409, "Main and Lazy announcements need different channels")
        before_row = db.execute(
            "SELECT channel_id,channel_name FROM announcement_channels WHERE season_id=? AND pool=?",
            (sid, pool),
        ).fetchone()
        before = dict(before_row) if before_row else None
        if channel is None:
            db.execute("DELETE FROM announcement_channels WHERE season_id=? AND pool=?", (sid, pool))
        else:
            db.execute(
                "INSERT INTO announcement_channels(season_id,pool,channel_id,channel_name,configured_by,configured_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(season_id,pool) DO UPDATE SET "
                "channel_id=excluded.channel_id,channel_name=excluded.channel_name,"
                "configured_by=excluded.configured_by,configured_at=excluded.configured_at",
                (sid, pool, channel_id, channel["name"], session["user_id"], _now()),
            )
        after = {"channel_id": channel_id, "channel_name": channel["name"] if channel else None}
        if before != after:
            _audit(db, sid, None, session["user_id"], f"announcement_channel_{pool}", before, after)
    return web.json_response({"pool": pool, **after})


async def send_announcement(request):
    if os.getenv('CWL_WEB_MANAGE_BRIDGE') == '1':
        raise web.HTTPConflict(text='Use the shared Manage announcement controls; the separate sender is retired')
    from .app import _require, _json, _sid, _store, _season, _fail, _audit
    session = _require(request, "editor")
    body = await _json(request)
    if set(body) != {"version", "channel_id"} or type(body["version"]) is not int or body["version"] < 1:
        _fail(400, "Expected published version and channel_id")
    version = body["version"]
    try:
        channel_id = _snowflake(body["channel_id"])
    except ValueError:
        _fail(400, "Invalid Discord channel ID")
    pool = _pool(request)
    sid = _sid(request)
    try:
        site_url = _public_url(request)
    except AnnouncementUnavailable:
        _fail(503, "CWL_WEB_PUBLIC_URL is not configured")
    with _store(request).tx() as db:
        season = _season(db, sid)
        latest = db.execute(
            "SELECT * FROM roster_publications WHERE season_id=? ORDER BY version DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if latest is None or latest["version"] != version:
            _fail(409, "Published roster changed; refresh before sending")
        setting = db.execute(
            "SELECT * FROM announcement_channels WHERE season_id=? AND pool=?", (sid, pool)
        ).fetchone()
        if setting is None or setting["channel_id"] != channel_id:
            _fail(409, "Announcement channel changed; refresh before sending")
        other = "lazy" if pool == "main" else "main"
        if db.execute("SELECT 1 FROM announcement_channels WHERE season_id=? AND pool=? AND channel_id=?",
                      (sid, other, channel_id)).fetchone():
            _fail(409, "Main and Lazy announcements need different channels")
        counts = _counts(db, latest["id"], pool)
        if counts["account_count"] == 0:
            _fail(409, "No published accounts in this pool")
        existing = db.execute(
            "SELECT * FROM announcement_deliveries WHERE season_id=? AND publication_version=? "
            "AND pool=? AND channel_id=?", (sid, version, pool, channel_id),
        ).fetchone()
        if existing:
            if existing["status"] == "sent":
                return web.json_response({"delivery": _delivery(existing)})
            if existing["status"] != "failed":
                _fail(409, "Prior delivery is unresolved; do not resend blindly")
        content = _content(season["label"], latest, pool, counts, site_url)
    try:
        channel = await _transport(request).get_channel(channel_id)
    except AnnouncementRejected:
        _fail(409, "Configured channel is no longer a usable guild text channel")
    except AnnouncementUnavailable:
        _fail(503, "Discord channel lookup unavailable")
    if channel["id"] != channel_id:
        _fail(503, "Discord channel response did not match")
    nonce = _nonce(sid, version, pool, channel_id)
    with _store(request).tx() as db:
        _season(db, sid)
        latest = db.execute("SELECT version FROM roster_publications WHERE season_id=? "
                            "ORDER BY version DESC LIMIT 1", (sid,)).fetchone()
        setting = db.execute("SELECT channel_id FROM announcement_channels WHERE season_id=? AND pool=?",
                             (sid, pool)).fetchone()
        if latest is None or latest["version"] != version or setting is None or setting["channel_id"] != channel_id:
            _fail(409, "Publication or channel changed; refresh before sending")
        existing = db.execute(
            "SELECT * FROM announcement_deliveries WHERE season_id=? AND publication_version=? "
            "AND pool=? AND channel_id=?", (sid, version, pool, channel_id),
        ).fetchone()
        if existing:
            if existing["status"] == "sent":
                return web.json_response({"delivery": _delivery(existing)})
            if existing["status"] != "failed":
                _fail(409, "Prior delivery is unresolved; do not resend blindly")
            changed = db.execute(
                "UPDATE announcement_deliveries SET status='sending',failure=NULL,"
                "message_id=NULL,sent_at=NULL,content=?,requested_by=?,requested_at=?,attempts=attempts+1 "
                "WHERE id=? AND status='failed'",
                (content, session["user_id"], _now(), existing["id"]),
            )
            if changed.rowcount != 1:
                _fail(409, "Delivery changed; refresh before retrying")
            _audit(db, sid, None, session["user_id"], "announcement_retry", _delivery(existing),
                   {"status": "sending", "attempts": existing["attempts"] + 1})
        else:
            db.execute(
                "INSERT INTO announcement_deliveries(season_id,publication_version,pool,channel_id,nonce,content,"
                "status,requested_by,requested_at) VALUES (?,?,?,?,?,?,'sending',?,?)",
                (sid, version, pool, channel_id, nonce, content, session["user_id"], _now()),
            )
    transport = _transport(request)
    try:
        message_id = await transport.send(channel_id, content, nonce)
    except AnnouncementRejected:
        status, failure = "failed", "Discord rejected the message or bot permissions"
        message_id = None
    except (AnnouncementUncertain, AnnouncementUnavailable, aiohttp.ClientError, asyncio.TimeoutError):
        status, failure = "uncertain", "Discord result is uncertain; do not resend"
        message_id = None
    else:
        status, failure = "sent", None
    with _store(request).tx() as db:
        db.execute(
            "UPDATE announcement_deliveries SET status=?,message_id=?,sent_at=?,failure=? "
            "WHERE season_id=? AND publication_version=? AND pool=? AND channel_id=? AND status='sending'",
            (status, message_id, _now() if status == "sent" else None, failure,
             sid, version, pool, channel_id),
        )
        row = db.execute(
            "SELECT * FROM announcement_deliveries WHERE season_id=? AND publication_version=? "
            "AND pool=? AND channel_id=?", (sid, version, pool, channel_id),
        ).fetchone()
        _audit(db, sid, None, session["user_id"], f"announcement_{status}", None, _delivery(row))
    if status != "sent":
        _fail(503 if status == "uncertain" else 409, failure)
    return web.json_response({"delivery": _delivery(row)}, status=201)


def routes():
    return [
        web.get(API + "/announcement-channels", list_channels),
        web.get(API + "/announcement-roles", list_roles),
        web.get(API + "/seasons/{season_id}/announcements", announcement_status),
        web.patch(API + "/seasons/{season_id}/announcements/{pool}/channel", set_channel),
        web.post(API + "/seasons/{season_id}/announcements/{pool}/send", send_announcement),
    ]
