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


@pytest.mark.parametrize('date,time,offset', [('10/10/2026','6:00 PM',-4),('01/10/2027','18:00',-5)])
def test_eastern_schedule_handles_seasonal_offset(date,time,offset):
    start=command.parse_eastern_start(date,time)
    assert start.hour==18
    assert start.utcoffset()==timedelta(hours=offset)
    assert ('EDT' if offset==-4 else 'EST') in command.eastern_time(start.isoformat())


@pytest.mark.parametrize('date,time', [('03/14/2027','2:30 AM'),('11/01/2026','1:30 AM'),('bad','6 PM')])
def test_eastern_schedule_rejects_invalid_or_ambiguous_times(date,time):
    with pytest.raises(ValueError):
        command.parse_eastern_start(date,time)


def test_banner_is_first_and_dates_use_discord_local_time(db,monkeypatch):
    event=store.ensure_current(db,WARRIORS_UNITED_GUILD_ID)
    monkeypatch.setattr(store,'utcnow',lambda:START)
    panel=command.render(store.snapshot(db,event['id']))[0]
    payload,attachments=panel.build()
    assert payload['components'][0]['type']==hikari.ComponentType.MEDIA_GALLERY
    assert len(attachments)==1
    assert command.discord_time(event['starts_at']) in str(payload)
    assert command.discord_time(event['ends_at']) in str(payload)
    assert 'EDT' not in str(payload)


def test_scheduled_panel_prominently_explains_signup_before_scoring(db,monkeypatch):
    event=store.create_event(db,guild_id=WARRIORS_UNITED_GUILD_ID,account_mode='per_account',allow_late_join=True,at=START,duration_hours=48)
    store.start_event(db,event['id'],at=START+timedelta(days=1))
    monkeypatch.setattr(store,'utcnow',lambda:START)
    panel=command.render(store.snapshot(db,event['id']))[0]
    text=str(panel.build())
    assert '48 HR GOLD RUSH' in text
    assert 'JOIN NOW' in text and 'Gold starts counting at the start time' in text
    assert 'before the start does not count' in text
    assert not panel.components[-1].components[0].is_disabled



def test_discord_timestamp_preserves_configured_eastern_instant():
    start=command.parse_eastern_start('10/12/2026','10:00 AM')
    assert start.astimezone(__import__('datetime').timezone.utc).hour==14
    assert command.discord_time(start.isoformat())==f'<t:{int(start.timestamp())}:f>'



def test_new_post_pings_only_announcement_role(monkeypatch):
    monkeypatch.setattr(command,'refresh',AsyncMock())
    monkeypatch.setattr(command,'panel_data',AsyncMock(return_value={}))
    monkeypatch.setattr(command,'render',lambda data: [])
    monkeypatch.setattr(command,'database',AsyncMock())
    rest=SimpleNamespace(create_message=AsyncMock(return_value=SimpleNamespace(id=456)))
    interaction=SimpleNamespace(app=SimpleNamespace(rest=rest),delete_initial_response=AsyncMock())
    ctx=SimpleNamespace(channel_id=123,interaction=interaction,defer=AsyncMock())
    asyncio.run(command.post(ctx,{'id':'event'}))
    args=rest.create_message.call_args.kwargs
    assert args['components'][0].content=='<@&1080521665584308286>'
    assert args['role_mentions']==[1080521665584308286]
    assert args['user_mentions'] is False and args['mentions_everyone'] is False



@pytest.mark.parametrize('hours,expected,unexpected', [(-1,'BE READY AT THE START','GOLD RUSH IS LIVE'),(1,'GOLD RUSH IS LIVE','BE READY AT THE START'),(25,'GOLD RUSH ENDED','JOIN NOW')])
def test_signup_heading_matches_configured_start(db,monkeypatch,hours,expected,unexpected):
    event=store.ensure_current(db,WARRIORS_UNITED_GUILD_ID)
    monkeypatch.setattr(store,'utcnow',lambda:START+timedelta(hours=hours))
    text=str(command.render(store.snapshot(db,event['id']))[0].build())
    assert expected in text and unexpected not in text
    if hours<24:
        assert ':R>' in text


