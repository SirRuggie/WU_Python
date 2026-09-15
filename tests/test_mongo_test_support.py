import asyncio

import pytest

from tests import mongo_test_support as support


def test_test_mongodb_uri_requires_the_explicit_test_database(monkeypatch):
    monkeypatch.setenv("TICKET_TEST_MONGODB_URI", "mongodb://example.test/wubot_test")
    assert support.test_mongodb_uri() == "mongodb://example.test/wubot_test"

    monkeypatch.setenv("TICKET_TEST_MONGODB_URI", "mongodb://example.test/production")
    with pytest.raises(ValueError, match="wubot_test"):
        support.test_mongodb_uri()


def test_generated_collection_name_is_uuid_scoped():
    first = support.test_collection_name("slot_race")
    second = support.test_collection_name("slot_race")

    assert first.startswith("ticket_real_mongo_slot_race_")
    assert first != second


def test_cleanup_refuses_non_test_collection_names():
    class Database:
        async def drop_collection(self, _name):
            raise AssertionError("unsafe collection must not be dropped")

    async def scenario():
        with pytest.raises(ValueError, match="test prefix"):
            await support.cleanup_test_collections(Database(), ["button_store"])

    asyncio.run(scenario())


def test_access_check_requires_only_the_test_database_readwrite_role():
    class Client:
        class Admin:
            async def command(self, _name):
                return {"authInfo": {"authenticatedUserRoles": [
                    {"role": "readWrite", "db": "wubot_test"},
                ]}}

        admin = Admin()

    asyncio.run(support.verify_test_mongodb_access(Client()))


def test_access_check_rejects_broad_database_roles():
    class Client:
        class Admin:
            async def command(self, _name):
                return {"authInfo": {"authenticatedUserRoles": [
                    {"role": "atlasAdmin", "db": "admin"},
                ]}}

        admin = Admin()

    async def scenario():
        with pytest.raises(RuntimeError, match="only the readWrite role"):
            await support.verify_test_mongodb_access(Client())

    asyncio.run(scenario())


def test_denied_access_path_does_not_clean_up_collections():
    class Client:
        class Admin:
            async def command(self, _name):
                return {"authInfo": {"authenticatedUserRoles": [
                    {"role": "readWriteAnyDatabase", "db": "admin"},
                ]}}

        admin = Admin()

    class Database:
        def __init__(self):
            self.dropped = []

        async def drop_collection(self, name):
            self.dropped.append(name)

    async def scenario():
        database = Database()
        access_verified = False
        try:
            with pytest.raises(RuntimeError, match="only the readWrite role"):
                await support.verify_test_mongodb_access(Client())
        finally:
            if access_verified:
                await support.cleanup_test_collections(
                    database, [support.test_collection_name("never_dropped")]
                )
        assert database.dropped == []

    asyncio.run(scenario())
