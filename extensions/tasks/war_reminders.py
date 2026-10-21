"""Bot-owned polling and Discord delivery for enabled family-clan reminders."""
import asyncio
import logging
from datetime import datetime, timezone

import coc
import hikari
import lightbulb

from utils import account_links, war_reminders as reminders
from utils.mongo import MongoClient
from utils.war_reminder_store import WarReminderStore, occurrence_key

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 60
FETCH_CONCURRENCY = 4
_task = None


async def send_occurrence(store, bot, config, war, event, owners):
    clan_tag = config['_id']
    key = occurrence_key(clan_tag, war['start'], event)
    fresh = await store.get_settings(clan_tag)
    if (not fresh or fresh.get('version') != config.get('version')
            or not fresh['enabled'] or not await store.clan(clan_tag)):
        return
    now = datetime.now(timezone.utc)
    if event not in reminders.due(war, config, now):
        return
    payloads = reminders.messages(war, config, event, owners)
    claimed = await store.claim_delivery(
        key, clan_tag=clan_tag, at=now, event=event,
        channel_id=config['channel_id'], test=False,
        status='sending' if payloads else 'skipped',
        detail='' if payloads else 'No players need a reminder.',
    )
    if not claimed:
        return
    urls = []
    try:
        for payload in payloads:
            sent = await bot.rest.create_message(
                int(config['channel_id']), content=payload['content'],
                mentions_everyone=False, role_mentions=False,
                user_mentions=[int(uid) for uid in payload['allowed_mentions']['users']],
            )
            urls.append(f"https://discord.com/channels/{reminders.GUILD_ID}/{config['channel_id']}/{sent.id}")
            # Preserve partial progress even if the process stops between parts.
            await store.finish_delivery(key, urls=urls)
        if payloads:
            await store.finish_delivery(key, status='sent', url=urls[0], urls=urls)
    except Exception:
        # Discord might already have accepted the request; do not retry a ping.
        await store.finish_delivery(
            key, status='uncertain', urls=urls,
            detail='Delivery interrupted. Check the channel; this occurrence will not be resent.',
        )
        raise


async def scan_clan(db, client, bot, links, config):
    store = WarReminderStore(db)
    clan_tag = config['_id']
    if not await store.clan(clan_tag):
        return
    try:
        war = reminders.snapshot(await client.get_current_war(clan_tag), clan_tag)
        now = datetime.now(timezone.utc)
        await store.record_status(
            clan_tag, checked_at=now, error=None,
            detail='Tracking battle day' if war else 'Waiting for an active war',
            war_end=war['end'] if war else None,
        )
        events = []
        for event in reminders.due(war, config, now):
            if not await store.delivered_or_claimed(occurrence_key(clan_tag, war['start'], event)):
                events.append(event)
        if not events:
            return
        members = reminders.pending(war, config['audience'])
        owners = await links.linked_owners([m['tag'] for m in members]) if members else {}
        channel = await bot.rest.fetch_channel(int(config['channel_id']))
        if (int(getattr(channel, 'guild_id', 0)) != reminders.GUILD_ID
                or channel.type not in (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS)):
            raise ValueError('Reminder channel is not a text channel in this server.')
        for event in events:
            await send_occurrence(store, bot, config, war, event, owners)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.warning('War reminder check failed for %s: %s', clan_tag, type(exc).__name__)
        await store.record_status(
            clan_tag, checked_at=datetime.now(timezone.utc), error=type(exc).__name__,
            detail='Could not check or deliver reminders. Check war-log visibility, link services, and channel permissions.',
        )


async def loop(db, client, bot):
    store = WarReminderStore(db)
    indexes_ready = False
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    while True:
        try:
            if not indexes_ready:
                await store.ensure_indexes()
                indexes_ready = True
            configs = await store.enabled_settings()

            async def run(config):
                async with semaphore:
                    try:
                        await scan_clan(db, client, bot, account_links, config)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _log.exception('War reminder state update failed for %s', config['_id'])

            await asyncio.gather(*(run(config) for config in configs))
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception('War reminder scan failed')
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(loop(mongo, coc_client, bot), name='war-reminders')


@loader.listener(hikari.StoppingEvent)
async def stop(event: hikari.StoppingEvent):
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
