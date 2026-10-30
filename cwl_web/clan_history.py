"""Staff activity and non-destructive recovery of removed family clans."""
import re
from datetime import timezone
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils.clan_dashboard_history import audit, collection
from utils.mongo import ensure_clan_tag_index
from .server_management import API, GUILD_ID, require_manage, mongo
from .manage_clans import public

LABELS = {'add':'Clan added', 'before_edit':'Before this change',
          'before_remove':'Clan saved before removal', 'before_emoji':'Emoji update requested',
          'before_thread':'Thread update requested', 'before_restore':'Restore requested',
          'restore':'Clan restored', 'reminders':'War reminders changed'}

FIELD_LABELS = {
    'name': 'Name', 'type': 'Clan type', 'th_requirements': 'Minimum Town Hall',
    'leader_id': 'Leader', 'leader_role_id': 'Leader role', 'role_id': 'Clan role',
    'chat_channel_id': 'Chat channel', 'announcement_id': 'Announcement channel',
    'rules_channel_id': 'Rules channel', 'leadership_channel_id': 'Leadership channel',
    'thread_id': 'Thread', 'logo': 'Logo', 'banner': 'Banner', 'profile': 'Profile',
    'emoji': 'Emoji', 'enabled': 'Reminders', 'channel_id': 'Reminder channel',
    'minutes': 'Reminder times', 'war_started': 'War-start message', 'audience': 'Remind who',
}

def history_value(field, value):
    if value is None or value == '':
        return 'Not set'
    if field.endswith('_id'):
        return 'Name not recorded' if value else 'Not set'
    if isinstance(value, bool):
        return 'On' if value else 'Off'
    if field == 'minutes' and isinstance(value, list):
        return ', '.join(f'{minute}m' for minute in value) or 'None'
    if field == 'audience':
        return {'remaining': 'Players with attacks left', 'zero': 'Players with no attacks used'}.get(value, 'Unknown')
    return str(value)

def public_changes(row):
    if not row.get('confirmed'):
        return []
    return [{'field': FIELD_LABELS[item['field']],
             'before': history_value(item['field'], item.get('before')),
             'after': history_value(item['field'], item.get('after'))}
            for item in row.get('changes', []) if item.get('field') in FIELD_LABELS]

async def history(request):
    await require_manage(request, 'clans')
    try:page = max(0, min(10000, int(request.query.get('page', '0'))))
    except ValueError:raise web.HTTPBadRequest(text='Choose a valid history page.') from None
    query = {'guild_id': GUILD_ID}
    term = request.query.get('q', '').strip()[:100]
    if term:query['$or'] = [{key:{'$regex':re.escape(term),'$options':'i'}} for key in ('clan.name','clan.tag')]
    kinds = {'removed': 'before_remove', 'settings': 'before_edit',
             'reminders': 'reminders', 'added': 'add', 'restored': 'restore'}
    kind = request.query.get('kind', 'all')
    if kind not in ('all', *kinds):
        raise web.HTTPBadRequest(text='Choose a valid change type.')
    if kind in kinds:
        query['action'] = kinds[kind]
    async with mongo(request) as db:
        rows = await collection(db).find(query).sort([('at',-1),('_id',-1)]).skip(page*15).limit(16).to_list(length=16)
        tags = list({r['clan']['tag'] for r in rows})
        live = await db.clans.find({'tag':{'$in':tags}}, {'tag':1}).to_list(length=None)
        present = {r['tag'] for r in live}
        latest = {}
        # One removal per clan is eligible; older snapshots are view-only.
        for tag in tags:
            last = await collection(db).find_one({'guild_id':GUILD_ID,'clan.tag':tag,'action':'before_remove'}, sort=[('at',-1),('_id',-1)])
            if last:latest[tag] = last['_id']
        events = []
        for row in rows[:15]:
            clan = row['clan'];date = row.get('at')
            events.append({'id':row['_id'],'action':LABELS.get(row['action'],'Saved snapshot'),
                'at':(date if date.tzinfo else date.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat() if date else None,'actor':row.get('actor_name') or 'Staff member (name unavailable)',
                'source':row.get('source','Dashboard'),'clan':public(clan),
                'changes':public_changes(row),
                'can_restore':row['action']=='before_remove' and clan['tag'] not in present and latest.get(clan['tag'])==row['_id'],
                'present':clan['tag'] in present})
    return web.json_response({'events':events,'more':len(rows)>15})

async def restore(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    async with mongo(request) as db:
        event = await collection(db).find_one({'_id':request.match_info['event_id'],'guild_id':GUILD_ID,'action':'before_remove'})
        if not event:raise web.HTTPNotFound(text='Removal snapshot not found.')
        row = event['clan'];tag = row['tag']
        if not isinstance(body,dict) or body.get('confirm_tag') != tag:
            raise web.HTTPBadRequest(text='Enter the clan tag to confirm restoration.')
        latest = await collection(db).find_one({'guild_id':GUILD_ID,'clan.tag':tag,'action':'before_remove'},sort=[('at',-1),('_id',-1)])
        if latest['_id'] != event['_id']:raise web.HTTPConflict(text='A newer removal exists. Refresh history.')
        if await db.clans.find_one({'tag':tag}):raise web.HTTPConflict(text='This clan already exists. Its current settings were kept.')
        if not await ensure_clan_tag_index(db):raise web.HTTPServiceUnavailable(text='Clan uniqueness check failed. Nothing was restored.')
        await audit(db,actor,'before_restore',row)
        try:await db.clans.insert_one(dict(row))
        except DuplicateKeyError:raise web.HTTPConflict(text='This clan was already restored or added. Its current settings were kept.') from None
        await audit(db,actor,'restore',row)
    return web.json_response({'clan':public(row),'message':'Clan restored. Review its roles, channels and artwork.'})

routes = [web.get(API+'/clan-history',history),web.post(API+'/clan-history/{event_id}/restore',restore)]
