"""Announcement permissions and HTTP adaptation for reviewed in-place edits."""

import re
from datetime import datetime, timezone

from aiohttp import web

from utils import cwl_post_updates
from utils.cwl_post_update_store import PostUpdateConflict, PostUpdateStore
from . import manage_bridge
from .roster_image_posts import staff


def _scope(request, *, writing=False):
    from .app import _sid, _store, _season

    actor = staff(request, send=True)
    sid = _sid(request)
    pool = manage_bridge._pool(request)
    cycle = manage_bridge._required_binding(request, sid)
    if writing:
        with _store(request).tx() as db:
            if _season(db, sid)["status"] != "draft":
                raise web.HTTPConflict(text="Season is archived")
    return actor, sid, cycle, pool


def _nonce(request):
    nonce = request.match_info["nonce"]
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise web.HTTPNotFound(text="Post review unavailable")
    return nonce


def _key(user_id, nonce):
    return f"cwl:post-update:{manage_bridge.GUILD_ID}:{int(user_id)}:{nonce}"


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def _worker_ready(mongo):
    return await PostUpdateStore(mongo).worker_ready(manage_bridge.GUILD_ID)


def _public(row, ready):
    status = row["status"]
    now = datetime.now(timezone.utc)
    expiry = _utc(row.get("expires_at"))
    updated = _utc(row.get("updated_at"))
    if status == "ready" and (expiry is None or expiry <= now):
        status = "expired"
    if status == "updating" and updated and (now - updated).total_seconds() > 180:
        # Reporting uncertainty never resets a claim or retries an edit.
        status = "uncertain"
    result = {
        key: row[key]
        for key in (
            "candidate",
            "generation",
            "future_months",
            "live_preview",
            "has_changes",
            "draft_preview",
            "error",
            "error_code",
            "message_url",
            "campaign_saved",
            "recurring_saved",
            "save_warning",
        )
        if key in row
    }
    target = row.get("target") or {}
    result.update(
        status=status,
        worker_ready=ready,
        channel_name=target.get("channel_name"),
        message_url=row.get("message_url") or target.get("message_url"),
    )
    if status == "uncertain":
        result["error"] = "Not sure it updated. Check the post."
    return result


async def _owned(mongo, actor, sid, cycle, pool, nonce):
    try:
        row = await PostUpdateStore(mongo).owned(
            _key(actor["user_id"], nonce),
            guild_id=manage_bridge.GUILD_ID,
            user_id=int(actor["user_id"]),
            season_id=sid,
            pool=pool,
        )
    except PostUpdateConflict as exc:
        raise web.HTTPNotFound(text="Post review unavailable") from exc
    if row["cycle"] != cycle:
        raise web.HTTPConflict(text="Month changed. Open a new preview.")
    return row


