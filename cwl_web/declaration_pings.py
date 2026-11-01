"""HTTP adaptation for explicit, reviewed declaration pings."""

import time
from aiohttp import web
from utils.cwl_roster_image_store import RosterImageStore
from utils.declaration_pings import missing_groups, messages, review_fingerprint
from utils.declaration_ping_store import DeclarationPingStore, PingConflict
from . import declaration_destinations as destinations
from .declaration_delivery import launch, public_receipt, visible_active
from .manage_content import serialize_components
from .roster_image_posts import staff
from .server_management import mongo, GUILD_ID

BASE = "/api/cwl/seasons/{season_id}/declaration-pings/{pool}"


def context(request, *, send=False):
    from .app import _sid, _season

    actor = staff(request, send=send)
    pool = request.match_info["pool"]
    if pool not in ("main", "lazy"):
        raise web.HTTPBadRequest(text="Choose Main or Lazy")
    sid = _sid(request)
    with request.app["store"].tx() as db:
        _season(db, sid)
    return actor["user_id"], sid, pool


def can_send(request):
    from .app import _owner
    from .access_control import request_scopes

    actor = staff(request)
    return _owner(actor) or "cwl_send" in request_scopes(request, actor["user_id"])


def test_channel(request):
    saved = RosterImageStore(request.app["store"]).test_channel()
    return {
        "id": saved["channel_id"],
        "name": saved["channel_name"],
        "revision": saved["revision"],
    }


async def fresh_groups(request, pool):
    from .app import arrival_snapshot

    snapshot = await arrival_snapshot(request, source="published", force=True)
    if not snapshot["publication_available"] or snapshot["source"] != "published":
        raise PingConflict("Publish the roster before reviewing pings")
    if snapshot["publication_outdated"]:
        raise PingConflict("Publish the changed lineup before reviewing pings")
    groups = missing_groups(snapshot["accounts"], pool)
    unknown = sum(
        1
        for row in snapshot["accounts"]
        if (row.get("hosting_pool") or row.get("pool")) == pool
        and row.get("arrival_status") == "unknown"
    )
    return groups, snapshot["version"], unknown


def fingerprint(groups, version, channel, revision):
    return review_fingerprint(
        groups,
        version=version,
        channel_id=channel["id"],
        revision=[revision, channel.get("revision")],
    )


async def state(request):
    _, _, pool = context(request)
    async with mongo(request) as client:
        lane = await DeclarationPingStore(client, GUILD_ID).read(pool)
    permitted = can_send(request)
    choices, warning = [], None
    if permitted and request.query.get("channels") != "0":
        try:
            choices = await destinations.channels(request)
        except web.HTTPException as exc:
            warning = exc.text
    return web.json_response(
        dict(
            revision=lane["revision"],
            channel=lane["channel"],
            can_send=permitted,
            channels=choices,
            warning=warning,
            active=visible_active(request, lane["active"]),
            test_running=bool(
                lane.get("active_test")
                and lane["active_test"]["token"]
                in request.app["declaration_running_tokens"]
            ),
            history=[public_receipt(row) for row in reversed(lane["history"])],
            cooldown_until=(
                lane["last_attempt_at"] + 300 if lane["last_attempt_at"] else 0
            ),
            test_channel=test_channel(request),
        )
    )


async def configure(request):
    from .app import _json

    actor, _, pool = context(request, send=True)
    body = await _json(request)
    if set(body) != {"channel_id", "revision"}:
        raise web.HTTPBadRequest(text="Choose a channel and its revision")
    channel = await destinations.destination(request, body["channel_id"])
    async with mongo(request) as client:
        lane = await DeclarationPingStore(client, GUILD_ID).configure(
            pool, channel["id"], channel["name"], actor, body["revision"]
        )
    return web.json_response({"revision": lane["revision"], "channel": lane["channel"]})


async def preview(request):
    from .app import _json

    actor, sid, pool = context(request, send=True)
    body = await _json(request)
    if (
        set(body) != {"revision", "mode"}
        or body["mode"] not in ("live", "test")
        or type(body["revision"]) is not int
    ):
        raise web.HTTPBadRequest(text="Choose a ping or no-ping test review")
    groups, version, unknown = await fresh_groups(request, pool)
    if not groups:
        raise PingConflict(
            "No confirmed missing players in this pool. Unavailable locations are excluded."
        )
    async with mongo(request) as client:
        storage = DeclarationPingStore(client, GUILD_ID)
        lane = await storage.read(pool)
        channel = test_channel(request) if body["mode"] == "test" else lane["channel"]
        if not channel or not channel["id"]:
            raise PingConflict(
                "Choose a posting channel first"
                if body["mode"] == "live"
                else "Set the shared Test channel in Announcements first"
            )
        await destinations.destination(request, channel["id"])
        row = await storage.preview(
            pool,
            actor,
            sid,
            groups,
            version,
            fingerprint(groups, version, channel, lane["revision"]),
            body["revision"],
            test_channel=channel if body["mode"] == "test" else None,
        )
    plan = messages(groups, test=body["mode"] == "test")
    return web.json_response(
        dict(
            token=row["token"],
            mode=row["mode"],
            channel=row["channel"],
            groups=groups,
            count=sum(len(g["accounts"]) for g in groups),
            unknown=unknown,
            unlinked=sum(len(g["unlinked"]) for g in groups),
            chunks=len(plan),
            previews=[
                serialize_components(payload["components"], "declaration-ping")
                for payload in plan
            ],
        )
    )


