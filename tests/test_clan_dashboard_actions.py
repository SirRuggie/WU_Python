import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from utils import clan_dashboard_actions as actions

def test_failed_creation_keeps_old_emoji(monkeypatch):
    monkeypatch.setattr(actions.asyncio,'to_thread',AsyncMock(return_value=b'image'))
    rest=NS(fetch_application=AsyncMock(return_value=NS(id=1)),create_application_emoji=AsyncMock(side_effect=RuntimeError('full')),delete_application_emoji=AsyncMock())
    db=NS(clans=NS(update_one=AsyncMock()))
    with pytest.raises(RuntimeError):asyncio.run(actions.replace_emoji(NS(rest=rest),db,{'_id':1,'name':'Clan','emoji':'old'},'https://example.com/a.png'))
    rest.delete_application_emoji.assert_not_awaited();db.clans.update_one.assert_not_awaited()

def test_success_keeps_existing_published_emoji(monkeypatch):
    monkeypatch.setattr(actions.asyncio,'to_thread',AsyncMock(return_value=b'image'))
    emoji=NS(id=2,mention='<:clan:2>')
    rest=NS(fetch_application=AsyncMock(return_value=NS(id=1)),create_application_emoji=AsyncMock(return_value=emoji),delete_application_emoji=AsyncMock())
    db=NS(clans=NS(update_one=AsyncMock(return_value=NS(matched_count=1))))
    assert asyncio.run(actions.replace_emoji(NS(rest=rest),db,{'_id':1,'name':'Clan','emoji':'old'},'https://example.com/a.png'))==emoji
    rest.delete_application_emoji.assert_not_awaited()
    assert db.clans.update_one.await_args.args[0]['emoji']=='old'

def test_conflict_removes_only_new_emoji(monkeypatch):
    monkeypatch.setattr(actions.asyncio,'to_thread',AsyncMock(return_value=b'image'))
    rest=NS(fetch_application=AsyncMock(return_value=NS(id=1)),create_application_emoji=AsyncMock(return_value=NS(id=2,mention='new')),delete_application_emoji=AsyncMock())
    db=NS(clans=NS(update_one=AsyncMock(return_value=NS(matched_count=0))))
    with pytest.raises(ValueError):asyncio.run(actions.replace_emoji(NS(rest=rest),db,{'_id':1,'name':'Clan','emoji':'old'},'https://example.com/a.png'))
    rest.delete_application_emoji.assert_awaited_once_with(application=1,emoji=2)

def test_thread_reuses_existing_without_creation():
    existing=NS(id=3,guild_id=1)
    rest=NS(fetch_channel=AsyncMock(return_value=existing),create_thread=AsyncMock())
    db=NS(clans=NS(update_one=AsyncMock()))
    assert asyncio.run(actions.ensure_thread(NS(rest=rest),db,{'thread_id':3},1)) is existing
    rest.create_thread.assert_not_awaited();db.clans.update_one.assert_not_awaited()

def test_thread_finds_named_thread_and_updates_shared_record():
    thread=NS(id=3,parent_id=1133096989748363294,name='Clan')
    rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=1)),fetch_active_threads=AsyncMock(return_value=[thread]),fetch_public_archived_threads=AsyncMock(return_value=[]),create_thread=AsyncMock())
    db=NS(clans=NS(update_one=AsyncMock(return_value=NS(matched_count=1))))
    assert asyncio.run(actions.ensure_thread(NS(rest=rest),db,{'_id':1,'name':'Clan','thread_id':0},1)) is thread
    rest.create_thread.assert_not_awaited()
    assert db.clans.update_one.await_args.args[1]=={'$set':{'thread_id':3}}

def test_new_thread_uses_one_day_archive_duration():
    from datetime import timedelta
    thread=NS(id=3)
    rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=1)),fetch_active_threads=AsyncMock(return_value=[]),fetch_public_archived_threads=AsyncMock(return_value=[]),create_thread=AsyncMock(return_value=thread))
    db=NS(clans=NS(update_one=AsyncMock(return_value=NS(matched_count=1))))
    asyncio.run(actions.ensure_thread(NS(rest=rest),db,{'_id':1,'name':'Clan','thread_id':0},1))
    assert rest.create_thread.await_args.kwargs['auto_archive_duration']==timedelta(days=1)
