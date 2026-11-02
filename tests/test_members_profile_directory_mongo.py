"""Real local command/projection proof, without a production connection."""

import asyncio, os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as S
from uuid import uuid4
import pytest
from pymongo import AsyncMongoClient, monitoring
from local_mongo_fixture import fixture_uri
from utils.member_profiles import MemberProfiles, DIRECTORY_FIELDS

URI = fixture_uri(os.environ.get("WU_ACTIVITY_TEST_MONGO_URI"))
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated local Mongo fixture not provided"
)


class Commands(monitoring.CommandListener):
    def __init__(self):
        self.commands = []
        self.cursors = []

    def started(self, event):
        if event.command_name in {"find", "getMore", "killCursors"}:
            self.commands.append(event.command_name)

    def succeeded(self, event):
        if event.command_name in {"find", "getMore"}:
            self.cursors.append(event.reply.get("cursor", {}).get("id"))

    def failed(self, event):
        pass


@pytest.mark.parametrize("active", [479, 1451])
def test_directory_profile_dto_is_bounded_single_batch_and_edit_reads_stay_complete(
    active,
):
    async def run():
        listener = Commands()
        client = AsyncMongoClient(URI, event_listeners=[listener])
        db = client["wu_p141_" + uuid4().hex]
        try:
            ids = [str(800000000000000000 + n) for n in range(1451)]
            now = datetime.now(timezone.utc)
            docs = [
                dict(
                    _id=uid,
                    discord_id=uid,
                    source="staff",
                    zone_id="utc",
                    gmt_label="GMT",
                    utc_offset_minutes=0,
                    country=None,
                    flag=None,
                    name_source_tag=None,
                    revision=7,
                    updated_at=now,
                    updated_by="800000000000999999",
                    left_at=None,
                )
                for uid in ids[:active]
            ]
            if active < 1451:
                docs += [
                    dict(
                        docs[0],
                        _id=uid,
                        discord_id=uid,
                        left_at=now - timedelta(days=1),
                    )
                    for uid in ids[active : active + 17]
                ]
            await db.member_profiles.insert_many(docs)
            store = MemberProfiles(S(member_profiles=db.member_profiles))
            await store.ensure_indexes()
            indexes = await db.member_profiles.index_information()
            listener.commands.clear()
            listener.cursors.clear()
            rows = await store.for_members(ids + [ids[0]], display_only=True)
            assert len(rows) == active
            assert listener.commands == ["find"] and listener.cursors == [0]
            assert all(
                set(row) <= set(DIRECTORY_FIELDS) - {"_id"} for row in rows.values()
            )
            assert all(
                row["revision"] == 7 and "updated_by" not in row
                for row in rows.values()
            )
            complete = await store.for_members(ids)
            assert len(complete) == active and all(
                "_id" in row and "updated_by" in row for row in complete.values()
            )
            assert {
                key: {
                    field: value
                    for field, value in row.items()
                    if field in DIRECTORY_FIELDS and field != "_id"
                }
                for key, row in complete.items()
            } == rows
            assert await db.member_profiles.index_information() == indexes
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
