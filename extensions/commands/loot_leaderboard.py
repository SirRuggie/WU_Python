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
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

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
        lines.append(f"{medal} **{safe_name(row['name'])}** — **{row['looted']:,}** gold\n-# {row['tag']}")
    components = [
        Text(content='## 🏆 Gold Loot Leaderboard\n**Warriors United • Top 10**'),
        Text(content=f"Since <t:{stamp(session['started'])}:f> • **{board['count']}** tracked players"),
        Separator(divider=True),
        Text(content='\n\n'.join(lines) or 'No player samples are available yet.'),
        Separator(divider=True),
    ]
    if board['warning']:
        components.append(Text(content=f"⚠️ {board['warning']}"))
    if board['oldest']:
        components.append(Text(content=(
            f"-# Player samples: <t:{stamp(board['oldest'])}:R> to <t:{stamp(board['newest'])}:R>\n"
            '-# Gold looted since the test began • Fixed starting roster • Ties ordered by player tag\n'
            '-# Run /loot-leaderboard to update. Results are reused for up to 60 seconds.'
        )))
    return [Container(accent_color=GOLDENROD_ACCENT, components=components)]


async def load_board():
    global _cached, _cached_at
    async with _lock:
        if _cached is None or time.monotonic() - _cached_at >= 60:
            _cached = await asyncio.to_thread(refresh_board)
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
