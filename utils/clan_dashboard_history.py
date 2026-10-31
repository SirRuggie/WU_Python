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

async def finish_change(db, event_id, before, after, *, names=None):
    """Attach a confirmed diff only after the setting's compare-and-set succeeds.

    The before-image remains durable if this secondary write is unavailable.
    It must then render as a snapshot, never as a confirmed completed change.
    """
    import logging
    changes = [
        {'field': key, 'before': before.get(key), 'after': after.get(key),
         **({'display': names[key]} if names and key in names else {})}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]
    cleanup = [item['before'] for item in changes
               if item['field'] in ('logo', 'banner') and item['before']]
    update = {'changes': changes, 'confirmed': True}
    if cleanup:
        update['artwork_cleanup'] = cleanup
    try:
        result = await collection(db).update_one(
            {'_id': event_id}, {'$set': update}
        )
        if not result.matched_count:
            raise RuntimeError('History snapshot missing')
    except Exception:
        logging.getLogger(__name__).exception(
            'Clan change saved; history remains a before-image event=%s', event_id
        )


async def cleanup_artwork(db, media):
    """Retry confirmed replacements; never delete a currently referenced clan image.

    Cleanup state belongs to the existing durable history event. A failed delete
    stays pending across backend restarts; deletion is idempotent in R2.
    """
    import logging
    import re
    rows = await collection(db).find({
        'confirmed': True, 'artwork_cleanup': {'$exists': True},
        'artwork_cleanup_done': {'$ne': True},
    }).sort([('artwork_cleanup_checked_at', 1), ('at', 1)]).limit(100).to_list(length=100)
    for event in rows:
        try:
            held = False
            for url in event['artwork_cleanup']:
                key = media.key_for_url(url)
                # Only content-addressed clan uploads. Never static art, FWA
                # bases, foreign hosts, or arbitrary objects in the bucket.
                if not key or not re.fullmatch(r'clans/.+/(?:logo|banner)\.[a-f0-9]{10}\.(?:png|jpg|gif|webp)', key):
                    continue
                if await db.clans.find_one({'$or': [{'logo': url}, {'banner': url}, {'profile': url}]}, {'_id': 1}):
                    held = True
                    continue
                # Removal before-images can be restored even after a clan leaves
                # the live directory. Retain their artwork conservatively.
                if await collection(db).find_one({
                    'action': 'before_remove',
                    '$or': [{'clan.logo': url}, {'clan.banner': url}, {'clan.profile': url}],
                }, {'_id': 1}):
                    held = True
                    continue
                await media.delete_url(url)
            if not held:
                await collection(db).update_one({'_id': event['_id']},
                                                {'$set': {'artwork_cleanup_done': True}})
        except Exception:
            logging.getLogger(__name__).exception(
                'Replaced clan artwork cleanup pending; will retry event=%s', event['_id'])
        finally:
            try:
                await collection(db).update_one({'_id': event['_id']}, {'$set': {
                    'artwork_cleanup_checked_at': datetime.now(timezone.utc),
                }})
            except Exception:
                logging.getLogger(__name__).exception('Could not record artwork cleanup check')


async def abandon_change(db, event_id):
    """Best-effort failure marker; unconfirmed snapshots remain non-changes."""
    import logging
    try:
        await collection(db).update_one({'_id': event_id}, {'$set': {'abandoned': True}})
    except Exception:
        logging.getLogger(__name__).exception('Could not mark failed clan change event=%s', event_id)
