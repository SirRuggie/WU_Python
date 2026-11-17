"""Fixture-only regressions for complete ordered writer jobs and anonymous auth."""
import asyncio
from collections import OrderedDict
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
import pytest

from cwl_web.app import API, _hash, auth_callback, auth_rate_limit, auth_start, create_app
from cwl_web.store import Store
from utils.cwl_dashboard_state import DashboardDurabilityError, MongoDashboardState
from test_cwl_dashboard_state import Collection


def test_slow_publish_serializes_saves_and_keeps_authenticated_reads_responsive(tmp_path):
    async def check():
        app = create_app(db_path=str(tmp_path / 'working.sqlite'), dev_fixture=True,
                         secure_cookies=False, oauth={'client_id': 'id', 'client_secret': 'test',
                                                     'redirect_uri': 'https://example.test/callback'})
        storage = app['store']
        with storage.tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)",
                       (_hash('fixture-cookie'), '505227988229554179', 'Owner', 0, 'csrf', int(time.time()) + 60))
        entered = threading.Event()
        order = []
        writer_threads = []
        class Owner:
            poisoned = False
            def check(self):
                pass
            def publish(self, db):
                writer_threads.append(threading.get_ident())
                order.append(db.execute('SELECT COUNT(*) FROM grants').fetchone()[0])
                if len(order) == 1:
                    entered.set()
                    time.sleep(2)
        storage.durability = Owner()
        # The real app lifecycle would perform recovery/heartbeats on this fake.
        # Attach the fake after startup, and remove it before normal cleanup.
        storage.durability = None
        client = TestClient(TestServer(app))
        await client.start_server()
        storage.durability = Owner()
        try:
            def first(db):
                db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('first','fixture')")
                db.execute("UPDATE sessions SET username='uncommitted' WHERE token_hash=?", (_hash('fixture-cookie'),))
            one = asyncio.create_task(storage.run_tx(first))
            assert await asyncio.to_thread(entered.wait, 1)
            two = asyncio.create_task(storage.run_tx(lambda db: db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('second','fixture')").rowcount))
            started = time.monotonic()
            response = await client.get(API + '/auth/me', headers={'Cookie': 'cwl_session=fixture-cookie'})
            elapsed = time.monotonic() - started
            assert response.status == 200
            assert (await response.json())['user']['username'] == 'Owner'
            assert elapsed < .2, elapsed
            assert storage.rows('SELECT * FROM grants') == []
            assert not two.done()
            await asyncio.gather(one, two)
            assert order == [1, 2]
            assert len(set(writer_threads)) == 1
            assert writer_threads[0] != threading.get_ident()
            assert len(storage.rows('SELECT * FROM grants')) == 2
        finally:
            storage.durability = None
            await client.close()
    asyncio.run(check())


def test_real_publish_failure_rolls_back_poison_and_hides_uncommitted_session(tmp_path):
    async def check():
        storage = Store(str(tmp_path / 'working.sqlite'))
        collection = Collection()
        owner = MongoDashboardState(collection)
        owner.seed(Path(storage.path))
        owner.acquire()
        storage.durability = owner
        collection.fail = 'before'
        try:
            with pytest.raises(DashboardDurabilityError):
                await storage.run_tx(lambda db: db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('hidden','fixture')").rowcount)
            assert owner.poisoned
            storage.durability = None
            assert storage.rows('SELECT * FROM grants') == []
            storage.durability = owner
            with pytest.raises(DashboardDurabilityError):
                await storage.run_tx(lambda db: db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('retry','fixture')").rowcount)
        finally:
            await storage.close_writer()
    asyncio.run(check())


def test_cancellation_drains_accepted_job_and_heartbeat_orders_behind_transaction(tmp_path):
    async def check():
        storage = Store(str(tmp_path / 'working.sqlite'))
        entered, release = threading.Event(), threading.Event()
        order = []
        def write(db):
            entered.set()
            assert release.wait(2)
            db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('accepted','fixture')")
            order.append(('write', threading.get_ident()))
        task = asyncio.create_task(storage.run_tx(write))
        assert await asyncio.to_thread(entered.wait, 1)
        heartbeat = asyncio.create_task(storage.run_writer(lambda: order.append(('heartbeat', threading.get_ident()))))
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        assert order == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await heartbeat
        assert [item[0] for item in order] == ['write', 'heartbeat']
        assert len({item[1] for item in order}) == 1
        assert storage.one("SELECT COUNT(*) n FROM grants")['n'] == 1
        await storage.close_writer()
        with pytest.raises(RuntimeError):
            await storage.run_writer(lambda: None)
    asyncio.run(check())


def test_role_progress_whole_body_runs_on_writer_and_table_fence_survives(tmp_path):
    import sqlite3
    async def check():
        storage = Store(str(tmp_path / 'working.sqlite'))
        try:
            thread = await storage.run_role_tx(lambda db: threading.get_ident())
            assert thread != threading.get_ident()
            with pytest.raises(sqlite3.DatabaseError):
                await storage.run_role_tx(lambda db: db.execute("INSERT INTO grants(user_id,granted_by) VALUES ('bad','fixture')"))
            assert storage.rows('SELECT * FROM grants') == []
        finally:
            await storage.close_writer()
    asyncio.run(check())


def request(path='/auth/me', *, peer='127.0.0.1', headers=None, app=None):
    transport = NS(get_extra_info=lambda name: (peer, 12345) if name == 'peername' else None)
    return make_mocked_request('GET', API + path, headers=headers or {},
                               app=app or {'auth_rate_buckets': OrderedDict()}, transport=transport)


def test_auth_rate_limit_twenty_requests_independent_ips_expiry_and_bounded_memory():
    async def check():
        app = {'auth_rate_buckets': OrderedDict()}
        handler = AsyncMock(return_value=web.Response())
        with patch('cwl_web.app.time.monotonic', return_value=100):
            for _ in range(20):
                await auth_rate_limit(request(headers={'X-WU-Client-IP': '203.0.113.1'}, app=app), handler)
            with pytest.raises(web.HTTPException) as denied:
                await auth_rate_limit(request(headers={'X-WU-Client-IP': '203.0.113.1'}, app=app), handler)
            assert denied.value.status == 429
            await auth_rate_limit(request(headers={'X-WU-Client-IP': '203.0.113.2'}, app=app), handler)
            await auth_rate_limit(request(peer='::1', headers={'X-WU-Client-IP': '2001:db8::1'}, app=app), handler)
        assert len(app['auth_rate_buckets']) == 3
        with patch('cwl_web.app.time.monotonic', return_value=161):
            await auth_rate_limit(request(headers={'X-WU-Client-IP': '203.0.113.1'}, app=app), handler)
        assert len(app['auth_rate_buckets']) == 1
        assert len(app['auth_rate_buckets']['203.0.113.1']) == 1
    asyncio.run(check())


@pytest.mark.parametrize('peer,headers', [
    ('198.51.100.1', {'X-WU-Client-IP': '203.0.113.1'}),
    ('127.0.0.2', {'X-WU-Client-IP': '203.0.113.1'}),
    ('127.0.0.1', {}), ('127.0.0.1', {'X-WU-Client-IP': ''}),
    ('127.0.0.1', {'X-WU-Client-IP': 'not-an-ip'}),
    ('127.0.0.1', {'X-Forwarded-For': '203.0.113.1', 'X-Real-IP': '203.0.113.1',
                   'Cf-Connecting-IP': '203.0.113.1'}),
])
def test_missing_invalid_and_untrusted_headers_never_create_a_bucket(peer, headers):
    async def check():
        app = {'auth_rate_buckets': OrderedDict()}
        for _ in range(21):
            await auth_rate_limit(request(peer=peer, headers=headers, app=app), AsyncMock(return_value=web.Response()))
        assert app['auth_rate_buckets'] == {}
    asyncio.run(check())


def test_oauth_start_never_writes_and_callback_replay_error_expiry_cookie_mismatch(tmp_path):
    async def check():
        app = {'oauth': {'client_id': 'id', 'client_secret': 'test', 'redirect_uri': 'https://example.test/callback'},
               'oauth_states': OrderedDict(), 'secure_cookies': False}
        with pytest.raises(web.HTTPFound) as start:
            await auth_start(request('/auth/discord', app=app))
        state = start.value.cookies['cwl_oauth_state'].value
        # Cookie mismatch cannot consume the matching server-side state.
        mismatch = request('/auth/callback?state=' + state, headers={'Cookie': 'cwl_oauth_state=wrong'}, app=app)
        with pytest.raises(web.HTTPForbidden):
            await auth_callback(mismatch)
        assert _hash(state) in app['oauth_states']
        callback = request('/auth/callback?state=' + state + '&error=access_denied',
                           headers={'Cookie': 'cwl_oauth_state=' + state}, app=app)
        with pytest.raises(web.HTTPUnauthorized):
            await auth_callback(callback)
        with pytest.raises(web.HTTPForbidden):
            await auth_callback(callback)
        app['oauth_states'][_hash(state)] = 0
        with pytest.raises(web.HTTPForbidden):
            await auth_callback(callback)
        assert not app['oauth_states']
    asyncio.run(check())


def test_actual_heartbeat_is_off_loop_and_cleanup_drains_it(tmp_path):
    from cwl_web import durability
    async def check():
        storage = Store(str(tmp_path / 'working.sqlite'))
        entered = threading.Event()
        threads = []
        class Owner:
            poisoned = False
            def heartbeat(self):
                threads.append(threading.get_ident())
                entered.set()
                time.sleep(.2)
        storage.durability = Owner()
        ticks = 0
        async def tick(delay):
            nonlocal ticks
            ticks += 1
            if ticks > 1:
                await asyncio.Future()
        fake_asyncio = NS(sleep=tick, create_task=asyncio.create_task,
                          CancelledError=asyncio.CancelledError)
        with patch.object(durability, 'asyncio', fake_asyncio):
            context = durability.lifecycle({'store': storage})
            await context.__anext__()
            assert await asyncio.to_thread(entered.wait, 1)
            started = time.monotonic()
            await asyncio.sleep(.01)
            assert time.monotonic() - started < .1
            await context.aclose()
        await storage.close_writer()
        assert len(threads) == 1
        assert threads[0] != threading.get_ident()
    asyncio.run(check())


def test_writer_lifecycle_closes_after_worker_cleanup(tmp_path):
    async def check():
        app = create_app(db_path=str(tmp_path / 'working.sqlite'), dev_fixture=True)
        order = []
        async def worker_lifecycle(app):
            yield
            await app['store'].run_tx(lambda db: order.append('last worker save'))
        app.cleanup_ctx.append(worker_lifecycle)
        client = TestClient(TestServer(app))
        await client.start_server()
        await client.close()
        assert order == ['last worker save']
        with pytest.raises(RuntimeError):
            await app['store'].run_writer(lambda: None)
    asyncio.run(check())


def test_callback_browser_rate_limit_remains_http_429(tmp_path):
    async def check():
        app = create_app(db_path=str(tmp_path / 'fixture.sqlite'), dev_fixture=True,
                         secure_cookies=False)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            headers = {'X-WU-Client-IP': '203.0.113.1', 'Accept': 'text/html'}
            for _ in range(20):
                response = await client.get(API + '/auth/callback', headers=headers, allow_redirects=False)
                assert response.status == 302
                await response.read()
            response = await client.get(API + '/auth/callback', headers=headers, allow_redirects=False)
            assert response.status == 429
            assert (await response.json())['error'] == 'Too many sign-in requests. Try again shortly.'
            assert response.headers['Cache-Control'] == 'no-store'
        finally:
            await client.close()
    asyncio.run(check())
