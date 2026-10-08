"""Goldenrod Components V2 view of the persistent main-clan loot test."""
import asyncio
from datetime import datetime
import logging
import re
import sqlite3
import time
import unicodedata

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from utils.recruit_links import resolve_players
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID
from utils.gold_loot import refresh_board, load_town_halls
from utils.emoji import emojis
from utils import bot_data

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
_lock = asyncio.Lock()
_cached = None
_cached_at = 0.0


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


def safe_name(value):
    value = ''.join(c for c in value if c.isprintable())[:32]
    value = value.replace('@', '@\u200b').replace('<', '‹').replace('>', '›')
    return re.sub(r'([\\`*_~|\[\]()])', r'\\\1', value)


def profile_label(value):
    """Avoid backslash escapes inside Discord masked-link labels.

    Use visually similar punctuation so names with separators or Markdown
    characters cannot break the link into literal source text.
    """
    # Discord parses emoji before masked links in some clients. Keep the
    # anchor text free of emoji, flags, joiners and variation selectors.
    label = ''.join(c for c in value if c.isprintable()
                    and unicodedata.category(c) != 'So'
                    and not ('\U0001f3fb' <= c <= '\U0001f3ff')
                    and c not in '\ufe0e\ufe0f\u20e3')[:64]
    label = label.translate(str.maketrans({
        '|': '│', '\\': '╲', '[': '［', ']': '］',
        '(': '（', ')': '）', '*': '∗', '_': '＿',
        '~': '～', '`': '′', '<': '‹', '>': '›',
    }))
    return ' '.join(label.replace('@', '@\u200b').split()) or 'Discord profile'


async def load_discord_labels(owners, *, rest=None):
    """Fetch names for explicit profile links; no dependence on viewer caches."""
    if rest is None:
        bot = bot_data.data.get('bot')
        if bot is None:
            return {}
        rest = bot.rest
    semaphore = asyncio.Semaphore(3)
    async def fetch(owner):
        async with semaphore:
            try:
                async with asyncio.timeout(10):
                    try:
                        user = await rest.fetch_member(WARRIORS_UNITED_GUILD_ID, int(owner))
                    except (hikari.NotFoundError, hikari.ForbiddenError):
                        user = await rest.fetch_user(int(owner))
                    return owner, user.display_name
            except (hikari.HTTPError, asyncio.TimeoutError):
                return owner, None
    return {owner: name for owner, name in await asyncio.gather(
        *(fetch(owner) for owner in set(owners.values()))
    ) if name}


def render_board(board):
    session = board['session']
    lines = []
    for rank, row in enumerate(board['rows'], 1):
        medal = ('🥇', '🥈', '🥉')[rank - 1] if rank <= 3 else f'**{rank}.**'
        owner = (board.get('owners') or {}).get(row['tag'])
        label = board.get('discord_labels', {}).get(owner)
        linked = (f'[{profile_label(label)}](https://discord.com/users/{owner})'
                  if label else f'[Discord profile](https://discord.com/users/{owner})') if owner and str(owner).isdigit() else (
            'Link conflict' if row['tag'] in board.get('link_conflicts', ()) else
            'Link unavailable' if board.get('owners') is None or board.get('link_unavailable') else
            'No linked Discord account'
        )
        clan = safe_name(row.get('clan_name') or 'Warriors United')
        level = board.get('town_halls', {}).get(row['tag'])
        th = str(getattr(emojis, f'TH{level}', f'🏰 TH{level}')) if level else '🏰 TH ?'
        lines.append(f"{medal} {th} **{safe_name(row['name'])}** — **{row['looted']:,}** gold\n-# `{row['tag']}` • {linked} • {clan}")
    components = [
        Text(content='## 🏆 Gold Loot Leaderboard\n**Warriors United Family • Top 10**'),
        Separator(divider=True),
        Text(content='\n\n'.join(lines) or 'No player samples are available yet.'),
        Separator(divider=True),
    ]
    if board['warning']:
        components.append(Text(content=f"⚠️ {board['warning']}"))
    refreshed = board.get('newest')
    components.append(Text(content=(
        f"-# Tracking started: <t:{stamp(session['started'])}:f>\n"
        + (f"-# Last refreshed: <t:{stamp(refreshed)}:f> • {board['count']} players • {board.get('clan_count', 1)} clans"
           if refreshed else f"-# Last refreshed: unavailable • {board['count']} players • {board.get('clan_count', 1)} clans")
    )))
    components.append(ActionRow(components=[Button(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id='loot_leaderboard_update:main', label='Update', emoji='🔄',
    )]))
    return [Container(accent_color=GOLDENROD_ACCENT, components=components)]


