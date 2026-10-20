"""Authenticated dashboard for the same account ledger used by Discord."""
from __future__ import annotations

import asyncio
import aiohttp
from datetime import datetime, timezone
from functools import wraps
import re

from aiohttp import web

from . import server_management as shared
from .providers import ProviderUnavailable, tag
from utils import recruit_links
from utils.strike_store import StrikeService, utc

API = '/api/cwl/strikes'
GUILD_ID = shared.GUILD_ID


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
        except RuntimeError as exc:
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
                role_cache[member_id] = None
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
    tags = list(links.sources)
    sem = asyncio.Semaphore(6)

    async def account(value):
        async with sem:
            return await request.app['providers'].player(value)
    rows = await asyncio.gather(*(account(value) for value in tags))
    return [{'tag': row['tag'], 'name': row['name'],
             'current_clan_tag': row.get('current_clan_tag'),
             'current_clan_name': row.get('current_clan_name')} for row in rows]


def display_member(row):
    user = row.get('user') or {}
    return {'id': str(user['id']), 'name': row.get('nick') or user.get('global_name') or user.get('username') or str(user['id']), 'accounts': []}


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
            'discord_name': None, 'current_clan_tag': current_tag,
            'current_clan_name': profile.get('current_clan_name') or clans.get(current_tag),
            'war_clan_tag': row.get('clan_tag'), 'war_clan_name': row.get('clan_name') or clans.get(row.get('clan_tag')),
            'war_end': public(row['occurred_at']), 'expires_at': public(row.get('expires_at')),
            'kind': 'strike' if kind == 'strike' else ('completed' if kind == 'completed' else 'miss'), 'source': row.get('source'),
            'status': 'recorded' if row.get('status') == 'missed' else row.get('status'),
            'missed_attacks': row.get('missed_attacks'), 'reason': row.get('reason'),
            'exemption': row.get('exemption'), 'removed_reason': row.get('revoke_reason')}


@endpoint
async def overview(request):
    query = request.query.get('query', '').strip()
    if len(query) > 80:
        raise ValueError('Use a shorter name or tag.')
    status = request.query.get('status') or None
    if status in ('all', ''):
        status = None
    if status not in (None, 'active', 'expired', 'removed', 'exempt', 'recorded'):
        raise ValueError('Choose a history status.')
    if status == 'recorded':
        status = 'missed'
    clan = request.query.get('clan') or None
    limit = number(request.query.get('limit', '25'))
    offset = number(request.query.get('offset', '0'), 0, 100000)
    args = {'status': status, 'clan_tag': clan, 'limit': limit, 'skip': offset}
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
        return web.json_response({'entries': [entry(row, names, by_tag.get(row['player_tag'])) for row in data['items']],
                                  'clans': clans, 'members': [], 'total': data['total'], 'limit': limit, 'offset': offset})


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
    roles = [{'id': str(row['id']), 'name': row['name']} for row in actor['roles'] if str(row['id']) != str(GUILD_ID)]
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
                       'player_tags': row.get('account_tags') or [], 'resume_date': utc(row['until']).date().isoformat()})
    return web.json_response({'excluded_roles': [{'id': str(value), 'name': role_names.get(str(value), f'Role {value}')} for value in config['exempt_role_ids']],
                              'roles': roles, 'leaves': result})


@endpoint
async def save_roles(request):
    data = await body(request, {'role_ids'})
    roles = data.get('role_ids')
    if not isinstance(roles, list) or len(roles) > 100:
        raise ValueError('Choose up to 100 roles.')
    roles = [uid(value) for value in roles]
    actor = await shared.identity(request)
    known = {str(row['id']) for row in actor['roles'] if str(row['id']) != str(GUILD_ID)}
    if set(roles) - known:
        raise ValueError('A selected role no longer exists. Refresh the role list.')
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        await ledger.set_exempt_roles(GUILD_ID, roles, int(actor['user_id']))
    return web.json_response({'ok': True})


@endpoint
async def save_leave(request):
    data = await body(request, {'discord_id', 'player_tags', 'resume_date'})
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
        await ledger.set_leave(GUILD_ID, int(member_id), data['resume_date'], int(_session(request)['user_id']), account_tags=values)
    return web.json_response({'ok': True})


@endpoint
async def remove_leave(request):
    member_id = uid(request.match_info['member_id'])
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        await ledger.clear_leave(GUILD_ID, int(member_id))
    return web.json_response({'ok': True})


