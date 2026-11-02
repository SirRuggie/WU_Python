"""Slow external work must not spend a later receipt's Mongo budget."""

import asyncio
from types import SimpleNamespace

from pymongo import _csot
from cwl_web import server_management
from cwl_web.mongo_operations import BudgetedCollection


class Cursor:
    def __init__(self, calls):
        self.calls = calls

    def sort(self, *args):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.calls.append(_csot.remaining())
        raise StopAsyncIteration

    async def to_list(self, length=None):
        self.calls.append(_csot.remaining())
        return [1]


class Collection:
    def __init__(self):
        self.calls = []

    async def find_one(self, query):
        self.calls.append(_csot.remaining())
        await asyncio.sleep(0)
        return {"ok": True}

    def find(self, query):
        return Cursor(self.calls)


def test_collection_and_cursor_reset_budget_after_external_wait():
    async def run():
        native = Collection()
        collection = BudgetedCollection(native, 0.01)
        await collection.find_one({})
        assert _csot.remaining() is None
        await asyncio.sleep(0.02)
        await collection.find_one({})
        cursor = collection.find({}).sort("x", 1)
        assert await cursor.to_list() == [1]
        async for _ in cursor:
            pass
        assert len(native.calls) == 4
        assert all(0 < value <= 0.01 for value in native.calls)
        assert _csot.remaining() is None

    asyncio.run(run())


def test_management_workflow_and_spawned_task_have_no_inherited_deadline():
    async def run():
        native = Collection()
        request = SimpleNamespace(app={"server_management_mongo": native})

        async def send_then_receipt(client):
            await asyncio.sleep(0.02)
            assert _csot.remaining() is None
            return await client.find_one({})

        async with server_management.mongo(request) as client:
            assert _csot.remaining() is None
            task = asyncio.create_task(send_then_receipt(client))
            await asyncio.sleep(0.02)
            assert await client.find_one({}) == {"ok": True}
        assert await task == {"ok": True}
        assert native.calls == [None, None]

    asyncio.run(run())


def test_with_options_preserves_native_pool_and_fresh_operation_budget():
    from pymongo import AsyncMongoClient
    from pymongo.read_concern import ReadConcern

    client = AsyncMongoClient("mongodb://127.0.0.1:27160", connect=False)
    native = client.fixture.rows
    wrapped = BudgetedCollection(native, 0.01).with_options(
        read_concern=ReadConcern("majority")
    )
    assert isinstance(wrapped, BudgetedCollection)
    assert wrapped.collection.database.client is client
    assert wrapped.collection.read_concern.level == "majority"
    assert wrapped.seconds == 0.01
    assert _csot.remaining() is None


def test_cursor_context_does_not_hold_deadline_during_external_work():
    from cwl_web.mongo_operations import BudgetedCursor

    class ContextCursor(Cursor):
        async def __aenter__(self):
            self.calls.append(_csot.remaining())
            return self

        async def __aexit__(self, *args):
            self.calls.append(_csot.remaining())
            return False

    async def run():
        native = ContextCursor([])
        async with BudgetedCursor(native, 0.01) as cursor:
            assert _csot.remaining() is None
            await asyncio.sleep(0.02)
            assert await cursor.to_list() == [1]
            assert _csot.remaining() is None
        assert len(native.calls) == 3
        assert all(0 < value <= 0.01 for value in native.calls)
        assert _csot.remaining() is None

    asyncio.run(run())


def test_configured_collection_calls_still_receive_new_budget_after_wait():
    class Configurable(Collection):
        def with_options(self, **kwargs):
            configured=Configurable()
            configured.calls=self.calls
            return configured
    async def run():
        native=Configurable()
        configured=BudgetedCollection(native,.01).with_options(option='fixture')
        await asyncio.sleep(.02)
        assert await configured.find_one({})=={'ok':True}
        assert len(native.calls)==1 and 0<native.calls[0]<=.01
        assert _csot.remaining() is None
    asyncio.run(run())


def test_owned_native_cursor_context_and_options_keep_pool_and_reset_budget():
    import os
    from uuid import uuid4
    import pytest
    from pymongo import AsyncMongoClient
    from pymongo.read_concern import ReadConcern
    uri=os.environ.get('WU_CURSOR_TEST_MONGO_URI')
    if not uri:pytest.skip('Owned cursor Mongo not supplied')
    assert uri=='mongodb://127.0.0.1:27161'
    async def run():
        client=AsyncMongoClient(uri,serverSelectionTimeoutMS=2000)
        name='wu_cursor_'+uuid4().hex[:16]
        try:
            native=client[name].rows
            await native.insert_one({'value':'fixture'})
            wrapped=BudgetedCollection(native,1).with_options(read_concern=ReadConcern('local'))
            assert wrapped.collection.database.client is client
            async with wrapped.find({}, {'_id':0}) as cursor:
                assert _csot.remaining() is None
                await asyncio.sleep(1.1)
                assert await cursor.to_list()==[{'value':'fixture'}]
                assert _csot.remaining() is None
            assert _csot.remaining() is None
        finally:
            await client.drop_database(name)
            await client.close()
    asyncio.run(run())
