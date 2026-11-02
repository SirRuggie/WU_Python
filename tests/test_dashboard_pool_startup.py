"""Production-shaped routes must reach the real client constructor at startup."""

import asyncio
import pytest
from cwl_web import mongo_client
from cwl_web.providers import LiveProviders
from utils.mongo_routes import load_routes


def test_default_live_provider_routes_start_and_close_actual_client_without_network(
    monkeypatch,
):
    monkeypatch.setenv("MONGODB_ROUTES", "{}")
    provider = LiveProviders(mongo_uri="mongodb://127.0.0.1:27160")
    app = {"providers": provider}

    async def run():
        context = mongo_client.lifecycle(app)
        await anext(context)
        try:
            client = app["dashboard_mongo"]
            assert client is not None
            assert client is mongo_client.get_client(app)
            assert client.options.pool_options.appname == "wu-dashboard-http"
            assert client.options.pool_options.max_pool_size == 20
            for alias, route in provider.routes.items():
                assert client._wu_collection_routes[alias] == route
        finally:
            await context.aclose()
        assert app["dashboard_mongo"] is None

    asyncio.run(run())


def test_explicit_normalized_routes_preserve_destinations_and_raw_routes_still_validate(
    monkeypatch,
):
    monkeypatch.setenv("MONGODB_ROUTES", "{}")
    override = {"clans": {"database": "startup_fixture", "collection": "custom_clans"}}

    async def run():
        for routes in (load_routes(override), override):
            provider = LiveProviders(
                mongo_uri="mongodb://127.0.0.1:27160", routes=routes
            )
            app = {"providers": provider}
            client = mongo_client.get_client(app)
            try:
                assert (
                    client._wu_collection_routes["clans"].database == "startup_fixture"
                )
                assert (
                    client._wu_collection_routes["clans"].collection == "custom_clans"
                )
            finally:
                await client.close()

    asyncio.run(run())


def test_invalid_route_settings_fail_before_native_client_construction(monkeypatch):
    from types import SimpleNamespace

    app = {
        "providers": SimpleNamespace(
            mongo_uri="mongodb://127.0.0.1:27160",
            routes={"clans": {"database": "admin", "collection": "invalid"}},
        )
    }
    with pytest.raises(ValueError):
        mongo_client.get_client(app)
    assert app.get("dashboard_mongo") is None


def test_owned_mongo_live_provider_reads_through_normalized_startup_pool():
    import os
    from uuid import uuid4

    uri = os.environ.get("WU_STARTUP_TEST_MONGO_URI")
    if not uri:
        pytest.skip("Owned startup Mongo not supplied")
    assert uri == "mongodb://127.0.0.1:27161"
    database = "wu_startup_" + uuid4().hex[:16]
    routes = load_routes(
        {"clans": {"database": database, "collection": "family_clans"}}
    )
    provider = LiveProviders(mongo_uri=uri, routes=routes)
    app = {"providers": provider}

    async def run():
        lifecycle = mongo_client.lifecycle(app)
        await anext(lifecycle)
        client = app["dashboard_mongo"]
        try:
            await client.admin.command("ping")
            await client.clans.insert_one(
                {"tag": "#C2Y", "name": "Owned fixture", "type": "FWA"}
            )
            clans = await provider.family_clans()
            assert (
                clans["status"] == "ok"
                and len(clans["clans"]) == 1
                and clans["clans"][0]["tag"] == "#C2Y"
            )
            assert mongo_client.get_client(app) is client
            assert provider._owned_mongo is None
        finally:
            await client.drop_database(database)
            await lifecycle.aclose()
        assert app["dashboard_mongo"] is None

    asyncio.run(run())
