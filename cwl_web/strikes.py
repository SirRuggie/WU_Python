"""Authenticated dashboard for the same account ledger used by Discord."""
from __future__ import annotations

import asyncio
import aiohttp
from datetime import datetime, timezone
from functools import wraps
import re
import logging
import time
import uuid
from types import SimpleNamespace

from aiohttp import web

from . import server_management as shared
from .providers import ProviderUnavailable, tag
from utils import recruit_links
from utils.strike_store import StrikeConflict, StrikeService, utc
from utils.strike_tracking import StrikeTracking
from utils.replacement_filters import parse_weight, compact_weight

API = '/api/cwl/strikes'
GUILD_ID = shared.GUILD_ID
_OPPONENT_NAME_CACHE = {}



def endpoint(fn=None, *, scope=None):
    if fn is None:
        return lambda handler: endpoint(handler, scope=scope)
    @wraps(fn)
    async def guarded(request):
        await shared.require_manage(request, scope or ('strikes_read' if request.method == 'GET' else 'strikes'), write=request.method != 'GET')
        try:
            return await fn(request)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except StrikeConflict as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except (RuntimeError, ProviderUnavailable) as exc:
            raise web.HTTPServiceUnavailable(text='Strike data could not be checked. Try again.') from exc
    return guarded


def public(value):
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(item) for item in value]
    return value


async def body(request, allowed):
    from .app import _json
    data = await _json(request)
    if set(data) - set(allowed):
        raise ValueError('Unknown field. Refresh this page.')
    return data


def uid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{15,22}', value):
        raise ValueError('Select a Discord member.')
    return value


def number(value, minimum=1, maximum=100):
    if isinstance(value, bool):
        raise ValueError('Enter a whole number.')
    if isinstance(value, str) and not value.isascii():
        raise ValueError('Enter a whole number.')
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError('Enter a whole number.') from None
    if str(result) != str(value) or not minimum <= result <= maximum:
        raise ValueError(f'Enter a number from {minimum} to {maximum}.')
    return result


async def service(request, db):
    injected = request.app.get('strike_service')
    if injected is not None:
        return injected
    role_cache = {}

    async def roles(guild_id, member_id):
        if member_id not in role_cache:
            try:
                member = await shared.discord(request, 'GET', f'/guilds/{guild_id}/members/{member_id}')
                role_cache[member_id] = member.get('roles', [])
            except web.HTTPNotFound:
                # Confirmed departed Discord members have no server roles.
                role_cache[member_id] = []
            except web.HTTPException:
                role_cache[member_id] = None
        return role_cache[member_id]

    return StrikeService(db, role_resolver=roles)


async def clan_rows(db):
    rows = await db.clans.find({}, {'tag': 1, 'name': 1, 'type': 1}).to_list(length=None)
    result = []
    for row in rows:
        try:
            value = tag(row.get('tag'))
        except ValueError:
            continue
        result.append({'tag': value, 'name': row.get('name') or value, 'is_fwa': row.get('type') == 'FWA'})
    return sorted(result, key=lambda row: row['name'].casefold())


async def account_rows(request, member_id):
    links = await recruit_links.resolve(int(member_id))
    if links.unavailable or links.conflicts:
        raise ProviderUnavailable('Account links could not be verified. Try again.')
    tags = sorted(links.sources)
    if len(tags) > 100:
        raise ProviderUnavailable('Too many linked accounts to verify safely. Contact staff.')
    sem = asyncio.Semaphore(6)

    async def account(value):
        async with sem:
            return await request.app['providers'].player(value)
    rows = await asyncio.gather(*(account(value) for value in tags))
    return [{'tag': row['tag'], 'name': row['name'], 'town_hall': row.get('town_hall'),
             'current_clan_tag': row.get('current_clan_tag'),
             'current_clan_name': row.get('current_clan_name')} for row in rows]


def display_member(row):
    user = row.get('user') or {}
    return {'id': str(user['id']), 'name': row.get('nick') or user.get('global_name') or user.get('username') or str(user['id']), 'accounts': []}


@endpoint(scope='strikes_add')
async def targets(request):
    """Known player names, direct tags, or member-linked accounts; no global name API."""
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter name, tag, or ID.')
    if len(query) < 2:
        return web.json_response({'accounts': [], 'members': []})
    members_found = []
    if query.startswith('#'):
        rows = [await request.app['providers'].player(tag(query))]
    elif re.fullmatch(r'[0-9]{15,22}', query):
        await shared.discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{query}')
        links = await recruit_links.resolve(int(query))
        if links.unavailable or links.conflicts:
            raise ProviderUnavailable('Account links could not be verified. Try again.')
        async with shared.mongo(request) as db:
            ledger = await service(request, db)
            rows = await ledger.saved_target_accounts(GUILD_ID, sorted(links.sources))
    else:
        from .manage_roles import searchable_members, search_text
        async with shared.mongo(request) as db:
            ledger = await service(request, db)
            known = await ledger.known_targets(GUILD_ID, query)
            rows = await ledger.saved_target_accounts(GUILD_ID, [row['player_tag'] for row in known])
        folded = search_text(query)
        candidates = await searchable_members(request)
        members_found = [display_member(row) for row in candidates
                         if not (row.get('user') or {}).get('bot') and folded in search_text(' '.join(
                             str(value or '') for value in (row.get('nick'),
                             (row.get('user') or {}).get('global_name'),
                             (row.get('user') or {}).get('username'))))][:25]
    accounts_found = [{key: row.get(key) for key in
                       ('tag', 'name', 'town_hall', 'current_clan_tag', 'current_clan_name')} for row in rows]
    return web.json_response({'accounts': accounts_found, 'members': members_found})


@endpoint
async def leave_state(request):
    member_id = uid(request.match_info['member_id'])
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        revision = await ledger.leave_revision(GUILD_ID, int(member_id))
    return web.json_response({'revision': revision})


