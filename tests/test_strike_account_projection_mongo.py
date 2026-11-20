"""Owned Mongo proves profile projection/batching preserves account-list results."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as S
from uuid import uuid4
import pytest
from bson import BSON
from pymongo import AsyncMongoClient, monitoring
from local_mongo_fixture import fixture_uri
from utils.strike_store import StrikeService

URI = fixture_uri(os.environ.get("WU_ACTIVITY_TEST_MONGO_URI"))
pytestmark = pytest.mark.skipif(not URI, reason="owned local Mongo fixture required")
GUILD = 123


def player(index):
    chars = "0289PYLQGRJCUV"
    value = ""
    while index:
        value = chars[index % len(chars)] + value
        index //= len(chars)
    return "#P" + (value or "0") + "Y"


class Replies(monitoring.CommandListener):
    def __init__(self):
        self.rows = []
        self.cursor_ids = []

    def started(self, event):
        pass

    def failed(self, event):
        pass

    def succeeded(self, event):
        cursor = event.reply.get("cursor", {})
        if cursor.get("ns", "").endswith(".strike_profiles"):
            rows = cursor.get("firstBatch", cursor.get("nextBatch", []))
            self.rows.append((event.command_name, rows))
            self.cursor_ids.append(cursor.get("id"))


class LegacyProfiles:
    """Only restore the old cursor shape; keep the real server and data identical."""

    def __init__(self, collection):
        self.collection = collection

    def find(self, query, *args, **kwargs):
        return self.collection.find(query)


def test_real_profile_cursor_reduces_round_trips_with_identical_rows_and_filters():
    async def run():
        replies = Replies()
        client = AsyncMongoClient(URI, event_listeners=[replies])
        db = client["wu_strike_projection_" + uuid4().hex]
        try:
            now = datetime.now(timezone.utc)
            await StrikeService(db).ensure_indexes()
            records = [
                dict(
                    _id=f"row{i}",
                    guild_id=GUILD,
                    player_tag=player(i % 306),
                    player_name=f"Record {i%306}",
                    member_id=100000000000000000 + i % 306,
                    kind="strike",
                    occurred_at=now - timedelta(minutes=i),
                    expires_at=now + timedelta(days=45),
                )
                for i in range(3715)
            ]
            await db.strike_records.insert_many(records)
            profiles = []
            for i in range(306):
                row = dict(
                    _id=player(i),
                    guild_id=GUILD,
                    player_tag=player(i),
                    unused_private_metadata="not needed by this response" * 10,
                )
                if i % 7:
                    row.update(
                        player_name=f"Profile {i}",
                        member_id=200000000000000000 + i,
                        current_clan_tag="#C2Y" if i % 2 else "#Q2Y",
                        roster_seen_at=now - timedelta(minutes=1 if i % 3 else 90),
                    )
                profiles.append(row)
            await db.strike_profiles.insert_many(profiles)
            optimized = StrikeService(db)
            baseline = StrikeService(
                S(
                    strike_records=db.strike_records,
                    strike_settings=db.strike_settings,
                    strike_profiles=LegacyProfiles(db.strike_profiles),
                )
            )
            replies.rows = []
            expected = await baseline.account_list(GUILD)
            old_replies = list(replies.rows)
            replies.rows = []
            replies.cursor_ids = []
            actual = await optimized.account_list(GUILD)
            new_replies = list(replies.rows)
            # A bounded firstBatch must close its server cursor, rather than
            # moving the saved getMore calls into delayed killCursors cleanup.
            assert replies.cursor_ids == [0, 0]
            assert actual == expected
            assert actual["total"] == 306 and len(actual["items"]) == 25
            assert actual["summary"] == dict(over_limit=306, new_this_week=306)
            assert len(old_replies) == 4 and len(new_replies) == 2
            assert sum(name == "getMore" for name, _ in old_replies) == 2
            assert all(name == "find" for name, _ in new_replies)
            wanted = {
                "player_tag",
                "player_name",
                "member_id",
                "current_clan_tag",
                "roster_seen_at",
            }
            assert all(set(row) <= wanted for _, rows in new_replies for row in rows)
            assert sum(
                len(BSON.encode(row)) for _, rows in new_replies for row in rows
            ) < sum(len(BSON.encode(row)) for _, rows in old_replies for row in rows)
            for options in [
                dict(skip=275, limit=25),
                dict(query="profile 305"),
                dict(clan_tag="#C2Y"),
                dict(action="over_limit"),
                dict(action="new_this_week"),
                dict(status="all"),
                dict(query=player(0)),
                dict(limit=100, skip=200),
            ]:
                assert await optimized.account_list(
                    GUILD, **options
                ) == await baseline.account_list(GUILD, **options)
            assert await db.strike_records.count_documents({}) == 3715
            assert await db.strike_profiles.count_documents({}) == 306
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
