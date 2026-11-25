"""Bot-owned polling and Discord delivery for enabled family-clan reminders."""
import asyncio
import logging
from datetime import datetime, timezone

import coc
import hikari
import lightbulb

from utils import account_links, coc_maintenance, war_reminders as reminders
from utils.mongo import MongoClient
from utils.war_reminder_store import WarReminderStore, occurrence_key
from utils.war_reminder_health import checked_settings
from utils.background import run_periodic, log_failure, cancel_and_wait

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 60
FETCH_CONCURRENCY = 4
_task = None
_warned_maintenance_start = None
_channel_locks: dict[int, asyncio.Lock] = {}


def _link_row(spec):
    row = hikari.impl.MessageActionRowBuilder()
    for button in spec['components']:
        row.add_link_button(button['url'], label=button['label'])
    return row


async def send_occurrence(store, bot, config, war, event, owners, *, maintenance_since=None, prior_war_start=None):
    # Fetches happen in scan_clan; only claim and complete delivery are serialized.
    lock = _channel_locks.setdefault(int(config['channel_id']), asyncio.Lock())
    async with lock:
        clan_tag = config['_id']
        key = occurrence_key(clan_tag, war['start'], event)
        fresh = await store.get_settings(clan_tag)
        if (not fresh or fresh.get('version') != config.get('version')
                or not fresh['enabled'] or not await store.clan_exists(clan_tag)):
            return
        now = datetime.now(timezone.utc)
        delayed = maintenance_since is not None
        if delayed:
            if coc_maintenance.in_maintenance():
                return
            state = await store.get_status(clan_tag) or {}
            if (state.get('error') == 'Maintenance'
                    or state.get('maintenance_since') is None
                    or reminders.utc(state['maintenance_since']) != reminders.utc(maintenance_since)
                    or state.get('war_start') is None
                    or reminders.utc(state['war_start']) != prior_war_start
                    or event not in dict(reminders.catchup_events(
                        war, config, now, maintenance_since, prior_war_start))):
                return
        elif event not in reminders.due(war, config, now):
            return
        payloads = reminders.messages(war, config, event, owners, **({'delayed_at': now} if delayed else {}))
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
                    components=[_link_row(row) for row in payload.get('components', [])],
                    **({'attachment': hikari.File('assets/Gold_Footer.png')} if payload.get('footer') else {}),
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
                detail="The delivery stopped. Check the channel. The bot will not send this reminder again.",
            )
            raise


async def _record_maintenance(store, config, now):
    global _warned_maintenance_start
    window = coc_maintenance.window_started_at()
    if _warned_maintenance_start != window:
        _warned_maintenance_start = window
        _log.warning('Clash maintenance; reminders continue when it ends')
    await store.record_status(
        config['_id'], settings_updated_at=config.get('updated_at'),
        settings_version=config.get('version'), checked_at=now, error='Maintenance',
        detail='Clash maintenance. Reminders continue when it ends.',
    )


async def scan_clan(db, client, bot, links, config):
    store = WarReminderStore(db)
    clan_tag = config['_id']
    if not await store.clan_exists(clan_tag):
        return
    try:
        current_war = await client.get_current_war(clan_tag)
        coc_maintenance.note_success()
        war = reminders.snapshot(current_war, clan_tag)
        now = datetime.now(timezone.utc)
        if coc_maintenance.in_maintenance():
            # Cached success does not clear the shared90s grace or paused window.
            await _record_maintenance(store, config, now)
            return False
        prior = await store.get_status(clan_tag) or {}
        maintenance_since = prior.get('maintenance_since')
        prior_start = reminders.utc(prior['war_start']) if prior.get('war_start') else None
        missed = (reminders.catchup_events(war, config, now, maintenance_since, prior_start)
                  if checked_settings(config, prior) else [])
        boundary = (checked_settings(config, prior) and reminders.catchup_boundary(
            war, config, now, maintenance_since, prior_start))
        latest = missed[-1][0] if missed else None
        earlier = [event for event, _ in missed[:-1]
                   if not await store.delivered_or_claimed(occurrence_key(clan_tag, war['start'], event))]
        detail = 'Tracking battle day' if war else 'Waiting for an active war'
        if missed:
            # Shaka1156: status/log only. Never reserve an earlier occurrence key;
            # a changed war end can make that event normally due on a later scan.
            detail += f'; {len(earlier)} earlier maintenance reminders skipped.'

        async def finish_maintenance():
            if maintenance_since is not None and not boundary:
                cleared = await store.clear_maintenance(config, maintenance_since, war['start'] if war else None)
                # The existing window-clear CAS owns the audit line. Concurrent
                # scans can share a preview but only one completes this window.
                if cleared and missed:
                    _log.info('Clash maintenance catch-up for %s: earlier offsets skipped: %s (%d)',
                              clan_tag, ', '.join(earlier) or 'none', len(earlier))
        await store.record_status(
            clan_tag, settings_updated_at=config.get('updated_at'),
            settings_version=config.get('version'), checked_at=now, error=None,
            detail=detail, war_end=war['end'] if war else None,
            war_start=war['start'] if war else None,
        )
        members = reminders.pending(war, config['audience']) if war else []
        events = []
        for event in reminders.due(war, config, now):
            if not await store.delivered_or_claimed(occurrence_key(clan_tag, war['start'], event)):
                events.append(event)
        delayed = (latest if latest and members and not await store.delivered_or_claimed(
            occurrence_key(clan_tag, war['start'], latest)) else None)
        if not events and not delayed:
            await finish_maintenance()
            return
        owners = await links.linked_owners([m['tag'] for m in members]) if members else {}
        channel = await bot.rest.fetch_channel(int(config['channel_id']))
        if (int(getattr(channel, 'guild_id', 0)) != reminders.GUILD_ID
                or channel.type not in (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS)):
            raise ValueError('Reminder channel is not a text channel in this server.')
        if delayed:
            await send_occurrence(store, bot, config, war, delayed, owners,
                                  maintenance_since=maintenance_since, prior_war_start=prior_start)
        for event in events:
            await send_occurrence(store, bot, config, war, event, owners)
        await finish_maintenance()
    except asyncio.CancelledError:
        raise
    except coc.Maintenance:
        coc_maintenance.note_maintenance()
        await _record_maintenance(store, config, datetime.now(timezone.utc))
        return False
    except Exception as exc:
        log_failure(_log, 'war-reminders.clan', exc)
        await store.record_status(
            clan_tag, settings_updated_at=config.get('updated_at'),
            settings_version=config.get('version'),
            checked_at=datetime.now(timezone.utc), error=type(exc).__name__,
            detail="The bot could not check or send the reminders. Check these things: the war log is public, the account link service works, and the bot can use the channel.",
        )
        return False


async def loop(db, client, bot):
    store = WarReminderStore(db)
    indexes_ready = False
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    async def scan():
        nonlocal indexes_ready
        if not indexes_ready:
            await store.ensure_indexes()
            indexes_ready = True
        configs = await store.enabled_settings()

        async def run(config):
            async with semaphore:
                try:
                    return await scan_clan(db, client, bot, account_links, config)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    log_failure(_log, "war-reminders.state-update", error)
                    return False

        tasks = []
        try:
            for config in configs:
                tasks.append(asyncio.create_task(run(config)))
            results = await asyncio.gather(*tasks)
            return all(result is not False for result in results)
        finally:
            # gather does not cancel siblings when a child itself is cancelled.
            # Own every scan until all of its cancellation cleanup has finished.
            await cancel_and_wait(tasks)

    await run_periodic("war-reminders", scan, SCAN_INTERVAL_SECONDS, logger=_log)


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
