"""Authorized HTTP adapters for staff-reviewed bonus raffles."""
import asyncio
import hashlib
import json
import sqlite3
from aiohttp import web
from .participation_display import participation_json_response
from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUnavailable, DiscordTransport
from utils.cwl_bonus_raffle_store import LAZY_SEASON_POOL, REP_NOTE_MAX, SEASON_POOL_JOIN, RaffleConflict, RaffleStore
from utils.cwl_bonus_allowance import AllowanceStore
from utils.cwl_bonus_raffle import eligibility, lazy_eligibility
from .bonuses import _view, _require_draft, _bump, _validate_revision, _cas


def _state(db, sid):
    from .app import _fail
    result = _view(db, sid, current_roster=True)
    if result is None:
        _fail(404, 'Season not found')
    rounds = {r['clan_tag']: len(json.loads(r['war_tags_json'])) for r in db.execute('SELECT clan_tag,war_tags_json FROM participation_group_observations WHERE season_id=? AND cycle=?', (sid, result['cycle']))}
    for account in result['accounts']:
        account['season_rounds'] = rounds.get(account['assigned_clan_tag'])
    store = RaffleStore(db, sid)
    # enrich_view sets FWA Rep odds from the saved family-wide account list.
    result = store.enrich_view(result)
    for account in result['accounts']:
        if account['pool'] == 'lazy':
            account['exclusion'] = lazy_eligibility(account)
    return {**result, 'policies': store.policies(), 'draws': store.draws(),
            'allowances': {c['tag']: AllowanceStore(db, sid, result['cycle']).view(c['tag']) for c in result['clans']}}


async def _response(request, sid):
    from .app import _store
    with _store(request).tx() as db:
        result = _state(db, sid)
    return participation_json_response(request, result)


def _selection(body):
    from .app import _fail
    if body.get('pool') not in ('main', 'lazy'):
        _fail(400, "Select Main or Lazy CWL")
    if not isinstance(body.get('clan_tag'), str) or len(body['clan_tag']) > 20:
        _fail(400, "Select a hosting clan")
    if body.get('slots') is not None and (type(body['slots']) is not int or not 1 <= body['slots'] <= 50):
        _fail(400, 'Enter 1–50 available bonuses, as shown in-game')
    return body['pool'], body['clan_tag'], body['slots']


async def state(request):
    from .app import _require, _sid, _store
    _require(request, 'editor')
    return await _response(request, _sid(request))


def _draw_state(draws, cycle, pool, clan_tag):
    # The newest draw per pool and clan wins; a cancelled draw only shows when nothing replaced it.
    matching = [d for d in draws if d['cycle'] == cycle and d['pool'] == pool and d['clan_tag'] == clan_tag]
    live = next((d for d in matching if not d['cancelled_at']), None)
    if live is None:
        return 'cancelled' if matching else 'none'
    if live['delivery'] and live['delivery']['status'] == 'sent':
        return 'sent'
    return 'approved' if live['approved_at'] else 'saved'


def _bonus_status(db, sid):
    # Read-only summary from stored results; Lazy counts omit FWA Rep weighting.
    view = _state(db, sid)
    minimum = view['policies']['main']
    pools = {'main': [], 'lazy': []}
    for pool in pools:
        by_clan = {}
        for account in view['accounts']:
            if account['pool'] == pool and account.get('assigned_clan_tag'):
                by_clan.setdefault(account['assigned_clan_tag'], []).append(account)
        names = {c['tag']: c['name'] for c in view['clans']}
        for tag, accounts in by_clan.items():
            if pool == 'lazy':
                meets = sum(1 for a in accounts if lazy_eligibility(a) is None)
            else:
                meets = None if minimum is None else sum(1 for a in accounts if eligibility(a, minimum) is None)
            # Did not join is a final result, so it never leaves results open.
            complete = sum(1 for a in accounts if a.get('source_complete') or a.get('source_no_show'))
            pools[pool].append({
                'tag': tag, 'name': names.get(tag) or accounts[0].get('assigned_clan_name') or tag,
                # Main has no host check; Lazy follows the season pool rule from enrich_view.
                'active': all(a.get('host_valid') for a in accounts) if pool == 'lazy' else True,
                'candidates': len(accounts), 'meets_rule': meets,
                'results_state': 'captured' if complete == len(accounts) else 'partial' if complete else 'not_checked',
                'allowance_ready': view['allowances'].get(tag, {}).get('status') == 'ready',
                'draw_state': _draw_state(view['draws'], view['cycle'], pool, tag),
            })
        pools[pool].sort(key=lambda c: (c['name'].lower(), c['tag']))
    return {'season_id': sid, 'cycle': view['cycle'], 'archived': view['season_status'] == 'archived',
            'main_minimum': minimum, 'pools': pools}


