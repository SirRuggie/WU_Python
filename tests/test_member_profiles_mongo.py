"""Opt-in dedicated local fixture; never uses the default Mongo endpoint."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as S
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from pymongo import AsyncMongoClient
from utils.member_profiles import MemberProfiles, ProfileConflict
from utils.member_profile_leases import editing, ProfileBusy

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated local profile Mongo fixture not provided"
)
USER = "123456789012345678"
ACTOR = "234567890123456789"
FIELDS = {"zone_id": "gmt-5", "country": "US", "name_source_tag": None}


def test_real_profile_lease_concurrency_failure_cas_and_ttl():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_profile_fixture_" + uuid4().hex]
        mongo = S(
            member_profiles=db.member_profiles,
            component_state=db.component_state,
            button_store=db.button_store,
        )
        store = MemberProfiles(mongo)
        try:
            await store.ensure_indexes()
            indexes = await db.member_profiles.index_information()
            assert (
                indexes["member_profile_left_90d"]["expireAfterSeconds"] == 90 * 86400
            )
            async with editing(mongo, USER):
                with pytest.raises(ProfileBusy):
                    await store.write(
                        USER,
                        FIELDS,
                        expected_revision=0,
                        updated_by=ACTOR,
                        source="staff",
                    )
            change = AsyncMock(side_effect=RuntimeError("Discord failed"))
            with pytest.raises(RuntimeError):
                await store.commit_after(
                    USER,
                    FIELDS,
                    change=change,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="warrior",
                )
            assert await store.get(USER) is None
            change.side_effect = None
            await store.commit_after(
                USER,
                FIELDS,
                change=change,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
            current = await store.get(USER)
            assert current["revision"] == 1
            change.reset_mock()
            with pytest.raises(ProfileConflict):
                await store.commit_after(
                    USER,
                    FIELDS,
                    change=change,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="warrior",
                )
            change.assert_not_awaited()
            await store.membership(
                USER, left_at=datetime.now(timezone.utc) - timedelta(days=91)
            )
            for _ in range(60):
                if await store.get(USER) is None:
                    break
                await asyncio.sleep(0.2)
            assert await store.get(USER) is None
            assert await db.component_state.count_documents({}) == 1
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
