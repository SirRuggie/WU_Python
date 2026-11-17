"""Fixture-only role-cache and unchanged dashboard management grant rights."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
import pytest

from cwl_web import access_settings as access
from cwl_web.server_management import allowed
from utils.dashboard_access import DOCUMENT_ID, OWNER_IDS, PERMISSIONS, SECTION_SCOPE


def test_role_cache_is_scoped_immutable_and_expires_at_30_seconds(monkeypatch):
    async def scenario():
        now = [0.0]
        monkeypatch.setattr(access, '_role_clock', lambda: now[0])
        app = {}
        request = SimpleNamespace(app=app)
        original = ['777']
        fetch = AsyncMock(return_value={'roles': original})
        result = await access.member_roles(request, 'guild1', 'user1', fetch)
        result.clear()
        original.append('888')
        now[0] = 29.999
        assert await access.member_roles(request, 'guild1', 'user1', fetch) == ['777']
        fetch.assert_awaited_once()
        for target, guild, user in (
            (request, 'guild1', 'user2'),
            (request, 'guild2', 'user1'),
            (SimpleNamespace(app={}), 'guild1', 'user1'),
        ):
            assert await access.member_roles(target, guild, user, fetch) == ['777', '888']
        assert fetch.await_count == 4
        now[0] = 30.0
        assert await access.member_roles(request, 'guild1', 'user1', fetch) == ['777', '888']
        assert fetch.await_count == 5
        assert all(isinstance(value[1], tuple) for value in app[access.ROLE_CACHE_KEY]['roles'].values())
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [web.HTTPNotFound, web.HTTPForbidden,
                                     web.HTTPServiceUnavailable, TimeoutError,
                                     RuntimeError, asyncio.CancelledError])
def test_expired_success_is_discarded_and_failures_are_never_cached(monkeypatch, failure):
    async def scenario():
        now = [0.0]
        monkeypatch.setattr(access, '_role_clock', lambda: now[0])
        request = SimpleNamespace(app={})
        fetch = AsyncMock(side_effect=[{'roles': ['777']}, failure(), {'roles': ['888']}])
        assert await access.member_roles(request, 1, 100, fetch) == ['777']
        now[0] = 30
        with pytest.raises(failure):
            await access.member_roles(request, 1, 100, fetch)
        assert request.app[access.ROLE_CACHE_KEY]['roles'] == {}
        assert await access.member_roles(request, 1, 100, fetch) == ['888']
        assert fetch.await_count == 3
    asyncio.run(scenario())


@pytest.mark.parametrize('member', [None, [], {}, {'roles': None}, {'roles': '777'},
                                   {'roles': [777]}, {'roles': [True]},
                                   {'roles': ['']}, {'roles': ['٧٧٧']},
                                   {'roles': ['x']}, {'roles': [{}]}])
def test_malformed_members_never_enter_cache(member):
    async def scenario():
        request = SimpleNamespace(app={})
        fetch = AsyncMock(side_effect=[member, {'roles': []}])
        with pytest.raises(web.HTTPServiceUnavailable):
            await access.member_roles(request, 1, 100, fetch)
        assert request.app[access.ROLE_CACHE_KEY]['roles'] == {}
        assert await access.member_roles(request, 1, 100, fetch) == []
        assert fetch.await_count == 2
    asyncio.run(scenario())



@pytest.mark.parametrize('role', ['0', '-1', '18446744073709551616',
                                 '9999999999999999999999999', '9' * 5000])
def test_out_of_range_role_response_is_not_cached_and_valid_response_is_refetched(role):
    async def scenario():
        request = SimpleNamespace(app={})
        valid = '123456789012345678'
        fetch = AsyncMock(side_effect=[{'roles': [valid, role]}, {'roles': [valid]}])
        with pytest.raises(web.HTTPServiceUnavailable):
            await access.member_roles(request, 1, 100, fetch)
        assert request.app[access.ROLE_CACHE_KEY]['roles'] == {}
        assert await access.member_roles(request, 1, 100, fetch) == [valid]
        assert await access.member_roles(request, 1, 100, fetch) == [valid]
        assert fetch.await_count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('role', ['1', '123456789012345678', '18446744073709551615', '00001'])
def test_valid_uint64_roles_are_cached_without_coercion(role):
    async def scenario():
        request = SimpleNamespace(app={})
        fetch = AsyncMock(return_value={'roles': [role]})
        assert await access.member_roles(request, 1, 100, fetch) == [role]
        assert await access.member_roles(request, 1, 100, fetch) == [role]
        assert request.app[access.ROLE_CACHE_KEY]['roles'][("1", "100")][1] == (role,)
        fetch.assert_awaited_once()
    asyncio.run(scenario())


def test_expired_success_has_no_fallback_when_role_numeric_range_is_invalid(monkeypatch):
    async def scenario():
        now = [0.0]
        monkeypatch.setattr(access, '_role_clock', lambda: now[0])
        request = SimpleNamespace(app={})
        fetch = AsyncMock(side_effect=[{'roles': ['123456789012345678']},
                                      {'roles': ['18446744073709551616']},
                                      {'roles': ['18446744073709551615']}])
        assert await access.member_roles(request, 1, 100, fetch) == ['123456789012345678']
        now[0] = 30.0
        with pytest.raises(web.HTTPServiceUnavailable):
            await access.member_roles(request, 1, 100, fetch)
        assert request.app[access.ROLE_CACHE_KEY]['roles'] == {}
        assert await access.member_roles(request, 1, 100, fetch) == ['18446744073709551615']
        assert fetch.await_count == 3
    asyncio.run(scenario())


def test_concurrent_reads_share_success_and_cancelled_waiter_does_not_cancel_fetch():
    async def scenario():
        request = SimpleNamespace(app={})
        started, release = asyncio.Event(), asyncio.Event()
        async def fetch():
            started.set()
            await release.wait()
            return {'roles': ['777']}
        lookup = AsyncMock(side_effect=fetch)
        leader = asyncio.create_task(access.member_roles(request, 1, 100, lookup))
        await started.wait()
        waiter = asyncio.create_task(access.member_roles(request, 1, 100, lookup))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        assert await leader == ['777']
        assert await access.member_roles(request, 1, 100, lookup) == ['777']
        lookup.assert_awaited_once()
    asyncio.run(scenario())


def test_cancelled_fetch_releases_waiters_and_does_not_cache_a_result():
    async def scenario():
        request = SimpleNamespace(app={})
        started = asyncio.Event()
        calls = []
        async def fetch():
            calls.append(1)
            if len(calls) == 1:
                started.set()
                await asyncio.Future()
            return {'roles': ['888']}
        leader = asyncio.create_task(access.member_roles(request, 1, 100, fetch))
        await started.wait()
        waiter = asyncio.create_task(access.member_roles(request, 1, 100, fetch))
        await asyncio.sleep(0)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        assert await waiter == ['888']
        assert len(calls) == 2
    asyncio.run(scenario())


def test_concurrent_cold_reads_fetch_once():
    async def scenario():
        request = SimpleNamespace(app={})
        async def fetch():
            await asyncio.sleep(0)
            return {'roles': ['777']}
        lookup = AsyncMock(side_effect=fetch)
        assert await asyncio.gather(*(access.member_roles(request, 1, 100, lookup) for _ in range(10))) == [['777']] * 10
        lookup.assert_awaited_once()
    asyncio.run(scenario())


def test_cache_is_bounded_and_expired_entries_are_pruned(monkeypatch):
    async def scenario():
        now = [0.0]
        monkeypatch.setattr(access, '_role_clock', lambda: now[0])
        monkeypatch.setattr(access, 'ROLE_CACHE_LIMIT', 2)
        request = SimpleNamespace(app={})
        fetch = AsyncMock(return_value={'roles': []})
        for user in ('100', '200', '300'):
            await access.member_roles(request, 1, user, fetch)
        assert len(request.app[access.ROLE_CACHE_KEY]['roles']) == 2
        await access.member_roles(request, 1, '100', fetch)
        assert fetch.await_count == 4
        now[0] = 30
        await access.member_roles(request, 1, '400', fetch)
        assert len(request.app[access.ROLE_CACHE_KEY]['roles']) == 1
    asyncio.run(scenario())


def test_management_grants_keep_every_section_write_and_read_only_aggregate_denies_writes():
    async def scenario():
        lookup = AsyncMock()
        db = SimpleNamespace(bot_config=SimpleNamespace(find_one=lookup))
        for kind in ('user', 'role'):
            for permission in PERMISSIONS:
                lookup.return_value = {'_id': DOCUMENT_ID, 'grants': [
                    {'kind': kind, 'id': '123' if kind == 'user' else '777', 'permissions': [permission]},
                ]}
                actor = {'dashboard': True, 'user_id': '123', 'role_ids': ['777'],
                         'dashboard_scopes': [permission]}
                for section, scope in SECTION_SCOPE.items():
                    for write in (False, True):
                        assert await allowed(actor, section, db, write=write) is (permission == scope)
                assert await allowed(actor, 'strikes_read', db, write=False) is (permission in {'strikes', 'strikes_add', 'strikes_remove'})
                assert not await allowed(actor, 'strikes_read', db, write=True)
                assert not await allowed(actor, 'unknown', db, write=True)
        for owner in OWNER_IDS:
            actor = {'dashboard': True, 'user_id': owner}
            assert await allowed(actor, 'strikes_read', db) is True
            assert not await allowed(actor, 'strikes_read', db, write=True)
            for section in SECTION_SCOPE:
                assert await allowed(actor, section, db, write=True) is True
    asyncio.run(scenario())
