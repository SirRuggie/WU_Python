"""Manual Ghosted uses the inactivity receipt and canonical Close CAS."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from extensions.commands.tickets import inactivity, lifecycle, store, flag_store
from tests.test_ticket_storage_foundation import _mongo, _ticket


@pytest.fixture
def setup(monkeypatch):
    @asynccontextmanager
    async def guard(*args,**kwargs): yield
    monkeypatch.setattr(flag_store,'identity_guard',guard)
    monkeypatch.setattr(inactivity.perms,'is_recruiter',AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity.perms,'can_handle',AsyncMock(return_value=True))
    monkeypatch.setattr(lifecycle.resolve,'_schedule_resolution_effects',lambda *args:None)
    monkeypatch.setattr(inactivity,'finish_ghosted',AsyncMock(return_value=True))
    return NS(id=9,guild_id=10)


def test_manual_ghosted_closes_once_with_same_reason_and_member_audit(setup):
    ticket=_ticket();db=_mongo(ticket)
    result=asyncio.run(inactivity.apply_manual_ghosted(NS(),db,ticket=ticket,member=setup,
        actor_name='Recruiter',reason='Recruit stopped replying'))
    assert result.won
    assert result.doc['status']=='closed'
    assert result.doc['closure_reason']=='Recruit stopped replying'
    assert result.doc['closed_by']==9
    assert result.doc['inactivity']['prompt']['state']=='yes'
    assert result.doc['audit'][-1]['inactivity_token']==result.doc['inactivity']['prompt']['token']
    inactivity.finish_ghosted.assert_awaited_once()


@pytest.mark.parametrize('status',['closed','approved','denied'])
def test_manual_helper_never_closes_terminal_ticket_again(setup,status,monkeypatch):
    ticket=_ticket();ticket['status']=status
    close=AsyncMock();monkeypatch.setattr(inactivity,'close_as_ghosted',close)
    result=asyncio.run(inactivity.apply_manual_ghosted(NS(),_mongo(ticket),ticket=ticket,
        member=setup,actor_name='Recruiter',reason='Already resolved'))
    assert not result.won;close.assert_not_awaited()


def test_staff_and_stale_flag_snapshot_do_not_close_or_set_flag(setup,monkeypatch):
    ticket=_ticket();ticket['ticket_type']='staff'
    claim=AsyncMock();monkeypatch.setattr(store,'claim_manual_ghosted',claim)
    result=asyncio.run(inactivity.apply_manual_ghosted(NS(),_mongo(ticket),ticket=ticket,
        member=setup,actor_name='Recruiter',reason='No response received'))
    assert not result.won;claim.assert_not_awaited()
    ticket['ticket_type']='main'
    monkeypatch.setattr(flag_store,'current_flag_expectation',AsyncMock(return_value=flag_store.FlagMutation(store.LOST,None,'Flag changed')))
    result=asyncio.run(inactivity.apply_manual_ghosted(NS(),_mongo(ticket),ticket=ticket,
        member=setup,actor_name='Recruiter',reason='No response received',check_expected=True))
    assert not result.won;claim.assert_not_awaited()


def test_flag_failure_leaves_closed_ticket_and_recoverable_receipt(setup,monkeypatch):
    ticket=_ticket();db=_mongo(ticket)
    monkeypatch.setattr(inactivity,'finish_ghosted',AsyncMock(side_effect=RuntimeError('offline')))
    result=asyncio.run(inactivity.apply_manual_ghosted(NS(),db,ticket=ticket,member=setup,
        actor_name='Recruiter',reason='No response received'))
    assert result.won and result.doc['status']=='closed'
    assert result.doc['inactivity']['prompt']['state']=='yes'
    assert 'recovery' in result.reason


def test_flag_receipt_sets_the_same_reason_and_recovery_is_idempotent(setup,monkeypatch):
    ticket=_ticket();db=_mongo(ticket)
    monkeypatch.setattr(flag_store,'ensure_indexes',AsyncMock())
    existing={'_id':'ghost','kind':'ghosted','active':True,'discord_ids':[str(ticket['user_id'])],
        'player_tags':[],'reason':'Earlier reason','rev':1,'audit':[]}
    db.ticket_flags.documents['ghost']=existing
    prompt={'token':'manual-1','manual_flag_update':True,'expected_flag_id':'ghost','expected_flag_rev':1,'source':'Manual staff Ghosted flag'}
    async def run():
        first=await flag_store.apply_ghosted_close_receipt(db,ticket=ticket,prompt=prompt,
            audit={'actor':9,'actor_name':'Recruiter'},reason='Exact closing reason')
        assert first.won and first.doc['reason']=='Exact closing reason'
        second=await flag_store.apply_ghosted_close_receipt(db,ticket=ticket,prompt=prompt,
            audit={'actor':9,'actor_name':'Recruiter'},reason='Exact closing reason')
        assert second.won and second.doc['rev']==first.doc['rev']
        assert len(second.doc['audit'])==1
    asyncio.run(run())


def test_flag_receipt_never_overwrites_newer_staff_edit_after_close(setup):
    ticket=_ticket();db=_mongo(ticket)
    db.ticket_flags.documents['ghost']={'_id':'ghost','kind':'ghosted','active':True,
        'discord_ids':[str(ticket['user_id'])],'player_tags':[],'reason':'New staff decision','rev':2}
    result=asyncio.run(flag_store.apply_ghosted_close_receipt(db,ticket=ticket,
        prompt={'token':'manual-1','manual_flag_update':True,'expected_flag_id':'ghost','expected_flag_rev':1},
        audit={'actor':9},reason='Older close reason'))
    assert not result.won
    assert db.ticket_flags.documents['ghost']['reason']=='New staff decision'
