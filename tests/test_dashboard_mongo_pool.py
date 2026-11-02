"""Shared HTTP pool contracts; fake adapters only, no production connection."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from cwl_web import manage_bridge, mongo_client, providers, server_management, todo


def test_all_async_http_paths_share_startup_pool_and_cleanup_once():
    async def run():
        client = NS(
            close=AsyncMock(),
            bot_config=object(),
            cwl_reminder=object(),
            cwl_pending_reminders=object(),
        )
        provider = providers.LiveProviders(
            mongo_uri="mongodb://fixture.invalid", routes={}
        )
        app = {"providers": provider}
        request = NS(app=app)
        factory = Mock(return_value=client)
        directory = NS(
            find=Mock(
                return_value=NS(
                    to_list=AsyncMock(
                        return_value=[
                            {"tag": "#P2Y", "name": "Fixture clan", "type": "FWA"}
                        ]
                    )
                )
            )
        )
        history = AsyncMock(return_value={})
        outcomes = AsyncMock(return_value={})
        budgets = []

        def budget(seconds):
            budgets.append(seconds)
            return nullcontext()

        with patch.object(mongo_client, "MongoClient", factory), patch.object(
            providers, "AsyncMongoClient", side_effect=AssertionError("Per-call pool")
        ), patch.object(
            providers, "collection_for", return_value=directory
        ), patch.object(
            todo.clan_history, "load_candidates", history
        ), patch(
            "utils.todo_fwa.load_fwa_records", outcomes
        ), patch.object(
            manage_bridge,
            "collection_for",
            side_effect=lambda c, name, **kw: getattr(c, name),
        ), patch.object(
            todo, "timeout", budget
        ), patch.object(
            providers, "timeout", budget
        ), patch.object(
            manage_bridge, "timeout", budget
        ), patch.object(
            server_management, "timeout", budget
        ):
            lifetime = mongo_client.lifecycle(app)
            await anext(lifetime)
            factory.assert_called_once()
            assert factory.call_args.kwargs["maxPoolSize"] == 20
            assert factory.call_args.kwargs["appName"] == "wu-dashboard-http"
            assert factory.call_args.kwargs["timeoutMS"] == 15000
            await asyncio.gather(*(provider.family_clans() for _ in range(4)))
            await todo.load_recent_clans(app, ["#P2Y"])
            await todo._fwa_outcomes(app, [NS(clan_tag="#P2Y", ends_at=1)])
            async with server_management.mongo(request) as shared:
                assert shared is client
            async with manage_bridge._mongo(request) as facade:
                assert facade.bot_config is client.bot_config
            assert history.await_args.args[0] is client
            assert outcomes.await_args.args[0] is client
            factory.assert_called_once()
            client.close.assert_not_awaited()
            assert budgets.count(5) == 6
            assert budgets.count(10) == 1 and budgets.count(15) == 1
            try:
                await anext(lifetime)
            except StopAsyncIteration:
                pass
            client.close.assert_awaited_once()
            assert app["dashboard_mongo"] is None

    asyncio.run(run())


def test_fixture_startup_never_uses_ambient_mongo_credentials():
    async def run():
        with patch.dict(
            "os.environ", {"MONGODB_URI": "mongodb://not-a-fixture"}
        ), patch.object(
            mongo_client, "MongoClient", side_effect=AssertionError("Ambient client")
        ):
            lifetime = mongo_client.lifecycle({"dev_fixture": True, "providers": NS()})
            await anext(lifetime)
            try:
                await anext(lifetime)
            except StopAsyncIteration:
                pass

    asyncio.run(run())


def test_standalone_provider_reuses_and_explicitly_closes_its_own_pool():
    async def run():
        client = NS(close=AsyncMock())
        directory = NS(
            find=Mock(
                return_value=NS(
                    to_list=AsyncMock(
                        return_value=[{"tag": "#P2Y", "name": "Fixture", "type": "FWA"}]
                    )
                )
            )
        )
        with patch.object(
            providers, "AsyncMongoClient", return_value=client
        ) as factory, patch.object(providers, "collection_for", return_value=directory):
            provider = providers.LiveProviders(
                mongo_uri="mongodb://fixture.invalid", routes={}
            )
            await provider.family_clans()
            await provider.family_clans()
            factory.assert_called_once()
            client.close.assert_not_awaited()
            await provider.close()
            await provider.close()
            client.close.assert_awaited_once()

    asyncio.run(run())
