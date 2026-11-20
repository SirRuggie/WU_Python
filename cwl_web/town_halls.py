"""Town Hall HTTP adaptation; all registry storage belongs to utils.town_halls."""
import asyncio
from copy import deepcopy
import json
import logging
import re
import time
from uuid import UUID, NAMESPACE_URL, uuid5

from aiohttp import web

from utils import town_halls as registry
from . import server_management as shared
from . import town_hall_bases as bases

API = shared.API + '/town-halls'
PATH = '/manage/town-halls'
LOG = logging.getLogger(__name__)
_MARKUP = re.compile(r'<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,22})>')


def emoji_url(markup, size=64):
    match = _MARKUP.fullmatch(markup or '')
    return (f'https://cdn.discordapp.com/emojis/{match[3]}.{"gif" if match[1] else "webp"}?size={size}'
            if match else None)


def field(key, label, value, kind='text', **kwargs):
    return dict(key=key, label=label, value=value, type=kind, **kwargs)


def document(doc, item=None, *, readonly=False, can_weight=True, can_bases=False):
    """Shape the registry without exposing stored metadata or Discord markup text."""
    result = dict(id='town_halls', label='Town Halls',
                  description='Emoji, weight range and bases for each Town Hall level.',
                  group='Clan resources', revision=doc['revision'], fields=[], readonly=readonly)
    levels = registry.levels(doc)
    lowest = doc['lowest_fwa_town_hall']
    records = [dict(id='add', label='Add Town Hall', endpoint=PATH + '/add', list_role='add'),
               dict(id='settings', label='Lowest FWA Town Hall', endpoint=PATH + '/settings',
                    list_role='setting', value=f'TH{lowest}')]
    for level in levels:
        weight = doc['levels'][str(level)].get('weight')
        meta = (f'{weight["min"] / 1000:g}k – {weight["max"] / 1000:g}k' if weight else 'No weight range')
        records.append(dict(id=str(level), label=f'Town Hall {level}', endpoint=f'{PATH}/{level}',
                            list_role='level', list_group='fwa' if level >= lowest else 'other',
                            meta=meta, emoji_url=emoji_url(registry.emoji_markup(doc, level))))
    if not can_weight:
        records = [record for record in records if record.get('list_role') != 'add' and record.get('list_group') != 'other']
        records[0]['readonly'] = True
        records[0].pop('endpoint', None)
    for record in records:
        if record.get('list_group') == 'fwa':
            stored = doc['levels'][record['id']].get('bases', {})
            level = int(record['id'])
            if level < registry.MERGED_DEFENSES_FROM:
                record['bases_meta'] = 'Shown to members' if stored.get('merged', {}).get('link') else 'Hidden from members'
            else:
                shown = [registry.variant_label(level, key) for key in ('merged', 'non_merged') if stored.get(key, {}).get('link')]
                record['bases_meta'] = ' · '.join(shown) or 'Hidden from members'
    result['documents'] = records
    if item is None:
        return result
    result['endpoint'] = PATH + '/' + item
    if item in ('settings', 'add') and not can_weight:
        raise web.HTTPForbidden(text='Only server admins can change Town Hall settings.')
    if item == 'settings':
        result['label'] = 'Lowest FWA Town Hall'
        result['fields'] = [field('lowest_fwa_town_hall', 'Lowest FWA Town Hall', lowest, 'select',
                                  required=True, options=[dict(value=str(level), label=f'TH{level}') for level in levels
                                           if 'weight' in doc['levels'][str(level)]])]
        return result
    if item == 'add':
        result.update(label='Add Town Hall', create=True, submit_label='Add Town Hall')
        result['fields'] = [field('level', 'Town Hall level', min(99, max(levels) + 1), 'number', min=1, max=99, required=True),
                            field('emoji', 'Town Hall emoji', '', 'emoji', options_endpoint='/manage/town-halls/emojis')]
        return result
    if re.fullmatch(r'[1-9][0-9]?', item) is None or item not in doc['levels']:
        raise web.HTTPNotFound(text='This Town Hall is not in the list.')
    level = int(item)
    if level < lowest and not can_weight:
        raise web.HTTPNotFound(text='This Town Hall is not available for bases.')
    result.update(label=f'Town Hall {level}', level=level, emoji_url=emoji_url(registry.emoji_markup(doc, level)),
                  lowest_fwa_town_hall=lowest)
    result['fields'] = [field('emoji', 'Town Hall emoji', registry.emoji_markup(doc, level), 'emoji',
                              options_endpoint='/manage/town-halls/emojis', group='Town Hall')]
    if level >= lowest:
        weight = doc['levels'][item].get('weight', {})
        result['fields'] += [field(key, label, weight.get(key), 'number', min=1, max=500000, group='Town Hall')
                             for key, label in [('min', 'Minimum weight'), ('max', 'Maximum weight')]]
        if not weight:
            result['warning'] = 'Add a weight range to use this level for FWA.'
    else:
        result['help'] = f'Weights and bases are for TH{lowest} and up.'
    for entry in result['fields']:
        entry['readonly'] = not can_weight
    if not can_weight and (not can_bases or doc['schema_version'] != 2):
        result['readonly'] = True
    if level >= lowest and doc['schema_version'] == 2:
        bases.decorate(result, doc, level, can_weight=can_weight, can_bases=can_bases)
    return result


