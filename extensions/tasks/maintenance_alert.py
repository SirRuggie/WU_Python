"""Observe existing Clash results and send one no-ping staff alert per window."""
import asyncio
from datetime import datetime, timezone
import logging

import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container
from hikari.impl import TextDisplayComponentBuilder as Text

from utils import coc_maintenance
from utils.background import run_periodic
from utils.constants import LOG_CHANNEL_ID, WU_GREEN, WU_RED
from utils.maintenance_alert_store import MaintenanceAlertStore
from utils.mongo import MongoClient
from utils.war_reminder_health import timestamp

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
_task = None


def alert_text(started, ended=None):
    if ended is None:
        return ('## 🔧 Clash maintenance\n'
                f'Started <t:{int(started.timestamp())}:R>\n'
                'War reminders pause. The latest missed reminder sends when it ends.')
    minutes = max(0, int((ended - started).total_seconds() // 60))
    return ('## ✅ Clash maintenance ended\n'
            f'Lasted {minutes} min · ended <t:{int(ended.timestamp())}:t>')


def payload(started, ended=None):
    return dict(components=[Container(accent_color=WU_GREEN if ended else WU_RED,
                                      components=[Text(content=alert_text(started, ended))])],
                flags=hikari.MessageFlag.IS_COMPONENTS_V2,
                mentions_everyone=False, user_mentions=False, role_mentions=False)


class AlertWorker:
    def __init__(self, store, bot, *, started_at=None):
        self.store = store
        self.bot = bot
        started_at = timestamp(started_at or datetime.now(timezone.utc))
        self.started_at = started_at.replace(microsecond=started_at.microsecond // 1000 * 1000)
        self.rendered = set()
        self.warned = set()
        self.pending_invalidations = {}
        self.pending_posts = {}

    def warn(self, window, action, error):
        key = (window, action)
        if key not in self.warned:
            self.warned.add(key)
            _log.warning('Maintenance alert %s unavailable error=%s; saved state retained',
                         action, type(error).__name__)

    async def edit(self, row, now, *, ended=None, close=False):
        intent = await self.store.claim_edit(row, now, close=close)
        if intent is None:
            return
        try:
            final_render = alert_text(timestamp(intent['started_at']), ended) if ended is not None else None
            if intent.get('_id', 'clash') != 'clash' and intent['final_render'] != final_render:
                raise ValueError('Closed maintenance render does not match its window')
            if intent.get('message_id'):
                await self.bot.rest.edit_message(int(intent['channel_id']), int(intent['message_id']),
                                                 **payload(timestamp(intent['started_at']), ended))
            acknowledged = await self.store.finish_edit(intent, ended=ended, final_render=final_render)
            if acknowledged and ended is None:
                self.rendered.add((timestamp(intent['started_at']), intent['message_id']))
        except (Exception, asyncio.CancelledError) as error:
            # Keep ownership of cleanup even if shutdown cancels us again.
            # The pre-REST dirty intent also survives an abrupt process death.
            cleanup = asyncio.create_task(self.store.finish_edit(intent, success=False))
            try:
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        continue
                cleanup.result()
            except (Exception, asyncio.CancelledError) as cleanup_error:
                # A newer acknowledgement may already have cleared our durable
                # intent. Retain its invalidation until storage is available.
                self.pending_invalidations[intent['edit_claim']] = intent
                self.warn(str(intent['started_at']), 'delivery', cleanup_error)
            # Storage cleanup failure must never swallow shutdown cancellation.
            raise error

    async def reconcile_closed(self, now):
        complete = True
        for receipt in await self.store.dirty_closed():
            try:
                self.store.closed_identity(receipt)
                await self.edit(receipt, now, ended=timestamp(receipt['ended_at']))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.warn(str(receipt.get('started_at')), 'closed reconciliation', error)
                complete = False
        return complete

    async def attach_post(self, intent, message_id):
        key = (self.store.window_id(intent), intent['revision'])
        # This is an actual known REST return, not permission for another POST.
        self.pending_posts[key] = (intent, message_id)
        accepted = await self.store.posted(intent, message_id)
        self.pending_posts.pop(key, None)
        if not accepted:
            self.warn(str(intent['started_at']), 'post attachment', ValueError())
        return accepted

    async def tick(self, now=None):
        now = timestamp(now or datetime.now(timezone.utc))
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        observation = coc_maintenance.observation()
        row = None
        try:
            complete = True
            for intent, message_id in tuple(self.pending_posts.values()):
                complete = await self.attach_post(intent, message_id) and complete
            for claim, intent in tuple(self.pending_invalidations.items()):
                await self.store.invalidate_edit(intent)
                self.pending_invalidations.pop(claim, None)
            complete = await self.reconcile_closed(now) and complete
            if observation['maintenance']:
                row, post = await self.store.observe(observation['started_at'],
                                                     observation['last_maintenance_at'], LOG_CHANNEL_ID)
                if str(row.get('channel_id')) != str(LOG_CHANNEL_ID):
                    raise ValueError('Maintenance alert destination is not the staff log channel')
                if row['state'] == 'closed':
                    if row.get('needs_red_edit') and timestamp(row.get('clear_since')):
                        await self.edit(row, now, ended=timestamp(row['clear_since']))
                    return complete
                started = timestamp(row['started_at'])
                if post:
                    # observe() committed uncertain before the ambiguous external call.
                    if not await self.store.can_post(row):
                        return complete
                    sent = await self.bot.rest.create_message(int(row['channel_id']), **payload(started))
                    if not await self.attach_post(row, sent.id):
                        return False
                    self.rendered.add((started, str(sent.id)))
                elif row.get('message_id') and row['state'] != 'closing':
                    key = (started, row['message_id'])
                    if key not in self.rendered or row.get('needs_red_edit'):
                        await self.edit(row, now)
                return complete
            row = await self.store.get()
            if not row:
                return complete
            if str(row.get('channel_id')) != str(LOG_CHANNEL_ID):
                raise ValueError('Maintenance alert destination is not the staff log channel')
            if row['state'] == 'closed':
                if row.get('needs_red_edit') and timestamp(row.get('clear_since')):
                    await self.edit(row, now, ended=timestamp(row['clear_since']))
                return complete
            # Reconcile actual transitions even if no alert tick ran during a flap.
            observed_seen = timestamp(observation['last_maintenance_at'])
            if observed_seen:
                observed_seen = observed_seen.replace(microsecond=observed_seen.microsecond // 1000 * 1000)
            saved_seen = timestamp(row.get('last_maintenance_at'))
            if observed_seen and (saved_seen is None or observed_seen > saved_seen):
                row, _ = await self.store.observe(observation['window_started_at'],
                                                  observed_seen, LOG_CHANNEL_ID)
            success = observation['last_success_at']
            last_seen = timestamp(row.get('last_maintenance_at'))
            # Default healthy memory after restart is not recovery evidence.
            if (success is None or success < self.started_at
                    or last_seen and success < last_seen):
                return complete
            observed_clear = timestamp(observation['clear_since'])
            if observed_clear is None:
                return complete
            observed_clear = observed_clear.replace(microsecond=observed_clear.microsecond // 1000 * 1000)
            clear = timestamp(row.get('clear_since'))
            hold_from = max(observed_clear, self.started_at)
            if clear is None or clear < hold_from:
                if row.get('needs_red_edit'):
                    await self.edit(row, now)
                    return complete
                await self.store.change(row, clear_since=hold_from)
                return complete
            if (now - clear).total_seconds() < 300:
                if row.get('needs_red_edit'):
                    await self.edit(row, now)
                return complete
            await self.edit(row, now, ended=observed_clear, close=True)
            return complete
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.warn(str(row.get('started_at')) if row else 'state', 'delivery', error)
            return False


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start(event: hikari.StartedEvent,
                mongo: MongoClient = lightbulb.di.INJECTED,
                bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    global _task
    if _task is None or _task.done():
        worker = AlertWorker(MaintenanceAlertStore(mongo), bot)
        _task = asyncio.create_task(run_periodic('maintenance-alert', worker.tick, 30, logger=_log),
                                    name='maintenance-alert')


@loader.listener(hikari.StoppingEvent)
async def stop(event: hikari.StoppingEvent):
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
