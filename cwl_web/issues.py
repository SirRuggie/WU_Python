"""Safe request diagnostics and owner-only issue list."""
import asyncio
import json
import logging
import secrets
import time
from aiohttp import web
from utils.dashboard_issues import IssueRepository

log = logging.getLogger('dashboard.issues')


def action(request):
    # Router templates omit account tags, search text, OAuth codes and query strings.
    resource = request.match_info.route.resource
    return getattr(resource, 'canonical', 'unknown') or 'unknown'


async def record(request, kind, status, *, error_type=None):
    from .app import _session
    from .server_management import mongo
    reference = secrets.token_hex(6)
    try:
        member = _session(request)['user_id']
    except Exception:
        member = None
    issue = dict(id=reference, at=time.time(), member=member,
                 kind=kind, status=status, action=action(request), method=request.method, error_type=error_type)
    # Safe fallback survives a Mongo outage in the service journal.
    log.warning('issue=%s kind=%s status=%s action=%s method=%s member=%s error_type=%s',
                reference, kind, status, issue['action'], request.method, member, error_type)
    try:
        async with asyncio.timeout(2):
            async with mongo(request) as db:
                await IssueRepository(db.bot_config).append(issue)
    except Exception:
        log.warning('issue=%s storage_unavailable', reference)
    return reference


@web.middleware
async def diagnostics(request, handler):
    if not request.path.startswith('/api/cwl/') or request.path.startswith('/api/cwl/issues'):
        return await handler(request)
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        reference = await record(request, 'server_error', 500, error_type=type(exc).__name__)
        return web.json_response({'error': 'Something went wrong. Please contact staff before retrying a send.',
                                  'issue_reference': reference}, status=500,
                                 headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    # Expected session probes and routine validation are not incidents.
    if response.status >= 500 or (request.method not in ('GET', 'HEAD', 'OPTIONS') and response.status >= 400):
        reference = await record(request, 'service_unavailable' if response.status >= 500 else 'action_rejected', response.status)
        if response.content_type == 'application/json':
            try:
                data = json.loads(response.text)
                data['issue_reference'] = reference
                response.text = json.dumps(data)
            except (ValueError, TypeError):
                pass
    return response


async def listing(request):
    from .app import _require
    from .server_management import mongo
    _require(request, 'owner')
    async with mongo(request) as db:
        items = await IssueRepository(db.bot_config).recent()
    return web.json_response({'items': items}, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


async def browser_report(request):
    from .app import _require, _json
    member = _require(request)['user_id']
    body = await _json(request)
    kind = body.get('kind')
    if kind not in ('browser_error', 'unhandled_promise', 'network_error'):
        raise web.HTTPBadRequest(text='Invalid issue type.')
    # Bounded per-process limiter; reports contain no caller-supplied free text.
    now = time.monotonic()
    limits = request.app.setdefault('issue_report_limits', {})
    for key, stamp in list(limits.items()):
        if now - stamp > 60:
            del limits[key]
    if member in limits or len(limits) >= 1000:
        raise web.HTTPTooManyRequests(text='Report already received. Please contact staff.')
    limits[member] = now
    reference = await record(request, kind, 0)
    return web.json_response({'reference': reference})


routes = [web.get('/api/cwl/issues', listing), web.post('/api/cwl/issues/browser', browser_report)]
