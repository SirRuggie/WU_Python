"""Opt-in Gold Rush panels, automatic updates and administrator configuration."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging
import time

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator, MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ModalActionRowBuilder as ModalRow,
    MediaGalleryComponentBuilder as Media, MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils import goldrush as store, recruit_links, bot_data
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID
from utils.gold_loot import refresh_board, load_town_halls
from utils.emoji import emojis

loader = lightbulb.Loader()
group = lightbulb.Group('goldrush', 'Manage the Gold Rush giveaway',
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    contexts=[hikari.ApplicationContextType.GUILD],
    integration_types=[hikari.ApplicationIntegrationType.GUILD_INSTALL])
_log = logging.getLogger(__name__)
_refresh_lock = asyncio.Lock()
_last_refresh = 0.0
_last_warning = None
_task = None


EASTERN = ZoneInfo('America/New_York')


def eastern_time(value):
    return datetime.fromisoformat(value).astimezone(EASTERN).strftime('%b %d, %Y • %I:%M %p %Z')


def discord_time(value):
    return f"<t:{int(datetime.fromisoformat(value).timestamp())}:f>"


def parse_eastern_start(date, time):
    try:
        day = datetime.strptime(date.strip(), '%m/%d/%Y')
        try:
            clock = datetime.strptime(time.strip().upper(), '%I:%M %p')
        except ValueError:
            clock = datetime.strptime(time.strip(), '%H:%M')
        naive = day.replace(hour=clock.hour, minute=clock.minute)
    except ValueError:
        raise ValueError('Use a date like 10/10/2026 and a time like 6:00 PM.') from None
    start = naive.replace(tzinfo=EASTERN)
    if start.astimezone(timezone.utc).astimezone(EASTERN).replace(tzinfo=None) != naive:
        raise ValueError('That time is skipped by daylight saving. Choose another time.')
    if start.utcoffset() != start.replace(fold=1).utcoffset():
        raise ValueError('That time occurs twice when daylight saving ends. Choose a time before 1 AM or after 2 AM.')
    return start


async def database(fn, *args, **kwargs):
    def run():
        with closing(store.open_store()) as db:
            return fn(db, *args, **kwargs)
    return await asyncio.to_thread(run)


def admin(ctx):
    member = ctx.interaction.member
    return (ctx.interaction.guild_id == WARRIORS_UNITED_GUILD_ID and member is not None
            and bool(member.permissions & hikari.Permissions.ADMINISTRATOR))


async def require_admin(ctx):
    if not admin(ctx):
        await ctx.respond('Only Warriors United administrators can do this.', ephemeral=True)
        return False
    return True


async def refresh(*, force=False):
    global _last_refresh, _last_warning
    requested = time.monotonic()
    async with _refresh_lock:
        if not _last_refresh or requested-_last_refresh >= 60 or (force and _last_refresh < requested):
            board = await asyncio.to_thread(refresh_board)
            _last_warning = board['warning']
            _last_refresh = time.monotonic()
    return _last_warning


async def panel_data(event_id):
    from extensions.commands.loot_leaderboard import load_discord_labels
    data = await database(store.snapshot,event_id)
    owners = {row['user_id']:row['user_id'] for row in data['rows']}
    # Each ranked account has its own town hall and score.
    tags = [row['accounts'][0]['tag'] for row in data['rows'] if row['accounts']]
    labels, levels = await asyncio.gather(load_discord_labels(owners),load_town_halls(tags))
    data.update(labels=labels, levels=levels, warning=_last_warning)
    return data


def render(data):
    from extensions.commands.loot_leaderboard import profile_label, safe_name, stamp
    event = data['event']
    current = store.utcnow()
    started = event['starts_at'] and current >= datetime.fromisoformat(event['starts_at'])
    ended = event['ends_at'] and current >= datetime.fromisoformat(event['ends_at'])
    final = event['final_results'] is not None
    status = 'FINAL RESULTS' if final else 'ENDED • RESULTS PENDING' if ended else 'LIVE' if started else 'SIGNUP OPEN'
    signup = ('## ✅ JOIN NOW • BE READY AT THE START\n'
              '**Gold starts counting at the start time below.**\n'
              'Join now to enter your linked family accounts. Gold looted before the start does not count.'
              if not started else
              '**Gold counts only between the start and end times below.**\n'
              + ('Join to enter your linked family accounts. Late joins count from the event start.' if not ended else 'Signup is closed.'))
    parts = [
        Media(items=[MediaItem(media="assets/Gold_Rush.png")]),
        Text(content=f"# 🚨 {event['duration_hours']} HR GOLD RUSH EVENT!\n**{event['prize']} • {status}**"),
        Text(content="💰 **Warriors, it's time to raid for gold!**\nLoot the most gold in Farming + Ranked battles to win the Gold Pass."),
        Separator(divider=True),
        Text(content=signup),
        Text(content=f"**Starts:** {discord_time(event['starts_at'])}\n**Ends:** {discord_time(event['ends_at'])}"),
        Text(content='**Each account ranks separately.**\n🔥 Raid hard. Collect gold. Claim the crown!'),
    ]
    lines = []
    for index,row in enumerate(data['rows'],1):
        label = data.get('labels',{}).get(row['user_id'],'Discord profile')
        owner = f"[{profile_label(label)}](https://discord.com/users/{row['user_id']})"
        rank = ('🥇','🥈','🥉')[index-1] if index<=3 else f'**{index}.**'
        account = row['accounts'][0]
        level = data.get('levels',{}).get(account['tag'])
        th = str(getattr(emojis,f'TH{level}',f'TH{level}')) if level else '🏰'
        extra = f" +{len(row['accounts'])-1} accounts" if len(row['accounts'])>1 else ''
        lines.append(f"{rank} {th} **{safe_name(account['name'])}** — **{row['gold']:,} gold**\n"
                     f"-# `{account['tag']}` • {owner} • {safe_name(account['clan_name'] or 'WU Family')}{extra}")
    parts += [Separator(divider=True),Text(content='## 🏆 TOP 10 • ENTRANTS ONLY'),
              Text(content='\n\n'.join(lines) or ('No gold recorded yet.' if data['entrants'] else '**Be the first to join!**'))]
    if data.get('warning'):
        parts.append(Text(content='⚠️ Some battle data could not refresh. Scores may be incomplete.'))
    footer = f"-# {data['entrants']} joined • {data['accounts']} accounts • Tie: first to reach the score."
    if data.get('refreshed'):
        footer += f"\n-# Last refreshed: {discord_time(data['refreshed'])}"
    if not final:
        footer += '\n-# Auto-refresh: every 10 min'
    parts += [Separator(divider=True),Text(content=footer),ActionRow(components=[
        Button(style=hikari.ButtonStyle.SUCCESS,label='Join Gold Rush',emoji='💰',
               custom_id=f"goldrush_join:{event['id']}",is_disabled=bool(ended or final)),
        Button(style=hikari.ButtonStyle.SECONDARY,label='Update',emoji='🔄',
               custom_id=f"goldrush_update:{event['id']}"),
    ])]
    return [Container(accent_color=GOLDENROD_ACCENT,components=parts)]


async def sync_messages(event_id, components=None):
    bot = bot_data.data.get('bot')
    if bot is None:
        return
    components = components or render(await panel_data(event_id))
    messages = await database(lambda db: [dict(row) for row in db.execute(
        'SELECT * FROM goldrush_messages WHERE event_id=?',(event_id,))])
    for message in messages:
        try:
            await bot.rest.edit_message(int(message['channel_id']),int(message['message_id']),
                components=components,user_mentions=False,role_mentions=False,mentions_everyone=False)
        except hikari.NotFoundError:
            await database(lambda db: db.execute('DELETE FROM goldrush_messages WHERE message_id=?',(message['message_id'],)) and db.commit())
        except hikari.HTTPError:
            _log.warning('Could not refresh Gold Rush panel %s',message['message_id'],exc_info=True)


async def post(ctx,event):
    await ctx.defer(ephemeral=True)
    await refresh()
    components=render(await panel_data(event['id']))
    message=await ctx.interaction.app.rest.create_message(ctx.channel_id,components=components,
        user_mentions=False,role_mentions=False,mentions_everyone=False)
    await database(store.register_message,event['id'],ctx.channel_id,message.id)
    await ctx.interaction.delete_initial_response()


async def route_existing(ctx, *, edit=False):
    """Existing /loot-leaderboard panels switch to opt-in rankings once enabled."""
    event=await database(store.current_event,WARRIORS_UNITED_GUILD_ID)
    if event is None:
        return False
    if edit:
        await refresh(force=True)
        components=render(await panel_data(event['id']))
        await ctx.interaction.edit_initial_response(components=components,
            user_mentions=False,role_mentions=False,mentions_everyone=False)
        await database(store.register_message,event['id'],ctx.interaction.channel_id,ctx.interaction.message.id)
    else:
        await post(ctx,event)
    return True


@register_action('goldrush_join',no_return=True,preload_state=False)
async def join(ctx,action_id,**kwargs):
    if ctx.interaction.guild_id != WARRIORS_UNITED_GUILD_ID:
        await ctx.respond('Join from Warriors United.',ephemeral=True)
        return
    try:
        event=await database(store.get_event,action_id)
        if event['guild_id'] != str(ctx.interaction.guild_id):
            raise ValueError('This event belongs to another server.')
        links=await recruit_links.resolve(int(ctx.user.id),verify_owners=False)
        if len(links.unavailable)==2:
            raise ValueError('Account lookup is temporarily unavailable. Please try Join again shortly.')
        tags=await database(lambda db: [row[0] for row in db.execute('SELECT tag FROM players') if row[0] in links.sources])
        if not tags:
            raise ValueError('No eligible linked account found. Link your Clash account and ask staff to check the family roster.')
        added=await database(store.join_event,action_id,str(ctx.user.id),tags)
        count=await database(lambda db: db.execute('SELECT count(*) FROM goldrush_entries WHERE event_id=? AND user_id=?',(action_id,str(ctx.user.id))).fetchone()[0])
        notice='\nSome links could not load. Tap Join again later to add them.' if links.unavailable else ''
        await ctx.respond(f"{'✅ You joined Gold Rush!' if added else '✅ You are already entered.'}\n"
                          f"**{count} accounts entered.** Each ranks separately.\n"
                          + ('You are entered. Gold starts counting at '+discord_time(event['starts_at'])+'.' if event['starts_at'] and store.utcnow()<datetime.fromisoformat(event['starts_at']) else 'Gold counts from the event start.')+notice,ephemeral=True,
                          user_mentions=False,role_mentions=False,mentions_everyone=False)
        await sync_messages(action_id)
    except ValueError as error:
        await ctx.respond(str(error),ephemeral=True)


@register_action('goldrush_update',no_return=True,preload_state=False)
async def update(ctx,action_id,**kwargs):
    if ctx.interaction.guild_id != WARRIORS_UNITED_GUILD_ID:
        return
    event=await database(store.get_event,action_id)
    if event['guild_id'] != str(ctx.interaction.guild_id):
        return
    await refresh(force=True)
    components=render(await panel_data(action_id))
    await ctx.interaction.edit_initial_response(components=components,
        user_mentions=False,role_mentions=False,mentions_everyone=False)


@register_action('goldrush_confirm',no_return=True,preload_state=False)
async def confirm(ctx,action_id,**kwargs):
    if not await require_admin(ctx):
        return
    try:
        event=await database(store.confirm_schedule,action_id,str(ctx.user.id),str(ctx.interaction.guild_id))
        await ctx.interaction.edit_initial_response(components=[Container(accent_color=GOLDENROD_ACCENT,
            components=[Text(content='## ✅ Gold Rush schedule saved\nScores now use the new event window. Signups and battle history are preserved.')])])
        await sync_messages(event['id'])
    except ValueError as error:
        await ctx.respond(str(error),ephemeral=True)


@group.register()
class Post(lightbulb.SlashCommand,name='post',description='Post the Gold Rush signup and entrant leaderboard'):
    @lightbulb.invoke
    async def invoke(self,ctx:lightbulb.Context):
        if not await require_admin(ctx):
            return
        event=await database(store.ensure_current,WARRIORS_UNITED_GUILD_ID)
        await post(ctx,event)


@group.register()
class Configure(lightbulb.SlashCommand,name='configure',description='Preview and confirm a Gold Rush time change'):
    @lightbulb.invoke
    async def invoke(self,ctx:lightbulb.Context):
        if not await require_admin(ctx):
            return
        await ctx.respond_with_modal(title='Gold Rush • Eastern Time', custom_id=f'goldrush_schedule:{ctx.user.id}', components=[
            ModalRow().add_text_input('date','Start date (MM/DD/YYYY)',placeholder='10/10/2026',value=store.utcnow().astimezone(EASTERN).strftime('%m/%d/%Y'),required=True),
            ModalRow().add_text_input('time','Start time (Eastern)',placeholder='6:00 PM',required=True),
            ModalRow().add_text_input('hours','Duration in hours',value='24',required=True),
        ])


@register_action('goldrush_schedule',is_modal=True,no_return=True,preload_state=False)
async def schedule(ctx,action_id,**kwargs):
        if not await require_admin(ctx):
            return
        if str(ctx.user.id) != action_id:
            await ctx.respond('Open your own configure form.',ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            fields={c.custom_id:c.value for row in ctx.interaction.components for c in row}
            start=parse_eastern_start(fields.get('date',''),fields.get('time',''))
            try:
                hours=int(fields.get('hours',''))
            except ValueError:
                raise ValueError('Duration must be a number from 1 to 168 hours.') from None
            event=await database(store.ensure_current,WARRIORS_UNITED_GUILD_ID)
            change=await database(store.propose_schedule,event['id'],str(ctx.user.id),start,hours)
            from extensions.commands.loot_leaderboard import stamp
            future=start>store.utcnow() if start.tzinfo else False
            await ctx.interaction.edit_initial_response(components=[Container(accent_color=GOLDENROD_ACCENT,components=[
                Text(content='## ⚙️ Confirm Gold Rush schedule'),
                Text(content=f"**Start:** {discord_time(change['starts_at'])}\n**End:** {discord_time(change['ends_at'])}\n\n"
                     + ('**All current event scores will reset to 0 until the new start.**\n' if future else '**Scores will be recalculated for this time window.**\n')
                     + 'Signups stay. Saved battle history stays. Only gold inside this window counts.\nThis confirmation expires in 10 minutes.'),
                ActionRow(components=[Button(style=hikari.ButtonStyle.DANGER,label='Confirm schedule & reset scores',
                    custom_id=f"goldrush_confirm:{change['id']}")]),
            ])])
        except ValueError as error:
            await ctx.interaction.edit_initial_response(content=str(error))


@group.register()
class Finalize(lightbulb.SlashCommand,name='finalize',description='Refresh and lock the results after Gold Rush ends'):
    @lightbulb.invoke
    async def invoke(self,ctx:lightbulb.Context):
        if not await require_admin(ctx):
            return
        await ctx.defer(ephemeral=True)
        try:
            event=await database(store.current_event,WARRIORS_UNITED_GUILD_ID)
            if not event or not event['ends_at'] or store.utcnow()<datetime.fromisoformat(event['ends_at']):
                raise ValueError('Gold Rush has not ended yet.')
            if await refresh(force=True):
                raise ValueError('Some battle data could not refresh. Wait and try again before locking results.')
            await database(store.finalize_event,event['id'])
            await sync_messages(event['id'])
            await ctx.interaction.edit_initial_response(content='Results locked. Review the winner on the Gold Rush panel. Prize delivery is manual.')
        except ValueError as error:
            await ctx.interaction.edit_initial_response(content=str(error))


async def loop():
    while True:
        try:
            event=await database(store.current_event,WARRIORS_UNITED_GUILD_ID)
            if event and event['final_results'] is None:
                await refresh(force=True)
                await sync_messages(event['id'])
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception('Gold Rush automatic update failed; retrying next cycle')
        await asyncio.sleep(600)


@loader.listener(hikari.StartedEvent)
async def started(event):
    global _task
    _task=asyncio.create_task(loop(),name='goldrush-auto-update')


@loader.listener(hikari.StoppingEvent)
async def stopping(event):
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass


loader.command(group,guilds=[WARRIORS_UNITED_GUILD_ID])
