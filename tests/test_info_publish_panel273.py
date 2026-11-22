"""Publish-page layout regressions using isolated saved rows and fake Discord."""
import asyncio
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from cwl_web import manage_delivery as delivery, server_management
from extensions.commands import content
from test_cwl_web_manage_delivery import fixture
from test_info_post_mapping272 import compact, raw
from utils.gauntlet_content import AMBIGUOUS_NOTICE, sections_for


@pytest.mark.parametrize('shape', ['compact28', 'genuine28', 'genuine34', 'ambiguous'])
def test_publish_get_projects_saved_layout_without_writes(shape):
    async def check():
        key = 'family-particulars'
        fields = compact() if shape in {'compact28', 'ambiguous'} else raw()
        if shape in {'genuine34', 'ambiguous'}:
            fields += sections_for(key)[28:]
        _row, mongo, _bot, _ctx = fixture()
        guild = delivery.GUILD_ID
        mongo.bot_config.documents.update({
            f'content:{key}:{guild}': {
                '_id': f'content:{key}:{guild}', 'sections': fields[:],
                'media': {}, 'revision': 3,
            },
            f'content_destination:{guild}:{key}': {
                '_id': f'content_destination:{guild}:{key}', 'guild_id': guild,
                'document': key, 'channel_id': 456,
            },
            f'content_published:{guild}:{key}': {
                '_id': f'content_published:{guild}:{key}', 'guild_id': guild,
                'document': key, 'channel_id': 456, 'message_id': 789,
            },
        })
        before = copy.deepcopy(mongo.bot_config.documents)

        @asynccontextmanager
        async def database(_request):
            yield mongo

        async def discord(_request, method, path):
            assert method == 'GET'
            if path.endswith('/messages/789'):
                return {'components': []}
            assert path == '/channels/456'
            return {'guild_id': str(guild), 'name': 'fixture-posts'}

        app = web.Application()
        delivery.routes(app)
        client = TestClient(TestServer(app))
        allowed = AsyncMock()
        lookup = AsyncMock(side_effect=discord)
        queued = AsyncMock()
        with patch.object(server_management, 'mongo', database), \
                patch.object(server_management, 'require_manage', allowed), \
                patch.object(server_management, 'discord', lookup), \
                patch.object(server_management, 'queue_action', queued):
            await client.start_server()
            try:
                response = await client.get('/api/cwl/manage/publish/' + key)
                assert response.status == 200
                result = await response.json()
                assert all(field['readonly'] for field in result['fields'])
                if shape == 'ambiguous':
                    assert result['actions'] == []
                    assert AMBIGUOUS_NOTICE in str(result)
                    saved = [field for field in result['fields'] if field['key'].startswith('section.')]
                    assert [field['value'] for field in saved] == fields
                    assert [field['label'] for field in saved] == [f'Raw saved field {i + 1}' for i in range(len(fields))]
                    lookup.assert_not_awaited()
                    rejected = await client.post('/api/cwl/manage/publish/' + key + '/update',
                                                 json={'revision': result['revision']})
                    assert rejected.status == 400
                    queued.assert_not_awaited()
                    lookup.assert_not_awaited()
                else:
                    # These positions come from the actual pre270 renderer and
                    # old web-save fixture, independently of logical_sections.
                    positions = (4, 6, 9, 11, 13, 15, 17, 19) if shape == 'compact28' else (5, 8, 12, 15, 18, 21, 24, 27)
                    labels = ('Friendly Challenges', 'Clan Games', 'War Status', 'Prep Day',
                              'Battle Day', 'Overview', 'Every CWL Battle', 'Body')
                    actual = {field['label']: field['value'] for field in result['fields']}
                    assert {label: actual[label] for label in labels} == dict(zip(labels, (fields[index] for index in positions)))
                    assert 'update' in {action['id'] for action in result['actions']}
                    assert result['existing_channel'] == '#fixture-posts'
                    queued.assert_not_awaited()
            finally:
                await client.close()
        assert allowed.await_args_list[0].args[1] == 'recruit'
        assert mongo.bot_config.documents == before
        assert len(fields) == (34 if shape in {'genuine34', 'ambiguous'} else 28)
    asyncio.run(check())


def test_ambiguous_worker_still_rejects_before_lease_or_discord():
    async def check():
        row, mongo, bot, ctx = fixture()
        row['action'] = 'update'
        row['values']['document'] = 'family-particulars'
        fields = compact() + sections_for('family-particulars')[28:]
        before = copy.deepcopy(mongo.bot_config.documents)
        with patch.object(content, 'template_for', AsyncMock(return_value=(fields, {}, 3))):
            with pytest.raises(ValueError, match='ambiguous'):
                await delivery.publish(bot, mongo, row, ctx)
        assert mongo.bot_config.documents == before
        bot.rest.create_message.assert_not_awaited()
        bot.rest.edit_message.assert_not_awaited()
    asyncio.run(check())


