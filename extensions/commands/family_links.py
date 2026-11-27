"""Persistent, private self-selection and read-only current clan links."""
import asyncio
import logging
import re
import unicodedata
from datetime import timedelta
from types import SimpleNamespace
from weakref import WeakValueDictionary
from urllib.parse import quote

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as Menu,
    SelectOptionBuilder as Option,
    LinkButtonBuilder as Link,
    InteractiveButtonBuilder as Button,
)
from extensions.components import register_action
from utils.background import log_failure
from utils.component_state import insert_state, get_state, utcnow
from utils.constants import WU_GOLD, WU_RED
from utils.dashboard_access import dashboard_role_grants
from utils.info_channel_content import load_family_clans, InfoContentUnavailable
from utils.mongo import MongoClient
from utils import server_roles, town_halls
from utils.role_permissions import role_is_self_selectable

_log = logging.getLogger(__name__)
loader = lightbulb.Loader()
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)
_locks = WeakValueDictionary()


async def private_message(ctx, message, *, error=False):
    await ctx.respond(components=[Container(accent_color=WU_RED if error else WU_GOLD,
        components=[Text(content='## Roles and clan links'), Text(content=message),
                    Media(items=[MediaItem(media='assets/Gold_Footer.png')])])],
        ephemeral=True, **NO_MENTIONS)


async def fresh_context(bot, guild_id, user_id):
    """REST-only hierarchy and member snapshot; never a cached full-role write."""
    me = bot.get_me()
    guild, roles, member, own = await asyncio.gather(
        bot.rest.fetch_guild(guild_id), bot.rest.fetch_roles(guild_id),
        bot.rest.fetch_member(guild_id, user_id), bot.rest.fetch_member(guild_id, me.id))
    by_id = {int(role.id): role for role in roles}
    adapted = SimpleNamespace(id=int(guild.id), owner_id=int(guild.owner_id),
        get_role=lambda role_id: by_id.get(int(role_id)),
        get_member=lambda member_id: own if int(member_id) == int(me.id) else None)
    return adapted, by_id, member


async def choices(mongo, guild_id, kind):
    if kind == 'th':
        return [dict(role_id=item['role_id'], label=f"TH{item['level']}",
                     short_line='', level=item['level'], emoji=item['emoji'])
                for item in await town_halls.role_choices(mongo, guild_id)]
    return await server_roles.panel_roles(mongo, guild_id)


async def private_roles(ctx, mongo, bot):
    guild_id, user_id = ctx.interaction.guild_id, ctx.user.id
    guild, roles, member = await fresh_context(bot, guild_id, user_id)
    protected = await dashboard_role_grants(mongo)
    components = [Text(content='## My roles')]
    offered = {'th': [], 'server': []}
    town_hall_ids = set()
    for kind, heading in [('th', 'Town Hall levels'), ('server', 'Server roles')]:
        rows = await choices(mongo, guild_id, kind)
        if kind == 'th':
            town_hall_ids = {row['role_id'] for row in rows}
        else:
            # Even if configuration changes between the two reads, this reply
            # must never display the same role in both independent menus.
            rows = [row for row in rows if row['role_id'] not in town_hall_ids]
        rows = [row for row in rows
                if role_is_self_selectable(guild, bot, roles.get(int(row['role_id'])))
                and row['role_id'] not in protected]
        if not rows:
            continue
        offered[kind] = [row['role_id'] for row in rows]
        options = [Option(label=row['label'], value=row['role_id'],
                    description=row['short_line'] or hikari.UNDEFINED,
                    emoji=hikari.Emoji.parse(row['emoji']) if kind == 'th' and row['emoji'] else hikari.UNDEFINED,
                    is_default=int(row['role_id']) in member.role_ids) for row in rows]
        components += [Text(content=f'### {heading}'), ActionRow(components=[Menu(
            custom_id=f'family_links_select_{kind}:', placeholder=heading,
            min_values=0, max_values=len(options), options=options)])]
    if len(components) == 1:
        components.append(Text(content='No roles to show right now.'))
    components.append(Media(items=[MediaItem(media='assets/Gold_Footer.png')]))
    response_id = await ctx.respond(
        components=[Container(accent_color=WU_GOLD, components=components)],
        ephemeral=True, **NO_MENTIONS)
    # Fixed custom IDs stay restart-safe. Bind the immutable displayed options to
    # this actual private Discord message, never a mutable per-user latest panel.
    message = await ctx.fetch_response(response_id)
    if not message.flags & hikari.MessageFlag.EPHEMERAL:
        raise ValueError('Expected a private role response.')
    await insert_state(mongo, {
        '_id': role_session_key(guild_id, user_id, message.id),
        'type': 'family_roles', 'guild_id': int(guild_id), 'user_id': int(user_id),
        'message_id': int(message.id), 'offered': offered,
    }, ttl=timedelta(minutes=15))


def role_session_key(guild_id, user_id, message_id):
    return f'family-roles:{int(guild_id)}:{int(user_id)}:{int(message_id)}'