async def bonus_status(request):
    from .app import _require, _sid, _store
    _require(request, 'editor')
    sid = _sid(request)
    with _store(request).tx() as db:
        result = _bonus_status(db, sid)
    return web.json_response(result)


async def refresh_results(request):
    from .app import _require, _sid, _store
    from .participation_sync import sync_season
    _require(request, 'editor')
    sid = _sid(request)
    await sync_season(request.app, sid, force=True)
    return await _response(request, sid)


async def policy(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'pool', 'minimum', 'revision'} or body['pool'] not in ('main', 'lazy') or type(body['minimum']) is not int or not 0 <= body['minimum'] <= 7:
        _fail(400, "Select a CWL pool and a minimum of 0–7 attacks")
    if body['pool'] == 'lazy':
        _fail(400, 'Lazy CWL uses 4 attacks, or 3 attacks with 8 stars')
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, _validate_revision(body, _fail), _fail)
        RaffleStore(db, sid).save_policy(body['pool'], body['minimum'])
        _bump(db, sid, actor)
        result = _state(db, sid)
    return participation_json_response(request, result)


async def preview(request):
    from .app import _require, _sid, _store, _json, _fail
    _require(request, 'editor')
    body = await _json(request)
    if set(body) != {'pool', 'clan_tag', 'slots'}:
        _fail(400, 'Expected CWL pool, hosting clan and bonus count')
    selection = _selection(body)
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        result = RaffleStore(db, sid).preview(_state(db, sid), *selection)
    return participation_json_response(request, result)


