"""Members role review, permission checks and durable-run HTTP adaptation."""

import time
from aiohttp import web
import hikari
from extensions.commands.recruit import perms
from utils.member_profiles import member_id
from utils.member_profile_runs import ProfileRuns
from utils.role_permissions import role_is_manageable
from utils.manage_web_worker import WORKER_ID
from .server_management import API, GUILD_ID, require_manage, mongo
from .manage_roles import hierarchy, dashboard_grant_roles
from .member_timezones import directory


def body_selection(body):
    required = {"member_ids", "role_id", "operation"}
    if not isinstance(body, dict) or not required <= set(body) <= required | {"guard_role_ids"}:
        raise ValueError("Choose one role and a reviewed member selection.")
    ids = body["member_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 10000:
        raise ValueError("Choose between 1 and 10000 people.")
    normalized = [member_id(uid) for uid in ids]
    if normalized != ids or len(set(normalized)) != len(normalized):
        raise ValueError("Choose each person once using their full Discord ID.")
    if body["operation"] not in ("add", "remove"):
        raise ValueError("Choose Add role or Remove role.")
    role = member_id(body["role_id"])
    if "guard_role_ids" in body:
        guard = body["guard_role_ids"]
        if len(ids) != 1 or not isinstance(guard, list) or len(guard) > 250:
            raise ValueError("Review the single person's current roles before Undo.")
        if [member_id(value) for value in guard] != guard or len(set(guard)) != len(guard):
            raise ValueError("Review the single person's current roles before Undo.")
    return normalized, role, body["operation"]


async def preview(request):
    actor = await require_manage(request, "roles", write=True)
    try:
        body = await request.json()
        ids, role_id, operation = body_selection(body)
    except (ValueError, TypeError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    role_map, guild, bot, person = await hierarchy(request, actor)
    role = role_map.get(int(role_id))
    if not role_is_manageable(guild, bot, role) or not perms.actor_can_manage_role(
        person, guild, role
    ):
        raise web.HTTPForbidden(text="This role cannot be changed by you or the bot.")
    forbidden = await dashboard_grant_roles(request, actor)
    if role_id in forbidden:
        raise web.HTTPForbidden(text="Only dashboard owners can change access roles.")
    # Include owner-visible access roles in the explicit confirmation warning.
    from utils.dashboard_access import AccessRepository

    async with mongo(request) as db:
        policy = await AccessRepository(db.bot_config).read()
    access_roles = {
        row["id"] for row in (policy or {}).get("grants", []) if row["kind"] == "role"
    }
    protected = role_id in access_roles or bool(
        role.permissions & hikari.Permissions.ADMINISTRATOR
    )
    raw = await directory(request)
    known = {str(row["user"]["id"]): row for row in raw}
    if any(uid not in known for uid in ids):
        raise web.HTTPConflict(
            text="The member list changed. Refresh the people before reviewing again."
        )
    from .manage_roles import member

    rows = []
    for uid in ids:
        data = known[uid]
        if "guard_role_ids" in body and sorted(map(str,data.get("roles", []))) != sorted(body["guard_role_ids"]):
            raise web.HTTPConflict(text="This person’s roles changed. Refresh before Undo; no role was changed.")
        if data["user"].get("bot") or not perms.actor_can_manage_member(
            person, member(data), guild
        ):
            raise web.HTTPForbidden(
                text="This selection includes a bot, server owner or person above your role. No changes were queued."
            )
        rows.append(
            dict(
                discord_id=uid,
                role_id=role_id,
                operation=operation,
                expected_role_ids=sorted(map(str, data.get("roles", []))),
                bot=False,
                protected=protected,
            )
        )
    async with mongo(request) as db:
        try:
            token = await ProfileRuns(db).preview(
                actor_id=actor["user_id"],
                guild_id=GUILD_ID,
                rows=rows,
                run_type="roles",
            )
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(
        dict(
            token=token,
            selected=ids,
            count=len(ids),
            role=dict(id=role_id, name=role.name, protected=protected),
            operation=operation,
        )
    )


async def confirm(request):
    actor = await require_manage(request, "roles", write=True)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="Choose a reviewed role change.") from None
    if (
        not isinstance(body, dict)
        or set(body) != {"token", "selected", "protected_confirmed"}
        or type(body["protected_confirmed"]) is not bool
    ):
        raise web.HTTPBadRequest(text="Choose a reviewed role change.")
    async with mongo(request) as db:
        heartbeat = await db.bot_config.find_one({"_id": WORKER_ID}) or {}
        if time.time() - heartbeat.get("checked_at", 0) > 60:
            raise web.HTTPServiceUnavailable(
                text="The bot is not ready. Nothing was queued."
            )
        try:
            run = await ProfileRuns(db).confirm(
                actor_id=actor["user_id"],
                guild_id=GUILD_ID,
                nonce=body["token"],
                selected=body["selected"],
                run_type="roles",
                protected_confirmed=body["protected_confirmed"],
            )
        except (ValueError, TypeError) as error:
            raise web.HTTPConflict(text=str(error)) from error
    return web.json_response(dict(run_id=run["_id"], state=run["state"]))


async def runs(request):
    await require_manage(request, "roles")
    async with mongo(request) as db:
        rows = await ProfileRuns(db).summaries(
            GUILD_ID, active_only=request.query.get("active") == "1", run_type="roles"
        )
    return web.json_response(
        dict(
            runs=[
                dict(
                    run_id=row["_id"],
                    state=row["state"],
                    started_by=row["user_id"],
                    stopped_by=row.get("stopped_by"),
                )
                for row in rows
            ]
        )
    )


async def status(request):
    await require_manage(request, "roles")
    async with mongo(request) as db:
        try:
            run, children = await ProfileRuns(db).status(
                request.match_info["run_id"], guild_id=GUILD_ID, run_type="roles"
            )
        except ValueError as error:
            raise web.HTTPNotFound(text=str(error)) from error
    known = {row["_id"]: row for row in children}
    rows = []
    for index, item in enumerate(run["items"]):
        child = known.get(run["_id"] + ":" + str(index), {})
        rows.append(
            dict(
                item,
                changed=(child.get("result") or {}).get("changed"),
                status=child.get(
                    "status", "stopped" if run.get("stop_requested") else "waiting"
                ),
                message=child.get("message", ""),
            )
        )
    return web.json_response(
        dict(
            run_id=run["_id"],
            state=(
                "stopping"
                if run["state"] == "queued" and run.get("stop_requested")
                else run["state"]
            ),
            rows=rows,
            started_by=run["user_id"],
            stopped_by=run.get("stopped_by"),
        )
    )


async def stop(request):
    actor = await require_manage(request, "roles", write=True)
    async with mongo(request) as db:
        try:
            run = await ProfileRuns(db).stop(
                request.match_info["run_id"],
                actor_id=actor["user_id"],
                guild_id=GUILD_ID,
                run_type="roles",
            )
        except ValueError as error:
            raise web.HTTPNotFound(text=str(error)) from error
    return web.json_response(
        dict(
            run_id=run["_id"],
            state=(
                "stopping"
                if run["state"] == "queued" and run.get("stop_requested")
                else run["state"]
            ),
        )
    )


routes = [
    web.post(API + "/members/role-preview", preview),
    web.post(API + "/members/role-confirm", confirm),
    web.get(API + "/members/role-runs", runs),
    web.get(API + "/members/role-runs/{run_id}", status),
    web.post(API + "/members/role-runs/{run_id}/stop", stop),
]