@endpoint
async def replacements(request):
    weight = number(request.query.get('weight'), 1, 1000000000)
    clan = request.query.get('clan') or None
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        clans = await clan_rows(db)
        # Profiles are refreshed by the background scanner. Refresh weight values
        # using the same shared feed and manual overrides as the roster dashboard.
        fwa_tags = [row['tag'] for row in clans if row['is_fwa']]
        profiles = await db.strike_profiles.find({'guild_id': GUILD_ID, 'current_clan_tag': {'$in': fwa_tags}}).to_list(length=None)
        tags = [row['player_tag'] for row in profiles]
        weights = await request.app['providers'].weights(tags)
        from .app import _store
        effective_weights = {}
        for value in tags:
            manual_weight = _store(request).one('SELECT weight FROM player_weights WHERE tag=?', (value,))
            found = manual_weight['weight'] if manual_weight and manual_weight['weight'] is not None else (weights.get(value) or {}).get('weight')
            effective_weights[value] = found
        rows = await ledger.replacement(GUILD_ID, weight, clan_tag=clan, limit=100, weights=effective_weights)
        names = {row['tag']: row['name'] for row in clans}
        return web.json_response({'candidates': [{'player_tag': row['player_tag'], 'player_name': row.get('player_name') or row['player_tag'],
               'clan_tag': row.get('current_clan_tag'), 'clan_name': names.get(row.get('current_clan_tag'), row.get('current_clan_tag')),
               'weight': row.get('weight'), 'active_strikes': row['active_strikes'], 'is_filler': bool(row.get('filler')),
               'weight_difference': row['weight_difference'], 'discord_id': str(row['member_id']) if row.get('member_id') else None} for row in rows]})


@endpoint
async def save_filler(request):
    data = await body(request, {'is_filler'})
    if type(data.get('is_filler')) is not bool:
        raise ValueError('Choose a replacement preference.')
    player = tag(request.match_info['player_tag'])
    from .app import _session
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        profile = await db.strike_profiles.find_one({'_id': f'{GUILD_ID}:{player}'})
        if not profile or not profile.get('current_clan_tag'):
            raise ValueError('Refresh the replacement list before choosing this account.')
        await ledger.set_filler(GUILD_ID, player, data['is_filler'], int(_session(request)['user_id']), clan_tag=profile['current_clan_tag'])
    return web.json_response({'ok': True})


@endpoint(scope='strikes_add')
async def import_preview(request):
    data = await body(request, {'days'})
    days = number(data.get('days', 90), 1, 90)
    from .app import _session
    from utils.strike_wars import fetch_history_report
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        clans = await clan_rows(db)
        semaphore = asyncio.Semaphore(6)
        async def fetch(clan):
            async with semaphore:
                try:
                    report = await fetch_history_report(clan['tag'], days=days)
                    ends = sorted(public(row['end_time']) for row in report['wars'])
                    return report['wars'], {'clan_name': clan['name'], 'wars': len(report['wars']),
                        'earliest': ends[0] if ends else None, 'latest': ends[-1] if ends else None,
                        'skipped': len(report['skipped']), 'source_count': report['source_count']}
                except (RuntimeError, ProviderUnavailable, ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                    return [], {'clan_name': clan['name'], 'wars': 0, 'skipped': 0,
                                'source_count': 0, 'error': 'War history unavailable'}
        reports = await asyncio.gather(*(fetch(clan) for clan in clans))
        wars = [war for found, _coverage in reports for war in found]
        coverage = [item for _found, item in reports]
        result = await ledger.preview_import(GUILD_ID, wars, int(_session(request)['user_id']))
        names = {row['tag']: row['name'] for row in clans}
        entries = [{'key': row['_id'], 'player_tag': row['player_tag'], 'player_name': row.get('player_name') or row['player_tag'],
                    'clan_name': names.get(row.get('clan_tag'), row.get('clan_tag')), 'war_end': public(row['occurred_at']),
                    'missed_attacks': row.get('missed_attacks'), 'will_strike': row['kind'] == 'strike',
                    'exempt': row['kind'] == 'exempt', 'duplicate': bool(row.get('existing'))} for row in result['items'] if row.get('missed_attacks')]
        return web.json_response({'preview_id': result['preview_id'], 'wars_scanned': sum(item['source_count'] for item in coverage), 'complete_wars': result['wars'],
                                  'incomplete_wars': len(result.get('skipped', [])) + sum(item['skipped'] for item in coverage), 'entries': entries, 'coverage': coverage,
                                  'existing': result.get('existing', 0)})


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
    async with shared.mongo(request) as db:
        ledger = await service(request, db)
        result = await ledger.apply_import(GUILD_ID, preview_id, int(_session(request)['user_id']), excluded_keys=exclusions)
    return web.json_response({'applied': result['applied'], 'strikes': result.get('strikes', 0),
                              'skipped': result.get('excluded', 0) + result.get('existing', 0),
                              'skipped_wars': len(result.get('skipped', []))})


routes = [web.get(API + '/overview', overview), web.get(API + '/members', members),
          web.get(API + '/members/{member_id}/accounts', member_accounts),
          web.post(API + '/manual', manual), web.post(API + '/{strike_id}/remove', remove),
          web.get(API + '/settings', settings), web.put(API + '/settings/roles', save_roles),
          web.post(API + '/settings/leaves', save_leave), web.delete(API + '/settings/leaves/{member_id}', remove_leave),
          web.get(API + '/replacements', replacements), web.put(API + '/replacements/{player_tag}', save_filler),
          web.post(API + '/import/preview', import_preview), web.post(API + '/import/apply', import_apply)]
