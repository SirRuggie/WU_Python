import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from extensions.commands import goldrush as command
from utils import goldrush as store, recruit_links
from utils.constants import WARRIORS_UNITED_GUILD_ID
from tests.test_goldrush import db, START


def test_panel_is_concise_has_join_and_only_entered_accounts(db,monkeypatch):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    monkeypatch.setattr(store,'utcnow',lambda:START)
    snapshot=store.snapshot(db,event['id'])
    payload=str(command.render(snapshot)[0].build())
    assert 'Join Gold Rush' in payload and 'No screenshots' not in payload
    assert 'Each account ranks separately.' in payload
    assert 'Be the first to join' in payload
    assert '#ONE' not in payload
    store.join_event(db,event['id'],1,['#ONE','#TWO'],at=START)
    with db:
        db.executemany('INSERT INTO loot_events VALUES (?, ?, ?, ?)',[(tag,START.isoformat(),'farming',100) for tag in ('#ONE','#TWO')])
    snapshot=store.snapshot(db,event['id'])
    payload=str(command.render(snapshot)[0].build())
    assert '#ONE' in payload and '#TWO' in payload
    assert payload.count('https://discord.com/users/1)') == 2
    assert '+1 accounts' not in payload
    assert '1 joined' in payload
    assert '#THREE' not in payload


def test_panel_disables_join_after_end(db,monkeypatch):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    monkeypatch.setattr(store,'utcnow',lambda:START+timedelta(days=1))
    panel=command.render(store.snapshot(db,event['id']))[0]
    assert panel.components[-1].components[0].is_disabled
    assert 'RESULTS PENDING' in str(panel.build())


def test_join_only_accepts_clickers_resolved_tracked_accounts(db,monkeypatch):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    monkeypatch.setattr(store,'utcnow',lambda:START)
    async def database(fn,*args,**kwargs):
        return fn(db,*args,**kwargs)
    monkeypatch.setattr(command,'database',database)
    resolver=AsyncMock(return_value=recruit_links.LinksResult(sources={'#ONE':('ClashKing',),'#TWO':('ClashPerk',),'#OUTSIDE':('ClashKing',)}))
    monkeypatch.setattr(command.recruit_links,'resolve',resolver)
    monkeypatch.setattr(command,'sync_messages',AsyncMock())
    ctx=SimpleNamespace(user=SimpleNamespace(id=123),interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID),respond=AsyncMock())
    asyncio.run(command.join(ctx,event['id']))
    resolver.assert_awaited_once_with(123,verify_owners=False)
    assert [r[0] for r in db.execute('SELECT player_tag FROM goldrush_entries ORDER BY player_tag')]==['#ONE','#TWO']
    assert ctx.respond.call_args.kwargs['ephemeral'] is True


@pytest.mark.parametrize('result',[
    recruit_links.LinksResult(unavailable=('ClashKing',)),
    recruit_links.LinksResult(conflicts=('#ONE',)),
])
def test_join_does_not_register_during_link_outage_or_conflict(db,monkeypatch,result):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    async def database(fn,*args,**kwargs): return fn(db,*args,**kwargs)
    monkeypatch.setattr(command,'database',database)
    monkeypatch.setattr(command.recruit_links,'resolve',AsyncMock(return_value=result))
    ctx=SimpleNamespace(user=SimpleNamespace(id=123),interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID),respond=AsyncMock())
    asyncio.run(command.join(ctx,event['id']))
    assert db.execute('SELECT count(*) FROM goldrush_entries').fetchone()[0]==0


def test_non_admin_cannot_confirm_schedule(monkeypatch):
    database=AsyncMock()
    monkeypatch.setattr(command,'database',database)
    ctx=SimpleNamespace(interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID,
        member=SimpleNamespace(permissions=hikari.Permissions.NONE)),respond=AsyncMock())
    asyncio.run(command.confirm(ctx,'forged'))
    database.assert_not_called()


def test_full_panel_fits_discord_text_limit(monkeypatch):
    monkeypatch.setattr(store,'utcnow',lambda:START)
    event=dict(id='test',starts_at=START.isoformat(),ends_at=(START+timedelta(days=1)).isoformat(),
        duration_hours=24,prize='1 Gold Pass',final_results=None)
    rows=[dict(user_id=str(100000000000000000+i),gold=1234567890,accounts=[dict(tag='#PPPPPPPP',name='*'*32,clan_name='*'*32)]) for i in range(10)]
    labels={r['user_id']:'N'*64 for r in rows}
    panel=command.render(dict(event=event,rows=rows,entrants=10,accounts=200,labels=labels,refreshed=START.isoformat()))[0]
    size=sum(len(c.content) for c in panel.components if hasattr(c,'content'))
    assert size<=4000


@pytest.mark.parametrize('conflict', ['#THREE', '#OUTSIDE'])
def test_join_keeps_valid_accounts_when_another_link_is_disputed(db,monkeypatch,conflict):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    monkeypatch.setattr(store,'utcnow',lambda:START)
    async def database(fn,*args,**kwargs): return fn(db,*args,**kwargs)
    monkeypatch.setattr(command,'database',database)
    monkeypatch.setattr(command.recruit_links,'resolve',AsyncMock(return_value=recruit_links.LinksResult(
        sources={'#ONE':('ClashKing',),'#TWO':('ClashPerk',)},conflicts=(conflict,))))
    monkeypatch.setattr(command,'sync_messages',AsyncMock())
    ctx=SimpleNamespace(user=SimpleNamespace(id=123),interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID),respond=AsyncMock())
    asyncio.run(command.join(ctx,event['id']))
    assert [r[0] for r in db.execute('SELECT player_tag FROM goldrush_entries ORDER BY player_tag')]==['#ONE','#TWO']
    message=ctx.respond.call_args.args[0]
    assert 'You joined' in message
    assert 'Not entered:' not in message
    assert ctx.respond.call_args.kwargs['ephemeral'] is True


def test_join_accepts_one_available_link_provider(db,monkeypatch):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START)
    store.start_event(db,event['id'],at=START)
    monkeypatch.setattr(store,'utcnow',lambda:START)
    async def database(fn,*args,**kwargs): return fn(db,*args,**kwargs)
    monkeypatch.setattr(command,'database',database)
    monkeypatch.setattr(command.recruit_links,'resolve',AsyncMock(return_value=recruit_links.LinksResult(
        sources={'#ONE':('ClashPerk',)},unavailable=('ClashKing',))))
    monkeypatch.setattr(command,'sync_messages',AsyncMock())
    ctx=SimpleNamespace(user=SimpleNamespace(id=123),interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID),respond=AsyncMock())
    asyncio.run(command.join(ctx,event['id']))
    assert db.execute('SELECT player_tag FROM goldrush_entries').fetchone()[0]=='#ONE'
    assert 'You joined' in ctx.respond.call_args.args[0]
