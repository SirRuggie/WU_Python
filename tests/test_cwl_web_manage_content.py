"""Shared content schema, rendering, and optimistic edit regressions."""
import asyncio
from types import SimpleNamespace
import pytest
from aiohttp import web
from cwl_web import manage_content as content
from test_recruit_question_content import ConfigCollection


def run(value):
    return asyncio.run(value)


def db():
    return SimpleNamespace(bot_config=ConfigCollection(), ticket_staff_templates=ConfigCollection())


@pytest.mark.parametrize('item', content.catalog(), ids=lambda item: item['id'])
def test_all_native_defaults_have_editable_schema_and_preview(item):
    loaded = run(content.load(db(), item))
    schema = content.schema(item, loaded)
    assert schema['fields']
    assert len({field['key'] for field in schema['fields']}) == len(schema['fields'])
    updated = content.candidate(item, loaded, {'revision': loaded['revision'], 'values': {}})
    assert run(content.preview(item, updated))


def test_unknown_fields_and_stale_revision_rejected():
    item = content.descriptor('question--family_codes')
    loaded = run(content.load(db(), item))
    with pytest.raises(web.HTTPConflict):
        content.candidate(item, loaded, {'revision': True, 'values': {}})
    with pytest.raises(web.HTTPConflict):
        content.candidate(item, loaded, {'revision': 1, 'values': {}})
    with pytest.raises(ValueError):
        content.candidate(item, loaded, {'revision': 0, 'values': {'variant': 'something'}})
    edited = content.candidate(item, loaded, {'revision': 0, 'values': {'sections.1': 'Missing mandatory codes'}})
    with pytest.raises(ValueError):
        run(content.preview(item, edited))


def test_shared_native_edit_invalidates_web_revision():
    mongo = db()
    item = content.descriptor('question--attack_strategies')
    loaded = run(content.load(mongo, item))
    _, questions, _, _ = content.modules()
    run(questions.save_template(mongo, content.GUILD_ID, 'attack_strategies', loaded, 0, 1))
    fresh = run(content.load(mongo, item))
    with pytest.raises(web.HTTPConflict):
        content.candidate(item, fresh, {'revision': loaded['revision'], 'values': {'sections.0': 'Old editor'}})


def test_preview_does_not_write():
    mongo = db()
    item = content.descriptor('war--win')
    loaded = run(content.load(mongo, item))
    assert run(content.preview(item, loaded))
    assert not mongo.bot_config.rows



def test_handler_preview_save_and_stale_native_revision():
    run(_handler_preview_save_and_stale_native_revision())


async def _handler_preview_save_and_stale_native_revision():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import server_management
    mongo = db()
    @asynccontextmanager
    async def database(_request):
        yield mongo
    request = SimpleNamespace(match_info={'item': 'question--attack_strategies'}, method='POST', path='/preview', json=AsyncMock(return_value={'revision': 0, 'values': {'sections.0': 'Updated heading {recruit}'}}))
    permission = AsyncMock(return_value={'user_id': '123'})
    with patch.object(server_management, 'mongo', database), patch.object(server_management, 'require_manage', permission):
        response = await content.item_handler(request)
        assert json.loads(response.text)['preview']
        assert not mongo.bot_config.rows
        request.path = '/question'
        request.method = 'PATCH'
        assert json.loads((await content.item_handler(request)).text)['revision'] == 1
        with pytest.raises(web.HTTPConflict):
            await content.item_handler(request)
        permission.side_effect = web.HTTPForbidden()
        with pytest.raises(web.HTTPForbidden):
            await content.item_handler(request)


def test_staff_add_remove_shared_storage():
    run(_staff_add_remove_shared_storage())


