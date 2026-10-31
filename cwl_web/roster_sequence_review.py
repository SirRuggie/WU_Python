"""Build frozen server-side sequence inputs from a reviewed publication."""
import secrets

from aiohttp import web
from utils.cwl_roster_order import ordered_roster_clans
from utils.cwl_roster_messages import clan_image_message, closing_message
from utils.cwl_roster_image_store import RosterImageStore, ImageConflict
from .clan_metadata import enrich
from .roster_image_posts import groups_for


async def frozen_plan(request, sid, pool, version):
    storage = RosterImageStore(request.app['store'])
    publication = storage.publication(sid)
    if not publication or publication[1]['version'] != version:
        raise web.HTTPConflict(text='Published roster changed; refresh and review')
    season, _, groups = groups_for(publication)
    clans = ordered_roster_clans(group for group in groups.values() if group['pool'] == pool)
    await enrich(request, clans)
    plan = {'clans': [], 'closing': {'request_id': secrets.token_hex(12), 'payload': closing_message()}}
    for clan in clans:
        pages = (len(clan['accounts']) + 14) // 15
        if not 1 <= pages <= 10:
            raise web.HTTPBadRequest(text='A clan roster is too large for one Discord message')
        plan['clans'].append({
            'tag': clan['tag'], 'name': clan['name'], 'pages': pages,
            'request_id': secrets.token_hex(12),
            'frozen': {'name': clan['name'], 'season_label': season['label'],
                       'league': clan.get('cwl_league') or clan['league'],
                       'payload': clan_image_message(clan['name'], clan['tag'])},
        })
    return plan


async def prepare(request, sid, pool, cycle, body, actor, previous):
    """Persist intent before the existing native announcement queue call."""
    if previous and previous.get('status') not in ('failed', 'stale'):
        raise web.HTTPConflict(text='This pool already has an announcement request; refresh its status')
    storage = RosterImageStore(request.app['store'])
    existing = storage.pool_sequence(sid, pool)
    if existing and existing['cycle'] != cycle:
        raise web.HTTPConflict(text='The sequence belongs to a different campaign month')
    plan = await frozen_plan(request, sid, pool, body['version'])
    try:
        if existing:
            return storage.revise_unsent_sequence(
                existing['sequence_id'], version=body['version'], generation=body['generation'],
                channel=body['channel_id'], actor=str(actor['user_id']), plan=plan,
            )
        return storage.prepare_sequence(
            sequence_id=secrets.token_hex(12), sid=sid, pool=pool, cycle=cycle,
            version=body['version'], generation=body['generation'], channel=body['channel_id'],
            actor=str(actor['user_id']), plan=plan,
        )
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None


def describe(storage, sid, pool):
    """Read-only review/status projection; never fetch or render image previews."""
    import json
    sequence = storage.pool_sequence(sid, pool)
    publication = storage.publication(sid)
    if sequence:
        plan = json.loads(sequence['plan_json'])
        clans = [{'tag': item['tag'], 'name': item.get('name') or item['frozen']['name'],
                  'pages': item.get('pages'), 'request_id': item['request_id'],
                  'status': (storage.receipt(item['request_id']) or {}).get('status', 'pending')}
                 for item in plan['clans']]
    else:
        groups = groups_for(publication)[2].values() if publication else []
        clans = [{'tag': group['tag'], 'name': group['name'],
                  'pages': (len(group['accounts']) + 14) // 15, 'status': 'not_started'}
                 for group in ordered_roster_clans(groups) if group['pool'] == pool]
    closing = storage.closing_receipt(sequence['sequence_id']) if sequence else None
    return {
        'sequence_id': sequence['sequence_id'] if sequence else None,
        'status': sequence['status'] if sequence else 'not_started',
        'announcement_confirmed': bool(sequence and sequence['announcement_message_id']),
        'error': sequence['error'] if sequence else None,
        'version': sequence['target_version'] if sequence else publication[1]['version'] if publication else None,
        'channel_id': sequence['channel_id'] if sequence else None,
        'closing': ({key: closing.get(key) for key in ('request_id', 'status', 'error')} if closing else None),
        'clans': clans,
    }


async def resume(request):
    from .app import _json, _sid
    from .manage_bridge import _pool
    from .roster_image_posts import staff
    actor = staff(request, send=True)
    body = await _json(request)
    storage = RosterImageStore(request.app['store'])
    job = storage.pool_sequence(_sid(request), _pool(request))
    _not_active(request, job)
    if set(body) != {'sequence_id'} or not job or body['sequence_id'] != job['sequence_id']:
        raise web.HTTPConflict(text='Sequence changed; refresh before resuming')
    import json
    plan = json.loads(job['plan_json'])
    receipts = [storage.receipt(item['request_id']) for item in plan['clans']]
    receipts.append(storage.closing_receipt(job['sequence_id']))
    if any(receipt and receipt['status'] in ('sending', 'uncertain') for receipt in receipts):
        raise web.HTTPConflict(text='Check Discord first: a message may already have posted')
    try:
        storage.request_sequence_resume(job['sequence_id'], str(actor['user_id']))
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return web.json_response({'sequence': describe(storage, job['season_id'], job['pool'])}, status=202)


def _not_active(request, job):
    jobs = request.app.get('roster_sequence_jobs')
    if jobs and job and job['sequence_id'] in jobs.tasks:
        raise web.HTTPConflict(text='The current delivery is still finishing; refresh before retrying')


async def recover(request):
    from .app import _json, _sid
    from .manage_bridge import _pool
    from .roster_image_posts import staff
    actor = staff(request, send=True)
    body = await _json(request)
    storage = RosterImageStore(request.app['store'])
    job = storage.pool_sequence(_sid(request), _pool(request))
    _not_active(request, job)
    if (set(body) != {'sequence_id', 'request_id', 'confirm_duplicate'}
            or body.get('confirm_duplicate') is not True or not job
            or body['sequence_id'] != job['sequence_id']):
        raise web.HTTPBadRequest(text='Check Discord first and confirm Post again anyway')
    try:
        storage.recover_sequence_message(job['sequence_id'], body['request_id'],
                                         secrets.token_hex(12), str(actor['user_id']))
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return web.json_response({'sequence': describe(storage, job['season_id'], job['pool'])}, status=202)
