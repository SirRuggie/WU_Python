"""Durable before-images and permission-checked configuration restoration."""
import copy
import re
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import unquote
from aiohttp import web
from .server_management import API, GUILD_ID, mongo, require_manage


def fields(document):
    return {field['key']: copy.deepcopy(field['value']) for field in document.get('fields', []) if not field.get('readonly')}


async def begin(db, target, actor, before, action='edit', raw=None):
    uid=str(actor['user_id'])
    member=actor.get('member', {})
    user=member.get('user', {})
    row={'_id':'dashboard-history:'+uuid4().hex,'revision':0,'kind':'dashboard_history','target':target,
         'status':'pending','actor_id':uid,'actor_name':member.get('nick') or user.get('global_name') or user.get('username') or uid,
         'at':datetime.now(timezone.utc),'action':action,'before':copy.deepcopy(before),'raw_before':copy.deepcopy(raw)}
    # Capture before changing configuration. If history cannot be written, do not edit.
    await db.bot_config.insert_one(row)
    return row['_id']


async def record_committed(db, target, actor, before, after, *, event_id,
                           action='edit', raw_before=None, raw_after=None):
    """Insert one committed-save history entry; a repeated revision is harmless.

    The caller has already committed its revision-checked edit. This owner does
    not retry a failed/uncertain insertion or pretend history is atomic with it.
    """
    from pymongo.errors import DuplicateKeyError
    uid=str(actor['user_id'])
    member=actor.get('member', {})
    user=member.get('user', {})
    row={'_id':event_id,'revision':0,'kind':'dashboard_history','target':target,
         'status':'saved','actor_id':uid,
         'actor_name':member.get('nick') or user.get('global_name') or user.get('username') or uid,
         'at':datetime.now(timezone.utc),'action':action,
         'before':copy.deepcopy(before),'after':copy.deepcopy(after),
         'raw_before':copy.deepcopy(raw_before),'raw_after':copy.deepcopy(raw_after)}
    try:
        await db.bot_config.insert_one(row)
    except DuplicateKeyError:
        pass


async def finish(db, token, after, raw=None):
    result = await db.bot_config.update_one({'_id':token,'revision':0},{'$set':{'status':'saved','after':copy.deepcopy(after),'raw_after':copy.deepcopy(raw)}})
    if not result.matched_count:
        raise RuntimeError('The change history could not be confirmed. Reload the saved settings before trying again.')


class RestoreRequest:
    def __init__(self, original, match_info, body, raw=None):
        self.original=original;self.match_info=match_info;self._body=body;self.method='PATCH'
        self.history_template=raw;self.history_action='restore';self.path=original.query.get('target','')
    def __getattr__(self,key):return getattr(self.original,key)
    def __contains__(self,key):return key in self.original
    def __getitem__(self,key):return self.original[key]
    def __setitem__(self,key,value):self.original[key]=value
    async def json(self):return self._body


def target_info(value):
    if not isinstance(value,str):raise web.HTTPBadRequest(text="Select a message or setting.")
    base='/api/cwl/manage/'
    path=value.removeprefix('/api/cwl')
    if path.startswith('/manage/content/'):
        from .manage_content import descriptor
        key=path.removeprefix('/manage/content/')
        item=descriptor(key)
        return 'content',item['permission'],{'item':key},base+'content/'+key
    match=re.fullmatch(r'/manage/operations/(fwa_weight|fwa_bases|fwa_points|fwa_sync)(?:/([a-zA-Z0-9_-]+))?',path)
    if match and match[2]!='new':
        return 'operations',match[1],{'section':match[1],**({'item':match[2]} if match[2] else {})},base+'operations/'+match[1]+('/'+match[2] if match[2] else '')
    match=re.fullmatch(r'/manage/town-halls/([1-9][0-9]?|settings)',path)
    if match:return 'town_halls','town_halls',{'item':match[1]},base+'town-halls/'+match[1]
    if path.startswith('/manage/text-commands/'):
        from utils.text_commands import command_name
        try: name=command_name(unquote(path.removeprefix('/manage/text-commands/')))
        except ValueError: raise web.HTTPBadRequest(text="Select a valid text command.") from None
        return 'commands','text_commands',{'name':name},base+'text-commands/'+name
    match=re.fullmatch(r'/manage/ticket-settings/(timers|main|fwa|viewers|desk)',path)
    if match:return 'tickets','ticket_settings',{'part':match[1]},base+'ticket-settings/'+match[1]
    raise web.HTTPBadRequest(text='History is not available for this action.')