async def _staff_add_remove_shared_storage():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import server_management
    from test_cwl_dashboard_integration import MemoryCollection
    mongo = db()
    mongo.ticket_staff_templates = MemoryCollection()
    @asynccontextmanager
    async def database(_request):
        yield mongo
    request = SimpleNamespace(match_info={'item': 'staff--main', 'action': 'add'}, method='POST', path='/add', json=AsyncMock(return_value={'revision': 0}))
    with patch.object(server_management, 'mongo', database), patch.object(server_management, 'require_manage', AsyncMock(return_value={'user_id': '123'})):
        item = json.loads((await content.item_handler(request)).text)
        remove = next(action for action in item['actions'] if action['id'].startswith('remove-'))
        request.match_info['action'] = remove['id']
        request.json.return_value = {'revision': 1}
        assert json.loads((await content.item_handler(request)).text)['revision'] == 2
        with pytest.raises(web.HTTPConflict):
            await content.item_handler(request)


def test_upload_validates_slot_revision_and_size_before_storage():
    run(_upload_validates_slot_revision_and_size_before_storage())


async def _upload_validates_slot_revision_and_size_before_storage():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import server_management
    from utils.url_safety import MAX_IMAGE_BYTES
    mongo = db()
    @asynccontextmanager
    async def database(_request):
        yield mongo
    class Stream:
        async def iter_chunked(self, _size):
            yield b'fixture image bytes'
    media = SimpleNamespace(upload_bytes=AsyncMock(return_value='https://images.example.org/art.png'))
    request = SimpleNamespace(match_info={'item':'gauntlet--about-us','slot':'media.welcome'}, query={'revision':'0'}, content_length=10, content=Stream(), app={'server_management_media':media})
    with patch.object(server_management, 'mongo', database), patch.object(server_management, 'require_manage', AsyncMock(return_value={'user_id':'123'})):
        assert json.loads((await content.upload(request)).text)['url'].endswith('art.png')
        assert not mongo.bot_config.rows  # Upload becomes a draft; Save stays explicit.
        media.upload_bytes.reset_mock()
        request.content_length = MAX_IMAGE_BYTES + 1
        with pytest.raises(web.HTTPRequestEntityTooLarge):
            await content.upload(request)
        media.upload_bytes.assert_not_awaited()
        request.query['revision'] = '9'
        with pytest.raises(web.HTTPConflict):
            await content.upload(request)
        request.query['revision'] = '0'
        request.match_info['slot'] = 'sections.0'
        with pytest.raises(web.HTTPBadRequest):
            await content.upload(request)


def test_load_published_returns_unsaved_draft_and_checks_bot_author():
    run(_load_published_returns_unsaved_draft_and_checks_bot_author())


async def _load_published_returns_unsaved_draft_and_checks_bot_author():
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch
    from cwl_web import server_management
    gauntlet, _, _, _ = content.modules()
    mongo = db()
    @asynccontextmanager
    async def database(_request):
        yield mongo
    author = '555'
    async def discord(_request, method, path):
        if path == '/users/@me': return {'id':'555'}
        if '/messages/' in path:
            return {'author':{'id':author},'components':[{'type':17,'components':[{'type':10,'content':'Published heading'},{'type':12,'items':[{'media':{'url':'https://example.org/image.png'}}]}]}]}
        return {'guild_id':str(content.GUILD_ID)}
    request=SimpleNamespace(match_info={'item':'gauntlet--about-us','action':'load-published'},method='POST',path='/load-published',json=AsyncMock(return_value={'revision':0}))
    with patch.object(server_management,'mongo',database),patch.object(server_management,'require_manage',AsyncMock(return_value={'user_id':'123'})),patch.object(server_management,'discord',discord),patch.object(gauntlet,'published_for',AsyncMock(return_value={'channel_id':1,'message_id':2})),patch.object(gauntlet,'component_shape',return_value='shape'),patch.object(gauntlet,'acknowledgement_id',return_value='ack'),patch.object(gauntlet,'render',AsyncMock(return_value=[])):
        response=json.loads((await content.item_handler(request)).text)
        assert response['draft_values']['sections.0']=='Published heading'
        assert not mongo.bot_config.rows
        author='different'
        with pytest.raises(web.HTTPBadRequest):
            await content.item_handler(request)


def walk_parts(parts):
    for part in parts:
        yield part
        yield from walk_parts(part.get('children', []))
        if part.get('accessory'):
            yield from walk_parts([part['accessory']])