async def send(request):
    from .app import _json, require_current_publication

    actor, sid, pool = context(request, send=True)
    body = await _json(request)
    if (
        set(body) != {"token", "confirm", "send_again"}
        or body["confirm"] is not True
        or type(body["send_again"]) is not bool
    ):
        raise web.HTTPBadRequest(text="Review and explicitly confirm before sending")
    token = body["token"]
    async with mongo(request) as client:
        storage = DeclarationPingStore(client, GUILD_ID)
        await storage.recover_other_process(pool, request.app["declaration_runtime"])
        prior = await storage.receipt(pool, token)
        if prior:
            if prior["actor_id"] != actor or prior["season_id"] != sid:
                raise PingConflict("This receipt belongs to another sender or season")
            return web.json_response({"receipt": public_receipt(prior)})
        test_prior = (
            request.app["declaration_test_jobs"].get(token)
            if isinstance(token, str)
            else None
        )
        if test_prior:
            if (
                test_prior["actor_id"] != actor
                or test_prior["season_id"] != sid
                or test_prior["pool"] != pool
            ):
                raise PingConflict("This test belongs to another sender or season")
            return web.json_response(
                {"receipt": public_receipt(test_prior), "test": True}
            )
        review = await storage.review(pool, actor, sid, token)
        test = review["mode"] == "test"
        if test and token in request.app["declaration_test_jobs"]:
            return web.json_response(
                {"receipt": public_receipt(request.app["declaration_test_jobs"][token])}
            )
        channel = (
            test_channel(request) if test else (await storage.read(pool))["channel"]
        )
        if channel != review["channel"]:
            raise PingConflict("The destination changed. Review again.")
        groups, version, _ = await fresh_groups(request, pool)
        fresh = fingerprint(groups, version, channel, review["revision"])
        await destinations.destination(request, channel["id"])
        if not await destinations.authorized(request, actor):
            raise web.HTTPForbidden(text="Send permission was removed")
        require_current_publication(request, version)
        plan = messages(groups, test=test)
        if test:
            await storage.consume_test(
                pool,
                actor,
                sid,
                token,
                fresh,
                runtime=request.app["declaration_runtime"],
            )
            active = dict(
                token=token,
                actor_id=actor,
                season_id=sid,
                publication_version=version,
                channel=channel,
                test=True,
                created_at=time.time(),
                pool=pool,
                state="sending",
                posted=[],
                next=0,
                attempting=None,
                chunks=len(plan),
                count=sum(len(g["accounts"]) for g in groups),
                unlinked=sum(len(g["unlinked"]) for g in groups),
            )
            jobs = request.app["declaration_test_jobs"]
            jobs[token] = active
            # Test state is ephemeral and bounded; never a real ping receipt.
            for old in list(jobs):
                if len(jobs) <= 20:
                    break
                if jobs[old]["state"] != "sending":
                    jobs.pop(old)
            claimed = True
        else:
            claimed, active = await storage.claim(
                pool,
                actor,
                sid,
                token,
                fresh,
                plan,
                request.app["declaration_runtime"],
                send_again=body["send_again"],
            )
        if claimed:
            launch(request, active, plan, test=test)
    return web.json_response(
        {"receipt": public_receipt(active), "test": test},
        status=202 if claimed else 200,
    )


async def job(request):
    _, sid, pool = context(request)
    token = request.match_info["token"]
    async with mongo(request) as client:
        row = await DeclarationPingStore(client, GUILD_ID).receipt(pool, token)
    row = row or request.app["declaration_test_jobs"].get(token)
    if not row or row["season_id"] != sid or row["pool"] != pool:
        raise web.HTTPNotFound(text="No delivery receipt found")
    return web.json_response({"receipt": public_receipt(row)})


async def close_interrupted(request):
    from .app import _json

    _, sid, pool = context(request, send=True)
    body = await _json(request)
    if set(body) != {"token", "confirm"} or body["confirm"] is not True:
        raise web.HTTPBadRequest(
            text="Confirm closing the interrupted receipt; this sends nothing"
        )
    token = body["token"]
    if not isinstance(token, str) or token in request.app["declaration_running_tokens"]:
        raise PingConflict("This worker is still running")
    async with mongo(request) as client:
        storage = DeclarationPingStore(client, GUILD_ID)
        row = await storage.receipt(pool, token)
        if not row or row["season_id"] != sid:
            raise PingConflict("No interrupted receipt found for this season")
        result = await storage.finish(
            pool,
            token,
            "uncertain",
            "Staff closed an interrupted send. Inspect confirmed IDs and the in-flight chunk; no retry was attempted.",
        )
    return web.json_response({"receipt": public_receipt(result)})


def guarded(handler):
    async def handle(request):
        try:
            return await handler(request)
        except PingConflict as exc:
            raise web.HTTPConflict(text=str(exc)) from None
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from None

    handle.__name__ = handler.__name__
    return handle


def routes():
    return [
        web.get(BASE, guarded(state)),
        web.put(BASE, guarded(configure)),
        web.post(BASE + "/close-interrupted", guarded(close_interrupted)),
        web.post(BASE + "/preview", guarded(preview)),
        web.post(BASE + "/send", guarded(send)),
        web.get(BASE + "/jobs/{token}", guarded(job)),
    ]
