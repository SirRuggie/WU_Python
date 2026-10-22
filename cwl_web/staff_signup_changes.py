"""Atomic, revision-checked staff changes to one member's saved signups."""
import asyncio
from aiohttp import web
from .providers import tag


async def change(request):
    from .app import (_require, _json, _fail, _sid, _store, _season,
                      _check_revision, _audit, _bump, _family_directory,
                      _family_status, _check_signup_pool)
    actor = _require(request, 'editor')
    body = await _json(request)
    values = body.get('tags')
    action = body.get('action')
    uid = body.get('user_id')
    if action not in ('main', 'lazy', 'remove') or not isinstance(uid, str):
        _fail(400, 'Choose an action and member')
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        _fail(400, 'Select between 1 and 100 accounts')
    try:
        tags = [tag(value) for value in values]
    except (ValueError, TypeError):
        _fail(400, 'Invalid player tag')
    if len(set(tags)) != len(tags):
        _fail(400, 'Account selected twice')
    sid = _sid(request)

    def check(db):
        if _season(db, sid)['status'] != 'draft':
            _fail(423, 'Season is archived')
        _check_revision(db, sid, body.get('revision'))
        accounts = []
        for value in tags:
            row = db.execute('SELECT * FROM signups WHERE season_id=? AND tag=?', (sid, value)).fetchone()
            if row is None or row['user_id'] != uid:
                _fail(409, 'Signups changed. Refresh and select the accounts again.')
            accounts.append(dict(row))
        return accounts

    with _store(request).tx() as db:
        accounts = check(db)
    # Verify current FWA eligibility only for accounts actually moving to Main.
    if action == 'main':
        directory = await _family_directory(request)
        limit = asyncio.Semaphore(5)
        async def eligible(account):
            async with limit:
                current = dict(await request.app['providers'].player(account['tag']))
            current['current_clan_type'] = (directory or {}).get(current.get('current_clan_tag'), {}).get('type')
            current['family_clan_status'] = _family_status(current.get('current_clan_tag'), None if directory is None else set(directory))
            _check_signup_pool('main', [current])
        await asyncio.gather(*(eligible(account) for account in accounts if account['pool'] != 'main'))
    with _store(request).tx() as db:
        accounts = check(db)
        count = 0
        for account in accounts:
            value = account['tag']
            if action == account['pool']:
                continue
            entry = db.execute('SELECT * FROM roster_entries WHERE season_id=? AND tag=?', (sid, value)).fetchone()
            before = {'signup': account, 'roster': dict(entry) if entry else None}
            if action == 'remove':
                db.execute('DELETE FROM signups WHERE season_id=? AND tag=?', (sid, value))
                after = None
            else:
                db.execute('UPDATE signups SET pool=?,prefer_crystal_1_or_lower=0,updated_at=CURRENT_TIMESTAMP WHERE season_id=? AND tag=?', (action, sid, value))
                db.execute('UPDATE roster_entries SET assigned_clan_tag=NULL,kept=0 WHERE season_id=? AND tag=?', (sid, value))
                after = dict(db.execute('SELECT * FROM signups WHERE season_id=? AND tag=?', (sid, value)).fetchone())
            _audit(db, sid, value, actor['user_id'], 'staff_remove_signup' if action == 'remove' else 'staff_pool_change', before, after)
            count += 1
        revision = _bump(db, sid) if count else body['revision']
    return web.json_response({'ok': True, 'count': count, 'revision': revision})


routes = [web.post('/api/cwl/seasons/{season_id}/staff-signup-changes', change)]
