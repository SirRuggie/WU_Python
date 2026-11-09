"""HTTP contract checks for moderation notices, without live Discord delivery."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace as NS

import pytest

from extensions.events import member_events as transport


@pytest.mark.parametrize('cache_kind', ['member', 'global_user', 'username', 'missing', 'raises'])
@pytest.mark.parametrize('forum', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_cached_names_keep_one_delivery_attempt_and_receipt(cache_kind, forum, failed):
    from utils.member_event_cards import sample_row
    from utils.member_event_settings import normalize_settings
    from utils.member_events import MemberEventStore, GUILD_ID
    def member(guild, uid):
        assert guild == GUILD_ID and uid == 987654321098765432
        if cache_kind == 'raises':
            raise RuntimeError('fixture cache error')
        return NS(display_name='Cached moderator') if cache_kind == 'member' else None
    def user(uid):
        assert uid == 987654321098765432
        if cache_kind == 'raises':
            raise RuntimeError('fixture user cache error')
        return (NS(global_name='Global moderator', username='fallback') if cache_kind == 'global_user'
                else NS(global_name=None, username='Username moderator') if cache_kind == 'username' else None)
    bot = NS(cache=NS(get_member=member, get_user=user), rest=NS(fetch_user=AsyncMock(side_effect=AssertionError('No REST lookup'))))
    row = {**sample_row('kick'), '_id': 'fixture', 'channel_id': '1004519991648997447',
           'forum_tag_id': None, 'details': {'recovered': True}}
    saved = normalize_settings(None, MemberEventStore.default_settings())
    saved['events']['kick'] = {'enabled': True, 'channel_id': row['channel_id'], 'forum_tag_id': None}
    store = NS(settings=AsyncMock(return_value=saved), claim=AsyncMock(return_value=row),
               finish=AsyncMock(), skip_queued=AsyncMock())
    calls = []
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'fixture-token'}), \
         patch.object(transport, 'channel_ready', new=AsyncMock(return_value=NS(type=15 if forum else 0))), \
         patch.object(transport.aiohttp, 'ClientSession', return_value=Session(calls, status=502 if failed else 200)):
        if failed:
            with pytest.raises(RuntimeError, match='HTTP 502'):
                asyncio.run(transport.deliver(store, bot, row))
            store.finish.assert_awaited_once_with('fixture', status='uncertain')
        else:
            assert asyncio.run(transport.deliver(store, bot, row))
            store.finish.assert_awaited_once_with('fixture', status='sent', message_id='123456789012345678')
    assert len(calls) == 1
    store.claim.assert_awaited_once_with('fixture')
    bot.rest.fetch_user.assert_not_awaited()
    payload = calls[0][1]['json']
    message = payload.get('message') or payload
    text = json.dumps(message, ensure_ascii=False)
    known = {'member': 'Cached moderator', 'global_user': 'Global moderator', 'username': 'Username moderator'}
    if cache_kind in known:
        assert f'[{known[cache_kind]}](https://discord.com/users/987654321098765432)' in text
    else:
        assert '<@987654321098765432>' in text
    assert text.count('Recovered after restart') == 1
    assert message['allowed_mentions'] == {'parse': []}
    if forum:
        assert payload['name'].startswith('Kicked · Sample member · 123456789012345678 · ')


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
    assert ':f>' in rendered and '**Joined**' in rendered
    actions = [component for container in payload['components']
               for row in container['components'] if row['type'] == 1
               for component in row['components']]
    assert actions == [{'type': 2, 'style': 5, 'label': 'View profile ↗',
                        'url': 'https://discord.com/users/123456789012345678'},
                       {'type': 2, 'style': 5, 'label': 'Member history ↗',
                        'url': 'https://dash.warriorsunited.cc/server/moderation/member/123456789012345678'}]


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
    assert 'flags' not in message
    assert message['allowed_mentions'] == {'parse': []}
    assert message['embeds'][0]['thumbnail']['url'] == 'attachment://member-avatar.png'
    assert message['components'] == [{'type': 1, 'components': [
        {'type': 2, 'style': 5, 'label': 'View profile ↗',
         'url': 'https://discord.com/users/123456789012345678'},
        {'type': 2, 'style': 5, 'label': 'Member history ↗',
         'url': 'https://dash.warriorsunited.cc/server/moderation/member/123456789012345678'}]}]
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


BATCH_TWO_KINDS = ['unban', 'role_create', 'role_update', 'role_delete', 'roles_added', 'roles_removed',
                   'message_delete', 'message_edit', 'message_bulk_delete', 'channel_create', 'channel_update',
                   'channel_delete', 'channel_permissions', 'thread_delete', 'thread_lock', 'server_update',
                   'emoji', 'sticker', 'app', 'webhook', 'automod']
NEW_KINDS = ['timeout_add', 'timeout_remove', 'member_update', 'link',
             'invite_create', 'invite_delete', 'invite_use', *BATCH_TWO_KINDS]


@pytest.mark.parametrize('kind', NEW_KINDS)
@pytest.mark.parametrize('forum', [False, True])
def test_new_logs_post_without_avatar_bytes_or_key_errors(kind, forum):
    from utils.member_event_cards import sample_row
    calls = []
    row = {**sample_row(kind), 'channel_id': 1004519991648997447}
    if kind in ('invite_create', 'invite_delete'):
        row['user_id'] = '0'
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls)
    ):
        assert asyncio.run(transport.post_card(row, forum=forum)) == '123456789012345678'
    url, request = calls[0]
    assert 'data' not in request  # No multipart avatar upload for the new kinds.
    payload = request['json']
    if forum:
        assert len(payload['name']) <= 100 and url.endswith('/threads')
        assert payload['message']['allowed_mentions'] == {'parse': []}
    else:
        assert payload['flags'] == 32768 and 'content' not in payload and 'embeds' not in payload
        assert payload['allowed_mentions'] == {'parse': []}


def test_every_configurable_kind_has_a_preview_card():
    from utils.member_event_cards import build_card, build_forum_message, sample_row
    from utils.member_event_settings import EVENT_TYPES
    assert set(NEW_KINDS) < set(EVENT_TYPES)
    for kind in EVENT_TYPES:
        assert build_card(sample_row(kind))['components'][0]['accent_color']
        assert build_forum_message(sample_row(kind))['embeds'][0]['description']


def test_link_card_is_inert_bounded_and_has_a_jump_button():
    from utils.member_event_cards import build_card, sample_row
    row = sample_row('link')
    row['details'] = {
        'channel_id': '223456789012345678', 'message_id': '323456789012345678',
        'content': '@everyone <@123456789012345678> https://evil.example/x [a](https://evil.example) ' + 'y' * 600,
        'urls': [f'https://e.example/{i}`' + 'z' * 300 for i in range(15)],
    }
    card = build_card(row)
    text = json.dumps(card, ensure_ascii=False)
    texts = [child['content'] for child in card['components'][0]['components'] if child['type'] == 10]
    message = next(t for t in texts if t.startswith('**Message**'))
    assert 'https://evil' not in message and 'https\u200b://evil' in message
    assert '@everyone' not in text and '<@123456789012345678> https' not in text
    assert len(message) < 560
    links = next(t for t in texts if t.startswith('**Links**')).split('\n')[1:]
    assert links.pop() == '+5 more'  # Ten shown, five summarized.
    assert len(links) == 10 and all(len(line) <= 202 and line.startswith('`') and line.endswith('`') for line in links)
    assert not any('`' in line[1:-1] for line in links)
    buttons = [c for r in card['components'][0]['components'] if r['type'] == 1 for c in r['components']]
    assert buttons[-1]['url'] == 'https://discord.com/channels/644963518025826315/223456789012345678/323456789012345678'


def test_invite_use_card_names_vanity_and_unknown_attribution():
    from utils.member_event_cards import build_card, sample_row
    row = sample_row('invite_use')
    vanity = json.dumps(build_card({**row, 'details': {**row['details'], 'vanity': True}}), ensure_ascii=False)
    unknown = json.dumps(build_card({**row, 'details': {'unknown': True}}), ensure_ascii=False)
    assert 'Vanity URL' in vanity and 'Unknown invite' in unknown and 'Inviter' not in unknown
    named = json.dumps(build_card(row), ensure_ascii=False)
    assert 'Spring recruitment' in named and '8 of 10' in named


def bulk_row(**changes):
    from utils.member_event_cards import sample_row
    row = sample_row('message_bulk_delete')
    row['details'] = {**row['details'], 'transcript': '[2026-11-06 12:00:00 UTC] alice (1): hello\n'}
    return {**row, 'channel_id': 1004519991648997447, **changes}


def test_bulk_delete_transcript_is_a_referenced_file_in_a_text_channel_post():
    calls = []
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls)
    ), patch.object(transport.aiohttp, 'FormData', Form):
        assert asyncio.run(transport.post_card(bulk_row())) == '123456789012345678'
    fields = calls[0][1]['data'].fields
    payload = json.loads(fields['payload_json'][0])
    assert payload['flags'] == 32768 and payload['attachments'] == [{'id': 0, 'filename': 'message-transcript.txt'}]
    container = payload['components'][0]['components']
    assert {'type': 13, 'file': {'url': 'attachment://message-transcript.txt'}} in container
    data, meta = fields['files[0]']
    assert data.decode().startswith('[2026-11-06') and meta['filename'] == 'message-transcript.txt'
    assert meta['content_type'].startswith('text/plain')


def test_bulk_delete_transcript_is_an_attachment_on_a_forum_starter_and_absent_without_one():
    calls = []
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls)
    ), patch.object(transport.aiohttp, 'FormData', Form):
        asyncio.run(transport.post_card(bulk_row(), forum=True))
    fields = calls[0][1]['data'].fields
    message = json.loads(fields['payload_json'][0])['message']
    assert message['attachments'] == [{'id': 0, 'filename': 'message-transcript.txt'}]
    assert 'flags' not in message and fields['files[0]'][1]['filename'] == 'message-transcript.txt'
    calls.clear()
    plain = bulk_row()
    plain['details'] = {k: v for k, v in plain['details'].items() if k != 'transcript'}
    with patch.dict('os.environ', {'DISCORD_TOKEN': 'test-token'}), patch.object(
        transport.aiohttp, 'ClientSession', return_value=Session(calls)
    ):
        asyncio.run(transport.post_card(plain))
    assert 'data' not in calls[0][1] and 'attachments' not in calls[0][1]['json']
    assert 13 not in [c['type'] for c in calls[0][1]['json']['components'][0]['components']]
