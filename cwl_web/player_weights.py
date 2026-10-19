"""Permanent manual player weights: transactional local outbox and Mongo history."""
import asyncio
import contextlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from pymongo.write_concern import WriteConcern

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_weight_events (
 id TEXT PRIMARY KEY, tag TEXT NOT NULL, weight INTEGER, season_id INTEGER,
 actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS player_weight_events_tag ON player_weight_events(tag,recorded_at,id);
CREATE TABLE IF NOT EXISTS player_weights (
 tag TEXT PRIMARY KEY, weight INTEGER, initial_weight INTEGER, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_weight_migrations (id TEXT PRIMARY KEY);
CREATE TRIGGER IF NOT EXISTS inherit_player_weight AFTER INSERT ON signups
BEGIN
 INSERT OR IGNORE INTO roster_entries(season_id,tag,manual_weight)
 SELECT NEW.season_id,NEW.tag,weight FROM player_weights WHERE tag=NEW.tag AND weight IS NOT NULL;
END;
"""


def rebuild(db, tag):
    rows = db.execute('SELECT weight,recorded_at FROM player_weight_events WHERE tag=? ORDER BY recorded_at,id', (tag,)).fetchall()
    if not rows:
        return
    initial = next((r['weight'] for r in rows if r['weight'] is not None), None)
    db.execute('INSERT OR REPLACE INTO player_weights VALUES (?,?,?,?)', (tag, rows[-1]['weight'], initial, rows[-1]['recorded_at']))


def record(db, tag, weight, season_id, actor_id, *, event_id=None, recorded_at=None):
    db.execute('INSERT OR IGNORE INTO player_weight_events(id,tag,weight,season_id,actor_id,recorded_at) VALUES (?,?,?,?,?,?)',
               (event_id or str(uuid.uuid4()), tag, weight, season_id, str(actor_id), recorded_at or datetime.now(timezone.utc).isoformat()))
    rebuild(db, tag)


def migrate(db):
    if db.execute("SELECT 1 FROM player_weight_migrations WHERE id='legacy'").fetchone():
        return
    for row in db.execute("SELECT * FROM roster_audit WHERE action='manual_roster_edit' ORDER BY id").fetchall():
        before = json.loads(row['before_json'] or 'null') or {}
        after = json.loads(row['after_json'] or 'null') or {}
        if before.get('manual_weight') != after.get('manual_weight'):
            record(db, row['tag'], after.get('manual_weight'), row['season_id'], row['actor_id'],
                   event_id=f"legacy-audit:{row['id']:020d}", recorded_at=row['created_at'].replace(' ', 'T') + '+00:00')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(roster_entries)')}
    legacy = db.execute('SELECT * FROM roster_entries WHERE manual_weight IS NOT NULL ORDER BY season_id').fetchall() if 'manual_weight' in columns else []
    for row in legacy:
        if not db.execute('SELECT 1 FROM player_weights WHERE tag=?', (row['tag'],)).fetchone():
            record(db,row['tag'],row['manual_weight'],row['season_id'],'legacy',event_id=f"legacy-entry:{row['season_id']}:{row['tag']}")
    db.execute("INSERT INTO player_weight_migrations VALUES ('legacy')")


async def sync(app):
    from .server_management import mongo, GUILD_ID
    store = app['store']
    async with mongo(SimpleNamespace(app=app)) as shared:
        collection = shared.fwa_data.database.get_collection('player_manual_weight_history', write_concern=WriteConcern(w='majority', wtimeout=10000))
        for row in store.rows('SELECT * FROM player_weight_events WHERE synced=0 ORDER BY recorded_at,id'):
            document = {key:value for key,value in row.items() if key not in ('id','synced')}
            await collection.update_one({'_id':f"{GUILD_ID}:{row['id']}"}, {'$setOnInsert':{**document,'event_id':row['id'],'guild_id':GUILD_ID}},upsert=True)
            with store.tx() as db:
                db.execute('UPDATE player_weight_events SET synced=1 WHERE id=?',(row['id'],))
        # Also rebuild the local cache from Mongo after a host/database recovery.
        rows = await collection.find({'guild_id':GUILD_ID}).to_list(length=None)
        with store.tx() as db:
            tags = set()
            for row in rows:
                db.execute('INSERT OR IGNORE INTO player_weight_events VALUES (?,?,?,?,?,?,1)',
                           (row['event_id'],row['tag'],row['weight'],row.get('season_id'),row['actor_id'],row['recorded_at']))
                tags.add(row['tag'])
            for tag in tags:
                rebuild(db,tag)


async def lifecycle(app):
    async def worker():
        while True:
            try:
                await sync(app)
            except Exception:
                logging.getLogger(__name__).exception('Manual player weight Mongo sync failed; durable local queue retained')
            await asyncio.sleep(30)
    task = None
    if not app.get('dev_fixture') and os.getenv('MONGODB_URI'):
        task = asyncio.create_task(worker())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
