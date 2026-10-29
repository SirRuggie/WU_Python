"""Loopback-only navigation identities using temporary data and fake providers."""
import importlib
import json
import os
import sys
from pathlib import Path

os.environ['PRANK_ENABLED'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tour_deadline as fixture  # noqa: E402
from aiohttp import web  # noqa: E402
from utils import dashboard_access  # noqa: E402

app = fixture.app
assert app['dev_fixture']
assert Path(app['store'].path).is_relative_to(fixture.folder.name)
identities = {
    'member': ('100000000000000001', []),
    'limited': ('100000000000000002', ['cwl_roster']),
    'multi': ('100000000000000003', ['cwl_roster', 'member_roles', 'tickets', 'clans', 'text_commands']),
    'owner': ('100000000000000004', []),
}
for module in (importlib.import_module('cwl_web.app'),
               importlib.import_module('cwl_web.access_control'), dashboard_access):
    module.OWNER_IDS = frozenset({identities['owner'][0]})
with app['store'].tx() as db:
    for role, (uid, permissions) in identities.items():
        db.execute('DELETE FROM grants WHERE user_id=?', (uid,))
        if permissions:
            db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES(?,?,?)',
                       (uid, identities['owner'][0], json.dumps(permissions)))


async def select_role(request):
    if request.remote not in ('127.0.0.1', '::1'):
        raise web.HTTPNotFound()
    role = request.query.get('role', 'member')
    if role not in identities:
        raise web.HTTPBadRequest(text='Unknown fixture role')
    app['dev_identity'] = {'id': identities[role][0], 'username': f'{role.title()} fixture',
                           'guild_owner': False}
    return web.json_response({'role': role, 'message': 'Open a fresh local test session.'})


app.router.add_get('/qa/nav-role', select_role)
if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=fixture.PORT)
