import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.setup import recruit_join_family, recruit_aboutus, recruit_strikesystem, recruit_familyparticulars
from utils import gauntlet_help, gauntlet_tracking

GUILD = 644963518025826315

@pytest.mark.parametrize('module,handler,role,stage', [
    (recruit_join_family, 'on_join_family_acknowledge', 1551011479577165844, 1),
    (recruit_aboutus, 'on_aboutus_acknowledge', 1553110276251979937, 2),
    (recruit_strikesystem, 'on_strikesystem_acknowledge', 1553110508746448956, 3),
    (recruit_familyparticulars, 'on_familyparticulars_acknowledge', 1553110621711634502, 4),
])
@pytest.mark.parametrize('already_has_role', [False, True])
def test_successful_confirmation_tracks_stage(monkeypatch, module, handler, role, stage, already_has_role):
    track = AsyncMock()
    monkeypatch.setattr(module, 'track_progress', track)
    mongo = SimpleNamespace()
    rest = SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=GUILD)),
                           fetch_member=AsyncMock(return_value=SimpleNamespace(role_ids=[role] if already_has_role else [])),
                           add_role_to_member=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), interaction=SimpleNamespace(guild_id=GUILD, execute=AsyncMock()))
    asyncio.run(getattr(module, handler)('persistent', ctx=ctx, bot=SimpleNamespace(rest=rest), mongo=mongo))
    track.assert_awaited_once_with(mongo, GUILD, 123, stage)
    assert rest.add_role_to_member.await_count == (0 if already_has_role else 1)


def test_failed_role_grant_does_not_start_timer(monkeypatch):
    track = AsyncMock()
    monkeypatch.setattr(recruit_join_family, 'track_progress', track)
    rest = SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=GUILD)),
                           fetch_member=AsyncMock(return_value=SimpleNamespace(role_ids=[])),
                           add_role_to_member=AsyncMock(side_effect=RuntimeError('denied')))
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), interaction=SimpleNamespace(guild_id=GUILD, execute=AsyncMock()))
    asyncio.run(recruit_join_family.on_join_family_acknowledge('persistent',ctx=ctx,bot=SimpleNamespace(rest=rest),mongo=SimpleNamespace()))
    track.assert_not_awaited()


def test_reminder_storage_failure_does_not_break_success(monkeypatch):
    monkeypatch.setattr(gauntlet_help, 'record_progress', AsyncMock(side_effect=RuntimeError('database unavailable')))
    asyncio.run(gauntlet_tracking.track_progress(SimpleNamespace(), GUILD, 123, 1))


@pytest.mark.parametrize('ticket_type,guild,expected', [('main',GUILD,1),('fwa',GUILD,1),('support',GUILD,0),('main',999,0)])
def test_only_application_ticket_completion_is_tracked(monkeypatch,ticket_type,guild,expected):
    done=AsyncMock()
    monkeypatch.setattr(gauntlet_help,'complete_progress',done)
    mongo=SimpleNamespace()
    asyncio.run(gauntlet_tracking.ticket_opened(mongo,{'_id':'ticket','ticket_type':ticket_type,'guild_id':guild,'user_id':123}))
    assert done.await_count==expected
    if expected: done.assert_awaited_once_with(mongo,GUILD,123)