async def role_session(ctx, mongo):
    message = getattr(ctx.interaction, 'message', None)
    if message is None or not message.flags & hikari.MessageFlag.EPHEMERAL:
        return None
    guild_id, user_id = int(ctx.interaction.guild_id), int(ctx.user.id)
    row = await get_state(mongo, role_session_key(guild_id, user_id, message.id))
    if (not isinstance(row, dict) or row.get('type') != 'family_roles'
            or row.get('guild_id') != guild_id or row.get('user_id') != user_id
            or row.get('message_id') != int(message.id)):
        return None
    expiry = row.get('expires_at')
    if expiry is None:
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=utcnow().tzinfo)
    if expiry <= utcnow():
        return None
    offered = row.get('offered')
    if not isinstance(offered, dict) or set(offered) != {'th', 'server'}:
        return None
    for identifiers in offered.values():
        if (not isinstance(identifiers, list) or len(identifiers) > 25
                or any(not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,19}', value) is None or int(value) > 2**64 - 1 for value in identifiers)):
            return None
    return offered


@register_action('family_links_my_roles', no_return=True, preload_state=False)
@register_action('family_links_th', no_return=True, preload_state=False)
@register_action('family_links_server_roles', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_roles(ctx, mongo: MongoClient = lightbulb.di.INJECTED,
                     bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_kwargs):
    # Legacy selections intentionally do not write; discard their old values.
    try:
        await private_roles(ctx, mongo, bot)
    except Exception as error:
        log_failure(_log, 'Roles and clan links could not load', error)
        await private_message(ctx, 'Roles are not available right now. Try again in a minute.', error=True)


async def select_roles(ctx, mongo, bot, kind):
    guild_id, user_id = int(ctx.interaction.guild_id), int(ctx.user.id)
    lock = _locks.setdefault((guild_id, user_id), asyncio.Lock())
    async with lock:
        try:
            offered = await role_session(ctx, mongo)
            if offered is None:
                await private_message(ctx, 'Open My roles again before changing your roles.', error=True)
                return
            offered_ids = set(map(int, offered[kind]))
            rows = await choices(mongo, guild_id, kind)
            current = {int(row['role_id']): row for row in rows}
            selected = {int(value) for value in ctx.interaction.values
                        if isinstance(value, str) and value.isdigit() and int(value) in current and int(value) in offered_ids}
            guild, roles, member = await fresh_context(bot, guild_id, user_id)
        except Exception as error:
            log_failure(_log, 'Roles and clan links unavailable before change', error)
            await private_message(ctx, 'Your roles did not change. Try again in a minute.', error=True)
            return
        held = set(map(int, member.role_ids))
        operations = [('add', role) for role in sorted(selected - held)]
        operations += [('remove', role) for role in sorted((held & current.keys() & offered_ids) - selected)]
        added, removed = [], []
        failed, uncertain = False, False
        for action, identifier in operations:
            # Re-read list, hierarchy and member before each incremental change.
            try:
                latest = {int(row['role_id']): row for row in await choices(mongo, guild_id, kind)}
                guild, roles, member = await fresh_context(bot, guild_id, user_id)
                protected = await dashboard_role_grants(mongo)
            except Exception as error:
                failed = True
                log_failure(_log, 'Roles and clan links role context unavailable', error)
                break
            if identifier not in latest or identifier not in offered_ids:
                continue
            if str(identifier) in protected or not role_is_self_selectable(guild, bot, roles.get(identifier)):
                failed = True
                continue
            if (identifier in member.role_ids) == (action == 'add'):
                continue
            try:
                operation = bot.rest.add_role_to_member if action == 'add' else bot.rest.remove_role_from_member
                await operation(guild_id, user_id, identifier, reason='Roles and clan links')
            except (hikari.ForbiddenError, hikari.NotFoundError, hikari.BadRequestError) as error:
                failed = True
                log_failure(_log, 'Roles and clan links role change failed', error)
            except Exception as error:
                failed = uncertain = True
                log_failure(_log, 'Roles and clan links role change unconfirmed', error)
                break  # Never repeat an ambiguous Discord write.
            else:
                (added if action == 'add' else removed).append(latest[identifier]['label'])
        parts = []
        if added:
            parts.append('Added: ' + ', '.join(added) + '.')
        if removed:
            parts.append('Removed: ' + ', '.join(removed) + '.')
        if failed:
            if uncertain:
                parts.append('The last role change could not be confirmed. Refresh your roles before trying again.')
            elif parts:
                parts.append('Your other roles did not change. Try again in a minute.')
            else:
                parts.append('Your roles did not change. Try again in a minute.')
        elif not parts:
            parts.append('No change.')
        await ctx.respond(components=[Container(accent_color=WU_RED if failed else WU_GOLD, components=[Text(content='## My roles'), Text(content=' '.join(parts)), Media(items=[MediaItem(media='assets/Gold_Footer.png')])])], ephemeral=True, **NO_MENTIONS)


@register_action('family_links_select_th', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def select_th(ctx, mongo: MongoClient = lightbulb.di.INJECTED,
                    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_kwargs):
    await select_roles(ctx, mongo, bot, 'th')


@register_action('family_links_select_server', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def select_server(ctx, mongo: MongoClient = lightbulb.di.INJECTED,
                        bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_kwargs):
    await select_roles(ctx, mongo, bot, 'server')


def clan_emoji(value, fallback):
    if isinstance(value, str) and re.fullmatch(r'<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>', value):
        return hikari.Emoji.parse(value)
    if (isinstance(value, str) and 0 < len(value) <= 16
            and any(unicodedata.category(char) == 'So' for char in value)
            and all(unicodedata.category(char) in {'So', 'Sk', 'Mn', 'Me', 'Cf'} for char in value)):
        return hikari.UnicodeEmoji(value)
    return fallback


async def clan_links(ctx, mongo, kind, page=0):
    descriptions = {'war': ('War clans', 'Tactical and Flexible Fun clans.'),
                    'fwa': ('FWA clans', 'Farm War Alliance clans.'),
                    'cwl': ('CWL clans', 'Clan War League clans.')}
    title, description = descriptions[kind]
    try:
        groups = await load_family_clans(mongo, include_cwl=True, require_nonempty=False)
    except InfoContentUnavailable:
        await private_message(ctx, 'Clan links are not available right now. Try again in a minute.', error=True)
        return
    rows = groups['Tactical'] + groups['Flexible Fun'] if kind == 'war' else groups[kind.upper()]
    components = [Text(content=f'## {title}'), Text(content=description)]
    if not rows:
        components.append(Text(content='No clans to show right now.'))
    elif len(rows) > 25:
        page = max(0, min(page, (len(rows) - 1) // 25))
        components.append(ActionRow(components=[Menu(custom_id=f'family_links_clan_select:{kind}',
            placeholder='Select a clan', min_values=1, max_values=1,
            options=[Option(label=row['name'][:100], value=row['tag']) for row in rows[page * 25:(page + 1) * 25]])]))
        components.append(ActionRow(components=[Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"family_links_clan_page:{kind}:{page + delta}", label=label, is_disabled=disabled) for delta, label, disabled in [(-1, "Previous clans", page == 0), (1, "More clans", (page + 1) * 25 >= len(rows))]]))
    else:
        for start in range(0, len(rows), 5):
            components.append(ActionRow(components=[Link(label=('Join ' + row['name'])[:80],
                url='https://link.clashofclans.com/en/?action=OpenClanProfile&tag=' + quote(row['tag']),
                emoji=clan_emoji(row.get('emoji'), {'war':'⚔️','fwa':'🏳️','cwl':'🏆'}[kind])) for row in rows[start:start + 5]]))
    components.append(Media(items=[MediaItem(media='assets/Gold_Footer.png')]))
    await ctx.respond(components=[Container(accent_color=WU_GOLD, components=components)], ephemeral=True, **NO_MENTIONS)


@register_action('family_links_war_clans', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def war_clans(ctx, mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    await clan_links(ctx, mongo, 'war')


@register_action('family_links_fwa_clans', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def fwa_clans(ctx, mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    await clan_links(ctx, mongo, 'fwa')


@register_action('family_links_cwl_clans', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def cwl_clans(ctx, mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    await clan_links(ctx, mongo, 'cwl')


@register_action('family_links_clan_page', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def clan_page(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    try:
        kind, page = action_id.split(':')
        if kind not in ('war', 'fwa', 'cwl') or not page.isdigit():
            raise ValueError
    except ValueError:
        await private_message(ctx, 'No clans to show right now.')
        return
    await clan_links(ctx, mongo, kind, int(page))


@register_action('family_links_clan_select', no_return=True, preload_state=False)
@register_action('view_clan_info', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def current_clan(ctx, mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    try:
        groups = await load_family_clans(mongo, include_cwl=True, require_nonempty=False)
        rows = [row for group in groups.values() for row in group]
        values = ctx.interaction.values
        chosen = values[0] if len(values) == 1 else ''
        # Legacy values may have a clan tag prefix; the current active reader is authority.
        chosen = chosen.removeprefix('clan:')
        row = next((row for row in rows if row['tag'] == chosen), None)
        if row is None:
            await private_message(ctx, 'No clans to show right now.')
            return
        link = Link(label=('Join ' + row['name'])[:80], url='https://link.clashofclans.com/en/?action=OpenClanProfile&tag=' + quote(row['tag']), emoji='⚔️')
        await ctx.respond(components=[Container(accent_color=WU_GOLD, components=[Text(content='## Join a clan'), ActionRow(components=[link]), Media(items=[MediaItem(media='assets/Gold_Footer.png')])])], ephemeral=True, **NO_MENTIONS)
    except InfoContentUnavailable:
        await private_message(ctx, 'Clan links are not available right now. Try again in a minute.', error=True)
