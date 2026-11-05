import asyncio
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import hikari
import pytest
from aiohttp import web

from cwl_web import manage_delivery as delivery, server_management as shared
from extensions.commands import content
from test_cwl_web_manage_delivery import fixture


def components():
    # Redacted text/IDs, with the actual Join the Family component layout:
    # a top-level gallery followed by a container of text and an action row.
    return json.loads((Path(__file__).parent / 'fixtures' / 'gauntlet_published_components.json').read_text())


def message(parts):
    payload = {
        'id': '789', 'channel_id': '456', 'guild_id': str(delivery.GUILD_ID),
        'author': {'id': '555', 'username': 'Test bot', 'discriminator': '0000', 'avatar': None},
        'timestamp': '2026-11-05T12:00:00+00:00', 'edited_timestamp': None,
        'content': '', 'tts': False, 'mention_everyone': False,
        'mentions': [], 'mention_roles': [], 'attachments': [], 'embeds': [],
        'pinned': False, 'type': 0, 'flags': 32768, 'components': parts,
    }
    return hikari.impl.EntityFactoryImpl(NS()).deserialize_message(payload)


def test_actual_post_layout_has_equal_json_and_hikari_snapshots():
    parts = components()
    observed = delivery.snapshot(parts)
    assert observed == delivery.snapshot(message(parts).components)
    assert len(observed['text']) == 4
    assert observed['media'] == ['https://cdn.discordapp.com/attachments/123/456/banner.png']


def test_recursive_text_gallery_and_thumbnail_order_matches_native_objects():
    parts = components()
    parts[1]['components'].insert(0, {
        'type': 9, 'id': 890,
        'components': [{'type': 10, 'id': 891, 'content': 'Nested section text'}],
        'accessory': {'type': 11, 'id': 892, 'media': {'url': 'https://example.com/thumb.png'}},
    })
    parts[1]['components'].append({
        'type': 12, 'id': 893,
        'items': [{'media': {'url': 'https://example.com/nested.png'}}],
    })
    parts.append({'type': 10, 'id': 894, 'content': 'Top-level text'})
    observed = delivery.snapshot(parts)
    assert observed == delivery.snapshot(message(parts).components)
    assert observed['text'][0] == 'Nested section text'
    assert observed['text'][-1] == 'Top-level text'
    assert observed['media'] == [
        'https://cdn.discordapp.com/attachments/123/456/banner.png',
        'https://example.com/thumb.png', 'https://example.com/nested.png',
    ]


def test_only_discord_attachment_signatures_are_ignored():
    parts = components()
    original = delivery.snapshot(parts)
    parts[0]['items'][0]['media']['url'] += '&width=400'
    assert delivery.snapshot(parts) != original
    assert delivery.snapshot(parts) == delivery.snapshot(message(parts).components)
    parts[0]['items'][0]['media']['url'] = 'https://example.com/image.png?ex=111'
    other = delivery.snapshot(parts)
    parts[0]['items'][0]['media']['url'] = 'https://example.com/image.png?ex=222'
    assert delivery.snapshot(parts) != other


@pytest.mark.parametrize('action', ['send', 'update'])
@pytest.mark.parametrize('change', [None, 'signature', 'text', 'image'])
def test_publish_checks_cross_representation_live_text_and_media(action, change):
    async def scenario():
        row, db, bot, ctx = fixture()
        original = components()
        current = copy.deepcopy(original)
        if change == 'text':
            current[1]['components'][0]['content'] += ' changed by another editor'
        elif change == 'image':
            current[0]['items'][0]['media']['url'] = 'https://cdn.discordapp.com/attachments/123/999/replacement.png'
        elif change == 'signature':
            current[0]['items'][0]['media']['url'] = 'https://cdn.discordapp.com/attachments/123/456/banner.png?ex=444&is=555&hm=666'
        target = {'channel_id': 456, 'message_id': 789}
        row['action'] = action
        row['values'].update(target=target, post=delivery.snapshot(original))
        bot.rest.fetch_message = AsyncMock(return_value=message(current))
        with (
            patch.object(content, 'template_for', AsyncMock(return_value=(['Test'], {}, 1))),
            patch.object(content, 'destination_for', AsyncMock(return_value=456)),
            patch.object(content, 'published_for', AsyncMock(return_value=target)),
            patch.object(content, 'destination_permissions', AsyncMock(return_value=hikari.Permissions.ADMINISTRATOR)),
            patch.object(content, '_ready_for_destination', AsyncMock(return_value=(True, None))),
            patch.object(content, 'render', AsyncMock(return_value=[])),
            patch.object(content, 'remember_published', AsyncMock()),
            patch.object(content, 'loaded_published_target', AsyncMock(return_value=target)),
            patch.object(content, 'component_shape', return_value='supported-shape'),
            patch.object(content, 'acknowledgement_id', return_value='existing-acknowledgement'),
            patch.object(content, 'baseline', AsyncMock(return_value=[])),
        ):
            if change in {'text', 'image'}:
                with pytest.raises(ValueError, match='Discord post changed'):
                    await delivery.publish(bot, db, row, ctx)
                bot.rest.create_message.assert_not_awaited()
                bot.rest.edit_message.assert_not_awaited()
            else:
                await delivery.publish(bot, db, row, ctx)
                called = bot.rest.create_message if action == 'send' else bot.rest.edit_message
                called.assert_awaited_once()
                assert all(called.await_args.kwargs[key] is False for key in content.NO_MENTIONS)
            assert not await db.bot_config.find_one({'_id': 'content_publish:456:789'})
    asyncio.run(scenario())


def test_deleted_saved_target_still_blocks_publish_review():
    async def scenario():
        @asynccontextmanager
        async def mongo(_):
            yield NS()
        request = NS()
        with (
            patch.object(shared, 'mongo', mongo),
            patch.object(shared, 'discord', AsyncMock(side_effect=web.HTTPNotFound())),
            patch.object(content, 'template_for', AsyncMock(return_value=(['Test'], {}, 1))),
            patch.object(content, 'destination_for', AsyncMock(return_value=456)),
            patch.object(content, 'published_for', AsyncMock(return_value={'channel_id': 456, 'message_id': 789})),
        ):
            with pytest.raises(web.HTTPNotFound):
                await delivery.review(request, 'join-family')
    asyncio.run(scenario())
