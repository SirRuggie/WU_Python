"""HTTP authorization/adaptation for the shared CWL role outbox."""

from aiohttp import web
from utils import cwl_pool_roles as service
from utils.role_permissions import role_is_safe_for_pool
from extensions.commands.recruit.perms import actor_can_manage_role
from .server_management import identity
from .manage_roles import hierarchy, dashboard_grant_roles


def require_settings(request):
    from .app import _require, _owner, request_scopes, _fail

    actor = _require(request)
    if not _owner(actor) and "cwl_settings" not in request_scopes(
        request, actor["user_id"]
    ):
        _fail(403, "Seasons access required.")
    return actor


async def role_context(request):
    actor = await identity(request)
    roles, guild, bot, person = await hierarchy(request, actor)
    forbidden = await dashboard_grant_roles(request, actor, include_owner=True)
    safe = {
        str(role.id)
        for role in roles.values()
        if str(role.id) not in forbidden and role_is_safe_for_pool(guild, bot, role)
    }
    options = [
        {"id": str(role.id), "name": role.name}
        for role in roles.values()
        if str(role.id) in safe and actor_can_manage_role(person, guild, role)
    ]
    return options, {str(role.id): role.name for role in roles.values()}, safe


async def choices(request):
    options, _, _ = await role_context(request)
    return options


async def get(request):
    from .app import _store

    require_settings(request)
    with _store(request).tx() as db:
        result = service.snapshot(db)
    store = _store(request)
    warning = store.role_recovery_error or store.role_backup_error
    import time

    if (
        not warning
        and time.time() - (store.role_last_contact or store.role_started_at) > 120
    ):
        warning = "Role worker is unavailable. Signups are unchanged."
    if warning and any(row["role_id"] for row in result["pools"]):
        result["worker_warning"] = warning
    configured = any(row["role_id"] for row in result["pools"])
    if request.query.get("choices") != "1" and (
        request.query.get("status") == "1" or not configured
    ):
        return web.json_response(result)
    try:
        options, names, safe = await role_context(request)
    except (web.HTTPServiceUnavailable, web.HTTPForbidden, web.HTTPNotFound):
        return web.json_response(
            result
            | {
                "roles": [],
                "roles_error": "Role choices unavailable. Refresh or turn off a saved role.",
            }
        )
    saved = {
        row["pool"]: {
            "name": names.get(row["role_id"], "Saved role"),
            "allowed": row["role_id"] in safe,
        }
        for row in result["pools"]
        if row["role_id"]
    }
    return web.json_response(result | {"roles": options, "saved_roles": saved})


async def save(request):
    from .app import _store, _json, _fail

    actor = require_settings(request)
    body = await _json(request)
    if set(body) != {"pool", "role_id", "revision", "member_basis"}:
        _fail(400, "Review a pool role before saving.")
    if (
        not isinstance(body["pool"], str)
        or body["pool"] not in service.POOLS
        or (
            body["role_id"] is not None
            and (
                not isinstance(body["role_id"], str)
                or not service.ID.fullmatch(body["role_id"])
            )
        )
        or type(body["revision"]) is not int
        or body["revision"] < 0
        or not isinstance(body["member_basis"], str)
    ):
        _fail(400, "Invalid pool role setting.")
    # Clearing cannot grant a role and remains available during a read outage.
    context = None if body["role_id"] is None else await role_context(request)
    options = context[0] if context else None
    if body["role_id"] is not None and body["role_id"] not in {
        r["id"] for r in (options or [])
    }:
        _fail(400, "Choose an available role below the bot.")
    try:
        with _store(request).tx() as db:
            result = service.save(
                db,
                body["pool"],
                body["role_id"],
                body["revision"],
                body["member_basis"],
                actor["user_id"],
            )
            paused = service.recovery_paused(db)
    except service.Conflict as exc:
        _fail(409, str(exc))
    except (ValueError, TypeError) as exc:
        _fail(400, str(exc))
    if not paused:
        _store(request).role_recovery_error = None
    metadata = {}
    if context:
        _, names, safe = context
        metadata = {
            "roles": options,
            "saved_roles": {
                row["pool"]: {
                    "name": names.get(row["role_id"], "Saved role"),
                    "allowed": row["role_id"] in safe,
                }
                for row in result["pools"]
                if row["role_id"]
            },
        }
    return web.json_response(result | metadata)


