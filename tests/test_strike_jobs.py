"""Bounded async strike import jobs: dedup, ownership, live authorization and cleanup."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
import pytest

from cwl_web import strikes


def test_jobs_coalesce_running_retries_but_refresh_completed_preview():
    async def run():
        app = {}
        gate = asyncio.Event()
        calls = 0
        async def work():
            nonlocal calls
            calls += 1
            await gate.wait()
            return {'ready': True}
        first = await strikes._start_job(app, 5, 'preview', '90', work)
        again = await strikes._start_job(app, 5, 'preview', '90', work)
        assert first['job_id'] == again['job_id']
        with pytest.raises(web.HTTPConflict):
            await strikes._start_job(app, 5, 'preview', '30', work)
        gate.set()
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert calls == 1
        fresh = await strikes._start_job(app, 5, 'preview', '90', work)
        assert fresh['job_id'] != first['job_id']
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert calls == 2
    asyncio.run(run())


def test_completed_apply_is_reused_and_other_actor_cannot_read_job():
    async def run():
        app = {}
        first = await strikes._start_job(app, 5, 'apply', 'same', lambda: asyncio.sleep(0, result={'applied': 1}))
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        second = await strikes._start_job(app, 5, 'apply', 'same', lambda: asyncio.sleep(0, result={'applied': 2}))
        assert first['job_id'] == second['job_id']
        async def permit(*_args, **_kwargs):
            return None
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch('cwl_web.app._session', return_value={'user_id': '5'}):
            response = await strikes.import_job(SimpleNamespace(method='GET', app=app,
                match_info={'job_id': first['job_id']}))
            assert json.loads(response.text)['result'] == {'applied': 1}
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch('cwl_web.app._session', return_value={'user_id': '6'}):
            with pytest.raises(web.HTTPNotFound):
                await strikes.import_job(SimpleNamespace(method='GET', app=app,
                    match_info={'job_id': first['job_id']}))
    asyncio.run(run())


def test_poll_rechecks_live_grant_and_worker_failure_is_terminal():
    async def run():
        app = {}
        async def broken():
            raise RuntimeError('history unavailable')
        row = await strikes._start_job(app, 5, 'preview', '90', broken)
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert row['status'] == 'failed'
        assert 'history unavailable' in row['error']
        async def deny(*_args, **_kwargs):
            raise web.HTTPForbidden(text='Grant removed')
        with patch.object(strikes.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await strikes.import_job(SimpleNamespace(method='GET', app=app,
                    match_info={'job_id': row['job_id']}))
    asyncio.run(run())


def test_lifecycle_cancels_pending_job_without_leaking_task():
    async def run():
        app = {}
        lifecycle = strikes.strike_jobs_lifecycle(app)
        await lifecycle.__anext__()
        async def waiting():
            await asyncio.Event().wait()
        row = await strikes._start_job(app, 5, 'preview', '90', waiting)
        await lifecycle.aclose()
        assert row['status'] == 'failed'
        assert not strikes._jobs(app)['tasks']
    asyncio.run(run())
