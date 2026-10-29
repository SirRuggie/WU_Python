"""Shared signup posts must only create a private, read-only member response."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import hikari

from extensions.commands import cwl_member as member
from test_cwl_discord_member import Context
from utils.cwl_member_summary import timing_lines


def view(count=2):
    return {'season': {'id': 1, 'label': 'November CWL', 'status': 'draft', 'signup_open': True},
            'accounts_status': 'ok', 'accounts': [{'tag': f'#P2Y2Y2Y{i}', 'name': name} for i, name in enumerate(['Aurora', 'Ace', 'Birch', 'Cedar', 'Dawn'])],
            'signups': [{'tag': f'#P2Y2Y2Y{i}', 'player_name': name, 'pool': 'main' if i == 0 else 'lazy'} for i, name in enumerate(['Aurora', 'Ace'][:count])]}


def test_shared_button_opens_private_signups_without_edit_or_write():
    async def run():
        ctx = Context()
        from utils import cwl_member_client
        with patch.object(cwl_member_client, 'request', new=AsyncMock(return_value=view())) as bridge:
            await member.check_signups(ctx, 'open')
            assert bridge.call_count == 1
            assert bridge.call_args.args[0] == 'view'
        assert not ctx.interaction.edits
        args, response = ctx.followups[0]
        assert response['flags'] & hikari.MessageFlag.EPHEMERAL
        assert not response['user_mentions'] and not response['role_mentions'] and not response['mentions_everyone']
        rendered = str(response['components'][0].build()[0])
        assert "You're signed up · 2 of 5 accounts" in rendered
        assert 'Aurora · Main CWL' in rendered and 'Ace · Lazy CWL' in rendered
        assert '3 accounts not signed up' in rendered
        assert 'Birch' in rendered and 'Dawn' in rendered
        assert 'Sign up for CWL' in rendered
    asyncio.run(run())


def test_zero_all_closed_unknown_and_pagination():
    session = member.MemberSession(123, member.WARRIORS_UNITED_GUILD_ID, 0, view=view(0), screen='my_signups')
    assert "You haven't signed up any accounts yet." in member._main_text(session)
    assert member._components('token', session)[0].components[0].url.endswith('/signup')
    session.view = view(1)
    session.view['accounts'] = session.view['accounts'][:1]
    assert 'all 1 account' in member._main_text(session)
    session.view = view()
    session.view['season']['signup_open'] = False
    assert "3 accounts weren't signed up · signups are closed" in member._main_text(session)
    assert 'signup_pick' not in str(member._components('token', session))
    session.view['accounts_status'] = 'unavailable'
    assert 'of 5' not in member._main_text(session)
    session.view = view()
    session.view['accounts'] += [{'tag': f'#P222{i:04}', 'name': f'Player {i}'} for i in range(40)]
    session.page = 2
    assert member._signup_pages(session) == 3
    assert 'Player 39' in member._main_text(session)
    # A remaining-only page must not contain an empty Discord select menu.
    assert all(not hasattr(item, 'options') for row in member._components('token', session) for item in row.components)


def test_bad_identity_or_service_failure_stays_private():
    async def run():
        for ctx in (Context(guild_id=1), Context(in_guild=False), Context()):
            with patch.object(member, '_refresh', new=AsyncMock(side_effect=OSError('fake outage'))):
                await member.check_signups(ctx, 'open')
            assert not ctx.interaction.edits
            assert ctx.followups[0][1]['flags'] & hikari.MessageFlag.EPHEMERAL
    asyncio.run(run())


def test_discord_timing_uses_localized_timestamps_and_past_due_text():
    season = {'signup_open': True, 'status': 'draft', 'signup_deadline': '2026-10-30T21:00:00+00:00', 'placements_by': '2026-10-31T21:00:00+00:00'}
    assert len(timing_lines(season, now=datetime(2026, 10, 28, tzinfo=timezone.utc))) == 2
    season['signup_open'] = False
    assert 'Signups closed' in timing_lines(season, now=datetime(2026, 10, 31, tzinfo=timezone.utc))[0]
    assert timing_lines(season, now=datetime(2026, 11, 1, tzinfo=timezone.utc)) == ['Taking a little longer than usual · check back soon']
    assert timing_lines({}) == []
    assert timing_lines(season, published=True) == []
