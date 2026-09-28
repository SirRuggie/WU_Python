import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from extensions.commands.tickets import handlers


@pytest.mark.parametrize('post_commit_failure', [False, True])
def test_ticket_link_shown_before_post_commit_work_and_retained_on_failure(monkeypatch, post_commit_failure):
    edits=[]
    async def edit(**kwargs): edits.append(kwargs)
    ctx=SimpleNamespace(guild_id=11,channel_id=22,user=SimpleNamespace(id=50,username='Tester'),
        member=SimpleNamespace(role_ids=(),display_name='Tester'),defer=AsyncMock(),
        interaction=SimpleNamespace(message=SimpleNamespace(id=32),edit_initial_response=edit))
    ticket={'guild_id':11,'ticket_type':'fwa','ticket_number':810,'location':{'id':99}}
    monkeypatch.setattr(handlers,'thread_intake_ready',lambda:True)
    monkeypatch.setattr(handlers.ticket_runtime,'route_public_intake',AsyncMock(return_value=SimpleNamespace(allowed=True,route='thread',revision=1)))
    monkeypatch.setattr(handlers.ticket_runtime,'claim_open_slot',AsyncMock(return_value=SimpleNamespace(won=True)))
    async def create(**kwargs):
        assert edits[-1]['content']=='🎫 Creating your ticket…'
        await kwargs['on_ready'](ticket)
        assert edits[-1]['components'][0].components[0].url=='https://discord.com/channels/11/99'
        assert edits[-1]['content']=='✅ Your FWA ticket #810 is created.'
        if post_commit_failure: raise RuntimeError('account lookup failed after commit')
        return SimpleNamespace(ticket=ticket,resumed=False,delivery_pending=False)
    monkeypatch.setattr(handlers.thread_service,'create_live_thread_ticket',create)
    handlers.user_cooldowns.clear()
    mongo=SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={})))
    asyncio.run(handlers.handle_create_ticket(ctx,'public:fwa',bot=object(),mongo=mongo))
    assert 'Creating your ticket' not in edits[-1]['content']
    assert edits[-1]['components'][0].components[0].label=='Open your ticket'
    assert 'could not be completed' not in edits[-1]['content']
    handlers.user_cooldowns.clear()