async def load_board(*, force=False):
    global _cached, _cached_at
    requested_at = time.monotonic()
    async with _lock:
        if (_cached is None or time.monotonic() - _cached_at >= 60
                or (force and _cached_at < requested_at)):
            board = await asyncio.to_thread(refresh_board)
            tags = [row['tag'] for row in board['rows']]
            links, town_halls = await asyncio.gather(resolve_players(tags), load_town_halls(tags))
            board['town_halls'] = town_halls
            board['owners'] = links.owners
            board['discord_labels'] = await load_discord_labels(links.owners)
            board['link_conflicts'] = links.conflicts
            board['link_unavailable'] = links.unavailable
            _cached = board
            _cached_at = time.monotonic()
        return _cached


async def execute(ctx):
    if ctx.guild_id != WARRIORS_UNITED_GUILD_ID:
        await ctx.respond('This leaderboard is available in Warriors United.', ephemeral=True)
        return
    from extensions.commands.goldrush import route_existing
    if await route_existing(ctx):
        return
    await ctx.defer(ephemeral=True)
    try:
        board = await load_board()
        components = render_board(board)
    except (ValueError, sqlite3.Error, OSError):
        _log.exception('Gold leaderboard could not load its saved test')
        components = [Container(accent_color=GOLDENROD_ACCENT, components=[Text(content=(
            '## 🏆 Gold Loot Leaderboard\n'
            'The saved gold-loot test is unavailable on this bot host. '
            'Ask the bot owner to restore the test data, then run this command again.'
        ))])]
        await ctx.interaction.edit_initial_response(
            components=components, user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        return
    try:
        await ctx.interaction.app.rest.create_message(
            ctx.channel_id, components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
    except hikari.HTTPError:
        _log.exception('Could not post gold leaderboard in channel')
        await ctx.interaction.edit_initial_response(
            content='Could not post the leaderboard. Check my channel permissions and try again.',
        )
        return
    # Leave only the standalone channel message, without a command reply header.
    try:
        await ctx.interaction.delete_initial_response()
    except hikari.HTTPError:
        _log.warning('Could not remove private leaderboard acknowledgement', exc_info=True)


@register_action('loot_leaderboard_update', preload_state=False, no_return=True)
async def update_leaderboard(ctx, action_id, **kwargs):
    # The dispatcher defers a message update and replaces the original panel.
    if ctx.interaction.guild_id != WARRIORS_UNITED_GUILD_ID:
        await ctx.respond('This leaderboard is available in Warriors United.', ephemeral=True)
        return None
    from extensions.commands.goldrush import route_existing
    if await route_existing(ctx, edit=True):
        return
    try:
        components = render_board(await load_board(force=True))
        await ctx.interaction.edit_initial_response(
            components=components, user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
    except (ValueError, sqlite3.Error, OSError):
        _log.exception('Gold leaderboard update failed')
        await ctx.respond('Could not update the leaderboard. Please try again.', ephemeral=True)
        return None


class LootLeaderboard(
    lightbulb.SlashCommand,
    name='loot-leaderboard',
    description='Show the top 10 gold looters across Warriors United’s linked clans',
    contexts=[hikari.ApplicationContextType.GUILD],
    integration_types=[hikari.ApplicationIntegrationType.GUILD_INSTALL],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await execute(ctx)


loader.command(LootLeaderboard, guilds=[WARRIORS_UNITED_GUILD_ID])
