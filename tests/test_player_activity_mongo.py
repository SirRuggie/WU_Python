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
pytestmark = pytest.mark.skipif(not URI, reason='isolated activity Mongo URI not provided')


def local_uri():
    if URI != 'mongodb://127.0.0.1:27154':
        raise ValueError('Only the dedicated local activity fixture port is allowed')
    return URI


def test_real_backup_restore_ttl_and_purge_invariance(tmp_path):
    now = datetime.now(timezone.utc)
    with MongoClient(local_uri()) as client:
        name = 'wu_activity_fixture_' + uuid4().hex
        db = client[name]
        try:
            db.strike_records.insert_many([
                {'_id': 'old', 'kind': 'strike', 'occurred_at': now-timedelta(days=100), 'expires_at': now-timedelta(days=40)},
                {'_id': 'active', 'kind': 'strike', 'occurred_at': now, 'expires_at': now+timedelta(days=60)}])
            db.strike_profiles.insert_one({'_id': 'player', 'streak_count': 5, 'streak_last_war_key': 'saved',
                                           'replacement_listed': True, 'replacement_note': 'Keep'})
            db.strike_war_snapshots.insert_one({'_id': 'war', 'end_time': now})
            routes = {key: SimpleNamespace(database=name, collection=key) for key in
                      ('strike_records', 'strike_profiles', 'strike_war_snapshots', 'player_activity')}
            profiles = list(db.strike_profiles.find({}))
            active = db.strike_records.count_documents({'expires_at': {'$gt': now}})
            result = migrate(client, routes, tmp_path/'backup', apply=True)
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
