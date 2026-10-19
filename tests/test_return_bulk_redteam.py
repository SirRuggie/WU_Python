"""Adversarial return-reminder retry checks; no network or live sends."""
import asyncio
from unittest.mock import AsyncMock

from extensions.commands import lazycwl_dashboard as dashboard


def test_native_bulk_retry_excludes_success_unknown_partial_and_stale(monkeypatch):
    async def scenario():
        docs = [{'_id': str(i), 'clan_tag': f'#A{i}', 'clan_name': f'Clan {i}', 'status': 'active'} for i in range(6)]
        token = dashboard._session(44, 55)
        dashboard._sessions[token]['section'] = 'FWA'
        monkeypatch.setattr(dashboard, '_active', AsyncMock(return_value=docs))
        monkeypatch.setattr(dashboard, 'build_home', AsyncMock(return_value=[]))
        outcomes = [
            {'ok': True, 'sent': True},
            RuntimeError('Connection lost after a message might have been sent'),
            {'ok': False, 'error': 'No reminder destination is configured.'},
            {'ok': False, 'sent': True, 'error': 'Partial delivery'},
            {'ok': False, 'stale': True, 'error': 'The list changed'},
            None,
        ]
        send = AsyncMock(side_effect=outcomes)
        monkeypatch.setattr(dashboard.service, 'remind_now', send)
        nonce = dashboard._bind(token, 'ALL', docs, operation='send')
        response = await dashboard._apply_bound(object(), token, nonce, 'send', None)
        assert send.await_count == 6
        pending = dashboard._sessions[token]['pending']
        assert len(pending) == 1
        retry_nonce, bound = next(iter(pending.items()))
        assert bound['ids'] == ['2']
        assert bound['retry'] is True
        text = '\n'.join(getattr(part, 'content', '') for container in response for part in container.components)
        assert 'Check Discord' in text
        send.side_effect = None
        send.return_value = {'ok': True, 'sent': True}
        await dashboard._apply_bound(object(), token, retry_nonce, 'send', None)
        assert send.await_count == 7
        assert send.call_args.args == ('#A2',)
        assert not dashboard._sessions[token]['pending']
        dashboard._sessions.pop(token, None)
    asyncio.run(scenario())


def test_native_unknown_delivery_has_no_retry_button(monkeypatch):
    async def scenario():
        doc = {'_id': '1', 'clan_tag': '#A1', 'clan_name': 'Clan 1', 'status': 'active'}
        token = dashboard._session(44, 55)
        dashboard._sessions[token]['section'] = 'FWA'
        monkeypatch.setattr(dashboard, '_active', AsyncMock(return_value=[doc]))
        monkeypatch.setattr(dashboard, 'build_home', AsyncMock(return_value=[]))
        monkeypatch.setattr(dashboard.service, 'remind_now', AsyncMock(side_effect=ValueError('ambiguous after send')))
        nonce = dashboard._bind(token, '#A1', [doc], operation='send')
        await dashboard._apply_bound(object(), token, nonce, 'send', None)
        assert dashboard._sessions[token]['pending'] == {}
        dashboard._sessions.pop(token, None)
    asyncio.run(scenario())
