"""HTTP authorization and bounded member directory adaptation for profile tools."""

import asyncio
from aiohttp import web
from utils.member_profiles import MemberProfiles
from utils.member_timezones import (
    COUNTRY_CHOICES,
    ZONE_CHOICES,
    highest_account,
    flag,
    nickname,
    SINGLE_ZONE,
    zones_for_country,
)
from utils.member_timezone_import import profile_zone, nickname_name
from .server_management import (
    API,
    GUILD_ID,
    discord,
    require_manage,
    mongo,
    queue_action,
)
from .manage_roles import member, hierarchy


async def directory(request):
    rows, after = [], None
    async with asyncio.timeout(45):
        while True:
            page = await discord(
                request,
                "GET",
                f"/guilds/{GUILD_ID}/members",
                params=dict(limit="1000", **({"after": after} if after else {})),
            )
            if not isinstance(page, list) or len(page) > 1000:
                raise web.HTTPServiceUnavailable(
                    text="Discord returned an incomplete member directory."
                )
            rows.extend(page)
            if len(rows) > 10000:
                raise web.HTTPServiceUnavailable(
                    text="Member directory exceeds the supported size."
                )
            if len(page) < 1000:
                break
            cursor = str(page[-1]["user"]["id"])
            if after is not None and int(cursor) <= int(after):
                raise web.HTTPServiceUnavailable(
                    text="Discord member pagination did not advance."
                )
            after = cursor
    me = await discord(request, "GET", "/users/@me")
    ids = [str(row["user"]["id"]) for row in rows]
    if str(me["id"]) not in ids or len(ids) != len(set(ids)):
        raise web.HTTPServiceUnavailable(
            text="Discord returned an incomplete member directory."
        )
    return rows


async def inventory(request):
    actor = await require_manage(request, "member_profiles")
    raw = await directory(request)
    roles, guild, bot, acting = await hierarchy(request, actor)
    from extensions.warrior import core
    import hikari

    role_list = list(roles.values())
    me = guild.get_member(bot.get_me().id)
    async with mongo(request) as db:
        profiles = await MemberProfiles(db).for_members(
            [row["user"]["id"] for row in raw]
        )
    rows = []
    for data in raw:
        uid = str(data["user"]["id"])
        from .manage_roles import member_option
        identity = member_option(data)
        profile = profiles.get(uid)
        parsed = profile_zone(data.get("nick"))
        status = (
            "Saved"
            if profile and profile["source"] in ("staff", "warrior")
            else (
                "From nickname"
                if profile or parsed and parsed["offsetMinutes"] is not None
                else "Unknown" if parsed else "Missing"
            )
        )
        skip = None
        try:
            if data["user"].get("bot"):
                raise ValueError("Bot account")
            core.manageable_target(
                dict(
                    member=member(data),
                    guild=guild,
                    actor=acting,
                    roles=role_list,
                    me=me,
                    actor_permissions=core.permissions(
                        acting, role_list, guild.owner_id
                    ),
                )
            )
            if (
                not core.permissions(me, role_list, guild.owner_id)
                & hikari.Permissions.MANAGE_NICKNAMES
            ):
                raise ValueError("Bot needs Manage Nicknames")
        except ValueError as error:
            skip = str(error)
        rows.append(
            dict(
                discord_id=uid,
                discord_profile={key: identity.get(key) for key in ("id", "display_name", "username", "avatar_url")},
                name=data["user"].get("global_name")
                or data["user"].get("username")
                or uid,
                nickname=data.get("nick"),
                bot=bool(data["user"].get("bot")),
                status=status,
                profile=(
                    {
                        k: profile.get(k)
                        for k in (
                            "zone_id",
                            "gmt_label",
                            "utc_offset_minutes",
                            "country",
                            "flag",
                            "name_source_tag",
                            "source",
                            "revision",
                        )
                    }
                    if profile
                    else None
                ),
                parsed=parsed,
                skip_reason=skip,
            )
        )
    return rows


async def overview(request):
    rows = await inventory(request)
    return web.json_response(
        dict(
            members=rows,
            countries=[
                dict(
                    code=code,
                    label=label,
                    flag=flag(code),
                    zone_id=SINGLE_ZONE.get(code),
                    zones=[dict(id=key, label=key.upper() + " · " + description) for key, _, description in zones_for_country(code)],
                )
                for code, label in COUNTRY_CHOICES
            ],
            zones=[
                dict(id=key, label=key.upper() + " · " + description)
                for key, _, description in ZONE_CHOICES
            ],
            permission="member_roles",
        )
    )


async def choices(request):
    await require_manage(request, "member_profiles")
    from utils.member_profiles import member_id

    try:
        uid = member_id(request.match_info["member_id"])
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    # Confirm destination belongs to this guild before any account lookup.
    await discord(request, "GET", f"/guilds/{GUILD_ID}/members/{uid}")
    provider = request.app["providers"]
    accounts = []
    complete = True
    try:
        async with asyncio.timeout(20):
            tags = list(await provider.linked_tags(uid))
            if len(tags) > 200:
                complete = False
            semaphore = asyncio.Semaphore(8)

            async def load(tag):
                nonlocal complete
                try:
                    async with semaphore:
                        row = await asyncio.wait_for(provider.player(tag), 8)
                    if (
                        not isinstance(row, dict)
                        or row.get("tag") != tag
                        or not isinstance(row.get("name"), str)
                        or not row["name"].strip()
                        or type(row.get("town_hall")) is not int
                        or row["town_hall"] < 1
                    ):
                        complete = False
                        return
                    accounts.append(
                        dict(tag=tag, name=row["name"], townHallLevel=row["town_hall"])
                    )
                except Exception:
                    complete = False

            await asyncio.gather(*(load(tag) for tag in tags[:200]))
    except Exception:
        complete = False
    return web.json_response(
        dict(
            accounts=accounts,
            suggested=highest_account(accounts, complete=complete),
            complete=complete,
        )
    )


