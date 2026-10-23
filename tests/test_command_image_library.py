import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager
import pytest
from aiohttp import web
from cwl_web import command_image_library as lib

def test_usage_nested_duplicate_disabled_and_legacy():
    url='https://example.com/photo.png'
    rows=[{'command':'!one','blocks':[{'type':'container','blocks':[{'type':'image','url':url},{'type':'section','accessory':{'type':'thumbnail','url':url}}]}]}, {'command':'!two','enabled':False,'image_url':url}]
    result=lib.merge_images([{'url':url,'name':'Welcome'}],rows)
    assert result==[{'url':url,'name':'Welcome','commands':['!one','!two'],'stored':True,'archived':False,'folder':''}]

def test_unused_and_video_and_external():
    result=lib.merge_images([{'url':'https://example.com/unused.png','name':'Unused'}],[{'command':'!one','blocks':[{'type':'gallery','items':[{'url':'https://example.com/movie.mp4'},{'url':'https://example.com/pic.png'}]}]}])
    assert len(result)==2
    assert next(item for item in result if item['name']=='Unused')['commands']==[]
    assert next(item for item in result if item['name']=='pic.png')['stored'] is False

def test_library_denied_before_database(monkeypatch):
    monkeypatch.setattr(lib,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(lib.listing(object()))

def test_catalog_upsert_scoped_and_stable(monkeypatch):
    target=NS(update_one=AsyncMock())
    @asynccontextmanager
    async def mongo(request):yield object()
    monkeypatch.setattr(lib,'mongo',mongo);monkeypatch.setattr(lib,'collection',lambda db:target)
    asyncio.run(lib.remember(object(),'https://example.com/a.png','My image',{'user_id':'123'}))
    query,update=target.update_one.call_args.args
    assert len(query['_id'])==64
    assert update['$setOnInsert']['guild_id']==lib.GUILD_ID
    assert update['$setOnInsert']['name']=='My image'
    assert target.update_one.call_args.kwargs['upsert'] is True


def test_archived_images_retain_usage_and_url():
    url='https://example.com/art.png'
    result=lib.merge_images([{'url':url,'name':'Art','archived':True}],[{'command':'!one','image_url':url}])
    assert result[0]['archived'] is True
    assert result[0]['url']==url and result[0]['commands']==['!one']

def test_rename_archive_metadata_only(monkeypatch):
    url='https://example.com/art.png'
    class Cursor:
        async def to_list(self,**kwargs):return [{'url':url,'name':'Art'}]
    target=NS(find=lambda query:Cursor(),update_one=AsyncMock())
    class Empty:
        async def to_list(self,**kwargs):return []
    @asynccontextmanager
    async def mongo(request):yield object()
    monkeypatch.setattr(lib,'mongo',mongo);monkeypatch.setattr(lib,'collection',lambda db:target)
    monkeypatch.setattr(lib,'commands',lambda db:NS(find=lambda query:Empty()))
    monkeypatch.setattr(lib,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    response=asyncio.run(lib.update(NS(json=AsyncMock(return_value={'url':url,'name':'Banner','archived':True}))))
    assert 'Banner' in response.text
    data=target.update_one.call_args.args[1]['$set']
    assert data['archived'] is True and data['url']==url and data['updated_by']=='123'


def test_sync_indexes_images_only_without_overwriting_names(monkeypatch):
    from unittest.mock import Mock
    from cwl_web import command_images
    target=NS(bulk_write=AsyncMock())
    @asynccontextmanager
    async def mongo(request):yield object()
    media=NS(list_objects=AsyncMock(return_value={'Contents':[{'Key':'clans/WU/logo.png'},{'Key':'archive.zip'},{'Key':'static/banner.webp'}],'IsTruncated':True,'NextContinuationToken':'next'}),public_url=lambda key:'https://img.example.com/'+key)
    monkeypatch.setattr(lib,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(lib,'mongo',mongo);monkeypatch.setattr(lib,'collection',lambda db:target)
    monkeypatch.setattr(command_images,'store',lambda req:media)
    response=asyncio.run(lib.sync_r2(NS(json=AsyncMock(return_value={'cursor':None}))))
    assert '"indexed": 2' in response.text and 'next' in response.text
    operations=target.bulk_write.call_args.args[0]
    assert len(operations)==2
    assert set(operations[0]._doc)=={'$setOnInsert'}
    assert operations[0]._doc['$setOnInsert']['folder']=='clans/WU'
    assert operations[0]._doc['$setOnInsert']['guild_id']==lib.GUILD_ID


def test_sync_requires_access_before_bucket_lookup(monkeypatch):
    monkeypatch.setattr(lib,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(lib.sync_r2(object()))


def test_folder_metadata_is_preserved_and_validated(monkeypatch):
    result=lib.merge_images([{'url':'https://example.com/a.png','name':'Welcome','folder':'Announcements'}],[])
    assert result[0]['folder']=='Announcements'
    monkeypatch.setattr(lib,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    with pytest.raises(web.HTTPBadRequest):asyncio.run(lib.update(NS(json=AsyncMock(return_value={'url':result[0]['url'],'name':'Welcome','archived':False,'folder':'bad\nfolder'}))))


def test_builtin_flag_art_uses_mirrored_r2_keys_and_keeps_saved_metadata(monkeypatch):
    from utils.ticket_flag_art import FLAG_ART
    monkeypatch.setenv('R2_PUBLIC_BASE_URL', 'https://img.example.com/')
    builtins = lib.builtin_flag_images()
    assert len(builtins) == 5
    assert {item['url'] for item in builtins} == {
        f'https://img.example.com/{art.r2_key}' for art in FLAG_ART.values()
    }
    assert all(art.local_path.is_file() for art in FLAG_ART.values())
    archived = {**builtins[0], 'name': 'Saved name', 'archived': True}
    merged = lib.merge_images([archived], [], builtins)
    same = next(item for item in merged if item['url'] == archived['url'])
    assert same['name'] == 'Saved name'
    assert same['archived'] is True
    assert len(merged) == 5


def test_builtin_flag_art_can_be_renamed_or_archived(monkeypatch):
    from cwl_web import command_image_library as lib
    monkeypatch.setenv('R2_PUBLIC_BASE_URL', 'https://img.example.com')
    url = lib.builtin_flag_images()[0]['url']
    class Cursor:
        async def to_list(self, **_kwargs): return []
    target = NS(find=lambda _query: Cursor(), update_one=AsyncMock())
    @asynccontextmanager
    async def mongo(_request): yield object()
    monkeypatch.setattr(lib, 'mongo', mongo)
    monkeypatch.setattr(lib, 'collection', lambda _db: target)
    monkeypatch.setattr(lib, 'commands', lambda _db: NS(find=lambda _query: Cursor()))
    monkeypatch.setattr(lib, 'require_manage', AsyncMock(return_value={'user_id': '123'}))
    response = asyncio.run(lib.update(NS(json=AsyncMock(return_value={
        'url': url, 'name': 'Recruitment flags', 'archived': True,
    }))))
    assert response.status == 200
    assert target.update_one.call_args.args[1]['$set']['archived'] is True


def test_saved_unsafe_urls_are_not_exposed():
    assert lib.merge_images([{'url':'javascript:alert(1)','name':'Unsafe'}],[])==[]

@pytest.mark.parametrize('stale', [True, False])
def test_image_expected_metadata_rejects_stale_and_concurrent_updates(monkeypatch,stale):
    from pymongo.errors import DuplicateKeyError
    url='https://example.com/image.png'
    item={'url':url,'name':'Current name','folder':'Clans','archived':False}
    class Cursor:
        def __init__(self,rows):self.rows=rows
        async def to_list(self,**kw):return self.rows
    target=NS(find=lambda q:Cursor([item]),update_one=AsyncMock(side_effect=DuplicateKeyError('raced')))
    @asynccontextmanager
    async def mongo(request):yield object()
    monkeypatch.setattr(lib,'mongo',mongo);monkeypatch.setattr(lib,'collection',lambda db:target)
    monkeypatch.setattr(lib,'commands',lambda db:NS(find=lambda q:Cursor([])))
    monkeypatch.setattr(lib,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    expected={'name':'Old name' if stale else item['name'],'folder':'Clans','archived':False}
    body={'url':url,'name':'My edit','folder':'Clans','archived':False,'expected':expected}
    with pytest.raises(web.HTTPConflict):asyncio.run(lib.update(NS(json=AsyncMock(return_value=body))))
    assert target.update_one.await_count==(0 if stale else 1)
    if not stale:
        query=target.update_one.await_args.args[0]
        assert query['name']=='Current name' and query['updated_at']=={'$exists':False}