def schedule_progress_backup(request):
    from .app import _store
    import asyncio
    import time

    store = _store(request)
    previous = request.app.get("pool_role_backup_task")
    if (
        store.durability is not None
        and store.role_dirty
        and time.time() >= store.role_next_backup
        and (previous is None or previous.done())
    ):
        # Also bound serialization/SQLite failures before a durable attempt stamp.
        store.role_next_backup = time.time() + 60

        async def flush():
            try:
                await asyncio.to_thread(store.flush_role_progress)
            except Exception:
                import logging

                store.role_backup_error = (
                    "Role progress backup is unavailable. Signups are unchanged."
                )

                logging.getLogger(__name__).warning(
                    "Role progress backup task unavailable"
                )

        request.app["pool_role_backup_task"] = asyncio.create_task(
            flush(), name="pool-role-progress-backup"
        )


async def bridge(request):
    from .app import _store, _fail
    from .discord_member import _authenticate
    from utils.cwl_member_service import MemberError

    try:
        _authenticate(request)
    except MemberError as exc:
        _fail(exc.status, str(exc))
    try:
        body = await request.json()
    except (ValueError, TypeError):
        _fail(400, "Invalid JSON.")
    if not isinstance(body, dict) or body.get("guild_id") != str(service.GUILD_ID):
        _fail(403, "WU server only.")
    action = body.get("action")
    if not isinstance(action, str):
        _fail(400, "Invalid role action.")
    if action == "health":
        if set(body) != {"guild_id", "action"}:
            _fail(400, "Invalid health check.")
        import time

        _store(request).role_last_contact = time.time()
        return web.json_response({"alive": True})
    if action == "claim":
        if set(body) != {"guild_id", "action"}:
            _fail(400, "Invalid claim.")
        store = _store(request)
        import time

        store.role_last_contact = time.time()
        with store.role_tx() as db:
            if service.clear_pause_if_off(db):
                store.role_recovery_error = None
            job = None if store.role_recovery_error else service.claim(db)
        schedule_progress_backup(request)
        return web.json_response({"job": job})
    if action not in {"validate", "finish"}:
        _fail(400, "Invalid role action.")
    required = {"guild_id", "action", "id", "lease_token", "generation"}
    allowed = required | (
        {"message", "failed", "retry", "page", "cursor"}
        if action == "finish"
        else set()
    )
    if (
        not required <= set(body) <= allowed
        or not isinstance(body["id"], str)
        or not isinstance(body["lease_token"], str)
        or type(body["generation"]) is not int
    ):
        _fail(400, "Invalid role receipt.")
    extra = {
        k: body[k]
        for k in ("message", "failed", "retry", "page", "cursor")
        if k in body
    }
    if (
        any(type(extra[k]) is not bool for k in ("failed", "retry") if k in extra)
        or not isinstance(extra.get("message", ""), str)
        or len(extra.get("message", "")) > 250
    ):
        _fail(400, "Invalid role result.")
    try:
        with _store(request).role_tx() as db:
            result = (
                service.validate(
                    db, body["id"], body["lease_token"], body["generation"]
                )
                if action == "validate"
                else service.finish(
                    db, body["id"], body["lease_token"], body["generation"], **extra
                )
            )
    except (ValueError, TypeError) as exc:
        _fail(400, str(exc))
    if action == "validate" and result.get("valid"):
        from .server_management import mongo
        from utils.dashboard_access import dashboard_role_grants

        async with mongo(request) as shared:
            forbidden = await dashboard_role_grants(shared)
        with _store(request).role_tx() as db:
            current = service.owned(
                db, body["id"], body["lease_token"], body["generation"]
            )
        result["role_allowed"] = bool(current and current["role_id"] not in forbidden)
    schedule_progress_backup(request)
    return web.json_response(result)


routes = [
    web.get("/api/cwl/pool-roles", get),
    web.post("/api/cwl/pool-roles", save),
    web.post("/api/cwl/discord/pool-roles", bridge),
]
