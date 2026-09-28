"""Warrior storage boundaries and restart-safe early-release migration."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace as S
from unittest.mock import AsyncMock

import pytest
from extensions.warrior import schema
from utils.mongo import MongoClient


class Source:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.delete_one = AsyncMock(return_value=S(deleted_count=1))

    def find(self, query):
        self.query = query

        async def iterate():
            for row in self.rows:
                yield deepcopy(row)

        return iterate()


class Target:
    name = "test"

    def __init__(self, document=None):
        self.document = document

    async def update_one(self, query, update, **kwargs):
        if self.document is None:
            self.document = deepcopy(update["$setOnInsert"])

    async def find_one(self, query):
        return deepcopy(self.document)


def test_namespaces_are_separate():
    client = MongoClient("mongodb://localhost", connect=False)
    names = [
        getattr(client, name).full_name
        for name in (
            "warrior_settings",
            "warrior_walkthroughs",
            "warrior_history",
            "warrior_audit",
        )
    ]
    assert len(set(names)) == 4
    assert all(
        name.startswith(client.ticket_setup.database.name + ".") for name in names
    )
    assert client.recruit_onboarding.full_name not in names
    asyncio.run(client.close())


def test_normalize_canonicalizes_without_mutating_source():
    original = {"guild_id": "10", "events": [{"at": datetime(2026, 9, 28)}]}
    result = schema.normalize(original)
    assert result["guild_id"] == 10
    assert result["schema_version"] == 1
    assert result["events"][0]["at"].tzinfo == timezone.utc
    assert original["events"][0]["at"].tzinfo is None
    with pytest.raises(ValueError):
        schema.normalize({"schema_version": 999})


@pytest.mark.parametrize("conflict", [False, True])
def test_migration_verifies_before_deleting_and_is_warrior_only(conflict):
    original = {"_id": "warrior_settings:10", "roles": {"family": 55}}
    source = Source([original])
    legacy = Source([])
    target = Target(
        {"_id": original["_id"], "roles": {"family": 66}} if conflict else None
    )
    mongo = S(
        ticket_setup=source,
        recruit_onboarding=legacy,
        warrior_settings=target,
        warrior_walkthroughs=Target(),
        warrior_history=Target(),
        warrior_audit=Target(),
    )
    if conflict:
        with pytest.raises(RuntimeError, match="source preserved"):
            asyncio.run(schema.migrate_early_records(mongo))
        source.delete_one.assert_not_awaited()
    else:
        asyncio.run(schema.migrate_early_records(mongo))
        assert target.document["roles"]["family"] == 55
        assert target.document["guild_id"] == 10
        source.delete_one.assert_awaited_once_with(original)
        # Simulate a restart after the copy, before the source deletion.
        asyncio.run(schema.migrate_early_records(mongo))
        assert source.delete_one.await_count == 2
    assert source.query["_id"]["$regex"].startswith("^warrior_settings:")
    legacy.delete_one.assert_not_awaited()
