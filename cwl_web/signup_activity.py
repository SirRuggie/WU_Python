"""Staff review of member withdrawals and pool changes, backed by the roster audit."""
import json
from aiohttp import web


async def activity(request):
    from .app import _require, _store, _sid, _season
    _require(request, 'editor')
    sid = _sid(request)
    with _store(request).tx() as db:
        _season(db, sid)
        clans = {row["tag"]: row["name"] for row in db.execute("SELECT tag,name FROM clans")}
    items = []
    for row in _store(request).signup_activity(sid):
        before = json.loads(row['before_json'] or '{}')
        after = json.loads(row['after_json'] or '{}')
        items.append({
            'id': row['id'], 'tag': row['tag'], 'player_name': before.get('player_name') or row['tag'],
            'action': row['action'], 'from_pool': before.get('pool'), 'to_pool': after.get('pool'),
            'assigned_clan_name': before.get('assigned_clan_name') or clans.get(before.get('assigned_clan_tag')),
            'assigned_clan_tag': before.get('assigned_clan_tag'), 'user_id': row['actor_id'],
            'created_at': row['created_at'].replace(' ', 'T') + 'Z',
        })
    return web.json_response({'items': items})


async def review(request):
    from .app import _require, _store, _sid, _fail
    actor = _require(request, 'editor')
    try:
        audit_id = int(request.match_info['audit_id'])
    except ValueError:
        _fail(400, 'Invalid activity')
    if not _store(request).review_signup_activity(_sid(request), audit_id, actor['user_id']):
        _fail(404, 'Signup activity not found')
    return web.json_response({'ok': True})


routes = [
    web.get('/api/cwl/seasons/{season_id}/signup-activity', activity),
    web.post('/api/cwl/seasons/{season_id}/signup-activity/{audit_id}/review', review),
]
