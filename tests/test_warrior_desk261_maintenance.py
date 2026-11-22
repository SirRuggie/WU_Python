"""1280 durable completion, hourly REST bounds and unchanged recovery paths."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError
from extensions.commands.tickets import auto_archive as aa, store
from tests import test_ticket_storage_foundation as fake

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)


class Cursor(fake.Cursor):
    def sort(self, spec, direction=None):
        return super().sort([(spec, direction)] if direction is not None else spec)


class Tickets(fake.Collection):
    def find(self, query, *_args, **_kwargs):
        return Cursor(row for row in self.documents.values() if fake._matches(row, query))


class Setup(fake.SetupCollection):
    async def find_one_and_update(self, query, update, **kwargs):
        result = await super().find_one_and_update(query, update)
        if result is None and kwargs.get('upsert'):
            if query['_id'] in self.documents:
                raise DuplicateKeyError('existing hourly claim')
            result = {'_id': query['_id'], **deepcopy(update['$set'])}
            self.documents[result['_id']] = result
        return deepcopy(result)


@pytest.fixture(autouse=True)
def fixture_clock_and_queries(monkeypatch):
    original = fake._condition
    def condition(values, expected):
        if isinstance(expected, dict) and '$lt' in expected:
            if not any(value is not None and value < expected['$lt'] for value in values):
                return False
            expected = {key: value for key, value in expected.items() if key != '$lt'}
            if not expected:
                return True
        if isinstance(expected, dict) and '$gt' in expected:
            if not any(value is not None and value > expected['$gt'] for value in values):
                return False
            expected = {key: value for key, value in expected.items() if key != '$gt'}
            if not expected:
                return True
        return original(values, expected)
    monkeypatch.setattr(fake, '_condition', condition)
    monkeypatch.setattr(aa, 'now', lambda: NOW)
    monkeypatch.setattr(aa, '_member_expiry_after', '')


def ticket(number=1):
    row = fake._ticket(number=number, public=100+number, staff=200+number)
    row.update(status='closed', closed_at=NOW-timedelta(days=61), resolution_effects={'complete': True})
    return row


def mongo(*rows):
    db = fake._mongo(*rows)
    db.tickets = Tickets(rows)
    db.ticket_setup = Setup()
    db.ticket_open_slots = fake.Collection()
    db.ticket_setup.documents['config'].update(ticket_target_guild_id=10, ticket_archive_quiet_days=0)
    return db


def bot(*, locked=False):
    return NS(get_me=lambda: NS(id=99), rest=NS(
        fetch_channel=AsyncMock(side_effect=lambda cid: NS(id=cid,guild_id=10,
            type=hikari.ChannelType.GUILD_PRIVATE_THREAD,is_locked=locked,owner_id=99)),
        edit_channel=AsyncMock()))


@pytest.mark.parametrize('locked', [False, True])
def test_proven_lock_is_durable_and_not_fetched_again(locked):
    row=ticket();db=mongo(row);b=bot(locked=locked)
    async def run():
        await aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config'])
        aa._member_expiry_after=''  # Restarted cursor still respects durable completion.
        await aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config'])
    asyncio.run(run())
    assert db.tickets.documents[row['_id']]['member_window_locked_at']==NOW
    assert 'member_window_lock' not in db.tickets.documents[row['_id']]
    b.rest.fetch_channel.assert_awaited_once()
    assert b.rest.edit_channel.await_count == (0 if locked else 1)


def test_missing_thread_is_completed_and_not_refetched():
    row=ticket();db=mongo(row);b=bot()
    b.rest.fetch_channel.side_effect=hikari.NotFoundError(url='fixture',headers={},raw_body=b'',message='missing',code=10003)
    async def run():
        for _ in range(2):await aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config'])
    asyncio.run(run());b.rest.fetch_channel.assert_awaited_once()
    assert db.tickets.documents[row['_id']]['member_window_locked_at']==NOW


def test_failed_lock_remains_retryable_with_crash_marker():
    row=ticket();db=mongo(row);b=bot();b.rest.edit_channel.side_effect=[RuntimeError('offline'),None]
    async def run():
        await aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config'])
        current=db.tickets.documents[row['_id']]
        assert 'member_window_locked_at' not in current and 'member_window_lock' in current
        await aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config'])
        assert current['member_window_locked_at']==NOW and 'member_window_lock' not in current
    asyncio.run(run());assert b.rest.edit_channel.await_count==2


def test_completion_cas_cannot_hide_reopened_pending_repair():
    row=ticket();db=mongo(row);marker={'rev':row['rev'],'candidate_id':row['location']['id']}
    current=db.tickets.documents[row['_id']];current.update(status='open',rev=row['rev']+1,member_window_lock=marker)
    assert not asyncio.run(store.complete_member_window_lock(db,row,row['location']['id'],at=NOW,marker=marker))
    assert 'member_window_locked_at' not in current
    b=bot(locked=True)
    asyncio.run(aa.lock_expired_member_threads(b,db,db.ticket_setup.documents['config']))
    assert b.rest.edit_channel.await_args.kwargs['locked'] is False
    assert 'member_window_lock' not in current


def test_reopen_and_later_close_clear_old_completion():
    row=ticket();row['member_window_locked_at']=NOW;db=mongo(row)
    async def run():
        opened=await store.transition(db,row['_id'],to_status='open',actor_id=99,
            actor_name='Staff',expect='closed',expected_rev=row['rev'],effect_kind='reopen')
        assert opened.won and 'member_window_locked_at' not in opened.doc
        # Even a stale marker attached to the open generation cannot suppress its next Close.
        db.tickets.documents[row['_id']]['member_window_locked_at']=NOW
        closed=await store.transition(db,row['_id'],to_status='closed',actor_id=99,
            actor_name='Staff',expect='open',expected_rev=opened.doc['rev'],effect_kind='close')
        assert closed.won and 'member_window_locked_at' not in closed.doc
        rows=await store.expired_member_ticket_page(db,guild_id=10,cutoff=closed.doc['closed_at']+timedelta(days=1))
        assert [x['_id'] for x in rows]==[row['_id']]
    asyncio.run(run())


def test_lock_pass_claim_is_hourly_and_survives_restart(monkeypatch):
    db=mongo();expiry=AsyncMock();monkeypatch.setattr(aa,'lock_expired_member_threads',expiry)
    async def run():
        await aa.sweep(NS(),db)
        aa._member_expiry_after=''
        await aa.sweep(NS(),db)
        assert expiry.await_count==1
        monkeypatch.setattr(aa,'now',lambda:NOW+timedelta(hours=1))
        await aa.sweep(NS(),db)
        assert expiry.await_count==2
    asyncio.run(run())