async def preview(request):
    from .app import _json

    actor, sid, cycle, pool = _scope(request, writing=True)
    body = await _json(request)
    if (
        set(body) != {"nonce", "generation", "candidate"}
        or not isinstance(body.get("nonce"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", body["nonce"])
        or not isinstance(body.get("generation"), str)
        or not 1 <= len(body["generation"]) <= 256
    ):
        raise web.HTTPBadRequest(text="Review the roster text and link buttons")
    async with manage_bridge._mongo(request) as mongo:
        if not await _worker_ready(mongo):
            raise web.HTTPServiceUnavailable(
                text="The bot post editor is not ready. Try again after it reconnects."
            )
        try:
            row = await cwl_post_updates.create_review(
                mongo,
                guild_id=manage_bridge.GUILD_ID,
                user_id=int(actor["user_id"]),
                season_id=sid,
                cycle=cycle,
                pool=pool,
                **body,
            )
        except PostUpdateConflict as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response(_public(row, True), status=202)


async def status(request):
    actor, sid, cycle, pool = _scope(request)
    async with manage_bridge._mongo(request) as mongo:
        row = await _owned(mongo, actor, sid, cycle, pool, _nonce(request))
        return web.json_response(_public(row, await _worker_ready(mongo)))


async def update(request):
    from .app import _json

    actor, sid, cycle, pool = _scope(request, writing=True)
    body = await _json(request)
    if set(body) != {"future_months"} or type(body["future_months"]) is not bool:
        raise web.HTTPBadRequest(
            text="Choose whether to use this copy for future months"
        )
    async with manage_bridge._mongo(request) as mongo:
        row = await _owned(mongo, actor, sid, cycle, pool, _nonce(request))
        ready = await _worker_ready(mongo)
        if (
            row["status"] not in ("pending_update", "updating", "done", "uncertain")
            and not ready
        ):
            raise web.HTTPServiceUnavailable(
                text="The bot post editor is not ready. Nothing was queued."
            )
        try:
            row = await PostUpdateStore(mongo).request_update(
                row, future_months=body["future_months"]
            )
        except PostUpdateConflict as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        return web.json_response(
            _public(row, ready),
            status=202 if row["status"] in ("pending_update", "updating") else 200,
        )


async def validate(request):
    """Fresh loopback-only scope check immediately before native side effects."""
    from .app import _store, _season, _fail
    from .discord_member import _authenticate
    from utils.cwl_member_service import MemberError

    try:
        _authenticate(request)
    except MemberError as exc:
        _fail(exc.status, str(exc))
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="Invalid validation request") from None
    required = {
        "guild_id",
        "user_id",
        "season_id",
        "cycle",
        "pool",
        "worker_epoch",
        "workflow_id",
    }
    if (
        not isinstance(body, dict)
        or set(body) != required
        or body["guild_id"] != manage_bridge.GUILD_ID
    ):
        raise web.HTTPBadRequest(text="Invalid validation scope")
    if (
        body["pool"] not in ("main", "lazy")
        or type(body["user_id"]) is not int
        or body["user_id"] < 1
        or not re.fullmatch(r"[0-9]{1,18}", str(body["season_id"]))
    ):
        raise web.HTTPBadRequest(text="Invalid validation scope")
    if (
        not isinstance(body["cycle"], str)
        or not re.fullmatch(r"20[0-9]{2}-(?:0[1-9]|1[0-2])", body["cycle"])
        or not isinstance(body["worker_epoch"], str)
        or not 1 <= len(body["worker_epoch"]) <= 128
        or not isinstance(body["workflow_id"], str)
        or not re.fullmatch(
            rf'cwl:post-update:{manage_bridge.GUILD_ID}:{body["user_id"]}:[a-f0-9]{{32}}',
            body["workflow_id"],
        )
    ):
        raise web.HTTPBadRequest(text="Invalid validation identity")
    sid = int(body["season_id"])
    with _store(request).tx() as db:
        season = _season(db, sid)
        binding = db.execute(
            "SELECT cycle FROM manage_campaign_bindings WHERE season_id=?", (sid,)
        ).fetchone()
        valid = (
            season["status"] == "draft"
            and binding is not None
            and binding["cycle"] == body["cycle"]
        )
    async with manage_bridge._mongo(request) as mongo:
        claimed = await PostUpdateStore(mongo).active_claim(
            workflow_id=body["workflow_id"],
            guild_id=manage_bridge.GUILD_ID,
            user_id=body["user_id"],
            season_id=sid,
            cycle=body["cycle"],
            pool=body["pool"],
            worker_epoch=body["worker_epoch"],
        )
    return web.json_response({"valid": bool(valid and claimed)})


def routes():
    base = manage_bridge.API + "/seasons/{season_id}/manage-bridge/{pool}/post-updates"
    return [
        web.post(base, preview),
        web.get(base + "/{nonce}", status),
        web.post(base + "/{nonce}/update", update),
        web.post(manage_bridge.API + "/discord/post-updates/validate", validate),
    ]
