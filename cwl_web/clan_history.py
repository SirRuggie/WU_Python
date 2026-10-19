"""Staff activity and non-destructive recovery of removed family clans."""
import re
from datetime import timezone
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils.clan_dashboard_history import audit, collection
from utils.mongo import ensure_clan_tag_index
from .server_management import API, GUILD_ID, require_manage, mongo
from .manage_clans import public

LABELS = {'add':'Clan added', 'before_edit':'Settings saved before edit',
          'before_remove':'Clan saved before removal', 'before_emoji':'Emoji update requested',
          'before_thread':'Thread update requested', 'before_restore':'Restore requested',
          'restore':'Clan restored'}

async def history(request):
    await require_manage(request, 'clans')
    try:page = max(0, min(10000, int(request.query.get('page', '0'))))
    except ValueError:raise web.HTTPBadRequest(text='Choose a valid history page.') from None
    query = {'guild_id': GUILD_ID}
    term = request.query.get('q', '').strip()[:100]
    if term:query['$or'] = [{key:{'$regex':re.escape(term),'$options':'i'}} for key in ('clan.name','clan.tag')]
    if request.query.get('kind') == 'removed':query['action'] = 'before_remove'
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
                'at':date.replace(tzinfo=timezone.utc).isoformat() if date else None,'actor':row.get('actor_name') or 'Staff · '+str(row.get('actor','unknown')),
                'source':row.get('source','Dashboard'),'clan':public(clan),
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
