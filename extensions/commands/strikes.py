"""Private Components V2 strike views and automatic ended-war monitor."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import uuid
import os
import sqlite3

import coc
import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text

from extensions.components import register_action
from utils import recruit_links, strike_wars
from utils.component_state import get_state, insert_state
from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils.mongo import MongoClient
from utils.strike_store import StrikeService, tag
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


async def authorized(ctx, mongo, scope='strikes_read') -> bool:
    # Read shared dashboard grants on every command and component action.
    if int(ctx.interaction.guild_id or 0) != WARRIORS_UNITED_GUILD_ID:
        return False
    member = getattr(ctx.interaction, 'member', None)
    if member is None:
        return False
    if member.permissions & hikari.Permissions.ADMINISTRATOR:
        return True
    from cwl_web.access_control import dashboard_allowed
    return await dashboard_allowed({'user_id': str(ctx.user.id)}, scope, mongo)


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
        return None
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
        status = row['status'].title()
        name = safe(row.get('player_name') or row['player_tag'], 36)
        clan = safe(row.get('clan_tag') or 'Clan unknown', 18)
        current = safe(current_clans.get(row['player_tag']) or 'Unknown', 18)
        lines.append(f"**{name}** `{row['player_tag']}` · {status}\n"
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
        lightbulb.Choice('One missed', 'missed')])

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
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED,
                     coc_client: coc.Client = lightbulb.di.INJECTED):
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
                f"`{row['player_tag']}` · Expires in 90 days\n{safe(row['reason'], 500)}"),
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
    return panel('Strike added', f"`{row['player_tag']}` · Expires in 90 days\n{safe(row['reason'], 500)}")


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


@strikes.register()
class Replacements(lightbulb.SlashCommand, name='replacements',
                   description='Match a recruit’s weight to FWA replacement candidates'):
    weight = lightbulb.integer('weight', 'Recruit total war weight', min_value=1, max_value=500000)
    clan = lightbulb.string('clan', 'Optional FWA clan tag', default=None)

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED):
        await ctx.defer(ephemeral=True)
        if not await authorized(ctx, mongo):
            await ctx.respond('Staff access required.', ephemeral=True)
            return
        profiles = await mongo.strike_profiles.find({'guild_id': int(ctx.guild_id)}).to_list(length=None)
        weight_map = await live_weights([row['player_tag'] for row in profiles])
        rows = await StrikeService(mongo).replacement(ctx.guild_id, self.weight,
            clan_tag=self.clan, limit=12, weights=weight_map)
        lines = []
        for index, row in enumerate(rows, 1):
            lines.append(replacement_line(index, row))
        await ctx.respond(components=panel('FWA replacements',
            f'Recruit weight: **{self.weight:,}**', '\n\n'.join(lines) or 'No weighted candidates yet.'),
            ephemeral=True, **NO_MENTIONS)




def replacement_line(index, row):
    label = {'replace_first': 'Replace first', 'high': 'High priority'}.get(row.get('priority', row.get('replacement_priority')), '')
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


async def live_weights(tags):
    try:
        fed = await _weight_provider.weights(tags)
    except ProviderUnavailable:
        fed = {}
    result = {player: item['weight'] for player, item in fed.items()}
    path = os.getenv('CWL_WEB_DB_PATH', '').strip()
    if path:
        def local():
            try:
                with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2) as db:
                    return {row[0]: row[1] for row in db.execute(
                        'SELECT tag,weight FROM player_weights WHERE weight IS NOT NULL')}
            except (sqlite3.Error, OSError):
                return {}
        result.update(await asyncio.to_thread(local))
    return result

async def scan_once(mongo: MongoClient, bot: hikari.GatewayBot, coc_client: coc.Client):
    store = service(mongo, bot)
    await store.ensure_indexes()
    activation = await store.monitor_activation(WARRIORS_UNITED_GUILD_ID)
    clans = await mongo.clans.find({'tag': {'$type': 'string'}}, {'tag': 1}).to_list(length=None)
    for clan in clans:
        try:
            current = await coc_client.get_clan(clan['tag'])
            roster = [{'tag': member.tag, 'name': member.name}
                      for member in current.members]
            await store.sync_roster(WARRIORS_UNITED_GUILD_ID, clan['tag'], roster)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[strikes] roster refresh deferred for {clan['tag']}: {type(error).__name__}: {error}")
        try:
            age_days = max(1, math.ceil((datetime.now(timezone.utc) - activation).days) + 1)
            wars = await strike_wars.fetch_history(clan['tag'], days=age_days)
            for war in wars:
                if war['end_time'] >= activation:
                    await store.process_war(WARRIORS_UNITED_GUILD_ID, war)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[strikes] scan deferred for {clan['tag']}: {type(error).__name__}: {error}")


async def loop(mongo, bot, coc_client):
    while True:
        try:
            await scan_once(mongo, bot, coc_client)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f'[strikes] scan deferred: {type(error).__name__}: {error}')
        await asyncio.sleep(POLL_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def started(event, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                  coc_client: coc.Client = lightbulb.di.INJECTED):
    global _task
    _task = asyncio.create_task(loop(mongo, bot, coc_client), name='strike-war-monitor')


@loader.listener(hikari.StoppingEvent)
async def stopped(event):
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass


loader.command(strikes, guilds=[WARRIORS_UNITED_GUILD_ID])
