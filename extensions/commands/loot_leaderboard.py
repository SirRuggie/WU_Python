"""Goldenrod Components V2 view of the persistent main-clan loot test."""
import asyncio
from datetime import datetime
import logging
import re
import sqlite3
import time

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
from utils.clash_links import resolve_discord_ids
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID
from utils.gold_loot import refresh_board

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


def render_board(board):
    session = board['session']
    lines = []
    for rank, row in enumerate(board['rows'], 1):
        medal = ('🥇', '🥈', '🥉')[rank - 1] if rank <= 3 else f'**{rank}.**'
        owner = (board.get('owners') or {}).get(row['tag'])
        linked = f'<@{owner}>' if owner and str(owner).isdigit() else (
            'Link unavailable' if board.get('owners') is None else 'No linked Discord account'
        )
        lines.append(f"{medal} **{safe_name(row['name'])}** — **{row['looted']:,}** gold\n-# {linked} • {row['tag']}")
    components = [
        Text(content='## 🏆 Gold Loot Leaderboard\n**Warriors United • Top 10**'),
        Separator(divider=True),
        Text(content='\n\n'.join(lines) or 'No player samples are available yet.'),
        Separator(divider=True),
    ]
    if board['warning']:
        components.append(Text(content=f"⚠️ {board['warning']}"))
    refreshed = board.get('newest')
    components.append(Text(content=(
        f"-# Tracking started: <t:{stamp(session['started'])}:f>\n"
        + (f"-# Last refreshed: <t:{stamp(refreshed)}:f> • {board['count']} tracked players"
           if refreshed else f"-# Last refreshed: unavailable • {board['count']} tracked players")
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
            board['owners'] = await resolve_discord_ids([row['tag'] for row in board['rows']])
            _cached = board
            _cached_at = time.monotonic()
        return _cached


async def execute(ctx):
    if ctx.guild_id != WARRIORS_UNITED_GUILD_ID:
        await ctx.respond('This leaderboard is available in Warriors United.', ephemeral=True)
        return
    await ctx.defer()
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


@register_action('loot_leaderboard_update', preload_state=False, no_return=True)
async def update_leaderboard(ctx, action_id, **kwargs):
    # The dispatcher defers a message update and replaces the original panel.
    if ctx.interaction.guild_id != WARRIORS_UNITED_GUILD_ID:
        await ctx.respond('This leaderboard is available in Warriors United.', ephemeral=True)
        return None
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
    description='Show Warriors United’s top 10 gold looters since the test began',
    contexts=[hikari.ApplicationContextType.GUILD],
    integration_types=[hikari.ApplicationIntegrationType.GUILD_INSTALL],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await execute(ctx)


loader.command(LootLeaderboard, guilds=[WARRIORS_UNITED_GUILD_ID])