def test_non_box_publish_page_keeps_its_existing_field_representation():
    async def check():
        fields = ['Heading', 'Body', 'What next\nNext body', 'Call to action\nCall body']
        data = {'sections': fields[:], 'destination': None, 'target': None}
        request = NS(match_info={'document': 'join-family'})
        with patch.object(server_management, 'require_manage', AsyncMock()), \
                patch.object(delivery, 'review', AsyncMock(return_value=data)), \
                patch.object(server_management, 'discord', AsyncMock()) as discord:
            response = await delivery.page(request)
        import json
        result = json.loads(response.text)
        assert [field['value'] for field in result['fields'][1:]] == fields
        assert result['actions'] == []
        discord.assert_not_awaited()
    asyncio.run(check())


@pytest.mark.parametrize('length', [0, 1, 12, 27, 29, 30, 31, 32, 33, 35, 40])
def test_unknown_text_lengths_display_raw_but_queue_and_worker_deny(length):
    async def check():
        key = 'family-particulars'
        fields = [f'Saved raw value {index}' for index in range(length)]
        media = {'welcome': 'https://fixture.invalid/welcome.png',
                 'cwl': 'https://fixture.invalid/cwl.png'}
        row, mongo, bot, ctx = fixture()
        guild = delivery.GUILD_ID
        mongo.bot_config.documents.update({
            f'content:{key}:{guild}': {
                '_id': f'content:{key}:{guild}', 'sections': fields[:],
                'media': media.copy(), 'revision': 7,
            },
            f'content_destination:{guild}:{key}': {
                '_id': f'content_destination:{guild}:{key}', 'guild_id': guild,
                'document': key, 'channel_id': 456,
            },
            f'content_published:{guild}:{key}': {
                '_id': f'content_published:{guild}:{key}', 'guild_id': guild,
                'document': key, 'channel_id': 456, 'message_id': 789,
            },
        })
        before = copy.deepcopy(mongo.bot_config.documents)
        document = content.DOCUMENTS[key]
        assert document.legacy_key is None
        displayed = await content.template_for(mongo, document, guild, allow_ambiguous_display=True)
        assert displayed == (fields, media, 7)
        with pytest.raises(ValueError, match='ambiguous'):
            await content.template_for(mongo, document, guild)

        @asynccontextmanager
        async def database(_request):
            yield mongo

        app = web.Application()
        delivery.routes(app)
        client = TestClient(TestServer(app))
        with patch.object(server_management, 'mongo', database), \
                patch.object(server_management, 'require_manage', AsyncMock()), \
                patch.object(server_management, 'discord', AsyncMock()) as discord, \
                patch.object(server_management, 'queue_action', AsyncMock()) as queued:
            await client.start_server()
            try:
                response = await client.get('/api/cwl/manage/publish/' + key)
                assert response.status == 200
                result = await response.json()
                assert result['actions'] == [] and result['warning'] == AMBIGUOUS_NOTICE
                assert [field['value'] for field in result['fields']] == fields
                assert [field['label'] for field in result['fields']] == [f'Raw saved field {i + 1}' for i in range(length)]
                assert all(field['readonly'] for field in result['fields'])
                response = await client.post('/api/cwl/manage/publish/' + key + '/update',
                                             json={'revision': result['revision']})
                assert response.status == 400
                assert AMBIGUOUS_NOTICE in await response.text()
                queued.assert_not_awaited()
                discord.assert_not_awaited()
            finally:
                await client.close()
        row['action'] = 'update'
        row['values']['document'] = key
        with pytest.raises(ValueError, match='ambiguous'):
            await delivery.publish(bot, mongo, row, ctx)
        bot.rest.create_message.assert_not_awaited()
        bot.rest.edit_message.assert_not_awaited()
        assert mongo.bot_config.documents == before
    asyncio.run(check())


@pytest.mark.parametrize('fields,media', [
    ([None] * 28, {}),
    ({'invalid': 'not a list'}, {}),
    (raw(), {'welcome': 'http://fixture.invalid/not-https.png'}),
    (raw(), ['invalid media']),
])
def test_display_option_does_not_bypass_text_or_media_validation(fields, media):
    async def check():
        row, mongo, bot, ctx = fixture()
        key = 'family-particulars'
        saved = {'_id': f'content:{key}:{delivery.GUILD_ID}',
                 'sections': copy.deepcopy(fields), 'media': copy.deepcopy(media), 'revision': 7}
        mongo.bot_config.documents[saved['_id']] = saved
        before = copy.deepcopy(mongo.bot_config.documents)
        for display in (False, True):
            with pytest.raises(ValueError):
                await content.template_for(mongo, content.DOCUMENTS[key], delivery.GUILD_ID,
                                           allow_ambiguous_display=display)
        row['action'] = 'update'
        row['values']['document'] = key
        with pytest.raises(ValueError):
            await delivery.publish(bot, mongo, row, ctx)
        assert mongo.bot_config.documents == before
        bot.rest.create_message.assert_not_awaited()
        bot.rest.edit_message.assert_not_awaited()
    asyncio.run(check())
