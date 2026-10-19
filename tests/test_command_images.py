import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import command_images as images

@pytest.fixture(autouse=True)
def mock_catalog(monkeypatch):
    monkeypatch.setattr(images,'remember',AsyncMock())

URL='https://media.discordapp.net/attachments/1/2/image.jpg?ex=123'
def test_nested_images_preserved_once_without_mutation():
    async def run():
        media=SimpleNamespace(upload_from_url=AsyncMock(return_value='https://images.example.com/saved.webp'))
        values={'blocks':[{'type':'container','blocks':[{'type':'image','url':URL},{'type':'gallery','items':[{'url':URL}]},{'type':'section','accessory':{'type':'thumbnail','url':URL}}]}]}
        result=await images.preserve_images(SimpleNamespace(app={'server_management_media':media}),values)
        assert media.upload_from_url.await_count==1
        assert result['blocks'][0]['blocks'][2]['accessory']['url'].endswith('saved.webp')
        assert values['blocks'][0]['blocks'][0]['url']==URL
    asyncio.run(run())

def test_no_store_needed_for_other_links():
    async def run():
        values={'blocks':[{'type':'image','url':'https://example.com/image.png'}]}
        assert await images.preserve_images(object(),values)==values
    asyncio.run(run())

def test_download_failure_clear():
    async def run():
        media=SimpleNamespace(upload_from_url=AsyncMock(side_effect=images.MediaStoreError('expired')))
        with pytest.raises(web.HTTPBadRequest) as error:
            await images.preserve_images(SimpleNamespace(app={'server_management_media':media}),{'blocks':[{'type':'image','url':URL}]})
        assert 'fresh image link' in error.value.text
    asyncio.run(run())

def test_permission_checked_before_upload_read(monkeypatch):
    async def run():
        async def denied(*a,**kw):raise web.HTTPForbidden()
        monkeypatch.setattr(images,'require_manage',denied)
        with pytest.raises(web.HTTPForbidden):await images.upload(object())
    asyncio.run(run())

def test_import_rejects_non_discord(monkeypatch):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock())
        with pytest.raises(web.HTTPBadRequest):await images.import_image(SimpleNamespace(json=AsyncMock(return_value={'url':'https://localhost/image.jpg'})))
    asyncio.run(run())

def test_upload_returns_stored_url(monkeypatch):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock())
        async def chunks(n):yield b'image'
        media=SimpleNamespace(upload_bytes=AsyncMock(return_value='https://images.example.com/image.png'))
        response=await images.upload(SimpleNamespace(content_length=5,content=SimpleNamespace(iter_chunked=chunks),app={'server_management_media':media},query={}))
        assert 'https://images.example.com/image.png' in response.text
    asyncio.run(run())

def test_upload_size_limit(monkeypatch):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock())
        with pytest.raises(web.HTTPRequestEntityTooLarge):await images.upload(SimpleNamespace(content_length=images.MAX_IMAGE_BYTES+1))
    asyncio.run(run())

def test_import_public_image_and_catalog(monkeypatch):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock(return_value={'user_id':'123'}))
        media=SimpleNamespace(upload_from_url=AsyncMock(return_value='https://images.example.com/saved.png'))
        source='https://configcat.com/blog/assets/images/example.png'
        request=SimpleNamespace(json=AsyncMock(return_value={'url':source}),app={'server_management_media':media})
        response=await images.import_image(request)
        assert 'https://images.example.com/saved.png' in response.text
        media.upload_from_url.assert_awaited_once_with(source,folder=images.folder(),name='image')
        images.remember.assert_awaited_once_with(request,'https://images.example.com/saved.png','example.png',{'user_id':'123'})
    asyncio.run(run())

def test_import_download_error(monkeypatch):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock())
        media=SimpleNamespace(upload_from_url=AsyncMock(side_effect=images.MediaStoreError('URL must point directly to an image.')))
        with pytest.raises(web.HTTPBadRequest) as error:
            await images.import_image(SimpleNamespace(json=AsyncMock(return_value={'url':'https://example.com/page'}),app={'server_management_media':media}))
        assert 'directly' in error.value.text
        images.remember.assert_not_awaited()
    asyncio.run(run())

@pytest.mark.parametrize('via_link',[False,True])
def test_category_saved_with_upload_and_import(monkeypatch,via_link):
    async def run():
        monkeypatch.setattr(images,'require_manage',AsyncMock(return_value={'user_id':'100'}))
        media=SimpleNamespace(upload_bytes=AsyncMock(return_value='https://images.example.com/new.png'),upload_from_url=AsyncMock(return_value='https://images.example.com/new.png'))
        async def chunks(n):yield b'image'
        req=SimpleNamespace(content_length=5,content=SimpleNamespace(iter_chunked=chunks),app={'server_management_media':media},query={'category':' Clans ','name':'logo.png'},json=AsyncMock(return_value={'url':'https://example.com/logo.png','category':' Clans '}))
        await (images.import_image(req) if via_link else images.upload(req))
        assert images.remember.await_args.kwargs=={'category':'Clans'}
    asyncio.run(run())

@pytest.mark.parametrize('value',[123,'x'*121,'bad\nname'])
def test_invalid_category_rejected(value):
    with pytest.raises(web.HTTPBadRequest):images.image_category(value)
