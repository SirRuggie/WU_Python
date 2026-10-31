"""Routing regression tests use disconnected clients; no production credentials."""
import asyncio
import json
from pathlib import Path

import pytest
from pymongo import MongoClient as SyncClient

from utils.mongo import MongoClient
from utils.mongo_routes import DEFAULT_ROUTES, RoutedCollections, collection_for, load_routes
from extensions.commands.tickets.testing_service import TestTicketMongo as SandboxMongo

URI = "mongodb://127.0.0.1:1/ignored_uri_database"
CLANS = {"clans": {"database": "warriors_united", "collection": "clans"}}


@pytest.fixture(autouse=True)
def clean_routes(monkeypatch):
    monkeypatch.delenv("MONGODB_ROUTES", raising=False)


def test_defaults_cover_live_inventory_without_changing_names():
    inventory = json.loads((Path(__file__).parents[1] / "docs/mongodb-inventory-2026-09-26.json").read_text())
    expected = {c["name"] for db in inventory["databases"] if db["name"] == "settings" for c in db["collections"]}
    # Strike storage was introduced after the September inventory snapshot.
    expected |= {'strike_records', 'strike_settings', 'strike_leaves',
                 'strike_leave_history', 'strike_profiles', 'strike_imports',
                 'strike_tracking', 'strike_war_snapshots', 'cwl_dashboard_state',
                 'member_events', 'member_event_test_audit', 'fwa_war_plans'}
    routes = load_routes({})
    assert {n.collection for n in routes.values()} == expected
    assert {n.database for n in routes.values()} == {"settings"}


def test_async_bot_and_sync_tools_agree_for_every_alias_and_override(monkeypatch):
    monkeypatch.setenv("MONGODB_ROUTES", json.dumps(CLANS))
    async def check():
        client = MongoClient(URI, connect=False)
        try:
            with SyncClient(URI, connect=False) as sync:
                facade = RoutedCollections(sync)
                for alias in DEFAULT_ROUTES:
                    assert getattr(client, alias).full_name == facade[alias].full_name
                assert client.clans.full_name == "warriors_united.clans"
                assert client.tickets.full_name == "settings.tickets"
                assert client.discord_polls.full_name == "settings.wu_discord_polls"
                assert client.lazy_cwl_lists.write_concern.document == {"w": "majority", "wtimeout": 10000}
                assert facade.lazy_cwl_lists.write_concern == client.lazy_cwl_lists.write_concern
        finally:
            await client.close()
    asyncio.run(check())


def test_all_proposed_names_can_be_resolved_without_writing():
    proposal = json.loads((Path(__file__).parents[1] / "docs/mongodb-naming-map-2026-09-26.json").read_text())
    aliases = {n.collection: alias for alias, n in DEFAULT_ROUTES.items()}
    overrides = {
        aliases[r["source_collection"]]: {"database": r["proposed_database"], "collection": r["proposed_collection"]}
        for r in proposal["collections"]
    }
    with SyncClient(URI, connect=False) as client:
        facade = RoutedCollections(client, overrides=overrides)
        assert facade.clans.full_name == "warriors_united.clans"
        assert facade.ticket_setup.full_name == "warriors_united.ticket_config"
        assert facade.legacy_fwa_sync_alerts.full_name == "warriors_united.legacy_fwa_sync_alerts"


def test_test_scope_never_inherits_production_overrides(monkeypatch):
    monkeypatch.setenv("MONGODB_ROUTES", json.dumps({
        "tickets": {"database": "warriors_united", "collection": "tickets"},
        "ticket_rollout": {"database": "warriors_united", "collection": "ticket_counters"},
    }))
    async def check():
        client = MongoClient(URI, connect=False)
        try:
            sandbox = SandboxMongo(client)
            for alias in sandbox._collections:
                assert getattr(sandbox, alias).full_name == "ticket_testing." + alias
            assert client.ticket_rollout.full_name == "warriors_united.ticket_counters"
            with pytest.raises(AttributeError):
                sandbox.clans
        finally:
            await client.close()
    asyncio.run(check())


