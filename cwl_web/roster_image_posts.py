"""Staff authorization and HTTP adaptation for roster image delivery."""
import re
from aiohttp import web
from utils.cwl_roster_image_store import RosterImageStore
from .server_management import discord, GUILD_ID


def staff(request, *, send=False):
    from .app import _require, _owner
    from .access_control import request_scopes
    actor = _require(request, 'editor')
    if send and not _owner(actor) and 'cwl_send' not in request_scopes(request, actor['user_id']):
        raise web.HTTPForbidden(text='You do not have permission for this CWL action.')
    return actor


def store(request):
    return RosterImageStore(request.app['store'])


async def channels(request):
    staff(request, send=True)
    return web.json_response({'channels': store(request).channels()})


async def configure(request):
    from .app import _json
    actor = staff(request, send=True)
    body = await _json(request)
    if set(body) != {'pool', 'channel_id'} or body.get('pool') not in ('main', 'lazy'):
        raise web.HTTPBadRequest(text='Choose Main or Lazy and a text channel.')
    channel = body['channel_id']
    if not isinstance(channel, str) or not re.fullmatch(r'\d{15,22}', channel):
        raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    destination = await discord(request, 'GET', f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    return web.json_response(store(request).configure(body['pool'], channel, str(destination.get('name') or channel), actor['user_id']))


async def posts(request):
    from .app import _sid, _season
    staff(request)
    sid = _sid(request)
    with request.app['store'].tx() as db:
        _season(db, sid)
    storage = store(request)
    result = storage.posts(sid)
    publication = storage.publication(sid)
    result['clans'] = [] if publication is None else [{k: v for k, v in group.items() if k != 'accounts'} | {'count': len(group['accounts']), 'pages': (len(group['accounts']) + 14) // 15} for group in groups_for(publication)[2].values()]
    return web.json_response(result)


def routes():
    return [web.get('/api/cwl/roster-image-channels', channels),
            web.put('/api/cwl/roster-image-channels', configure),
            web.get('/api/cwl/seasons/{season_id}/roster-image-posts', posts),
            web.post('/api/cwl/seasons/{season_id}/roster-image-posts/{tag}', deliver),
            web.post('/api/cwl/seasons/{season_id}/roster-image-posts/{tag}/{operation}', deliver)]


def public_receipt(receipt):
    keys = ('request_id', 'operation', 'season_id', 'pool', 'clan_tag', 'channel_id', 'message_id', 'status', 'error', 'posted_version', 'target_version', 'posted_at')
    return {key: receipt.get(key) for key in keys}


def delivery_response(receipt):
    status = receipt['status']
    if receipt.get('retry_after') is not None:
        return web.json_response({'retry_after': receipt['retry_after'], 'error': 'Discord rate limit'}, status=429)
    code = 200 if status in ('posted', 'dropped') else 409 if status == 'sending' else 503 if status == 'uncertain' else 400
    return web.json_response({'post': public_receipt(receipt), 'error': receipt.get('error') or ('Another post for this clan is in progress' if status == 'sending' else None)}, status=code)


def groups_for(publication):
    season, pub, accounts = publication
    import json
    clans = {c['tag']: c for c in json.loads(pub['clans_json'])}
    groups = {}
    for account in accounts:
        clan = account['assigned_clan_tag']
        if not clan:
            continue
        group = groups.setdefault(clan, {'tag': clan, 'name': account['assigned_clan_name'] or clan,
            'pool': clans.get(clan, {}).get('pool') or account['pool'],
            'league': clans.get(clan, {}).get('cwl_league') or 'League unavailable', 'accounts': []})
        group['accounts'].append(account)
    return season, pub, groups


async def deliver(request):
    import asyncio
    import json
    import math
    import aiohttp
    from urllib.parse import quote
    from .app import _json, _sid
    from .providers import tag as parse_tag
    from .roster_images import metadata, render
    from .server_management import DiscordDeliveryUncertain
    from utils.cwl_roster_image_store import ImageConflict
    actor = staff(request, send=True)
    body = await _json(request)
    if set(body) != {'pool', 'version', 'request_id'} or body.get('pool') not in ('main', 'lazy'):
        raise web.HTTPBadRequest(text='Choose a pool and published version.')
    version, nonce = body['version'], body['request_id']
    if type(version) is not int or version < 1 or not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{24}', nonce):
        raise web.HTTPBadRequest(text='Invalid version or request ID.')
    sid, pool = _sid(request), body['pool']
    try:
        clan = parse_tag(request.match_info['tag'])
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid clan tag.') from None
    operation = request.match_info.get('operation', 'post')
    if operation not in ('post', 'update', 'drop'):
        raise web.HTTPNotFound()
    storage = store(request)
    old_request = storage.receipt(nonce)
    if old_request:
        if (old_request['season_id'], old_request['pool'], old_request['clan_tag'], old_request['target_version'], old_request['operation']) != (sid, pool, clan, version, operation):
            raise web.HTTPConflict(text='Request ID belongs to a different action')
        return delivery_response(old_request)
    publication = storage.publication(sid)
    if not publication:
        raise web.HTTPConflict(text='Publish the roster before posting images')
    season, pub, groups = groups_for(publication)
    if pub['version'] != version:
        raise web.HTTPConflict(text='A newer roster is published. Refresh before posting images.')
    previous = storage.current(sid, pool, clan)
    if previous and previous['status'] in ('posted', 'dropped') and previous['posted_version'] == version:
        if (operation == 'drop') == (previous['status'] == 'dropped'):
            return delivery_response(previous)
    frozen = None
    if previous and previous['status'] == 'uncertain':
        uncertain = storage.receipt(previous['request_id'])
        if uncertain and uncertain['operation'] != operation:
            raise web.HTTPConflict(text='Retry the uncertain operation explicitly before changing this message.')
    if previous and previous['status'] in ('uncertain', 'failed') and operation != 'post':
        prior = storage.receipt(previous['request_id'])
        if prior and prior['operation'] == operation and prior['target_version'] == version:
            frozen = json.loads(prior['payload_json'])
    if operation == 'drop':
        if clan in groups or not previous or not previous['message_id']:
            raise web.HTTPConflict(text='Only a previously posted clan no longer hosting can be marked dropped.')
        group = {'name': clan, 'tag': clan, 'pool': pool, 'league': '', 'accounts': []}
        if not frozen:
            old = storage.publication(sid, previous['posted_version'])
            if old:
                group = groups_for(old)[2].get(clan, group)
    else:
        group = groups.get(clan)
        if not group or group['pool'] != pool:
            raise web.HTTPBadRequest(text='This clan is not in the published pool.')
    if operation == 'post':
        if previous and previous['message_id'] and previous['status'] == 'posted':
            raise web.HTTPConflict(text='Update the existing posted message instead.')
        channel_row = next((c for c in storage.channels() if c['pool'] == pool), None)
        if not channel_row:
            raise web.HTTPBadRequest(text='Choose an image channel first.')
        channel, message_id = channel_row['channel_id'], None
    else:
        if not previous or not previous['message_id']:
            raise web.HTTPConflict(text='No posted message to edit.')
        channel, message_id = previous['channel_id'], previous['message_id']
    destination = await discord(request, 'GET', f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    if frozen is None:
        if operation != 'drop':
            await metadata(request, group)
        payload = {'content': f"{group['name']} is no longer hosting · Roster v{version}" if operation == 'drop' else f"{group['name']} · {season['label']} · Roster v{version}",
                   'allowed_mentions': {'parse': []}, 'attachments': [], 'components': []}
        if operation != 'drop':
            payload['components'] = [{'type': 1, 'components': [{'type': 2, 'style': 5, 'label': 'Open clan', 'url': f'https://link.clashofclans.com/en?action=OpenClanProfile&tag={quote(clan, safe="")}'}]}]
        frozen = {'payload': payload, 'season_label': season['label'], 'name': group['name'], 'league': group['league']}
    images = []
    if operation != 'drop':
        # Retry inputs come from the receipt and immutable publication rows, never live metadata.
        group = {**group, 'name': frozen['name'], 'league': frozen['league']}
        pages = math.ceil(len(group['accounts']) / 15)
        if pages > 10:
            raise web.HTTPBadRequest(text='This roster is too large to send.')
        images = await asyncio.gather(*(asyncio.to_thread(render, {'label': frozen['season_label']}, pub, group, page) for page in range(1, pages + 1)))
    try:
        receipt, acquired = storage.claim(sid, pool, clan, version, nonce, operation, channel, message_id, frozen, actor['user_id'])
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    if not acquired:
        return delivery_response(receipt)
    payload = dict(frozen['payload'])
    if operation == 'post':
        payload.update(nonce=nonce, enforce_nonce=True)
    payload['attachments'] = [{'id': i, 'filename': f'roster-{clan[1:]}-{i+1}.png'} for i in range(len(images))]
    method = 'POST' if operation == 'post' else 'PATCH'
    path = f'/channels/{channel}/messages' + (f'/{message_id}' if message_id else '')
    try:
        if images:
            form = aiohttp.FormData()
            form.add_field('payload_json', json.dumps(payload))
            for i, png in enumerate(images):
                form.add_field(f'files[{i}]', png, filename=payload['attachments'][i]['filename'], content_type='image/png')
            result = await discord(request, method, path, data=form, roster_delivery=True)
        else:
            result = await discord(request, method, path, json=payload, roster_delivery=True)
        message_id = str((result or {}).get('id') or message_id or '')
        if not re.fullmatch(r'\d{15,22}', message_id):
            raise DiscordDeliveryUncertain('Discord did not return a message ID')
        return delivery_response(storage.finish(receipt, 'dropped' if operation == 'drop' else 'posted', message_id))
    except web.HTTPTooManyRequests as exc:
        wait = float(json.loads(exc.text).get('retry_after', 1))
        storage.finish(receipt, 'failed', error='Discord rate limit', retry_after=wait)
        return web.json_response({'retry_after': wait, 'error': 'Discord rate limit'}, status=429)
    except web.HTTPNotFound:
        return delivery_response(storage.finish(receipt, 'dropped' if operation == 'drop' else 'failed', error='Message was deleted in Discord'))
    except (DiscordDeliveryUncertain, aiohttp.ClientError, TimeoutError, asyncio.CancelledError):
        return delivery_response(storage.finish(receipt, 'uncertain', error='Check Discord: this clan may have posted'))
    except web.HTTPException as exc:
        return delivery_response(storage.finish(receipt, 'failed', error=exc.text))
