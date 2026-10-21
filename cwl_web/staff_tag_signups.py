"""Staff player-tag signup with optional season-local Discord association."""
import re
from aiohttp import web
from .providers import tag

async def lookup(request):
    from .app import _require, _fail, _store, _sid, _season
    _require(request, 'editor')
    try:
        value = tag(request.query.get('tag'))
    except ValueError:
        _fail(400, 'Enter a valid player tag')
    with _store(request).tx() as db:
        _season(db, _sid(request))
        saved = db.execute('SELECT pool FROM signups WHERE season_id=? AND tag=?', (_sid(request), value)).fetchone()
    provider = request.app['providers']
    account = await provider.player(value)
    owner = await provider.linked_owner(value)
    return web.json_response({'account': account, 'linked_user_id': owner, 'signed_up_pool': saved['pool'] if saved else None})

async def add(request):
    from .app import _require, _fail, _json, _store, _sid, _season, _audit, _bump, _family_directory, _family_status, _check_signup_pool
    actor = _require(request, 'editor')
    body = await _json(request)
    try:
        value = tag(body.get('tag'))
    except ValueError:
        _fail(400, 'Enter a valid player tag')
    pool = body.get('pool')
    preference = body.get('prefer_crystal_1_or_lower')
    has_discord = body.get('has_discord')
    if pool not in ('main', 'lazy') or type(preference) is not bool or type(has_discord) is not bool:
        _fail(400, 'Choose a CWL type and Discord option')
    uid = body.get('user_id') or ''
    if not isinstance(uid, str) or (has_discord and not re.fullmatch(r'[0-9]{15,22}', uid)) or (not has_discord and uid):
        _fail(400, 'Enter a valid Discord ID or turn off Has a Discord account')
    sid = _sid(request)
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            _fail(423, 'Archived seasons cannot be changed')
    provider = request.app['providers']
    account = await provider.player(value)
    directory = await _family_directory(request)
    account['current_clan_type'] = (directory or {}).get(account['current_clan_tag'], {}).get('type')
    account['family_clan_status'] = _family_status(account['current_clan_tag'], None if directory is None else set(directory))
    _check_signup_pool(pool, [account])
    owner = await provider.linked_owner(value)
    if body.get('expected_linked_user_id') != owner:
        _fail(409, 'The Discord link changed. Look up the player again.')
    if owner and (not has_discord or uid != owner):
        _fail(409, 'Use the Discord account already linked to this player')
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            _fail(423, 'Archived seasons cannot be changed')
        if db.execute('SELECT 1 FROM signups WHERE season_id=? AND tag=?', (sid, value)).fetchone():
            _fail(409, 'This account is already signed up. Use Roster builder to move it.')
        # Empty owner means no Discord association; never invent a Discord ID.
        db.execute('INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall,signup_clan_tag,signup_clan_name) VALUES (?,?,?,?,?,?,?,?,?)',
                   (sid, value, uid, pool, int(preference if pool == 'lazy' else False), account['name'], account['town_hall'], account['current_clan_tag'], account['current_clan_name']))
        after = dict(db.execute('SELECT * FROM signups WHERE season_id=? AND tag=?', (sid, value)).fetchone())
        _audit(db, sid, value, actor['user_id'], 'staff_signup', None, {**after, 'association_source': 'linked' if owner else 'staff' if uid else 'none'})
        _bump(db, sid)
    return web.json_response({'ok': True, 'count': 1}, status=201)

routes = [web.get('/api/cwl/seasons/{season_id}/staff-signups/player', lookup),
          web.post('/api/cwl/seasons/{season_id}/staff-signups/player', add)]