async def listing(request):
    _,scope,_,target=target_info(request.query.get('target'))
    await require_manage(request,scope)
    async with mongo(request) as db:
        rows=await db.bot_config.find({'kind':'dashboard_history','target':target}).sort('at',-1).limit(30).to_list(length=30)
    result=[]
    for row in rows:
        changed=[key for key in set(row['before'])|set(row.get('after',{})) if row['before'].get(key)!=row.get('after',{}).get(key)]
        result.append(dict(id=row['_id'],actor_id=row['actor_id'],actor_name=row['actor_name'],at=row['at'].replace(tzinfo=timezone.utc).isoformat(),action=row['action'],status=row['status'],changed=sorted(changed),before=row['before'],after=row.get('after',{})))
    return web.json_response({'entries':result})


async def restore(request):
    kind,scope,match,target=target_info(request.query.get('target'))
    await require_manage(request,scope,write=True)
    body=await request.json()
    if not isinstance(body,dict) or body.get('side') not in ('before','after') or not isinstance(body.get('id'),str):
        raise web.HTTPBadRequest(text="Select a saved version.")
    async with mongo(request) as db:
        row=await db.bot_config.find_one({'_id':body['id']})
    if not row or row.get('kind')!='dashboard_history' or row.get('target')!=target or row.get('status')!='saved':
        raise web.HTTPNotFound(text='This saved version is not available.')
    if kind == 'town_halls' and row.get('action') == 'create' and body['side'] == 'before':
        raise web.HTTPConflict(text='A newly created Town Hall has no prior version to restore.')
    values=copy.deepcopy(row[body['side']])
    if kind == 'town_halls' and row.get('action') == 'create' and body['side'] == 'after':
        # Creation records the level as a displayed value; the level is the
        # immutable target, not an editable field on the saved level document.
        if values.get('level') != int(match['item']):
            raise web.HTTPConflict(text='This saved Town Hall version cannot be restored.')
        values.pop('level')
    proxy=RestoreRequest(request,match,{'revision':body.get('revision'),'values':values,**({'request_id':body['request_id']} if body.get('request_id') else {})},row.get('raw_'+body['side']))
    if kind=='town_halls':
        from utils import town_halls as registry
        from .town_halls import save
        base_keys = {key for key in values if key.startswith('bases.')}
        if base_keys:
            async with mongo(request) as db:
                current = await registry.load(db, GUILD_ID)
            if current is None or type(body.get('revision')) is not int or current['revision'] != body['revision']:
                raise web.HTTPConflict(text=registry.CONFLICT_MESSAGE)
            proxy._body['originals'] = {key: registry.base_field_snapshot(current, int(match['item']), key[len('bases.'):]) for key in base_keys}
            target_raw = row.get('raw_' + body['side'])
            opposite_raw = row.get('raw_' + ('after' if body['side'] == 'before' else 'before'))
            if not isinstance(target_raw, dict) or not isinstance(opposite_raw, dict):
                raise web.HTTPConflict(text='This saved base version cannot be restored exactly.')
            try:
                for raw in (target_raw, opposite_raw):
                    registry.validate(raw)
                    if raw.get('_id') != str(GUILD_ID):
                        raise ValueError('Wrong saved server.')
                desired = {key: registry.base_field_snapshot(target_raw, int(match['item']), key[len('bases.'):]) for key in base_keys}
            except ValueError:
                raise web.HTTPConflict(text='This saved base version cannot be restored exactly.') from None
            proxy._body['values'].update({key: value.get('value', '') for key, value in desired.items()})
            proxy.history_base_restore = (target_raw, opposite_raw, body['revision'])
        return await save(proxy)
    if kind=='content':
        from .manage_content import item_handler
        if proxy.history_template is None: raise web.HTTPConflict(text='This version cannot be restored.')
        proxy._body['values']={}
        return await item_handler(proxy)
    if kind=='operations':
        from .manage_operations import save
        return await save(proxy)
    if kind=='commands':
        from .text_commands import save
        from utils.text_commands import collection, GUILD_ID as command_guild_id
        if not values or values.get('command') != match['name']:
            raise web.HTTPBadRequest(text="Select a version containing a command reply.")
        async with mongo(request) as db:
            current = await collection(db).find_one({'_id': f"{command_guild_id}:{match['name']}"})
        if row.get('action') == 'delete' and body['side'] == 'before':
            if current:
                raise web.HTTPConflict(text='This command name is already taken. Edit the existing command instead.')
            proxy.method = 'POST'
        elif current and 'delete_trigger' not in values:
            values['delete_trigger'] = current.get('delete_trigger', True)
        return await save(proxy)
    from .manage_tickets import save
    return await save(proxy)

routes=[web.get(API+'/history',listing),web.post(API+'/history/restore',restore)]
