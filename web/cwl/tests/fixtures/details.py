"""Details-only extension of the 125-account loopback fixture; no external IO."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import player_cards as fixture
from aiohttp import web
import json
import asyncio

# All storage below belongs to player_cards' TemporaryDirectory.
with fixture.app['store'].tx() as db:
    db.execute("INSERT INTO clan_player_weights(tag,weight,revision,player_name,town_hall,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES(?,174000,1,'Clan managed',18,?,'Amber Knights','2026-10-27T13:10:00Z','fixture')", (fixture.players[7], fixture.clans[2]))
    db.execute("UPDATE signups SET player_name='Clan managed' WHERE tag=?", (fixture.players[7],))
    db.execute("UPDATE roster_entries SET manual_weight=NULL,source_weight=165000,source_status='current',source_name='Fixture import',source_checked_at='2026-10-27T14:10:00Z',source_modified_at='2026-10-27T13:10:00Z' WHERE tag=?", (fixture.players[8],))
    db.execute("UPDATE signups SET player_name='Imported weight' WHERE tag=?", (fixture.players[8],))
    for table in ('signups', 'roster_entries'):
        columns = [row['name'] for row in db.execute(f'PRAGMA table_info({table})')]
        selection = ','.join('2' if column == 'season_id' else column for column in columns)
        db.execute(f"INSERT INTO {table} ({','.join(columns)}) SELECT {selection} FROM {table} WHERE season_id=1")

@web.middleware
async def permissions(request, handler):
    response = await handler(request)
    if request.path.endswith('/staff-signup-members') and response.status == 200:
        payload = json.loads(response.text)
        for member in payload['options']:
            member.update(value=member['id'], label=member['display_name'], role_ids=[], role_names=[])
        payload.update(next=None, truncated=False)
        response = web.json_response(payload)
    if request.path.endswith('/auth/me') and response.status == 200:
        mode = fixture.mode.get('details_permissions', 'all')
        if mode != 'all':
            payload = json.loads(response.text)
            payload['is_owner'] = False
            payload['dashboard_permissions'] = ['cwl_signups'] if mode == 'signups' else ['cwl_publish']
            response = web.json_response(payload)
    return response

fixture.app.middlewares.insert(0, permissions)
asyncio.run(fixture.main())
