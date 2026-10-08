import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest
from extensions.commands.tickets import auto_archive as aa

NOW = datetime.now(timezone.utc)


class Messages:
    def __init__(self, items): self.items = items
    def limit(self, n): self.items = self.items[:n]; return self
    def __aiter__(self):
        async def run():
            for x in self.items: yield x
        return run()


def message(days, bot=False):
    return NS(timestamp=NOW-timedelta(days=days), author=NS(is_bot=bot), webhook_id=None)


def fixtures(status='approved'):
    ticket = {'_id':'t','status':status,'rev':1,'created_at':NOW-timedelta(days=30),
              'handled_at':NOW-timedelta(days=2),'location':{'id':10,'staff_space_id':11}}
    config = {'ticket_target_guild_id':1,'ticket_archive_quiet_days':1}
    rest = NS(fetch_channel=AsyncMock(side_effect=lambda cid:NS(id=cid,guild_id=1,type=hikari.ChannelType.GUILD_PUBLIC_THREAD,is_archived=False)),
              edit_channel=AsyncMock(),fetch_messages=lambda cid:Messages([message(3)]))
    mongo = NS(tickets=NS(find_one=AsyncMock(return_value=ticket),update_one=AsyncMock()),
               ticket_setup=NS(find_one=AsyncMock(return_value=config)))
    return ticket,config,NS(rest=rest),mongo


@pytest.mark.parametrize('status',['approved','denied','closed'])
def test_archives_both_resolved_threads_without_locking_or_changing_status(status):
    t,c,b,m=fixtures(status)
    assert asyncio.run(aa.archive_pair(b,m,t,c))
    assert [call.args[0] for call in b.rest.edit_channel.call_args_list]==[10,11]
    assert all(call.kwargs['archived'] and 'locked' not in call.kwargs for call in b.rest.edit_channel.call_args_list)
    assert 'status' not in m.tickets.update_one.call_args.args[1]['$set']


@pytest.mark.parametrize('active_id',[10,11])
def test_human_activity_in_either_thread_protects_pair(active_id):
    t,c,b,m=fixtures()
    b.rest.fetch_messages=lambda cid:Messages([message(0.1 if cid==active_id else 3)])
    assert not asyncio.run(aa.archive_pair(b,m,t,c))
    b.rest.edit_channel.assert_not_awaited()


def test_bot_messages_do_not_reset_timer():
    t,c,b,m=fixtures()
    b.rest.fetch_messages=lambda cid:Messages([message(0.1,bot=True),message(3)])
    assert asyncio.run(aa.archive_pair(b,m,t,c))


@pytest.mark.parametrize('change',[{'status':'open'},{'handled_at':NOW},{'mode':'test'}])
def test_open_recently_resolved_and_test_tickets_excluded(change):
    t,c,b,m=fixtures();t.update(change)
    assert not asyncio.run(aa.archive_pair(b,m,t,c))
    b.rest.edit_channel.assert_not_awaited()


def test_unknown_history_is_not_archived():
    t,c,b,m=fixtures();b.rest.fetch_messages=lambda cid:Messages([message(0.1,bot=True)]*500)
    assert not asyncio.run(aa.archive_pair(b,m,t,c))


def test_new_message_during_archive_restores_pair():
    t,c,b,m=fixtures()
    b.rest.fetch_messages=lambda cid:Messages([message(0.1 if b.rest.edit_channel.await_count else 3)])
    assert not asyncio.run(aa.archive_pair(b,m,t,c))
    calls=b.rest.edit_channel.call_args_list
    assert len(calls)==2 and calls[0].kwargs['archived'] and not calls[1].kwargs['archived']


def test_reopen_during_archive_restores_pair():
    t,c,b,m=fixtures()
    m.tickets.find_one.side_effect=[t,{**t,'status':'open','rev':2}]
    assert not asyncio.run(aa.archive_pair(b,m,t,c))
    assert [x.kwargs['archived'] for x in b.rest.edit_channel.call_args_list]==[True,True,False,False]


def test_disabled_and_invalid_periods():
    t,c,b,m=fixtures();c['ticket_archive_quiet_days']=0
    assert not asyncio.run(aa.archive_pair(b,m,t,c))
    assert aa.quiet_days({})==1
    with pytest.raises(ValueError):aa.quiet_days({'ticket_archive_quiet_days':366})


def test_daily_completion_prevents_repeat_on_restart():
    t,c,b,m=fixtures()
    m.ticket_setup.find_one.side_effect=[c,{'completed_at':NOW}]
    b.rest.fetch_active_threads=AsyncMock()
    asyncio.run(aa.sweep(b,m))
    b.rest.fetch_active_threads.assert_not_awaited()


def test_partial_pair_failure_restores_first_thread():
    t,c,b,m=fixtures()
    b.rest.edit_channel.side_effect=[None,RuntimeError('Discord unavailable'),None]
    with pytest.raises(RuntimeError):asyncio.run(aa.archive_pair(b,m,t,c))
    calls=b.rest.edit_channel.call_args_list
    assert calls[-1].args==(10,) and calls[-1].kwargs['archived'] is False
    m.tickets.update_one.assert_not_awaited()


def test_permission_failure_does_not_archive_any_thread():
    t,c,b,m=fixtures();b.rest.fetch_channel.side_effect=RuntimeError('Forbidden')
    with pytest.raises(RuntimeError):asyncio.run(aa.archive_pair(b,m,t,c))
    b.rest.edit_channel.assert_not_awaited()
