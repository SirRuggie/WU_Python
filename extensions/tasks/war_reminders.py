"""Poll only enabled family clans; durable claims prevent duplicate notifications."""
import asyncio
import logging
from datetime import datetime, timezone
import coc
import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError
from utils.mongo import MongoClient
from utils import war_reminders as reminders
from cwl_web.providers import LiveProviders

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
_task = None


async def scan_clan(db, client, bot, providers, config):
    clan_tag = config['_id']
    if not await db.clans.find_one({'tag': clan_tag}):
        return
    state = reminders.collection(db, 'war_reminder_status')
    now = datetime.now(timezone.utc)
    try:
        war = reminders.snapshot(await client.get_current_war(clan_tag), clan_tag)
        await state.update_one({'_id': clan_tag}, {'$set': {'checked_at': now, 'detail': 'Tracking battle day' if war else 'Waiting for an active war', 'war_end': war['end'] if war else None, 'error': None}}, upsert=True)
        events = reminders.due(war, config, now)
        if not events:
            return
        members = reminders.pending(war, config['audience'])
        owners = {}
        if members:
            links = await providers._combined_links(player_tags=[m['tag'] for m in members])
            choices = {}
            for tag, uid, _ in links:
                choices.setdefault(tag, set()).add(uid)
            owners = {tag: next(iter(ids)) for tag, ids in choices.items() if len(ids) == 1}
        channel = await bot.rest.fetch_channel(int(config['channel_id']))
        if int(getattr(channel, 'guild_id', 0)) != reminders.GUILD_ID or channel.type not in (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS):
            raise ValueError('Reminder channel is not a text channel in this server.')
        deliveries = reminders.collection(db, 'war_reminder_deliveries')
        # War identity excludes end time, which can shift during maintenance.
        for event in events:
            key = f"{clan_tag}:{int(war['start'].timestamp())}:{event}"
            if await deliveries.find_one({'_id': key}):
                continue
            # Respect a disable/edit/removal during the network lookups above.
            fresh = await reminders.collection(db).find_one({'_id': clan_tag})
            if not fresh or fresh.get('version') != config.get('version') or not fresh['enabled'] or not await db.clans.find_one({'tag': clan_tag}):
                return
            if event not in reminders.due(war, config, datetime.now(timezone.utc)):
                continue
            payloads = reminders.messages(war, config, event, owners)
            try:
                await deliveries.insert_one(dict(_id=key, clan_tag=clan_tag, at=now, event=event, channel_id=config['channel_id'], test=False, status='sending' if payloads else 'skipped', detail='' if payloads else 'No players need a reminder.'))
            except DuplicateKeyError:
                continue
            urls = []
            try:
                for payload in payloads:
                    data = payload['embeds'][0]
                    embed = hikari.Embed(title=data['title'], description=data['description'], color=data['color']).set_footer(data['footer']['text'])
                    sent = await bot.rest.create_message(int(config['channel_id']), content=payload['content'], embed=embed,
                        mentions_everyone=False, role_mentions=False, user_mentions=[int(uid) for uid in payload['allowed_mentions']['users']])
                    urls.append(f"https://discord.com/channels/{reminders.GUILD_ID}/{config['channel_id']}/{sent.id}")
                if payloads:
                    await deliveries.update_one({'_id': key}, {'$set': {'status': 'sent', 'url': urls[0], 'urls': urls}})
            except Exception:
                # Discord may have accepted the request. Never blindly retry a ping.
                await deliveries.update_one({'_id': key}, {'$set': {'status': 'uncertain', 'detail': 'Delivery interrupted. Check the channel; this occurrence will not be resent.', 'urls': urls}})
                raise
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.warning('War reminder check failed for %s: %s', clan_tag, type(exc).__name__)
        await state.update_one({'_id': clan_tag}, {'$set': {'checked_at': now, 'detail': 'Could not check or deliver reminders. Check war-log visibility, link services, and channel permissions.', 'error': type(exc).__name__}}, upsert=True)


async def loop(db, client, bot):
    providers = LiveProviders()
    while True:
        try:
            configs = await reminders.collection(db).find({'enabled': True}).to_list(length=None)
            sem = asyncio.Semaphore(4)
            async def run(config):
                async with sem:
                    await scan_clan(db, client, bot, providers, config)
            await asyncio.gather(*(run(c) for c in configs))
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception('War reminder scan failed')
        await asyncio.sleep(60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start(event: hikari.StartedEvent, mongo: MongoClient = lightbulb.di.INJECTED,
                coc_client: coc.Client = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED):
    global _task
    _task = asyncio.create_task(loop(mongo, coc_client, bot), name='war-reminders')


@loader.listener(hikari.StoppingEvent)
async def stop(event: hikari.StoppingEvent):
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