async def required(db):
    doc = await registry.load(db, shared.GUILD_ID)
    if doc is None:
        raise web.HTTPServiceUnavailable(text=registry.MISSING_MESSAGE)
    return doc


async def read(request):
    actor = await shared.require_manage(request, 'town_halls')
    async with shared.mongo(request) as db:
        doc = await required(db)
        can_weight, can_bases = await bases.permissions(actor, db)
    return web.json_response(document(doc, request.match_info.get('item'),
                                      readonly=not (can_weight or can_bases),
                                      can_weight=can_weight, can_bases=can_bases))


class RefreshRequest:
    """Use the existing queue owner with an immutable revision-based operation ID."""
    def __init__(self, original, revision):
        self.original = original
        self.revision = revision
    def __getattr__(self, key):
        return getattr(self.original, key)
    def __contains__(self, key):
        return key in self.original
    def __getitem__(self, key):
        return self.original[key]
    def __setitem__(self, key, value):
        self.original[key] = value
    async def json(self):
        return {'request_id': str(uuid5(NAMESPACE_URL, f'wu-town-halls:{shared.GUILD_ID}:{self.revision}'))}


async def save(request):
    from .app import _json
    from . import change_history
    actor = await shared.require_manage(request, 'town_halls', write=True)
    body = await _json(request)
    item = request.match_info.get('item')
    if not isinstance(body, dict) or type(body.get('revision')) is not int or not isinstance(body.get('values'), dict):
        raise web.HTTPBadRequest(text='Review the Town Hall fields before saving.')
    if body.get('request_id') is not None:
        try:
            UUID(body['request_id'])
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text='Invalid action identifier. Reload and try again.') from None
    try:
        async with shared.mongo(request) as db:
            current = await required(db)
            can_weight, can_bases = await bases.permissions(actor, db)
            before = document(current, item, can_weight=can_weight, can_bases=can_bases)
            values = body['values']
            if can_bases and before.get('partial_save'):
                for key in values:
                    if key.startswith(bases.PREFIX):
                        registry.validate_base_path(int(item), key[len(bases.PREFIX):])
            allowed = {entry['key'] for entry in before['fields'] if not entry.get('readonly')}
            if not values or not set(values) <= allowed:
                raise web.HTTPForbidden(text='You cannot change these Town Hall fields.')
            if not before.get('partial_save') and set(values) != allowed:
                raise ValueError('Review all fields on this page before saving.')
            base_values = {key[len(bases.PREFIX):]: value for key, value in values.items() if key.startswith(bases.PREFIX)}
            admin_values = {key: value for key, value in values.items() if not key.startswith(bases.PREFIX)}
            if admin_values and not can_weight or base_values and not can_bases:
                raise web.HTTPForbidden(text='You cannot change these Town Hall fields.')
            originals = body.get('originals', {})
            if not isinstance(originals, dict) or set(originals) != {bases.PREFIX + key for key in base_values}:
                raise ValueError('Review the original base values before saving.')
            base_originals = {key: originals[bases.PREFIX + key] for key in base_values}
            restore = getattr(request, 'history_base_restore', None)
            if restore is not None and getattr(request, 'history_action', None) != 'restore':
                raise ValueError('Review the saved base version before restoring.')
            if admin_values and current.get('nonbase_revision', current['revision']) > body['revision']:
                raise registry.TownHallsConflict(registry.CONFLICT_MESSAGE)
            if item == 'add':
                updated = registry.add_level(current, values['level'], values['emoji'])
                destination = str(values['level'])
            elif item == 'settings':
                updated = registry.set_lowest_fwa(current, values['lowest_fwa_town_hall'])
                destination = item
            elif item and re.fullmatch(r'[1-9][0-9]?', item):
                updated = deepcopy(current)
                if 'emoji' in admin_values:
                    updated['levels'][item]['emoji'] = values['emoji']
                if {'min', 'max'} & set(admin_values):
                    old_weight = updated['levels'][item].get('weight', {})
                    minimum = values.get('min', old_weight.get('min'))
                    maximum = values.get('max', old_weight.get('max'))
                    updated = registry.set_weight(updated, int(item), minimum, maximum)
                destination = item
            else:
                raise ValueError('Open a Town Hall or setting before saving.')
            if admin_values:
                updated['revision'] = body['revision']
                saved = await registry.save(db, shared.GUILD_ID, updated, int(actor['user_id']), body['revision'],
                                            **({'base_level': int(item), 'base_values': base_values, 'base_originals': base_originals, **({'base_restore': restore} if restore is not None else {})} if base_values else {}))
            else:
                saved = await registry.save_base_fields(db, shared.GUILD_ID, int(item), base_values, base_originals, int(actor['user_id']), **({'restore': restore} if restore is not None else {}))
            target = '/api/cwl' + PATH + '/' + destination
            if base_values or current['lowest_fwa_town_hall'] != saved['lowest_fwa_town_hall']:
                from .base_bank import invalidate
                invalidate(request.app)
            result = document(saved, destination, can_weight=can_weight, can_bases=can_bases)
            warnings = []
            try:
                history_before = {} if item == 'add' else change_history.fields(before)
                history_after = change_history.fields(result)
                if item == 'add':
                    # Add creates only Town Hall values, never blank base fields.
                    history_after = {entry['key']: entry['value'] for entry in result['fields'] if entry.get('group') == 'Town Hall'}
                    history_after['level'] = int(destination)
                elif before.get('partial_save'):
                    # A concurrent unrelated base/admin edit is not this Save's history.
                    history_before = {key: value for key, value in history_before.items() if key in values}
                    history_after = {key: value for key, value in history_after.items() if key in values}
                await change_history.record_committed(
                    db, target, actor, history_before, history_after,
                    event_id=f'dashboard-history:town-halls:{shared.GUILD_ID}:{saved["revision"]}',
                    action='create' if item == 'add' else getattr(request, 'history_action', 'edit'),
                    raw_before=current, raw_after=saved)
                result['history_saved'] = True
            except Exception:
                LOG.warning('Town Halls revision %s saved but history could not be recorded.', saved['revision'])
                result['history_saved'] = False
    except registry.TownHallsConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    # Save is already committed. Never report a failed enqueue as an unsaved edit.
    try:
        queued = await shared.queue_action(RefreshRequest(request, saved['revision']), 'town_halls', 'refresh', {}, saved['revision'])
        result['refresh'] = json.loads(queued.text)
    except Exception:
        LOG.warning('Town Halls saved but bot refresh could not be queued.')
        warnings.append('Town Halls saved. Bot refresh is pending; the bot checks again within five minutes.')
    request.app.pop('town_halls_member_cache', None)
    result['saved'] = True
    if warnings:
        result['warning'] = ' '.join(warnings)
    return web.json_response(result)


