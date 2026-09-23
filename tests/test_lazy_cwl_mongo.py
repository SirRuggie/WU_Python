"""Real MongoDB contract/concurrency tests in disposable wubot_test collections.

Opt in with LAZYCWL_TEST_MONGODB_URI. The database name is hardcoded to
wubot_test and each test drops only its own randomly named collection.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import OperationFailure

from utils import lazy_cwl_store as store
from utils.lazy_cwl_schema import apply_schema, audit_collection
from utils.mongo import LAZYCWL_WRITE_CONCERN

pytestmark = pytest.mark.skipif(not os.getenv('LAZYCWL_TEST_MONGODB_URI'), reason='isolated MongoDB URI not configured')


@asynccontextmanager
async def sandbox():
    client = AsyncMongoClient(os.environ['LAZYCWL_TEST_MONGODB_URI'], serverSelectionTimeoutMS=10000)
    db = client.get_database('wubot_test')
    name = 'lazycwl_contract_' + uuid4().hex
    collection = await db.create_collection(name)
    collection = collection.with_options(write_concern=LAZYCWL_WRITE_CONCERN)
    mongo = SimpleNamespace(lazy_cwl_lists=collection)
    try:
        await store.ensure_indexes(mongo)
        yield mongo, collection
    finally:
        await db.drop_collection(name)
        await client.close()


def player(tag='#P1'):
    return {'tag': tag, 'name': 'Player', 'town_hall': 16, 'discord_id': 123456789012345678}


async def save(mongo, tag='#ABC'):
    return await store.save_list(mongo, clan_tag=tag, clan_name='Clan', players=[player()], saved_by=123456789012345678)


def test_backfill_and_validation_are_idempotent_and_preserve_data():
    async def scenario():
        async with sandbox() as (mongo, collection):
            document = await save(mongo)
            await collection.update_one({'_id': document['_id']}, {'$unset': {'schema_version': ''}})
            before = await collection.find_one({})
            report = await apply_schema(collection)
            assert report['validator_matches'] and report['validation_action'] == 'error'
            assert report['validation_level'] == 'strict'
            after = await collection.find_one({})
            assert after == {**before, 'schema_version': 1}
            assert await apply_schema(collection) == report
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'purge_at': 'not a date'},
    {'status': 'unexpected'},
    {'schema_version': 2},
    {'schema_version': None},
    {'players.0.discord_id': '1234'},
    {'reminders.enabled': True},
    {'players.0.tag': 'lowercase'},
])
def test_database_rejects_invalid_writes(change):
    async def scenario():
        async with sandbox() as (mongo, collection):
            document = await save(mongo)
            await apply_schema(collection)
            before = await collection.find_one({})
            with pytest.raises(OperationFailure) as error:
                await collection.update_one({'_id': document['_id']}, {'$set': change})
            assert error.value.code == 121
            assert await collection.find_one({}) == before
    asyncio.run(scenario())


def test_duplicate_players_are_rejected_even_outside_application_code():
    async def scenario():
        async with sandbox() as (mongo, collection):
            document = await save(mongo)
            await apply_schema(collection)
            duplicate = {**document['players'][0], 'name': 'Different name'}
            with pytest.raises(OperationFailure) as error:
                await collection.update_one({'_id': document['_id']}, {'$push': {'players': duplicate}})
            assert error.value.code == 121
    asyncio.run(scenario())


def test_concurrent_capture_and_add_have_one_winner():
    async def scenario():
        async with sandbox() as (mongo, collection):
            await apply_schema(collection)
            captures = await asyncio.gather(*(save(mongo) for _ in range(8)), return_exceptions=True)
            assert sum(isinstance(result, dict) for result in captures) == 1
            assert all(isinstance(result, (dict, store.AlreadySavedError)) for result in captures)
            doc = await collection.find_one({})
            additions = await asyncio.gather(*(store.add_player(mongo, '#ABC', player('#P2'), expected_list_id=doc['_id']) for _ in range(8)), return_exceptions=True)
            assert sum(isinstance(result, dict) for result in additions) == 1
            assert all(isinstance(result, (dict, store.PlayerAlreadyListedError)) for result in additions)
            assert len((await collection.find_one({}))['players']) == 2
    asyncio.run(scenario())


def test_finished_roster_cannot_mutate_replacement_and_unique_index_allows_history():
    async def scenario():
        async with sandbox() as (mongo, collection):
            await apply_schema(collection)
            old = await save(mongo)
            await store.finish(mongo, '#ABC', expected_list_id=old['_id'])
            replacement = await save(mongo)
            before = await collection.find_one({'_id': replacement['_id']})
            assert await store.set_reminders(mongo, '#ABC', enabled=True, every_minutes=60, expected_list_id=old['_id']) is None
            with pytest.raises(store.StaleListError):
                await store.remove_players(mongo, '#ABC', ['#P1'], expected_list_id=old['_id'])
            assert await collection.find_one({'_id': replacement['_id']}) == before
            assert await collection.count_documents({}) == 2
    asyncio.run(scenario())


def test_invalid_existing_data_prevents_schema_change_without_rewriting_data():
    async def scenario():
        async with sandbox() as (mongo, collection):
            doc = await save(mongo)
            await collection.update_one({'_id': doc['_id']}, {'$set': {'schema_version': 2}})
            before = await collection.find_one({})
            assert (await audit_collection(collection))['invalid_after_version_backfill'] == 1
            with pytest.raises(RuntimeError, match='nothing was changed'):
                await apply_schema(collection)
            assert await collection.find_one({}) == before
            assert not (await collection.options()).get('validator')
    asyncio.run(scenario())


def test_overdue_import_repair_obeys_schema_and_frees_active_roster_slot():
    async def scenario():
        async with sandbox() as (mongo, collection):
            old = await store.save_list(mongo, clan_tag='#ABC', clan_name='Clan', players=[player()], saved_by=1,
                                        now=datetime(2026, 9, 1, tzinfo=timezone.utc))
            bad_expiry = datetime(2026, 10, 16, tzinfo=timezone.utc)
            await collection.update_one({'_id': old['_id']}, {'$set': {
                'legacy_snapshot_id': 'old-source', 'expires_at': bad_expiry,
                'purge_at': bad_expiry + store.PURGE_RETENTION,
            }})
            await apply_schema(collection)
            original_players = (await collection.find_one({'_id': old['_id']}))['players']
            today = datetime(2026, 9, 23, tzinfo=timezone.utc)
            assert await store.repair_imported_expiry(mongo, today) == 1
            assert await store.get_active(mongo, '#ABC') is None
            assert await store.repair_imported_expiry(mongo, today) == 0
            replacement = await save(mongo)
            assert replacement['_id'] != old['_id']
            assert (await collection.find_one({'_id': old['_id']}))['players'] == original_players
            assert await collection.count_documents({}) == 2
            assert await collection.count_documents({'status': 'active'}) == 1
            assert (await collection.find_one({'_id': old['_id']}))['status'] == 'expired'
    asyncio.run(scenario())