@endpoint
async def members(request):
    from .manage_roles import searchable_members, search_text
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter name or ID.')
    if re.fullmatch(r'[0-9]{15,22}', query):
        try:
            rows = [await shared.discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{query}')]
        except web.HTTPNotFound:
            rows = []
    elif query.startswith('#'):
        owner = await request.app['providers'].linked_owner(tag(query))
        rows = [await shared.discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{owner}')] if owner else []
    else:
        if len(query) < 2:
            return web.json_response({'members': []})
        rows = await searchable_members(request)
        folded = search_text(query)
        rows = [row for row in rows if folded in search_text(' '.join(str(x or '') for x in (
            row.get('nick'), row.get('user', {}).get('global_name'), row.get('user', {}).get('username'), row.get('user', {}).get('id'))))]
    return web.json_response({'members': [display_member(row) for row in rows[:25] if not row.get('user', {}).get('bot')]})


@endpoint
async def member_accounts(request):
    member_id = uid(request.match_info['member_id'])
    member = await shared.discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{member_id}')
    result = display_member(member)
    result['accounts'] = await account_rows(request, member_id)
    return web.json_response({'member': result})


def entry(row, clans, profile=None):
    profile = profile or {}
    current_tag = profile.get('current_clan_tag')
    kind = row.get('kind')
    return {'id': row['_id'], 'player_tag': row['player_tag'], 'player_name': row.get('player_name') or row['player_tag'],
            'discord_id': str(row['member_id']) if row.get('member_id') else None,
            'link_status': row.get('link_status') or ('linked' if row.get('member_id') else 'unlinked'),
            'discord_name': None, 'current_clan_tag': current_tag,
            'current_clan_name': profile.get('current_clan_name') or clans.get(current_tag),
            'war_clan_tag': row.get('clan_tag'), 'war_clan_name': row.get('clan_name') or clans.get(row.get('clan_tag')),
            'war_key': row.get('war_key'), 'war_type': row.get('war_type') or 'regular',
            'war_tag': row.get('war_tag'), 'attacks_used': row.get('attacks_used'),
            'attacks_per_member': row.get('attacks_per_member'),
            'opponent_tag': row.get('opponent_tag'),
            'opponent_name': row.get('opponent_name') or clans.get(row.get('opponent_tag'))
                or _OPPONENT_NAME_CACHE.get(row.get('opponent_tag'), (0, None))[1]
                or row.get('opponent_tag'),
            'war_end': public(row['occurred_at']), 'expires_at': public(row.get('expires_at')),
            'kind': kind if kind in ('no_attack', 'mismatch') else ('cwl' if kind == 'cwl' else ('strike' if kind == 'strike' else ('completed' if kind == 'completed' else 'miss'))),
            'source': row.get('source'),
            'source_label': ('Clash API' if row.get('capture_source') == 'clash_api' else
                             'ClashKing (import)' if row.get('import_id') or
                               row.get('capture_source') == 'clashking_import' else
                             'ClashKing (legacy)' if row.get('source') in ('war', 'cwl') else None),
            'status': 'recorded' if row.get('status') == 'missed' else row.get('status'),
            'missed_attacks': row.get('missed_attacks'), 'reason': row.get('reason'),
            'war_plan_reason': row.get('war_plan_reason'),
            'exemption': row.get('exemption'), 'removed_reason': row.get('revoke_reason')}


@endpoint
async def overview(request):
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter name or tag.')
    status = request.query.get('status') or 'strikes'
    if status not in ('strikes', 'all', 'active', 'expired', 'removed', 'exempt', 'recorded', 'cwl', 'mismatch'):
        raise ValueError('Choose a history status.')
    if status == 'recorded':
        status = 'missed'
    clan = request.query.get('clan') or None
    war_key = request.query.get('war_key') or None
    limit = number(request.query.get('limit', '25'))
    offset = number(request.query.get('offset', '0'), 0, 100000)
    args = {'status': status, 'clan_tag': clan, 'war_key': war_key,
            'limit': limit, 'skip': offset}
    if query.startswith('#'):
        args['player_tag'] = tag(query)
    elif query.isascii() and query.isdigit():
        args['member_id'] = int(uid(query))
    elif query:
        args['query'] = query
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        data = await ledger.history(GUILD_ID, **args)
        clans = await clan_rows(db)
        names = {row['tag']: row['name'] for row in clans}
        await _enrich_war_names(request, data['items'], names)
        tags = sorted({row['player_tag'] for row in data['items']})
        profiles = await db.strike_profiles.find({'guild_id': GUILD_ID, 'player_tag': {'$in': tags}}).to_list(length=None)
        by_tag = {row['player_tag']: row for row in profiles}
        # Current clan is fetched independently of the immutable war snapshot.
        sem = asyncio.Semaphore(6)
        async def current(value):
            try:
                async with sem:
                    return value, await request.app['providers'].player(value)
            except ProviderUnavailable:
                return value, None
        for value, profile in await asyncio.gather(*(current(value) for value in tags)):
            if profile is not None:
                by_tag[value] = profile
        streak = await ledger.streak(GUILD_ID, args['player_tag']) if args.get('player_tag') else None
        return web.json_response({
            'entries': [entry(row, names, by_tag.get(row['player_tag'])) for row in data['items']],
            'clans': clans, 'members': [], 'streak': streak,
            'total': data['total'], 'limit': limit, 'offset': offset,
        })


@endpoint
async def accounts(request):
    if request.query.get('activity') == 'true':
        return await activity_accounts(request)
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter account search.')
    clan = request.query.get('clan') or None
    status = request.query.get('status') or 'active'
    if status not in ('active', 'all'):
        raise ValueError('Choose active or all accounts.')
    limit = number(request.query.get('limit', '25'))
    offset = number(request.query.get('offset', '0'), 0, 100000)
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        result = await ledger.account_list(GUILD_ID, query=query, clan_tag=clan,
                                           status=status, limit=limit, skip=offset,
                                           action=request.query.get('action', 'all'))
        clans = await clan_rows(db)
    names = {row['tag']: row['name'] for row in clans}
    entries = [{'player_tag': row['player_tag'], 'player_name': row['player_name'],
                'discord_id': str(row['member_id']) if row.get('member_id') else None,
                'link_status': row.get('link_status') or ('linked' if row.get('member_id') else 'unlinked'),
                'current_clan_tag': row.get('current_clan_tag'),
                'current_clan_name': names.get(row.get('current_clan_tag')),
                'clan_seen_at': public(row.get('clan_seen_at')),
                'clan_is_current': row.get('clan_is_current', False),
                'active_strikes': row['active_strikes'], 'total_strikes': row['total_strikes'],
                'over_limit': row.get('over_limit', False), 'new_this_week': row.get('new_this_week', False),
                'last_strike_at': public(row['last_strike_at']),
                'last_record_at': public(row.get('last_record_at'))}
               for row in result['items']]
    return web.json_response({'accounts': entries, 'total': result['total'],
                              'clans': clans, 'limit': limit, 'offset': offset,
                              'summary': result['summary'], 'strike_limit': result['strike_limit']})


async def activity_accounts(request):
    from utils.player_activity_store import PlayerActivityStore
    from utils.player_activity_overview import family_activity_rows
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        activity = await PlayerActivityStore(db).all_players()
        context = await ledger.activity_context(GUILD_ID, [row['tag'] for row in activity])
    rows = family_activity_rows(activity, **context)
    return web.json_response(public({'accounts': rows, 'total': len(rows),
                                    'clans': [{'tag': row['tag'], 'name': row.get('name') or row['tag']}
                                              for row in context['clans']]}))


async def _enrich_war_names(request, rows, clan_names, *, budget=8):
    """Resolve only missing opponent labels, using bounded cache and time."""
    now = time.monotonic()
    missing = set()
    for row in rows:
        row['clan_name'] = row.get('clan_name') or clan_names.get(row.get('clan_tag')) or row.get('clan_tag')
        opponent = row.get('opponent_tag')
        row['opponent_name'] = row.get('opponent_name') or clan_names.get(opponent)
        if not row['opponent_name'] and opponent:
            cached = _OPPONENT_NAME_CACHE.get(opponent)
            if cached and cached[0] > now:
                row['opponent_name'] = cached[1]
            else:
                missing.add(opponent)
    semaphore = asyncio.Semaphore(6)
    async def lookup(opponent):
        try:
            async with semaphore:
                found = await asyncio.wait_for(request.app['providers'].clan(opponent), timeout=4)
            name = found.get('name') if isinstance(found, dict) else None
            if not isinstance(name, str) or not name.strip():
                name = None
        except (ProviderUnavailable, aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            name = None
        _OPPONENT_NAME_CACHE[opponent] = (time.monotonic() + (3600 if name else 300), name)
    if missing and budget > 0:
        tasks = [asyncio.create_task(lookup(opponent)) for opponent in sorted(missing)]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=budget)
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for opponent in missing:
                cached = _OPPONENT_NAME_CACHE.get(opponent)
                if cached is None or cached[0] <= time.monotonic():
                    _OPPONENT_NAME_CACHE[opponent] = (time.monotonic() + 300, None)
    for row in rows:
        opponent = row.get('opponent_tag')
        if not row.get('opponent_name'):
            row['opponent_name'] = _OPPONENT_NAME_CACHE.get(opponent, (0, None))[1] or opponent
    return rows


@endpoint
async def wars(request):
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter clan, opponent, or date.')
    clan = request.query.get('clan') or None
    limit = number(request.query.get('limit', '25'))
    offset = number(request.query.get('offset', '0'), 0, 100000)
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        clans = await clan_rows(db)
        names = {row['tag']: row['name'] for row in clans}
        deadline = time.monotonic() + 8
        name_search_incomplete = False
        async def enrich(rows):
            nonlocal name_search_incomplete
            await _enrich_war_names(request, rows, names, budget=max(0, deadline - time.monotonic()))
            name_search_incomplete |= any(row.get('opponent_tag') and
                                          row.get('opponent_name') == row['opponent_tag'] for row in rows)
        result = await ledger.war_page(GUILD_ID, clan_tag=clan, query=query,
                                       limit=limit, skip=offset, clan_names=names, enrich_names=enrich)
    # Without a search only the displayed page needs remote name enrichment.
    await _enrich_war_names(request, result['items'], names)
    return web.json_response({'wars': [public(row) for row in result['items']],
                              'total': result['total'], 'limit': limit, 'offset': offset,
                              'name_search_incomplete': bool(name_search_incomplete)})


@endpoint(scope='strikes_add')
async def manual(request):
    data = await body(request, {'player_tag', 'reason', 'request_id'})
    request_id = data.get('request_id')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_id):
        raise ValueError('Start a new strike draft and try again.')
    player = tag(data.get('player_tag'))
    reason = data.get('reason')
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError('Enter a reason under 500 characters.')
    provider = request.app['providers']
    account = await provider.player(player)
    owners = await recruit_links.resolve_players([player])
    if owners.unavailable or owners.conflicts:
        raise ProviderUnavailable('Account links could not be verified. Try again.')
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        row = await ledger.add_manual(GUILD_ID, player, reason, int(_session(request)['user_id']),
                                      member_id=owners.owners.get(player), clan_tag=account.get('current_clan_tag'), player_name=account['name'], request_id=request_id)
    return web.json_response({'id': row['_id']}, status=201)


@endpoint(scope='strikes_remove')
async def remove(request):
    data = await body(request, {'reason'})
    if not isinstance(data.get('reason'), str) or not 1 <= len(data['reason'].strip()) <= 500:
        raise ValueError('Enter a reason under 500 characters.')
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        await ledger.revoke(GUILD_ID, request.match_info['strike_id'], int(_session(request)['user_id']), data['reason'])
    return web.json_response({'ok': True})


@endpoint
async def settings(request):
    actor = await shared.identity(request)
    roles = [{'id': str(row['id']), 'name': row['name'],
              'managed': bool(row.get('managed', False)), 'position': row.get('position', 0),
              'color': row.get('color', 0)} for row in actor['roles'] if str(row['id']) != str(GUILD_ID)]
    roles.sort(key=lambda row: (-row['position'], int(row['id'])))
    role_names = {row['id']: row['name'] for row in roles}
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        config = await ledger.settings(GUILD_ID)
        leaves = await db.strike_leaves.find({'guild_id': GUILD_ID, 'until': {'$gt': datetime.now(timezone.utc)}}).to_list(length=None)
    semaphore = asyncio.Semaphore(6)
    async def leave_name(row):
        try:
            async with semaphore:
                member = await shared.discord(request, 'GET', f"/guilds/{GUILD_ID}/members/{row['member_id']}")
            return display_member(member)['name']
        except web.HTTPException:
            return row.get('display_name') or str(row['member_id'])
    names = await asyncio.gather(*(leave_name(row) for row in leaves))
    result = []
    for row, name in zip(leaves, names):
        result.append({'discord_id': str(row['member_id']), 'display_name': name,
                       'revision': row.get('revision', 0),
                       'player_tags': row.get('account_tags') or [], 'resume_date': utc(row['until']).date().isoformat()})
    return web.json_response({'excluded_roles': [{'id': str(value), 'name': role_names.get(str(value), f'Role {value}')} for value in config['exempt_role_ids']],
                              'roles': roles, 'leaves': result, 'strike_limit': config['strike_limit'],
                              'revision': config['revision']})


@endpoint
async def save_roles(request):
    data = await body(request, {'role_ids', 'strike_limit', 'revision'})
    revision = number(data.get('revision'), 0, 2**53 - 1)
    limit = number(data['strike_limit'], 1, 20) if 'strike_limit' in data else None
    roles = data.get('role_ids')
    if not isinstance(roles, list) or len(roles) > 100:
        raise ValueError('Choose up to 100 roles.')
    roles = [uid(value) for value in roles]
    actor = await shared.identity(request)
    selectable = {str(row['id']) for row in actor['roles']
                  if str(row['id']) != str(GUILD_ID) and not row.get('managed', False)}
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        current = await ledger.settings(GUILD_ID)
        if current['revision'] != revision:
            raise StrikeConflict('Changed by someone else · Reload')
        retained = {str(value) for value in current['exempt_role_ids']}
        if set(roles) - selectable - retained:
            raise ValueError('A selected role is managed or no longer exists. Refresh the role list.')
        config = await ledger.set_exempt_roles(GUILD_ID, roles, int(actor['user_id']),
                                               expected_revision=revision, strike_limit=limit)
    return web.json_response({'ok': True, 'revision': config['revision'],
                              'strike_limit': config['strike_limit']})


@endpoint
async def save_leave(request):
    data = await body(request, {'discord_id', 'player_tags', 'resume_date', 'revision'})
    revision = number(data.get('revision'), 0, 2**53 - 1)
    member_id = uid(data.get('discord_id'))
    values = data.get('player_tags')
    if not isinstance(values, list) or not values or len(values) > 100:
        raise ValueError('Select at least one account.')
    values = [tag(value) for value in values]
    linked = {row['tag'] for row in await account_rows(request, member_id)}
    if set(values) - linked:
        raise ValueError('Account links changed. Select the member again.')
    if not isinstance(data.get('resume_date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data['resume_date']):
        raise ValueError('Choose a return date.')
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        saved = await ledger.set_leave(GUILD_ID, int(member_id), data['resume_date'],
                                        int(_session(request)['user_id']), account_tags=values,
                                        expected_revision=revision)
    return web.json_response({'ok': True, 'revision': saved['revision']})


@endpoint
async def remove_leave(request):
    data = await body(request, {'revision'})
    revision = number(data.get('revision'), 0, 2**53 - 1)
    member_id = uid(request.match_info['member_id'])
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        saved = await ledger.clear_leave(GUILD_ID, int(member_id), expected_revision=revision)
    return web.json_response({'ok': True, 'revision': saved['revision']})


@endpoint
async def replacements(request):
    raw_weight = request.query.get('weight')
    weight = parse_weight(raw_weight) if raw_weight else None
    clan = request.query.get('clan') or None
    scope = request.query.get('scope') or 'fwa'
    if scope not in ('fwa', 'all'):
        raise ValueError('Choose FWA or all clans.')
    raw_low = request.query.get('include_low', 'false').lower()
    if raw_low not in ('true', 'false', '1', '0'):
        raise ValueError('Choose whether to show one or two strikes.')
    include_low = raw_low in ('true', '1')
    offset = number(request.query.get('offset', '0'), 0, 100000)
    limit = number(request.query.get('limit', '25'), 1, 100)
    sort = request.query.get('sort', 'priority')
    search = request.query.get('query', '')
    exact_tag = tag(request.query['exact_tag']) if request.query.get('exact_tag') else None
    raw_browse = request.query.get('browse_all', 'false').lower()
    if raw_browse not in ('true', 'false', '1', '0'):
        raise ValueError('Choose whether to browse all accounts.')
    browse_all = raw_browse in ('true', '1')
    town_hall = number(request.query['town_hall'], 1, 99) if request.query.get('town_hall') else None
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        clans = await clan_rows(db)
        allowed_tags = [row['tag'] for row in clans if row['is_fwa'] or weight is None or scope == 'all']
        profiles = await db.strike_profiles.find(
            {'guild_id': GUILD_ID, 'current_clan_tag': {'$in': allowed_tags}}).to_list(length=None)
        tags = [row['player_tag'] for row in profiles]
        try:
            from utils.clan_weights import source_weights
            weights = await source_weights(request.app['store'], request.app['providers'], tags) if tags else {}
        except ProviderUnavailable as exc:
            if weight is not None:
                raise web.HTTPServiceUnavailable(text='Current FWA weights are unavailable. Try again.') from exc
            weights = {}
        from .app import _store
        from utils.clan_weights import overlay_accounts
        resolved = overlay_accounts(_store(request), {'accounts': [
            {'tag': value, 'war_weight': (weights.get(value) or {}).get('weight')}
            for value in tags
        ]})
        effective_weights = {row['tag']: row['war_weight'] for row in resolved['accounts']}
        rows = await ledger.replacement(GUILD_ID, weight, clan_tag=clan if weight is not None else None,
                                        limit=None, weights=effective_weights,
                                        browse_all=browse_all, family_scope=scope,
                                        town_hall=town_hall if weight is not None else None)
    town_halls = sorted({row['town_hall'] for row in rows if row.get('town_hall')})
    if exact_tag:
        rows = [row for row in rows if row['player_tag'] == exact_tag]
    names = {row['tag']: row['name'] for row in clans}
    def candidate(row):
        return {'player_tag': row['player_tag'], 'player_name': row.get('player_name') or row['player_tag'],
                   'clan_tag': row.get('last_seen_clan_tag') if row.get('departed') else row.get('current_clan_tag'),
                   'clan_name': names.get(row.get('last_seen_clan_tag') if row.get('departed') else row.get('current_clan_tag')),
                   'current_clan_tag': row.get('current_clan_tag'),
                   'current_clan_name': names.get(row.get('current_clan_tag')),
                   'departed': bool(row.get('departed')),
                   'last_seen_clan_tag': row.get('last_seen_clan_tag'),
                   'last_seen_clan_name': names.get(row.get('last_seen_clan_tag')),
                   'last_seen_at': public(row.get('last_seen_at')),
                   'weight': row.get('weight'), 'weight_label': compact_weight(row.get('weight')),
                   'town_hall': row.get('town_hall'), 'active_strikes': row['active_strikes'],
                   'is_filler': bool(row.get('filler')), 'is_manual': bool(row.get('is_manual')),
                   'priority': row['replacement_priority'], 'note': row.get('replacement_note') or '',
                   'clan_seen_at': public(row.get('clan_seen_at')),
                   'clan_is_current': bool(row.get('clan_is_current')),
                   'weight_difference': row['weight_difference'],
                   'discord_id': str(row['member_id']) if row.get('member_id') else None, 'revision': row.get('revision', 0)}
    from utils.replacement_view import replacement_page, best_slots
    if weight is not None:
        selected = best_slots(rows, weight)
        page = {'items': selected, 'total': len(selected), 'top': [], 'groups': []}
    else:
        page = replacement_page(rows, include_low=include_low, clan=clan,
                                town_hall=town_hall, search=search, sort=sort,
                                offset=offset, limit=limit)
    return web.json_response({'candidates': [candidate(row) for row in page['items']],
                              'top': [candidate(row) for row in page['top']],
                              'groups': [{**group, 'clan_name': names.get(group['clan_tag']) or group['clan_tag']}
                                         for group in page['groups']],
                              'clans': clans, 'town_halls': town_halls, 'total': page['total'], 'offset': offset,
                              'limit': limit, 'include_low': include_low, 'sort': sort,
                              'matching_weight': weight, 'matching_weight_label': compact_weight(weight),
                              'scope': scope, 'browse_all': browse_all, 'town_hall': town_hall})


async def _verified_replacement_player(request, player_tag):
    player = tag(player_tag)
    try:
        profile = await request.app['providers'].player(player)
    except ProviderUnavailable as exc:
        raise web.HTTPServiceUnavailable(text='Could not verify the current player clan. Try again.') from exc
    if tag(profile.get('tag')) != player:
        raise web.HTTPServiceUnavailable(text='Player lookup returned a different account. Try again.')
    if not profile.get('current_clan_tag'):
        raise ValueError('This account is not in a registered family clan.')
    return profile


async def _live_replacement_roster(request, db, clan_value):
    clan_tag = tag(clan_value)
    if not await db.clans.find_one({'tag': clan_tag}, {'_id': 1}):
        raise ValueError('Choose a registered family clan.')
    try:
        roster = await request.app['providers'].clan_roster(clan_tag)
    except ProviderUnavailable as exc:
        raise web.HTTPServiceUnavailable(text='Current clan members are unavailable. Try again.') from exc
    if roster.get('tag') != clan_tag or not isinstance(roster.get('members'), list):
        raise web.HTTPServiceUnavailable(text='Current clan members could not be verified. Try again.')
    return roster


@endpoint(scope='strikes_read')
async def replacement_roster(request):
    clan = request.query.get('clan')
    if not clan:
        raise ValueError('Choose a clan.')
    async with shared.mongo(request) as db:
        roster = await _live_replacement_roster(request, db, clan)
        tags = [row['tag'] for row in roster['members']]
        profiles = await db.strike_profiles.find(
            {'guild_id': GUILD_ID, 'player_tag': {'$in': tags}}).to_list(length=None)
    by_tag = {row['player_tag']: row for row in profiles}
    return web.json_response({'clan_tag': roster['tag'], 'clan_name': roster['name'],
        'accounts': [{'player_tag': row['tag'], 'player_name': row['name'],
                      'town_hall': row.get('town_hall'),
                      'is_manual': bool(((by_tag.get(row['tag']) or {}).get('replacement_listed')
                                         and (by_tag.get(row['tag']) or {}).get('replacement_clan_tag') == roster['tag'])
                                        or ((by_tag.get(row['tag']) or {}).get('filler')
                                            and (by_tag.get(row['tag']) or {}).get('filler_clan_tag') == roster['tag']))}
                     for row in roster['members']]})


@endpoint
async def bulk_add_replacement_list(request):
    data = await body(request, {'clan_tag', 'player_tags', 'priority', 'note'})
    raw_tags = data.get('player_tags')
    if not isinstance(raw_tags, list) or not 1 <= len(raw_tags) <= 50:
        raise ValueError('Choose 1 to 50 accounts.')
    if any(not isinstance(value, str) for value in raw_tags):
        raise ValueError('Choose valid player accounts.')
    selected = [tag(value) for value in raw_tags]
    if len(set(selected)) != len(selected):
        raise ValueError('Select each account only once.')
    priority = data.get('priority')
    note = data.get('note', '')
    if priority not in ('replace_first', 'high', 'normal'):
        raise ValueError('Choose a replacement priority.')
    if not isinstance(note, str) or len(note.strip()) > 500:
        raise ValueError('Keep the note under 500 characters.')
    from .app import _session
    actor = int(_session(request)['user_id'])
    async with shared.mongo(request) as db:
        roster = await _live_replacement_roster(request, db, data.get('clan_tag'))
        members = {row['tag']: row for row in roster['members']}
        absent = [value for value in selected if value not in members]
        if absent:
            raise web.HTTPConflict(text='Some selected accounts left this clan. Refresh the list and try again.')
        existing = await db.strike_profiles.find(
            {'guild_id': GUILD_ID, 'player_tag': {'$in': selected}}).to_list(length=None)
        already = {row['player_tag'] for row in existing
                   if (row.get('replacement_listed') and row.get('replacement_clan_tag') == roster['tag'])
                   or (row.get('filler') and row.get('filler_clan_tag') == roster['tag'])}
        ledger = await service(request, db)
        added, skipped = [], [value for value in selected if value in already]
        try:
            for value in selected:
                if value in already:
                    continue
                result = await ledger.set_replacement_preference(
                    GUILD_ID, value, priority, note, actor, clan_tag=roster['tag'],
                    player_name=members[value]['name'],
                    town_hall=members[value].get('town_hall'), only_if_unmarked=True)
                (added if result is not None else skipped).append(value)
        except Exception:
            _job_log.exception('Replacement bulk add stopped after partial write')
            return web.json_response({'clan_tag': roster['tag'], 'added': added, 'skipped': skipped,
                'added_count': len(added), 'skipped_count': len(skipped),
                'error': 'Bulk add stopped. Retry to finish; saved choices will be skipped.'}, status=503)
    return web.json_response({'clan_tag': roster['tag'], 'added': added, 'skipped': skipped,
                              'added_count': len(added), 'skipped_count': len(skipped)})


@endpoint
async def replacement_preference(request):
    player = tag(request.match_info['player_tag'])
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        return web.json_response(await ledger.replacement_preference(GUILD_ID, player))


@endpoint
async def add_replacement_list(request):
    data = await body(request, {'player_tag', 'priority', 'note', 'revision'})
    if 'player_tag' not in data:
        raise ValueError('Choose a player account.')
    revision = number(data.get('revision'), 0, 2**53 - 1)
    profile = await _verified_replacement_player(request, data['player_tag'])
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        saved = await ledger.set_replacement_preference(
            GUILD_ID, profile['tag'], data.get('priority'), data.get('note', ''),
            int(_session(request)['user_id']), clan_tag=profile['current_clan_tag'],
            player_name=profile.get('name'), town_hall=profile.get('town_hall'), expected_revision=revision)
    return web.json_response({'ok': True, 'player_tag': saved['player_tag'],
                              'priority': saved['replacement_priority'],
                              'clan_tag': saved['replacement_clan_tag'], 'revision': saved['revision']})


@endpoint
async def update_replacement_list(request):
    data = await body(request, {'priority', 'note', 'revision'})
    revision = number(data.get('revision'), 0, 2**53 - 1)
    profile = await _verified_replacement_player(request, request.match_info['player_tag'])
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        saved = await ledger.set_replacement_preference(
            GUILD_ID, profile['tag'], data.get('priority'), data.get('note', ''),
            int(_session(request)['user_id']), clan_tag=profile['current_clan_tag'],
            player_name=profile.get('name'), town_hall=profile.get('town_hall'), expected_revision=revision)
    return web.json_response({'ok': True, 'player_tag': saved['player_tag'],
                              'priority': saved['replacement_priority'],
                              'clan_tag': saved['replacement_clan_tag'], 'revision': saved['revision']})


@endpoint
async def delete_replacement_list(request):
    data = await body(request, {'revision'})
    revision = number(data.get('revision'), 0, 2**53 - 1)
    player = tag(request.match_info['player_tag'])
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        saved = await ledger.clear_replacement_preference(GUILD_ID, player, int(_session(request)['user_id']),
                                                           expected_revision=revision)
    return web.json_response({'ok': True, 'revision': saved['revision']})




JOB_TTL_SECONDS = 60 * 60
JOB_TIMEOUT_SECONDS = 20 * 60
MAX_JOBS = 200
_job_log = logging.getLogger(__name__)


def _jobs(app):
    state = app.get('strike_import_jobs')
    if state is None:
        state = {'rows': {}, 'tasks': set(), 'lock': asyncio.Lock()}
        app['strike_import_jobs'] = state
    return state


def _prune_jobs(state):
    now = time.monotonic()
    rows = state['rows']
    for key, row in list(rows.items()):
        if row['status'] != 'running' and row['expires_at'] <= now:
            del rows[key]


async def _start_job(app, actor_id, kind, fingerprint, operation):
    state = _jobs(app)
    async with state['lock']:
        _prune_jobs(state)
        for row in state['rows'].values():
            if row['actor_id'] != actor_id or row['kind'] != kind:
                continue
            if row['fingerprint'] == fingerprint and (row['status'] == 'running' or
                    (kind == 'apply' and row['status'] == 'complete')):
                return row
            if row['status'] == 'running':
                raise web.HTTPConflict(text='Another import is running. Wait for it to finish.')
        if len(state['rows']) >= MAX_JOBS:
            raise web.HTTPServiceUnavailable(text='Import jobs are busy. Try again later.')
        job_id = uuid.uuid4().hex
        row = {'job_id': job_id, 'actor_id': actor_id, 'kind': kind,
               'fingerprint': fingerprint, 'status': 'running',
               'created_at': time.monotonic(),
               'expires_at': time.monotonic() + JOB_TIMEOUT_SECONDS + JOB_TTL_SECONDS}
        state['rows'][job_id] = row
        task = asyncio.create_task(_run_job(row, operation), name=f'strike-import-{kind}-{job_id[:8]}')
        state['tasks'].add(task)
        task.add_done_callback(state['tasks'].discard)
        return row


async def _run_job(row, operation):
    try:
        row['result'] = await asyncio.wait_for(operation(), timeout=JOB_TIMEOUT_SECONDS)
        row['status'] = 'complete'
    except asyncio.CancelledError:
        row['status'] = 'failed'
        row['error'] = 'Import stopped. You can retry from the dashboard.'
        raise
    except asyncio.TimeoutError:
        row['status'] = 'failed'
        row['error'] = 'Import took too long. Try again; existing records will not be duplicated.'
    except (ValueError, RuntimeError, ProviderUnavailable) as error:
        row['status'] = 'failed'
        row['error'] = str(error)[:240]
    except Exception:
        _job_log.exception('Strike import %s job failed', row['kind'])
        row['status'] = 'failed'
        row['error'] = 'Import could not complete. Try again; existing records will not be duplicated.'
    finally:
        row['expires_at'] = time.monotonic() + JOB_TTL_SECONDS


async def strike_jobs_lifecycle(app):
    state = _jobs(app)
    try:
        yield
    finally:
        tasks = list(state['tasks'])
        for row in state['rows'].values():
            if row['status'] == 'running':
                row['status'] = 'failed'
                row['error'] = 'Import stopped. You can retry from the dashboard.'
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
            except asyncio.TimeoutError:
                pass
        state['rows'].clear()


async def _preview_work(app, actor_id, days, actor=None):
    from utils.strike_wars import fetch_history_report
    background = SimpleNamespace(app=app)
    async with shared.mongo(background) as db:
        if actor is not None and not await shared.allowed(actor, 'strikes_add', db, write=True):
            raise ValueError('Strike access changed. Start again from the dashboard.')
        ledger = await service(background, db)
        clans = await clan_rows(db)
        semaphore = asyncio.Semaphore(6)
        async def fetch(clan):
            async with semaphore:
                try:
                    report = await fetch_history_report(clan['tag'], days=days)
                    ends = sorted(public(row['end_time']) for row in
                                  report['wars'] + report.get('cwl_wars', []))
                    return report['wars'], report.get('cwl_wars', []), {'clan_tag': clan['tag'], 'clan_name': clan['name'],
                        'wars': len(report['wars']) + len(report.get('cwl_wars', [])),
                        'regular_wars': len(report['wars']), 'cwl_wars': len(report.get('cwl_wars', [])),
                        'earliest': ends[0] if ends else None, 'latest': ends[-1] if ends else None,
                        'skipped': len(report['skipped']), 'source_count': report['source_count']}
                except (RuntimeError, ProviderUnavailable, ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                    return [], [], {'clan_tag': clan['tag'], 'clan_name': clan['name'], 'wars': 0,
                                    'regular_wars': 0, 'cwl_wars': 0, 'skipped': 0, 'source_count': 0,
                                    'error': 'War history unavailable'}
        reports = await asyncio.gather(*(fetch(clan) for clan in clans))
        wars = [war for found, _cwl, _coverage in reports for war in found]
        cwl_wars = [war for _regular, found, _coverage in reports for war in found]
        coverage = [item for _regular, _cwl, item in reports]
        result = await ledger.preview_import(GUILD_ID, wars, actor_id, cwl_wars=cwl_wars)
        names = {row['tag']: row['name'] for row in clans}
        entries = [{'key': row['_id'], 'player_tag': row['player_tag'], 'player_name': row.get('player_name') or row['player_tag'],
                    'clan_name': names.get(row.get('clan_tag'), row.get('clan_tag')), 'war_end': public(row['occurred_at']),
                    'missed_attacks': row.get('missed_attacks'),
                    'kind': row.get('kind'), 'source': row.get('source'),
                    'source_label': 'ClashKing (import)',
                    'war_type': row.get('war_type') or 'regular',
                    'attacks_used': row.get('attacks_used'),
                    'discord_id': str(row['member_id']) if row.get('member_id') else None,
                    'link_status': row.get('link_status') or ('linked' if row.get('member_id') else 'unlinked'),
                    'will_strike': row['kind'] == 'strike',
                    'exempt': row['kind'] == 'exempt', 'duplicate': bool(row.get('existing'))}
                   for row in result['items'] if row.get('missed_attacks') or row.get('kind') == 'cwl']
        deferred = result.get('deferred_accounts', [])
        for item in coverage:
            item['deferred_accounts'] = sum(1 for row in deferred if row['clan_tag'] == item['clan_tag'])
            item['processing_skipped_wars'] = sum(1 for row in result.get('skipped', [])
                                                  if row.get('war') == item['clan_tag'])
        return {'preview_id': result['preview_id'], 'summary': result['summary'], 'wars_scanned': sum(item['source_count'] for item in coverage),
                'complete_wars': result['wars'] + result.get('cwl_wars', 0),
                'regular_wars': result['wars'], 'cwl_wars': result.get('cwl_wars', 0),
                'cwl_records': result.get('cwl_records', 0), 'cwl_missed': result.get('cwl_missed', 0),
                'incomplete_wars': len(result.get('skipped', [])) + sum(item['skipped'] for item in coverage), 'entries': entries, 'coverage': coverage,
                'existing': result.get('existing', 0), 'deferred_accounts': public(deferred),
                'deferred_count': len(deferred), 'skipped_war_details': result.get('skipped', [])}


async def _apply_work(app, actor_id, preview_id, exclusions, actor=None):
    background = SimpleNamespace(app=app)
    async with shared.mongo(background) as db:
        if actor is not None and not await shared.allowed(actor, 'strikes_add', db, write=True):
            raise ValueError('Strike access changed. Start again from the dashboard.')
        ledger = await service(background, db)
        result = await ledger.apply_import(GUILD_ID, preview_id, actor_id, excluded_keys=exclusions)
    return {'applied': result['applied'], 'strikes': result.get('strikes', 0),
            'added_strikes': result['added_strikes'], 'history_only': result['history_only'],
            'duplicates': result['duplicates'], 'excluded': result.get('excluded', 0),
            'cwl_wars': result.get('cwl_wars', 0), 'cwl_records': result.get('cwl_records', 0),
            'cwl_missed': result.get('cwl_missed', 0),
            'skipped': result.get('excluded', 0) + result.get('existing', 0),
            'skipped_wars': len(result.get('skipped', [])),
            'deferred_accounts': public(result.get('deferred_accounts', [])),
            'deferred_count': len(result.get('deferred_accounts', [])),
            'skipped_war_details': result.get('skipped', [])}


@endpoint(scope='strikes_add')
async def import_preview(request):
    data = await body(request, {'days'})
    days = number(data.get('days', 60), 1, 60)
    from .app import _session
    actor_id = int(_session(request)['user_id'])
    actor = getattr(request, 'get', lambda *_: None)('manage_identity')
    actor = dict(actor) if actor is not None else None
    app = request.app
    row = await _start_job(app, actor_id, 'preview', str(days),
                           lambda: _preview_work(app, actor_id, days, actor))
    return web.json_response({'job_id': row['job_id'], 'status': row['status']}, status=202)


@endpoint(scope='strikes_add')
async def import_apply(request):
    data = await body(request, {'preview_id', 'excluded_keys'})
    preview_id = data.get('preview_id')
    exclusions = data.get('excluded_keys', [])
    if not isinstance(preview_id, str) or not 1 <= len(preview_id) <= 160:
        raise ValueError('Create an import preview first.')
    if not isinstance(exclusions, list) or len(exclusions) > 10000 or any(not isinstance(value, str) or len(value) > 250 for value in exclusions):
        raise ValueError('Invalid import selection.')
    from .app import _session
    actor_id = int(_session(request)['user_id'])
    actor = getattr(request, 'get', lambda *_: None)('manage_identity')
    actor = dict(actor) if actor is not None else None
    exclusions = sorted(set(exclusions))
    fingerprint = preview_id + ':' + '|'.join(exclusions)
    app = request.app
    row = await _start_job(app, actor_id, 'apply', fingerprint,
                           lambda: _apply_work(app, actor_id, preview_id, exclusions, actor))
    return web.json_response({'job_id': row['job_id'], 'status': row['status']}, status=202)


@endpoint(scope='strikes_add')
async def import_job(request):
    from .app import _session
    actor_id = int(_session(request)['user_id'])
    state = _jobs(request.app)
    async with state['lock']:
        _prune_jobs(state)
        row = state['rows'].get(request.match_info['job_id'])
        if row is None or row['actor_id'] != actor_id:
            raise web.HTTPNotFound(text='Import job not found. Start a new preview if the server restarted.')
        response = {'job_id': row['job_id'], 'status': row['status']}
        if row['status'] == 'complete':
            response['result'] = row['result']
        elif row['status'] == 'failed':
            response['error'] = row.get('error', 'Import failed.')
    return web.json_response(response)


@endpoint
async def tracking_status(request):
    async with shared.mongo(request) as db:
        clans = await clan_rows(db)
        rows = await StrikeTracking(db).rows(GUILD_ID, clans)
    summary = {key: sum(row['status'] == key for row in rows)
               for key in ('healthy', 'behind', 'private', 'error')}
    return web.json_response({'clans': public(rows),
                              'summary': {**summary, 'total': len(rows)}})


@endpoint(scope='strikes_add')
async def tracking_retry(request):
    data = await body(request, {'clan_tag'})
    clan_tag = tag(data.get('clan_tag'))
    actor = await shared.identity(request)
    async with shared.mongo(request) as db:
        registered = await db.clans.find_one({'tag': clan_tag}, {'tag': 1})
        if registered is None:
            raise ValueError('Choose a registered family clan.')
        row = await StrikeTracking(db).queue_retry(GUILD_ID, clan_tag, int(actor['user_id']))
    return web.json_response({'clan_tag': clan_tag, 'retry_pending': True,
                              'retry_requested_at': public(row['retry_requested_at'])}, status=202)


@endpoint(scope='strikes')
async def tracking_resolve(request):
    data = await body(request, {'war_key', 'revision', 'reason'})
    actor = await shared.identity(request)
    async with shared.mongo(request) as db:
        receipt = await StrikeTracking(db).resolve_review(GUILD_ID, data.get('war_key'),
            data.get('revision'), data.get('reason'), int(actor['user_id']))
    return web.json_response(public({'resolved': True, 'receipt': receipt}))


routes = [web.get(API + '/tracking', tracking_status),
          web.post(API + '/tracking/retry', tracking_retry),
          web.post(API + '/tracking/resolve', tracking_resolve),
          web.get(API + '/overview', overview), web.get(API + '/accounts', accounts),
          web.get(API + '/wars', wars),
          web.get(API + '/members', members), web.get(API + '/targets', targets),
          web.get(API + '/members/{member_id}/accounts', member_accounts),
          web.post(API + '/manual', manual), web.post(API + '/{strike_id}/remove', remove),
          web.get(API + '/settings', settings), web.put(API + '/settings/roles', save_roles),
          web.get(API + '/settings/leaves/{member_id}', leave_state),
          web.post(API + '/settings/leaves', save_leave), web.delete(API + '/settings/leaves/{member_id}', remove_leave),
          web.get(API + '/replacements', replacements),
          web.get(API + '/replacement-roster', replacement_roster),
          web.get(API + '/replacement-list/{player_tag}', replacement_preference),
          web.post(API + '/replacement-list/bulk', bulk_add_replacement_list),
          web.post(API + '/replacement-list', add_replacement_list),
          web.put(API + '/replacement-list/{player_tag}', update_replacement_list),
          web.delete(API + '/replacement-list/{player_tag}', delete_replacement_list),
          web.post(API + '/import/preview', import_preview), web.post(API + '/import/apply', import_apply),
          web.get(API + '/import/jobs/{job_id}', import_job)]