@pytest.mark.parametrize("database", [
    "ticket_testing", "wubot_test", "warriors_united_test", "warriors_united_sandbox",
    "admin", "local", "config", "database", "test", "other_testing",
    "", "Settings", "some.db", "a" * 39,
])
def test_rejects_reserved_or_invalid_database(database):
    with pytest.raises(ValueError):
        load_routes({"clans": {"database": database, "collection": "clans"}})


@pytest.mark.parametrize("overrides", [
    [], None, {"unknown": {"database": "warriors_united", "collection": "clans"}},
    {"clans": {}}, {"clans": {"database": "warriors_united"}},
    {"clans": {"database": "warriors_united", "collection": "clans", "extra": True}},
    {"clans": {"database": "warriors_united", "collection": "system.users"}},
    {"clans": {"database": "warriors_united", "collection": "a" * 95}},
    {"clans": {"database": "settings", "collection": "tickets"}},
])
def test_invalid_configuration_fails_before_client_construction(monkeypatch, overrides):
    monkeypatch.setenv("MONGODB_ROUTES", json.dumps(overrides))
    from pymongo import AsyncMongoClient
    def unexpected(*args, **kwargs):
        pytest.fail("client constructor should not be reached")
    monkeypatch.setattr(AsyncMongoClient, "__init__", unexpected)
    with pytest.raises(ValueError):
        MongoClient(URI, connect=False)


@pytest.mark.parametrize("raw", [
    "{broken", '{"clans": {}, "clans": {}}',
    '{"clans": {"database":"settings", "database":"ticket_testing", "collection":"clans"}}',
])
def test_invalid_json_and_duplicate_keys_rejected(monkeypatch, raw):
    monkeypatch.setenv("MONGODB_ROUTES", raw)
    with pytest.raises(ValueError):
        load_routes()


def test_unknown_tool_alias_has_no_implicit_collection_fallback():
    with SyncClient(URI, connect=False) as client:
        facade = RoutedCollections(client, overrides=CLANS)
        with pytest.raises(AttributeError):
            facade.clan_data
        with pytest.raises(KeyError):
            facade["typo"]
        with pytest.raises(TypeError):
            facade._routes["clans"] = DEFAULT_ROUTES["clans"]


def test_existing_clients_keep_routes_when_environment_changes(monkeypatch):
    async def check():
        client = MongoClient(URI, route_overrides={
            "legacy_fwa_sync_alerts": {"database": "warriors_united", "collection": "legacy_fwa_sync_alerts"},
        }, connect=False)
        try:
            monkeypatch.setenv("MONGODB_ROUTES", json.dumps(CLANS))
            assert collection_for(client, "legacy_fwa_sync_alerts").full_name == "warriors_united.legacy_fwa_sync_alerts"
            assert client.clans.full_name == "settings.clan_data"
        finally:
            await client.close()
    asyncio.run(check())


def test_override_resolves_destination_without_querying_source():
    class Client:
        def get_database(self, name):
            assert name == "warriors_united"
            return self
        def get_collection(self, name, **kwargs):
            assert name == "clans"
            return ("destination", name)
    assert collection_for(Client(), "clans", routes=load_routes(CLANS)) == ("destination", "clans")

def test_band_legacy_reader_uses_client_route_snapshot():
    from extensions.tasks.band_sync_ical import _legacy_alerts
    async def check():
        client = MongoClient(URI, route_overrides={
            "legacy_fwa_sync_alerts": {"database": "warriors_united", "collection": "legacy_fwa_sync_alerts"},
        }, connect=False)
        try:
            assert _legacy_alerts(client).full_name == "warriors_united.legacy_fwa_sync_alerts"
        finally:
            await client.close()
    asyncio.run(check())
