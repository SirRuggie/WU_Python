"""Durable clan recovery snapshots shared by Discord and the dashboard."""
from datetime import datetime, timezone
from uuid import uuid4
from pymongo.write_concern import WriteConcern

GUILD_ID = 644963518025826315

def collection(db):
    return db.bot_config.database.get_collection(
        'clan_dashboard_history', write_concern=WriteConcern(w='majority', wtimeout=10000))

async def audit(db, actor, action, row):
    if row is None:
        raise ValueError('Clan no longer exists. Refresh before trying again.')
    member = actor.get('member') or {}
    user = member.get('user') or {}
    event = {'_id': uuid4().hex, 'guild_id': GUILD_ID,
             'actor': str(actor['user_id']),
             'actor_name': actor.get('name') or member.get('nick') or user.get('global_name') or user.get('username') or '',
             'source': actor.get('source', 'Dashboard'), 'action': action,
             'at': datetime.now(timezone.utc), 'clan': row}
    await collection(db).insert_one(event)
    return event['_id']

async def native_snapshot(db, ctx, action, tag):
    row = await db.clans.find_one({'tag': tag})
    user = ctx.user
    await audit(db, {'user_id': str(user.id), 'name': getattr(user, 'display_name', None) or getattr(user, 'username', ''), 'source': 'Discord'}, action, row)
    return row
