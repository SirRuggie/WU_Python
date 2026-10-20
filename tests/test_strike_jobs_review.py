"""Background import job lifecycle, ownership and retry regressions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
import pytest

from cwl_web import strikes


def test_running_preview_coalesces_then_completed_preview_refreshes():
    async def run():
        app = {}
        release = asyncio.Event()
        calls = []

        async def operation():
            calls.append(True)
            await release.wait()
            return {'preview_id': str(len(calls))}

        first = await strikes._start_job(app, 123, 'preview', '90', operation)
        again = await strikes._start_job(app, 123, 'preview', '90', operation)
        assert again['job_id'] == first['job_id']
        release.set()
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert first['status'] == 'complete'
        refreshed = await strikes._start_job(app, 123, 'preview', '90', operation)
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert refreshed['job_id'] != first['job_id']
        assert len(calls) == 2

    asyncio.run(run())


def test_completed_apply_reuses_job_for_same_selection():
    async def run():
        app = {}
        calls = []

        async def operation():
            calls.append(True)
            return {'applied': 1}

        first = await strikes._start_job(app, 123, 'apply', 'preview:row', operation)
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        again = await strikes._start_job(app, 123, 'apply', 'preview:row', operation)
        assert again['job_id'] == first['job_id']
        assert calls == [True]

    asyncio.run(run())


def test_poll_requires_owner_and_current_add_grant():
    async def run():
        app = {}
        async def operation():
            return {'preview_id': 'saved'}
        row = await strikes._start_job(app, 123, 'preview', '90', operation)
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        request = SimpleNamespace(method='GET', app=app,
                                  match_info={'job_id': row['job_id']})
        async def allow(request, section, *, write=False):
            assert section == 'strikes_add' and write is False
        with patch.object(strikes.shared, 'require_manage', allow), \
             patch('cwl_web.app._session', return_value={'user_id': '456'}):
            with pytest.raises(web.HTTPNotFound):
                await strikes.import_job(request)
        async def deny(request, section, *, write=False):
            raise web.HTTPForbidden(text='Grant revoked')
        with patch.object(strikes.shared, 'require_manage', deny), \
             patch('cwl_web.app._session', return_value={'user_id': '123'}):
            with pytest.raises(web.HTTPForbidden):
                await strikes.import_job(request)
        with patch.object(strikes.shared, 'require_manage', allow), \
             patch('cwl_web.app._session', return_value={'user_id': '123'}):
            response = await strikes.import_job(request)
        assert json.loads(response.text)['result'] == {'preview_id': 'saved'}

    asyncio.run(run())


def test_failed_job_can_retry_and_timeout_is_terminal():
    async def run():
        app = {}
        async def slow():
            await asyncio.sleep(0.05)
        with patch.object(strikes, 'JOB_TIMEOUT_SECONDS', 0.001):
            first = await strikes._start_job(app, 123, 'preview', '90', slow)
            await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert first['status'] == 'failed'
        assert 'too long' in first['error']
        async def recover():
            return {'preview_id': 'retry'}
        second = await strikes._start_job(app, 123, 'preview', '90', recover)
        await asyncio.gather(*strikes._jobs(app)['tasks'])
        assert second['job_id'] != first['job_id']
        assert second['status'] == 'complete'

    asyncio.run(run())
