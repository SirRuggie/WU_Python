"""Owner decisions 1265–1267: close remains readable, member message reopens."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest

from extensions.commands.tickets import lifecycle


@pytest.fixture(autouse=True)
def mongo_expression_clock(monkeypatch):
    """Fixture-only evaluation of the CAS deadline; no real Mongo claim."""
    from tests import test_ticket_storage_foundation as fake
    original = fake._matches
    original_condition = fake._condition
    def condition(values, expected):
        if isinstance(expected,dict) and "$gte" in expected:
            if not any(value is not None and value >= expected["$gte"] for value in values):
                return False
            expected={key:value for key,value in expected.items() if key != "$gte"}
        return original_condition(values,expected)
    monkeypatch.setattr(fake,"_condition",condition)
    clock = NS(now=None)
    def expression(value, doc):
        if value == "$$NOW":
            return clock.now or datetime.now(timezone.utc)
        if isinstance(value,str) and value.startswith("$"):
            return doc.get(value[1:])
        if not isinstance(value,dict):
            return value
        op, items = next(iter(value.items()))
        if op == "$and": return all(expression(item,doc) for item in items)
        left, right = (expression(item,doc) for item in items)
        if op == "$subtract": return left-timedelta(milliseconds=right)
        if op == "$gte": return left is not None and left >= right
        if op == "$lte": return left is not None and left <= right
        raise AssertionError(f"Unsupported fixture expression {op}")
    def matches(doc, query):
        expr = query.get("$expr")
        return (expr is None or expression(expr,doc)) and original(doc,{k:v for k,v in query.items() if k != "$expr"})
    monkeypatch.setattr(fake,"_matches",matches)
    return clock


def test_close_archives_member_thread_unlocked_during_sixty_day_window():
    now = datetime.now(timezone.utc)
    rest = NS(fetch_channel=AsyncMock(return_value=NS(is_archived=False,is_locked=False)),
              edit_channel=AsyncMock())
    ticket = {'_id':'ticket_1','status':'closed','closed_at':now,'location':{'id':100,'staff_space_id':200}}
    asyncio.run(lifecycle.finish_effects(NS(rest=rest),NS(),ticket,'close'))
    edits = {call.args[0]: call.kwargs for call in rest.edit_channel.await_args_list}
    assert edits[100]['archived'] is True
    assert edits[100]['locked'] is False
    assert edits[200]['locked'] is True


def test_delayed_close_recovery_locks_member_thread_after_sixty_days():
    rest = NS(fetch_channel=AsyncMock(return_value=NS(is_archived=False,is_locked=False)),
              edit_channel=AsyncMock())
    ticket = {'_id':'ticket_1','status':'closed','closed_at':datetime.now(timezone.utc)-timedelta(days=61),
              'location':{'id':100,'staff_space_id':200}}
    asyncio.run(lifecycle.finish_effects(NS(rest=rest),NS(),ticket,'close'))
    assert rest.edit_channel.await_args_list[0].kwargs['locked'] is True


def _closed():
    from tests.test_ticket_storage_foundation import _ticket
    row = _ticket()
    row['status']='closed'
    row['closed_at'] = datetime.now(timezone.utc)-timedelta(days=1)
    row['resolution_effects'] = {'complete':True}
    return row


def _message(ticket, **changes):
    values = dict(id=321, author=NS(id=ticket['user_id'],username='Member',is_bot=False),
        guild_id=ticket['guild_id'], channel_id=ticket['location']['id'],
        timestamp=datetime.now(timezone.utc), webhook_id=None)
    return NS(**{**values,**changes})


def _reopen_setup(monkeypatch):
    from extensions.commands.tickets import resolve
    from extensions.commands import ticket_runtime
    monkeypatch.setattr(resolve,'_schedule_resolution_effects',lambda *args:None)
    monkeypatch.setattr(ticket_runtime,'get_rollout',AsyncMock(return_value=NS(revision=1)))
    claim=AsyncMock(return_value=ticket_runtime.SlotClaim(True,'owner',{'_id':'slot'}))
    monkeypatch.setattr(ticket_runtime,'claim_open_slot',claim)
    return claim


def test_member_message_reuses_guarded_transition_and_duplicate_only_wins_once(monkeypatch):
    from tests.test_ticket_storage_foundation import _mongo
    ticket = _closed()
    db = _mongo(ticket)
    claim = _reopen_setup(monkeypatch)
    async def run():
        result=await lifecycle.reopen_from_member_message(NS(),db,ticket,_message(ticket))
        assert result.won and result.doc['status']=='open'
        assert result.doc['handled_by']==ticket['user_id']
        assert result.doc['reopen_trigger']=={'kind':'member_message','message_id':321}
        duplicate=await lifecycle.reopen_from_member_message(NS(),db,ticket,_message(ticket,id=322))
        assert not duplicate.won
    asyncio.run(run())
    assert claim.await_count==1


def test_full_slot_does_not_reopen_and_notice_is_attempted_once(monkeypatch):
    from tests.test_ticket_storage_foundation import _mongo
    from extensions.commands import ticket_runtime
    ticket=_closed();db=_mongo(ticket)
    _reopen_setup(monkeypatch)
    monkeypatch.setattr(ticket_runtime,'claim_open_slot',AsyncMock(return_value=ticket_runtime.SlotClaim(False,None,{})))
    rest=NS(create_message=AsyncMock())
    async def run():
        for message_id in (321,322):
            result=await lifecycle.reopen_from_member_message(NS(rest=rest),db,ticket,_message(ticket,id=message_id))
            assert not result.won
        assert (await lifecycle.store.find_one(db,{'_id':ticket['_id']}))['status']=='closed'
    asyncio.run(run())
    rest.create_message.assert_awaited_once()


def test_wrong_author_bot_foreign_thread_and_expired_message_are_noops(monkeypatch):
    from tests.test_ticket_storage_foundation import _mongo
    ticket=_closed();claim=_reopen_setup(monkeypatch)
    cases=[_message(ticket,author=NS(id=999,is_bot=False)),
        _message(ticket,author=NS(id=ticket['user_id'],is_bot=True)),
        _message(ticket,channel_id=999),_message(ticket,guild_id=999),
        _message(ticket,timestamp=ticket['closed_at']-timedelta(seconds=1))]
    async def run():
        for message in cases:
            assert not (await lifecycle.reopen_from_member_message(NS(),_mongo(ticket),ticket,message)).won
        ticket['closed_at']=datetime.now(timezone.utc)-timedelta(days=61)
        assert not (await lifecycle.reopen_from_member_message(NS(),_mongo(ticket),ticket,_message(ticket))).won
    asyncio.run(run());claim.assert_not_awaited()


def test_missing_candidate_and_finishing_ghosted_cannot_reopen(monkeypatch):
    from tests.test_ticket_storage_foundation import _mongo
    from extensions.commands import ticket_runtime
    ticket=_closed();claim=_reopen_setup(monkeypatch)
    ticket['inactivity']={'prompt':{'state':'yes','token':'ghost'}}
    assert not asyncio.run(lifecycle.reopen_from_member_message(NS(),_mongo(ticket),ticket,_message(ticket))).won
    ticket.pop('inactivity')
    monkeypatch.setattr(ticket_runtime,'thread_missing_has_role',lambda row,role:role=='candidate')
    assert not asyncio.run(lifecycle.reopen_from_member_message(NS(),_mongo(ticket),ticket,_message(ticket))).won
    claim.assert_not_awaited()


def test_restart_expiry_lock_runs_even_when_quiet_archiving_is_disabled(monkeypatch):
    from extensions.commands.tickets import auto_archive as aa, store
    import hikari
    ticket=_closed();ticket['closed_at']=datetime.now(timezone.utc)-timedelta(days=61)
    config={'ticket_target_guild_id':ticket['guild_id'],'ticket_archive_quiet_days':0}
    db=NS(ticket_setup=NS(find_one=AsyncMock(return_value=config)))
    monkeypatch.setattr(store,'claim_member_window_sweep',AsyncMock(return_value=True))
    monkeypatch.setattr(store,'complete_member_window_lock',AsyncMock(return_value=True))
    monkeypatch.setattr(store,'expired_member_ticket_page',AsyncMock(return_value=[ticket]))
    monkeypatch.setattr(store,'claim_member_window_lock',AsyncMock(return_value={'rev':ticket.get('rev',0),'candidate_id':ticket['location']['id']}))
    monkeypatch.setattr(store,'clear_member_window_lock',AsyncMock())
    monkeypatch.setattr(store,'find_one',AsyncMock(return_value=ticket))
    rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=ticket['guild_id'],
        type=hikari.ChannelType.GUILD_PRIVATE_THREAD,is_locked=False)),edit_channel=AsyncMock())
    asyncio.run(aa.sweep(NS(rest=rest),db))
    rest.edit_channel.assert_awaited_once()
    assert rest.edit_channel.await_args.kwargs['locked'] is True


def test_reopen_wins_race_with_sixty_day_lock(monkeypatch):
    from extensions.commands.tickets import auto_archive as aa, store
    import hikari
    ticket=_closed();ticket['closed_at']=datetime.now(timezone.utc)-timedelta(days=61)
    monkeypatch.setattr(store,'expired_member_ticket_page',AsyncMock(return_value=[ticket]))
    monkeypatch.setattr(store,'claim_member_window_lock',AsyncMock(return_value={'rev':ticket.get('rev',0),'candidate_id':ticket['location']['id']}))
    monkeypatch.setattr(store,'clear_member_window_lock',AsyncMock())
    monkeypatch.setattr(store,'find_one',AsyncMock(side_effect=[ticket,{**ticket,'status':'open','rev':2}]))
    rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=ticket['guild_id'],
        type=hikari.ChannelType.GUILD_PRIVATE_THREAD,is_locked=False)),edit_channel=AsyncMock())
    asyncio.run(aa.lock_expired_member_threads(NS(rest=rest),NS(),{'ticket_target_guild_id':ticket['guild_id']}))
    assert [call.kwargs['locked'] for call in rest.edit_channel.await_args_list]==[True,False]
    assert rest.edit_channel.await_args.kwargs['archived'] is False


def test_slot_claim_delayed_beyond_deadline_cannot_win_atomic_update(monkeypatch,mongo_expression_clock):
    from tests.test_ticket_storage_foundation import _mongo
    from extensions.commands import ticket_runtime
    ticket=_closed();db=_mongo(ticket);_reopen_setup(monkeypatch)
    db.ticket_open_slots=NS(delete_one=AsyncMock())
    async def delayed(*args,**kwargs):
        mongo_expression_clock.now=ticket['closed_at']+timedelta(days=60,seconds=1)
        return ticket_runtime.SlotClaim(True,'owner',{'_id':'slot'})
    monkeypatch.setattr(ticket_runtime,'claim_open_slot',delayed)
    result=asyncio.run(lifecycle.reopen_from_member_message(NS(),db,ticket,_message(ticket)))
    assert not result.won
    assert db.tickets.documents[ticket['_id']]['status']=='closed'


def test_my_tickets_same_member_never_crosses_configured_guild():
    from tests.test_ticket_storage_foundation import _mongo
    from extensions.commands.tickets import store
    own=_closed();db=_mongo(own)
    foreign={**own,'_id':'ticket_999','guild_id':999}
    denied={**own,'_id':'ticket_998','status':'denied'}
    db.tickets.documents.update({foreign['_id']:foreign,denied['_id']:denied})
    rows=asyncio.run(store.member_visible_tickets(db,user_id=own['user_id'],
        guild_id=own['guild_id'],at=datetime.now(timezone.utc)))
    assert [row['_id'] for row in rows]==[own['_id']]


def test_failed_post_lock_read_is_recovered_even_after_ticket_reopened(monkeypatch):
    from extensions.commands.tickets import auto_archive as aa, store
    import hikari
    ticket=_closed();ticket['closed_at']=datetime.now(timezone.utc)-timedelta(days=61)
    marker={'rev':ticket.get('rev',0),'candidate_id':ticket['location']['id']}
    row={**ticket};opened={**ticket,'status':'open','rev':2,'member_window_lock':marker}
    pages=AsyncMock(side_effect=[[row],[opened]])
    monkeypatch.setattr(store,'expired_member_ticket_page',pages)
    monkeypatch.setattr(store,'claim_member_window_lock',AsyncMock(return_value=marker))
    clear=AsyncMock();monkeypatch.setattr(store,'clear_member_window_lock',clear)
    monkeypatch.setattr(store,'find_one',AsyncMock(side_effect=[ticket,RuntimeError('read unavailable'),opened]))
    rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=ticket['guild_id'],
        type=hikari.ChannelType.GUILD_PRIVATE_THREAD,is_locked=False)),edit_channel=AsyncMock())
    async def run():
        for _ in range(2):
            await aa.lock_expired_member_threads(NS(rest=rest),NS(),{'ticket_target_guild_id':ticket['guild_id']})
    asyncio.run(run())
    assert [call.kwargs['locked'] for call in rest.edit_channel.await_args_list]==[True,False]
    clear.assert_awaited_once()
