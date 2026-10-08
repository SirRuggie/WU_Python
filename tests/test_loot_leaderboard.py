import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

from extensions.commands import loot_leaderboard as command
from utils import gold_loot
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID


def test_api_failure_keeps_original_baseline_and_warns(tmp_path, monkeypatch):
    path = tmp_path / 'loot.sqlite3'
    db = gold_loot.connect(path)
    timestamp = '2026-10-08T13:47:41+00:00'
    with db:
        db.execute('INSERT INTO session VALUES (?, ?, ?)', ('#CLAN', 'Warriors United', timestamp))
        db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)',
                   ('#ABC', '**Player** @everyone', 1000, 1600, timestamp, timestamp))
    db.close()
    monkeypatch.setattr(gold_loot, 'collect', AsyncMock(side_effect=ValueError('unavailable')))
    board = gold_loot.refresh_board(path)
    assert board['rows'][0]['looted'] == 600
    assert board['session']['started'] == timestamp
    assert 'last saved totals' in board['warning']
    panel = command.render_board(board)[0]
    assert panel.accent_color == GOLDENROD_ACCENT
    payload = str(panel.build())
    assert '600' in payload and 'Gold Loot Leaderboard' in payload
    assert '@everyone' not in payload
    assert 'Refresh unavailable' in payload


def test_concurrent_requests_share_refresh(monkeypatch):
    calls = []
    def refresh():
        calls.append(1)
        return {'rows': []}
    monkeypatch.setattr(command, 'refresh_board', refresh)
    monkeypatch.setattr(command, '_cached', None)
    async def run():
        monkeypatch.setattr(command, '_lock', asyncio.Lock())
        results = await asyncio.gather(command.load_board(), command.load_board())
        assert results[0] is results[1]
    asyncio.run(run())
    assert len(calls) == 1


def test_command_missing_baseline_returns_components(monkeypatch):
    monkeypatch.setattr(command, 'load_board', AsyncMock(side_effect=ValueError('missing')))
    ctx = SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID, defer=AsyncMock(),
                          interaction=SimpleNamespace(edit_initial_response=AsyncMock()))
    asyncio.run(command.execute(ctx))
    ctx.defer.assert_awaited_once()
    kwargs = ctx.interaction.edit_initial_response.call_args.kwargs
    assert 'content' not in kwargs
    assert kwargs['mentions_everyone'] is False
    assert 'unavailable' in str(kwargs['components'][0].build())


def test_wrong_guild_does_not_read_tracker(monkeypatch):
    load = AsyncMock()
    monkeypatch.setattr(command, 'load_board', load)
    ctx = SimpleNamespace(guild_id=1, respond=AsyncMock())
    asyncio.run(command.execute(ctx))
    load.assert_not_called()
    assert ctx.respond.call_args.kwargs['ephemeral'] is True
