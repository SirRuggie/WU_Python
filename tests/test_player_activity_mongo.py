"""Opt-in, isolated local Mongo verification. No default/live Mongo address."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import MongoClient, AsyncMongoClient

from utils.player_activity_store import PlayerActivityStore
from tools.maintenance.strike_retention import migrate

URI = os.getenv('WU_ACTIVITY_TEST_MONGO_URI')
RESTORE_URI = os.getenv('WU_ACTIVITY_RESTORE_MONGO_URI')
pytestmark = pytest.mark.skipif(not URI, reason='isolated activity Mongo URI not provided')


def local_uri():
    if URI != 'mongodb://127.0.0.1:27154':
        raise ValueError('Only the dedicated local activity fixture port is allowed')
    return URI


def test_real_backup_restore_ttl_and_purge_invariance(tmp_path):
    if RESTORE_URI != 'mongodb://127.0.0.1:27155':
        pytest.skip('Separate local restore Mongo27155 is required')
    now = datetime.now(timezone.utc)
    with MongoClient(local_uri()) as client, MongoClient(RESTORE_URI) as restore:
        name = 'wu_activity_fixture_' + uuid4().hex
        db = client[name]
        try:
            db.strike_records.insert_many([
                {'_id': 'old', 'kind': 'strike', 'occurred_at': now-timedelta(days=100), 'expires_at': now-timedelta(days=40)},
                {'_id': 'active', 'kind': 'strike', 'occurred_at': now, 'expires_at': now+timedelta(days=60)}])
            db.strike_profiles.insert_one({'_id': 'player', 'streak_count': 5, 'streak_last_war_key': 'saved',
                                           'replacement_listed': True, 'replacement_note': 'Keep'})
            db.strike_war_snapshots.insert_one({'_id': 'war', 'end_time': now, 'status': 'finalized'})
            routes = {key: SimpleNamespace(database=name, collection=key) for key in
                      ('strike_records', 'strike_profiles', 'strike_war_snapshots', 'player_activity')}
            profiles = list(db.strike_profiles.find({}))
            active = db.strike_records.count_documents({'expires_at': {'$gt': now}})
            result = migrate(client, routes, tmp_path/'backup', restore_client=restore, apply=True)
            assert result['restored'] and result['ttl_applied']
            db.strike_records.delete_many({'purge_after': {'$lte': now}})
            assert list(db.strike_profiles.find({})) == profiles
            assert db.strike_records.count_documents({'expires_at': {'$gt': now}}) == active
            assert db.strike_records.index_information()['retention_purge_after']['expireAfterSeconds']==0
            assert db.player_activity.index_information()['activity_departure_retention']['expireAfterSeconds']==90*86400
        finally:
            client.drop_database(name)


def test_real_concurrent_record_seed_and_bounded_documents():
    async def run():
        client = AsyncMongoClient(local_uri())
        name = 'wu_activity_fixture_' + uuid4().hex
        store = PlayerActivityStore(SimpleNamespace(player_activity=client[name].player_activity))
        now = datetime.now(timezone.utc)
        try:
            await store.record({'tag': '#PC9YGL0JL', 'attackWins': 1}, '#2UVGQU9', now=now)
            await asyncio.gather(store.seed('#PC9YGL0JL', now-timedelta(days=2), now=now),
                                 store.record({'tag': '#PC9YGL0JL', 'attackWins': 2}, '#2UVGQU9', now=now+timedelta(seconds=1)))
            row = await store.get('#PC9YGL0JL')
            assert row['last_seen_source']=='clash_api'
            assert await client[name].player_activity.count_documents({}) == 1
        finally:
            await client.drop_database(name)
            await client.close()
    asyncio.run(run())


def test_unresolved_survives_real_ttl_and_restore_is_separate(tmp_path):
    import time
    from tools.maintenance.strike_retention import restore_backup
    if RESTORE_URI != 'mongodb://127.0.0.1:27155':
        pytest.skip('Separate restore Mongo required')
    now = datetime.now(timezone.utc)
    with MongoClient(local_uri()) as source, MongoClient(RESTORE_URI) as restore:
        name = 'wu_activity_fixture_'+uuid4().hex
        db = source[name]
        recovery = None
        try:
            db.strike_records.insert_one({'_id': 'record', 'occurred_at': now})
            db.strike_profiles.insert_one({'_id': 'profile', 'streak_count': 7})
            db.strike_war_snapshots.insert_many([
                {'_id': 'deferred', 'status': 'observing', 'end_time': now-timedelta(days=45), 'purge_after': now-timedelta(days=15)},
                {'_id': 'final', 'status': 'finalized', 'end_time': now-timedelta(days=45)},
                {'_id': 'incomplete', 'status': 'incomplete', 'end_time': now-timedelta(days=45)}])
            routes = {key: SimpleNamespace(database=name, collection=key) for key in
                      ('strike_records', 'strike_profiles', 'strike_war_snapshots', 'player_activity')}
            before = list(db.strike_war_snapshots.find({}))
            databases = set(source.list_database_names())
            dry = migrate(source, routes, tmp_path/'dry', restore_client=restore)
            assert dry['unresolved_snapshots_over_30_days'] == 1
            assert list(db.strike_war_snapshots.find({})) == before
            assert set(source.list_database_names()) == databases
            result = migrate(source, routes, tmp_path/'apply', restore_client=restore, apply=True)
            assert result['ttl_applied']
            deadline = time.monotonic()+12
            while db.strike_war_snapshots.find_one({'_id': 'final'}) and time.monotonic()<deadline:
                time.sleep(.2)
            assert db.strike_war_snapshots.find_one({'_id': 'final'}) is None
            assert 'purge_after' not in db.strike_war_snapshots.find_one({'_id': 'deferred'})
            assert db.strike_war_snapshots.find_one({'_id': 'incomplete'}) is not None
            recovery = restore_backup(tmp_path/'apply', restore)
            assert restore[recovery].strike_war_snapshots.count_documents({}) == 3
            assert recovery not in source.list_database_names()
        finally:
            source.drop_database(name)
            if recovery:
                restore.drop_database(recovery)