def test_repeated_refresh_uses_cooldown(monkeypatch):
    calls=[]
    monkeypatch.setattr(command,'refresh_board',lambda: calls.append(1) or {'warning':None})
    monkeypatch.setattr(command,'_last_refresh',0)
    async def run():
        monkeypatch.setattr(command,'_refresh_lock',asyncio.Lock())
        await asyncio.gather(command.refresh(),command.refresh(),command.refresh())
        await command.refresh()
    asyncio.run(run())
    assert len(calls)==1


def test_private_pages_cover_all_accounts_and_fit_limits(db):
    event=store.ensure_current(db,WARRIORS_UNITED_GUILD_ID)
    data=dict(event=event,rows=[dict(tag=f'#TAG{i}',name='N'*32,gold=i,status='Entered',updated=START.isoformat()) for i in range(30)])
    text=''
    for page in range(3):
        panel=command.render_personal(data,123,page)[0]
        contents='\n'.join(c.content for c in panel.components if hasattr(c,'content'))
        assert len(contents)<4000
        text+=contents
        assert all('|123|' in b.custom_id for b in panel.components[-1].components)
    assert all(text.count(f'`#TAG{i}`')==1 for i in range(30))


def test_private_page_rejects_another_user(monkeypatch):
    database=AsyncMock()
    monkeypatch.setattr(command,'database',database)
    ctx=SimpleNamespace(user=SimpleNamespace(id=999),interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID),respond=AsyncMock())
    asyncio.run(command.personal_page(ctx,'event|123|1'))
    database.assert_not_called()
    assert ctx.respond.call_args.kwargs['ephemeral'] is True


def test_final_winner_card_survives_update_and_sync(db, monkeypatch):
    event=store.ensure_current(db,WARRIORS_UNITED_GUILD_ID)
    store.join_event(db,event['id'],123,['#ONE'],at=START)
    with db:
        db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)',('#ONE',START.isoformat(),'farming',12345))
    store.finalize_event(db,event['id'],at=START+timedelta(days=1))
    data=store.snapshot(db,event['id'])
    data.update(labels={'123':'Winner'},levels={'#ONE':18})
    monkeypatch.setattr(command,'panel_data',AsyncMock(return_value=data))
    monkeypatch.setattr(command,'refresh',AsyncMock())
    async def database(fn,*args,**kwargs): return fn(db,*args,**kwargs)
    monkeypatch.setattr(command,'database',database)
    ctx=SimpleNamespace(interaction=SimpleNamespace(guild_id=WARRIORS_UNITED_GUILD_ID,edit_initial_response=AsyncMock()))
    asyncio.run(command.update(ctx,event['id']))
    panels=ctx.interaction.edit_initial_response.call_args.kwargs['components']
    assert len(panels)==2
    assert 'TOP 10' in str(panels[0].build())
    assert '12,345 gold' in str(panels[0].build())
    card=str(panels[1].build())
    assert '<@123>' in card and '#ONE' in card and 'TH_18' in card
    assert 'Go touch some grasss ffs' in card
    store.register_message(db,event['id'],111,222)
    rest=SimpleNamespace(edit_message=AsyncMock())
    monkeypatch.setitem(command.bot_data.data,'bot',SimpleNamespace(rest=rest))
    asyncio.run(command.sync_messages(event['id']))
    synced=rest.edit_message.call_args.kwargs['components']
    assert str(synced[1].build())==card
    assert rest.edit_message.call_args.kwargs['user_mentions'] is False


@pytest.mark.parametrize('scores', [[], [100,100]])
def test_final_card_does_not_declare_winner_for_empty_or_tied_results(db,scores):
    event=store.ensure_current(db,WARRIORS_UNITED_GUILD_ID)
    for i,score in enumerate(scores):
        tag=('#ONE','#TWO')[i]
        store.join_event(db,event['id'],i+1,[tag],at=START)
        with db:
            db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)',(tag,START.isoformat(),'farming',score))
    store.finalize_event(db,event['id'],at=START+timedelta(days=1))
    card=str(command.render(store.snapshot(db,event['id']))[1].build())
    assert '<@' not in card
    assert ('Exact tie' if scores else 'no winner') in card
