"""Durable per-clan batch receipts; completed/ambiguous sends are never retried."""
import hashlib
import json
import time
from pymongo.errors import DuplicateKeyError

BATCH_KIND = 'manage_return_batch'
OPERATIONS = {'save','replace','send','start','pause','resume','clear','away'}
MAX_CLANS = 50


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


async def queue(db, *, user_id, guild_id, request_id, operation, items, minutes=60, retry_of=None, selection_key=None):
    if operation not in OPERATIONS or not 1<=len(items)<=MAX_CLANS:
        raise ValueError('Choose an action and 1 to 50 clans.')
    key='manage-return-batch:'+digest([str(user_id),request_id])
    payload=dict(user_id=str(user_id),guild_id=guild_id,operation=operation,items=items,minutes=minutes,retry_of=retry_of,selection_key=selection_key)
    fingerprint=digest(payload)
    try:
        await db.bot_config.insert_one(dict(_id=key,kind=BATCH_KIND,created_at=time.time(),state='building',request_id=request_id,payload_hash=fingerprint,**payload))
    except DuplicateKeyError:
        old=await db.bot_config.find_one({'_id':key})
        if not old or old.get('payload_hash')!=fingerprint:
            raise ValueError('This request ID was already used for another selection.')
    parent=await db.bot_config.find_one({'_id':key})
    created=parent['created_at']
    for index,item in enumerate(items):
        values=dict(clan_tag=item['tag'],section=item['section'],every_minutes=minutes)
        if 'destination' in item:values['destination']=item['destination']
        child=dict(_id=key+':'+str(index),kind='manage_web_request',parent_id=key,section='cwl_rosters',action=operation,
                   values=values,revision=item['revision'],user_id=str(user_id),guild_id=guild_id,status='held',created_at=created,
                   expires_at=created+900,clan_name=item['name'])
        try:await db.bot_config.insert_one(child)
        except DuplicateKeyError:pass
    await db.bot_config.update_one({'_id':key,'state':'building'},{'$set':{'state':'ready'}})
    await db.bot_config.update_many({'parent_id':key,'status':'held'},{'$set':{'status':'pending'}})
    await db.bot_config.update_one({"_id":key,"state":"ready"},{"$set":{"state":"queued"}})
    return key


async def activate(db):
    # Finish manifests interrupted before all children existed.
    async for parent in db.bot_config.find({'kind':BATCH_KIND,'state':'building'}).sort('created_at',1).limit(50):
        if parent.get('request_id'):
            await queue(db,user_id=parent['user_id'],guild_id=parent['guild_id'],request_id=parent['request_id'],operation=parent['operation'],items=parent['items'],minutes=parent['minutes'],retry_of=parent.get('retry_of'),selection_key=parent.get('selection_key'))
    # Recover a crash between making the complete manifest ready and releasing children.
    async for parent in db.bot_config.find({'kind':BATCH_KIND,'state':'ready'}).sort('created_at',-1).limit(50):
        await db.bot_config.update_many({'parent_id':parent['_id'],'status':'held'},{'$set':{'status':'pending'}})
        await db.bot_config.update_one({'_id':parent['_id'],'state':'ready'},{'$set':{'state':'queued'}})


async def children(db,parent):
    return await db.bot_config.find({'parent_id':parent['_id']}).sort('_id',1).to_list(length=MAX_CLANS)


def summary(parent,rows):
    counts={key:sum(r['status']==key for r in rows) for key in ('done','failed','uncertain','running','pending','held')}
    pending=counts['running']+counts['pending']+counts['held'] or len(rows)<len(parent['items'])
    message=f"{counts['done']} completed · {counts['failed']} failed · {counts['uncertain']} need checking"
    if pending:message+=' · Still working'
    labels={'done':'Completed','failed':'Failed — review before retry','uncertain':'Check Discord — do not retry','running':'Working','pending':'Waiting','held':'Waiting'}
    details='\n'.join(f"{r.get('clan_name') or r['values']['clan_tag']}: {labels.get(r['status'],r['status'])}"+(f" — {r['message']}" if r.get('message') and r['status']!='done' else '') for r in rows)
    return {'status':'pending' if pending else 'done','message':message,'result':{'message':message,'details':details}}


def retryable(rows):
    # Never include pending, running, successful or uncertain outcomes.
    return [row for row in rows if row['status']=='failed']
