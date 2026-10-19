import json
import asyncio
from functools import wraps
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from utils import return_reminder_settings as settings
from cwl_web import manage_return_channels as api
from cwl_web.manage_operations import revision


def run_async(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapped


@run_async
async def test_destination_defaults_then_reads_changes_without_cache():
    collection = SimpleNamespace(find_one=AsyncMock(side_effect=[None, {'main_channel_id': 123456789012345678}]))
    db = SimpleNamespace(bot_config=collection)
    assert await settings.destination(db, 'MAIN') == settings.DEFAULT_CHANNELS['MAIN']
    assert await settings.destination(db, 'MAIN') == 123456789012345678
    assert collection.find_one.await_count == 2


@run_async
async def test_database_failure_does_not_silently_use_old_channel():
    db = SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(side_effect=RuntimeError('offline'))))
    with pytest.raises(RuntimeError):
        await settings.destination(db, 'FWA')


@run_async
async def test_save_validates_live_channels_and_cas():
    row = {}
    collection = SimpleNamespace(find_one=AsyncMock(side_effect=[row, {'main_channel_id':123456789012345678,'fwa_channel_id':223456789012345678}]),
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0,upserted_id=settings.DOCUMENT_ID)))
    @asynccontextmanager
    async def mongo(_):yield SimpleNamespace(bot_config=collection)
    body={'revision':revision(row),'values':{'main_channel_id':'123456789012345678','fwa_channel_id':'223456789012345678'}}
    with patch.object(api.shared,'mongo',mongo), patch.object(api.shared,'require_manage',AsyncMock()), patch('cwl_web.app._json',AsyncMock(return_value=body)), patch.object(api.shared,'discord',AsyncMock(return_value={'guild_id':str(api.shared.GUILD_ID),'type':0})), patch.object(api,'check_channel_permissions',AsyncMock()) as check:
        response=await api.save({})
    assert check.await_count==2
    assert json.loads(response.text)['fields'][0]['value']=='123456789012345678'
    query=collection.update_one.await_args.args[0]
    assert query=={'_id':settings.DOCUMENT_ID,'main_channel_id':{'$exists':False},'fwa_channel_id':{'$exists':False}}


@run_async
@pytest.mark.parametrize('channel', [{'guild_id':'9','type':0},{'guild_id':str(api.shared.GUILD_ID),'type':2}])
async def test_rejects_other_guild_or_voice(channel):
    body={'revision':revision({}),'values':{'main_channel_id':'123456789012345678','fwa_channel_id':'223456789012345678'}}
    with patch.object(api.shared,'require_manage',AsyncMock()), patch('cwl_web.app._json',AsyncMock(return_value=body)), patch.object(api.shared,'discord',AsyncMock(return_value=channel)), patch.object(api.shared,'mongo') as mongo:
        with pytest.raises(web.HTTPBadRequest):await api.save({})
    mongo.assert_not_called()


@run_async
async def test_rejects_stale_settings_without_write():
    collection=SimpleNamespace(find_one=AsyncMock(return_value={'main_channel_id':323456789012345678}),update_one=AsyncMock())
    @asynccontextmanager
    async def mongo(_):yield SimpleNamespace(bot_config=collection)
    body={'revision':revision({}),'values':{'main_channel_id':'123456789012345678','fwa_channel_id':'223456789012345678'}}
    with patch.object(api.shared,'mongo',mongo),patch.object(api.shared,'require_manage',AsyncMock()),patch('cwl_web.app._json',AsyncMock(return_value=body)),patch.object(api.shared,'discord',AsyncMock(return_value={'guild_id':str(api.shared.GUILD_ID),'type':0})),patch.object(api,'check_channel_permissions',AsyncMock()):
        with pytest.raises(web.HTTPConflict):await api.save({})
    collection.update_one.assert_not_awaited()


@run_async
async def test_permission_denial_prevents_save():
    with patch.object(api.shared,'require_manage',AsyncMock(side_effect=web.HTTPForbidden())),patch.object(api.shared,'mongo') as mongo:
        with pytest.raises(web.HTTPForbidden):await api.save({})
    mongo.assert_not_called()

@run_async
async def test_single_changed_channel_preserves_other_and_compares_both():
    row={'_id':settings.DOCUMENT_ID,'main_channel_id':123456789012345678,'fwa_channel_id':223456789012345678}
    collection=SimpleNamespace(find_one=AsyncMock(return_value=row),update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1,upserted_id=None)))
    @asynccontextmanager
    async def mongo(_):yield SimpleNamespace(bot_config=collection)
    body={'revision':revision(row),'values':{'main_channel_id':'323456789012345678'}}
    with patch.object(api.shared,'mongo',mongo),patch.object(api.shared,'require_manage',AsyncMock()),patch('cwl_web.app._json',AsyncMock(return_value=body)),patch.object(api.shared,'discord',AsyncMock(return_value={'guild_id':str(api.shared.GUILD_ID),'type':0})),patch.object(api,'check_channel_permissions',AsyncMock()):
        await api.save({})
    query,update=collection.update_one.await_args.args
    assert query==row
    assert update['$set']=={'main_channel_id':323456789012345678,'fwa_channel_id':223456789012345678}