def test_native_preview_preserves_artwork_groups_buttons_and_separators():
    item = content.descriptor('gauntlet--about-us')
    loaded = run(content.load(db(), item))
    parts = list(walk_parts(run(content.preview(item, loaded))))
    assert any(p['type'] == 'container' and p['accent'].startswith('#') for p in parts)
    assert any(p['type'] == 'separator' for p in parts)
    media = next(p for p in parts if p['type'] == 'media')
    assert media['items'][0]['url'].startswith('/api/cwl/manage/content/gauntlet--about-us/artwork/')
    buttons = [p for p in parts if p['type'] == 'button']
    assert buttons and 'Continue' in buttons[-1]['label']
    assert all('custom_id' not in p for p in parts)


def test_serialization_rejects_unsafe_urls_without_evaluating_html():
    payload = {'type':17,'components':[
        {'type':10,'content':'<script>alert(1)</script>'},
        {'type':12,'items':[{'media':{'url':'https://127.0.0.1/secret.png'}}]},
        {'type':1,'components':[{'type':2,'label':'Danger','style':5,'url':'javascript:alert(1)','custom_id':'do-not-expose'}]},
        {'type':3,'placeholder':'Select clan','options':[{'label':'Main','value':'private-id','description':'Main clan'}]},
    ]}
    builder = SimpleNamespace(build=lambda:(payload,[]))
    parts = list(walk_parts(content.serialize_components([builder],'test')))
    assert parts[1]['text'] == '<script>alert(1)</script>' # Plain JSON text, never HTML.
    assert next(p for p in parts if p['type']=='media')['items'][0]['url'] is None
    button = next(p for p in parts if p['type']=='button')
    assert 'url' not in button and 'custom_id' not in button
    assert 'value' not in next(p for p in parts if p['type']=='select')['options'][0]


def test_upload_fields_explain_position_and_save_requirement():
    for item in content.catalog():
        loaded = run(content.load(db(), item))
        for field in content.schema(item, loaded)['fields']:
            if field.get('upload_endpoint'):
                assert field['upload_label'].startswith('Upload ')
                assert 'draft' in field['description']
                assert 'Save changes' in field['description']


def test_get_editor_already_contains_visual_preview():
    async def check():
        import json
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, patch
        from cwl_web import server_management
        @asynccontextmanager
        async def mongo(_):yield db()
        req=SimpleNamespace(match_info={'item':'gauntlet--about-us'},method='GET')
        with patch.object(server_management,'mongo',mongo),patch.object(server_management,'require_manage',AsyncMock(return_value={'user_id':'1'})):
            result=json.loads((await content.item_handler(req)).text)
        assert any(p['type']=='media' for p in result['preview'])
    run(check())


def test_artwork_requires_permission_and_renderer_registered_path():
    async def check():
        from unittest.mock import AsyncMock,patch
        from cwl_web import server_management
        item=content.descriptor('gauntlet--about-us')
        preview=await content.preview(item,await content.load(db(),item))
        url=next(p for p in walk_parts(preview) if p['type']=='media')['items'][0]['url']
        req=SimpleNamespace(match_info={'item':item['id'],'token':url.rsplit('/',1)[1]})
        with patch.object(server_management,'require_manage',AsyncMock(side_effect=web.HTTPForbidden())):
            with pytest.raises(web.HTTPForbidden):await content.artwork(req)
        with patch.object(server_management,'require_manage',AsyncMock()):
            result=await content.artwork(req)
            assert result.headers['Cache-Control'].startswith('private')
            req.match_info['token']='../../.env'
            with pytest.raises(web.HTTPNotFound):await content.artwork(req)
    run(check())


def test_preview_ready_and_recovery_actions_are_secondary():
    item = content.descriptor('gauntlet--about-us')
    loaded = run(content.load(db(), item))
    document = run(content.editor_document(item, loaded))
    assert document['preview']
    assert document['publish_endpoint'].endswith('/manage/publish/about-us')
    assert {action['label'] for action in document['actions']} == {'Copy from Discord', 'Reset to default'}
    assert all(action['advanced'] for action in document['actions'])
    assert not run(content.editor_document(content.descriptor('question--family_codes'), run(content.load(db(), content.descriptor('question--family_codes')))))['publish_endpoint']
