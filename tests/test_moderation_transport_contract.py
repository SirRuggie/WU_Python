"""HTTP contract checks for moderation notices, without live Discord delivery."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from extensions.events import member_events as transport


class Form:
    def __init__(self):
        self.fields = {}

    def add_field(self, name, value, **metadata):
        self.fields[name] = (value, metadata)


class Response:
    def __init__(self, status, payload):
        self.status, self.payload = status, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.payload


class Session:
    def __init__(self, calls, status=200, payload=None):
        self.calls, self.status = calls, status
        self.payload = payload or {'id': '123456789012345678'}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.status, self.payload)


def sample(**changes):
    return {
        'channel_id': 1004519991648997447,
        'event_type': 'kick',
        'user_id': '123456789012345678',
        'display_name': '@everyone **Name**',
        'username': 'sample',
        'occurred_at': datetime(2026, 10, 27, tzinfo=timezone.utc),
        'joined_at': datetime(2025, 7, 30, tzinfo=timezone.utc),
        'moderator_id': '123456789012345679',
        'reason': '@here <@123456789012345678> [unsafe](https://example.com)',
        'avatar': None,
        **changes,
    }


def test_text_notice_has_v2_and_disables_mentions():
    calls = []
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls)
    ):
        receipt = asyncio.run(transport.post_card(sample()))
    assert receipt == '123456789012345678'
    assert len(calls) == 1
    url, request = calls[0]
    assert url.endswith('/channels/1004519991648997447/messages')
    payload = request['json']
    assert payload['flags'] == 32768
    assert payload['allowed_mentions'] == {'parse': []}
    assert 'embeds' not in payload and 'content' not in payload
    rendered = json.dumps(payload['components'], ensure_ascii=False)
    assert '@everyone' not in rendered and '@here' not in rendered
    assert ':D>' in rendered and 'Moderator ID:' in rendered


def test_forum_notice_uploads_avatar_in_initial_request_and_returns_message_receipt():
    calls = []
    row = sample(avatar=b'avatar-bytes', avatar_type='image/png', forum_tag_id=123456789012345680)
    response = {'id': '123456789012345681', 'message': {'id': '123456789012345682'}}
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls, payload=response)
    ), patch.object(transport.aiohttp, 'FormData', Form):
        receipt = asyncio.run(transport.post_card(row, forum=True))
    assert receipt == '123456789012345682'
    assert len(calls) == 1
    url, request = calls[0]
    assert url.endswith('/channels/1004519991648997447/threads')
    fields = request['data'].fields
    payload = json.loads(fields['payload_json'][0])
    assert len(payload['name']) <= 100
    assert payload['applied_tags'] == ['123456789012345680']
    message = payload['message']
    assert 'flags' not in message and 'components' not in message
    assert message['allowed_mentions'] == {'parse': []}
    assert message['embeds'][0]['thumbnail']['url'] == 'attachment://member-avatar.png'
    assert fields['files[0]'][0] == b'avatar-bytes'
    assert fields['files[0]'][1]['content_type'] == 'image/png'


@pytest.mark.parametrize('forum', [False, True])
def test_failed_create_is_not_retried_or_replaced_with_another_format(forum):
    calls = []
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls, status=502)
    ):
        with pytest.raises(RuntimeError, match='HTTP 502'):
            asyncio.run(transport.post_card(sample(), forum=forum))
    assert len(calls) == 1
