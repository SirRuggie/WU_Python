import asyncio
import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace

from extensions.commands import loot_leaderboard as command
from utils import gold_loot
from utils.recruit_links import PlayerOwners
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID


@pytest.fixture(autouse=True)
def mock_town_hall_lookup(monkeypatch):
    monkeypatch.setattr(command, 'load_town_halls', AsyncMock(return_value={}))
    monkeypatch.setattr(command, 'load_discord_labels', AsyncMock(return_value={}))


def test_api_failure_keeps_original_baseline_and_warns(tmp_path, monkeypatch):
    path = tmp_path / 'loot.sqlite3'
    db = gold_loot.connect(path)
    timestamp = '2026-10-08T13:47:41+00:00'
    with db:
        db.execute('INSERT INTO session VALUES (?, ?, ?)', ('#CLAN', 'Warriors United', timestamp))
        db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)',
                   ('#ABC', '**Player** @everyone', 1000, 1600, timestamp, timestamp))
    with db:
        db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)', ('#ABC', timestamp, 'farming', 600))
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
    monkeypatch.setattr(command, 'resolve_players', AsyncMock(return_value=PlayerOwners()))
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


def test_linked_accounts_and_compact_update_panel():
    board = dict(session={'started': '2026-10-08T13:47:41+00:00'}, count=44,
                 rows=[dict(tag='#ABC', name='Player', looted=12500)],
                 owners={'#ABC': '123456789012345678'}, warning=None)
    payload = str(command.render_board(board)[0].build())
    assert 'https://discord.com/users/123456789012345678' in payload
    assert '<@123456789012345678>' not in payload
    assert '12,500' in payload
    assert 'loot_leaderboard_update:main' in payload
    assert 'Player samples' not in payload
    assert 'Fixed starting roster' not in payload
    assert '60 seconds' not in payload
    board['owners'] = {}
    assert 'No linked Discord account' in str(command.render_board(board)[0].build())
    board['owners'] = None
    assert 'Link unavailable' in str(command.render_board(board)[0].build())


def test_update_button_forces_refresh(monkeypatch):
    load = AsyncMock(return_value={'test': True})
    monkeypatch.setattr(command, 'load_board', load)
    monkeypatch.setattr(command, 'render_board', lambda board: ['updated panel'])
    ctx = SimpleNamespace(interaction=SimpleNamespace(
        guild_id=WARRIORS_UNITED_GUILD_ID, edit_initial_response=AsyncMock()))
    asyncio.run(command.update_leaderboard(ctx, 'main'))
    ctx.interaction.edit_initial_response.assert_awaited_once_with(
        components=['updated panel'], user_mentions=False, role_mentions=False, mentions_everyone=False)
    load.assert_awaited_once_with(force=True)


def test_force_refresh_bypasses_recent_cache(monkeypatch):
    monkeypatch.setattr(command, '_cached', {'old': True})
    monkeypatch.setattr(command, '_cached_at', command.time.monotonic())
    monkeypatch.setattr(command, 'refresh_board', lambda: {'rows': [{'tag': '#ABC'}]})
    links = AsyncMock(return_value=PlayerOwners(owners={'#ABC': '123'}))
    monkeypatch.setattr(command, 'resolve_players', links)
    async def run():
        monkeypatch.setattr(command, '_lock', asyncio.Lock())
        result = await command.load_board(force=True)
        assert result['owners'] == {'#ABC': '123'}
    asyncio.run(run())
    links.assert_awaited_once_with(['#ABC'])


def test_tracking_times_are_small_footer_below_rankings():
    board = dict(session={'started': '2026-10-08T13:47:41+00:00'}, count=44,
                 newest='2026-10-08T14:00:00+00:00',
                 rows=[dict(tag='#ABC', name='Player', looted=12500)],
                 owners={}, warning=None)
    panel = command.render_board(board)[0]
    texts = [c.content for c in panel.components if hasattr(c, 'content')]
    footer = next(t for t in texts if 'Tracking started:' in t)
    assert footer.startswith('-# Tracking started:')
    assert '\n-# Last refreshed:' in footer
    assert '44 players' in footer
    assert texts.index(footer) > next(i for i, t in enumerate(texts) if '12,500' in t)
    assert 'tracked players' not in texts[0]


def test_link_conflict_and_provider_outage_are_not_unlinked():
    board = dict(session={'started': '2026-10-08T13:47:41+00:00'}, count=44,
                 rows=[dict(tag='#ABC', name='Player', looted=10)],
                 owners={}, warning=None, link_conflicts=('#ABC',))
    assert 'Link conflict' in str(command.render_board(board)[0].build())
    board['link_conflicts'] = ()
    board['link_unavailable'] = ('ClashPerk',)
    payload = str(command.render_board(board)[0].build())
    assert 'Link unavailable' in payload
    assert 'No linked Discord account' not in payload


def test_row_shows_th_emoji_tag_discord_clan_and_loot():
    board = dict(session={'started': '2026-10-08T13:47:41+00:00'}, count=551,
                 rows=[dict(tag='#RU00V8UP', name='Sir Ruggie', looted=1665325, clan_name='Warriors United')],
                 owners={'#RU00V8UP': '123456789012345678'}, warning=None,
                 town_halls={'#RU00V8UP': 18})
    payload = str(command.render_board(board)[0].build())
    assert str(command.emojis.TH18) in payload
    assert '`#RU00V8UP`' in payload
    assert 'https://discord.com/users/123456789012345678' in payload
    assert '<@123456789012345678>' not in payload
    assert 'Warriors United' in payload and '1,665,325' in payload
    assert 'clashk.ing' not in payload


def test_explicit_name_and_id_do_not_depend_on_mentions():
    board = dict(session={'started': '2026-10-08T13:47:41+00:00'}, count=551,
                 rows=[dict(tag='#ABC', name='Player', looted=1)],
                 owners={'#ABC': '123456789012345678'}, warning=None,
                 discord_labels={'123456789012345678': 'Luke'})
    payload = str(command.render_board(board)[0].build())
    assert '[Luke](https://discord.com/users/123456789012345678)' in payload
    assert '`123456789012345678`' not in payload
    assert '<@' not in payload


def test_command_posts_standalone_in_invoking_channel(monkeypatch):
    monkeypatch.setattr(command, 'load_board', AsyncMock(return_value={}))
    monkeypatch.setattr(command, 'render_board', lambda _: ['panel'])
    rest = SimpleNamespace(create_message=AsyncMock())
    interaction = SimpleNamespace(app=SimpleNamespace(rest=rest),
        delete_initial_response=AsyncMock(), edit_initial_response=AsyncMock())
    ctx = SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID, channel_id=123,
                          defer=AsyncMock(), interaction=interaction)
    asyncio.run(command.execute(ctx))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    rest.create_message.assert_awaited_once_with(
        123, components=['panel'], user_mentions=False, role_mentions=False, mentions_everyone=False)
    interaction.delete_initial_response.assert_awaited_once()
    interaction.edit_initial_response.assert_not_awaited()
