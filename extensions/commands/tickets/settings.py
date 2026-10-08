"""Owner-bound administrator settings; persistent config stays in ticket_setup.

Transient drafts use component_state. Audit entries use ticket_settings_audit in
that same settings database, never button_store or applicant ticket records.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import asyncio

import hikari
import lightbulb
from hikari.impl import (ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator, MessageActionRowBuilder as Row,
    ModalActionRowBuilder as ModalRow, SelectMenuBuilder as Select)
from extensions.components import register_action
from extensions.commands import ticket_runtime
from extensions.commands.tickets import perms, thread_service, console, setup
from utils.component_state import insert_state, get_state
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient

NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)
FIELDS = tuple(f'{kind}_{key}' for kind in ('main', 'fwa') for key in
               ('candidate_parent', 'staff_parent', 'thread_recruiter_role')) + (
               'ticket_staff_viewer_role_ids', 'ticket_inactivity_minutes', 'ticket_archive_quiet_days')
PANEL_LOCK = asyncio.Lock()


def member(ctx):
    return getattr(ctx, 'member', None) or getattr(ctx.interaction, 'member', None)


def guild(ctx):
    return int(getattr(ctx, 'guild_id', None) or getattr(ctx.interaction, 'guild_id', 0) or 0)


async def session(ctx, mongo, token):
    data = await get_state(mongo, token)
    if not data or data.get('type') != 'ticket_settings':
        raise ValueError('This panel expired. Open Ticket Settings in /manage again.')
    if data['user_id'] != int(ctx.user.id) or data['guild_id'] != guild(ctx):
        raise ValueError('Open your own Ticket Settings panel in this server.')
    if not await perms.is_target_admin(member(ctx), mongo):
        raise ValueError('Administrator permission is required in the ticket server.')
    return data


async def draft(mongo, data, **changes):
    data = deepcopy(data)
    data.update(changes, _id=uuid4().hex, type='ticket_settings')
    await insert_state(mongo, data, ttl=timedelta(minutes=30))
    return data


def button(token, action, label):
    return Row().add_interactive_button(hikari.ButtonStyle.SECONDARY,
        f'ticket_settings:{token}:{action}', label=label)


def channel(value):
    return f'<#{value}>' if value else 'Not configured'


def role(value):
    return f'<@&{value}>' if value else 'Not configured'


def duration(minutes):
    minutes = int(minutes)
    for unit, size in (('day', 1440), ('hour', 60), ('minute', 1)):
        if minutes % size == 0:
            value = minutes // size
            return f'{value} {unit}' + ('' if value == 1 else 's')


def page(data, notice=''):
    token, cfg, view = data['_id'], data['draft'], data.get('view', 'home')
    titles = {'home': 'Ticket Settings', 'timers': 'Inactivity & Archiving',
              'routing': 'Channels & Staff', 'main': 'Main Applications',
              'fwa': 'FWA Applications', 'access': 'Additional Staff Viewers',
              'tools': 'Troubleshooting', 'panels': 'Restore Ticket Messages'}
    body = [Text(content=f'-# Admin Settings › Recruitment\n## {titles.get(view, "Ticket Settings")}')]
    if notice:
        body.append(Text(content=notice[:3500]))

    def section(title, description, controls):
        body.extend([Separator(), Text(content=f'### {title}\n{description}'), *controls])

    def direct(action, label):
        return Row().add_interactive_button(hikari.ButtonStyle.SECONDARY,
            f'{action}:{token}', label=label)

    review = duration(cfg.get('ticket_inactivity_minutes', 10080))
    days = cfg.get('ticket_archive_quiet_days', 1)
    archive = duration(int(days) * 1440) if days else 'Off'
    if view == 'home':
        body.append(Text(content='Choose what you want to manage. These settings are only available to server administrators.'))
        section('Keep the ticket list tidy',
                f'**Open tickets:** ask recruiters to review after **{review}** of silence.\n'
                f'**Resolved tickets:** automatically archive after **{archive}** of silence.' if days else
                f'**Open tickets:** review after **{review}** of silence.\n**Automatic archiving is off.**',
                [button(token, 'timers', 'Manage inactivity & archiving')])
        section('Choose where tickets go',
                'Set the recruit and staff channels for Main and FWA applications, choose recruiters, or allow extra staff viewers.',
                [button(token, 'routing', 'Manage channels & staff')])
        section('Fix or test ticket setup',
                'Check bot permissions, restore missing ticket messages, or try the ticket flow in a separate test area.',
                [button(token, 'tools', 'Open troubleshooting')])
    elif view == 'timers':
        section('1 · Open tickets — ask staff to review',
                f'**Current wait: {review}.**\nAfter no human messages in the recruit thread, the bot asks recruiters whether to deny as Ghosted or keep waiting. It does not automatically deny or archive the ticket. Staff-thread chat does not reset this timer.',
                [direct('ticket_settings_interval', 'Change open-ticket review wait')])
        section('2 · Resolved tickets — archive quiet chats',
                f'**Current wait: {archive}.**\nApplies only to approved, denied, or closed tickets. Daily cleanup archives both threads after neither has human messages for this long. A new decision also starts a fresh wait. Bot messages do not reset it. History is kept; no new locks are added.',
                [direct('ticket_settings_archive', 'Change resolved-ticket archive wait')])
        body.append(Text(content='The form saves your new wait when you submit it. Set the archive wait to 0 to turn automatic archiving off.'))
    elif view == 'routing':
        section('Main applications', 'Choose where Main recruit and staff threads are created, and which role handles these applications.',
                [button(token, 'main', 'Configure Main applications')])
        section('FWA applications', 'Choose where FWA recruit and staff threads are created, and which role handles these applications.',
                [button(token, 'fwa', 'Configure FWA applications')])
        section('Other staff who may view tickets', 'Register additional roles already allowed to see the staff channel. This does not give them approval or denial powers.',
                [button(token, 'access', 'Manage additional viewers')])
    elif view in ('main', 'fwa'):
        body.append(Text(content='Select each setting below, then **Save channel & role changes**. These choices apply to new tickets; existing tickets stay where they are.'))
        for key, label, explanation in (
            ('candidate_parent', 'Recruit channel', 'New private recruit threads are created here. This must be the channel containing the application entry message.'),
            ('staff_parent', 'Staff channel', 'New staff discussion threads are created here. Only authorized staff should be able to view this channel.'),
            ('thread_recruiter_role', 'Recruiter role', 'Members of this role handle these applications and receive recruiter notifications.'),
        ):
            is_role = key.endswith('role')
            value = role(cfg.get(view+'_'+key)) if is_role else channel(cfg.get(view+'_'+key))
            section(label, f'**Selected:** {value}\n{explanation}', [Row(components=[Select(
                type=hikari.ComponentType.ROLE_SELECT_MENU if is_role else hikari.ComponentType.CHANNEL_SELECT_MENU,
                custom_id=f'ticket_settings:{token}:select:{view}_{key}', placeholder=f'Choose {label.lower()}', min_values=1, max_values=1)])])
        body.append(button(token, 'save', 'Save channel & role changes'))
    elif view == 'access':
        body.append(Text(content='Allow the bot to recognize extra staff roles that already have access to the staff channel. This does not change Discord permissions or grant approve/deny actions.\n\nFirst give the role access in Discord channel permissions, then select it here and save.'))
        section('Allowed viewer roles', ', '.join(role(x) for x in cfg.get('ticket_staff_viewer_role_ids', [])) or 'No additional roles selected.',
                [Row(components=[Select(type=hikari.ComponentType.ROLE_SELECT_MENU,
                 custom_id=f'ticket_settings:{token}:select:ticket_staff_viewer_role_ids', placeholder='Choose all additional viewer roles', min_values=0, max_values=25)]),
                 button(token, 'save', 'Save viewer roles')])
    elif view == 'tools':
        section('Check for setup problems', 'Check both ticket types for channel access, recruiter permissions, and ticket storage readiness. This check does not change your settings.',
                [button(token, 'validate', 'Run setup check')])
        section('Restore a missing or outdated message', 'Update or recreate the recruit application message or staff console using the saved layout.',
                [button(token, 'panels', 'Manage ticket messages')])
        section('Try the flow safely', 'Open the separate ticket testing controls. Test tickets use isolated storage and do not change live applications.',
                [button(token, 'testing', 'Open ticket testing')])
    elif view == 'panels':
        section('Recruit application message', f'**Channel:** {channel(data.get("entry_channel"))}\nUpdate the saved application message, or recreate it if deleted. Clicking below applies the repair immediately.',
                [button(token, 'repair_entry', 'Restore application message')])
        section('Staff console', f'**Channel:** {channel(data.get("console_channel"))}\nRefresh or recreate the staff ticket console. Select its current channel, or choose a channel for first-time setup. This cannot move an existing console. Clicking Restore applies immediately.',
                [Row(components=[Select(type=hikari.ComponentType.CHANNEL_SELECT_MENU, custom_id=f'ticket_settings:{token}:select:console_channel', placeholder='Choose the staff console channel',min_values=1,max_values=1)]),
                 button(token, 'repair_console', 'Restore staff console')])
    if view != 'home':
        body.append(Separator())
        if view in ('main', 'fwa', 'access'):
            body.append(Text(content='Selections are not saved until you press Save. Returning to all settings discards unsaved changes.'))
        body.append(button(token, 'home', 'Back to all settings'))
    if data.get('manage_token'):
        body.append(Row().add_interactive_button(hikari.ButtonStyle.SECONDARY,f'manage_home:{data["manage_token"]}',label='Back to server management'))
    return [Container(accent_color=GOLDENROD_ACCENT,components=body)]


async def fresh(ctx,mongo,data=None,**changes):
    cfg = await mongo.ticket_setup.find_one({'_id':'config'}) or {}
    state = await ticket_runtime.get_rollout(mongo)
    hub = await mongo.ticket_setup.find_one({'_id':console.HUB_STATE_ID}) or {}
    return await draft(mongo, data or {'user_id':int(ctx.user.id),'guild_id':guild(ctx)},
        baseline=cfg, draft=cfg, phase=state.phase, entry_channel=getattr(state.thread_intake,'channel_id',None),
        console_channel=hub.get('channel_id'),view='home',**changes)


async def open_dashboard(ctx,mongo,*,manage_token=None,deferred=False):
    if not deferred:
        await ctx.defer(ephemeral=True)
    if not await perms.is_target_admin(member(ctx),mongo):
        await ctx.interaction.edit_initial_response(content='Administrator permission is required in the ticket server.',**NO_MENTIONS)
        return
    data=await fresh(ctx,mongo,manage_token=manage_token)
    await ctx.interaction.edit_initial_response(components=page(data),**NO_MENTIONS)


async def validate(mongo,rest,cfg,gid):
    me=await rest.fetch_my_user()
    for kind in ('main','fwa'):
        parents=thread_service.parents_from_config(cfg,gid,kind)
        await thread_service.validate_thread_parents(rest,parents,bot_user_id=int(me.id))
    state=await ticket_runtime.get_rollout(mongo)
    if not state.valid or not state.thread_intake or state.thread_intake.guild_id!=gid:
        raise ValueError('The active entry-panel binding is unavailable. Nothing was saved.')
    if any(int(cfg.get(f'{kind}_candidate_parent') or 0)!=state.thread_intake.channel_id for kind in ('main','fwa')):
        raise ValueError('Candidate channels must match the active entry panel. Moving intake requires a coordinated binding change; nothing was saved.')


async def save(ctx,mongo,rest,data):
    cfg=data['draft'];baseline=data['baseline']
    changes={k:cfg.get(k) for k in FIELDS if cfg.get(k)!=baseline.get(k)}
    if not changes:return 'No changes to save.'
    await validate(mongo,rest,cfg,guild(ctx))
    # Compare every relevant setting; two admins cannot silently overwrite one another.
    query={'_id':'config','ticket_target_guild_id':guild(ctx)}
    for k in (*FIELDS,'ticket_settings_revision'):
        query[k]=baseline[k] if k in baseline else {'$exists':False}
    audit=mongo.ticket_setup.database.get_collection('ticket_settings_audit')
    aid=uuid4().hex
    await audit.insert_one({'_id':aid,'guild_id':guild(ctx),'actor_id':int(ctx.user.id),'at':datetime.now(timezone.utc),'state':'pending','before':{k:baseline.get(k) for k in changes},'after':changes})
    result=await mongo.ticket_setup.update_one(query,{'$set':changes,'$inc':{'ticket_settings_revision':1}})
    await audit.update_one({'_id':aid},{'$set':{'state':'committed' if result.matched_count else 'conflict'}})
    if not result.matched_count:raise ValueError('Settings changed while you were editing. Return to Ticket Settings and try again.')
    return 'Settings validated and saved.'


async def repair_entry(ctx,mongo,bot):
    async with PANEL_LOCK:
        cfg=await mongo.ticket_setup.find_one({'_id':'config'}) or {}
        await validate(mongo,bot.rest,cfg,guild(ctx))
        state=await ticket_runtime.get_rollout(mongo)
        source=state.thread_intake
        payload=await setup.saved_public_ticket_embed(mongo,guild(ctx))
        me=await bot.rest.fetch_my_user()
        try:
            old=await bot.rest.fetch_message(source.channel_id,source.message_id)
        except hikari.NotFoundError:
            old=None
        if old:
            if int(old.author.id)!=int(me.id):raise ValueError('The bound entry message is not owned by this bot.')
            await bot.rest.edit_message(source.channel_id,source.message_id,components=payload,**NO_MENTIONS)
            return 'Entry panel updated.'
        new=await bot.rest.create_message(source.channel_id,components=payload,**NO_MENTIONS)
        try:
            await ticket_runtime.configure_rollout(mongo,expected_revision=state.revision,actor_id=int(ctx.user.id),
                legacy_intake=state.legacy_intake,
                thread_intake=ticket_runtime.IntakeSource(guild(ctx),source.channel_id,int(new.id)),
                pilot={'intake':{'guild_id':state.pilot_intake.guild_id,'channel_id':state.pilot_intake.channel_id,'message_id':state.pilot_intake.message_id},'user_ids':list(state.pilot_user_ids),'role_ids':list(state.pilot_role_ids),'ticket_types':list(state.pilot_ticket_types)})
        except Exception:
            await bot.rest.delete_message(source.channel_id,new.id)
            raise
        return 'Missing entry panel recreated and bound.'


@register_action('ticket_settings',preload_state=False,no_return=True)
@lightbulb.di.with_di
async def action(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,bot:hikari.GatewayBot=lightbulb.di.INJECTED,**_):
    token,op,*args=action_id.split(':')
    try:
        data=await session(ctx,mongo,token);notice=''
        if op in ('home','timers','routing','tools','main','fwa','access','panels'):
            data=await fresh(ctx,mongo,data) if op=='home' else await draft(mongo,data,view=op)
        elif op=='select':
            key=args[0];values=[int(x) for x in ctx.interaction.values]
            allowed={f'{data.get("view")}_{k}' for k in ('candidate_parent','staff_parent','thread_recruiter_role')} if data.get('view') in ('main','fwa') else {'ticket_staff_viewer_role_ids'} if data.get('view')=='access' else {'console_channel'} if data.get('view')=='panels' else set()
            if key not in allowed:raise ValueError('This setting is not available in this panel.')
            if key=='console_channel':data=await draft(mongo,data,console_channel=values[0])
            else:
                cfg=deepcopy(data['draft']);cfg[key]=values if key=='ticket_staff_viewer_role_ids' else values[0]
                data=await draft(mongo,data,draft=cfg)
        elif op=='save':
            notice=await save(ctx,mongo,bot.rest,data);data=await fresh(ctx,mongo,data)
        elif op=='validate':
            cfg=await mongo.ticket_setup.find_one({'_id':'config'}) or {}
            await validate(mongo,bot.rest,cfg,guild(ctx))
            from extensions.commands import tickets
            notice='Main and FWA permissions passed. '+('Storage indexes healthy.' if not tickets.startup_index_errors else 'Storage index issues: '+', '.join(tickets.startup_index_errors))
        elif op=='repair_entry':notice=await repair_entry(ctx,mongo,bot)
        elif op=='repair_console':
            await console.configure_hub_here(bot,mongo,guild_id=guild(ctx),channel_id=int(data.get('console_channel') or 0));notice='Recruiter console saved and repaired.'
        elif op=='testing':
            from extensions.commands.tickets import testing
            await testing.open_dashboard(ctx,mongo,deferred=True,return_action=f"ticket_settings:{token}:home");return
        else:raise ValueError('Unknown Ticket Settings action.')
        await ctx.interaction.edit_initial_response(components=page(data,notice),**NO_MENTIONS)
    except (ValueError,thread_service.ThreadConfigurationError,ticket_runtime.TicketRuntimeError,console.ConsoleConfigurationError) as exc:
        await ctx.respond(str(exc),ephemeral=True,**NO_MENTIONS)


@register_action('ticket_settings_interval',opens_modal=True,preload_state=False,no_return=True)
@lightbulb.di.with_di
async def interval(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,**_):
    try:data=await session(ctx,mongo,action_id)
    except ValueError as exc:
        await ctx.respond(str(exc),ephemeral=True);return
    await ctx.respond_with_modal(title='Open Ticket Review Wait',custom_id=f'ticket_settings_interval_submit:{action_id}',components=[ModalRow().add_text_input('days','Quiet days before staff review (1–365)',value=str(data['draft'].get('ticket_inactivity_minutes',10080) / 1440).removesuffix('.0'),min_length=1,max_length=10)])


@register_action('ticket_settings_interval_submit',is_modal=True,preload_state=False,no_return=True)
@lightbulb.di.with_di
async def interval_submit(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,bot:hikari.GatewayBot=lightbulb.di.INJECTED,**_):
    await ctx.defer(ephemeral=True)
    try:
        data=await session(ctx,mongo,action_id)
        from extensions.commands.tickets.testing import _modal_value
        from decimal import Decimal, InvalidOperation
        try:
            days=Decimal(_modal_value(ctx,'days'))
            if not days.is_finite() or not 1<=days<=365:raise ValueError('Use 1–365 days.')
            value=int(days*1440)
        except InvalidOperation:
            raise ValueError('Enter a number of days, such as 7.')
        cfg=deepcopy(data['draft']);cfg['ticket_inactivity_minutes']=value;data['draft']=cfg
        notice=await save(ctx,mongo,bot.rest,data);data=await fresh(ctx,mongo,data)
        await ctx.interaction.edit_initial_response(components=page(data,notice),**NO_MENTIONS)
    except (ValueError,thread_service.ThreadConfigurationError) as exc:
        await ctx.interaction.edit_initial_response(content=str(exc),**NO_MENTIONS)


@register_action('ticket_settings_archive',opens_modal=True,preload_state=False,no_return=True)
@lightbulb.di.with_di
async def archive_interval(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,**_):
    try:data=await session(ctx,mongo,action_id)
    except ValueError as exc:
        await ctx.respond(str(exc),ephemeral=True);return
    await ctx.respond_with_modal(title='Resolved Ticket Archive Wait',custom_id=f'ticket_settings_archive_submit:{action_id}',components=[ModalRow().add_text_input('days','Quiet days in BOTH threads (0 = off)',value=str(data['draft'].get('ticket_archive_quiet_days',1)),min_length=1,max_length=3)])


@register_action('ticket_settings_archive_submit',is_modal=True,preload_state=False,no_return=True)
@lightbulb.di.with_di
async def archive_interval_submit(ctx,action_id:str,mongo:MongoClient=lightbulb.di.INJECTED,bot:hikari.GatewayBot=lightbulb.di.INJECTED,**_):
    await ctx.defer(ephemeral=True)
    try:
        data=await session(ctx,mongo,action_id)
        from extensions.commands.tickets.testing import _modal_value
        from .auto_archive import quiet_days
        cfg=deepcopy(data['draft']);cfg['ticket_archive_quiet_days']=int(_modal_value(ctx,'days'))
        quiet_days(cfg);data['draft']=cfg
        notice=await save(ctx,mongo,bot.rest,data);data=await fresh(ctx,mongo,data)
        await ctx.interaction.edit_initial_response(components=page(data,notice),**NO_MENTIONS)
    except (ValueError,thread_service.ThreadConfigurationError) as exc:
        await ctx.interaction.edit_initial_response(content=str(exc),**NO_MENTIONS)


@register_action('ticket_admin_settings',opens_modal=True,preload_state=False,no_return=True)
@lightbulb.di.with_di
async def console_admin_settings(ctx,mongo:MongoClient=lightbulb.di.INJECTED,**_):
    await open_dashboard(ctx,mongo)
