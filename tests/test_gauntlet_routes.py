import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands import content
from extensions.commands.setup import recruit_aboutus, recruit_strikesystem, recruit_familyparticulars
from utils.gauntlet_routes import LEGACY_GUILD_ID, NEW_GUILD_ID, route_for

STEPS = [
    ('about-us', recruit_aboutus, 'on_aboutus_acknowledge'),
    ('strike-system', recruit_strikesystem, 'on_strikesystem_acknowledge'),
    ('family-particulars', recruit_familyparticulars, 'on_familyparticulars_acknowledge'),
]


@pytest.mark.parametrize('guild', [LEGACY_GUILD_ID, NEW_GUILD_ID])
@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('key,module,handler', STEPS)
def test_each_server_grants_only_its_role_and_links_its_channel(monkeypatch, guild, existing, key, module, handler):
    role, channel = route_for(key, guild)
    track = AsyncMock()
    monkeypatch.setattr(module, 'track_progress', track)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), interaction=SimpleNamespace(guild_id=guild, execute=AsyncMock()))
    rest = SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=guild)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(role_ids=[role] if existing else [])),
        add_role_to_member=AsyncMock())
    asyncio.run(getattr(module, handler)('old-persistent-button', ctx=ctx, bot=SimpleNamespace(rest=rest), mongo=object()))
    rest.fetch_channel.assert_awaited_once_with(channel)
    if existing:
        rest.add_role_to_member.assert_not_awaited()
    else:
        rest.add_role_to_member.assert_awaited_once_with(guild=guild, user=123, role=role)
    link = ctx.interaction.execute.call_args.kwargs['components'][0].components[-1].components[0]
    assert link.url == f'https://discord.com/channels/{guild}/{channel}'
    assert content.acknowledgement_setup(key, guild) == (role, channel)
    assert track.await_count == (1 if guild == NEW_GUILD_ID else 0)


@pytest.mark.parametrize('key,module,handler', STEPS)
def test_cross_server_channel_is_rejected(monkeypatch, key, module, handler):
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), interaction=SimpleNamespace(guild_id=LEGACY_GUILD_ID, execute=AsyncMock()))
    rest = SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=NEW_GUILD_ID)),
        fetch_member=AsyncMock(), add_role_to_member=AsyncMock())
    asyncio.run(getattr(module, handler)('old-button', ctx=ctx, bot=SimpleNamespace(rest=rest), mongo=object()))
    rest.fetch_member.assert_not_awaited()
    rest.add_role_to_member.assert_not_awaited()
    assert 'content' in ctx.interaction.execute.call_args.kwargs
