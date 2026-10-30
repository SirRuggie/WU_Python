"""Standalone Tasks review fixture. No real API, Mongo, or shared SQLite access.

WU_FIXTURE_BACKEND=<checkout> python tasks_official.py <built-dist> <port>
Open /qa/login (fixture session), then /tasks. Optional ?scenario=unavailable
on /qa/login changes the war section to an explicit unavailable sample.
The port is assigned by the review coordinator; this script does not auto-start.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ['WU_FIXTURE_BACKEND'])
sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_network_guard  # noqa: E402,F401
from aiohttp import web  # noqa: E402
from cwl_web import create_app  # noqa: E402
from cwl_web.app import dev_login  # noqa: E402


def create_fixture_app(static, database):
    scenario = {'value': 'normal'}
    @web.middleware
    async def sample_state(request, handler):
        response = await handler(request)
        if (request.path == '/api/cwl/todo' and response.status == 200
                and scenario['value'] == 'unavailable'):
            payload = json.loads(response.text)
            snapshot = payload.get('snapshot') if 'snapshot' in payload else payload
            if not isinstance(snapshot, dict) or 'views' not in snapshot:
                return response
            snapshot['views']['war'] = {
                'ok': False, 'note': 'War could not be checked (fixture timeout)',
                'notes': ['War could not be checked (fixture timeout)'],
                'unavailable': 'War could not be checked (fixture timeout)',
                'incomplete': 'Fixture upstream unavailable', 'rows': [],
            }
            return web.json_response(payload, headers={'Cache-Control': 'no-store'})
        return response
    app = create_app(db_path=str(database),
                     dev_fixture=True, secure_cookies=False, static_dir=static)
    app.middlewares.insert(0, sample_state)
    async def login(request):
        choice = request.query.get('scenario', 'normal')
        if choice not in ('normal', 'unavailable'):
            raise web.HTTPBadRequest(text='Choose normal or unavailable')
        scenario['value'] = choice
        app['todo_cache'].clear()
        authenticated = await dev_login(request)
        response = web.HTTPFound('/tasks')
        response.cookies.update(authenticated.cookies)
        return response
    app.router.add_get('/qa/login', login)
    return app


async def serve(static, port):
    if not 8900 <= port <= 8999:
        raise ValueError('Use an assigned isolated preview port in 8900–8999')
    with tempfile.TemporaryDirectory(prefix='wu-tasks-official-fixture-') as folder:
        app = create_fixture_app(static, Path(folder) / 'fixture.sqlite')
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            await web.TCPSite(runner, '127.0.0.1', port).start()
            print(json.dumps({'ready': True, 'url': f'http://127.0.0.1:{port}/qa/login',
                              'database': 'temporary fixture only',
                              'scenarios': ['normal', 'unavailable']}), flush=True)
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('static', type=Path)
    parser.add_argument('port', type=int)
    args = parser.parse_args()
    asyncio.run(serve(args.static.resolve(), args.port))
