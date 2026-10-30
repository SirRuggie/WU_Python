"""Private Components V2 strike views and automatic ended-war monitor."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import logging
import traceback
import uuid
import os
import sqlite3
import time

import coc
import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text

from extensions.components import register_action
from utils import recruit_links
from utils.component_state import get_state, insert_state, update_state
from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils.mongo import MongoClient
from utils.strike_store import STRIKE_DAYS, StrikeService, tag, utc
from utils.strike_tracking import StrikeTracking
from utils.strike_official import normalize as normalize_official_war
from utils.replacement_filters import parse_weight, compact_weight
from cwl_web.providers import LiveProviders, ProviderUnavailable

loader = lightbulb.Loader()
strikes = lightbulb.Group('strikes', 'View account strikes and find replacements',
    contexts=[hikari.ApplicationContextType.GUILD],
    integration_types=[hikari.ApplicationIntegrationType.GUILD_INSTALL])
NO_MENTIONS = {'user_mentions': False, 'role_mentions': False, 'mentions_everyone': False}
PAGE_SIZE = 8
POLL_SECONDS = 10 * 60
_task = None
_weight_provider = LiveProviders(coc_token="", mongo_uri="")
_weight_cache = {}
_weight_cache_at = 0.0
_weight_retry_at = 0.0
_weight_refresh_task = None
_weight_warm_task = None
_weight_cached_tags = set()
_WEIGHT_TTL_SECONDS = 10 * 60
_WEIGHT_RETRY_SECONDS = 60


async def authorized(ctx, mongo, scope='strikes_read') -> bool:
    # Read shared dashboard grants on every command and component action.
    if int(ctx.interaction.guild_id or 0) != WARRIORS_UNITED_GUILD_ID:
        return False
    member = getattr(ctx.interaction, 'member', None)
    if member is None:
        return False
    if member.permissions & hikari.Permissions.ADMINISTRATOR:
        return True
    from utils.dashboard_access import dashboard_allowed
    return await dashboard_allowed({'user_id': str(ctx.user.id), 'role_ids': getattr(member, 'role_ids', ())}, scope, mongo)


def panel(title: str, *lines: str, buttons=None):
    children = [Text(content=f'## {title}')]
    children.extend(Text(content=line) for line in lines if line)
    if buttons:
        row = hikari.impl.MessageActionRowBuilder()
        for custom_id, label, enabled in buttons:
            row.add_interactive_button(hikari.ButtonStyle.SECONDARY, custom_id,
                                       label=label, is_disabled=not enabled)
        children.append(row)
    return [Container(accent_color=0xD9A441, components=children)]


def safe(value, length=90):
    return str(value or '').replace('@', '＠').replace('<', '‹').replace('>', '›').replace('`', 'ˋ')[:length]


async def roles(guild_id: int, member_id: int, bot: hikari.GatewayBot):
    try:
        member = await bot.rest.fetch_member(guild_id, member_id)
    except hikari.NotFoundError:
        # A confirmed absent member has no roles in this server.
        return []
    except hikari.HTTPError:
        return None
    return [int(item) for item in member.role_ids]


def service(mongo, bot):
    return StrikeService(mongo, role_resolver=lambda guild, member: roles(guild, member, bot))


async def history_panel(store, state, page=0):
    result = await store.history(state['guild_id'], member_id=state.get('member_id'),
        player_tag=state.get('player_tag'), clan_tag=state.get('clan_tag'), status=state.get('status', 'strikes'),
        limit=PAGE_SIZE, skip=page*PAGE_SIZE)
    pages = max(1, math.ceil(result['total']/PAGE_SIZE))
    page = min(max(page, 0), pages-1)
    if page*PAGE_SIZE >= result['total'] and result['total']:
        result = await store.history(state['guild_id'], member_id=state.get('member_id'),
            player_tag=state.get('player_tag'), clan_tag=state.get('clan_tag'), status=state.get('status', 'strikes'),
            limit=PAGE_SIZE, skip=page*PAGE_SIZE)
    tags = list({row['player_tag'] for row in result['items']})
    profiles = await store.mongo.strike_profiles.find(
        {'guild_id': state['guild_id'], 'player_tag': {'$in': tags}}).to_list(length=None)
    current_clans = {row['player_tag']: row.get('current_clan_tag') for row in profiles}
    lines = []
    for row in result['items']:
        when = int(row['occurred_at'].replace(tzinfo=timezone.utc).timestamp()) if row['occurred_at'].tzinfo is None else int(row['occurred_at'].timestamp())
        status = 'CWL · No strikes' if row.get('kind') == 'cwl' else row['status'].title()
        name = safe(row.get('player_name') or row['player_tag'], 36)
        clan = safe(row.get('clan_tag') or 'Clan unknown', 18)
        current = safe(current_clans.get(row['player_tag']) or 'Unknown', 18)
        linked = (f"Discord {row['member_id']}" if row.get('member_id') else
                  'Link needs review' if row.get('link_status') in ('unknown', 'conflict', 'pending') else 'Not linked')
        lines.append(f"**{name}** `{row['player_tag']}` · {status} · {linked}\n"
                     f"War: {clan} · Now: {current} · <t:{when}:d>\n"
                     f"{safe(row.get('reason'), 100)}\n"
                     f"ID: `{row['_id']}`")
    return panel('Strike history', '\n\n'.join(lines) or 'No records found.',
                 f'Page {page+1} of {pages} · {result["total"]} records',
                 buttons=[(f'strike_page:{state["_id"]}|{page-1}', 'Previous', page>0),
                          (f'strike_page:{state["_id"]}|{page+1}', 'Next', page+1<pages)])


async def _state(ctx, mongo, token):
    state = await get_state(mongo, token)
    if (state is None or state.get('user_id') != int(ctx.user.id)
            or state.get('guild_id') != int(ctx.interaction.guild_id or 0)):
        return None
    return state


@register_action('strike_page')
@lightbulb.di.with_di
async def page(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    token, page_text = action_id.split('|', 1)
    state = await _state(ctx, mongo, token)
    if state is None or not await authorized(ctx, mongo):
        return panel('Strike history', 'This view expired. Run /strikes view again.')
    try:
        number = int(page_text)
    except ValueError:
        number = 0
    return await history_panel(StrikeService(mongo), state, number)


@strikes.register()
class View(lightbulb.SlashCommand, name='view', description='View strike history by member, player, or clan'):
    member = lightbulb.user('member', 'Discord member', default=None)
    player = lightbulb.string('player', 'Clash player tag', default=None)
    clan = lightbulb.string('clan', 'Clan tag where strikes happened', default=None)
    status = lightbulb.string('status', 'Records to show', default='strikes', choices=[
        lightbulb.Choice('Strikes', 'strikes'), lightbulb.Choice('All records', 'all'),
        lightbulb.Choice('One missed', 'missed'), lightbulb.Choice('CWL · No strikes', 'cwl')])

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED):
        await ctx.defer(ephemeral=True)
        if not await authorized(ctx, mongo):
            await ctx.respond('Staff access required.', ephemeral=True)
            return
        if sum(value is not None for value in (self.member, self.player, self.clan)) > 1:
            await ctx.respond('Choose one filter: member, player, or clan.', ephemeral=True)
            return
        state = {'_id': uuid.uuid4().hex, 'user_id': int(ctx.user.id),
                 'guild_id': int(ctx.guild_id), 'member_id': int(self.member.id) if self.member else None,
                 'player_tag': tag(self.player) if self.player else None,
                 'clan_tag': tag(self.clan) if self.clan else None, 'status': self.status}
        await insert_state(mongo, state)
        try:
            components = await history_panel(StrikeService(mongo), state)
        except (RuntimeError, ValueError) as error:
            components = panel('Strike history', safe(error, 250))
        await ctx.respond(components=components, ephemeral=True, **NO_MENTIONS)


@strikes.register()
class Add(lightbulb.SlashCommand, name='add', description='Give one player account a strike'):
    reason = lightbulb.string('reason', 'Why this account gets a strike', max_length=500)
    member = lightbulb.user('member', 'Choose from this member’s linked accounts', default=None)
    player = lightbulb.string('player', 'Or enter a Clash player tag', default=None)

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED):
        await ctx.defer(ephemeral=True)
        if not await authorized(ctx, mongo, 'strikes_add'):
            await ctx.respond('Staff access required.', ephemeral=True)
            return
        if bool(self.member) == bool(self.player):
            await ctx.respond('Choose a Discord member or player tag.', ephemeral=True)
            return
        store = StrikeService(mongo)
        if self.player:
            try:
                player = tag(self.player)
                owners = await recruit_links.resolve_players([player])
                if owners.unavailable or owners.conflicts:
                    raise ValueError('Account links could not be checked. Try again.')
                account = await coc_client.get_player(player)
                clan_tag = getattr(getattr(account, 'clan', None), 'tag', None)
                row = await store.add_manual(int(ctx.guild_id), player, self.reason,
                    int(ctx.user.id), member_id=owners.owners.get(player),
                    clan_tag=clan_tag, player_name=account.name,
                    request_id=str(ctx.interaction.id))
            except ValueError as error:
                await ctx.respond(safe(error, 250), ephemeral=True)
                return
            except Exception:
                await ctx.respond('Player lookup is unavailable. Try again later.', ephemeral=True)
                return
            await ctx.respond(components=panel('Strike added',
                f"`{row['player_tag']}` · Expires in {STRIKE_DAYS} days\n{safe(row['reason'], 500)}"),
                ephemeral=True, **NO_MENTIONS)
            return
        links = await recruit_links.resolve(int(self.member.id))
        if links.unavailable or links.conflicts:
            await ctx.respond('Account links are unavailable or disputed. Try again later.', ephemeral=True)
            return
        tags = list(links.sources)
        if not tags:
            await ctx.respond('This member has no linked player accounts.', ephemeral=True)
            return
        state = {'_id': uuid.uuid4().hex, 'guild_id': int(ctx.guild_id),
                 'user_id': int(ctx.user.id), 'member_id': int(self.member.id),
                 'reason': self.reason, 'tags': tags[:25], 'request_id': str(ctx.interaction.id)}
        await insert_state(mongo, state)
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(f'strike_pick:{state["_id"]}',
            placeholder='Choose the account to strike', min_values=1, max_values=1)
        for player in state['tags']:
            menu.add_option(player, player)
        await ctx.respond(components=[Container(accent_color=0xD9A441, components=[
            Text(content='## Choose an account'),
            Text(content=f'{len(tags)} linked account(s). Select the account that gets this strike.'),
            menu_row])], ephemeral=True, **NO_MENTIONS)


@register_action('strike_pick')
@lightbulb.di.with_di
async def pick(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
               coc_client: coc.Client = lightbulb.di.INJECTED, **kwargs):
    state = await _state(ctx, mongo, action_id)
    if state is None or not await authorized(ctx, mongo, 'strikes_add'):
        return panel('Strike', 'This selection expired or staff access changed.')
    selected = ctx.interaction.values[0]
    if selected not in state['tags']:
        return panel('Strike', 'Choose an account from this menu.')
    links = await recruit_links.resolve(state['member_id'])
    if links.unavailable or selected not in links.sources or selected in links.conflicts:
        return panel('Strike', 'Account links changed. Run /strikes add again.')
    try:
        account = await coc_client.get_player(selected)
        clan_tag = getattr(getattr(account, 'clan', None), 'tag', None)
        row = await StrikeService(mongo).add_manual(state['guild_id'], selected,
            state['reason'], state['user_id'], member_id=state['member_id'],
            clan_tag=clan_tag, player_name=account.name,
            request_id=state['request_id'])
    except ValueError as error:
        return panel('Strike', safe(error, 250))
    except Exception:
        return panel('Strike', 'Player lookup is unavailable. Try again later.')
    return panel('Strike added', f"`{row['player_tag']}` · Expires in {STRIKE_DAYS} days\n{safe(row['reason'], 500)}")


@strikes.register()
class Remove(lightbulb.SlashCommand, name='remove', description='Remove one strike, keeping an audit record'):
    strike_id = lightbulb.string('strike-id', 'Strike ID shown in history')
    reason = lightbulb.string('reason', 'Why this strike is removed', max_length=500)

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED):
        await ctx.defer(ephemeral=True)
        if not await authorized(ctx, mongo, 'strikes_remove'):
            await ctx.respond('Staff access required.', ephemeral=True)
            return
        try:
            row = await StrikeService(mongo).revoke(ctx.guild_id, self.strike_id, ctx.user.id, self.reason)
        except ValueError as error:
            await ctx.respond(safe(error, 250), ephemeral=True)
            return
        await ctx.respond(components=panel('Strike removed',
            f"`{row['player_tag']}` · {safe(row['revoke_reason'], 500)}"), ephemeral=True, **NO_MENTIONS)


REPLACEMENT_PAGE_SIZE = 5
CLAN_OPTIONS_PAGE_SIZE = 24
REPLACEMENT_SORTS = {'priority': 'Priority', 'weight': 'Closest weight', 'strikes': 'Most strikes', 'th': 'Town Hall'}


def replacement_browser_line(index, row, clan_names):
    player = safe(row.get('player_name') or row['player_tag'], 32)
    clan = safe(clan_names.get(row.get('current_clan_tag'), row.get('current_clan_tag') or 'Unknown clan'), 40)
    th = row.get('town_hall')
    th_text = f'TH{th}' if isinstance(th, int) and th > 0 else 'TH?'
    priority = {'replace_first': 'Chopping Block', 'high': 'High', 'normal': 'Normal'}.get(
        row.get('replacement_priority'), 'Normal')
    weight = compact_weight(row.get('weight')) if row.get('weight') else 'Weight unknown'
    gap = row.get('weight_difference')
    gap_text = f' · Gap {compact_weight(gap) if gap else "0k"}' if isinstance(gap, int) else ''
    strikes = int(row.get('active_strikes') or 0)
    stale = ' · Last known' if row.get('clan_is_current') is False else ''
    return (f"**{index}. {player}** `{row['player_tag']}`\n"
            f"{clan}{stale} · {th_text} · {weight}{gap_text}\n"
            f"{priority} · {strikes} active {'strike' if strikes == 1 else 'strikes'}")


def replacement_sort_rows(rows, mode, weight):
    priority = {'replace_first': 0, 'high': 1, 'normal': 2}
    def key(row):
        marked = priority.get(row.get('replacement_priority'), 2)
        strikes = -int(row.get('active_strikes') or 0)
        th = -(row.get('town_hall') or 0)
        gap = row.get('weight_difference')
        missing_weight = row.get('weight') is None
        tie = row['player_tag']
        if mode == 'weight' and weight is not None:
            return (gap is None, gap if gap is not None else 0, marked, strikes, tie)
        if mode == 'strikes':
            return (strikes, marked, missing_weight, gap or 0, tie)
        if mode == 'th':
            return (th, marked, strikes, missing_weight, tie)
        return (marked, strikes, missing_weight, gap or 0, tie)
    return sorted(rows, key=key)


def _replacement_button_row(*buttons):
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, enabled in buttons:
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY, custom_id,
                                   label=label, is_disabled=not enabled)
    return row


def _replacement_menu(action, token, placeholder, options, selected):
    row = hikari.impl.MessageActionRowBuilder()
    menu = row.add_text_menu(f'{action}:{token}', placeholder=placeholder,
                             min_values=1, max_values=1)
    for label, value in options:
        menu.add_option(label[:100], value, is_default=value == selected)
    return row


async def replacement_panel(store, state, *, notice=''):
    guild = state['guild_id']
    clans = await store.mongo.clans.find({'tag': {'$type': 'string'}},
                                         {'tag': 1, 'name': 1}).to_list(length=None)
    clans = sorted(clans, key=lambda row: (str(row.get('name') or '').casefold(), row['tag']))
    clan_names = {tag(row['tag']): row.get('name') or row['tag'] for row in clans}
    selected_clan = state.get('clan_tag')
    weight = state.get('weight')
    th = state.get('town_hall')
    sort_mode = state.get('sort', 'priority')
    profiles = await store.mongo.strike_profiles.find({'guild_id': guild}, {'player_tag': 1}).to_list(length=None)
    weights = cached_weights([row['player_tag'] for row in profiles])
    rows = await store.replacement(guild, weight, clan_tag=selected_clan,
                                   town_hall=th, browse_all=True, family_scope='all',
                                   limit=5000, weights=weights)
    rows = [row for row in rows if row.get('active_strikes', 0) > 0 or row.get('is_manual')]
    rows = replacement_sort_rows(rows, sort_mode, weight)
    pages = max(1, math.ceil(len(rows) / REPLACEMENT_PAGE_SIZE))
    page = min(max(0, int(state.get('page', 0))), pages - 1)
    start = page * REPLACEMENT_PAGE_SIZE
    showing = rows[start:start + REPLACEMENT_PAGE_SIZE]
    clan_pages = max(1, math.ceil(len(clans) / CLAN_OPTIONS_PAGE_SIZE))
    clan_page = min(max(0, int(state.get('clan_page', 0))), clan_pages - 1)
    clan_slice = clans[clan_page*CLAN_OPTIONS_PAGE_SIZE:(clan_page+1)*CLAN_OPTIONS_PAGE_SIZE]
    filters = [clan_names.get(selected_clan, 'All clans'), f'TH{th}' if th else 'All TH',
               f'Weight {compact_weight(weight)}' if weight else 'No weight',
               REPLACEMENT_SORTS.get(sort_mode, 'Priority')]
    children = [Text(content='## Replacements'),
                Text(content=' · '.join(safe(item, 60) for item in filters))]
    messages = []
    if state.get('refresh_warning'):
        messages.append('Some clans could not refresh; showing last known data.')
    if notice:
        messages.append(safe(notice, 180))
    if messages:
        children.append(Text(content='\n'.join(messages)))
    if showing:
        children.append(Text(content='\n\n'.join(
            replacement_browser_line(start + index, row, clan_names)
            for index, row in enumerate(showing, 1))))
    else:
        children.append(Text(content='No accounts match these filters.'))
    children.append(Text(content=f'Page {page+1}/{pages} · {len(rows)} accounts'))
    token = state['_id']
    children.append(_replacement_menu('strike_replace_clan', token, 'Clan',
        [('All clans', 'all')] + [(safe(row.get('name') or row['tag'], 75), tag(row['tag'])) for row in clan_slice],
        selected_clan or 'all'))
    children.append(_replacement_menu('strike_replace_th', token, 'Town Hall',
        [('All Town Halls', 'all')] + [(f'TH{number}', str(number)) for number in range(1, 21)],
        str(th) if th else 'all'))
    children.append(_replacement_menu('strike_replace_sort', token, 'Sort by',
        [(label, mode) for mode, label in REPLACEMENT_SORTS.items()], sort_mode))
    page_buttons = [
        (f'strike_replace_page:{token}|{page-1}', 'Previous', page > 0),
        (f'strike_replace_page:{token}|{page+1}', 'Next', page+1 < pages)]
    if clan_pages > 1:
        page_buttons.extend([
            (f'strike_replace_clan_page:{token}|{clan_page-1}', 'Clans ◀', clan_page > 0),
            (f'strike_replace_clan_page:{token}|{clan_page+1}', 'Clans ▶', clan_page+1 < clan_pages)])
    children.append(_replacement_button_row(*page_buttons))
    children.append(_replacement_button_row(
        (f'strike_replace_weight:{token}', 'Set weight', True),
        (f'strike_replace_clear:{token}', 'Clear filters', bool(selected_clan or th or weight or sort_mode != 'priority'))))
    return [Container(accent_color=0xD9A441, components=children)]


async def _replacement_action_state(ctx, mongo, token):
    state = await _state(ctx, mongo, token)
    if state is None or not await authorized(ctx, mongo):
        return None
    return state


async def _replacement_denied(ctx):
    # Public panels must not be overwritten by another member's button click.
    await ctx.respond('Run /strikes replacements to open your own view.', ephemeral=True)
    return None


async def _replacement_update(ctx, mongo, token, changes, *, notice=''):
    state = await _replacement_action_state(ctx, mongo, token)
    if state is None:
        return await _replacement_denied(ctx)
    await update_state(mongo, token, {'$set': changes})
    state.update(changes)
    return await replacement_panel(StrikeService(mongo), state, notice=notice)


@register_action('strike_replace_clan', preload_state=False)
@lightbulb.di.with_di
async def replacement_clan(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    if await _replacement_action_state(ctx, mongo, action_id) is None:
        return await _replacement_denied(ctx)
    selected = ctx.interaction.values[0]
    if selected != 'all':
        try:
            selected = tag(selected)
        except ValueError:
            return panel('Replacements', 'Choose a clan from the menu.')
        if not await mongo.clans.find_one({'tag': selected}):
            return panel('Replacements', 'That clan is no longer registered.')
    return await _replacement_update(ctx, mongo, action_id,
                                     {'clan_tag': None if selected == 'all' else selected, 'page': 0})


@register_action('strike_replace_th', preload_state=False)
@lightbulb.di.with_di
async def replacement_th(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    if await _replacement_action_state(ctx, mongo, action_id) is None:
        return await _replacement_denied(ctx)
    selected = ctx.interaction.values[0]
    try:
        th = None if selected == 'all' else int(selected)
        if th is not None and not 1 <= th <= 20:
            raise ValueError
    except ValueError:
        return panel('Replacements', 'Choose a Town Hall from the menu.')
    return await _replacement_update(ctx, mongo, action_id, {'town_hall': th, 'page': 0})


@register_action('strike_replace_sort', preload_state=False)
@lightbulb.di.with_di
async def replacement_sort(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    if await _replacement_action_state(ctx, mongo, action_id) is None:
        return await _replacement_denied(ctx)
    selected = ctx.interaction.values[0]
    if selected not in REPLACEMENT_SORTS:
        return panel('Replacements', 'Choose a sort from the menu.')
    state = await _replacement_action_state(ctx, mongo, action_id)
    if state is None:
        return await _replacement_denied(ctx)
    if selected == 'weight' and state.get('weight') is None:
        return await replacement_panel(StrikeService(mongo), state, notice='Set a weight first.')
    return await _replacement_update(ctx, mongo, action_id, {'sort': selected, 'page': 0})


@register_action('strike_replace_page', preload_state=False)
@lightbulb.di.with_di
async def replacement_page(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    token, raw = action_id.split('|', 1)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    return await _replacement_update(ctx, mongo, token, {'page': page})


@register_action('strike_replace_clan_page', preload_state=False)
@lightbulb.di.with_di
async def replacement_clan_page(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    token, raw = action_id.split('|', 1)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    return await _replacement_update(ctx, mongo, token, {'clan_page': page})


@register_action('strike_replace_clear', preload_state=False)
@lightbulb.di.with_di
async def replacement_clear(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    return await _replacement_update(ctx, mongo, action_id,
        {'clan_tag': None, 'town_hall': None, 'weight': None, 'sort': 'priority', 'page': 0, 'clan_page': 0})


@register_action('strike_replace_weight', opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def replacement_weight(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    if await _replacement_action_state(ctx, mongo, action_id) is None:
        await ctx.respond('This view expired or access changed. Run /strikes replacements again.', ephemeral=True)
        return
    await ctx.respond_with_modal(title='Recruit war weight',
        custom_id=f'strike_replace_weight_submit:{action_id}',
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            'weight', 'War weight', placeholder='149, 149k, or 149000',
            required=True, min_length=1, max_length=10)])


def _replacement_modal_value(ctx):
    return next((str(item.value or '') for row in getattr(ctx.interaction, 'components', ())
                 for item in row if getattr(item, 'custom_id', None) == 'weight'), '')


@register_action('strike_replace_weight_submit', is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def replacement_weight_submit(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    if getattr(ctx.interaction, 'message', None) is not None:
        await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    state = await _replacement_action_state(ctx, mongo, action_id)
    if state is None:
        return await _replacement_denied(ctx)
    else:
        try:
            weight = parse_weight(_replacement_modal_value(ctx))
            changes = {'weight': weight, 'sort': 'weight', 'page': 0}
            await update_state(mongo, action_id, {'$set': changes})
            state.update(changes)
            components = await replacement_panel(StrikeService(mongo), state)
        except ValueError as error:
            components = await replacement_panel(StrikeService(mongo), state, notice=str(error))
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)




@strikes.register()
class Replacements(lightbulb.SlashCommand, name='replacements',
                   description='Browse family replacement candidates'):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED,
                     coc_client: coc.Client = lightbulb.di.INJECTED):
        await ctx.defer(ephemeral=False)
        if not await authorized(ctx, mongo):
            await ctx.respond('Staff access required.', ephemeral=True)
            return
        state = {'_id': uuid.uuid4().hex, 'user_id': int(ctx.user.id),
                 'guild_id': int(ctx.guild_id), 'clan_tag': None, 'town_hall': None,
                 'weight': None, 'sort': 'priority', 'page': 0, 'clan_page': 0}
        await insert_state(mongo, state)
        try:
            components = await replacement_panel(StrikeService(mongo), state)
        except (RuntimeError, ValueError) as error:
            components = panel('Replacements', safe(error, 250))
        await ctx.respond(components=components, ephemeral=False, **NO_MENTIONS)



def replacement_line(index, row):
    label = {'replace_first': 'Chopping Block', 'high': 'High priority'}.get(row.get('priority', row.get('replacement_priority')), '')
    priority = f' · {label}' if label else ''
    weight, difference = row.get('weight'), row.get('weight_difference')
    weight_text = f'{weight:,} weight' if isinstance(weight, int) else 'Weight unknown'
    if isinstance(difference, int):
        weight_text += f' (difference {difference:,})'
    saved_note = row.get('note', row.get('replacement_note', ''))
    note = f'\n{safe(saved_note, 100)}' if saved_note else ''
    return (f"**{index}. {safe(row.get('player_name') or row['player_tag'], 32)}** "
            f"`{row['player_tag']}`{priority}\n"
            f"{row['current_clan_tag']} · {weight_text} · {row['active_strikes']} active strikes{note}")


def _manual_weights():
    path = os.getenv('CWL_WEB_DB_PATH', '').strip()
    if not path:
        return {}
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=0.2) as db:
            from utils.clan_weight_store import effective_weights
            db.row_factory = sqlite3.Row
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            legacy = ({row['tag']: row['weight'] for row in db.execute(
                'SELECT tag,weight FROM player_weights')} if 'player_weights' in tables else {})
            if 'clan_player_weights' not in tables:
                return ({row['tag']: row['weight'] for row in db.execute(
                    'SELECT tag,weight FROM player_weights WHERE weight IS NOT NULL')}
                    if 'player_weights' in tables else {})
            tags = set(legacy) | {row[0] for row in db.execute('SELECT tag FROM clan_player_weights')}
            try:
                resolved = effective_weights(db, tags)
            except ValueError:
                # Isolate corrupt timestamps without losing unrelated saved weights.
                resolved = {}
                for tag in sorted(tags):
                    try:
                        resolved.update(effective_weights(db, [tag]))
                    except ValueError:
                        logging.getLogger(__name__).warning(
                            'Skipping saved weight with invalid timestamp for %s', tag)
            return {tag: row['weight'] for tag, row in resolved.items()}
    except (sqlite3.Error, OSError, ValueError):
        return {}


async def _provider_weights(tags):
    feed = await _weight_provider.weights(tags)
    return {player: item['weight'] for player, item in feed.items()}


async def live_weights(tags):
    """Compatibility helper for callers that explicitly want a fresh feed."""
    try:
        result = await _provider_weights(tags)
    except ProviderUnavailable:
        result = {}
    return {**result, **_manual_weights()}


async def _refresh_weight_cache(tags):
    global _weight_cache, _weight_cache_at, _weight_retry_at, _weight_cached_tags
    try:
        fresh = await _provider_weights(tags)
    except asyncio.CancelledError:
        raise
    except Exception:
        _weight_retry_at = time.monotonic() + _WEIGHT_RETRY_SECONDS
    else:
        _weight_cache = fresh
        _weight_cached_tags = set(tags)
        _weight_cache_at = time.monotonic()
        _weight_retry_at = 0.0


def cached_weights(tags):
    """Return available weights immediately; one background request refreshes stale data."""
    global _weight_refresh_task
    now = time.monotonic()
    if tags and now >= _weight_retry_at and (now - _weight_cache_at >= _WEIGHT_TTL_SECONDS or set(tags) - _weight_cached_tags):
        if _weight_refresh_task is None or _weight_refresh_task.done():
            _weight_refresh_task = asyncio.create_task(_refresh_weight_cache(list(dict.fromkeys(tags))),
                                                        name='strike-weight-refresh')
    return {**_weight_cache, **_manual_weights()}


async def _warm_weight_cache(mongo):
    try:
        profiles = await mongo.strike_profiles.find(
            {'guild_id': WARRIORS_UNITED_GUILD_ID}, {'player_tag': 1}).to_list(length=None)
        cached_weights([row['player_tag'] for row in profiles])
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def _finish_official_war(tracking, store, guild_id, war):
    """Only a previously observed, complete official final may write records."""
    if war.get('state') != 'warEnded':
        return 0, 0, 0, 0
    prior = await tracking.snapshot(guild_id, war)
    if prior is None:
        # The current endpoint may still show a war that ended before this
        # monitor was deployed. Do not report or backfill that historical gap.
        return 0, 0, 0, 0
    snapshot = await tracking.observe(guild_id, war)
    if snapshot.get('status') in ('finalized', 'incomplete', 'abandoned'):
        return 0, 0, 0, 0
    if not snapshot.get('seen_active'):
        # An already-ended war first seen at startup belongs to the old gap.
        # It cannot be established that we captured its active state.
        return 0, 0, 0, 0
    if not war['complete']:
        # A final response can briefly lack a full roster; the persisted final
        # remains due for another official fetch before the next war replaces it.
        return 0, 0, 0, 1
    if war['type'] == 'regular' and war['attacks_per_member'] == 2:
        result = await store.process_war(guild_id, war, official_capture=True)
        deferred = result.get('deferred_count', 0)
        if deferred:
            return 0, 0, deferred, 0
        await tracking.finalized(guild_id, war)
        return 1, 0, 0, 0
    if war['type'] == 'cwl' and war['attacks_per_member'] == 1:
        await store.process_cwl_war(guild_id, war)
        await tracking.finalized(guild_id, war)
        return 0, 1, 0, 0
    # Friendly and other non-two-attack wars are retained as observations only.
    await tracking.finalized(guild_id, war)
    return 0, 0, 0, 0


async def _league_observations(client, clan_tag, cache, ended_cache=None):
    """Read the bounded current league group; only previously active wars can post."""
    try:
        group = await client.get_league_group(clan_tag)
    except coc.NotFound:
        return []
    rounds = getattr(group, 'rounds', None) or []
    # Later rounds are often placeholders even while a middle round is live.
    tags = list(dict.fromkeys(value for round_tags in rounds
                              for value in round_tags if value and value != '#0'))[:64]
    observations = []
    for war_tag in tags:
        if war_tag not in cache:
            if ended_cache is not None and war_tag in ended_cache:
                cache[war_tag] = ended_cache[war_tag]
            else:
                cache[war_tag] = await client.get_league_war(war_tag)
        war = cache[war_tag]
        if war is None:
            raise ValueError('Official CWL war response is unavailable.')
        state = str(getattr(getattr(war, 'state', None), 'value', getattr(war, 'state', None)))
        if ended_cache is not None and state == 'warEnded' and war_tag not in ended_cache:
            # Cache complete ended wars even when this pair is unrelated to the
            # selected clan; every group member otherwise refetches those tags.
            owner_tag = getattr(getattr(war, 'clan', None), 'tag', None)
            try:
                complete = normalize_official_war(war, owner_tag)
            except (TypeError, ValueError, AttributeError):
                complete = None
            if complete and complete['complete']:
                ended_cache[war_tag] = war
                while len(ended_cache) > 1024:
                    oldest = next(key for key in ended_cache if key != '__client__')
                    ended_cache.pop(oldest)
        sides = (getattr(war, 'clan', None), getattr(war, 'opponent', None))
        if not any(side is not None and getattr(side, 'tag', None) == clan_tag
                   for side in sides):
            continue  # A different pair in the same league round.
        item = normalize_official_war(war, clan_tag)
        if item and item['type'] == 'cwl':
            observations.append(item)
    return observations

def _log_scan_failure(error, *, clan_tag=None):
    """Keep diagnostic locations, never upstream exception text or credentials."""
    frames = traceback.extract_tb(error.__traceback__)
    locations = ' -> '.join(
        f'{os.path.basename(frame.filename)}:{frame.lineno} ({frame.name})'
        for frame in frames
    )
    logging.getLogger(__name__).error(
        '[strikes] scan deferred%s: %s at %s',
        f' for {clan_tag}' if clan_tag else '', type(error).__name__, locations,
    )


async def scan_once(mongo: MongoClient, bot: hikari.GatewayBot, coc_client: coc.Client,
                    *, clan_tags: set[str] | None = None, ended_cache=None):
    if ended_cache is not None and ended_cache.get('__client__') is not coc_client:
        ended_cache.clear()
        ended_cache['__client__'] = coc_client
    store = service(mongo, bot)
    tracking = StrikeTracking(mongo)
    await store.ensure_indexes()
    await tracking.ensure_indexes()
    clans = await mongo.clans.find({'tag': {'$type': 'string'}}, {'tag': 1}).to_list(length=None)
    tracked_tags = {tag(clan['tag']) for clan in clans}
    for removed in await tracking.abandon_untracked(WARRIORS_UNITED_GUILD_ID, tracked_tags):
        print(f'[strikes] stopped tracking removed clan {removed}')
    league_cache = {}
    checked = finalized_total = 0
    successful = set()
    forbidden_results = []
    for clan in clans:
        clan_tag = tag(clan['tag'])
        if clan_tags is not None and clan_tag not in clan_tags:
            continue
        started = None
        attempted_at = datetime.now(timezone.utc)
        attempt_token = uuid.uuid4().hex
        regular_count = cwl_count = deferred_count = skipped_count = 0
        attempted_finals = set()
        problem = None
        current_state = 'unknown'
        private = False
        try:
            started = await tracking.begin(WARRIORS_UNITED_GUILD_ID, clan_tag, token=attempt_token)
            try:
                roster_observed_at = datetime.now(timezone.utc)
                current = await coc_client.get_clan(clan_tag)
                roster = [{'tag': member.tag, 'name': member.name,
                           'town_hall': getattr(member, 'town_hall', None)}
                          for member in current.members]
                await store.sync_roster(WARRIORS_UNITED_GUILD_ID, clan_tag, roster,
                                        observed_at=roster_observed_at)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _log_scan_failure(error, clan_tag=clan_tag)
                problem = 'Clan roster unavailable'
                print(f'[strikes] roster refresh deferred for {clan_tag}')
            current_keys = set()
            regular_ok = league_ok = False
            try:
                current = await coc_client.get_clan_war(clan_tag)
                observed = normalize_official_war(current, clan_tag) if current is not None else None
                if current is None:
                    raise ValueError('Current war response is unavailable.')
                current_state = observed['state'] if observed else 'notInWar'
                regular_ok = True
                if observed:
                    current_keys.add(tracking.snapshot_key(WARRIORS_UNITED_GUILD_ID, observed))
                    if observed['state'] == 'warEnded':
                        attempted_finals.add(tracking.snapshot_key(WARRIORS_UNITED_GUILD_ID, observed))
                        r, c, d, s = await _finish_official_war(
                            tracking, store, WARRIORS_UNITED_GUILD_ID, observed)
                        regular_count += r
                        cwl_count += c
                        deferred_count += d
                        skipped_count += s
                    else:
                        await tracking.observe(WARRIORS_UNITED_GUILD_ID, observed)
            except coc.PrivateWarLog as error:
                forbidden_results.append((clan_tag, started))
                reason = str(getattr(error, 'reason', '') or '').lower()
                if ('invalid' in reason and ('ip' in reason or 'key' in reason)):
                    problem = 'Clash API key/IP rejected'
                else:
                    private = True
                    current_state = 'private'
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _log_scan_failure(error, clan_tag=clan_tag)
                problem = 'War processing failed' if regular_ok else 'War source unavailable'
                print(f'[strikes] official war check deferred for {clan_tag}')
            try:
                league_wars = await _league_observations(coc_client, clan_tag,
                                                         league_cache, ended_cache)
                league_ok = True
                for observed in league_wars:
                    current_keys.add(tracking.snapshot_key(WARRIORS_UNITED_GUILD_ID, observed))
                    if observed['state'] == 'warEnded':
                        attempted_finals.add(tracking.snapshot_key(WARRIORS_UNITED_GUILD_ID, observed))
                        r, c, d, s = await _finish_official_war(
                            tracking, store, WARRIORS_UNITED_GUILD_ID, observed)
                        regular_count += r
                        cwl_count += c
                        deferred_count += d
                        skipped_count += s
                    else:
                        await tracking.observe(WARRIORS_UNITED_GUILD_ID, observed)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _log_scan_failure(error, clan_tag=clan_tag)
                problem = problem or ('War processing failed' if league_ok else 'War source unavailable')
                print(f'[strikes] official CWL check deferred for {clan_tag}')
            if regular_ok and league_ok:
                skipped_count += await tracking.abandon_older(
                    WARRIORS_UNITED_GUILD_ID, clan_tag, current_keys)
            # A final payload survives a restart or a subsequent prep war when
            # link/role resolution was unavailable on its first processing pass.
            for saved in await tracking.pending_finals(WARRIORS_UNITED_GUILD_ID, clan_tag):
                if saved['_id'] in attempted_finals:
                    continue
                due_at = saved.get('next_check_at')
                if due_at is not None and utc(due_at) > datetime.now(timezone.utc):
                    continue
                try:
                    r, c, d, s = await _finish_official_war(
                        tracking, store, WARRIORS_UNITED_GUILD_ID, saved['war'])
                    regular_count += r
                    cwl_count += c
                    deferred_count += d
                    skipped_count += s
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    _log_scan_failure(error, clan_tag=clan_tag)
                    problem = 'War processing failed'
            if problem or deferred_count or not regular_ok or not league_ok:
                await tracking.defer_due(WARRIORS_UNITED_GUILD_ID, clan_tag)
            await tracking.finish(WARRIORS_UNITED_GUILD_ID, clan_tag, started_at=started,
                                  regular_wars=regular_count, cwl_wars=cwl_count,
                                  deferred_accounts=deferred_count, skipped_wars=skipped_count,
                                  error=problem, current_war_state=current_state,
                                  private=private)
            if not problem and not deferred_count and not private:
                successful.add(clan_tag)
            checked += 1
            finalized_total += regular_count + cwl_count
        except asyncio.CancelledError:
            # A cancelled attempt must never mark this clan healthy.
            raise
        except Exception as error:
            _log_scan_failure(error, clan_tag=clan_tag)
            if started is not None:
                try:
                    await tracking.finish(
                        WARRIORS_UNITED_GUILD_ID, clan_tag, started_at=started,
                        error='War processing failed', current_war_state=current_state,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as tracking_error:
                    _log_scan_failure(tracking_error, clan_tag=clan_tag)
            try:
                if started is None:
                    await tracking.failed_begin(WARRIORS_UNITED_GUILD_ID, clan_tag, attempted_at, token=attempt_token)
                await tracking.defer_due(WARRIORS_UNITED_GUILD_ID, clan_tag)
            except asyncio.CancelledError:
                raise
            except Exception as tracking_error:
                _log_scan_failure(tracking_error, clan_tag=clan_tag)
            # A bad payload or failed clan must not starve the remaining clans.
            continue
    full_coverage = clan_tags is None or tracked_tags <= clan_tags
    if full_coverage and tracked_tags and len(forbidden_results) == len(tracked_tags):
        for clan_tag, started in forbidden_results:
            await tracking.finish(WARRIORS_UNITED_GUILD_ID, clan_tag, started_at=started,
                                  error='Clash API key/IP rejected', current_war_state='private')
    successful.difference_update(clan for clan, _ in forbidden_results)
    if clan_tags is None:
        await _warm_weight_cache(mongo)
    if checked:
        rows = await tracking.rows(WARRIORS_UNITED_GUILD_ID,
                                   [clan for clan in clans if clan_tags is None or
                                    tag(clan['tag']) in clan_tags])
        behind = sum(row['status'] == 'behind' for row in rows)
        print(f'[strikes] pass: {checked} clans, {finalized_total} wars finalized, {behind} behind')
    return successful


async def loop(mongo, bot, coc_client):
    tracking = StrikeTracking(mongo)
    ended_cache = {}
    next_full = 0.0
    while True:
        try:
            if time.monotonic() >= next_full:
                pending = await tracking.pending(WARRIORS_UNITED_GUILD_ID)
                successful = await scan_once(mongo, bot, coc_client, ended_cache=ended_cache)
                for row in pending:
                    if row['clan_tag'] not in (successful or set()):
                        continue
                    await tracking.consume_retry(WARRIORS_UNITED_GUILD_ID,
                                                 row['clan_tag'], row['retry_requested_at'])
                next_full = time.monotonic() + POLL_SECONDS
            else:
                pending = await tracking.pending(WARRIORS_UNITED_GUILD_ID)
                due = await tracking.due_clans(WARRIORS_UNITED_GUILD_ID)
                if pending or due:
                    wanted = {row['clan_tag'] for row in pending} | due
                    successful = await scan_once(mongo, bot, coc_client, clan_tags=wanted,
                                    ended_cache=ended_cache)
                    for row in pending:
                        if row['clan_tag'] not in (successful or set()):
                            continue
                        await tracking.consume_retry(WARRIORS_UNITED_GUILD_ID,
                                                     row['clan_tag'], row['retry_requested_at'])
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _log_scan_failure(error)
        await asyncio.sleep(15)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def started(event, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                  coc_client: coc.Client = lightbulb.di.INJECTED):
    global _task, _weight_warm_task
    _task = asyncio.create_task(loop(mongo, bot, coc_client), name='strike-war-monitor')
    _weight_warm_task = asyncio.create_task(_warm_weight_cache(mongo), name='strike-weight-warm')


@loader.listener(hikari.StoppingEvent)
async def stopped(event):
    global _task, _weight_warm_task, _weight_refresh_task
    tasks = [task for task in (_task, _weight_warm_task, _weight_refresh_task)
             if task is not None and not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _task = None
    _weight_warm_task = None
    _weight_refresh_task = None


loader.command(strikes, guilds=[WARRIORS_UNITED_GUILD_ID])
