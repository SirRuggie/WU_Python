"""Daily, reversible archival of resolved ticket pairs after human inactivity."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import hikari
from . import store, testing_service

_log = logging.getLogger(__name__)
_task = None
STATE_ID = 'resolved_ticket_archive_schedule'
STATUSES = ('approved', 'denied', 'closed')


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def quiet_days(config):
    value = int(config.get('ticket_archive_quiet_days', 1))
    if not 0 <= value <= 365:
        raise ValueError('Archive quiet days must be between 0 and 365.')
    return value


def eligible(ticket, cutoff):
    if ticket.get('status') not in STATUSES or testing_service.is_test_ticket(ticket):
        return False
    # A newly resolved old conversation gets a full quiet period too.
    times = [aware(ticket.get(k)) for k in ('created_at', 'handled_at', 'approved_at', 'denied_at', 'closed_at') if ticket.get(k)]
    return bool(times) and max(times) <= cutoff


async def quiet(rest, ids, cutoff):
    for channel_id in ids:
        count = 0
        async for message in rest.fetch_messages(channel_id).limit(500):
            count += 1
            if aware(message.timestamp) <= cutoff:
                break
            if not message.author.is_bot and not getattr(message, 'webhook_id', None):
                return False
        else:
            # A capped scan cannot establish silence beyond its history window.
            if count >= 500:
                return False
    return True


async def archive_pair(bot, mongo, ticket, config):
    days = quiet_days(config)
    cutoff = now() - timedelta(days=days)
    if not days or not eligible(ticket, cutoff):
        return False
    location = ticket.get('location') or {}
    ids = [int(location.get(key) or 0) for key in ('id', 'staff_space_id')]
    if not all(ids) or ids[0] == ids[1]:
        return False
    channels = [await bot.rest.fetch_channel(cid) for cid in ids]
    if any(ch.type not in (hikari.ChannelType.GUILD_PUBLIC_THREAD, hikari.ChannelType.GUILD_PRIVATE_THREAD)
           or int(ch.guild_id) != int(config['ticket_target_guild_id']) for ch in channels):
        return False
    active = [int(ch.id) for ch in channels if not ch.is_archived]
    if not active or not await quiet(bot.rest, ids, cutoff):
        return False
    current = await mongo.tickets.find_one({'_id': ticket['_id'], **store.RUNTIME_FILTER})
    fresh_config = await mongo.ticket_setup.find_one({'_id': 'config'}) or {}
    if (not current or current.get('rev') != ticket.get('rev') or current.get('location') != location
            or not eligible(current, cutoff) or quiet_days(fresh_config) != days
            or fresh_config.get('ticket_target_guild_id') != config.get('ticket_target_guild_id')):
        return False
    changed = []
    try:
        for cid in active:
            # Recheck both conversations immediately before each Discord edit.
            if not await quiet(bot.rest, ids, cutoff):
                break
            await bot.rest.edit_channel(cid, archived=True, reason=f'Resolved ticket quiet for {days} days')
            changed.append(cid)
        current = await mongo.tickets.find_one({'_id': ticket['_id'], **store.RUNTIME_FILTER})
        if (len(changed) != len(active) or not current or current.get('rev') != ticket.get('rev')
                or not eligible(current, cutoff) or not await quiet(bot.rest, ids, cutoff)):
            for cid in changed:
                await bot.rest.edit_channel(cid, archived=False, reason='Conversation or ticket changed during cleanup')
            return False
    except Exception:
        for cid in changed:
            try:
                await bot.rest.edit_channel(cid, archived=False, reason='Incomplete paired archive rollback')
            except Exception:
                _log.exception('Could not restore thread after incomplete archive: %s', cid)
        raise
    await mongo.tickets.update_one({'_id': ticket['_id']}, {'$set': {'auto_archive': {
        'at': now(), 'quiet_days': days, 'thread_ids': ids,
    }}})
    _log.info('Archived resolved ticket pair ticket=%s quiet_days=%s', ticket['_id'], days)
    return True


async def sweep(bot, mongo):
    if testing_service.is_test_scope(mongo):
        return
    config = await mongo.ticket_setup.find_one({'_id': 'config'}) or {}
    days = quiet_days(config)
    gid = int(config.get('ticket_target_guild_id') or 0)
    if not days or not gid:
        return
    schedule = await mongo.ticket_setup.find_one({'_id': STATE_ID}) or {}
    if schedule.get('completed_at') and now() - aware(schedule['completed_at']) < timedelta(days=1):
        return
    active = await bot.rest.fetch_active_threads(gid)
    ids = [int(ch.id) for ch in active]
    query = {**store.RUNTIME_FILTER, 'guild_id': gid, 'status': {'$in': list(STATUSES)},
             '$or': [{'location.id': {'$in': ids}}, {'location.staff_space_id': {'$in': ids}}]}
    archived = errors = 0
    async for ticket in mongo.tickets.find(query):
        try:
            archived += bool(await archive_pair(bot, mongo, ticket, config))
        except Exception:
            errors += 1
            _log.exception('Resolved ticket archive skipped ticket=%s', ticket['_id'])
    await mongo.ticket_setup.update_one({'_id': STATE_ID}, {'$set': {
        'completed_at': now(), 'archived_pairs': archived, 'errors': errors,
    }}, upsert=True)
    _log.info('Daily resolved ticket archive complete pairs=%s errors=%s', archived, errors)


async def _run(bot, mongo):
    while True:
        try:
            from . import thread_intake_ready
            if thread_intake_ready():
                await sweep(bot, mongo)
        except Exception:
            _log.exception('Daily resolved ticket archive failed')
        await asyncio.sleep(60)


def start(bot, mongo):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(bot, mongo), name='resolved-ticket-archive')


async def stop():
    global _task
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