async def draw(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'pool', 'clan_tag', 'slots', 'fingerprint'} or not isinstance(body.get('fingerprint'), str) or len(body['fingerprint']) != 64:
        _fail(400, 'Review qualifying accounts before drawing')
    selection = _selection(body)
    sid = _sid(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            RaffleStore(db, sid).draw(_state(db, sid), *selection, body['fingerprint'], actor)
            result = _state(db, sid)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return participation_json_response(request, result)


def _draw_id(request):
    from .app import _fail
    try:
        return int(request.match_info['draw_id'])
    except ValueError:
        _fail(400, 'Invalid saved draw')


async def approve(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    if await _json(request) != {}:
        _fail(400, 'Unexpected approval fields')
    sid, draw_id = _sid(request), _draw_id(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            prior = RaffleStore(db, sid).get(draw_id)
            RaffleStore(db, sid).approve(draw_id, _state(db, sid), actor)
            if not prior['approved_at']:
                _bump(db, sid, actor)
            result = _state(db, sid)
    except (RaffleConflict, sqlite3.IntegrityError) as exc:
        _fail(409, str(exc) if isinstance(exc, RaffleConflict) else 'Bonus selections changed. Refresh and review')
    return participation_json_response(request, result)


async def cancel(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'reason'} or not isinstance(body['reason'], str) or not 1 <= len(body['reason'].strip()) <= 500:
        _fail(400, 'Explain why this draw needs to be cancelled (up to 500 characters)')
    sid = _sid(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            RaffleStore(db, sid).cancel(_draw_id(request), actor, body['reason'].strip())
            result = _state(db, sid)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return participation_json_response(request, result)


async def send(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) not in ({'channel_id'}, {'channel_id', 'retry'}) or type(body.get('retry', False)) is not bool or not isinstance(body['channel_id'], str) or not body['channel_id'].isdigit() or not 15 <= len(body['channel_id']) <= 22:
        _fail(400, "Select an announcement channel")
    channel_id = body['channel_id']
    sid, draw_id = _sid(request), _draw_id(request)
    transport = request.app.get('announcement_transport') or DiscordTransport()
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            prior = RaffleStore(db, sid).get(draw_id)
            if prior['delivery'] and not (prior['delivery']['status'] == 'failed' and body.get('retry') is True):
                return participation_json_response(request, _state(db, sid), db=db)
        channel = await transport.get_channel(channel_id)
        if channel['id'] != channel_id:
            _fail(503, 'Discord channel lookup did not match')
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            messages = RaffleStore(db, sid).reserve_delivery(draw_id, channel_id, actor, retry=body.get('retry', False))
    except RaffleConflict as exc:
        _fail(409, str(exc))
    except (AnnouncementRejected, AnnouncementUnavailable):
        _fail(503, "Channel unavailable or outside this server. Select a usable server channel")
    try:
        for index, message in messages:
            nonce = hashlib.blake2s(f'bonus:{sid}:{draw_id}:{index}'.encode(), digest_size=12).hexdigest()
            message_id = await transport.send(channel_id, message, nonce)
            with _store(request).tx() as db:
                RaffleStore(db, sid).page_sent(draw_id, index, message_id)
    except asyncio.CancelledError:
        # Restart/cancellation leaves the durable reservation unresolved, never replayed.
        raise
    except Exception as exc:
        rejected = isinstance(exc, AnnouncementRejected)
        with _store(request).tx() as db:
            RaffleStore(db, sid).finish_delivery(draw_id, 'failed' if rejected else 'uncertain',
                'Delivery stopped. Check Discord and the receipts below; this announcement will not resend automatically.')
    else:
        with _store(request).tx() as db:
            RaffleStore(db, sid).finish_delivery(draw_id, 'sent')
    with _store(request).tx() as db:
        result = _state(db, sid)
    return participation_json_response(request, result)


def _review_body(body, keys):
    from .app import _fail
    from .providers import tag
    if set(body) != keys:
        _fail(400, 'Invalid bonus review fields')
    revision = _validate_revision(body, _fail)
    try:
        value = tag(body['tag'])
    except (ValueError, TypeError):
        _fail(400, 'Enter a valid player tag')
    return value, revision


async def account_review(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    tag, revision = _review_body(body, {'tag', 'flags', 'override_reason', 'revision'})
    if (not isinstance(body['flags'], list) or any(not isinstance(flag, str) for flag in body['flags'])
            or len(body['flags']) > 3 or len(set(body['flags'])) != len(body['flags'])
            or not set(body['flags']) <= {'missed_sync', 'lingering', 'left_family'}
            or not isinstance(body['override_reason'], str) or len(body['override_reason']) > 500):
        _fail(400, "Select valid flags and an override reason of at most 500 characters")
    sid = _sid(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            _cas(db, sid, revision, _fail)
            current = _state(db, sid)
            account = next((a for a in current['accounts'] if a['tag'] == tag), None)
            if not account or account['pool'] != 'lazy':
                _fail(400, "Select a Lazy CWL account from this season")
            RaffleStore(db, sid).save_account_review(tag, body['flags'], body['override_reason'], actor)
            _bump(db, sid, actor)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return await _response(request, sid)


async def rep_accounts(request):
    """Add (POST), edit the note of (PATCH) or remove (DELETE) one FWA Rep account."""
    from .app import _require, _sid, _store, _json, _fail
    from .providers import ProviderUnavailable
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    keys = {'POST': {'tag', 'note', 'revision'}, 'PATCH': {'tag', 'note', 'rep_revision', 'revision'},
            'DELETE': {'tag', 'rep_revision', 'revision'}}[request.method]
    tag, revision = _review_body(body, keys)
    if 'note' in keys and (not isinstance(body['note'], str) or len(body['note'].strip()) > REP_NOTE_MAX):
        _fail(400, f'Enter a note of up to {REP_NOTE_MAX} characters')
    if 'rep_revision' in keys and (type(body['rep_revision']) is not int or body['rep_revision'] < 1):
        _fail(400, 'Refresh the FWA Rep accounts and try again')
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, revision, _fail)
    identity = None
    if request.method == 'POST':
        provider = request.app['providers']
        try:
            account, owner = await asyncio.wait_for(asyncio.gather(provider.player(tag), provider.linked_owner(tag)), timeout=20)
        except (ProviderUnavailable, TimeoutError, KeyError):
            _fail(503, 'Could not verify this player. Try again shortly')
        if account.get('tag') != tag:
            _fail(503, 'Player lookup did not match the requested tag')
        identity = {'tag': tag, 'player_name': account.get('name') or tag, 'town_hall': account.get('town_hall'), 'user_id': owner}
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            _cas(db, sid, revision, _fail)
            store = RaffleStore(db, sid)
            if request.method == 'POST':
                store.add_rep_account(identity, body['note'], actor)
            elif request.method == 'PATCH':
                store.update_rep_note(tag, body['note'], body['rep_revision'], actor)
            else:
                store.remove_rep_account(tag, body['rep_revision'], actor)
            _bump(db, sid, actor)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return await _response(request, sid)


async def manual_candidates(request):
    from .app import _require, _sid, _store, _json, _fail
    from .providers import ProviderUnavailable, tag as normalize_tag
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    removing = request.method == 'DELETE'
    tag, revision = _review_body(body, {'tag', 'revision'} if removing else {'tag', 'clan_tag', 'reason', 'revision'})
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, revision, _fail)
    identity = None
    if not removing:
        if not isinstance(body['reason'], str) or not 1 <= len(body['reason'].strip()) <= 500:
            _fail(400, 'Explain why this player is being added (up to 500 characters)')
        try:
            clan_tag = normalize_tag(body['clan_tag'])
        except (ValueError, TypeError):
            _fail(400, "Select an active Lazy hosting clan")
        with _store(request).tx() as db:
            host = db.execute(f"SELECT c.tag FROM clans c JOIN lineup l ON c.tag=l.tag {SEASON_POOL_JOIN} WHERE l.season_id=? AND c.tag=? AND c.archived=0 AND {LAZY_SEASON_POOL}", (sid, clan_tag)).fetchone()
            if not host:
                _fail(400, "Select an active Lazy hosting clan in this season")
        provider = request.app['providers']
        try:
            account, owner = await asyncio.wait_for(asyncio.gather(provider.player(tag), provider.linked_owner(tag)), timeout=20)
        except (ProviderUnavailable, TimeoutError, KeyError):
            _fail(503, 'Could not verify this player and Discord link. Try again shortly')
        if account.get('tag') != tag:
            _fail(503, 'Player lookup did not match the requested tag')
        identity = {'tag': tag, 'player_name': account.get('name'), 'town_hall': account.get('town_hall'), 'user_id': owner}
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            _cas(db, sid, revision, _fail)
            store = RaffleStore(db, sid)
            if removing:
                store.remove_manual_candidate(tag, actor)
            else:
                store.add_manual_candidate(identity, clan_tag, body['reason'].strip(), actor)
            _bump(db, sid, actor)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return await _response(request, sid)


def routes():
    from .app import API
    base = API + '/seasons/{season_id}/bonus-raffle'
    return [web.patch(base + '/account-review', account_review),
            web.post(base + '/rep-accounts', rep_accounts),
            web.patch(base + '/rep-accounts', rep_accounts),
            web.delete(base + '/rep-accounts', rep_accounts),
            web.post(base + '/manual-candidates', manual_candidates),
            web.delete(base + '/manual-candidates', manual_candidates),
            web.get(base, state), web.get(API + '/seasons/{season_id}/bonus-status', bonus_status),
            web.post(base + '/refresh-results', refresh_results), web.patch(base + '/policy', policy),
            web.post(base + '/preview', preview), web.post(base + '/draw', draw),
            web.post(base + '/{draw_id}/approve', approve), web.post(base + '/{draw_id}/cancel', cancel), web.post(base + '/{draw_id}/send', send)]