async def member_list(request):
    from .app import _require
    _require(request)
    cached = request.app.get('town_halls_member_cache')
    if cached and time.monotonic() - cached[0] < 60:
        return web.json_response(cached[1])
    async with shared.mongo(request) as db:
        doc = await required(db)
    values = [dict(level=level, emoji_url=emoji_url(registry.emoji_markup(doc, level))) for level in registry.levels(doc)]
    request.app['town_halls_member_cache'] = (time.monotonic(), values)
    return web.json_response(values)


async def emojis(request):
    await shared.require_manage(request, 'fwa_weight')

    async def bot_emojis():
        application = await shared.discord(request, 'GET', '/applications/@me')
        app_id = str(application.get('id', ''))
        if re.fullmatch(r'[0-9]{15,22}', app_id) is None:
            raise ValueError('Invalid application')
        response = await shared.discord(request, 'GET', f'/applications/{app_id}/emojis')
        return response.get('items')

    sources = await asyncio.gather(
        shared.discord(request, 'GET', f'/guilds/{shared.GUILD_ID}/emojis'),
        bot_emojis(), return_exceptions=True)
    result, errors = [], {}
    for source, values in zip(('server', 'bot'), sources):
        if isinstance(values, BaseException) or not isinstance(values, list):
            errors[source] = f'{"Server" if source == "server" else "Bot"} emojis could not load.'
            continue
        for value in values[:500]:
            if not isinstance(value, dict):
                LOG.debug('Skipped malformed Town Hall emoji.')
                continue
            name, identifier = value.get('name'), str(value.get('id', ''))
            markup = f'<{"a" if value.get("animated") is True else ""}:{name}:{identifier}>'
            if not isinstance(name, str) or _MARKUP.fullmatch(markup) is None:
                LOG.debug('Skipped malformed Town Hall emoji.')
                continue
            result.append(dict(value=markup, name=name, source=source, image_url=emoji_url(markup, 48),
                               available=value.get('available', True) is not False))
    if len(errors) == 2:
        raise web.HTTPServiceUnavailable(text='Emojis could not load. Try again.')
    result.sort(key=lambda item: (item['source'] != 'server', item['name'].casefold(), item['value']))
    return web.json_response({'emojis': result, 'errors': errors})


routes = [web.get(API + '/emojis', emojis), web.post(API + '/{item}/upload/{slot}', bases.upload), web.get('/api/cwl/town-halls', member_list),
          web.get(API, read), web.get(API + '/{item}', read), web.patch(API + '/{item}', save)]
