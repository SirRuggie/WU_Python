"""Collection selection and defaults are centralized; disconnected clients only."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern
from utils.mongo_routes import (
    DEFAULT_ROUTES, PARENT_ALIASES, collection_for, collection_from,
    load_routes, ticket_test_collection,
)

ROOT = Path(__file__).parents[1]


def tracked_sources():
    return [ROOT / name for name in subprocess.check_output(
        ['git', 'ls-files', '-z', '--', 'utils/*.py', 'cwl_web/*.py', 'extensions/**/*.py'],
        cwd=ROOT, text=True).split('\0') if name]


def test_get_collection_only_exists_in_route_owner():
    violations = []
    for path in tracked_sources():
        if path == ROOT / 'utils/mongo_routes.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get_collection':
                violations.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    assert violations == []


@pytest.mark.parametrize('alias,parent', sorted(PARENT_ALIASES.items()))
def test_child_preserves_defaults_parent_database_override_and_explicit_override(alias, parent):
    with MongoClient('mongodb://127.0.0.1:1', connect=False) as client:
        routes = load_routes({parent: {'database': 'configured_parent', 'collection': 'parent_renamed'}})
        client._wu_collection_routes = routes
        parent_collection = collection_for(client, parent)
        result = collection_from(parent_collection, alias, write_concern=WriteConcern(w='majority', j=True))
        assert result.full_name == 'configured_parent.' + alias
        assert result.write_concern.document == {'w': 'majority', 'j': True}
        assert DEFAULT_ROUTES[alias].database == 'settings'
        assert DEFAULT_ROUTES[alias].collection == alias
        client._wu_collection_routes = load_routes({
            parent: {'database': 'configured_parent', 'collection': 'parent_renamed'},
            alias: {'database': 'explicit_child', 'collection': 'child_renamed'},
        })
        assert collection_from(collection_for(client, parent), alias).full_name == 'explicit_child.child_renamed'
        assert ticket_test_collection(client, 'tickets').full_name == 'ticket_testing.tickets'


def test_narrow_fixture_facades_keep_parent_database_and_write_options():
    database = NS(get_collection=Mock(return_value='fixture'))
    parent = NS(database=database)
    concern = WriteConcern(w='majority')
    assert collection_from(parent, 'war_reminder_status', write_concern=concern) == 'fixture'
    database.get_collection.assert_called_once_with('war_reminder_status', write_concern=concern)
    with pytest.raises(KeyError):
        collection_from(parent, 'arbitrary')
    with pytest.raises(KeyError):
        ticket_test_collection(NS(), 'arbitrary')


def test_equal_parent_handles_keep_distinct_facade_routes_on_same_sync_client():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from utils.mongo_routes import RoutedCollections
    barrier = threading.Barrier(2)
    def resolve(facade):
        parent = facade.bot_config
        barrier.wait(timeout=2)
        return parent, collection_from(parent, 'war_reminder_settings').full_name
    with MongoClient('mongodb://127.0.0.1:1', connect=False) as client:
        first = RoutedCollections(client, overrides={
            'bot_config': {'database': 'parent_db', 'collection': 'parent_config'},
            'war_reminder_settings': {'database': 'first_db', 'collection': 'first_settings'},
        })
        second = RoutedCollections(client, overrides={
            'bot_config': {'database': 'parent_db', 'collection': 'parent_config'},
            'war_reminder_settings': {'database': 'second_db', 'collection': 'second_settings'},
        })
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(resolve, first)
            b = pool.submit(resolve, second)
            parent_a, child_a = a.result()
            parent_b, child_b = b.result()
        assert parent_a == parent_b and hash(parent_a) == hash(parent_b)
        assert parent_a is not parent_b
        assert child_a == 'first_db.first_settings'
        assert child_b == 'second_db.second_settings'
        assert collection_from(parent_a, 'war_reminder_settings').full_name == child_a
        assert collection_from(parent_b, 'war_reminder_settings').full_name == child_b
        assert collection_from(first.bot_config, 'war_reminder_status').full_name == 'parent_db.war_reminder_status'


def test_equal_parent_handles_keep_distinct_facade_routes_on_same_async_client():
    import asyncio
    from pymongo import AsyncMongoClient
    from utils.mongo_routes import RoutedCollections
    async def check():
        client = AsyncMongoClient('mongodb://127.0.0.1:1', connect=False)
        try:
            first = RoutedCollections(client, overrides={
                'bot_config': {'database': 'parent_db', 'collection': 'parent_config'},
                'war_reminder_settings': {'database': 'first_db', 'collection': 'first_settings'},
            })
            second = RoutedCollections(client, overrides={
                'bot_config': {'database': 'parent_db', 'collection': 'parent_config'},
                'war_reminder_settings': {'database': 'second_db', 'collection': 'second_settings'},
            })
            async def resolve(facade):
                parent = facade.bot_config
                await asyncio.sleep(0)
                return parent, collection_from(parent, 'war_reminder_settings').full_name
            (parent_a, child_a), (parent_b, child_b) = await asyncio.gather(resolve(first), resolve(second))
            assert parent_a == parent_b and hash(parent_a) == hash(parent_b)
            assert parent_a is not parent_b
            assert child_a == 'first_db.first_settings'
            assert child_b == 'second_db.second_settings'
            assert collection_from(parent_a, 'war_reminder_settings').full_name == child_a
            assert collection_from(parent_b, 'war_reminder_settings').full_name == child_b
            assert collection_from(second.bot_config, 'war_reminder_status').full_name == 'parent_db.war_reminder_status'
        finally:
            await client.close()
    asyncio.run(check())
