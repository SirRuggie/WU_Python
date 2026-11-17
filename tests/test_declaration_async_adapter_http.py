"""Always-run HTTP adapter checks with fixture SQLite and async Mongo fakes.

These exercise the real handlers/auth/response adaptation without opting into a
Mongo server or launching any notification task.
"""
import asyncio
from contextlib import asynccontextmanager
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_cwl_web_roster as fixtures
from utils.declaration_ping_store import PingConflict


class DeclarationAsyncAdapterHTTP(unittest.IsolatedAsyncioTestCase):
    auth = fixtures.RosterTests.auth
    call = fixtures.RosterTests.call
    asyncTearDown = fixtures.RosterTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.RosterTests.asyncSetUp(self)
        self.base = f'/seasons/{self.sid}/declaration-pings/lazy'
        self.token = 'a' * 32
        self.channel = {'id': '234567890123456789', 'name': 'fixture'}
        self.active = {'token': self.token, 'actor_id': '505227988229554179',
                       'season_id': self.sid, 'pool': 'lazy', 'state': 'sending'}
        self.claim_threads = []
        self.finish_threads = []
        async def claim(*args, **kwargs):
            self.claim_threads.append(threading.get_ident())
            await asyncio.sleep(0)
            return True, dict(self.active)
        async def finish(*args, **kwargs):
            self.finish_threads.append(threading.get_ident())
            await asyncio.sleep(0)
            return {**self.active, 'state': 'uncertain'}
        self.storage = NS(
            recover_other_process=AsyncMock(), receipt=AsyncMock(return_value=None),
            review=AsyncMock(return_value={'mode': 'live', 'channel': self.channel, 'revision': 1}),
            read=AsyncMock(return_value={'channel': self.channel}), claim=AsyncMock(side_effect=claim),
            finish=AsyncMock(side_effect=finish),
        )  # Deliberately no `.store`: this is an async Mongo owner, not SQLite.
        @asynccontextmanager
        async def mongo(request):
            yield NS()
        self.launch = Mock()
        replacements = {
            'cwl_web.declaration_pings.mongo': mongo,
            'cwl_web.declaration_pings.DeclarationPingStore': Mock(return_value=self.storage),
            'cwl_web.declaration_pings.fresh_groups': AsyncMock(return_value=([{}], 1, {}, 'lineup')),
            'cwl_web.declaration_pings.fingerprint': Mock(return_value='fixture-fingerprint'),
            'cwl_web.declaration_pings.messages': Mock(return_value=[{'fixture': True}]),
            'cwl_web.declaration_pings.declaration_lineup.current': Mock(return_value={'changes': [], 'signature': 'lineup'}),
            'cwl_web.declaration_pings.destinations.destination': AsyncMock(return_value=self.channel),
            'cwl_web.declaration_pings.destinations.authorized': AsyncMock(return_value=True),
            'cwl_web.declaration_pings.launch': self.launch,
        }
        for target, replacement in replacements.items():
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def send(self, headers=None, **overrides):
        body = {'token': self.token, 'confirm': True, 'send_again': False, **overrides}
        return await self.call('POST', self.base + '/send', headers or self.owner, json=body)

    async def test_live_claim_is_awaited_and_receipt_replay_does_not_claim_twice(self):
        response = await self.send()
        self.assertEqual(response.status, 202, await response.text())
        self.assertEqual((await response.json())['receipt']['state'], 'sending')
        self.storage.claim.assert_awaited_once()
        self.assertEqual(self.claim_threads, [threading.get_ident()])
        self.assertEqual(self.storage.claim.await_args.args[:4],
                         ('lazy', self.active['actor_id'], self.sid, self.token))
        self.assertFalse(self.storage.claim.await_args.kwargs['send_again'])
        self.launch.assert_called_once()
        self.storage.receipt.return_value = dict(self.active)
        replay = await self.send()
        self.assertEqual(replay.status, 200)
        self.storage.claim.assert_awaited_once()
        self.launch.assert_called_once()

    async def test_interrupted_finalize_is_awaited_without_launching_delivery(self):
        self.storage.receipt.return_value = dict(self.active)
        response = await self.call('POST', self.base + '/close-interrupted', self.owner,
                                   json={'token': self.token, 'confirm': True})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())['receipt']['state'], 'uncertain')
        self.storage.finish.assert_awaited_once()
        self.assertEqual(self.finish_threads, [threading.get_ident()])
        self.assertEqual(self.storage.finish.await_args.args[:3], ('lazy', self.token, 'uncertain'))
        self.launch.assert_not_called()

    async def test_claim_and_finalize_conflicts_remain_http_409(self):
        self.storage.claim.side_effect = PingConflict('Review changed')
        response = await self.send()
        self.assertEqual(response.status, 409)
        self.launch.assert_not_called()
        self.storage.receipt.return_value = dict(self.active)
        self.storage.finish.side_effect = PingConflict('Receipt changed')
        response = await self.call('POST', self.base + '/close-interrupted', self.owner,
                                   json={'token': self.token, 'confirm': True})
        self.assertEqual(response.status, 409)
        self.launch.assert_not_called()

    async def test_permissions_confirmation_and_receipt_scope_still_block_calls(self):
        self.assertEqual((await self.send(self.member)).status, 403)
        self.assertEqual((await self.send(confirm=False)).status, 400)
        self.storage.claim.assert_not_awaited()
        self.storage.receipt.return_value = {**self.active, 'season_id': self.sid + 1}
        response = await self.call('POST', self.base + '/close-interrupted', self.owner,
                                   json={'token': self.token, 'confirm': True})
        self.assertEqual(response.status, 409)
        self.storage.finish.assert_not_awaited()
        self.launch.assert_not_called()
