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