async def save(request):
    await require_manage(request, "member_profiles", write=True)
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Choose a member profile.")
    values = {
        key: body.get(key)
        for key in ("discord_id", "fields", "rename", "name", "old_nickname")
    }
    return await queue_action(
        request, "member_profiles", "save", values, body.get("revision")
    )


async def import_current(request):
    await require_manage(request, "member_profiles", write=True)
    return await queue_action(request, "member_profiles", "import", {}, 0)


async def standardize_preview(request):
    actor = await require_manage(request, "member_profiles", write=True)
    rows = await inventory(request)
    from utils.member_timezone_review import preview_rows
    preview = preview_rows(rows)
    from utils.member_profile_runs import ProfileRuns

    async with mongo(request) as db:
        try:
            token = await ProfileRuns(db).preview(
                actor_id=actor["user_id"], guild_id=GUILD_ID, rows=preview
            )
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(dict(token=token, rows=preview))


async def standardize_confirm(request):
    actor = await require_manage(request, "member_profiles", write=True)
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Choose a reviewed selection.")
    from utils.member_profile_runs import ProfileRuns
    from utils.manage_web_worker import WORKER_ID
    import time

    async with mongo(request) as db:
        worker = await db.bot_config.find_one({"_id": WORKER_ID}) or {}
        if time.time() - worker.get("checked_at", 0) > 60:
            raise web.HTTPServiceUnavailable(
                text="The bot is not ready. Nothing was queued."
            )
        try:
            run = await ProfileRuns(db).confirm(
                actor_id=actor["user_id"],
                guild_id=GUILD_ID,
                nonce=body.get("token"),
                selected=body.get("selected"),
            )
        except (ValueError, TypeError) as error:
            raise web.HTTPConflict(text=str(error)) from error
    return web.json_response(dict(run_id=run["_id"], state=run["state"]))


async def standardize_runs(request):
    actor = await require_manage(request, "member_profiles")
    from utils.member_profile_runs import ProfileRuns

    async with mongo(request) as db:
        runs = await ProfileRuns(db).summaries(GUILD_ID, active_only=getattr(request, 'query', {}).get('active') == '1')
    return web.json_response(
        dict(
            runs=[
                dict(
                    run_id=row["_id"],
                    state=row["state"],
                    started_by=row.get("user_id"),
                    stopped_by=row.get("stopped_by"),
                )
                for row in runs
            ]
        )
    )


async def standardize_stop(request):
    actor = await require_manage(request, "member_profiles")
    from utils.member_profile_runs import ProfileRuns

    async with mongo(request) as db:
        try:
            run = await ProfileRuns(db).stop(
                request.match_info["run_id"],
                actor_id=actor["user_id"],
                guild_id=GUILD_ID,
            )
        except ValueError as error:
            raise web.HTTPNotFound(text=str(error)) from error
    return web.json_response(
        dict(
            run_id=run["_id"],
            started_by=run.get("user_id"),
            stopped_by=run.get("stopped_by"),
            state=(
                "stopping"
                if run["state"] == "queued" and run.get("stop_requested")
                else run["state"]
            ),
        )
    )


async def standardize_status(request):
    actor = await require_manage(request, "member_profiles")
    from utils.member_profile_runs import KIND

    async with mongo(request) as db:
        run = await db.bot_config.find_one(
            {
                "_id": request.match_info["run_id"],
                "kind": KIND,
                "guild_id": GUILD_ID,
            }
        )
        if not run:
            raise web.HTTPNotFound(text="This run is no longer available.")
        children = await db.bot_config.find(
            {"parent_id": run["_id"], "kind": "manage_web_request"}
        ).to_list(length=10000)
    statuses = {row["_id"]: row for row in children}
    rows = []
    for index, item in enumerate(run["items"]):
        child = statuses.get(run["_id"] + ":" + str(index)) or {}
        rows.append(
            dict(
                item,
                status=child.get(
                    "status", "stopped" if run.get("stop_requested") else "waiting"
                ),
                message=child.get(
                    "message",
                    (
                        "Stopped before this member started."
                        if run.get("stop_requested")
                        else "Waiting for the previous member."
                    ),
                ),
            )
        )
    return web.json_response(
        dict(
            run_id=run["_id"],
            started_by=run.get("user_id"),
            stopped_by=run.get("stopped_by"),
            state=(
                "stopping"
                if run["state"] == "queued" and run.get("stop_requested")
                else run["state"]
            ),
            rows=rows,
        )
    )


routes = [
    web.get(API + "/member-timezones/runs", standardize_runs),
    web.post(API + "/member-timezones/preview", standardize_preview),
    web.post(API + "/member-timezones/confirm", standardize_confirm),
    web.get(API + "/member-timezones/runs/{run_id}", standardize_status),
    web.post(API + "/member-timezones/runs/{run_id}/stop", standardize_stop),
    web.get(API + "/member-timezones", overview),
    web.get(API + "/member-timezones/{member_id}/choices", choices),
    web.post(API + "/member-timezones/save", save),
    web.post(API + "/member-timezones/import", import_current),
]
