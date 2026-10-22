"""Move legacy browser visits before creating origin-bound login cookies."""

from aiohttp import web

from utils.dashboard_urls import DASHBOARD_ORIGIN, LEGACY_DASHBOARD_HOST


@web.middleware
async def canonical_host(request, handler):
    host = request.headers.get("Host", "").split(":", 1)[0].lower().rstrip(".")
    if host != LEGACY_DASHBOARD_HOST or request.app.get("dev_fixture", False):
        return await handler(request)
    if request.method not in {"GET", "HEAD"}:
        return web.json_response(
            {"error": "The dashboard has moved. Open dash.warriorsunited.cc and sign in again."},
            status=409,
            headers={"Cache-Control": "no-store"},
        )
    # An old callback has an old-origin state cookie. Never forward its code.
    destination = "/" if request.path == "/api/cwl/auth/callback" else str(request.rel_url)
    raise web.HTTPFound(
        DASHBOARD_ORIGIN + destination,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
